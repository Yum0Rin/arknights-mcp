#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从**本机 Firefox 的登录态**里取「明日方舟用户中心」API 凭据（免密码 / 免验证码）。

> 仅在**你自己的机器**上读**你自己**的浏览器数据；不联网、不上传、不修改 Firefox。

## 为什么要这么绕

寻访记录接口（`ak.hypergryph.com/user/api/inquiry/gacha/*`）**两个凭据缺一不可**
（2026-10-12 实测，三种组合都试过）：

    cookie + 真 role_token  → ✅ 通过
    cookie + 假/空 token    → ❌ 401 {"reason":"DETECTED_ROLE_CHANGED"}（服务端会交叉校验）
    无 cookie               → ❌ 401 {"reason":"UN_LOGIN"}

而这两个凭据**都不在 cookies.sqlite 里**：

| 凭据 | 在哪 |
|---|---|
| `ak-user-center`（cookie） | **会话 cookie** → 只存在 `sessionstore*.jsonlz4`（Firefox 靠它做会话恢复） |
| `x-role-token`（role token） | 官网 SPA 存在 `ak.hypergryph.com` 的 **localStorage** (`ONE_ACCOUNT_ROLE_META.token`) |
| 角色 `uid` | 同一个 localStorage 的 `APP_CURRENT_ROLE:arknights` → `"218193258::"` |

## 与 `gacha_client.derive_credentials()` 的关系

两条路都能拿到同一形态的凭据，二选一：

- `gacha_client.derive_credentials(account_token)` —— 正规 6 步登录链，需要手机号+密码/验证码；
- `ff_session.read_ak_login()`（本模块）—— 直接抄浏览器当前会话，**不碰密码**，但只在
  "Firefox 里 ak.hypergryph.com 处于登录态"时有效（cookie 是会话级的，浏览器关了会话恢复失败就没了）。

## 格式

`*.jsonlz4` = `b"mozLz40\\0"` + 4 字节小端原始长度 + 标准 **LZ4 block**。
本模块自带纯 Python LZ4 解码，不依赖 `lz4` 包。

## 用法

    import ff_session
    cred = ff_session.read_ak_login()     # -> {uid, u8_token, cookie, ...}
    # 然后交给 gacha_client.categories / fetch_all
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile

AK_HOST = "ak.hypergryph.com"
AK_ORIGIN = f"https://{AK_HOST}"
COOKIE_NAME = "ak-user-center"
LS_ROLE_KEY = "ONE_ACCOUNT_ROLE_META"
LS_UID_KEY = "APP_CURRENT_ROLE:arknights"

PROFILES_DIR = os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles")


class FirefoxSessionError(Exception):
    """读不到可用的 Firefox 登录态。"""


# ---------------------------------------------------------------- mozLz4

def lz4_block_decompress(src: bytes) -> bytes:
    """解标准 LZ4 block（纯 Python；只依赖标准库）。"""
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]
        i += lit
        if i >= n:
            break
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        mlen = token & 0x0F
        if mlen == 15:
            while True:
                b = src[i]
                i += 1
                mlen += b
                if b != 255:
                    break
        mlen += 4
        start = len(dst) - offset
        if start < 0:
            raise FirefoxSessionError("LZ4 数据损坏（offset 越界）")
        for k in range(mlen):
            dst.append(dst[start + k])
    return bytes(dst)


def load_mozlz4(path: str):
    """读 Firefox 的 .jsonlz4（会话恢复文件）。"""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:8] != b"mozLz40\0":
        raise FirefoxSessionError(f"不是 mozLz4 文件：{path}")
    return json.loads(lz4_block_decompress(raw[12:]).decode("utf-8", "replace"))


# ---------------------------------------------------------------- 定位文件

def _copy_to_temp(src: str) -> str:
    """Firefox 可能占着这些文件，先拷一份再读（含 -wal/-shm）。"""
    fd, tmp = tempfile.mkstemp(prefix="ffsess_", suffix=os.path.basename(src))
    os.close(fd)
    shutil.copy2(src, tmp)
    for suffix in ("-wal", "-shm"):
        if os.path.exists(src + suffix):
            shutil.copy2(src + suffix, tmp + suffix)
    return tmp


def _newest(paths: list[str]) -> str | None:
    alive = [p for p in paths if os.path.exists(p)]
    if not alive:
        return None
    return max(alive, key=lambda p: os.path.getmtime(p))


def session_files(profile: str) -> list[str]:
    """按"最新优先"候选会话文件：运行时 recovery 最新，关掉后 sessionstore 最新。"""
    return [
        os.path.join(profile, "sessionstore-backups", "recovery.jsonlz4"),
        os.path.join(profile, "sessionstore.jsonlz4"),
        os.path.join(profile, "sessionstore-backups", "previous.jsonlz4"),
    ]


def list_profiles() -> list[str]:
    if not os.path.isdir(PROFILES_DIR):
        return []
    return [os.path.join(PROFILES_DIR, d) for d in os.listdir(PROFILES_DIR)
            if os.path.isdir(os.path.join(PROFILES_DIR, d))]


def read_session_cookie(profile: str, host: str = AK_HOST,
                        name: str = COOKIE_NAME) -> str | None:
    """从会话恢复文件里取会话 cookie 的值（就是 cookies.sqlite 里没有的那种）。"""
    src = _newest(session_files(profile))
    if not src:
        return None
    tmp = _copy_to_temp(src)
    try:
        data = load_mozlz4(tmp)
    finally:
        for p in (tmp, tmp + "-wal", tmp + "-shm"):
            try:
                os.remove(p)
            except OSError:
                pass
    for c in data.get("cookies") or []:
        if c.get("host") == host and c.get("name") == name:
            return c.get("value") or None
    return None


def read_local_storage(profile: str, origin: str = AK_ORIGIN) -> dict:
    """读某个 origin 的 localStorage。origin 形如 https://ak.hypergryph.com。"""
    safe = origin.replace(":", "+").replace("/", "+")
    db = os.path.join(profile, "storage", "default", safe, "ls", "data.sqlite")
    if not os.path.exists(db):
        return {}
    tmp = _copy_to_temp(db)
    try:
        con = sqlite3.connect(tmp)
        out = {}
        for k, v in con.execute("select key, value from data"):
            if isinstance(k, (bytes, bytearray)):
                k = k.decode("utf-8", "replace")
            if isinstance(v, (bytes, bytearray)):
                v = v.decode("utf-8", "replace")
            out[k] = v
        con.close()
        return out
    finally:
        for p in (tmp, tmp + "-wal", tmp + "-shm"):
            try:
                os.remove(p)
            except OSError:
                pass


# ---------------------------------------------------------------- 主入口

def read_ak_login(profile: str | None = None) -> dict:
    """取一份可直接用于 gacha_client 的凭据。

    只传 profile 时就用它；不传则遍历所有配置，返回第一个装齐了凭据的。
    失败抛 FirefoxSessionError，消息里说明缺哪一环。
    """
    profiles = [profile] if profile else list_profiles()
    if not profiles:
        raise FirefoxSessionError(f"没找到 Firefox 配置目录：{PROFILES_DIR}")

    problems = []
    best = None
    for prof in profiles:
        ls = read_local_storage(prof)
        meta_raw = ls.get(LS_ROLE_KEY)
        if not meta_raw:
            continue
        try:
            token = (json.loads(meta_raw) or {}).get("token") or ""
        except ValueError:
            problems.append(f"{os.path.basename(prof)}：{LS_ROLE_KEY} 不是合法 JSON")
            continue
        uid = (ls.get(LS_UID_KEY) or "").split("::")[0]
        if not (token and uid):
            problems.append(f"{os.path.basename(prof)}：localStorage 里缺 token 或 uid")
            continue
        cookie = read_session_cookie(prof)
        if not cookie:
            problems.append(f"{os.path.basename(prof)}：没有 {COOKIE_NAME} 会话 cookie"
                            f"（Firefox 里可能没登录 / 会话没恢复）")
            continue
        cand = {
            "uid": uid,
            "u8_token": token,
            "cookie": cookie,
            "account_token": "",          # 走这条路拿不到，也不需要
            "profile": os.path.basename(prof),
            "source": "firefox-session",
        }
        if profile:
            return cand
        best = best or cand
    if best:
        return best
    detail = ("；".join(problems) if problems
              else "所有 Firefox 配置里都没有 ak.hypergryph.com 的 localStorage")
    raise FirefoxSessionError(
        "读不到 Firefox 的登录态：" + detail +
        "。请在该浏览器里登录 https://ak.hypergryph.com/user/headhunting 后重试（cookie 是会话级的，"
        "Firefox 关闭且未恢复会话就会失效）。")


def self_test() -> int:
    """不联网的本机自测：报告各 Firefox 配置里能否装齐凭据。"""
    print(f"Firefox 配置目录：{PROFILES_DIR}")
    profs = list_profiles()
    if not profs:
        print("  (没找到配置目录)")
        return 1
    ok = 0
    for prof in profs:
        name = os.path.basename(prof)
        ls = read_local_storage(prof)
        uid = (ls.get(LS_UID_KEY) or "").split("::")[0]
        try:
            token = (json.loads(ls.get(LS_ROLE_KEY) or "{}") or {}).get("token") or ""
        except ValueError:
            token = ""
        cookie = read_session_cookie(prof)
        mark = "✅" if (uid and token and cookie) else "—"
        print(f"  {mark} {name:34s} uid={uid or '-':12s} "
              f"role_token={'有' if token else '无'}(len={len(token)}) "
              f"cookie={'有' if cookie else '无'}(len={len(cookie or '')})")
        if uid and token and cookie:
            ok += 1
    print(f"\n可用配置：{ok} 个")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(self_test())
