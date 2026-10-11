#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键长草 · 应用层：把 weekly_plan.json 应用到 MAA 或直驱 MaaCore。

设计原则：
  - 唯一事实源 = scheduling/data/weekly_plan.json。
  - 两条落地路径同源：
      write → 渲染进 MAA GUI 配置 gui.new.json（你开 MAA 点「开始」即可；**只动每周会变的部分**）
      run   → 直驱 MaaCore 顺序跑（agent 在场时全自动；带防御性报告）
  - 其余任务一律保持 MAA 原配置（"别的就按照 MAA 来"）。

子命令：
  show                     打印本周计划（任务序列 + 理智分配理由）
  write [--maa-config P]   写进 MAA GUI 配置（需 MAA 关闭；写前自动备份）
  run   [--timeout S] [--dry]   直驱 MaaCore 跑（--dry 只校验不执行）

留痕：scheduling/data/run_report.jsonl
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time

MAA = pathlib.Path(os.environ.get("ARK_MAA_PATH", r"C:\MAA"))
ADB = os.environ.get("ARK_ADB", r"C:\leidian\LDPlayer9\adb.exe")
ADDR = os.environ.get("ARK_ADDR", "127.0.0.1:5555")
TOUCH = os.environ.get("ARK_TOUCH", "maatouch")
# 模拟器（雷电）：startup 时若设备不在线就用它拉起
EMULATOR = os.environ.get("ARK_EMULATOR", r"C:\leidian\LDPlayer9\ldconsole.exe")
EMU_INDEX = int(os.environ.get("ARK_EMU_INDEX", "0"))

REPO = pathlib.Path(__file__).resolve().parents[2]
PLAN_FILE = REPO / "scheduling" / "data" / "weekly_plan.json"
RUN_REPORT = REPO / "scheduling" / "data" / "run_report.jsonl"
GUI_CFG = MAA / "config" / "gui.new.json"
TMP = pathlib.Path(os.environ.get("TEMP", ".")) / "maa-week"

# 与 arknights_mcp.py 的 TASK_DEFAULTS 保持一致；公招口径对齐 GUI（3/4/5、6 星不自动）
TASK_DEFAULTS = {
    "Recruit": {"select": [3, 4, 5], "confirm": [3, 4, 5], "times": 50},
    "StartUp": {"client_type": "Official"},
    "Infrast": {"mode": 20000, "facility": ["Mfg", "Trade", "Reception"]},
}

# weekly_plan.tasks[].type  →  gui.new.json 里的 $type / TaskType
GUI_TYPE = {
    "StartUp": "StartUpTask", "Fight": "FightTask", "Recruit": "RecruitTask",
    "Infrast": "InfrastTask", "Mall": "MallTask", "Award": "AwardTask",
}


def log(msg):
    print("[maa-week] %s" % msg, flush=True)


def _now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# 计划读写
# ---------------------------------------------------------------------------
def load_plan(path=None) -> dict:
    p = pathlib.Path(path) if path else PLAN_FILE
    if not p.exists():
        raise SystemExit("找不到计划文件: %s（先由意图层生成）" % p)
    return json.loads(p.read_text(encoding="utf-8"))


def merged_params(task: dict) -> dict:
    p = dict(TASK_DEFAULTS.get(task["type"], {}))
    p.update(task.get("params") or {})
    return p


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------
def cmd_show(args):
    plan = load_plan(args.plan)
    print("本周计划：%s   %s" % (plan.get("week", "?"), plan.get("range", "")))
    print("生成：%s by %s" % (plan.get("generated_at", "?"), plan.get("by", "?")))
    b = plan.get("budget", {})
    print("理智预算：自然 %s + 周常 %s + 理智药 %s"
          % (b.get("sanity_natural"), b.get("weekly_potion"), b.get("meds_available")))
    print("\n任务序列：")
    for i, t in enumerate(plan.get("tasks", []), 1):
        pr = merged_params(t)
        desc = pr.get("stage") or pr.get("mode") or ""
        times = ("×%s" % pr["times"]) if "times" in pr else ""
        print("  %2d. %-9s %s %s" % (i, t["type"], desc, times))
    for s in plan.get("side", []):
        print("  +  换班(另跑) %s  [%s]" % (s.get("script"), s.get("when")))
    r = plan.get("rationale", {})
    if r.get("sanity_alloc"):
        print("\n理智分配：%s" % r["sanity_alloc"])
    for n in r.get("notes", []):
        print("  · %s" % n)


# ---------------------------------------------------------------------------
# write：只动 Fight(stage/times) + Infrast(filename)，其余保持原配置
# ---------------------------------------------------------------------------
def _maa_running() -> bool:
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MAA.exe"],
                       capture_output=True, text=True)
    return "MAA.exe" in (r.stdout or "")


def cmd_write(args):
    cfg_path = pathlib.Path(args.maa_config) if args.maa_config else GUI_CFG
    plan = load_plan(args.plan)
    if not cfg_path.exists():
        raise SystemExit("找不到 MAA 配置: %s" % cfg_path)

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cur = cfg.get("Current", "Default")
    queue = cfg["Configurations"][cur]["TaskQueue"]

    fights = [t for t in plan.get("tasks", []) if t["type"] == "Fight"]
    fight_slots = [q for q in queue if q.get("TaskType") == "Fight"]
    # 新增 Fight 必须插在「最后一个 Fight 之后」，否则会落到 Roguelike 后面 → 顺序错
    insert_at = (max(i for i, q in enumerate(queue) if q.get("TaskType") == "Fight") + 1
                 if fight_slots else len(queue))

    changed = []
    for i, t in enumerate(fights):
        pr = merged_params(t)
        stage, times = pr.get("stage"), pr.get("times", 1)
        if i < len(fight_slots):
            slot = fight_slots[i]
        else:  # 计划里的 Fight 比原配置多 → 克隆第一个 Fight，插在最后一个 Fight 后
            slot = json.loads(json.dumps(fight_slots[0])) if fight_slots else \
                {"$type": "FightTask", "Name": "刷理智", "IsEnable": True, "TaskType": "Fight"}
            queue.insert(insert_at, slot)
            insert_at += 1
        slot["StagePlan"] = [stage] if stage else slot.get("StagePlan", [])
        slot["EnableTimesLimit"] = True
        slot["TimesLimit"] = int(times)
        slot["IsEnable"] = True
        slot["Name"] = t.get("name") or ("刷理智·%s" % stage)
        changed.append("Fight#%d -> %s ×%s" % (i + 1, stage, times))

    # 公招次数同步到 GUI 的 MaxTimes（6 星不自动由 GUI 的 Level6Choose 控制，此处不碰）
    rec_slots = [q for q in queue if q.get("TaskType") == "Recruit"]
    for i, t in enumerate([x for x in plan.get("tasks", []) if x["type"] == "Recruit"]):
        if i >= len(rec_slots):
            break
        pr = merged_params(t)
        if "times" in pr:
            rec_slots[i]["MaxTimes"] = int(pr["times"])
            rec_slots[i]["IsEnable"] = True
            changed.append("Recruit#%d MaxTimes -> %s" % (i + 1, pr["times"]))

    # 基建 filename（可选）：计划里若带 filename 就同步
    for t in plan.get("tasks", []):
        if t["type"] == "Infrast" and (t.get("params") or {}).get("filename"):
            for q in queue:
                if q.get("TaskType") == "Infrast":
                    q["Filename"] = t["params"]["filename"]
                    changed.append("Infrast.Filename -> %s" % q["Filename"])

    if args.dry:
        log("[dry] 不写盘。将改动：")
        for c in changed:
            log("  " + c)
        return

    if _maa_running() and not args.force:
        raise SystemExit("MAA 正在运行 —— 运行中改配置会被覆盖。请先退出 MAA，或加 --force。")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = cfg_path.with_name("%s.bak-%s" % (cfg_path.name, stamp))
    bak.write_bytes(cfg_path.read_bytes())
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    log("已写 %s（备份 %s）" % (cfg_path, bak.name))
    for c in changed:
        log("  " + c)


# ---------------------------------------------------------------------------
# run：直驱 MaaCore（防御性）
# ---------------------------------------------------------------------------
_asst = None


def _devices() -> list:
    """adb devices 里在线的设备名列表。"""
    try:
        r = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=20)
    except Exception:  # noqa: BLE001
        return []
    return [l.split("\t")[0] for l in (r.stdout or "").splitlines()[1:] if "\tdevice" in l]


def _start_emulator() -> bool:
    """用 ldconsole 拉起雷电实例（index=EMU_INDEX）。"""
    exe = pathlib.Path(EMULATOR)
    if not exe.exists():
        log("找不到模拟器控制程序：%s" % exe)
        return False
    try:
        subprocess.Popen([str(exe), "launch", "--index", str(EMU_INDEX)],
                         cwd=str(exe.parent))
        log("已请求启动雷电实例 index=%d" % EMU_INDEX)
        return True
    except Exception as e:  # noqa: BLE001
        log("启动模拟器失败：%r" % e)
        return False


def _wait_device(timeout_s: int) -> bool:
    """轮询等设备上线（顺带 adb connect）。"""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if _devices():
            return True
        subprocess.run([ADB, "connect", ADDR], capture_output=True, timeout=15)
        time.sleep(3)
    return bool(_devices())


def _get_asst():
    global _asst
    if _asst is not None:
        return _asst
    sys.path.insert(0, str(MAA / "Python"))
    from asst.asst import Asst
    from asst.utils import InstanceOptionType
    user_dir = TMP / "maa"
    user_dir.mkdir(parents=True, exist_ok=True)
    Asst.load(str(MAA), user_dir=str(user_dir))
    a = Asst(Asst.CallBackType(lambda m, d, x: None))
    a.load(str(MAA))
    a.set_instance_option(InstanceOptionType.touch_type, TOUCH)
    # 依次尝试 ADDR 与 adb 探测到的设备（本机常见 127.0.0.1:5555 未注册、实际是 emulator-5554）
    candidates = [ADDR] + [d for d in _devices() if d != ADDR]
    for addr in candidates:
        try:
            if a.connect(ADB, addr, "General"):
                log("已连接设备：%s" % addr)
                _asst = a
                return a
        except Exception as e:  # noqa: BLE001
            log("连接 %s 失败：%r" % (addr, e))
    raise RuntimeError("连接模拟器失败（试过 %s）—— 确认雷电已开" % candidates)


def _shot(tag: str) -> str:
    TMP.mkdir(parents=True, exist_ok=True)
    p = TMP / ("fail_%s_%s.png" % (tag, dt.datetime.now().strftime("%H%M%S")))
    with open(p, "wb") as f:
        subprocess.run([ADB, "-s", ADDR, "exec-out", "screencap", "-p"],
                       stdout=f, timeout=40)
    return str(p)


def _report(entry: dict):
    RUN_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(RUN_REPORT, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _today_tasks(plan: dict, date: str = ""):
    """把「周计划」切成「今天那一份」：StartUp → 当天各关 → Recruit/Infrast/Mall/Award。"""
    sys.path.insert(0, str(REPO / "scheduling" / "tools"))
    import datetime as dt
    from plan_util import distribute_daily
    today = date or dt.date.today().isoformat()
    daily = distribute_daily(plan)
    day = next((d for d in daily if d.get("date") == today), None)
    out = []
    for t in plan.get("tasks", []):
        if t.get("type") == "StartUp":
            out.append(("StartUp", merged_params(t)))
            break
    if day:
        # 从 plan.tasks 取每关的 series（连战）；没配的普通关用默认 6，别退化成单次刷
        series_map = {}
        for t in plan.get("tasks", []):
            p = t.get("params") or {}
            if t.get("type") == "Fight" and p.get("stage"):
                series_map[p["stage"]] = int(p.get("series") or 0)
        for stage, runs in (day.get("runs") or {}).items():
            if runs > 0:
                prms = {"stage": stage, "times": int(runs)}
                s = series_map.get(stage) or int(os.environ.get("ARK_SERIES", "6"))
                if s > 1:
                    prms["series"] = s
                out.append(("Fight", prms))
    for t in plan.get("tasks", []):
        if t.get("type") in ("Recruit", "Infrast", "Mall", "Award"):
            out.append((t["type"], merged_params(t)))
    return out, today, (day or {})


def cmd_run(args):
    plan = load_plan(args.plan)
    if args.whole_week:
        tasks = [(t["type"], merged_params(t)) for t in plan.get("tasks", [])]
        scope = "整周"
    else:
        tasks, today, day = _today_tasks(plan, getattr(args, "date", "") or "")
        scope = "%s（当天）" % today
        log("今天分配：%s   理智 %s" % ("、".join("%s×%d" % kv for kv in (day.get("runs") or {}).items())
                                      or "无", day.get("sanity")))
    entry = {"ts": _now(), "week": plan.get("week"), "scope": scope, "tasks": [t for t, _ in tasks]}

    if args.dry:
        log("[dry] 将按顺序跑 %d 个任务：%s" % (len(tasks), scope))
        for t, p in tasks:
            log("  %-9s %s" % (t, {k: p[k] for k in ("stage", "times", "mode") if k in p}))
        for s in plan.get("side", []) or []:
            log("  + 附带脚本 %s（%s）" % (s.get("script"), s.get("when")))
        log("[dry] 未执行（也不跑换班）")
        return

    if args.dry:
        log("[dry] 将按顺序跑 %d 个任务：" % len(tasks))
        for t, p in tasks:
            log("  %-9s %s" % (t, {k: p[k] for k in ("stage", "times", "mode") if k in p}))
        log("[dry] 未执行")
        return

    if _maa_running():
        log("!! MAA GUI 在运行 —— 单客户端纪律：先退出 MAA 再 run")
        _report({**entry, "ok": False, "stage": "precheck", "error": "MAA GUI 正在运行"})
        raise SystemExit(2)

    # 附带脚本（基建换班，含收菜）—— 先跑，收菜在刷关之前
    if not getattr(args, "no_side", False):
        for s in plan.get("side", []) or []:
            sp = REPO / str(s.get("script") or "")
            if not sp.exists():
                log("附带脚本不存在，跳过：%s" % sp)
                continue
            log("先跑附带脚本（%s）：%s" % (s.get("when", ""), sp.name))
            r = subprocess.run([sys.executable, str(sp)], cwd=str(REPO))
            log("附带脚本 %s 退出码 %s" % (sp.name, r.returncode))
            _report({**entry, "ok": r.returncode == 0, "stage": "side",
                     "script": str(sp), "rc": r.returncode})

    try:
        a = _get_asst()
    except Exception as e:
        log("!! 连接失败：%s" % e)
        _report({**entry, "ok": False, "stage": "connect", "error": str(e)})
        raise SystemExit(2)

    tids = []
    for name, params in tasks:
        try:
            tid = a.append_task(name, params)
        except Exception as e:
            tid = 0
            log("!! append 异常 %s: %s" % (name, e))
        tids.append({"task": name, "id": tid})
        log("append %-9s -> id=%s" % (name, tid))
        if not tid:
            shot = _shot(name)
            log("!! append 失败（id=0）→ 停止，截图 %s" % shot)
            _report({**entry, "ok": False, "stage": "append", "task": name,
                     "tids": tids, "screenshot": shot})
            raise SystemExit(2)

    a.start()
    log("已启动，共 %d 任务；轮询中（超时 %ss）…" % (len(tids), args.timeout))
    t0 = time.time()
    while a.running() and time.time() - t0 < args.timeout:
        time.sleep(1.0)
    running = bool(a.running())
    elapsed = round(time.time() - t0, 1)
    if running:
        shot = _shot("timeout")
        log("!! 超时仍在跑（%.0fs）→ 不硬杀，留证 %s" % (elapsed, shot))
        _report({**entry, "ok": False, "stage": "timeout", "elapsed": elapsed,
                 "tids": tids, "screenshot": shot})
        raise SystemExit(3)

    log("跑完，用时 %.0fs" % elapsed)
    _report({**entry, "ok": True, "elapsed": elapsed, "tids": tids})


def cmd_startup(args):
    """先确保模拟器在线（不在线就拉起雷电），再用 MaaCore 的 StartUp 启动/唤醒游戏。"""
    devs = _devices()
    if not devs:
        log("未检测到在线设备 → 启动雷电模拟器…")
        if not _start_emulator():
            raise SystemExit("启动模拟器失败（找不到 %s）" % EMULATOR)
        if not _wait_device(args.emulator_timeout):
            raise SystemExit("等模拟器上线超时（%ds）—— 首次启动较慢可加大 --emulator-timeout"
                             % args.emulator_timeout)
        devs = _devices()
    log("模拟器已在线：%s" % devs)

    a = _get_asst()
    tid = a.append_task("StartUp", {"client_type": args.client, "start_game_enabled": True})
    if not tid:
        raise SystemExit("StartUp append 失败（client_type=%s）" % args.client)
    a.start()
    log("已请求启动游戏（client_type=%s），等待就绪…" % args.client)
    t0 = time.time()
    while a.running() and time.time() - t0 < args.timeout:
        time.sleep(1.0)
    if a.running():
        log("超时仍在跑（%.0fs）—— 可继续观察" % (time.time() - t0))
    else:
        log("启动流程结束（%.0fs）" % (time.time() - t0))


def main():
    ap = argparse.ArgumentParser(description="一键长草 · weekly_plan 应用器")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("show", cmd_show), ("write", cmd_write), ("run", cmd_run)):
        p = sub.add_parser(name)
        p.add_argument("--plan", default=None, help="weekly_plan.json 路径")
        if name == "write":
            p.add_argument("--maa-config", default=None)
            p.add_argument("--dry", action="store_true")
            p.add_argument("--force", action="store_true", help="MAA 在跑也写（危险）")
        if name == "run":
            p.add_argument("--timeout", type=int, default=7200)
            p.add_argument("--dry", action="store_true")
            p.add_argument("--date", default="", help="跑哪一天（默认今天）")
            p.add_argument("--whole-week", action="store_true", help="跑整周总量（默认只跑当天）")
            p.add_argument("--no-side", action="store_true", help="不跑附带脚本（基建换班）")
        p.set_defaults(func=fn)
    sp = sub.add_parser("startup", help="启动/唤醒游戏（含拉起雷电模拟器）")
    sp.add_argument("--client", default="Official", help="Official / Bilibili / txwy / YoStarEN…")
    sp.add_argument("--timeout", type=int, default=300, help="StartUp 任务超时（秒）")
    sp.add_argument("--emulator-timeout", type=int, default=120, help="等模拟器上线超时（秒）")
    sp.set_defaults(func=cmd_startup)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
