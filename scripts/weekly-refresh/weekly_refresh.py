#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每周刷新计划 —— 供 Windows 定时任务（**每周日 20:00**）调用。

做四件事（**顺序很重要**：先测药再生成计划，计划才能用上新鲜读数）：
  1. **复测理智药**（默认开，`--no-measure` 关）：跑 `sanity_potion.py --ensure-main`
     （拉起模拟器 + MAA StartUp 把游戏带到主界面 → 读「理智恢复」面板 → 写 `scheduling/data/sanity.json`）。
     该脚本自带容错（不盲点 / 有界恢复 / 退出码），失败只记录、不崩。
  2. **重新生成计划**：`plan_week.plan(target)` → 写 `scheduling/data/weekly_plan.json`。
     周日晚上跑时今天属于**旧的一周** → 用「明天(下周一)」算所属周 → 窗口 = 下周一..下周日（满 7 天），
     与原先「周一早上跑」等价。**代价**：今天(周日)本身不在该计划内 —— 周日日常先跑完再刷新，
     或手动 `python scheduling/tools/plan_week.py`（默认今天..本周日）补一份。
  3. **检查理智药读数**（`scheduling/data/sanity.json`）是否过期（默认 > 7 天算过期）。
  4. **弹一个提示**（Windows MessageBox，超时自动关）：计划窗口/预算/逐日 + 复测结果/是否要重测。
     结果同时写 `scheduling/data/weekly_refresh.json`（GUI / 脚本可读）+ 追加 `%TEMP%\\arknights-mcp.log`。

⚠ **单一客户端铁律**：测药要驱动设备（拉起模拟器 + MAA），跑的时候**别同时**用 MAA GUI / 别的客户端驱动同一台。
   定时任务设在周日 20:00（默认无人在玩）；若那一刻你正在手动玩，任务会失败并留证（不会乱点）。
   `sanity_potion.py` 自身**绝不盲点**（不在主界面就不点「+」），最坏情况是这次没测到、下次再来。

用法：
  python weekly_refresh.py               # 测药 + 生成 + 弹窗（定时任务用）
  python weekly_refresh.py --no-measure  # 只生成 + 弹窗，不测药
  python weekly_refresh.py --no-popup    # 不弹窗（调试/静默）
  python weekly_refresh.py --dry         # 不写文件、不测药，只打印结果
  python weekly_refresh.py --stale-days 3   # 自定义「药读数几天算过期」（默认 7）
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

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOLS = ROOT / "scheduling" / "tools"
DATA = ROOT / "scheduling" / "data"
sys.path.insert(0, str(TOOLS))

import plan_week  # noqa: E402  （同目录 tools；有 __main__ 保护，import 安全）

PLAN_OUT = DATA / "weekly_plan.json"
SANITY = DATA / "sanity.json"
MARKER = DATA / "weekly_refresh.json"
LOG = pathlib.Path(os.environ.get("TEMP", ".")) / "arknights-mcp.log"

DEFAULT_STALE_DAYS = 7
POPUP_TIMEOUT_MS = 60000


def log(msg: str) -> None:
    line = "[%s] [weekly-refresh] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def _sanity_info() -> dict:
    """读 sanity.json → {ts, age_days, potion_sanity}。读不到 → age_days=None。"""
    try:
        d = json.loads(SANITY.read_text(encoding="utf-8"))
        ts = str(d.get("ts") or "")[:10]
        age = None
        if ts:
            age = (dt.date.today() - dt.date.fromisoformat(ts)).days
        return {"ts": ts, "age_days": age, "potion_sanity": d.get("potion_sanity")}
    except Exception:  # noqa: BLE001
        return {"ts": "", "age_days": None, "potion_sanity": None}


MEASURE_TIMEOUT_S = 780          # 测药子进程超时（含拉起模拟器+StartUp 到主界面），给足
RC_MEAN = {0: "成功", 2: "设备不在线", 3: "不在主界面", 4: "理智恢复面板没打开", 5: "读数失败"}


def _measure_potion(timeout_s: int = MEASURE_TIMEOUT_S) -> dict:
    """跑 `sanity_potion.py --ensure-main` 复测药（拉起模拟器 + MAA StartUp 把游戏带到主界面 → 读数 → 写 sanity.json）。

    返回 {ran, rc, ok, ts, potion_sanity, error}。**绝不抛**（失败只记录，交给上层弹窗/日志）。
    """
    script = ROOT / "scripts" / "sanity-potion" / "sanity_potion.py"
    if not script.exists():
        return {"ran": False, "rc": None, "ok": False, "ts": "", "potion_sanity": None,
                "error": "找不到 %s" % script}
    try:
        r = subprocess.run(
            [sys.executable, str(script), "--ensure-main", "--tries", "4", "--json", str(SANITY)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=timeout_s,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        rc = r.returncode
        info = _sanity_info()
        tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-3:]
        return {"ran": True, "rc": rc, "ok": rc == 0,
                "ts": info["ts"], "potion_sanity": info["potion_sanity"],
                "error": None if rc == 0 else "rc=%d（%s）：%s"
                         % (rc, RC_MEAN.get(rc, "未知"), " | ".join(tail))}
    except subprocess.TimeoutExpired:
        return {"ran": True, "rc": -1, "ok": False, "ts": "", "potion_sanity": None,
                "error": "测药超时（%ds）" % timeout_s}
    except Exception as e:  # noqa: BLE001
        return {"ran": True, "rc": None, "ok": False, "ts": "", "potion_sanity": None,
                "error": repr(e)}


def _popup(title: str, body: str, warn: bool) -> bool:
    """Windows 原生提示框（超时自动关，不阻塞自动化）。非 Windows / 失败 → 返回 False。"""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        MB_ICONWARNING, MB_ICONINFO = 0x30, 0x40
        MB_TOPMOST = 0x40000
        flags = (MB_ICONWARNING if warn else MB_ICONINFO) | MB_TOPMOST
        ctypes.windll.user32.MessageBoxTimeoutW(0, body, title, flags, 0, POPUP_TIMEOUT_MS)
        return True
    except Exception as e:  # noqa: BLE001
        log("弹窗失败（忽略）：%r" % e)
        return False


def main() -> int:
    # GBK 控制台无法编码 ✔/⚠ 等符号 → 打印时降级为 '?'，不影响文件（utf-8）与弹窗（UTF-16）
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001
            pass

    ap = argparse.ArgumentParser(description="每周刷新计划（测药 + 生成 + 提醒）")
    ap.add_argument("--no-popup", action="store_true", help="不弹窗")
    ap.add_argument("--dry", action="store_true", help="不写文件、不测药，只打印")
    ap.add_argument("--measure", dest="measure", action="store_true", default=True,
                    help="先复测理智药（默认开）")
    ap.add_argument("--no-measure", dest="measure", action="store_false",
                    help="跳过复测理智药")
    ap.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS,
                    help="药读数超过几天算过期（默认 %d）" % DEFAULT_STALE_DAYS)
    a = ap.parse_args()

    # 0) **先复测药**（默认开）—— 必须在生成计划之前，计划才会用上新鲜读数。
    #    --dry 不动设备；测药子进程自带容错，失败只记录、不崩（见 _measure_potion）。
    meas = None
    if a.measure and not a.dry:
        log("先复测理智药（--ensure-main：拉起模拟器 + StartUp 到主界面）…")
        meas = _measure_potion()
        if meas.get("ok"):
            log("复测成功：理智药 ≈ %s（%s）" % (meas["potion_sanity"], meas["ts"]))
        else:
            log("复测失败：%s（不影响生成计划，继续）" % meas.get("error"))

    today = dt.date.today()
    # 周日晚上跑（定时任务 = 每周日 20:00）时，今天属于**旧的一周**：此刻要的是**下周**的计划。
    #   → 用「明天」（下周一）算所属周 → range = 下周一..下周日（满 7 天），与原先「周一早上跑」等价。
    #   ⚠ 代价：今天（周日）本身不再被这份计划覆盖 —— 若周日日常还没跑，先跑完再刷新，
    #     或手动 `python scheduling/tools/plan_week.py`（默认今天..本周日）补一份。
    target = today + dt.timedelta(days=1) if today.weekday() == 6 else today
    try:
        plan = plan_week.plan(target)
    except Exception as e:  # noqa: BLE001
        log("生成计划失败：%r" % e)
        if not a.no_popup:
            _popup("方舟·每周刷新计划 · 失败",
                   "生成本周计划失败：\n%r\n\n请手动跑：python scheduling/tools/plan_week.py" % e, warn=True)
        return 1

    rng = plan.get("range", "?")
    b = plan.get("budget") or {}
    n_days = b.get("n_days")
    budget = (int(b.get("sanity_natural") or 0) + int(b.get("weekly_potion") or 0)
              + int(b.get("meds_usable") or 0))
    daily = plan.get("daily") or []
    daily_line = " / ".join("%s=%s" % (d.get("date", "?")[5:], d.get("sanity", "?"))
                            for d in daily)

    med = _sanity_info()
    age = med["age_days"]
    # 复测成功 → med 已是新读数（age=0）→ 不再判 stale；复测失败/没测 → 按原读数新鲜度判。
    needs = (age is None) or (age > a.stale_days)
    meas_failed = (meas is not None) and (not meas.get("ok"))

    lines = ["%s计划已生成（窗口 %s，%s 天）" % ("下周" if target != today else "本周", rng, n_days),
             "预算：%d 理智" % budget]
    if daily_line:
        lines.append("逐日：%s" % daily_line)
    if target != today:
        lines.append("")
        lines.append("（今天 %s 不在本计划内 —— 周日日常若还没跑，先跑完再刷新。）" % today.isoformat())
    lines.append("")
    if meas is not None:
        lines.append(("✔ 理智药已复测：%s（%s）" % (meas["potion_sanity"], meas["ts"]))
                     if meas.get("ok") else ("⚠ 理智药复测失败：%s" % meas.get("error")))
    if needs:
        if age is None:
            lines.append("⚠ 没读到理智药读数（scheduling/data/sanity.json 缺失或损坏）")
        else:
            lines.append("⚠ 理智药读数是 %s（%d 天前，%s）→ 建议重测" %
                         (med["ts"], age, med["potion_sanity"]))
        lines.append("")
        lines.append("开游戏停在主界面后跑：")
        lines.append("  python scripts/sanity-potion/sanity_potion.py")
        lines.append("再点 GUI「生成/刷新计划」。")
    elif meas is None:
        lines.append("理智药读数：%s（%d 天前，%s）✔ 新鲜" % (med["ts"], age, med["potion_sanity"]))

    body = "\n".join(lines)
    title = "方舟·每周刷新计划"

    if not a.dry:
        PLAN_OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        MARKER.write_text(json.dumps({
            "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "range": rng, "n_days": n_days, "budget": budget,
            "measured": bool(meas and meas.get("ok")),
            "measure_error": (meas or {}).get("error"),
            "sanity_ts": med["ts"], "sanity_age_days": age,
            "potion_sanity": med["potion_sanity"], "needs_remeasure": bool(needs),
            "message": body,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        log("已写 %s；%s" % (PLAN_OUT.name, "需重测药" if needs else "药读数新鲜"))

    print(body)
    if not a.no_popup and not a.dry:
        _popup(title, body, warn=bool(needs or meas_failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
