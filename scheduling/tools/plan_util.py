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
import functools
import json
import math
import pathlib

DOW = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
BUILTIN_COST = {"Annihilation": 25, "1-7": 6}   # 已知每局理智
DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"   # scheduling/data
# 本机关卡表（关 code → apCost）：覆盖**非活动关**（主线/资源/材料关，如 MN-4=12）。
# 旧版 load_costs() 只读 event_*.json，导致培养关 MN-4（12 理智）在逐日分配里按 0 计，
# 10-12 真实负载虚低（406→实为 418），自检探针因此漏判（复盘层 2026-10-12 发现）。
STAGE_TABLES = [
    pathlib.Path(r"C:\MAA\resource\stages.json"),
    DATA_DIR / "gamedata" / "stage_table.json",
]
# 本机关卡表缺、但计划会出现的非活动关 → 显式兜底（来源：MAA resource stages.json apCost）
EXPLICIT_COST = {"MN-4": 12}
SANITY_CAP = 205        # 理智上限
REGEN_PER_12H = 120     # 每 12h 回 120（10/h）
KEEP_AFTER = SANITY_CAP - REGEN_PER_12H   # 85：花到 ≤85，12h 后刚好回满不溢出


def _load_stage_apcost() -> dict:
    """从本机关卡表取「关 code → apCost」，覆盖非活动关（主线/材料/资源关）。

    依次尝试 STAGE_TABLES 里的候选文件；兼容两种结构：
      · list：`[{code, apCost, ...}, ...]`（MAA `resource/stages.json`）；
      · dict：`{stages: {id: {code, apCost}}}` 或 `{id: {code, apCost}}`（ArknightsGameData）。
    第一个能解析出至少一条关卡的表即采用。结果缓存（distribute_daily 会在自检里反复调用）。
    """
    return _load_stage_apcost_cached()


@functools.lru_cache(maxsize=1)
def _load_stage_apcost_cached() -> dict:
    for p in STAGE_TABLES:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        stages = data.get("stages") if isinstance(data, dict) else data
        if isinstance(stages, list):
            it = (s for s in stages if isinstance(s, dict))
        elif isinstance(stages, dict):
            it = (v for v in stages.values() if isinstance(v, dict))
        else:
            continue
        out = {}
        for s in it:
            code, ap = s.get("code"), s.get("apCost")
            if code and isinstance(ap, (int, float)):
                out[str(code)] = int(ap)
        if out:
            return out
    return {}


def load_costs() -> dict:
    """每关理智单价：本机关卡表(apCost) + 已知内置 + 所有 event_*.json 的 stages[].sanity。

    优先级（后者覆盖前者）：本机关卡表 → 内置已知 → 活动价目表（活动关权威）。
    最后对 EXPLICIT_COST 兜底补缺（表里查不到的个别非活动关）。
    """
    c = _load_stage_apcost()          # 先铺底：非活动关（含 MN-4 等培养关）
    c.update(BUILTIN_COST)            # 内置已知单价（Annihilation 等表里没有的）
    try:
        for p in DATA_DIR.glob("event_*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for s in d.get("stages") or []:
                code, san = s.get("code"), s.get("sanity")
                if code and isinstance(san, (int, float)):
                    c[code] = int(san)   # 活动价目表权威，覆盖关卡表
    except Exception:  # noqa: BLE001
        pass
    for code, san in EXPLICIT_COST.items():
        c.setdefault(code, san)
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
RAID_TYPE = "Raid"         # 突袭任务类型（MAA Fight 做不了活动突袭 → 不 append，交 Copilot/手点）


def budget_total(plan: dict, n: int) -> int:
    """本周可花理智 = 自然 + 理智药存量。

    注：`weekly_potion` 恒 0（已废弃）——理智药存量**已含周常药**，不再另加
    （2026-10-12 用户裁定）。保留 `b.get("weekly_potion") or 0` 只为兼容旧 plan。
    """
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
    """把本周刷关次数分到每天，**按每天上限 day_cap 往最空的天摊**。

    - `day_cap = ceil(周总预算 / n)`（自然 + 理智药存量；**药已含周常药，不再加 240**）；
    - 剿灭每天 1 次（每日券，排到窗内前 times 天）；
    - **有序首通**（带 `seq` 的任务，如 EX-1→EX-8 的普通 + 突袭）：按 `seq` 升序、**跨天单调不减**
      依次放置（同一天可放多个），不会出现「后一天排 seq 小的、前一天排 seq 大的」；
    - **突袭**（`type=Raid`）与普通首通同价计入理智，排在其对应普通之后（靠 seq 保证）；
    - **窄窗关**（仅开放窗口内可排）**在窗口内的多天分摊**：逐次挑「该关当天
      已排最少、再取当前最空」的那天，避免全挤在开放首日把单日撑爆；
    - 宽窗关（如全周可排的 YW-6）再往最空的天摊；
    - **严格不超 day_cap**；若容量确实不够（如 day_cap=372 装不下 1-7 下限 417 次 + 剿灭），
      放不下的次数登记进 `unplaced`，不静默丢、也不硬塞爆表。
    - 返回每天 {date,dow,runs,raids,sanity,over,cap,day_cap,opens,unplaced}。
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
    # 每天上限 = 周总预算（自然 + 理智药存量；**药已含周常药**）均摊到 n 天、向上取整。
    # 旧版只算「自然 + 药/天」，漏了周常 240，导致末尾任务排不下被丢（W42 丢了 417 理智）。
    _n = n or 7
    day_cap = (budget_total(plan, _n) + _n - 1) // _n
    acc = [{} for _ in range(n)]
    load = [0] * n
    opens = [[] for _ in range(n)]
    # 开放窗口**不覆盖本周**的 Fight 任务：在这里如实登记（→ 合入 unplaced），
    # 不静默 continue，否则自检/调用方无从察觉（复盘层的隐患）。
    window_unplaced = {}

    jobs = []          # Fight 任务（含带 seq 的有序首通）
    raid_jobs = []     # Raid（突袭）任务：单次、不 append 给 MAA，但仍占理智/占位
    for t in plan.get("tasks", []):
        tt = t.get("type")
        p = t.get("params") or {}
        stage = p.get("stage")
        if tt == "Fight":
            times = p.get("times")
            if not stage or not isinstance(times, int) or times <= 0:
                continue
        elif tt == RAID_TYPE:
            times = 1
            if not stage:
                continue
        else:
            continue
        win = wins.get(stage) or {}
        idxs = ([i for i in range(n) if _in_window(dates[i], win)]
                if dates else list(range(n)))
        if not idxs:
            # 该任务开放窗口与本周边界无交集（如 open/close 都在下周）→ 整条无法排，
            # **登记进 unplaced**（而非静默丢弃），使自检/调用方能察觉。
            _key = stage if tt == "Fight" else "%s(突袭)" % stage
            window_unplaced[_key] = window_unplaced.get(_key, 0) + times
            continue
        o = str(win.get("open") or "")[:10]
        if o and dates:
            for i in idxs:
                if dates[i].isoformat()[:10] == o:
                    opens[i].append(stage)
        rec = {"stage": stage, "times": times, "cost": cost.get(stage, 0), "idxs": idxs,
               "seq": t.get("seq"), "kind": ("raid" if tt == RAID_TYPE else "fight")}
        (raid_jobs if tt == RAID_TYPE else jobs).append(rec)

    # 拆成：剿灭 / 有序（带 seq 的首通+突袭）/ 窄窗（可用天 < 全周）/ 宽窗（可用天 = 全周）
    ann, narrow, wide, ordered = [], [], [], []
    for j in jobs:
        if str(j["stage"]).lower() == "annihilation":
            ann.append(j)
        elif j.get("seq") is not None:
            ordered.append(j)                 # 有序首通 → 走「按 seq 跨天单调不减」通道
        elif len(j["idxs"]) < n:
            narrow.append(j)
        else:
            wide.append(j)
    ordered += raid_jobs
    ordered.sort(key=lambda j: j["seq"] if j.get("seq") is not None else 10 ** 9)

    unplaced = dict(window_unplaced)   # {stage: 放不下的次数}——容量不够/窗口不覆盖本周时**如实登记**，不静默丢、不硬塞爆表

    def _put(j, i):
        acc[i][j["stage"]] = acc[i].get(j["stage"], 0) + 1
        load[i] += j["cost"]

    # 剿灭：每天 1 次（剿灭券每日领，只能排到窗内前 times 天）
    for j in ann:
        for i in j["idxs"][:j["times"]]:
            _put(j, i)

    # 有序首通（EX-1→EX-8 普通 + 突袭；带 seq）：**按 seq 升序、跨天单调不减**依次放置。
    #   规则：第 k 条只能落在「窗口内、且 ≥ 上一条所在天」的日子；优先最早可放天（first-fit，
    #   → 普通关开放在前、突袭紧跟其后，天然满足「先普通后突袭」）。全部不超 day_cap；
    #   若某条在 ≥ prev 的日子里都放不下，则退而取负载最低的一天（保序优先，极端兜底）。
    raid_acc = [[] for _ in range(n)]
    _prev = -1
    for u in ordered:
        cands = [i for i in u["idxs"] if i >= _prev] or list(u["idxs"])
        under = [i for i in cands if load[i] + u["cost"] <= day_cap]
        pick = min(under) if under else min(cands, key=lambda k: (load[k], k))
        if u["kind"] == "raid":
            raid_acc[pick].append(u["stage"])
        else:
            acc[pick][u["stage"]] = acc[pick].get(u["stage"], 0) + 1
        load[pick] += u["cost"]
        _prev = pick

    wide_sorted = sorted(wide, key=lambda j: -(j["cost"] or 0))

    def _pack_wide(L0, A0):
        """给定已排 load/acc，把宽窗关填进去（不超 day_cap），返回 (已放理智, load, acc)。

        两种摆法各试一次、取「放得更多」的那种：
          · 平衡（往最空的天摊）— 平时用，天数摊得匀；
          · 紧凑（往最紧的天塞）— 紧张时用，能多塞下就多塞（与窗口内窄窗关抢容量时关键）。
        """
        def _run(tight):
            L, A, placed = list(L0), [dict(a) for a in A0], 0
            for j in wide_sorted:
                for _ in range(j["times"]):
                    cand = [k for k in j["idxs"] if L[k] + j["cost"] <= day_cap]
                    if not cand:
                        continue
                    i = (min(cand, key=lambda k: (day_cap - L[k], k)) if tight
                         else max(cand, key=lambda k: (day_cap - L[k], -k)))
                    A[i][j["stage"]] = A[i].get(j["stage"], 0) + 1
                    L[i] += j["cost"]
                    placed += j["cost"]
            return placed, L, A
        p_w, L_w, A_w = _run(False)
        p_b, L_b, A_b = _run(True)
        return (p_b, L_b, A_b) if p_b > p_w else (p_w, L_w, A_w)

    # 窄窗关（EX/S 首通等，仅开放窗口内可排）：穷举其落天，选「宽窗关放得最多 → 窄窗关
    # 在窗口内**分摊得最匀** → 单日负载最低」的摆法；**全部不超 day_cap**。
    # （旧版只按「宽窗放最多 + 单日最低」，会把 8 个 EX 全塞到开放首日。）
    narrow_units = [j for j in sorted(narrow, key=lambda j: (len(j["idxs"]), -(j["cost"] or 0)))
                    for _ in range(j["times"])]
    space = 1
    for j in narrow:
        space *= max(1, len(j["idxs"])) ** j["times"]

    best = {"key": None, "load": None, "acc": None}
    if narrow_units and space <= 30000:
        def _dfs(k, L, A, NC):
            if k == len(narrow_units):
                wp, LL, AA = _pack_wide(L, A)
                key = (wp, -(max(NC) if NC else 0), -(max(LL) if LL else 0))
                if best["key"] is None or key > best["key"]:
                    best.update(key=key, load=LL, acc=AA)
                return
            j = narrow_units[k]
            for i in j["idxs"]:
                if L[i] + j["cost"] > day_cap:
                    continue
                A[i][j["stage"]] = A[i].get(j["stage"], 0) + 1
                L[i] += j["cost"]
                NC[i] += 1
                _dfs(k + 1, L, A, NC)
                L[i] -= j["cost"]
                NC[i] -= 1
                A[i][j["stage"]] -= 1
                if A[i][j["stage"]] == 0:
                    del A[i][j["stage"]]

        _dfs(0, list(load), [dict(a) for a in acc], [0] * n)

    if best["acc"] is not None:
        load, acc = best["load"], best["acc"]
    elif narrow_units:                          # 规模太大/无解 → 贪心分摊窄窗关（不超 day_cap）
        for j in narrow_units:
            fits = [i for i in j["idxs"] if load[i] + j["cost"] <= day_cap]
            if not fits:
                unplaced[j["stage"]] = unplaced.get(j["stage"], 0) + 1
                continue
            i = min(fits, key=lambda k: (acc[k].get(j["stage"], 0), load[k], k))
            _put(j, i)
        _, load, acc = _pack_wide(load, acc)
    else:                                       # 无窄窗关 → 直接填宽窗关
        _, load, acc = _pack_wide(load, acc)

    # 收尾：容量实在不够、个别次数没排下的 → 记入 unplaced（**不硬塞爆表**）。
    for j in jobs:
        got = sum(acc[i].get(j["stage"], 0) for i in range(n))
        if got < j["times"]:
            unplaced[j["stage"]] = unplaced.get(j["stage"], 0) + (j["times"] - got)
    placed = sum(load)

    # 分配对象就是「计划里的 Fight 任务」（plan_week 已自行算好 1-7 filler）；
    # 这里只在「固源岩下限」不足时才补 1-7，不再额外平白补 filler。
    # 注意：若已有放不下的次数（容量确实不够，如 day_cap=406 放不下 123 次 YW-6），
    # 说明本周被容量卡住，此时**不补 filler**——避免「丢了 A 又悄悄换成 B」。
    if not unplaced:
        fstage, fcost = _filler(plan, cost)
        # 计划理智合计 = Fight 任务 + 突袭（Raid 单次）
        target = (sum(j["times"] * j["cost"] for j in jobs)
                  + sum(j["cost"] for j in raid_jobs))
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
                fits = [k for k in range(n) if load[k] + fcost <= day_cap]
                if not fits:
                    break
                i = min(fits, key=lambda k: (load[k], k))
                acc[i][fstage] = acc[i].get(fstage, 0) + 1
                load[i] += fcost

    out = []
    for i in range(n):
        d = dates[i] if i < len(dates) else None
        out.append({
            "date": d.isoformat() if d else "",
            "dow": DOW[d.weekday()] if d else "第%d天" % (i + 1),
            "runs": acc[i],
            "raids": raid_acc[i],            # 当天要打的突袭关（按 seq 顺序；MAA 不做 → Copilot/手点）
            "sanity": load[i],
            "cap": cap,
            "day_cap": day_cap,
            "over": load[i] > day_cap,
            "opens": opens[i],
            "unplaced": dict(unplaced),      # 超 day_cap 容量、放不下的次数（非静默丢弃）
        })
    return out
