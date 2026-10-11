#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""weekly_plan 的「每日分配」工具（build_site 与 GUI 共用）。

把 weekly_plan.tasks 里 Fight 的总次数分到每一天：
  - 剿灭(Annihilation) → **每天 1 次**（剿灭券是每日任务当天领的，不能一天刷完）；
  - 其余关卡 → 在日期范围内**尽量均分**（余数给前几天）。
plan 自带 `daily` 时原样采用。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import pathlib

DOW = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
BUILTIN_COST = {"Annihilation": 25, "1-7": 6}   # 已知每局理智
DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"   # scheduling/data
SANITY_CAP = 205        # 理智上限
REGEN_PER_12H = 120     # 每 12h 回 120（10/h）
KEEP_AFTER = SANITY_CAP - REGEN_PER_12H   # 85：花到 ≤85，12h 后刚好回满不溢出


def load_costs() -> dict:
    """每关理智单价：内置 + 所有 event_*.json 的 stages[].sanity。"""
    c = dict(BUILTIN_COST)
    try:
        for p in DATA_DIR.glob("event_*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for s in d.get("stages") or []:
                code, san = s.get("code"), s.get("sanity")
                if code and isinstance(san, (int, float)):
                    c.setdefault(code, int(san))
    except Exception:  # noqa: BLE001
        pass
    return c


def _dates(rng: str):
    try:
        a, b = rng.split("..")
        d0 = dt.date.fromisoformat(a.strip())
        d1 = dt.date.fromisoformat(b.strip())
        n = (d1 - d0).days + 1
        return [d0 + dt.timedelta(days=i) for i in range(max(1, n))]
    except Exception:  # noqa: BLE001
        return []


def _in_window(day, win: dict) -> bool:
    """day 是否落在 win={open,close} 内（缺项=不限）。"""
    if not win:
        return True
    d = day.isoformat()[:10] if hasattr(day, "isoformat") else str(day)[:10]
    o = str(win.get("open") or "")[:10]
    c = str(win.get("close") or "")[:10]
    if o and d < o:
        return False
    if c and d > c:
        return False
    return True


DEFAULT_FILLER = "1-7"     # 兜底填充关（搓玉固源岩）；预算没花完就填它


def budget_total(plan: dict, n: int) -> int:
    """本周可花理智 = 自然 + 周常药 + 理智药存量。"""
    b = plan.get("budget") or {}
    return ((b.get("sanity_natural") or 240 * n)
            + (b.get("weekly_potion") or 0)
            + (b.get("meds_available") or 0))


def _filler(plan: dict, cost: dict):
    f = plan.get("filler")
    if isinstance(f, str):
        stage = f
    elif isinstance(f, dict):
        stage = f.get("stage") or DEFAULT_FILLER
    else:
        stage = DEFAULT_FILLER
    return stage, cost.get(stage, 0)


def session_advice(plan: dict, daily: list) -> list:
    """上线建议：不浪费自动回复的节奏。

    原则：理智上限 205、每 12h 回 120 → 花到 ≤85，12h 后刚好回满，不溢出。
    所以**常规每 12h 上线一次**；某天要花 > 12h 回复量时提醒多上线 / 吃理智药。
    """
    rows = []
    for d in daily:
        s = int(d.get("sanity", 0) or 0)
        if s <= 0:
            rows.append({"date": d.get("date"), "dow": d.get("dow"), "sanity": s,
                         "sessions": 0, "note": "本日无需上线"})
            continue
        n = max(1, math.ceil(s / REGEN_PER_12H))
        note = []
        if s > 240:
            note.append("超单日自然回复 240 → 需理智药 ≈%d" % (s - 240))
        if n >= 3:
            note.append("建议分 %d 次上线（每次≤%d）" % (n, SANITY_CAP))
        rows.append({"date": d.get("date"), "dow": d.get("dow"), "sanity": s,
                     "sessions": n, "note": "；".join(note)})
    return rows


def shard_requirement(plan: dict, cost: dict) -> dict | None:
    """按固源岩库存/消耗算 1-7 至少要刷多少次，才能保证周后库存 ≥ target。

    plan.shards = {stock, target, per_run, daily_use, stage}(缺省从 MASTER-PLAN 口径取)。
    """
    s = plan.get("shards") or {}
    inv = plan.get("inventory") or {}
    stock = s.get("stock", inv.get("固源岩"))
    if stock is None:
        return None
    target = s.get("target", 1000)
    per_run = s.get("per_run", 1.245)
    daily_use = s.get("daily_use", 92.4)
    stage = s.get("stage", DEFAULT_FILLER)
    days = len(plan.get("daily") or []) or 7
    need = target + daily_use * days - stock
    runs = max(0, math.ceil(need / per_run)) if per_run else 0
    return {"stage": stage, "runs": runs, "sanity": runs * cost.get(stage, 6),
            "need_shards": round(need, 1), "stock": stock, "target": target,
            "daily_use": daily_use, "days": days}


def weekly_summary(plan: dict, daily: list) -> dict:
    """周合计理智 vs 周预算；标出超每日上限的日子。"""
    total = sum(d.get("sanity", 0) for d in daily)
    b = plan.get("budget") or {}
    natural = b.get("sanity_natural") or 240 * (len(daily) or 7)
    potion = b.get("weekly_potion") or 0
    meds = b.get("meds_available")
    avail = natural + potion + (meds or 0)
    return {
        "total": total, "natural": natural, "weekly_potion": potion, "meds": meds,
        "avail": avail, "gap": max(0, total - avail),
        "over_days": [d.get("date") for d in daily if d.get("over")],
    }


def daily_cap(plan: dict) -> int:
    """每天自然回复的理智（默认 240 = 10/h×24）。"""
    b = plan.get("budget") or {}
    try:
        return int(b.get("daily_natural") or 240)
    except Exception:  # noqa: BLE001
        return 240


def distribute_daily(plan: dict) -> list:
    """把本周刷关次数分到每天，**按每天体力上限（默认 240）往最空的天摊**。

    - 窗口窄的关卡先排（如只开放 3 天的活动关）；
    - 剿灭每天 1 次（每日券）；
    - 返回每天 {date,dow,runs,sanity,over,cap,opens}。
    """
    if not plan:
        return []
    if plan.get("daily"):
        return plan["daily"]
    dates = _dates(plan.get("range", ""))
    n = len(dates) or 7
    wins = plan.get("windows") or {}
    cost = dict(load_costs())
    cost.update(plan.get("sanity_cost") or {})
    cap = daily_cap(plan)
    meds = int((plan.get("budget") or {}).get("meds_available") or 0)
    day_cap = cap + (meds // n if n else 0)     # 每天最多：自然 + 均摊的药
    acc = [{} for _ in range(n)]
    load = [0] * n
    unscheduled = []                            # 排不下的（超每日上限）
    opens = [[] for _ in range(n)]

    jobs = []
    for t in plan.get("tasks", []):
        if t.get("type") != "Fight":
            continue
        p = t.get("params") or {}
        stage, times = p.get("stage"), p.get("times")
        if not stage or not isinstance(times, int) or times <= 0:
            continue
        win = wins.get(stage) or {}
        idxs = ([i for i in range(n) if _in_window(dates[i], win)]
                if dates else list(range(n)))
        if not idxs:
            continue
        o = str(win.get("open") or "")[:10]
        if o and dates:
            for i in idxs:
                if dates[i].isoformat()[:10] == o:
                    opens[i].append(stage)
        jobs.append({"stage": stage, "times": times, "cost": cost.get(stage, 0), "idxs": idxs})

    jobs.sort(key=lambda j: len(j["idxs"]))          # 可用天数少（窗口紧）的先排
    placed = 0
    for j in jobs:
        if str(j["stage"]).lower() == "annihilation":
            for i in j["idxs"][:j["times"]]:          # 每天 1 次
                acc[i][j["stage"]] = acc[i].get(j["stage"], 0) + 1
                load[i] += j["cost"]
                placed += j["cost"]
            continue
        for _ in range(j["times"]):
            i = max(j["idxs"], key=lambda k: (day_cap - load[k], -k))   # 最空的一天
            if load[i] + j["cost"] > day_cap:            # 当天封顶 → 排不下就不排
                unscheduled.append({"stage": j["stage"], "cost": j["cost"]})
                continue
            acc[i][j["stage"]] = acc[i].get(j["stage"], 0) + 1
            load[i] += j["cost"]
            placed += j["cost"]

    # 预算没花完 → 填充关补齐；同时保证固源岩 ≥ target（1-7 下限）
    fstage, fcost = _filler(plan, cost)
    target = budget_total(plan, n)
    runs = max(0, (target - placed) // fcost) if fcost else 0
    req = shard_requirement(plan, cost)
    if req and fstage == req["stage"]:
        runs = max(runs, req["runs"])          # 固源岩下限优先
    # 若填充关已经作为任务出现在 tasks[] 里（plan_week 会写），就别再加一遍
    task_stages = {(t.get("params") or {}).get("stage")
                   for t in plan.get("tasks", []) if t.get("type") == "Fight"}
    if fstage in task_stages and not plan.get("daily"):
        runs = 0
    if fstage and fcost > 0 and runs > 0:
        for _ in range(runs):
            i = max(range(n), key=lambda k: (cap - load[k], -k))
            acc[i][fstage] = acc[i].get(fstage, 0) + 1
            load[i] += fcost

    out = []
    for i in range(n):
        d = dates[i] if i < len(dates) else None
        out.append({
            "date": d.isoformat() if d else "",
            "dow": DOW[d.weekday()] if d else "第%d天" % (i + 1),
            "runs": acc[i],
            "sanity": load[i],
            "cap": cap,
            "day_cap": day_cap,
            "over": load[i] > day_cap,
            "opens": opens[i],
        })
    return out
