#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""明日方舟官方「寻访记录」（抽卡记录）客户端 —— 鹰角网络用户中心。

⚠ 与 `skland_client.py` 的**关键区别**（别搞混）：

    | | 森空岛 Skland | 用户中心（本模块） |
    |---|---|---|
    | 域名 | `zonai.skland.com` | `ak.hypergryph.com` |
    | 数据 | 干员 / 基建 / 签到 … | **抽卡记录**（官网 → 个人中心 → 自助查询） |
    | 鉴权 | `cred` + `sign` 签名头 | 请求头 `x-role-token`/`x-account-token` + cookie `ak-user-center` |
    | 抽卡记录 | **没有** | **有** |

两套接口共用同一套鹰角通行证登录，分叉点在 OAuth `grant`：

    appCode="be36d44aa36bfb5b" + type=1  → 用户中心 OAuth token（本模块）
    appCode="4ca99fa6b56cc2ba" + type=0  → 森空岛一次性 code（skland_client）

**用错 appCode 拿不到抽卡记录**（只会得到一次性 code），这是本流程最容易踩的坑。

登录链（6 步）：
    1 账号 token（as.hypergryph.com，复用森空岛登录的产物）
    2 grant            → OAuth token
    3 binding_list     → 角色 uid（含 官服 / B服 渠道）
    4 u8_token_by_uid  → u8_token（后续走 x-role-token 头）
    5 role/login       → ak-user-center cookie（缺了接口只回 {"reason":"MissingCookie"}）
    （终末地到第 4 步就够，明日方舟多第 5 步）

接口来自社区逆向（Gordenghost/arklog、AceDroidX/arknights-gacha-export、RoLingG/Arknights_Gacha），
鹰角随时可能改版。**仅限官服**：B 服是 B 站账号、国际服（Yostar）没有这个接口。

已知坑（写进代码里的）：
  - 旧端点 `/user/api/inquiry/gacha?page=&token=` 已废弃 → 现在返回 HTML（会被 `_envelope` 认出来）。
  - `history` 一条 = **一抽**；十连 = 10 条 `gachaTs` 相同、`pos` 0..9 的记录。
  - `rarity` 是 **0 基**（5 表示 6★）；`gachaTs` 是**毫秒**（常为字符串）。
  - 翻页游标是上一页最后一条的 `pos` + `gachaTs`，**不是**页码。
  - 接口不提供唯一 ID，去重键必须自己合成，且 `pos` 不能省（一次十连里的重复干员只差 `pos`）。
"""
from __future__ import annotations

import gzip
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- 常量

APP_CODE_USER_CENTER = "be36d44aa36bfb5b"   # 「明日方舟用户中心」的 appCode（≠ 森空岛的）
GRANT_TYPE_TOKEN = 1                        # type=1 → grant 直接返回 data.token
BINDING_APP_CODE = "arknights"              # binding_list 里筛明日方舟

AS_BASE = "https://as.hypergryph.com"
BINDING_BASE = "https://binding-api-account-prod.hypergryph.com"
AK_BASE = "https://ak.hypergryph.com"

GACHA_REFERER = f"{AK_BASE}/user/headhunting"      # 官网寻访记录页
GACHA_PAGE_URL = f"{AK_BASE}/user/headhunting"     # 给 GUI「打开官网」用

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

ARCHIVE_PATH = os.path.join(os.path.expanduser("~"), ".arknights_gacha_records.json")

_CTX = ssl.create_default_context()


class GachaError(Exception):
    """接口异常 / 鉴权失败 / 数据不合法。"""

    def __init__(self, code, message, url=""):
        self.code = code
        self.message = message
        self.url = url
        self.reason = str(code)
        super().__init__(f"[{code}] {message}" + (f" ({url})" if url else ""))


# ---------------------------------------------------------------- 底层 HTTP

def _request(method, url, *, headers=None, body: bytes | None = None, timeout=20):
    """返回 (文本响应, Set-Cookie 列表)。HTTP 层错误抛 GachaError。"""
    h = {"User-Agent": UA, "Accept-Encoding": "gzip", "Connection": "close"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            cookies = resp.headers.get_all("Set-Cookie") or []
        return raw.decode("utf-8", "replace"), cookies
    except urllib.error.HTTPError as e:  # 4xx/5xx 也可能带 JSON 体
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise GachaError(e.code, f"HTTP {e.code} {detail}", url) from e
    except urllib.error.URLError as e:
        raise GachaError(-1, f"网络错误: {e.reason}", url) from e


def _envelope(text, url):
    """拆 {code|status, msg, data} 外壳，返回 data；鉴权失败会转成可读错误。

    注意：鉴权失败时响应**没有 code 字段**，只有 {"reason": "...", "message": "..."}，
    不单独判就会静默当成 code=0「成功」。
    """
    stripped = text.lstrip()
    if stripped.startswith("<"):
        raise GachaError(-2, "接口返回的是网页而不是 JSON（端点可能已废弃 / 落到 SPA 路由）", url)
    try:
        data = json.loads(text)
    except ValueError as e:
        raise GachaError(-2, f"返回不是合法 JSON: {text[:200]}", url) from e

    reason = data.get("reason")
    if reason:
        raise GachaError(reason, data.get("message") or data.get("msg") or "(无说明)", url)
    code = data.get("code", data.get("status", 0)) or 0
    if code != 0:
        raise GachaError(code, data.get("msg") or data.get("message") or "", url)
    return data.get("data")


def _post_json(url, payload, *, headers=None, timeout=20):
    h = dict(headers or {})
    h["Content-Type"] = "application/json;charset=utf-8"
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _request("POST", url, headers=h, body=body, timeout=timeout)


def _get(url, *, headers=None, timeout=20):
    return _request("GET", url, headers=headers, timeout=timeout)


# ---------------------------------------------------------------- 登录链

def grant_user_center(account_token: str) -> str:
    """第 2 步：账号 token → 用户中心 OAuth token。

    appCode/type 用错（比如借森空岛那套）会返回一次性 `code` 而不是 `token`，这里直接点破。
    """
    url = f"{AS_BASE}/user/oauth2/v2/grant"
    text, _ = _post_json(url, {"token": account_token,
                               "appCode": APP_CODE_USER_CENTER,
                               "type": GRANT_TYPE_TOKEN})
    data = _envelope(text, url) or {}
    token = data.get("token")
    if not token:
        if data.get("code"):
            raise GachaError(-3, "grant 返回的是一次性 code 而不是 token，"
                                 "说明 appCode 用错了（应为本模块的 "
                                 f"{APP_CODE_USER_CENTER!r} + type={GRANT_TYPE_TOKEN}）", url)
        raise GachaError(-3, "grant 未返回 token（appCode 可能已变更）", url)
    return token


def binding_list(oauth_token: str, app_code: str = BINDING_APP_CODE) -> list[dict]:
    """第 3 步：查绑定角色（uid / 渠道 / 昵称）。返回拍平后的 list。"""
    query = urllib.parse.urlencode({"token": oauth_token, "appCode": app_code})
    url = f"{BINDING_BASE}/account/binding/v1/binding_list?{query}"
    text, _ = _get(url)
    data = _envelope(text, url) or {}
    out: list[dict] = []
    for app in data.get("list") or []:
        for b in app.get("bindingList") or []:
            b = dict(b)
            b["appCode"] = app.get("appCode")
            b["appName"] = app.get("appName")
            out.append(b)
    return out


def u8_token_by_uid(oauth_token: str, uid: str) -> str:
    """第 4 步：uid + OAuth token → u8_token（后续走 x-role-token 头）。"""
    url = f"{BINDING_BASE}/account/binding/v1/u8_token_by_uid"
    text, _ = _post_json(url, {"uid": str(uid), "token": oauth_token})
    token = (_envelope(text, url) or {}).get("token")
    if not token:
        raise GachaError(-3, "u8_token_by_uid 未返回 token", url)
    return token


AK_USER_CENTER_COOKIE = "ak-user-center"


def role_login(u8_token: str) -> str:
    """第 5 步：u8_token → ak-user-center cookie 值（抽卡接口没它只回 MissingCookie）。"""
    url = f"{AK_BASE}/user/api/role/login"
    text, cookies = _post_json(url, {"token": u8_token, "source_from": "",
                                     "share_type": "", "share_by": ""})
    _envelope(text, url)
    for c in cookies:
        head = c.split(";", 1)[0]
        if head.startswith(AK_USER_CENTER_COOKIE + "="):
            return head.split("=", 1)[1]
    raise GachaError(-3, f"role/login 成功但未下发 {AK_USER_CENTER_COOKIE} cookie", url)


def derive_credentials(account_token: str, uid: str | None = None,
                       nickname: str | None = None) -> dict:
    """走完 2~5 步，返回可长期复用的抽卡凭证 dict。

    uid 缺省时取账号下第一个明日方舟角色；nickname 用于在多个角色里挑。
    """
    if not account_token:
        raise GachaError(-4, "缺少账号 token（先登录）")

    oauth = grant_user_center(account_token)
    bindings = binding_list(oauth)
    if not bindings:
        raise GachaError(-5, "该鹰角账号下没有明日方舟角色"
                             "（B 服账号通常无法用鹰角通行证登录，国际服没有此接口）")

    picked = None
    if uid:
        picked = next((b for b in bindings if str(b.get("uid")) == str(uid)), None)
        if picked is None:
            raise GachaError(-5, f"该账号下找不到 uid={uid} 的角色（可用：{_describe(bindings)}）")
    elif nickname:
        picked = next((b for b in bindings if b.get("nickName") == nickname), None)
        if picked is None:
            raise GachaError(-5, f"该账号下找不到昵称 {nickname!r} 的角色（可用：{_describe(bindings)}）")
    else:
        picked = bindings[0]

    uid = str(picked.get("uid"))
    u8 = u8_token_by_uid(oauth, uid)
    cookie = role_login(u8)
    return {
        "account_token": account_token,
        "oauth_token": oauth,
        "u8_token": u8,
        "cookie": cookie,
        "uid": uid,
        "nickName": picked.get("nickName"),
        "channelName": picked.get("channelName"),
        "isOfficial": picked.get("isOfficial"),
        "saved_at": int(time.time()),
        "bindings": [{"uid": str(b.get("uid")), "nickName": b.get("nickName"),
                      "channelName": b.get("channelName")} for b in bindings],
    }


def _describe(bindings: list[dict]) -> str:
    return "、".join(f"{b.get('nickName') or '?'}({b.get('uid')}/{b.get('channelName') or '?'})"
                     for b in bindings)


# ---------------------------------------------------------------- 抽卡数据

def _gacha_headers(cred: dict) -> dict:
    h = {"Referer": GACHA_REFERER, "x-role-token": cred.get("u8_token", "")}
    if cred.get("account_token"):
        h["x-account-token"] = cred["account_token"]
    if cred.get("cookie"):
        h["Cookie"] = f"{AK_USER_CENTER_COOKIE}={cred['cookie']}"
    return h


def categories(uid: str, cred: dict) -> list[dict]:
    """卡池分类（限定寻访 / 标准寻访 / 中坚寻访 …）。"""
    url = f"{AK_BASE}/user/api/inquiry/gacha/cate?" + urllib.parse.urlencode({"uid": str(uid)})
    text, _ = _get(url, headers=_gacha_headers(cred))
    data = _envelope(text, url)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("list"), list):
        return data["list"]
    raise GachaError(-6, f"卡池分类既不是数组也不是 {{list:[…]}}: {str(data)[:200]}", url)


def history(uid: str, category: str, cred: dict, *, size: int = 50,
            pos: int | None = None, gacha_ts: str | None = None) -> dict:
    """某一卡池分类的一页记录 → {list:[…], hasMore:bool}。

    首页不带 pos/gachaTs；后续页用上一页最后一条的 pos + gachaTs。
    """
    params = {"uid": str(uid), "category": category, "size": int(size)}
    if gacha_ts:
        params["pos"] = int(pos or 0)
        params["gachaTs"] = str(gacha_ts)
    url = f"{AK_BASE}/user/api/inquiry/gacha/history?" + urllib.parse.urlencode(params)
    text, _ = _get(url, headers=_gacha_headers(cred))
    data = _envelope(text, url) or {}
    return {"list": data.get("list") or [], "hasMore": bool(data.get("hasMore"))}


def normalize(item: dict, category: str = "") -> dict | None:
    """把接口的一条记录统一成内部形态；时间戳不可解析时返回 None（调用方跳过）。"""
    ts = item.get("gachaTs")
    try:
        ts = int(str(ts).strip())
    except (TypeError, ValueError):
        return None
    rarity = item.get("rarity")
    stars = rarity + 1 if isinstance(rarity, int) else None   # 接口 0 基，5 = 6★
    try:
        pos = int(item.get("pos") or 0)
    except (TypeError, ValueError):
        pos = 0
    return {
        "poolId": item.get("poolId") or "",
        "poolName": item.get("poolName") or category or "未知卡池",
        "charId": item.get("charId") or "",
        "charName": item.get("charName") or item.get("charId") or "",
        "stars": stars,
        "isNew": bool(item.get("isNew")),
        "ts": ts,                 # 毫秒
        "pos": pos,
        "category": category,
    }


def record_key(r: dict) -> tuple:
    """去重键：poolId+charId+ts+pos（pos 不能省——十连里的重复干员只差它）。"""
    return (r.get("poolId"), r.get("charId"), r.get("ts"), r.get("pos"))


def fetch_all(uid: str, cred: dict, *, size: int = 50, delay_ms: int = 600,
              max_pages: int = 200, progress=None) -> dict:
    """拉全部卡池分类的记录。

    单个分类失败不中断其余（收集进 errors），与 arklog 的 PartialError 语义一致。
    返回 {"categories", "records", "per_category", "errors"}。
    """
    cates = categories(uid, cred)
    all_recs: list[dict] = []
    per: dict[str, int] = {}
    errors: list[str] = []
    for cate in cates:
        cid = cate.get("id") or ""
        name = cate.get("name") or cid
        try:
            recs = _paginate(uid, cid, cred, size, delay_ms, max_pages, progress, name)
        except GachaError as e:
            errors.append(f"卡池「{name}」拉取失败：{e}")
            continue
        per[name] = len(recs)
        all_recs.extend(recs)
    return {"categories": cates, "records": all_recs, "per_category": per, "errors": errors}


def fetch_category(uid: str, category: str, cred: dict, *, size: int = 50,
                   delay_ms: int = 600, max_pages: int = 200, progress=None) -> list[dict]:
    """只拉某一个卡池分类（CLI / 按需刷新用）。"""
    return _paginate(uid, category, cred, size, delay_ms, max_pages, progress, category)


def _paginate(uid: str, category: str, cred: dict, size: int, delay_ms: int,
              max_pages: int, progress, label: str) -> list[dict]:
    out: list[dict] = []
    seen: set = set()
    pos: int | None = None
    ts: str | None = None
    for page in range(max_pages):
        if page and delay_ms:
            time.sleep(delay_ms / 1000.0)     # 页间隔速，别把账号送进风控
        data = history(uid, category, cred, size=size, pos=pos, gacha_ts=ts)
        items = data["list"]
        if not items:
            break
        for it in items:
            rec = normalize(it, category)
            if rec is None:
                continue
            key = record_key(rec)
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
        if progress:
            progress(label, len(out))
        if not data["hasMore"]:
            break
        last = items[-1]
        nts = str(last.get("gachaTs") or "")
        try:
            npos = int(last.get("pos") or 0)
        except (TypeError, ValueError):
            npos = 0
        if not nts or (nts == ts and npos == pos):
            break                              # 游标没推进，再翻还是同一页
        pos, ts = npos, nts
    return out


# ---------------------------------------------------------------- 本地留档

def load_archive() -> dict:
    if os.path.exists(ARCHIVE_PATH):
        try:
            with open(ARCHIVE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    return {}


def save_archive(arch: dict) -> None:
    tmp = ARCHIVE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(arch, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ARCHIVE_PATH)


def merge_archive(uid: str, records: list[dict], *, categories: list | None = None) -> dict:
    """增量并档（只增不删）：接口不再返回的旧记录会留在本地。返回 {records, added}。"""
    arch = load_archive()
    slot = arch.setdefault(str(uid), {})
    have = {record_key(r) for r in slot.get("records") or []}
    added = 0
    merged = list(slot.get("records") or [])
    for r in records:
        if record_key(r) in have:
            continue
        have.add(record_key(r))
        merged.append(r)
        added += 1
    merged.sort(key=lambda r: (r.get("ts", 0), r.get("pos", 0)))
    slot["records"] = merged
    slot["updated_at"] = int(time.time())
    if categories:
        slot["categories"] = categories
    save_archive(arch)
    return {"records": merged, "added": added}


# ---------------------------------------------------------------- 统计

def classify(category_id: str) -> str:
    """按接口 category 判定结转链（保底只在自己这条链里累加）。

    含 classic → 中坚；含 normal → 标准；其余（含认不出的）→ 限定。
    认不出归「限定」是刻意的保守方向：宁可少算结转，不可无中生有。
    """
    c = (category_id or "").lower()
    if "classic" in c:
        return "中坚"
    if "normal" in c:
        return "标准"
    return "限定"


def summarize(records: list[dict]) -> dict:
    """总抽数 / 星级分布 / 出金水位（按 限定·标准·中坚 三条链）/ 最早最晚时间。"""
    recs = sorted(records, key=lambda r: (r.get("ts", 0), r.get("pos", 0)))
    by_stars: dict[int, int] = {}
    six: list[dict] = []
    counters = {"限定": 0, "标准": 0, "中坚": 0}
    for r in recs:
        s = r.get("stars") or 0
        by_stars[s] = by_stars.get(s, 0) + 1
        chain = classify(r.get("category") or r.get("poolId") or "")
        counters[chain] += 1
        if s == 6:
            six.append({**r, "pity": counters[chain], "chain": chain})
            counters[chain] = 0
    six.reverse()   # 最近的在前
    total = len(recs)
    avg6 = (total / len(six)) if six else None
    return {
        "total": total,
        "by_stars": by_stars,
        "six": six,
        "six_count": len(six),
        "avg_pulls_per_six": avg6,
        "pending": dict(counters),          # 各链「垫了多少抽还没出金」
        "new_count": sum(1 for r in recs if r.get("isNew")),
        "earliest_ts": recs[0]["ts"] if recs else None,
        "latest_ts": recs[-1]["ts"] if recs else None,
    }


# ---------------------------------------------------------------- 离线自测

def self_test() -> int:
    """不联网、不用账号的解析/统计自测（合成数据）。"""
    fails = 0

    def ok(cond, msg):
        nonlocal fails
        if not cond:
            fails += 1
            print("  [FAIL]", msg)
        else:
            print("  [ok]  ", msg)

    print("normalize：")
    r = normalize({"poolId": "normal_1", "poolName": "标准寻访", "charId": "char_002_amiya",
                   "charName": "阿米娅", "rarity": 5, "isNew": True,
                   "gachaTs": "1770697079082", "pos": 3}, "normal_1")
    ok(r and r["stars"] == 6, "rarity 0 基 → 6★")
    ok(r and r["ts"] == 1770697079082, "毫秒字符串时间戳")
    ok(normalize({"gachaTs": "abc"}) is None, "坏时间戳返回 None")

    print("去重键：")
    a = dict(r)
    b = dict(r, pos=4)
    ok(record_key(a) != record_key(b), "十连里同名同星只差 pos 也能区分")
    ok(record_key(a) == record_key(dict(r)), "同一条记录键一致")

    print("classify：")
    ok(classify("normal") == "标准", "normal → 标准")
    ok(classify("classic_1") == "中坚", "classic → 中坚")
    ok(classify("MH_02") == "限定", "认不出 → 限定")
    ok(classify("limit_spring") == "限定", "限定池")

    print("summarize：")
    fake = []
    ts = 1_700_000_000_000
    for i in range(10):
        fake.append(normalize({"poolId": "normal_2", "poolName": "标准", "charId": f"c{i}",
                               "charName": f"干员{i}", "rarity": 2 if i < 9 else 5,
                               "isNew": False, "gachaTs": str(ts + i * 1000), "pos": i}, "normal"))
    s = summarize(fake)
    ok(s["total"] == 10, "总抽数 10")
    ok(s["by_stars"].get(6) == 1, "1 个 6★")
    ok(s["six"][0]["pity"] == 10, "出金水位 10 抽")
    ok(s["avg_pulls_per_six"] == 10, "平均 10 抽/金")
    ok(s["pending"]["标准"] == 0, "出金后该链归零")

    print(f"\n{'全部通过' if fails == 0 else f'{fails} 项未通过'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(self_test())
