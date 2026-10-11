#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""锚点录制器（命令行版）——把屏幕上一块区域存成锚点模板，或往流程里追加一步。

用法:
  # 1) 截一张当前屏（存到 %TEMP%\\anchor-runner\\shot.png），--grid 叠网格方便读坐标
  python record.py shot [--grid 100] [--out shot.png]

  # 2) 从截图裁一块当锚点模板（默认模式，坐标 = 实际屏幕像素 x y w h）
  python record.py --anchor X Y W H --save page_overview [--from shot.png] [--ref-w 1920]

  # 3) 往流程文件追加一步（“录制”动作）
  python record.py step --flow steps.json --name "点基建" \
        --anchor page_main --click-anchor btn_infrast [--wait 2.0] [--on-fail abort]

坐标怎么量：先 `python record.py shot --grid 100`，打开 grid_shot.png，
按 100px 网格数出按钮的 x y w h，再跑第 2 条命令。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import cv2

import anchors


def cmd_shot(argv):
    ap = argparse.ArgumentParser(prog="record.py shot")
    ap.add_argument("--out", default="shot.png")
    ap.add_argument("--grid", type=int, default=0, help="叠加 N 像素网格+刻度")
    ap.add_argument("--addr", default="")
    a = ap.parse_args(argv)
    if a.addr:
        anchors.ADDR = a.addr
    anchors.resolve_addr()
    img = anchors.screenshot(save=a.out)
    if img is None:
        anchors.log("截图失败")
        sys.exit(1)
    h, w = img.shape[:2]
    print("截图: %s  (%dx%d)" % (anchors.TMP / a.out, w, h))
    if a.grid > 0:
        g = anchors.draw_grid(img, a.grid)
        p = anchors.TMP / ("grid_" + a.out)
        cv2.imwrite(str(p), g)
        print("带网格: %s  (红线每 %d px，角上是刻度)" % (p, a.grid))


def cmd_anchor(argv):
    ap = argparse.ArgumentParser(prog="record.py anchor")
    ap.add_argument("--anchor", "--rect", dest="rect", nargs=4, type=int, required=True,
                    metavar=("X", "Y", "W", "H"), help="锚点区域（实际屏幕像素）")
    ap.add_argument("--save", required=True, help="模板名（存到 anchors/）或 .png 路径")
    ap.add_argument("--from", dest="src", default=None, help="从这张图裁（默认用最新 shot.png）")
    ap.add_argument("--ref-w", type=int, default=0, help="参考宽度（默认=源图宽度）")
    ap.add_argument("--addr", default="")
    a = ap.parse_args(argv)
    if a.addr:
        anchors.ADDR = a.addr
    if a.src and pathlib.Path(a.src).exists():
        img = anchors.imread(a.src)
    else:
        anchors.resolve_addr()
        img = anchors.screenshot(save="shot.png")
    if img is None:
        anchors.log("没有可用截图")
        sys.exit(1)
    x, y, w, h = a.rect
    crop = img[y:y + h, x:x + w]
    if crop.size == 0:
        anchors.log("裁剪区域为空，检查坐标是否超出 %dx%d" % (img.shape[1], img.shape[0]))
        sys.exit(1)
    ref_w = a.ref_w or img.shape[1]
    p = anchors.save_anchor(a.save, crop, ref_w, rect=[x, y, w, h])
    print("锚点已保存: %s  (%dx%d, ref_w=%d, rect=%s)"
          % (p, crop.shape[1], crop.shape[0], ref_w, [x, y, w, h]))


def cmd_step(argv):
    ap = argparse.ArgumentParser(prog="record.py step")
    ap.add_argument("--flow", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--anchor", required=True, help="页面锚点模板名（校验当前页面）")
    ap.add_argument("--anchor-thr", type=float, default=0.8)
    ap.add_argument("--click-anchor", default="", help="目标模板名（找它并点中心）")
    ap.add_argument("--click-thr", type=float, default=0.8)
    ap.add_argument("--click-xy", nargs=2, type=int, default=None, metavar=("X", "Y"),
                    help="或直接点固定坐标")
    ap.add_argument("--wait", type=float, default=1.5)
    ap.add_argument("--on-fail", choices=["abort", "skip", "back"], default="abort")
    a = ap.parse_args(argv)
    flow = pathlib.Path(a.flow)
    data = (json.loads(flow.read_text(encoding="utf-8"))
            if flow.exists() else {"name": flow.stem, "steps": []})
    step = {"name": a.name, "anchor": a.anchor, "anchor_thr": a.anchor_thr,
            "wait": a.wait, "on_fail": a.on_fail}
    if a.click_anchor:
        step["click_anchor"] = a.click_anchor
        step["click_thr"] = a.click_thr
    if a.click_xy:
        step["click_xy"] = list(a.click_xy)
    data.setdefault("steps", []).append(step)
    flow.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已追加步骤到 %s（共 %d 步）" % (flow, len(data["steps"])))


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("shot", "step", "anchor"):
        cmd, rest = argv[0], argv[1:]
    else:
        cmd, rest = "anchor", argv  # 默认=裁锚点，兼容 record.py --anchor x y w h --save n
    {"shot": cmd_shot, "anchor": cmd_anchor, "step": cmd_step}[cmd](rest)


if __name__ == "__main__":
    main()
