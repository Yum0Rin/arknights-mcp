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
import re
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

# 基建（2026-10-14 用户裁定「选 2」）：改用 MAA **自定义换班**（`mode=10000` Custom）。
#   · Custom 才**逐设施摆干员** + 执行**菲亚梅塔置换**（方案里的 `Fiammetta` 块，MaaCore `InfrastTask.cpp:420-464`）；
#     Rotation(20000) 只点一次游戏内「队列轮换」且 `skip shift`（不摆干员、不做菲亚梅塔）。见 docs/FINDINGS.md §24。
#   · 方案表 = 一图流「243 搓玉两换」（`scheduling/一图流产物/243-搓玉-合成玉-MAA.json`）经
#     `scheduling/tools/convert_to_maa.py` 转成 MAA `custom_infrast` 格式，落在**仓库**里
#     `scheduling/MAA基建排班/243_搓玉_定制.json` —— 放仓库而不是 MAA 的 resource 目录：防 MAA 更新覆盖、可版本管理。
#     两份 plan：index 0 = B班、index 1 = A班（干员已核对：29/29 全持有）。
#     ⚠ **绝不能指回 `C:\MAA\resource\custom_infrast\maa-243-custom.json`** —— 那是「钱书均衡·龙门币优先」版
#       （2026-10-14 核对：该文件与 `scheduling/一图流产物/243-钱书均衡-龙门币优先-MAA.json` 哈希相同），
#       **不是《搓玉·合成玉》方案**（搓玉 = 制造站产源石碎片 + 贸易站卖合成玉）。
#   · ⚠ MAA **不看** plan 里的 `period`（那是 GUI「按时间自动选」用的），也**不吃** `plan_index=-1`
#     （Core 里 `index < 0` → set_params false → append 0 打死整队）→ 由**我们显式传** plan_index：
#       14:00「方舟·每日日常」→ A班(1)；02:00「方舟·凌晨基建换班」→ B班(0)。
INFRAST_CUSTOM_FILE = os.environ.get(
    "ARK_INFRAST_CUSTOM_FILE",
    str(REPO / "scheduling" / "MAA基建排班" / "243_搓玉_定制.json"))
INFRAST_PLAN_DAY = 1      # 14:00「每日日常」跑的那一班（A班）
INFRAST_PLAN_NIGHT = 0    # 02:00「凌晨基建换班」跑的那一班（B班）
INFRAST_FACILITY = ["Mfg", "Trade", "Power", "Control", "Reception",
                    "Office", "Dorm", "Processing", "Training"]


def infrast_params(plan_index: int | None = None, facility: list | None = None) -> dict:
    """基建 `Infrast` 的 params（Custom 口径）—— **唯一出口**，别在别处手写 mode/filename。

    `plan_index=None` → 用「白天那一班」(INFRAST_PLAN_DAY)。
    """
    return {
        "mode": 10000,
        "filename": INFRAST_CUSTOM_FILE,
        "plan_index": INFRAST_PLAN_DAY if plan_index is None else int(plan_index),
        "facility": list(facility or INFRAST_FACILITY),
    }


# 与 arknights_mcp.py 的 TASK_DEFAULTS 保持一致；公招口径对齐 GUI（3/4/5、6 星不自动）
TASK_DEFAULTS = {
    "Recruit": {"select": [3, 4, 5], "confirm": [3, 4, 5], "times": 50},
    "StartUp": {"client_type": "Official"},
    "Infrast": infrast_params(),
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
        raise SystemExit("找不到计划文件: %s\n  修复：python scheduling/tools/plan_week.py   （生成本周计划）" % p)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # 读不了 / JSON 损坏 → 给可操作提示，别甩 traceback
        raise SystemExit("计划文件读取/解析失败: %s（%r）\n  修复：python scheduling/tools/plan_week.py   （重新生成）"
                         % (p, e))


def merged_params(task: dict) -> dict:
    p = dict(TASK_DEFAULTS.get(task["type"], {}))
    p.update(task.get("params") or {})
    return p


# ---------------------------------------------------------------------------
# 防御：把「周计划」定位到「今天」，识别「今天不在计划里」
#   计划过期 / 该日无分配时，**不能静默**跑成「只做了日常杂活」或悄悄停用所有 Fight 槽位。
#   判定逻辑统一放在 plan_util.plan_day（与 GUI 长草页共用一份口径，避免两处漂移）。
# ---------------------------------------------------------------------------
def _plan_day(plan, today: str):
    """定位 today 在计划里的分配。返回 (day | None, status)。

    委托 plan_util.plan_day（**与 GUI 长草页同一份口径**）。status 见该函数文档：
    ok / out_of_range / no_entry / no_daily。
    """
    sys.path.insert(0, str(REPO / "scheduling" / "tools"))
    from plan_util import plan_day
    return plan_day(plan, today)


def _plan_day_error(status: str, today: str, plan) -> str:
    """把 status 翻成人话。"""
    rng = (plan or {}).get("range") or "?"
    if status == "out_of_range":
        return ("今天 %s 不在计划区间 [%s] 内 —— 计划已过期或未生成到本周。"
                % (today, rng))
    if status == "no_daily":
        return ("计划没有 daily 逐日表，且现算失败 —— 计划文件可能损坏（range=%s）。" % rng)
    return "计划区间 [%s] 内缺 %s 这一天的分配 —— 计划不完整。" % (rng, today)


def _plan_day_fail(status: str, today: str, plan, force: bool, action: str) -> None:
    """今天不在计划里时的统一处理：报因 + 给修复命令；默认 SystemExit，--force 才继续。"""
    log("!! " + _plan_day_error(status, today, plan))
    log("   修复：python scheduling/tools/plan_week.py   （重新生成本周计划）")
    if not force:
        raise SystemExit(2)
    log("   --force：继续，但**今天不会刷关**（%s 只处理日常：StartUp/公招/基建/信用/领奖）。" % action)


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------
def cmd_show(args):
    plan = load_plan(args.plan)
    print("本周计划：%s   %s" % (plan.get("week", "?"), plan.get("range", "")))
    print("生成：%s by %s" % (plan.get("generated_at", "?"), plan.get("by", "?")))
    _cap = _series_cap()
    print("连战上限：%d（判据：本机 resource %s `FightSeries-OldMethodFlag`）"
          % (_cap, "有" if _cap == 6 else "无"))
    b = plan.get("budget", {})
    _mu = b.get("meds_usable")
    if _mu is None:                       # 老计划没有 meds_usable → 退回读数
        _mu = b.get("meds_available")
    print("理智预算：自然 %s + 周常 %s + 理智药 %s（读数 %s，整瓶可用）"
          % (b.get("sanity_natural"), b.get("weekly_potion"), _mu, b.get("meds_available")))
    print("\n任务序列：")
    for i, t in enumerate(plan.get("tasks", []), 1):
        pr = merged_params(t)
        desc = pr.get("stage") or pr.get("mode") or ""
        times = ("×%s" % pr["times"]) if "times" in pr else ""
        print("  %2d. %-9s %s %s" % (i, t["type"], desc, times))
    for s in plan.get("side", []):
        print("  +  附带脚本 %s  [%s]" % (s.get("script"), s.get("when")))
    # 逐日表：队列「按天编辑」就看这一张
    today = getattr(args, "date", "") or dt.date.today().isoformat()
    daily = plan.get("daily") or []
    if daily:
        print("\n逐日分配（%s ← 今天；write/run 默认只下这一天）：" % today)
        for d in daily:
            runs = "、".join("%s×%d" % kv for kv in (d.get("runs") or {}).items()) or "无"
            if d.get("raids"):
                runs += "  突袭:%s" % "、".join(d.get("raids") or [])
            mark = ">>" if d.get("date") == today else "  "
            print("  %s %s(%s)  理智 %-5s / 软上限 %-5s 药 %-4s %s%s"
                  % (mark, d.get("date"), d.get("dow", ""), d.get("sanity", 0),
                     d.get("day_cap", d.get("cap", "")), d.get("medicine", 0), runs,
                     "  !!未排下:%s" % d["unplaced"] if d.get("unplaced") else ""))
    # 防御：今天不在计划里就醒目提示（write/run 会因此拒绝执行）
    _day, _status = _plan_day(plan, today)
    if _status != "ok":
        print("\n  !! 今天不在计划里：%s" % _plan_day_error(_status, today, plan))
        print("    修复：python scheduling/tools/plan_week.py   （重新生成本周计划）")
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
def _run_console(cmd, timeout=20):
    """跑外部控制台命令，返回 (rc, 文本)。

    ⚠ 不能用 `text=True` 的默认解码：父进程（daily-auto）会传 `PYTHONUTF8=1`，
    那会把**默认编码**改成 UTF-8，而 Windows 的 tasklist/adb/ldconsole 输出是 GBK
    → 读线程 `UnicodeDecodeError` → stdout 变 None（2026-10-14~18 每日日志里那串
    Traceback 就是它，且导致 `_maa_running()` 恒 False、MAA GUI 互斥护栏失效）。
    这里拿原始 bytes，先按 UTF-8 试，失败再按 GBK 兜底。
    """
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except Exception:  # noqa: BLE001
        return -1, ""
    raw = (r.stdout or b"") + (r.stderr or b"")
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        txt = raw.decode("gbk", errors="replace")
    return r.returncode, txt


def _maa_running() -> bool:
    _rc, out = _run_console(["tasklist", "/FI", "IMAGENAME eq MAA.exe"])
    return "MAA.exe" in out


class _StallWatch:
    """盯 MaaCore 日志尾部，识别「卡在基建选人」的死循环。

    2026-10-15/17 的凌晨换班：方案表指定的干员选不上（心情涣散/被占用），MAA 不做降级，
    只反复翻页重试 —— `no custom operators found` / `select opers review fail` 刷几百次，
    20+ 分钟不结束，最后靠超时收场（B 班没换成）。
    这里数「新增」这类告警：超过阈值就主动 stop，把 25 分钟的死等收敛成几分钟的明确失败。
    """

    PATTERNS = ("no custom operators found", "select opers review fail",
                "name not in this page")

    def __init__(self, limit: int = 120, path=None):
        self.path = pathlib.Path(path) if path else (TMP / "maa" / "debug" / "asst.log")
        self.limit = limit
        self.hits = 0
        try:
            self.pos = self.path.stat().st_size
        except OSError:
            self.pos = 0

    def poll(self) -> int:
        """读日志新增部分并累计命中数（只读增量，不扫全文件）。"""
        try:
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                chunk = f.read()
                self.pos = f.tell()
        except OSError:
            return self.hits
        if chunk:
            txt = chunk.decode("utf-8", "replace")
            for p in self.PATTERNS:
                self.hits += txt.count(p)
        return self.hits


def _event_id(plan) -> str:
    return str((plan or {}).get("event") or "<活动id>")


def _copilot_cmd(plan, kind: str) -> str:
    """可直接复制的 event-copilot 命令（EX/S 首通/突袭链）。"""
    return ("python scripts/event-copilot/event_copilot.py run %s --chain %s --try"
            % (_event_id(plan), kind))


def _series_cap() -> int:
    """本机连战上限（运行时按资源判定：有 FightSeries-OldMethodFlag → 6，无 → 10）。"""
    try:
        sys.path.insert(0, str(REPO / "scheduling" / "tools"))
        import plan_util
        return int(plan_util.series_cap())
    except Exception:  # noqa: BLE001
        return 10


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

    tasks, today, day, status = _today_tasks(plan, getattr(args, "date", "") or "")
    if status != "ok":
        # 防御：今天不在计划里 → 明确报错（默认停），别静默把 Fight 槽位全停用。
        _plan_day_fail(status, today, plan, getattr(args, "force", False), "写 MAA 配置")
        log("   → 继续写：所有 Fight 槽位会被停用（今天无刷关）。")
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
            slot["Series"] = min(int(p["series"]), _series_cap())
        # 用药：把当天药量同步到 GUI 槽位（只配药的关有计划药量；剿灭/EX 为 0）
        med = int(p.get("medicine") or 0)
        slot["UseMedicine"] = bool(med)
        slot["MedicineCount"] = med
        slot["MedicineExpireDays"] = 2
        slot["UseExpiringMedicine"] = bool(med)     # 临期药也吃（2 天阈值，沿用现有字段语义）
        changed.append("Fight %-12s ×%-4d series=%s 药=%d"
                       % (stage, times, p.get("series", "不变"), med))
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
            # 2026-10-14 改口径：Rotation → Custom（自定义换班，含菲亚梅塔置换）。见 docs/FINDINGS.md §24。
            if q.get("Mode") != "Custom":
                changed.append("Infrast.Mode %s → Custom（改用自定义换班方案表）" % q.get("Mode"))
                q["Mode"] = "Custom"
            if q.get("Filename") != INFRAST_CUSTOM_FILE:
                changed.append("Infrast.Filename %s → %s" % (q.get("Filename"), INFRAST_CUSTOM_FILE))
                q["Filename"] = INFRAST_CUSTOM_FILE
            if int(q.get("PlanSelect", -1)) != INFRAST_PLAN_DAY:
                changed.append("Infrast.PlanSelect %s → %d（14:00 跑 A班）"
                               % (q.get("PlanSelect"), INFRAST_PLAN_DAY))
                q["PlanSelect"] = INFRAST_PLAN_DAY
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
    _rc, out = _run_console([ADB, "devices"], timeout=20)
    return [l.split("\t")[0] for l in (out or "").splitlines()[1:] if "\tdevice" in l]


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


def _ensure_device(wait_s: int = 180) -> list:
    """确保有在线设备：没有就拉起雷电并等它上线。返回设备列表。

    防御：让 GUI「直驱跑一键长草」从冷启动也能跑 —— 模拟器没开时自动拉起，
    而不是 connect 失败就整趟退出（用户点一次按钮就该跑起来）。
    """
    devs = _devices()
    if devs:
        return devs
    log("未检测到在线设备 → 启动雷电模拟器…")
    if not _start_emulator():
        raise SystemExit("启动模拟器失败（找不到 %s）" % EMULATOR)
    if not _wait_device(wait_s):
        raise SystemExit("等模拟器上线超时（%ds）—— 首次启动较慢，可加大超时" % wait_s)
    return _devices()


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
        # 活动 EX：MAA 的 Fight **打不了**（stages.json 里没有 EX 关），但计划里会照排（理智要对账）。
        # → 这里静默改道：不 append Fight，交给跑完日常后的 Copilot 链（ex_auto --auto）去打。
        if name == "Raid":
            # 突袭同理：交给 ex_auto 的突袭链（这里只从队列里摘掉，dry 输出也就对得上）
            log("活动突袭 %s：改由 Copilot 突袭链补打（ex_auto --with-raid）" % stage)
            continue
        if name == "Fight" and stage and "-EX-" in str(stage):
            log("活动 EX 关 %s：Fight 不支持 → 改由 Copilot 链补打（ex_auto，日常跑完自动执行）" % stage)
            continue
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
    返回 (tasks, today, day, status)；status != "ok" 表示今天不在计划里（调用方须防御）。
    """
    today = date or dt.date.today().isoformat()
    day, status = _plan_day(plan, today)
    out = []
    for t in plan.get("tasks", []):
        if t.get("type") == "StartUp":
            out.append(("StartUp", merged_params(t)))
            break
    if day:
        # 从 plan.tasks 取每关的 series（连战）：**计划里没写 = 单次**（剿灭/EX 首通别乱套连战）；
        # 计划里没有的关（极少）才回落到 ARK_SERIES（默认 = 本机 series_cap()）。
        series_map, name_map = {}, {}
        for t in plan.get("tasks", []):
            p = t.get("params") or {}
            if t.get("type") == "Fight" and p.get("stage"):
                series_map[p["stage"]] = int(p.get("series") or 1)
                name_map[p["stage"]] = t.get("name") or p["stage"]
        med_stages = set(plan.get("medicine_stages") or [])
        day_med = int(day.get("medicine") or 0)
        for stage, runs in (day.get("runs") or {}).items():
            if runs > 0:
                prms = {"stage": stage, "times": int(runs), "_name": name_map.get(stage, stage)}
                s = series_map.get(stage, int(os.environ.get("ARK_SERIES", str(_series_cap()))))
                if s > 1:
                    prms["series"] = s
                # 用药：只给「配上药的关」（1-7/活动关）；剿灭/EX 首通不吃药
                if stage in med_stages and day_med > 0:
                    prms["medicine"] = day_med
                    prms["medicine_expire_days"] = 2      # 临期药也吃（沿用现有字段语义）
                out.append(("Fight", prms))
        # 突袭（Raid）：MAA Fight 做不了活动突袭 → 独立类型，run 时跳过并提示走 Copilot/手点
        for stage in (day.get("raids") or []):
            out.append(("Raid", {"stage": stage, "_name": "%s 突袭" % stage}))
    for t in plan.get("tasks", []):
        if t.get("type") in ("Recruit", "Infrast", "Mall", "Award"):
            out.append((t["type"], merged_params(t)))
    return out, today, (day or {}), status


def cmd_run(args):
    plan = load_plan(args.plan)
    if args.whole_week:
        tasks = [(t["type"], merged_params(t)) for t in plan.get("tasks", [])]
        scope = "整周"
    else:
        tasks, today, day, status = _today_tasks(plan, getattr(args, "date", "") or "")
        has_raids = bool((day or {}).get("raids"))
        if status != "ok":
            # 防御：今天不在计划里 → 明确报错（默认停），别静默只跑日常却像"跑过了"。
            _plan_day_fail(status, today, plan, getattr(args, "force", False), "直驱跑一键长草")
        scope = "%s（当天）" % today
        if not ((day.get("runs") or {}) or (day.get("raids") or [])):
            log("!! 今天 %s 计划里没有刷关任务（runs 为空）—— 只跑日常：基建/公招/信用/领奖。" % today)
        log("今天分配：%s   理智 %s" % ("、".join("%s×%d" % kv for kv in (day.get("runs") or {}).items())
                                      or "无", day.get("sanity")))
    entry = {"ts": _now(), "week": plan.get("week"), "scope": scope, "tasks": [t for t, _ in tasks]}

    # [dry] 不动设备、不截图：只把队列和跳关判据打印出来
    if args.dry:
        if not getattr(args, "whole_week", False):
            tasks = _preflight(tasks, strict=getattr(args, "strict", False),
                               dry=True, event_id=_event_id(plan))
        log("[dry] 将按顺序跑 %d 个任务：%s" % (len(tasks), scope))
        for t, p in tasks:
            log("  %-9s %s" % (t, {k: p[k] for k in ("stage", "times", "mode") if k in p}))
        for s in plan.get("side", []) or []:
            log("  + 附带脚本 %s（%s）" % (s.get("script"), s.get("when")))
        log("[dry] 未执行")
        return

    # 单客户端纪律：MAA GUI 在跑就别抢设备（这一步不碰设备，摊在最前）
    if _maa_running():
        log("!! MAA GUI 在运行 —— 单客户端纪律：先退出 MAA 再 run")
        _report({**entry, "ok": False, "stage": "precheck", "error": "MAA GUI 正在运行"})
        raise SystemExit(2)

    # 防御：确保有在线设备（没有就自动拉起雷电），否则 connect 必失败 —— 让一键从冷启动也能跑
    # ⚠ 必须放在 preflight **之前**：preflight 会给「MAA 不支持的关」截图留证，
    #   设备没上线时 screencap 返回空 → 留一堆 0 字节 PNG（2026-10-16 的 8 张空图）。
    try:
        _ensure_device()
    except SystemExit as e:
        log("!! %s" % e)
        _report({**entry, "ok": False, "stage": "device", "error": str(e)})
        raise

    # 预检：MAA 导航不了的关**跳过**而非打死整条队列（默认；--strict 则直接失败）
    if not getattr(args, "whole_week", False):
        tasks = _preflight(tasks, strict=getattr(args, "strict", False),
                           dry=False, event_id=_event_id(plan))

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
            # 活动突袭：MAA 的 Fight 做不了（is_raid 只在 Copilot 里）→ 也交给 ex_auto 的突袭链，
            # 这里不再报「跳过」，免得 run_report 每天刷一堆 raid-skip。
            log("活动突袭 %s：改由 Copilot 突袭链补打（ex_auto --with-raid，跑完日常自动执行）"
                % (params or {}).get("stage"))
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
    watch = _StallWatch()
    stalled = False
    t0 = time.time()
    last_probe = 0.0
    while a.running() and time.time() - t0 < args.timeout:
        time.sleep(1.0)
        if time.time() - last_probe >= 5:
            last_probe = time.time()
            if watch.poll() >= watch.limit:
                stalled = True
                break
    if stalled:
        log("!! 疑似卡在基建选人（日志里「找不到干员」类告警 %d 次）→ 主动停止，不再空等到超时" % watch.hits)
        try:
            a.stop()
        except Exception:  # noqa: BLE001
            pass
        for _ in range(30):
            if not a.running():
                break
            time.sleep(1.0)
        shot = _shot("stalled")
        _report({**entry, "ok": False, "stage": "stalled", "hits": watch.hits,
                 "elapsed": round(time.time() - t0, 1), "tids": tids, "screenshot": shot})
        raise SystemExit(6)
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

    # 3) 活动 EX 自动补打（**并进「一键长草」**：MAA 的 Fight 打不了 EX，只能走 Copilot；
    #    这里不需要任何人点按钮，日常 14:00 跑完就顺手把没通的 EX 打掉）
    if not getattr(args, "no_ex", False):
        # 先把这个 MaaCore 实例放掉，避免和 ex_auto 的新实例抢同一个设备（单客户端纪律）
        try:
            a.stop()
        except Exception:  # noqa: BLE001
            pass
        del a
        import gc
        gc.collect()
        # 用户 2026-10-18 定：突袭也**自动打**（普通清完自动接突袭；理智不够由 MAA 自己停）
        _run_ex_auto(entry, with_raid=True)


def _run_ex_auto(entry: dict, with_raid: bool = False) -> None:
    """跑 scripts/event-copilot/ex_auto.py --auto（自动发现未通 EX 并打）——失败只记日志不中断。"""
    ex = REPO / "scripts" / "event-copilot" / "ex_auto.py"
    if not ex.exists():
        log("活动 EX：找不到 ex_auto.py，跳过")
        return
    log("活动 EX：自动补打未通关（ex_auto --auto）…")
    t0 = time.time()
    try:
        cmd = [sys.executable, str(ex), "--auto", "--timeout", "600", "--budget", "3600"]
        if with_raid:
            cmd.append("--with-raid")     # 计划里排了突袭 → 普通清完后接着打突袭
        r = subprocess.run(cmd,
                           cwd=str(REPO), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=5400,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        rc = r.returncode
        out = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        rc, out = -1, "超时（5400s）"
    for ln in (out or "").strip().splitlines()[-8:]:
        log("  | " + ln)
    log("活动 EX 自动补打结束：rc=%s（%.0fs）" % (rc, time.time() - t0))
    _report({**entry, "stage": "ex-auto", "ok": rc == 0, "rc": rc,
             "elapsed": round(time.time() - t0, 1)})


def cmd_startup(args):
    """先确保模拟器在线（不在线就拉起雷电），再用 MaaCore 的 StartUp 启动/唤醒游戏。"""
    devs = _ensure_device(args.emulator_timeout)
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


def cmd_depot(args):
    """读一次仓库（跑 MAA `Depot` 任务）→ 写 `C:\\MAA\\data\\DepotData.json`（供收益账本 collect 用）。

    背景：直驱 MaaCore **不会**写 DepotData.json（只有 MAA GUI 会写），所以这里自己**捕获
    `DepotInfo` 回调**（msg 20003）并落盘，让每日自动化的收益账本能拿到新鲜仓库读数。
    设备需在线（游戏开着）；`--startup` 可先把游戏带到主界面。
    """
    devs = _ensure_device(args.emulator_timeout)
    log("模拟器已在线：%s" % devs)

    sys.path.insert(0, str(MAA / "Python"))
    from asst.asst import Asst
    from asst.utils import InstanceOptionType
    user_dir = TMP / "maa"
    user_dir.mkdir(parents=True, exist_ok=True)
    Asst.load(str(MAA), user_dir=str(user_dir))
    snap: dict = {}

    def _cb(m, d, x):
        try:
            o = json.loads(d.decode("utf-8", "ignore"))
        except Exception:  # noqa: BLE001
            return
        if int(m) == 20003 and o.get("what") == "DepotInfo":
            det = o.get("details") or {}
            if det.get("done"):
                snap["depot"] = det

    a = Asst(Asst.CallBackType(_cb))
    a.load(str(MAA))
    a.set_instance_option(InstanceOptionType.touch_type, TOUCH)
    connected = False
    for addr in [ADDR] + [d for d in _devices() if d != ADDR]:
        try:
            if a.connect(ADB, addr, "General"):
                connected = True
                log("已连接设备：%s" % addr)
                break
        except Exception as e:  # noqa: BLE001
            log("连接 %s 失败：%r" % (addr, e))
    if not connected:
        raise SystemExit("连接模拟器失败 —— 确认雷电已开")

    if args.startup:
        a.append_task("StartUp", {"client_type": args.client, "start_game_enabled": True})

    def _run_once() -> dict:
        """跑一次 Depot，返回识别到的 {itemId: qty}（失败返回 {}）。"""
        snap.clear()
        tid = a.append_task("Depot", {"enable": True})
        if not tid:
            raise SystemExit("Depot append 失败（id=0）")
        a.start()
        t0 = time.time()
        while a.running() and time.time() - t0 < args.timeout:
            time.sleep(1.0)
        det = snap.get("depot")
        if not det:
            log("!! 未捕获 DepotInfo（超时=%s）" % (time.time() - t0 > args.timeout))
            return {}
        data = det.get("data")
        return json.loads(data) if isinstance(data, str) else (data or {})

    # ---- 重试：MAA 偶尔只翻 3 页就 done=true（2026-10-18：47 项 vs 平日 85 项）----
    out = MAA / "data" / "DepotData.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    parsed = {}
    attempts = max(1, int(getattr(args, "retries", 2)))
    for i in range(1, attempts + 1):
        got = _run_once()
        log("第 %d 次识别：%d 项" % (i, len(got or {})))
        if len(got or {}) > len(parsed or {}):
            parsed = got
        if len(parsed or {}) >= 60:   # 平日 85~87，60 已足够说明翻页没提前结束
            break
        if i < attempts:
            log("   偏少（<60 项），重试一次…")
    if not parsed:
        raise SystemExit("未捕获 DepotInfo —— 可能未进到仓库")

    # ---- 完整性护栏（2026-10-18 踩过：47 项被当成「其它全消耗光」，账本结出一整条假账）----
    prev = {}
    try:
        prev = json.loads(out.read_text(encoding="utf-8")).get("data") or {}
    except Exception:  # noqa: BLE001
        prev = {}
    n_new, n_prev = len(parsed or {}), len(prev or {})
    ratio = (n_new / n_prev) if n_prev else 1.0
    suspicious = bool(n_prev >= 40 and n_new < max(30, n_prev * args.min_ratio))
    if suspicious and not getattr(args, "force", False):
        bak = out.with_name("DepotData.json.incomplete-%s" % _now().replace("-", "").replace(":", "").replace(" ", "-"))
        bak.write_text(json.dumps({"done": True, "data": parsed}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        log("!! 仓库识别疑似不全：本次 %d 项 / 上次 %d 项（%.0f%% < %.0f%%）→ **不覆盖** %s"
            % (n_new, n_prev, ratio * 100, args.min_ratio * 100, out.name))
        log("   本次读数另存：%s" % bak)
        log("   处理：重跑 python scripts/maa-week/maa_week.py depot（确认仓库页停在「全部/材料」且未滚动）"
            "；确认确实是大量清空才加 --force 强制写入")
        _report({"ts": _now(), "ok": False, "stage": "depot-incomplete",
                 "items": n_new, "prev_items": n_prev, "saved_as": str(bak)})
        raise SystemExit(5)

    if n_prev:
        bak = out.with_name("DepotData.json.bak-%s" % _now().replace("-", "").replace(":", "").replace(" ", "-"))
        try:
            bak.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    out.write_text(json.dumps({"done": True, "data": parsed}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    log("仓库已写入 %s（%d 项%s）" % (out, n_new, "，上次 %d" % n_prev if n_prev else ""))


# ---------------------------------------------------------------------------
# sanity：读主界面理智数字（只读；给收益账本一个真读数，别再恒 160）
# ---------------------------------------------------------------------------
OCR_DIR = pathlib.Path.home() / ".config" / "opencode" / "tools" / "ocr"
SANITY_JSON = REPO / "scheduling" / "data" / "sanity.json"
SANITY_CAP = 205


def _ocr_boxes(png_path: str) -> list:
    sys.path.insert(0, str(OCR_DIR))
    import ocr as ocrlib  # noqa: PLC0415
    return ocrlib.recognize(png_path, True) or []


# 结算界面底部有「理智返还」——旧逻辑只要文本含「理智」就当成主界面锚点，
# 于是按 (Δ-124, Δ-64) 点进结算界面（2026-10-19 踩过：点完游戏进入加载，理智读不到）。
_SANITY_BAD_WORDS = ("返还", "恢复", "提升", "药剂", "消耗", "上限", "不足", "补充", "领取")
RESULT_MARKERS = ("行动结束", "MISSION RESULTS", "战斗结束", "作战结束", "理智返还")
LOADING_MARKERS = ("RHODESISLAND", "NOWLOADING", "LOADING", "正在加载", "资源加载")


def _png_size(p) -> tuple:
    """读 PNG 头拿 (w, h)；失败返回 (0, 0)。不依赖 PIL。"""
    try:
        with open(p, "rb") as f:
            head = f.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return 0, 0
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    except Exception:  # noqa: BLE001
        return 0, 0


def _parse_sanity(boxes: list, w: int = 0, h: int = 0):
    """从整帧 OCR 框里找**主界面**理智条锚点，返回 (cx, cy) 或 None。

    2026-10-18 实测：这个主题的主界面**只渲染「理智 /205」，当前数值不显示在数字位置**
    （截图放大确认过，不是 OCR 漏读）→ 只能靠点「+」开药剂面板、读面板里的「当前 » 总量」。

    2026-10-19 收紧（同时保留 10-18 的坐标口径）：
      · 主界面理智条在右侧中部（`sanity_potion.PLUS=(1107,282)` → 锚点约 (1231,346)，约 0.32H），
        所以只接受 `0.12H ~ 0.60H` 的锚点；结算界面的「理智返还」在 ~0.9H，天然排除；
      · 优先认独立的 `/205` 框（10-18 实际走的就是它）；再认「理智/205」合并框；
      · 排除「理智返还」等结算/弹窗文案；
      · OCR 把「理智」和「/205」拆成两个框时，要求两者垂直相邻（±45px）。
    """
    y_lo, y_hi = (h * 0.12 if h > 0 else 0), (h * 0.60 if h > 0 else 10 ** 9)

    def _in_band(b):
        cy = int(b.get("cy") or 0)
        return y_lo <= cy <= y_hi

    def _ok_text(t):
        return ("理智" in t) and not any(bad in t for bad in _SANITY_BAD_WORDS)

    # A) 独立容量框「/205」（主界面主题只渲染容量，10-18 实测走这条）
    for b in boxes:
        t = (b.get("text") or "").replace(" ", "")
        if re.fullmatch(r"[/／]\s*%d" % SANITY_CAP, t) and _in_band(b):
            return int(b.get("cx") or 0), int(b.get("cy") or 0)
    # B) 合并框「理智/205」
    for b in boxes:
        t = (b.get("text") or "").replace(" ", "")
        if not _ok_text(t) or not _in_band(b):
            continue
        if re.search(r"[/／]\s*\d{2,4}", t):
            return int(b.get("cx") or 0), int(b.get("cy") or 0)
    # C) 拆框：「理智」+ 垂直相邻的「/205」→ 用数字框中心（与 A 的坐标口径一致）
    for b in boxes:
        t = (b.get("text") or "").replace(" ", "")
        if t != "理智" or not _in_band(b):
            continue
        cy = int(b.get("cy") or 0)
        for nb in boxes:
            t2 = (nb.get("text") or "").replace(" ", "")
            if re.fullmatch(r"[/／]\s*%d" % SANITY_CAP, t2) and _in_band(nb) \
                    and abs(cy - int(nb.get("cy") or 0)) <= 45:
                return int(nb.get("cx") or 0), int(nb.get("cy") or 0)
    # D) 最后兜底：只有「理智」二字（容量数字没被 OCR 到）→ 只认已知主界面坐标带
    #    （右侧中部；sanity_potion.PLUS=(1107,282)，锚点约 (1231,346)）。别放宽成全屏。
    if w > 0:
        for b in boxes:
            t = (b.get("text") or "").replace(" ", "")
            if t != "理智":
                continue
            cx, cy = int(b.get("cx") or 0), int(b.get("cy") or 0)
            if 0.55 * w <= cx <= 0.75 * w and 0.22 * h <= cy <= 0.45 * h:
                return cx, cy
    return None


def _parse_panel_sanity(boxes: list):
    """从药剂面板 OCR 读「当前 » 总量」；返回 (当前, 总量) 或 None。"""
    texts = [((b.get("text") or "") + "") for b in boxes]
    joined = "".join(texts)
    m = re.search(r"(\d{1,4})\s*[》»≫>]\s*(\d{1,4})", joined)
    if m:
        cur, tot = int(m.group(1)), int(m.group(2))
        if 0 <= cur <= SANITY_CAP and cur <= tot <= 9999:
            return cur, tot
    # 兜底：只有「提升 N 理智」+ 总量时反推
    return None


def _grab(png: pathlib.Path) -> bool:
    """adb 截图到 png；成功（非空）返回 True。"""
    devs = _devices()
    dev = devs[0] if devs else ADDR
    try:
        with open(png, "wb") as f:
            r = subprocess.run([ADB, "-s", dev, "exec-out", "screencap", "-p"],
                               stdout=f, timeout=40)
        return r.returncode == 0 and png.stat().st_size > 0
    except Exception as e:  # noqa: BLE001
        log("截图异常（%s）：%r" % (dev, e))
        return False


def _tap_xy(x: int, y: int):
    devs = _devices()
    dev = devs[0] if devs else ADDR
    subprocess.run([ADB, "-s", dev, "shell", "input", "tap", str(int(x)), str(int(y))],
                   capture_output=True, timeout=20)


def _key_back(devs=None):
    """按一次 Android BACK（只用于「离开结算/关卡界面回主界面」，不点任何游戏按钮）。"""
    dev = (devs[0] if devs else ADDR)
    subprocess.run([ADB, "-s", dev, "shell", "input", "keyevent", "4"],
                   capture_output=True, timeout=20)


PANEL_CANCEL = (1224, 972)   # 药剂面板底部 ✕（只关面板，**绝无点 ✓ 的路径**）


def cmd_sanity(args):
    """读一次主界面理智 → 写 scheduling/data/sanity.json 的 current_sanity。

    实测（2026-10-18）：这个主题主界面只显示「理智 /205」，**当前数值不渲染** →
    只能点理智条上的「+」打开药剂面板，读面板里的「当前 » 总量」，再点 ✕ 关掉。

    安全边界（务必保留）：
      · 每轮只点 `+` 与底部 `✕`；**代码里没有任何点 ✓ 的路径**（✓ 在面板右下，绝不触碰）。
      · **认不出主界面就绝不点任何按钮**：结算/关卡界面只按 BACK，加载界面只等待；
        面板没打开就重试，不盲点其它位置（2026-10-19 就是「理智返还」被当成锚点，点进加载）。
      · 读不到就返回 3，**不写** sanity.json。
    """
    devs = _ensure_device(args.emulator_timeout)
    log("模拟器已在线：%s" % devs)
    TMP.mkdir(parents=True, exist_ok=True)
    png = TMP / "sanity.png"
    png2 = TMP / "sanity_panel.png"
    got = None
    back_left = max(0, args.back)
    tries = max(1, args.tries)
    for i in range(tries):
        if not _grab(png):
            time.sleep(1.5)
            continue
        w, h = _png_size(str(png))
        try:
            boxes = _ocr_boxes(str(png))
        except Exception as e:  # noqa: BLE001
            log("OCR 异常：%r" % e)
            boxes = []
        txt = "".join((b.get("text") or "") for b in boxes)
        flat = txt.replace(" ", "").upper()

        # 1) 药剂面板已开着（上次没关成功）
        if "药剂" in txt:
            got = _parse_panel_sanity(boxes)
            _tap_xy(*PANEL_CANCEL)
            time.sleep(1.0)
            if got:
                break
            log("药剂面板开着但读数没解析出来（第 %d 次）" % (i + 1))
            continue

        # 2) 结算/关卡界面（EX 链失败常停在这里）→ 只按 BACK，绝不点击
        hit = next((m for m in RESULT_MARKERS if m in txt), None)
        if hit:
            if back_left > 0:
                back_left -= 1
                log("画面停在结算/关卡界面（含「%s」）→ 按 BACK 回主界面再试（第 %d 次）"
                    % (hit, i + 1))
                _key_back(devs)
                time.sleep(2.5)
            else:
                log("!! 画面停在结算/关卡界面，且 BACK 次数已用完 → 不盲点，退出")
                break
            continue

        # 3) 还在加载 / 没有任何文字 → 只等待
        if (not boxes) or any(m in flat for m in LOADING_MARKERS):
            log("画面还在加载/无文字 → 等 3s 再试（不点击）")
            time.sleep(3.0)
            continue

        # 4) 严格认主界面理智条；认不出只按 BACK
        anchor = _parse_sanity(boxes, w, h)
        if not anchor:
            if back_left > 0:
                back_left -= 1
                log("没看到主界面「理智/上限」（可能不在主界面）→ 按一次 BACK 再试")
                _key_back(devs)
                time.sleep(2.5)
            else:
                log("!! 认不出主界面理智条（截图 %s）→ 不盲点，退出" % png)
                break
            continue
        ax, ay = anchor
        plus = (ax - 124, ay - 64)              # 实测：+ 在「理智」标签左上 (Δ-124, Δ-64)
        log("点理智条「+」(%d,%d) 开药剂面板（第 %d 次）" % (plus[0], plus[1], i + 1))
        _tap_xy(*plus)
        time.sleep(1.8)
        if not _grab(png2):
            continue
        try:
            boxes2 = _ocr_boxes(str(png2))
        except Exception as e:  # noqa: BLE001
            log("OCR 异常：%r" % e)
            boxes2 = []
        txt2 = "".join((b.get("text") or "") for b in boxes2)
        if "药剂" not in txt2:
            # 不点其它按钮，等画面稳定后重试（之前这里直接 return 3，一次失败就整天没读数）
            log("!! 点了 + 但没打开药剂面板（截图 %s）→ 不点其它按钮，等 2s 重试" % png2)
            time.sleep(2.0)
            continue
        got = _parse_panel_sanity(boxes2)
        # 无条件关面板（点 ✕，绝不用药），再判读数
        _tap_xy(*PANEL_CANCEL)
        time.sleep(1.0)
        if got:
            log("读到面板读数：当前 %d / 总量 %d" % got)
            break
        log("面板读数没解析出来（第 %d 次）" % (i + 1))
    if not got:
        log("!! 读不到理智（截图 %s）—— 不写 sanity.json" % png)
        return 3

    val = got[0]
    d = {}
    try:
        d = json.loads(SANITY_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        d = {}
    # ⚠ 不要动 `ts`：`ts` = **理智药**测量时间（weekly_refresh 用它判断药读数是否过期）。
    #   每日理智读数单独记在 current_sanity_ts 里，别让药读数看起来"永远新鲜"。
    d["current_sanity"] = int(val)
    d["current_sanity_ts"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    d["current_sanity_src"] = "maa_week sanity（药剂面板 OCR，只读不用药）"
    d["panel_total"] = int(got[1])
    SANITY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SANITY_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    log("已写 %s：current_sanity=%d" % (SANITY_JSON, val))
    return 0


def _harden_stdio():
    """防御：Windows 控制台默认 GBK，打印非 GBK 符号（如 ⚠ U+26A0）会 UnicodeEncodeError
    直接把脚本崩在半途。统一给 stdout/stderr 加 errors=replace（不改编码），
    任何字符都打得出、最多显示成 `?`，绝不因一个符号打死整趟执行。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001
            pass


def main():
    _harden_stdio()
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
            p.add_argument("--force", action="store_true",
                           help="今天不在计划里（过期/未排）也照跑——只跑日常，不刷关")
            p.add_argument("--no-ex", action="store_true",
                           help="跳过「活动 EX 自动补打」（默认跑完日常会顺手打掉未通的 EX）")
        p.set_defaults(func=fn)
    sp = sub.add_parser("startup", help="启动/唤醒游戏（含拉起雷电模拟器）")
    sp.add_argument("--client", default="Official", help="Official / Bilibili / txwy / YoStarEN…")
    sp.add_argument("--timeout", type=int, default=300, help="StartUp 任务超时（秒）")
    sp.add_argument("--emulator-timeout", type=int, default=120, help="等模拟器上线超时（秒）")
    sp.set_defaults(func=cmd_startup)
    dp = sub.add_parser("depot", help="读一次仓库并写 C:\\MAA\\data\\DepotData.json（收益账本用）")
    dp.add_argument("--startup", action="store_true", help="先跑 StartUp 把游戏带到主界面")
    dp.add_argument("--client", default="Official")
    dp.add_argument("--timeout", type=int, default=300, help="Depot 任务超时（秒）")
    dp.add_argument("--emulator-timeout", type=int, default=120, help="等模拟器上线超时（秒）")
    dp.add_argument("--min-ratio", type=float, default=0.75,
                    help="完整性护栏：本次类目数 < 上次×该比例 判「识别不全」，不覆盖旧文件")
    dp.add_argument("--retries", type=int, default=2,
                    help="识别项数 <60 时最多重试几次（MAA 偶尔翻页提前结束）")
    dp.add_argument("--force", action="store_true", help="跳过完整性护栏，强制写入")
    dp.set_defaults(func=cmd_depot)
    sn = sub.add_parser("sanity", help="读主界面理智（截图+OCR，只读）并写 scheduling/data/sanity.json")
    sn.add_argument("--tries", type=int, default=3, help="截图+OCR 重试次数")
    sn.add_argument("--back", type=int, default=2, help="读不到时最多按几次 BACK 回主界面")
    sn.add_argument("--emulator-timeout", type=int, default=120, help="等模拟器上线超时（秒）")
    sn.set_defaults(func=cmd_sanity)
    args = ap.parse_args()
    rc = args.func(args)
    if isinstance(rc, int):
        sys.exit(rc)


if __name__ == "__main__":
    main()
