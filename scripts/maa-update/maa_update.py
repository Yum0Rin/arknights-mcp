"""MAA 资源 / 软件 更新检查与更新（自用）。

背景：
- 本机 MAA 的 **资源**只随 OTA 更新，而 `ota.maa.plus` 不可达 -> 资源会停在旧版，
  于是 MAA 不认识新活动（`Fight("YW-6")` append 失败 / Copilot `Not support stage`）。
- 资源来源改用 GitHub 的 **MaaResource** 仓库（可达）。
- **软件**（MaaCore）走 GitHub Release（本机实测已是最新时无需动）。

用法：
    python scripts/maa-update/maa_update.py check              # 只检查（默认）
    python scripts/maa-update/maa_update.py check --json
    python scripts/maa-update/maa_update.py apply              # 检查 + 应用资源更新
    python scripts/maa-update/maa_update.py apply --software   # 连软件一起（谨慎，会自动备份）

约定：
- 资源版本 = `C:\\MAA\\resource\\version.json` 的 `last_updated`；远端 = MaaResource main 的同文件。
- 软件版本 = `C:\\MAA\\MAA.exe` 的 FileVersion；远端 = GitHub latest release 的 tag。
- 应用资源 = 下载 MaaResource main zip -> 解压 -> robocopy /E 覆盖 `C:\\MAA\\resource`（**不删**本地额外文件），
  覆盖前把 `version.json` 备份成 `version.json.bak-<时间戳>`。
- 每次运行追加一行到 `scheduling/data/maa_update_log.jsonl`（留痕）。
- 改完资源后，**已在运行的 MCP/MAA 实例仍用旧缓存** -> 需重启 MCP 才生效（脚本会提示）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

MAA = pathlib.Path(os.environ.get("ARK_MAA_PATH", r"C:\MAA"))
RES_DIR = MAA / "resource"
VER_FILE = RES_DIR / "version.json"

RELEASE_API = "https://api.github.com/repos/MaaAssistantArknights/MaaAssistantArknights/releases/latest"
RES_VERSION_URL = ("https://raw.githubusercontent.com/MaaAssistantArknights/MaaResource/"
                   "main/resource/version.json")
RES_ZIP_URL = "https://codeload.github.com/MaaAssistantArknights/MaaResource/zip/refs/heads/main"

REPO = pathlib.Path(__file__).resolve().parents[2]
LOG_FILE = REPO / "scheduling" / "data" / "maa_update_log.jsonl"

UA = {"User-Agent": "arknights-mcp/maa-update"}


def _http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def _download(url, dst: pathlib.Path):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=600) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f, length=1024 * 256)
    return dst


def local_resource_version() -> str | None:
    try:
        return json.load(open(VER_FILE, encoding="utf-8")).get("last_updated")
    except Exception:
        return None


def remote_resource_version() -> str | None:
    try:
        return _http_json(RES_VERSION_URL).get("last_updated")
    except Exception:
        return None


def local_software_version() -> str | None:
    if not (MAA / "MAA.exe").exists():
        return None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Item '%s').VersionInfo.FileVersion" % (MAA / "MAA.exe")],
            capture_output=True, text=True, timeout=30)
        return (out.stdout or "").strip() or None
    except Exception:
        return None


def remote_software_version():
    try:
        d = _http_json(RELEASE_API)
        tag = (d.get("tag_name") or "").lstrip("v")
        asset = next((a for a in d.get("assets", [])
                      if a["name"].endswith("win-x64.zip") and a["name"].startswith("MAA-v")), None)
        return tag, (asset or {}).get("browser_download_url")
    except Exception:
        return None, None


def _norm(v):
    if not v:
        return ()
    v = v.lstrip("v").split("-")[0]
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return ()


def check() -> dict:
    lr, rr = local_resource_version(), remote_resource_version()
    ls, (rs, sw_url) = local_software_version(), remote_software_version()
    res_outdated = bool(rr and lr and rr > lr)
    sw_outdated = bool(rs and _norm(ls) and _norm(rs) > _norm(ls))
    return {
        "resource": {"local": lr, "remote": rr, "outdated": res_outdated},
        "software": {"local": ls, "remote": rs, "outdated": sw_outdated, "url": sw_url},
        "action_needed": res_outdated or sw_outdated,
    }


def apply_resource() -> dict:
    tmp = pathlib.Path(tempfile.gettempdir()) / "MaaResource-main.zip"
    print("[res] 下载 %s ..." % RES_ZIP_URL, flush=True)
    _download(RES_ZIP_URL, tmp)
    print("[res] 解压 ...", flush=True)
    with zipfile.ZipFile(tmp) as z:
        root = z.namelist()[0].split("/")[0]
        z.extractall(tmp.parent)
    src = tmp.parent / root / "resource"
    if not (src / "version.json").exists():
        raise RuntimeError("解压结果不含 resource/version.json：%s" % src)
    # 备份旧 version.json
    if VER_FILE.exists():
        bak = VER_FILE.with_name("version.json.bak-%s" % _dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(VER_FILE, bak)
    # robocopy /E 覆盖（不删本地额外文件）
    r = subprocess.run(["robocopy", str(src), str(RES_DIR), "/E", "/NFL", "/NDL", "/NJH", "/NP",
                        "/R:1", "/W:1"], capture_output=True, text=True)
    ok = r.returncode < 8
    return {"src": str(src), "robocopy_rc": r.returncode, "ok": ok,
            "new_version": local_resource_version()}


def apply_software(url: str) -> dict:
    if not url:
        return {"ok": False, "error": "没有可下载的 win-x64 资产 URL"}
    tmp = pathlib.Path(tempfile.gettempdir()) / "MAA-update.zip"
    print("[sw] 下载 %s ..." % url, flush=True)
    _download(url, tmp)
    out = pathlib.Path(tempfile.gettempdir()) / "MAA-update"
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(out)
    # 备份 config / data（用户配置与识别产物）
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for name in ("config", "data"):
        p = MAA / name
        if p.exists():
            shutil.copytree(p, MAA / ("%s.bak-%s" % (name, stamp)), dirs_exist_ok=True)
    # 只覆盖程序与运行库，保留 config/data/cache/debug
    EXCLUDE = {"config", "data", "cache", "debug", "achievement"}
    copied = []
    for item in out.rglob("*"):
        rel = item.relative_to(out)
        if rel.parts and rel.parts[0] in EXCLUDE:
            continue
        if item.is_file():
            dst = MAA / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst)
            copied.append(str(rel))
    return {"ok": True, "copied": len(copied), "backup_stamp": stamp}


def _log(entry: dict):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="MAA 资源/软件 更新检查与更新")
    ap.add_argument("cmd", nargs="?", default="check", choices=["check", "apply"])
    ap.add_argument("--software", action="store_true", help="apply 时连软件一起更新（谨慎）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args(argv)

    st = check()
    print("[MAA] 资源 本地=%s 远端=%s %s" % (
        st["resource"]["local"], st["resource"]["remote"],
        "需更新" if st["resource"]["outdated"] else "最新"))
    print("[MAA] 软件 本地=%s 远端=%s %s" % (
        st["software"]["local"], st["software"]["remote"],
        "需更新" if st["software"]["outdated"] else "最新"))

    result = {"check": st, "applied": []}
    if args.cmd == "apply":
        if st["resource"]["outdated"]:
            r = apply_resource()
            result["applied"].append({"resource": r})
            print("[res] 完成：新版本=%s rc=%s" % (r.get("new_version"), r.get("robocopy_rc")))
            print("[!] 资源已更新，**需重启 MCP/MAA 实例**才生效（MaaCore 启动时缓存了资源）。")
        if st["software"]["outdated"] and args.software:
            r = apply_software(st["software"]["url"])
            result["applied"].append({"software": r})
            print("[sw] 完成：%s" % r)
            print("[!] 软件已更新，**需重启 MAA/MCP**。")
        elif st["software"]["outdated"]:
            print("[sw] 发现软件有新版本，但未加 --software，跳过。")

    _log({"ts": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "cmd": args.cmd,
          "check": st, "applied": result["applied"]})
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not st["action_needed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
