#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读主界面「理智药」总量（只读，绝不用药）。

思路（2026-10-11 实机验证）：主界面点理智条的 `+` → 弹「理智恢复」面板，
把面板里每种药剂卡**点满**（点卡片 = +1，超上限会夹住、不回绕），
顶部 `当前 » 理论总量` 即"全用掉后能到多少理智"。

    → **理智药总量 = 理论总量 − 当前理智**

读完点 **✕** 关闭（**绝不点 ✓**——那是确认使用）。

前置：游戏停在「主界面」。用法:
  python sanity_potion.py
  python sanity_potion.py --json out.json
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

PLUS = (1107, 282)           # 主界面理智条上的 +
CANCEL = (1224, 972)         # 面板底部 ✕（取消，不用药）
TOP_CURRENT = (1100, 140, 1480, 370)   # 顶部「当前理智」区
TOP_TOTAL = (1520, 140, 1920, 370)     # 顶部「理论总量」区
CARD_TAP_DY = -130           # 卡片点击点 = 到期徽章(x, y) 上移 130px
FALLBACK_CARDS = [1120, 1370]  # OCR 找不到徽章时的兜底 x


def log(msg):
    print("[sanity] %s" % msg, flush=True)


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
    r = subprocess.run([ADB, "-s", ADDR, "exec-out", "screencap | gzip -1"],
                       capture_output=True, timeout=40)
    if r.returncode == 0 and r.stdout:
        try:
            return _raw_to_bgr(gzip.decompress(r.stdout))
        except Exception as e:
            log("解码失败，回退 PNG: %s" % e)
    p = TMP / name
    with open(p, "wb") as f:
        subprocess.run([ADB, "-s", ADDR, "exec-out", "screencap", "-p"],
                       stdout=f, timeout=40)
    data = np.fromfile(str(p), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def tap(x, y):
    subprocess.run([ADB, "-s", ADDR, "shell", "input", "tap", str(int(x)), str(int(y))],
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


def _ints(text):
    return [int(x) for x in re.findall(r"\d+", text)]


def _roi_ocr(img, roi, tag):
    x0, y0, x1, y1 = roi
    return "".join(_ocr([_save(img[y0:y1, x0:x1], tag), False]) or [])


def find_cards(img):
    """用「X天」到期徽章定位每张药剂卡；失败则用兜底 x。返回点击点列表。"""
    boxes = _ocr([_save(img, "panel.png"), True]) or []
    pts = []
    for b in boxes:
        if "天" in (b.get("text") or ""):
            pts.append((int(b["cx"]), int(b["cy"]) + CARD_TAP_DY))
    if not pts:
        pts = [(x, 600) for x in FALLBACK_CARDS]
    return pts


def main():
    global ADDR
    ap = argparse.ArgumentParser(description="读主界面理智药总量（只读）")
    ap.add_argument("--addr", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    if a.addr:
        ADDR = a.addr
        os.environ["ARK_ADDR"] = a.addr

    tap(*PLUS)
    time.sleep(1.6)
    img = cap("p0.png")
    if img is None:
        raise SystemExit("截图失败")
    opened = any("药剂" in (b.get("text") or "")
                 for b in (_ocr([_save(img, "chk.png"), True]) or []))
    if not opened:
        raise SystemExit("没打开理智恢复面板（游戏在主界面吗？）")

    cards = find_cards(img)
    log("找到 %d 张药剂卡，点满中…" % len(cards))
    for (cx, cy) in cards:
        for _ in range(12):          # 点满（超上限会夹住，安全）
            tap(cx, cy)
            time.sleep(0.35)

    img = cap("p1.png")
    cur = _ints(_roi_ocr(img, TOP_CURRENT, "cur.png"))
    tot = _ints(_roi_ocr(img, TOP_TOTAL, "tot.png"))
    current = cur[0] if cur else None
    total = max(tot) if tot else None

    tap(*CANCEL)                     # 关闭，不用药
    time.sleep(1.0)

    out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
           "current_sanity": current, "theoretical_total": total,
           "potion_sanity": (total - current) if (current is not None and total is not None) else None,
           "cards": [{"x": cx, "y": cy} for cx, cy in cards]}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if out["potion_sanity"] is not None:
        log("理智药合计 ≈ %d 理智（当前 %d → 全用后 %d）"
            % (out["potion_sanity"], current, total))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                        encoding="utf-8")


if __name__ == "__main__":
    main()
