"""单页汇总站点生成器（幂等）：把 weekly_plan / 收益账本 / 数据源渲染进一个 HTML。

改版（2026-10-14）：从「设计文档 + 数据 dump」改为「今天的决策看板」——
  * 页签 **今天 / 本周 / 培养·工具 / 账本**（原「概览/本周/一键长草/周报/排班」5 页）；
  * 删「一键长草」（设计文档不进看板）、「排班」（自研排班已归档，基建交 MAA 队列轮换）；
  * 概览 4 卡 → 顶部**状态条**；新增「今天要刷什么」；逐日表今天高亮；计划 stale 醒目提示；
  * 「周报」→「账本」（收益账本，接好数据后由 revenue_ledger 差分产出）。

用法：
  python scheduling/tools/build_site.py
  python scheduling/tools/build_site.py --out PATH
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
DATA = ROOT / "scheduling" / "data"
STYLE = TOOLS / "assets" / "pico.min.css"  # Pico v2.2（内联，离线）
REPORT_DIR = ROOT / "scheduling" / "报告"
DEFAULT_OUT = REPORT_DIR / "汇总.html"

sys.path.insert(0, str(TOOLS))
from plan_util import (  # noqa: E402
    budget_total, distribute_daily, load_costs, plan_day, plan_range,
    session_advice, weekly_summary,
)

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


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


def card(title: str, body: str) -> str:
    return f"<article class=\"card\"><h3>{e(title)}</h3>{body}</article>"


def today_iso() -> str:
    return _dt.date.today().isoformat()


def dow_of(iso: str) -> str:
    try:
        return WEEKDAYS[_dt.date.fromisoformat(iso).weekday()]
    except (ValueError, TypeError):
        return ""


def _norm_counts(v) -> dict:
    """runs 是 {关卡: 次数}、raids 是 [关卡, ...]（每个元素一次）→ 统一成 {关卡: 次数}。"""
    if not v:
        return {}
    if isinstance(v, dict):
        return {str(k): int(x) for k, x in v.items()}
    out: dict = {}
    for x in v:
        out[str(x)] = out.get(str(x), 0) + 1
    return out


# ---------------------------------------------------------------- 顶部状态条

def status_bar(plan, sanity) -> str:
    """常驻状态条：日期/更新/计划范围/理智。计划 stale 时红字提醒。"""
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    t = today_iso()
    rng = (plan or {}).get("range", "—")
    gen = (plan or {}).get("generated_at", "—")
    cur = (sanity or {}).get("current_sanity", "—")
    pot = (sanity or {}).get("potion_sanity", "—")

    _day, status = plan_day(plan, t)
    alert = ""
    if status == "out_of_range":
        alert = ("<div class=\"alert\">⚠ 计划范围 <b>%s</b> 未覆盖今天（%s）——已过期或未生成到本周，"
                 "重生成：<code>python scheduling/tools/plan_week.py</code></div>" % (e(rng), e(t)))
    elif status == "no_entry":
        alert = ("<div class=\"alert\">⚠ 计划里没有今天（%s）的条目——计划不完整，"
                 "重生成：<code>python scheduling/tools/plan_week.py</code></div>" % e(t))
    elif status == "no_daily":
        alert = "<div class=\"alert\">⚠ 计划缺「逐日视图」——重生成：<code>python scheduling/tools/plan_week.py</code></div>"

    items = "".join(
        "<div class=\"sb-item\"><span class=\"k\">%s</span><span class=\"v\">%s</span></div>"
        % (e(k), e(v))
        for k, v in (("今天", "%s %s" % (t, dow_of(t))),
                     ("计划范围", rng),
                     ("计划生成", gen),
                     ("当前理智", cur),
                     ("理智药", pot),
                     ("页面更新", now)))
    return f"<div class=\"statusbar\">{items}</div>{alert}"


# ---------------------------------------------------------------- ① 今天

def today_section(plan, sanity) -> str:
    t = today_iso()
    day, status = plan_day(plan, t)
    head = f"<h2>今天 · {e(t)} {e(dow_of(t))}</h2>"
    if not day:
        msg = {"out_of_range": "今天的计划不在当前周计划范围内（见顶部红字）。",
               "no_entry": "周计划里没有今天这一天。",
               "no_daily": "周计划缺逐日视图。"}.get(status, "没有可用的今日安排。")
        return f"<section id=\"今天\"><div class=\"page-head\">{head}</div><p class=\"muted\">{e(msg)}</p></section>"

    cost = load_costs()
    runs = _norm_counts(day.get("runs"))
    raids = _norm_counts(day.get("raids"))
    rows = ""
    for stage, cnt in sorted(runs.items(), key=lambda kv: -kv[1]):
        unit = cost.get(stage, 0)
        rows += "<tr><td>%s</td><td>%d</td><td>%d</td><td>%d</td></tr>" % (
            e(stage), cnt, unit, unit * cnt)
    for stage, cnt in sorted(raids.items(), key=lambda kv: -kv[1]):
        unit = cost.get(stage, 0)
        rows += "<tr><td>%s <span class=\"muted\">突袭</span></td><td>%d</td><td>%d</td><td>%d</td></tr>" % (
            e(stage), cnt, unit, unit * cnt)
    if not rows:
        rows = "<tr><td colspan=\"4\" class=\"muted\">今天没有排刷关（日常/收菜类任务见「本周」明细）</td></tr>"
    table = ("<div class=\"tbl-wrap\"><table><thead><tr><th>关卡</th><th>次数</th>"
             "<th>单次理智</th><th>小计</th></tr></thead><tbody>" + rows + "</tbody></table></div>")

    used = day.get("sanity", 0) or 0
    med = day.get("medicine", 0) or 0
    tips = ["今天目标理智 <b>%s</b>；其中需吃理智药 <b>%s</b>（整瓶 60，花到 ~0 最省）。" % (e(used), e(med))]
    if day.get("opens"):
        tips.append("<span style=\"color:#C03A2B\">★ 本日新开：%s</span>" % e("、".join(day["opens"])))
    if day.get("over"):
        tips.append("<span style=\"color:#C03A2B\">当天会超自然回复上限（%s），靠理智药覆盖。</span>" % e(day.get("cap", "—")))
    ev = plan.get("event")
    if ev:
        w = (plan.get("event_window") or {})
        if isinstance(w, dict) and w.get("close"):
            try:
                left = (_dt.date.fromisoformat(str(w["close"])[:10]) - _dt.date.today()).days
                if left >= 0:
                    tips.append("活动 <b>%s</b> 剩 <b>%d</b> 天（%s 截止）。" % (e(ev), left, e(w["close"])))
            except ValueError:
                pass
    tip_html = "<ul class=\"tips\">" + "".join("<li>%s</li>" % s for s in tips) + "</ul>"
    return f"<section id=\"今天\"><div class=\"page-head\">{head}</div>{table}{tip_html}</section>"


# ---------------------------------------------------------------- ② 本周

def _progress(used, total) -> str:
    pct = 0 if not total else max(0, min(100, round(100 * used / total)))
    return (f"<div class=\"bar\"><div class=\"bar-fill\" style=\"width:{pct}%\"></div>"
            f"<span class=\"bar-txt\">{used} / {total}（{pct}%）</span></div>")


def weekly_section(plan, sanity) -> str:
    head = "<div class=\"page-head\"><h2>本周安排</h2></div>"
    if not plan or not plan.get("tasks"):
        return (f"<section id=\"本周\">{head}"
                "<p class=\"muted\">本周计划未生成（缺 scheduling/data/weekly_plan.json）。</p>"
                + sanity_block(sanity) + "</section>")
    t = today_iso()
    daily = distribute_daily(plan) or []

    drows = ""
    for d in daily:
        runs = "、".join("%s ×%d" % (k, v) for k, v in _norm_counts(d.get("runs")).items()) or "—"
        _raids = _norm_counts(d.get("raids"))
        if _raids:
            runs += "　突袭 " + "、".join("%s×%d" % (k, v) for k, v in _raids.items())
        if d.get("opens"):
            runs += "　<span style=\"color:#C03A2B\">★本日新开：%s</span>" % e("、".join(d["opens"]))
        cls = " class=\"today\"" if d.get("date") == t else ""
        sstyle = " style=\"color:#C03A2B;font-weight:700\"" if d.get("over") else ""
        drows += ("<tr%s><td>%s</td><td>%s</td><td>%s</td><td%s>%s%s</td></tr>"
                  % (cls, e(d.get("date", "")), e(d.get("dow", "")), runs, sstyle,
                     e(d.get("sanity", 0) or 0),
                     "（超上限 %s）" % e(d.get("cap", 240)) if d.get("over") else ""))
    daily_tbl = ('<div class="tbl-wrap"><table><thead><tr><th>日期</th><th>星期</th>'
                 '<th>刷关</th><th>理智</th></tr></thead><tbody>' + drows + '</tbody></table></div>')

    sm = weekly_summary(plan, daily)
    n = len(daily) or 7
    total = budget_total(plan, n)
    used = sm["total"]
    line = ("<p>本周合计 <strong>%d</strong> 理智；预算 <strong>%d</strong>"
            "（自然 %s + 理智药 %s）。%s</p>"
            % (used, total, sm["natural"], (plan.get("budget") or {}).get("meds_usable", sm.get("meds") or 0),
               ("<span style=\"color:#C03A2B\">缺口 %d（需靠理智药）</span>" % sm["gap"])
               if sm["gap"] else "预算够。"))
    line += _progress(used, total)

    # 各关合计（本周）
    agg: dict = {}
    for d in daily:
        for k, v in _norm_counts(d.get("runs")).items():
            agg[k] = agg.get(k, 0) + v
        for k, v in _norm_counts(d.get("raids")).items():
            agg[k + "（突袭）"] = agg.get(k + "（突袭）", 0) + v
    cost = load_costs()
    if agg:
        grows = "".join("<tr><td>%s</td><td>%d</td><td>%d</td></tr>"
                        % (e(k), v, cost.get(k, 0) * v)
                        for k, v in sorted(agg.items(), key=lambda kv: -kv[1]))
        agg_html = ('<h3>各关合计</h3><div class="tbl-wrap"><table><thead><tr>'
                    '<th>关卡</th><th>次数</th><th>理智</th></tr></thead><tbody>'
                    + grows + '</tbody></table></div>')
    else:
        agg_html = ""

    # 上线建议
    srows = "".join("<tr><td>%s %s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (e(s.get("date", "")), e(s.get("dow", "")), e(s.get("sanity", 0)),
                       e(s.get("sessions", 0)), e(s.get("note", "")))
                    for s in session_advice(plan, daily))
    ses_html = ('<details><summary>上线建议（1 次/天，花到 ~0）</summary>'
                '<div class="tbl-wrap"><table><thead><tr><th>日期</th><th>当天理智</th>'
                '<th>建议上线次数</th><th>备注</th></tr></thead><tbody>'
                + srows + '</tbody></table></div></details>')

    # 任务明细（MAA 队列视角，折叠）
    trows = "".join(
        "<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (i, e(t_.get("type", "")),
           e((t_.get("params") or {}).get("stage") or (t_.get("params") or {}).get("mode")
             or (t_.get("params") or {}).get("client_type") or "—"),
           e((t_.get("params") or {}).get("times", "—")))
        for i, t_ in enumerate(plan.get("tasks", []), 1))
    tasks_html = ('<details><summary>任务明细（写进 MAA 队列的条目）</summary>'
                  '<div class="tbl-wrap"><table><thead><tr><th>#</th><th>类型</th>'
                  '<th>关卡/模式</th><th>次数</th></tr></thead><tbody>'
                  + trows + '</tbody></table></div></details>')

    return (f"<section id=\"本周\">{head}{daily_tbl}{line}{agg_html}{ses_html}"
            f"{tasks_html}{sanity_block(sanity)}</section>")


def sanity_block(sanity) -> str:
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


# ---------------------------------------------------------------- ③ 培养 · 工具

def training_section(plan) -> str:
    tr = (plan or {}).get("training")
    if not tr:
        return "<h3>培养进度</h3><p class=\"muted\">无培养目标 / 本周未排培养。</p>"
    grows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (e(g.get("name")), e(g.get("qty")), e(g.get("stock", 0)), e(g.get("sanity")))
        for g in tr.get("top_gaps", []))
    return (
        "<h3>培养进度</h3>"
        "<p>目标：<strong>%s</strong>；总缺口 <strong>%s</strong> 理智"
        "（材料 %s + 精英化龙门币 %s）；本周投 <strong>%s</strong> 理智%s</p>"
        '<div class="tbl-wrap"><table><thead><tr><th>缺的材料</th><th>需</th>'
        '<th>库存已抵</th><th>还需理智</th></tr></thead><tbody>%s</tbody></table></div>'
        % (e("、".join(tr.get("targets", []))), e(tr.get("total_sanity")),
           e(tr.get("material_sanity")), e(tr.get("lmd_sanity")), e(tr.get("week_sanity")),
           ("（还需约 %s 周）" % tr["need_weeks"]) if tr.get("need_weeks") else "",
           grows))


def training_tools_section(plan, combos) -> str:
    head = "<div class=\"page-head\"><h2>培养 · 工具</h2></div>"
    return f"<section id=\"培养工具\">{head}{training_section(plan)}{recruit_tool(combos)}</section>"


RECRUIT_TOOL = """
<article class="card" style="margin:.8rem 0">
  <h3>公招：贴词条 → 推荐（按需）</h3>
  <p class="muted">把公招刷出的词条粘进来（空格 / 逗号 / 顿号分隔）——<strong>输入即自动计算</strong>。
  需先起后端：<code>python scheduling/tools/site_server.py</code>，再用 <code>http://127.0.0.1:8787/</code> 打开本页。</p>
  <div style="display:flex;gap:.5rem;flex-wrap:wrap">
    <input id="taginput" placeholder="高级资深干员 输出 近战位 新手 生存" style="flex:1;min-width:260px">
    <button id="tagbtn" type="button">推荐</button>
  </div>
  <div id="tagresult" class="muted" style="margin-top:.6rem"></div>
</article>
"""


def recruit_tool(combos) -> str:
    return "<h3>公招推荐</h3>" + RECRUIT_TOOL + recruit_block(combos)


def recruit_block(combos) -> str:
    """公招词条参考（静态兜底表；交互版需 site_server）。"""
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

    meta = ("<p class=\"muted\">owned 来源 <strong>%s</strong>（%d 人）；枚举 %d 个组合。"
            "判据：P(新)=池中未拥有/池大小，同 P 取高星。</p>"
            % (e(combos.get("source", "?")), combos.get("owned_count", 0),
               combos.get("total_combos", 0)))
    sp = combos.get("specials") or []
    rec = combos.get("combos") or []
    sp_html = ("<h4>特殊词条（必选）</h4>" + table(sp)) if sp else ""
    return (meta + sp_html + "<h4>推荐组合（按 P(新) 排序）</h4>" + table(rec))


# ---------------------------------------------------------------- ④ 账本（收益账本）

def _fmt(v) -> str:
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


def ledger_section(ledger) -> str:
    head = "<div class=\"page-head\"><h2>收益账本</h2></div>"
    if not ledger:
        return (f"<section id=\"账本\">{head}"
                "<p class=\"muted\">账本为空。收益账本按 04:00 结算段记「基建收益 / 刷关 / 消耗 / 练度变化」的差额，"
                "需要每段采集一次快照再差分。接法：</p>"
                "<pre class=\"muted\">python scheduling/tools/revenue_ledger.py settle --auto   "
                "# 自动采集（MAA仓库+森空岛干员箱+理智读数+当日计划）并差分入账</pre>"
                "<p class=\"muted\">首次为基线（无差额）；之后每段产生一行。详见 <code>docs/收益账本与周报.md</code>。</p>"
                "</section>")
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
        if r.get("first"):
            parts.append("<p class=\"muted\">（基线段：首个快照，无差额）</p>")
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

    return (f'<section id="账本">{head}'
            f'<div class="cards" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">{cards}</div>'
            + "".join(blocks) + '</section>')


# ---------------------------------------------------------------- 提示 / 组装

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
h2{color:#2F4858;border-bottom:2px solid #E8DCC8;padding-bottom:.3rem;margin-bottom:.6rem}
h3,h4{color:#2F4858}
section{scroll-margin-top:5rem;margin-bottom:2rem}
.page-head h2{margin-top:0}
nav.tabs{position:sticky;top:0;z-index:30;background:var(--pico-background-color,#fff);
  border-bottom:1px solid #E8DCC8;padding:.4rem 0;margin-bottom:.6rem;}
nav.tabs ul{flex-wrap:wrap;gap:.2rem;margin:0}
nav.tabs a{font-size:.95rem;padding:.25rem .6rem;cursor:pointer}
nav.tabs a.active{font-weight:700;color:#C03A2B;border-bottom:2px solid #C03A2B}
.statusbar{display:flex;flex-wrap:wrap;gap:.4rem 1.2rem;align-items:center;
  background:#F7F4EC;border:1px solid #E8DCC8;border-radius:8px;padding:.5rem .8rem;margin:.4rem 0 .8rem;
  font-size:.88rem}
.statusbar .sb-item{display:flex;gap:.35rem;align-items:baseline}
.statusbar .k{color:#777}
.statusbar .v{font-weight:600;color:#2F4858}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}
@media(max-width:720px){.cards{grid-template-columns:repeat(2,1fr)}}
.card{border:1px solid var(--pico-muted-border-color);border-radius:8px;padding:1rem}
.card h3{margin-top:0;font-size:1rem;color:#2F4858}
.card p{margin:0 0 .3rem}
.alert{background:#F7E7E5;border-left:4px solid #C03A2B;color:#8a2a1f;
  padding:.7rem 1rem;border-radius:6px;margin:.6rem 0;white-space:normal}
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
tr.today{background:#F7E7E5;font-weight:700}
tr.today td{color:#8a2a1f}
.tips{margin:.4rem 0 0;font-size:.92rem}
.bar{position:relative;background:#EFE9DC;border-radius:6px;height:1.4rem;margin:.4rem 0;overflow:hidden}
.bar-fill{background:#C03A2B;height:100%}
.bar-txt{position:absolute;left:0;right:0;top:0;line-height:1.4rem;text-align:center;
  font-size:.82rem;color:#2F4858}
details{margin:.5rem 0}
summary{cursor:pointer;color:#2F4858;font-weight:600}
pre{white-space:pre-wrap;word-break:break-all;background:#F7F4EC;padding:.6rem .8rem;border-radius:6px}
"""


def build(plan, sanity, ledger, run_report, combos) -> str:
    style_css = read_text(STYLE)
    nav = (
        "<nav class=\"tabs container\">"
        "<ul><li><strong>明日方舟 · 汇总</strong></li></ul>"
        "<ul>"
        "<li><a href=\"#今天\" data-page=\"今天\">今天</a></li>"
        "<li><a href=\"#本周\" data-page=\"本周\">本周</a></li>"
        "<li><a href=\"#培养工具\" data-page=\"培养工具\">培养 · 工具</a></li>"
        "<li><a href=\"#账本\" data-page=\"账本\">账本</a></li>"
        "</ul></nav>"
    )
    body = "".join([
        build_alert(run_report),
        nav,
        status_bar(plan, sanity),                # 常驻状态条（不在 .page 里，任何页都可见）
        today_section(plan, sanity),
        weekly_section(plan, sanity),
        training_tools_section(plan, combos),
        ledger_section(ledger),
    ])
    # 每个 <section id=...> 变成一个「页」（一次只显示一页，靠顶部导航切换）
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
  show(h||'今天');

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
    _i.addEventListener('input', _deb);
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

    doc = build(plan, sanity, ledger, run_report, combos)

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out}")
    print(f"bytes={len(doc.encode('utf-8'))} sections={doc.count('<section')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
