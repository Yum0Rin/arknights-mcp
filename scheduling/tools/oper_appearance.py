#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
干员培养推荐（按「挂机作业出现率」）
====================================
从 MAA 作业站 prts.maa.plus 抓大量**挂机类作业**，统计每个干员的出现次数/频率，
再和本人干员箱(OperBoxData.json)对照 → 推荐「应优先培养」的干员。

口径：高频出现 = 以后各关都能抄到，练它收益最大。
- 必选干员(作业顶层的 opers) 计入出现率；替选组(groups 成员)单独统计(可选)。
- 只看挂机作业：作业站查询 `document=挂机`（标题/详情含"挂机"）。

用法：
  python oper_appearance.py                 # 抓 1500 个热门挂机作业统计
  python oper_appearance.py --pages 25      # 更多
  python oper_appearance.py --kw 挂机 --order views
产出：oper_appearance.json + 控制台排行（含"该练哪些"）。
"""
from __future__ import annotations
import argparse, json, urllib.request, urllib.parse, sys, pathlib, os

PRTS = "https://prts.maa.plus"
HERE = pathlib.Path(__file__).resolve().parent
BOX = pathlib.Path(os.environ.get("ARK_MAA_PATH", r"C:\MAA")) / "data" / "OperBoxData.json"


def q(**kw):
    kw.setdefault("page", 1); kw.setdefault("limit", 100); kw.setdefault("type", "PRTS")
    url = PRTS + "/copilot/query?" + urllib.parse.urlencode(kw)
    req = urllib.request.Request(url, headers={"User-Agent": "arknights-mcp/oper-appearance"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def load_box():
    if not BOX.exists():
        return {}
    d = json.load(open(BOX, encoding="utf-8"))
    return {o["name"]: o for o in d["own_opers"] if o.get("own")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=15)
    ap.add_argument("--kw", default="挂机", help="标题/详情关键字(document)，留空=不筛")
    ap.add_argument("--order", default="views", help="views / hot / hot_score")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    req_total, req = {}, {}
    grp_total = {}
    got = 0
    for page in range(1, args.pages + 1):
        kw = dict(document=args.kw, orderBy=args.order, desc="true", page=page, limit=100, type="PRTS")
        if not args.kw:
            kw.pop("document")
        try:
            d = q(**kw)
        except Exception as e:
            print("page %d ERR %s" % (page, e)); break
        data = d["data"]["data"]
        if not data:
            break
        for it in data:
            try:
                c = json.loads(it["content"])
            except Exception:
                continue
            got += 1
            for o in c.get("opers", []) or []:
                req[o["name"]] = req.get(o["name"], 0) + 1
            for g in c.get("groups", []) or []:
                for m in g.get("opers", []) or []:
                    grp_total[m["name"]] = grp_total.get(m["name"], 0) + 1
    print("样本作业数：%d（关键字=%r，order=%s）" % (got, args.kw, args.order))
    if not got:
        return
    box = load_box()

    def status(n):
        o = box.get(n)
        if not o:
            return "缺"
        return "E2" if o.get("elite", 0) >= 2 else "E%d" % o.get("elite", 0)

    rank = sorted(req.items(), key=lambda kv: -kv[1])
    out = []
    for name, cnt in rank:
        out.append({"name": name, "required_count": cnt, "required_rate": round(cnt / got, 4),
                    "group_count": grp_total.get(name, 0), "status": status(name)})
    json.dump({"sample": got, "kw": args.kw, "order": args.order, "opers": out},
              open(HERE / "oper_appearance.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("\n[挂机作业 必选干员 出现率 TOP%d]" % args.top)
    print("  %-10s %6s %6s  %s" % ("干员", "次数", "出现率", "我的练度"))
    for name, cnt in rank[:args.top]:
        print("  %-10s %6d %5.1f%%  %s" % (name, cnt, 100 * cnt / got, status(name)))

    print("\n[建议培养：出现率高 但 我还没精二]")
    rec = [(n, c) for n, c in rank if box.get(n) and box[n].get("elite", 0) < 2]
    for name, cnt in rec[:args.top]:
        o = box[name]
        print("  %-10s 出现%d(%.1f%%)  现%selite Lv%s" % (name, cnt, 100 * cnt / got, o.get("elite"), o.get("level")))
    if not rec:
        print("  （高出现率干员均已精二）")
    lack = [(n, c) for n, c in rank[:args.top] if n not in box]
    if lack:
        print("\n[缺(未拥有) 但出现率高]：" + "、".join("%s(%d)" % (n, c) for n, c in lack))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
