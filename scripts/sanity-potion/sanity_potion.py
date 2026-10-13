#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读主界面「理智药」总量（**只读，绝不用药**）。

思路（2026-10-11 实机验证）：主界面点理智条的 `+` → 弹「理智恢复」面板，
把面板里每种药剂卡**点满**（点卡片 = +1，超上限会夹住、不回绕），
顶部 `当前 » 理论总量` 即"全用掉后能到多少理智"。

    → **理智药总量 = 理论总量 − 当前理智**

读完点 **✕** 关闭（**绝不点 ✓**——那是确认使用）。

## 容错设计（2026-10-14 重写，为「自动化」准备）

- **不盲点**：先判「是不是主界面」（OCR 到『理智』/`/205`）→ 不是就**不点 +**，
  默认直接报错退出（退出码 3）并留证截图；加 `--recover` 才做**有界**恢复（BACK 最多 N 次，
  遇到「确认退出游戏」弹窗**只点『取消』**，绝不点『确认』）。
- **开面板校验 + 重试**：点 + 后 OCR 面板有『药剂』才算开；失败重试 `--tries` 次。
- **读数用「整帧 OCR」+ 按行拼接**（2026-10-14 关键修正，实测踩坑）：
  1) 面板大号数字是**白色描边字压在活动 banner 上**，裁剪+放大反而糊掉 → **整张 1920×1080 原图直接 OCR** 才读得准；
  2) 面板把 `当前》总量` **拆成两个 OCR 框**（如 `'101》'` + `'621'`）→ 必须**按 y 分行、行内按 x 拼接**后再匹配；
  3) 数字取「当前》总量」与底部「提升 N 理智」**两路交叉校验**，不一致就重试。
- **卡片定位**：面板会把多张卡的「X天」徽章**合并成一个框**（`'5购12天'`）→ 不能只靠徽章；
  改为「卡片行内的数字框按 x 聚类」定位每张卡（实测 3 张卡 → 3 个聚类）。
- **收尾**：点 ✕ 关闭（**绝无点 ✓ 的代码路径**）。

前置：游戏停在「主界面」。用法:
  python sanity_potion.py                      # 读一次（不在主界面就报错停）
  python sanity_potion.py --json out.json      # 同时写 JSON
  python sanity_potion.py --recover            # 不在主界面时尝试 BACK 回主界面
  python sanity_potion.py --ensure-main        # 先跑 maa_week startup 把游戏带到主界面
  python sanity_potion.py --dry                # 只判状态（不开面板、不点卡）
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import pathlib
import re
import struct
import subprocess
import sys
import time

import numpy as np
import cv2

ADB = os.environ.get("ARK_ADB", r"C:\leidian\LDPlayer9\adb.exe")
ADDR = os.environ.get("ARK_ADDR", "127.0.0.1:5555")
TMP = pathlib.Path(os.environ.get("TEMP", ".")) / "sanity-potion"
OCR_DIR = pathlib.Path.home() / ".config" / "opencode" / "tools" / "ocr"
REPO = pathlib.Path(__file__).resolve().parents[2]
# 面板大号白字用 server 模型更准（实测 medium 读不出面板数字）
os.environ.setdefault("OCR_MODEL", "server")

PLUS = (1107, 282)           # 主界面理智条上的 +
CANCEL = (1224, 972)         # 面板底部 ✕（取消，不用药）
CARD_ROW_Y = (555, 735)      # 卡片数字所在的 y 带
CARD_X_MIN = 1000            # 卡片在面板右侧；x 小于此的数字（LV/货币）不算
CARD_TAP_Y = 600             # 卡片点击的 y（卡片中心）
# 卡片行**已验证的卡中心**（实测 3 张卡 = 1146/1350/1578，卡宽 ~200）——确定性兜底。
#   面板 OCR 常漏个别卡片数字/把多张卡的「X天」徽章并成一框 → 只靠识别会漏点卡 → 少读。
#   ⚠ 别用「整行宽栅格」：点到卡片右侧/间隙会**关掉面板**，之后继续点就误触主界面按钮（实测踩坑）。
CARD_GRID_X = [1146, 1350, 1578]
CARD_MERGE_PX = 60           # 已知卡中心与识别到的点 合并容差
CARD_TAPS = 10               # 每张卡点几次（点满；超上限会夹住）
FALLBACK_CARDS = [1146, 1350, 1578]
SANITY_CAP = 205

# 退出码（自动化/定时任务据此判成败）
RC_OK = 0
RC_NO_DEVICE = 2
RC_NOT_MAIN = 3
RC_PANEL = 4
RC_READ = 5

_CUR_TOT_RE = re.compile(r"(\d{1,4})\s*[》»≫>]+\s*(\d{1,4})")
_DELTA_RE = re.compile(r"提升\s*(\d{1,4})\s*理智")


def log(msg):
    print("[sanity] %s" % msg, flush=True)


def _harden():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# adb / 截图 / OCR
# ---------------------------------------------------------------------------
def _dev_online() -> bool:
    try:
        r = subprocess.run([ADB, "-s", ADDR, "get-state"], capture_output=True,
                           text=True, timeout=15)
        return "device" in (r.stdout or "")
    except Exception:  # noqa: BLE001
        return False


def _raw_to_bgr(raw: bytes):
    w, h, fmt = struct.unpack_from("<III", raw, 0)
    n4 = w * h * 4
    off = len(raw) - n4
    if off < 0:
        n3 = w * h * 3
        off3 = len(raw) - n3
        if off3 < 0:
            raise ValueError("raw 尺寸不符")
        pix = np.frombuffer(raw[off3:off3 + n3], np.uint8).reshape(h, w, 3)
        return cv2.cvtColor(pix, cv2.COLOR_RGB2BGR)
    pix = np.frombuffer(raw[off:off + n4], np.uint8).reshape(h, w, 4)
    if fmt == 2:
        return cv2.cvtColor(pix[:, :, :3], cv2.COLOR_RGB2BGR)
    return cv2.cvtColor(pix, cv2.COLOR_RGBA2BGR)


def cap(name="shot.png"):
    TMP.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run([ADB, "-s", ADDR, "exec-out", "screencap | gzip -1"],
                           capture_output=True, timeout=40)
        if r.returncode == 0 and r.stdout:
            try:
                return _raw_to_bgr(gzip.decompress(r.stdout))
            except Exception as e:  # noqa: BLE001
                log("解码失败，回退 PNG: %s" % e)
    except Exception as e:  # noqa: BLE001
        log("截图(gzip)异常：%r" % e)
    p = TMP / name
    try:
        with open(p, "wb") as f:
            subprocess.run([ADB, "-s", ADDR, "exec-out", "screencap", "-p"],
                           stdout=f, timeout=40)
        data = np.fromfile(str(p), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    except Exception as e:  # noqa: BLE001
        log("截图(PNG)异常：%r" % e)
        return None


def tap(x, y):
    subprocess.run([ADB, "-s", ADDR, "shell", "input", "tap", str(int(x)), str(int(y))],
                   capture_output=True, timeout=20)


def key_back():
    subprocess.run([ADB, "-s", ADDR, "shell", "input", "keyevent", "4"],
                   capture_output=True, timeout=20)


def _ocr(args):
    sys.path.insert(0, str(OCR_DIR))
    import ocr as ocrlib
    return ocrlib.recognize(*args)


def _save(img, name):
    TMP.mkdir(parents=True, exist_ok=True)
    p = TMP / name
    cv2.imwrite(str(p), img)
    return str(p)


def boxes(img, tag):
    """**整帧 OCR**（不裁剪）——面板大号白字裁剪+放大反而读不出，整帧才准。返回 [{text,cx,cy}]。"""
    try:
        return _ocr([_save(img, tag), True]) or []
    except Exception as e:  # noqa: BLE001
        log("OCR 异常（%s）：%r" % (tag, e))
        return []


def _joined_lines(bs) -> list:
    """把整帧 OCR 的碎框**按 y 分行、行内按 x 拼接**（面板把 `当前》总量` 拆成两个框，必须拼回来）。"""
    items = sorted(bs, key=lambda b: (int(b.get("cy", 0)), int(b.get("cx", 0))))
    lines, cur, cy0 = [], [], None
    for b in items:
        cy = int(b.get("cy", 0))
        if cy0 is None or abs(cy - cy0) <= 22:
            cur.append(b)
            if cy0 is None:
                cy0 = cy
        else:
            lines.append("".join(x.get("text") or ""
                                 for x in sorted(cur, key=lambda z: int(z.get("cx", 0)))))
            cur, cy0 = [b], cy
    if cur:
        lines.append("".join(x.get("text") or ""
                             for x in sorted(cur, key=lambda z: int(z.get("cx", 0)))))
    return lines


# ---------------------------------------------------------------------------
# 状态判定（都走整帧 OCR）
# ---------------------------------------------------------------------------
def _panel_open(bs) -> bool:
    return any("药剂" in (b.get("text") or "") for b in bs)


def _on_main(bs) -> bool:
    """主界面判定：OCR 到『理智』或形如 `x/205`。"""
    for b in bs:
        t = b.get("text") or ""
        if "理智" in t or re.search(r"/\s*%d" % SANITY_CAP, t):
            return True
    return False


def _exit_dialog(bs) -> bool:
    return any("退出" in (b.get("text") or "") for b in bs)


def _tap_cancel_dialog(bs) -> bool:
    for b in bs:
        if "取消" in (b.get("text") or ""):
            tap(b["cx"], b["cy"])
            return True
    return False


def find_cards(bs):
    """定位药剂卡点击点：**固定栅格**（覆盖整行，确定性）+ 识别到的卡片数字/「X天」徽章，按 x 合并。

    面板 OCR 常漏个别卡片数字、或把多张卡的「X天」徽章并成一框（`'5购12天'`）→ 只靠识别会漏点卡。
    栅格多点是安全的：点空=无操作，点同一卡多次=点满后夹住不回绕。
    """
    xs = list(CARD_GRID_X)
    for b in bs:
        t = (b.get("text") or "").strip()
        cx, cy = int(b.get("cx", 0)), int(b.get("cy", 0))
        if cx < CARD_X_MIN:
            continue
        if "天" in t or (CARD_ROW_Y[0] <= cy <= CARD_ROW_Y[1] and re.fullmatch(r"\d{1,3}", t)):
            xs.append(cx)
    if not xs:
        return [(x, CARD_TAP_Y) for x in FALLBACK_CARDS]
    xs.sort()
    clusters = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= CARD_MERGE_PX:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [(sum(c) // len(c), CARD_TAP_Y) for c in clusters]


# ---------------------------------------------------------------------------
# 核心流程
# ---------------------------------------------------------------------------
def _recover_to_main(tries: int) -> bool:
    """有界恢复：BACK 最多 tries 次；遇退出弹窗只点『取消』。回到主界面即 True。"""
    for i in range(tries):
        img = cap("recover.png")
        if img is None:
            return False
        bs = boxes(img, "chk_recover.png")
        if _exit_dialog(bs):
            if _tap_cancel_dialog(bs):
                log("遇到『确认退出游戏』弹窗 → 点『取消』（绝不确认）")
                time.sleep(1.0)
                continue
            log("退出弹窗上没找到『取消』→ 放弃恢复（不冒险）")
            return False
        if _on_main(bs):
            return True
        log("第 %d 次 BACK 回退…" % (i + 1))
        key_back()
        time.sleep(1.2)
    img = cap("recover_end.png")
    return bool(img is not None and _on_main(boxes(img, "chk_recover_end.png")))


def _open_panel(tries: int, recover: bool):
    """确保『理智恢复』面板打开。返回 (img, boxes, rc)。"""
    for i in range(max(1, tries)):
        img = cap("pre.png")
        if img is None:
            return None, [], RC_NO_DEVICE
        bs = boxes(img, "chk_pre.png")
        if _panel_open(bs):
            return img, bs, RC_OK
        if not _on_main(bs):
            if recover and _recover_to_main(3):
                continue
            shot = _save(img, "not_main_%d.png" % i)
            log("!! 不在主界面（也判不到理智恢复面板）→ 不点 +，已留证：%s" % shot)
            return None, [], RC_NOT_MAIN
        log("点 + 开面板（第 %d 次）" % (i + 1))
        tap(*PLUS)
        time.sleep(1.6)
        img2 = cap("panel_open.png")
        bs2 = boxes(img2, "chk_panel.png") if img2 is not None else []
        if _panel_open(bs2):
            return img2, bs2, RC_OK
    return None, [], RC_PANEL


def _read_totals(tries: int):
    """整帧 OCR → 按行拼接 → 读「当前》总量」(+底部 delta 交叉校验)，带重试。"""
    for i in range(max(1, tries)):
        img = cap("read.png")
        if img is None:
            continue
        bs = boxes(img, "read_ocr.png")
        if not _panel_open(bs):
            log("读数时面板不见了（第 %d 次）" % (i + 1))
            continue
        cur = tot = delta = None
        for line in _joined_lines(bs):
            m = _CUR_TOT_RE.search(line)
            if m:
                cur, tot = int(m.group(1)), int(m.group(2))
            m2 = _DELTA_RE.search(line)
            if m2:
                delta = int(m2.group(1))
        if cur is None or tot is None:
            log("整帧 OCR 没读到『当前》总量』，重试")
            continue
        if tot < cur:
            log("读数不合理（当前 %d > 总量 %d），重试" % (cur, tot))
            continue
        if delta is not None and (tot - cur) != delta:
            log("两路不一致（总量−当前=%d，底部提升=%d），重试" % (tot - cur, delta))
            continue
        return {"current": cur, "total": tot, "delta": delta, "consistent": delta is not None}
    return None


def main():
    global ADDR
    _harden()
    ap = argparse.ArgumentParser(description="读主界面理智药总量（只读，绝不用药）")
    ap.add_argument("--addr", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--tries", type=int, default=3, help="开面板/读数的重试次数（默认 3）")
    ap.add_argument("--recover", action="store_true", help="不在主界面时尝试 BACK 回主界面")
    ap.add_argument("--ensure-main", action="store_true",
                    help="先跑 maa_week startup（拉起雷电+启动游戏到主界面）再测")
    ap.add_argument("--dry", action="store_true", help="只判状态，不开面板、不点卡")
    a = ap.parse_args()
    if a.addr:
        ADDR = a.addr
        os.environ["ARK_ADDR"] = a.addr

    if not _dev_online():
        log("!! 设备不在线（%s）—— 先启动模拟器" % ADDR)
        return RC_NO_DEVICE

    if a.ensure_main:
        log("先跑 maa_week startup 把游戏带到主界面…")
        try:
            subprocess.run([sys.executable, str(REPO / "scripts" / "maa-week" / "maa_week.py"),
                            "startup"], cwd=str(REPO), timeout=420)
        except Exception as e:  # noqa: BLE001
            log("!! startup 异常（继续尝试测药）：%r" % e)
        time.sleep(3)

    if a.dry:
        img0 = cap("dry.png")
        bs = boxes(img0, "chk_dry.png") if img0 is not None else []
        state = ("panel" if _panel_open(bs) else "main" if _on_main(bs) else "other")
        print(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "state": state,
                          "dry": True}, ensure_ascii=False, indent=2))
        return RC_OK

    img, bs, rc = _open_panel(a.tries, a.recover)
    if rc != RC_OK or img is None:
        return rc

    cards = find_cards(bs)
    log("找到 %d 张药剂卡，点满中…" % len(cards))
    for (cx, cy) in cards:
        for _ in range(CARD_TAPS):       # 点满（超上限会夹住，安全）
            tap(cx, cy)
            time.sleep(0.3)

    got = _read_totals(a.tries)
    tap(*CANCEL)                     # 关闭，不用药
    time.sleep(1.0)

    if got is None:
        log("!! 读不到有效读数（已关闭面板、未用药）")
        return RC_READ

    cur, tot = got["current"], got["total"]
    out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
           "current_sanity": cur, "theoretical_total": tot, "potion_sanity": tot - cur,
           "bottom_delta": got.get("delta"), "consistent": got.get("consistent"),
           "cards": [{"x": cx, "y": cy} for cx, cy in cards]}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    log("理智药合计 ≈ %d 理智（当前 %d → 全用后 %d%s）"
        % (out["potion_sanity"], cur, tot,
           "" if got.get("consistent") else "；仅单路读数，未交叉校验"))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
