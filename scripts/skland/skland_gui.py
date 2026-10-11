#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""明日方舟 · 助手（总控台）—— CustomTkinter 图形界面版。

流程：**登录 → 拉数据 → 看板**

1. 填手机号，选「验证码 / 密码」登录（凭证存 ~/.arknights_skland.json，只留 cred）；
2. 登录后自动拉取本人账号数据：概览 / 干员 / 基建 / 公招 / 战绩 / 签到；
3. 「刷新数据」重新拉；「样例」用本地样例 JSON 预览界面（不需要账号）。

界面/线程/主题逻辑照搬 cx-downloader：
  - 网络请求跑工作线程，结果经 self.q 回主线程（tkinter 非线程安全）；
  - 配色走点石国风五色，明暗两套，用 pair() 拼 (light, dark)；
  - Win11 标题栏着色 + DPI 自适应窗口尺寸/位置。

依赖: customtkinter
"""
from __future__ import annotations

import ctypes
import json
import os
import pathlib
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import customtkinter as ctk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import skland_client as core  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]  # 仓库根（本文件在 scripts/skland/ 下）
SETTINGS = os.path.join(os.path.expanduser("~"), ".arknights_skland_gui.json")
_SAMPLE_REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_player_info.json")
FIXTURE = (_SAMPLE_REPO if os.path.exists(_SAMPLE_REPO)
           else os.path.join(os.environ.get("TEMP", "."), "opencode", "skland-dump.json"))
LOG_FILE = os.path.join(os.environ.get("TEMP", "."), "arknights_skland_gui.log")

# ---------------------------------------------------------------- 配色（点石国风五色）
LIGHT = {
    "page": "#E9EDF2", "card": "#FFFFFF", "border": "#DFE5EC",
    "input": "#F1F4F8", "input_border": "#D3DBE4", "text": "#2F4858",
    "muted": "#5F6E7E", "primary": "#C03A2B", "primary_hover": "#A62F22",
    "secondary": "#EDF1F6", "secondary_hover": "#DDE4EC", "track": "#DFE6EE",
    "caption": "#2F4858", "caption_text": "#FFFFFF", "ok": "#1A7F37",
}
DARK = {
    "page": "#16191E", "card": "#20252C", "border": "#2E353E",
    "input": "#1A1E24", "input_border": "#333C46", "text": "#A8C6D8",
    "muted": "#8A97A5", "primary": "#D8503F", "primary_hover": "#E5675A",
    "secondary": "#2A313A", "secondary_hover": "#353E4A", "track": "#2E353E",
    "caption": "#20252C", "caption_text": "#D7DEE7", "ok": "#6FCF97",
}
LOG_STYLE = {
    "light": {"bg": "#F4F7FA", "border": "#DCE3EB", "fg": "#2F4858",
              "tags": {"ok": "#1A7F37", "err": "#C03A2B", "dim": "#78838F", "head": "#2F6F86"}},
    "dark": {"bg": "#151A21", "border": "#2E353E", "fg": "#D7DEE7",
             "tags": {"ok": "#6FCF97", "err": "#EE7B6E", "dim": "#8A97A5", "head": "#9CC2E5"}},
}

FONT = "Microsoft YaHei UI"
MONO = "Consolas"
FONT_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                   "Hiragino Sans GB", "Noto Sans CJK SC", "Source Han Sans SC",
                   "WenQuanYi Micro Hei", "Noto Sans SC", "DejaVu Sans")
MONO_CANDIDATES = ("Consolas", "Cascadia Mono", "Menlo", "Monaco",
                   "DejaVu Sans Mono", "Noto Sans Mono CJK SC", "Liberation Mono", "Courier")

PROFESSIONS = {"PIONEER": "先锋", "WARRIOR": "近卫", "SNIPER": "狙击", "CASTER": "术师",
               "MEDIC": "医疗", "SUPPORT": "辅助", "TANK": "重装", "SPECIAL": "特种",
               "TOKEN": "召唤物", "TRAP": "装置"}
ELITE = {0: "精0", 1: "精1", 2: "精2", 3: "精3"}

TABS = ["概览", "干员", "基建", "公招", "长草", "战绩", "签到", "原始 JSON"]

LOGIN_HINT = (
    "森空岛用「鹰角通行证」登录，和游戏是同一套账号。\n\n"
    "两条登录方式：\n"
    "  验证码 —— 填手机号 → 点「发送验证码」→ 填收到的码 → 登录。\n"
    "  密码   —— 直接填手机号 + 密码。\n\n"
    "登录成功后只把 cred（访问凭证）存到本机 ~/.arknights_skland.json，\n"
    "不保存密码。cred 等同账号访问权，别把它发给任何人。"
)
CRED_HINT = (
    "数据来自森空岛接口（zonai.skland.com），只读，不下任何操作指令。\n\n"
    "本工具不会也不能拿到「抽卡记录」—— 森空岛接口里没有这项数据，\n"
    "原版明日方舟官方也没有公开的抽卡查询接口。\n\n"
    "cred 会过期，过期后重新登录即可。"
)


def pair(key: str):
    return (LIGHT[key], DARK[key])


def load_settings() -> dict:
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_settings(d: dict) -> None:
    try:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def pick_font(candidates: tuple[str, ...], fallback: str) -> str:
    try:
        import tkinter.font as tkfont  # noqa: PLC0415

        have = {f.lower() for f in tkfont.families()}
    except Exception:  # noqa: BLE001
        return fallback
    for name in candidates:
        if name.lower() in have:
            return name
    return fallback


def fmt_ts(ts) -> str:
    if not ts or ts < 0:
        return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except (OSError, ValueError):
        return "—"


def stars(rarity) -> str:
    return "★" * (int(rarity) + 1) if isinstance(rarity, int) and rarity >= 0 else "?"


def fmt_dur(sec) -> str:
    if sec is None or sec < 0:
        return "—"
    sec = int(sec)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m = sec // 60
    return (f"{d}天" if d else "") + f"{h}时{m}分"


def hex_to_colorref(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def round_rect(cv: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [
        x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y1 + r, x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2,
        x2 - r, y2, x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
        x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1, x1 + r, y1,
    ]
    return cv.create_polygon(pts, smooth=True, **kw)


DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR, DWMWA_USE_IMMERSIVE_DARK_MODE = 35, 36, 20


class ToggleGroup(ctk.CTkFrame):
    """自绘单选按钮组（CTkSegmentedButton 选中态文字会和底色撞色，弃用）。"""

    def __init__(self, master, values, variable, command=None, selected=None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.values = list(values)
        self.variable = variable
        self.command = command
        self.sel = selected or (pair("primary"), pair("primary_hover"), "#FFFFFF")
        self.buttons: dict[str, ctk.CTkButton] = {}
        self.font = ctk.CTkFont(FONT, 12)
        for i, v in enumerate(self.values):
            b = ctk.CTkButton(self, text=v, width=self.font.measure(v) + 30, height=32,
                              corner_radius=9, font=self.font,
                              command=lambda v=v: self.set(v))
            b.pack(side="left", padx=(0 if i == 0 else 6, 0))
            self.buttons[v] = b
        self._restyle()

    def _restyle(self):
        cur = self.variable.get()
        sel_fg, sel_hover, sel_text = self.sel
        for v, b in self.buttons.items():
            if v == cur:
                b.configure(fg_color=sel_fg, hover_color=sel_hover, text_color=sel_text)
            else:
                b.configure(fg_color=pair("secondary"), hover_color=pair("secondary_hover"),
                            text_color=pair("text"))

    def set(self, value: str):
        if value not in self.buttons:
            return
        self.variable.set(value)
        self._restyle()
        if self.command:
            self.command(value)

    def get(self) -> str:
        return self.variable.get()


class HintIcon(ctk.CTkLabel):
    """圆圈 i，悬停弹说明气泡（CustomTkinter 无 tooltip，用 overrideredirect Toplevel）。"""

    def __init__(self, master, text: str, size: int = 18, **kw):
        kw.setdefault("width", size)
        kw.setdefault("height", size)
        kw.setdefault("corner_radius", size // 2)
        kw.setdefault("font", ctk.CTkFont(FONT, 11, "bold"))
        kw.setdefault("fg_color", pair("secondary"))
        kw.setdefault("text_color", pair("muted"))
        super().__init__(master, text="i", **kw)
        self.hint_text = text
        self._tip: tk.Toplevel | None = None
        self.bind("<Enter>", self._pop)
        self.bind("<Leave>", self._drop)
        self.bind("<Button-1>", self._pop)

    def _pop(self, _evt=None):
        self._drop()
        dark = ctk.get_appearance_mode().lower() == "dark"
        bg = "#20252C" if dark else "#FFFFFF"
        fg = "#D7DEE7" if dark else "#2F4858"
        bd = "#3E4A56" if dark else "#C9D3DE"
        outside = "#16191E" if dark else "#E9EDF2"
        try:
            scale = ctk.ScalingTracker.get_widget_scaling(self) or 1.0
        except Exception:  # noqa: BLE001
            scale = 1.0

        def px(v):
            return max(1, int(round(v * scale)))

        tip = tk.Toplevel(self)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg=outside)
        cv = tk.Canvas(tip, bg=outside, highlightthickness=0, bd=0)
        cv.pack()
        label = tk.Label(cv, text=self.hint_text, justify="left", anchor="nw",
                         bg=bg, fg=fg, bd=0, highlightthickness=0,
                         wraplength=px(340), font=(FONT, -px(12)))
        label.update_idletasks()
        lw, lh = label.winfo_reqwidth(), label.winfo_reqheight()
        m, r = px(14), px(10)
        cv.configure(width=lw + m * 2, height=lh + m * 2)
        round_rect(cv, 0.5, 0.5, lw + m * 2 - 0.5, lh + m * 2 - 0.5, r,
                   fill=bg, outline=bd, width=max(1, px(1)))
        cv.create_window(m, m, anchor="nw", window=label)
        tip.update_idletasks()
        w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
        x = self.winfo_rootx() + self.winfo_width() + px(8)
        y = self.winfo_rooty() - px(8)
        x = min(x, tip.winfo_screenwidth() - w - px(12))
        y = min(y, tip.winfo_screenheight() - h - px(12))
        tip.geometry(f"+{max(px(8), x)}+{max(px(8), y)}")
        self._tip = tip

    def _drop(self, _evt=None):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._tip = None


class Card(ctk.CTkFrame):
    def __init__(self, master, title: str, **kw):
        kw.setdefault("fg_color", pair("card"))
        kw.setdefault("corner_radius", 12)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", pair("border"))
        super().__init__(master, **kw)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(head, text=title, font=ctk.CTkFont(FONT, 12, "bold"),
                     text_color=pair("primary"), anchor="w", height=20).pack(side="left")


class MultiChips(ctk.CTkFrame):
    """一排可多选的标签（筛选用）。空选 = 不筛选。"""

    def __init__(self, master, items, selected=None, command=None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.command = command
        self.font = ctk.CTkFont(FONT, 12)
        self.vars: dict = {}
        self.btns: dict = {}
        sel = set(selected or ())
        for label, value in items:
            var = ctk.BooleanVar(value=value in sel)
            b = ctk.CTkButton(self, text=label, width=self.font.measure(label) + 24, height=28,
                              corner_radius=8, font=self.font,
                              command=lambda v=value: self.toggle(v))
            b.pack(side="left", padx=(0, 5))
            self.vars[value] = var
            self.btns[value] = b
        self._restyle()

    def toggle(self, value):
        self.vars[value].set(not self.vars[value].get())
        self._restyle()
        if self.command:
            self.command()

    def selected(self) -> set:
        return {v for v, var in self.vars.items() if var.get()}

    def clear(self):
        for var in self.vars.values():
            var.set(False)
        self._restyle()

    def _restyle(self):
        for v, var in self.vars.items():
            b = self.btns[v]
            if var.get():
                b.configure(fg_color=pair("primary"), hover_color=pair("primary_hover"),
                            text_color="#FFFFFF")
            else:
                b.configure(fg_color=pair("secondary"), hover_color=pair("secondary_hover"),
                            text_color=pair("text"))


class App(ctk.CTk):
    timeout = 20

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        global FONT, MONO
        FONT = pick_font(FONT_CANDIDATES, FONT)
        MONO = pick_font(MONO_CANDIDATES, MONO)

        self.title("明日方舟 · 助手")
        self.configure(fg_color=pair("page"))
        self._fit_geometry(1140, 840)
        self.minsize(940, 620)

        cfg = load_settings()
        self.phone = ctk.StringVar(value=cfg.get("phone") or "")
        self.password = ctk.StringVar(value="")
        self.code = ctk.StringVar(value="")
        self.login_mode = ctk.StringVar(value=cfg.get("login_mode") or "验证码")
        self.appearance = ctk.StringVar(value=cfg.get("appearance") or "跟随系统")
        self.role_var = ctk.StringVar(value="")
        self.sort_key = ctk.StringVar(value="星级")
        self.sort_order = ctk.StringVar(value="降序")

        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self._last_mode = ""
        self.data = None
        self.binding: list[dict] = []
        self.roles: dict[str, dict] = {}
        self._busy = False

        self._build()
        self._apply_appearance(self.appearance.get())
        self._restyle_for_theme()
        self._apply_saved_cred()
        self.after(100, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- 窗口 ----------------
    def _screen_size(self):
        if sys.platform.startswith("win"):
            try:
                return (ctypes.windll.user32.GetSystemMetrics(0),
                        ctypes.windll.user32.GetSystemMetrics(1))
            except Exception:  # noqa: BLE001
                pass
        return self.winfo_screenwidth(), self.winfo_screenheight()

    def _fit_geometry(self, want_w, want_h):
        try:
            sw, sh = self._screen_size()
            scale = ctk.ScalingTracker.get_widget_scaling(self) or 1.0
            avail_w = int(sw / scale) - 40
            avail_h = int(sh / scale) - 110
            want_w = max(900, min(want_w, avail_w))
            want_h = max(560, min(want_h, avail_h))
            x = max(0, (avail_w - want_w) // 2) + 20
            y = max(0, (avail_h - want_h) // 2) + 20
            self.geometry(f"{want_w}x{want_h}+{x}+{y}")
        except Exception:  # noqa: BLE001
            self.geometry(f"{want_w}x{want_h}")

    def _apply_titlebar(self):
        if not sys.platform.startswith("win"):
            return
        try:
            dark = 1 if ctk.get_appearance_mode().lower() == "dark" else 0
            pal = DARK if dark else LIGHT
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            dwm = ctypes.windll.dwmapi
            for attr, color in ((DWMWA_USE_IMMERSIVE_DARK_MODE, dark),
                                (DWMWA_CAPTION_COLOR, hex_to_colorref(pal["caption"])),
                                (DWMWA_TEXT_COLOR, hex_to_colorref(pal["caption_text"]))):
                v = ctypes.c_int(color)
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        except Exception:  # noqa: BLE001
            pass

    def _style_log(self):
        mode = "dark" if ctk.get_appearance_mode().lower() == "dark" else "light"
        st = LOG_STYLE[mode]
        self.txt_log.configure(fg_color=st["bg"], text_color=st["fg"], border_color=st["border"])
        for tag, color in st["tags"].items():
            self.txt_log.tag_config(tag, foreground=color)

    def _restyle_for_theme(self):
        self._apply_titlebar()
        self._style_log()
        self._style_oper_tree()
        self.tg_appearance._restyle()
        self.tg_mode._restyle()

    # ---------------- 界面 ----------------
    def _build(self):
        self._build_header()

        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=14, pady=(2, 12))

        left = ctk.CTkFrame(wrap, fg_color="transparent", width=392)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        right = ctk.CTkFrame(wrap, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        self._build_login(left)
        self._build_role(left)
        self._build_options(left)
        self._build_tools(left)
        self._build_board(right)
        self._build_log(right)
        self._build_actions(self)

    def _build_header(self):
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(12, 4))
        left = ctk.CTkFrame(head, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text="明日方舟 · 助手", font=ctk.CTkFont(FONT, 21, "bold"),
                     text_color=pair("text"), anchor="w", height=28).pack(anchor="w")
        ctk.CTkLabel(left, text="用鹰角通行证登录，拉取 养成 / 基建 / 公招 / 剿灭 / 肉鸽 / 签到 —— 只读自己账号",
                     font=ctk.CTkFont(FONT, 12), text_color=pair("muted"), anchor="w",
                     height=18).pack(anchor="w")
        self.tg_appearance = ToggleGroup(
            head, values=["跟随系统", "浅色", "深色"], variable=self.appearance,
            command=self._on_appearance,
            selected=(pair("text"), pair("secondary_hover"), ("#FFFFFF", "#16191E")),
        )
        self.tg_appearance.pack(side="right", padx=(10, 0))

    def _build_login(self, parent):
        card = Card(parent, "① 账号登录")
        card.pack(fill="x", pady=(6, 8))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(8, 4))
        ctk.CTkLabel(row, text="手机号", font=ctk.CTkFont(FONT, 12), text_color=pair("muted"),
                     height=32, width=52, anchor="w").pack(side="left")
        self.phone_entry = ctk.CTkEntry(row, textvariable=self.phone, height=32, corner_radius=9,
                     border_width=1, border_color=pair("input_border"), fg_color=pair("input"),
                     text_color=pair("text"), font=ctk.CTkFont(FONT, 12),
                     placeholder_text="手机号")
        self.phone_entry.pack(side="left", fill="x", expand=True)
        self.phone_entry.bind("<Return>", lambda e: self.login())

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(row2, text="方式", font=ctk.CTkFont(FONT, 12), text_color=pair("muted"),
                     height=32, width=52, anchor="w").pack(side="left")
        self.tg_mode = ToggleGroup(row2, values=["验证码", "密码"], variable=self.login_mode,
                                   command=self._on_mode)
        self.tg_mode.pack(side="left")
        HintIcon(row2, LOGIN_HINT).pack(side="left", padx=(8, 0))

        row3 = ctk.CTkFrame(card, fg_color="transparent")
        row3.pack(fill="x", padx=14, pady=(0, 6))
        self.pw_entry = ctk.CTkEntry(row3, textvariable=self.password, height=32, corner_radius=9,
                                     border_width=1, border_color=pair("input_border"),
                                     fg_color=pair("input"), text_color=pair("text"),
                                     font=ctk.CTkFont(FONT, 12), placeholder_text="密码", show="*")
        self.code_entry = ctk.CTkEntry(row3, textvariable=self.code, height=32, corner_radius=9,
                                       border_width=1, border_color=pair("input_border"),
                                       fg_color=pair("input"), text_color=pair("text"),
                                       font=ctk.CTkFont(FONT, 12), placeholder_text="验证码")
        self.pw_entry.bind("<Return>", lambda e: self.login())
        self.code_entry.bind("<Return>", lambda e: self.login())
        self.btn_inline_login = ctk.CTkButton(
            row3, text="登录", width=74, height=32, corner_radius=9,
            font=ctk.CTkFont(FONT, 12), fg_color=pair("primary"),
            hover_color=pair("primary_hover"), text_color="#FFFFFF", command=self.login)

        self.send_row = ctk.CTkFrame(card, fg_color="transparent")
        self.btn_send = self._btn(self.send_row, "发送验证码", self.send_code, width=96)
        self.btn_send.pack(side="left")
        ctk.CTkLabel(self.send_row, text="验证码会发到上面的手机号", font=ctk.CTkFont(FONT, 11),
                     text_color=pair("muted")).pack(side="left", padx=8)
        self._on_mode(self.login_mode.get())

    def _build_role(self, parent):
        card = Card(parent, "② 账号信息")
        card.pack(fill="x", pady=8)
        self.lbl_acct = ctk.CTkLabel(card, text="未登录", anchor="w", justify="left",
                                     font=ctk.CTkFont(FONT, 12), text_color=pair("muted"))
        self.lbl_acct.pack(fill="x", padx=14, pady=(8, 4))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(row, text="角色", font=ctk.CTkFont(FONT, 12), text_color=pair("muted"),
                     width=44, anchor="w", height=32).pack(side="left")
        self.role_menu = ctk.CTkOptionMenu(
            row, variable=self.role_var, values=["—"], width=200, height=32, corner_radius=9,
            font=ctk.CTkFont(FONT, 12), fg_color=pair("secondary"),
            button_color=pair("secondary_hover"), button_hover_color=pair("border"),
            text_color=pair("text"), dropdown_fg_color=pair("card"),
            dropdown_hover_color=pair("secondary"), dropdown_text_color=pair("text"),
            command=self._on_role)
        self.role_menu.pack(side="left")

    def _build_options(self, parent):
        card = Card(parent, "③ 选项")
        card.pack(fill="x", pady=8)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(8, 4))
        self.remember = ctk.CTkSwitch(
            row, text="记住手机号", font=ctk.CTkFont(FONT, 12), text_color=pair("text"),
            progress_color=pair("primary"), fg_color=pair("input_border"),
            button_color=("#FFFFFF", "#E4EAF0"), button_hover_color=("#FFFFFF", "#FFFFFF"))
        if load_settings().get("remember", True):
            self.remember.select()
        self.remember.pack(side="left")
        HintIcon(row, CRED_HINT).pack(side="left", padx=(8, 0))
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=(0, 12))
        self._btn(row2, "载入样例数据", self.load_fixture, width=124).pack(side="left")
        ctk.CTkLabel(row2, text="（无需账号，仅预览界面）", font=ctk.CTkFont(FONT, 11),
                     text_color=pair("muted")).pack(side="left", padx=8)

    def _build_tools(self, parent):
        card = Card(parent, "④ 快捷工具")
        card.pack(fill="x", pady=8)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(8, 4))
        self._btn(row, "启动游戏", self._lc_start_game, width=112).pack(side="left", padx=(0, 6))
        self._btn(row, "打开 MAA", self._lc_open_maa, width=112).pack(side="left", padx=6)
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=(0, 12))
        self._btn(row2, "生成汇总网页", self._lc_build_site, width=118).pack(side="left", padx=(0, 6))
        self._btn(row2, "打开汇总网页", self._lc_open_site, width=118).pack(side="left", padx=6)
        ctk.CTkLabel(card, text="生成汇总网页 = 把本周计划/每日安排/上线建议/培养进度/周报\n"
                                "渲染成一个单页站点（scheduling/报告/汇总.html）；\n"
                                "打开汇总网页 = 起本地后端并浏览器打开它。",
                     font=ctk.CTkFont(FONT, 11), text_color=pair("muted"),
                     justify="left", anchor="w").pack(fill="x", padx=14, pady=(0, 10))

    def _build_board(self, parent):
        card = Card(parent, "⑤ 看板")
        card.pack(fill="both", expand=True, pady=8)
        self.board = ctk.CTkTabview(
            card, fg_color=pair("card"), border_width=0,
            segmented_button_fg_color=pair("secondary"),
            segmented_button_selected_color=pair("primary"),
            segmented_button_selected_hover_color=pair("primary_hover"),
            segmented_button_unselected_color=pair("secondary"),
            segmented_button_unselected_hover_color=pair("secondary_hover"),
            text_color=pair("text"), command=self._on_tab_change)
        self.board.pack(fill="both", expand=True, padx=10, pady=(6, 12))
        self.tabs_frame: dict[str, ctk.CTkFrame] = {}
        for name in TABS:
            self.board.add(name)
            if name == "干员":
                f = ctk.CTkFrame(self.board.tab(name), fg_color=pair("card"))
            else:
                f = ctk.CTkScrollableFrame(self.board.tab(name), fg_color=pair("card"),
                                           label_fg_color=pair("card"))
            f.pack(fill="both", expand=True)
            self.tabs_frame[name] = f
        self._placeholder("未登录 —— 填手机号登录（或点「载入样例数据」预览）。")
        self._build_recruit_tool(self.tabs_frame["公招"])
        self._build_longcao(self.tabs_frame["长草"])

    def _build_log(self, parent):
        card = Card(parent, "⑥ 日志")
        card.pack(fill="x", pady=(8, 0))
        self.txt_log = ctk.CTkTextbox(card, height=118, corner_radius=9, border_width=1,
                                      border_color=pair("border"), fg_color=pair("card"),
                                      text_color=pair("text"), font=ctk.CTkFont(MONO, 12),
                                      wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=14, pady=(8, 12))
        self.txt_log.configure(state="disabled")
        self._style_log()

    def _build_actions(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(10, 8), padx=14)
        self.btn_refresh = ctk.CTkButton(
            row, text="刷新数据", width=112, height=40, corner_radius=11,
            font=ctk.CTkFont(FONT, 14, "bold"), fg_color=pair("primary"),
            hover_color=pair("primary_hover"), text_color="#FFFFFF", command=self.refresh)
        self.btn_refresh.pack(side="left")
        self.btn_checkin = self._btn(row, "每日签到", self.checkin, width=110, height=40)
        self.btn_checkin.pack(side="left", padx=10)
        self.pb = ctk.CTkProgressBar(row, height=8, corner_radius=4, fg_color=pair("track"),
                                     progress_color=pair("track"))
        self.pb.set(0)
        self.pb.pack(side="left", fill="x", expand=True, padx=(6, 12))
        self.lbl = ctk.CTkLabel(row, text="就绪", width=140, anchor="e",
                                font=ctk.CTkFont(FONT, 13), text_color=pair("muted"), height=40)
        self.lbl.pack(side="left")

    def _btn(self, master, text, command, width=100, **kw):
        kw.setdefault("height", 32)
        kw.setdefault("corner_radius", 9)
        kw.setdefault("font", ctk.CTkFont(FONT, 12))
        return ctk.CTkButton(master, text=text, width=width, command=command,
                             fg_color=pair("secondary"), hover_color=pair("secondary_hover"),
                             text_color=pair("text"), text_color_disabled=pair("muted"), **kw)

    # ---------------- 主题 ----------------
    def _apply_appearance(self, choice):
        ctk.set_appearance_mode(
            {"跟随系统": "system", "浅色": "light", "深色": "dark"}.get(choice, "system"))

    def _on_appearance(self, choice):
        self._apply_appearance(choice)
        self.after(60, self._restyle_for_theme)

    def _on_mode(self, mode):
        for w in (self.pw_entry, self.code_entry, self.btn_inline_login):
            w.pack_forget()
        if mode == "密码":
            self.pw_entry.pack(side="left", fill="x", expand=True, padx=(52, 6))
            self.send_row.pack_forget()
        else:
            self.code_entry.pack(side="left", fill="x", expand=True, padx=(52, 6))
            self.send_row.pack(fill="x", padx=14, pady=(0, 12))
        self.btn_inline_login.pack(side="left")

    def _on_role(self, label):
        uid = self.roles.get(label, {}).get("uid")
        if uid and self._has_cred():
            self._start_fetch(uid)

    # ---------------- 凭证 ----------------
    def _has_cred(self) -> bool:
        return bool(core.load_config().get("cred"))

    def _apply_saved_cred(self):
        cfg = core.load_config()
        if cfg.get("cred"):
            self.log("发现本机已保存的凭证，点「刷新数据」直接拉取。", "dim")
            self.lbl_acct.configure(text="已保存凭证（未校验）", text_color=pair("muted"))

    # ---------------- 交互 ----------------
    def _run_worker(self, fn):
        if self._busy:
            self.log("正在忙，等当前任务结束。", "dim")
            return
        self._busy = True
        self._set_busy(True)

        def target():
            try:
                fn()
            except core.SklandError as e:
                self.q.put(("err", str(e)))
                return
            except Exception as e:  # noqa: BLE001
                import traceback

                self.q.put(("log", ("内部错误: " + traceback.format_exc(), "err")))
                self.q.put(("err", repr(e)))
                return
            self.q.put(("done", None))

        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def _set_busy(self, busy):
        self.btn_refresh.configure(state="disabled" if busy else "normal")
        self.btn_checkin.configure(state="disabled" if busy else "normal")
        self.lbl.configure(text="处理中…" if busy else "就绪", text_color=pair("muted"))
        self.pb.configure(progress_color=pair("primary") if busy else pair("track"))
        if busy:
            self.pb.start()
        else:
            self.pb.stop()
            self.pb.set(0)

    def login(self):
        phone = self.phone.get().strip()
        mode = self.login_mode.get()
        secret = (self.password.get() if mode == "密码" else self.code.get()).strip()
        if not phone or not secret:
            messagebox.showwarning("缺信息", "手机号和密码/验证码都要填。")
            return
        self.log(f"\n开始登录（{mode}）：{phone[:3]}****", "head")

        def work():
            if mode == "密码":
                token = core.token_by_phone_password(phone, secret)
            else:
                token = core.token_by_phone_code(phone, secret)
            cred, sign_token = core.cred_from_token(token)
            core.save_config(cred, token=sign_token)
            self.q.put(("log", ("登录成功，凭证已保存到 ~/.arknights_skland.json", "ok")))
            chars = core.binding(cred, sign_token)
            self.q.put(("binding", chars))
            if chars:
                self._fetch_into_queue(cred, sign_token, chars[0]["uid"])

        self._run_worker(work)

    def send_code(self):
        phone = self.phone.get().strip()
        if not phone:
            messagebox.showwarning("缺信息", "先填手机号。")
            return

        def work():
            core.send_phone_code(phone)
            self.q.put(("log", (f"验证码已发送到 {phone[:3]}****{phone[-4:]}，请查收", "ok")))

        self._run_worker(work)

    def refresh(self):
        cfg = core.load_config()
        if not cfg.get("cred"):
            messagebox.showinfo("未登录", "先登录，或点「载入样例数据」预览界面。")
            return
        uid = cfg.get("uid") or (self.binding[0]["uid"] if self.binding else None)
        if not uid:
            try:
                roles = core.binding(cfg["cred"], cfg.get("token"))
                uid = roles[0]["uid"] if roles else None
                if uid:
                    core.save_config(uid=uid)
            except (core.SklandError, IndexError):
                uid = None
        if not uid:
            self.log("没找到绑定角色（uid 为空），先登录一次。", "err")
            return
        self._start_fetch(uid)

    def _start_fetch(self, uid):
        cfg = core.load_config()
        self.log("\n拉取账号数据…", "head")

        def work():
            cred, token = cfg["cred"], cfg.get("token")
            try:                     # sign_token 会话级、易过期 → 每次拉取前先续期
                token = core.refresh_token(cred)
                core.save_config(cred, token=token)
            except Exception as e:   # noqa: BLE001
                self.q.put(("log", ("续期失败（退回旧 token 试）：%r" % e, "err")))
            self._fetch_into_queue(cred, token, uid)

        self._run_worker(work)

    def _fetch_into_queue(self, cred, token, uid):
        info = core.player_info(cred, uid, token)
        attendance = None
        try:
            attendance = core.attendance_status(cred, uid, token)
        except core.SklandError:
            pass
        self.q.put(("board", {"info": info, "attendance": attendance, "uid": uid}))

    def checkin(self):
        cfg = core.load_config()
        if not cfg.get("cred") or not cfg.get("uid"):
            messagebox.showinfo("未登录", "先登录再签到。")
            return

        def work():
            cred, token = cfg["cred"], cfg.get("token")
            try:                     # 签到同样先续期
                token = core.refresh_token(cred)
                core.save_config(cred, token=token)
            except Exception:        # noqa: BLE001
                pass
            awards = core.do_checkin(cred, cfg["uid"], token)
            if awards:
                txt = "；".join(f"{a.get('resource', {}).get('name')} x{a.get('count')}"
                                for a in awards)
            else:
                txt = "今日已签到或无奖励"
            self.q.put(("log", (f"签到：{txt}", "ok")))

        self._run_worker(work)

    def load_fixture(self):
        if not os.path.exists(FIXTURE):
            messagebox.showinfo("没有样例", "找不到样例文件：\n" + FIXTURE)
            return
        with open(FIXTURE, encoding="utf-8") as f:
            raw = json.load(f)
        info = raw.get("data", raw)
        self._render(info, attendance=None)
        self.lbl_acct.configure(text="样例数据（阿米娅/凯尔希那位的账号）", text_color=pair("muted"))
        self.log("已载入样例数据 —— 仅界面预览，不代表你的账号。", "ok")

    # ---------------- 队列泵 ----------------
    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(payload[0], payload[1])
                elif kind == "binding":
                    self._on_binding(payload)
                elif kind == "board":
                    self._on_board(payload)
                elif kind == "done":
                    self._busy = False
                    self._set_busy(False)
                elif kind == "err":
                    self._busy = False
                    self._set_busy(False)
                    self.log("出错：" + payload, "err")
                    self.lbl.configure(text="出错", text_color=pair("primary"))
        except queue.Empty:
            pass
        mode = ctk.get_appearance_mode().lower()
        if mode != self._last_mode:
            self._last_mode = mode
            self._restyle_for_theme()
        self.after(100, self._drain)

    def _on_binding(self, chars):
        self.binding = chars
        self.roles = {}
        labels = []
        for c in chars:
            label = f"{c.get('nickName')}（{c.get('channelName')}）"
            self.roles[label] = c
            labels.append(label)
        if labels:
            self.role_menu.configure(values=labels)
            self.role_var.set(labels[0])
            self.role_menu.set(labels[0])
        if chars:
            core.save_config(uid=chars[0]["uid"])
        self.log(f"绑定角色 {len(chars)} 个：" + "、".join(labels or ["无"]), "dim")

    def _on_board(self, payload):
        info = payload.get("info")
        if not info:
            self.log("没有取到玩家数据。", "err")
            return
        s = info.get("status") or {}
        uid = payload.get("uid")
        self.lbl_acct.configure(
            text=f"昵称：{s.get('name', '—')}　ID：{uid}\n等级：Lv{s.get('level', '—')}　"
                 f"干员：{s.get('charCnt', '—')}",
            text_color=pair("text"))
        self._render(info, attendance=payload.get("attendance"))
        self.log(f"数据已更新（{s.get('name', '')} Lv{s.get('level', '')}）", "ok")
        self.save_gui_settings()

    # ---------------- 渲染 ----------------
    def _placeholder(self, text):
        for name in TABS:
            if name in ("公招", "长草"):
                continue  # 这两块有独立入口/工具，别被占位清掉
            f = self.tabs_frame[name]
            self._clear(f)
            ctk.CTkLabel(f, text=text, text_color=pair("muted")).pack(padx=12, pady=20)

    @staticmethod
    def _clear(frame):
        for w in frame.winfo_children():
            w.destroy()

    def _head(self, frame, text):
        ctk.CTkLabel(frame, text=text, font=ctk.CTkFont(FONT, 14, "bold"),
                     text_color=pair("primary"), anchor="w").pack(fill="x", padx=8, pady=(12, 4))

    def _kv(self, frame, key, val, keyw=130):
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=1)
        ctk.CTkLabel(row, text=key, width=keyw, anchor="w", font=ctk.CTkFont(FONT, 12),
                     text_color=pair("muted")).pack(side="left")
        ctk.CTkLabel(row, text=str(val), anchor="w", font=ctk.CTkFont(FONT, 12),
                     text_color=pair("text")).pack(side="left")

    def _render(self, data, attendance=None):
        self.data = data
        s = data.get("status") or {}
        chars = data.get("chars") or []
        info_map = data.get("charInfoMap") or {}
        self._render_overview(s, chars, data)
        self._render_opers(chars, info_map)
        self._render_base(data.get("building") or {}, info_map)
        self._render_recruit(data.get("recruit") or [])
        self._render_records(data)
        self._render_checkin(attendance)
        self._render_raw(data)

    def _render_overview(self, s, chars, data):
        f = self.tabs_frame["概览"]
        self._clear(f)
        self._head(f, "博士档案")
        self._kv(f, "昵称", s.get("name", "—"))
        self._kv(f, "等级", f"Lv{s.get('level', '—')}")
        ap = s.get("ap") or {}
        self._kv(f, "理智", f"{ap.get('current', '—')} / {ap.get('max', '—')}")
        char_cnt = s.get("charCnt") or len(chars)
        skin_cnt = s.get("skinCnt") or len(data.get("skins") or [])
        furn = s.get("furnitureCnt") or (data.get("building") or {}).get("furniture") or 0
        if isinstance(furn, dict):
            furn = furn.get("total", 0)
        self._kv(f, "干员数", char_cnt)
        self._kv(f, "时装 / 家具", f"{skin_cnt} / {furn}")
        self._kv(f, "注册", fmt_ts(s.get("registerTs")))
        self._kv(f, "上次在线", fmt_ts(s.get("lastOnlineTs")))
        self._kv(f, "主线进度", s.get("mainStageProgress") or "（已通关或未取到）")
        self._head(f, "助战干员")
        assist = data.get("assistChars") or []
        if not assist:
            self._kv(f, "—", "无")
        info_map = data.get("charInfoMap") or {}
        for a in assist:
            cid = a.get("charId", "")
            nm = (info_map.get(cid) or {}).get("name", cid)
            self._kv(f, nm, f"{ELITE.get(a.get('evolvePhase'), '')} Lv{a.get('level')} "
                            f"潜{a.get('potentialRank')} 专{a.get('specializeLevel', 0)}")

    def _render_opers(self, chars, info_map):
        self._opers_chars = chars
        self._opers_map = info_map
        f = self.tabs_frame["干员"]
        self._clear(f)
        self.oper_summary = ctk.CTkLabel(f, text="", anchor="w", font=ctk.CTkFont(FONT, 12),
                                         text_color=pair("text"))
        self.oper_summary.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(f, text="技能等级 1–7 由三技能共享；专精列依次为 S1/S2/S3 各自等级",
                     anchor="w", font=ctk.CTkFont(FONT, 11), text_color=pair("muted")
                     ).pack(fill="x", padx=12, pady=(0, 2))
        self._build_oper_controls(f)
        wrap = ctk.CTkFrame(f, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        try:
            scale = ctk.ScalingTracker.get_widget_scaling(self) or 1.0
        except Exception:  # noqa: BLE001
            scale = 1.0

        def colw(base):
            return int(base * scale)

        cols = [("rarity", "星级", colw(42)), ("name", "名称", colw(92)),
                ("prof", "职业", colw(30)), ("lv", "等级", colw(64)),
                ("pot", "潜能", colw(32)), ("skill", "技能", colw(30)),
                ("spec", "专精", colw(50)), ("_pad", "", colw(10))]
        self.oper_tree = ttk.Treeview(wrap, columns=[c[0] for c in cols], show="headings",
                                      style="Oper.Treeview")
        for cid, title, w in cols:
            self.oper_tree.heading(cid, text=title, anchor="w")
            self.oper_tree.column(cid, width=w, minwidth=w, anchor="w",
                                  stretch=(cid == "_pad"))
        vs = ctk.CTkScrollbar(wrap, command=self.oper_tree.yview)
        self.oper_tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.oper_tree.pack(side="left", fill="both", expand=True)
        self._style_oper_tree()
        self._render_oper_list()

    def _build_oper_controls(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(8, 2))

        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text="星级", width=40, anchor="w", font=ctk.CTkFont(FONT, 12),
                     text_color=pair("muted")).pack(side="left")
        self.chips_rarity = MultiChips(row, [(stars(r), r) for r in (5, 4, 3, 2, 1, 0)],
                                       command=self._render_oper_list)
        self.chips_rarity.pack(side="left")

        row2 = ctk.CTkFrame(bar, fg_color="transparent")
        row2.pack(fill="x", pady=2)
        ctk.CTkLabel(row2, text="职业", width=40, anchor="w", font=ctk.CTkFont(FONT, 12),
                     text_color=pair("muted")).pack(side="left")
        self.chips_prof = MultiChips(row2, [(cn, en) for en, cn in PROFESSIONS.items()
                                            if en not in ("TOKEN", "TRAP")],
                                     command=self._render_oper_list)
        self.chips_prof.pack(side="left")

        row3 = ctk.CTkFrame(bar, fg_color="transparent")
        row3.pack(fill="x", pady=2)
        ctk.CTkLabel(row3, text="排序", width=40, anchor="w", font=ctk.CTkFont(FONT, 12),
                     text_color=pair("muted")).pack(side="left")
        ctk.CTkOptionMenu(row3, variable=self.sort_key, values=["星级", "等级", "技能等级"],
                          width=104, height=28, corner_radius=8, font=ctk.CTkFont(FONT, 12),
                          fg_color=pair("secondary"), button_color=pair("secondary_hover"),
                          button_hover_color=pair("border"), text_color=pair("text"),
                          dropdown_fg_color=pair("card"), dropdown_hover_color=pair("secondary"),
                          dropdown_text_color=pair("text"),
                          command=lambda _v: self._render_oper_list()).pack(side="left")
        self.tg_order = ToggleGroup(row3, values=["降序", "升序"], variable=self.sort_order,
                                    command=lambda _v: self._render_oper_list(),
                                    selected=(pair("primary"), pair("primary_hover"), "#FFFFFF"))
        self.tg_order.pack(side="left", padx=(8, 0))
        self._btn(row3, "清空筛选", self._clear_oper_filter, width=84, height=28).pack(
            side="left", padx=(8, 0))

    def _style_oper_tree(self):
        if not getattr(self, "oper_tree", None):
            return
        dark = ctk.get_appearance_mode().lower() == "dark"
        pal = DARK if dark else LIGHT
        try:
            scale = ctk.ScalingTracker.get_widget_scaling(self) or 1.0
        except Exception:  # noqa: BLE001
            scale = 1.0
        px = max(11, int(round(12 * scale)))
        row_h = max(22, int(round(px * 1.95)))
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:  # noqa: BLE001
            pass
        st.configure("Oper.Treeview", background=pal["card"], fieldbackground=pal["card"],
                     foreground=pal["text"], rowheight=row_h, borderwidth=0, font=(FONT, -px))
        st.configure("Oper.Treeview.Heading", background=pal["secondary"], foreground=pal["muted"],
                     font=(FONT, -px), relief="flat")
        st.map("Oper.Treeview", background=[("selected", pal["primary"])],
               foreground=[("selected", "#FFFFFF")])
        st.map("Oper.Treeview.Heading", background=[("active", pal["secondary_hover"])])
        self.oper_tree.tag_configure("odd", background=pal["secondary"])

    def _clear_oper_filter(self):
        self.chips_rarity.clear()
        self.chips_prof.clear()
        self._render_oper_list()

    def _render_oper_list(self):
        info_map, chars = self._opers_map, self._opers_chars

        def info(c):
            return info_map.get(c.get("charId")) or {}

        def rarity(c):
            return info(c).get("rarity", -1)

        rar_sel = self.chips_rarity.selected()
        prof_sel = self.chips_prof.selected()
        flt = [c for c in chars
               if (not rar_sel or rarity(c) in rar_sel)
               and (not prof_sel or info(c).get("profession") in prof_sel)]

        key = self.sort_key.get()
        desc = self.sort_order.get() == "降序"
        if key == "等级":
            sortf = lambda c: (c.get("level", 0), rarity(c), info(c).get("name", ""))  # noqa: E731
        elif key == "技能等级":
            sortf = lambda c: (  # noqa: E731
                c.get("mainSkillLvl", 0),
                sum(s.get("specializeLevel", 0) for s in (c.get("skills") or [])), rarity(c))
        else:
            sortf = lambda c: (rarity(c), c.get("level", 0))  # noqa: E731
        flt.sort(key=sortf, reverse=desc)

        upgraded = sum(1 for c in flt if c.get("evolvePhase", 0) >= 2)
        dist: dict = {}
        for c in flt:
            r = rarity(c)
            dist[r] = dist.get(r, 0) + 1
        dist_txt = "  ".join(f"{stars(r)}{dist[r]}" for r in sorted(dist, reverse=True) if r >= 0)
        self.oper_summary.configure(
            text=f"筛选结果 {len(flt)} / {len(chars)}　精二 {upgraded}　|　{dist_txt}")

        tree = self.oper_tree
        tree.delete(*tree.get_children())
        for i, c in enumerate(flt):
            inf = info(c)
            specs = [s.get("specializeLevel", 0) for s in (c.get("skills") or [])]
            spec_txt = "/".join(str(x) for x in specs) if any(specs) else ""
            r = inf.get("rarity", -1)
            tree.insert("", "end", tags=("odd",) if i % 2 else (), values=(
                f"{r + 1}★" if r >= 0 else "?",
                inf.get("name", c.get("charId", "")),
                PROFESSIONS.get(inf.get("profession", ""), inf.get("profession", "")),
                f"{ELITE.get(c.get('evolvePhase'), '')} Lv{c.get('level')}",
                f"潜{c.get('potentialRank')}",
                f"技{c.get('mainSkillLvl')}",
                spec_txt))

    def _render_base(self, b, info_map):
        f = self.tabs_frame["基建"]
        self._clear(f)
        if not b:
            self._kv(f, "—", "无基建数据")
            return
        groups = [("控制中枢", b.get("control")), ("贸易站", b.get("tradings")),
                  ("制造站", b.get("manufactures")), ("发电站", b.get("powers")),
                  ("宿舍", b.get("dormitories")), ("会客室", b.get("meeting")),
                  ("办公室", b.get("hire")), ("训练室", b.get("training"))]
        for title, slots in groups:
            if not slots:
                continue
            if isinstance(slots, dict):
                slots = [slots]
            self._head(f, title)
            for s in slots:
                names = [(info_map.get(c.get("charId")) or {}).get("name", c.get("charId", ""))
                         for c in s.get("chars") or []]
                lvl = f"Lv{s.get('level')}" if s.get("level") else "—"
                self._kv(f, lvl, "、".join(names) or "空置", keyw=60)
        labor = b.get("labor") or {}
        if labor:
            self._head(f, "无人机")
            self._kv(f, "数量", f"{labor.get('value')}/{labor.get('maxValue')}")
        if b.get("furniture") is not None:
            furn = b.get("furniture")
            if isinstance(furn, dict):
                furn = furn.get("total")
            self._kv(f, "家具件数", furn)

    def _render_recruit(self, rec):
        f = self.tabs_frame["公招"]
        self._clear(f)
        self._head(f, "公开招募 · 4 栏位")
        now = time.time()
        for i, r in enumerate(rec):
            state, finish = r.get("state"), r.get("finishTs", -1)
            if state == 1 and finish and finish > now:
                line = f"进行中，剩余 {fmt_dur(finish - now)}（完成 {fmt_ts(finish)}）"
            elif state == 1:
                line = "已完成，待领取"
            elif state == 0:
                line = "空闲"
            else:
                line = f"状态 {state}"
            self._kv(f, f"栏位 {i + 1}", line, keyw=70)
        hire = (self.data.get("building") or {}).get("hire") or {}
        if hire:
            self._head(f, "办公室")
            self._kv(f, "刷新次数", hire.get("refreshCount", "—"))
            self._kv(f, "下次刷新", fmt_ts(hire.get("completeWorkTime")))
        self._build_recruit_tool(f)

    def _render_records(self, data):
        f = self.tabs_frame["战绩"]
        self._clear(f)
        camp = data.get("campaign") or {}
        self._head(f, "剿灭作战")
        rew = camp.get("reward") or {}
        self._kv(f, "本周合成玉", f"{rew.get('current', '—')} / {rew.get('total', '—')}")
        for rec in camp.get("records") or []:
            self._kv(f, rec.get("campaignId", ""), f"最高击杀 {rec.get('maxKills')}")
        tower = data.get("tower") or {}
        self._head(f, "保全派驻")
        trew = tower.get("reward") or {}
        if trew:
            self._kv(f, "奖励进度", f"{trew.get('current', '—')} / {trew.get('total', '—')}")
        for rec in tower.get("records") or []:
            self._kv(f, rec.get("towerId", ""), json.dumps(rec, ensure_ascii=False)[:80])
        rogue = data.get("rogue") or {}
        self._head(f, "集成战略（肉鸽）")
        for rec in rogue.get("records") or []:
            bank = rec.get("bank") or {}
            self._kv(f, rec.get("rogueId", ""),
                     f"收藏品 {rec.get('relicCnt')} · 存款 {bank.get('current')}/{bank.get('record')}")
        routine = data.get("routine") or {}
        self._head(f, "任务")
        d, w = routine.get("daily") or {}, routine.get("weekly") or {}
        self._kv(f, "每日任务", f"{d.get('current', '—')} / {d.get('total', '—')}")
        self._kv(f, "每周任务", f"{w.get('current', '—')} / {w.get('total', '—')}")

    def _render_checkin(self, attendance):
        f = self.tabs_frame["签到"]
        self._clear(f)
        self._head(f, "每日签到")
        ctk.CTkButton(f, text="执行今日签到", fg_color=pair("primary"),
                      hover_color=pair("primary_hover"), text_color="#FFFFFF",
                      font=ctk.CTkFont(FONT, 13, "bold"), command=self.checkin).pack(
            anchor="w", padx=16, pady=10)
        if not attendance:
            self._kv(f, "状态", "未登录 / 未取到（登录后显示）")
            return
        cal = attendance.get("calendar") or []
        done = sum(1 for c in cal if c.get("done"))
        today = [c for c in cal if c.get("available")]
        self._kv(f, "本月已签", f"{done} 天")
        if today and not today[0].get("done"):
            items = "、".join(f"{c.get('resourceId')}×{c.get('count')}" for c in today)
            self._kv(f, "今日", f"可签到（{items}）")
        elif today:
            self._kv(f, "今日", "已签到")
        else:
            self._kv(f, "今日", "不可签")

    def _render_raw(self, data):
        f = self.tabs_frame["原始 JSON"]
        self._clear(f)
        box = ctk.CTkTextbox(f, font=ctk.CTkFont(MONO, 11))
        box.pack(fill="both", expand=True, padx=6, pady=6)
        box.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))
        box.configure(state="disabled")

    # ---------------- 公招 · 贴词条推荐 ----------------
    def _build_recruit_tool(self, frame):
        self._head(frame, "贴词条 → 推荐")
        self._recruit_tags = ctk.CTkEntry(
            frame, height=32, corner_radius=9, border_width=1,
            border_color=pair("input_border"), fg_color=pair("input"),
            text_color=pair("text"), font=ctk.CTkFont(FONT, 12),
            placeholder_text="高级资深干员 输出 近战位 新手 生存")
        self._recruit_tags.pack(fill="x", padx=14, pady=(2, 4))
        self._recruit_tags.bind("<Return>", lambda e: self._recruit_recommend())
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 4))
        self._btn(row, "推荐", self._recruit_recommend, width=84).pack(side="left")
        ctk.CTkLabel(row, text="（取前 10 个词条组合，优先补图鉴）", font=ctk.CTkFont(FONT, 11),
                     text_color=pair("muted")).pack(side="left", padx=8)
        self._recruit_out = ctk.CTkTextbox(
            frame, height=240, corner_radius=9, border_width=1,
            border_color=pair("border"), fg_color=pair("card"),
            text_color=pair("text"), font=ctk.CTkFont(MONO, 11), wrap="none")
        self._recruit_out.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self._recruit_out.configure(state="disabled")

    def _set_recruit_out(self, text):
        out = getattr(self, "_recruit_out", None)
        if out is None:
            return
        out.configure(state="normal")
        out.delete("1.0", "end")
        out.insert("1.0", text)
        out.configure(state="disabled")

    def _recruit_recommend(self):
        entry = getattr(self, "_recruit_tags", None)
        if entry is None:
            return
        text = entry.get().strip()
        if not text:
            self.log("先在「公招」里贴上词条。", "dim")
            return
        self._set_recruit_out("计算中…（首次会拉取干员箱，稍等）")
        self.log("公招推荐：计算中…", "head")
        tools_dir = str(ROOT / "scheduling" / "tools")

        def work():
            try:
                if tools_dir not in sys.path:
                    sys.path.insert(0, tools_dir)
                from recruit_combo import load_pool, load_owned, recommend, parse_tags_arg
                pool, _all_tags = load_pool()
                owned, src = load_owned()
                tags = parse_tags_arg(text)
                rows = recommend(tags, pool, owned, topn=10)
                lines = [f"owned 来源={src}（{len(owned)} 人）　词条：{'、'.join(tags)}", ""]
                lines.append(f"{'词条组合':<24}{'池':>4}{'未拥有':>6}{'P(新)':>8}{'星级':>8}  未拥有干员")
                lines.append("-" * 82)
                for r in rows:
                    star = f"{r['rare_min']}~{r['rare_max']}"
                    lines.append(
                        f"{'+'.join(r['tags']):<24}{r['size']:>4}{r['unowned']:>6}"
                        f"{r['p_new']:>8.2f}{star:>8}  {'、'.join(r['unowned_names'])}")
                out = "\n".join(lines)
            except Exception as e:  # noqa: BLE001
                import traceback
                out = "推荐失败：" + repr(e) + "\n" + traceback.format_exc()
            self.after(0, lambda: self._set_recruit_out(out))

        threading.Thread(target=work, daemon=True).start()

    # ---------------- 长草 · 一键长草 ----------------
    def _build_longcao(self, frame):
        self._clear(frame)
        self._head(frame, "本周计划（一键长草）")
        bar = ctk.CTkFrame(frame, fg_color="transparent")
        bar.pack(fill="x", padx=8, pady=(2, 8))
        self._btn(bar, "基建换班", self._lc_swap, width=100).pack(side="left", padx=4)
        self._btn(bar, "写 MAA 配置", self._lc_write_maa, width=112).pack(side="left", padx=4)
        self._btn(bar, "直驱跑一键长草", self._lc_run, width=132).pack(side="left", padx=4)
        ctk.CTkLabel(bar, text="（会操作 MAA 与游戏，均需二次确认）",
                     font=ctk.CTkFont(FONT, 11), text_color=pair("muted")).pack(
            side="left", padx=8)
        self.longcao_plan = ctk.CTkFrame(frame, fg_color="transparent")
        self.longcao_plan.pack(fill="both", expand=True, padx=6, pady=(2, 8))
        self._render_longcao()

    def _on_tab_change(self, name=None):
        if name is None:
            try:
                name = self.board.get()
            except Exception:  # noqa: BLE001
                return
        if name == "长草":
            self._render_longcao()

    def _render_longcao(self):
        f = getattr(self, "longcao_plan", None)
        if f is None:
            return
        self._clear(f)
        path = ROOT / "scheduling" / "data" / "weekly_plan.json"
        if not path.exists():
            self._kv(f, "状态", "未生成（找不到 scheduling/data/weekly_plan.json）")
            return
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            self._kv(f, "状态", f"读取失败：{e!r}")
            return
        self._kv(f, "周号", plan.get("week", "—"))
        self._kv(f, "日期范围", plan.get("range", "—"))
        budget = plan.get("budget") or {}
        self._kv(f, "预算", f"自然理智 {budget.get('sanity_natural', '—')} · "
                            f"周药 {budget.get('weekly_potion', '—')} · "
                            f"理智药 {budget.get('meds_available', '—')}")
        self._head(f, "任务")
        for i, t in enumerate(plan.get("tasks") or [], 1):
            p = t.get("params") or {}
            stage = p.get("stage") or p.get("mode") or ""
            mode = p.get("facility") or ""
            if isinstance(mode, list):
                mode = "/".join(str(x) for x in mode)
            parts = [str(t.get("type", ""))]
            if stage:
                parts.append(str(stage))
            if mode:
                parts.append(str(mode))
            if p.get("times") is not None:
                parts.append(f"×{p.get('times')}")
            desc = " · ".join(parts)
            extra = t.get("name") or t.get("note") or ""
            self._kv(f, str(i), desc + (f"　{extra}" if extra else ""), keyw=30)
        try:
            sys.path.insert(0, str(ROOT / "scheduling" / "tools"))
            from plan_util import distribute_daily, weekly_summary, session_advice
            daily = distribute_daily(plan)
            summary = weekly_summary(plan, daily) if daily else None
            advice = session_advice(plan, daily) if daily else []
        except Exception:  # noqa: BLE001
            daily, summary, advice = [], None, []
        if daily:
            self._head(f, "每日安排")
            for d in daily:
                runs = d.get("runs") or {}
                txt = "、".join(f"{k}×{v}" for k, v in runs.items()) or "—"
                if d.get("opens"):
                    txt += "　★新开：" + "、".join(d["opens"])
                txt += f"　（理智 {d.get('sanity', 0)}"
                txt += f"，超上限{d.get('cap')}！" if d.get("over") else ""
                txt += "）"
                self._kv(f, f"{d.get('date', '')} {d.get('dow', '')}", txt, keyw=150)
            if summary:
                s = (f"合计 {summary['total']} / 预算 {summary['avail']}"
                     f"（自然{summary['natural']}+周药{summary['weekly_potion']}）")
                s += f"　缺口 {summary['gap']}（需理智药）" if summary["gap"] else "　够"
                self._kv(f, "周合计", s, keyw=60)
        tr = plan.get("training")
        if tr:
            self._head(f, "培养进度")
            self._kv(f, "目标", "、".join(tr.get("targets", [])), keyw=60)
            self._kv(f, "总缺口", "%s 理智（材料 %s + 龙门币 %s）"
                     % (tr.get("total_sanity"), tr.get("material_sanity"),
                        tr.get("lmd_sanity")), keyw=60)
            weeks = ("（还需约 %s 周）" % tr["need_weeks"]) if tr.get("need_weeks") else ""
            self._kv(f, "本周投", "%s 理智%s" % (tr.get("week_sanity"), weeks), keyw=60)
            for g in (tr.get("top_gaps") or [])[:8]:
                self._kv(f, "  " + str(g.get("name")),
                         "需 %s（库存抵 %s）→ %s 理智"
                         % (g.get("qty"), g.get("stock", 0), g.get("sanity")), keyw=90)
        notes = (plan.get("rationale") or {}).get("notes") or []
        if notes:
            self._head(f, "说明")
            for n in notes:
                self._kv(f, "·", str(n), keyw=20)
        side = plan.get("side") or []
        if side:
            self._head(f, "附脚本")
            for s in side:
                self._kv(f, str(s.get("when", "—")), str(s.get("script", "")), keyw=110)

    def _popen_log(self, args, title, done_msg=None):
        self.log(f"{title}：启动 {' '.join(str(a) for a in args)}", "head")
        try:
            proc = subprocess.Popen(
                args, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            self.log(f"{title} 启动失败：{e!r}", "err")
            return None

        def reader():
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        self.after(0, self.log, line, "dim")
            except Exception:  # noqa: BLE001
                pass
            rc = proc.wait()
            tag = "ok" if rc == 0 else "err"
            if rc == 0 and done_msg:
                self.after(0, self.log, done_msg, "ok")
            else:
                self.after(0, self.log, f"{title} 结束（退出码 {rc}）", tag)

        threading.Thread(target=reader, daemon=True).start()
        return proc

    @staticmethod
    def _port_open(host, port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                return s.connect_ex((host, port)) == 0
        except Exception:  # noqa: BLE001
            return False

    def _lc_build_site(self):
        self._popen_log([sys.executable, str(ROOT / "scheduling" / "tools" / "build_site.py")],
                        "生成汇总网页", done_msg="网页已生成")

    def _lc_open_maa(self):
        exe = pathlib.Path(r"C:\MAA\MAA.exe")
        if not exe.exists():
            self.log(f"找不到 MAA：{exe}", "err")
            return
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
            self.log("已启动 MAA（需要 MAA 干活时用）", "ok")
        except Exception as e:  # noqa: BLE001
            self.log(f"启动 MAA 失败：{e!r}", "err")

    def _lc_start_game(self):
        self._popen_log(
            [sys.executable, str(ROOT / "scripts" / "maa-week" / "maa_week.py"), "startup"],
            "启动游戏")

    def _lc_open_site(self):
        url = "http://127.0.0.1:8787/"
        if not self._port_open("127.0.0.1", 8787):
            self._popen_log(
                [sys.executable, str(ROOT / "scheduling" / "tools" / "site_server.py")],
                "汇总网页服务")
            time.sleep(0.8)
        webbrowser.open(url)
        self.log(f"已打开汇总网页 {url}", "ok")

    def _lc_swap(self):
        """基建换班（收菜+菲亚梅塔+13房切队列）。会操作游戏，需模拟器 + 单客户端。"""
        self._popen_log(
            [sys.executable, str(ROOT / "scripts" / "infrast-rotation" / "infrast_rotation.py"), "all"],
            "基建换班")

    def _lc_read_potion(self):
        self._popen_log(
            [sys.executable, str(ROOT / "scripts" / "sanity-potion" / "sanity_potion.py")],
            "读理智药")

    def _lc_write_maa(self):
        if not messagebox.askyesno(
                "确认写 MAA 配置",
                "这会把 weekly_plan 写进 MAA 的 gui.new.json。\n"
                "请先关闭 MAA，否则改动会被覆盖。\n\n继续？"):
            return
        self._popen_log(
            [sys.executable, str(ROOT / "scripts" / "maa-week" / "maa_week.py"), "write"],
            "写 MAA 配置")

    def _lc_run(self):
        if not messagebox.askyesno(
                "确认直驱跑一键长草",
                "这会真的操作 MAA / 游戏，按本周计划自动执行。\n\n继续？"):
            return
        self._popen_log(
            [sys.executable, str(ROOT / "scripts" / "maa-week" / "maa_week.py"), "run"],
            "直驱跑一键长草")

    # ---------------- 日志 / 设置 ----------------
    def log(self, msg, tag=""):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg + "\n", tag)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def save_gui_settings(self):
        save_settings({"phone": self.phone.get().strip() if self.remember.get() else "",
                       "login_mode": self.login_mode.get(), "appearance": self.appearance.get(),
                       "remember": bool(self.remember.get())})

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel("正在忙", "还有任务在跑，确定退出吗？"):
                return
        self.save_gui_settings()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
