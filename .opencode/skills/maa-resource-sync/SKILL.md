---
name: maa-resource-sync
description: 当 MAA 不认识当期新活动（MaaCore 日志 Not support stage / UnsupportedLevel，ark_run_task("Copilot") 返回 id=0）时，从 GitHub MaaResource 补齐 MAA 本地资源（overview.json + 该活动 Arknights-Tile-Pos）。适用于「MAA 打新活动/新关卡报错」「跨版本跑旧作业」。
---

# 给 MAA 补资源（让它认识新活动）

## 症状
- `ark_run_task("Copilot", {...})` 返回 `id=0`；
- MaaCore 日志：`BattleProcessTask::set_stage_name` → **`UnsupportedLevel`** / `Not support stage`。

## 根因
Copilot 的 `BattleProcessTask::set_stage_name` 用 `resource/Arknights-Tile-Pos/overview.json` 索引校验关卡；
MAA 资源只随 OTA 更新，而本机 **`ota.maa.plus` 不可达(curl 000)** → 资源停在旧版本、不认识新活动。
（`api.maa.plus` / `mirrorchyan` 也不一定通；**GitHub raw 可达**。）

## 修复（推荐用脚本，已封装）
```bash
python scripts/event-copilot/event_copilot.py sync act52side
```
它做两件事：
1. 从 `https://raw.githubusercontent.com/MaaAssistantArknights/MaaResource/main/resource/Arknights-Tile-Pos/overview.json` 拉最新 overview，**整体替换**本地（旧的自动备份成 `overview.json.bak-*`）；
2. 下载该活动缺失的 `resource/Arknights-Tile-Pos/<levelid>-activities-...json`。

## 手动等价步骤
```
base=https://raw.githubusercontent.com/MaaAssistantArknights/MaaResource/main/resource
curl.exe -s -L --ssl-no-revoke <base>/Arknights-Tile-Pos/overview.json -o <MAA>/resource/Arknights-Tile-Pos/overview.json
# 再按 overview 里该活动的 filename 逐个下载
```

## 注意
- 改完资源后，**已在运行的 MCP/MAA 实例仍用旧缓存** → 要**重启**它（本机重启过 arknights MCP 进程）。
- `resource/stages.json`：**本地那份会过期**。实测（2026-10-10）本地旧版**没有 YW-/act52side**，
  导致 `ark_run_task("Fight", {"stage":"YW-6"})` **append_task 失败(id=0)**；而 MaaResource main 的
  `stages.json`（616 条）**已含 YW-1..8**。→ 更新资源后 `Fight` 就能直接刷活动关（**需重启 MCP 生效**）。
  Copilot 的关卡索引则一直是 `overview.json`。
- **一键检查/更新 MAA 资源/软件**：`python scripts/maa-update/maa_update.py check|apply`（见该脚本头注释）。
  软件目前是最新 v6.18.0；资源靠它从 GitHub MaaResource 覆盖更新。**建议每天先跑一次 check**。
- `overview.json` 每条含 `code`(如 YW-5) / `name`(三岔路口) / `levelId` / `filename`，也是取关卡清单的来源。
