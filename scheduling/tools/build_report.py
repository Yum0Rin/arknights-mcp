# -*- coding: utf-8 -*-
"""解析一图流产物（MAA 排班协议 JSON + 结果页文本）→ 结构化 report_data.json。

用法：
    python build_report.py            # 解析并写出 report_data.json（同级目录）
输入目录：../一图流产物/   （相对本脚本）
"""
import json, re, os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "一图流产物"))
OUT_JSON = os.path.join(HERE, "report_data.json")

# 每日综合产出的字段顺序（与一图流 .resource-* class 对应）
DAILY_LABELS = ["龙门币", "赤金", "经验", "黄票", "绿票", "合成玉", "源石碎片"]

PLANS = [
    {"id": "lmd", "file_maa": "243-钱书均衡-龙门币优先-MAA.json",
     "file_txt": "243-钱书均衡-结果页文本.txt",
     "name": "钱书均衡 · 龙门币优先", "preset": "243 钱书均衡/龙门币优先"},
    {"id": "orundum", "file_maa": "243-搓玉-合成玉-MAA.json",
     "file_txt": "243-搓玉-结果页文本.txt",
     "name": "搓玉 · 合成玉", "preset": "243（搓玉）合成玉"},
]


def _lines(txt):
    return [l.strip() for l in txt.splitlines()]


def parse_daily(txt):
    lines = _lines(txt)
    try:
        i = lines.index("每日综合产出")
    except ValueError:
        return {}
    nums = []
    k = i + 1
    while k < len(lines) and len(nums) < len(DAILY_LABELS) and re.match(r"^-?[\d,\.]+$", lines[k]):
        nums.append(lines[k]); k += 1
    return {DAILY_LABELS[n]: v for n, v in enumerate(nums)}


def parse_resources(txt):
    """资源产出与消耗：{项目: 数值}，如 赤金:+73.85 / 固源岩:-92.4 / --。"""
    lines = _lines(txt)
    try:
        i = lines.index("资源产出与消耗")
    except ValueError:
        return {}
    res = {}
    k = i + 1
    while k < len(lines) - 1:
        label = lines[k]
        if label.startswith("A班") or label.startswith("B班"):
            break
        val = lines[k + 1]
        if re.match(r"^[+\-]?[\d,\.]+$", val) or val == "--":
            res[label] = val; k += 2
        else:
            k += 1
    return res


def parse_advice(txt):
    lines = _lines(txt)
    try:
        start = lines.index("干员培养建议") + 1
    except ValueError:
        start = next((k + 1 for k, l in enumerate(lines) if "干员培养建议" in l), len(lines))
    out = []
    i = start
    while i < len(lines):
        if lines[i] in ("更新日志",):
            break
        if re.match(r"^精英\s", lines[i]) and "→" in lines[i]:
            name = lines[i - 1]
            level = lines[i]
            parts, k = [], i + 1
            while k < len(lines) and not lines[k].startswith("培养成本"):
                parts.append(lines[k]); k += 1
            cost = lines[k] if k < len(lines) else ""
            sanity = lines[k + 1] if k + 1 < len(lines) and "理智" in lines[k + 1] else ""
            exp = lmd = san = None
            m = re.search(r"经验\s*([\d,]+)", cost)
            if m: exp = m.group(1)
            m = re.search(r"龙门币\s*([\d,]+)", cost)
            if m: lmd = m.group(1)
            m = re.search(r"约\s*([\d,\.]+)\s*理智", sanity)
            if m: san = m.group(1)
            out.append({
                "name": name, "level": level,
                "remark": parts[0] if parts else "",
                "skill": parts[1] if len(parts) > 1 else "",
                "cost_exp": exp, "cost_lmd": lmd, "sanity": san,
            })
            i = k + 2
        else:
            i += 1
    return out


def main():
    data = {"baseLayout": {"trading": 2, "manufacture": 4, "power": 3, "dormitory": 4},
            "boxTotal": 337, "plans": []}
    for p in PLANS:
        maa = json.load(open(os.path.join(SRC, p["file_maa"]), encoding="utf-8"))
        txt = open(os.path.join(SRC, p["file_txt"]), encoding="utf-8-sig").read()
        data["plans"].append({
            "id": p["id"], "name": p["name"], "preset": p["preset"],
            "title": maa.get("title"), "scheduleType": maa.get("scheduleType"),
            "daily": parse_daily(txt), "resources": parse_resources(txt),
            "manifest": maa,
        })
    data["advice"] = parse_advice(open(os.path.join(SRC, PLANS[0]["file_txt"]), encoding="utf-8-sig").read())
    json.dump(data, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("wrote", OUT_JSON)
    for pl in data["plans"]:
        print(" ", pl["id"], "daily=", pl["daily"], "res=", pl["resources"])
    print("  advice n=", len(data["advice"]))


if __name__ == "__main__":
    main()
