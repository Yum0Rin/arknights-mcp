# -*- coding: utf-8 -*-
"""周报聚合 + 渲染 —— 读 revenue_ledger.jsonl → 7 日聚合 → HTML（复用 render_report 组件）。

三块模板（见 docs/收益账本与周报.md）：
  1. 本周练度提升   train[] 聚合（精英化 / 技能 / 专精 / 模组）
  2. 本周踩坑       各结算行 issues[] 汇总
  3. 下周优化       由数据启发式给出（理智去向 / 龙门币 / 固源岩 / 练度）

用法：
  python revenue_weekly.py                 # 读真实账本 → ../报告/周报.html
  python revenue_weekly.py demo            # 生成假数据跑通 → %TEMP%\\opencode\\ark\\weekly-demo.html
  python revenue_weekly.py --days 7 --out <path>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render_report as rr  # noqa: E402  复用 e() / PICO 约定
import revenue_ledger as rl  # noqa: E402

e = rr.e
REP = os.path.normpath(os.path.join(HERE, "..", "报告"))


def aggregate(entries):
    a = {
        "n": len(entries), "windows": [],
        "base": {}, "farm_materials": {}, "farm_lmd": 0, "tokens": {},
        "spend_sanity": 0.0, "meds": {}, "spend_materials": {}, "spend_lmd": 0,
        "train": [], "issues": [],
    }
    for it in entries:
        a["windows"].append(it.get("window", {}).get("end", ""))

        for fac, prods in (it.get("base") or {}).items():
            if fac == "src" or not isinstance(prods, dict):
                continue
            for k, v in prods.items():
                if isinstance(v, (int, float)):
                    a["base"][k] = a["base"].get(k, 0) + v

        f = it.get("farm") or {}
        for k, v in (f.get("材料") or {}).items():
            a["farm_materials"][k] = a["farm_materials"].get(k, 0) + v
        a["farm_lmd"] += f.get("龙门币", 0) or 0
        for k, v in (f.get("活动代币") or {}).items():
            a["tokens"][k] = a["tokens"].get(k, 0) + v

        s = it.get("spend") or {}
        a["spend_sanity"] += s.get("理智", 0) or 0
        for k, v in (s.get("理智药") or {}).items():
            a["meds"][k] = a["meds"].get(k, 0) + v
        for k, v in (s.get("材料") or {}).items():
            a["spend_materials"][k] = a["spend_materials"].get(k, 0) + v
        a["spend_lmd"] += s.get("龙门币", 0) or 0

        a["train"].extend(it.get("train") or [])
        a["issues"].extend(it.get("issues") or [])
    return a


def filter_days(entries, days):
    """只保留距最近结算 end 不超过 days 天的行（相对账本自身最新，而非今天）。"""
    ends = [rl._parse_iso((it.get("window") or {}).get("end")) for it in entries]
    ends = [x for x in ends if x]
    if not ends:
        return entries
    cut = max(ends) - dt.timedelta(days=days)
    out = []
    for it in entries:
        end = rl._parse_iso((it.get("window") or {}).get("end"))
        if end and end > cut:
            out.append(it)
    return out


FIELD_ORDER = ["new", "elite", "level", "skill_1", "skill_2", "skill_3",
               "spec_1", "spec_2", "spec_3", "mod_1", "mod_2", "mod_3"]


def _field_label(f, c):
    if f == "new":
        return "新获得"
    if f == "elite":
        return "精%s→精%s" % (c["from"], c["to"])
    if f == "level":
        return "Lv%s→Lv%s" % (c["from"], c["to"])
    if f.startswith("skill_"):
        return "技能%s Lv%s→Lv%s" % (f[-1], c["from"], c["to"])
    if f.startswith("spec_"):
        return "技能%s 专%s→专%s" % (f[-1], c["from"], c["to"])
    if f.startswith("mod_"):
        return "模组%s %s→%s" % (f[-1], c["from"], c["to"])
    return "%s %s→%s" % (f, c["from"], c["to"])


def summarize_train(train):
    """按干员+字段折叠成「净变化」（首 from → 末 to），再分类计数。"""
    by = {}
    for c in train:
        name, f = c.get("name"), c.get("field")
        if not name or not f:
            continue
        d = by.setdefault(name, {})
        if f not in d:
            d[f] = {"from": c.get("from"), "to": c.get("to")}
        else:
            d[f]["to"] = c.get("to")  # 取最后一次 to = 净变化
    rows = []
    for name, fields in by.items():
        order = [f for f in FIELD_ORDER if f in fields]
        order += [f for f in fields if f not in FIELD_ORDER]  # 兼容旧/未知字段
        labels = [_field_label(f, fields[f]) for f in order]
        rows.append({"name": name, "detail": "；".join(labels), "n": len(labels)})
    rows.sort(key=lambda r: r["n"], reverse=True)
    stat = {
        "opers": len(rows),
        "e2": sum(1 for fl in by.values() if fl.get("elite", {}).get("to") == 2),
        "skill": sum(1 for fl in by.values() for f in fl if f.startswith("skill_")),
        "spec": sum(1 for fl in by.values() for f in fl if f.startswith("spec_")),
        "mod": sum(1 for fl in by.values() for f in fl if f.startswith("mod_")),
    }
    return rows, stat


def optimize(a, days):
    out = []
    san_day = a["spend_sanity"] / max(1, days)
    out.append("本周理智消耗 ≈ %s/日（%d 日共 %s）。周预算 1920 理智，按 240/日 估。"
               % (round(san_day), days, round(a["spend_sanity"])))
    net_lmd = a["farm_lmd"] - a["spend_lmd"]
    if net_lmd < 0:
        out.append("龙门币净流出 %s → 下周优先 CE-6 补龙门币，或把一座制造站改产赤金。"
                   % f"{-net_lmd:,}")
    elif a["farm_lmd"] > 0:
        out.append("龙门币净入 %s，可维持现状。" % f"{net_lmd:,}")
    rock = a["spend_materials"].get("固源岩", 0)
    if rock > 0:
        out.append("本周耗固源岩 %s → 若继续搓玉，下周留 ≥377 理智给 1-7（≈92.4/日缺口）。" % rock)
    if a["tokens"]:
        t = "、".join("%s +%s" % (k, v) for k, v in a["tokens"].items())
        out.append("活动代币累计 %s；按商店优先级先换家具满、再龙门币。" % t)
    if not a["train"]:
        out.append("本周无练度提升 → 下周从抄作业刚需（E0/E1 高出现率）里挑 1~2 名精二。")
    if a["issues"]:
        out.append("本周有 %d 条踩坑（见「本周踩坑」）→ 下周执行前先核对清单。" % len(a["issues"]))
    return out


def _tbl(headers, rows):
    h = "".join(f"<th>{e(x)}</th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<div class='tbl-wrap'><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>"


def render_html(a, days, box_total=None):
    rows, stat = summarize_train(a["train"])
    train_rows = [[f"<b>{e(r['name'])}</b>", e(r["detail"])] for r in rows] or [["—", "本周无"]]

    base_keys = sorted(a["base"])
    base_rows = [[e(k), f"{a['base'][k]:,}"] for k in base_keys] or [["—", "—"]]

    mat_rows = []
    for k in sorted(set(a["farm_materials"]) | set(a["spend_materials"])):
        got = a["farm_materials"].get(k, 0)
        used = a["spend_materials"].get(k, 0)
        mat_rows.append([e(k), (f"+{got:,}" if got else "—"), (f"-{used:,}" if used else "—")])
    if not mat_rows:
        mat_rows = [["—", "—", "—"]]

    issue_items = "".join(f"<li>{e(x)}</li>" for x in a["issues"]) or "<li class='muted'>本周无</li>"
    opt_items = "".join(f"<li>{e(x)}</li>" for x in optimize(a, days))

    body = f"""
<header>
  <h1>明日方舟 · 本周收益/练度周报</h1>
  <p class="muted">结算窗 {e(a['windows'][0] if a['windows'] else '—')} ~ {e(a['windows'][-1] if a['windows'] else '—')}
   | 覆盖 {a['n']} 个 04:00 结算段 | 生成 {dt.date.today().isoformat()}</p>
</header>
<nav class="tabs" id="tabs">
  <button data-tab="ov" class="active">概览</button>
  <button data-tab="train">本周练度提升</button>
  <button data-tab="issues">本周踩坑</button>
  <button data-tab="next">下周优化</button>
</nav>

<div class="tabpanel active" id="tab-ov">
  <section><h2>本周收益概览</h2>
  <p>理智消耗 ≈ <b>{round(a['spend_sanity'])}</b>　|　获取材料 {len(a['farm_materials'])} 种
     |　练度变化 <b>{stat['opers']}</b> 名干员（精二 {stat['e2']}·技能 {stat['skill']}·专精 {stat['spec']}·模组 {stat['mod']}）</p>
  <h3>基建收益（副手简报口径，累计）</h3>{_tbl(["产物", "本周累计"], base_rows)}
  <h3>刷关所得 / 消耗（仓库差分口径）</h3>{_tbl(["物品", "刷关所得", "消耗"], mat_rows)}
  <p class="muted">龙门币：刷关/贸易入 {a['farm_lmd']:,}，消耗 {a['spend_lmd']:,}。理智药：{e(a['meds'] or '无')}。</p>
  </section>
</div>

<div class="tabpanel" id="tab-train">
  <section><h2>本周练度提升</h2>
  <p class="muted">精二 {stat['e2']} 次 · 技能升级 {stat['skill']} 次 · 专精 {stat['spec']} 次 · 模组 {stat['mod']} 次。</p>
  {_tbl(["干员", "变化"], train_rows)}
  </section>
</div>

<div class="tabpanel" id="tab-issues">
  <section><h2>本周踩坑</h2><ul>{issue_items}</ul></section>
</div>

<div class="tabpanel" id="tab-next">
  <section><h2>下周优化</h2><ul>{opt_items}</ul></section>
</div>

<footer><p class="muted">本地周报 · arknights-mcp/scheduling · 数据源：副手简报 OCR + Depot 差分 + 森空岛练度差分</p></footer>

<script>
(function(){{
  var btns=document.querySelectorAll('#tabs button');
  btns.forEach(function(b){{b.addEventListener('click',function(){{
    btns.forEach(function(x){{x.classList.remove('active');}});
    document.querySelectorAll('.tabpanel').forEach(function(x){{x.classList.remove('active');}});
    b.classList.add('active');
    var p=document.getElementById('tab-'+b.getAttribute('data-tab')); if(p)p.classList.add('active');
    window.scrollTo(0,0);
  }});}});
}})();
</script>
"""
    css = """
:root{--pico-font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;
 --pico-primary:#C03A2B;--pico-primary-hover:#a52f22;--pico-primary-background:#C03A2B;--pico-primary-hover-background:#a52f22;--pico-primary-underline:#C03A2B}
h1{color:#C03A2B} h2{color:#2F4858;border-bottom:2px solid #E8DCC8;padding-bottom:.3rem}
h3{color:#2F4858} h4{color:#444;margin-bottom:.2rem}
table{font-size:.92rem} th{background:#2F4858;color:#fff}
.tbl-wrap{overflow-x:auto} td.nw,th.nw{white-space:nowrap} th,td{vertical-align:top}
nav.tabs{display:flex;flex-wrap:wrap;gap:.4rem;position:sticky;top:0;z-index:20;background:var(--pico-background-color,#fff);padding:.55rem 0;margin:.4rem 0 1rem;border-bottom:1px solid #E8DCC8}
nav.tabs button{margin:0;width:auto;padding:.35rem .9rem;font-size:.9rem;border-radius:999px;background:#efeae2;color:#2F4858;border:1px solid #e0d8cc;box-shadow:none}
nav.tabs button.active{background:#2F4858;color:#fff;border-color:#2F4858}
.tabpanel{display:none}.tabpanel.active{display:block}.muted{color:#777}section{margin-bottom:2rem}
"""
    pico = open(rr.PICO, encoding="utf-8").read()
    return (f"<!doctype html><html lang=\"zh-CN\" data-theme=\"light\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>明日方舟 · 本周周报</title>"
            f"<style>{pico}</style><style>{css}</style></head>"
            f"<body><main class=\"container\">{body}</main></body></html>")


def text_report(a, days):
    rows, stat = summarize_train(a["train"])
    L = []
    L.append("【本周练度提升】")
    if rows:
        for r in rows:
            L.append("  - %s：%s" % (r["name"], r["detail"]))
    else:
        L.append("  - 无")
    L.append("【本周踩坑】")
    L.extend(["  - " + x for x in a["issues"]] or ["  - 无"])
    L.append("【下周优化】")
    L.extend(["  - " + x for x in optimize(a, days)])
    return "\n".join(L)


def demo_entries():
    base_days = [
        "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06",
        "2026-10-07", "2026-10-08", "2026-10-09",
    ]
    ents = []
    for i, d in enumerate(base_days):
        nxt = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
        ent = {
            "schema": 1,
            "window": {"start": d + "T04:00", "end": nxt + "T04:00"},
            "ts": nxt + "T04:05",
            "base": {"贸易站": {"合成玉": 972, "龙门币": 0},
                     "制造站": {"赤金": 106, "源石碎片": 63, "作战记录": 61},
                     "src": "副手简报OCR"},
            "farm": {"stage": "YW-6", "runs": 20,
                     "活动代币": {"act52side": 400},
                     "材料": {"全新装置": 24 if i % 2 == 0 else 18},
                     "龙门币": 0},
            "spend": {"理智": [480, 360, 480, 240, 480, 480, 300][i],
                      "理智药": {"应急理智浓缩液": 1} if i in (2, 5) else {},
                      "材料": {"固源岩": 92},
                      "龙门币": 34642},
            "train": [],
        }
        if i == 0:
            ent["train"] = [{"name": "德克萨斯", "field": "elite", "from": 1, "to": 2}]
        if i == 2:
            ent["train"] = [{"name": "夜莺", "field": "skill_2", "from": 7, "to": 8}]
        if i == 3:
            ent["train"] = [{"name": "伊芙利特", "field": "spec_2", "from": 0, "to": 1}]
        if i == 5:
            ent["train"] = [{"name": "德克萨斯", "field": "skill_2", "from": 7, "to": 8},
                            {"name": "澄闪", "field": "elite", "from": 1, "to": 2}]
        if i == 2:
            ent["issues"] = ["YW-6 第 3 次二星，代币少拿 20。"]
        if i == 4:
            ent["issues"] = ["基建换班漏跑，贸易站停了约 2h。"]
        ents.append(ent)
    return ents


def main():
    ap = argparse.ArgumentParser(description="收益周报聚合 + 渲染")
    ap.add_argument("mode", nargs="?", default="real", choices=["real", "demo"])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--in", dest="inp", default=rl.LEDGER)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.mode == "demo":
        entries = demo_entries()
        out = args.out or os.path.join(rl.SNAP_DIR, "weekly-demo.html")
    else:
        entries = rl.read_all(args.inp)
        out = args.out or os.path.join(REP, "周报.html")

    entries = filter_days(entries, args.days)
    a = aggregate(entries)
    rl._ensure(out)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_html(a, args.days))
    print("wrote", out, len(entries), "entries")
    print(text_report(a, args.days))


if __name__ == "__main__":
    main()
