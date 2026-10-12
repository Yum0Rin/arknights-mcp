#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干员培养材料账 —— 官方表算「需求」、比仓库算「缺口」，按「当前练度」只算剩余段。

数据源（官方静态表 + 本人账号）：
  · 需求        scheduling/data/gamedata/character_table.json
      phases[].evolveCost                         精英化材料
      allSkillLvlup[].lvlUpCost                   技能 1→7
      skills[].levelUpCostCond[].levelUpCost       专精 M1/M2/M3
  · 升级/精英化  scheduling/data/gamedata/gamedata_const.json（官方）
      characterExpMap / characterUpgradeCostMap   （按精英阶段 3 组）
      evolveGoldCost / maxLevel                   （按星级）
  · 名称        C:\\MAA\\resource\\item_index.json
  · 库存        C:\\MAA\\data\\DepotData.json
  · 当前练度    森空岛（--from-skland，含 skill_lvl/spec）或 --box 或显式参数

标准（用户定）：
  6★ → 精二 60 级 + 技能 7 + 常用技能专三
  5★ → 精二 50 级 + 技能 7 + 常用技能专三
  ≤4★ → 精二 1 级（不练技能）

用法：
  python scheduling/tools/oper_cost.py --name 乌尔比安 --from-skland
  python scheduling/tools/oper_cost.py --name 乌尔比安 --elite 1 --level 1 --skill-lvl 7 --spec 0,0,0
  python scheduling/tools/oper_cost.py --all --from-skland
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
CONST = ROOT / "scheduling" / "data" / "gamedata" / "gamedata_const.json"
ITEM_INDEX = pathlib.Path(r"C:\MAA\resource\item_index.json")
DEPOT = pathlib.Path(r"C:\MAA\data\DepotData.json")
OPERBOX = pathlib.Path(r"C:\MAA\data\OperBoxData.json")
DEFAULT_TARGETS = ["德克萨斯", "乌尔比安", "伊芙利特", "山"]

# 星级 → 官方表下标（evolveGoldCost / maxLevel / characterExpMap 分组）
RAR_IDX = {"TIER_1": 0, "TIER_2": 1, "TIER_3": 2, "TIER_4": 3, "TIER_5": 4, "TIER_6": 5}
# 折理智常量（LS-6 / CE-6：36 理智 = 10000 经验 / 10000 龙门币）
EXP_PER_SANITY = 10000 / 36.0
LMD_PER_SANITY = 10000 / 36.0


def load():
    chars = json.loads(GD.read_text(encoding="utf-8"))
    idx = json.loads(ITEM_INDEX.read_text(encoding="utf-8"))
    try:
        depot = (json.loads(DEPOT.read_text(encoding="utf-8")).get("data") or {})
    except Exception:  # noqa: BLE001
        depot = {}
    return chars, idx, depot


def load_const():
    return json.loads(CONST.read_text(encoding="utf-8"))


def by_name(chars, name):
    for v in chars.values():
        if v.get("name") == name:
            return v
    return None


def target_std(rarity):
    """→ (目标精英, 目标等级, 是否练技能/专精)。"""
    if rarity == "TIER_6":
        return 2, 60, True
    if rarity == "TIER_5":
        return 2, 50, True
    return 2, 1, False


def level_cost(cst, rarity, cur_e, cur_l, tgt_e, tgt_l):
    """→ (升级经验, 升级龙门币, 精英化龙门币)。cur_e/tgt_e: 0/1/2。"""
    si = RAR_IDX.get(rarity, 0)
    maxlv = cst["maxLevel"][si]
    exp = lmd = 0
    for ph in range(int(cur_e), int(tgt_e) + 1):
        start = int(cur_l) if ph == cur_e else 1
        end = int(tgt_l) if ph == tgt_e else maxlv[ph]
        if end <= start:
            continue
        exp += sum(x for x in cst["characterExpMap"][ph][start - 1:end - 1] if x > 0)
        lmd += sum(x for x in cst["characterUpgradeCostMap"][ph][start - 1:end - 1] if x > 0)
    eg = cst["evolveGoldCost"][si]
    elite_lmd = sum(eg[ph] for ph in range(int(cur_e), int(tgt_e))
                    if 0 <= ph < len(eg) and eg[ph] > 0)
    return exp, lmd, elite_lmd


def need_materials(ch, rarity, cur=None, mastery_skill=1, mastery=True):
    """只算「当前练度 → 目标」的材料：精英化 + 技能 1→7 + 专精（默认技能 1 号专三）。"""
    c = Counter()
    cur = cur or {}
    cur_e = int(cur.get("elite") or 0)
    tgt_e, _, combat = target_std(rarity)
    # 精英化：只算 cur_e+1 .. tgt_e
    for ph in range(cur_e + 1, tgt_e + 1):
        for it in (ch["phases"][ph].get("evolveCost") or []):
            c[it["id"]] += it["count"]
    if combat:
        # 技能 1→7：索引 i 对应 从 (i+1) 升 (i+2)；已 skill_lvl 则从其下一个开始
        cur_skill = int(cur.get("skill_lvl") or 1)
        lu = ch.get("allSkillLvlup") or []
        for i in range(max(cur_skill - 1, 0), len(lu)):
            for it in (lu[i].get("lvlUpCost") or []):
                c[it["id"]] += it["count"]
        # 专精
        if mastery:
            sk = ch.get("skills") or []
            if sk:
                idx = min(max(mastery_skill - 1, 0), len(sk) - 1)
                spec = cur.get("spec") or [0, 0, 0]
                cur_m = int(spec[idx]) if idx < len(spec) else 0
                conds = sk[idx].get("levelUpCostCond") or []
                for m in range(max(cur_m, 0), len(conds)):
                    for it in (conds[m].get("levelUpCost") or []):
                        c[it["id"]] += it["count"]
    return c


def load_current(box_path=None, from_skland=False):
    """→ {name: {elite, level, skill_lvl, spec}}。优先森空岛，其次本地箱。"""
    data = None
    if from_skland:
        sys.path.insert(0, str(ROOT / "scripts" / "skland"))
        try:
            import skland_box  # type: ignore
            data = skland_box.fetch_operbox()
        except Exception as e:  # noqa: BLE001
            print("[oper_cost] 森空岛取数失败：%r（改用本地箱）" % e)
    if data is None:
        p = pathlib.Path(box_path) if box_path else OPERBOX
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
    out = {}
    for o in (data or {}).get("own_opers") or []:
        out[o.get("name")] = {"elite": o.get("elite", 0), "level": o.get("level", 1),
                              "skill_lvl": o.get("skill_lvl", 1),
                              "spec": o.get("spec") or [0, 0, 0]}
    return out


def compute(targets=None, skill=1, mastery=True, credit=None, box=None, from_skland=False):
    """对一组目标算：材料理智 / 升级经验 / 龙门币；含「先用库存 + 能合就合」。

    credit: {itemId: 数量} —— 别处已能白拿的材料（如活动商店），先从需求里扣掉。
    """
    chars, idx, depot = load()
    cst = load_const()
    targets = targets or DEFAULT_TARGETS
    curmap = load_current(box, from_skland)
    needs, exp, up_lmd, elite_lmd, detail = Counter(), 0, 0, 0, []
    for n in targets:
        ch = by_name(chars, n)
        if not ch:
            continue
        rar = ch.get("rarity")
        cur = curmap.get(n) or {}
        needs.update(need_materials(ch, rar, cur, mastery_skill=skill, mastery=mastery))
        te, tl, _ = target_std(rar)
        ce = int(cur.get("elite") or 0)
        cl = int(cur.get("level") or 1)
        e, u, el = level_cost(cst, rar, ce, cl, te, tl)
        exp += e
        up_lmd += u
        elite_lmd += el
        detail.append({"name": n, "rarity": rar, "cur": cur})
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
    lmd = up_lmd + elite_lmd
    lmd_san = lmd * val.lmd_unit()
    return {"targets": detail, "material_sanity": round(total, 1),
            "level_exp": exp, "level_lmd": up_lmd, "elite_lmd": elite_lmd,
            "lmd_sanity": round(lmd_san, 1), "total_sanity": round(total + lmd_san, 1),
            "rows": rows, "val": val, "credited": credited}


def report(name, chars, idx, depot, cst, cur=None, **kw):
    ch = by_name(chars, name)
    if not ch:
        print("  %s：表里没找到" % name)
        return None
    rar = ch.get("rarity")
    cur = cur or {}
    tgt_e, tgt_l, _ = target_std(rar)
    need = need_materials(ch, rar, cur, **kw)
    ce = int(cur.get("elite") or 0)
    cl = int(cur.get("level") or 1)
    lines, short = [], []
    for iid, cnt in sorted(need.items(), key=lambda x: -x[1]):
        have = int(depot.get(iid) or 0)
        gap = max(0, cnt - have)
        nm = (idx.get(iid) or {}).get("name", iid)
        if gap:
            short.append({"name": nm, "gap": gap})
        lines.append("    %-14s 需 %4d  有 %5d  → %s"
                     % (nm, cnt, have, ("缺 %d" % gap) if gap else "够"))
    exp, up_lmd, elite_lmd = level_cost(cst, rar, ce, cl, tgt_e, tgt_l)
    print("  【%s】%s 当前 E%dL%d → 目标 E%dL%d" % (name, rar, ce, cl, tgt_e, tgt_l))
    print("\n".join(lines) if lines else "    (材料已齐)")
    print("    升级：经验 %d ｜ 龙门币 %d ＋ 精英化 %d = %d"
          % (exp, up_lmd, elite_lmd, up_lmd + elite_lmd))
    return {"name": name, "rarity": rar, "std_target": [tgt_e, tgt_l],
            "cur": {"elite": ce, "level": cl, "skill_lvl": cur.get("skill_lvl"),
                    "spec": cur.get("spec")},
            "need": dict(need), "short": short,
            "exp": exp, "upgrade_lmd": up_lmd, "elite_lmd": elite_lmd}


def main():
    ap = argparse.ArgumentParser(description="干员培养材料账（当前练度→目标，官方表）")
    ap.add_argument("--name", default="")
    ap.add_argument("--all", action="store_true", help="对默认 %d 个目标一起算" % len(DEFAULT_TARGETS))
    ap.add_argument("--skill", type=int, default=1, help="常用技能序号（1/2/3，默认 1）")
    ap.add_argument("--no-mastery", action="store_true", help="不算专精")
    ap.add_argument("--from-skland", action="store_true", help="从森空岛读当前练度（含技能/专精）")
    ap.add_argument("--box", default="", help="操作箱 json 路径（与 skland_box 同构）")
    ap.add_argument("--elite", type=int, default=None, help="覆盖当前精英阶段")
    ap.add_argument("--level", type=int, default=None, help="覆盖当前等级")
    ap.add_argument("--skill-lvl", type=int, default=None, help="覆盖当前技能等级（1-7）")
    ap.add_argument("--spec", default="", help="覆盖当前专精，如 0,0,0")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    chars, idx, depot = load()
    cst = load_const()
    names = DEFAULT_TARGETS if (args.all or not args.name) else [args.name]
    curmap = load_current(args.box or None, args.from_skland)
    if args.elite is not None:
        for n in names:
            curmap.setdefault(n, {})
            curmap[n].update({"elite": args.elite, "level": args.level or 1})
    if args.skill_lvl is not None:
        for n in names:
            curmap.setdefault(n, {})
            curmap[n]["skill_lvl"] = args.skill_lvl
    if args.spec:
        sp = [int(x) for x in args.spec.split(",")]
        for n in names:
            curmap.setdefault(n, {})
            curmap[n]["spec"] = sp

    needs = Counter()
    detail = []
    total_exp = total_up = total_elite = 0
    for n in names:
        ch = by_name(chars, n)
        if not ch:
            print("  %s：表里没找到" % n)
            continue
        rar = ch.get("rarity")
        cur = curmap.get(n) or {}
        needs.update(need_materials(ch, rar, cur,
                                    mastery_skill=args.skill, mastery=not args.no_mastery))
        te, tl, _ = target_std(rar)
        ce = int(cur.get("elite") or 0)
        cl = int(cur.get("level") or 1)
        e, u, el = level_cost(cst, rar, ce, cl, te, tl)
        total_exp += e
        total_up += u
        total_elite += el
        detail.append((n, rar, cur, te, tl))
        print("  【%s】%s 当前 E%dL%d 技能%s 专精%s → 目标 E%dL%d"
              % (n, rar, ce, cl, cur.get("skill_lvl", "?"), cur.get("spec"), te, tl))

    print("\n=== 材料缺口 ===")
    short = []
    for iid, cnt in sorted(needs.items(), key=lambda x: -x[1]):
        have = int(depot.get(iid) or 0)
        gap = max(0, cnt - have)
        nm = (idx.get(iid) or {}).get("name", iid)
        if gap:
            short.append({"name": nm, "gap": gap})
        print("  %-14s 需 %4d  有 %5d  → %s" % (nm, cnt, have, ("缺 %d" % gap) if gap else "够"))

    try:
        sys.path.insert(0, str(TOOLS))
        from material_cost import Valuation, plan_needs
        val = Valuation()
        mat_san, rows = plan_needs(val, dict(needs), dict(depot))
        lmd = total_up + total_elite
        lmd_san = lmd * val.lmd_unit()
        exp_san = total_exp / EXP_PER_SANITY
        print("\n=== 汇总 ===")
        print("  材料理智       %8.1f" % mat_san)
        print("  升级经验       %8d  → ≈ %.0f 理智" % (total_exp, exp_san))
        print("  升级龙门币     %8d" % total_up)
        print("  精英化龙门币   %8d" % total_elite)
        print("  龙门币合计     %8d  → ≈ %.0f 理智" % (lmd, lmd_san))
        print("  合计（材料+经验+龙门币）≈ %.0f 理智" % (mat_san + exp_san + lmd_san))
        if args.json:
            pathlib.Path(args.json).write_text(json.dumps(
                {"targets": [{"name": n, "rarity": r, "cur": c} for n, r, c, _, _ in detail],
                 "material_sanity": round(mat_san, 1), "level_exp": total_exp,
                 "level_lmd": total_up, "elite_lmd": total_elite,
                 "total_sanity": round(mat_san + exp_san + lmd_san, 1),
                 "short": short, "rows": rows},
                ensure_ascii=False, indent=2), encoding="utf-8")
            print("[oper_cost] 已写", args.json)
    except Exception as e:  # noqa: BLE001
        print("\n[oper_cost] 估值模块失败：%r" % e)


if __name__ == "__main__":
    main()
