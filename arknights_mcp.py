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

__version__ = "0.3.0"

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
_connected = False
_last_run: dict = {}            # 最近一次 ark_run_task 的 {tasks, started_at, done}

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
def _detect_serial():
    """选取 adb 目标序列号。雷电常同时暴露 127.0.0.1:5555 与 emulator-5554（同一设备），
    优先用 ARK_ADDR，其次 emulator-*，避免 adb 报 'more than one device'。"""
    global _serial
    try:
        r = subprocess.run([ADB_BIN, "devices"], capture_output=True, text=True, timeout=30)
        devs = [ln.split()[0] for ln in r.stdout.splitlines() if "\tdevice" in ln]
        if not devs:
            _serial = None
        elif ADB_ADDR in devs:
            _serial = ADB_ADDR
        else:
            emu = [d for d in devs if d.startswith("emulator-")]
            _serial = emu[0] if emu else devs[0]
    except Exception as e:
        log("detect serial 失败: %s" % e)
        _serial = None
    return _serial


def _ensure_serial():
    if not _serial:
        _detect_serial()


def _adb(*args, timeout: int = 60) -> subprocess.CompletedProcess:
    _ensure_serial()
    cmd = [ADB_BIN]
    if _serial:
        cmd += ["-s", _serial]
    cmd += [str(a) for a in args]
    log("adb: " + " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _screencap_bytes() -> bytes:
    _ensure_serial()
    cmd = [ADB_BIN]
    if _serial:
        cmd += ["-s", _serial]
    cmd += ["exec-out", "screencap", "-p"]
    r = subprocess.run(cmd, capture_output=True, timeout=40)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("screencap 失败: " + r.stderr.decode("utf-8", "ignore"))
    # exec-out 为二进制安全，切勿做 \r\n 替换（会损坏 PNG）
    return r.stdout


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
    global ADB_ADDR, ADB_BIN, TOUCH_MODE, _connected
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
    _connected = bool(ok)
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
    return {"serial": _serial, "address": ADB_ADDR, "connected": _connected, "running": running}


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


def _start_tasks(tasks: list):
    """connect（若未连）+ append 多个任务 + start。返回 (asst, tids)；append 失败抛 RuntimeError。"""
    global _connected, _last_run
    a = _ensure_asst()
    # 关键：任务要驱动设备必须先 connect，否则 MaaCore 报 m_controller is not inited（滑动/战斗静默失效）
    if not _connected:
        try:
            a.set_instance_option(InstanceOptionType.touch_type, TOUCH_MODE)
        except Exception as e:
            log("auto set touch 失败: %s" % e)
        ok = a.connect(ADB_BIN, ADB_ADDR, "General")
        _connected = bool(ok)
        log("auto-connect %s ok=%s" % (ADB_ADDR, ok))
    with _lock:
        _callbacks.clear()
    tids = []
    for name, params in tasks:
        tid = a.append_task(name, params or {})
        tids.append({"task": name, "id": tid})
        if not tid:
            _last_run = {"tasks": tids, "started_at": time.time(), "done": True}
            raise RuntimeError("append_task 失败: %s" % name)
    a.start()
    _last_run = {"tasks": tids, "started_at": time.time(), "done": False}
    log("start tasks=%s" % tids)
    return a, tids


def _collect(a) -> dict:
    """读取回调，汇总 TaskChain 完成(chains) / 出错(errors)。"""
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
    return {"chains": chains, "errors": errors, "callback_count": len(cbs)}


def _run_sequence(tasks: list, timeout_s: int, wait: bool = True, stop_on_timeout: bool = False) -> dict:
    """append+start 一组任务。
    - wait=False：启动后立即返回（**异步**，长任务推荐；用 ark_task_result() 轮询）。
    - wait=True ：阻塞至多 timeout_s 秒；**默认超时不杀任务**（stop_on_timeout=False），
      以便调用方继续轮询，避免把已进队的长任务（如战斗）掐断在中间画面。"""
    global _last_run
    try:
        a, tids = _start_tasks(tasks)
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "tasks": _last_run.get("tasks", [])}
    if not wait:
        return {"ok": True, "async": True, "running": True, "done": False, "tasks": tids,
                "note": "已后台启动，请用 ark_task_result() 轮询；或 ark_status() 看 running"}
    end = time.time() + timeout_s
    while a.running() and time.time() < end:
        time.sleep(0.2)
    timed_out = bool(a.running())
    if timed_out and stop_on_timeout:
        a.stop()
        log("timeout -> stop tasks=%s" % tids)
    done = not a.running()
    _last_run["done"] = done
    return {"ok": not timed_out, "async": False, "timed_out": timed_out, "done": done,
            "running": timed_out and not stop_on_timeout,
            "tasks": tids, **_collect(a)}


@mcp.tool()
def ark_run_task(name: str, params: dict = None, timeout_s: int = 300,
                 wait: bool = True, stop_on_timeout: bool = False) -> dict:
    """运行一个 MAA 任务（如 StartUp / Fight / Infrast / Recruit / Mall / Award / Copilot 等）。
    - wait=True（默认）：阻塞至多 timeout_s 秒；**超时不杀任务**，可继续用 ark_task_result() 轮询。
    - wait=False：启动后立即返回（长任务/战斗/自动战斗推荐），随后用 ark_task_result() 轮询。
    - stop_on_timeout=True：恢复旧行为（超时即 stop 任务）。
    params 为该任务参数（见 MAA 集成文档）。"""
    return _run_sequence([(name, params or {})], timeout_s, wait=wait, stop_on_timeout=stop_on_timeout)


@mcp.tool()
def ark_task_result() -> dict:
    """轮询当前/最近一次 ark_run_task 的状态与结果（供长任务用）。
    返回 running(是否仍在跑) / done / elapsed，以及 TaskChain 完成(chains)与出错(errors)。
    done=True 且 errors 为空 = 正常结束。"""
    if _asst is None:
        return {"ok": False, "error": "尚未运行任何任务（先 ark_connect 或 ark_run_task）"}
    try:
        running = bool(_asst.running())
    except Exception as e:
        return {"ok": False, "error": str(e)}
    started = _last_run.get("started_at")
    out = {"ok": True, "running": running, "done": not running,
           "tasks": _last_run.get("tasks", []),
           "elapsed": round(time.time() - started, 1) if started else None}
    if not running:
        _last_run["done"] = True
        out.update(_collect(_asst))
    return out


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


# ----------------------------------------------------------------------------
# 森空岛在线取数（**免模拟器**）：走 zonai.skland.com 的账号接口，不碰 MAA/雷电。
# 适配器 scripts/skland/skland_box.py 把结果转成与 OperBoxData.json 同构的形态。
# 取数/登录细节见 docs/DATA-SOURCES.md §7；与 MAA 路径的取舍见仓库 AGENTS.md。
# ----------------------------------------------------------------------------
def _skland_box():
    """惰性加载 scripts/skland/skland_box.py（不需要 MAA，也不需要模拟器）。"""
    p = str(pathlib.Path(__file__).resolve().parent / "scripts" / "skland")
    if p not in sys.path:
        sys.path.insert(0, p)
    import skland_box  # noqa: PLC0415
    return skland_box


@mcp.tool()
def ark_operbox_online(save_to: str = "") -> dict:
    """在线读干员箱（走森空岛接口，**免模拟器/MAA**）。

    返回与 `ark_operbox` 同构的 `own_opers`（id/name/elite/level/potential/rarity/own），
    另带 MAA 给不了的 `skill_lvl`（技能等级 1–7）与 `spec`（各技能专精等级）。
    需先登录存凭证：`python scripts/skland/skland_cli.py login`。
    只读查询，不用开模拟器；数据来源与字段映射见 `docs/DATA-SOURCES.md` §7。
    """
    try:
        data = _skland_box().fetch_operbox()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    if save_to:
        with io.open(save_to, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        data["saved_to"] = save_to
    return data


@mcp.tool()
def ark_infrast_status() -> dict:
    """读当前基建状态（走森空岛接口，免模拟器）。

    返回各设施槽位等级 + 进驻干员（控制中枢/贸易站/制造站/发电站/宿舍/会客室/办公室/训练室）、
    无人机、家具数、疲劳干员。MCP 原先没有这个"查询"（只有 `Infrast` 任务=改基建）。
    """
    try:
        return _skland_box().fetch_base()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


# 页面锚点：页面名 -> MAA 模板（用于 ark_where；可被 custom 覆盖/追加）
# 注意：默认锚点是"起始种子"，未必对所有页面都准（MAA 的 QuickSwitch/* 图标是
#       快捷切换弹窗里的图标，不是各页常驻元素）。要精确识别某页，请用 custom 传
#       {页面名: 模板名/绝对路径}，模板可为 MAA 自带，也可自行截图裁剪。
DEFAULT_ANCHORS = {
    "快捷切换-首页": "QuickSwitch/Home.png",
    "快捷切换-终端": "QuickSwitch/Terminal.png",
    "快捷切换-干员": "QuickSwitch/OperBox.png",
    "快捷切换-基建": "QuickSwitch/Infrast.png",
    "快捷切换-采购中心": "QuickSwitch/Mall.png",
    "快捷切换-公开招募": "QuickSwitch/Recruit.png",
    "快捷切换-干员寻访": "QuickSwitch/Gacha.png",
    "快捷切换-菜单": "QuickSwitch/Menu.png",
}


def _grab_screen():
    """截当前画面为 BGR ndarray。"""
    shot = str(pathlib.Path(os.environ.get("TEMP", ".")) / "ark_screen.png")
    with open(shot, "wb") as f:
        f.write(_screencap_bytes())
    return cv2.imread(shot, cv2.IMREAD_COLOR)


def _match(screen, tpath):
    """在 screen 上匹配模板，返回 (res_map, tw, th)。
    4 通道模板先按 alpha 合成到中灰再匹配，并用 TM_CCOEFF_NORMED，
    避免 TM_CCORR_NORMED 对亮模板产生的虚高假阳性。"""
    tmpl = cv2.imread(str(tpath), cv2.IMREAD_UNCHANGED)
    if tmpl is None:
        raise RuntimeError("模板读取失败: %s" % tpath)
    if tmpl.ndim == 3 and tmpl.shape[2] == 4:
        a = tmpl[:, :, 3:4].astype(np.float32) / 255.0
        bgr = tmpl[:, :, :3].astype(np.float32)
        tmpl3 = (bgr * a + 128.0 * (1.0 - a)).astype(np.uint8)
    elif tmpl.ndim == 3:
        tmpl3 = tmpl
    else:
        tmpl3 = cv2.cvtColor(tmpl, cv2.COLOR_GRAY2BGR)
    res = cv2.matchTemplate(screen, tmpl3, cv2.TM_CCOEFF_NORMED)
    th, tw = tmpl3.shape[:2]
    return res, tw, th


@mcp.tool()
def ark_find(template: str, threshold: float = 0.8, roi: list = None) -> dict:
    """在当前画面里做模板匹配（MAA 模板库里的 png），返回所有命中矩形。
    template: 模板名（如 "OperBox/OperBoxFlagElite2.png" 或文件名），roi: [x,y,w,h] 可选。"""
    if not _HAS_CV:
        return {"ok": False, "error": "缺少 opencv/numpy"}
    tpath = _resolve_template(template)
    if not tpath:
        return {"ok": False, "error": "模板未找到: %s" % template}
    screen = _grab_screen()
    if screen is None:
        return {"ok": False, "error": "截图读取失败"}
    ox, oy = 0, 0
    if roi and len(roi) == 4:
        ox, oy, w, h = roi
        screen = screen[oy:oy + h, ox:ox + w]
    res, tw, th = _match(screen, tpath)
    if screen.shape[0] < th or screen.shape[1] < tw:
        return {"ok": True, "matches": [], "template": str(tpath)}
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
def ark_where(threshold: float = 0.85, custom: dict = None) -> dict:
    """判断当前处于哪个页面：对一组"页面锚点"模板做匹配，返回命中页面（按分数降序）。
    完全基于模板匹配，不需要 AI 读图。custom 可传 {页面名: 模板名} 覆盖/追加默认锚点。"""
    if not _HAS_CV:
        return {"ok": False, "error": "缺少 opencv/numpy"}
    anchors = dict(DEFAULT_ANCHORS)
    if custom:
        anchors.update(custom)
    screen = _grab_screen()
    if screen is None:
        return {"ok": False, "error": "截图读取失败"}
    results = []
    for page, tpl in anchors.items():
        tpath = _resolve_template(tpl)
        if not tpath:
            results.append({"page": page, "template": tpl, "score": None})
            continue
        try:
            res, tw, th = _match(screen, tpath)
            results.append({"page": page, "template": tpl, "score": round(float(res.max()), 4)})
        except Exception as e:
            results.append({"page": page, "template": tpl, "score": None, "error": str(e)})
    scored = [r for r in results if isinstance(r.get("score"), float)]
    scored.sort(key=lambda r: -r["score"])
    matched = [r for r in scored if r["score"] >= threshold]
    best = scored[0] if scored else None
    log("where -> matched=%s best=%s" % ([m["page"] for m in matched], best and best["page"]))
    return {"ok": True, "matched": matched, "best": best, "all": scored}


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
