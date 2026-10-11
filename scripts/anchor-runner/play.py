#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""锚点回放引擎：读流程 JSON，每步先校验「页面锚点」，命中才点击目标。

用法:
  python play.py --steps steps.json [--dry-run] [--thr 0.8] [--addr ADDR]

流程格式（见 steps.example.json）:
{
  "name": "示例流程",
  "steps": [
    {
      "name": "点基建入口",
      "anchor": "page_main",          // 页面锚点：必须在场，否则视为不在预期页面
      "anchor_thr": 0.8,
      "click_anchor": "btn_infrast",  // 目标锚点：找到它、点它的中心
      "click_thr": 0.8,
      "wait": 2.0,                    // 点完等多久
      "on_fail": "abort"              // 页面锚点没命中时: abort(停) / skip(跳) / back(返回重试)
    },
    {
      "name": "点固定坐标",
      "anchor": "page_overview",
      "click_xy": [175, 156],         // 或直接点固定坐标（二者其一）
      "wait": 1.5
    }
  ]
}

--dry-run：只截图校验页面锚点、报告能不能命中，绝不点击。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import anchors


def run_step(a, step, dry) -> str:
    name = step.get("name", "?")
    thr = step.get("anchor_thr", a.thr)
    img = anchors.screenshot(save="play.png")
    if img is None:
        anchors.log("步骤[%s] 截图失败" % name)
        return "abort"

    anchor = step.get("anchor")
    m = anchors.match(img, anchor, thr) if anchor else {"score": 1.0, "cx": 0, "cy": 0}
    if not m:
        fail = step.get("on_fail", "abort")
        anchors.log("步骤[%s] 页面锚点未命中 (%s, thr=%.2f) -> %s" % (name, anchor, thr, fail))
        return fail
    anchors.log("步骤[%s] 页面锚点命中 score=%.3f" % (name, m["score"]))

    if dry:
        if step.get("click_anchor"):
            mm = anchors.match(img, step["click_anchor"], step.get("click_thr", a.thr))
            anchors.log("  [dry] 目标锚点 %s -> %s"
                        % (step["click_anchor"],
                           ("命中 @ (%d,%d) score=%.3f" % (mm["cx"], mm["cy"], mm["score"]))
                           if mm else "未命中"))
        elif step.get("click_xy"):
            anchors.log("  [dry] 将点固定坐标 %s" % (step["click_xy"],))
        return "ok"

    if step.get("click_anchor"):
        mm = anchors.match(img, step["click_anchor"], step.get("click_thr", a.thr))
        if not mm:
            anchors.log("  目标锚点未命中 (%s) -> abort" % step["click_anchor"])
            return "abort"
        anchors.tap(mm["cx"], mm["cy"])
        anchors.log("  点击 %s @ (%d,%d) score=%.3f"
                    % (step["click_anchor"], mm["cx"], mm["cy"], mm["score"]))
    elif step.get("click_xy"):
        x, y = step["click_xy"]
        anchors.tap(x, y)
        anchors.log("  点击坐标 (%d,%d)" % (x, y))
    else:
        anchors.log("  无点击动作（只校验页面）")

    time.sleep(step.get("wait", 1.5))
    return "ok"


def main():
    ap = argparse.ArgumentParser(description="锚点回放引擎")
    ap.add_argument("--steps", required=True, help="流程 JSON 路径")
    ap.add_argument("--dry-run", action="store_true", help="只校验页面锚点，不点击")
    ap.add_argument("--thr", type=float, default=0.8, help="默认匹配阈值")
    ap.add_argument("--addr", default="")
    a = ap.parse_args()

    if a.addr:
        anchors.ADDR = a.addr
    anchors.resolve_addr()

    flow = pathlib.Path(a.steps)
    data = json.loads(flow.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    print("流程「%s」共 %d 步%s" % (data.get("name", flow.stem), len(steps),
                                   "（dry-run）" if a.dry_run else ""))

    for i, step in enumerate(steps):
        print("--- 第 %d/%d 步 ---" % (i + 1, len(steps)))
        r = run_step(a, step, a.dry_run)
        if r == "abort":
            anchors.log("流程中止于步骤[%s]" % step.get("name", "?"))
            sys.exit(2)
        if r == "back":
            anchors.log("步骤[%s] 按返回键重试" % step.get("name", "?"))
            anchors.key(4)
            time.sleep(2.0)
            r2 = run_step(a, step, a.dry_run)
            if r2 != "ok":
                anchors.log("重试仍失败 -> 中止")
                sys.exit(2)
        # skip -> 继续下一步
    print("流程结束%s" % ("（仅校验，未操作）" if a.dry_run else ""))


if __name__ == "__main__":
    main()
