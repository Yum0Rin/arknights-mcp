#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活动关作业工作流 (activity copilot)
================================
抓「当期活动」的 MAA 作业(prts.maa.plus) → 比对本人干员箱(OperBoxData.json) →
用 MAA 的多作业自动战斗(自带关卡导航)逐关通关。

与 `scheduling/` 的基建排班工作流并列，是「打活动关」的固化流程。

单客户端纪律
------------
同一时刻只让 **一个** 程序驱动设备。运行前请先关掉 MAA GUI / 其它 arknights MCP，
否则会出现 MaaTouch 抢占、连接错乱。 (见 AGENTS.md 铁律)

导航分工（重要）
----------------
本脚本只负责「活动关卡列表页 → 逐关自动战斗」这段确定性流程。
**从首页走进活动**那一步 MAA Copilot 不做，得由上层 MCP/Agent 完成：
  ark_where 判页面 → ark_find/OCR 找当期活动 banner → ark_tap 逐层点入 → 停在关卡列表。
（详见 docs/WORKFLOW-活动关作业.md 的「导航层」一节。）

子命令
------
  events                       列出 MAA 资源已知的 side story 活动(actNNside)
  sync    <event>              从 MaaResource(GitHub) 补齐关缺失的关卡数据
                               (Arknights-Tile-Pos/overview.json + 该活动的 Tile-Pos)
  plan    <event> [--top N]    抓作业并按干员箱打分，打印每关推荐 + 候选
  run     <event> --stages 5,6,7,8 [--try]   执行(单关失败逐候选重试)
  run     <event> --all

示例
----
  python event_copilot.py sync act52side
  python event_copilot.py plan act52side
  python event_copilot.py run  act52side --stages 5,6,7,8
  python event_copilot.py run  act52side --all --try

前置：MAA(含 MaaCore) 已装在 C:\\MAA；模拟器已开、adb 可连 127.0.0.1:5555。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
MAA = os.environ.get("ARK_MAA_PATH", r"C:\MAA")
ADB = os.environ.get("ARK_ADB", r"C:\leidian\LDPlayer9\adb.exe")
ADDR = os.environ.get("ARK_ADDR", "127.0.0.1:5555")
TOUCH = os.environ.get("ARK_TOUCH", "maatouch")
# 自动编队固定用「第四编队」，避免动到用户其它编队(尤其第二编队)。
# 0=不选择编队；1..N=第 N 队。MAA GUI 里对应「选择编队」。
FORMATION_INDEX = int(os.environ.get("ARK_FORMATION_INDEX", "4"))

PRTS = "https://prts.maa.plus"
RES_RAW = "https://raw.githubusercontent.com/MaaAssistantArknights/MaaResource/main/resource"
TILE_DIR = pathlib.Path(MAA) / "resource" / "Arknights-Tile-Pos"
COPILOT_DIR = pathlib.Path(MAA) / "config" / "copilot"
BOX_FILE = pathlib.Path(MAA) / "data" / "OperBoxData.json"

MAX_CORE = (6, 18, 0)  # 本机 MaaCore 版本 upper-bound，作业 minimum_required 更高则跳过


def log(*a):
    print(*a, flush=True)


def http_json(url: str, timeout: int = 40):
    req = urllib.request.Request(url, headers={"User-Agent": "arknights-mcp/event-copilot"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_text(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": "arknights-mcp/event-copilot"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


# ---------------------------------------------------------------------------
# 干员箱
# ---------------------------------------------------------------------------
def load_box():
    d = json.load(open(BOX_FILE, encoding="utf-8"))
    own = {o["name"]: o for o in d["own_opers"] if o.get("own")}
    return own


def elite(own, name):
    o = own.get(name)
    return o["elite"] if o else -1


# ---------------------------------------------------------------------------
# 资源同步（关键：MAA 旧资源不认识新活动 → 报 Not support stage）
# ---------------------------------------------------------------------------
def local_overview():
    return json.load(open(TILE_DIR / "overview.json", encoding="utf-8"))


def ensure_resource(event_id: str) -> bool:
    """确保 overview.json 含该活动；否则从 GitHub 拉最新 overview 并补下载该活动的 Tile-Pos。"""
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    remote = http_json(RES_RAW + "/Arknights-Tile-Pos/overview.json")
    have = [k for k in remote if k.startswith(event_id + "_")]
    if not have:
        log("[!] 远端资源里也没有 %s 的关卡数据（活动 id 是否写错？）" % event_id)
        return False

    local = {}
    if (TILE_DIR / "overview.json").exists():
        local = json.load(open(TILE_DIR / "overview.json", encoding="utf-8"))
    if not any(k.startswith(event_id + "_") for k in local):
        bak = TILE_DIR / ("overview.json.bak-%s" % time.strftime("%Y%m%d%H%M%S"))
        shutil.copy2(TILE_DIR / "overview.json", bak) if (TILE_DIR / "overview.json").exists() else None
        log("[*] 替换 overview.json（旧备份 -> %s），新增 %d 条" % (bak.name, len(set(remote) - set(local))))
        json.dump(remote, open(TILE_DIR / "overview.json", "w", encoding="utf-8"), ensure_ascii=False)
    else:
        log("[=] overview.json 已含 %s" % event_id)

    # 下载缺失的 Tile-Pos 文件
    missing = []
    for k in have:
        fn = remote[k]["filename"]
        if not (TILE_DIR / fn).exists():
            missing.append(fn)
    for fn in missing:
        try:
            txt = http_text(RES_RAW + "/Arknights-Tile-Pos/" + urllib.parse.quote(fn))
            (TILE_DIR / fn).write_text(txt, encoding="utf-8")
            log("    +", fn)
        except Exception as e:
            log("    ! 下载失败", fn, e)
    return True


def stages_of(event_id: str):
    """从 overview.json 取该活动的关卡列表 (code, name, level_id, filename)。"""
    ov = local_overview()
    rows = []
    for k, v in ov.items():
        if k.startswith(event_id + "_"):
            # overview key 形如 "act52side_05-activities/act52side/level_act52side_05"
            stage_name = k.split("-activities")[0]
            rows.append((v.get("code", ""), v.get("name", ""), stage_name, v.get("filename", "")))
    # 仅保留可战斗关卡（有 code 形如 XX-N），按 code 排序
    rows = [r for r in rows if r[0]]
    rows.sort(key=lambda r: r[0])
    return rows


# ---------------------------------------------------------------------------
# 作业抓取 + 打分
# ---------------------------------------------------------------------------
def _min_required_ok(c) -> bool:
    mr = (c.get("minimum_required") or "v0.0.0").lstrip("v").split("-")[0]
    try:
        mv = tuple(int(x) for x in mr.split("."))
    except Exception:
        return True
    return mv <= MAX_CORE


def score(c, own):
    indiv = c.get("opers", []) or []
    groups = c.get("groups", []) or []
    not_owned = sum(1 for o in indiv if elite(own, o["name"]) < 0)
    low = sum(1 for o in indiv if 0 <= elite(own, o["name"]) < 2)
    empty = glow = 0
    for g in groups:
        ms = g.get("opers") or []
        if any(elite(own, m["name"]) >= 2 for m in ms):
            continue
        if any(elite(own, m["name"]) >= 0 for m in ms):
            glow += 1
        else:
            empty += 1
    return (not_owned, empty, low, glow)


def candidates_for(level_id: str, name: str, own, limit: int = 80):
    """返回按 [未拥有→空组→低练→热度] 排序的候选作业 [(score, id, content_dict), ...]"""
    q = http_json("%s/copilot/query?%s" % (PRTS, urllib.parse.urlencode(
        {"page": 1, "limit": limit, "levelKeyword": name, "type": "PRTS"})))
    out = []
    for it in q["data"]["data"]:
        try:
            c0 = json.loads(it["content"])
        except Exception:
            continue
        if c0.get("stage_name") != level_id:
            continue
        if not _min_required_ok(c0):
            continue
        try:
            full = json.loads(http_json("%s/copilot/get/%d" % (PRTS, it["id"]))["data"]["content"])
        except Exception:
            continue
        if not full.get("actions"):       # MAA 要求非空 actions，否则解析失败
            continue
        out.append((score(full, own), -it.get("views", 0), it["id"], full,
                    (full.get("doc") or {}).get("title", "")))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def save_copilot(event_id: str, code: str, content: dict) -> pathlib.Path:
    COPILOT_DIR.mkdir(parents=True, exist_ok=True)
    p = COPILOT_DIR / ("%s_%s.json" % (event_id, code))
    json.dump(content, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return p


# ---------------------------------------------------------------------------
# 执行（MaaCore 多作业模式：copilot_list 自带 OCR 关卡导航）
# ---------------------------------------------------------------------------
def _make_asst(cb):
    sys.path.insert(0, str(pathlib.Path(MAA) / "Python"))
    from asst.asst import Asst
    from asst.utils import InstanceOptionType
    # user_dir 指向临时目录，避免 MaaCore 的调试图写进当前工作目录(仓库)
    user_dir = pathlib.Path(os.environ.get("TEMP", ".")) / "arknights-mcp-maa"
    user_dir.mkdir(parents=True, exist_ok=True)
    Asst.load(MAA, user_dir=str(user_dir))
    a = Asst(Asst.CallBackType(cb))
    if not a.load(MAA):
        raise RuntimeError("Asst.load 失败")
    a.set_instance_option(InstanceOptionType.touch_type, TOUCH)
    if not a.connect(ADB, ADDR, "General"):
        raise RuntimeError("连接模拟器失败: %s" % ADDR)
    return a


def run_plan(event_id, plan, try_all=False, per_stage_timeout=360, formation_index=FORMATION_INDEX, loop=1):
    """plan: [(stage_tuple, [(score, content, title, id), ...]), ...]
    逐关执行；try_all=True 时某关失败则自动换下一个候选（失败会退理智，代价低）。"""
    state = {"error": False}

    def cb(msg, detail, arg):
        if msg == 10000:  # AsstMsg::TaskChainError
            state["error"] = True
            log("    [x] TaskChainError")

    a = _make_asst(cb)

    for stage, cands in plan:
        code = stage[0]
        ok = False
        tried = cands if try_all else cands[:1]
        for j, (sc, content, title, cid) in enumerate(tried):
            if not content.get("actions"):
                continue
            p = save_copilot(event_id, code, content)
            log("[*] %s 候选%d id=%s %s -> %s" % (code, j + 1, cid, title, p.name))
            state["error"] = False
            tid = a.append_task("Copilot", {
                "formation": True,
                "formation_index": formation_index,   # 只用第四编队，不动别的编队
                "ignore_requirements": True,          # 练度不那么够也能用
                "loop_times": loop,                   # >1 = 刷关(重复同一关)
                "copilot_list": [{"id": 0, "filename": str(p)}],
            })
            if not tid:
                log("    append 失败，跳过该候选")
                continue
            a.start()
            t0 = time.time()
            while a.running() and time.time() - t0 < per_stage_timeout:
                time.sleep(2)
            if a.running():
                a.stop()
            if not state["error"]:
                log("    [v] 成功")
                ok = True
                break
            log("    [x] 该候选未过，尝试下一个")
        if not ok:
            log("[!] %s 所有候选均未成功（可能已 2 星通关，或需更高练度/换作业）" % code)
    log("=== 完成 ===")


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def cmd_events(_):
    ov = local_overview()
    ids = sorted({k.split("_")[0] for k in ov if k.startswith("act") and "side" in k.split("_")[0]})
    log("已知 side story 活动：")
    for i in ids:
        codes = sorted(v["code"] for k, v in ov.items() if k.startswith(i + "_") and v.get("code"))
        log("  %-12s %s" % (i, ",".join(codes[:14])))


def cmd_sync(args):
    if ensure_resource(args.event):
        log("[=] 资源就绪")
        for st in stages_of(args.event):
            log("   ", st[0], st[1], st[2])


def cmd_plan(args):
    own = load_box()
    stages = stages_of(args.event)
    if not stages:
        log("找不到活动 %s 的关卡；先跑 sync 或检查 id" % args.event)
        return
    for code, name, level_id, _fn in stages:
        cands = candidates_for(level_id, name, own)
        log("=" * 70)
        log("%s %s  候选 %d" % (code, name, len(cands)))
        for i, (sc, negv, cid, content, title) in enumerate(cands[:args.top]):
            log("  #%d id=%-7d 未拥有=%d 空组=%d 低练=%d 低练组=%d  %s" % (
                i + 1, cid, sc[0], sc[1], sc[2], sc[3], title))


def cmd_run(args):
    own = load_box()
    stages = stages_of(args.event)
    if not stages:
        log("找不到活动 %s 的关卡" % args.event)
        return
    want = None
    if args.stages:
        want = set(args.stages.split(","))

    def selected(code: str) -> bool:
        return want is None or code in want or code.split("-", 1)[-1] in want

    plan = []
    for code, name, level_id, _fn in stages:
        if not selected(code):
            continue
        cands = candidates_for(level_id, name, own)
        if not cands:
            log("[!] %s 无可用候选" % code)
            continue
        plan.append(((code, name, level_id),
                     [(sc, content, title, cid) for (sc, negv, cid, content, title) in cands]))
    if not plan:
        log("[!] 没有要执行的关卡")
        return
    run_plan(args.event, plan, try_all=args.try_, per_stage_timeout=args.timeout,
             formation_index=args.formation, loop=args.loop)


def _adb_tap(xy: str):
    x, y = [int(v) for v in xy.split(",")]
    import subprocess
    subprocess.run([ADB, "-s", ADDR, "shell", "input", "tap", str(x), str(y)], capture_output=True)


def cmd_goto(args):
    """简易导航：主页按钮 -> 当期活动 banner -> 活动主页的『关卡地图』入口。
    坐标是事件/分辨率相关的经验值；换活动/分辨率请用 --home-xy/--banner-xy/--hub-xy 覆盖。
    更稳的做法是用 MCP 的 ark_where/ark_find 判页面、ark_tap 点击（见工作流文档『导航层』）。"""
    log("[goto] 回主页 %s" % args.home_xy)
    _adb_tap(args.home_xy); time.sleep(3)
    log("[goto] 点活动 banner %s" % args.banner_xy)
    _adb_tap(args.banner_xy); time.sleep(3)
    log("[goto] 进关卡地图 %s" % args.hub_xy)
    _adb_tap(args.hub_xy); time.sleep(3)
    log("[goto] 完成（若没到 YW-N 关卡列表，用 MCP 工具微调坐标/手动点）")


def main():
    ap = argparse.ArgumentParser(description="活动关作业工作流")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("events").set_defaults(func=cmd_events)

    p = sub.add_parser("sync"); p.add_argument("event"); p.set_defaults(func=cmd_sync)

    p = sub.add_parser("plan"); p.add_argument("event"); p.add_argument("--top", type=int, default=6)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run"); p.add_argument("event")
    p.add_argument("--stages", default=""); p.add_argument("--all", action="store_true")
    p.add_argument("--try", dest="try_", action="store_true")
    p.add_argument("--timeout", type=int, default=360)
    p.add_argument("--loop", type=int, default=1, help="重复次数(=1 通关一次；>1 刷代币)")
    p.add_argument("--formation", type=int, default=FORMATION_INDEX,
                   help="自动编队用第几个编队(默认 4=第四编队，不会动其它编队)")
    p.set_defaults(func=cmd_run)

    g = sub.add_parser("goto", help="从当前画面导航到活动关卡列表(首页→活动→关卡)")
    g.add_argument("--home-xy", default="370,45", help="主页按钮坐标(默认 370,45)")
    g.add_argument("--banner-xy", default="1770,205", help="当期活动 banner 坐标")
    g.add_argument("--hub-xy", default="1400,860", help="活动主页里『关卡地图』入口坐标")
    g.set_defaults(func=cmd_goto)

    ap.set_defaults(func=None)

    args = ap.parse_args()
    if args.cmd == "run" and not args.stages and not args.all:
        ap.error("run 需要 --stages 或 --all")
    args.func(args)


if __name__ == "__main__":
    main()
