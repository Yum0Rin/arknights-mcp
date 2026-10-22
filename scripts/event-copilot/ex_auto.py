#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""活动 EX 关自动链（把 2026-10-18 手工摸出来的流程固化，以后新活动直接套）。

背景 / 为什么单独一个脚本
------------------------
MAA 的 `Fight` 只认 `resource/stages.json` 里的关（有掉落价值的普通关），**活动 EX 关不在里面**；
但 **Copilot 能打**：它靠 `Arknights-Tile-Pos/overview.json` 的 `code`（如 `YW-EX-1`）+ OCR 点关来导航。
2026-10-18 实测踩到的三条硬知识（详见 docs/FINDINGS.md §25）：

1. `sync` 之后**必须重启 MCP/MAA 才生效**（MaaCore 启动时缓存资源）；资源没落地时报「不在 MAA 资源」是假象。
2. `copilot_list[].nav_name_override` **必须给关卡代号**（如 `YW-EX-1`）：作业里的 `stage_name` 是 level id
   （`act52side_ex01`），MAA 靠 stages.json 映射显示名，EX 不在表里 → 不给就找不到关。
   而且**传 None 会让 MaaCore 抛 C++ 异常**（`OSError 0xe06d7363`）——已在 event_copilot.run_plan 修好。
3. 「全员精二」不等于能抄：2~3 人极限作业还要看**专精**。实测 EX-1 的 3 人作业一次过；
   EX-2 三个全员 E2 候选全败（凛御银灰/予愿安洁莉娜 专0），换「单核挂件兼容」作业才过。
   → 本脚本按 **strict(E2) → compat(单核/挂件兼容/低练组≤1)** 两档依次试。

用法
----
  python scripts/event-copilot/ex_auto.py act52side                    # 自动进 EX 页 → 普通连打未通关
  python scripts/event-copilot/ex_auto.py act52side --dry              # 只看计划，不动设备
  python scripts/event-copilot/ex_auto.py act52side --raid             # 突袭链（要求该关普通已通）
  python scripts/event-copilot/ex_auto.py act52side --max-candidates 3 # 每关最多试几个候选
  python scripts/event-copilot/ex_auto.py act52side --no-goto          # 已经停在 EX 页时跳过导航

留痕：scheduling/data/ex_run.jsonl（每关每次尝试一行）+ docs/state.json.progress.<event 字段>
实测机器：雷电 1920x1080 / MaaTouch / 单客户端（跑前别开 MAA GUI）。
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

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "skland"))

import event_copilot as ec  # noqa: E402  复用：box/候选/run_plan/回写

ADB = ec.ADB
ADDR = ec.ADDR
REPORT = ROOT / "scheduling" / "data" / "ex_run.jsonl"
OCR_DIR = pathlib.Path.home() / ".config" / "opencode" / "tools" / "ocr"
SHOT_DIR = pathlib.Path(os.environ.get("TEMP", ".")) / "event-ex"


def log(msg: str) -> None:
    print("[ex] %s" % msg, flush=True)


# ---------------------------------------------------------------- 截图 / OCR
def _shot(tag: str) -> pathlib.Path:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    p = SHOT_DIR / ("%s_%s.png" % (tag, dt.datetime.now().strftime("%H%M%S")))
    with open(p, "wb") as f:
        subprocess.run([ADB, "-s", ADDR, "exec-out", "screencap", "-p"],
                       stdout=f, timeout=40)
    return p


def _ocr_boxes(png) -> list:
    """整帧 OCR → [{text, cx, cy}]（本地 RapidOCR，纯 CPU）。"""
    sys.path.insert(0, str(OCR_DIR))
    import ocr as ocrlib  # noqa: PL0415
    return ocrlib.recognize(str(png), True) or []


def _tap(x, y) -> None:
    subprocess.run([ADB, "-s", ADDR, "shell", "input", "tap", str(int(x)), str(int(y))],
                   capture_output=True, timeout=20)


def _back(n: int = 1) -> None:
    for _ in range(n):
        subprocess.run([ADB, "-s", ADDR, "shell", "input", "keyevent", "4"],
                       capture_output=True, timeout=20)
        time.sleep(1.2)


def _find(boxes, pred):
    for b in boxes:
        t = (b.get("text") or "").strip()
        if pred(t):
            return b
    return None


def _on_ex_page(boxes) -> bool:
    """EX 关卡列表判定：能看到 `XX-EX-1` 这种关卡名。"""
    import re
    return any(re.search(r"[A-Z]{1,4}-EX-\d", (b.get("text") or "")) for b in boxes)


# ---------------------------------------------------------------- 导航
def goto_ex(event_id: str, tries: int = 3) -> bool:
    """把游戏带到该活动的 **EX 关卡列表**。

    步骤（OCR 定位，坐标只作兜底）：
      当前已在 EX 页 → 直接就绪；
      否则 BACK 回主界面 → 点活动名 → 点 EX 入口 → 校验。
    """
    ev = ec.event_data(event_id)
    ev_name = (ev.get("name") or "").strip()
    log("目标活动：%s（%s）" % (event_id, ev_name or "<无名>"))
    for i in range(max(1, tries)):
        boxes = _ocr_boxes(_shot("nav_%d" % i))
        if _on_ex_page(boxes):
            log("已在 EX 关卡列表 ✅")
            return True

        # 主界面：找活动名（如「昨日海」）
        b = _find(boxes, lambda t: ev_name and ev_name in t)
        if b:
            log("点活动入口 %s (%s,%s)" % (ev_name, b["cx"], b["cy"]))
            _tap(b["cx"], b["cy"])
            time.sleep(6)
            boxes = _ocr_boxes(_shot("hub_%d" % i))
            if _on_ex_page(boxes):
                return True
            # 活动主页：找「EX」入口
            b2 = _find(boxes, lambda t: t.upper() == "EX")
            if b2:
                log("点 EX 入口 (%s,%s)" % (b2["cx"], b2["cy"]))
                _tap(b2["cx"], b2["cy"])
                time.sleep(5)
                if _on_ex_page(_ocr_boxes(_shot("exmap_%d" % i))):
                    log("已进入 EX 关卡列表 ✅")
                    return True
            log("活动主页没找到 EX 入口（截图见 %s）" % SHOT_DIR)
        else:
            log("当前不在主界面/没看到活动入口 → 按 BACK 回退")
        _back(1)
    log("!! 没能自动进到 EX 关卡列表；请手动停在 EX 页后加 --no-goto 重跑")
    return False


# ---------------------------------------------------------------- 候选分档
def tiered_candidates(event_id: str, code: str, name: str, level_id: str, own, limit: int,
                      relaxed: bool = False, is_raid: bool = False):
    """返回 [(tier, score, cid, content, title)]，按「先 strict 后 compat」排。

    strict = 作业里每个干员槽都 E2+（用户铁律，2026-10-10）。
    compat = 单核/挂件兼容类（可能有 1 个低练组），**实测最容易被卡时靠它过关**（EX-2）。
    relaxed = strict/compat 都失败后，把剩余候选（不按标题过滤）也放进来，继续换作业。
    """
    out = []
    for tier, strict in (("strict", True), ("compat", False)):
        cands = ec.candidates_for(level_id, name, own, limit=80, strict=strict)
        for sc, _negv, cid, content, title in cands:
            _ttl = title or ""
            if is_raid and "仅普通" in _ttl:
                continue
            if (not is_raid) and "仅突袭" in _ttl:
                continue
            if tier == "compat":
                # compat 档只收「差一点点」的：未拥有=0 且 空组=0 且 低练+低练组 ≤ 1
                if sc[0] != 0 or sc[1] != 0 or (sc[2] + sc[3]) > 1:
                    continue
                ttl = (title or "")
                if not any(k in ttl for k in ("单核", "挂件", "兼容", "低配", "一摆")):
                    continue
            out.append((tier, sc, cid, content, title))
    if relaxed:
        _have = {x[2] for x in out}
        for sc, _negv, cid, content, title in ec.candidates_for(level_id, name, own, limit=80, strict=False):
            _ttl = title or ""
            if is_raid and "仅普通" in _ttl:
                continue
            if (not is_raid) and "仅突袭" in _ttl:
                continue
            if cid in _have:
                continue
            _have.add(cid)
            out.append(("relax", sc, cid, content, title))
    # 去重（同一 id 可能两档都命中）
    seen, uniq = set(), []
    for x in out:
        if x[2] in seen:
            continue
        seen.add(x[2])
        uniq.append(x)
    return uniq[:limit] if limit else uniq


# ---------------------------------------------------------------- 报告
def _report(entry: dict) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **entry}
    with open(REPORT, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 主流程
def run_chain(event_id: str, kind: str, own, max_cands: int, per_stage_timeout: int,
              dry: bool = False, deadline: float | None = None,
              force_codes: list | None = None, skip_ids=None,
              cand_offset: int = 0, relaxed: bool = False,
              second_pass_max: int = 6) -> dict:
    codes = ec.chain_codes(event_id, kind)          # 已按关卡序号排序
    prog = ec.read_prog(event_id)
    is_raid = kind in ("raid", "sraid")
    done_key = "raid_done" if is_raid else "normal_done"
    normal_done = prog["normal_done"]

    if force_codes:
        todo = [c for c in codes if c in set(force_codes)]
        log("强制重打：%s（无视已通/解锁，用于普通 2 星补 3 星）" % "、".join(todo))
    else:
        todo = []
        for c in codes:
            if c in prog[done_key]:
                continue
            if is_raid and c not in normal_done:
                log("%s 普通未通 → 突袭链到此为止" % c)
                break
            todo.append(c)
    if not todo:
        log("没有要打的关（已全通 / 未解锁）")
        return {}

    log("计划：%s（%s）" % (" → ".join(todo), "突袭" if is_raid else "普通"))
    ov = {code: (name, level_id) for (code, name, level_id, _f) in ec.stages_of(event_id)}
    results: dict = {}

    _skip = {str(x) for x in (skip_ids or set())}

    def _cands(code):
        name, level_id = ov[code]
        cands = tiered_candidates(event_id, code, name, level_id, own, max_cands, relaxed=relaxed, is_raid=is_raid)
        if _skip:
            kept = [c for c in cands if str(c[2]) not in _skip]
            if len(kept) != len(cands):
                log("  跳过指定作业 id：%s" % "、".join(sorted(_skip)))
            cands = kept
        if cand_offset and cand_offset > 0:
            if cands:
                log("  从第 %d 个候选开始（跳过前 %d 个已试过的）" % (cand_offset + 1, cand_offset))
            cands = cands[cand_offset:]
        return name, cands

    def _log_cands(code, name, cands, tag=""):
        log("=" * 60)
        log("%s %s：%s候选 %d（strict→compat）" % (code, name, tag, len(cands)))
        for i, (tier, sc, cid, _c, title) in enumerate(cands):
            log("  #%d [%s] id=%s 未拥有=%d 空组=%d 低练=%d 低练组=%d 专精缺=%d(缺%d人) %s" % (
                i + 1, tier, cid, sc[0], sc[1], sc[2], sc[3],
                (sc[4] if len(sc) > 4 else 0), (sc[5] if len(sc) > 5 else 0), title))

    def _attempt(code, name, level_id, cands, tag=""):
        plan = [((code, name, level_id), [((sc, c, title, cid)) for (_t, sc, cid, c, title) in cands])]
        t0 = time.time()
        res = ec.run_plan(event_id, plan, try_all=True, per_stage_timeout=per_stage_timeout,
                          formation_index=ec.FORMATION_INDEX, loop=1,
                          is_raid=is_raid, stop_on_fail=True, deadline=deadline)
        ok = bool(res.get(code))
        elapsed = round(time.time() - t0)
        results[code] = results.get(code, False) or ok
        _report({"event": event_id, "chain": kind, "stage": code, "pass": tag or "单遍",
                 "ok": ok, "elapsed": elapsed,
                 "tried": [{"tier": t, "id": cid, "score": list(sc), "title": title}
                           for (t, sc, cid, _c, title) in cands]})
        log("  → %s%s（%ds）" % ("通过 ✅" if ok else "本批候选失败 ❌",
                                ("（%s）" % tag) if tag else "", elapsed))
        ec._writeback(event_id, {code: ok}, is_raid=is_raid,
                      note="ex_auto %s：%s %s%s" % (kind, code, "ok" if ok else "失败",
                                                    ("（%s）" % tag) if tag else ""))
        return ok

    def _budget_out(left):
        if deadline is not None and time.time() > deadline:
            log("!! 本次总预算用完 → 剩余 %s 下次再打" % "、".join(left))
            return True
        return False

    if is_raid:
        # 第一遍：每关只试第 1 个候选；打不过的先记下，继续把其他关打完。
        for idx, code in enumerate(todo):
            if _budget_out(todo[idx:]):
                return results
            if code not in ov:
                log("!! %s 不在 overview（资源没落地？先 sync 并重启 MAA）→ 停" % code)
                return results
            name, cands = _cands(code)
            _log_cands(code, name, cands, "第一遍 ")
            if dry:
                continue
            if not cands:
                log("  无候选 → 跳过，继续后面的突袭")
                continue
            _attempt(code, name, ov[code][1], cands[:1], "第一遍")
            time.sleep(2)
        if dry:
            return results

        # 第二遍：回头把第一遍没过的关，用剩下的候选换作业再试。
        left = [c for c in todo if not results.get(c)]
        if left:
            log("#" * 60)
            log("第一遍结束：%s 未过 → 回头换作业再试" % "、".join(left))
        for idx, code in enumerate(left):
            if _budget_out(left[idx:]):
                break
            name, cands = _cands(code)
            _cap = max(0, second_pass_max)
            rest = cands[1:1 + _cap] if _cap else cands[1:]
            if len(cands) - 1 > len(rest):
                log("%s：第二遍最多再试 %d 个（共剩 %d 个）" % (code, len(rest), len(cands) - 1))
            if not rest:
                log("%s：没有更多候选（%d 个已试完）" % (code, len(cands)))
                continue
            _log_cands(code, name, rest, "第二遍换作业 ")
            _attempt(code, name, ov[code][1], rest, "第二遍换作业")
            time.sleep(2)
        return results

    # 普通链：顺序解锁，失败即停；每关照旧把候选试完。
    for idx, code in enumerate(todo):
        if _budget_out(todo[idx:]):
            break
        if code not in ov:
            log("!! %s 不在 overview（资源没落地？先 sync 并重启 MAA）→ 停" % code)
            break
        name, cands = _cands(code)
        _log_cands(code, name, cands)
        if dry:
            continue
        if not cands:
            log("  无候选 → 停")
            break
        if not _attempt(code, name, ov[code][1], cands):
            log("  链停在这里（后续普通关依赖前一关解锁）")
            break
        time.sleep(2)
    return results


def pending_events(with_raid: bool = False) -> list[tuple[str, int, str]]:
    """扫 scheduling/data/event_*.json，返回 [(event_id, 剩余关数, chain)] —— 有 EX 且没打完的。

    不需要人工指定活动/关卡：新活动只要有了 event_<id>.json（含 ex_stages），就会被自动发现。
    """
    out = []
    for p in sorted((ROOT / "scheduling" / "data").glob("event_*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        ev_id = p.stem[len("event_"):]
        codes = [s.get("code") for s in (d.get("ex_stages") or []) if s.get("code")]
        if not codes:
            continue
        try:
            prog = ec.read_prog(ev_id)
        except Exception:  # noqa: BLE001
            prog = {"normal_done": set(), "raid_done": set()}
        left = [c for c in codes if c not in prog.get("normal_done", set())]
        if left:
            out.append((ev_id, len(left), "ex"))
            continue
        if with_raid:
            raids = [c for c in codes if c not in prog.get("raid_done", set())]
            if raids:
                out.append((ev_id, len(raids), "raid"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="活动 EX 关自动链（MAA Copilot）")
    ap.add_argument("event", nargs="?", default="", help="活动 id（省略且加 --auto = 自动发现所有未通的）")
    ap.add_argument("--auto", action="store_true",
                    help="自动扫 scheduling/data/event_*.json：把没打完的 EX 全打掉（14:00 日常会调用）")
    ap.add_argument("--with-raid", action="store_true", help="自动模式下顺带打突袭（理智够才建议开）")
    ap.add_argument("--chain", default="ex", choices=["ex", "raid"])
    ap.add_argument("--max-candidates", type=int, default=6, help="每关最多试几个候选（默认 6）")
    ap.add_argument("--timeout", type=int, default=900, help="单关单候选超时（秒）")
    ap.add_argument("--budget", type=int, default=4800,
                    help="本次 ex_auto 总预算（秒，0=不限；默认 4800，给 14:00 日常外层 5400s 留余量）")
    ap.add_argument("--no-goto", action="store_true", help="跳过导航（已停在 EX 关卡列表）")
    ap.add_argument("--stages", default="",
                    help="强制只跑这些关（逗号分隔，代号或序号，如 4 或 YW-EX-4；需同时给 event）")
    ap.add_argument("--skip-ids", default="", help="跳过这些作业 id（逗号分隔，已知打不过/2 星的）")
    ap.add_argument("--candidate-offset", type=int, default=0,
                    help="从第 N+1 个候选开始（跳过前 N 个已试过的，默认 0）")
    ap.add_argument("--relaxed", action="store_true",
                    help="strict/compat 都失败后，把剩余候选（不按标题过滤）也加入，继续换作业")
    ap.add_argument("--second-pass-max", type=int, default=6,
                    help="第二遍每关最多再试几个候选（默认 6，防止单关空转几小时）")
    ap.add_argument("--dry", action="store_true", help="只打印计划，不动设备")
    a = ap.parse_args()
    deadline = (time.time() + a.budget) if a.budget and a.budget > 0 else None
    force = None
    if a.stages:
        if not a.event:
            ap.error("--stages 需要同时给 event（例如 act52side）")
        _all = ec.chain_codes(a.event, a.chain)
        _want = {x.strip() for x in a.stages.split(",") if x.strip()}
        force = [c for c in _all if c in _want or c.rsplit("-", 1)[-1] in _want]
        if not force:
            log("!! --stages 没匹配到关卡：%s" % a.stages)
            return 2

    # ---- 自动模式：自己决定打哪个活动/哪条链（不需要任何人工点击）----
    if a.auto:
        todo = pending_events(with_raid=a.with_raid)
        if not todo:
            log("没有未通的 EX 关（或没有 event_*.json）→ 什么都不做")
            return 0
        log("自动发现：%s" % "；".join("%s 剩 %d 关(%s)" % t for t in todo))
        own = ec.load_box()
        rc_all = 0
        for ev_id, _left, chain in todo:
            ex_codes = [c for (c, _n, _l, _f) in ec.stages_of(ev_id) if "-EX-" in c]
            if not ex_codes:
                log("!! overview 里没有 %s 的 EX 关 → 先 sync 并重启 MAA（跳过）" % ev_id)
                rc_all = 2
                continue
            if a.dry:
                run_chain(ev_id, chain, own, a.max_candidates, a.timeout, dry=True, deadline=deadline)
                continue
            if not goto_ex(ev_id):
                rc_all = 3
                continue
            res = run_chain(ev_id, chain, own, a.max_candidates, a.timeout, deadline=deadline)
            if res and not all(res.values()):
                rc_all = 1
            # 普通清完后**接着打突袭**（活动突袭双倍理智；够不够由 MAA 自己停）
            if a.with_raid and chain == "ex" and res and all(res.values()):
                log("普通已清完 → 接着打突袭链")
                if goto_ex(ev_id):
                    rres = run_chain(ev_id, "raid", own, a.max_candidates, a.timeout, deadline=deadline)
                    if rres and not all(rres.values()):
                        rc_all = 1
        if a.dry:
            log("[dry] 未执行")
        return rc_all

    if not a.event:
        ap.error("要么给 event，要么加 --auto")

    # 0) 资源检查：overview 必须已含该活动的 EX（stages.json 不含 EX 是正常的！）
    ex_codes = [c for (c, _n, _l, _f) in ec.stages_of(a.event) if "-EX-" in c]
    if not ex_codes:
        log("!! overview 里没有 %s 的 EX 关 → 先跑 `python scripts/event-copilot/event_copilot.py "
            "sync %s`，**并重启 MCP/MAA**（MaaCore 启动时缓存资源）" % (a.event, a.event))
        return 2
    log("overview 已含 EX 关 %d 个（%s…）" % (len(set(ex_codes)), sorted(set(ex_codes))[0]))

    own = ec.load_box()
    if a.dry:
        run_chain(a.event, a.chain, own, a.max_candidates, a.timeout, dry=True, deadline=deadline, force_codes=force, skip_ids={x.strip() for x in a.skip_ids.split(",") if x.strip()}, cand_offset=a.candidate_offset, relaxed=a.relaxed, second_pass_max=a.second_pass_max)
        log("[dry] 未执行")
        return 0

    if not a.no_goto and not goto_ex(a.event):
        return 3

    res = run_chain(a.event, a.chain, own, a.max_candidates, a.timeout, deadline=deadline, force_codes=force, skip_ids={x.strip() for x in a.skip_ids.split(",") if x.strip()}, cand_offset=a.candidate_offset, relaxed=a.relaxed, second_pass_max=a.second_pass_max)
    ok = [c for c, v in res.items() if v]
    log("==== 结束：通过 %s；失败/未打 %s ====" % (",".join(ok) or "无",
                                                ",".join(c for c, v in res.items() if not v) or "无"))
    return 0 if res and all(res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
