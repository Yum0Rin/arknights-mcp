#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一图流导出的 MAA 排班 JSON 转成 MAA `resource/custom_infrast` 格式并落盘。

用法：
  python convert_to_maa.py <一图流MAA json> <输出json>
  # 可选：改写各方案的「换班时间窗口」（不给就原样透传源文件的 period）
  python convert_to_maa.py <src> <dst> --periods "B班=02:00-04:00,A班=14:00-16:00"

落盘前会把关（`plan_fatals`）：**致命项直接拒绝写出**（退出码 2），见下面的常量与函数注释。
判据与 yuMAArin GUI「保存」**共用同一份**（GUI 直接 import 本模块的 `plan_fatals`）。

为什么要转（一图流 `-MAA.json` 不是直接能用吗）：
  · 一图流导出的 plans **没有 `index` 字段** → MAA GUI 读 `CustomInfrastConfig.Plan.Index` 时
    每份方案都是 0，方案下拉里选哪个都等于选 plan 0（`InfrastSettingsUserControlModel.RefreshCustomInfrastPlanList`
    用 `Index` 当 `Value`）。这里补上 `index = 0..n-1`。
  · 顺带把 `period`（GUI「按换班时间自动选」要用）、`duration`、`scheduleType`、`description_post`
    **透传**（MaaCore 不读这几个键，但 GUI 会读 `period`）。
  · 注意：**`plan_index` 换班时由调用方显式传**（`maa_week.INFRAST_PLAN_DAY/NIGHT`），MAA 不看 `period`
    自动挑方案；`period` 只是给 GUI 显示/自动模式用的。
"""
from __future__ import annotations

import argparse
import json
import time

# ---------------------------------------------------------------- 方案表「致命项」判据（**唯一一份**）
# 下面这些既是**转换器落盘前**的把关，也是 yuMAArin GUI「保存」前的把关
# （`skland_gui.py` 直接 import 这里的 `plan_fatals`，避免两处判据漂移）。
# 「致命」= 会让 MAA 跑废整队 / 方案结构性无效 / 静默失效。

# MaaCore `InfrastTask.cpp:330-337` 认得的产物名。不在白名单 → 该房间**照常换人，但不校验、不切换产物**
# （只留一行 warning，极易漏 —— 那就是「看着跑了却没换对」那类坑）。
MAA_INFRA_PRODUCTS = {"Battle Record", "Pure Gold", "Dualchip", "Originium Shard", "LMD", "Orundum"}

# 「关键设施」= 除宿舍以外的功能设施（宿舍本来就常走 autofill，空着不算错）
INFRA_KEY_FACILITIES = ("manufacture", "trading", "power", "control", "meeting", "hire")

# 我们的自动化固定用这两个班次下标（14:00「每日日常」→1＝A班、02:00「凌晨基建换班」→0＝B班），
# 与 `scripts/maa-week/maa_week.py` 的 `INFRAST_PLAN_DAY / INFRAST_PLAN_NIGHT` 同口径。
# ⇒ 方案表必须 ≥ 2 份，否则 `plan_index=1` 越界 → MaaCore `set_params` false → `append 0` **打死整队**。
INFRA_REQUIRED_PLANS = 2


def plan_fatals(cfg, room_cn=None, owned=None):
    """方案表的**致命项**列表（空列表 = 可以落盘）。

    :param cfg: 排班表 dict
    :param room_cn: {英文房间键: 中文名}，只影响提示文案；不传就用英文键
    :param owned: 已拥有的干员名集合；**不传就跳过「干员持有性」这条**（转换器没有账号数据）
    """
    out = []
    plans = (cfg or {}).get("plans") or []
    name = lambda k: (room_cn or {}).get(k, k)          # noqa: E731

    if len(plans) < INFRA_REQUIRED_PLANS:
        out.append(
            f"只有 {len(plans)} 份方案 —— 我们的自动化固定用 plan_index=0/1（14:00→1、02:00→0），"
            f"越界会让 MaaCore `set_params` false、`append 0` **打死整队**（14:00 那次用的是 1）。"
            f"至少要 {INFRA_REQUIRED_PLANS} 份。")

    bad_prods, empty_plans = [], []
    for i, p in enumerate(plans):
        p = p or {}
        rooms = p.get("rooms") or {}
        for fac, arr in rooms.items():
            for j, r in enumerate(arr or []):
                prod = (r or {}).get("product")
                if prod and prod not in MAA_INFRA_PRODUCTS:
                    bad_prods.append(f"plans[{i}] {name(fac)}#{j} 写的是 `{prod}`")
        n_key = sum(len([o for o in (r.get("operators") or []) if o])
                    for k in INFRA_KEY_FACILITIES for r in (rooms.get(k) or []))
        if n_key == 0:
            empty_plans.append(f"plans[{i}]「{p.get('name', '?')}」")

    if bad_prods:
        out.append("产物名不在 MaaCore 白名单（" + "；".join(bad_prods) + "）→ 该房间会**照常换人但不切换产物**，"
                   "静默失效（继续产原来的东西，正是「看着跑了却没换对」那类坑）。"
                   f"合法值只有：{' / '.join(sorted(MAA_INFRA_PRODUCTS))}。")
    if empty_plans:
        out.append("、".join(empty_plans) + " 在关键设施（制造/贸易/发电/控制中枢/会客室/办公室）里"
                   "**一个人都没写** → 这一班什么也摆不出来（等于没换班）。")

    if owned is not None:
        miss = {}      # 干员名 → 出现的房间
        for i, p in enumerate(plans):
            p = p or {}
            for fac, arr in (p.get("rooms") or {}).items():
                for r in (arr or []):
                    for op in [o for o in (r.get("operators") or []) if o]:
                        if op not in owned:
                            miss.setdefault(op, []).append(f"plans[{i}] {name(fac)}")
            fia = p.get("Fiammetta") or {}
            if fia.get("enable") and fia.get("target") and fia["target"] not in owned:
                miss.setdefault(fia["target"], []).append(f"plans[{i}] 菲亚梅塔目标")
        if miss:
            names = list(miss)
            shown = "；".join(f"{op}（{'、'.join(sorted(set(miss[op])))[:36]}）" for op in names[:8])
            more = f" …（共 {len(miss)} 名）" if len(names) > 8 else ""
            out.append(f"有 {len(miss)} 名干员未持有：{shown}{more} → MAA 摆不上，对应设施会"
                       "**换不齐 / 继续用旧人**（等于没换成）。")
    return out


def parse_periods(spec: str) -> dict:
    """'B班=02:00-04:00,A班=14:00-16:00' → {'B班': [['02:00','04:00']], ...}"""
    out = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, win = part.partition("=")
        a, sep2, b = win.partition("-")
        if not (sep and sep2 and name.strip() and a.strip() and b.strip()):
            raise SystemExit("--periods 格式应为 '方案名=HH:MM-HH:MM,...'，收到：%r" % part)
        out[name.strip()] = [[a.strip(), b.strip()]]
    return out


def convert(src, dst, periods=None):
    d = json.load(open(src, encoding="utf-8"))
    out = {
        "author": "arknights-mcp",
        "description": "由一图流生成、arknights-mcp 转换（勿手改，重生成覆盖）",
        "id": int(time.time() * 1000),
        "title": d.get("title", "排班表"),
        "planTimes": d.get("planTimes", "2班"),
    }
    if "scheduleType" in d:
        out["scheduleType"] = d["scheduleType"]

    out["plans"] = []
    for i, pl in enumerate(d.get("plans", [])):
        rooms = {}
        for fac, arr in (pl.get("rooms") or {}).items():
            items = []
            for r in arr:
                it = {
                    "skip": False,
                    "operators": r.get("operators", []),
                    "sort": bool(r.get("sort", False)),
                    "autofill": bool(r.get("autofill", False)),
                }
                if "product" in r:
                    it["product"] = r["product"]
                items.append(it)
            rooms[fac] = items

        dr = pl.get("drones", {}) or {}
        plan = {
            "index": i,                       # ← 新增：GUI 方案下拉靠它区分（源文件没有）
            "name": pl.get("name", ""),
            "description": pl.get("description", ""),
            "Fiammetta": pl.get("Fiammetta", {"enable": False, "target": "", "order": "pre"}),
            "drones": {
                "room": dr.get("room", "trading"),
                "index": dr.get("index", 1),
                "enable": bool(dr.get("enable", False)),
                "order": dr.get("order", "pre"),
            },
            "rooms": rooms,
        }
        if "description_post" in pl:
            plan["description_post"] = pl["description_post"]
        if "duration" in pl:
            plan["duration"] = pl["duration"]
        period = pl.get("period")
        if periods is not None and plan["name"] in periods:
            period = periods[plan["name"]]     # ← --periods 指定时改写成我们的换班窗口
        if period:
            plan["period"] = period

        out["plans"].append(plan)

    # **致命项 → 拒绝写出**（与 yuMAArin GUI「保存」同一份判据：让 MAA 跑废整队 / 结构性无效 / 静默失效的，
    # 一律不落盘。这里不给 `owned`（转换器没有账号数据）→ 自动跳过「干员持有性」那条。）
    fatals = plan_fatals(out)
    for w in fatals:
        print("!! 致命：" + w)
    if fatals:
        raise SystemExit("拒绝写出 %s —— 先把上面 %d 条致命项改掉（源文件多半就有问题）。" % (dst, len(fatals)))

    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("wrote", dst, "plans=", len(out["plans"]))
    for p in out["plans"]:
        print("   plan[%s] %-6s period=%s" % (p["index"], p["name"], json.dumps(p.get("period"), ensure_ascii=False)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="一图流 MAA 排班 → MAA custom_infrast 格式")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--periods", default=None,
                    help="改写换班时间窗口，如 'B班=02:00-04:00,A班=14:00-16:00'；不给则透传源文件 period")
    a = ap.parse_args()
    convert(a.src, a.dst, parse_periods(a.periods) if a.periods else None)
