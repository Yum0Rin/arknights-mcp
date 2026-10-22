#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每周规划器 —— 规则写死，确定性产出一周的 `weekly_plan.json`。

思路（像 OI：固定输入 + 固定算法 → 固定输出）：

输入
  · 固源岩库存      ← MAA `DepotData.json`（item 30012）
  · 理智药存量      ← `scheduling/data/sanity.json`（sanity_potion.py 产出）
  · 当期活动        ← `scheduling/data/event_*.json`（含每关理智 + 开放/结束日）

预算
  budget = 自然(240×7=1680) + 理智药存量
  注：理智药存量**已包含周常药**（由每周日手动跑 scripts/sanity-potion/sanity_potion.py 测出，
      写入 scheduling/data/sanity.json），故**不再另加周常浓缩液 240**（重复计入会把预算虚高）。

规则（严格按优先级，先满足前面的，余下再给后面）
  R1 剿灭：打满周上限 → runs = ceil(1800/370) = 5 次 × 25 理智 = 125（**每天 1 次**）
  R2 固源岩下限：期末库存 ≥ target（**条件**：有活动要打 → 500；无 → 1000）
        → 1-7 下限 = ceil((target + 日耗×7 - 库存) / 单次产出)，**向上取整到 series 整倍数**
  R2.5 EX/S 首通链：读 docs/state.json.progress.<活动> 的已通进度，
        **只排未通的关、从第一个未通起的解锁链**（EX-1→EX-8 依次解锁，已通的不重复排）；
        且 **只有 EX/S 有突袭**（普通关 YW-1..8 无），突袭依赖「该关普通已通」，
        每关普通首通后紧跟一条该关 `Raid`（突袭）；进度缺失 → 当全未通
  R3 活动关：**在 ann + EX/S首通 + 1-7下限 之后**吃剩余预算（上限仍是「商店要买总量反推」的次数）
  R3.5 培养：再剩 → 培养刷材料
  R4 1-7 填充：最后剩 → 1-7 填充（**理智尽量花光**）
  R5 每日分配：活动只在开放窗口内；剿灭每天 1；带 seq 的首通按序单调不减；其余往"最空的天"填
  次数取整：每个 Fight 关的次数**按该关 series 取整**（下限向上、活动/填充向下）；余数回流预算，
        逐日分配也保持**每天是该关 series 的整倍数**（否则 GUI 会警告「余数无法用尽」）
  用药：逐日视图带 `medicine`（= max(0, 当天理智 − 自然 240)）；只**配上药的关**（1-7/活动关）

输出
  `scheduling/data/weekly_plan.json`（含 tasks / windows / budget / inventory / shards / rationale）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "scheduling" / "data"
TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

# ------------------------- 规则参数（写死） -------------------------
RULE = {
    # 「自然/天」= **上限 205**，不是 240（2026-10-14 用户裁定）。
    # 本机玩法是「**1 次/天**、来时理智满、跑完下线」：24h 自然回 240 被上限 205 卡住，
    # 每天实际只能用 205，多出的 35/天**溢出丢掉**。故预算里的自然量按 205/天。
    "natural_per_day": 205,
    "cap": 205,                      # 理智上限
    # 理智药**整瓶 60**：只有整瓶能喝，余数本周用不掉（留到下周）→ 预算里的药按整瓶计
    "medicine_bottle": 60,
    # ⚠ 已删除 weekly_potion：周常浓缩液**不再单独计入预算**——理智药存量（sanity.json，
    #   每周日手动跑 scripts/sanity-potion/sanity_potion.py 测出）**已包含周常药**，
    #   重复计入会把预算虚高（2026-10-12 用户裁定：「预算理智药已经包含了周药，不可另行考虑周药」）。
    # 剿灭：25 理智/次；**用券（全权委托）只是速刷、跳过战斗，理智照扣**（2026-10-11 用户纠正）。
    # 券=每日任务当天领 1 张 → 每天 1 次（周一~周五 5 次 = 打满 1800 玉），一张一天才回转得过来。
    "annihilation": {"sanity": 25, "jade_per_run": 370, "weekly_jade_cap": 1800,
                     "per_day": 1, "via_ticket": True},
    # 固源岩下限：**随「本期有没有活动要打」而变**（2026-10-12 用户裁定）
    #   · 有活动要打（选中活动且还有未完成：首通/突袭未打完 或 商店还要买）→ 下限 500（1-7 让位给活动）
    #   · 无活动要打 → 下限 1000
    "shards": {"item_id": "30012", "stage": "1-7",
               "target_activity": 500, "target_idle": 1000,
               "per_run": 1.245, "daily_use": 92.4},
    "filler": "1-7",
    # 连战上限：本机 resource **无** `FightSeries-OldMethodFlag` → 走新列表分支，上限 **10**
    # （活动关与普通关都用 10；旧文档写 6 是旧列表口径，已作废）。
    "normal_series": 10,
    "event_series": 10,
    "train_targets": ["乌尔比安"],   # 本期只养乌尔比安（用户 2026-10-11 定）
    # 基建（2026-10-14 用户裁定「选 2」）：MAA **自定义换班**（`mode=10000` Custom）
    #   · 只有 Custom/Default 才**逐设施摆干员**并执行**菲亚梅塔置换**；Rotation(20000) 只点一次
    #     游戏内「队列轮换」且 `skip shift`（不摆干员）。见 docs/FINDINGS.md §24。
    #   · 方案表 = 一图流「243 两换」两份 plan：index 0 = B班、index 1 = A班。MAA **不看** plan 的
    #     `period`（那是 GUI「按时间自动」用的）→ 由我们**显式传** `plan_index`。
    #   · 班次：14:00「每日日常」→ A班(1)；02:00「凌晨基建换班」→ B班(0)，两边各换一次对齐 720min。
    #   · 方案表 = 一图流「243 搓玉两换」→ `convert_to_maa.py` 转成 MAA custom_infrast 格式，
    #     落在仓库 `scheduling/MAA基建排班/243_搓玉_定制.json`（**不是** MAA resource 里那份「钱书均衡·龙门币优先」版；
    #     同口径见 `scripts/maa-week/maa_week.py` 的 `INFRAST_CUSTOM_FILE`，改口径要**两处一起改**）。
    "infra_mode": 10000,
    "infra_custom_file": str(ROOT / "scheduling" / "MAA基建排班" / "243_搓玉_定制.json"),
    "infra_plan_day": 1,     # 14:00 跑的那一班
    "infra_plan_night": 0,   # 02:00 跑的那一班
    # 收哪些设施（= MAA GUI RoomList 里启用的那批；**Custom 下顺序 = 执行顺序**）。AssistantChange 不启用。
    "infra_facilities": ["Mfg", "Trade", "Power", "Control", "Reception",
                         "Office", "Dorm", "Processing", "Training"],
    # 突袭（raid）：**只有 EX 关和 S 关有突袭**，普通关（YW-1..8）没有；每关**打完普通首通后**才可打其突袭。
    # MAA `Fight` 做不了活动突袭（`is_raid` 只在 Copilot 的 `copilot_list` 条目里，见 docs/MAA-INTERNALS.md §2.10）
    # → 计划里用独立 task 类型 `Raid` 表示，执行交 scripts/event-copilot（Copilot is_raid）或手点。
    # 突袭理智**先按与普通关相同计**（EX 10/10/15/15/15/15/20/20、S 15）—— **口径待数据层核实**。
    "raid": {"only": ["EX", "S"], "after_normal": True, "type": "Raid"},
}

# 突袭任务类型名（与 plan_util / maa_week 共用口径）
RAID_TYPE = "Raid"
DEPOT = pathlib.Path(r"C:\MAA\data\DepotData.json")
OUT = DATA / "weekly_plan.json"


def _series_cap() -> int:
    """本机连战上限（运行时按资源判定；见 plan_util.series_cap）。失败按新列表 10。"""
    try:
        import plan_util
        return int(plan_util.series_cap())
    except Exception:  # noqa: BLE001
        return 10


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


_STAGE_CODE_RE = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)?-?\d+")


def _stage_codes(raw) -> set:
    """从进度字段（`list[str]` 或 `str`）解析关卡代号前缀集合。
    容错：`\"YW-5(2星)\"` -> `\"YW-5\"`；`\"YW-EX-3\"` -> `\"YW-EX-3\"`（只取代号前缀，别被 `(2星)` 绊倒）。"""
    out = set()
    if isinstance(raw, str):
        raw = [raw]
    for it in (raw or []):
        m = _STAGE_CODE_RE.search(str(it))
        if m:
            out.add(m.group(0))
    return out


def read_event_progress(event_id: str) -> dict:
    """读 `docs/state.json.progress.<event_id>` 的「已通关」进度（**只读**，不写）。

    返回 `{normal_done:set, raid_done:set, missing:bool}`：
      · normal_done = first_clear_done ∪ ex_clear_done ∪ s_clear_done（普通关已通）；
      · raid_done   = raid_clear_done（突袭已通，用关卡代号）；
      · **字段缺失/格式意外 → 两个集合为空**（当「全未通」，宁可多排一次首通，也别漏排导致后面解锁不了）。
    """
    normal, raid, missing = set(), set(), True
    try:
        st = json.loads((ROOT / "docs" / "state.json").read_text(encoding="utf-8"))
        _prog = st.get("progress") or {}
        # state.json 里活动进度键是 `event_<id>`（如 event_act52side）；也兼容裸 <id>
        pr = (_prog.get("event_%s" % event_id)
              or _prog.get(event_id) or {})
        for k in ("first_clear_done", "ex_clear_done", "s_clear_done"):
            if k in pr:
                missing = False
                normal |= _stage_codes(pr.get(k))
        if "raid_clear_done" in pr:
            missing = False
            raid |= _stage_codes(pr.get("raid_clear_done"))
    except Exception:  # noqa: BLE001
        pass
    return {"normal_done": normal, "raid_done": raid, "missing": missing}


def _num_suffix(code: str) -> int:
    m = re.search(r"(\d+)$", str(code))
    return int(m.group(1)) if m else 10 ** 9


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


def _assemble_tasks(ann_runs, ev_stage, ev_runs, extra_tasks, r17_total, train_tasks) -> list:
    """按当前各关次数组装本周 tasks（StartUp→剿灭→活动→EX/S→1-7→培养→日常）。"""
    tasks = [{"type": "StartUp", "params": {"client_type": "Official", "start_game_enabled": True}}]
    tasks.append({"type": "Fight", "params": {"stage": "Annihilation", "times": ann_runs},
                  "name": "剿灭"})
    if ev_stage and ev_runs:
        # 活动关用「连战」：times 仍是总次数，series=10 让 MAA 每次开战连打 10 局
        tasks.append({"type": "Fight",
                      "params": {"stage": ev_stage, "times": ev_runs,
                                 "series": RULE.get("event_series", 10)},
                      "name": "活动刷代币"})
    # EX/S 首通 + 突袭：带 seq（升序），plan_util 会按 seq「跨天单调不减」依次放置。
    # 突袭**不是 Fight**（MAA Fight 做不了活动突袭）→ 用独立类型 Raid，执行交 Copilot/手点。
    for e in extra_tasks:
        if e.get("kind") == "raid":
            tasks.append({"type": RAID_TYPE, "params": {"stage": e["stage"]},
                          "name": e["name"], "seq": e["seq"]})
        else:
            tasks.append({"type": "Fight", "params": {"stage": e["stage"], "times": e["times"]},
                          "name": e["name"], "seq": e["seq"]})
    if r17_total > 0:
        tasks.append({"type": "Fight", "params": {"stage": RULE["shards"]["stage"],
                                                  "times": r17_total,
                                                  "series": RULE.get("normal_series", 10)},
                      "name": "搓玉/填充"})
    for code, cnt in sorted(train_tasks.items(), key=lambda kv: -kv[1]):
        tasks.append({"type": "Fight", "params": {"stage": code, "times": cnt},
                      "name": "培养刷材料"})
    tasks += [
        {"type": "Recruit", "params": {"select": [3, 4, 5], "confirm": [3, 4, 5], "times": 4}},
        # 基建：2026-10-14 用户裁定改 **MAA 自定义换班**（mode=10000）——逐设施摆干员 + 菲亚梅塔置换。
        # ⚠ MAA 不看 plan 的 `period`，也不吃 plan_index=-1 → 显式传：14:00「每日日常」跑 A班(index 1)，
        #    02:00「凌晨基建换班」跑 B班(index 0)。见 docs/FINDINGS.md §24。
        {"type": "Infrast",
         "params": {"mode": RULE["infra_mode"], "filename": RULE["infra_custom_file"],
                    "plan_index": RULE["infra_plan_day"], "facility": RULE["infra_facilities"]},
         "name": "基建·自定义换班（A班）"},
        {"type": "Mall", "params": {"enable": True}},
        {"type": "Award", "params": {"enable": True}},
    ]
    return tasks


def _build_windows(ev_stage, ev_win, ev) -> dict:
    """窗口表：剿灭不限 + 农场关 + EX/S 首通（不登记窗口会被 plan_util 当成「全周可排」）。"""
    win_map = {"Annihilation": {}}
    if ev_stage:
        win_map[ev_stage] = ev_win
    if ev:
        _combat_end = str(ev.get("combat_end") or ev.get("end"))[:10]
        for _key, _listkey in (("ex_open", "ex_stages"), ("s_open", "s_stages")):
            _o = str(ev.get(_key) or "")[:10]
            if not _o:
                continue
            for _s in (ev.get(_listkey) or []):
                _c = _s.get("code")
                if _c:
                    win_map[_c] = {"open": _o, "close": _combat_end}
    return win_map


def _fit_to_schedule(plan, *, ev_stage, ev_runs, ev_san, extra_tasks, train_tasks,
                     ann_runs, r17, fill_runs, ann_san, extra_san, train_spent, budget,
                     series17=1, series_ev=1, max_iters=2000):
    """排期自检回退 —— 让 plan 能被 plan_util.distribute_daily 完整装下（尽量无 unplaced）。

    **回退顺序**（用户 2026-10-12 裁定：1-7 让位于活动）：
      ① 先减「**填充用 1-7**」（`fill_runs`，按 series17 递减；**1-7 下限 `r17` 不动**）；
      ② 填充归 0 后再减**活动关次数**（`ev_runs`，按 series_ev 递减）；
      ③ 两者都不动了还有 unplaced → 记 trace（容量确实不足：多半是 1-7下限+剿灭+EX 本身超容量）。
    旧行为「活动被压到 0、1-7 吃掉全部预算」已作废。

    返回 (plan, ev_runs, r17_total, fill_runs, trace)。
    """
    import plan_util  # 单向依赖：plan_util 不 import plan_week，无循环 import
    trace = []
    for _ in range(max_iters):
        r17_total = int(r17 + fill_runs)
        plan["tasks"] = _assemble_tasks(ann_runs, ev_stage, ev_runs, extra_tasks,
                                        r17_total, train_tasks)
        daily = plan_util.distribute_daily(plan)
        # 每个 day 里登记的是同一份 unplaced（见 plan_util），取第一份即可
        unplaced = dict((daily[0].get("unplaced") if daily else {}) or {})
        if not unplaced:
            break
        if fill_runs > 0:
            step = min(fill_runs, max(1, series17))
            trace.append("回退①填充 1-7 %d→%d 次（逐日装不下 %s）" % (fill_runs, fill_runs - step, unplaced))
            fill_runs -= step
            continue
        if ev_runs > 0:
            step = min(ev_runs, max(1, series_ev))
            trace.append("回退②活动 %s %d→%d 次（填充已为 0，逐日仍装不下 %s）"
                         % (ev_stage, ev_runs, ev_runs - step, unplaced))
            ev_runs -= step
            continue
        trace.append("填充=0、活动=0，仍有排不下 %s（容量确实不足：1-7下限+剿灭+EX 本身超容量）"
                     % unplaced)
        break
    return plan, ev_runs, int(r17 + fill_runs), fill_runs, trace


def plan(date: dt.date, start: dt.date | None = None) -> dict:
    """生成计划。

    `start` = 计划的**第一天**（默认 = 今天）→ 只排 `start..本周日`，即「**剩余 X 天**」，
    而非固定整周 7 天（2026-10-14 用户需求：按现状算本周剩余 X 天）。
    """
    mon, sun, wk = _week(date)
    plan_week_id = "%d-%s" % (mon.year, wk)
    # 「剩余 X 天」：默认从今天排到本周日；start 越界（早于周一/晚于周日）时夹紧到本周内
    start = start or date
    if start < mon:
        start = mon
    if start > sun:
        start = sun
    n_days = (sun - start).days + 1
    stock = read_shard_stock()
    med = read_meds()
    meds = med["sanity"]
    # 预算 = 自然(205/天 × 剩余天数) + 理智药（**整瓶 60 计**：余数本周用不掉）
    #   药存量已含周常药 → 不再另加 240（2026-10-12 用户裁定）；整瓶口径 2026-10-14 定。
    _bottle = int(RULE.get("medicine_bottle", 60))
    meds_usable = (meds // _bottle) * _bottle
    notes = ["计划窗口 %s ~ %s（**剩余 %d 天**，非固定 7 天）"
             % (start.isoformat(), sun.isoformat(), n_days),
             "预算 = 自然 %d/天 × %d 天 = %d + 理智药 %d（读数 %d，**整瓶 %d 可用 %d**，余 %d 留到下周）"
             " = %d（药读数 %s；**已含周常药，不加 240**）"
             % (RULE["natural_per_day"], n_days, RULE["natural_per_day"] * n_days,
                meds_usable, meds, _bottle, meds_usable, meds - meds_usable,
                RULE["natural_per_day"] * n_days + meds_usable, med["ts"] or "无")]
    budget = RULE["natural_per_day"] * n_days + meds_usable

    # --- R1 剿灭 ---
    a = RULE["annihilation"]
    ann_runs = math.ceil(a["weekly_jade_cap"] / a["jade_per_run"])
    # 按「本周已完成合成玉」扣减（state.json.progress.annihilation）→ 别重复刷、别超周上限白花理智
    #   （2026-10-14：剩余 X 天规划要「按现状」——已打的剿灭不再排）
    try:
        stj = json.loads((ROOT / "docs" / "state.json").read_text(encoding="utf-8"))
        pa = ((stj.get("progress") or {}).get("annihilation") or {})
        if str(pa.get("week") or "") == plan_week_id:
            _done_jade = int(pa.get("jade") or 0)
            _cap = int(pa.get("cap") or a["weekly_jade_cap"])
            if pa.get("done") or _done_jade >= _cap:
                ann_runs = 0
                notes.append("本周剿灭已打满（%s %s/%s）→ 不再排剿灭"
                             % (pa.get("week"), _done_jade, _cap))
            elif _done_jade > 0:
                _max_runs = math.ceil(a["weekly_jade_cap"] / a["jade_per_run"])
                ann_runs = min(ann_runs, max(0, math.ceil((_cap - _done_jade) / a["jade_per_run"])))
                notes.append("本周剿灭已 %s/%s（%s）→ 按现状只排 %d 次（满额 %d 次）"
                             % (_done_jade, _cap, pa.get("week"), ann_runs, _max_runs))
    except Exception:  # noqa: BLE001
        pass
    ann_san = ann_runs * a["sanity"]

    # （R2 固源岩下限移到 R2.5 之后算 —— 因为 target 取决于「本期是否有活动要打」）
    sh = RULE["shards"]

    ev = pick_event(read_events(), mon, sun)
    ev_stage, ev_san, ev_runs, ev_win = None, 0, 0, {}
    shop_credit = {}          # 活动商店能白拿的材料 → 抵扣培养需求

    # --- R2.5 EX / S 首通链（读进度：**只排未通、从第一个未通起的解锁链**；先占预算）---
    #   依赖语义（2026-10-12 用户补充）：EX-i **未通就不能打 EX-(i+1)**（依次解锁）；
    #   所以只排「未通」的关、按解锁顺序（EX-1→EX-8 / S-1）排成链，且**链是前缀式的**：
    #   从第一个未通关开始，其后各关都在链内（已通的关跳过、不重复排首通）。
    #   突袭依赖「该关普通已通」：普通已通(或在本链中先通)的关才排突袭，且**紧跟其普通之后**、
    #   按关顺序（用 seq 保证「按序、跨天单调不减」，执行时遇挫即停由 event-copilot 负责）。
    prog = read_event_progress(ev.get("event_id")) if ev else {"normal_done": set(), "raid_done": set(),
                                                               "missing": True}
    normal_done, raid_done = prog["normal_done"], prog["raid_done"]
    extra_tasks, extra_san, extra_san_normal, extra_san_raid = [], 0, 0, 0
    seq = 0
    if ev:
        if prog["missing"]:
            notes.append("⚠ 未读到活动进度（state.json.progress.%s 缺 first_clear_done/ex_clear_done/"
                         "s_clear_done）→ **当全未通**（宁可多排一次首通，也别漏排导致后面解锁不了）"
                         % ev.get("event_id"))
        _combat_end = str(ev.get("combat_end") or ev.get("end") or "")[:10]
        for key, listkey, label in (("ex_open", "ex_stages", "EX"), ("s_open", "s_stages", "S")):
            d0 = str(ev.get(key) or "")[:10]
            if not d0:
                continue
            try:
                dd = dt.date.fromisoformat(d0)
            except Exception:  # noqa: BLE001
                continue
            _stages = ev.get(listkey) or []
            _codes = [s["code"] for s in _stages]
            _san_by = {s["code"]: int(s.get("sanity") or 0) for s in _stages}
            _has_raid = label in RULE["raid"]["only"]
            # 本关「可排进本周」= 开放日 ≤ 本周末 且 作战截止 ≥ 本周一（含「上周已开放、仍未通」）
            _in_week = (dd <= sun) and (not _combat_end or _combat_end >= mon.isoformat())
            if not _in_week:
                notes.append("%s 关 %s 开放（不在本周，或本周前已结束），本周不排（已通 %d/%d，突袭 %d）"
                             % (label, d0, sum(1 for c in _codes if c in normal_done), len(_codes),
                                sum(1 for c in _codes if c in raid_done)))
                continue
            # 解锁链 = 从「第一个未通」起到末尾（前缀式；已通的前缀跳过）
            first_un = next((i for i, c in enumerate(_codes) if c not in normal_done), None)
            chain = _codes[first_un:] if first_un is not None else []
            _n_norm = _n_raid = 0
            for c in _codes:
                _cleared = c in normal_done
                _scheduled = c in chain            # 未通但落在本周链内 → 本周会通
                if not _cleared and not _scheduled:
                    continue                       # 普通既没通也不在本周链内 → 该关不可达（锁着）
                san = _san_by.get(c, 0)
                if not _cleared:                   # 已通的不再排首通
                    seq += 1
                    extra_tasks.append({"kind": "fight", "stage": c, "times": 1,
                                        "sanity": san, "seq": seq, "name": "%s 首通" % c})
                    extra_san += san; extra_san_normal += san; _n_norm += 1
                if _has_raid and c not in raid_done:   # 突袭依赖「该关普通已通」→ 排在其后
                    seq += 1
                    extra_tasks.append({"kind": "raid", "stage": c, "times": 1,
                                        "sanity": san, "seq": seq, "name": "%s 突袭" % c})
                    extra_san += san; extra_san_raid += san; _n_raid += 1
            if chain:
                notes.append("★ %s 首通链：已通 %d/%d 关，本周排 %s..%s（共 %d 关普通%s）"
                             "—— 依次解锁，前面未通则后面排不了"
                             % (label, sum(1 for c in _codes if c in normal_done), len(_codes),
                                chain[0], chain[-1], len(chain),
                                ("；另排突袭 %d 关（按关顺序、紧跟其普通；理智按普通计，口径待核）" % _n_raid)
                                if _has_raid else ""))
            else:
                notes.append("%s 首通链：%d 关普通**全部已通**，本周不排首通（未通突袭 %d 关照排）"
                             % (label, len(_codes), _n_raid))

    # --- R2 固源岩下限（**条件 target**：有活动要打 → 500；无 → 1000）---
    #   「有活动要打」= 选中活动 且（首通/突袭链非空 或 商店还要买）。在 R2.5 + 商店需求之后才判。
    ev_stage, ev_san, ev_win, need_tok, cap_runs, tok_per_run = None, 0, {}, 0, 10 ** 9, 1
    if ev:
        _st = ev.get("farm")
        _stages = {s.get("code"): s for s in ev.get("stages", [])}
        if _st not in _stages:                    # 没指定就取理智最高的关（产料最多）
            _st = max(_stages, key=lambda k: _stages[k].get("sanity") or 0, default=None)
        if _st:
            ev_stage = _st
            ev_san = int(_stages[_st].get("sanity") or 0)
            ev_win = {"open": str(ev.get("start"))[:10],
                      "close": str(ev.get("combat_end") or ev.get("end"))[:10]}
            shop = ev.get("shop") or []

            def _qty(it):   # 限购项目标代币：remaining 优先，否则 limit；skip 项不计
                _r = it.get("remaining")
                return int(_r) if _r is not None else int(it.get("limit") or 0)
            need_tok = sum((it.get("price") or 0) * _qty(it)
                           for it in shop if (it.get("limit") or 0) > 0 and not it.get("skip"))
            tok_per_run = int(_stages[_st].get("token_per_run") or 0) or 1
            cap_runs = math.ceil(need_tok / tok_per_run) if need_tok else 10 ** 9
            # 商店能换的材料 → 抵扣培养需求
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

    has_activity_work = bool(ev) and (bool(extra_tasks) or need_tok > 0)
    # 连战上限**运行时判定**（资源有 FightSeries-OldMethodFlag → 6；无 → 10），不写死
    _cap = _series_cap()
    _series17 = min(int(RULE["normal_series"]), _cap)
    _series_ev = min(int(RULE.get("event_series", 10)), _cap)
    notes.append("本机连战上限 = %d（判据：resource %s `FightSeries-OldMethodFlag` → %s列表；"
                 "期望 series 普通 %d / 活动 %d 取 min 后 = %d / %d）"
                 % (_cap, "有" if _cap == 6 else "无", "旧" if _cap == 6 else "新",
                    int(RULE["normal_series"]), int(RULE.get("event_series", 10)),
                    _series17, _series_ev))
    if stock is None:
        r17, target = 0, int(sh["target_idle"])
        notes.append("未读到固源岩库存（DepotData 缺失）→ 1-7 暂按填充处理")
    else:
        target = int(sh["target_activity"] if has_activity_work else sh["target_idle"])
        _need = target + sh["daily_use"] * 7 - stock
        _raw17 = max(0, math.ceil(_need / sh["per_run"]))
        r17 = int(math.ceil(_raw17 / _series17) * _series17)   # 下限**向上**对齐 series（保库存下限）
        notes.append("固源岩 %d → 期末需 ≥%d（%s）→ 1-7 下限 %d 次（原始 %d 向上对齐 series=%d；"
                     "周耗 %.0f，单次产 %.3f）"
                     % (stock, target, "有活动要打→target=500" if has_activity_work else "无活动→target=1000",
                        r17, _raw17, _series17, sh["daily_use"] * 7, sh["per_run"]))
    san17 = r17 * 6

    # --- R3 活动：**在 ann + EX/S首通 + 1-7下限 之后**吃剩余预算（活动期 1-7 让位）---
    ev_runs = 0
    if ev_stage:
        left = budget - ann_san - extra_san - san17
        _raw_ev = max(0, min(left // ev_san, cap_runs)) if ev_san else 0
        ev_runs = (_raw_ev // _series_ev) * _series_ev       # 向下对齐 series
        notes.append("活动 %s：开放 %s~%s，每局 %d 理智；商店要买 %d 代币 → 需 %d 次；"
                     "预算剩 %d → 活动排 %d 次（原始 %d 向下对齐 series=%d）"
                     % (ev_stage, ev_win["open"], ev_win["close"], ev_san, need_tok, cap_runs,
                        max(0, left), ev_runs, _raw_ev, _series_ev))
    if not ev:
        notes.append("本期无进行中的活动 → 预算全给 1-7")


    # --- R3.5 培养：按缺口"刷材料"关卡分配，产出额外 Fight 任务 ---
    # 培养预算 = 「**活动没吃完的剩余**」。RULE 顺序是 R3 活动 → R3.5 培养 → R4 1-7填充：
    #   活动先吃剩余（受商店 cap_runs 限制），活动吃不完的才轮到培养；培养吃完剩下的给 1-7 填充。
    #   ⚠ 修（2026-10-14）：此前 `train_budget` 从未定义 —— 潜在 `NameError`，被下面的 except 吞成
    #   「培养估值失败」→ 培养**恒为 0**（当前场景 rows 恰为空才没炸）。现按 RULE 顺序显式给值。
    train_budget = max(0, budget - ann_san - extra_san - san17 - ev_runs * ev_san)
    train_tasks, train_spent, train_info = {}, 0, None
    try:
        sys.path.insert(0, str(TOOLS))
        import oper_cost as oc
        train_info = oc.compute(targets=RULE.get("train_targets"), credit=shop_credit)
        if shop_credit:
            notes.append("活动商店可白拿 %d 种材料（已从培养需求里抵扣）"
                         % len(train_info.get("credited") or {}))
        val = train_info["val"]
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

    # --- 组装 plan（tasks 先留空，交由 _fit_to_schedule 填 + 自检）---
    plan = {
        "week": "%d-%s" % (mon.year, wk),
        # range = 剩余天数窗口（start..本周日），不是整周 —— daily/write/run 都按它走
        "range": "%s..%s" % (start.isoformat(), sun.isoformat()),
        "generated_at": dt.datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "by": "plan_week.py",
        # 当期活动 id（供 maa_week 拼 event-copilot 命令；EX/S 首通链走 event-copilot 跑）
        "event": (ev.get("event_id") if ev else None),
        "budget": {"sanity_natural": RULE["natural_per_day"] * n_days,
                   "n_days": n_days,
                   # weekly_potion 恒 0（已废弃）：药存量已含周常药，不再另加（2026-10-12 裁定）
                   "weekly_potion": 0,
                   "meds_available": meds,
                   "meds_usable": meds_usable,     # 整瓶 60 可用量（budget_total 用这个）
                   "meds_week": med["week"],
                   "meds_source": "scheduling/data/sanity.json（每周日手动跑 sanity_potion.py）",
                   "daily_natural": RULE["natural_per_day"]},
        "inventory": {"固源岩": stock},
        "shards": {"stock": stock, "target": target,
                   "target_activity": sh["target_activity"], "target_idle": sh["target_idle"],
                   "target_reason": ("有活动要打 → 500" if has_activity_work else "无活动 → 1000"),
                   "per_run": sh["per_run"], "daily_use": sh["daily_use"], "stage": sh["stage"]},
        # 「配上药的关」= 允许吃理智药的关（1-7 / 活动农场关）。剿灭/EX 首通不配药。
        "medicine_stages": [x for x in (sh["stage"], ev_stage) if x],
        "series": {"normal": _series17, "event": _series_ev, "cap": _cap,
                   "cap_reason": ("有 FightSeries-OldMethodFlag → 旧列表 6" if _cap == 6
                                  else "无 FightSeries-OldMethodFlag → 新列表 10")},
        "windows": _build_windows(ev_stage, ev_win, ev),
        "tasks": [],
        # side = 「run 时要额外交给本机脚本的活」。**基建已交还 MAA 自带的队列轮换**（见 tasks 里的 Infrast），
        # 所以这里为空；保留该字段是为了以后还有别的附带脚本时不用改 schema。
        "side": [],
    }

    # --- R4 1-7 填充（剩余预算，向下对齐 series）→ 排期自检回退 ---
    #   used 必须含 EX/S 首通（extra_san）与活动（ev_runs*ev_san），否则 filler 会超预算。
    _used0 = ann_san + extra_san + san17 + ev_runs * ev_san + train_spent
    fill_runs = max(0, (budget - _used0) // 6)
    fill_runs = (fill_runs // _series17) * _series17
    plan, ev_runs, r17_total, fill_runs, _fit_trace = _fit_to_schedule(
        plan, ev_stage=ev_stage, ev_runs=ev_runs, ev_san=ev_san, extra_tasks=extra_tasks,
        train_tasks=train_tasks, ann_runs=ann_runs, r17=r17, fill_runs=fill_runs,
        ann_san=ann_san, extra_san=extra_san, train_spent=train_spent, budget=budget,
        series17=_series17, series_ev=_series_ev)
    used = ann_san + extra_san + r17_total * 6 + ev_runs * ev_san + train_spent
    notes.append("预算 %d；剿灭 %d + EX/S首通 %d + EX/S突袭 %d + 1-7 %d(下限 %d+填充 %d) + 活动 %d + 培养 %d = %d"
                 % (budget, ann_san, extra_san_normal, extra_san_raid, r17_total * 6, r17, fill_runs,
                    ev_runs * ev_san, round(train_spent), round(used)))
    for _t in _fit_trace:
        notes.append("★ 排期自检：" + _t)
    # 自检回归后的「实排」口径 —— 与最终 tasks / sanity_alloc 对齐（此时 ev_runs / r17_total 已定稿）
    if ev_stage:
        notes.append("活动 %s：本周实排 %d 次（每局 %d 理智，共 %d 理智）"
                     % (ev_stage, ev_runs, ev_san, ev_runs * ev_san))
    notes.append("1-7：本周实排 %d 次（下限 %d + 填充 %d），共 %d 理智"
                 % (r17_total, r17, fill_runs, r17_total * 6))
    plan["rationale"] = {"notes": notes,
                         "sanity_alloc": {"annihilation": ann_san, "EX/S首通": extra_san_normal,
                                          "EX/S突袭": extra_san_raid,
                                          "1-7": r17_total * 6,
                                          "活动": ev_runs * ev_san, "培养": train_spent}}
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
            # 缺口按合成关系**递归降级**后的材料（缺的兑成下一级；中间材料已用库存抵扣）
            "resolved": train_info.get("resolved") or [],
            "downgrades": train_info.get("downgrades") or [],
            "craft_gold": train_info.get("craft_gold") or 0,
        }
    # --- 逐日视图：队列**按天编辑**用（maa_week write/run 都读这里，别再各自重算）---
    # 结构：[{date, dow, runs:{stage:次数}, sanity, cap, day_cap, opens, over, unplaced}, ...]
    try:
        import plan_util
        plan["daily"] = plan_util.distribute_daily(plan)
    except Exception as e:  # noqa: BLE001
        plan["daily"] = []
        notes.append("逐日分配失败：%r" % e)
    return plan


def main():
    ap = argparse.ArgumentParser(description="周规划器（规则写死；支持「剩余 X 天」）")
    ap.add_argument("--date", default="", help="以哪天为准算所属周（默认今天）")
    ap.add_argument("--from", dest="start", default="",
                    help="计划第一天（默认=今天）→ 只排 start..本周日，即剩余 X 天")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    d = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    s = dt.date.fromisoformat(args.start) if args.start else None
    p = plan(d, start=s)
    print(json.dumps(p, ensure_ascii=False, indent=2))
    if not args.dry:
        pathlib.Path(args.out).write_text(json.dumps(p, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        print("\n[plan] 已写 %s" % args.out)


if __name__ == "__main__":
    main()
