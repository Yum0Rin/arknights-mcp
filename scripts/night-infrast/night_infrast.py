#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凌晨基建换班：确保雷电 + 游戏在线 → 跑一次 MAA `Infrast`（自定义换班）→ 关雷电。

供 Windows 计划任务「方舟·凌晨基建换班」调用（**每天 02:00**；**错过不补跑** ——
2:00 电脑不在线（关机/睡眠）就整晚不跑。见 install_task.ps1 故意不设 -StartWhenAvailable）。

为什么放 02:00：
  14:00 的「每日日常」也跑一次 Infrast 换班；A/B 班各 720min = 12h → 14:00 ↔ 02:00 正好对齐，
  两边各换一次（14:00 装 A班、02:00 装 B班）。

基建口径（2026-10-14 用户裁定「选 2」= 改用 MAA **自定义换班** `mode=10000 (Custom)`）：
  · 方案表 = 仓库里 `scheduling/MAA基建排班/243_搓玉_定制.json`（《搓玉·合成玉》A/B 两班，由
    `scheduling/tools/convert_to_maa.py` 从一图流 `243-搓玉-合成玉-MAA.json` 转出）；
  · Custom 下 MAA 按方案表**逐设施摆干员**，并执行**菲亚梅塔置换**（`Fiammetta` 块 → 宿舍放 `[但书, 菲亚梅塔]`）；
  · ⚠ MAA **不看** plan 里的 `period`（那是 GUI「按时间自动选」用的），也不吃 `plan_index=-1`
    （Core 里 `index<0` → set_params false → append 0）→ **由本脚本显式传** `plan_index`；
  · params 走 `maa_week.infrast_params(...)`（与 14:00 日常**同一出口**，只是班次不同）。
  旧口径 Rotation(20000) 只点一次游戏内「队列轮换」且 `skip shift`（不摆干员、不做菲亚梅塔），
  源码+日志实证见 docs/FINDINGS.md §24。

留痕：
  - scripts/night-infrast/运行日志.txt   人读，追加，带时间戳
  - scheduling/data/night_run.jsonl       结构化，每次一条

用法：
  python scripts/night-infrast/night_infrast.py              # 正常跑（计划任务用）
  python scripts/night-infrast/night_infrast.py --dry        # 只打印将做什么，不执行
  python scripts/night-infrast/night_infrast.py --force      # 忽略「今晚已跑」防重复
  python scripts/night-infrast/night_infrast.py --no-close   # 跑完不关雷电
  python scripts/night-infrast/night_infrast.py --date 2026-10-15 --timeout 1800

⚠ 单一客户端铁律：检测到 MAA GUI 在运行 → **直接跳过**（不抢设备、不关雷电）。
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

REPO = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
LOG_TXT = HERE / "运行日志.txt"
NIGHT_JSONL = REPO / "scheduling" / "data" / "night_run.jsonl"
MAA_WEEK_DIR = REPO / "scripts" / "maa-week"
LDCONSOLE = pathlib.Path(os.environ.get("ARK_EMULATOR", r"C:\leidian\LDPlayer9\ldconsole.exe"))
EMU_INDEX = int(os.environ.get("ARK_EMU_INDEX", "0"))

# 基建 params 与 14:00「每日日常」**同一个出口**（`maa_week.infrast_params`），只把班次换成夜间那一班。
# 口径（2026-10-14 用户裁定「选 2」）：MAA **自定义换班** `mode=10000 (Custom)` + **菲亚梅塔置换**；
#   14:00 跑 A班(`mw.INFRAST_PLAN_DAY`=1)、02:00 跑 B班(`mw.INFRAST_PLAN_NIGHT`=0)。
# ⚠ 别在这里手写 mode/filename —— 改口径要改 `maa_week.INFRAST_*`（唯一事实源）。

STARTUP_TIMEOUT_S = 420          # 冷启动：等模拟器上线 + 开游戏到主界面
DEFAULT_TOTAL_TIMEOUT_S = 1500   # StartUp + Infrast 整体上限

CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

sys.path.insert(0, str(MAA_WEEK_DIR))
import maa_week as mw  # noqa: E402  （复用 _ensure_device / _get_asst / _devices / _maa_running / _shot）


def log(msg: str) -> None:
    """写运行日志（人读）。**不依赖 print** —— 计划任务用 pythonw，那里 sys.stdout is None。"""
    line = "[%s] [night-infrast] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except Exception:  # noqa: BLE001  pythonw 下 sys.stdout 为 None
        pass
    try:
        LOG_TXT.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_TXT, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def _jsonl(entry: dict) -> None:
    entry = {"ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **entry}
    try:
        NIGHT_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with open(NIGHT_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _already_ran(date: str) -> bool:
    """今晚（该日期）是否已有**成功**记录 —— 防「计划任务 + 手动跑」把队列连换两次。"""
    try:
        if not NIGHT_JSONL.exists():
            return False
        for ln in NIGHT_JSONL.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            if e.get("ok") is True and str(e.get("date")) == date:
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _emu_running():
    """雷电实例是否在运行：True/False，查询失败 None。

    ⚠ 走 mw._run_console（UTF-8→GBK 双解码）：本进程 env 带 PYTHONUTF8=1，
    `text=True` 会按 UTF-8 解 ldconsole 的 GBK 输出 → 读线程崩、stdout=None。
    """
    _rc, out = mw._run_console([str(LDCONSOLE), "list2"], timeout=15)
    for row in (out or "").splitlines():
        parts = row.split(",")
        if len(parts) >= 5 and parts[0].strip().isdigit() and int(parts[0]) == EMU_INDEX:
            return parts[4].strip() == "1"
    return None


def _close_emulator(timeout_s: int = 60) -> str:
    """关雷电实例，返回结果标记（closed/unconfirmed/...）。绝不抛。"""
    if not LDCONSOLE.exists():
        log("找不到 ldconsole：%s（跳过关雷电）" % LDCONSOLE)
        return "no-ldconsole"
    log("关闭雷电实例 %d…" % EMU_INDEX)
    try:
        subprocess.run([str(LDCONSOLE), "quit", "--index", str(EMU_INDEX)],
                       cwd=str(LDCONSOLE.parent), capture_output=True, timeout=30, env=CHILD_ENV)
    except Exception as e:  # noqa: BLE001
        log("发送关闭指令失败：%r" % e)
        return "quit-failed"
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(1)
        st = _emu_running()
        if st is False:
            log("已确认：雷电实例 %d 已关闭。" % EMU_INDEX)
            return "closed"
        if st is None:
            break
    log("已发送关闭指令，但未能在 %ds 内确认关闭。" % timeout_s)
    return "unconfirmed"


def _custom_plan_check(plan_index: int):
    """校验自定义换班方案表（Custom 模式的前置）。返回 (ok, 说明)。

    坏文件/越界会让 MaaCore `set_params` 返 false → `append` 返 0 → 打死整队，
    所以**在拉模拟器之前**就拦下。
    """
    f = pathlib.Path(mw.INFRAST_CUSTOM_FILE)
    if not f.exists():
        return False, "方案表不存在：%s" % f
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, "方案表 JSON 解析失败：%s（%r）" % (f, e)
    plans = d.get("plans") or []
    if not (0 <= int(plan_index) < len(plans)):
        return False, "plan_index=%s 越界（%s 共 %d 份方案）" % (plan_index, f.name, len(plans))
    p = plans[plan_index] or {}
    ops = 0
    for rooms in (p.get("rooms") or {}).values():
        for room in rooms or []:
            ops += len([n for n in (room.get("operators") or []) if n])
    fia = p.get("Fiammetta") or {}
    return True, ("plan[%d]=%s（%d 名干员，Fiammetta %s→%s）"
                  % (plan_index, p.get("name"), ops,
                     "开" if fia.get("enable") else "关", fia.get("target") or "-"))


def main() -> int:
    # GBK 控制台无法编码 ⚠ 等符号 → 打印降级为 '?'（不影响文件，文件是 utf-8）
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001  pythonw 下为 None
            pass

    ap = argparse.ArgumentParser(description="凌晨基建换班：跑一次 MAA Infrast（自定义换班）→ 关雷电")
    ap.add_argument("--date", default="", help="算哪一晚（默认今天）")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TOTAL_TIMEOUT_S, help="StartUp+Infrast 整体超时（秒）")
    ap.add_argument("--startup-timeout", type=int, default=STARTUP_TIMEOUT_S, help="等模拟器上线超时（秒）")
    ap.add_argument("--no-close", action="store_true", help="跑完不关雷电")
    ap.add_argument("--force", action="store_true", help="忽略「今晚已跑」防重复")
    ap.add_argument("--dry", action="store_true", help="只打印将做什么，不执行")
    a = ap.parse_args()

    date = a.date or dt.date.today().isoformat()
    log("===== 凌晨基建换班开始（date=%s）=====" % date)

    if a.dry:
        log("[dry] 将依次执行：")
        log("  0) 单客户端检查：MAA.exe 在跑 → 直接跳过（不抢设备）")
        log("  0.5) 防重复：今晚已有成功记录 → 跳过（--force 可强制）")
        log("  0.7) 校验自定义换班方案表：%s（plan_index=%d）"
            % (mw.INFRAST_CUSTOM_FILE, mw.INFRAST_PLAN_NIGHT))
        log("  1) 确保设备在线：%s（不在线就拉起雷电 index=%d，等 %ds）"
            % (mw.ADB, EMU_INDEX, a.startup_timeout))
        log("  2) 连接 MaaCore 并 append：StartUp(client_type=Official, start_game_enabled=True)"
            " → Infrast(mode=10000 Custom, plan_index=%d, facility=%d 项)"
            % (mw.INFRAST_PLAN_NIGHT, len(mw.INFRAST_FACILITY)))
        log("  3) 关雷电：%s quit --index %d（--no-close 可关）" % (LDCONSOLE, EMU_INDEX))
        log("[dry] 未执行。")
        return 0

    if not a.force and _already_ran(date):
        log("今晚（%s）已有成功的基建换班记录 → 跳过（--force 可强制再跑）。" % date)
        _jsonl({"date": date, "skipped": "already_ran", "ok": False})
        return 0

    if mw._maa_running():
        log("检测到 MAA GUI 正在运行 → 按单一客户端纪律**跳过**（不动设备、不关雷电）。"
            " 若要本任务生效，请退出 MAA 后手动补跑：python %s" % pathlib.Path(__file__).name)
        _jsonl({"date": date, "skipped": "maa-gui-running", "ok": False, "close": "skipped"})
        return 0

    # 0.7) 先校验自定义换班方案表 —— 坏文件会让 MaaCore `set_params` false → append 0 打死整队，
    #      所以在这里就拦下，**连模拟器都不用拉**。
    plan_ok, plan_why = _custom_plan_check(mw.INFRAST_PLAN_NIGHT)
    log("自定义换班方案表：%s" % plan_why)
    if not plan_ok:
        log("!! %s → 跳过（不拉起模拟器、不改任何东西）" % plan_why)
        _jsonl({"date": date, "stage": "custom-file", "error": plan_why, "ok": False})
        return 4

    # 1) 确保有在线设备（没有就拉起雷电并等它上线）—— 冷启动是本任务的常态
    try:
        devs = mw._ensure_device(a.startup_timeout)
    except SystemExit as e:
        log("!! 设备准备失败：%s" % e)
        close_result = "no-close-flag" if a.no_close else _close_emulator()
        _jsonl({"date": date, "stage": "device", "error": str(e), "ok": False, "close": close_result})
        return 1
    log("设备已在线：%s" % devs)

    # 2) 连接 MaaCore
    try:
        asst = mw._get_asst()
    except Exception as e:  # noqa: BLE001
        log("!! 连接 MaaCore/模拟器失败：%s" % e)
        close_result = "no-close-flag" if a.no_close else _close_emulator()
        _jsonl({"date": date, "stage": "connect", "error": str(e), "ok": False, "close": close_result})
        return 2

    # 3) StartUp（冷启动会点游戏图标）→ Infrast（Custom：逐设施摆干员 + 菲亚梅塔置换）
    infrast = mw.infrast_params(mw.INFRAST_PLAN_NIGHT)
    log("Infrast params：mode=%s plan_index=%s（方案表 %s）"
        % (infrast["mode"], infrast["plan_index"], pathlib.Path(infrast["filename"]).name))
    tids = []
    for name, params in (
        ("StartUp", {"client_type": "Official", "start_game_enabled": True}),
        ("Infrast", infrast),
    ):
        try:
            tid = asst.append_task(name, params)
        except Exception as e:  # noqa: BLE001
            tid = 0
            log("!! append 异常 %s: %s" % (name, e))
        tids.append({"task": name, "id": tid})
        log("append %-9s -> id=%s" % (name, tid))
        if not tid:
            shot = mw._shot("night_" + name)
            log("!! append 失败（id=0）→ 停止，截图 %s" % shot)
            close_result = "skipped" if a.no_close else _close_emulator()
            _jsonl({"date": date, "stage": "append", "task": name, "tids": tids,
                    "screenshot": shot, "ok": False, "close": close_result})
            return 2

    asst.start()
    log("已启动，共 %d 任务；轮询中（超时 %ss）…" % (len(tids), a.timeout))
    watch = mw._StallWatch()
    stalled = False
    t0 = time.time()
    last_probe = 0.0
    while asst.running() and time.time() - t0 < a.timeout:
        time.sleep(1.0)
        if time.time() - last_probe >= 5:
            last_probe = time.time()
            if watch.poll() >= watch.limit:
                stalled = True
                break
    elapsed = round(time.time() - t0, 1)

    if stalled:
        log("!! 疑似卡在基建选人（日志里「找不到干员」类告警 %d 次）→ 主动停止（用时 %.0fs）"
            % (watch.hits, elapsed))
        try:
            asst.stop()
        except Exception:  # noqa: BLE001
            pass
        for _ in range(30):
            if not asst.running():
                break
            time.sleep(1.0)
        shot = mw._shot("night_stalled")
        log("   留证 %s" % shot)
        close_result = "skipped" if a.no_close else _close_emulator()
        _jsonl({"date": date, "elapsed": elapsed, "tids": tids, "stage": "stalled",
                "hits": watch.hits, "screenshot": shot, "ok": False, "close": close_result})
        log("===== 凌晨基建换班结束：ok=False 用时=%.0fs 关雷电=%s =====" % (elapsed, close_result))
        return 6

    running = bool(asst.running())

    if running:
        shot = mw._shot("night_timeout")
        log("!! 超时仍在跑（%.0fs）→ 不硬杀，留证 %s" % (elapsed, shot))
        ok, stage = False, "timeout"
    else:
        log("跑完，用时 %.0fs" % elapsed)
        shot, ok, stage = "", True, "done"

    # 4) 关雷电（成功/失败/超时都关；--no-close 则不关）
    if a.no_close:
        log("按 --no-close 不关雷电。")
        close_result = "no-close-flag"
    else:
        close_result = _close_emulator()

    _jsonl({"date": date, "elapsed": elapsed, "tids": tids, "stage": stage,
            "screenshot": shot, "ok": ok, "close": close_result})
    log("===== 凌晨基建换班结束：ok=%s 用时=%.0fs 关雷电=%s =====" % (ok, elapsed, close_result))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
