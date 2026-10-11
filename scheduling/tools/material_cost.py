#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""材料 → 理智 估值：**直接刷关卡 vs 加工站合成**，递归取更省的那条路。

数据：
  · `gamedata/penguin_matrix.json`  企鹅物流：每关每物品 times/quantity（掉落率）
  · `gamedata/penguin_stages.json`  企鹅物流：stageId → code / apCost
  · `gamedata/building_data.json`   `workshopFormulas`（合成配方：costs + goldCost）
  · `resource/item_index.json`      物品名（MAA 本地）

估值规则：
  直接刷： sanity_per_item(item) = min over stages of  apCost / (quantity/times)
  合成：   craft(item) = (Σ inputs估值 + goldCost×LMD单价) / count   （递归，带深度限制）
  有效值： effective(item) = min(直接刷, 合成)

龙门币(LMD, item 4001)：按最优龙门币关（CE-6）折算 → LMD_UNIT 理智/个。
"""
from __future__ import annotations

import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
GD = ROOT / "scheduling" / "data" / "gamedata"
ITEM_INDEX = pathlib.Path(r"C:\MAA\resource\item_index.json")
LMD_ID = "4001"


def _j(p):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


class Valuation:
    def __init__(self):
        self.idx = _j(ITEM_INDEX) or {}
        mat = _j(GD / "penguin_matrix.json") or {}
        st = _j(GD / "penguin_stages.json") or []
        bd = _j(GD / "building_data.json") or {}
        self.ap = {s["stageId"]: s.get("apCost") for s in st if s.get("stageId")}
        self.code = {s["stageId"]: s.get("code") for s in st if s.get("stageId")}
        # 直接刷：itemId -> (理智/个, 关卡code, 每局期望产出)
        best = {}
        for row in mat.get("matrix") or []:
            ap = self.ap.get(row.get("stageId"))
            times = row.get("times") or 0
            qty = row.get("quantity") or 0
            if not ap or times < 30 or qty <= 0:
                continue
            per_item = ap / (qty / times)
            cur = best.get(row["itemId"])
            if cur is None or per_item < cur[0]:
                best[row["itemId"]] = (per_item, self.code.get(row["stageId"], row["stageId"]),
                                       round(qty / times, 3))
        self.direct = best
        # 合成配方
        self.recipes = {}
        for f in (bd.get("workshopFormulas") or {}).values():
            out, cnt = f.get("itemId"), f.get("count") or 1
            self.recipes.setdefault(out, []).append({
                "costs": [(c["id"], c["count"]) for c in (f.get("costs") or [])],
                "gold": f.get("goldCost") or 0, "count": cnt})

    def name(self, iid):
        return (self.idx.get(iid) or {}).get("name", iid)

    def lmd_unit(self):
        """1 龙门币 = 多少理智（按最优龙门币关）。"""
        d = self.direct.get(LMD_ID)
        return d[0] if d else 1 / 278.0        # 兜底：CE-6 口径 278 LMD/理智

    def effective(self, iid, depth=0, seen=None):
        """有效理智估值（递归取 min(刷, 合)）。返回 float 或 None。"""
        seen = seen or set()
        if iid in seen or depth > 4:
            return None
        direct = self.direct.get(iid)
        base = direct[0] if direct else None
        for r in self.recipes.get(iid, []):
            seen.add(iid)
            cost = 0.0
            ok = True
            for cid, ccnt in r["costs"]:
                v = self.effective(cid, depth + 1, seen)
                if v is None:
                    ok = False
                    break
                cost += v * ccnt
            if ok:
                cost += r["gold"] * self.lmd_unit()
                cand = cost / r["count"]
                if base is None or cand < base:
                    base = cand
            seen.discard(iid)
        return base

    # -------- 库存感知：先用库存，不够的再"刷 or 合"，就地扣库存 --------
    def fulfill(self, iid, qty, stock, depth=0, log=None):
        """满足 qty 个 iid，返回 (理智, 明细dict) 或 (None, {})。会消耗 stock。"""
        if qty <= 0:
            return 0.0, {"stock": 0, "farm": 0, "craft": 0}
        have = int(stock.get(iid, 0))
        use = min(have, qty)
        if use:
            stock[iid] = have - use
        qty -= use
        det = {"stock": use, "farm": 0, "craft": 0}
        if qty <= 0:
            return 0.0, det
        d = self.direct.get(iid)
        best = d[0] * qty if d else None
        best_det = {"stock": use, "farm": qty, "craft": 0} if d else None
        if depth < 4:
            for r in self.recipes.get(iid, []):
                n = math.ceil(qty / r["count"])          # 需要合的批数
                c, ok = r["gold"] * n * self.lmd_unit(), True
                sub = {"stock": use, "farm": 0, "craft": n}
                for cid, ccnt in r["costs"]:
                    sc, sd = self.fulfill(cid, ccnt * n, stock, depth + 1, log)
                    if sc is None:
                        ok = False
                        break
                    c += sc
                    for k in ("stock", "farm", "craft"):
                        sub[k] = sub.get(k, 0) + sd.get(k, 0)
                if ok and (best is None or c < best):
                    best, best_det = c, sub
        return (best if best is not None else None), (best_det or det)


def plan_needs(val: Valuation, needs: dict, stock: dict):
    """对一组需求（{itemId: 数量}）做库存感知分配，返回 (总理智, 明细列表)。"""
    # 高价值/高阶的先满足（先决定合成，再让低阶需求用剩余库存）
    order = sorted(needs.items(), key=lambda kv: -(val.effective(kv[0]) or 0))
    total, rows = 0.0, []
    for iid, qty in order:
        cost, det = val.fulfill(iid, qty, stock)
        if cost is None:
            rows.append({"item": iid, "name": val.name(iid), "qty": qty,
                         "sanity": None, "note": "无估值(该材料不在掉落/配方表)"})
            continue
        total += cost
        rows.append({"item": iid, "name": val.name(iid), "qty": qty,
                     "sanity": round(cost, 1), "det": det})
    return total, rows


if __name__ == "__main__":
    v = Valuation()
    print("直接刷覆盖物品:", len(v.direct), "| 合成配方物品:", len(v.recipes))
    print("LMD 单价(理智/个): %.6f  → 10000 龙门币 ≈ %.1f 理智"
          % (v.lmd_unit(), v.lmd_unit() * 10000))
    for iid in ("30012", "30013", "30014", "30145", "31054", "3223", "3303", LMD_ID):
        d = v.direct.get(iid)
        print("  %-6s %-10s 直接刷 %s 理智/个 → 合成有效值 %s"
              % (iid, v.name(iid),
                 ("%.2f(%s)" % (d[0], d[1])) if d else "—",
                 ("%.2f" % v.effective(iid)) if v.effective(iid) else "—"))
