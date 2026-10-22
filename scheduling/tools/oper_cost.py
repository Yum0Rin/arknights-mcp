#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干员培养材料账 —— 官方表算「需求」、比仓库算「缺口」，按「当前练度」只算剩余段。

数据源（官方静态表 + 本人账号）：
  · 需求        scheduling/data/gamedata/character_table.json
      phases[].evolveCost                         精英化材料
      allSkillLvlup[].lvlUpCost                   技能 1→7
      skills[].levelUpCostCond[].levelUpCost       专精 M1/M2/M3
  · 模组        scheduling/data/gamedata/uniequip_table.json（官方）
      charEquip[charId]                            该干员有哪些模组
      equipDict[id].itemCost{"1"/"2"/"3"}          模组升到 1/2/3 级的材料（type=GOLD 的折龙门币）
  · 升级/精英化  scheduling/data/gamedata/gamedata_const.json（官方）
      characterExpMap / characterUpgradeCostMap   （按精英阶段 3 组）
      evolveGoldCost / maxLevel                   （按星级）
  · 名称        C:\\MAA\\resource\\item_index.json
  · 库存        C:\\MAA\\data\\DepotData.json
  · 当前练度    森空岛（--from-skland，含 skill_lvl/spec/modules）或 --box 或显式参数

标准（用户定，仅在未显式给目标时套用）：
  6★ → 精二 60 级 + 技能 7 + 常用技能专三
  5★ → 精二 50 级 + 技能 7 + 常用技能专三
  ≤4★ → 精二 1 级（不练技能）

用法：
  # 标准目标（旧）
  python scheduling/tools/oper_cost.py --name 乌尔比安 --from-skland
  # 自定义目标：精二 90 + 一/二/三技能专精 3/3/0 + 第二个模组升到 3 级
  python scheduling/tools/oper_cost.py --name 乌尔比安 --from-skland \\
      --target-elite 2 --target-level 90 --mastery 3,3,0 --module 3 --module-sel 2
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
MODULE = ROOT / "scheduling" / "data" / "gamedata" / "uniequip_table.json"
BUILDING = ROOT / "scheduling" / "data" / "gamedata" / "building_data.json"   # 加工站配方（合成关系）
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


def load_modules():
    """→ 官方 `uniequip_table.json`（{equipDict, charEquip, ...}）。缺表时返回空壳（模组成本按 0 算）。"""
    if not MODULE.exists():
        return {"equipDict": {}, "charEquip": {}}
    d = json.loads(MODULE.read_text(encoding="utf-8"))
    return {"equipDict": d.get("equipDict") or {}, "charEquip": d.get("charEquip") or {}}


def load_recipes():
    """加工站**合成配方**（合成关系）：→ {产物id: [{"costs":[(投入id, 数)], "gold": 龙门币, "count": 每批产出}, ...]}。

    与 material_cost 同源（`building_data.workshopFormulas`）；用于把「缺的成品材料」还原成
    「可去加工站用低级材料合成」的路线（对齐 MAA `MaterialSynthesisTaskPlugin` 的「即缺即合」）。
    """
    if not BUILDING.exists():
        return {}
    d = json.loads(BUILDING.read_text(encoding="utf-8"))
    out: dict = {}
    for src in ("workshopFormulas", "manufactFormulas"):   # 加工站 + 制造站（双芯片在制造站）
        for f in (d.get(src) or {}).values():
            oid = f.get("itemId")
            if not oid:
                continue
            out.setdefault(oid, []).append({
                "costs": [(c["id"], int(c["count"])) for c in (f.get("costs") or [])],
                "gold": int(f.get("goldCost") or 0),
                "count": int(f.get("count") or 1),
            })
    return out


def resolve_needs(needs, stock, recipes, max_depth=5):
    """把需求按**合成关系递归降级**，并扣库存 → (最终要弄的材料 Counter, 合成消耗龙门币)。

    规则（对齐 MAA `OperProgress` 的「即缺即合」）：某材料先用库存；仍然缺、且加工站有配方的，
    就把缺口换成**配方投入**（递归处理，投入自身也优先用库存/继续降级）；没有配方的才留在结果里。
    返回的 Counter 就是「最终还需要获取的材料」（基础材料为主）。
    """
    pool = {k: v for k, v in (stock or {}).items()}
    out: Counter = Counter()
    log: list = []          # 降级记录：[{id, gap, batches, out, costs:[(id, 数)], gold}]
    gold = 0

    def rec(iid, qty, depth):
        nonlocal gold
        if qty <= 0:
            return
        opts = recipes.get(iid)
        r = opts[0] if opts else None
        if r and any(cid == iid for cid, _ in r["costs"]):
            r = None                            # 自环配方跳过，避免死循环
        if r and depth < max_depth:             # 可合成 → 先用库存，再**把缺口降级成配方投入**（递归）
            use = min(pool.get(iid, 0), qty)
            if use:
                pool[iid] = pool.get(iid, 0) - use
                qty -= use
            if qty <= 0:
                return
            batches = -(-qty // r["count"])     # 向上取整批数
            gold += r["gold"] * batches
            log.append({"id": iid, "gap": qty, "batches": batches, "out": r["count"],
                        "costs": [(cid, ccnt * batches) for cid, ccnt in r["costs"]],
                        "gold": r["gold"] * batches})
            for cid, ccnt in r["costs"]:
                rec(cid, ccnt * batches, depth + 1)
        else:
            out[iid] += qty                     # 叶子：记录「要弄到多少」（库存由 需/有/缺 展示）

    for iid, q in needs.items():
        rec(iid, q, 0)
    return out, gold, log


def module_list(uni, char_id):
    """该干员的模组列表（按 `charEquipOrder` 排序）；含不可升级的 INITIAL 模组。"""
    ed = uni.get("equipDict") or {}
    ids = (uni.get("charEquip") or {}).get(char_id) or []
    out = [ed[i] for i in ids if i in ed]
    out.sort(key=lambda e: int(e.get("charEquipOrder") or 0))
    return out


def resolve_module(modules, selector):
    """按 序号(1/2/3/4…，= charEquipOrder+1) / 模组名 / 完整 id 选中一个模组。找不到返回 None。"""
    if selector is None or selector == "":
        return None
    s = str(selector).strip()
    # 序号：只看「模组 id 里的 00N」或列表位次，避免把中文名误判
    if s.isdigit():
        n = int(s)
        for e in modules:
            eid = str(e.get("uniEquipId") or "")
            if eid.startswith("uniequip_%03d_" % n):
                return e
        if 1 <= n <= len(modules):
            return modules[n - 1]
        return None
    for e in modules:
        if e.get("uniEquipName") == s or e.get("uniEquipId") == s:
            return e
    return None


def by_name(chars, name):
    for v in chars.values():
        if v.get("name") == name:
            return v
    return None


def find_char(chars, name):
    """→ (charId, 条目)；charId 是 character_table 的字典键（条目本身不含 id 字段）。找不到返回 (None, None)。"""
    for cid, v in chars.items():
        if v.get("name") == name:
            return cid, v
    return None, None


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


def _norm_mastery(v, n=3):
    out = [0] * n
    if v is None:
        return out
    for i, x in enumerate(list(v)[:n]):
        try:
            out[i] = max(0, min(3, int(x)))
        except Exception:  # noqa: BLE001
            out[i] = 0
    return out


def norm_target(rarity, tgt):
    """把「目标练度」补全默认：elite/level 缺省按星级标准，skill_lvl 缺省 7，mastery 缺省 [0,0,0]。"""
    std_e, std_l, _ = target_std(rarity)
    tgt = tgt or {}
    return {
        "elite": int(tgt.get("elite", std_e)),
        "level": int(tgt.get("level", std_l)),
        "skill_lvl": int(tgt.get("skill_lvl", 7)),
        "mastery": _norm_mastery(tgt.get("mastery")),
        "modules": dict(tgt.get("modules") or {}),
    }


def plan_need(ch, uni, rarity, cur, tgt, char_id=None):
    """「当前练度 → 目标」的**材料 + 模组龙门币**，覆盖 精英化 / 技能1-7 / 专精 / 模组。

    参数：
      · ch      官方 character_table 里的干员条目
      · uni     官方 uniequip_table（load_modules()）
      · tgt     已补全的目标（norm_target 的结果）：{elite, level, skill_lvl, mastery[3], modules{selector:level}}
      · cur     当前练度：{elite, level, skill_lvl, spec[3], modules{uniEquipId:level}}
      · char_id character_table 的键（查模组用；缺省则跳过模组）
    返回：
      · materials    Counter（精英化 + 技能 + 专精 + 模组 的材料 id→数量）
      · module_lmd   模组升级的龙门币（itemCost 里 type=GOLD 的部分）
      · modules      模组明细（每个选中的模组：当前级→目标级、材料、龙门币）
    """
    c = Counter()
    cur = cur or {}
    cur_e = int(cur.get("elite") or 0)
    cur_skill = int(cur.get("skill_lvl") or 1)
    cur_spec = list(cur.get("spec") or [0, 0, 0])

    # 精英化材料：cur_e+1 .. tgt_e
    phases = ch.get("phases") or []
    for ph in range(cur_e + 1, int(tgt["elite"]) + 1):
        if 0 <= ph < len(phases):
            for it in (phases[ph].get("evolveCost") or []):
                c[it["id"]] += it["count"]
    # 技能 1→7（三技能共享的通用等级）
    lu = ch.get("allSkillLvlup") or []
    for i in range(max(cur_skill - 1, 0), min(int(tgt["skill_lvl"]) - 1, len(lu))):
        for it in (lu[i].get("lvlUpCost") or []):
            c[it["id"]] += it["count"]
    # 专精（每技能独立，mastery[i] 对应第 i+1 个技能）
    sk = ch.get("skills") or []
    for idx, want in enumerate(tgt["mastery"]):
        if want <= 0 or idx >= len(sk):
            continue
        cur_m = int(cur_spec[idx]) if idx < len(cur_spec) else 0
        conds = sk[idx].get("levelUpCostCond") or []
        for m in range(max(cur_m, 0), min(want, len(conds))):
            for it in (conds[m].get("levelUpCost") or []):
                c[it["id"]] += it["count"]

    # 模组（每模组独立，含龙门币）
    mlist = module_list(uni, char_id or "")
    mdetail, module_lmd = [], 0
    cur_mods = cur.get("modules") or {}
    for sel, lvl in (tgt["modules"] or {}).items():
        eq = resolve_module(mlist, sel)
        if not eq:
            continue
        eid = eq.get("uniEquipId")
        cost = eq.get("itemCost") or {}
        cur_lv = int(cur_mods.get(eid, 0))
        want = int(lvl)
        gold, mats = 0, Counter()
        for lv in range(cur_lv + 1, want + 1):
            for it in (cost.get(str(lv)) or []):
                if it.get("id") == "4001" or it.get("type") == "GOLD":
                    gold += it["count"]
                else:
                    mats[it["id"]] += it["count"]
        c.update(mats)
        module_lmd += gold
        mdetail.append({"id": eid, "name": eq.get("uniEquipName"), "selector": sel,
                        "cur": cur_lv, "target": want, "gold": gold,
                        "materials": dict(mats)})
    return {"materials": c, "module_lmd": module_lmd, "modules": mdetail}


def load_current(box_path=None, from_skland=False):
    """→ {name: {elite, level, skill_lvl, spec, modules}}。优先森空岛，其次本地箱。"""
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
        # 模组当前等级：只记已解锁的（locked=False）→ {uniEquipId: level}；未解锁按 0 级
        mods = {m.get("id"): int(m.get("level") or 0)
                for m in (o.get("modules") or []) if m.get("id") and not m.get("locked")}
        out[o.get("name")] = {"elite": o.get("elite", 0), "level": o.get("level", 1),
                              "skill_lvl": o.get("skill_lvl", 1),
                              "spec": o.get("spec") or [0, 0, 0],
                              "modules": mods}
    return out


def compute(targets=None, skill=1, mastery=True, credit=None, box=None, from_skland=False):
    """对一组目标算：材料理智 / 升级经验 / 龙门币；含「先用库存 + 能合就合」。

    credit: {itemId: 数量} —— 别处已能白拿的材料（如活动商店），先从需求里扣掉。
    """
    chars, idx, depot = load()
    specs = []
    for n in (targets or DEFAULT_TARGETS):
        cid, ch = find_char(chars, n)
        if not ch:
            continue
        rar = ch.get("rarity")
        te, tl, combat = target_std(rar)
        msl = [0, 0, 0]                          # 常用技能专三（默认技能 1；≤4★ 不练技能）
        if combat and mastery and 1 <= int(skill) <= 3:
            msl[int(skill) - 1] = 3
        specs.append({"name": n, "elite": te, "level": tl,
                      "skill_lvl": 7 if combat else 1, "mastery": msl})
    res = compute_custom(specs, box=box, from_skland=from_skland, credit=credit)
    tot = res["total"]
    return {
        "targets": [{"name": t["name"], "rarity": t["rarity"], "cur": t["current"]}
                    for t in res["targets"] if not t.get("error")],
        "material_sanity": tot["material_sanity"],
        "level_exp": tot["exp"], "level_lmd": tot["upgrade_lmd"], "elite_lmd": tot["elite_lmd"],
        "lmd_sanity": tot["lmd_sanity"], "total_sanity": tot["total_sanity"],
        "rows": tot["rows"], "val": res["val"], "credited": res["credited"],
        "resolved": tot["resolved"], "downgrades": tot["downgrades"],
        "craft_gold": tot["craft_gold"],
    }


def compute_custom(specs, box=None, from_skland=False, include_exp=True, credit=None):
    """对一组「干员 + 目标练度」算养成所需资源（**自定义目标**版，区别于按星级标准的 compute）。

    specs: 列表，每项一个干员及其目标：
        {"name": "乌尔比安",          # 必填，中文名
         "elite": 2,                  # 目标精英阶段 0/1/2（省 = 按星级标准）
         "level": 60,                 # 目标等级（省 = 按星级标准）
         "skill_lvl": 7,              # 目标技能通用等级 1-7（省 = 7）
         "mastery": [3, 3, 0],        # 一/二/三技能 各自的专精目标 0-3（省 = 不专精）
         "modules": {"1": 3}}         # 模组目标：{序号/名字/id: 目标等级}（省 = 不动）
    credit: {itemId: 数量} —— 别处可白拿的材料，先从需求里扣掉。

    返回 {source, targets, total, val}；`targets[].materials` 为逐干员缺口，`total` 为合计+理智估值。
    """
    chars, idx, depot = load()
    cst = load_const()
    uni = load_modules()
    curmap = load_current(box, from_skland)

    def nm(iid):
        return (idx.get(iid) or {}).get("name", iid)

    def res_rows(counter):
        rows = []
        for i, q in sorted(counter.items(), key=lambda x: -x[1]):
            have = int(depot.get(i) or 0)
            rows.append({"id": i, "name": nm(i), "need": q, "have": have,
                         "gap": max(0, q - have)})
        return rows

    # 合成配方（加工站 + 制造站）。**芯片只允许「双芯片」降级**（→ 芯片组 + 芯片助剂）；
    # 芯片/芯片组的「转换」配方会成链爆炸（每级 ×3），排除。
    recipes = {k: v for k, v in load_recipes().items()
               if "芯片" not in nm(k) or "双芯片" in nm(k)}

    needs = Counter()
    tot_exp = tot_up = tot_elite = tot_modlmd = 0
    total_resolved: Counter = Counter()
    total_craft_gold = 0
    total_downgrades: list = []
    targets_out = []
    stock_pool = dict(depot)      # 共享库存池：多干员时不会重复抵扣同一份库存
    for s in specs:
        n = s.get("name")
        cid, ch = find_char(chars, n)
        if not ch:
            targets_out.append({"name": n, "error": "表里没找到该干员（检查中文名）"})
            continue
        rar = ch.get("rarity")
        cur = curmap.get(n) or {}
        nt = norm_target(rar, s)
        mi = plan_need(ch, uni, rar, cur, nt, char_id=cid)
        needs.update(mi["materials"])
        ce, cl = int(cur.get("elite") or 0), int(cur.get("level") or 1)
        exp, up_lmd, elite_lmd = level_cost(cst, rar, ce, cl, nt["elite"], nt["level"])
        if not include_exp:
            exp = up_lmd = 0
        tot_exp += exp
        tot_up += up_lmd
        tot_elite += elite_lmd
        tot_modlmd += mi["module_lmd"]
        resolved, craft_gold, dlog = resolve_needs(dict(mi["materials"]), stock_pool, recipes)
        total_resolved.update(resolved)
        total_craft_gold += craft_gold
        downgrades = [{"name": nm(x["id"]), "gap": x["gap"], "batches": x["batches"],
                       "out": x["out"], "gold": x["gold"],
                       "inputs": [{"id": cid, "name": nm(cid), "count": c} for cid, c in x["costs"]]}
                      for x in dlog]
        total_downgrades.extend(downgrades)
        rows = []
        for iid, cnt in sorted(mi["materials"].items(), key=lambda x: -x[1]):
            have = int(depot.get(iid) or 0)
            gap = max(0, cnt - have)
            row = {"id": iid, "name": nm(iid), "need": cnt, "have": have, "gap": gap}
            if gap > 0 and iid in recipes:      # 缺口可去加工站合成 → 给出配方（差额 = 缺多少合成多少批）
                r0 = recipes[iid][0]
                b = -(-gap // r0["count"])      # 向上取整批数
                row["craft"] = {
                    "out": r0["count"], "batches": b,
                    "gold_batches": r0["gold"] * b,
                    "need": [{"id": cid, "name": nm(cid), "count": cc * b} for cid, cc in r0["costs"]],
                }
            rows.append(row)
        targets_out.append({
            "name": n, "id": cid, "rarity": rar,
            "current": {"elite": ce, "level": cl, "skill_lvl": int(cur.get("skill_lvl") or 1),
                        "spec": cur.get("spec") or [0, 0, 0], "modules": cur.get("modules") or {}},
            "target": nt,
            "materials": rows, "modules": mi["modules"],
            "resolved": res_rows(resolved),
            "downgrades": downgrades,
            "craft_gold": craft_gold,
            "exp": exp, "upgrade_lmd": up_lmd, "elite_lmd": elite_lmd,
            "module_lmd": mi["module_lmd"], "lmd": up_lmd + elite_lmd + mi["module_lmd"],
        })

    credited = {}
    for iid, cnt in (credit or {}).items():
        take = min(needs.get(iid, 0), cnt)
        if take:
            needs[iid] -= take
            credited[iid] = take
            if needs[iid] <= 0:
                del needs[iid]

    sys.path.insert(0, str(TOOLS))
    from material_cost import Valuation, plan_needs
    val = Valuation()
    mat_san, mrows = plan_needs(val, dict(needs), dict(depot))
    lmd = tot_up + tot_elite + tot_modlmd
    exp_san = tot_exp / EXP_PER_SANITY
    lmd_san = lmd * val.lmd_unit()
    total_mat_rows = []
    for iid, cnt in sorted(needs.items(), key=lambda x: -x[1]):
        have = int(depot.get(iid) or 0)
        total_mat_rows.append({"id": iid, "name": nm(iid), "need": cnt, "have": have,
                               "gap": max(0, cnt - have)})
    total = {
        "materials": total_mat_rows,
        "resolved": res_rows(total_resolved),
        "downgrades": total_downgrades,
        "craft_gold": total_craft_gold,
        "exp": tot_exp, "upgrade_lmd": tot_up, "elite_lmd": tot_elite,
        "module_lmd": tot_modlmd, "lmd": lmd,
        "material_sanity": round(mat_san, 1),
        "exp_sanity": round(exp_san, 1),
        "lmd_sanity": round(lmd_san, 1),
        "total_sanity": round(mat_san + exp_san + lmd_san, 1),
        "rows": mrows,
    }
    src = "skland" if from_skland else ("local_box" if curmap else "none")
    return {"source": src, "targets": targets_out, "total": total,
            "credited": credited, "val": val}


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


def first_upgradable(uni, char_id):
    """该干员第一个**可升级**模组（itemCost 非空，即 ADVANCED）；没有则 None。"""
    for e in module_list(uni, char_id):
        if e.get("itemCost"):
            return e
    return None


def _specs_for(names, chars, uni, target_elite, target_level, mastery, module_level, module_sel):
    """把 CLI 参数摊成 compute_custom 的 specs（逐干员；模组默认取该干员第一个可升级模组）。"""
    specs = []
    for n in names:
        s = {"name": n}
        if target_elite is not None:
            s["elite"] = target_elite
        if target_level is not None:
            s["level"] = target_level
        if mastery is not None:
            s["mastery"] = mastery
        if module_level is not None:
            _cid, ch = find_char(chars, n)
            sel = module_sel
            if not sel and ch:
                fe = first_upgradable(uni, _cid or "")
                sel = fe.get("uniEquipId") if fe else None
            if sel:
                s["modules"] = {sel: module_level}
        specs.append(s)
    return specs


def main():
    ap = argparse.ArgumentParser(description="干员养成材料账（当前练度→目标，官方表）")
    ap.add_argument("--name", default="", help="干员中文名（逗号分隔可多个）")
    ap.add_argument("--all", action="store_true", help="对默认 %d 个目标一起算" % len(DEFAULT_TARGETS))
    # —— 目标练度（本次新增）——
    ap.add_argument("--target-elite", type=int, default=None, help="目标精英阶段 0/1/2（省=按星级标准）")
    ap.add_argument("--target-level", type=int, default=None, help="目标等级（省=按星级标准）")
    ap.add_argument("--mastery", default="", help="一/二/三技能目标专精，如 3,3,0（省=见 --skill）")
    ap.add_argument("--skill", type=int, default=1, help="未给 --mastery 时，把该技能专三（默认 1）")
    ap.add_argument("--no-mastery", action="store_true", help="未给 --mastery 时，不算专精")
    ap.add_argument("--module", type=int, default=None, dest="module_level",
                    help="模组目标等级 1/2/3（默认作用于第一个可升级模组）")
    ap.add_argument("--module-sel", default="", help="选哪个模组：序号(1/2/3)/模组名/id")
    # —— 当前练度来源 / 覆盖 ——
    ap.add_argument("--from-skland", action="store_true", help="从森空岛读当前练度（含技能/专精/模组）")
    ap.add_argument("--box", default="", help="操作箱 json 路径（与 skland_box 同构）")
    ap.add_argument("--elite", type=int, default=None, help="覆盖当前精英阶段")
    ap.add_argument("--level", type=int, default=None, help="覆盖当前等级")
    ap.add_argument("--skill-lvl", type=int, default=None, help="覆盖当前技能等级（1-7）")
    ap.add_argument("--spec", default="", help="覆盖当前专精，如 0,0,0")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    chars, idx, depot = load()
    uni = load_modules()
    names = DEFAULT_TARGETS if (args.all or not args.name) else \
        [x.strip() for x in args.name.split(",") if x.strip()]

    # 目标专精：优先 --mastery，其次 --skill/--no-mastery（保持旧语义：常用技能专三）
    if args.mastery:
        mastery = [int(x) for x in args.mastery.split(",")]
    elif args.no_mastery:
        mastery = [0, 0, 0]
    else:
        mastery = [0, 0, 0]
        if 1 <= args.skill <= 3:
            mastery[args.skill - 1] = 3

    specs = _specs_for(names, chars, uni, args.target_elite, args.target_level,
                       mastery, args.module_level, args.module_sel)

    # 当前练度覆盖（旧参数）
    box = args.box or None
    if args.elite is not None or args.skill_lvl is not None or args.spec:
        cm = load_current(box, args.from_skland)
        for n in names:
            cm.setdefault(n, {})
            if args.elite is not None:
                cm[n].update({"elite": args.elite, "level": args.level or 1})
            if args.skill_lvl is not None:
                cm[n]["skill_lvl"] = args.skill_lvl
            if args.spec:
                cm[n]["spec"] = [int(x) for x in args.spec.split(",")]
        box = "-"  # 标记走覆盖（compute_custom 里 box 会被 load_current 忽略），改用临时文件更稳
        import tempfile
        tf = pathlib.Path(tempfile.gettempdir()) / "oper_cost_box_override.json"
        tf.write_text(json.dumps({"own_opers": [
            {"name": n, "elite": v.get("elite", 0), "level": v.get("level", 1),
             "skill_lvl": v.get("skill_lvl", 1), "spec": v.get("spec") or [0, 0, 0]}
            for n, v in cm.items()]}, ensure_ascii=False), encoding="utf-8")
        box = str(tf)

    res = compute_custom(specs, box=box, from_skland=args.from_skland)

    for t in res["targets"]:
        if t.get("error"):
            print("  %s：%s" % (t["name"], t["error"]))
            continue
        ct, tg = t["current"], t["target"]
        print("  【%s】%s 当前 E%dL%d 技能%s 专精%s 模组%s → 目标 E%dL%d 技能%d 专精%s 模组%s"
              % (t["name"], t["rarity"], ct["elite"], ct["level"], ct["skill_lvl"], ct["spec"],
                 ct["modules"] or {}, tg["elite"], tg["level"], tg["skill_lvl"], tg["mastery"],
                 tg["modules"] or {}))
        for m in t["materials"]:
            print("    %-16s 需 %4d  有 %5d  → %s"
                  % (m["name"], m["need"], m["have"], ("缺 %d" % m["gap"]) if m["gap"] else "够"))
        for md in t["modules"]:
            print("    模组[%s] Lv%d→Lv%d  龙门币 %d  材料 %s"
                  % (md["name"], md["cur"], md["target"], md["gold"],
                     "、".join("%s×%d" % (k, v) for k, v in md["materials"].items()) or "无"))
        print("    升级经验 %d ｜ 升级龙门币 %d ｜ 精英化龙门币 %d ｜ 模组龙门币 %d"
              % (t["exp"], t["upgrade_lmd"], t["elite_lmd"], t["module_lmd"]))

    tot = res["total"]
    print("\n=== 合计 ===")
    print("  材料理智       %8.1f" % tot["material_sanity"])
    print("  升级经验       %8d  → ≈ %.0f 理智" % (tot["exp"], tot["exp_sanity"]))
    print("  升级龙门币     %8d" % tot["upgrade_lmd"])
    print("  精英化龙门币   %8d" % tot["elite_lmd"])
    print("  模组龙门币     %8d" % tot["module_lmd"])
    print("  龙门币合计     %8d  → ≈ %.0f 理智" % (tot["lmd"], tot["lmd_sanity"]))
    print("  合计（材料+经验+龙门币）≈ %.0f 理智" % tot["total_sanity"])
    if args.json:
        out = {k: v for k, v in res.items() if k != "val"}
        pathlib.Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
        print("[oper_cost] 已写", args.json)


if __name__ == "__main__":
    main()
