#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公招词条组合推荐 —— 算「出未拥有干员概率最大」的词条组合。

数据：
  - 公招池：MAA 本地 `C:\\MAA\\resource\\recruitment.json`（160 干员，各带 rarity + tags）。
  - 本人 owned：优先森空岛（scripts/skland），失败回退 MAA `C:\\MAA\\data\\OperBoxData.json`。

判据（用户 2026-10-10 定）：
  ① 优先补图鉴 → P(新) = 池中未拥有数 / 池子大小 最大；
  ② 其次星级 → 同 P 时取可产出最高星级；
  ③ 高级资深干员 / 资深干员 tag 必选（脚本里它们自然会因高星级排前）。

用法：
  python scheduling/tools/recruit_combo.py                 # 枚举 1~3 词条组合
  python scheduling/tools/recruit_combo.py --max-tags 4
  python scheduling/tools/recruit_combo.py --top 80
输出：scheduling/data/recruit_combos.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
MAA_RECRUIT = pathlib.Path(r"C:\MAA\resource\recruitment.json")
MAA_BOX = pathlib.Path(r"C:\MAA\data\OperBoxData.json")
OUT = ROOT / "scheduling" / "data" / "recruit_combos.json"


def load_pool():
    d = json.loads(MAA_RECRUIT.read_text(encoding="utf-8"))
    ops = []
    for o in d["operators"]:
        ops.append({"name": o["name"], "rarity": int(o["rarity"]),
                    "tags": set(o.get("tags") or [])})
    return ops, list(d["tags"].keys())


def load_owned():
    """返回 (owned 名字集合, 来源)。优先森空岛（先自动续期），失败回退 MAA。"""
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "skland"))
        import skland_client as sk  # type: ignore
        import skland_box  # type: ignore
        cfg = sk.load_config()
        cred = cfg.get("cred")
        if cred:                     # sign_token 会话级、易过期：先续期
            try:
                tok = sk.refresh_token(cred)
                sk.save_config(cred, token=tok)
            except Exception:  # noqa: BLE001
                pass
        d = skland_box.fetch_operbox()
        own = {o["name"] for o in d.get("own_opers", []) if o.get("own")}
        if own:
            return own, "skland"
    except Exception as e:  # noqa: BLE001
        print("[recruit] 森空岛失败(%s) → 回退 MAA OperBoxData.json" % type(e).__name__)
    d = json.loads(MAA_BOX.read_text(encoding="utf-8"))
    own = {o["name"] for o in d.get("own_opers", []) if o.get("own")}
    return own, "maa"


def recommend(tags, pool, owned, topn=8, must_tags=("高级资深干员", "资深干员")):
    """在给定词条的所有子集里排序：含高级资深/资深优先 → P(新) 高 → 星级高 → 池子小。
    返回 list[dict]（tags/size/unowned/p_new/rare_min/rare_max/unowned_names）。"""
    must = [t for t in must_tags if t in tags]
    cands = []
    for k in range(1, len(tags) + 1):
        for combo in itertools.combinations(tags, k):
            cs = set(combo)
            p = [o for o in pool if cs <= o["tags"]]
            if not p:
                continue
            un = sum(1 for o in p if o["name"] not in owned)
            rar = [o["rarity"] for o in p]
            cands.append({"tags": list(combo), "size": len(p), "unowned": un,
                          "p_new": round(un / len(p), 3),
                          "rare_min": min(rar), "rare_max": max(rar),
                          "unowned_names": sorted(o["name"] for o in p
                                                  if o["name"] not in owned)[:10]})
    cands.sort(key=lambda r: (
        -(1 if any(m in r["tags"] for m in must) else 0),
        -r["p_new"], -r["rare_max"], r["size"]))
    return cands[:topn]


def parse_tags_arg(s: str):
    """把用户粘贴的词条串（支持 空格 / 逗号 / 顿号 / 换行 分隔）拆成列表。"""
    for ch in ("，", "、", ",", "\n", "\t", " "):
        s = s.replace(ch, "\x00")
    return [t for t in s.split("\x00") if t.strip()]


def main():
    ap = argparse.ArgumentParser(description="公招词条组合推荐")
    ap.add_argument("--max-tags", type=int, default=3, help="枚举到几个词条（默认 3）")
    ap.add_argument("--top", type=int, default=80, help="输出前 N 个组合")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--tags", default="",
                    help="即席推荐：直接给词条串（空格/逗号分隔），算完就退")
    args = ap.parse_args()

    ops, tags = load_pool()
    owned, src = load_owned()

    if args.tags:
        ts = parse_tags_arg(args.tags)
        print("[recruit] owned=%s(%d)｜词条：%s" % (src, len(owned), "、".join(ts)))
        hit = [t for t in ("高级资深干员", "资深干员") if t in ts]
        if hit:
            print("★ 出现：%s" % " / ".join(hit))
        for r in recommend(ts, ops, owned, topn=10):
            print("  %-24s 池%2d 未拥有%d P=%.2f ★%d~%d  %s"
                  % ("+".join(r["tags"]), r["size"], r["unowned"], r["p_new"],
                     r["rare_min"], r["rare_max"], "、".join(r["unowned_names"])))
        return
    print("[recruit] 公招池 %d 人，tag %d 个；owned 来源=%s（%d 人）"
          % (len(ops), len(tags), src, len(owned)))

    results = []
    for k in range(1, args.max_tags + 1):
        for combo in itertools.combinations(tags, k):
            cs = set(combo)
            pool = [o for o in ops if cs <= o["tags"]]
            if not pool:
                continue
            un = [o for o in pool if o["name"] not in owned]
            rar = [o["rarity"] for o in pool]
            results.append({
                "tags": list(combo),
                "size": len(pool),
                "unowned": len(un),
                "p_new": round(len(un) / len(pool), 4),
                "rare_min": min(rar),
                "rare_max": max(rar),
                "unowned_names": sorted(o["name"] for o in un)[:12],
            })

    # ① P(新) 降序 ② 最高星级降序 ③ 池子小优先
    results.sort(key=lambda r: (-r["p_new"], -r["rare_max"], r["size"]))
    top = results[: args.top]

    # 特殊词条（高级资深/资深）：用户口径「必选」→ 单独列
    special_tags = {"高级资深干员", "资深干员"}
    specials = [r for r in results if special_tags & set(r["tags"])]
    specials.sort(key=lambda r: (-r["rare_min"], -r["p_new"], r["size"]))
    specials = specials[:20]

    out = {"source": src, "owned_count": len(owned), "max_tags": args.max_tags,
           "total_combos": len(results), "combos": top, "specials": specials}
    pathlib.Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print("[recruit] 输出 %d/%d 条 -> %s" % (len(top), len(results), args.out))
    for r in top[:8]:
        print("  %-28s 池%3d 未拥%3d P=%.2f ★%d~%d"
              % ("+".join(r["tags"]), r["size"], r["unowned"], r["p_new"],
                 r["rare_min"], r["rare_max"]))


if __name__ == "__main__":
    main()
