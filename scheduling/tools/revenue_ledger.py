# -*- coding: utf-8 -*-
"""收益账本（revenue ledger）—— 日结差分 + 追加式 jsonl。

一行 = 一个 04:00 结算窗（window.end 为结算时刻，即当日 04:00）。
账本文件：scheduling/data/revenue_ledger.jsonl（入库，追加；只记差额，不存全量快照）。

数据来源映射（详见 docs/收益账本与周报.md）：
  base   <- 游戏内「控制中枢→基建副手→副手简报」截图 OCR（04:00 结算，最近 3 日）
  farm   <- MAA DepotData.json 前后差分 + 关卡运行记录 + 活动代币读数
  spend  <- Depot 差分（材料/龙门币）+ 理智实机截图 + 仓库理智药 OCR
  train  <- 森空岛 ark_operbox_online 两次快照差分
  predict/actual/delta <- 计划预期（MASTER-PLAN 判据） vs 上述实际

快照纪律（docs/STATE.md §7）：原始 bundle 只落 %TEMP%\\opencode\\ark\\bundle-last.json，
**不入库**；账本里只有差分结论。

用法：
  python revenue_ledger.py example                     # 写一行示例（seed）
  python revenue_ledger.py settle --bundle cur.json    # 读上次快照→算Δ→追加一行
  python revenue_ledger.py show                        # 打印账本概况
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.normpath(os.path.join(HERE, "..", "data", "revenue_ledger.jsonl"))
SNAP_DIR = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "opencode", "ark")
LAST_SNAP = os.path.join(SNAP_DIR, "bundle-last.json")

# 练度字段白名单（bundle.operbox[] 契约字段；缺失按 0 处理）
TRAIN_FIELDS = ["elite", "level", "skill_1", "skill_2", "skill_3",
                "spec_1", "spec_2", "spec_3", "mod_1", "mod_2", "mod_3"]
# 理智药名 → 单瓶折算理智
SANITY_PER = {"应急理智浓缩液": 120, "应急理智加强剂": 60}
# 视为货币的 depot 项（其余归材料）
CURRENCY = {"龙门币"}
CAP = 205  # 理智上限（99 级）

SCHEMA = 1
BUNDLE_SCHEMA = 1

# ---- bundle.json 字段契约（设备侧采集 → 逻辑差分；见 docs/收益账本与周报.md §二）----
# 归属：device=设备侧 agent 填；auto=本工具自动算（不写进 bundle）；-双方可给
# 级别：req=差分必需；opt=可选；auto=工具产物
BUNDLE_FIELDS = [
    # key            owner   level  说明
    ("ts",              "device", "req", "落账时刻 ISO，如 2026-10-10T04:05"),
    ("window_start",    "device", "opt", "结算窗起；缺则由 ts 推导"),
    ("window_end",      "device", "opt", "结算窗止（当日 04:00）；缺则由 ts 推导"),
    ("sanity",          "device", "req", "实机理智截图读数（森空岛 ap 不可信）"),
    ("sanity_spent",    "device", "opt", "权威理智消耗；缺则按 10/h+理智药估算"),
    ("meds",            "device", "opt", "{理智药名: 存量}，仓库页 OCR"),
    ("depot",           "device", "req", "{物品名|itemId: 数量}，MAA DepotData.json"),
    ("depot_names",     "device", "opt", "{itemId: 中文名}，depot 用 itemId 时必给"),
    ("operbox",         "device", "req", "森空岛 ark_operbox_online 快照数组"),
    ("tokens",          "device", "opt", "{actId: 数量}，活动代币读数"),
    ("stage_runs",      "device", "opt", "{关卡: 次数}，本段运行的关"),
    ("secondary_brief", "device", "opt", "副手简报 OCR {src,parsed,raw}"),
    ("plan",            "device", "opt", "计划预期 {理智,活动代币,龙门币}（MASTER-PLAN 判据）"),
    ("issues",          "device", "opt", "踩坑项 []（也可 --issue 传）"),
    ("note",            "device", "opt", "备注"),
    # ↓ 工具自动算，不写进 bundle
    ("base",            "auto",   "auto", "基建收益（secondary_brief.parsed → 本工具落账）"),
    ("farm",            "auto",   "auto", "刷关所得（depot/tokens 差分）"),
    ("spend",           "auto",   "auto", "消耗（depot 差分 + sanity/meds）"),
    ("train",           "auto",   "auto", "练度变化（operbox 前后差分）"),
    ("actual/delta",    "auto",   "auto", "实际 vs plan（给 plan 才有）"),
]
DEVICE_REQUIRED = [k for k, o, lv, _ in BUNDLE_FIELDS if o == "device" and lv == "req"]

EXAMPLE_ENTRY = {
    "schema": SCHEMA,
    "window": {"start": "2026-10-09T04:00", "end": "2026-10-10T04:00"},
    "ts": "2026-10-10T04:05",
    "base": {
        "贸易站": {"合成玉": 972, "龙门币": 0},
        "制造站": {"赤金": 106, "源石碎片": 63, "作战记录": 61},
        "src": "副手简报OCR",
    },
    "farm": {
        "stage": "YW-6", "runs": 20,
        "活动代币": {"act52side": 400},
        "材料": {"全新装置": 24, "转质盐组": 6},
        "龙门币": 0,
    },
    "spend": {
        "理智": 480,
        "理智药": {"应急理智浓缩液": 1},
        "材料": {"固源岩": 92},
        "龙门币": 34642,
    },
    "train": [
        {"name": "德克萨斯", "field": "elite", "from": 1, "to": 2},
        {"name": "夜莺", "field": "skill_2", "from": 7, "to": 8},
    ],
    "predict": {"理智": 480, "活动代币": 400, "龙门币": -30000},
    "actual": {"理智": 480, "活动代币": 380, "龙门币": -34642},
    "delta": {"理智": 0, "活动代币": -20, "龙门币": -4642},
    "issues": ["YW-6 第 3 次二星，代币少拿 20"],
    "note": "基建换班 01:15 完成，方向 队列2->队列1",
}


def _ensure(path):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def load_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _num(x):
    x = float(x)
    return int(x) if x.is_integer() else round(x, 3)


def normalize_depot(bundle):
    """bundle.depot 为 {itemId|name: qty}；若键为数字且有 depot_names 则映射为中文名。"""
    depot = (bundle or {}).get("depot") or {}
    names = (bundle or {}).get("depot_names") or {}
    out = {}
    for k, v in depot.items():
        key = str(k)
        if key.isdigit() and names:
            key = names.get(key, key)
        try:
            out[key] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def diff_numeric(prev, cur):
    """{key: cur - prev}，只保留非零。"""
    prev, cur = prev or {}, cur or {}
    out = {}
    for k in set(prev) | set(cur):
        d = (cur.get(k, 0) or 0) - (prev.get(k, 0) or 0)
        if abs(d) > 1e-9:
            out[k] = _num(d)
    return out


def _box_index(ops):
    idx = {}
    for o in ops or []:
        n = o.get("name")
        if n:
            idx[n] = o
    return idx


def diff_operbox(prev_ops, cur_ops):
    """两次干员箱 diff → train[]。新干员记 field='new'。"""
    if prev_ops is None:
        return []
    p, c = _box_index(prev_ops), _box_index(cur_ops)
    changes = []
    for name, co in c.items():
        if name not in p:
            changes.append({"name": name, "field": "new", "from": 0, "to": 1})
            continue
        po = p[name]
        elite_changed = (po.get("elite", 0) or 0) != (co.get("elite", 0) or 0)
        for f in TRAIN_FIELDS:
            a, b = po.get(f, 0) or 0, co.get(f, 0) or 0
            if b == a:
                continue
            # 精英化会重置等级：此时 level 80→1 是噪声，不记为练度变化
            if f == "level" and elite_changed:
                continue
            changes.append({"name": name, "field": f, "from": a, "to": b})
    return changes


def meds_used(prev_m, cur_m):
    out = {}
    for k in set(prev_m or {}) | set(cur_m or {}):
        d = (prev_m or {}).get(k, 0) - (cur_m or {}).get(k, 0)
        if d > 0:
            out[k] = _num(d)
    return out


def validate_bundle(b):
    """校验 device 侧 bundle；返回问题清单（空=通过）。"""
    problems = []
    if not isinstance(b, dict):
        return ["bundle 不是 JSON 对象"]
    for k in DEVICE_REQUIRED:
        if k not in b or b.get(k) in (None, "", {}):
            problems.append("缺必需字段: %s" % k)
    if "depot" in b and not isinstance(b["depot"], dict):
        problems.append("depot 应为 {物品:数量} 对象")
    if "operbox" in b and not isinstance(b["operbox"], list):
        problems.append("operbox 应为快照数组")
    if "sanity" in b and not isinstance(b["sanity"], (int, float)):
        problems.append("sanity 应为数值（实机截图读数）")
    if "meds" in b and not isinstance(b["meds"], dict):
        problems.append("meds 应为 {药名:存量} 对象")
    if "plan" in b and not isinstance(b["plan"], dict):
        problems.append("plan 应为 {理智,活动代币,龙门币}")
    return problems


def bundle_template():
    """生成带归属标注的 bundle 模板（设备侧 agent 可直接填）。"""
    tpl = {
        "_schema": BUNDLE_SCHEMA,
        "_fields": {k: {"owner": o, "level": lv, "desc": d} for k, o, lv, d in BUNDLE_FIELDS},
        "ts": "2026-10-10T04:05",
        "window_start": "2026-10-09T04:00",
        "window_end": "2026-10-10T04:00",
        "sanity": 85,
        "sanity_spent": None,
        "meds": {"应急理智浓缩液": 3},
        "depot": {"固源岩": 1234, "龙门币": 3120000},
        "depot_names": {},
        "operbox": [{"name": "德克萨斯", "elite": 2, "level": 1, "skill_1": 7, "skill_2": 8,
                     "spec_1": 0, "mod_1": 0}],
        "tokens": {"act52side": 520},
        "stage_runs": {"YW-6": 20},
        "secondary_brief": {"src": "副手简报OCR", "parsed": {}, "raw": ""},
        "plan": {"理智": 480, "活动代币": 400, "龙门币": -30000},
        "issues": [],
        "note": "",
    }
    return tpl


def _parse_iso(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def build_entry(cur, prev, window_start, window_end, ts,
                predict=None, issues=None, note=""):
    prev = prev or {}
    first = not prev
    depot_delta = {} if first else diff_numeric(normalize_depot(prev), normalize_depot(cur))
    token_delta = {} if first else diff_numeric(prev.get("tokens"), cur.get("tokens"))

    farm_mat, spend_mat = {}, {}
    farm_lmd = spend_lmd = 0
    for k, d in depot_delta.items():
        if k in CURRENCY:
            if d > 0:
                farm_lmd += d
            else:
                spend_lmd += -d
        elif d > 0:
            farm_mat[k] = d
        else:
            spend_mat[k] = -d

    used = meds_used(prev.get("meds"), cur.get("meds"))
    meds_san = sum(used.get(k, 0) * SANITY_PER.get(k, 0) for k in used)

    s0, s1 = prev.get("sanity"), cur.get("sanity")
    sanity = {}
    spent = cur.get("sanity_spent")  # 采集方可直接给权威消耗；缺则估算
    if spent is None and s0 is not None and s1 is not None:
        ws, we = _parse_iso(window_start), _parse_iso(window_end)
        hours = (we - ws).total_seconds() / 3600 if (ws and we) else 24.0
        regen = hours * 10.0  # 240 理智/日 = 10/h
        spent = max(0.0, s0 + regen + meds_san - s1)
        sanity = {"start": s0, "end": s1, "regen_est": round(regen, 1),
                  "spent_est": round(spent, 1), "caution": "est"}
    elif spent is not None:
        sanity = {"spent": spent, "caution": "measured"}

    stage_runs = cur.get("stage_runs") or {}
    runs = int(sum(stage_runs.values())) if stage_runs else 0
    actual = {
        "理智": _num(spent) if spent is not None else None,
        "活动代币": _num(sum(token_delta.values())) if token_delta else 0,
        "龙门币": _num(farm_lmd - spend_lmd),
    }
    entry = {
        "schema": SCHEMA,
        "window": {"start": window_start, "end": window_end},
        "ts": ts,
        "base": _base_from_bundle(cur),
        "farm": {
            "stage": "、".join(stage_runs) if stage_runs else "",
            "runs": runs,
            "活动代币": token_delta,
            "材料": farm_mat,
            "龙门币": _num(farm_lmd) if farm_lmd else 0,
        },
        "spend": {
            "理智": spent if spent is not None else 0,
            "理智药": used,
            "材料": spend_mat,
            "龙门币": _num(spend_lmd) if spend_lmd else 0,
        },
        "train": diff_operbox(prev.get("operbox"), cur.get("operbox")),
    }
    if sanity:
        entry["sanity_read"] = sanity
    if first:
        entry["first"] = True
    predict = predict or cur.get("plan")
    if predict:
        entry["predict"] = predict
        entry["actual"] = {k: actual.get(k) for k in predict}
        entry["delta"] = {k: (_num((actual.get(k) or 0) - v)) for k, v in predict.items()}
    if issues:
        entry["issues"] = issues
    if note:
        entry["note"] = note
    return entry


def _base_from_bundle(cur):
    sb = cur.get("secondary_brief") or {}
    parsed = sb.get("parsed")
    if isinstance(parsed, dict):
        out = {k: v for k, v in parsed.items() if isinstance(v, (dict, int, float))}
        out["src"] = sb.get("src", "副手简报OCR")
        return out
    return {"src": sb.get("src", "副手简报OCR"), "raw": (sb.get("raw") or "")[:400]}


def append_entry(path, entry):
    _ensure(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_all(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _default_window(ts):
    t = _parse_iso(ts) or dt.datetime.now()
    end = t.replace(hour=4, minute=0, second=0, microsecond=0)
    if end > t:
        end -= dt.timedelta(days=1)
    start = end - dt.timedelta(days=1)
    return start.strftime("%Y-%m-%dT%H:%M"), end.strftime("%Y-%m-%dT%H:%M")


def cmd_settle(args):
    cur = load_json(args.bundle)
    if cur is None:
        raise SystemExit("读不到 bundle: %s" % args.bundle)
    prev = load_json(LAST_SNAP)
    ts = cur.get("ts") or dt.datetime.now().strftime("%Y-%m-%dT%H:%M")
    ws = args.window_start or cur.get("window_start")
    we = args.window_end or cur.get("window_end")
    if not (ws and we):
        ws, we = _default_window(ts)
    issues = args.issue or None
    entry = build_entry(cur, prev, ws, we, ts,
                        predict=json.loads(args.predict) if args.predict else None,
                        issues=issues, note=args.note or "")
    append_entry(args.ledger, entry)
    if not args.no_save:
        _ensure(LAST_SNAP)
        with open(LAST_SNAP, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
    print("settled %s -> %s  (train %d, farm %d 材料, spend 理智 %s)" % (
        ws, we, len(entry["train"]), len(entry["farm"]["材料"]), entry["spend"]["理智"]))


def cmd_validate(args):
    b = load_json(args.bundle)
    if b is None:
        raise SystemExit("读不到 bundle: %s" % args.bundle)
    problems = validate_bundle(b)
    if problems:
        print("bundle 不合格（%d 项）：" % len(problems))
        for p in problems:
            print("  - " + p)
        raise SystemExit(1)
    print("bundle OK：必需字段齐全（%s）" % ", ".join(DEVICE_REQUIRED))


def cmd_bundle(args):
    _ensure(args.out)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(bundle_template(), f, ensure_ascii=False, indent=2)
    print("wrote bundle template -> %s（含 _fields 归属标注）" % args.out)


def cmd_example(args):
    append_entry(args.ledger, EXAMPLE_ENTRY)
    print("wrote example line -> %s" % args.ledger)


def cmd_show(args):
    rows = read_all(args.ledger)
    print("ledger: %s  (%d 行)" % (args.ledger, len(rows)))
    for e in rows[-10:]:
        w = e.get("window", {})
        print("  %s ~ %s  train=%d farm=%d spend理智=%s" % (
            w.get("start"), w.get("end"), len(e.get("train", [])),
            len(e.get("farm", {}).get("材料", {})), e.get("spend", {}).get("理智")))


def main():
    ap = argparse.ArgumentParser(description="收益账本 · 日结差分")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("settle", help="读上次快照→算Δ→追加一行")
    p.add_argument("--bundle", required=True, help="本次采集 bundle.json")
    p.add_argument("--ledger", default=LEDGER)
    p.add_argument("--window-start", default="")
    p.add_argument("--window-end", default="")
    p.add_argument("--predict", default="", help="JSON 串：计划预期")
    p.add_argument("--issue", action="append", help="踩坑项，可多次")
    p.add_argument("--note", default="")
    p.add_argument("--no-save", action="store_true", help="不更新上次快照（测试用）")
    p.set_defaults(func=cmd_settle)

    p = sub.add_parser("validate", help="校验设备侧 bundle.json 是否合格")
    p.add_argument("--bundle", required=True)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("bundle", help="写 bundle 模板（含字段归属标注）")
    p.add_argument("--out", default=os.path.join(SNAP_DIR, "bundle.template.json"))
    p.set_defaults(func=cmd_bundle)

    p = sub.add_parser("example", help="写一行示例到账本")
    p.add_argument("--ledger", default=LEDGER)
    p.set_defaults(func=cmd_example)

    p = sub.add_parser("show", help="打印账本概况")
    p.add_argument("--ledger", default=LEDGER)
    p.set_defaults(func=cmd_show)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
