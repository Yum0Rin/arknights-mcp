#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日自动化：森空岛签到 → 直驱跑 MAA 当天日常 → 关雷电。

供 Windows 计划任务「方舟·每日日常」调用（**每天 14:00**）：
  1. 森空岛签到（skland_cli.py checkin）—— 失败（凭证过期等）只记日志提醒，**不中断**，继续跑日常。
  2. 直驱 MaaCore 跑当天日常（maa_week.py run，内置冷启动会自动拉起雷电）。
  3. 跑完关雷电模拟器（ldconsole quit --index 0）—— 成功/失败/超时都关；
     唯一例外：MAA GUI 正在运行（maa_week 退出码 2 且输出含「MAA GUI」）→ 不关，免得打断你手动玩。

留痕：
  - scripts/daily-auto/运行日志.txt          人读，追加，带时间戳
  - scheduling/data/daily_run.jsonl          结构化，每次一条
（maa_week.py 自身另写 scheduling/data/run_report.jsonl）

⚠ 单一客户端铁律：跑的时候别同时用 MAA GUI / 别的客户端驱动同一台设备。

用法：
  python scripts/daily-auto/daily_auto.py            # 正常跑（计划任务用）
  python scripts/daily-auto/daily_auto.py --dry      # 只打印将做什么，不执行
  python scripts/daily-auto/daily_auto.py --force    # 忽略「今日已跑」防重复
  python scripts/daily-auto/daily_auto.py --no-close # 跑完不关雷电
  python scripts/daily-auto/daily_auto.py --skip-checkin
  python scripts/daily-auto/daily_auto.py --date 2026-10-16 --timeout 7200
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
RUN_REPORT = REPO / "scheduling" / "data" / "run_report.jsonl"
DAILY_JSONL = REPO / "scheduling" / "data" / "daily_run.jsonl"
SKLAND_CLI = REPO / "scripts" / "skland" / "skland_cli.py"
MAA_WEEK = REPO / "scripts" / "maa-week" / "maa_week.py"
LDCONSOLE = pathlib.Path(os.environ.get("ARK_EMULATOR", r"C:\leidian\LDPlayer9\ldconsole.exe"))
EMU_INDEX = int(os.environ.get("ARK_EMU_INDEX", "0"))

CHECKIN_TIMEOUT_S = 120

# 子进程强制 UTF-8，避免 GBK 控制台把中文/符号打崩
CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def log(msg: str) -> None:
    """写运行日志（人读）。**不依赖 print**——计划任务用 pythonw，那里 sys.stdout is None。"""
    line = "[%s] [daily-auto] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
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
        DAILY_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with open(DAILY_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _run_step(name: str, cmd: list, timeout: int):
    """跑一个子进程步骤：捕获输出写日志，返回 (rc, 合并输出)。绝不抛。"""
    log("→ 开始：%s" % name)
    log("  命令：%s" % " ".join(str(c) for c in cmd))
    t0 = time.time()
    rc, out = None, ""
    try:
        r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=CHILD_ENV)
        rc = r.returncode
        out = ((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired as e:
        rc = -1
        so = e.stdout if isinstance(e.stdout, str) else ""
        se = e.stderr if isinstance(e.stderr, str) else ""
        out = (so + se).strip()
        log("!! %s 超时（%ds）" % (name, timeout))
    except Exception as e:  # noqa: BLE001
        log("!! %s 启动失败：%r" % (name, e))
    for ln in out.splitlines():
        log("   | %s" % ln)
    log("← 结束：%s rc=%s（%.0fs）" % (name, rc, time.time() - t0))
    return rc, out


def _already_ran_today(date: str) -> bool:
    """今日是否已有**成功**的日常记录（读 maa_week 写的 run_report.jsonl）。
    防「手动跑过 + 计划任务补跑」导致理智双花。"""
    try:
        if not RUN_REPORT.exists():
            return False
        for ln in RUN_REPORT.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            if e.get("ok") is True and str(e.get("scope", "")).startswith(date):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _emu_running():
    """雷电实例是否在运行：True/False，查询失败 None。"""
    try:
        r = subprocess.run([str(LDCONSOLE), "list2"], cwd=str(LDCONSOLE.parent),
                           capture_output=True, text=True, timeout=15, env=CHILD_ENV)
    except Exception:  # noqa: BLE001
        return None
    for row in (r.stdout or "").splitlines():
        parts = row.split(",")
        if len(parts) >= 5 and parts[0].strip().isdigit() and int(parts[0]) == EMU_INDEX:
            return parts[4].strip() == "1"
    return None


def _close_emulator(timeout_s: int = 30) -> str:
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


def main() -> int:
    # GBK 控制台无法编码 ⚠/✔ 等符号 → 打印降级为 '?'（不影响文件，文件是 utf-8）
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001  pythonw 下为 None
            pass

    ap = argparse.ArgumentParser(description="每日自动化：森空岛签到 → 跑 MAA 日常 → 关雷电")
    ap.add_argument("--date", default="", help="跑哪一天（默认今天）")
    ap.add_argument("--timeout", type=int, default=7200, help="maa_week run 的超时（秒，默认 7200）")
    ap.add_argument("--no-close", action="store_true", help="跑完不关雷电")
    ap.add_argument("--skip-checkin", action="store_true", help="跳过森空岛签到")
    ap.add_argument("--force", action="store_true", help="忽略「今日已跑」防重复")
    ap.add_argument("--dry", action="store_true", help="只打印将做什么，不执行")
    a = ap.parse_args()

    date = a.date or dt.date.today().isoformat()
    log("===== 每日自动化开始（date=%s）=====" % date)

    if a.dry:
        log("[dry] 将依次执行：")
        if not a.skip_checkin:
            log("  1) 森空岛签到：%s status（续期 sign_token）→ checkin" % SKLAND_CLI)
        log("  2) 跑当天日常：%s run --date %s --timeout %d" % (MAA_WEEK, date, a.timeout))
        log("  3) 关雷电：%s quit --index %d（--no-close 可关）" % (LDCONSOLE, EMU_INDEX))
        log("[dry] 未执行。")
        return 0

    if not a.force and _already_ran_today(date):
        log("今日（%s）已有成功的日常记录 → 跳过（--force 可强制再跑）。" % date)
        _jsonl({"date": date, "skipped": "already_ran", "checkin_rc": None, "maa_rc": None})
        return 0

    # 1) 森空岛签到（失败不中断）
    checkin_rc = None
    if a.skip_checkin:
        log("已跳过森空岛签到（--skip-checkin）。")
    else:
        # 先 `status` 续期 sign_token：token 过期会让 attendance POST 直接 401（实测踩过）。
        _run_step("森空岛凭证续期", [sys.executable, str(SKLAND_CLI), "status"],
                  timeout=CHECKIN_TIMEOUT_S)
        checkin_rc, _ = _run_step("森空岛签到",
                                  [sys.executable, str(SKLAND_CLI), "checkin"],
                                  timeout=CHECKIN_TIMEOUT_S)
        if checkin_rc != 0:
            log("!! 签到未成功（rc=%s）—— 凭证可能过期；重登：python scripts/skland/skland_cli.py login" % checkin_rc)
            log("   → 按约定继续跑 MAA 日常，不中断。")

    # 2) 跑当天日常（maa_week 内置冷启动会拉起雷电）
    maa_rc, maa_out = _run_step(
        "跑当天日常",
        [sys.executable, str(MAA_WEEK), "run", "--date", date, "--timeout", str(a.timeout)],
        timeout=a.timeout + 600)

    # 3) 关雷电（成功/失败/超时都关；MAA GUI 在跑则不关）
    gui_busy = (maa_rc == 2) and ("MAA GUI" in (maa_out or ""))
    if a.no_close:
        log("按 --no-close 不关雷电。")
        close_result = "no-close-flag"
    elif gui_busy:
        log("检测到 MAA GUI 正在运行（日常未跑）→ 不关雷电，免得打断你手动玩。")
        close_result = "skip-gui-busy"
    else:
        close_result = _close_emulator()

    ok = (maa_rc == 0)
    _jsonl({"date": date, "checkin_rc": checkin_rc, "maa_rc": maa_rc,
            "ok": ok, "close": close_result})
    log("===== 每日自动化结束：maa_rc=%s ok=%s 关雷电=%s =====" % (maa_rc, ok, close_result))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
