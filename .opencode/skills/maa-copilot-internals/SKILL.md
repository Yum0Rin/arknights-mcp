---
name: maa-copilot-internals
description: MAA「自动战斗(Copilot)」内部机制与踩坑——导航只在多作业 copilot_list 路径、作业必须含 actions、练度不足用 ignore_requirements、编队用 formation_index、作业站 prts.maa.plus API、adb 滑动失效改用 MAA、用 Custom 任务跑 tasks.json 任意任务。当要深入用 MAA 自动战斗、排查 Copilot 报错、或驱动 MAA 做任意操作时使用。
---

# MAA Copilot 机制与坑

源码依据（branch `dev-v2`）：`src/MaaCore/Task/Interface/CopilotTask.cpp`、`Task/Miscellaneous/MultiCopilotTaskPlugin.cpp`。
留痕：`docs/FINDINGS.md` §14、§15。

## 机制
- **Copilot 任务本身不导航**：8 个子任务第 2 个直接找 `BattleStartPre`（=已站在关卡准备界面才行）。
- **导航在"多作业"路径**：`params["copilot_list"] = [{"id":0,"filename":...,"nav_name_override":可空,"is_raid":false}]`，
  由 `MultiCopilotTaskPlugin::navigate_to_stage` 实现：有 `resource/template/StageNavigation` 模板走模板；否则 **HSV 颜色掩膜 + OCR 找关卡代号**(如 `YW-5`)点击，找不到就 `Copilot@StageNavigationSlowlySwipeLeft` 翻页。
  目标代号缺省取 `overview.json` 的 `code`。⇒ **游戏要先停在活动关卡列表页**。
- 参数：`filename`(单作业,无导航) / `copilot_list`(多作业,有导航) / `formation`(自动编队) / `formation_index`(第几队) /
  `ignore_requirements`(跳过未满足的属性/技能要求) / `loop_times`(重复) / `add_trust` / `support_unit_*`。

## 坑
1. **作业必须含非空 `actions`**，否则 `Json parse failed ... invalid map<K,T> key`。
   作业站 `/copilot/query` 列表的 `content` **不含 actions**，完整版用 **`https://prts.maa.plus/copilot/get/<id>`**。
2. **练度不够** → 自动编队 `OperatorMissing`（`reason=Unavailable`，`check_oper_level` 不过）→ 加 `ignore_requirements:true`。
3. **编队会覆盖槽位**：`formation_index` 0=不选择(不可控)；要写第 N 队就显式给 `formation_index=N`。
4. **失败退理智**：非三星时找不到 `StageDrops-Stars-3` → `TaskChainError`(msg 10000)；不亏，可换作业重试。
5. **MaaCore `append_task` 只认注册的任务类型**：`append_task("SlowlySwipeToTheUp")` 报 `invalid type`。
   → 用 **`Custom`** 类型跑 tasks.json 里的任意任务：`append_task("Custom", {"task_names": ["SwipeToTheUp"]})`。
6. **adb 滑动在本机失效**（`input swipe`/`input touchscreen swipe` 都不滚）；滑动只能用 **MAA(MaaTouch)**。tap 一般可用。
7. 作业站基址 `https://prts.maa.plus`（MAA.dll 里写死 `.../copilot/get/`）；`ota.maa.plus` 本机不可达，资源走 GitHub。

## 用 MCP 直接跑
`ark_run_task("Copilot", {"copilot_list":[...], "formation":true, "formation_index":4, "ignore_requirements":true})`。
