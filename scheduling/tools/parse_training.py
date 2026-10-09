# -*- coding: utf-8 -*-
"""解析"干员培养建议"卡片 → training.json（逐干员培养前后技能加成）。

数据来源：一图流 培养建议卡片（name/target/verdict/skill[培养后]/tip[含当前技能]/cost）。
"提升比例" = 技能对所属设施的加成（培养后新增/升级的那项；取技能文本里的最大百分数，
如"每小时+2%…最终+20%"取 +20%）。条件/按数量叠加类技能（如"每发电站+15%"）以技能文本为准。
"""
import json, re, os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "一图流产物"))
CARDS = os.path.join(SRC, "243-培养建议-cards.json")
OUT = os.path.join(HERE, "training.json")

FAC_KEYS = ["控制中枢", "贸易站", "制造站", "发电站", "会客室", "人力办公室",
            "办公室", "宿舍", "加工站", "训练室"]


def load_cards(path):
    d = json.load(open(path, encoding="utf-8"))
    if isinstance(d, str):          # 双重编码
        d = json.loads(d)
    return d["cards"]


def find_fac(t):
    for k in FAC_KEYS:
        if k in t:
            return "办公室" if k == "人力办公室" else k
    return ""


def maxpct(t):
    xs = re.findall(r"([+\-]?\d+(?:\.\d+)?)%", t)
    if not xs:
        return ""
    m = max((float(x) for x in xs), key=abs)
    return f"{m:g}"


def classify(fac, skill):
    s = skill or ""
    if "源石" in s:
        return "合成玉型"
    if "作战记录" in s:
        return "经验书型"
    if "贵金属" in s or "金属工艺" in s or "赤金" in s:
        return "龙门币型"
    if fac == "贸易站":
        return "龙门币型"
    if fac == "发电站":
        return "发电型"
    if fac == "办公室":
        return "办公型"
    if fac == "制造站":
        return "通用制造型"
    return "其它"


def before_from_tip(tip, fac):
    cands = []
    for line in tip.split("\n")[1:]:
        if fac and fac in line and "：" in line:
            name, eff = line.split("：", 1)
            cands.append({"skill": name, "effect": eff, "pct": maxpct(eff)})
    if not cands:
        return None
    withpct = [c for c in cands if c["pct"]]
    return withpct[0] if withpct else cands[0]


def parse():
    out = []
    for c in load_cards(CARDS):
        after = c.get("skill", "")
        fac = find_fac(after) or find_fac(c.get("tip", ""))
        after_pct = maxpct(after)
        before = before_from_tip(c.get("tip", ""), fac)
        cost = c.get("cost", "")
        exp = lmd = san = None
        m = re.search(r"经验\s*([\d,]+)", cost)
        if m: exp = m.group(1)
        m = re.search(r"龙门币\s*([\d,]+)", cost)
        if m: lmd = m.group(1)
        m = re.search(r"约\s*([\d,\.]+)\s*理智", cost)
        if m: san = m.group(1)
        rec = "ok" if "非常推荐" in c.get("verdict", "") else (
            "warn" if ("推荐" in c.get("verdict", "") or "酌情" in c.get("verdict", "")) else "bad")
        # 净增（相对当前下位替代/当前练度）：升级→取差；新增/换技能→取整段
        net = None
        try:
            a = float(after_pct)
            if before and before.get("pct"):
                b = float(before["pct"])
                net = round(a - b, 1) if a >= b else a
            else:
                net = a
        except Exception:
            net = None
        out.append({
            "name": c.get("name"), "target": c.get("target"), "verdict": c.get("verdict"),
            "facility": fac, "category": classify(fac, after),
            "after_skill": after, "after_pct": after_pct, "net_pct": net,
            "before_skill": before, "rec": rec,
            "cost_exp": exp, "cost_lmd": lmd, "sanity": san,
        })
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("wrote", OUT, "n=", len(out))
    for r in out:
        b = r["before_skill"]
        print(f"  {r['name']:6} | {r['facility']:4} | 前:{ (b['pct'] if b else '无'):>5} -> 后:{r['after_pct']:>5} | {r['rec']}")


if __name__ == "__main__":
    parse()
