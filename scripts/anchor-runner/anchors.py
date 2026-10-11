#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""锚点工具库：截图(快速 gzip 通道) + 模板匹配(按分辨率自动缩放) + adb 点击。

给 record.py / play.py 用，也可被其它脚本 import。

- 截图走 MAA 同款 `screencap | gzip -1`（本机实测 666ms -> 261ms），失败自动回退 PNG。
- 坐标一律「实际屏幕像素」（1920x1080）。
- 模板图可来自两处：
    * 本目录 anchors/  —— 自录锚点，参考宽度记在 anchors/index.json；
    * MAA 模板库 C:\\MAA\\resource\\template —— 参考宽度按 1280（MAA 约定）。
  匹配时按 `当前屏宽 / 参考宽` 自动缩放，所以换分辨率模板仍可用。
"""
from __future__ import annotations

import gzip
import json
import os
import pathlib
import struct
import subprocess
import time

import numpy as np
import cv2

ADB = os.environ.get("ARK_ADB", r"C:\leidian\LDPlayer9\adb.exe")
ADDR = os.environ.get("ARK_ADDR", "127.0.0.1:5555")
MAA = os.environ.get("ARK_MAA_PATH", r"C:\MAA")
ROOT = pathlib.Path(__file__).resolve().parent
ANCHOR_DIR = ROOT / "anchors"
INDEX = ANCHOR_DIR / "index.json"
MAA_TPL = pathlib.Path(MAA) / "resource" / "template"
TMP = pathlib.Path(os.environ.get("TEMP", ".")) / "anchor-runner"


def log(msg) -> None:
    print("[anchor] " + str(msg), flush=True)


# ---------------------------------------------------------------------------
# adb 原语
# ---------------------------------------------------------------------------
def _adb(*args, timeout=40):
    return subprocess.run([ADB, "-s", ADDR] + [str(a) for a in args],
                          capture_output=True, timeout=timeout)


def _devices():
    r = subprocess.run([ADB, "devices"], capture_output=True, timeout=20)
    lines = r.stdout.decode("utf-8", "replace").splitlines()
    return [l.split("\t")[0] for l in lines[1:] if "\tdevice" in l]


def resolve_addr():
    """优先用 ADDR；连不上就退回 `adb devices` 里的第一台（本机实际是 emulator-5554）。"""
    global ADDR
    r = subprocess.run([ADB, "-s", ADDR, "get-state"], capture_output=True, timeout=15)
    if r.returncode == 0 and b"device" in r.stdout:
        return ADDR
    devs = _devices()
    if devs:
        log("ADDR=%s 连不上，改用 %s" % (ADDR, devs[0]))
        ADDR = devs[0]
    else:
        log("警告：adb 里没有在线设备")
    return ADDR


_ADDR_OK = False


def ensure_addr():
    """首次使用时自动解析一次地址（库被直接 import 时也能连上设备）。"""
    global _ADDR_OK
    if not _ADDR_OK:
        resolve_addr()
        _ADDR_OK = True
    return ADDR


def tap(x, y) -> None:
    ensure_addr()
    _adb("shell", "input", "tap", int(x), int(y))


def key(code) -> None:
    ensure_addr()
    _adb("shell", "input", "keyevent", int(code))


# ---------------------------------------------------------------------------
# 截图：MAA 同款 raw+gzip 通道
# ---------------------------------------------------------------------------
def _raw_to_bgr(raw: bytes):
    """Android `screencap`（无 -p）raw 字节 -> BGR。像素取「末尾 w*h*4」，对头长不敏感
    （本机头长实测 16 字节，新 Android 多带字段）。"""
    w, h, fmt = struct.unpack_from("<III", raw, 0)
    n4 = w * h * 4
    off = len(raw) - n4
    if off < 0:  # 回退 3 字节/像素
        n3 = w * h * 3
        off3 = len(raw) - n3
        if off3 < 0:
            raise ValueError("raw 尺寸不符: %dx%d, %d bytes" % (w, h, len(raw)))
        pix = np.frombuffer(raw[off3:off3 + n3], np.uint8).reshape(h, w, 3)
        return cv2.cvtColor(pix, cv2.COLOR_RGB2BGR)
    pix = np.frombuffer(raw[off:off + n4], np.uint8).reshape(h, w, 4)
    if fmt == 2:  # RGBX_8888：第 4 通道是填充
        return cv2.cvtColor(pix[:, :, :3], cv2.COLOR_RGB2BGR)
    return cv2.cvtColor(pix, cv2.COLOR_RGBA2BGR)


def imread(path):
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def screenshot(save: str | None = None):
    """截一张当前屏（BGR）。save 给文件名时，同时把 PNG 存到 TMP 便于排障。
    失败（无设备/解码失败）返回 None，不抛异常。"""
    ensure_addr()
    r = subprocess.run([ADB, "-s", ADDR, "exec-out", "screencap | gzip -1"],
                       capture_output=True, timeout=40)
    img = None
    if r.returncode == 0 and r.stdout:
        try:
            img = _raw_to_bgr(gzip.decompress(r.stdout))
        except Exception as e:
            log("raw+gzip 解码失败，回退 PNG: %s" % e)
    if img is None:
        TMP.mkdir(parents=True, exist_ok=True)
        p = TMP / (save or "shot.png")
        with open(p, "wb") as f:
            subprocess.run([ADB, "-s", ADDR, "exec-out", "screencap", "-p"],
                           stdout=f, timeout=40)
        img = imread(p)
    if save and img is not None:
        TMP.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(TMP / save), img)
    return img


# ---------------------------------------------------------------------------
# 锚点存取（anchors/ + index.json）
# ---------------------------------------------------------------------------
def _load_index() -> dict:
    if INDEX.exists():
        try:
            return json.loads(INDEX.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_index(d: dict) -> None:
    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def save_anchor(name: str, crop, ref_w: int, rect=None) -> pathlib.Path:
    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    fn = name if name.lower().endswith(".png") else name + ".png"
    p = ANCHOR_DIR / pathlib.Path(fn).name
    cv2.imwrite(str(p), crop)
    d = _load_index()
    d[p.name] = {"ref_w": int(ref_w), "rect": list(rect or []),
                 "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    _save_index(d)
    return p


def resolve_template(name: str):
    """把模板名解析为 (路径, 参考宽度)。找不到返回 (None, None)。"""
    p = pathlib.Path(name)
    if p.exists():
        return p, _load_index().get(p.name, {}).get("ref_w", 1280)
    cand = ANCHOR_DIR / (name if name.lower().endswith(".png") else name + ".png")
    if cand.exists():
        return cand, _load_index().get(cand.name, {}).get("ref_w", 1280)
    if MAA_TPL.exists():
        for f in MAA_TPL.rglob(pathlib.Path(name).name):
            return f, 1280
    return None, None


def load_tpl(path):
    t = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if t is None:
        return None
    if t.ndim == 3 and t.shape[2] == 4:  # 透明底压到灰底，与截图背景更接近
        a = t[:, :, 3:4].astype(np.float32) / 255.0
        bgr = t[:, :, :3].astype(np.float32)
        t = (bgr * a + 128.0 * (1.0 - a)).astype(np.uint8)
    elif t.ndim == 2:
        t = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
    return t


def match(screen, name: str, thr: float = 0.8, roi=None):
    """在 screen 里找模板 name。命中返回 {cx,cy,score,tpl}，否则 None。
    roi=[x,y,w,h] 限定搜索区；按分辨率缩放会自动处理。"""
    path, ref_w = resolve_template(name)
    if path is None:
        log("模板不存在: %s" % name)
        return None
    tpl = load_tpl(path)
    if tpl is None:
        return None
    sc = screen.shape[1] / float(ref_w) if ref_w else 1.0
    if abs(sc - 1.0) > 0.01:
        tpl = cv2.resize(tpl, (max(1, int(round(tpl.shape[1] * sc))),
                               max(1, int(round(tpl.shape[0] * sc)))))
    ox, oy = 0, 0
    region = screen
    if roi:
        ox, oy, w, h = roi
        region = screen[oy:oy + h, ox:ox + w]
    if region.shape[0] < tpl.shape[0] or region.shape[1] < tpl.shape[1]:
        return None
    res = cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(res)
    if mx < thr:
        return None
    return {"cx": int(ox + loc[0] + tpl.shape[1] // 2),
            "cy": int(oy + loc[1] + tpl.shape[0] // 2),
            "score": round(float(mx), 4), "tpl": str(path)}


def draw_grid(img, step: int):
    """在图上叠 step 像素网格 + 刻度，方便按格读坐标。"""
    out = img.copy()
    h, w = out.shape[:2]
    for x in range(0, w, step):
        cv2.line(out, (x, 0), (x, h), (0, 0, 255), 1)
        cv2.putText(out, str(x), (x + 2, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    for y in range(0, h, step):
        cv2.line(out, (0, y), (w, y), (0, 0, 255), 1)
        cv2.putText(out, str(y), (2, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    return out
