"""森空岛数据查询 命令行探针（配合 skland_client.py）。

用法：
    python skland_cli.py login              # 交互式：选 密码 / 验证码
    python skland_cli.py login --code       # 验证码登录
    python skland_cli.py login --password   # 密码登录
    python skland_cli.py status             # 校验凭证 + 列出绑定角色
    python skland_cli.py dump [--uid X] [--out DIR]   # 拉全量数据存 JSON
    python skland_cli.py checkin [--uid X]  # 森空岛签到
    python skland_cli.py gacha [--uid X] [--category ID] [--size N] [--refresh] [--from-firefox] [--out F]

    # 抽卡记录走的是「鹰角官网用户中心」而不是森空岛（详见 gacha_client.py）。
    # 凭据两条路：login 时顺带派生；或 --from-firefox 抄本机 Firefox 已登录的会话（免密码）。

凭证存 ~/.arknights_skland.json（含 cred，等同账号访问权，别外传）；
抽卡记录本地留档在 ~/.arknights_gacha_records.json（只增不删）。
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time

import ff_session as ffs
import gacha_client as gc
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

    # 顺带派生「抽卡记录」凭证（用户中心接口，与森空岛不是同一套，见 gacha_client.py）
    try:
        g = gc.derive_credentials(token, uid=chars[0].get("uid"))
        sk.save_config(extra={"gacha": g})
        _line(f"抽卡记录凭证已就绪（uid={g['uid']}  {g.get('channelName') or '?'}）")
    except gc.GachaError as e:
        _line(f"抽卡记录凭证获取失败（不影响看板数据）：{e}")
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


def _gacha_cred(cfg, uid, refresh):
    """取（必要时重新派生）抽卡凭证。"""
    g = dict(cfg.get("gacha") or {})
    if not g.get("account_token"):
        _line("没有抽卡凭证。先跑 `python skland_cli.py login` —— 登录时会顺带生成。")
        return None
    need = refresh or not (g.get("u8_token") and g.get("cookie"))
    if uid and str(uid) != str(g.get("uid")):
        need = True
    if need:
        try:
            g = gc.derive_credentials(g.get("account_token"), uid=uid)
        except gc.GachaError as e:
            _line(f"派生抽卡凭证失败：{e}")
            return None
        sk.save_config(extra={"gacha": g})
        _line(f"抽卡凭证已更新（uid={g['uid']}  {g.get('channelName') or '?'}）")
    return g


def _print_gacha_stats(stats):
    _line(f"总抽数：{stats['total']}　新获得：{stats['new_count']}")
    dist = "  ".join(f"{k}★×{stats['by_stars'][k]}" for k in sorted(stats["by_stars"], reverse=True))
    _line(f"星级分布：{dist}")
    pend = "  ".join(f"{k}垫{v}抽" for k, v in (stats.get("pending") or {}).items())
    _line(f"当前水位：{pend}")
    if stats.get("six"):
        if stats.get("avg_pulls_per_six"):
            _line(f"平均出金：{stats['avg_pulls_per_six']:.1f} 抽/6★")
        _line("最近的 6★：")
        for s in stats["six"][:15]:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["ts"] / 1000))
            new = "NEW " if s.get("isNew") else ""
            _line(f"  {ts}  {s['charName']}（{s['chain']}·{s['poolName']}）"
                  f"  第 {s['pity']} 抽  {new}")
    if stats.get("earliest_ts"):
        lo = time.strftime("%Y-%m-%d %H:%M", time.localtime(stats["earliest_ts"] / 1000))
        hi = time.strftime("%Y-%m-%d %H:%M", time.localtime(stats["latest_ts"] / 1000))
        _line(f"记录区间：{lo}  →  {hi}")


def _do_gacha(args):
    cfg = sk.load_config()
    if getattr(args, "from_firefox", False):
        # 免密码：直接抄本机 Firefox 里已登录的官网会话（见 ff_session.py）
        try:
            cred = ffs.read_ak_login()
        except ffs.FirefoxSessionError as e:
            _line(f"从火狐读登录态失败：{e}")
            return 2
        sk.save_config(extra={"gacha": cred})
        _line(f"已从 Firefox（{cred['profile']}）导入登录态：uid={cred['uid']}")
    else:
        uid = getattr(args, "uid", None) or (cfg.get("gacha") or {}).get("uid")
        cred = _gacha_cred(cfg, uid, getattr(args, "refresh", False))
        if not cred:
            return 1
    uid = cred["uid"]

    if args.category:
        _line(f"拉取卡池分类 {args.category} …")
        recs = gc.fetch_category(uid, args.category, cred, size=args.size)
        res = {"categories": [{"id": args.category, "name": args.category}],
               "records": recs, "per_category": {args.category: len(recs)}, "errors": []}
    else:
        _line("拉取全部卡池分类（按 pos+gachaTs 翻页，稍慢）…")
        res = gc.fetch_all(uid, cred, size=args.size)

    for e in res["errors"]:
        _line(f"[WARN] {e}")
    for name, n in res["per_category"].items():
        _line(f"  {name}: {n} 条")

    merged = gc.merge_archive(uid, res["records"], categories=res.get("categories"))
    _line(f"本次拉到 {len(res['records'])} 条，新入库 {merged['added']} 条，"
          f"本地留档共 {len(merged['records'])} 条")
    _line(f"留档文件：{gc.ARCHIVE_PATH}")
    _line("")
    _print_gacha_stats(gc.summarize(merged["records"]))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"uid": uid, "fetched_at": int(time.time()),
                       "categories": res["categories"], "records": merged["records"]},
                      f, ensure_ascii=False, indent=2)
        _line(f"\n已写出：{args.out}")
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

    ga = sub.add_parser("gacha", help="拉明日方舟官方寻访记录（抽卡记录）")
    ga.add_argument("--uid")
    ga.add_argument("--category", help="只拉某个卡池分类 id（默认全部）")
    ga.add_argument("--size", type=int, default=50, help="每页条数，默认 50（接口支持 10/50/100）")
    ga.add_argument("--refresh", action="store_true", help="强制重新派生抽卡凭证")
    ga.add_argument("--from-firefox", action="store_true",
                    help="免密码：从本机 Firefox 已登录的官网会话取凭据（见 ff_session.py）")
    ga.add_argument("--out", help="另存一份原始 JSON 到该路径")
    ga.set_defaults(func=_do_gacha)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except sk.SklandError as e:
        _line(f"错误：{e}")
        return 2
    except gc.GachaError as e:
        _line(f"错误：{e}")
        return 2
    except ffs.FirefoxSessionError as e:
        _line(f"错误：{e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
