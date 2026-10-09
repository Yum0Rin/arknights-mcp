# -*- coding: utf-8 -*-
"""把 report_data.json + 一图流预览图 + Pico.css 渲染成自包含单文件 index.html。

用法：
    python render_report.py
输出：../报告/index.html（离线可开，含内联图片与 CSS）
"""
import json, os, base64, html

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "一图流产物"))
REP = os.path.normpath(os.path.join(HERE, "..", "报告"))
DATA = os.path.join(HERE, "report_data.json")
PICO = r"C:\Users\<user>\AppData\Local\Temp\opencode\pico.min.css"
PREVIEW = os.path.join(SRC, "243-搓玉-预览图.png")
PREVIEW_LMD = os.path.join(SRC, "243-钱书均衡-预览图.png")

FAC = {"control": "控制中枢", "trading": "贸易站", "manufacture": "制造站",
       "power": "发电站", "meeting": "会客室", "hire": "办公室",
       "dormitory": "宿舍", "processing": "加工站", "training": "训练室"}
PROD = {"LMD": "龙门币", "Battle Record": "经验书", "Pure Gold": "赤金",
        "Originium Shard": "源石碎片", "Orundum": "合成玉", "Combat Record": "作战记录"}


def e(x):
    return html.escape(str(x), quote=True)


def room_rows(plan_plan):
    rows = []
    rooms = plan_plan.get("rooms", {})
    order = ["control", "trading", "manufacture", "power", "meeting", "hire",
             "processing", "training", "dormitory"]
    for key in order:
        for idx, r in enumerate(rooms.get(key, []) or [], 1):
            ops = r.get("operators", []) or []
            prod = PROD.get(r.get("product", ""), r.get("product", "")) if r.get("product") else ""
            label = FAC.get(key, key) + (f" {idx}" if len(rooms.get(key, [])) > 1 else "")
            if key == "dormitory":
                ops_txt = "自动填充" if r.get("autofill") else "、".join(ops)
            else:
                ops_txt = "、".join(ops) if ops else "—"
            rows.append((label, prod, ops_txt))
    return rows


def render_plan_shifts(manifest):
    out = []
    for pl in manifest.get("plans", []):
        rows = room_rows(pl)
        drones = pl.get("drones", {})
        drone_txt = ""
        if drones.get("enable"):
            drone_txt = f"无人机：{FAC.get(drones.get('room',''), drones.get('room','')) } #{drones.get('index','')}（{drones.get('order','')}）"
        trs = "".join(
            f"<tr><td>{e(a)}</td><td>{e(b)}</td><td>{e(c)}</td></tr>" for a, b, c in rows)
        cls = "班" if False else ""
        out.append(
            f"<h4>{e(pl.get('name'))} <small>{e(pl.get('duration'))} 分钟</small></h4>"
            f"<p class='muted'>{e(drone_txt)}</p>"
            f"<table><thead><tr><th>设施</th><th>产品</th><th>干员</th></tr></thead>"
            f"<tbody>{trs}</tbody></table>")
    return "".join(out)


def render_compare(plans):
    keys = ["龙门币", "经验", "合成玉", "赤金", "源石碎片", "黄票", "绿票"]
    head = "".join(f"<th>{e(p['name'])}</th>" for p in plans)
    body = ""
    for k in keys:
        cells = "".join(f"<td>{e(p['daily'].get(k, '—'))}</td>" for p in plans)
        body += f"<tr><th>{e(k)}/日</th>{cells}</tr>"
    # 资源结余
    body += "<tr><td colspan='%d'><em>资源产出与消耗（一图流口径）</em></td></tr>" % (len(plans) + 1)
    allkeys = []
    for p in plans:
        for k in p["resources"]:
            if k not in allkeys:
                allkeys.append(k)
    for k in allkeys:
        cells = "".join(f"<td>{e(p['resources'].get(k, '—'))}</td>" for p in plans)
        body += f"<tr><th>{e(k)}</th>{cells}</tr>"
    return f"<table><thead><tr><th>产出项</th>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_sanity(sp):
    p, pl, a = sp["params"], sp["plans"], sp["anni"]
    g, o = pl["grow6"], pl["orundum"]

    def row(k, v, u=""):
        return f"<tr><td>{e(k)}</td><td>{e(v)}{e(u)}</td></tr>"

    params = (
        "<ul>"
        f"<li>周理智预算 = 自然 {e(p['regenPerDay'])}×7 + 周常浓缩液×2 = <b>{e(p['weeklyBudget'])}</b> 理智</li>"
        f"<li>理智上限(99级) <b>{e(p['sanityCap'])}</b>；每 12h 回复 {e(p['regenPerInterval'])}（&lt; 上限）→ 每次上线把理智花到 "
        f"<b>≤{e(p['safeLeaveBelow'])}</b> 即不溢出；道具可临时突破上限(≤999)</li>"
        f"<li>剿灭当期：{e(a['san_per_run'])} 理智/次 ≈ {e(a['orundum_per_run'])} 合成玉/次，周上限 {e(a['week_cap'])} "
        f"→ 打满约 {e(g['allocation']['anniRuns'])} 次 = {e(g['allocation']['anni'])} 理智</li>"
        f"<li>CE-6：36 理智 = 10000 龙门币　|　LS-6：36 理智 = 10000 经验　|　1-7：6 理智 ≈ 1.245 固源岩（≈4.82 理智/个）</li>"
        f"<li>每日任务：龙门币 9500/天 + 合成玉 100/天；每周任务：龙门币 2.3 万 + 合成玉 500 + 浓缩液×2（=240 理智）</li>"
        "</ul>")
    grow = ("<table><thead><tr><th>项</th><th>数值/周</th></tr></thead><tbody>"
            + row("剿灭（合成玉打满 1800）", g["allocation"]["anni"], " 理智")
            + row("CE-6（龙门币）", g["allocation"]["ce"], " 理智")
            + row("LS-6（经验）", g["allocation"]["ls"], " 理智")
            + row("基地+任务 龙门币", f"{g['fromBaseAndTasks']['lmd']:,}")
            + row("基地+任务 经验", f"{g['fromBaseAndTasks']['exp']:,}")
            + row("<b>合计 龙门币</b>", f"<b>{g['total']['lmd']:,}</b>")
            + row("<b>合计 经验</b>", f"<b>{g['total']['exp']:,}</b>")
            + row("<b>≈ 可养 6★（精0Lv1→精2Lv1）</b>", f"<b>{g['sixStarEquivPerWeek']}</b>", " 个/周")
            + row("合成玉合计（含剿灭+任务）", f"{g['orundumPerWeek']:,}")
            + "</tbody></table>")
    oru = ("<table><thead><tr><th>项</th><th>数值/周</th></tr></thead><tbody>"
           + row("剿灭（合成玉打满 1800）", o["allocation"]["anni"], " 理智")
           + row("1-7（刷固源岩）", o["allocation"]["stage17"], " 理智")
           + row("固源岩", o["rockPerWeek"], " 个")
           + row("源石碎片", o["shardsPerWeek"], " 个")
           + row("搓玉合成玉", f"{o['craftOrundum']:,}")
           + row("<b>合成玉合计（含剿灭+任务）</b>", f"<b>{o['orundumTotalPerWeek']:,}</b>")
           + "</tbody></table>")
    return (f"<details open><summary>参数</summary>{params}</details>"
            f"<details><summary>方案 A · 养成向（6★配比 LMD:EXP≈1.63）</summary>{grow}</details>"
            f"<details><summary>方案 B · 搓玉向（合成玉优先）</summary>{oru}</details>")


def render_sources(sp):
    def tbl(headers, rows):
        h = "".join(f"<th>{e(x)}</th>" for x in headers)
        b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
        return f"<div class='tbl-wrap'><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>"

    orundum = tbl(["来源", "量/周", "说明"], [
        ["剿灭作战", "1,800", "当期 25 理智/次 ≈370 玉/次，打满约 5 次 = 125 理智（周上限 1800）"],
        ["每日任务", "700", "100/天 ×7"],
        ["每周任务", "500", ""],
        ["基建搓玉", "0 ~ 3,402", "贸易站卖源石碎片 → 合成玉；产能受<b>固源岩供给</b>约束"],
        ["└ 全周刷 1-7 可支撑", "≈1,860", "1795 理智 → 372 固源岩 → 186 源石碎片 → 1,860 玉"],
        ["<b>小计（养成向）</b>", "<b>3,000</b>", "剿灭 + 每日 + 每周（不搓玉）"],
        ["<b>小计（搓玉向）</b>", "<b>≈4,862</b>", "含搓玉 ≈1,860"],
    ])
    lmd = tbl(["来源", "量/周", "说明"], [
        ["基建（钱书均衡）", "390,985", "55,855 龙门币/天（贸易站卖赤金）"],
        ["每日任务", "66,500", "9,500/天 ×7"],
        ["每周任务", "23,000", ""],
        ["CE-6（刷取）", "按理智", "36 理智 = 10,000（277.8 龙门币/理智）"],
        ["<b>小计（不含刷取）</b>", "<b>480,485</b>", ""],
    ])
    exp = tbl(["来源", "量/周", "说明"], [
        ["基建（钱书均衡）", "212,121", "30,303 经验/天（制造站产作战记录）"],
        ["每日任务", "67,200", "8 基础 + 5 初级 + 6 中级 = 9,600 经验/天"],
        ["每周任务", "24,400", "4 基础 + 4 初级 + 4 中级 + 9 高级"],
        ["LS-6（刷取）", "按理智", "36 理智 = 10,000（277.8 经验/理智）"],
        ["<b>小计（不含刷取）</b>", "<b>303,721</b>", ""],
    ])
    san = tbl(["来源", "量/周", "说明"], [
        ["自然回复", "1,680", "240/天（6 分钟 1 点）；上限 205，12h 回复 120"],
        ["周常 · 应急理智浓缩液 ×2", "240", "120 × 2"],
        ["每日任务 / 绿票商店", "0", "均不给理智"],
        ["<b>合计</b>", "<b>1,920</b>", ""],
    ])
    mat = tbl(["资源", "来源", "说明"], [
        ["固源岩", "关卡 1-7", "6 理智 ≈ 1.245 个（≈4.82 理智/个）；也可加工/其它关"],
        ["源石碎片", "制造站", "2 固源岩 → 1 源石碎片"],
        ["合成玉", "贸易站", "1 源石碎片 → 10 合成玉（搓玉）"],
        ["赤金", "制造站", "产赤金 → 龙门币贸易站卖出得龙门币"],
        ["作战记录", "制造站 / 关卡 LS / 任务", "产经验"],
    ])
    return (f"<details open><summary>合成玉来源（周）</summary>{orundum}</details>"
            f"<details><summary>龙门币来源（周）</summary>{lmd}</details>"
            f"<details><summary>经验（作战记录）来源（周）</summary>{exp}</details>"
            f"<details><summary>理智来源（周）</summary>{san}</details>"
            f"<details><summary>其它资源链路</summary>{mat}</details>")


def render_training(rows):
    body = ""
    for r in rows:
        b = r.get("before_skill")
        if not b:
            before = "<span class='muted'>无</span>"
        else:
            bp = b.get("pct") or ""
            before = f"<small>{e(b.get('skill'))}</small>" + (f"<br><b>{e(bp)}%</b>" if bp else "")
        ap = (r.get("after_pct") or "")
        after = f"<small>{e(r.get('after_skill'))}</small>" + (f"<br><b>{e(ap)}%</b>" if ap else "")
        flag = {"ok": "★ 推荐", "warn": "○ 可选", "bad": "✗ 不推荐"}[r["rec"]]
        body += (f"<tr class='{r['rec']}'><td><b>{e(r['name'])}</b><br><small class='muted'>{e(r['target'])}</small></td>"
                 f"<td class='nw'>{e(r['facility'])}</td>"
                 f"<td>{before}</td><td>{after}</td>"
                 f"<td class='nw'>{flag}</td><td class='nw'>{e(r.get('sanity'))}</td></tr>")
    return ("<div class='tbl-wrap'><table><thead><tr><th>干员 / 目标</th><th>设施</th>"
            "<th>培养前（当前技能）</th><th>培养后（新增/升级加成）</th><th>推荐</th><th>理智</th>"
            f"</tr></thead><tbody>{body}</tbody></table></div>")


EST = {"龙门币型": ("龙门币", 280), "经验书型": ("经验", 150), "合成玉型": ("合成玉", 5)}


def render_board(rows):
    order = ["龙门币型", "经验书型", "合成玉型", "通用制造型", "发电型", "办公型", "其它"]

    def val(r):
        return r.get("net_pct") if r.get("net_pct") is not None else -999

    def est(r):
        c, n = r.get("category"), r.get("net_pct")
        if n is None or c not in EST:
            return "—"
        nm, f = EST[c]
        return f"+{round(n * f):,} {nm}/天"

    groups = {}
    for r in rows:
        groups.setdefault(r.get("category", "其它"), []).append(r)
    out = []
    for cat in order:
        if cat not in groups:
            continue
        lst = sorted(groups[cat], key=val, reverse=True)
        trs = ""
        for i, r in enumerate(lst, 1):
            n = r.get("net_pct")
            ns = f"{n:g}" if n is not None else "—"
            flag = {"ok": "★", "warn": "○", "bad": "✗"}[r["rec"]]
            trs += (f"<tr class='{r['rec']}'><td>{i}</td><td><b>{e(r['name'])}</b></td>"
                    f"<td class='nw'>{e(r['facility'])}</td>"
                    f"<td class='nw'><b>+{e(ns)}</b></td><td class='nw'>{e(est(r))}</td>"
                    f"<td class='nw'>{flag}</td></tr>")
        out.append(f"<h4>{e(cat)}（{len(lst)}）</h4>"
                   f"<div class='tbl-wrap'><table><thead><tr><th>#</th><th>干员</th><th>设施</th>"
                   f"<th>净增(点)</th><th>估算创收/天</th><th>荐</th></tr></thead><tbody>{trs}</tbody></table></div>")
    return "".join(out)


def main():
    data = json.load(open(DATA, encoding="utf-8"))
    training = json.load(open(os.path.join(HERE, "training.json"), encoding="utf-8"))
    sp = json.load(open(os.path.join(HERE, "sanity_plan.json"), encoding="utf-8"))
    pico = open(PICO, encoding="utf-8").read()
    img_b64 = base64.b64encode(open(PREVIEW, "rb").read()).decode()
    img_lmd_b64 = base64.b64encode(open(PREVIEW_LMD, "rb").read()).decode()

    plans = data["plans"]
    lmd = next(p for p in plans if p["id"] == "lmd")
    oru = next(p for p in plans if p["id"] == "orundum")

    summary = f"""
    <p>基地：<b>243</b>（贸易站 2 · 制造站 4 · 发电站 3）　干员箱：<b>{e(data['boxTotal'])}</b> 名</p>
    <p class="tag-reco">你的优先级：<b>先龙门币 → 再合成玉</b>。据此推荐 <b>《钱书均衡 · 龙门币优先》</b>：
       龙门币 {e(lmd['daily'].get('龙门币'))}/日、经验 {e(lmd['daily'].get('经验'))}/日，均为两案最高。</p>
    <p>想要合成玉时才用 <b>《搓玉 · 合成玉》</b>：合成玉 {e(oru['daily'].get('合成玉'))}/日，但龙门币降到
       {e(oru['daily'].get('龙门币'))}/日、经验降到 {e(oru['daily'].get('经验'))}/日，且每日需补
       <b>固源岩 {e(oru['resources'].get('固源岩'))}</b>（靠理智刷）。</p>
    """

    sanity = """
    <h3>《钱书均衡 · 龙门币优先》的理智怎么花</h3>
    <ul>
      <li>制造站产赤金/经验书<b>不消耗</b>刷图材料，基地基本自给。</li>
      <li>注意：该案 <b>赤金净结余为负</b>（产出 73.85 / 消耗 106.86，即卖赤金换龙门币动用库存），
          建议保留一定赤金库存，或偶尔把一座制造站改产赤金回补。</li>
      <li>理智优先投 <b>精英化 / 专精 / 模组材料</b>；若龙门币仍紧，刷 <b>CE-5 / CE-6</b>（龙门币本）补。</li>
    </ul>
    <h3>《搓玉 · 合成玉》的理智怎么花</h3>
    <ul>
      <li>搓玉的合成玉来自贸易站卖源石碎片；源石碎片由制造站产，<b>需要固源岩</b>。</li>
      <li>每日缺口 <b>固源岩 ≈ 92.4</b>，必须靠理智刷（推荐 <b>1-7</b>；最优关卡随时变，
          用一图流"关卡推荐"核对）。仅靠理智自然恢复（≈240/日）较紧张 → 搓玉更适合
          "固源岩有富余/有库存"时开，别长期硬搓，否则龙门币与经验都被拖低。</li>
      <li>剩余理智再按精英化/专精材料需求分配。</li>
    </ul>
    """

    maa_lmd = base64.b64encode(json.dumps(lmd["manifest"], ensure_ascii=False).encode()).decode()
    maa_oru = base64.b64encode(json.dumps(oru["manifest"], ensure_ascii=False).encode()).decode()

    body = f"""
<header>
  <h1>明日方舟 · 基建排班报告</h1>
  <p class="muted">基地 243　|　干员箱 {e(data['boxTotal'])}　|　生成 2026-10-09　|　数据来源：MAA 识别 + 一图流 scheduleV3</p>
</header>

<nav class="tabs" id="tabs">
  <button data-tab="overview" class="active">概览</button>
  <button data-tab="shifts">排班明细</button>
  <button data-tab="sanity">理智规划</button>
  <button data-tab="grow">干员培养</button>
  <button data-tab="files">下载 / 预览</button>
</nav>

<div class="tabpanel active" id="tab-overview">
  <section>
    <h2>结论摘要</h2>
    {summary}
  </section>
  <section>
    <h2>两方案产出对比</h2>
    {render_compare(plans)}
    <p class="muted">"合成玉"仅搓玉案有；"赤金/源石碎片"为一图流口径的日结余。</p>
  </section>
</div>

<div class="tabpanel" id="tab-shifts">
  <section>
    <h2>方案明细（A/B 班）</h2>
    <h3>《{e(lmd['name'])}》</h3>
    {render_plan_shifts(lmd['manifest'])}
    <h3>《{e(oru['name'])}》</h3>
    {render_plan_shifts(oru['manifest'])}
  </section>
</div>

<div class="tabpanel" id="tab-sanity">
  <section>
    <h2>理智规划（运筹模型 · 以周为单位）</h2>
    <p class="muted">本质是"周度理智分配"优化：目标=养成产出/合成玉，约束=周理智预算、理智上限、剿灭周上限、经验:龙门币配比；每日/每周任务与剿灭奖励已计入。</p>
    {render_sanity(sp)}
    <h3>方案取向补充</h3>
    {sanity}
  </section>
  <section>
    <h2>资源来源明细（合成玉 / 龙门币 / 经验 / 理智…）</h2>
    <p class="muted">每种资源从哪来、每天/每周多少——用于核对模型输入。</p>
    {render_sources(sp)}
  </section>
</div>

<div class="tabpanel" id="tab-grow">
  <section>
    <h2>精二培养建议 · 培养前后收益提升（按技能效果算）</h2>
    <p class="muted">「培养前」= 当前练度下该设施的技能；「培养后」= 训练解锁/升级的技能加成。百分比是<strong>技能对所属设施</strong>的产能提升比例（设施级；一个设施只占基地一部分，折算到全基地总产出会更小）。部分干员是"升级技能"（如 α→β，提升较小），部分是"解锁新技能"（提升=整段加成），以技能文本为准。</p>
    {render_training(training)}
  </section>
  <section>
    <h2>干员榜（按产出类型 · 收益率排名）</h2>
    <p class="muted">把"培养建议"里的干员按产出类型归类，同类按收益率(%)降序——一眼看出各类型头名最值得优先练。收益率=训练后技能对所属设施的加成。</p>
    {render_board(training)}
  </section>
</div>

<div class="tabpanel" id="tab-files">
  <section>
    <h2>导入 MAA 用（排班协议 JSON）</h2>
    <p>两方案的排班表已导出为 MAA 可识别的 JSON，点下方按钮下载后，在 MAA「基建排班」里导入即可。</p>
    <p><a role="button" download="243-钱书均衡-龙门币优先-MAA.json" href="data:application/json;base64,{maa_lmd}">下载：钱书均衡 · 龙门币优先</a>
       <a role="button" class="secondary" download="243-搓玉-合成玉-MAA.json" href="data:application/json;base64,{maa_oru}">下载：搓玉 · 合成玉</a></p>
  </section>
  <section>
    <h2>一图流预览图</h2>
    <figure><figcaption><b>《钱书均衡 · 龙门币优先》</b></figcaption>
      <img src="data:image/png;base64,{img_lmd_b64}" alt="钱书均衡预览" style="width:100%;border-radius:8px"></figure>
    <figure><figcaption><b>《搓玉 · 合成玉》</b></figcaption>
      <img src="data:image/png;base64,{img_b64}" alt="搓玉预览" style="width:100%;border-radius:8px"></figure>
  </section>
</div>

<footer>
  <p class="muted">本地报告 · 由 arknights-mcp/scheduling 生成 · 未联网、无外部依赖</p>
</footer>

<script>
(function(){{
  var btns = document.querySelectorAll('#tabs button');
  btns.forEach(function(b){{
    b.addEventListener('click', function(){{
      btns.forEach(function(x){{ x.classList.remove('active'); }});
      document.querySelectorAll('.tabpanel').forEach(function(x){{ x.classList.remove('active'); }});
      b.classList.add('active');
      var p = document.getElementById('tab-' + b.getAttribute('data-tab'));
      if (p) p.classList.add('active');
      window.scrollTo(0, 0);
    }});
  }});
}})();
</script>
"""

    css = """
:root{
  --pico-font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;
  --pico-primary:#C03A2B; --pico-primary-hover:#a52f22;
  --pico-primary-background:#C03A2B; --pico-primary-hover-background:#a52f22;
  --pico-primary-underline:#C03A2B;
}
h1{color:#C03A2B} h2{color:#2F4858;border-bottom:2px solid #E8DCC8;padding-bottom:.3rem}
h3{color:#2F4858} h4{color:#444;margin-bottom:.2rem}
table{font-size:.92rem}
th{background:#2F4858;color:#fff}
.tbl-wrap{overflow-x:auto}
td.nw,th.nw{white-space:nowrap}
th,td{vertical-align:top}
small{line-height:1.35}
nav.tabs{display:flex;flex-wrap:wrap;gap:.4rem;position:sticky;top:0;z-index:20;background:var(--pico-background-color,#fff);padding:.55rem 0;margin:.4rem 0 1rem;border-bottom:1px solid #E8DCC8}
nav.tabs button{margin:0;width:auto;padding:.35rem .9rem;font-size:.9rem;border-radius:999px;background:#efeae2;color:#2F4858;border:1px solid #e0d8cc;box-shadow:none}
nav.tabs button.active{background:#2F4858;color:#fff;border-color:#2F4858}
.tabpanel{display:none}
.tabpanel.active{display:block}
h2{margin-top:1rem}
details{border:1px solid #E8DCC8;border-radius:8px;padding:.1rem .9rem;margin:.55rem 0;background:#FCFAF6}
details>summary{cursor:pointer;font-weight:600;color:#2F4858;padding:.55rem 0;list-style:none}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"▸ ";color:#C03A2B}
details[open]>summary::before{content:"▾ "}
tr.ok td:first-child{border-left:4px solid #3E8E5A}
tr.warn td:first-child{border-left:4px solid #C99A2E}
tr.bad td:first-child{border-left:4px solid #B0524A}
.tag-reco{background:#F7E7E5;border-left:4px solid #C03A2B;padding:.6rem .9rem;border-radius:6px}
.muted{color:#777} small{color:#666}
section{margin-bottom:2rem}
@media(max-width:640px){table{font-size:.8rem} th,td{padding:.35rem}}
"""
    doc = (f"<!doctype html><html lang=\"zh-CN\" data-theme=\"light\"><head><meta charset=\"utf-8\">"
           f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
           f"<title>明日方舟 · 基建排班报告</title>"
           f"<style>{pico}</style><style>{css}</style></head>"
           f"<body><main class=\"container\">{body}</main></body></html>")

    os.makedirs(REP, exist_ok=True)
    out = os.path.join(REP, "index.html")
    open(out, "w", encoding="utf-8").write(doc)
    print("wrote", out, len(doc), "bytes")


if __name__ == "__main__":
    main()
