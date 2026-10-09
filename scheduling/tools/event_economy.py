#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活动商店 · 理智/代币规划器
==========================
给定一个活动的数据文件(关卡理智、每关代币产出、商店道具价格/限购)，计算：
  · 各关「代币/理智」>> 选最优刷关；
  · 目标道具集需要的总代币 → 需要打多少次、花多少理智；
  · 对比活动期自然理智预算，判断能否换完 / 缺口。

数据来源(每次活动都要更新，见 docs/WORKFLOW-活动关作业.md 的「活动经济」节)：
  · 关卡理智     -> PRTS 关卡页「作战消耗」；代币产出 -> 游戏内关卡详情「掉落预览」/ 一图流 / PRTS
  · 商店道具价格/限购 -> 游戏内活动商店(劳工配给所之类)；wiki 更新后亦可
  数据文件：scheduling/data/event_<id>.json  (schema 见同目录 event_act52side.json)

用法：
  python event_economy.py scheduling/data/event_act52side.json
  python event_economy.py ... --farm YW-8           # 指定刷关
  python event_economy.py ... --min-priority 高      # 只算高优先级道具
  python event_economy.py ... --tokens-owned 179     # 手里已有多少代币
  python event_economy.py ... --medicine 3 --med-per 120   # 另加 3 瓶浓缩液(120)
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import sys

PRI_ORDER = {"高": 0, "中": 1, "低": 2}


def load(path):
    return json.load(open(path, encoding="utf-8"))


def days_between(a, b):
    da = dt.date.fromisoformat(a)
    db = dt.date.fromisoformat(b)
    return max(0, (db - da).days)


def build(args):
    ev = load(args.event)
    stages = ev.get("stages", [])
    shop = ev.get("shop", [])

    # 代币/理智
    for s in stages:
        s["tp"] = None
        if s.get("token_per_run") and s.get("sanity"):
            s["tp"] = s["token_per_run"] / s["sanity"]

    have_tokens = args.tokens_owned

    # 目标集
    sel = [it for it in shop if PRI_ORDER.get(it.get("priority", "低"), 2) <= PRI_ORDER.get(args.min_priority, 2)]
    need = sum(it["price"] * it["limit"] for it in sel)
    remain = max(0, need - have_tokens)

    print("=" * 74)
    print("活动：%s (%s)   代币：%s   期间：%s ~ %s   共 %d 天" % (
        ev.get("name"), ev.get("event_id"), (ev.get("token") or {}).get("name"),
        ev.get("start"), ev.get("end"), days_between(ev.get("start"), ev.get("end"))))
    print("=" * 74)

    print("\n[各关 代币/理智]")
    rank = sorted([s for s in stages if s["tp"]], key=lambda s: -s["tp"])
    for s in stages:
        tp = ("%.3f" % s["tp"]) if s["tp"] else "??(缺 token_per_run)"
        print("  %-6s %-6s 理智%3d  代币/次 %-5s  代币/理智 %s" % (
            s["code"], s.get("name", ""), s["sanity"], s.get("token_per_run") or "?", tp))

    farm = None
    if args.farm:
        farm = next((s for s in stages if s["code"] == args.farm), None)
    elif rank:
        farm = rank[0]

    print("\n[目标道具]  优先级<=%s   共 %d 项" % (args.min_priority, len(sel)))
    for it in sel:
        print("  %-12s 价%-4d 限购%-2d 需%-6d  [%s] %s" % (
            it["name"], it["price"], it["limit"], it["price"] * it["limit"],
            it.get("kind", ""), it.get("priority", "")))
    print("  —— 需代币合计 %d，已有 %d，还差 %d" % (need, have_tokens, remain))

    print("\n[结论]")
    if not farm or not farm.get("token_per_run"):
        print("  ⚠ 还缺『代币/次』数据，无法算刷关次数。")
        print("     → 在游戏内打开一关的『掉落预览』读『未来瞻望镜 xN』，填进数据文件 stages[].token_per_run 后重跑；")
        print("       或等 PRTS/一图流 补数据。理智已就绪(可用于对比)。")
        return
    runs = math.ceil(remain / farm["token_per_run"]) if remain else 0
    sanity = runs * farm["sanity"]
    days = days_between(ev.get("start"), ev.get("end"))
    budget = days * 240 + (days // 7) * 240 + args.medicine * args.med_per   # 自然 + 周常浓缩液(240/周) + 药
    print("  最优刷关：%s（%s） 代币/理智=%.3f" % (farm["code"], farm.get("name", ""), farm["tp"]))
    print("  还需代币 %d → 需刷 %d 次 × %d 理智 = **%d 理智**" % (remain, runs, farm["sanity"], sanity))
    print("  活动期自然+周常预算 ≈ %d 理智（%d 天；另计药 %d 瓶×%d）" % (budget, days, args.medicine, args.med_per))
    if sanity <= budget:
        print("  ✅ 够换完（余 %d 理智可另用）" % (budget - sanity))
    else:
        print("  ❌ 缺口 %d 理智 → 需再攒药/源石，或砍掉低优先级道具" % (sanity - budget))


def main():
    ap = argparse.ArgumentParser(description="活动商店·理智/代币规划器")
    ap.add_argument("event", help="scheduling/data/event_<id>.json")
    ap.add_argument("--farm", default="", help="指定刷关代号，如 YW-8")
    ap.add_argument("--min-priority", default="低", choices=["高", "中", "低"])
    ap.add_argument("--tokens-owned", type=int, default=0)
    ap.add_argument("--medicine", type=int, default=0)
    ap.add_argument("--med-per", type=int, default=120)
    args = ap.parse_args()
    build(args)


if __name__ == "__main__":
    main()
