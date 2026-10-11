#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库逐项读数（消耗物品 / 养成材料…）—— 补 MAA `Depot` 拿不到的消耗品。

背景：MAA 的 `Depot` 任务只识别「基础物品」那批模板，**拿不到理智药等消耗品**。
本脚本仿照 `docs/WORKFLOW-仓库取数.md` 的手工流程，把它自动化：

    MAA Depot 任务导航到仓库 → 点 tab → 逐个道具（点开详情 → OCR 标题+库存 → 点 ▶ 翻页）

前置：**游戏停在「主界面」**（MAA 会自己导航到仓库）+ MAA 空闲 + 单客户端。

用法:
  python depot_items.py                    # 导航 + 读「消耗物品」tab
  python depot_items.py --no-nav           # 已在仓库页，跳过 MAA 导航
  python depot_items.py --tab grow         # 读「养成材料」
  python depot_items.py --json out.json    # 结果另存
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

MAA = os.environ.get("ARK_MAA_PATH", r"C:\MAA")
ADB = os.environ.get("ARK_ADB", r"C:\leidian\LDPlayer9\adb.exe")
ADDR = os.environ.get("ARK_ADDR", "127.0.0.1:5555")
TOUCH = os.environ.get("ARK_TOUCH", "maatouch")
TMP = pathlib.Path(os.environ.get("TEMP", ".")) / "depot-items"
OCR_DIR = pathlib.Path.home() / ".config" / "opencode" / "tools" / "ocr"

# 仓库页坐标（1920×1080，来自 WORKFLOW-仓库取数.md 实测）
TAB_X = {"all": 755, "consume": 978, "basic": 1190, "grow": 1440, "special": 1680}
TAB_Y = 57
GRID_X = [185 + 238 * i for i in range(8)]   # 每行 8 个
GRID_Y = [300, 555, 800]
DETAIL_CROP = (330, 195, 1700, 255)          # 详情面板「名称+到期+库存」区
PREV = (95, 520)
NEXT = (1845, 520)


def log(msg):
    print("[depot] %s" % msg, flush=True)


# ---------------------------------------------------------------------------
# adb：快速截图（MAA 同款 raw+gzip）+ 点击
# ---------------------------------------------------------------------------
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
    img = None
    if r.returncode == 0 and r.stdout:
        try:
            img = _raw_to_bgr(gzip.decompress(r.stdout))
        except Exception as e:
            log("解码失败，回退 PNG: %s" % e)
    if img is None:
        p = TMP / name
        with open(p, "wb") as f:
            subprocess.run([ADB, "-s", ADDR, "exec-out", "screencap", "-p"],
                           stdout=f, timeout=40)
        data = np.fromfile(str(p), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    return img


def tap(x, y):
    subprocess.run([ADB, "-s", ADDR, "shell", "input", "tap", str(int(x)), str(int(y))],
                   capture_output=True, timeout=20)


# ---------------------------------------------------------------------------
# MAA 导航（仅用 Depot 任务把游戏带到仓库页）
# ---------------------------------------------------------------------------
def nav_to_depot():
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
        raise RuntimeError("连接模拟器失败（确认雷电已开、游戏在主界面）")
    tid = a.append_task("Depot", {"enable": True})
    if not tid:
        raise RuntimeError("Depot 任务 append 失败")
    a.start()
    t0 = time.time()
    while a.running() and time.time() - t0 < 240:
        time.sleep(0.5)
    if a.running():
        a.stop()
    log("Depot 导航结束（%.0fs），应在仓库页" % (time.time() - t0))


# ---------------------------------------------------------------------------
# OCR + 解析
# ---------------------------------------------------------------------------
def _ocr_lines(png):
    sys.path.insert(0, str(OCR_DIR))
    import ocr as ocrlib
    try:
        return ocrlib.recognize(str(png))
    except Exception as e:
        log("OCR 失败: %s" % e)
        return []


def parse_detail(text: str) -> dict:
    """从「名称+到期+库存」文本里抽 {name, expiry, stock}。"""
    t = text.replace(" ", "").replace("\n", "")
    stock = None
    m = re.search(r"库存(\d+)", t)
    if m:
        stock = int(m.group(1))
    expiry = None
    m = re.search(r"(\d{1,2}/\d{1,2})\s*(\d{1,2}:\d{2})", t)
    if m:
        expiry = "%s %s" % (m.group(1), m.group(2))
    name = t
    name = re.sub(r"库存\d+.*$", "", name)
    name = re.sub(r"\d{1,2}/\d{1,2}\d{1,2}:\d{2}到期.*$", "", name)
    name = re.sub(r"(限时|到期).*$", "", name)
    return {"name": name.strip(), "expiry": expiry, "stock": stock}


def read_one():
    img = cap()
    if img is None:
        return None
    x0, y0, x1, y1 = DETAIL_CROP
    crop = img[y0:y1, x0:x1]
    TMP.mkdir(parents=True, exist_ok=True)
    p = TMP / "detail.png"
    cv2.imwrite(str(p), crop)
    text = "".join(_ocr_lines(p))
    if not text.strip():
        return None
    rec = parse_detail(text)
    rec["raw"] = text
    return rec


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def read_tab(tab: str, max_items: int = 40):
    log("切到 tab=%s" % tab)
    tap(TAB_X[tab], TAB_Y)
    time.sleep(2.0)

    # 点开第一个道具（先试第一行前几格，防空格）
    opened = False
    for cx in GRID_X[:4]:
        tap(cx, GRID_Y[0])
        time.sleep(1.5)
        rec = read_one()
        if rec and rec.get("name") and rec.get("stock") is not None:
            opened = True
            break
    if not opened:
        log("!! 未能点开道具详情（是否在仓库页？坐标是否失效？）")
        return []

    items, last = [], None
    for i in range(max_items):
        rec = read_one()
        if not rec or not rec.get("name"):
            log("第 %d 项无内容 → 结束" % (i + 1))
            break
        if rec["name"] == last:
            log("第 %d 项与上一项同名 → 已到末尾/回卷，结束" % (i + 1))
            break
        rec.pop("raw", None)
        items.append(rec)
        last = rec["name"]
        log("  %2d. %-16s 到期=%-12s 库存=%s"
            % (i + 1, rec["name"], rec.get("expiry") or "-", rec.get("stock")))
        tap(*NEXT)
        time.sleep(1.2)
    return items


def main():
    global ADDR
    ap = argparse.ArgumentParser(description="仓库逐项读数（补 MAA Depot 拿不到的消耗品）")
    ap.add_argument("--tab", default="consume",
                    choices=list(TAB_X.keys()), help="默认 consume=消耗物品")
    ap.add_argument("--no-nav", action="store_true", help="已在仓库页，跳过 MAA 导航")
    ap.add_argument("--addr", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    if a.addr:
        ADDR = a.addr
        os.environ["ARK_ADDR"] = a.addr

    if not a.no_nav:
        log("用 MAA Depot 导航到仓库（需游戏在主界面）…")
        nav_to_depot()
        time.sleep(2.0)

    items = read_tab(a.tab)
    print("\n共 %d 项：" % len(items))
    print(json.dumps(items, ensure_ascii=False, indent=2))
    if a.json:
        pathlib.Path(a.json).write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        log("已存 %s" % a.json)


if __name__ == "__main__":
    main()
