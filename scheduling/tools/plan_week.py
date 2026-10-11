#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每周规划器 —— 规则写死，确定性产出一周的 `weekly_plan.json`。

思路（像 OI：固定输入 + 固定算法 → 固定输出）：

输入
  · 固源岩库存      ← MAA `DepotData.json`（item 30012）
  · 理智药存量      ← `scheduling/data/sanity.json`（sanity_potion.py 产出）
  · 当期活动        ← `scheduling/data/event_*.json`（含每关理智 + 开放/结束日）

预算
  budget = 自然(240×7=1680) + 周常浓缩液(2×120=240) + 理智药存量

规则（严格按优先级，先满足前面的，余下再给后面）
  R1 剿灭：打满周上限 → runs = ceil(1800/370) = 5 次 × 25 理智 = 125（**每天 1 次**）
  R2 固源岩下限：期末库存 ≥ target(1000)
        → 1-7 次数 = ceil((target + 日耗×7 - 库存) / 单次产出)
  R3 活动关：剩余预算装满（受开放窗口约束；次数由剩余预算反推）
  R4 填充：预算还有零头 → 继续 1-7（**理智必须花光**）
  R5 每日分配：活动只在开放窗口内；剿灭每天 1；其余往"最空的天"填

输出
  `scheduling/data/weekly_plan.json`（含 tasks / windows / budget / inventory / shards / rationale）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "scheduling" / "data"
TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

# ------------------------- 规则参数（写死） -------------------------
RULE = {
    "natural_per_day": 240,          # 自然回复 10/h
    "cap": 205,                      # 理智上限
    "weekly_potion": 240,            # 周常浓缩液 ×2
    "annihilation": {"sanity": 25, "jade_per_run": 370, "weekly_jade_cap": 1800,
                     "per_day": 1},
    "shards": {"item_id": "30012", "target": 500, "stage": "1-7",
               "per_run": 1.245, "daily_use": 92.4},
    "filler": "1-7",
    "train_targets": ["乌尔比安"],   # 本期只养乌尔比安（用户 2026-10-11 定）
}
DEPOT = pathlib.Path(r"C:\MAA\data\DepotData.json")
OUT = DATA / "weekly_plan.json"


def _week(d: dt.date):
    mon = d - dt.timedelta(days=d.weekday())
    sun = mon + dt.timedelta(days=6)
    iso = d.isocalendar()
    return mon, sun, "W%02d" % iso[1]


def read_shard_stock() -> int | None:
    try:
        dep = json.loads(DEPOT.read_text(encoding="utf-8"))
        return int((dep.get("data") or {}).get(RULE["shards"]["item_id"]))
    except Exception:  # noqa: BLE001
        return None


def read_meds() -> dict:
    """读理智药读数：{sanity, week}。week = 读数所在 ISO 周，用来判断周常 240 会不会重复计。"""
    try:
        d = json.loads((DATA / "sanity.json").read_text(encoding="utf-8"))
        san = int(d.get("potion_sanity") or 0)
        ts = str(d.get("ts") or "")[:10]
        wk = None
        if ts:
            dd = dt.date.fromisoformat(ts)
            wk = "%d-W%02d" % (dd.isocalendar()[0], dd.isocalendar()[1])
        return {"sanity": san, "week": wk, "ts": ts}
    except Exception:  # noqa: BLE001
        return {"sanity": 0, "week": None, "ts": ""}


def read_events() -> list:
    out = []
    for p in DATA.glob("event_*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if d.get("stages"):
            out.append(d)
    return out


def pick_event(events: list, mon: dt.date, sun: dt.date):
    """选覆盖本期的活动（start ≤ sun 且 end ≥ mon）。"""
    for e in events:
        try:
            s = dt.date.fromisoformat(str(e.get("start"))[:10])
            t = dt.date.fromisoformat(str(e.get("exchange_end") or e.get("end"))[:10])
        except Exception:  # noqa: BLE001
            continue
        if s <= sun and t >= mon:
            return e
    return None


def plan(date: dt.date) -> dict:
    mon, sun, wk = _week(date)
    plan_week_id = "%d-%s" % (mon.year, wk)
    stock = read_shard_stock()
    med = read_meds()
    meds = med["sanity"]
    # 周常 240：只有「读数不在计划周内」时才加（否则存量里已经含了本周周常，会重复计）
    weekly_potion = RULE["weekly_potion"]
    if med["week"] and med["week"] == plan_week_id:
        weekly_potion = 0
        notes = ["理智药读数(%s)就在计划周内 → 周常 240 已含在存量，不重复计" % med["ts"]]
    else:
        notes = []
    budget = RULE["natural_per_day"] * 7 + weekly_potion + meds

    # --- R1 剿灭 ---
    a = RULE["annihilation"]
    ann_runs = math.ceil(a["weekly_jade_cap"] / a["jade_per_run"])
    # 本周若已打满（state.json.progress.annihilation）→ 跳过，别白花理智
    try:
        stj = json.loads((ROOT / "docs" / "state.json").read_text(encoding="utf-8"))
        pa = ((stj.get("progress") or {}).get("annihilation") or {})
        if pa.get("done") and str(pa.get("week") or "") == plan_week_id:
            ann_runs = 0
            notes.append("本周剿灭已打满（%s %s/%s）→ 本周不再排剿灭"
                         % (pa.get("week"), pa.get("jade"), pa.get("cap")))
    except Exception:  # noqa: BLE001
        pass
    ann_san = ann_runs * a["sanity"]

    # --- R2 固源岩下限 → 1-7 ---
    sh = RULE["shards"]
    if stock is None:
        r17 = 0
        notes.append("未读到固源岩库存（DepotData 缺失）→ 1-7 暂按填充处理")
    else:
        need = sh["target"] + sh["daily_use"] * 7 - stock
        r17 = max(0, math.ceil(need / sh["per_run"]))
        notes.append("固源岩 %d → 期末需 ≥%d：1-7 至少 %d 次（周耗 %.0f）"
                     % (stock, sh["target"], r17, sh["daily_use"] * 7))
    san17 = r17 * 6

    ev = pick_event(read_events(), mon, sun)
    ev_stage, ev_san, ev_runs, ev_win = None, 0, 0, {}
    shop_credit = {}          # 活动商店能白拿的材料 → 抵扣培养需求

    # --- R2.5 EX / S 首通（开放即打，必做；先占预算）---
    extra_tasks, extra_san = [], 0
    if ev:
        for key, listkey, label in (("ex_open", "ex_stages", "EX"), ("s_open", "s_stages", "S")):
            d0 = str(ev.get(key) or "")[:10]
            if not d0:
                continue
            try:
                dd = dt.date.fromisoformat(d0)
            except Exception:  # noqa: BLE001
                continue
            if mon <= dd <= sun:
                for s in (ev.get(listkey) or []):
                    extra_tasks.append((s["code"], 1, int(s.get("sanity") or 0)))
                    extra_san += int(s.get("sanity") or 0)
                notes.append("★ 本周 %s 开放 %s 关 %d 个 → 首通共 %d 理智（必做）"
                             % (d0, label, len(ev.get(listkey) or []),
                                sum(int(s.get("sanity") or 0) for s in (ev.get(listkey) or []))))
            elif dd > sun:
                notes.append("%s 关 %s 开放（不在本周），届时首通（往期口径 %d 个 ≈ %d 理智）"
                             % (label, d0, len(ev.get(listkey) or []),
                                sum(int(s.get("sanity") or 0) for s in (ev.get(listkey) or []))))

    # --- R3 活动：剩余预算反推 ---
    if ev:
        st = ev.get("farm")
        stages = {s.get("code"): s for s in ev.get("stages", [])}
        if st not in stages:                      # 没指定就取理智最高的关（产料最多）
            st = max(stages, key=lambda k: stages[k].get("sanity") or 0, default=None)
        if st:
            ev_stage = st
            ev_san = int(stages[st].get("sanity") or 0)
            ev_win = {"open": str(ev.get("start"))[:10], "close": str(ev.get("combat_end")
                                                                   or ev.get("end"))[:10]}
            left = budget - ann_san - san17 - extra_san
            # 活动优先：次数按「商店要买的总量」封顶（活动=囤资源期，能换的都换）
            shop = ev.get("shop") or []
            need_tok = sum((it.get("price") or 0) * (it.get("limit") or 0)
                           for it in shop if (it.get("limit") or 0) > 0)
            tok_per_run = int(stages[st].get("token_per_run") or 0) or 1
            cap_runs = math.ceil(need_tok / tok_per_run) if need_tok else 10 ** 9
            ev_runs = min(left // ev_san, cap_runs) if ev_san else 0
            train_budget = max(0, left - ev_runs * ev_san)
            notes.append("活动 %s：开放 %s~%s，每局 %d 理智；商店要买 %d 代币 → 需 %d 次，"
                         "本周排 %d 次（预算够 %d 次）"
                         % (st, ev_win["open"], ev_win["close"], ev_san,
                            need_tok, cap_runs, ev_runs, left // ev_san if ev_san else 0))
            # 商店能换的材料 → 直接抵扣培养需求
            try:
                _idx = json.loads(pathlib.Path(r"C:\MAA\resource\item_index.json")
                                  .read_text(encoding="utf-8"))
                name2id = {(v or {}).get("name"): k for k, v in _idx.items()}
                for it in shop:
                    iid = name2id.get(it.get("name"))
                    lim = it.get("limit") or 0
                    if iid and lim > 0:
                        shop_credit[iid] = shop_credit.get(iid, 0) + lim
            except Exception:  # noqa: BLE001
                pass
    if not ev:
        notes.append("本期无进行中的活动 → 预算全给 1-7")

    # --- R3.5 培养：按缺口"刷材料"关卡分配，产出额外 Fight 任务 ---
    train_tasks, train_spent, train_info = {}, 0, None
    try:
        sys.path.insert(0, str(TOOLS))
        import oper_cost as oc
        train_info = oc.compute(targets=RULE.get("train_targets"), credit=shop_credit)
        if shop_credit:
            notes.append("活动商店可白拿 %d 种材料（已从培养需求里抵扣）"
                         % len(train_info.get("credited") or {}))
        val = train_info["val"]
        if not ev:
            train_budget = max(0, budget - ann_san - san17)
        rows = [r for r in train_info["rows"] if (r.get("det") or {}).get("farm")]
        rows.sort(key=lambda r: -(r.get("sanity") or 0))
        for r in rows:
            if train_spent >= train_budget:
                break
            d = val.direct.get(r["item"])
            if not d:
                continue
            unit, code, per_run = d
            san_per_run = unit * per_run
            runs = int((train_budget - train_spent) // san_per_run)
            if runs <= 0:
                continue
            train_tasks[code] = train_tasks.get(code, 0) + runs
            train_spent += runs * san_per_run
        notes.append("培养：总缺口 %.0f 理智（材料 %.0f + 龙门币 %.0f）；本周投 %d 理智刷 %s"
                     % (train_info["total_sanity"], train_info["material_sanity"],
                        train_info["lmd_sanity"], train_spent,
                        "、".join("%s×%d" % (k, v) for k, v in train_tasks.items()) or "无"))
    except Exception as e:  # noqa: BLE001
        notes.append("培养估值失败：%r" % e)

    # --- R4 填充：花光预算 ---
    used = ann_san + san17 + ev_runs * ev_san + train_spent
    fill_runs = max(0, (budget - used) // 6)
    r17_total = int(r17 + fill_runs)
    notes.append("预算 %d；剿灭 %d + 1-7 %d + 活动 %d + 培养 %d = %d；补 1-7 %d 次花光"
                 % (budget, ann_san, san17, ev_runs * ev_san, train_spent, used, fill_runs))

    # --- R2.5 EX / S 首通 —— 已在前面算过（勿重复！）---

    tasks = [{"type": "StartUp", "params": {"client_type": "Official", "start_game_enabled": True}}]
    tasks.append({"type": "Fight", "params": {"stage": "Annihilation", "times": ann_runs},
                  "name": "剿灭"})
    if ev_stage and ev_runs:
        # 活动关用「连战」：times 仍是总次数，series=10 让 MAA 每次开战连打 10 局
        tasks.append({"type": "Fight",
                      "params": {"stage": ev_stage, "times": ev_runs,
                                 "series": RULE.get("event_series", 10)},
                      "name": "活动刷代币"})
    for code, cnt, _sn in extra_tasks:
        tasks.append({"type": "Fight", "params": {"stage": code, "times": cnt},
                      "name": "EX/S 首通"})
    if r17_total > 0:
        tasks.append({"type": "Fight", "params": {"stage": RULE["shards"]["stage"],
                                                  "times": r17_total,
                                                  "series": RULE.get("normal_series", 6)},
                      "name": "搓玉/填充"})
    for code, cnt in sorted(train_tasks.items(), key=lambda kv: -kv[1]):
        tasks.append({"type": "Fight", "params": {"stage": code, "times": cnt},
                      "name": "培养刷材料"})
    tasks += [
        {"type": "Recruit", "params": {"select": [3, 4, 5], "confirm": [3, 4, 5], "times": 4}},
        # 收菜交给 infrast_rotation.py（见 side 的 collect），别再用 MAA Infrast 重复收
        {"type": "Mall", "params": {"enable": True}},
        {"type": "Award", "params": {"enable": True}},
    ]
    plan = {
        "week": "%d-%s" % (mon.year, wk),
        "range": "%s..%s" % (mon.isoformat(), sun.isoformat()),
        "generated_at": dt.datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "by": "plan_week.py",
        "budget": {"sanity_natural": RULE["natural_per_day"] * 7,
                   "weekly_potion": weekly_potion,
                   "meds_available": meds,
                   "meds_week": med["week"],
                   "daily_natural": RULE["natural_per_day"]},
        "inventory": {"固源岩": stock},
        "shards": {"stock": stock, "target": sh["target"], "per_run": sh["per_run"],
                   "daily_use": sh["daily_use"], "stage": sh["stage"]},
        "windows": {**({"Annihilation": {}}),
                    **({ev_stage: ev_win} if ev_stage else {})},
        "tasks": tasks,
        "side": [
            # 换班（收菜 → 菲亚梅塔置换 → 13房切队列 → 换班后再收菜）
            # 收菜跟着换班走；只在到期时跑（if_due 查 state.json.triggers），别每趟跑
            {"script": "scripts/infrast-rotation/infrast_rotation.py", "args": ["all"],
             "when": "换班到期时", "if_due": "infra_next_swap_at"},
        ],
        "rationale": {"notes": notes,
                      "sanity_alloc": {"annihilation": ann_san, "1-7": r17_total * 6,
                                       "活动": ev_runs * ev_san, "培养": train_spent}},
    }
    if train_info:
        plan["training"] = {
            "targets": [t["name"] for t in train_info["targets"]],
            "total_sanity": train_info["total_sanity"],
            "material_sanity": train_info["material_sanity"],
            "lmd_sanity": train_info["lmd_sanity"],
            "week_sanity": train_spent,
            "week_tasks": train_tasks,
            "credited_count": len(train_info.get("credited") or {}),
            "credited": train_info.get("credited") or {},
            "need_weeks": round(train_info["total_sanity"] / max(1, train_spent), 1) if train_spent else None,
            "top_gaps": [{"name": r["name"], "qty": r["qty"], "sanity": r["sanity"],
                          "stock": (r.get("det") or {}).get("stock", 0)}
                         for r in sorted((x for x in train_info["rows"] if x.get("sanity")),
                                         key=lambda x: -(x["sanity"] or 0))[:12]],
        }
    return plan


def main():
    ap = argparse.ArgumentParser(description="每周规划器（规则写死）")
    ap.add_argument("--date", default="", help="以哪天为准算所属周（默认今天）")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    d = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    p = plan(d)
    print(json.dumps(p, ensure_ascii=False, indent=2))
    if not args.dry:
        pathlib.Path(args.out).write_text(json.dumps(p, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        print("\n[plan] 已写 %s" % args.out)


if __name__ == "__main__":
    main()
