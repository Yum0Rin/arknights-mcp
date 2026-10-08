#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
arknights-mcp —— 明日方舟 MCP 服务器
=====================================
把 MaaCore（MAA）的识别能力 + adb 操作封装成 MCP 工具，让任意 LLM Agent 能
“观察 + 操作”明日方舟。

识别原理与 MAA 一致：**模板匹配 + OCR（确定性 CV）**，不依赖任何 AI 读图。

运行方式：stdio（供 opencode / 其它 MCP 客户端调用）。
"""
from __future__ import annotations

import os
import io
import sys
import json
import time
import base64
import pathlib
import subprocess
import threading

__version__ = "0.1.0"

# ----------------------------------------------------------------------------
# 配置（均可用环境变量覆盖）
# ----------------------------------------------------------------------------
MAA_PATH = os.environ.get("ARK_MAA_PATH", r"C:\MAA")
ADB_BIN = os.environ.get("ARK_ADB", r"C:\leidian\LDPlayer9\adb.exe")
ADB_ADDR = os.environ.get("ARK_ADDR", "127.0.0.1:5555")
TOUCH_MODE = os.environ.get("ARK_TOUCH", "maatouch")
TEMPLATE_DIR = pathlib.Path(MAA_PATH) / "resource" / "template"
TASKS_FILE = pathlib.Path(MAA_PATH) / "resource" / "tasks" / "tasks.json"
LOG_FILE = os.environ.get(
    "ARK_LOG",
    str(pathlib.Path(os.environ.get("TEMP", ".")) / "arknights-mcp.log"),
)

sys.path.insert(0, str(pathlib.Path(MAA_PATH) / "Python"))

# ----------------------------------------------------------------------------
# 日志（写文件；stdout 留给 MCP 传输，绝不能打印）
# ----------------------------------------------------------------------------
def log(msg: str) -> None:
    try:
        with io.open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


# ----------------------------------------------------------------------------
# 依赖
# ----------------------------------------------------------------------------
try:
    import numpy as np
    import cv2
    _HAS_CV = True
except Exception as e:  # pragma: no cover
    _HAS_CV = False
    log("cv2/numpy 不可用: %s" % e)

try:
    from mcp.server.fastmcp import FastMCP
except Exception as e:  # pragma: no cover
    raise SystemExit("缺少 mcp 包，请 pip install mcp：%s" % e)

mcp = FastMCP("arknights-mcp")

# ----------------------------------------------------------------------------
# 全局状态
# ----------------------------------------------------------------------------
_asst = None
_loaded = False
_serial = None
_callbacks: list = []          # [(msg:int, details:str), ...]
_latest: dict = {}             # 最近一次 OperBox / Depot 结果
_lock = threading.Lock()

try:
    from asst.asst import Asst
    from asst.utils import InstanceOptionType, Message
    _HAS_ASST = True
except Exception as e:  # pragma: no cover
    _HAS_ASST = False
    log("asst 绑定不可用: %s" % e)


def _on_callback(msg, details, arg):
    """MAA 回调：留痕 + 捕获识别结果。"""
    try:
        s = details.decode("utf-8", "ignore")
    except Exception:
        s = str(details)
    with _lock:
        _callbacks.append((int(msg), s))
        if len(_callbacks) > 8000:
            del _callbacks[:4000]
    # 20003 = SubTaskExtraInfo
    if int(msg) == 20003 and ("OperBoxInfo" in s or "DepotInfo" in s):
        try:
            o = json.loads(s)
            what = o.get("what")
            d = o.get("details", {})
            if what == "OperBoxInfo" and d.get("done"):
                _latest["operbox"] = d
            elif what == "DepotInfo" and d.get("done"):
                _latest["depot"] = d
        except Exception:
            pass


# ctypes 回调必须常驻引用，否则被 GC 回收会导致崩溃
_CB = Asst.CallBackType(_on_callback) if _HAS_ASST else None


def _ensure_asst():
    global _asst, _loaded
    if not _HAS_ASST:
        raise RuntimeError("MaaCore(asst) 不可用，请检查 ARK_MAA_PATH")
    if _asst is not None:
        return _asst
    if not _loaded:
        ok = Asst.load(path=pathlib.Path(MAA_PATH))
        _loaded = True
        log("Asst.load(%s) -> %s" % (MAA_PATH, ok))
    _asst = Asst(callback=_CB)
    return _asst


# ----------------------------------------------------------------------------
# adb 辅助
# ----------------------------------------------------------------------------
def _adb(*args, timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = [ADB_BIN]
    if _serial:
        cmd += ["-s", _serial]
    cmd += [str(a) for a in args]
    log("adb: " + " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _detect_serial():
    global _serial
    try:
        r = subprocess.run([ADB_BIN, "devices"], capture_output=True, text=True, timeout=30)
        for ln in r.stdout.splitlines():
            if "\tdevice" in ln:
                _serial = ln.split("\t")[0].strip()
                return _serial
    except Exception as e:
        log("detect serial 失败: %s" % e)
    return None


def _screencap_bytes() -> bytes:
    cmd = [ADB_BIN]
    if _serial:
        cmd += ["-s", _serial]
    cmd += ["exec-out", "screencap", "-p"]
    r = subprocess.run(cmd, capture_output=True, timeout=40)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("screencap 失败: " + r.stderr.decode("utf-8", "ignore"))
    # 修正 Windows 下 adb 对 png 的 \n -> \r\n 行为
    return r.stdout.replace(b"\r\n", b"\n")


def _resolve_template(name: str):
    """在 MAA 模板目录里按文件名/相对路径找模板。"""
    p = pathlib.Path(name)
    if p.is_file():
        return p
    if not TEMPLATE_DIR.exists():
        return None
    # 先精确匹配文件名
    for f in TEMPLATE_DIR.rglob(name):
        return f
    # 再匹配带 .png 的文件名
    if not name.lower().endswith(".png"):
        for f in TEMPLATE_DIR.rglob(name + ".png"):
            return f
    return None


# ============================================================================
# MCP 工具
# ============================================================================
@mcp.tool()
def ark_version() -> dict:
    """返回本 MCP 版本与后端信息（MaaCore 版本、依赖状态）。"""
    info = {
        "mcp_version": __version__,
        "maa_path": MAA_PATH,
        "maa_core": None,
        "cv2": _HAS_CV,
        "asst": _HAS_ASST,
        "adb": ADB_BIN,
        "address": ADB_ADDR,
        "touch": TOUCH_MODE,
        "log": LOG_FILE,
    }
    if _HAS_ASST:
        try:
            info["maa_core"] = _ensure_asst().get_version()
        except Exception as e:
            info["maa_core"] = "err: %s" % e
    return info


@mcp.tool()
def ark_connect(address: str = "", adb_path: str = "", touch: str = "", config: str = "General") -> dict:
    """连接模拟器。默认连雷电 LDPlayer9（127.0.0.1:5555, maatouch）。address/adb_path/touch 可覆盖。"""
    global ADB_ADDR, ADB_BIN, TOUCH_MODE
    if address:
        ADB_ADDR = address
    if adb_path:
        ADB_BIN = adb_path
    if touch:
        TOUCH_MODE = touch
    a = _ensure_asst()
    try:
        a.set_instance_option(InstanceOptionType.touch_type, TOUCH_MODE)
    except Exception as e:
        log("set touch 失败: %s" % e)
    ok = a.connect(ADB_BIN, ADB_ADDR, config)
    _detect_serial()
    log("connect %s ok=%s serial=%s touch=%s" % (ADB_ADDR, ok, _serial, TOUCH_MODE))
    return {"connected": bool(ok), "address": ADB_ADDR, "touch": TOUCH_MODE, "serial": _serial}


@mcp.tool()
def ark_status() -> dict:
    """返回连接/运行状态。"""
    running = None
    if _asst is not None:
        try:
            running = bool(_asst.running())
        except Exception:
            running = None
    return {"serial": _serial, "address": ADB_ADDR, "connected": _asst is not None, "running": running}


@mcp.tool()
def ark_screenshot(save_path: str = "") -> dict:
    """截取当前画面并保存为 PNG，返回路径（供 Agent 用文件读取查看）。"""
    if not save_path:
        save_path = str(pathlib.Path(os.environ.get("TEMP", ".")) / ("ark_shot_%d.png" % int(time.time() * 1000)))
    data = _screencap_bytes()
    with open(save_path, "wb") as f:
        f.write(data)
    log("screenshot -> %s (%d bytes)" % (save_path, len(data)))
    return {"ok": True, "path": save_path, "bytes": len(data)}


@mcp.tool()
def ark_tap(x: int, y: int) -> dict:
    """在屏幕坐标 (x, y) 点击一下。"""
    r = _adb("shell", "input", "tap", x, y)
    return {"ok": r.returncode == 0}


@mcp.tool()
def ark_swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> dict:
    """从 (x1,y1) 滑到 (x2,y2)，持续 duration_ms 毫秒。"""
    r = _adb("shell", "input", "swipe", x1, y1, x2, y2, duration_ms)
    return {"ok": r.returncode == 0}


@mcp.tool()
def ark_key(code: int) -> dict:
    """发送 Android 按键事件，如 4=返回, 3=Home, 26=电源。"""
    r = _adb("shell", "input", "keyevent", code)
    return {"ok": r.returncode == 0}


@mcp.tool()
def ark_list_tasks(keyword: str = "") -> dict:
    """列出 MAA 内置任务名（可按关键字过滤），供 ark_run_task 使用。"""
    if not TASKS_FILE.exists():
        return {"ok": False, "error": "找不到 %s" % TASKS_FILE}
    try:
        # tasks.json 存在大小写重复键，标准 json 会报错，这里做一次容错
        txt = TASKS_FILE.read_text(encoding="utf-8")
        keys = sorted(set(__import__("re").findall(r'^\s{4}"([^"]+)"\s*:\s*\{', txt, __import__("re").M)))
        names = [k for k in keys if (not keyword or keyword.lower() in k.lower())]
        return {"ok": True, "count": len(names), "tasks": names[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _run_sequence(tasks: list, timeout_s: int) -> dict:
    """依次 append 多个任务并运行到结束。返回结果摘要。"""
    a = _ensure_asst()
    with _lock:
        _callbacks.clear()
    tids = []
    for name, params in tasks:
        tid = a.append_task(name, params or {})
        tids.append({"task": name, "id": tid})
        if not tid:
            return {"ok": False, "error": "append_task 失败: %s" % name, "tasks": tids}
    a.start()
    end = time.time() + timeout_s
    while a.running() and time.time() < end:
        time.sleep(0.2)
    timed_out = bool(a.running())
    if timed_out:
        a.stop()
    with _lock:
        cbs = list(_callbacks)
    chains, errors = [], []
    for m, d in cbs:
        try:
            o = json.loads(d)
        except Exception:
            continue
        if m == 10001:  # TaskChainStart
            chains.append(o.get("taskchain"))
        elif m == 10000:  # TaskChainError
            errors.append(o.get("taskchain"))
    return {"ok": not timed_out, "timed_out": timed_out,
            "tasks": tids, "chains": chains, "errors": errors, "callback_count": len(cbs)}


@mcp.tool()
def ark_run_task(name: str, params: dict = None, timeout_s: int = 300) -> dict:
    """运行一个 MAA 任务（如 StartUp / Fight / Infrast / Recruit / Mall / Award / OperBox / Depot 等）。
    params 为该任务参数（见 MAA 集成文档）。任务跑完返回摘要。"""
    return _run_sequence([(name, params or {})], timeout_s)


@mcp.tool()
def ark_operbox(start_game: bool = True, timeout_s: int = 300, save_to: str = "") -> dict:
    """干员 box 识别：跑 MAA 的 OperBox 任务，返回识别到的干员（含精英/等级/潜能）。
    这是 MAA 的确定性识别，不涉及 AI 读图。"""
    _latest.pop("operbox", None)
    seq = []
    if start_game:
        seq.append(("StartUp", {"enable": True, "client_type": "Official", "start_game_enabled": True}))
    seq.append(("OperBox", {"enable": True}))
    res = _run_sequence(seq, timeout_s)
    box = _latest.get("operbox")
    if not box:
        res["error"] = "未捕获到 OperBoxInfo（识别可能未完成或失败）"
        return res
    out = {"done": True, "own_opers": box.get("own_opers", []), "all_opers": box.get("all_opers", [])}
    if save_to:
        with io.open(save_to, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        res["saved_to"] = save_to
    res["own_count"] = len(out["own_opers"])
    res["own_opers"] = out["own_opers"]
    return res


@mcp.tool()
def ark_depot(timeout_s: int = 300, save_to: str = "") -> dict:
    """仓库识别：跑 MAA 的 Depot 任务，返回物品数量字典。"""
    _latest.pop("depot", None)
    res = _run_sequence([("Depot", {"enable": True})], timeout_s)
    d = _latest.get("depot")
    if not d:
        res["error"] = "未捕获到 DepotInfo"
        return res
    data = d.get("data", "{}")
    try:
        parsed = json.loads(data) if isinstance(data, str) else data
    except Exception:
        parsed = data
    res["items"] = parsed
    if save_to:
        with io.open(save_to, "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)
        res["saved_to"] = save_to
    return res


@mcp.tool()
def ark_find(template: str, threshold: float = 0.8, roi: list = None) -> dict:
    """在当前画面里做模板匹配（MAA 模板库里的 png），返回所有命中矩形。
    template: 模板名（如 "OperBox/OperBoxFlagElite2.png" 或文件名），roi: [x,y,w,h] 可选。"""
    if not _HAS_CV:
        return {"ok": False, "error": "缺少 opencv/numpy"}
    tpath = _resolve_template(template)
    if not tpath:
        return {"ok": False, "error": "模板未找到: %s" % template}
    shot = str(pathlib.Path(os.environ.get("TEMP", ".")) / "ark_find_shot.png")
    with open(shot, "wb") as f:
        f.write(_screencap_bytes())
    screen = cv2.imread(shot, cv2.IMREAD_COLOR)
    tmpl = cv2.imread(str(tpath), cv2.IMREAD_UNCHANGED)
    if screen is None or tmpl is None:
        return {"ok": False, "error": "图像读取失败"}
    ox, oy = 0, 0
    if roi and len(roi) == 4:
        ox, oy, w, h = roi
        screen = screen[oy:oy + h, ox:ox + w]
    mask = None
    if tmpl.ndim == 3 and tmpl.shape[2] == 4:
        mask = tmpl[:, :, 3]
        tmpl3 = tmpl[:, :, :3]
    else:
        tmpl3 = tmpl if tmpl.ndim == 3 else cv2.cvtColor(tmpl, cv2.COLOR_GRAY2BGR)
    th, tw = tmpl3.shape[:2]
    if screen.shape[0] < th or screen.shape[1] < tw:
        return {"ok": True, "matches": [], "template": str(tpath)}
    if mask is not None:
        res = cv2.matchTemplate(screen, tmpl3, cv2.TM_CCORR_NORMED, mask=mask)
    else:
        res = cv2.matchTemplate(screen, tmpl3, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    matches = []
    for (x, y, score) in sorted(
        [(int(x), int(y), float(res[y, x])) for y, x in zip(ys, xs)],
        key=lambda t: -t[2],
    ):
        matches.append({"x": x + ox, "y": y + oy, "w": tw, "h": th,
                        "cx": x + ox + tw // 2, "cy": y + oy + th // 2, "score": round(score, 4)})
        if len(matches) >= 30:
            break
    log("find %s thr=%.2f -> %d" % (template, threshold, len(matches)))
    return {"ok": True, "template": str(tpath), "matches": matches}


@mcp.tool()
def ark_read_log(lines: int = 80) -> dict:
    """读取本 MCP 的调试日志尾部（留痕/排障用）。"""
    try:
        with io.open(LOG_FILE, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        return {"ok": True, "tail": "".join(all_lines[-lines:])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    log("===== arknights-mcp %s 启动 =====" % __version__)
    mcp.run()
