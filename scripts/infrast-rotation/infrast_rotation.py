#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基建换班（搓玉 A/B 班轮换）自动化
==================================
把「基建换班」的整条人工流程固化成一条命令：
    收菜 → 菲亚梅塔置换但书心情 → 13 房间切队列 → 换班后再收菜 → 写日志

单客户端纪律
------------
运行前请关掉 MAA GUI / 其它 arknights MCP（同一时刻只让一个程序驱动设备）。
设备默认 127.0.0.1:5555（雷电），把 MAA/MaaCore 的 Custom 任务只用于「滑动」
（本机 adb swipe 失效）；点击/截图走 adb，识别走 cv2 模板+颜色 + 本地 OCR。

用法
----
  python infrast_rotation.py all            # 全流程（默认）
  python infrast_rotation.py check          # 只侦察不改状态（开面板看青块/待办）
  python infrast_rotation.py collect        # 只收菜
  python infrast_rotation.py fia            # 只菲亚梅塔置换
  python infrast_rotation.py swap           # 只切队列

依赖：本机 MAA(C:\\MAA)、雷电 adb、cv2/numpy、本地 OCR 工具。
坐标基于 1920x1080；MAA 模板为 1280x720，匹配时自动按屏幕宽度缩放。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import time

import numpy as np
import cv2

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
MAA = os.environ.get("ARK_MAA_PATH", r"C:\MAA")
ADB = os.environ.get("ARK_ADB", r"C:\leidian\LDPlayer9\adb.exe")
ADDR = os.environ.get("ARK_ADDR", "127.0.0.1:5555")
TOUCH = os.environ.get("ARK_TOUCH", "maatouch")
TMP = pathlib.Path(os.environ.get("TEMP", ".")) / "infrast-rotation"
TPL_ROOT = pathlib.Path(MAA) / "resource" / "template"
REPO = pathlib.Path(__file__).resolve().parents[2]
LOG_JSONL = REPO / "scheduling" / "data" / "infrast_rotation_log.jsonl"
STATE_JSON = REPO / "docs" / "state.json"
OCR_TOOL = os.environ.get(
    "ARK_OCR_TOOL",
    str(pathlib.Path.home() / ".config" / "opencode" / "tools" / "ocr" / "ocr.py"),
)

# 坐标（1920x1080）——来自 2026-10-11 实机侦察，标注 [V]=已实机验证 [R]=据 MAA ROI×1.5
C = {
    "main_infrast": (1455, 845),        # [V] 主界面「基建」卡片
    "overview_entry": (175, 156),       # [V] 基建页「进驻总览」
    "tab_work": (1420, 59),             # [V] 进驻总览「工作区」页签中心
    "tab_nonwork": (1696, 59),          # [V] 进驻总览「非工作区」页签中心
    "badge": (1841, 139),               # [V] 右上角角标中心（蓝/红同位）
    "badge_roi": (1750, 100, 1920, 178),  # [V]
    "todo_card1": (295, 995),           # [R] 待办面板第一张卡片
    "todo_roi": (0, 900, 1100, 1080),   # [R] 待办面板条
    "qt_entry": (763, 340),             # [V] 第一行房间「编辑队列」按钮（控制中枢行）
    "qt_roi": (1400, 480, 1720, 980),   # [V] 编辑队列面板：⇄ 竖条所在区
    "chev_x": 1565,                     # [V] ⇄ 竖条中心 x
    "chev_y": (623, 848),               # [V] (生效行 y, 目标行 y)
    "next_room": (1727, 500),           # [R] 面板右侧 ⟫
    "dorm_info": (65, 410),             # [R] 房间内「进驻信息」
    "dorm_row1": (1535, 215),           # [R] 入住信息面板第一行（点进编辑）
    "clear_sel": (763, 995),            # [V] 编辑界面「清空选择」
    "confirm": (1670, 1000),            # [V] 编辑界面「确认」
    "oplist_roi": (600, 100, 1840, 960),  # [R] 干员卡片网格
}

# OCR 关键词（页面判别）
KW_MAIN = ("角色管理", "公开招募", "干员寻访", "采购中心", "档案", "终端")
KW_OVERVIEW = ("工作区情况", "非工作区情况", "进驻干员", "房间数量", "编辑队列", "队列轮换")
KW_BASE = ("进驻总览", "建造模式", "INFRASTRUCTURE", "加工站")
KW_EXIT = ("确认退出游戏", "退出游戏")
KW_LIST = ("心情", "休息中", "工作中", "进驻", "清空选择")

TPL_DORM = ("InfrastPic/Facilities/DormMini.png", "InfrastPic/Facilities/Dorm.png")
TPL_NOTIFY = "InfrastPic/InfrastNotification.png"
TPL_CONFLICT = "InfrastPic/InfrastOperConflictConfirm.png"


def log(msg: str) -> None:
    print("[infra] " + str(msg), flush=True)


# ---------------------------------------------------------------------------
# adb 原语
# ---------------------------------------------------------------------------
def _adb(*args, timeout: int = 60):
    cmd = [ADB, "-s", ADDR] + [str(a) for a in args]
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def tap(x, y):
    _adb("shell", "input", "tap", int(x), int(y))


def key(code: int):
    _adb("shell", "input", "keyevent", int(code))


def cap(name: str):
    TMP.mkdir(parents=True, exist_ok=True)
    p = TMP / name
    with open(p, "wb") as f:
        subprocess.run([ADB, "-s", ADDR, "exec-out", "screencap", "-p"], stdout=f, timeout=40)
    return cv2.imread(str(p), cv2.IMREAD_COLOR)


# ---------------------------------------------------------------------------
# MaaCore（仅用于 Custom 滑动任务）
# ---------------------------------------------------------------------------
_asst = None


def get_asst():
    global _asst
    if _asst is not None:
        return _asst
    sys.path.insert(0, str(pathlib.Path(MAA) / "Python"))
    from asst.asst import Asst
    from asst.utils import InstanceOptionType
    user_dir = TMP / "maa"
    user_dir.mkdir(parents=True, exist_ok=True)
    Asst.load(str(MAA), user_dir=str(user_dir))
    a = Asst(Asst.CallBackType(lambda m, d, x: None))
    a.load(str(MAA))
    a.set_instance_option(InstanceOptionType.touch_type, TOUCH)
    if not a.connect(ADB, ADDR, "General"):
        raise RuntimeError("连接模拟器失败: %s" % ADDR)
    _asst = a
    return a


def swipe_task(names, timeout: int = 15):
    a = get_asst()
    tid = a.append_task("Custom", {"task_names": list(names)})
    if not tid:
        raise RuntimeError("Custom 任务 append 失败: %s" % names)
    a.start()
    t0 = time.time()
    while a.running() and time.time() - t0 < timeout:
        time.sleep(0.2)
    if a.running():
        a.stop()
    time.sleep(0.8)


def swipe_oplist_right(n=1):
    for _ in range(n):
        swipe_task(["InfrastOperListSlowlySwipeToTheRight"])


def swipe_oplist_left(n=1):
    for _ in range(n):
        swipe_task(["InfrastOperListSwipeToTheLeft"])


# ---------------------------------------------------------------------------
# 识别：本地 OCR + cv2
# ---------------------------------------------------------------------------
def _ocr(png, upscale=2.0):
    try:
        r = subprocess.run([sys.executable, OCR_TOOL, str(png)], capture_output=True, timeout=120)
        return r.stdout.decode("utf-8", "replace")
    except Exception as e:
        log("ocr 失败: %s" % e)
        return ""


def ocr_img(img, roi=None, tag="ocr"):
    TMP.mkdir(parents=True, exist_ok=True)
    if roi:
        x, y, w, h = roi
        img = img[y:y + h, x:x + w]
    p = TMP / (tag + ".png")
    cv2.imwrite(str(p), img)
    return _ocr(p)


def _load_tpl(name):
    paths = [name] if isinstance(name, str) else list(name)
    for nm in paths:
        for f in TPL_ROOT.rglob(pathlib.Path(nm).name):
            t = cv2.imread(str(f), cv2.IMREAD_UNCHANGED)
            if t is None:
                continue
            if t.ndim == 3 and t.shape[2] == 4:
                a = t[:, :, 3:4].astype(np.float32) / 255.0
                bgr = t[:, :, :3].astype(np.float32)
                t = (bgr * a + 128.0 * (1.0 - a)).astype(np.uint8)
            elif t.ndim == 2:
                t = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
            return t
    return None


def find_tpl(img, name, thr=0.75, roi=None):
    t = _load_tpl(name)
    if t is None:
        return None
    sc = img.shape[1] / 1280.0
    if abs(sc - 1.0) > 0.01:
        t = cv2.resize(t, (max(1, int(round(t.shape[1] * sc))), max(1, int(round(t.shape[0] * sc)))))
    ox, oy = 0, 0
    region = img
    if roi:
        ox, oy, w, h = roi
        region = img[oy:oy + h, ox:ox + w]
    if region.shape[0] < t.shape[0] or region.shape[1] < t.shape[1]:
        return None
    res = cv2.matchTemplate(region, t, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(res)
    cx = ox + loc[0] + t.shape[1] // 2
    cy = oy + loc[1] + t.shape[0] // 2
    return {"cx": cx, "cy": cy, "score": round(float(mx), 4)}


def badge_kind(img):
    x, y, w, h = C["badge_roi"]
    r = img[y:h, x:w].astype(int)
    b, g, rr = r[:, :, 0], r[:, :, 1], r[:, :, 2]
    if ((rr > 150) & (g < 100) & (b < 100)).sum() > 200:
        return "red"
    if ((b > 150) & (b > rr + 30) & (b > g + 10)).sum() > 200:
        return "blue"
    return None


def cyan_clusters(img):
    x, y, w, h = C["qt_roi"]
    r = img[y:h, x:w].astype(int)
    b, g, rr = r[:, :, 0], r[:, :, 1], r[:, :, 2]
    mask = ((b > 110) & (b > rr + 45) & (g > rr + 30)).astype(np.uint8)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area >= 200:
            out.append((area, int(cent[i][0]) + x, int(cent[i][1]) + y))
    out.sort(key=lambda t: -t[0])
    return out


# ---------------------------------------------------------------------------
# 导航
# ---------------------------------------------------------------------------
def screen_kind(img):
    t = ocr_img(img, tag="screen")
    if any(k in t for k in KW_EXIT):
        return "exit"
    if any(k in t for k in KW_OVERVIEW):
        return "overview"
    if any(k in t for k in KW_MAIN):
        return "main"
    if any(k in t for k in KW_BASE):
        return "base"
    return "unknown"


def goto_overview(tries=10):
    backs = 0
    for _ in range(tries):
        img = cap("nav.png")
        k = screen_kind(img)
        log("screen=%s" % k)
        if k == "overview":
            return True
        if k == "exit":
            key(4); time.sleep(1.5); continue
        if k == "main":
            tap(*C["main_infrast"]); time.sleep(5.0); continue
        if k == "base":
            tap(*C["overview_entry"]); time.sleep(3.5); continue
        backs += 1
        if backs > 5:
            log("[!] 导航失败（反复未知页面），放弃")
            return False
        key(4); time.sleep(2.0)
    return False


def _ocr_screen(tag="s"):
    img = cap(tag + ".png")
    return img, ocr_img(img, tag=tag)


def open_queue_panel(tries=5):
    """鲁棒地打开「编辑队列」面板：处理 非工作区页签 / 房间行被选中 / 未开 等情况。"""
    for attempt in range(tries):
        img, t = _ocr_screen("qt_pre%d" % attempt)
        if ("预设队列" in t) or ("当前进驻" in t):
            log("编辑队列面板已打开")
            return True
        if "房间运行信息" in t:
            log("房间行被选中 → 返回重进进驻总览")
            key(4); time.sleep(2.0)
            tap(*C["overview_entry"]); time.sleep(3.0)
            continue
        if "非工作区情况" in t:
            log("切到工作区页签")
            tap(*C["tab_work"]); time.sleep(2.0)
            continue
        if ("工作区情况" in t) or ("进驻干员" in t) or ("编辑队列" in t):
            log("点编辑队列按钮")
            tap(*C["qt_entry"]); time.sleep(2.5)
            continue
        key(4); time.sleep(2.0)
    log("[!] 未能打开编辑队列面板")
    return False


# ---------------------------------------------------------------------------
# 步骤 1：收菜 / 待办（可收获 + 干员休整）
# ---------------------------------------------------------------------------
def collect(dry=False):
    if not goto_overview():
        log("[!] 未到进驻总览，跳过收菜")
        return
    for rnd in range(10):
        img = cap("collect_%d.png" % rnd)
        kind = badge_kind(img)
        if kind is None:
            log("收菜完成（无角标）")
            return
        if kind == "red":
            log("[!] 右上角是红色 EMERGENCY，非待办，跳过")
            return
        if dry:
            log("[check] 蓝色待办角标存在（dry，不点）")
            return
        tap(*C["badge"]); time.sleep(2.0)
        for _ in range(8):
            img = cap("todo.png")
            x, y, w, h = C["todo_roi"]
            t = ocr_img(img, roi=(x, y, w - x, h - y), tag="todo")
            if "更换队列" in t or "队列轮换" in t:
                log("待办遇到「更换队列」，跳过")
                break
            if ("可收获" in t) or ("干员休整" in t) or ("收获" in t) or ("收取" in t):
                tap(*C["todo_card1"]); time.sleep(2.2)
            else:
                break
    log("收菜循环结束")


# ---------------------------------------------------------------------------
# 步骤 2：菲亚梅塔置换但书心情
# ---------------------------------------------------------------------------
CARD_COLS = [690, 900, 1115, 1330, 1545]
CARD_ROWS = [310, 740]


def _card_scan(name, max_screens=8):
    """逐卡片裁剪 OCR，找到目标干员卡。返回卡片中心 (x,y) 或 None。
    本地 OCR 只出文本无坐标 → 用它裁剪每张卡的小图分别识别来定位。"""
    for i in range(max_screens):
        img = cap("card_%d.png" % i)
        for cy in CARD_ROWS:
            for cx in CARD_COLS:
                crop = img[cy - 205:cy + 205, cx - 72:cx + 72]
                p = TMP / "card_one.png"
                cv2.imwrite(str(p), crop)
                if name in _ocr(p):
                    log("列表(第%d屏)找到 %s @ (%d,%d)" % (i, name, cx, cy))
                    return (cx, cy)
        swipe_oplist_right()
    return None


def _select_oper(name):
    swipe_oplist_left(6)
    pos = _card_scan(name)
    if not pos:
        return False
    tap(*pos); time.sleep(1.3)
    return True


def fiammetta(dry=False, targets=("但书", "菲亚梅塔")):
    if not goto_overview():
        log("[!] 未到进驻总览，跳过菲亚梅塔")
        return False
    key(4); time.sleep(2.5)
    img = cap("base_map.png")
    m = find_tpl(img, TPL_DORM, thr=0.7)
    log("宿舍建筑模板匹配: %s" % m)
    if not m:
        log("[!] 找不到宿舍建筑，跳过")
        return False
    tap(m["cx"], m["cy"]); time.sleep(3.0)
    tap(*C["dorm_info"]); time.sleep(2.0)
    tap(*C["dorm_row1"]); time.sleep(3.0)
    img = cap("dorm_edit.png")
    t = ocr_img(img, tag="dorm_edit")
    if not any(k in t for k in KW_LIST):
        log("[!] 未进入干员编辑界面（OCR 无 清空选择/心情），跳过")
        return False
    log("已进入干员编辑界面")
    if dry:
        log("[check] 编辑界面已打开（dry，不改动）")
        return True
    tap(*C["clear_sel"]); time.sleep(2.0)
    for name in targets:
        if not _select_oper(name):
            log("[!] 列表里找不到 %s，中止置换（未提交）" % name)
            key(4); time.sleep(2)
            return False
        log("已点选 %s" % name)
    tap(*C["confirm"]); time.sleep(2.0)
    img = cap("conflict.png")
    m = find_tpl(img, TPL_CONFLICT, thr=0.7, roi=(945, 930, 975, 150))
    if m and m["score"] >= 0.7:
        tap(m["cx"], m["cy"]); time.sleep(2.0)
        log("已点二次确认")
    log("菲亚梅塔置换已提交")
    return True


# ---------------------------------------------------------------------------
# 步骤 3：13 房间切队列
# ---------------------------------------------------------------------------
def _room_no(img):
    t = ocr_img(img, roi=(1450, 60, 300, 90), tag="roomno")
    m = re.search(r"房间\s*(\d+)\s*/\s*(\d+)", t)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def switch_queues(dry=False):
    if not goto_overview():
        log("[!] 未到进驻总览，跳过切队列")
        return 0, 0
    if not open_queue_panel():
        return 0, 0
    img = cap("qt_first.png")
    clusters = cyan_clusters(img)
    if not clusters:
        log("[!] 编辑队列面板里找不到青色 ⇄（是否已开面板？）")
        return 0, 0
    target_y = clusters[0][2]
    n1, total = _room_no(img)
    total = total or 13
    log("目标队列行 y≈%d（共 %s 房间）" % (target_y, total))
    done = skipped = 0
    for room in range(total):
        img = cap("qt_r%02d.png" % (room + 1))
        n, tot = _room_no(img)
        cs = cyan_clusters(img)
        on_target = [c for c in cs if abs(c[2] - target_y) < 90]
        if on_target:
            cx, cy = C["chev_x"], on_target[0][2]
            if dry:
                log("[check] 房间%s 目标行青块存在 (y=%d)（dry，不点）" % (n or room + 1, cy))
                done += 1
            else:
                tap(cx, cy); time.sleep(1.3)
                c2 = cyan_clusters(cap("qt_v.png"))
                moved = [c for c in c2 if abs(c[2] - target_y) >= 90]
                if moved:
                    log("房间%s 切换✓" % (n or room + 1)); done += 1
                else:
                    log("[!] 房间%s 点击后青块未移动" % (n or room + 1)); skipped += 1
        else:
            log("房间%s 已在目标队列或无青块 → 跳过" % (n or room + 1))
            skipped += 1
        if room < total - 1:
            tap(*C["next_room"]); time.sleep(1.2)
    if not dry:
        key(4); time.sleep(1.5)
    log("切队列完成：切换 %d / 跳过 %d" % (done, skipped))
    return done, skipped


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
def flip_direction(d):
    return "队列2->队列1" if d == "队列1->队列2" else "队列1->队列2"


def last_direction():
    try:
        lines = [l for l in io.open(LOG_JSONL, encoding="utf-8").read().splitlines() if l.strip()]
        if lines:
            return json.loads(lines[-1]).get("next_direction")
    except Exception:
        pass
    return None


def write_log(done, skipped, total=13):
    ts = time.strftime("%Y-%m-%d %H:%M")
    nxt = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + 12 * 3600))
    direction = last_direction() or "队列1->队列2"
    entry = {
        "ts": ts, "by": "script", "direction": direction, "rooms": total,
        "switched": done, "skipped": skipped,
        "next_due": ">= " + nxt, "next_direction": flip_direction(direction),
        "note": "infrast_rotation.py all：收菜+菲亚梅塔置换但书心情+13房间切队列+换班后再收菜。",
    }
    LOG_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with io.open(LOG_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    log("已写日志: %s" % entry)
    return entry


def update_state(entry):
    try:
        d = json.load(io.open(STATE_JSON, encoding="utf-8"))
        d["updated_at"] = entry["ts"]
        tr = d.setdefault("triggers", {})
        tr["infrast_next_swap_at"] = entry["next_due"].replace(">= ", "")
        tr["infrast_next_swap_direction"] = entry["next_direction"]
        json.dump(d, io.open(STATE_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        log("已更新 state.json triggers")
    except Exception as e:
        log("[!] 更新 state.json 失败: %s" % e)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def run_all(steps, dry=False, update=False):
    if "collect" in steps:
        collect(dry=dry)
    if "fia" in steps:
        fiammetta(dry=dry)
    if "swap" in steps:
        done, skipped = switch_queues(dry=dry)
        if "collect" in steps:
            collect(dry=dry)
        if not dry:
            entry = write_log(done, skipped)
            if update:
                update_state(entry)


def main():
    ap = argparse.ArgumentParser(description="基建换班自动化（搓玉 A/B 轮换）")
    ap.add_argument("cmd", nargs="?", default="all",
                    choices=["all", "check", "collect", "fia", "swap"])
    ap.add_argument("--dry-run", action="store_true", help="只识别不改状态")
    ap.add_argument("--update-state", action="store_true", help="同时回写 docs/state.json")
    args = ap.parse_args()

    TMP.mkdir(parents=True, exist_ok=True)
    if args.cmd == "check":
        get_asst()
        img = cap("check.png")
        log("角标: %s" % badge_kind(img))
        run_all({"collect"}, dry=True)
        run_all({"swap"}, dry=True)
        return
    if args.cmd == "collect":
        run_all({"collect"}, dry=args.dry_run, update=args.update_state)
    elif args.cmd == "fia":
        run_all({"fia"}, dry=args.dry_run, update=args.update_state)
    elif args.cmd == "swap":
        run_all({"swap"}, dry=args.dry_run, update=args.update_state)
    else:
        get_asst()
        run_all({"collect", "fia", "swap"}, dry=args.dry_run, update=args.update_state)


if __name__ == "__main__":
    main()
