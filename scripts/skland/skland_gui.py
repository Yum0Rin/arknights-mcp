#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""yuMAArin —— 明日方舟账号看板 + 基建/长草助手（Qt / PySide6 + Fluent Design）。

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

import datetime
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
import unicodedata
import webbrowser

from PySide6.QtCore import QLockFile, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QIntValidator, QKeySequence, QPainter,
                           QPainterPath, QPen, QShortcut)
from PySide6.QtWidgets import (
    QAbstractItemView, QCompleter, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QMessageBox, QSizePolicy, QTableWidgetItem, QVBoxLayout, QWidget,
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

APP_NAME = "yuMAArin"

# 单实例锁：放在临时目录，进程退出时锁自动释放（QLockFile 用 PID 判活，崩溃残留也能自动清理）
LOCK_FILE = os.path.join(os.environ.get("TEMP", "."), "yuMAArin.gui.lock")

# MAA 基建相关路径（「现阶段基建配置 · 保存并应用」用）
MAA_GUI_CFG = r"C:\MAA\config\gui.new.json"
# ⚠ 方案表放**仓库**里（不是 MAA 的 resource 目录）：防 MAA 更新覆盖 + 可版本管理，
#   且与自动化（`maa_week.INFRAST_CUSTOM_FILE` / `night_infrast.py`）**同一份**，避免两处打架。
#   2026-10-14 起该文件 = 《搓玉·合成玉》A/B 两班（由 `scheduling/tools/convert_to_maa.py` 从一图流转出）。
MAA_CUSTOM_INFRAST = str(ROOT / "scheduling" / "MAA基建排班" / "243_搓玉_定制.json")
# 本机留档（保存配置时一并写一份，供无 MAA 环境/回看用）
INFRA_CFG_LOCAL = ROOT / "scheduling" / "data" / "infra_config.json"
# 自研换班脚本写的轮换日志（虽脚本已归档，历史记录仍可读，用来判断「是否该换班」）
INFRA_ROTATION_LOG = ROOT / "scheduling" / "data" / "infrast_rotation_log.jsonl"
# 每个班的时长（分钟）——与 MAA custom_infrast 里 plans[].duration 一致，兜底用 720
SHIFT_MINUTES_FALLBACK = 720

# MAA custom_infrast 的 room key → (森空岛 building key, 中文名)
INFRA_ROOM_MAP = {
    "control": ("control", "控制中枢"),
    "trading": ("tradings", "贸易站"),
    "manufacture": ("manufactures", "制造站"),
    "power": ("powers", "发电站"),
    "meeting": ("meeting", "会客室"),
    "hire": ("hire", "办公室"),
    "dormitory": ("dormitories", "宿舍"),
}

_INFRA_ROOM_CN = {k: v[1] for k, v in INFRA_ROOM_MAP.items()}     # 给「致命项」提示用的中文名表

# 方案表「致命项」判据 = **与转换器共用同一份**（`scheduling/tools/convert_to_maa.py`，纯 stdlib，import 安全）：
# 会让 MAA 跑废整队 / 方案结构性无效 / 静默失效的，一律**禁止保存**（清单与理由见那边的 `plan_fatals`）。
sys.path.insert(0, str(ROOT / "scheduling" / "tools"))
from convert_to_maa import plan_fatals  # noqa: E402

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


def dwidth(s) -> int:
    """字符串的**显示宽度**（等宽字体下 CJK 全角占 2 列）。用于文本表格对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(s))


def dpad(s, width: int, align: str = "<") -> str:
    """按**显示宽度**补空格（`str.ljust/rjust` 按字符数，中文会错位）。align: < 左 / > 右。"""
    s = str(s)
    pad = max(0, width - dwidth(s))
    return s + " " * pad if align == "<" else " " * pad + s


def dcut(s, width: int) -> str:
    """按显示宽度截断，超出补 `…`（同样按宽度算，避免中文被腰斩）。"""
    s = str(s)
    if dwidth(s) <= width:
        return s
    out, w = "", 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > width - 1:
            break
        out += ch
        w += cw
    return out + "…"


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


def make_table(headers: list[str], stretch: tuple[int, ...] = (),
               wrap: bool = False) -> qfw.TableWidget:
    """`wrap=True`：单元格文字写不下时**换行**，行高随之自适应（用 `ResizeToContents`）。"""
    t = qfw.TableWidget()
    t.setBorderVisible(False)
    t.setWordWrap(wrap)
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(34)
    if wrap:
        t.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
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


def fill_table(t: qfw.TableWidget, rows: list[list], right: tuple[int, ...] = (),
               sortable: bool = True):
    """填入表格。`sortable=False` 时禁用表头点击排序（用于已由 Python 排好序的表，如干员表）。

    ⚠ 开着表头排序时，QTableWidget 会按**当前排序指示列**、用单元格**显示文本**重排；
    若上一次点击过某列，排序指示会残留 → 覆盖我们排好的顺序（且文本排序对"等级/专精"这类列是错的）。
    这里每次填表都先把排序指示清掉（-1），避免残留列乱排。
    """
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
    try:
        t.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)   # 清残留的排序指示
    except Exception:  # noqa: BLE001
        pass
    t.setSortingEnabled(sortable)


# ---------------------------------------------------------------- 主窗口

# ---------------- 运行态告警：没按安排来时，GUI 里必须一眼看见 ----------------
DATA_DIR = ROOT / "scheduling" / "data"


def _tail_jsonl(path: pathlib.Path, n: int = 400) -> list[dict]:
    """读 jsonl 末尾 n 条（文件不存在/损坏 → 空表，绝不抛）。"""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:  # noqa: BLE001
        return []
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:  # noqa: BLE001
            continue
    return out


def _load_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _event_stage_names() -> dict:
    """MAA `Arknights-Tile-Pos/overview.json` → {关卡代号: 名称}（EX 关只有代号，名字得从这里取）。"""
    ov = _load_json(pathlib.Path(r"C:\MAA") / "resource" / "Arknights-Tile-Pos" / "overview.json")
    if not isinstance(ov, dict):
        return {}
    out = {}
    for v in ov.values():
        if isinstance(v, dict) and v.get("code") and v.get("name"):
            out.setdefault(str(v["code"]), str(v["name"]))
    return out


def collect_alerts(today: str | None = None) -> list[dict]:
    """把「自动化有没有按安排来」汇总成清单（纯读文件，可单独跑）。

    返回 [{level: err|warn|info, title, detail, hint}]
      err  = 必须处理（任务失败 / 账本作废 / 今天没跑）
      warn = 偏离安排（计划里的关没打、读数过期、EX 未清）
      info = 提示
    """
    today = today or time.strftime("%Y-%m-%d")
    out: list[dict] = []

    # 1) 今日 14:00 日常
    daily = _tail_jsonl(DATA_DIR / "daily_run.jsonl")
    ent = next((e for e in reversed(daily) if str(e.get("date")) == today), None)
    _now = datetime.datetime.now()
    _before_daily = (_now.hour, _now.minute) < (14, 10)     # 14:00 才跑，别提前报警
    if ent is None:
        if _before_daily:
            out.append({"level": "info", "title": "今天的日常还没到点",
                        "detail": f"计划 14:00 自动跑（现在 {_now.strftime('%H:%M')}）", "hint": ""})
        else:
            out.append({"level": "err", "title": "今天没有日常记录",
                        "detail": f"{today} 的「每日日常」没跑（正常应在 14:00）",
                        "hint": "长草页「直驱跑一键长草」，或等计划任务补跑"})
    else:
        bad = []
        for key, label in (("maa_rc", "MAA 日常"), ("sanity_rc", "理智读数"),
                           ("depot_rc", "仓库读数"), ("ledger_rc", "账本结算")):
            v = ent.get(key)
            if v not in (None, 0):
                bad.append(f"{label} rc={v}")
        if ent.get("ok") is False or bad:
            _fixed = ent.get("repaired_at")
            out.append({"level": "info" if _fixed else "err",
                        "title": "今日日常有步骤失败" + ("（已修复，明日生效）" if _fixed else ""),
                        "detail": ("；".join(bad) or "ok=false") +
                                  (("；" + str(ent.get("repaired_note"))) if _fixed and ent.get("repaired_note") else ""),
                        "hint": "" if _fixed else "看「日志」页与 scripts/daily-auto/运行日志.txt"})
        if ent.get("close") not in (None, "closed"):
            out.append({"level": "warn", "title": "雷电没关掉",
                        "detail": f"close={ent.get('close')}", "hint": "手动关雷电，或下次日常会再关"})

    # 2) 今日凌晨基建换班
    night = _tail_jsonl(DATA_DIR / "night_run.jsonl")
    nent = next((e for e in reversed(night) if str(e.get("date")) == today), None)
    if nent is None:
        out.append({"level": "info", "title": "凌晨换班没有记录",
                    "detail": f"{today} 02:00 未运行（设计如此：2 点不在线就不补跑）", "hint": ""})
    elif nent.get("ok") is False or str(nent.get("stage")) in ("timeout", "stalled", "append", "custom-file"):
        out.append({"level": "err", "title": "凌晨基建换班失败",
                    "detail": f"stage={nent.get('stage')} 用时={nent.get('elapsed')}s",
                    "hint": "B 班可能没换成；看 night-infrast 日志与截图"})

    # 3) 今天的跑关报告：被跳过的关 / 卡住
    rep = [e for e in _tail_jsonl(DATA_DIR / "run_report.jsonl")
           if str(e.get("ts", "")).startswith(today)]
    skipped = [e.get("skipped_stage") for e in rep if e.get("stage") == "preflight"]
    if skipped:
        out.append({"level": "warn", "title": "有 %d 关被跳过（MAA 不认识）" % len(skipped),
                    "detail": "、".join(str(s) for s in skipped[:8]),
                    "hint": "活动 EX 请用「活动 EX」页的自动链（Copilot 能打，Fight 不能）"})
    stalled = [e for e in rep if e.get("stage") in ("stalled", "timeout")]
    if stalled:
        e = stalled[-1]
        out.append({"level": "err", "title": "日常跑到一半卡住",
                    "detail": "stage=%s 用时=%ss %s" % (e.get("stage"), e.get("elapsed"),
                                                   ("命中卡死告警 %s 次" % e.get("hits")) if e.get("hits") else ""),
                    "hint": "多半是基建选人卡住（指定干员心情/占用），看长期方案"})

    # 4) 账本：最近一条是否作废
    led = _tail_jsonl(DATA_DIR / "revenue_ledger.jsonl", 40)
    if led:
        e = led[-1]
        if e.get("invalid") or e.get("depot_incomplete"):
            _fixed = e.get("repaired_at")
            _detail = "；".join(e.get("issues") or [e.get("invalid_reason") or "仓库读数不全"])
            if _fixed and e.get("repaired_note"):
                _detail += "；" + str(e["repaired_note"])
            out.append({"level": "info" if _fixed else "err",
                        "title": "收益账本最近一条已作废" + ("（已修复基线）" if _fixed else ""),
                        "detail": _detail,
                        "hint": "" if _fixed else "仓库页确认无误后重跑 depot + settle"})

    # 5) 计划 vs 实际（今天该打的关有没有排进队列）
    plan = _load_json(DATA_DIR / "weekly_plan.json") or {}
    day = next((d for d in (plan.get("daily") or []) if d.get("date") == today), None)
    if day is None:
        if ent is not None and ent.get("ok"):
            out.append({"level": "info",
                        "title": "周计划已切到下周（今天不在区间内）",
                        "detail": f"{today} 的日常已在 {str(ent.get('ts'))[11:16]} 跑完；"
                                  f"当前计划覆盖 {plan.get('range') or '下周'}",
                        "hint": ""})
        else:
            out.append({"level": "warn", "title": "今天不在周计划里",
                        "detail": f"weekly_plan.json 没有 {today}",
                        "hint": "长草页「生成/刷新计划」"})
    else:
        want = {k: int(v) for k, v in (day.get("runs") or {}).items() if v}
        fights = sum(1 for e in rep if e.get("stage") == "ok" or e.get("tids"))
        if want and fights == 0 and not _before_daily:
            out.append({"level": "err", "title": "计划今天要刷 %d 关，但没有任何跑关记录" % len(want),
                        "detail": "、".join("%s×%d" % kv for kv in want.items()),
                        "hint": "看「日志」页里的 maa_week 输出"})

    # 6) 活动 EX 进度
    st = _load_json(ROOT / "docs" / "state.json") or {}
    for key, prog in (st.get("progress") or {}).items():
        if not key.startswith("event_"):
            continue
        ev_id = key[len("event_"):]
        ev = _load_json(DATA_DIR / ("event_%s.json" % ev_id)) or {}
        ex_left = int(prog.get("ex_pending") or 0)
        raid_left = int(prog.get("raid_pending") or 0)
        end = str(ev.get("end") or "")[:10] or "?"
        if ex_left or raid_left:
            _det = "活动结束 %s" % end
            _rp = _today_raid_progress()
            if _rp["planned"]:
                _det += "；今日计划突袭已通 %d/%d" % (
                    len(set(_rp["planned"]) & _rp["done"]), len(_rp["planned"]))
            out.append({"level": "warn" if end > today else "err",
                        "title": "%s：EX 还剩 %d 关 / 突袭 %d 关" % (ev.get("name") or ev_id, ex_left, raid_left),
                        "detail": _det,
                        "hint": "已并入「一键长草」：14:00 日常跑完自动补打（也可在长草页点「手动补跑一次」）"})

    # 7) 理智读数新鲜度
    san = _load_json(DATA_DIR / "sanity.json") or {}
    ts = str(san.get("current_sanity_ts") or "")
    if not ts:
        out.append({"level": "warn", "title": "没有理智读数", "detail": "sanity.json 缺 current_sanity_ts",
                    "hint": "长草页没跑成功？或手动 maa_week sanity"})
    else:
        try:
            age = (datetime.datetime.now() -
                   datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
            if age > 30:
                out.append({"level": "warn", "title": "理智读数已 %.0f 小时未更新" % age,
                            "detail": "当前记录 %s（%s）" % (san.get("current_sanity"), ts),
                            "hint": "账本会按估算记；跑一次日常即可刷新"})
        except Exception:  # noqa: BLE001
            pass

    order = {"err": 0, "warn": 1, "info": 2}
    out.sort(key=lambda x: order.get(x["level"], 9))
    return out


def _today_raid_progress() -> dict:
    """今日计划里的突袭 vs state.json 已通 → {planned, done, left}。

    为什么单独算：`daily_run.ok` 只代表 MAA 日常主体跑完；突袭是 ex_auto 补打的，
    两者不是一回事（2026-10-19 用户指出「说今天跑完了、可突袭又写没打」）。
    """
    plan = _load_json(DATA_DIR / "weekly_plan.json") or {}
    today = time.strftime("%Y-%m-%d")
    day = next((d for d in (plan.get("daily") or []) if str(d.get("date")) == today), None)
    planned = [str(x) for x in ((day or {}).get("raids") or []) if x]
    st = _load_json(ROOT / "docs" / "state.json") or {}
    done: set = set()
    for key, prog in (st.get("progress") or {}).items():
        if not str(key).startswith("event_"):
            continue
        done |= {str(x) for x in (prog.get("raid_clear_done") or [])}
    left = [x for x in planned if x not in done]
    return {"planned": planned, "done": done, "left": left}


class App(FluentWindow):

    def __init__(self):
        super().__init__()
        self.cfg = load_settings()
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.data = None
        self.binding: list[dict] = []
        self._busy = False
        self._gacha_records: list[dict] = []
        self._gacha_all: list[dict] = []
        self._gacha_view = "6star"
        self.attendance: dict | None = None
        self._shortcuts: list = []          # QShortcut 必须留引用，否则会被 GC

        self._init_window()
        self._build_pages()
        self._apply_theme(self.cfg.get("theme", "auto"))
        self._apply_saved_cred()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain)
        self.timer.start(120)

        # 偏离提醒：每 60s 重算一次（定时任务可能刚更新了留痕文件）
        self.timer_alert = QTimer(self)
        self.timer_alert.timeout.connect(self._render_alerts)
        self.timer_alert.start(60_000)

        self._auto_queue: list[str] = []
        QTimer.singleShot(900, self._auto_start)   # 窗口出来后自动登录

    # ---------------- 窗口 ----------------
    def _init_window(self):
        self.setWindowTitle(APP_NAME)
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
            (self.pg_raw, FI.CODE, "原始 JSON"),
        ):
            self.addSubInterface(pg, icon, text)

        # 森空岛签到：直接做进左侧界面 —— 一个「签到 / 今日已签到」按键 + 一行本月天数小字
        # （NavigationUserCard：title=按键文字，subtitle=下面那行小字；已签到时置灰不可点）
        self.nav_checkin = self.navigationInterface.addUserCard(
            "navCheckin", FI.ACCEPT, "签到", "本月已签到 — 天",
            onClick=lambda *_: self.checkin(), position=NavigationItemPosition.BOTTOM)
        self.nav_checkin.setToolTip("森空岛每日签到（登录后可用）")
        self._render_checkin(None)          # 初始态：未登录

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

        # 浏览器式刷新：重读本地文件 + 重绘当前页（已登录时顺带重拉森空岛）；快捷键 F5 / Ctrl+R
        self.btn_reload = qfw.TransparentToolButton(FI.SYNC, self)
        self.btn_reload.setToolTip("刷新（重新读取本地数据/日志，已登录同时重拉森空岛）　F5")
        self.btn_reload.clicked.connect(self.reload_all)
        if not self._put_in_titlebar(self.btn_reload):
            self.btn_reload.setParent(self.pg_account)
        for _seq in ("F5", "Ctrl+R"):
            try:
                _sc = QShortcut(QKeySequence(_seq), self)
                _sc.activated.connect(self.reload_all)
                self._shortcuts.append(_sc)
            except Exception:  # noqa: BLE001
                pass

        self._build_account()
        self._build_gacha()
        self._build_recruit()
        self._build_longcao()
        self._build_log()
        self._placeholder("未登录 —— 去「账号」页登录（或点「载入样例数据」预览）。")
        self._gacha_local_initial()

    def _placeholder(self, text: str):
        for pg, keep in ((self.pg_overview, False), (self.pg_oper, False), (self.pg_base, False),
                         (self.pg_record, False), (self.pg_raw, False)):
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
        self.cb_mode.currentIndexChanged.connect(lambda _: self._update_login_mode())
        self._update_login_mode()

        self.lbl_acct = qfw.BodyLabel("未登录")
        register_color(self.lbl_acct, "muted")
        login.add(self.lbl_acct)

        r3 = login.row()
        self.sw_remember = qfw.SwitchButton()
        self.sw_remember.setChecked(bool(self.cfg.get("remember", True)))
        r3.addWidget(self.sw_remember)
        r3.addWidget(qfw.BodyLabel("记住手机号"))
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
        b_fix = btn("载入样例数据", FI.DOCUMENT)
        b_fix.clicked.connect(self.load_fixture)
        r4.addWidget(b_fix)
        b_ff = btn("从火狐导入抽卡凭证", FI.GLOBE)
        b_ff.clicked.connect(self._gacha_import_firefox)
        r4.addWidget(b_ff)
        r4.addStretch(1)
        data.add(note("森空岛签到已挪到左侧导航（「签到」按键，下面显示本月已签天数）。"))
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
                # 列宽按**显示宽度**对齐（等宽字体下中文占 2 列，str.ljust 会错位）
                W = (26, 5, 7, 7, 8)
                lines = [f"owned 来源={src}（{len(owned)} 人）　词条：{'、'.join(tags)}", ""]
                lines.append(dpad("词条组合", W[0]) + dpad("池", W[1], ">") +
                             dpad("未拥有", W[2], ">") + dpad("P(新)", W[3], ">") +
                             dpad("星级", W[4], ">") + "  未拥有干员")
                lines.append("-" * (sum(W) + 2 + 24))
                for r in rows:
                    star = f"{r['rare_min']}~{r['rare_max']}"
                    lines.append(dpad(dcut("+".join(r["tags"]), W[0]), W[0]) +
                                 dpad(r["size"], W[1], ">") + dpad(r["unowned"], W[2], ">") +
                                 dpad(f"{r['p_new']:.2f}", W[3], ">") + dpad(star, W[4], ">") +
                                 "  " + "、".join(r["unowned_names"]))
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

        # 最上面：偏离提醒（今天该做什么没做、哪一步失败、账本作废、读数过期…）
        self.sec_alert = Section("⚠ 需要处理")
        pg.add(self.sec_alert)
        self._render_alerts()

        # 顶部操作台：主操作 + 快捷工具全放在最上面（原先把「快捷工具」沉在页面最底部，不顺手）
        ops = Section("操作")
        r1 = ops.row()
        for text, fn, icon in (("生成/刷新计划", self._lc_gen_plan, FI.SYNC),
                               ("写 MAA 配置", self._lc_write_maa, FI.SAVE),
                               ("直驱跑一键长草", self._lc_run, FI.PLAY)):
            b = btn(text, icon, primary=(icon == FI.PLAY))
            b.clicked.connect(lambda _=False, f=fn: f())
            r1.addWidget(b)
        r1.addStretch(1)

        r2 = ops.row()
        r2.addWidget(register_color(qfw.CaptionLabel("快捷工具"), "muted"))
        for text, fn, icon in (("启动游戏", self._lc_start_game, FI.PLAY),
                               ("打开 MAA", self._lc_open_maa, FI.ROBOT),
                               ("生成汇总网页", self._lc_build_site, FI.DOCUMENT),
                               ("打开汇总网页", self._lc_open_site, FI.GLOBE),
                               ("刷新计划", self._render_longcao, FI.SYNC)):
            b = btn(text, icon)
            b.clicked.connect(lambda _=False, f=fn: f())
            r2.addWidget(b)
        r2.addStretch(1)
        ops.add(note("会操作 MAA 与游戏，均需二次确认。基建已交回 MAA 自带的「队列轮换」"
                     "（队列里含 Infrast 任务，无需本机脚本）"))
        pg.add(ops)

        self.sec_longcao = Section("计划")
        pg.add(self.sec_longcao)

        self._build_ex_section()    # 活动 EX 并进「一键长草」：日常跑完自动补打，这里只看进度
        self._render_longcao()      # 建页时先填一次，切过来即可看到

    def reload_all(self):
        """浏览器式刷新（标题栏 ↻ / F5 / Ctrl+R）。

        · 重读**本地文件**（weekly_plan / state.json / 运行日志 / 账本）并重绘当前页；
        · 已登录且当前没有取数任务时，顺带重拉一次森空岛（等同「账号 → 刷新数据」）；
        · 不做任何写操作，纯刷新。
        """
        w = self.stackedWidget.currentWidget()
        try:
            # 「需要处理」始终重算（它读 daily_run / 账本 / state.json，定时任务随时可能更新）
            self._render_alerts()
            if w is self.pg_longcao:
                self._render_longcao()
                self._render_ex()
            elif self.data:
                s = self.data.get("status") or {}
                chars = self.data.get("chars") or []
                im = self.data.get("charInfoMap") or {}
                if w is self.pg_overview:
                    self._render_overview(s, chars, self.data)
                elif w is self.pg_oper:
                    self._render_opers(chars, im)
                elif w is self.pg_base:
                    self._render_base(self.data.get("building") or {}, im)
                elif w is self.pg_recruit:
                    self._render_recruit_info(self.data.get("recruit") or [])
                elif w is self.pg_record:
                    self._render_records(self.data)
                elif w is self.pg_raw:
                    self._render_raw(self.data)
            elif w is self.pg_gacha:
                self._gacha_local_initial()
        except Exception as e:  # noqa: BLE001
            self.log("刷新失败：%r" % e, "err")
            self._toast("err", "刷新失败", str(e)[:120])
            return

        # 已登录才重拉远端；正在取数就只刷本地，避免两个 worker 打架
        cfg = core.load_config()
        if cfg.get("cred") and not self._busy:
            self.log("已重读本地数据，正在重拉森空岛…", "dim")
            self.refresh()
        else:
            self._toast("ok", "已刷新", "本地数据已重读 %s" % time.strftime("%H:%M:%S"))

    def _on_page_changed(self, index: int):
        w = self.stackedWidget.currentWidget()
        if w is self.pg_longcao:
            self._render_alerts()
            self._render_longcao()
            self._render_ex()

    # ---------------- 偏离提醒 ----------------
    def _render_alerts(self):
        """把 collect_alerts() 渲染成卡片（红=必须处理 / 橙=偏离 / 灰=提示）。"""
        sec = getattr(self, "sec_alert", None)
        if sec is None:
            return
        while sec.vbox.count() > 1:
            item = sec.vbox.takeAt(1)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        try:
            alerts = collect_alerts()
        except Exception as e:  # noqa: BLE001
            sec.add(note("告警收集失败：%r" % e))
            return
        if not alerts:
            ok = qfw.BodyLabel("一切正常：今天该跑的都跑了，没有失败步骤。")
            ok.setTextColor(QColor("#4CAF7D" if is_dark() else "#1A7F37"))
            sec.add(ok)
            return
        colors = {"err": "#E0685A" if is_dark() else "#C03A2B",
                  "warn": "#D9A441" if is_dark() else "#A9741A",
                  "info": pal()["muted"]}
        for a in alerts[:3]:
            lab = qfw.BodyLabel("● %s —— %s" % (a["title"], a.get("detail") or ""))
            lab.setWordWrap(True)
            lab.setTextColor(QColor(colors.get(a["level"], colors["info"])))
            sec.add(lab)
            if a.get("hint"):
                h = qfw.CaptionLabel("　→ " + a["hint"])
                h.setWordWrap(True)
                register_color(h, "muted")
                sec.add(h)
        if len(alerts) > 8:
            sec.add(note("…还有 %d 条（看「日志」页 / 各留痕文件）" % (len(alerts) - 3)))

    # ---------------- 长草页：可视化重排 ----------------
    def _clear_section(self, sec):
        while sec.vbox.count() > 1:
            item = sec.vbox.takeAt(1)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _fold(self, sec, title: str, build, opened: bool = False):
        """可折叠块：一行标题按钮 + 内容（默认收起），把「明细」从主视图里收走。"""
        btn = qfw.PushButton(("▾  " if opened else "▸  ") + title)
        btn.setMinimumHeight(32)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(8, 6, 0, 0)
        v.setSpacing(8)
        body.setVisible(opened)

        def _toggle(_=False):
            vis = not body.isVisible()
            body.setVisible(vis)
            btn.setText(("▾  " if vis else "▸  ") + title)

        btn.clicked.connect(_toggle)
        sec.add(btn)
        sec.add(body)
        build(v)
        return body

    def _day_card(self, d) -> QWidget:
        """一天的迷你卡片：日期 + 理智大字 + 关卡（替代原来 7 行的宽表）。"""
        card = GameCard()
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(3)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        lab = qfw.StrongBodyLabel("%s %s" % (str(d.get("date", ""))[5:], d.get("dow", "")))
        register_color(lab, "title")
        top.addWidget(lab)
        if str(d.get("date")) == time.strftime("%Y-%m-%d"):
            tag = qfw.CaptionLabel("今天")
            tag.setTextColor(QColor(pal()["accent"]))
            top.addWidget(tag)
        top.addStretch(1)
        v.addLayout(top)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        big = qfw.SubtitleLabel(str(int(d.get("sanity") or 0)))
        f = QFont()
        f.setPixelSize(22)
        f.setBold(True)
        big.setFont(f)
        register_color(big, "title")
        row.addWidget(big)
        cap = qfw.CaptionLabel("理智" + ("　超上限" if d.get("over") else ""))
        register_color(cap, "muted")
        row.addWidget(cap)
        row.addStretch(1)
        v.addLayout(row)

        runs = d.get("runs") or {}
        txt = "、".join("%s×%s" % (k, n) for k, n in runs.items()) or "—"
        lab2 = qfw.CaptionLabel(txt)
        lab2.setWordWrap(True)
        register_color(lab2, "muted")
        v.addWidget(lab2)
        if d.get("raids"):
            _rt = "突袭：" + "、".join(d["raids"])
            if str(d.get("date")) == time.strftime("%Y-%m-%d"):
                _rp = _today_raid_progress()
                if _rp["planned"]:
                    _rt += "（已通 %d/%d）" % (len(set(_rp["planned"]) & _rp["done"]),
                                              len(_rp["planned"]))
            r = qfw.CaptionLabel(_rt)
            r.setWordWrap(True)
            r.setTextColor(QColor(pal()["accent"]))
            v.addWidget(r)
        return card

    def _ex_counts(self) -> tuple[int, int]:
        """所有活动进度里的 EX 普通：已通 / 总数。"""
        st = _load_json(ROOT / "docs" / "state.json") or {}
        prog_all = st.get("progress") or {}
        done = total = 0
        for ev in self._ex_events():
            codes = [s.get("code") for s in (ev["data"].get("ex_stages") or []) if s.get("code")]
            if not codes:
                continue
            prog = prog_all.get("event_%s" % ev["id"]) or {}
            done += len([c for c in codes if c in set(prog.get("ex_clear_done") or [])])
            total += len(codes)
        return done, total

    def _render_longcao(self):
        sec = self.sec_longcao
        self._clear_section(sec)
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

        # 头部：一行小字（周 + 范围 + 生成时间）
        sec.add(note(f"{plan.get('week', '—')}　{plan.get('range', '—')}"
                     f"　·　生成于 {plan.get('generated_at', '—')}（{plan.get('by', '—')}）"))

        try:
            sys.path.insert(0, str(ROOT / "scheduling" / "tools"))
            from plan_util import distribute_daily, session_advice, weekly_summary
            daily = distribute_daily(plan)
            summary = weekly_summary(plan, daily) if daily else None
            advice = session_advice(plan, daily) if daily else []
        except Exception:  # noqa: BLE001
            daily, summary, advice = [], None, []

        dl = _tail_jsonl(DATA_DIR / "daily_run.jsonl", 300)
        de = next((e for e in reversed(dl) if str(e.get("date")) == time.strftime("%Y-%m-%d")), None)
        _n = datetime.datetime.now()
        if de is None:
            daily_txt = "待跑 14:00" if (_n.hour, _n.minute) < (14, 10) else "未跑"
        elif de.get("ok"):
            _rp = _today_raid_progress()
            if _rp["planned"] and _rp["left"]:
                # 日常主体 ✅，但计划里的突袭没打完 → 别显示成一个光秃秃的「跑完了」
                daily_txt = "⚠ %s 部分完成" % str(de.get("ts"))[11:16]
            else:
                daily_txt = "✅ " + str(de.get("ts"))[11:16]
        else:
            daily_txt = "❌ " + str(de.get("ts"))[11:16]

        # 今天在不在计划里（不满足就一句红字，不再整段）
        try:
            sys.path.insert(0, str(ROOT / "scheduling" / "tools"))
            from plan_util import plan_day
            _today = time.strftime("%Y-%m-%d")
            _d, _st = plan_day(plan, _today)
            if _st != "ok":
                _done_today = bool(de is not None and de.get("ok"))
                if _done_today:
                    warn = qfw.BodyLabel(
                        f"周刷新已把计划切到 {plan.get('range') or '下周'}；"
                        f"今天 {_today} 的日常已完成，不需要再操作。")
                    register_color(warn, "muted")
                else:
                    warn = qfw.BodyLabel(f"⚠ 今天 {_today} 不在计划里 —— 点「生成/刷新计划」重新生成")
                    warn.setTextColor(QColor("#E0685A" if is_dark() else "#C03A2B"))
                warn.setWordWrap(True)
                sec.add(warn)
        except Exception:  # noqa: BLE001
            pass

        # 四张数字磁贴（原来三张灰字 + 一段长文字）
        td = next((x for x in daily if str(x.get("date")) == time.strftime("%Y-%m-%d")), None)
        ex_done, ex_total = self._ex_counts()
        sec.add(self._stat_row([
            ("今日日常", daily_txt),
            ("今日理智", (td or {}).get("sanity", "—")),
            ("本周已排 / 预算", "%s / %s" % ((summary or {}).get("total", "—"),
                                          (summary or {}).get("avail",
                                                              budget.get("sanity_natural", "—")))),
            ("活动 EX 普通", f"{ex_done}/{ex_total}" if ex_total else "—"),
        ]))
        _rp = _today_raid_progress()
        if de is not None and de.get("ok") and _rp["planned"] and _rp["left"]:
            _done_n = len(set(_rp["planned"]) & _rp["done"])
            sec.add(note("今日计划含突袭 %d 关，已通 %d 关，剩 %d 关未打（%s）。"
                         "「今日日常」只代表 MAA 日常主体完成，突袭由 EX 自动链补打；"
                         "两者都完成才算今天全部跑完。"
                         % (len(_rp["planned"]), _done_n, len(_rp["left"]),
                            "、".join(_rp["left"][:4]) + ("…" if len(_rp["left"]) > 4 else ""))))
        if daily and summary:
            sec.add(self._progress_block(summary))

        # 每日卡片：3 列网格（原来是一张 7 行的宽表，把页面撑爆）
        if daily:
            holder = QWidget()
            grid = QGridLayout(holder)
            grid.setContentsMargins(0, 4, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            for i, d in enumerate(daily):
                grid.addWidget(self._day_card(d), i // 3, i % 3)
            for c in range(3):
                grid.setColumnStretch(c, 1)
            sec.add(holder)
        if advice:
            lines = []
            for a in advice[:3]:
                if isinstance(a, dict):
                    san = a.get("sanity")
                    lines.append("%s %s：%s%s" % (
                        str(a.get("date", ""))[5:], a.get("dow", ""), a.get("note") or "",
                        "（理智 %s）" % san if san else ""))
                else:
                    lines.append(str(a))
            sec.add(note("💡 " + "；".join(lines)))

        # 折叠区：明细收进去
        tasks = plan.get("tasks") or []
        if tasks:
            def _build_tasks(v, tasks=tasks):
                t = make_table(["#", "任务", "参数"], stretch=(1,), wrap=True)
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
                t.setMinimumHeight(min(320, 40 + 30 * len(rows)))
                v.addWidget(t)
            self._fold(sec, "本周任务清单（%d 条）" % len(tasks), _build_tasks)

        tr = plan.get("training")
        if tr:
            def _build_train(v, tr=tr):
                v.addWidget(self._kv("目标干员", "、".join(tr.get("targets", [])) or "—"))
                v.addWidget(self._stat_row([
                    ("总缺口（理智）", str(tr.get("total_sanity", "—"))),
                    ("本周投入（理智）", str(tr.get("week_sanity", "—"))),
                    ("还需", f"{tr['need_weeks']} 周" if tr.get("need_weeks") else "—"),
                ]))
                if tr.get("material_sanity") is not None:
                    v.addWidget(note(f"其中 材料 {tr.get('material_sanity')} + "
                                     f"龙门币 {tr.get('lmd_sanity')}（理智折算）"))
            self._fold(sec, "培养目标", _build_train)

        notes = (plan.get("rationale") or {}).get("notes") or []
        if notes:
            def _build_notes(v, notes=notes):
                for n in notes:
                    v.addWidget(self._bullet(n))
            self._fold(sec, "决策依据（%d 条）" % len(notes), _build_notes)

    def _stat_row(self, pairs) -> QWidget:
        """一排数字磁贴（把原本的灰色文字行变成可视卡片）。"""
        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        for title, value in pairs:
            h.addWidget(StatTile(str(title), str(value)), 1)
        return holder

    def _progress_block(self, summary) -> QWidget:
        """本周理智进度：已排 / 预算 + 进度条（原先是「周合计」一行灰字）。"""
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 2, 0, 2)
        v.setSpacing(6)
        total, avail = int(summary.get("total") or 0), int(summary.get("avail") or 0)
        gap = int(summary.get("gap") or 0)
        lab = qfw.BodyLabel(
            f"本周已排理智 {total} / 预算 {avail}"
            f"（自然 {summary.get('natural')} + 周药 {summary.get('weekly_potion')}）"
            + (f"　缺口 {gap}（需吃理智药）" if gap else "　预算够"))
        lab.setWordWrap(True)
        v.addWidget(lab)
        bar = qfw.ProgressBar()
        bar.setRange(0, max(1, avail))
        bar.setValue(min(total, max(1, avail)))
        try:
            bar.setCustomBarColor(QColor(pal()["accent"]), QColor(pal()["accent"]))
        except Exception:  # noqa: BLE001
            pass
        v.addWidget(bar)
        return holder

    def _bullet(self, text) -> QWidget:
        """决策依据的条目：金色圆点 + 展开的正文（原来是灰色小字）。"""
        if isinstance(text, dict):
            text = text.get("note") or json.dumps(text, ensure_ascii=False)
        lab = qfw.BodyLabel("◆  " + str(text))
        lab.setWordWrap(True)
        register_color(lab, "title")
        return lab

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

    def _scroll_list(self, items, max_h: int = 190, expand: bool = False) -> QWidget:
        """把一组行塞进「内部滚动」的小盒子：内容少时贴合内容、超过上限才出内部滚动条。

        用于行数不定且可能很长的列表（剿灭 records / 保全 / 肉鸽），避免把整张卡片撑高。
        expand=True：不限高、随卡片一起长（占满分给它的高度）；False：高不过 max_h。
        """
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 4, 0)
        v.setSpacing(4)
        for w in items:
            v.addWidget(w)
        v.addStretch(1)
        sa = qfw.ScrollArea()
        sa.setWidget(holder)
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if expand:
            sa.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        else:
            sa.setMaximumHeight(int(max_h))
            sa.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        sa.setStyleSheet("background:transparent;")
        try:
            sa.viewport().setStyleSheet("background:transparent;")
        except Exception:  # noqa: BLE001
            pass
        return sa

    # ---------------- 日志页 ----------------
    # ---------------- 活动 EX（并进「一键长草」：默认全自动，这里只看 + 手动兜底） ----------------
    def _ex_events(self) -> list[dict]:
        """扫 scheduling/data/event_<id>.json，返回有 EX 关的活动。"""
        out = []
        for p in sorted(DATA_DIR.glob("event_*.json")):
            d = _load_json(p) or {}
            if not (d.get("ex_stages") or []):
                continue
            out.append({"id": p.stem[len("event_"):], "name": d.get("name") or p.stem,
                        "end": str(d.get("end") or "")[:10], "data": d})
        return out

    def _build_ex_section(self):
        """把「活动 EX」做成「长草」页里的一个区块：默认由 14:00 日常自动补打，无需点按钮。"""
        pg = self.pg_longcao
        sec = Section("活动 EX（已并进一键长草 · 自动补打）")
        pg.add(sec)
        self.sec_ex = sec

        evs = self._ex_events()
        if not evs:
            sec.add(note("scheduling/data 里没有带 ex_stages 的活动 —— 没有活动时这一块是空的。"))
            self.tbl_ex = None
            self.txt_ex = None
            self.btn_ex_stop = None
            self._ex_proc = None
            return

        r = sec.row()
        r.addWidget(register_color(qfw.CaptionLabel("活动"), "muted"))
        self.cb_ex_event = qfw.ComboBox()
        self.cb_ex_event.setMinimumWidth(220)
        for ev in evs:
            self.cb_ex_event.addItem("%s（%s，结束 %s）" % (ev["name"], ev["id"], ev["end"]), userData=ev["id"])
        self.cb_ex_event.currentIndexChanged.connect(lambda _i: self._render_ex())
        r.addWidget(self.cb_ex_event)
        r.addStretch(1)
        self.btn_ex_stop = btn("停止（手动兜底）", FI.CANCEL)
        self.btn_ex_stop.clicked.connect(self._ex_stop)
        self.btn_ex_stop.setEnabled(False)
        self.btn_ex_stop.setVisible(False)
        r.addWidget(self.btn_ex_stop)

        sec.add(note("平时不用点任何东西：每日 14:00「直驱跑一键长草」跑完日常后会自动扫未通的 EX 并打掉"
                     "（全员精二作业优先，不行换单核/挂件兼容）。这里只显示进度；"
                     "只有想立刻补一次时才点下面的「手动补跑」。"))
        self.lbl_ex = qfw.BodyLabel("—")
        sec.add(self.lbl_ex)
        self.bar_ex = qfw.ProgressBar()
        self.bar_ex.setRange(0, 1)
        self.bar_ex.setValue(0)
        try:
            self.bar_ex.setCustomBarColor(QColor(pal()["accent"]), QColor(pal()["accent"]))
        except Exception:  # noqa: BLE001
            pass
        sec.add(self.bar_ex)

        self.tbl_ex = make_table(["关卡", "名称", "理智", "普通", "突袭"], stretch=(0, 1, 0, 0, 0))
        self.tbl_ex.setMinimumHeight(220)
        self._fold(sec, "关卡明细", lambda v: v.addWidget(self.tbl_ex))

        r2 = sec.row()
        b = btn("手动补跑一次", FI.PLAY)
        b.clicked.connect(lambda: self._ex_start(False))
        r2.addWidget(b)
        b = btn("只看计划（不动设备）", FI.DOCUMENT)
        b.clicked.connect(lambda: self._ex_start(True))
        r2.addWidget(b)
        r2.addStretch(1)

        self.txt_ex = qfw.TextEdit()
        self.txt_ex.setReadOnly(True)
        self.txt_ex.setFont(QFont("Consolas", 10))
        self.txt_ex.setMinimumHeight(120)
        self.txt_ex.setVisible(False)     # 平时收起，跑的时候展开
        sec.add(self.txt_ex)
        self._ex_proc = None
        self._render_ex()

    def _ex_log(self, line: str):
        box = getattr(self, "txt_ex", None)
        if box is None:
            return
        tag = ("ok" if ("通过 ✅" in line or "已在 EX" in line or "已进入 EX" in line)
               else "err" if ("失败" in line or "!!" in line or "EXC" in line)
               else "dim")
        colors = {"ok": "#4CAF7D" if is_dark() else "#1A7F37",
                  "err": "#E0685A" if is_dark() else "#C03A2B",
                  "dim": pal()["muted"]}
        text = html.escape(line).replace(" ", "&nbsp;")
        color = colors.get(tag)
        box.append('<span style="color:%s">%s</span>' % (color, text) if color else text)
        box.verticalScrollBar().setValue(box.verticalScrollBar().maximum())

    def _ex_selected(self):
        """当前下拉选的活动 id（只用于展示进度表；自动跑不依赖它）。"""
        i = self.cb_ex_event.currentIndex()
        ev_id = self.cb_ex_event.currentData() if hasattr(self.cb_ex_event, "currentData") else None
        if not ev_id:
            evs = self._ex_events()
            ev_id = evs[i]["id"] if 0 <= i < len(evs) else ""
        return ev_id, "ex", 0

    def _ex_start(self, dry: bool):
        if self._ex_proc is not None:
            self._toast("warn", "正在跑", "先等这一轮结束，或点「停止」。")
            return
        what = "自动发现并补打未通的 EX 关"
        if not dry:
            r = QMessageBox.question(self, "确认", "现在手动补跑一次？\n\n%s\n会拉起雷电并驱动游戏（单客户端）。"
                                     % what)
            if r != QMessageBox.Yes:
                return
        cmd = [sys.executable, str(ROOT / "scripts" / "event-copilot" / "ex_auto.py"),
               "--auto", "--with-raid", "--timeout", "900"]   # 突袭也一起（与 14:00 自动口径一致）
        if dry:
            cmd.append("--dry")
        self.txt_ex.clear()
        self.txt_ex.setVisible(True)
        self._ex_log("$ " + " ".join(cmd))
        self.btn_ex_stop.setVisible(True)
        self.btn_ex_stop.setEnabled(True)
        self.log("活动 EX 开始：%s" % what, "head")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        try:
            self._ex_proc = subprocess.Popen(
                cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env)
        except Exception as e:  # noqa: BLE001
            self._ex_proc = None
            self.btn_ex_stop.setEnabled(False)
            self._toast("err", "启动失败", repr(e))
            return

        def pump():
            proc = self._ex_proc
            try:
                for line in proc.stdout:  # type: ignore[union-attr]
                    self.q.put(("ex_log", line.rstrip()))
                rc = proc.wait()
            except Exception as e:  # noqa: BLE001
                self.q.put(("ex_log", "读取输出失败：%r" % e))
                rc = -1
            self.q.put(("ex_done", rc))

        threading.Thread(target=pump, daemon=True).start()

    def _ex_stop(self):
        p = self._ex_proc
        if p is None:
            return
        self._ex_log("!! 用户点了停止 → 终止子进程")
        try:
            p.terminate()
        except Exception:  # noqa: BLE001
            pass

    def _render_ex(self):
        """进度表：该活动所有 EX/突袭关 + 已通状态（读 docs/state.json + overview 取名）。"""
        tbl = getattr(self, "tbl_ex", None)
        if tbl is None:
            return
        ev_id, chain, _n = self._ex_selected()
        evs = {e["id"]: e for e in self._ex_events()}
        ev = evs.get(ev_id)
        if not ev:
            fill_table(tbl, [["—", "没有可选活动", "", "—", "scheduling/data/event_*.json 里没有 ex_stages"]])
            return
        st = _load_json(ROOT / "docs" / "state.json") or {}
        prog = ((st.get("progress") or {}).get("event_%s" % ev_id) or {})
        done_ex = set(prog.get("ex_clear_done") or [])
        done_raid = set(prog.get("raid_clear_done") or [])
        done_s = set(prog.get("s_clear_done") or [])
        names = _event_stage_names()          # code -> 名称（来自 MAA overview）
        d = ev["data"]
        rows = []
        for stg in (d.get("ex_stages") or []):
            code = stg.get("code")
            rows.append([code, names.get(code, ""), str(stg.get("sanity") or ""),
                         "✅" if code in done_ex else "未打",
                         "✅" if code in done_raid else "未打"])
        for stg in (d.get("s_stages") or []):
            code = stg.get("code")
            rows.append([code, names.get(code, ""), str(stg.get("sanity") or ""),
                         "✅" if code in done_s else "未打",
                         "✅" if code in (prog.get("s_raid_clear_done") or set()) else "未打"])
        if not rows:
            rows = [[ev_id, ev["name"], "", "—", "该活动没有 EX 关"]]
        fill_table(tbl, rows, sortable=False)
        for col, w in ((0, 110), (2, 60), (3, 70), (4, 70)):
            tbl.setColumnWidth(col, w)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        # 顶部一行进度：普通 x/total（+ 突袭 y/total）
        total = len(rows)
        done = sum(1 for r in rows if r[3] == "✅")
        rd = sum(1 for r in rows if r[4] == "✅")
        lbl = getattr(self, "lbl_ex", None)
        bar = getattr(self, "bar_ex", None)
        if lbl is not None:
            lbl.setText("%s：普通 %d/%d，突袭 %d/%d（结束 %s）%s" % (
                ev["name"], done, total, rd, total, ev.get("end") or "—",
                "　—— 普通已清完，接下来打突袭" if done == total and rd < total else ""))
        if bar is not None:
            bar.setRange(0, max(1, total))
            bar.setValue(done)

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

    def _update_login_mode(self):
        """登录方式为「密码」时隐藏「发送验证码」键，并同步密码框提示。"""
        is_code = self.cb_mode.currentText() == "验证码"
        self.btn_send.setVisible(is_code)
        self.ed_secret.setPlaceholderText("验证码" if is_code else "密码")

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
        for name in ("btn_refresh", "btn_login", "btn_gacha",
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
                elif kind == "oper_cost":
                    box = getattr(self, "q_result", None)
                    if box is not None:
                        box.setPlainText(payload)
                elif kind == "infra_check":
                    box = getattr(self, "inf_check", None)
                    if box is not None:
                        box.setPlainText(payload)
                elif kind == "ex_log":
                    self._ex_log(payload)
                elif kind == "ex_done":
                    self._ex_proc = None
                    self.btn_ex_stop.setEnabled(False)
                    self.btn_ex_stop.setVisible(False)
                    self._render_ex()
                    self._render_alerts()
                    ok = (payload == 0)
                    self._toast("ok" if ok else "err", "活动 EX 结束",
                                "退出码 %s%s" % (payload, "" if ok else "（看「活动 EX」页日志）"))
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
        if chars:
            core.save_config(uid=chars[0]["uid"])
        labels = [f"{c.get('nickName')}（{c.get('channelName')}）" for c in chars]
        tail = "" if len(chars) <= 1 else f"（共 {len(chars)} 个，默认用第一个）"
        self.log(f"绑定角色：{'、'.join(labels) or '无'}{tail}", "dim")

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
                             ("时装", str(skin_cnt)),
                             ("家具", str(furn))):
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
        info_map = data.get("charInfoMap") or {}
        own = {c.get("charId"): c for c in chars}
        if not assist:
            a.add(qfw.BodyLabel("无"))
        for x in assist:
            cid = x.get("charId", "")
            nm = (info_map.get(cid) or {}).get("name", cid)
            c = own.get(cid)
            if c:  # 与「干员」页同口径：专精依次为 S1/S2/S3
                specs = [s.get("specializeLevel", 0) for s in (c.get("skills") or [])]
                spec_txt = "/".join(str(v) for v in specs) if any(specs) else "—"
            else:  # 兜底：只有助战自带的单个专精 → 标出是哪个技能，避免「专3」歧义
                no = str(x.get("skillId", ""))[-1]
                spec_txt = (f"S{no}={x.get('specializeLevel', 0)}" if no.isdigit()
                            else str(x.get("specializeLevel", 0)))
            a.add(self._kv(nm, f"{ELITE.get(x.get('evolvePhase'), '')} Lv{x.get('level')} "
                               f"潜{x.get('potentialRank')} 技{x.get('mainSkillLvl')} 专精 {spec_txt}"))
        if assist:
            a.add(note("口径同「干员」页：技=技能等级(1-7)，专精依次为 S1/S2/S3"))
        pg.add(a)

    def _render_opers(self, chars, info_map):
        pg = self.pg_oper
        pg.clear()
        self._opers_chars = chars
        self._opers_map = info_map
        pg.add(qfw.TitleLabel("干员"))

        # 左半：**一个大白框**（干员总览）—— 筛选行 + 统计小字 + 总览表全在同一张卡里，
        # 不再出现「上半截白框、下半截裸表」的割裂布局。
        left = Section("干员总览")
        r = left.row()
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
        r.addStretch(1)

        r2 = left.row()          # 排序单独一行（左栏变窄后，三项挤一行会超宽）
        r2.addWidget(qfw.BodyLabel("排序"))
        self.cb_sort = qfw.ComboBox()
        self.cb_sort.addItems(["星级", "等级", "技能等级"])
        self.cb_sort.setFixedWidth(110)
        self.cb_sort.currentIndexChanged.connect(lambda _: self._fill_opers())
        r2.addWidget(self.cb_sort)
        r2.addStretch(1)
        self.lbl_oper = qfw.BodyLabel("")
        self.lbl_oper.setWordWrap(True)
        left.add(self.lbl_oper)
        left.add(note("技能等级 1–7 由三技能共享；专精列依次为 S1/S2/S3 各自等级；模组列 = 各模组当前等级"))

        self.tbl_oper = make_table(["星级", "名称", "职业", "等级", "潜能", "技能", "专精", "模组"],
                                   stretch=(1,))
        self.tbl_oper.horizontalHeader().setMinimumSectionSize(52)   # 列多，留窄些 → 整表不横向滚动
        self.tbl_oper.setMinimumHeight(320)
        left.vbox.addWidget(self.tbl_oper, 1)

        # 右：养成资源查询（左表偏窄会触发横向滚动 → 左 3 : 右 2）
        right = self._build_oper_query()
        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        h.addWidget(left, 3)
        h.addWidget(right, 2)
        pg.add(holder, 1)

        self._fill_opers()
        self._fill_query_opers()

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
        # 排序键补上**精英阶段**做次档：星级排序里同星级按 精英→等级，否则「精1 满级」会压过「精2」看着乱。
        if key == "等级":
            sortf = lambda c: (c.get("level", 0), c.get("evolvePhase", 0),
                               info(c).get("rarity", -1))
        elif key == "技能等级":
            sortf = lambda c: (c.get("mainSkillLvl", 0),
                               sum(x.get("specializeLevel", 0) for x in (c.get("skills") or [])),
                               c.get("evolvePhase", 0), info(c).get("rarity", -1))
        else:  # 星级：先稀有度，再精英，再等级
            sortf = lambda c: (info(c).get("rarity", -1), c.get("evolvePhase", 0),
                               c.get("level", 0))
        flt.sort(key=sortf, reverse=True)

        rows = []
        for c in flt:
            inf = info(c)
            specs = [x.get("specializeLevel", 0) for x in (c.get("skills") or [])]
            r = inf.get("rarity", -1)
            mlv = [int(e.get("level") or 0) for e in (c.get("equip") or []) if not e.get("locked")]
            rows.append([
                NumItem(f"{r + 1}★" if r >= 0 else "?", r),
                NumItem(inf.get("name", c.get("charId", "")), inf.get("name", "")),
                PROFESSIONS.get(inf.get("profession", ""), inf.get("profession", "")),
                NumItem(f"{ELITE.get(c.get('evolvePhase'), '')} Lv{c.get('level')}",
                        (c.get("evolvePhase", 0), c.get("level", 0))),
                f"潜{c.get('potentialRank')}",
                f"技{c.get('mainSkillLvl')}",
                "/".join(str(x) for x in specs) if any(specs) else "",
                NumItem("/".join(str(x) for x in mlv) if mlv else "", max(mlv) if mlv else 0),
            ])
        fill_table(self.tbl_oper, rows, sortable=False)   # 顺序由上面「排序」下拉决定，禁表头文本排序
        up = sum(1 for c in flt if c.get("evolvePhase", 0) >= 2)
        dist: dict = {}
        for c in flt:
            rr = info(c).get("rarity", -1)
            dist[rr] = dist.get(rr, 0) + 1
        dist_txt = "　".join(f"{rr + 1}★×{dist[rr]}" for rr in sorted(dist, reverse=True) if rr >= 0)
        self.lbl_oper.setText(f"筛选 {len(flt)} / {len(chars)}　精二 {up}　|　{dist_txt}")

    # ---------------- 干员 · 养成资源查询 ----------------
    def _build_oper_query(self) -> QWidget:
        """养成资源查询面板：选干员（**可输入搜索**）+ 目标（精英/等级/技能等级/三技能专精/模组）→ 算所需资源。

        调 `scheduling/tools/oper_cost.py`（官方表算需求、比仓库算缺口、折理智）；
        当前练度直接用 GUI 已拉的**森空岛**数据（不重新联网）。
        规则：**专精的前提是技能 7 级**（技能 <7 时专精锁 M0）；模组可选具体哪一个（干员常有多个）。
        """
        sec = Section("养成资源查询")
        self._mod_oc = None
        self._mod_uni = None
        self._q_mod_ids: list = []

        r1 = sec.row()
        r1.addWidget(qfw.BodyLabel("干员"))
        self.q_oper = qfw.EditableComboBox()                # 可输入搜索
        self.q_oper.setMinimumWidth(160)
        self.q_oper.currentIndexChanged.connect(lambda _: self._q_sync_cur())
        r1.addWidget(self.q_oper, 1)

        r2 = sec.row()
        r2.addWidget(qfw.BodyLabel("目标"))
        self.q_elite = qfw.ComboBox()
        self.q_elite.addItems(["精0", "精1", "精2"])
        self.q_elite.setFixedWidth(78)
        r2.addWidget(self.q_elite)
        r2.addWidget(qfw.BodyLabel("等级"))
        # 用 LineEdit + 整数校验：qfw.SpinBox 自绘的上下箭头会把数字盖住
        self.q_level = qfw.LineEdit()
        self.q_level.setValidator(QIntValidator(1, 90, self))
        self.q_level.setText("60")
        self.q_level.setFixedWidth(64)
        self.q_level.setAlignment(Qt.AlignCenter)
        r2.addWidget(self.q_level)
        r2.addStretch(1)

        r3 = sec.row()
        r3.addWidget(qfw.BodyLabel("技能"))
        self.q_skill = qfw.ComboBox()
        self.q_skill.addItems(["1", "4", "7"])
        self.q_skill.setCurrentText("7")
        self.q_skill.setFixedWidth(70)
        self.q_skill.currentIndexChanged.connect(lambda _: self._q_sync_mastery())
        r3.addWidget(self.q_skill)
        r3.addWidget(qfw.BodyLabel("专精"))
        self.q_ms = []
        for lab in ("S1", "S2", "S3"):
            r3.addWidget(qfw.BodyLabel(lab))
            cb = qfw.ComboBox()
            cb.addItems(["M0", "M1", "M2", "M3"])
            cb.setFixedWidth(66)
            r3.addWidget(cb)
            self.q_ms.append(cb)
        r3.addStretch(1)

        r4 = sec.row()                                      # 模组选具体哪一个（名字长 → 单独占一行）
        r4.addWidget(qfw.BodyLabel("模组"))
        self.q_mod_sel = qfw.ComboBox()
        self.q_mod_sel.setMinimumWidth(240)                 # 拉长，避免「模组名（未解锁）」被截断
        self.q_mod_sel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.q_mod_sel.currentIndexChanged.connect(lambda _: self._q_mod_enabled())
        r4.addWidget(self.q_mod_sel, 1)

        r5 = sec.row()
        r5.addWidget(qfw.BodyLabel("到"))
        self.q_mod = qfw.ComboBox()
        self.q_mod.addItems(["1", "2", "3"])
        self.q_mod.setCurrentIndex(2)
        self.q_mod.setFixedWidth(64)
        r5.addWidget(self.q_mod)
        b = btn("计算", FI.SEARCH, primary=True)
        b.clicked.connect(self._oper_query_run)
        r5.addWidget(b)
        r5.addStretch(1)

        self.q_cur = qfw.CaptionLabel("")
        self.q_cur.setWordWrap(True)
        register_color(self.q_cur, "muted")
        sec.add(self.q_cur)
        sec.add(note("读森空岛当前练度 → 只算「当前 → 目标」的剩余段；材料比仓库算缺口、折理智。专精需技能 7 级。"))

        self.q_result = qfw.TextEdit()
        self.q_result.setReadOnly(True)
        self.q_result.setFont(QFont("Consolas", 10))
        self.q_result.setMinimumHeight(300)
        sec.add(self.q_result)
        return sec

    def _q_modules(self):
        """懒加载官方模组表（只读一次）。→ (oper_cost 模块, uniequip 表)。"""
        if self._mod_uni is None:
            try:
                tools = str(ROOT / "scheduling" / "tools")
                if tools not in sys.path:
                    sys.path.insert(0, tools)
                import oper_cost as oc
                self._mod_oc = oc
                self._mod_uni = oc.load_modules()
            except Exception:  # noqa: BLE001
                self._mod_oc, self._mod_uni = None, {"equipDict": {}, "charEquip": {}}
        return self._mod_oc, self._mod_uni

    def _q_oc(self):
        """懒加载 oper_cost 模块（只读一次）。"""
        if self._mod_oc is None:
            try:
                tools = str(ROOT / "scheduling" / "tools")
                if tools not in sys.path:
                    sys.path.insert(0, tools)
                import oper_cost as oc
                self._mod_oc = oc
            except Exception:  # noqa: BLE001
                self._mod_oc = None
        return self._mod_oc

    def _q_chars_all(self) -> dict:
        """全量干员表（`character_table`，含未拥有）：charId → 条目。"""
        if getattr(self, "_q_chars", None) is None:
            oc = self._q_oc()
            try:
                self._q_chars = oc.load()[0] if oc else {}
            except Exception:  # noqa: BLE001
                self._q_chars = {}
        return self._q_chars

    def _q_all_names(self) -> set:
        """干员名集合（排除召唤物/装置等非干员条目）。"""
        out = set()
        for v in self._q_chars_all().values():
            if v.get("name") and v.get("profession") not in ("TOKEN", "TRAP"):
                out.add(v["name"])
        return out

    def _q_fill_modules(self, char_id, cur_equip):
        """按干员重建模组选择器（只列**可升级**模组，标当前等级/未解锁）。"""
        oc, uni = self._q_modules()
        mods = oc.module_list(uni, char_id or "") if oc else []
        cur_equip = cur_equip or {}
        self.q_mod_sel.blockSignals(True)
        self.q_mod_sel.clear()
        self._q_mod_ids = [None]
        self.q_mod_sel.addItem("（不练模组）")
        for m in mods:
            if not m.get("itemCost"):            # 初始模组不可升级 → 不列
                continue
            eid = m.get("uniEquipId")
            e = cur_equip.get(eid) or {}
            tag = "未解锁" if e.get("locked") else f"当前{int(e.get('level') or 0)}级"
            self.q_mod_sel.addItem(f"{m.get('uniEquipName')}（{tag}）")
            self._q_mod_ids.append(eid)
        self.q_mod_sel.setCurrentIndex(1 if len(self._q_mod_ids) > 1 else 0)
        self.q_mod_sel.blockSignals(False)
        self._q_mod_enabled()

    def _q_sync_mastery(self):
        """技能 <7 级时锁死专精（专精前提是 7 级）。"""
        ok = self.q_skill.currentText() == "7"
        for cb in self.q_ms:
            cb.setEnabled(ok)
            if not ok:
                cb.setCurrentIndex(0)

    def _q_mod_enabled(self):
        idx = self.q_mod_sel.currentIndex()
        self.q_mod.setEnabled(0 <= idx < len(self._q_mod_ids) and bool(self._q_mod_ids[idx]))

    def _fill_query_opers(self):
        """下拉含**全部干员**（未拥有的也能选/搜）：已拥有按星级↓ 排前，其余按名。"""
        chars = getattr(self, "_opers_chars", []) or []
        info_map = getattr(self, "_opers_map", {}) or {}
        owned = []
        for c in chars:
            inf = info_map.get(c.get("charId")) or {}
            owned.append((inf.get("rarity", -1), inf.get("name", c.get("charId", ""))))
        owned.sort(key=lambda x: (-x[0], x[1]))
        owned_names = [nm for _r, nm in owned if nm]
        self._q_owned = set(owned_names)
        names = owned_names + sorted(self._q_all_names() - set(owned_names))
        self.q_oper.blockSignals(True)
        self.q_oper.clear()
        self.q_oper.addItems(names)
        self.q_oper.blockSignals(False)
        comp = QCompleter(names, self)
        comp.setFilterMode(Qt.MatchContains)                # 输入任意片段即可匹配
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.activated.connect(lambda _t: self._q_sync_cur())
        self.q_oper.setCompleter(comp)
        self._q_sync_cur()

    def _q_find(self, name):
        for cc in getattr(self, "_opers_chars", []) or []:
            inf = (getattr(self, "_opers_map", {}) or {}).get(cc.get("charId")) or {}
            if inf.get("name") == name:
                return cc
        return None

    def _q_sync_cur(self):
        """选中/输入干员变化：已拥有显示当前练度；**未拥有按「刚获得 E0L1」模拟**并给星级标准目标。"""
        name = self.q_oper.currentText().strip()
        c = self._q_find(name)
        oc = self._q_oc()
        if c is not None:                        # 已拥有：目标默认 = 当前练度
            specs = [x.get("specializeLevel", 0) for x in (c.get("skills") or [])]
            self.q_cur.setText(
                f"当前：{ELITE.get(c.get('evolvePhase'), '')} Lv{c.get('level')} · "
                f"技{c.get('mainSkillLvl')} · 专精 {'/'.join(str(x) for x in specs) or '0'}")
            self.q_elite.setCurrentIndex(min(2, int(c.get("evolvePhase", 0) or 0)))
            self.q_level.setText(str(int(c.get("level", 1) or 1)))
            self._q_fill_modules(c.get("charId"), {e.get("id"): e for e in (c.get("equip") or [])})
            return
        cid = ch = None                          # 未拥有（但在干员表里）：按刚获得模拟
        for k, v in self._q_chars_all().items():
            if v.get("name") == name:
                cid, ch = k, v
                break
        if not ch:
            self.q_cur.setText("")
            self._q_fill_modules("", {})
            return
        te, tl, _combat = oc.target_std(ch.get("rarity")) if oc else (2, 60, True)
        self.q_cur.setText(f"⚠ 我没有（按「刚获得」E0L1 模拟）→ 默认目标 精{te} Lv{tl}")
        self.q_elite.setCurrentIndex(min(2, te))
        self.q_level.setText(str(tl))
        self.q_skill.setCurrentText("7" if tl > 1 else "1")
        self._q_sync_mastery()
        self._q_fill_modules(cid, {})            # 未拥有：模组全部未解锁

    def _oper_query_run(self):
        name = self.q_oper.currentText().strip()
        if name not in self._q_all_names():
            self._toast("warn", "没选干员", "在「干员」框里选/输入一个干员名。")
            return
        if self.data is None:
            self._toast("warn", "无数据", "先「刷新数据」拉到账号数据。")
            return
        skill_lvl = int(self.q_skill.currentText())
        mastery = [cb.currentIndex() for cb in self.q_ms] if skill_lvl >= 7 else [0, 0, 0]
        try:
            lvl = int(self.q_level.text())
        except ValueError:
            lvl = 1
        spec = {"name": name,
                "elite": self.q_elite.currentIndex(),
                "level": max(1, min(90, lvl)),
                "skill_lvl": skill_lvl,
                "mastery": mastery}
        mi = self.q_mod_sel.currentIndex()
        mod_id = self._q_mod_ids[mi] if 0 <= mi < len(self._q_mod_ids) else None
        if mod_id:
            spec["modules"] = {mod_id: self.q_mod.currentIndex() + 1}
        self.q_result.setPlainText("计算中…")

        def work():
            try:
                tools = str(ROOT / "scheduling" / "tools")
                if tools not in sys.path:
                    sys.path.insert(0, tools)
                import oper_cost as oc
                import skland_box
                box = skland_box.to_operbox(self.data or {})   # 当前练度：GUI 已拉的森空岛数据
                bpath = str(pathlib.Path(os.environ.get("TEMP", ".")) / "skland_gui_operbox.json")
                with open(bpath, "w", encoding="utf-8") as f:
                    json.dump(box, f, ensure_ascii=False)
                res = oc.compute_custom([spec], box=bpath, from_skland=False)
                out = self._fmt_oper_cost(res)
            except Exception as e:  # noqa: BLE001
                import traceback
                out = "计算失败：" + repr(e) + "\n" + traceback.format_exc()
            self.q.put(("oper_cost", out))

        threading.Thread(target=work, daemon=True).start()

    def _fmt_oper_cost(self, res) -> str:
        t = (res.get("targets") or [{}])[0]
        if t.get("error"):
            return t["error"]
        ct, tg, tot = t["current"], t["target"], res["total"]
        mods = "、".join(f"{m['name']}→{m['target']}" for m in (t.get("modules") or [])) or "—"
        lines = [
            f"{t['name']}（{t['rarity']}）",
            f"当前 {ELITE.get(ct['elite'], ct['elite'])} Lv{ct.get('level')} 技{ct.get('skill_lvl')} "
            f"专精 {'/'.join(str(x) for x in (ct.get('spec') or []))}",
            f"目标 精{tg['elite']} Lv{tg['level']} 技{tg.get('skill_lvl')} "
            f"专精 {'/'.join(str(x) for x in tg['mastery'])} 模组 {mods}",
            "",
            dpad("材料", 12) + dpad("需", 6, ">") + dpad("有", 7, ">") + dpad("缺", 6, ">"),
        ]
        for m in t["materials"]:
            lines.append(dpad(m["name"], 12) + dpad(m["need"], 6, ">")
                         + dpad(m["have"], 7, ">") + dpad(m["gap"], 6, ">"))
        if not t["materials"]:
            lines.append("（材料已齐）")
        resolved = t.get("resolved") or []
        if resolved:                                # 缺口按合成关系**递归降级**后的材料
            lines += ["", "—— 缺口降级后（缺的按配方递归兑成下一级；中间材料已用库存抵扣）——",
                      dpad("材料", 12) + dpad("需", 6, ">") + dpad("有", 7, ">") + dpad("缺", 6, ">")]
            for r in resolved:
                lines.append(dpad(r["name"], 12) + dpad(r["need"], 6, ">")
                             + dpad(r["have"], 7, ">") + dpad(r["gap"], 6, ">"))
        downs = t.get("downgrades") or []
        if downs:                                   # 备注：具体降级情况（芯片仅「双芯片」可降级）
            lines += ["", "—— 材料降级备注 ——"]
            for d in downs:
                ins = " + ".join(f"{x['name']}×{x['count']}" for x in d["inputs"])
                g = f"（龙门币 {d['gold']}）" if d["gold"] else ""
                lines.append(f"{d['name']} ×{d['gap']} → {ins}{g}")
        if t.get("craft_gold"):
            lines.append(f"合成合计消耗龙门币 {t['craft_gold']}")
        lines += [
            "",
            f"升级经验 {tot['exp']}　升级龙门币 {tot['upgrade_lmd']}",
            f"精英化龙门币 {tot['elite_lmd']}　模组龙门币 {tot['module_lmd']}",
            f"≈ 材料 {tot['material_sanity']} + 经验 {tot['exp_sanity']} + 龙门币 {tot['lmd_sanity']} "
            f"= 合计 {tot['total_sanity']} 理智",
        ]
        return "\n".join(lines)

    def _render_base(self, b, info_map):
        """基建页：各设施卡片 **2 列网格** + 「排班校验」+「现阶段基建配置」。"""
        pg = self.pg_base
        pg.clear()
        pg.add(qfw.TitleLabel("基建"))
        if b:
            groups = [("控制中枢", b.get("control")), ("贸易站", b.get("tradings")),
                      ("制造站", b.get("manufactures")), ("发电站", b.get("powers")),
                      ("宿舍", b.get("dormitories")), ("会客室", b.get("meeting")),
                      ("办公室", b.get("hire")), ("训练室", b.get("training"))]
            cards = []
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
                cards.append(sec)
            labor = b.get("labor") or {}
            if labor:
                sec = Section("无人机")
                sec.add(self._kv("数量", f"{labor.get('value')}/{labor.get('maxValue')}"))
                cards.append(sec)
            if cards:
                ncol = 2
                grid = QGridLayout()
                grid.setHorizontalSpacing(12)
                grid.setVerticalSpacing(12)
                for i, c in enumerate(cards):
                    c.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)   # 贴合内容、不拉伸
                    r, cc = divmod(i, ncol)
                    grid.addWidget(c, r, cc, Qt.AlignTop)
                for i in range(ncol):
                    grid.setColumnStretch(i, 1)
                holder = QWidget()
                holder.setLayout(grid)
                pg.add(holder)
        else:
            pg.add(qfw.BodyLabel("无基建数据（未登录？下面仍可配置 / 校验排班）。"))

        # 工具区（放在设施现状之后）：排班校验 + 现阶段基建配置
        pg.add(self._base_check_section())
        pg.add(self._base_config_section())

    # ---------------- 基建 · 排班校验 ----------------
    def _base_check_section(self) -> QWidget:
        sec = Section("排班校验")
        r = sec.row()
        b = btn("检查排班", FI.SYNC, primary=True)
        b.clicked.connect(self._infra_check)
        r.addWidget(b)
        r.addStretch(1)
        sec.add(note("比对「森空岛当前进驻」与「现阶段基建配置」里的 A/B 班：现在更像哪一班、"
                     "各设施是否吻合；并按最近一次换班时间 + 每班时长判断「是否该换班」。"))
        self.inf_check = qfw.TextEdit()
        self.inf_check.setReadOnly(True)
        self.inf_check.setFont(QFont("Consolas", 9))
        self.inf_check.setMinimumHeight(220)
        sec.add(self.inf_check)
        return sec

    def _infra_check(self):
        box = getattr(self, "inf_check", None)
        if box is None:
            return
        if self.data is None:
            self._toast("warn", "无数据", "先「刷新数据」拉到账号数据（当前进驻来自森空岛）。")
            return
        box.setPlainText("检查中…")
        self.log("排班校验：检查中…", "head")

        def work():
            try:
                out = self._infra_check_text()
            except Exception as e:  # noqa: BLE001
                import traceback
                out = "检查失败：" + repr(e) + "\n" + traceback.format_exc()
            self.q.put(("infra_check", out))

        threading.Thread(target=work, daemon=True).start()

    def _infra_check_text(self) -> str:
        import skland_box
        base = skland_box.to_base(self.data or {})
        cur: dict = {}
        for r in base.get("rooms") or []:
            cur.setdefault(r.get("key"), []).append(r)
        for k in cur:
            cur[k].sort(key=lambda r: str(r.get("slotId") or ""))

        p = pathlib.Path(MAA_CUSTOM_INFRAST)
        cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        plans = cfg.get("plans") or []

        lines = [f"当前进驻 {len(base.get('rooms') or [])} 个设施　·　"
                 f"配置 {p.name if p.exists() else '（缺失）'}　·　计划 {len(plans)} 班", ""]
        scored = []
        for plan in plans:
            m, t, diffs = self._infra_match(plan, cur)
            scored.append((plan, m, t, diffs))
        scored.sort(key=lambda x: (x[1] / x[2]) if x[2] else 0, reverse=True)

        if scored:
            best = scored[0]
            ratio = (best[1] / best[2] * 100) if best[2] else 0
            lines.append(f"当前更像：【{best[0].get('name')}】　整体吻合 {best[1]}/{best[2]}（{ratio:.0f}%）")
            rm, rt, _rd = self._infra_match(best[0], cur, only=("trading", "manufacture"))
            rp = (rm / rt * 100) if rt else 0
            lines.append(f"　（其中 MAA Rotation 真正会换的 贸易/制造：{rm}/{rt}，{rp:.0f}%）")
            for plan, m, t, _d in scored:
                r2 = (m / t * 100) if t else 0
                lines.append(f"　· {plan.get('name')}：{m}/{t}（{r2:.0f}%）")
            lines.append("")
            lines.append(f"—— 与【{best[0].get('name')}】逐设施比对 ——")
            if best[3]:
                for fac, idx, want, have in best[3]:
                    lines.append(f"{fac} #{idx}")
                    lines.append(f"    计划：{'、'.join(want) or '（空）'}")
                    lines.append(f"    实际：{'、'.join(have) or '（空）'}")
                lines.append("（注：MAA Rotation 不摆 发电 / 办公室 / 控制中枢 / 宿舍，"
                             "这些不吻合属正常——见 docs/FINDINGS.md §24）")
            else:
                lines.append("全部吻合 ✔")
        else:
            lines.append("配置里没有 plans[]，无法比对。")

        lines += ["", "—— 是否该换班 ——"]
        lines += self._shift_due_lines(plans)
        return "\n".join(lines)

    def _infra_match(self, plan, cur, only=None):
        """把一班的 rooms 与当前进驻逐设施比对 → (命中数, 计划总数, 差异列表)。

        `only`：只比这些 MAA room key（如只看 Rotation 实换的 贸易/制造）。
        计划里**为空**的槽位（例如宿舍 autofill）不计、也不报差异。
        """
        rooms = plan.get("rooms") or {}
        matched = total = 0
        diffs = []
        for pkey, (ckey, cn) in INFRA_ROOM_MAP.items():
            if only and pkey not in only:
                continue
            slots = rooms.get(pkey) or []
            if not slots:
                continue
            cslots = cur.get(ckey) or []
            for i, ps in enumerate(slots):
                want = [str(x) for x in (ps.get("operators") or [])]
                if not want:
                    continue                      # 计划空槽（autofill）→ 无可比对
                have = [o.get("name") for o in ((cslots[i].get("operators") if i < len(cslots) else []) or [])]
                total += len(want)
                matched += len(set(want) & set(have))
                if set(want) != set(have):
                    diffs.append((cn, i + 1, want, have))
        return matched, total, diffs

    def _last_rotation_dt(self):
        """最近一次基建换班时间：取 换班日志 / 每日日常 / 凌晨基建 三处日志里最新的一条。"""
        best = None
        def _from(path, key="ts"):
            nonlocal best
            try:
                if not path.exists():
                    return
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    s = str(rec.get(key) or "")[:19]
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                        try:
                            t = datetime.datetime.strptime(s, fmt)
                            if best is None or t > best:
                                best = t
                            break
                        except ValueError:
                            continue
            except Exception:  # noqa: BLE001
                pass
        _from(INFRA_ROTATION_LOG)
        _from(ROOT / "scheduling" / "data" / "daily_run.jsonl")
        _from(ROOT / "scheduling" / "data" / "night_run.jsonl")
        return best

    def _shift_due_lines(self, plans) -> list:
        dur = SHIFT_MINUTES_FALLBACK
        for pl in plans:
            try:
                dur = int(pl.get("duration") or dur)
                break
            except (TypeError, ValueError):
                pass
        now = datetime.datetime.now()
        last = self._last_rotation_dt()
        out = []
        if last is not None:
            due = last + datetime.timedelta(minutes=dur)
            out.append(f"最近一次换班：{last:%Y-%m-%d %H:%M}　·　每班 {dur} 分钟")
            out.append(f"下次该换：{due:%Y-%m-%d %H:%M}")
            delta = now - due
            mins = int(abs(delta.total_seconds()) // 60)
            if delta.total_seconds() >= 0:
                out.append(f"⇒ 该换班了（已超时 {mins // 60} 时 {mins % 60} 分）。")
            else:
                out.append(f"⇒ 还没到点（还有 {mins // 60} 时 {mins % 60} 分）。")
            return out
        # 无日志 → 退化为固定节律（每日 02:00 / 14:00 各换一次）
        cands = []
        for h in (2, 14):
            t = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if t <= now:
                t += datetime.timedelta(days=1)
            cands.append(t)
        nxt = min(cands)
        mins = int((nxt - now).total_seconds() // 60)
        out.append("（没有换班日志，按固定节律 02:00 / 14:00 估计）")
        out.append(f"下一次计划换班：{nxt:%m-%d %H:%M}（还有 {mins // 60} 时 {mins % 60} 分）")
        return out

    # ---------------- 基建 · 现阶段基建配置 ----------------
    def _base_config_section(self) -> QWidget:
        sec = Section("现阶段基建配置")
        self.inf_cfg_summary = qfw.BodyLabel("—")
        self.inf_cfg_summary.setWordWrap(True)
        sec.add(self.inf_cfg_summary)
        r = sec.row()
        b_load = btn("载入当前配置", FI.FOLDER)
        b_load.clicked.connect(self._infra_load_current)
        r.addWidget(b_load)
        b_prev = btn("预览排班表", FI.DOCUMENT)
        b_prev.clicked.connect(self._infra_preview)
        r.addWidget(b_prev)
        b_save = btn("保存", FI.SAVE, primary=True)
        b_save.clicked.connect(self._infra_save)
        r.addWidget(b_save)
        b_apply = btn("应用", FI.ACCEPT)
        b_apply.clicked.connect(self._infra_apply)
        r.addWidget(b_apply)
        r.addStretch(1)
        self.inf_edit = qfw.TextEdit()
        self.inf_edit.setFont(QFont("Consolas", 9))
        self.inf_edit.setPlaceholderText(
            "把一图流 / MAA 的基建排班 JSON（含 plans[] 的排班表）粘贴到这里 → 保存 / 应用。")
        self.inf_edit.setMinimumHeight(180)
        sec.add(self.inf_edit)
        sec.add(qfw.CaptionLabel("排班表预览（保存前必看；「保存」会自动预览并再让你确认一次）"))
        self.inf_preview = qfw.TextEdit()
        self.inf_preview.setReadOnly(True)
        self.inf_preview.setFont(QFont("Consolas", 9))
        self.inf_preview.setPlaceholderText("点「预览排班表」把上面粘贴的 JSON 解析成人能看的排班表（含校验提示）。")
        self.inf_preview.setMinimumHeight(200)
        sec.add(self.inf_preview)
        self._inf_preview_for = None      # 已预览过的文本，用来判断「改过没 / 预览过没」
        sec.add(note(f"「保存」= **先预览排班表 → 你确认 → 才** 备份旧文件写入 {MAA_CUSTOM_INFRAST}"
                     "（并留档 scheduling/data/infra_config.json）；"
                     "「应用」= 把 MAA 的 Infrast 改成 Custom 并指向该文件。\n"
                     "✗ **致命项直接禁止保存**（预览框里标 `✗`）：① 方案份数 < 2（自动化 plan_index=1 会越界 → "
                     "`append 0` 打死整队）② 产物名不在 MaaCore 白名单（照常换人但**不切换产物**，静默失效）"
                     "③ 某班在 制造/贸易/发电/控制中枢/会客室/办公室 一个人都没写 ④ **有干员未持有**"
                     "（摆不上 → 换不齐）。这些判据与 `scheduling/tools/convert_to_maa.py` **共用同一份**。\n"
                     "⚠ 提醒（标 `⚠`）不阻止保存：缺 `plans[].index`、`index` 为负 等。\n"
                     "⚠ 别贴**原始一图流导出**：它没有 `plans[].index`（GUI 方案下拉会全是 0），"
                     "`period` 也不是我们的换班窗口 —— 要规范化就跑 "
                     "`python scheduling/tools/convert_to_maa.py <一图流.json> <目标.json> "
                     '--periods "B班=02:00-04:00,A班=14:00-16:00"`，再把结果贴进来。')
                )
        self._infra_refresh_summary()
        return sec

    def _infra_refresh_summary(self):
        label = getattr(self, "inf_cfg_summary", None)
        if label is None:
            return
        p = pathlib.Path(MAA_CUSTOM_INFRAST)
        if not p.exists():
            label.setText(f"未找到配置文件：{p}")
            return
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            label.setText(f"读取失败：{e!r}")
            return
        plans = cfg.get("plans") or []
        st = cfg.get("scheduleType") or {}
        names = "、".join(f"{x.get('name')}（{x.get('duration')}min）" for x in plans) or "—"
        fac = "　".join(f"{k}{v}" for k, v in (("贸易", st.get("trading")), ("制造", st.get("manufacture")),
                                              ("发电", st.get("power")), ("宿舍", st.get("dormitory")))
                        if v)
        label.setText(f"来源 {p}　·　标题：{cfg.get('title', '—')}　·　{len(plans)} 班：{names}"
                      + (f"　·　{fac}" if fac else ""))

    def _infra_load_current(self):
        p = pathlib.Path(MAA_CUSTOM_INFRAST)
        if not p.exists():
            self._toast("err", "找不到配置", str(p))
            return
        try:
            self.inf_edit.setPlainText(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            self._toast("err", "读取失败", repr(e))
            return
        self.log(f"已载入当前基建配置：{p}", "dim")

    # ---------------- 排班表：解析 / 校验 / 预览 ----------------
    def _infra_owned_names(self) -> set:
        """当前账号已拥有的干员名（拿不到账号数据就返回空集 → 预览里跳过持有性校验）。"""
        info_map = getattr(self, "_opers_map", None) or {}
        out = set()
        for c in (getattr(self, "_opers_chars", None) or []):
            nm = (info_map.get(c.get("charId")) or {}).get("name")
            if nm:
                out.add(nm)
        return out

    def _infra_parse(self, txt: str):
        """解析 + 结构校验排班表。返回 (cfg, error)；error 非空 = 不能保存。"""
        if not txt:
            return None, "先粘贴基建配置 JSON（含 plans[]）。"
        try:
            cfg = json.loads(txt)
        except Exception as e:  # noqa: BLE001
            return None, f"JSON 解析失败：{e!r}"
        if not isinstance(cfg, dict):
            return None, "配置应是一个 JSON 对象（{...}）。"
        plans = cfg.get("plans")
        if not isinstance(plans, list) or not plans:
            return None, ("没有 plans[]（或为空）—— MAA 自定义换班必须要有 plans 列表"
                          "（一图流 / MAA 排班表格式）。")
        for i, p in enumerate(plans):
            if not isinstance(p, dict) or not isinstance(p.get("rooms"), dict) or not p.get("rooms"):
                return None, f"plans[{i}] 缺少 rooms —— MaaCore 读不到要摆哪些房间，保存了也不会生效。"
        return cfg, None

    def _infra_render_preview(self, cfg: dict):
        """排班表 → 人读文本 + 校验结果。

        返回 `(text, warns, fatals)`：
          · `warns` = 提醒（**不阻止保存**，但请确认是有意为之）
          · `fatals` = **致命项 → 禁止保存**（会让 MAA 跑废整队 / 方案结构性无效 / 静默失效）
        """
        plans = cfg.get("plans") or []
        st = cfg.get("scheduleType") or {}
        owned = self._infra_owned_names()
        warns, out = [], []
        out.append(f"标题：{cfg.get('title', '—')}")
        head = f"planTimes：{cfg.get('planTimes', '—')}　·　共 {len(plans)} 班"
        fac = "　".join(f"{k}{st.get(k)}" for k in ("trading", "manufacture", "power", "dormitory") if st.get(k))
        out.append(head + (f"　·　{fac}" if fac else ""))
        out.append("═" * 48)

        for i, p in enumerate(plans):
            idx = p.get("index")
            per = p.get("period") or []
            per_txt = "、".join(f"{a}-{b}" for a, b in per) if per else "（无）"
            rooms = p.get("rooms") or {}
            nop = sum(len([o for o in (r.get("operators") or []) if o])
                      for arr in rooms.values() for r in (arr or []))
            out.append(f"[{idx if idx is not None else i}] {p.get('name', '?')}"
                       f"　时长 {p.get('duration') if p.get('duration') is not None else '—'}min"
                       f"　换班窗口 {per_txt}　干员 {nop}")
            if idx is None:
                warns.append(f"plans[{i}] 没有 `index` → MAA GUI 的方案下拉每项都会是 0（选谁都等于第 0 份）。"
                             "建议先过一遍 scheduling/tools/convert_to_maa.py。")
            elif isinstance(idx, int) and idx < 0:
                warns.append(f"plans[{i}] 的 `index` 是负数（{idx}）→ 会和 GUI 方案下拉里的「自动」项撞车，"
                             "建议改成 0..n-1。")

            for fac_key, arr in rooms.items():
                cn = INFRA_ROOM_MAP.get(fac_key, (fac_key, fac_key))[1]
                for j, r in enumerate(arr or []):
                    names = [o for o in (r.get("operators") or []) if o]
                    tags = []
                    prod = r.get("product")
                    if prod:
                        tags.append(str(prod))
                    if r.get("autofill"):
                        tags.append("自动填充")
                    if r.get("skip"):
                        tags.append("skip")
                    body = "、".join(names) if names else "（空 → 不摆人）"
                    out.append(f"   {cn}#{j}：{body}" + (f"　[{' / '.join(tags)}]" if tags else ""))
            fia = p.get("Fiammetta") or {}
            if fia:
                out.append(f"   菲亚梅塔：{'开' if fia.get('enable') else '关'} → {fia.get('target') or '—'}"
                           f"（order={fia.get('order', 'pre')}）")
            dr = p.get("drones") or {}
            if dr:
                # 只列 MaaCore 真正会读的 4 个键（room/index/enable/order）；index 是 **1-based**（Core 里 `-1`）
                out.append(f"   无人机：{'开' if dr.get('enable') else '关'}"
                           f"　{dr.get('room', '—')} #{dr.get('index', '—')}"
                           f"（order={dr.get('order', 'pre')}）")
            out.append("")

        # ---- 致命项：判据在 `convert_to_maa.plan_fatals`（**与转换器共用同一份**）----
        # 份数<2（plan_index 越界打死整队）、产物名不在 MaaCore 白名单（静默不切产物）、
        # 某班关键设施全空（等于没换班）、干员未持有（摆不上，换不齐）。
        fatals = plan_fatals(cfg, room_cn=_INFRA_ROOM_CN, owned=(owned or None))

        out.append("─" * 48)
        if fatals:
            out.append(f"✗ 致命项（{len(fatals)} 条）—— **禁止保存**，请先改好：")
            out += [f"  ✗ {w}" for w in fatals]
        if warns:
            out.append(f"⚠ 提醒（{len(warns)} 条，不阻止保存，但请确认是有意为之）：")
            out += [f"  · {w}" for w in warns]
        if not fatals and not warns:
            out.append("✓ 校验通过：结构 / 产物白名单 / 方案份数 / 干员持有性 都没发现问题。")
        return "\n".join(out), warns, fatals

    def _infra_preview(self, txt: str | None = None, silent: bool = False) -> bool:
        """解析并渲染预览。返回是否解析成功（失败时预览框里写原因）。"""
        box = getattr(self, "inf_preview", None)
        if box is None:
            return False
        txt = self.inf_edit.toPlainText().strip() if txt is None else txt
        cfg, err = self._infra_parse(txt)
        if err:
            box.setPlainText(f"✗ 无法预览：{err}")
            self._inf_preview_for, self._inf_last_warns, self._inf_last_fatals = None, [], []
            if not silent:
                self._toast("err", "预览失败", err[:160])
            return False
        text, warns, fatals = self._infra_render_preview(cfg)
        box.setPlainText(text)
        self._inf_preview_for, self._inf_last_warns, self._inf_last_fatals = txt, warns, fatals
        if not silent:
            self.log(f"已生成排班表预览（未写入；致命 {len(fatals)} 条 / 提醒 {len(warns)} 条）",
                     "err" if fatals else "dim")
        return True

    def _infra_summary_lines(self, cfg: dict) -> list:
        """确认框里的要点摘要。"""
        plans = cfg.get("plans") or []
        st = cfg.get("scheduleType") or {}
        lines = [f"标题：{cfg.get('title', '—')}", f"方案：{len(plans)} 班"]
        for i, p in enumerate(plans):
            per = (p.get("period") or [[None, None]])[0]
            lines.append(f"  [{p.get('index', i)}] {p.get('name', '?')}"
                         f"　{p.get('duration', '—')}min"
                         f"　换班窗口 {per[0] or '—'}-{per[1] or '—'}")
        fac = "　".join(f"{k}{st.get(k)}" for k in ("trading", "manufacture", "power", "dormitory") if st.get(k))
        if fac:
            lines.append(f"布局：{fac}")
        targets = sorted({(p.get("Fiammetta") or {}).get("target", "")
                          for p in plans if (p.get("Fiammetta") or {}).get("enable")})
        lines.append("菲亚梅塔置换：开 → " + "、".join(t for t in targets if t) if any(targets) else "菲亚梅塔置换：关")
        return lines

    def _infra_save(self):
        txt = self.inf_edit.toPlainText().strip()
        # 1) **保存前必先预览**：解析不过就停在这里，一个字节都不写。
        #    （若这份内容刚预览过就不重复渲染，`_inf_last_warns` 还是同一份的。）
        if txt != getattr(self, "_inf_preview_for", None) and not self._infra_preview(txt=txt, silent=True):
            self._toast("err", "未保存：排班表没解析通过", "看下方预览框里的原因，修好再存。")
            return
        cfg, _err = self._infra_parse(txt)
        if cfg is None:      # 理论到不了这
            return

        # 1.5) **致命项 → 禁止保存**（会让 MAA 跑废整队 / 方案结构性无效 / 静默失效）
        fatals = getattr(self, "_inf_last_fatals", []) or []
        if fatals:
            head = fatals[0]
            more = f"\n（共 {len(fatals)} 条，详见预览框）" if len(fatals) > 1 else ""
            self.log(f"禁止保存：{len(fatals)} 项致命问题 —— {head}", "err")
            self._toast("err", f"禁止保存：{len(fatals)} 项致命问题", head[:220] + more)
            return

        plans = cfg["plans"]
        warns = getattr(self, "_inf_last_warns", []) or []
        p = pathlib.Path(MAA_CUSTOM_INFRAST)

        # 2) **让用户确认**（把要点 + 提醒摆出来）
        msg = [f"即将写入：\n{p}\n", *self._infra_summary_lines(cfg)]
        if warns:
            msg += ["", f"⚠ 预览里有 {len(warns)} 条提醒（不阻止保存，请确认是有意为之）：",
                    *[f"  · {w}" for w in warns[:6]]]
            if len(warns) > 6:
                msg.append(f"  …（共 {len(warns)} 条，详见预览框）")
        msg += ["", f"旧文件会先备份为 {p.name}.bak-<时间戳>；同时留档 {INFRA_CFG_LOCAL.name}。",
                "确认写入吗？"]
        if not qfw.MessageBox("确认保存排班表", "\n".join(msg), self).exec():
            self.log("已取消保存（已预览、未写入）", "dim")
            return

        # 3) 落盘（备份 → 写 MAA 方案表 → 留档）
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                bak = p.with_name(p.name + time.strftime(".bak-%Y%m%d-%H%M%S"))
                try:
                    p.replace(bak)
                    self.log(f"旧配置已备份：{bak.name}", "dim")
                except Exception:  # noqa: BLE001
                    pass
            text = json.dumps(cfg, ensure_ascii=False, indent=2)
            p.write_text(text, encoding="utf-8")
            INFRA_CFG_LOCAL.parent.mkdir(parents=True, exist_ok=True)
            INFRA_CFG_LOCAL.write_text(text, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            self._toast("err", "保存失败（MAA 在运行？）", repr(e)[:120])
            return
        self._infra_preview_for = None
        self._infra_refresh_summary()
        self.log(f"基建配置已保存：{p}（{len(plans)} 班；写入前已预览 + 确认）", "ok")
        self._toast("ok", "基建配置已保存", f"{len(plans)} 班（已预览 + 确认）")

    def _infra_apply(self):
        if not qfw.MessageBox("应用基建配置",
                              "把 MAA 的 Infrast 改成 Custom 模式并指向：\n"
                              f"{MAA_CUSTOM_INFRAST}\n\n"
                              "⚠ 请先关闭 MAA（运行中改配置会被它覆盖回写）；\n"
                              "（`maa_week write` 现在写的是同一口径：Custom + 这个文件 + PlanSelect=1，"
                              "不再回退 Rotation。）",
                              self).exec():
            return
        gp = pathlib.Path(MAA_GUI_CFG)
        try:
            cfg = json.loads(gp.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            self._toast("err", "读 MAA 配置失败", repr(e)[:120])
            return
        hit = 0
        for q in ((cfg.get("Configurations") or {}).get("Default") or {}).get("TaskQueue") or []:
            if q.get("TaskType") == "Infrast":
                q["Mode"] = "Custom"
                q["Filename"] = MAA_CUSTOM_INFRAST
                hit += 1
        if not hit:
            self._toast("warn", "没找到 Infrast 任务", "MAA 配置里没有 Infrast 队列项。")
            return
        try:
            gp.write_text(json.dumps(cfg, ensure_ascii=False, indent=4), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            self._toast("err", "写入失败（MAA 在运行？）", repr(e)[:120])
            return
        self.log(f"已应用：MAA Infrast → Custom + {MAA_CUSTOM_INFRAST}", "ok")
        self._toast("ok", "已应用", "MAA Infrast = Custom")

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
        """战绩页：**2 列网格**（剿灭 / 保全 / 肉鸽 / 任务）。

        目的：整页一屏放下、**不需要页面滚动**；剿灭的长列表用内部滚动小盒（`_scroll_list`）收纳，
        并让它**占满卡片剩余高度**（窗口高就多显示几行，矮则内部滚动），从而页面永不溢出。
        """
        pg = self.pg_record
        pg.clear()
        pg.add(qfw.TitleLabel("战绩"))

        cards: list = []

        camp = data.get("campaign") or {}
        sec = Section("剿灭作战")
        rew = camp.get("reward") or {}
        sec.add(self._kv("本周合成玉", f"{rew.get('current', '—')} / {rew.get('total', '—')}"))
        recs = camp.get("records") or []
        if recs:
            sec.add(self._scroll_list(
                [self._kv(rec.get("campaignId", ""), f"最高击杀 {rec.get('maxKills')}")
                 for rec in recs], expand=True))
        cards.append(sec)

        tower = data.get("tower") or {}
        if tower:
            sec = Section("保全派驻")
            trew = tower.get("reward") or {}
            if trew:
                sec.add(self._kv("奖励进度", f"{trew.get('current', '—')} / {trew.get('total', '—')}"))
            trecs = tower.get("records") or []
            if trecs:
                sec.add(self._scroll_list(
                    [self._kv(rec.get("towerId", ""), json.dumps(rec, ensure_ascii=False)[:90])
                     for rec in trecs], max_h=150))
            cards.append(sec)

        rogue = data.get("rogue") or {}
        if rogue.get("records"):
            sec = Section("集成战略（肉鸽）")
            rrecs = rogue.get("records") or []
            if rrecs:
                sec.add(self._scroll_list([
                    self._kv(rec.get("rogueId", ""),
                             f"收藏品 {rec.get('relicCnt')} · "
                             f"存款 {(rec.get('bank') or {}).get('current')}/{(rec.get('bank') or {}).get('record')}")
                    for rec in rrecs], max_h=150))
            cards.append(sec)

        routine = data.get("routine") or {}
        if routine:
            sec = Section("任务")
            d, w = routine.get("daily") or {}, routine.get("weekly") or {}
            sec.add(self._kv("每日任务", f"{d.get('current', '—')} / {d.get('total', '—')}"))
            sec.add(self._kv("每周任务", f"{w.get('current', '—')} / {w.get('total', '—')}"))
            cards.append(sec)

        if not cards:
            return

        ncol = 2
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for i, c in enumerate(cards):
            r, cc = divmod(i, ncol)
            if c is cards[0]:                 # 剿灭：占满卡片高（内部滚动自适应）
                c.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                grid.addWidget(c, r, cc)
            else:                             # 其余：贴合内容、顶部对齐
                c.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                grid.addWidget(c, r, cc, Qt.AlignTop)
        for i in range(ncol):
            grid.setColumnStretch(i, 1)
        if len(cards) > ncol:
            grid.setRowStretch(0, 1)          # 第一行（含剿灭）吃掉多余高度
        holder = QWidget()
        holder.setLayout(grid)
        pg.add(holder, 1)

    def _render_checkin(self, attendance):
        """更新左侧导航的「签到」卡片：title = 可/不可点的签到键，subtitle = 本月已签天数。"""
        self.attendance = attendance
        card = getattr(self, "nav_checkin", None)
        if card is None:
            return
        if not attendance:
            card.setTitle("签到")
            card.setSubtitle("未登录 / 未取到")
            card.setEnabled(True)
            card.setToolTip("森空岛每日签到（登录后可用）")
            return

        cal = attendance.get("calendar") or []
        recs = attendance.get("records") or []
        rim = attendance.get("resourceInfoMap") or {}
        n_done = sum(1 for c in cal if c.get("done"))
        card.setSubtitle(f"本月已签到 {n_done} 天")

        def _rname(iid):
            return (rim.get(str(iid)) or {}).get("name", str(iid))

        def _rdate(r):
            try:
                return datetime.date.fromtimestamp(int(r.get("ts")))
            except (TypeError, ValueError, OSError):
                return None

        # 「今日」按**签到记录**判定：records 里出现今天的日期 = 今天已签。
        try:
            srv_today = datetime.date.fromtimestamp(int(attendance.get("currentTs")))
        except (TypeError, ValueError, OSError):
            srv_today = datetime.date.today()

        if any(_rdate(r) == srv_today for r in recs):
            card.setTitle("今日已签到")
            card.setEnabled(False)                 # 已签 → 置灰、不可点
            card.setToolTip("今天已经签过啦，明天再来。")
        elif n_done < len(cal):
            nxt = cal[n_done]
            card.setTitle("签到")
            card.setEnabled(True)
            card.setToolTip(f"点一下即可签到：{_rname(nxt.get('resourceId'))}×{nxt.get('count')}")
        else:
            card.setTitle("本月已签满")
            card.setEnabled(False)
            card.setToolTip("本月签到奖励已全部领完。")

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

    # 单实例：已经有 yuMAArin 在跑就别再开第二个（QLockFile 用 PID 判活，崩溃残留会自动清理）
    lock = QLockFile(LOCK_FILE)
    lock.setStaleLockTime(30000)
    if not lock.tryLock(100):
        QMessageBox.information(
            None, APP_NAME,
            "yuMAArin 已经在运行了。\n\n请在任务栏里切到已打开的那个窗口，\n"
            "不要重复打开（同一个账号/设备同时只能有一个界面在驱动）。")
        sys.exit(0)

    qfw.setThemeColor(QColor(GAME["dark"]["accent"]))
    w = App()
    w._lock = lock          # 持有到进程结束，退出时自动释放
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
