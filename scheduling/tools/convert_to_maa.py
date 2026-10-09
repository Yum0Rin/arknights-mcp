# -*- coding: utf-8 -*-
"""把一图流导出的 MAA 排班 JSON 转成 MAA `resource/custom_infrast` 格式并落盘。

用法：python convert_to_maa.py <一图流MAA json> <输出json>
"""
import json, os, sys, time


def convert(src, dst):
    d = json.load(open(src, encoding="utf-8"))
    out = {
        "author": "arknights-mcp",
        "description": "由一图流生成、arknights-mcp 转换（勿手改，重生成覆盖）",
        "id": int(time.time() * 1000),
        "title": d.get("title", "排班表"),
        "planTimes": d.get("planTimes", "2班"),
        "plans": [],
    }
    for pl in d.get("plans", []):
        rooms = {}
        for fac, arr in (pl.get("rooms") or {}).items():
            items = []
            for r in arr:
                it = {
                    "skip": False,
                    "operators": r.get("operators", []),
                    "sort": bool(r.get("sort", False)),
                    "autofill": bool(r.get("autofill", False)),
                }
                if "product" in r:
                    it["product"] = r["product"]
                items.append(it)
            rooms[fac] = items
        dr = pl.get("drones", {}) or {}
        out["plans"].append({
            "name": pl.get("name", ""),
            "description": "",
            "Fiammetta": pl.get("Fiammetta", {"enable": False, "target": "", "order": "pre"}),
            "drones": {
                "room": dr.get("room", "trading"),
                "index": dr.get("index", 1),
                "enable": bool(dr.get("enable", False)),
                "order": dr.get("order", "pre"),
            },
            "rooms": rooms,
        })
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=4)
    print("wrote", dst, "plans=", len(out["plans"]))


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2])
