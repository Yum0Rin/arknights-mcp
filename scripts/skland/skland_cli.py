"""森空岛数据查询 命令行探针（配合 skland_client.py）。

用法：
    python skland_cli.py login              # 交互式：选 密码 / 验证码
    python skland_cli.py login --code       # 验证码登录
    python skland_cli.py login --password   # 密码登录
    python skland_cli.py status             # 校验凭证 + 列出绑定角色
    python skland_cli.py dump [--uid X] [--out DIR]   # 拉全量数据存 JSON
    python skland_cli.py checkin [--uid X]  # 森空岛签到

凭证存 ~/.arknights_skland.json（含 cred，等同账号访问权，别外传）。
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time

import skland_client as sk

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _line(msg=""):
    print(msg)


def _do_login(args):
    cred = sk.load_config().get("cred")
    if cred and not args.force:
        _line(f"本地已有凭证（{sk.CONFIG_PATH}），如需重新登录加 --force。")
        return 0

    if args.code or (not args.password and _ask("登录方式：[1]验证码  [2]密码 （默认1）") in ("", "1")):
        phone = _ask("手机号")
        sk.send_phone_code(phone)
        _line("验证码已发送，请查收短信。")
        code = _ask("验证码")
        token = sk.token_by_phone_code(phone, code)
    else:
        phone = _ask("手机号")
        password = getpass.getpass("密码（不回显）: ")
        token = sk.token_by_phone_password(phone, password)

    info = sk.account_basic(token)
    _line(f"登录成功：{info.get('phone') or info.get('email') or '?'}  "
          f"未成年={info.get('isMinor')}")

    cred, sign_token = sk.cred_from_token(token)
    cfg = sk.save_config(cred, token=sign_token)
    _line(f"已保存凭证 -> {sk.CONFIG_PATH}")

    chars = sk.binding(cred, sign_token)
    if not chars:
        _line("该账号没有绑定任何明日方舟角色。")
        return 0
    _line("绑定角色：")
    for c in chars:
        _line(f"  uid={c.get('uid')}  {c.get('channelName')}  {c.get('nickName')}")
    if len(chars) == 1:
        sk.save_config(cred, token=sign_token, uid=chars[0].get("uid"))
    return 0


def _ask(prompt):
    try:
        return input(prompt + ": ").strip()
    except EOFError:
        return ""


def _load_uid(args):
    cfg = sk.load_config()
    cred = cfg.get("cred")
    token = cfg.get("token")
    if not cred:
        _line("没有本地凭证，先跑 `python skland_cli.py login`。")
        return None, None, None
    uid = getattr(args, "uid", None) or cfg.get("uid")
    if not uid:
        chars = sk.binding(cred, token)
        if not chars:
            _line("没有绑定角色。")
            return None, None, None
        uid = chars[0]["uid"]
    return cred, token, uid


def _do_status(args):
    cred, token, uid = _load_uid(args)
    if not cred:
        return 1
    try:
        new_token = sk.refresh_token(cred)
        sk.save_config(cred, token=new_token)
        _line(f"凭证有效，sign_token 已续期（uid={uid}）。")
    except sk.SklandError as e:
        _line(f"凭证可能失效：{e}")
    for c in sk.binding(cred, sk.load_config().get("token")):
        _line(f"  uid={c.get('uid')}  {c.get('channelName')}  {c.get('nickName')}  Lv?")
    return 0


def _do_dump(args):
    cred, token, uid = _load_uid(args)
    if not cred:
        return 1
    out_dir = args.out or os.path.join(
        os.environ.get("TEMP", os.path.expanduser("~")), "opencode", "skland-dump"
    )
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    jobs = {
        "binding": lambda: sk.binding(cred, token),
        "player_info": lambda: sk.player_info(cred, uid, token),
        "cultivate": lambda: sk.cultivate(cred, uid, token),
        "attendance": lambda: sk.attendance_status(cred, uid, token),
    }
    for name, fn in jobs.items():
        try:
            data = fn()
        except sk.SklandError as e:
            _line(f"[FAIL] {name}: {e}")
            continue
        path = os.path.join(out_dir, f"{stamp}-{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _line(f"[OK] {name}: {path}")
    _line(f"\n输出目录：{out_dir}")
    return 0


def _do_checkin(args):
    cred, token, uid = _load_uid(args)
    if not cred:
        return 1
    awards = sk.do_checkin(cred, uid, token)
    if not awards:
        _line("今日已签到，或没有奖励。")
    for a in awards:
        r = a.get("resource", {})
        _line(f"  {r.get('name')} x{a.get('count')}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="森空岛数据查询 CLI（自用）")
    sub = p.add_subparsers(dest="cmd", required=True)

    lg = sub.add_parser("login", help="登录并保存凭证")
    lg.add_argument("--code", action="store_true", help="用短信验证码登录")
    lg.add_argument("--password", action="store_true", help="用密码登录")
    lg.add_argument("--force", action="store_true", help="已有凭证也重新登录")
    lg.set_defaults(func=_do_login)

    st = sub.add_parser("status", help="校验凭证并列出角色")
    st.add_argument("--uid")
    st.set_defaults(func=_do_status)

    dp = sub.add_parser("dump", help="拉全量数据存 JSON")
    dp.add_argument("--uid")
    dp.add_argument("--out")
    dp.set_defaults(func=_do_dump)

    ck = sub.add_parser("checkin", help="森空岛签到")
    ck.add_argument("--uid")
    ck.set_defaults(func=_do_checkin)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except sk.SklandError as e:
        _line(f"错误：{e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
