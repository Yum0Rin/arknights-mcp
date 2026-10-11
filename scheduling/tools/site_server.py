#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地站点后端：服务「明日方舟汇总」网页 + 提供公招推荐 API。

网页里粘贴词条（空格/逗号分隔）→ 调本后端 → 用本人 owned 现算推荐。

用法：
  python scheduling/tools/site_server.py            # 默认 http://127.0.0.1:8787
  python scheduling/tools/site_server.py --port 8787
  python scheduling/tools/site_server.py --build    # 先生成网页再起服务

API：
  GET  /api/recommend?tags=高级资深干员%20输出%20...
  POST /api/recommend   body: {"tags": "..."} 或 {"tags":["...","..."]}
  GET  /api/reload      重新拉 owned（森空岛）
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import recruit_combo as rc  # noqa: E402

DEFAULT_HTML = ROOT / "scheduling" / "报告" / "汇总.html"
STATE = {"pool": None, "owned": None, "src": None}


def ensure_data(force=False):
    if STATE["pool"] is None or force:
        STATE["pool"], _ = rc.load_pool()
    if STATE["owned"] is None or force:
        STATE["owned"], STATE["src"] = rc.load_owned()
    return STATE


def payload(tags):
    st = ensure_data()
    tags = [t.strip() for t in tags if t and t.strip()]
    rec = rc.recommend(tags, st["pool"], st["owned"], topn=10)
    hit = [t for t in ("高级资深干员", "资深干员") if t in tags]
    return {"ok": True, "tags": tags, "hit": hit,
            "owned": len(st["owned"]), "source": st["src"], "recommend": rec}


class Handler(BaseHTTPRequestHandler):
    html_path = DEFAULT_HTML

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _html(self):
        try:
            b = pathlib.Path(self.html_path).read_bytes()
        except OSError as e:
            self.send_error(500, "读不到网页: %s（先跑 build_site.py）" % e)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/recommend":
            q = urllib.parse.parse_qs(u.query)
            raw = (q.get("tags") or [""])[0]
            self._json(payload(rc.parse_tags_arg(raw)))
        elif u.path == "/api/reload":
            st = ensure_data(force=True)
            self._json({"ok": True, "owned": len(st["owned"]), "source": st["src"]})
        elif u.path in ("/", "/index.html"):
            self._html()
        else:
            self.send_error(404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != "/api/recommend":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8") if n else "{}"
        try:
            d = json.loads(body)
        except json.JSONDecodeError:
            d = {}
        raw = d.get("tags") or ""
        tags = raw if isinstance(raw, list) else rc.parse_tags_arg(raw)
        self._json(payload(tags))

    def log_message(self, *args):  # 安静点
        pass


def main():
    ap = argparse.ArgumentParser(description="本地站点后端（网页 + 公招推荐 API）")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--html", default=str(DEFAULT_HTML))
    ap.add_argument("--build", action="store_true", help="起服务前先跑 build_site.py")
    args = ap.parse_args()

    if args.build:
        subprocess.run([sys.executable, str(HERE / "build_site.py")], check=False)

    Handler.html_path = args.html
    st = ensure_data()
    print("[site] owned=%s(%d)，公招池=%d" % (st["src"], len(st["owned"]), len(st["pool"])))
    print("[site] 打开 http://127.0.0.1:%d/" % args.port)
    print("[site] API: /api/recommend?tags=...   /api/reload")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[site] 停止")


if __name__ == "__main__":
    main()
