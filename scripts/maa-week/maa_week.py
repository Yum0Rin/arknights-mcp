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
    # 基建：MAA 自带的「队列轮换」（mode=20000）。facility = 收哪些设施（顺序无所谓）。
    "Infrast": {"mode": 20000, "facility": ["Mfg", "Trade", "Power", "Control", "Reception",
                                            "Office", "Dorm", "Processing", "Training"]},
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


def _due(trigger_key: str) -> bool:
    """查 docs/state.json.triggers[key]（形如 '2026-10-11 14:33'）是否已到期。
    读不到/格式怪 → 当作到期（宁可跑，别漏）。"""
    try:
        d = json.loads((REPO / "docs" / "state.json").read_text(encoding="utf-8"))
        v = (d.get("triggers") or {}).get(trigger_key)
        if not v:
            return True
        s = str(v).replace(">= ", "").strip()
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return dt.datetime.now() >= dt.datetime.strptime(s, fmt)
            except ValueError:
                continue
        return True
    except Exception:  # noqa: BLE001
        return True


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
        print("  +  附带脚本 %s  [%s]" % (s.get("script"), s.get("when")))
    # 逐日表：队列「按天编辑」就看这一张
    daily = plan.get("daily") or []
    if daily:
        today = getattr(args, "date", "") or dt.date.today().isoformat()
        print("\n逐日分配（%s ← 今天；write/run 默认只下这一天）：" % today)
        for d in daily:
            runs = "、".join("%s×%d" % kv for kv in (d.get("runs") or {}).items()) or "无"
            if d.get("raids"):
                runs += "  突袭:%s" % "、".join(d.get("raids") or [])
            mark = ">>" if d.get("date") == today else "  "
            print("  %s %s(%s)  理智 %-5s / 上限 %-5s %s%s"
                  % (mark, d.get("date"), d.get("dow", ""), d.get("sanity", 0),
                     d.get("day_cap", d.get("cap", "")), runs,
                     "  ⚠未排下:%s" % d["unplaced"] if d.get("unplaced") else ""))
    r = plan.get("rationale", {})
    if r.get("sanity_alloc"):
        print("\n理智分配：%s" % r["sanity_alloc"])
    for n in r.get("notes", []):
        print("  · %s" % n)


# ---------------------------------------------------------------------------
# write：把**当天那一份**刷进 MAA GUI 配置（一天一天编辑，不写整周）
#   - Fight 槽位按「关卡」匹配：今天的关写次数，**不在今天计划里的槽位一律停用**（跑完即停）
#   - 固定任务（StartUp/Recruit/Infrast/Mall/Award）确保启用；Infrast 强制 Mode=Rotation
#   - 其余任务（Roguelike / OperProgress 等）**不动**，只有「空 Plans 的 OperProgress」会被停用
#     （它 set_params 会失败 → 会拖垮整条队列）
# ---------------------------------------------------------------------------
def _maa_running() -> bool:
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MAA.exe"],
                       capture_output=True, text=True)
    return "MAA.exe" in (r.stdout or "")


def _event_id(plan) -> str:
    return str((plan or {}).get("event") or "<活动id>")


def _copilot_cmd(plan, kind: str) -> str:
    """可直接复制的 event-copilot 命令（EX/S 首通/突袭链）。"""
    return ("python scripts/event-copilot/event_copilot.py run %s --chain %s --try"
            % (_event_id(plan), kind))


def _clone_fight_slot(queue, slots, insert_at):
    """克隆一个现有 Fight 槽位（今天有新的关、原配置没这个槽位时用）。"""
    if slots:
        return json.loads(json.dumps(slots[0]))
    return {"$type": "FightTask", "Name": "刷理智", "IsEnable": True, "TaskType": "Fight",
            "StagePlan": [], "EnableTimesLimit": True, "TimesLimit": 1}


def cmd_write(args):
    cfg_path = pathlib.Path(args.maa_config) if args.maa_config else GUI_CFG
    plan = load_plan(args.plan)
    if not cfg_path.exists():
        raise SystemExit("找不到 MAA 配置: %s" % cfg_path)

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cur = cfg.get("Current", "Default")
    queue = cfg["Configurations"][cur]["TaskQueue"]

    tasks, today, day = _today_tasks(plan, getattr(args, "date", "") or "")
    fights = [p for (t, p) in tasks if t == "Fight"]
    changed = []

    # 预检（与 cmd_run 一致）：MAA 导航不了的关（如活动 EX）**不写进槽位**，
    # 否则用户在 MAA GUI 点「开始」时该槽位 append=0 → 打死整队（见 stage_navigable 注释）。
    blocked = [p.get("stage") for p in fights
               if p.get("stage") and not stage_navigable(p["stage"])]
    if blocked:
        log("!! 以下关 MAA 导航不了（resource 无同名任务），**不写进槽位**：%s" % "、".join(blocked))
        log("   处理：先跑 python scripts/maa-update/maa_update.py check（看远端是否已收录）；"
            "仍无则走作业链（Copilot 用作业导航）——可直接复制：")
        _cmds = []
        if any("-EX-" in s for s in blocked):
            _cmds.append(_copilot_cmd(plan, "ex"))
        if any("-S-" in s and "-EX-" not in s for s in blocked):
            _cmds.append(_copilot_cmd(plan, "s"))
        for _c in (_cmds or [_copilot_cmd(plan, "ex")]):
            log("         " + _c)
    fights = [p for p in fights
              if not (p.get("stage") and not stage_navigable(p["stage"]))]

    # --- Fight：按关卡匹配槽位（一天一天编辑的核心）---
    slots = [q for q in queue if q.get("TaskType") == "Fight"]
    by_stage = {}
    for q in slots:
        by_stage.setdefault(((q.get("StagePlan") or [""])[0]), q)
    insert_at = (max(i for i, q in enumerate(queue) if q.get("TaskType") == "Fight") + 1
                 if slots else len(queue))

    today_stages = set()
    for p in fights:
        stage, times = p.get("stage"), int(p.get("times") or 0)
        if not stage or times <= 0:
            continue
        today_stages.add(stage)
        slot = by_stage.get(stage)
        if slot is None:
            slot = _clone_fight_slot(queue, slots, insert_at)
            slot["StagePlan"] = [stage]
            queue.insert(insert_at, slot)
            insert_at += 1
            slots.append(slot)
            by_stage[stage] = slot
            changed.append("+ Fight 新槽位：%s（克隆现有槽位）" % stage)
        slot["StagePlan"] = [stage]
        slot["EnableTimesLimit"] = True
        slot["TimesLimit"] = times
        slot["IsEnable"] = True
        slot["Name"] = p.get("_name") or stage
        if "series" in p:
            slot["Series"] = int(p["series"])
        changed.append("Fight %-12s ×%-4d series=%s" % (stage, times, p.get("series", "不变")))
    for st, q in by_stage.items():
        if st and st not in today_stages and q.get("IsEnable"):
            q["IsEnable"] = False
            changed.append("Fight %-12s → 停用（不在 %s 计划内）" % (st, today))

    # --- 固定任务：确保启用 + 同步可变量 ---
    want = {}
    for t, p in tasks:
        if t in ("StartUp", "Recruit", "Infrast", "Mall", "Award"):
            want[t] = p
    infra_fac = (want.get("Infrast") or {}).get("facility") or []
    for q in queue:
        tt = q.get("TaskType")
        if tt not in want:
            continue
        if not q.get("IsEnable", True):
            q["IsEnable"] = True
            changed.append("%s → 启用" % tt)
        if tt == "Recruit":
            mt = int((want["Recruit"] or {}).get("times") or 0)
            if mt and int(q.get("MaxTimes") or 0) != mt:
                q["MaxTimes"] = mt
                changed.append("Recruit MaxTimes → %d" % mt)
        elif tt == "Infrast":
            if q.get("Mode") != "Rotation":
                changed.append("Infrast.Mode %s → Rotation（改用 MAA 自带的队列轮换）" % q.get("Mode"))
                q["Mode"] = "Rotation"
            for r in (q.get("RoomList") or []):
                if r.get("Room") == "AssistantChange":
                    continue
                on = r.get("Room") in infra_fac
                if bool(r.get("IsEnabled", True)) != on:
                    r["IsEnabled"] = on
                    changed.append("Infrast.RoomList.%s → %s" % (r.get("Room"), on))

    for q in queue:
        if q.get("TaskType") == "OperProgress" and not (q.get("Plans") or []) and q.get("IsEnable", True):
            q["IsEnable"] = False
            changed.append("OperProgress → 停用（Plans 为空，跑起来 set_params 会失败拖垮队列）")

    log("写入口径：%s（当天）   分配=%s   理智=%s"
        % (today, "、".join("%s×%d" % kv for kv in (day.get("runs") or {}).items()) or "无",
           day.get("sanity")))
    _raids = [p.get("stage") for (t, p) in tasks if t == "Raid"]
    if _raids:
        log("!! 当天含突袭 %s：MAA Fight 做不了活动突袭 → **不写槽位**，走 Copilot is_raid 或手点——可直接复制："
            % "、".join(_raids))
        log("         " + _copilot_cmd(plan, "raid"))

    if args.dry:
        log("[dry] 不写盘。将改动 %d 条：" % len(changed))
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
    """留证截图。设备地址用 `_devices()` 实测（本机常见 `127.0.0.1:5555` 未注册、实际是 `emulator-5554`），
    并**校验返回码/文件大小**——0 字节只打印警告，不静默留个空文件。"""
    TMP.mkdir(parents=True, exist_ok=True)
    p = TMP / ("fail_%s_%s.png" % (tag, dt.datetime.now().strftime("%H%M%S")))
    devs = _devices()
    if not devs:
        try:
            subprocess.run([ADB, "connect", ADDR], capture_output=True, timeout=15)
        except Exception:  # noqa: BLE001
            pass
        devs = _devices()
    dev = devs[0] if devs else ADDR
    rc, size = None, 0
    try:
        with open(p, "wb") as f:
            r = subprocess.run([ADB, "-s", dev, "exec-out", "screencap", "-p"],
                               stdout=f, timeout=40)
        rc = r.returncode
        size = p.stat().st_size if p.exists() else 0
    except Exception as e:  # noqa: BLE001
        log("!! 截图异常（dev=%s）: %r" % (dev, e))
    if rc != 0 or size == 0:
        log("!! 截图失败/为空（dev=%s rc=%s size=%s 字节）: %s" % (dev, rc, size, p))
    else:
        log("截图已留证（dev=%s, %s 字节）: %s" % (dev, size, p))
    return str(p)


_STAGE_KEYS: set | None = None


def _stage_keys() -> set:
    """MAA 认得的关卡名集合 = resource/tasks/tasks.json + resource/tasks/Stages/*.json 的键。"""
    global _STAGE_KEYS
    if _STAGE_KEYS is None:
        keys: set = set()
        paths = [MAA / "resource" / "tasks" / "tasks.json"]
        paths += sorted((MAA / "resource" / "tasks" / "Stages").glob("*.json"))
        for p in paths:
            try:
                keys |= set(json.loads(p.read_text(encoding="utf-8")).keys())
            except Exception:  # noqa: BLE001
                continue
        _STAGE_KEYS = keys
    return _STAGE_KEYS


def stage_navigable(stage: str) -> bool:
    """该关 MAA 能不能导航到（≈ MaaCore `StageNavigationTask::set_stage_name` 的接受条件）。

    能导航 = ① resource 里有同名任务（含 Stages/*.json，如 1-7 / Annihilation / YW-6 / CE-6）；
            ② 别传重开 `SSReopen-XX`（总长 11）；
            ③ 主线关正则 `^[A-Za-z]{0,3}\\d{1,2}-\\d{1,2}(-\\w+)*$`（MaaCore 原正则，来源 docs/MAA-INTERNALS.md §3.2）。
    **注意**：像 `YW-EX-1` 这种「字母-字母-数字」的活动 EX 关**不匹配任何一条** → 现在导航必然失败
    （本机 resource 2026-10-09 里 Stages/YW.json 只有 YW-4/6/7/8，全库无 EX 关定义）。
    """
    if not stage:
        return True
    if stage in _stage_keys():
        return True
    if stage.startswith("SSReopen-") and len(stage) == 11:
        return True
    import re
    return bool(re.match(r"^([A-Za-z]{0,3})(\d{1,2})-(\d{1,2})(?:-?(\w+))*$", stage))


def _preflight(tasks: list, strict: bool, dry: bool = False, event_id: str = "") -> list:
    """剔除 MAA 导航不了的 Fight 关（**别让一条 append=0 把整天的队列打死**）。"""
    out = []
    _cmd_shown = False
    for name, params in tasks:
        stage = (params or {}).get("stage")
        if name == "Fight" and stage and not stage_navigable(stage):
            shot = "" if dry else _shot("unsupported_" + str(stage).replace("/", "_"))
            log("!! 跳过 %s：MAA resource 里没有该关卡任务（导航会失败）%s"
                % (stage, ("→ 截图 %s" % shot) if shot else ""))
            if not _cmd_shown:
                log("   处理：先 python scripts/maa-update/maa_update.py check 看远端资源是否已收录；"
                    "仍未收录 → 走作业链（Copilot 用作业导航）或手点——可直接复制：")
                log("         python scripts/event-copilot/event_copilot.py run %s --chain ex --try"
                    % (event_id or "<活动id>"))
                _cmd_shown = True
            if not dry:
                _report({"ts": _now(), "stage": "preflight", "skipped_stage": stage,
                         "reason": "MAA resource 无此关卡任务", "screenshot": shot})
            if strict:
                raise SystemExit(4)
            continue
        out.append((name, params))
    return out


def _report(entry: dict):
    RUN_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(RUN_REPORT, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _today_tasks(plan: dict, date: str = ""):
    """把「周计划」切成「今天那一份」：StartUp → 当天各关 → Recruit/Infrast/Mall/Award。

    逐日分配优先读 `plan["daily"]`（plan_week 已算好，别再重算 → 口径唯一）；
    老计划没有该字段时才现算（兼容旧 weekly_plan.json）。
    """
    sys.path.insert(0, str(REPO / "scheduling" / "tools"))
    import datetime as dt
    today = date or dt.date.today().isoformat()
    daily = plan.get("daily") or []
    if not daily:
        from plan_util import distribute_daily
        daily = distribute_daily(plan)
    day = next((d for d in daily if d.get("date") == today), None)
    out = []
    for t in plan.get("tasks", []):
        if t.get("type") == "StartUp":
            out.append(("StartUp", merged_params(t)))
            break
    if day:
        # 从 plan.tasks 取每关的 series（连战）：**计划里没写 = 单次**（剿灭/EX 首通别乱套连战）；
        # 计划里没有的关（极少）才回落到 ARK_SERIES（默认 1）。
        series_map, name_map = {}, {}
        for t in plan.get("tasks", []):
            p = t.get("params") or {}
            if t.get("type") == "Fight" and p.get("stage"):
                series_map[p["stage"]] = int(p.get("series") or 1)
                name_map[p["stage"]] = t.get("name") or p["stage"]
        for stage, runs in (day.get("runs") or {}).items():
            if runs > 0:
                prms = {"stage": stage, "times": int(runs), "_name": name_map.get(stage, stage)}
                s = series_map.get(stage, int(os.environ.get("ARK_SERIES", "1")))
                if s > 1:
                    prms["series"] = s
                out.append(("Fight", prms))
        # 突袭（Raid）：MAA Fight 做不了活动突袭 → 独立类型，run 时跳过并提示走 Copilot/手点
        for stage in (day.get("raids") or []):
            out.append(("Raid", {"stage": stage, "_name": "%s 突袭" % stage}))
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

    # 预检：MAA 导航不了的关**跳过**而非打死整条队列（默认；--strict 则直接失败）
    if not getattr(args, "whole_week", False):
        tasks = _preflight(tasks, strict=getattr(args, "strict", False),
                           dry=bool(args.dry), event_id=_event_id(plan))

    if args.dry:
        log("[dry] 将按顺序跑 %d 个任务：%s" % (len(tasks), scope))
        for t, p in tasks:
            log("  %-9s %s" % (t, {k: p[k] for k in ("stage", "times", "mode") if k in p}))
        for s in plan.get("side", []) or []:
            log("  + 附带脚本 %s（%s）" % (s.get("script"), s.get("when")))
        log("[dry] 未执行")
        return

    if _maa_running():
        log("!! MAA GUI 在运行 —— 单客户端纪律：先退出 MAA 再 run")
        _report({**entry, "ok": False, "stage": "precheck", "error": "MAA GUI 正在运行"})
        raise SystemExit(2)

    # 附带脚本（plan.side；基建已改 MAA 自带队列轮换 → 正常为空）—— 先跑；带 if_due 的只在到期时跑
    if not getattr(args, "no_side", False):
        for s in plan.get("side", []) or []:
            sp = REPO / str(s.get("script") or "")
            if not sp.exists():
                log("附带脚本不存在，跳过：%s" % sp)
                continue
            key = s.get("if_due")
            if key and not _due(key):
                log("附带脚本（%s）未到期，跳过" % s.get("when", ""))
                continue
            cmd = [sys.executable, str(sp)] + [str(a) for a in (s.get("args") or [])]
            log("跑附带脚本（%s）：%s %s" % (s.get("when", ""), sp.name, " ".join(s.get("args") or [])))
            r = subprocess.run(cmd, cwd=str(REPO))
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
        if name == "Raid":
            # 突袭：MAA `Fight` 做不了活动突袭（`is_raid` 只在 Copilot `copilot_list` 里，
            # 见 docs/MAA-INTERNALS.md §2.10）→ 不 append，交给 event-copilot / 手点（非错误）。
            _stage = (params or {}).get("stage")
            log("!! Raid %s：MAA Fight 做不了活动突袭 → 走 Copilot is_raid 或手点；跳过 append——可直接复制："
                % _stage)
            log("         " + _copilot_cmd(plan, "raid"))
            _report({**entry, "ok": True, "stage": "raid-skip", "raid_stage": _stage,
                     "hint": "event-copilot --chain raid / 手点",
                     "cmd": _copilot_cmd(plan, "raid")})
            continue
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
            p.add_argument("--date", default="", help="写哪一天（默认今天）——队列按天编辑")
            p.add_argument("--dry", action="store_true")
            p.add_argument("--force", action="store_true", help="MAA 在跑也写（危险）")
        if name == "show":
            p.add_argument("--date", default="", help="另标出哪一天（默认今天）")
        if name == "run":
            p.add_argument("--timeout", type=int, default=7200)
            p.add_argument("--dry", action="store_true")
            p.add_argument("--date", default="", help="跑哪一天（默认今天）")
            p.add_argument("--whole-week", action="store_true", help="跑整周总量（默认只跑当天）")
            p.add_argument("--no-side", action="store_true", help="不跑 plan.side 里的附带脚本")
            p.add_argument("--strict", action="store_true",
                           help="预检发现 MAA 导航不了的关时直接失败（默认是跳过并继续）")
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
