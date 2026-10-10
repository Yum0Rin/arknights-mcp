"""森空岛（Skland）只读数据客户端。

登录取凭证（cred），再拉取本人明日方舟账号的游戏内数据。
**仅供本人账号自查**：cred 等同于账号访问权限，只能本地保存、切勿外传。

接口来自社区逆向（参考 ProbiusOfficial/Skland_API 文档 与 nemowang2003/skland-api），
鹰角随时可能改版。核心只依赖标准库（urllib）。

登录两条路（二选一）：
    手机号 + 密码         -> token_by_phone_password()
    手机号 + 短信验证码    -> send_phone_code() / token_by_phone_code()
再走 token -> code -> cred 三级换取；cred 存本地配置文件，后续读数据都用它。

读数据要带 **sign 签名头**：
    sign = md5( hmac_sha256(key=sign_token, msg = path + query/body + timestamp + json(header)) )
    header = {platform, timestamp, dId, vName}
sign_token 是换 cred 时一起返回的；dId 本地生成一次后持久化（服务端不校验其真伪）。

已知：Skland 没有「抽卡记录」接口，本模块也提供不了抽卡数据。
"""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

APP_CODE = "4ca99fa6b56cc2ba"  # 森空岛 APP 固定 appCode
UA = (
    "Mozilla/5.0 (Linux; Android 12; SM-A5560 Build/V417IR; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/101.0.4951.61 Safari/537.36; SKLand/1.52.1"
)

AS_BASE = "https://as.hypergryph.com"      # 鹰角通行证（登录）
SKLAND_BASE = "https://zonai.skland.com"   # 森空岛（游戏数据）

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".arknights_skland.json")

_CTX = ssl.create_default_context()
_DID_CACHE: str | None = None


class SklandError(Exception):
    """接口返回非 0 状态码或网络错误。"""

    def __init__(self, code, message, url=""):
        self.code = code
        self.message = message
        self.url = url
        super().__init__(f"[{code}] {message}" + (f" ({url})" if url else ""))


# ---------------------------------------------------------------- 底层 HTTP

def _http(method, url, *, headers, body: bytes | None = None, timeout=20):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        raise SklandError(e.code, f"HTTP {e.code} {detail}", url) from e
    except urllib.error.URLError as e:
        raise SklandError(-1, f"网络错误: {e.reason}", url) from e

    code = data.get("status", 0) or data.get("code", 0)
    if code != 0:
        raise SklandError(code, data.get("msg") or data.get("message") or "", url)
    return data


def _as_post(path, payload):
    body = json.dumps(payload).encode("utf-8")
    return _http("POST", f"{AS_BASE}{path}",
                 headers={"User-Agent": UA, "Content-Type": "application/json",
                          "Accept-Encoding": "gzip", "Connection": "close"},
                 body=body)


# ---------------------------------------------------------------- 签名

def get_did() -> str:
    """本机 dId：生成一次后持久化（服务端不校验其真伪，只要前后一致）。"""
    global _DID_CACHE
    if _DID_CACHE:
        return _DID_CACHE
    cfg = load_config()
    did = cfg.get("did")
    if not did:
        did = uuid.uuid4().hex
        cfg["did"] = did
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
    _DID_CACHE = did
    return did


def _skland_headers(cred, token, path, payload_str):
    ts = str(int(time.time()))
    header = {"platform": "3", "timestamp": ts, "dId": get_did(), "vName": "1.0.0"}
    if token:
        msg = path + payload_str + ts + json.dumps(header, separators=(",", ":"))
        enc = hmac.new(token.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
        header["sign"] = hashlib.md5(enc.encode("utf-8")).hexdigest()
    headers = {**header, "User-Agent": UA, "Accept-Encoding": "gzip", "Connection": "close",
               "X-Requested-With": "com.hypergryph.skland"}
    if cred:
        headers["cred"] = cred
    return headers


def _skland_request(method, path, cred, token=None, params=None, payload=None):
    query = urllib.parse.urlencode(params) if params else ""
    if payload is None:
        payload_str, body = "", None
    else:
        payload_str = json.dumps(payload, separators=(",", ":"))
        body = payload_str.encode("utf-8")
    url = f"{SKLAND_BASE}{path}" + (f"?{query}" if query else "")
    headers = _skland_headers(cred, token, path, query or payload_str)
    if body is not None:
        headers["Content-Type"] = "application/json"
    return _http(method, url, headers=headers, body=body)


def _skland_get(path, cred, token=None, params=None):
    return _skland_request("GET", path, cred, token, params=params)


def _skland_post(path, cred, token=None, payload=None):
    return _skland_request("POST", path, cred, token, payload=payload)


# ---------------------------------------------------------------- 登录 / 凭证

def token_by_phone_password(phone, password):
    """手机号 + 密码 -> 鹰角通行证 token。"""
    return _as_post("/user/auth/v1/token_by_phone_password",
                    {"phone": phone, "password": password})["data"]["token"]


def send_phone_code(phone):
    """给手机号发送登录验证码（type=2）。"""
    _as_post("/general/v1/send_phone_code", {"phone": phone, "type": 2})


def token_by_phone_code(phone, code):
    """手机号 + 验证码 -> 鹰角通行证 token。"""
    return _as_post("/user/auth/v2/token_by_phone_code",
                    {"phone": phone, "code": code})["data"]["token"]


def account_basic(token):
    """校验 token 并返回账号基本信息（手机号打码、是否未成年等）。"""
    url = f"{AS_BASE}/user/info/v1/basic?token={urllib.parse.quote(token)}"
    return _http("GET", url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})["data"]


def cred_from_token(token):
    """token -> OAuth2 code -> 森空岛 cred。

    返回 (cred, sign_token)：cred 用于所有游戏数据请求；sign_token 是签名密钥。
    """
    grant = _as_post("/user/oauth2/v2/grant",
                     {"token": token, "appCode": APP_CODE, "type": 0})["data"]["code"]
    data = _skland_post("/api/v1/user/auth/generate_cred_by_code", cred=None,
                        payload={"code": grant, "kind": 1})["data"]
    return data["cred"], data.get("token")


def refresh_token(cred, token=None):
    """用已有 cred 换一个新的 sign_token（cred 长期有效时用于续期）。"""
    return _skland_get("/api/v1/auth/refresh", cred, token)["data"]["token"]


# ---------------------------------------------------------------- 游戏数据

def binding(cred, token=None):
    """返回绑定的游戏角色列表（已拍平，含 uid / serverId / channelName / nickName）。"""
    chars = []
    for game in _skland_get("/api/v1/game/player/binding", cred, token)["data"]["list"]:
        for c in game.get("bindingList", []):
            c = dict(c)
            c["appName"] = game.get("appName")
            chars.append(c)
    return chars


def player_info(cred, uid, token=None):
    """玩家全量数据（status / chars / skins / building / recruit / campaign / tower / rogue / routine ...）。"""
    return _skland_get("/api/v1/game/player/info", cred, token, params={"uid": uid})["data"]


def cultivate(cred, uid, token=None):
    """干员养成数据（专精 / 等级 / 精英化等）。"""
    return _skland_get("/api/v1/game/cultivate/player", cred, token,
                       params={"uid": uid})["data"]


def attendance_status(cred, uid, token=None):
    """当月签到状态。"""
    return _skland_get("/api/v1/game/attendance", cred, token, params={"uid": uid})["data"]


def do_checkin(cred, uid, token=None):
    """执行森空岛签到，返回奖励列表。"""
    body = _skland_post("/api/v1/game/attendance", cred, token,
                        payload={"gameId": 1, "uid": uid})
    return body["data"].get("awards", [])


# ---------------------------------------------------------------- 本地凭证存取

def save_config(cred=None, token=None, uid=None, extra=None):
    cfg = load_config()
    if cred:
        cfg["cred"] = cred
    if token:
        cfg["token"] = token
    if uid:
        cfg["uid"] = uid
    if extra:
        cfg.update(extra)
    cfg["saved_at"] = int(time.time())
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)
    return cfg


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    return {}


if __name__ == "__main__":
    print("这是一个库模块，请用 skland_cli.py 操作。")
