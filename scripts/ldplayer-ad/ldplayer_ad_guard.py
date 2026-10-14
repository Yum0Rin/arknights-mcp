#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""雷电模拟器「广告」清理 / 守护（LDPlayer 启动器 & 浮层广告）。

## 背景（2026-10-14 实机定位）

雷电的广告组件是**独立包** `com.android.flysilkworm`（**用户应用**，装在 `/data/app`，
不是系统应用）。它拿 `SYSTEM_ALERT_WINDOW`（悬浮窗）权限，在**任意界面之上**弹浮层广告：
有时是启动器整屏广告，有时**直接盖在明日方舟上**（会干扰 MAA 的识别/点击）。

它会「有概率出现」，且**每次杀掉后仍可能再弹**（有自启），所以给了三档处理：

| 方式 | 命令 | 效果 | 可逆 |
|---|---|---|---|
| **治本** | `--disable` | `pm disable-user --user 0 com.android.flysilkworm` 永久禁用 → **不再出现** | `--enable` |
| 治本(备选) | `--uninstall` | `pm uninstall --user 0 …` 卸载 | `pm install-existing` |
| 治标 | `--once`(默认) / `--watch` | 检测到浮层就 `am force-stop` 掉，立即消失 | 无需（下次仍可能弹） |

**推荐**：先跑 `--status` 看现状，再 `--disable` 一劳永逸（想恢复 `--enable`）。
不方便禁用就挂 `--watch`（跑 MAA 期间守护）。

## 检测原理

`dumpsys window windows` 里是否存在 **可见**（`isVisible=true`）的 `com.android.flysilkworm` 窗口。
- 在屏 → 有该窗口（且通常就是 `mCurrentFocus`）；
- 不在 → 整份 dump 里没有该窗口（实测：杀掉后窗口消失，只剩 `Window #…` 里的别的包）。

## 用法

    python ldplayer_ad_guard.py --status        # 报告：包安装/启用状态 + 广告当前是否在屏
    python ldplayer_ad_guard.py                 # 检测一次，在屏就杀掉（默认动作）
    python ldplayer_ad_guard.py --watch         # 守护：每 5s 检测，出现就杀（Ctrl-C 停）
    python ldplayer_ad_guard.py --watch --interval 3 --duration 600   # 守护 10 分钟
    python ldplayer_ad_guard.py --disable       # 永久禁用广告包（治本）
    python ldplayer_ad_guard.py --enable        # 恢复（撤销 --disable）
    python ldplayer_ad_guard.py --uninstall     # 卸载广告包（可 pm install-existing 恢复）
    python ldplayer_ad_guard.py --json          # 机器可读输出（配合上面任一动作）

退出码：0=正常 / 2=设备不在线 / 3=adb 命令失败。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

ADB = os.environ.get("ARK_ADB", r"C:\leidian\LDPlayer9\adb.exe")
ADDR = os.environ.get("ARK_ADDR", "127.0.0.1:5555")
PKG = os.environ.get("LD_AD_PKG", "com.android.flysilkworm")

RC_OK, RC_NO_DEVICE, RC_ADB = 0, 2, 3


def _harden():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001
            pass


def log(msg):
    print("[ld-ad] %s" % msg, flush=True)


def adb(*args, timeout=20):
    """跑 adb 命令 → (rc, stdout)。**不抛**（异常也变 rc=-1）。"""
    try:
        r = subprocess.run([ADB, "-s", ADDR, *args], capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "")
    except Exception as e:  # noqa: BLE001
        return -1, "adb 异常：%r" % e


def device_online():
    rc, out = adb("get-state", timeout=15)
    return rc == 0 and "device" in out


def ad_window_visible():
    """广告浮层是否在屏 → (visible: bool|None, detail: str)。None=查不到（dumpsys 失败）。"""
    rc, out = adb("shell", "dumpsys", "window", "windows", timeout=30)
    if rc != 0:
        return None, "dumpsys 失败：%s" % (out or "").strip()[:200]
    # 按 "Window #" 切块，只认「块头（Window{...} 行）里含包名」且「块内 isVisible=true」的窗口。
    for blk in re.split(r"\n\s*Window #", out)[1:]:
        header = blk.split("\n", 1)[0]
        if PKG in header and re.search(r"isVisible\s*=\s*true", blk):
            return True, header.strip()
    # 兜底：当前焦点是广告包（dumpsys window 的 mCurrentFocus）
    rc2, out2 = adb("shell", "dumpsys", "window", timeout=20)
    if re.search(r"mCurrentFocus=Window\{[^}]*" + re.escape(PKG), out2 or ""):
        return True, "mCurrentFocus=" + PKG
    return False, "无可见广告窗口"


def package_state():
    """→ {installed, disabled, enabled}。"""
    _, out_all = adb("shell", "pm", "list", "packages", PKG)
    installed = PKG in (out_all or "")
    _, out_dis = adb("shell", "pm", "list", "packages", "-d", PKG)
    disabled = PKG in (out_dis or "")
    return {"installed": installed, "disabled": disabled, "enabled": installed and not disabled}


def dismiss():
    """杀掉广告浮层（force-stop）→ (ok, msg)。"""
    rc, out = adb("shell", "am", "force-stop", PKG)
    return rc == 0, (out or "").strip()


def set_disabled(disabled: bool):
    """永久禁用/恢复广告包 → (ok, msg)。"""
    if disabled:
        rc, out = adb("shell", "pm", "disable-user", "--user", "0", PKG)
    else:
        rc, out = adb("shell", "pm", "enable", PKG)
    return rc == 0, (out or "").strip()


def uninstall_pkg():
    rc, out = adb("shell", "pm", "uninstall", "--user", "0", PKG)
    return rc == 0, (out or "").strip()


def _emit(a, payload: dict, human_lines):
    """统一输出：--json 打 JSON，否则打人话。"""
    if a.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for ln in human_lines:
            print(ln)


def cmd_status(a):
    st = package_state()
    vis, detail = ad_window_visible()
    payload = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "pkg": PKG, "addr": ADDR,
               "installed": st["installed"], "enabled": st["enabled"], "disabled": st["disabled"],
               "ad_visible": vis, "detail": detail}
    lines = ["包 %s：%s" % (PKG, "已安装" if st["installed"] else "未安装"),
             "状态：%s" % ("已启用" if st["enabled"] else "已禁用" if st["disabled"] else "未安装"),
             "广告当前：%s" % ("在屏（%s）" % detail if vis else "不在屏")]
    _emit(a, payload, lines)
    return RC_OK


def _handle_once(a):
    vis, detail = ad_window_visible()
    if vis is None:
        log("!! 检测失败：%s" % detail)
        return RC_ADB
    if not vis:
        log("没有广告在屏（%s）" % detail)
        return RC_OK
    log("检测到广告在屏（%s）→ force-stop…" % detail)
    ok, msg = dismiss()
    time.sleep(1.0)
    vis2, detail2 = ad_window_visible()
    gone = (vis2 is False)
    if gone:
        log("已清除 ✔（复检：%s）" % detail2)
    else:
        log("!! force-stop 后仍在屏（%s）—— 可能被自启，建议 --disable" % detail2)
    return RC_OK if gone else RC_ADB


def cmd_watch(a):
    t0 = time.time()
    n_seen = n_killed = 0
    log("守护中：每 %.1fs 检测一次%s（Ctrl-C 停）"
        % (a.interval, "" if not a.duration else "，持续 %ds" % a.duration))
    try:
        while True:
            vis, detail = ad_window_visible()
            if vis:
                n_seen += 1
                log("发现广告（%s）→ 清除" % detail)
                ok, msg = dismiss()
                if ok:
                    n_killed += 1
            if a.duration and (time.time() - t0) >= a.duration:
                break
            time.sleep(max(1.0, a.interval))
    except KeyboardInterrupt:
        log("收到 Ctrl-C，停止守护")
    log("结束：发现 %d 次，清除 %d 次" % (n_seen, n_killed))
    return RC_OK


def main():
    global ADDR
    _harden()
    ap = argparse.ArgumentParser(description="雷电模拟器广告清理/守护（com.android.flysilkworm）")
    ap.add_argument("--addr", default="", help="设备地址（默认 %s）" % ADDR)
    ap.add_argument("--status", action="store_true", help="只报告：包状态 + 广告是否在屏")
    ap.add_argument("--watch", action="store_true", help="守护模式：循环检测并清除")
    ap.add_argument("--interval", type=float, default=5.0, help="守护检测间隔秒（默认 5）")
    ap.add_argument("--duration", type=float, default=0, help="守护持续秒（0=一直）")
    ap.add_argument("--disable", action="store_true", help="永久禁用广告包（治本，可 --enable 恢复）")
    ap.add_argument("--enable", action="store_true", help="恢复被 --disable 的广告包")
    ap.add_argument("--uninstall", action="store_true", help="卸载广告包（--user 0，可 install-existing 恢复）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args()
    if a.addr:
        ADDR = a.addr
        os.environ["ARK_ADDR"] = a.addr

    if not device_online():
        log("!! 设备不在线（%s）—— 先启动雷电" % ADDR)
        return RC_NO_DEVICE

    if a.status:
        return cmd_status(a)

    if a.disable or a.enable or a.uninstall:
        if a.disable:
            ok, msg = set_disabled(True)
            log("永久禁用 %s：%s %s" % (PKG, "成功 ✔" if ok else "失败", msg))
        elif a.enable:
            ok, msg = set_disabled(False)
            log("恢复 %s：%s %s" % (PKG, "成功 ✔" if ok else "失败", msg))
        else:
            ok, msg = uninstall_pkg()
            log("卸载 %s：%s %s" % (PKG, "成功 ✔" if ok else "失败", msg))
        st = package_state()
        if a.json:
            print(json.dumps({"pkg": PKG, "ok": ok, "msg": msg, **st},
                             ensure_ascii=False, indent=2))
        else:
            log("现状态：%s" % ("已禁用" if st["disabled"] else
                                "已启用" if st["enabled"] else "未安装"))
        return RC_OK if ok else RC_ADB

    if a.watch:
        return cmd_watch(a)

    return _handle_once(a)


if __name__ == "__main__":
    sys.exit(main())
