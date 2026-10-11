#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干员培养材料账 —— 官方表算「需求」，对比 MAA 仓库算「缺口」。

数据：
  · 需求：`scheduling/data/gamedata/character_table.json`（官方）
      phases[].evolveCost          精英化材料
      allSkillLvlup[].lvlUpCost    技能 1→7
      skills[].levelUpCostCond[].levelUpCost   专精 M1/M2/M3
  · 名称：MAA `resource/item_index.json`
  · 库存：MAA `data/DepotData.json`（itemId→数量）

标准（用户定）：
  6★ → 精二 60 级 + 技能 7 + 常用技能专三
  5★ → 精二 50 级 + 技能 7 + 常用技能专三
  基建 → 精二 1 级（技能无要求）

用法：
  python scheduling/tools/oper_cost.py --name 乌尔比安
  python scheduling/tools/oper_cost.py --name 乌尔比安 --skill 2 --no-mastery
  python scheduling/tools/oper_cost.py --all          # 对 state.json 里的 4 个目标一起算
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOLS = pathlib.Path(__file__).resolve().parent
GD = ROOT / "scheduling" / "data" / "gamedata" / "character_table.json"
ITEM_INDEX = pathlib.Path(r"C:\MAA\resource\item_index.json")
DEPOT = pathlib.Path(r"C:\MAA\data\DepotData.json")
DEFAULT_TARGETS = ["德克萨斯", "乌尔比安", "伊芙利特", "山"]
# 精二目标等级（用于标注；等级经验/龙门币不在官方表，见 docs/PLAN-培养与规划逻辑.md §1）
STD_LEVEL = {"TIER_5": 80, "TIER_6": 60, "TIER_4": 50}
# 精英化龙门币（官方 character_table 不含；按星级常量，(E0→E1, E1→E2)）
ELITE_LMD = {"TIER_6": (30000, 180000), "TIER_5": (20000, 120000),
             "TIER_4": (15000, 60000), "TIER_3": (10000, 0)}


def load():
    chars = json.loads(GD.read_text(encoding="utf-8"))
    idx = json.loads(ITEM_INDEX.read_text(encoding="utf-8"))
    try:
        depot = (json.loads(DEPOT.read_text(encoding="utf-8")).get("data") or {})
    except Exception:  # noqa: BLE001
        depot = {}
    return chars, idx, depot


def by_name(chars: dict, name: str):
    for v in chars.values():
        if v.get("name") == name:
            return v
    return None


def need_materials(ch: dict, std: str, mastery_skill: int = 1, mastery: bool = True) -> Counter:
    """按标准累计材料：{itemId: 数量}。"""
    c = Counter()
    phases = ch.get("phases") or []
    want_phase = 2 if std in ("6star", "5star", "base") else 1
    for ph in phases[1:want_phase + 1]:              # E0->E1, E1->E2
        for it in ph.get("evolveCost") or []:
            c[it["id"]] += it["count"]
    if std in ("6star", "5star"):                     # 战斗向：技能 7 + 专三
        for lv in ch.get("allSkillLvlup") or []:
            for it in lv.get("lvlUpCost") or []:
                c[it["id"]] += it["count"]
        if mastery:
            sk = ch.get("skills") or []
            if sk:
                idx = min(max(mastery_skill - 1, 0), len(sk) - 1)
                for cond in sk[idx].get("levelUpCostCond") or []:
                    for it in cond.get("levelUpCost") or []:
                        c[it["id"]] += it["count"]
    return c


def report(name: str, chars, idx, depot, std: str | None = None, **kw):
    ch = by_name(chars, name)
    if not ch:
        print("  %s：表里没找到" % name)
        return None
    rar = ch.get("rarity")
    std = std or ("6star" if rar == "TIER_6" else "5star" if rar == "TIER_5" else "base")
    need = need_materials(ch, std, **kw)
    lines, gap_total, short = [], 0, []
    for iid, cnt in sorted(need.items(), key=lambda x: -x[1]):
        have = int(depot.get(iid) or 0)
        gap = max(0, cnt - have)
        nm = (idx.get(iid) or {}).get("name", iid)
        flag = "缺 %d" % gap if gap else "够"
        if gap:
            short.append((nm, gap))
        lines.append("    %-14s 需 %4d  有 %5d  → %s" % (nm, cnt, have, flag))
    print("  【%s】%s  精二目标 Lv%d" % (name, rar, STD_LEVEL.get(rar, "?")))
    print("\n".join(lines))
    return {"name": name, "rarity": rar, "std": std,
            "need": dict(need), "short": [{"name": n, "gap": g} for n, g in short]}


def compute(targets=None, skill=1, mastery=True, credit=None):
    """对一组目标算：材料理智 / 精英化龙门币 / 合计；含"先用库存+能合就合"。

    credit: {itemId: 数量} —— 别处已经能白拿的材料（如**活动商店**换的），先从需求里扣掉。
    """
    chars, idx, depot = load()
    targets = targets or DEFAULT_TARGETS
    needs, lmd, detail = Counter(), 0, []
    for n in targets:
        ch = by_name(chars, n)
        if not ch:
            continue
        rar = ch.get("rarity")
        std = "6star" if rar == "TIER_6" else "5star" if rar == "TIER_5" else "base"
        needs.update(need_materials(ch, std, mastery_skill=skill, mastery=mastery))
        lmd += sum(ELITE_LMD.get(rar, (0, 0))[:2])
        detail.append({"name": n, "rarity": rar, "std": std})
    credited = {}
    for iid, c in (credit or {}).items():
        take = min(needs.get(iid, 0), c)
        if take:
            needs[iid] -= take
            credited[iid] = take
            if needs[iid] <= 0:
                del needs[iid]
    sys.path.insert(0, str(TOOLS))
    from material_cost import Valuation, plan_needs
    val = Valuation()
    total, rows = plan_needs(val, dict(needs), dict(depot))
    lmd_san = lmd * val.lmd_unit()
    return {"targets": detail, "material_sanity": round(total, 1), "elite_lmd": lmd,
            "lmd_sanity": round(lmd_san, 1), "total_sanity": round(total + lmd_san, 1),
            "rows": rows, "val": val, "credited": credited}


def main():
    ap = argparse.ArgumentParser(description="干员培养材料账（官方表 → 仓库缺口 → 理智）")
    ap.add_argument("--name", default="")
    ap.add_argument("--all", action="store_true", help="对默认 4 个目标一起算")
    ap.add_argument("--skill", type=int, default=1, help="常用技能序号（1/2/3）")
    ap.add_argument("--no-mastery", action="store_true", help="不算专精")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    chars, idx, depot = load()
    names = DEFAULT_TARGETS if (args.all or not args.name) else [args.name]

    needs = Counter()          # 多目标合并的需求
    detail = []
    for n in names:
        ch = by_name(chars, n)
        if not ch:
            print("  %s：表里没找到" % n)
            continue
        rar = ch.get("rarity")
        std = "6star" if rar == "TIER_6" else "5star" if rar == "TIER_5" else "base"
        m = need_materials(ch, std, mastery_skill=args.skill, mastery=not args.no_mastery)
        needs.update(m)
        detail.append((n, rar, std, m))
        print("  【%s】%s 精二目标 Lv%s" % (n, rar, STD_LEVEL.get(rar, "?") if rar in ("TIER_5", "TIER_6") else "1"))

    # 材料理智（库存感知：先用库存 + 能合就合）
    try:
        sys.path.insert(0, str(TOOLS))
        from material_cost import Valuation, plan_needs
        val = Valuation()
        total, rows = plan_needs(val, dict(needs), dict(depot))
        print("\n=== 材料账（%d 项，含 先用库存/能合就合 ）===" % len(rows))
        for r in sorted(rows, key=lambda x: -(x.get("sanity") or 0))[:20]:
            if r.get("sanity") is None:
                print("  %-14s 需%4d  ⚠ %s" % (r["name"], r["qty"], r["note"]))
            else:
                d = r.get("det", {})
                print("  %-14s 需%4d  库存抵%3d  刷%3d  合%2d批  → %6.1f 理智"
                      % (r["name"], r["qty"], d.get("stock", 0), d.get("farm", 0),
                         d.get("craft", 0), r["sanity"]))
        # 精英化龙门币（官方表没有，按星级常量补）
        lmd = sum(sum(ELITE_LMD.get(rar, (0, 0))[:2 if std != "base" else 1])
                  for _, rar, std, _ in detail)
        lmd_san = lmd * val.lmd_unit()
        print("\n=== 汇总 ===")
        print("  材料理智         %8.1f" % total)
        print("  精英化龙门币     %8d LMD  → %.1f 理智" % (lmd, lmd_san))
        print("  合计（不含升级经验/龙门币）≈ %.0f 理智" % (total + lmd_san))
        days = (total + lmd_san) / 240
        print("  按自然 240/天      ≈ %.1f 天（用药更快）" % days)
        if args.json:
            pathlib.Path(args.json).write_text(json.dumps(
                {"targets": [{"name": n, "rarity": r} for n, r, _, _ in detail],
                 "material_sanity": round(total, 1), "elite_lmd": lmd,
                 "total_sanity": round(total + lmd_san, 1), "rows": rows},
                ensure_ascii=False, indent=2), encoding="utf-8")
            print("[oper_cost] 已写", args.json)
    except Exception as e:  # noqa: BLE001
        print("\n[oper_cost] 估值模块失败：%r" % e)


if __name__ == "__main__":
    main()

