"""森空岛 -> MAA 数据形态 适配器（**免模拟器**在线取数）。

把 `zonai.skland.com` 的 `player/info` 转成与 MAA `OperBoxData.json` **同构**的
`{done, own_opers:[...]}`，使 `scripts/event-copilot/`、`scheduling/tools/oper_appearance.py`、
`base_gap*.py`、一图流「导入 MAA JSON」等既有消费方**零改动**即可换数据源；
另提供基建状态（MCP 原先没有此查询）。

面向的调用方：
    - MCP 工具 `ark_operbox_online()` / `ark_infrast_status()`（见仓库根 `arknights_mcp.py`）
    - 命令行：`python skland_cli.py dump`（原始 JSON）

字段映射（**两处 off-by-one 必须注意**）：
    id = charId             name = charInfoMap[charId].name
    elite = evolvePhase      level = level
    rarity = charInfoMap[charId].rarity + 1     # MAA 1 起算，Skland 0 起算
    potential = potentialRank + 1               # 同上
    own = True               （`chars` 数组本身即"已拥有"）
    超集（MAA 给不了）：skill_lvl=mainSkillLvl、spec=skills[].specializeLevel、favor、profession

实测对拷（账号「博士」）：MAA 337 个 owned ↔ Skland 339 个 chars，**同名 337、精英/等级/星级逐个一致**；
差的是 rarity/potential 各 +1 的固定偏移（见上）。Skland 多出的是 MAA 本地资源尚未收录的新干员。

⚠️ 依赖：先 `python scripts/skland/skland_cli.py login` 存好凭证（`~/.arknights_skland.json`）。
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skland_client as sk  # noqa: E402

# 基建设施：中文名 -> player/info.building 的键
FACILITIES = [
    ("控制中枢", "control"), ("贸易站", "tradings"), ("制造站", "manufactures"),
    ("发电站", "powers"), ("宿舍", "dormitories"), ("会客室", "meeting"),
    ("办公室", "hire"), ("训练室", "training"),
]


def _cred():
    cfg = sk.load_config()
    if not cfg.get("cred"):
        raise sk.SklandError(-1, "本地无森空岛凭证：先跑 `python scripts/skland/skland_cli.py login`")
    return cfg["cred"], cfg.get("token"), cfg.get("uid")


def _resolve_uid(cred, token, uid=None):
    uid = uid or sk.load_config().get("uid")
    if not uid:
        roles = sk.binding(cred, token)
        uid = roles[0]["uid"] if roles else None
        if uid:
            sk.save_config(uid=uid)
    if not uid:
        raise sk.SklandError(-1, "该账号没有绑定明日方舟角色")
    return uid


# ---------------------------------------------------------------- 转换

def to_operbox(info: dict) -> dict:
    """player/info -> OperBoxData 同构。"""
    im = info.get("charInfoMap") or {}
    ops = []
    for c in info.get("chars") or []:
        cid = c.get("charId")
        meta = im.get(cid) or {}
        r = meta.get("rarity")
        ops.append({
            "id": cid,
            "name": meta.get("name", cid),
            "elite": c.get("evolvePhase", 0),
            "level": c.get("level", 0),
            "own": True,
            "potential": (c.get("potentialRank") or 0) + 1,
            "rarity": (r + 1) if isinstance(r, int) and r >= 0 else 0,
            "profession": meta.get("profession", ""),
            # 超集（MAA 无）
            "skill_lvl": c.get("mainSkillLvl"),
            "spec": [s.get("specializeLevel", 0) for s in (c.get("skills") or [])],
            "favor": c.get("favorPercent"),
        })
    return {"done": True, "own_opers": ops, "own_count": len(ops),
            "source": "skland", "syncedAt": info.get("currentTs") or int(time.time())}


def to_base(info: dict) -> dict:
    """player/info -> 基建状态（按设施分组的槽位 + 进驻干员）。"""
    b = info.get("building") or {}
    im = info.get("charInfoMap") or {}

    def nm(cid):
        return (im.get(cid) or {}).get("name", cid) if cid else None

    def cid_of(x):
        return x.get("charId") if isinstance(x, dict) else x

    rooms = []
    for title, key in FACILITIES:
        slots = b.get(key)
        if not slots:
            continue
        if isinstance(slots, dict):
            slots = [slots]
        for s in slots:
            ops = [{"id": c.get("charId"), "name": nm(c.get("charId")),
                    "index": c.get("index"), "ap": c.get("ap"),
                    "workTime": c.get("workTime")}
                   for c in s.get("chars") or []]
            rooms.append({
                "facility": title, "key": key, "slotId": s.get("slotId"),
                "level": s.get("level"), "operators": ops,
                "trainee": nm(cid_of(s.get("trainee"))),
            })
    labor = b.get("labor") or {}
    furn = b.get("furniture")
    if isinstance(furn, dict):
        furn = furn.get("total")
    return {"done": True, "source": "skland", "rooms": rooms,
            "drone": labor, "furniture": furn,
            "tiredChars": [nm(cid_of(x)) for x in (b.get("tiredChars") or [])]}


# ---------------------------------------------------------------- 取数入口

def fetch_player_info(uid: str = "") -> dict:
    cred, token, cfg_uid = _cred()
    uid = _resolve_uid(cred, token, uid or cfg_uid)
    return sk.player_info(cred, uid, token)


def fetch_operbox(uid: str = "") -> dict:
    """在线干员箱（OperBoxData 同构）。"""
    return to_operbox(fetch_player_info(uid))


def fetch_base(uid: str = "") -> dict:
    """在线基建状态。"""
    return to_base(fetch_player_info(uid))


def save_operbox(path: str, uid: str = "") -> dict:
    """把在线干员箱写成 OperBoxData.json 同构文件（供既有脚本直接吃）。"""
    data = fetch_operbox(uid)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    data["saved_to"] = path
    return data


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="森空岛 -> MAA 形态适配器")
    p.add_argument("what", choices=["operbox", "base"], help="取干员箱 or 基建状态")
    p.add_argument("--uid")
    p.add_argument("--out", help="operbox 时写一份同构 JSON 到此路径")
    a = p.parse_args()
    if a.what == "operbox":
        d = save_operbox(a.out, a.uid) if a.out else fetch_operbox(a.uid)
        print(json.dumps({k: v for k, v in d.items() if k != "own_opers"}, ensure_ascii=False))
        print("own_opers:", len(d["own_opers"]))
    else:
        print(json.dumps(fetch_base(a.uid), ensure_ascii=False, indent=2))
