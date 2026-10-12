#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可续传下载明日方舟官方 gamedata（ArknightsGameData），并校验 JSON 完整。

痛点：`raw.githubusercontent.com` 直连**动不动就超时截断**（实测 15MB 的表下到 9.5MB 就断）。
对策：HTTP Range **断点续传** + 多镜像轮换 + 多轮重试 + 下完 **JSON 校验**。

用法：
  python scheduling/tools/fetch_gamedata.py                    # 默认下表（character/item/uniequip）
  python scheduling/tools/fetch_gamedata.py --only character_table.json
  python scheduling/tools/fetch_gamedata.py --check            # 只校验现有文件
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "scheduling" / "data" / "gamedata"

# 三个镜像（raw 直连最稳但易断；jsdelivr 快但偶 reset；yuanyan 备用）
MIRRORS = [
    "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/",
    "https://cdn.jsdelivr.net/gh/Kengxxiao/ArknightsGameData@master/zh_CN/gamedata/excel/",
    "https://raw.githubusercontent.com/yuanyan3060/ArknightsGameResource/main/gamedata/excel/",
]
FILES = ["character_table.json", "item_table.json", "uniequip_table.json", "gamedata_const.json"]
UA = {"User-Agent": "Mozilla/5.0 arknights-mcp/fetch_gamedata"}


def download_one(name: str, tries: int = 12) -> bool:
    dst = OUT / name
    OUT.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, tries + 1):
        url = MIRRORS[(attempt - 1) % len(MIRRORS)] + name
        pos = dst.stat().st_size if dst.exists() else 0
        headers = dict(UA)
        if pos:
            headers["Range"] = "bytes=%d-" % pos
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                if pos and r.status != 206:      # 服务器不理 Range → 从头下
                    pos = 0
                    dst.write_bytes(b"")
                with open(dst, "ab") as f:
                    while True:
                        chunk = r.read(1024 * 256)
                        if not chunk:
                            break
                        f.write(chunk)
        except Exception as e:  # noqa: BLE001
            print("  [%d/%d] %s @%.1fMB 断: %s" % (attempt, tries, name,
                                                   dst.stat().st_size / 1e6, type(e).__name__))
            time.sleep(2)
            continue
        # 下完一轮 → 校验
        size = dst.stat().st_size
        try:
            json.loads(dst.read_text(encoding="utf-8"))
            print("  OK %s  %.2f MB" % (name, size / 1e6))
            return True
        except Exception as e:  # noqa: BLE001
            print("  [%d/%d] %s 不完整(%.2fMB)：%s" % (attempt, tries, name, size / 1e6,
                                                       str(e)[:60]))
            time.sleep(1)
    print("  FAIL %s（%d 轮仍不完整）" % (name, tries))
    return False


def main():
    ap = argparse.ArgumentParser(description="可续传下载官方 gamedata")
    ap.add_argument("--only", default="", help="只下一个文件")
    ap.add_argument("--check", action="store_true", help="只校验现有文件")
    args = ap.parse_args()

    files = [args.only] if args.only else FILES
    ok = True
    for name in files:
        p = OUT / name
        if args.check:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                print("  OK %s  条目 %s" % (name, len(d) if hasattr(d, "__len__") else "-"))
            except Exception as e:  # noqa: BLE001
                print("  BAD %s: %s" % (name, str(e)[:80]))
                ok = False
            continue
        ok = download_one(name) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
