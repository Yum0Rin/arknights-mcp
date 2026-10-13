#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""明日方舟 · 助手 —— Qt (PySide6) + Fluent Design 界面。

流程：**登录 → 拉数据 → 看板**

1. 「账号」页填手机号，选「验证码 / 密码」登录（凭证存 ~/.arknights_skland.json）；
2. 登录后自动拉取本人账号数据：概览 / 干员 / 基建 / 公招 / 抽卡 / 战绩 / 签到；
3. 「刷新数据」重新拉；「样例」用本地样例 JSON 预览界面（不需要账号）。

抽卡记录是个例外：它不是森空岛的接口，而是鹰角官网「用户中心」的寻访记录
（ak.hypergryph.com，见 gacha_client.py），所以只在「抽卡」页按需拉取，
可以「从火狐导入」直接抄浏览器已登录的会话（ff_session.py，免密码），
并在本地留档（~/.arknights_gacha_records.json，只增不删）。

界面用 PySide6 + PySide6-Fluent-Widgets（zhiyiYo/PyQt-Fluent-Widgets，GPL-3.0）：
Mica 窗口 / 左侧 NavigationInterface / Fluent 控件 / 明暗跟随系统。
线程模型沿用旧版：网络请求跑工作线程，结果经 queue 回主线程，QTimer 轮询取。
"""
from __future__ import annotations

import html
import json
import os
import pathlib
import queue
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QSizePolicy,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

import qfluentwidgets as qfw
from qfluentwidgets import (
    FluentIcon as FI, FluentWindow, InfoBar, InfoBarPosition, NavigationItemPosition,
    Theme, qconfig,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ff_session as ffs  # noqa: E402
import gacha_client as gc  # noqa: E402
import skland_client as core  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
SETTINGS = os.path.join(os.path.expanduser("~"), ".arknights_skland_gui.json")
_SAMPLE_REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_player_info.json")
FIXTURE = (_SAMPLE_REPO if os.path.exists(_SAMPLE_REPO)
           else os.path.join(os.environ.get("TEMP", "."), "opencode", "skland-dump.json"))

# ---------------------------------------------------------------- 配色（方舟风：深海蓝 + 金）
# 卡片是 CardWidget 自绘的，所以颜色走这里的调色板，而不是框架主题。
GAME = {
    "dark": {
        "window": "#0A121D", "card": "#121E2E", "border": "#27405F",
        "text": "#E6EDF6", "muted": "#8296AD", "title": "#E3BE63",
        "accent": "#C9973B", "row": "#16243A", "sel": "#2A4566",
        "line": "#1E3350",
    },
    "light": {
        "window": "#F4F2EC", "card": "#FFFFFF", "border": "#DDD3BC",
        "text": "#1B2836", "muted": "#6B7A8C", "title": "#A97C1F",
        "accent": "#B8892B", "row": "#F8F6F0", "sel": "#EADFC4",
        "line": "#E6DECB",
    },
}


def is_dark() -> bool:
    try:
        return bool(qfw.isDarkTheme())
    except Exception:  # noqa: BLE001
        return qconfig.theme != Theme.LIGHT


def pal() -> dict:
    return GAME["dark"] if is_dark() else GAME["light"]


# 需要跟随主题重上色的控件：(控件, 调色板键)
_COLORED: list = []


def register_color(widget, key: str):
    _COLORED.append((widget, key))
    try:
        widget.setTextColor(QColor(pal()[key]))
    except Exception:  # noqa: BLE001
        pass
    return widget


def refresh_theme_colors():
    """主题切换后重新上色；已销毁的控件会抛 RuntimeError，顺手剔除。"""
    alive = []
    for w, key in _COLORED:
        try:
            w.setTextColor(QColor(pal()[key]))
            alive.append((w, key))
        except RuntimeError:
            pass
    _COLORED[:] = alive

PROFESSIONS = {"PIONEER": "先锋", "WARRIOR": "近卫", "SNIPER": "狙击", "CASTER": "术师",
               "MEDIC": "医疗", "SUPPORT": "辅助", "TANK": "重装", "SPECIAL": "特种",
               "TOKEN": "召唤物", "TRAP": "装置"}
ELITE = {0: "精0", 1: "精1", 2: "精2", 3: "精3"}

LOGIN_HINT = (
    "用「鹰角通行证」登录，和游戏是同一套账号。\n\n"
    "验证码：填手机号 → 发送验证码 → 填码 → 登录。\n"
    "密码：直接填手机号 + 密码。\n\n"
    "登录成功只把凭证存到本机 ~/.arknights_skland.json，不保存密码。"
)


# ---------------------------------------------------------------- 小工具

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


def fmt_ts(ts) -> str:
    if not ts or ts < 0:
        return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except (OSError, ValueError):
        return "—"


def fmt_ts_ms(ms) -> str:
    return fmt_ts((ms or 0) / 1000)


def stars_txt(n) -> str:
    return f"{int(n)}★" if isinstance(n, int) and n > 0 else "?"


def fmt_dur(sec) -> str:
    if sec is None or sec < 0:
        return "—"
    sec = int(sec)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m = sec // 60
    return (f"{d}天" if d else "") + f"{h}时{m}分"


def dt(ts) -> str:                     # 秒级时间戳 → 展示串
    if not ts or ts < 0:
        return "—"
    try:
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except (OSError, ValueError):
        return "—"


def btn(text: str, icon=None, primary: bool = False, parent=None):
    """Fluent 按钮工厂。

    注意签名是 (text, parent, icon) —— 参数顺序写反不会报错、但图标会变成文字，
    所以统一从这里造按钮，别直接 new。
    """
    cls = qfw.PrimaryPushButton if primary else qfw.PushButton
    b = cls(text, parent, icon) if icon is not None else cls(text, parent)
    b.setMinimumHeight(34)
    return b


def note(text: str) -> qfw.CaptionLabel:
    """说明性小字：必须开 wordWrap，否则长句会把页面撑得比视口宽（出现横向滚动）。"""
    lab = qfw.CaptionLabel(text)
    lab.setWordWrap(True)
    return register_color(lab, "muted")


class NumItem(QTableWidgetItem):
    """表格项：显示文本与排序键分离（数字列按数字排，不按字符串）。"""

    def __init__(self, text: str, key):
        super().__init__(text)
        self.key = key

    def __lt__(self, other):  # noqa: D105
        ok = getattr(other, "key", None)
        if ok is None:
            return super().__lt__(other)
        return self.key < ok


# ---------------------------------------------------------------- 基础控件

class GameCard(qfw.CardWidget):
    """方舟风卡片：深海蓝底 + 一条描边（框架的 CardWidget 是自绘的，所以直接覆盖 paintEvent）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBorderRadius(9)

    def paintEvent(self, e):  # noqa: N802
        c = pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2),
                            self.getBorderRadius(), self.getBorderRadius())
        p.fillPath(path, QColor(c["card"]))
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawPath(path)


class Section(GameCard):
    """带标题的卡片容器。"""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(18, 14, 18, 16)
        self.vbox.setSpacing(8)
        if title:
            lab = qfw.StrongBodyLabel(title)
            self.vbox.addWidget(register_color(lab, "title"))

    def add(self, w: QWidget):
        self.vbox.addWidget(w)
        return w

    def row(self) -> QHBoxLayout:
        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.vbox.addWidget(holder)
        return h


class StatTile(GameCard):
    """数字磁贴：大数字 + 说明。"""

    def __init__(self, title: str, value: str = "—", parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(2)
        self.lbl_value = qfw.SubtitleLabel(value)
        f = QFont()
        f.setPixelSize(26)
        f.setBold(True)
        self.lbl_value.setFont(f)
        register_color(self.lbl_value, "title")
        self.lbl_title = qfw.CaptionLabel(title)
        register_color(self.lbl_title, "muted")
        v.addWidget(self.lbl_value)
        v.addWidget(self.lbl_title)

    def set_value(self, text: str):
        self.lbl_value.setText(text)


class Page(qfw.ScrollArea):
    """可滚动页面：外面是 ScrollArea，里面一个透明 QWidget + 竖排布局。"""

    def __init__(self, route: str, parent=None):
        super().__init__(parent)
        self.setObjectName(route)
        self.body = QWidget()
        self.body.setObjectName(route + "Body")
        self.vbox = QVBoxLayout(self.body)
        self.vbox.setContentsMargins(26, 18, 26, 26)
        self.vbox.setSpacing(12)
        self.setWidget(self.body)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        for w in (self, self.body):
            w.setStyleSheet(f"#{w.objectName()}{{background:transparent;}}")
        self.vbox.addStretch(1)

    def clear(self):
        while self.vbox.count():
            item = self.vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.vbox.addStretch(1)          # 清完补回末尾弹簧，保证 add() 的插入位置正确

    def add(self, w: QWidget, stretch: int = 0):
        """stretch>0 的控件会吃掉剩余高度（表格 / 文本区），并让末尾弹簧让位。"""
        self.vbox.insertWidget(max(0, self.vbox.count() - 1), w, stretch)
        if stretch:
            self.vbox.setStretch(self.vbox.count() - 1, 0)
        return w

    def add_layout(self, lay):
        holder = QWidget()
        holder.setLayout(lay)
        return self.add(holder)


_TABLES: list = []


def table_qss() -> str:
    c = pal()
    return f"""
    QTableWidget, QTableView {{
        background: transparent;
        border: none;
        gridline-color: transparent;
        color: {c['text']};
        selection-background-color: {c['sel']};
        selection-color: {c['text']};
    }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{
        background: {c['card']};
        color: {c['title']};
        border: none;
        border-bottom: 1px solid {c['border']};
        padding: 7px 10px;
    }}
    QTableView::item {{ border: none; padding: 3px 8px; }}
    QTableView::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
    QTableCornerButton::section {{ background: {c['card']}; border: none; }}
    """


def make_table(headers: list[str], stretch: tuple[int, ...] = ()) -> qfw.TableWidget:
    t = qfw.TableWidget()
    t.setBorderVisible(False)
    t.setWordWrap(False)
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(34)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setShowGrid(False)
    t.setAlternatingRowColors(False)
    hh = t.horizontalHeader()
    hh.setMinimumSectionSize(78)
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    for i in stretch:
        hh.setSectionResizeMode(i, QHeaderView.Stretch)
    t.setStyleSheet(table_qss())
    _TABLES.append(t)
    return t


def fill_table(t: qfw.TableWidget, rows: list[list], right: tuple[int, ...] = ()):
    t.setSortingEnabled(False)
    t.setRowCount(0)
    for r, row in enumerate(rows):
        t.insertRow(r)
        for c, cell in enumerate(row):
            if isinstance(cell, QTableWidgetItem):
                item = cell
            else:
                item = QTableWidgetItem(str(cell))
            if c in right:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(r, c, item)
    t.setSortingEnabled(True)


# ---------------------------------------------------------------- 主窗口

class App(FluentWindow):

    def __init__(self):
        super().__init__()
        self.cfg = load_settings()
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.data = None
        self.binding: list[dict] = []
        self.roles: dict[str, dict] = {}
        self._busy = False
        self._gacha_records: list[dict] = []
        self._gacha_all: list[dict] = []
        self._gacha_view = "6star"
        self.attendance: dict | None = None

        self._init_window()
        self._build_pages()
        self._apply_theme(self.cfg.get("theme", "auto"))
        self._apply_saved_cred()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain)
        self.timer.start(120)

        self._auto_queue: list[str] = []
        QTimer.singleShot(900, self._auto_start)   # 窗口出来后自动登录

    # ---------------- 窗口 ----------------
    def _init_window(self):
        self.setWindowTitle("明日方舟 · 助手")
        self.resize(1280, 860)
        try:
            self.setMicaEffectEnabled(False)   # 用纯色深海蓝；开云母底色会被冲淡
        except Exception:  # noqa: BLE001
            pass
        self.navigationInterface.setExpandWidth(220)
        try:                       # 默认展开成「图标 + 文字」，11 个页面纯图标认不出来
            self.navigationInterface.expand(useAni=False)
        except Exception:  # noqa: BLE001
            pass
        self._center()

    def _center(self):
        """按屏幕可用区夹取尺寸 + 居中（高 DPI 下 1280×860 逻辑可能比物理屏还大）。"""
        scr = self.screen().availableGeometry()
        w = max(900, min(self.width(), scr.width() - 40))
        h = max(600, min(self.height(), scr.height() - 60))
        self.resize(w, h)
        self.move(scr.x() + (scr.width() - w) // 2,
                  scr.y() + max(0, (scr.height() - h) // 2))

    def _put_in_titlebar(self, w: QWidget):
        tb = getattr(self, "titleBar", None)
        for attr in ("titleBarLayout", "hBoxLayout"):
            lay = getattr(tb, attr, None)
            if lay is not None:
                try:
                    lay.insertWidget(1, w)
                    return True
                except Exception:  # noqa: BLE001
                    pass
        return False

    # ---------------- 页面骨架 ----------------
    def _build_pages(self):
        self.pg_overview = Page("overview")
        self.pg_oper = Page("oper")
        self.pg_base = Page("base")
        self.pg_recruit = Page("recruit")
        self.pg_gacha = Page("gacha")
        self.pg_longcao = Page("longcao")
        self.pg_record = Page("record")
        self.pg_checkin = Page("checkin")
        self.pg_raw = Page("raw")
        self.pg_account = Page("account")
        self.pg_log = Page("log")

        for pg, icon, text in (
            (self.pg_overview, FI.HOME, "概览"),
            (self.pg_oper, FI.PEOPLE, "干员"),
            (self.pg_base, FI.IOT, "基建"),
            (self.pg_recruit, FI.SEARCH, "公招"),
            (self.pg_gacha, FI.TILES, "抽卡"),
            (self.pg_longcao, FI.CALENDAR, "长草"),
            (self.pg_record, FI.HISTORY, "战绩"),
            (self.pg_checkin, FI.ACCEPT, "签到"),
            (self.pg_raw, FI.CODE, "原始 JSON"),
        ):
            self.addSubInterface(pg, icon, text)

        self.addSubInterface(self.pg_account, FI.FINGERPRINT, "账号",
                             NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.pg_log, FI.COMMAND_PROMPT, "日志",
                             NavigationItemPosition.BOTTOM)

        # 切到「长草」页时重新读盘渲染（计划由外部脚本/定时任务更新）
        self.stackedWidget.currentChanged.connect(self._on_page_changed)

        self.btn_theme = qfw.TransparentToolButton(FI.CONSTRACT, self)
        self.btn_theme.setToolTip("切换 浅色 / 深色 / 跟随系统")
        self.btn_theme.clicked.connect(self._cycle_theme)
        if not self._put_in_titlebar(self.btn_theme):
            self.btn_theme.setParent(self.pg_account)

        self._build_account()
        self._build_gacha()
        self._build_recruit()
        self._build_longcao()
        self._build_log()
        self._placeholder("未登录 —— 去「账号」页登录（或点「载入样例数据」预览）。")
        self._gacha_local_initial()

    def _placeholder(self, text: str):
        for pg, keep in ((self.pg_overview, False), (self.pg_oper, False), (self.pg_base, False),
                         (self.pg_record, False), (self.pg_checkin, False), (self.pg_raw, False)):
            pg.clear()
            lab = qfw.BodyLabel(text)
            register_color(lab, "muted")
            pg.add(lab)

    # ---------------- 账号页 ----------------
    def _build_account(self):
        pg = self.pg_account

        top = qfw.TitleLabel("账号")
        pg.add(top)
        pg.add(note(LOGIN_HINT.replace("\n", " ")))

        login = Section("登录（鹰角通行证）")
        r1 = login.row()
        r1.addWidget(qfw.BodyLabel("手机号"))
        self.ed_phone = qfw.LineEdit()
        self.ed_phone.setPlaceholderText("手机号")
        self.ed_phone.setText(self.cfg.get("phone") or "")
        self.ed_phone.setClearButtonEnabled(True)
        r1.addWidget(self.ed_phone, 1)

        r2 = login.row()
        r2.addWidget(qfw.BodyLabel("方式"))
        self.cb_mode = qfw.ComboBox()
        self.cb_mode.addItems(["验证码", "密码"])
        self.cb_mode.setCurrentIndex(0 if self.cfg.get("login_mode") != "密码" else 1)
        self.cb_mode.setFixedWidth(120)
        r2.addWidget(self.cb_mode)
        self.ed_secret = qfw.PasswordLineEdit()
        self.ed_secret.setPlaceholderText("密码 / 验证码")
        self.ed_secret.returnPressed.connect(self.login)
        r2.addWidget(self.ed_secret, 1)
        self.btn_send = btn("发送验证码")
        self.btn_send.clicked.connect(self.send_code)
        r2.addWidget(self.btn_send)
        self.btn_login = btn("登录", FI.ACCEPT, primary=True)
        self.btn_login.clicked.connect(self.login)
        r2.addWidget(self.btn_login)

        self.lbl_acct = qfw.BodyLabel("未登录")
        register_color(self.lbl_acct, "muted")
        login.add(self.lbl_acct)

        r3 = login.row()
        r3.addWidget(qfw.BodyLabel("角色"))
        self.cb_role = qfw.ComboBox()
        self.cb_role.addItems(["—"])
        self.cb_role.setMinimumWidth(220)
        self.cb_role.currentTextChanged.connect(self._on_role)
        r3.addWidget(self.cb_role)
        self.sw_remember = qfw.SwitchButton()
        self.sw_remember.setChecked(bool(self.cfg.get("remember", True)))
        r3.addWidget(qfw.BodyLabel("记住手机号"))
        r3.addWidget(self.sw_remember)
        r3.addStretch(1)

        r3b = login.row()
        self.sw_auto = qfw.SwitchButton()
        self.sw_auto.setChecked(bool(self.cfg.get("auto_login", True)))
        self.sw_auto.checkedChanged.connect(self._set_auto_login)
        r3b.addWidget(self.sw_auto)
        r3b.addWidget(qfw.BodyLabel("打开时自动登录"))
        r3b.addWidget(note("用本机已保存的凭证直接拉数据；抽卡会顺带从火狐更新"
                           "（留档超过 6 小时才更新）。"))
        r3b.addStretch(1)
        pg.add(login)

        tools = Section("快捷工具")
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        pairs = [
            ("启动游戏", self._lc_start_game, FI.PLAY),
            ("打开 MAA", self._lc_open_maa, FI.ROBOT),
            ("生成汇总网页", self._lc_build_site, FI.DOCUMENT),
            ("打开汇总网页", self._lc_open_site, FI.GLOBE),
            ("写 MAA 配置", self._lc_write_maa, FI.SAVE),
        ]
        for i, (text, fn, icon) in enumerate(pairs):
            b = btn(text, icon)
            b.setMinimumHeight(38)
            b.clicked.connect(fn)
            g.addWidget(b, i // 3, i % 3)
        holder = QWidget()
        holder.setLayout(g)
        tools.add(holder)
        tools.add(note("「生成汇总网页」= 把本周计划/每日安排/上线建议/培养进度渲染成单页站点"
                       "（scheduling/报告/汇总.html）。"))
        pg.add(tools)

        data = Section("数据")
        r4 = data.row()
        self.btn_refresh = btn("刷新数据", FI.SYNC, primary=True)
        self.btn_refresh.clicked.connect(self.refresh)
        r4.addWidget(self.btn_refresh)
        self.btn_checkin = btn("每日签到", FI.ACCEPT)
        self.btn_checkin.clicked.connect(self.checkin)
        r4.addWidget(self.btn_checkin)
        b_fix = btn("载入样例数据", FI.DOCUMENT)
        b_fix.clicked.connect(self.load_fixture)
        r4.addWidget(b_fix)
        b_ff = btn("从火狐导入抽卡凭证", FI.GLOBE)
        b_ff.clicked.connect(self._gacha_import_firefox)
        r4.addWidget(b_ff)
        r4.addStretch(1)
        pg.add(data)

        theme = Section("外观")
        r5 = theme.row()
        self.cb_theme = qfw.ComboBox()
        self.cb_theme.addItems(["跟随系统", "浅色", "深色"])
        self.cb_theme.setCurrentIndex({"auto": 0, "light": 1, "dark": 2}.get(
            self.cfg.get("theme", "auto"), 0))
        self.cb_theme.setFixedWidth(140)
        self.cb_theme.currentIndexChanged.connect(
            lambda i: self._apply_theme(("auto", "light", "dark")[i]))
        r5.addWidget(qfw.BodyLabel("主题"))
        r5.addWidget(self.cb_theme)
        r5.addStretch(1)
        pg.add(theme)

    # ---------------- 抽卡页 ----------------
    def _build_gacha(self):
        pg = self.pg_gacha
        pg.clear()
        pg.add(qfw.TitleLabel("抽卡记录"))
        pg.add(note("来自 ak.hypergryph.com 用户中心的「寻访记录」（不是森空岛），只支持官服。"))
        pg.add(note("官方口径：可查询 90 日内记录、结果可能有 30 分钟延迟。"
                    "本地留档只增不删，所以超过 90 天的旧记录也不会丢。"))

        bar = Section()
        r = bar.row()
        self.btn_gacha = btn("拉取 / 更新", FI.SYNC, primary=True)
        self.btn_gacha.clicked.connect(self._gacha_fetch)
        r.addWidget(self.btn_gacha)
        self.btn_gacha_ff = btn("从火狐导入", FI.GLOBE)
        self.btn_gacha_ff.clicked.connect(self._gacha_import_firefox)
        r.addWidget(self.btn_gacha_ff)
        self.btn_gacha_local = btn("只读本地留档", FI.FOLDER)
        self.btn_gacha_local.clicked.connect(self._gacha_local)
        r.addWidget(self.btn_gacha_local)
        b_site = btn("打开官网记录页", FI.LINK)
        b_site.clicked.connect(self._gacha_open_site)
        r.addWidget(b_site)
        r.addStretch(1)
        self.seg_view = qfw.SegmentedWidget()
        self.seg_view.addItem("6star", "只看 6★", onClick=lambda: self._set_gacha_view("6star"))
        self.seg_view.addItem("all", "全部记录", onClick=lambda: self._set_gacha_view("all"))
        self.seg_view.setCurrentItem("6star")
        self.seg_view.setFixedWidth(200)
        r.addWidget(self.seg_view)
        pg.add(bar)

        tiles = QWidget()
        tg = QHBoxLayout(tiles)
        tg.setContentsMargins(0, 0, 0, 0)
        tg.setSpacing(12)
        self.tiles: dict[str, StatTile] = {}
        for key, title in (("total", "总抽数"), ("six", "6★ 个数"),
                           ("avg", "平均抽 / 金"), ("span", "记录区间")):
            t = StatTile(title)
            self.tiles[key] = t
            tg.addWidget(t, 1)
        pg.add(tiles)

        self.tbl_gacha = make_table(["时间", "链", "卡池", "干员", "星级", "第 N 抽", "新"],
                                    stretch=(2,))
        self.tbl_gacha.setMinimumHeight(320)
        pg.add(self.tbl_gacha, stretch=1)

    def _set_gacha_view(self, key: str):
        self._gacha_view = key
        self._fill_gacha_table()

    def _fill_gacha_table(self):
        if self._gacha_view == "all":
            recs = list(self._gacha_all or [])
            if len(recs) > 3000:
                recs = recs[-3000:]
            rows = []
            for r in reversed(recs):
                rows.append([
                    fmt_ts_ms(r.get("ts")),
                    gc.classify(r.get("category") or r.get("poolId") or ""),
                    r.get("poolName", ""), r.get("charName", ""),
                    stars_txt(r.get("stars")), "", "NEW" if r.get("isNew") else "",
                ])
            fill_table(self.tbl_gacha, rows)
            return
        rows = []
        for s in self._gacha_records or []:
            rows.append([
                fmt_ts_ms(s["ts"]), s.get("chain", ""), s.get("poolName", ""),
                s.get("charName", ""), stars_txt(s.get("stars")),
                NumItem(f"{s.get('pity', '')} 抽", s.get("pity", 0)),
                "NEW" if s.get("isNew") else "",
            ])
        fill_table(self.tbl_gacha, rows)

    def _render_gacha(self, payload):
        st = payload["stats"]
        self._gacha_records = st["six"]
        uid = self._gacha_uid()
        arch = (gc.load_archive().get(str(uid)) or {}) if uid else {}
        self._gacha_all = arch.get("records") or []
        self._fill_gacha_table()
        self.tiles["total"].set_value(str(st["total"]))
        self.tiles["six"].set_value(str(st["six_count"]))
        self.tiles["avg"].set_value(
            f"{st['avg_pulls_per_six']:.1f}" if st.get("avg_pulls_per_six") else "—")
        self.tiles["span"].set_value(
            f"{dt((st['earliest_ts'] or 0)/1000)} → {dt((st['latest_ts'] or 0)/1000)}"
            if st.get("earliest_ts") else "—")
        dist = "　".join(f"{k}★×{st['by_stars'][k]}" for k in sorted(st["by_stars"], reverse=True))
        pend = "　".join(f"{k}垫{v}抽" for k, v in (st.get("pending") or {}).items())
        extra = []
        if payload.get("added"):
            extra.append(f"本次新入库 {payload['added']} 条")
        if payload.get("src") == "firefox-session":
            extra.append("来源：火狐会话")
        if payload.get("local"):
            extra.append("本地留档")
        self.log(f"抽卡：总抽 {st['total']}　6★ {st['six_count']}　{dist}　|　{pend}"
                 + ("　|　" + "　".join(extra) if extra else ""), "ok")

    def _gacha_uid(self):
        cfg = core.load_config()
        return (cfg.get("gacha") or {}).get("uid") or cfg.get("uid")

    def _gacha_fetch(self):
        cfg = core.load_config()
        g = dict(cfg.get("gacha") or {})
        if not (g.get("u8_token") and g.get("cookie")) and not g.get("account_token"):
            self._toast("err", "需要凭据",
                        "点「从火狐导入」（浏览器已登录官网即可，免密码），或在「账号」页重新登录。")
            return
        self.log("\n拉取抽卡记录…", "head")

        def work():
            cred = g
            if not (cred.get("u8_token") and cred.get("cookie")):
                cred = gc.derive_credentials(cred["account_token"], uid=cred.get("uid"))
                core.save_config(extra={"gacha": cred})
            res = self._gacha_pull(cred)
            self._gacha_report(cred, res)

        self._run_worker(work)

    def _gacha_import_firefox(self, auto: bool = False):
        """免密码：直接抄本机 Firefox 里已登录的官网会话（见 ff_session.py）。

        auto=True 是「打开时自动登录」带的：读不到会话或拉取失败只记日志，不弹提示。
        """
        self.log("\n从 Firefox 读登录态（免密码）…", "head")

        def work():
            try:
                cred = ffs.read_ak_login()
            except ffs.FirefoxSessionError as e:
                if auto:
                    self.q.put(("log", (f"跳过抽卡自动更新：{e}", "dim")))
                    return
                raise
            core.save_config(extra={"gacha": cred})
            self.q.put(("log", (f"已从 Firefox（{cred['profile']}）导入登录态：uid={cred['uid']}", "ok")))
            try:
                res = self._gacha_pull(cred)
            except gc.GachaError as e:
                if auto:
                    self.q.put(("log", (f"抽卡自动更新失败：{e}", "dim")))
                    return
                raise
            self._gacha_report(cred, res)

        self._run_worker(work)

    def _gacha_pull(self, cred):
        try:
            return gc.fetch_all(cred["uid"], cred)
        except gc.GachaError as e:
            stale = any(k in str(e) for k in
                        ("MissingCookie", "UN_LOGIN", "DETECTED_ROLE_CHANGED"))
            if not (stale and cred.get("account_token")):
                if stale:
                    raise gc.GachaError(
                        e.code, f"{e.message}（凭据已失效，请重新登录或用「从火狐导入」重取会话）",
                        e.url) from e
                raise
            self.q.put(("log", ("抽卡凭证失效，重新派生一次…", "dim")))
            cred = gc.derive_credentials(cred["account_token"], uid=cred["uid"])
            core.save_config(extra={"gacha": cred})
            return gc.fetch_all(cred["uid"], cred)

    def _gacha_report(self, cred, res):
        for e in res["errors"]:
            self.q.put(("log", (e, "err")))
        merged = gc.merge_archive(cred["uid"], res["records"], categories=res.get("categories"))
        self.q.put(("gacha", {"stats": gc.summarize(merged["records"]),
                              "added": merged["added"], "fetched": len(res["records"]),
                              "per": res.get("per_category") or {},
                              "src": cred.get("source") or "login"}))

    def _gacha_local_initial(self):
        """启动时若本地已有留档就直接渲染（不弹提示）。"""
        uid = self._gacha_uid()
        recs = ((gc.load_archive().get(str(uid)) or {}) if uid else {}).get("records") or []
        if recs:
            self._render_gacha({"stats": gc.summarize(recs), "added": 0, "fetched": 0,
                                "per": {}, "local": True})

    def _gacha_local(self):
        uid = self._gacha_uid()
        arch = (gc.load_archive().get(str(uid)) or {}) if uid else {}
        recs = arch.get("records") or []
        if not recs:
            self._toast("warn", "本地还没有留档", "先点「拉取 / 更新」或「从火狐导入」。")
            return
        self._render_gacha({"stats": gc.summarize(recs), "added": 0, "fetched": 0,
                            "per": {}, "local": True})

    def _gacha_open_site(self):
        webbrowser.open(gc.GACHA_PAGE_URL)
        self.log(f"已打开官网寻访记录页：{gc.GACHA_PAGE_URL}", "dim")

    # ---------------- 公招页 ----------------
    def _build_recruit(self):
        pg = self.pg_recruit
        pg.clear()
        pg.add(qfw.TitleLabel("公开招募"))
        self.sec_recruit = Section("栏位")
        pg.add(self.sec_recruit)

        tool = Section("贴词条 → 推荐")
        r = tool.row()
        self.ed_tags = qfw.LineEdit()
        self.ed_tags.setPlaceholderText("高级资深干员 输出 近战位 新手 生存")
        self.ed_tags.returnPressed.connect(self._recruit_recommend)
        r.addWidget(self.ed_tags, 1)
        b = btn("推荐", FI.SEARCH, primary=True)
        b.clicked.connect(self._recruit_recommend)
        r.addWidget(b)
        tool.add(note("取前 10 个词条组合，优先补图鉴"))
        self.txt_recruit = qfw.TextEdit()
        self.txt_recruit.setReadOnly(True)
        self.txt_recruit.setMinimumHeight(200)
        self.txt_recruit.setFont(QFont("Consolas", 10))
        tool.vbox.addWidget(self.txt_recruit, 1)
        pg.add(tool)

    def _recruit_recommend(self):
        text = self.ed_tags.text().strip()
        if not text:
            self._toast("warn", "缺词条", "先在输入框里贴上这次的公招词条。")
            return
        self.txt_recruit.setPlainText("计算中…（首次会拉取干员箱，稍等）")
        self.log("公招推荐：计算中…", "head")
        tools_dir = str(ROOT / "scheduling" / "tools")

        def work():
            try:
                if tools_dir not in sys.path:
                    sys.path.insert(0, tools_dir)
                from recruit_combo import load_owned, load_pool, parse_tags_arg, recommend
                pool, _all_tags = load_pool()
                owned, src = load_owned()
                tags = parse_tags_arg(text)
                rows = recommend(tags, pool, owned, topn=10)
                lines = [f"owned 来源={src}（{len(owned)} 人）　词条：{'、'.join(tags)}", ""]
                lines.append(f"{'词条组合':<24}{'池':>4}{'未拥有':>6}{'P(新)':>8}{'星级':>8}  未拥有干员")
                lines.append("-" * 82)
                for r in rows:
                    lines.append(
                        f"{'+'.join(r['tags']):<24}{r['size']:>4}{r['unowned']:>6}"
                        f"{r['p_new']:>8.2f}{str(r['rare_min']) + '~' + str(r['rare_max']):>8}"
                        f"  {'、'.join(r['unowned_names'])}")
                out = "\n".join(lines)
            except Exception as e:  # noqa: BLE001
                import traceback
                out = "推荐失败：" + repr(e) + "\n" + traceback.format_exc()
            self.q.put(("recruit", out))

        threading.Thread(target=work, daemon=True).start()

    # ---------------- 长草页 ----------------
    def _build_longcao(self):
        pg = self.pg_longcao
        pg.clear()
        pg.add(qfw.TitleLabel("一键长草 · 本周计划"))
        bar = Section()
        r = bar.row()
        for text, fn, icon in (("生成/刷新计划", self._lc_gen_plan, FI.SYNC),
                               ("写 MAA 配置", self._lc_write_maa, FI.SAVE),
                               ("直驱跑一键长草", self._lc_run, FI.PLAY)):
            b = btn(text, icon, primary=(icon == FI.PLAY))
            b.clicked.connect(lambda _=False, f=fn: f())
            r.addWidget(b)
        r.addStretch(1)
        bar.add(note("会操作 MAA 与游戏，均需二次确认。基建已交回 MAA 自带的「队列轮换」"
                     "（队列里含 Infrast 任务，无需本机脚本）"))
        pg.add(bar)

        self.sec_longcao = Section("计划")
        pg.add(self.sec_longcao)

        tools = Section("快捷工具")
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        pairs = [
            ("启动游戏", self._lc_start_game, FI.PLAY),
            ("打开 MAA", self._lc_open_maa, FI.ROBOT),
            ("生成汇总网页", self._lc_build_site, FI.DOCUMENT),
            ("打开汇总网页", self._lc_open_site, FI.GLOBE),
            ("刷新计划", self._render_longcao, FI.SYNC),
        ]
        for i, (text, fn, icon) in enumerate(pairs):
            b = btn(text, icon)
            b.setMinimumHeight(38)
            b.clicked.connect(lambda _=False, f=fn: f())
            g.addWidget(b, i // 3, i % 3)
        holder = QWidget()
        holder.setLayout(g)
        tools.add(holder)
        pg.add(tools)

        self._render_longcao()      # 建页时先填一次，切过来即可看到

    def _on_page_changed(self, index: int):
        w = self.stackedWidget.currentWidget()
        if w is self.pg_longcao:
            self._render_longcao()

    def _render_longcao(self):
        sec = self.sec_longcao
        while sec.vbox.count() > 1:
            item = sec.vbox.takeAt(1)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        path = ROOT / "scheduling" / "data" / "weekly_plan.json"
        if not path.exists():
            sec.add(self._kv("状态", "未生成（找不到 scheduling/data/weekly_plan.json）"))
            return
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            sec.add(self._kv("状态", f"读取失败：{e!r}"))
            return
        budget = plan.get("budget") or {}
        sec.add(self._kv("周号 / 区间", f"{plan.get('week', '—')}　{plan.get('range', '—')}"))
        # 防御：今天不在计划里（过期 / 缺该日）→ 页面醒目提示（与 maa_week 同口径 plan_util.plan_day）
        try:
            sys.path.insert(0, str(ROOT / "scheduling" / "tools"))
            from plan_util import plan_day
            _today = time.strftime("%Y-%m-%d")
            _d, _st = plan_day(plan, _today)
            if _st != "ok":
                _why = ("计划已过期或未生成到本周" if _st == "out_of_range"
                        else "计划缺这一天" if _st == "no_entry"
                        else "计划没有逐日表")
                warn = qfw.BodyLabel(
                    f"!! 今天 {_today} 不在计划里（{_why}）—— 点「生成/刷新计划」重新生成；"
                    f"在此之前「写 MAA 配置」「直驱跑一键长草」会被拒绝。")
                warn.setWordWrap(True)
                warn.setTextColor(QColor("#E0685A" if is_dark() else "#C03A2B"))
                sec.add(warn)
        except Exception:  # noqa: BLE001
            pass
        if plan.get("generated_at") or plan.get("by"):
            sec.add(self._kv("生成时间", f"{plan.get('generated_at', '—')}　"
                                         f"（{plan.get('by', '—')}）"))
        sec.add(self._kv("预算", f"自然理智 {budget.get('sanity_natural', '—')} · "
                                 f"周药 {budget.get('weekly_potion', '—')} · "
                                 f"理智药 {budget.get('meds_available', '—')}"))
        tasks = plan.get("tasks") or []
        if tasks:
            t = make_table(["#", "任务", "参数"], stretch=(1,))
            rows = []
            for i, task in enumerate(tasks, 1):
                p = task.get("params") or {}
                stage = p.get("stage") or p.get("mode") or ""
                mode = p.get("facility") or ""
                if isinstance(mode, list):
                    mode = "/".join(str(x) for x in mode)
                parts = [str(task.get("type", ""))]
                if stage:
                    parts.append(str(stage))
                if mode:
                    parts.append(str(mode))
                if p.get("times") is not None:
                    parts.append(f"×{p.get('times')}")
                rows.append([str(i), " · ".join(parts),
                             task.get("name") or task.get("note") or ""])
            fill_table(t, rows)
            t.setMinimumHeight(min(360, 40 + 30 * len(rows)))
            sec.vbox.addWidget(t, 1)

        try:
            sys.path.insert(0, str(ROOT / "scheduling" / "tools"))
            from plan_util import distribute_daily, session_advice, weekly_summary
            daily = distribute_daily(plan)
            summary = weekly_summary(plan, daily) if daily else None
            advice = session_advice(plan, daily) if daily else []
        except Exception:  # noqa: BLE001
            daily, summary, advice = [], None, []
        if daily:
            t2 = make_table(["日期", "安排", "理智"], stretch=(1,))
            rows = []
            for d in daily:
                runs = d.get("runs") or {}
                txt = "、".join(f"{k}×{v}" for k, v in runs.items()) or "—"
                if d.get("opens"):
                    txt += "　★新开：" + "、".join(d["opens"])
                san = str(d.get("sanity", 0)) + ("（超上限）" if d.get("over") else "")
                rows.append([f"{d.get('date', '')} {d.get('dow', '')}", txt, san])
            fill_table(t2, rows, right=(2,))
            t2.setMinimumHeight(min(420, 40 + 30 * len(rows)))
            sec.vbox.addWidget(t2, 1)
            if summary:
                sec.add(self._kv("周合计", f"{summary['total']} / 预算 {summary['avail']}"
                                          f"（自然{summary['natural']}+周药{summary['weekly_potion']}）"
                                          + (f"　缺口 {summary['gap']}（需理智药）"
                                             if summary["gap"] else "　够")))
        tr = plan.get("training")
        if tr:
            sec.add(self._kv("培养目标", "、".join(tr.get("targets", []))))
            sec.add(self._kv("总缺口", f"{tr.get('total_sanity')} 理智"
                                       f"（材料 {tr.get('material_sanity')} + 龙门币 {tr.get('lmd_sanity')}）"))
            sec.add(self._kv("本周投", f"{tr.get('week_sanity')} 理智"
                                       + (f"（还需约 {tr['need_weeks']} 周）" if tr.get("need_weeks") else "")))
        for n in (plan.get("rationale") or {}).get("notes") or []:
            sec.add(note("· " + str(n)))

    def _kv(self, key: str, value: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        k = qfw.CaptionLabel(key)
        k.setFixedWidth(104)
        register_color(k, "muted")
        v = qfw.BodyLabel(str(value))
        v.setWordWrap(True)
        h.addWidget(k)
        h.addWidget(v, 1)
        return w

    # ---------------- 日志页 ----------------
    def _build_log(self):
        pg = self.pg_log
        pg.clear()
        pg.add(qfw.TitleLabel("日志"))
        bar = Section()
        r = bar.row()
        b = btn("清空", FI.DELETE)
        b.clicked.connect(lambda: self.txt_log.clear())
        r.addWidget(b)
        r.addStretch(1)
        pg.add(bar)
        try:
            self.txt_log = qfw.TextEdit()
        except Exception:  # noqa: BLE001
            from PySide6.QtWidgets import QTextEdit
            self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Consolas", 10))
        self.txt_log.setMinimumHeight(320)
        pg.add(self.txt_log, stretch=1)

    def log(self, msg: str, tag: str = ""):
        box = getattr(self, "txt_log", None)
        if box is None:
            return
        colors = {"ok": "#4CAF7D" if is_dark() else "#1A7F37",
                  "err": "#E0685A" if is_dark() else "#C03A2B",
                  "dim": pal()["muted"], "head": pal()["title"]}
        text = html.escape(str(msg)).replace("\n", "<br>")
        color = colors.get(tag)
        if color:
            box.append(f'<span style="color:{color}">{text}</span>')
        else:
            box.append(text)
        box.verticalScrollBar().setValue(box.verticalScrollBar().maximum())

    def _toast(self, kind: str, title: str, content: str = ""):
        fn = {"ok": InfoBar.success, "err": InfoBar.error,
              "warn": InfoBar.warning, "info": InfoBar.info}.get(kind, InfoBar.info)
        fn(title, content, duration=3500, position=InfoBarPosition.TOP_RIGHT, parent=self)

    # ---------------- 主题 ----------------
    def _restyle_game(self):
        """把「深海蓝 + 金」这套配色重新铺到全局（主题切换后调用）。"""
        c = pal()
        try:
            qfw.setThemeColor(QColor(c["accent"]))
        except Exception:  # noqa: BLE001
            pass
        try:      # (light, dark) 两套底色由框架按当前主题挑
            self.setCustomBackgroundColor(QColor(GAME["light"]["window"]),
                                          QColor(GAME["dark"]["window"]))
        except Exception:  # noqa: BLE001
            pass
        refresh_theme_colors()
        qss = table_qss()
        alive = []
        for t in _TABLES:
            try:
                t.setStyleSheet(qss)
                alive.append(t)
            except RuntimeError:      # 页面重渲染时旧表已销毁
                pass
        _TABLES[:] = alive
        for w in self.findChildren(QWidget):   # 卡片是自绘的，必须显式重绘
            w.update()

    def _apply_theme(self, mode: str):
        qfw.setTheme({"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}[mode])
        self.cfg["theme"] = mode
        save_settings(self.cfg)
        self._restyle_game()
        if getattr(self, "cb_theme", None) is not None:
            idx = {"auto": 0, "light": 1, "dark": 2}[mode]
            if self.cb_theme.currentIndex() != idx:
                self.cb_theme.blockSignals(True)
                self.cb_theme.setCurrentIndex(idx)
                self.cb_theme.blockSignals(False)

    def _cycle_theme(self):
        order = ["auto", "light", "dark"]
        cur = self.cfg.get("theme", "auto")
        self._apply_theme(order[(order.index(cur) + 1) % 3])

    # ---------------- 账号 / 交互 ----------------
    def _has_cred(self) -> bool:
        return bool(core.load_config().get("cred"))

    def _apply_saved_cred(self):
        cfg = core.load_config()
        if cfg.get("cred"):
            self.log("发现本机已保存的凭证。", "dim")
            self.lbl_acct.setText("已保存凭证（未校验）")

    def _set_auto_login(self, value: bool):
        self.cfg["auto_login"] = bool(value)
        save_settings(self.cfg)
        self.log(f"「打开时自动登录」已{'开启' if value else '关闭'}。", "dim")

    # ---------------- 打开即自动登录 ----------------
    def _auto_start(self):
        """窗口显示后：有本机凭证就直接拉数据，顺带把抽卡也更新一遍。"""
        if not self.sw_auto.isChecked():
            self.log("未开启自动登录，点「刷新数据」手动拉取。", "dim")
            return
        if not self._has_cred():
            self.log("本机没有凭证，无法自动登录 —— 在下面登录一次，以后就会自动。", "dim")
            return
        self.log("\n自动登录：用本机凭证拉取数据…", "head")
        self._auto_queue = ["refresh", "gacha"]
        self._run_auto_next()

    def _run_auto_next(self):
        if not self._auto_queue:
            return
        task = self._auto_queue.pop(0)
        if task == "refresh":
            self.refresh()
        elif task == "gacha":
            if self._gacha_auto_due():
                self._gacha_import_firefox(auto=True)
            else:
                self.log("抽卡留档还新鲜（6 小时内），跳过自动更新。", "dim")

    def _gacha_auto_due(self) -> bool:
        """抽卡要不要顺带更新：留档超过 6 小时才拉，免得每次开界面都打接口。"""
        uid = self._gacha_uid()
        slot = (gc.load_archive().get(str(uid)) or {}) if uid else {}
        return (time.time() - (slot.get("updated_at") or 0)) > 6 * 3600

    def _on_role(self, label: str):
        uid = self.roles.get(label, {}).get("uid")
        if uid and self._has_cred():
            self._start_fetch(uid)

    def _run_worker(self, fn):
        if self._busy:
            self.log("正在忙，等当前任务结束。", "dim")
            return
        self._busy = True
        self._set_busy(True)

        def target():
            try:
                fn()
            except (core.SklandError, gc.GachaError, ffs.FirefoxSessionError) as e:
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

    def _set_busy(self, busy: bool):
        for name in ("btn_refresh", "btn_checkin", "btn_login", "btn_gacha",
                     "btn_gacha_ff", "btn_gacha_local"):
            w = getattr(self, name, None)
            if w is not None:
                w.setEnabled(not busy)

    def login(self):
        phone = self.ed_phone.text().strip()
        mode = self.cb_mode.currentText()
        secret = self.ed_secret.text().strip()
        if not phone or not secret:
            self._toast("warn", "缺信息", "手机号和密码/验证码都要填。")
            return
        self.log(f"\n开始登录（{mode}）：{phone[:3]}****", "head")

        def work():
            token = (core.token_by_phone_password(phone, secret) if mode == "密码"
                     else core.token_by_phone_code(phone, secret))
            cred, sign_token = core.cred_from_token(token)
            core.save_config(cred, token=sign_token)
            self.q.put(("log", ("登录成功，凭证已保存到 ~/.arknights_skland.json", "ok")))
            chars = core.binding(cred, sign_token)
            self.q.put(("binding", chars))
            try:
                g = gc.derive_credentials(token, uid=(chars[0]["uid"] if chars else None))
                core.save_config(extra={"gacha": g})
                self.q.put(("log", (f"抽卡记录凭证已就绪（uid={g['uid']}　"
                                    f"{g.get('channelName') or ''}）", "ok")))
            except gc.GachaError as e:
                self.q.put(("log", (f"抽卡凭证获取失败（不影响看板）：{e}", "err")))
            if chars:
                self._fetch_into_queue(cred, sign_token, chars[0]["uid"])

        self._run_worker(work)

    def send_code(self):
        phone = self.ed_phone.text().strip()
        if not phone:
            self._toast("warn", "缺信息", "先填手机号。")
            return

        def work():
            core.send_phone_code(phone)
            self.q.put(("ok", f"验证码已发送到 {phone[:3]}****{phone[-4:]}"))

        self._run_worker(work)

    def refresh(self):
        cfg = core.load_config()
        if not cfg.get("cred"):
            self._toast("warn", "未登录", "先去「账号」页登录，或点「载入样例数据」预览界面。")
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
            try:
                token = core.refresh_token(cred)
                core.save_config(cred, token=token)
            except Exception as e:  # noqa: BLE001
                self.q.put(("log", (f"续期失败（退回旧 token 试）：{e!r}", "err")))
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
            self._toast("warn", "未登录", "先登录再签到。")
            return

        def work():
            cred, token = cfg["cred"], cfg.get("token")
            try:
                token = core.refresh_token(cred)
                core.save_config(cred, token=token)
            except Exception:  # noqa: BLE001
                pass
            awards = core.do_checkin(cred, cfg["uid"], token)
            if awards:
                txt = "；".join(f"{a.get('resource', {}).get('name')} x{a.get('count')}"
                                for a in awards)
            else:
                txt = "今日已签到或无奖励"
            self.q.put(("ok", f"签到：{txt}"))
            # 签到后立即重拉签到状态，让「今日」状态即时更新（不等手动「刷新数据」）
            try:
                att = core.attendance_status(cred, cfg["uid"], token)
                self.q.put(("attendance", att))
            except core.SklandError as e:
                self.q.put(("log", (f"签到后刷新状态失败（稍后可手动刷新）：{e}", "dim")))

        self._run_worker(work)

    def load_fixture(self):
        if not os.path.exists(FIXTURE):
            self._toast("err", "没有样例", "找不到样例文件：" + FIXTURE)
            return
        with open(FIXTURE, encoding="utf-8") as f:
            raw = json.load(f)
        info = raw.get("data", raw)
        self._render(info, attendance=None)
        self.lbl_acct.setText("样例数据（仅界面预览，不代表你的账号）")
        self.log("已载入样例数据。", "ok")

    # ---------------- 队列泵 ----------------
    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(payload[0], payload[1])
                elif kind == "ok":
                    self.log(str(payload), "ok")
                    self._toast("ok", str(payload)[:60])
                elif kind == "binding":
                    self._on_binding(payload)
                elif kind == "board":
                    self._on_board(payload)
                elif kind == "attendance":
                    self.attendance = payload
                    self._render_checkin(payload)
                elif kind == "reload_plan":
                    self._render_longcao()
                elif kind == "gacha":
                    self._render_gacha(payload)
                elif kind == "recruit":
                    self.txt_recruit.setPlainText(payload)
                elif kind == "done":
                    self._busy = False
                    self._set_busy(False)
                    self._run_auto_next()          # 自动登录的下一步（拉完看板再更新抽卡）
                elif kind == "err":
                    self._busy = False
                    self._set_busy(False)
                    self.log("出错：" + str(payload), "err")
                    self._toast("err", "出错", str(payload)[:120])
                    self._run_auto_next()
        except queue.Empty:
            pass

    def _on_binding(self, chars):
        self.binding = chars
        self.roles = {}
        labels = []
        for c in chars:
            label = f"{c.get('nickName')}（{c.get('channelName')}）"
            self.roles[label] = c
            labels.append(label)
        self.cb_role.blockSignals(True)
        self.cb_role.clear()
        self.cb_role.addItems(labels or ["—"])
        self.cb_role.blockSignals(False)
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
        self.lbl_acct.setText(f"{s.get('name', '—')}　Lv{s.get('level', '—')}　ID {uid}")
        self._render(info, attendance=payload.get("attendance"))
        self.log(f"数据已更新（{s.get('name', '')} Lv{s.get('level', '')}）", "ok")
        self._toast("ok", "数据已更新", f"{s.get('name', '')} Lv{s.get('level', '')}")
        self.save_gui_settings()

    def save_gui_settings(self):
        self.cfg.update({"phone": self.ed_phone.text().strip() if self.sw_remember.isChecked() else "",
                         "login_mode": self.cb_mode.currentText(),
                         "remember": bool(self.sw_remember.isChecked()),
                         "auto_login": bool(self.sw_auto.isChecked())})
        save_settings(self.cfg)

    # ---------------- 渲染 ----------------
    def _render(self, data, attendance=None):
        self.data = data
        s = data.get("status") or {}
        chars = data.get("chars") or []
        info_map = data.get("charInfoMap") or {}
        self._render_overview(s, chars, data)
        self._render_opers(chars, info_map)
        self._render_base(data.get("building") or {}, info_map)
        self._render_recruit_info(data.get("recruit") or [])
        self._render_records(data)
        self._render_checkin(attendance)
        self._render_raw(data)

    def _render_overview(self, s, chars, data):
        pg = self.pg_overview
        pg.clear()
        pg.add(qfw.TitleLabel("博士档案"))
        tiles = QWidget()
        g = QHBoxLayout(tiles)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(12)
        ap = s.get("ap") or {}
        skin_cnt = s.get("skinCnt") or len(data.get("skins") or [])
        furn = s.get("furnitureCnt") or (data.get("building") or {}).get("furniture") or 0
        if isinstance(furn, dict):
            furn = furn.get("total", 0)
        for title, value in (("等级", f"Lv{s.get('level', '—')}"),
                             ("理智", f"{ap.get('current', '—')} / {ap.get('max', '—')}"),
                             ("干员数", str(s.get("charCnt") or len(chars))),
                             ("时装 / 家具", f"{skin_cnt} / {furn}")):
            g.addWidget(StatTile(title, value), 1)
        pg.add(tiles)

        card = Section("档案")
        card.add(self._kv("昵称", s.get("name", "—")))
        card.add(self._kv("注册", fmt_ts(s.get("registerTs"))))
        card.add(self._kv("上次在线", fmt_ts(s.get("lastOnlineTs"))))
        card.add(self._kv("主线进度", s.get("mainStageProgress") or "（已通关或未取到）"))
        pg.add(card)

        assist = data.get("assistChars") or []
        a = Section("助战干员")
        if not assist:
            a.add(qfw.BodyLabel("无"))
        info_map = data.get("charInfoMap") or {}
        for x in assist:
            cid = x.get("charId", "")
            nm = (info_map.get(cid) or {}).get("name", cid)
            a.add(self._kv(nm, f"{ELITE.get(x.get('evolvePhase'), '')} Lv{x.get('level')} "
                               f"潜{x.get('potentialRank')} 专{x.get('specializeLevel', 0)}"))
        pg.add(a)

    def _render_opers(self, chars, info_map):
        pg = self.pg_oper
        pg.clear()
        self._opers_chars = chars
        self._opers_map = info_map
        pg.add(qfw.TitleLabel("干员"))
        bar = Section()
        r = bar.row()
        r.addWidget(qfw.BodyLabel("星级"))
        self.cb_rarity = qfw.ComboBox()
        self.cb_rarity.addItems(["全部", "6★", "5★", "4★", "3★", "2★", "1★"])
        self.cb_rarity.setFixedWidth(90)
        self.cb_rarity.currentIndexChanged.connect(lambda _: self._fill_opers())
        r.addWidget(self.cb_rarity)
        r.addWidget(qfw.BodyLabel("职业"))
        self.cb_prof = qfw.ComboBox()
        self.cb_prof.addItems(["全部"] + [cn for en, cn in PROFESSIONS.items()
                                          if en not in ("TOKEN", "TRAP")])
        self.cb_prof.setFixedWidth(100)
        self.cb_prof.currentIndexChanged.connect(lambda _: self._fill_opers())
        r.addWidget(self.cb_prof)
        r.addWidget(qfw.BodyLabel("排序"))
        self.cb_sort = qfw.ComboBox()
        self.cb_sort.addItems(["星级", "等级", "技能等级"])
        self.cb_sort.setFixedWidth(110)
        self.cb_sort.currentIndexChanged.connect(lambda _: self._fill_opers())
        r.addWidget(self.cb_sort)
        r.addStretch(1)
        self.lbl_oper = qfw.BodyLabel("")
        self.lbl_oper.setWordWrap(True)
        bar.add(self.lbl_oper)
        bar.add(note("技能等级 1–7 由三技能共享；专精列依次为 S1/S2/S3 各自等级"))
        pg.add(bar)

        self.tbl_oper = make_table(["星级", "名称", "职业", "等级", "潜能", "技能", "专精"],
                                   stretch=(1,))
        self.tbl_oper.setMinimumHeight(320)
        pg.add(self.tbl_oper, stretch=1)
        self._fill_opers()

    def _fill_opers(self):
        info_map, chars = getattr(self, "_opers_map", {}) or {}, getattr(self, "_opers_chars", [])
        if not chars:
            return
        rar = self.cb_rarity.currentText()
        prof = self.cb_prof.currentText()
        want_rarity = None if rar == "全部" else int(rar.rstrip("★")) - 1

        def info(c):
            return info_map.get(c.get("charId")) or {}

        flt = [c for c in chars
               if (want_rarity is None or info(c).get("rarity") == want_rarity)
               and (prof == "全部" or PROFESSIONS.get(info(c).get("profession", "")) == prof)]

        key = self.cb_sort.currentText()
        if key == "等级":
            sortf = lambda c: (c.get("level", 0), info(c).get("rarity", -1))
        elif key == "技能等级":
            sortf = lambda c: (c.get("mainSkillLvl", 0),
                               sum(x.get("specializeLevel", 0) for x in (c.get("skills") or [])))
        else:
            sortf = lambda c: (info(c).get("rarity", -1), c.get("level", 0))
        flt.sort(key=sortf, reverse=True)

        rows = []
        for c in flt:
            inf = info(c)
            specs = [x.get("specializeLevel", 0) for x in (c.get("skills") or [])]
            r = inf.get("rarity", -1)
            rows.append([
                NumItem(f"{r + 1}★" if r >= 0 else "?", r),
                NumItem(inf.get("name", c.get("charId", "")), inf.get("name", "")),
                PROFESSIONS.get(inf.get("profession", ""), inf.get("profession", "")),
                NumItem(f"{ELITE.get(c.get('evolvePhase'), '')} Lv{c.get('level')}",
                        (c.get("evolvePhase", 0), c.get("level", 0))),
                f"潜{c.get('potentialRank')}",
                f"技{c.get('mainSkillLvl')}",
                "/".join(str(x) for x in specs) if any(specs) else "",
            ])
        fill_table(self.tbl_oper, rows)
        up = sum(1 for c in flt if c.get("evolvePhase", 0) >= 2)
        dist: dict = {}
        for c in flt:
            rr = info(c).get("rarity", -1)
            dist[rr] = dist.get(rr, 0) + 1
        dist_txt = "　".join(f"{rr + 1}★×{dist[rr]}" for rr in sorted(dist, reverse=True) if rr >= 0)
        self.lbl_oper.setText(f"筛选 {len(flt)} / {len(chars)}　精二 {up}　|　{dist_txt}")

    def _render_base(self, b, info_map):
        pg = self.pg_base
        pg.clear()
        pg.add(qfw.TitleLabel("基建"))
        if not b:
            pg.add(qfw.BodyLabel("无基建数据"))
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
            sec = Section(title)
            for s in slots:
                names = [(info_map.get(c.get("charId")) or {}).get("name", c.get("charId", ""))
                         for c in s.get("chars") or []]
                lvl = f"Lv{s.get('level')}" if s.get("level") else "—"
                sec.add(self._kv(lvl, "、".join(names) or "空置"))
            pg.add(sec)
        labor = b.get("labor") or {}
        if labor:
            sec = Section("无人机")
            sec.add(self._kv("数量", f"{labor.get('value')}/{labor.get('maxValue')}"))
            pg.add(sec)

    def _render_recruit_info(self, rec):
        sec = self.sec_recruit
        while sec.vbox.count() > 1:
            item = sec.vbox.takeAt(1)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
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
            sec.add(self._kv(f"栏位 {i + 1}", line))
        hire = (self.data.get("building") or {}).get("hire") or {}
        if hire:
            sec.add(self._kv("办公室刷新", f"{hire.get('refreshCount', '—')}　"
                                          f"下次 {fmt_ts(hire.get('completeWorkTime'))}"))

    def _render_records(self, data):
        pg = self.pg_record
        pg.clear()
        pg.add(qfw.TitleLabel("战绩"))
        camp = data.get("campaign") or {}
        sec = Section("剿灭作战")
        rew = camp.get("reward") or {}
        sec.add(self._kv("本周合成玉", f"{rew.get('current', '—')} / {rew.get('total', '—')}"))
        for rec in camp.get("records") or []:
            sec.add(self._kv(rec.get("campaignId", ""), f"最高击杀 {rec.get('maxKills')}"))
        pg.add(sec)

        tower = data.get("tower") or {}
        if tower:
            sec = Section("保全派驻")
            trew = tower.get("reward") or {}
            if trew:
                sec.add(self._kv("奖励进度", f"{trew.get('current', '—')} / {trew.get('total', '—')}"))
            for rec in tower.get("records") or []:
                sec.add(self._kv(rec.get("towerId", ""),
                                 json.dumps(rec, ensure_ascii=False)[:90]))
            pg.add(sec)

        rogue = data.get("rogue") or {}
        if rogue.get("records"):
            sec = Section("集成战略（肉鸽）")
            for rec in rogue.get("records") or []:
                bank = rec.get("bank") or {}
                sec.add(self._kv(rec.get("rogueId", ""),
                                 f"收藏品 {rec.get('relicCnt')} · "
                                 f"存款 {bank.get('current')}/{bank.get('record')}"))
            pg.add(sec)

        routine = data.get("routine") or {}
        if routine:
            sec = Section("任务")
            d, w = routine.get("daily") or {}, routine.get("weekly") or {}
            sec.add(self._kv("每日任务", f"{d.get('current', '—')} / {d.get('total', '—')}"))
            sec.add(self._kv("每周任务", f"{w.get('current', '—')} / {w.get('total', '—')}"))
            pg.add(sec)

    def _render_checkin(self, attendance):
        self.attendance = attendance
        pg = self.pg_checkin
        pg.clear()
        pg.add(qfw.TitleLabel("每日签到"))
        sec = Section("森空岛签到")
        r = sec.row()
        b = btn("执行今日签到", FI.ACCEPT, primary=True)
        b.clicked.connect(self.checkin)
        r.addWidget(b)
        r.addStretch(1)
        if not attendance:
            sec.add(self._kv("状态", "未登录 / 未取到（登录后显示）"))
            pg.add(sec)
            return
        cal = attendance.get("calendar") or []
        done = sum(1 for c in cal if c.get("done"))
        sec.add(self._kv("本月已签", f"{done} 天"))
        today = [c for c in cal if c.get("available")]
        if today and not today[0].get("done"):
            items = "、".join(f"{c.get('resourceId')}×{c.get('count')}" for c in today)
            sec.add(self._kv("今日", f"可签到（{items}）"))
        elif today:
            sec.add(self._kv("今日", "已签到"))
        else:
            sec.add(self._kv("今日", "不可签"))
        pg.add(sec)

    def _render_raw(self, data):
        pg = self.pg_raw
        pg.clear()
        pg.add(qfw.TitleLabel("原始 JSON"))
        box = qfw.TextEdit()
        box.setReadOnly(True)
        box.setFont(QFont("Consolas", 9))
        box.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))
        box.setMinimumHeight(320)
        pg.add(box, stretch=1)

    # ---------------- 外部工具 ----------------
    def _popen_log(self, args, title, done_msg=None, reload_plan=False):
        self.log(f"{title}：启动 {' '.join(str(a) for a in args)}", "head")
        # 子进程统一按 UTF-8 输出：GUI 是按 utf-8 读的，而 Windows 下 Python 子进程默认用 GBK
        # 写 stdout → 中文在日志面板全变乱码。用 env 强制子进程走 UTF-8（不改本机全局设置）。
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        try:
            proc = subprocess.Popen(
                args, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env)
        except Exception as e:  # noqa: BLE001
            self.log(f"{title} 启动失败：{e!r}", "err")
            return None

        def reader():
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        self.q.put(("log", (line, "dim")))
            except Exception:  # noqa: BLE001
                pass
            rc = proc.wait()
            if rc == 0 and done_msg:
                self.q.put(("log", (done_msg, "ok")))
            else:
                self.q.put(("log", (f"{title} 结束（退出码 {rc}）", "ok" if rc == 0 else "err")))
            if rc == 0 and reload_plan:
                self.q.put(("reload_plan", None))   # 回主线程重读 weekly_plan 刷新长草页

        threading.Thread(target=reader, daemon=True).start()
        return proc

    def _lc_gen_plan(self):
        self._popen_log([sys.executable, str(ROOT / "scheduling" / "tools" / "plan_week.py")],
                        "生成周计划", done_msg="周计划已生成", reload_plan=True)

    @staticmethod
    def _port_open(host, port) -> bool:
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
            self.log("已启动 MAA", "ok")
        except Exception as e:  # noqa: BLE001
            self.log(f"启动 MAA 失败：{e!r}", "err")

    def _lc_start_game(self):
        self._popen_log([sys.executable, str(ROOT / "scripts" / "maa-week" / "maa_week.py"),
                         "startup"], "启动游戏")

    def _lc_open_site(self):
        url = "http://127.0.0.1:8787/"
        if not self._port_open("127.0.0.1", 8787):
            self._popen_log([sys.executable, str(ROOT / "scheduling" / "tools" / "site_server.py")],
                            "汇总网页服务")
            time.sleep(0.8)
        webbrowser.open(url)
        self.log(f"已打开汇总网页 {url}", "ok")

    def _lc_write_maa(self):
        if not qfw.MessageBox("确认写 MAA 配置",
                              "这会把 weekly_plan 写进 MAA 的 gui.new.json。\n"
                              "请先关闭 MAA，否则改动会被覆盖。",
                              self).exec():
            return
        self._popen_log([sys.executable, str(ROOT / "scripts" / "maa-week" / "maa_week.py"),
                         "write"], "写 MAA 配置")

    def _lc_run(self):
        if not qfw.MessageBox("确认直驱跑一键长草",
                              "这会真的操作 MAA / 游戏，按本周计划自动执行。",
                              self).exec():
            return
        self._popen_log([sys.executable, str(ROOT / "scripts" / "maa-week" / "maa_week.py"),
                         "run"], "直驱跑一键长草")

    # ---------------- 关闭 ----------------
    def closeEvent(self, e):  # noqa: N802
        if self.worker and self.worker.is_alive():
            box = qfw.MessageBox("正在忙", "还有任务在跑，确定退出吗？", self)
            if not box.exec():
                e.ignore()
                return
        try:
            self.save_gui_settings()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(e)


def main():
    from PySide6.QtWidgets import QApplication

    try:                     # 让 Qt 跟随 Windows 的高 DPI 缩放
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    qfw.setThemeColor(QColor(GAME["dark"]["accent"]))
    w = App()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
