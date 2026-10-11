"""单页汇总站点生成器（幂等）：把 weekly_plan / 一键长草方案 / 数据源渲染进一个 HTML。

用法：
  python scheduling/tools/build_site.py
  python scheduling/tools/build_site.py --out PATH
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
DATA = ROOT / "scheduling" / "data"
STYLE = TOOLS / "assets" / "pico.min.css"  # Pico v2.1.1（内联，离线）
PLAN_MD = ROOT / "docs" / "PLAN-一键长草.md"
REPORT_DIR = ROOT / "scheduling" / "报告"
DEFAULT_OUT = REPORT_DIR / "汇总.html"
BASE_REPORT = REPORT_DIR / "index.html"      # 基建排班报告（render_report.py 产出，若rame 内嵌）

sys.path.insert(0, str(TOOLS))
from plan_util import distribute_daily, weekly_summary, session_advice  # noqa: E402


def e(x) -> str:
    return html.escape(str(x), quote=True)


def read_text(p: Path, default: str = "") -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return default


def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def load_jsonl(p: Path) -> list:
    rows = []
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def render_markdown(p: Path) -> str:
    try:
        import markdown
    except ImportError:
        return f"<p class=\"muted\">未安装 markdown 库，无法渲染 {e(p.name)}。</p>"
    text = read_text(p)
    if not text:
        return f"<p class=\"muted\">{e(str(p.relative_to(ROOT)))} 不存在或为空。</p>"
    return markdown.markdown(text, extensions=["tables", "fenced_code"])


def card(title: str, body: str) -> str:
    return f"<article class=\"card\"><h3>{e(title)}</h3>{body}</article>"


RECRUIT_TOOL = """
<article class="card" style="margin:.8rem 0">
  <h3>贴词条 → 推荐</h3>
  <p class="muted">把公招刷出的词条粘进来（空格 / 逗号 / 顿号分隔）——<strong>输入即自动计算</strong>，也可点按钮/回车。
  需先起后端：<code>python scheduling/tools/site_server.py</code>。</p>
  <div style="display:flex;gap:.5rem;flex-wrap:wrap">
    <input id="taginput" placeholder="高级资深干员 输出 近战位 新手 生存" style="flex:1;min-width:260px">
    <button id="tagbtn" type="button">推荐</button>
  </div>
  <div id="tagresult" class="muted" style="margin-top:.6rem"></div>
</article>
"""


def overview_section(plan, sanity, combos) -> str:
    week = plan.get("week", "—") if plan else "—"
    rng = plan.get("range", "—") if plan else "—"

    cur = sanity.get("current_sanity", "—") if sanity else "—"
    pot = sanity.get("potion_sanity", "—") if sanity else "—"
    sanity_body = f"<p><strong>{e(cur)}</strong> 当前理智</p><p class=\"muted\">理智药 {e(pot)}</p>"

    annih = "—"
    event_stage = "—"
    if plan:
        for t in plan.get("tasks", []):
            params = t.get("params", {}) or {}
            stage = str(params.get("stage", ""))
            if stage.lower() == "annihilation":
                annih = f"{params.get('times', '—')} 次"
            elif stage and "YW" in stage.upper():
                event_stage = stage + f" ×{params.get('times', '—')}"
    annih_body = f"<p><strong>{e(annih)}</strong></p>"

    window = plan.get("event_window") if plan else None
    if not window:
        window = event_stage if event_stage != "—" else "见本周安排"
    window_body = f"<p><strong>{e(window)}</strong></p>"

    cards = "".join([
        card("本周", f"<p><strong>{e(week)}</strong></p><p class=\"muted\">{e(rng)}</p>"),
        card("理智", sanity_body),
        card("剿灭", annih_body),
        card("活动窗口", window_body),
    ])
    rec = ("<details style=\"margin-top:1rem\" open>"
           "<summary>公招推荐（贴词条 → 出未拥有概率最大的组合）</summary>"
           + RECRUIT_TOOL + recruit_block(combos) + "</details>")
    return (f"<section id=\"概览\"><h2>概览</h2><div class=\"cards\">{cards}</div>"
            f"{rec}</section>")


def weekly_section(plan, sanity) -> str:
    if not plan or not plan.get("tasks"):
        return ("<section id=\"本周\"><h2>本周安排</h2>"
                "<p class=\"muted\">本周计划未生成（缺 scheduling/data/weekly_plan.json）。</p>"
                + sanity_block(sanity) + "</section>")
    rows = []
    for i, t in enumerate(plan.get("tasks", []), 1):
        typ = t.get("type", "")
        params = t.get("params", {}) or {}
        target = params.get("stage") or params.get("mode") or params.get("client_type") or "—"
        times = params.get("times")
        if times is None and params.get("enable") is not None:
            times = "开" if params.get("enable") else "关"
        if times is None:
            times = "—"
        note = t.get("name") or t.get("note") or ""
        rows.append(
            f"<tr><td>{i}</td><td>{e(typ)}</td><td>{e(target)}</td>"
            f"<td>{e(times)}</td><td>{e(note)}</td></tr>"
        )
    table = (
        "<div class=\"tbl-wrap\"><table><thead><tr>"
        "<th>序号</th><th>类型</th><th>关卡或模式</th><th>次数</th><th>说明</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )
    side = plan.get("side") or []
    side_html = ""
    if side:
        items = "".join(f"<li><code>{e(s.get('script', ''))}</code> — {e(s.get('when', ''))}</li>" for s in side)
        side_html = f"<h3>附带脚本</h3><ul>{items}</ul>"
    daily = distribute_daily(plan)
    daily_html = ""
    if daily:
        drows = ""
        for d in daily:
            runs = "、".join("%s ×%d" % (k, v) for k, v in (d.get("runs") or {}).items()) or "—"
            if d.get("opens"):
                runs += "　<span style=\"color:#C03A2B\">★本日新开：%s</span>" % e("、".join(d["opens"]))
            sstyle = " style=\"color:#C03A2B;font-weight:700\"" if d.get("over") else ""
            drows += ("<tr><td>%s</td><td>%s</td><td>%s</td><td%s>%s%s</td></tr>"
                      % (e(d.get("date", "")), e(d.get("dow", "")), runs, sstyle,
                         e(d.get("sanity", 0) or 0),
                         "（超上限 %s）" % e(d.get("cap", 240)) if d.get("over") else ""))
        sm = weekly_summary(plan, daily)
        line = ("<p>本周合计 <strong>%d</strong> 理智；自然预算 %s + 周常药 %s"
                % (sm["total"], sm["natural"], sm["weekly_potion"]))
        if sm.get("meds"):
            line += " + 理智药存量 %s" % sm["meds"]
        line += " = <strong>%s</strong>。" % sm["avail"]
        if sm["gap"]:
            line += "　<span style=\"color:#C03A2B\">缺口 %d（需靠理智药）</span>" % sm["gap"]
        else:
            line += "　够。"
        if sm["over_days"]:
            line += "　标红的日子当天会超自然回复，需吃理智药。"
        line += "</p>"
        # 上线建议（不浪费自动回复）
        srows = ""
        for s in session_advice(plan, daily):
            srows += ("<tr><td>%s %s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                      % (e(s.get("date", "")), e(s.get("dow", "")), e(s.get("sanity", 0)),
                         e(s.get("sessions", 0)), e(s.get("note", ""))))
        line += ('<h4>上线建议（不浪费自动回复）</h4>'
                 '<p class="muted">上限 205、每 12h 回 120 → 常规 <strong>每 12h 上线一次</strong>，'
                 '每次花到 ≤85（12h 后刚好回满、不溢出）。</p>'
                 '<div class="tbl-wrap"><table><thead><tr><th>日期</th><th>当天理智</th>'
                 '<th>建议上线次数</th><th>备注</th></tr></thead><tbody>'
                 + srows + '</tbody></table></div>')
        daily_html = ('<h3>每日安排</h3><div class="tbl-wrap"><table><thead><tr>'
                      '<th>日期</th><th>星期</th><th>刷关</th><th>理智</th></tr></thead><tbody>'
                      + drows + '</tbody></table></div>' + line)
    tr = plan.get("training")
    train_html = ""
    if tr:
        grows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (e(g.get("name")), e(g.get("qty")), e(g.get("stock", 0)), e(g.get("sanity")))
            for g in tr.get("top_gaps", []))
        train_html = (
            "<h3>培养进度</h3>"
            "<p>目标：<strong>%s</strong>；总缺口 <strong>%s</strong> 理智"
            "（材料 %s + 精英化龙门币 %s）；本周投 <strong>%s</strong> 理智%s</p>"
            '<div class="tbl-wrap"><table><thead><tr><th>缺的材料</th><th>需</th>'
            '<th>库存已抵</th><th>还需理智</th></tr></thead><tbody>%s</tbody></table></div>'
            % (e("、".join(tr.get("targets", []))), e(tr.get("total_sanity")),
               e(tr.get("material_sanity")), e(tr.get("lmd_sanity")), e(tr.get("week_sanity")),
               ("（还需约 %s 周）" % tr["need_weeks"]) if tr.get("need_weeks") else "",
               grows))
    return (f"<section id=\"本周\"><h2>本周安排</h2>{table}{daily_html}"
            f"{train_html}{side_html}{sanity_block(sanity)}</section>")


def recruit_block(combos) -> str:
    """公招词条参考（不放独立页，作为概览里的折叠块）。"""
    if not combos or not combos.get("combos"):
        return ("<p class=\"muted\">公招词条数据待接入（跑 "
                "<code>python scheduling/tools/recruit_combo.py</code>）。</p>")

    def table(rows):
        body = "".join(
            "<tr><td>%s</td><td>%d</td><td>%d</td><td>%s</td><td>★%d~%d</td></tr>"
            % (e("+".join(r.get("tags", []))), r.get("size", 0), r.get("unowned", 0),
               ("%.0f%%" % (100 * r.get("p_new", 0))), r.get("rare_min", 0), r.get("rare_max", 0))
            for r in rows)
        return ('<div class="tbl-wrap"><table><thead><tr><th>词条组合</th><th>池子</th>'
                '<th>未拥有</th><th>P(新)</th><th>星级</th></tr></thead><tbody>'
                + body + '</tbody></table></div>')

    meta = ("<p class=\"muted\">公招池 160 人；owned 来源 <strong>%s</strong>（%d 人）；"
            "枚举 %d 个组合。判据：P(新)=池中未拥有/池大小，同 P 取高星。"
            "<br>※ 仅在公招刷出「高级资深干员」等好词条时才需要查这张表。"
            % (e(combos.get("source", "?")), combos.get("owned_count", 0),
               combos.get("total_combos", 0)))
    sp = combos.get("specials") or []
    rec = combos.get("combos") or []
    sp_html = ("<h3>特殊词条（必选）</h3>" + table(sp)) if sp else ""
    return (meta + sp_html + "<h3>推荐组合（按 P(新) 排序）</h3>" + table(rec))


def sanity_block(sanity) -> str:
    """理智药读数（并入「本周」，不单列一页）。"""
    if not sanity:
        return "<p class=\"muted\">理智药：数据待接入（缺 sanity.json）。</p>"
    rows = []
    zh = {"current_sanity": "当前理智", "theoretical_total": "全用后理论理智",
          "potion_sanity": "理智药合计"}
    for key in ("current_sanity", "theoretical_total", "potion_sanity"):
        if key in sanity:
            rows.append(f"<tr><td>{e(zh.get(key, key))}</td><td>{e(sanity[key])}</td></tr>")
    for k, v in sanity.items():
        if k in ("current_sanity", "theoretical_total", "potion_sanity"):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            rows.append(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>")
    table = ("<div class=\"tbl-wrap\"><table><tbody>" + "".join(rows) + "</tbody></table></div>")
    return "<h3>理智药</h3>" + table


def _fmt(v) -> str:
    """把嵌套 dict/list 压成一行可读文本。"""
    if isinstance(v, dict):
        return "，".join("%s %s" % (k, _fmt(vv)) for k, vv in v.items())
    if isinstance(v, list):
        return "，".join(_fmt(x) for x in v)
    return str(v)


def _kv_block(d, title: str) -> str:
    if not isinstance(d, dict) or not d:
        return ""
    rr = "".join("<tr><td>%s</td><td>%s</td></tr>" % (e(k), e(_fmt(v))) for k, v in d.items())
    return f'<div class="kv"><h4>{e(title)}</h4><table><tbody>{rr}</tbody></table></div>'


def _field_zh(f: str) -> str:
    """练度字段内部名 -> 中文（elite/level/skill_N/spec_N/mod_N/new）。"""
    if f.startswith("skill_"):
        return "技能" + f.split("_", 1)[1]
    if f.startswith("spec_"):
        return "专精" + f.split("_", 1)[1]
    if f.startswith("mod_"):
        return "模组" + f.split("_", 1)[1]
    return {"elite": "精英化", "level": "等级", "new": "新获得"}.get(f, f)


def _val_zh(field: str, v) -> str:
    if field == "elite":
        try:
            return ["精英0", "精英1", "精英2"][int(v)]
        except Exception:  # noqa: BLE001
            return str(v)
    return str(v)


def weekly_report_section(ledger: list) -> str:
    if not ledger:
        return ("<section id=\"周报\"><h2>收益周报</h2>"
                "<p class=\"muted\">数据待接入（缺 scheduling/data/revenue_ledger.jsonl）。</p></section>")
    rows = [r for r in ledger if isinstance(r, dict)]
    n = len(rows)

    def _sum(path, key):
        tot = 0
        for r in rows:
            d = r.get(path, {}) or {}
            v = d.get(key)
            if isinstance(v, (int, float)):
                tot += v
        return tot

    cards = "".join([
        card("结算段", f"<p><strong>{n}</strong> 段</p>"),
        card("累计理智消耗", f"<p><strong>{_sum('spend','理智')}</strong></p>"),
        card("累计龙门币消耗", f"<p><strong>{_sum('spend','龙门币')}</strong></p>"),
        card("累计刷关", f"<p><strong>{_sum('farm','runs')}</strong> 局</p>"),
        card("练度提升", f"<p><strong>{sum(len(r.get('train') or []) for r in rows)}</strong> 项</p>"),
    ])

    blocks = []
    for r in reversed(rows):
        w = r.get("window", {}) or {}
        parts = [f"<h3>{e(r.get('ts',''))} <span class=\"muted\">"
                 f"{e(w.get('start',''))} .. {e(w.get('end',''))}</span></h3>"]
        tri = (_kv_block(r.get("base"), "基建收益")
               + _kv_block(r.get("farm"), "刷关")
               + _kv_block(r.get("spend"), "消耗"))
        if tri:
            parts.append(f'<div class="cols">{tri}</div>')

        tr = r.get("train") or []
        if tr:
            rr = "".join(
                "<tr><td>%s</td><td>%s</td><td>%s → %s</td></tr>"
                % (e(x.get("name")), e(_field_zh(x.get("field", ""))),
                   e(_val_zh(x.get("field", ""), x.get("from"))),
                   e(_val_zh(x.get("field", ""), x.get("to"))))
                for x in tr)
            parts.append('<h4>练度变化</h4><div class="tbl-wrap"><table><thead><tr>'
                         '<th>干员</th><th>字段</th><th>变化</th></tr></thead><tbody>'
                         + rr + '</tbody></table></div>')

        pa = (_kv_block(r.get("predict"), "计划")
              + _kv_block(r.get("actual"), "实际")
              + _kv_block(r.get("delta"), "偏差"))
        if pa:
            parts.append(f'<h4>计划 vs 实际</h4><div class="cols">{pa}</div>')

        iss = r.get("issues") or []
        if iss:
            parts.append('<h4>踩坑</h4><ul>' + "".join(f"<li>{e(x)}</li>" for x in iss) + '</ul>')
        if r.get("note"):
            parts.append(f'<p class="muted">备注：{e(r.get("note"))}</p>')

        blocks.append('<article class="card">' + "".join(parts) + '</article>')

    return (f'<section id="周报"><h2>收益周报</h2>'
            f'<div class="cards" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">{cards}</div>'
            + "".join(blocks) + '</section>')


def rotation_section() -> str:
    if BASE_REPORT.exists():
        return ("<section id=\"排班\"><h2>基建排班报告</h2>"
                "<iframe src=\"index.html\" "
                "style=\"width:100%;height:1400px;border:0\"></iframe></section>")
    return ("<section id=\"排班\"><h2>基建排班报告</h2>"
            "<p class=\"muted\">未找到 基建排班报告（scheduling/报告/index.html）。</p></section>")


def build_alert(run_report: list) -> str:
    if not run_report:
        return ""
    last = run_report[-1]
    if not isinstance(last, dict) or last.get("ok", True):
        return ""
    name = last.get("task") or last.get("name") or last.get("type") or "未知任务"
    ts = last.get("ts") or last.get("time") or last.get("generated_at") or ""
    err = last.get("error") or last.get("msg") or last.get("message") or ""
    return (f"<div class=\"alert\">⚠ 最近一次执行失败 — {e(name)} "
            f"<span class=\"muted\">（{e(ts)}）</span><br>{e(err)}</div>")


CSS = """
:root{
  --pico-font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;
  --pico-primary:#C03A2B; --pico-primary-hover:#a52f22;
  --pico-primary-background:#C03A2B; --pico-primary-hover-background:#a52f22;
  --pico-primary-underline:#C03A2B;
}
h1{color:#C03A2B}
h2{color:#2F4858;border-bottom:2px solid #E8DCC8;padding-bottom:.3rem}
h3,h4{color:#2F4858}
section{scroll-margin-top:5rem;margin-bottom:2rem}
nav.tabs{position:sticky;top:0;z-index:30;background:var(--pico-background-color,#fff);
  border-bottom:1px solid #E8DCC8;padding:.4rem 0;margin-bottom:1rem;}
nav.tabs ul{flex-wrap:wrap;gap:.2rem}
nav.tabs a{font-size:.9rem;padding:.2rem .5rem;cursor:pointer}
nav.tabs a.active{font-weight:700;color:#C03A2B;border-bottom:2px solid #C03A2B}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}
@media(max-width:720px){.cards{grid-template-columns:repeat(2,1fr)}}
.card{border:1px solid var(--pico-muted-border-color);border-radius:8px;padding:1rem}
.card h3{margin-top:0;font-size:1rem;color:#2F4858}
.card p{margin:0 0 .3rem}
.alert{background:#F7E7E5;border-left:4px solid #C03A2B;color:#8a2a1f;
  padding:.7rem 1rem;border-radius:6px;margin:.6rem 0}
.tbl-wrap{overflow-x:auto}
table{font-size:.92rem}
th{background:#2F4858;color:#fff}
th,td{padding:.45rem .6rem}
.muted{color:#777}
.page{display:none}
.page.active{display:block}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}
.kv h4{margin:.1rem 0 .3rem;font-size:.9rem;color:#2F4858}
.kv table{font-size:.85rem;margin:0}
.kv td:first-child{color:#666;white-space:nowrap}
article.card>h3{border-bottom:1px dashed #E8DCC8;padding-bottom:.3rem}
"""


def build(plan, sanity, ledger, run_report, plan_html, combos) -> str:
    style_css = read_text(STYLE)
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    plan_ts = (plan.get("generated_at") if plan else None) or "—"
    nav = (
        "<nav class=\"tabs container\">"
        "<ul><li><strong>明日方舟 · 汇总</strong></li></ul>"
        "<ul>"
        "<li><a href=\"#概览\" data-page=\"概览\">概览</a></li>"
        "<li><a href=\"#本周\" data-page=\"本周\">本周</a></li>"
        "<li><a href=\"#一键长草\" data-page=\"一键长草\">一键长草</a></li>"
        "<li><a href=\"#周报\" data-page=\"周报\">周报</a></li>"
        "<li><a href=\"#排班\" data-page=\"排班\">排班</a></li>"
        "</ul></nav>"
    )
    body = "".join([
        build_alert(run_report),
        nav,
        f"<p class=\"muted\">计划生成：{e(plan_ts)} · 页面更新：{e(now)}</p>",
        overview_section(plan, sanity, combos),
        weekly_section(plan, sanity),
        f"<section id=\"一键长草\"><h2>一键长草思路</h2>{plan_html}</section>",
        weekly_report_section(ledger),
        rotation_section(),
    ])
    # 每个区块变成一个「页」（一次只显示一页，靠顶部导航切换）
    body = re.sub(r'<section id="([^"]+)">', r'<section id="\1" class="page">', body)
    script = """<script>
(function(){
  function show(id){
    var pages=document.querySelectorAll('.page');
    var found=false;
    pages.forEach(function(s){var on=(s.id===id);s.classList.toggle('active',on);if(on)found=true;});
    if(!found&&pages.length){pages[0].classList.add('active');id=pages[0].id;}
    document.querySelectorAll('nav.tabs a[data-page]').forEach(function(a){
      a.classList.toggle('active', a.getAttribute('data-page')===id);});
    window.scrollTo(0,0);
  }
  document.querySelectorAll('nav.tabs a[data-page]').forEach(function(a){
    a.addEventListener('click',function(ev){
      ev.preventDefault();
      var id=a.getAttribute('data-page');
      show(id);
      if(history.replaceState){history.replaceState(null,'','#'+id);}
    });
  });
  var h=location.hash?decodeURIComponent(location.hash.slice(1)):null;
  show(h||'概览');

  // --- 公招：贴词条 -> 后端推荐 ---
  var API=(location.protocol==='file:')?'http://127.0.0.1:8787':'';
  function esc(s){return String(s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
  window.__recruit=function(){
    var t=document.getElementById('taginput').value.trim();
    var box=document.getElementById('tagresult');
    if(!t){box.textContent='请先贴词条';return;}
    box.textContent='计算中…';
    fetch(API+'/api/recommend?tags='+encodeURIComponent(t))
      .then(function(r){return r.json();})
      .then(function(d){
        if(!d||!d.ok){box.textContent='后端返回异常';return;}
        var s='<div class="muted">owned '+d.owned+'（'+esc(d.source)+'）'+(d.hit&&d.hit.length?('　★ 出现 '+esc(d.hit.join(' / '))):'')+'</div>';
        s+='<div class="tbl-wrap"><table><thead><tr><th>词条组合</th><th>池</th><th>未拥有</th><th>P(新)</th><th>星级</th><th>未拥有干员</th></tr></thead><tbody>';
        (d.recommend||[]).forEach(function(r){
          s+='<tr><td>'+esc(r.tags.join('+'))+'</td><td>'+r.size+'</td><td>'+r.unowned+'</td><td>'+Math.round(r.p_new*100)+'%</td><td>★'+r.rare_min+'~'+r.rare_max+'</td><td class="muted">'+esc((r.unowned_names||[]).join('、'))+'</td></tr>';
        });
        s+='</tbody></table></div>';
        box.innerHTML=s;
      })
      .catch(function(){box.innerHTML='连不上后端：先运行 <code>python scheduling/tools/site_server.py</code>，再用 http://127.0.0.1:8787/ 打开本页。';});
  };
  var _b=document.getElementById('tagbtn'); if(_b){_b.addEventListener('click',window.__recruit);}
  var _i=document.getElementById('taginput');
  var _tm=null;
  function _deb(){ if(_tm){clearTimeout(_tm);} _tm=setTimeout(window.__recruit,450); }
  if(_i){
    _i.addEventListener('input', _deb);   // 边输/边贴，停顿 0.45s 自动算
    _i.addEventListener('paste', function(){ setTimeout(_deb,0); });
    _i.addEventListener('keydown',function(e){
      if(e.key==='Enter'){ if(_tm){clearTimeout(_tm);} window.__recruit(); }
    });
  }
})();
</script>"""
    return (
        "<!doctype html><html lang=\"zh-CN\" data-theme=\"light\"><head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>明日方舟 · 汇总</title>"
        f"<style>{style_css}</style><style>{CSS}</style></head>"
        f"<body><main class=\"container\">{body}</main>{script}</body></html>"
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成单页明日方舟汇总站点")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出 HTML 路径")
    args = ap.parse_args(argv)

    plan = load_json(DATA / "weekly_plan.json")
    sanity = load_json(DATA / "sanity.json")
    ledger = load_jsonl(DATA / "revenue_ledger.jsonl")
    run_report = load_jsonl(DATA / "run_report.jsonl")
    combos = load_json(DATA / "recruit_combos.json")
    plan_html = render_markdown(PLAN_MD)

    doc = build(plan, sanity, ledger, run_report, plan_html, combos)

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    sections = doc.count("<section")
    print(f"wrote {out}")
    print(f"bytes={len(doc.encode('utf-8'))} sections={sections}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
