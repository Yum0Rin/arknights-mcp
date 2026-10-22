#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活动关作业工作流 (activity copilot)
================================
抓「当期活动」的 MAA 作业(prts.maa.plus) → 比对本人干员箱(OperBoxData.json) →
用 MAA 的多作业自动战斗(自带关卡导航)逐关通关。

与 `scheduling/` 的基建排班工作流并列，是「打活动关」的固化流程。

单客户端纪律
------------
同一时刻只让 **一个** 程序驱动设备。运行前请先关掉 MAA GUI / 其它 arknights MCP，
否则会出现 MaaTouch 抢占、连接错乱。 (见 AGENTS.md 铁律)

导航分工（重要）
----------------
本脚本只负责「活动关卡列表页 → 逐关自动战斗」这段确定性流程。
**从首页走进活动**那一步 MAA Copilot 不做，得由上层 MCP/Agent 完成：
  ark_where 判页面 → ark_find/OCR 找当期活动 banner → ark_tap 逐层点入 → 停在关卡列表。
（详见 docs/WORKFLOW-活动关作业.md 的「导航层」一节。）

子命令
------
  events                       列出 MAA 资源已知的 side story 活动(actNNside)
  sync    <event>              从 MaaResource(GitHub) 补齐关缺失的关卡数据
                               (Arknights-Tile-Pos/overview.json + 该活动的 Tile-Pos)
  plan    <event> [--top N]    抓作业并按干员箱打分，打印每关推荐 + 候选
  run     <event> --stages 5,6,7,8 [--try]   执行(单关失败逐候选重试)
  run     <event> --all
  run     <event> --stages 1,2 --raid       打活动突袭(is_raid=true，只能走 Copilot)
  run     <event> --chain ex                 ★按解锁链打 EX 普通（EX-1→EX-8，遇挫即停）
  run     <event> --chain raid               按解锁链打 EX 突袭（需该关普通已通）
  run     <event> --chain s | --chain sraid  同理，S 关

解锁依赖链（2026-10-12 用户口径）
--------------------------------
活动 **只有 EX / S 关有突袭**，普通关(YW-1..8)没有。EX-i 未通就打不了 EX-(i+1)
（依次解锁）；突袭依赖「该关普通已通」。故：
  · `--chain` 只排**未通**的关、从**第一个未通**起按顺序跑；
  · **遇挫即停**：某关没作业 / 执行失败 → 后面本来没解锁，直接结束（不跳关）；
  · 跑完/失败都**回写** docs/state.json.progress.<event_<id>>（ex/s_clear_done、raid_clear_done、*_pending）。

示例
----
  python event_copilot.py sync act52side
  python event_copilot.py plan act52side
  python event_copilot.py run  act52side --stages 5,6,7,8
  python event_copilot.py run  act52side --all --try
  python event_copilot.py run  act52side --chain ex --try         # EX 普通解锁链
  python event_copilot.py run  act52side --chain raid --try       # EX 突袭解锁链

前置：MAA(含 MaaCore) 已装在 C:\\MAA；模拟器已开、adb 可连 127.0.0.1:5555。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
MAA = os.environ.get("ARK_MAA_PATH", r"C:\MAA")
ADB = os.environ.get("ARK_ADB", r"C:\leidian\LDPlayer9\adb.exe")
ADDR = os.environ.get("ARK_ADDR", "127.0.0.1:5555")
TOUCH = os.environ.get("ARK_TOUCH", "maatouch")
# 自动编队固定用「第四编队」，避免动到用户其它编队(尤其第二编队)。
# 0=不选择编队；1..N=第 N 队。MAA GUI 里对应「选择编队」。
FORMATION_INDEX = int(os.environ.get("ARK_FORMATION_INDEX", "4"))

PRTS = "https://prts.maa.plus"
RES_RAW = "https://raw.githubusercontent.com/MaaAssistantArknights/MaaResource/main/resource"
TILE_DIR = pathlib.Path(MAA) / "resource" / "Arknights-Tile-Pos"
COPILOT_DIR = pathlib.Path(MAA) / "config" / "copilot"
BOX_FILE = pathlib.Path(os.environ.get("ARK_BOX", str(pathlib.Path(MAA) / "data" / "OperBoxData.json")))

ROOT = pathlib.Path(__file__).resolve().parents[2]          # 仓库根
DOCS = ROOT / "docs"
STATE_JSON = DOCS / "state.json"
EVENT_DATA = ROOT / "scheduling" / "data"                    # event_<id>.json

MAX_CORE = (6, 18, 0)  # 本机 MaaCore 版本 upper-bound，作业 minimum_required 更高则跳过


def log(*a):
    print(*a, flush=True)


_HTTP_CACHE: dict[str, object] = {}


def http_json(url: str, timeout: int = 40, retries: int = 3):
    """带进程内缓存（作业详情/查询结果在下一次跑之前不会变，省掉重复请求）。"""
    if url in _HTTP_CACHE:
        return _HTTP_CACHE[url]
    data = _http_json_nocache(url, timeout=timeout, retries=retries)
    if len(_HTTP_CACHE) < 4000:
        _HTTP_CACHE[url] = data
    return data


def _http_json_nocache(url: str, timeout: int = 40, retries: int = 3):
    """GET→JSON，**带重试**：prts.maa.plus 是第三方站，偶发 SSL/断流会让整条自动链崩掉
    （2026-10-18 实测：`ssl.py recv_into` 读到一半断）。重试 3 次、退避 1.5s。"""
    last = None
    for i in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "arknights-mcp/event-copilot"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            if i + 1 < retries:
                time.sleep(1.5 * (i + 1))
    raise last  # type: ignore[misc]


def http_text(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": "arknights-mcp/event-copilot"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


# ---------------------------------------------------------------------------
# 干员箱
# ---------------------------------------------------------------------------
def load_box():
    d = json.load(open(BOX_FILE, encoding="utf-8"))
    own = {o["name"]: o for o in d["own_opers"] if o.get("own")}
    return own


def elite(own, name):
    o = own.get(name)
    return o["elite"] if o else -1


# ---------------------------------------------------------------------------
# 资源同步（关键：MAA 旧资源不认识新活动 → 报 Not support stage）
# ---------------------------------------------------------------------------
def local_overview():
    return json.load(open(TILE_DIR / "overview.json", encoding="utf-8"))


def ensure_resource(event_id: str) -> bool:
    """确保 overview.json 含该活动；否则从 GitHub 拉最新 overview 并补下载该活动的 Tile-Pos。"""
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    remote = http_json(RES_RAW + "/Arknights-Tile-Pos/overview.json")
    have = [k for k in remote if k.startswith(event_id + "_")]
    if not have:
        log("[!] 远端资源里也没有 %s 的关卡数据（活动 id 是否写错？）" % event_id)
        return False

    local = {}
    if (TILE_DIR / "overview.json").exists():
        local = json.load(open(TILE_DIR / "overview.json", encoding="utf-8"))
    if not any(k.startswith(event_id + "_") for k in local):
        bak = TILE_DIR / ("overview.json.bak-%s" % time.strftime("%Y%m%d%H%M%S"))
        shutil.copy2(TILE_DIR / "overview.json", bak) if (TILE_DIR / "overview.json").exists() else None
        log("[*] 替换 overview.json（旧备份 -> %s），新增 %d 条" % (bak.name, len(set(remote) - set(local))))
        json.dump(remote, open(TILE_DIR / "overview.json", "w", encoding="utf-8"), ensure_ascii=False)
    else:
        log("[=] overview.json 已含 %s" % event_id)

    # 下载缺失的 Tile-Pos 文件
    missing = []
    for k in have:
        fn = remote[k]["filename"]
        if not (TILE_DIR / fn).exists():
            missing.append(fn)
    for fn in missing:
        try:
            txt = http_text(RES_RAW + "/Arknights-Tile-Pos/" + urllib.parse.quote(fn))
            (TILE_DIR / fn).write_text(txt, encoding="utf-8")
            log("    +", fn)
        except Exception as e:
            log("    ! 下载失败", fn, e)
    return True


def stages_of(event_id: str):
    """从 overview.json 取该活动的关卡列表 (code, name, level_id, filename)。"""
    ov = local_overview()
    rows = []
    for k, v in ov.items():
        if k.startswith(event_id + "_"):
            # overview key 形如 "act52side_05-activities/act52side/level_act52side_05"
            stage_name = k.split("-activities")[0]
            rows.append((v.get("code", ""), v.get("name", ""), stage_name, v.get("filename", "")))
    # 仅保留可战斗关卡（有 code 形如 XX-N），按 code 排序
    rows = [r for r in rows if r[0]]
    rows.sort(key=lambda r: r[0])
    return rows


# ---------------------------------------------------------------------------
# 进度（docs/state.json.progress.<event_<id>>）—— 首通/突袭链依赖它
# ---------------------------------------------------------------------------
_STAGE_CODE_RE = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)?-?\d+")


def _stage_codes(raw) -> set:
    """解析进度字段里的关卡代号前缀（容错 `\"YW-5(2星)\"` -> `\"YW-5\"`）。"""
    out = set()
    if isinstance(raw, str):
        raw = [raw]
    for it in (raw or []):
        m = _STAGE_CODE_RE.search(str(it))
        if m:
            out.add(m.group(0))
    return out


def _num_suffix(code: str) -> int:
    m = re.search(r"(\d+)$", str(code))
    return int(m.group(1)) if m else 10 ** 9


def event_data(event_id: str) -> dict:
    """读 scheduling/data/event_<id>.json（含 ex_stages/s_stages 的**权威顺序**）。"""
    p = EVENT_DATA / ("event_%s.json" % event_id)
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def read_prog(event_id: str) -> dict:
    """读 state.json 里该活动的已通进度（只读）。
    返回 {normal_done:set, raid_done:set, key:str}；缺失/异常 → 空集合（当全未通）。"""
    normal, raid = set(), set()
    key = "event_%s" % event_id
    try:
        st = json.load(open(STATE_JSON, encoding="utf-8"))
        pr = (st.get("progress") or {}).get(key) or (st.get("progress") or {}).get(event_id) or {}
        for k in ("first_clear_done", "ex_clear_done", "s_clear_done"):
            normal |= _stage_codes(pr.get(k))
        raid |= _stage_codes(pr.get("raid_clear_done"))
    except Exception:  # noqa: BLE001
        pass
    return {"normal_done": normal, "raid_done": raid, "key": key}


def update_progress(event_id: str, normal_ok=(), raid_ok=(), chain_note: str = ""):
    """把本轮**已通**的关写回 state.json.progress.<event_<id>>（沿用既有字段风格）。

    · 普通关 → 按类型写进 ex_clear_done / s_clear_done（EX/S）或 first_clear_done（故事关）；
    · 突袭   → raid_clear_done（用关卡代号）；
    · 顺带刷新 ex_pending / raid_pending 计数与 updated_at。
    """
    try:
        st = json.load(open(STATE_JSON, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log("[!] 读 state.json 失败，进度未回写: %r" % e)
        return
    pr = (st.setdefault("progress", {})).setdefault("event_%s" % event_id, {})
    for k in ("first_clear_done", "ex_clear_done", "s_clear_done", "raid_clear_done"):
        pr.setdefault(k, [])

    def _add(key, code):
        if code and code not in pr[key]:
            pr[key].append(code)

    for c in normal_ok:
        if "-EX-" in c:
            _add("ex_clear_done", c)
        elif "-S-" in c:
            _add("s_clear_done", c)
        else:
            _add("first_clear_done", c)
    for c in raid_ok:
        _add("raid_clear_done", c)

    d = event_data(event_id)
    ex = [s["code"] for s in (d.get("ex_stages") or [])]
    ss = [s["code"] for s in (d.get("s_stages") or [])]
    if ex:
        pr["ex_pending"] = max(0, len(ex) - len(set(ex) & set(pr["ex_clear_done"])))
    if ex or ss:
        allr = set(ex) | set(ss)
        pr["raid_pending"] = max(0, len(allr) - len(allr & set(pr["raid_clear_done"])))
    if chain_note:
        pr["last_chain_note"] = chain_note
    st["updated_at"] = time.strftime("%Y-%m-%d %H:%M")
    json.dump(st, open(STATE_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log("[*] 已回写进度 -> %s" % STATE_JSON)


# 链模式：kind -> (组标签, event 数据字段, 是否突袭)
CHAIN_KINDS = {
    "ex":    ("EX", "ex_stages", False),
    "raid":  ("EX", "ex_stages", True),      # EX 突袭
    "s":     ("S",  "s_stages",  False),
    "sraid": ("S",  "s_stages",  True),      # S 突袭
}


def chain_codes(event_id: str, kind: str):
    """该链的**按解锁顺序**的关卡代号数组（EX-1→EX-8 / S-1）。"""
    _lbl, listkey, _raid = CHAIN_KINDS[kind]
    codes = [s["code"] for s in (event_data(event_id).get(listkey) or [])]
    return sorted(codes, key=_num_suffix)



# ---------------------------------------------------------------------------
# 作业抓取 + 打分
# ---------------------------------------------------------------------------
def _min_required_ok(c) -> bool:
    mr = (c.get("minimum_required") or "v0.0.0").lstrip("v").split("-")[0]
    try:
        mv = tuple(int(x) for x in mr.split("."))
    except Exception:
        return True
    return mv <= MAX_CORE


def mastery_gap(c, own) -> tuple[int, int]:
    """作业用的是「哪个技能」→ 和我们的专精比，返回 (总缺口, 缺专三人数)。

    作业 `opers[].skill` 是 1/2/3（用第几个技能）；我们的 `spec` 是 [S1,S2,S3] 的专精等级。
    该技能专精 <3 就记 3-mastery 的缺口（专0=3、专一=2、专二=1、专三=0）。没有专精数据按 0 算。
    只做**排序偏好**，不做硬性过滤 —— 用户要求「不符合要求的作业也要试」。
    """
    tot = n = 0
    for o in (c.get("opers") or []):
        box = own.get(o.get("name") or "")
        if not box:
            continue
        try:
            sk = int(o.get("skill") or 1)
        except (TypeError, ValueError):
            sk = 1
        spec = box.get("spec") or []
        try:
            m = int(spec[sk - 1]) if 0 < sk <= len(spec) else 0
        except (TypeError, ValueError, IndexError):
            m = 0
        g = max(0, 3 - m)
        if g:
            n += 1
            tot += g
    return tot, n


def score(c, own):
    """(未拥有, 空组, 低练, 低练组, 专精总缺口, 缺专三人数)

    后两位只用于**排序**（专精越足越先试），不参与「可抄」判定 —— 见 copyable()。
    """
    indiv = c.get("opers", []) or []
    groups = c.get("groups", []) or []
    not_owned = sum(1 for o in indiv if elite(own, o["name"]) < 0)
    low = sum(1 for o in indiv if 0 <= elite(own, o["name"]) < 2)
    empty = glow = 0
    for g in groups:
        ms = g.get("opers") or []
        if any(elite(own, m["name"]) >= 2 for m in ms):
            continue
        if any(elite(own, m["name"]) >= 0 for m in ms):
            glow += 1
        else:
            empty += 1
    mg_sum, mg_n = mastery_gap(c, own)
    return (not_owned, empty, low, glow, mg_sum, mg_n)


def copyable(sc) -> bool:
    """用户铁律(2026-10-10)：作业要求的每个干员槽都 E2+ 才算「可抄」。
    等价于 未拥有=0 且 空组=0 且 低练=0 且 低练组=0（后两位专精缺口只用于排序）。"""
    return tuple(sc)[:4] == (0, 0, 0, 0)


def candidates_for(level_id: str, name: str, own, limit: int = 80, strict: bool = False):
    """返回按 [未拥有→空组→低练→热度] 排序的候选作业 [(score, id, content_dict), ...]
    strict=True 时只保留「全员/全组 E2+」的可抄候选（用户口径）。"""
    q = http_json("%s/copilot/query?%s" % (PRTS, urllib.parse.urlencode(
        {"page": 1, "limit": limit, "levelKeyword": name, "type": "PRTS"})))
    out = []
    for it in q["data"]["data"]:
        try:
            c0 = json.loads(it["content"])
        except Exception:
            continue
        if c0.get("stage_name") != level_id:
            continue
        if not _min_required_ok(c0):
            continue
        try:
            full = json.loads(http_json("%s/copilot/get/%d" % (PRTS, it["id"]))["data"]["content"])
        except Exception:
            continue
        if not full.get("actions"):       # MAA 要求非空 actions，否则解析失败
            continue
        out.append((score(full, own), -it.get("views", 0), it["id"], full,
                    (full.get("doc") or {}).get("title", "")))
    if strict:
        out = [x for x in out if copyable(x[0])]
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def save_copilot(event_id: str, code: str, content: dict) -> pathlib.Path:
    COPILOT_DIR.mkdir(parents=True, exist_ok=True)
    p = COPILOT_DIR / ("%s_%s.json" % (event_id, code))
    json.dump(content, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return p


# ---------------------------------------------------------------------------
# 执行（MaaCore 多作业模式：copilot_list 自带 OCR 关卡导航）
# ---------------------------------------------------------------------------
def _make_asst(cb):
    sys.path.insert(0, str(pathlib.Path(MAA) / "Python"))
    from asst.asst import Asst
    from asst.utils import InstanceOptionType
    # user_dir 指向临时目录，避免 MaaCore 的调试图写进当前工作目录(仓库)
    user_dir = pathlib.Path(os.environ.get("TEMP", ".")) / "arknights-mcp-maa"
    user_dir.mkdir(parents=True, exist_ok=True)
    Asst.load(MAA, user_dir=str(user_dir))
    a = Asst(Asst.CallBackType(cb))
    if not a.load(MAA):
        raise RuntimeError("Asst.load 失败")
    a.set_instance_option(InstanceOptionType.touch_type, TOUCH)
    if not a.connect(ADB, ADDR, "General"):
        raise RuntimeError("连接模拟器失败: %s" % ADDR)
    return a


def run_plan(event_id, plan, try_all=False, per_stage_timeout=360, formation_index=FORMATION_INDEX,
             loop=1, is_raid=False, stop_on_fail=False, deadline=None):
    """plan: [(stage_tuple, [(score, content, title, id), ...]), ...]
    逐关执行；try_all=True 时某关失败则自动换下一个候选（失败会退理智，代价低）。

    · `is_raid=True`：作业条目带 `is_raid`（**活动突袭只能走 Copilot**，MAA `Fight` 不支持）；
    · `stop_on_fail=True`（链模式）：某关未过 → 结束**本关**（后续关是否继续由调用方/解锁规则决定）；
    · 返回 `{stage_code: ok(bool)}`（供调用方回写进度）。
    """
    state = {"error": False, "stars": None}

    def cb(msg, detail, arg):
        if msg == 10000:  # AsstMsg::TaskChainError
            state["error"] = True
            log("    [x] TaskChainError")
        # 2 星时 MAA **不会**报 TaskChainError，只会匹配 StageDrops-Stars-Adverse；
        # 用户口径：两星也算没过（2026-10-19 实测 EX-3 被误记成 ok）。
        s = detail if isinstance(detail, str) else str(detail or "")
        if "StageDrops-Stars-3" in s:
            state["stars"] = 3
        elif "StageDrops-Stars-Adverse" in s and state.get("stars") != 3:
            state["stars"] = 2

    a = _make_asst(cb)
    results = {}

    for stage, cands in plan:
        code = stage[0]
        ok = False
        tried = cands if try_all else cands[:1]
        if not tried:
            log("[!] %s 无可用候选" % code)
        for j, (sc, content, title, cid) in enumerate(tried):
            if deadline is not None and time.time() > deadline:
                log("[!] 总预算用完 → 停止本关后续候选（%s）" % code)
                break
            if not content.get("actions"):
                continue
            p = save_copilot(event_id, code, content)
            log("[*] %s%s 候选%d id=%s %s -> %s"
                % (code, "（突袭）" if is_raid else "", j + 1, cid, title, p.name))
            state["error"] = False
            state["stars"] = None
            # ⚠ `nav_name_override: None` 会让 MaaCore 直接抛 C++ 异常
            #   （OSError 0xe06d7363 / WinError -529697949）→ append 直接崩。只有真有值时才带上这个键。
            # 而且活动 EX 关**必须**给值：作业里的 stage_name 是 level_id（act52side_ex01），
            # MAA 靠 stages.json 把 level_id 映射成显示名，而 EX 不在 stages.json 里 → 不给就找不到关。
            _item = {"id": 0, "filename": str(p), "is_raid": bool(is_raid),
                     "nav_name_override": str(stage[0])}
            tid = a.append_task("Copilot", {
                "formation": True,
                "formation_index": formation_index,   # 只用第四编队，不动别的编队
                "ignore_requirements": True,          # 练度不那么够也能用
                "loop_times": loop,                   # >1 = 刷关(重复同一关)
                "copilot_list": [_item],              # 突袭开关 is_raid（活动突袭必走 Copilot）
            })
            if not tid:
                log("    append 失败，跳过该候选")
                continue
            a.start()
            t0 = time.time()
            timed_out = False
            while a.running() and time.time() - t0 < per_stage_timeout:
                time.sleep(2)
            if a.running():
                timed_out = True
                a.stop()
            if not state["error"] and not timed_out and (is_raid or state.get("stars") == 3):
                log("    [v] 成功" + ("（3 星）" if state.get("stars") == 3 else
                                     ("（突袭：只判过/不过）" if is_raid else "")))
                ok = True
                break
            if timed_out:
                log("    [x] 超时（%ds）被停止 → 按未过处理，换下一个候选" % per_stage_timeout)
            elif state.get("stars") == 2 and not is_raid:
                log("    [x] 普通只有 2 星（未满 3 星，突袭不解锁）→ 按未过处理，换下一个候选")
            elif not is_raid and state.get("stars") is None:
                log("    [x] 没取到 3 星确认（可能点击/识别异常）→ 按未过处理，换下一个候选")
            else:
                log("    [x] 该候选未过，尝试下一个")
        results[code] = ok
        if not ok:
            log("[!] %s 所有候选均未成功（可能已 2 星通关，或需更高练度/换作业）" % code)
            if stop_on_fail:
                log("[!] %s 候选已试完，本关结束（后续是否继续由链决定）" % code)
                break
    log("=== 完成 ===")
    return results


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def cmd_events(_):
    ov = local_overview()
    ids = sorted({k.split("_")[0] for k in ov if k.startswith("act") and "side" in k.split("_")[0]})
    log("已知 side story 活动：")
    for i in ids:
        codes = sorted(v["code"] for k, v in ov.items() if k.startswith(i + "_") and v.get("code"))
        log("  %-12s %s" % (i, ",".join(codes[:14])))


def cmd_sync(args):
    if ensure_resource(args.event):
        log("[=] 资源就绪")
        for st in stages_of(args.event):
            log("   ", st[0], st[1], st[2])


def cmd_plan(args):
    own = load_box()
    stages = stages_of(args.event)
    if not stages:
        log("找不到活动 %s 的关卡；先跑 sync 或检查 id" % args.event)
        return
    for code, name, level_id, _fn in stages:
        cands = candidates_for(level_id, name, own)
        log("=" * 70)
        log("%s %s  候选 %d" % (code, name, len(cands)))
        for i, (sc, negv, cid, content, title) in enumerate(cands[:args.top]):
            mark = "★可抄" if copyable(sc) else "  不可抄"
            log("  #%d id=%-7d %s 未拥有=%d 空组=%d 低练=%d 低练组=%d 专精缺=%d(缺%d人)  %s" % (
                i + 1, cid, mark, sc[0], sc[1], sc[2], sc[3],
                (sc[4] if len(sc) > 4 else 0), (sc[5] if len(sc) > 5 else 0), title))


def _ov_index(event_id: str) -> dict:
    """MAA overview 里的 stage code -> (name, level_id)。"""
    return {code: (name, level_id) for (code, name, level_id, _fn) in stages_of(event_id)}


def _build_plan(event_id, codes, own, strict, first_missing_is_stop=True):
    """按 codes 顺序抓作业。返回 (plan, missing_code)：
    某关不在 MAA 资源（未开放/需 sync）或没有可抄作业 → 记为「卡点」并**不再往后抓**。"""
    ov = _ov_index(event_id)
    plan = []
    for code in codes:
        if code not in ov:
            log("[!] %s 不在 MAA 资源（未开放 / 需 sync）→ 无法导航" % code)
            return plan, code
        name, level_id = ov[code]
        cands = candidates_for(level_id, name, own, strict=strict)
        if not cands:
            log("[!] %s 无可用候选（可抄*）" % code)
            return plan, code
        plan.append(((code, name, level_id),
                     [(sc, content, title, cid) for (sc, negv, cid, content, title) in cands]))
    return plan, None


def _writeback(event_id, results, is_raid, note=""):
    """把本轮已通的关回写 state.json（跑完/失败都回写；失败时只更新 last_chain_note）。"""
    ok = [c for c, v in (results or {}).items() if v]
    if is_raid:
        update_progress(event_id, raid_ok=ok, chain_note=note)
    else:
        update_progress(event_id, normal_ok=ok, chain_note=note)


def _cmd_run_chain(args, own):
    """按「解锁链」执行（严格顺序、遇挫即停、跑完回写进度）。"""
    kind = args.chain
    lbl, listkey, is_raid = CHAIN_KINDS[kind]
    codes = chain_codes(args.event, kind)
    if not codes:
        log("[!] event_%s.json 里没有 %s 的关卡定义（%s）—— 跑 sync 或检查活动数据" % (args.event, lbl, listkey))
        return
    prog = read_prog(args.event)
    normal_key = "ex" if kind in ("ex", "raid") else "s"
    mode = "突袭" if is_raid else "普通"
    blocked = None
    if is_raid:
        todo = []
        for c in codes:
            if c not in prog["normal_done"]:
                blocked = c            # 该关普通未通 → 它和后面都没解锁（链到此为止）
                break
            if c in prog["raid_done"]:
                continue
            todo.append(c)
    else:
        first_un = next((i for i, c in enumerate(codes) if c not in prog["normal_done"]), None)
        todo = codes[first_un:] if first_un is not None else []
    if not todo:
        if blocked:
            log("[=] %s %s链：没有可打的突袭（卡在 %s：该关普通未通，先跑 --chain %s）"
                % (lbl, mode, blocked, normal_key))
        else:
            log("[=] %s %s链：没有要打的关（已全通 / 未解锁）" % (lbl, mode))
        return
    log("[*] %s %s链（依次解锁，遇挫即停）：%s" % (lbl, mode, " → ".join(todo)))
    plan, miss = _build_plan(args.event, todo, own, getattr(args, "strict", True))
    res = {}
    if plan:
        res = run_plan(args.event, plan, try_all=args.try_, per_stage_timeout=args.timeout,
                       formation_index=args.formation, loop=1, is_raid=is_raid, stop_on_fail=True)
    ok = [c for c, v in res.items() if v]
    # 「卡在哪」= todo 里第一个没成功的关；若 todo 全成功但链因「普通未通」到下不去 → 卡在 blocked
    stuck = next((c for c in todo if not res.get(c)), None)
    extra = ""
    if stuck is None and blocked:
        stuck, extra = blocked, "（该关普通未通）"
    if stuck and miss == stuck:
        extra = "（该关无作业/不在 MAA 资源 → 请换作业站作业或手点通关）"
        log("[!] %s 无作业/不在 MAA 资源 → 链停" % stuck)
    note = "%s%s链：成功[%s]；%s" % (lbl, mode, ",".join(ok) or "无",
                                   ("卡在 %s%s" % (stuck, extra)) if stuck else "全部完成")
    log("[=] " + note)
    _writeback(args.event, res, is_raid=is_raid, note=note)


def cmd_run(args):
    own = load_box()
    if getattr(args, "chain", ""):
        return _cmd_run_chain(args, own)
    stages = stages_of(args.event)
    if not stages:
        log("找不到活动 %s 的关卡" % args.event)
        return
    want = None
    if args.stages:
        want = set(args.stages.split(","))

    def selected(code: str) -> bool:
        return want is None or code in want or code.split("-", 1)[-1] in want

    codes = [code for (code, _n, _l, _f) in stages if selected(code)]
    plan, _miss = _build_plan(args.event, codes, own, getattr(args, "strict", True))
    if not plan:
        log("[!] 没有要执行的关卡")
        return
    res = run_plan(args.event, plan, try_all=args.try_, per_stage_timeout=args.timeout,
                   formation_index=args.formation, loop=args.loop, is_raid=getattr(args, "raid", False))
    _writeback(args.event, res, is_raid=getattr(args, "raid", False),
               note="%s：成功[%s]" % ("突袭" if getattr(args, "raid", False) else "普通",
                                     ",".join(c for c, v in res.items() if v) or "无"))


def _adb_tap(xy: str):
    x, y = [int(v) for v in xy.split(",")]
    import subprocess
    subprocess.run([ADB, "-s", ADDR, "shell", "input", "tap", str(x), str(y)], capture_output=True)


def _screencap_png(path: str):
    import subprocess
    with open(path, "wb") as f:
        subprocess.run([ADB, "-s", ADDR, "exec-out", "screencap", "-p"], stdout=f, timeout=40)


def _ocr_local(png: str) -> str:
    """调用本地 OCR 工具取字（仅文本，省 token）。可用 ARK_OCR_TOOL 覆盖路径。"""
    import subprocess
    default_tool = os.path.join(os.path.expanduser("~"), ".config", "opencode", "tools", "ocr", "ocr.py")
    tool = os.environ.get("ARK_OCR_TOOL", default_tool)
    try:
        r = subprocess.run([sys.executable, tool, png], capture_output=True, timeout=120)
        return r.stdout.decode("utf-8", "replace")
    except Exception as e:
        return "[ocr error] %s" % e


def cmd_shop(args):
    """翻活动商店：逐页截图+OCR 落盘（供人工/Agent 整理成数据文件的 shop）。
    前提：游戏停在活动商店页；**同一时刻只让一个程序驱动设备**（先关 MCP/MAA GUI）。
    翻页用 MaaCore 的 Custom 任务(SlowlySwipeToTheLeft)，因为本机 adb 滑动失效。"""
    outdir = pathlib.Path(args.outdir or (pathlib.Path(os.environ.get("TEMP", ".")) / "event-shop"))
    outdir.mkdir(parents=True, exist_ok=True)
    a = _make_asst(lambda m, d, x: None)
    prev = None
    for i in range(args.pages):
        png = str(outdir / ("shop_%02d.png" % i))
        _screencap_png(png)
        txt = _ocr_local(png)
        (outdir / ("shop_%02d.txt" % i)).write_text(txt, encoding="utf-8")
        first = " | ".join(txt.split("\n")[:6])
        log("[shop] page %d: %s" % (i, first[:300]))
        if prev is not None and txt.strip() == prev:
            log("  (与上页一致 → 可能到末尾/方向不对)")
        prev = txt.strip()
        tid = a.append_task("Custom", {"task_names": ["SlowlySwipeToTheLeft"]})
        if not tid:
            log("  swipe append 失败，停止"); break
        a.start()
        t0 = time.time()
        while a.running() and time.time() - t0 < 20:
            time.sleep(0.2)
        if a.running():
            a.stop()
        time.sleep(1.5)
    log("[shop] 截图+文本已落盘：%s" % outdir)


def cmd_goto(args):
    """简易导航：主页按钮 -> 当期活动 banner -> 活动主页的『关卡地图』入口。
    坐标是事件/分辨率相关的经验值；换活动/分辨率请用 --home-xy/--banner-xy/--hub-xy 覆盖。
    更稳的做法是用 MCP 的 ark_where/ark_find 判页面、ark_tap 点击（见工作流文档『导航层』）。"""
    log("[goto] 回主页 %s" % args.home_xy)
    _adb_tap(args.home_xy); time.sleep(3)
    log("[goto] 点活动 banner %s" % args.banner_xy)
    _adb_tap(args.banner_xy); time.sleep(3)
    log("[goto] 进关卡地图 %s" % args.hub_xy)
    _adb_tap(args.hub_xy); time.sleep(3)
    log("[goto] 完成（若没到 YW-N 关卡列表，用 MCP 工具微调坐标/手动点）")


def main():
    ap = argparse.ArgumentParser(description="活动关作业工作流")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("events").set_defaults(func=cmd_events)

    p = sub.add_parser("sync"); p.add_argument("event"); p.set_defaults(func=cmd_sync)

    p = sub.add_parser("plan"); p.add_argument("event"); p.add_argument("--top", type=int, default=6)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run"); p.add_argument("event")
    p.add_argument("--stages", default=""); p.add_argument("--all", action="store_true")
    p.add_argument("--raid", action="store_true",
                   help="按突袭打（is_raid=true；活动突袭只能走 Copilot，MAA Fight 不支持）")
    p.add_argument("--chain", choices=["ex", "raid", "s", "sraid"], default="",
                   help="按解锁链执行（ex=EX普通 / raid=EX突袭 / s=S普通 / sraid=S突袭）："
                        "依次解锁、遇挫即停、跑完回写进度")
    p.add_argument("--try", dest="try_", action="store_true")
    p.add_argument("--timeout", type=int, default=360)
    p.add_argument("--loop", type=int, default=1, help="重复次数(=1 通关一次；>1 刷代币)")
    p.add_argument("--formation", type=int, default=FORMATION_INDEX,
                   help="自动编队用第几个编队(默认 4=第四编队，不会动其它编队)")
    p.add_argument("--no-strict", dest="strict", action="store_false", default=True,
                   help="放宽准入：不要求全员/全组精二(默认严格=只用可抄作业)")
    p.set_defaults(func=cmd_run)

    g = sub.add_parser("goto", help="从当前画面导航到活动关卡列表(首页→活动→关卡)")
    g.add_argument("--home-xy", default="370,45", help="主页按钮坐标(默认 370,45)")
    g.add_argument("--banner-xy", default="1770,205", help="当期活动 banner 坐标")
    g.add_argument("--hub-xy", default="1400,860", help="活动主页里『关卡地图』入口坐标")
    g.set_defaults(func=cmd_goto)

    s = sub.add_parser("shop", help="翻活动商店：逐页截图+OCR 落盘(左右翻页, 用 MAA Custom 滑动)")
    s.add_argument("--pages", type=int, default=8)
    s.add_argument("--outdir", default="")
    s.set_defaults(func=cmd_shop)

    ap.set_defaults(func=None)

    args = ap.parse_args()
    if args.cmd == "run" and not args.stages and not args.all and not args.chain:
        ap.error("run 需要 --stages 或 --all（或 --chain ex|raid|s|sraid 跑解锁链）")
    args.func(args)


if __name__ == "__main__":
    main()
