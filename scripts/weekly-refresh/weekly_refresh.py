#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每周刷新计划 —— 供 Windows 定时任务（每周一）调用。

做三件事：
  1. **重新生成本周计划**：`plan_week.plan(today)` → 写 `scheduling/data/weekly_plan.json`
     （窗口 = 今天..本周日，即「剩余 X 天」；周一跑 = 满 7 天）。
  2. **检查理智药读数**（`scheduling/data/sanity.json`）是否过期（默认 > 7 天算过期）。
  3. **弹一个提示**（Windows MessageBox，超时自动关）告诉用户：计划窗口/预算/逐日 + 药读数是否要重测。
     结果同时写 `scheduling/data/weekly_refresh.json`（GUI / 脚本可读）+ 追加 `%TEMP%\\arknights-mcp.log`。

⚠ **不自动测药**：`sanity_potion.py` 要求游戏停在**主界面**、且同一时刻只有**一个**客户端在驱动设备。
定时任务无法保证游戏状态（不在主界面时点「+」有误点风险），故这里**只生成计划 + 提醒重测**，
把「测药」留给用户在手边时手动跑（这正是本项目「单一客户端驱动」铁律的落地）。

用法：
  python weekly_refresh.py               # 生成 + 弹窗（定时任务用）
  python weekly_refresh.py --no-popup    # 只生成，不弹窗（调试/静默）
  python weekly_refresh.py --dry         # 不写文件，只打印结果
  python weekly_refresh.py --stale-days 3   # 自定义「药读数几天算过期」（默认 7）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
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

    ap = argparse.ArgumentParser(description="每周刷新计划（生成 + 提醒重测药）")
    ap.add_argument("--no-popup", action="store_true", help="不弹窗")
    ap.add_argument("--dry", action="store_true", help="不写文件，只打印")
    ap.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS,
                    help="药读数超过几天算过期（默认 %d）" % DEFAULT_STALE_DAYS)
    a = ap.parse_args()

    today = dt.date.today()
    try:
        plan = plan_week.plan(today)
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
    needs = (age is None) or (age > a.stale_days)

    lines = ["本周计划已生成（窗口 %s，剩余 %s 天）" % (rng, n_days),
             "预算：%d 理智" % budget]
    if daily_line:
        lines.append("逐日：%s" % daily_line)
    lines.append("")
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
    else:
        lines.append("理智药读数：%s（%d 天前，%s）✔ 新鲜" % (med["ts"], age, med["potion_sanity"]))

    body = "\n".join(lines)
    title = "方舟·每周刷新计划"

    if not a.dry:
        PLAN_OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        MARKER.write_text(json.dumps({
            "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "range": rng, "n_days": n_days, "budget": budget,
            "sanity_ts": med["ts"], "sanity_age_days": age,
            "potion_sanity": med["potion_sanity"], "needs_remeasure": bool(needs),
            "message": body,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        log("已写 %s；%s" % (PLAN_OUT.name, "需重测药" if needs else "药读数新鲜"))

    print(body)
    if not a.no_popup and not a.dry:
        _popup(title, body, warn=bool(needs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
