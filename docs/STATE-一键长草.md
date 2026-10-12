# 一键长草 · 现状速查（on-call 先读这份）

> 更新：2026-10-12 夜（基建改 MAA 自带队列轮换；队列改**按天编辑**；监工对账见文末）
> **单一事实源：`scheduling/data/weekly_plan.json`**（含 `daily` 逐日视图；`weekly_plan.W42.json` 只是镜像）

## 入口

- 桌面快捷方式 **「明日方舟·助手」** → `pythonw scripts/skland/skland_gui.py`
- GUI「**长草**」tab 按钮：`直驱跑一键长草`（跑**当天那一份**）/ `写 MAA 配置`（也**只写当天**）/ `生成汇总网页` / `打开汇总网页`
- 「快捷工具」卡：`启动游戏`（含拉起雷电）/ `打开 MAA`
- 命令行：`python scripts/maa-week/maa_week.py show|write|run [--date YYYY-MM-DD] [--whole-week] [--strict] [--dry]`

## 规则（写死在 `scheduling/tools/plan_week.py` 的 `RULE`）

```
预算 = 自然(240×7) + 周常浓缩液(240，仅当"理智药读数不在本计划周"才加) + 理智药存量
R1 剿灭：5 次×25=125，每天 1 次；若 state.json.progress.annihilation.done(W=本周) → 跳过
R2 固源岩：期末 ≥ RULE.shards.target(现 1000) → 1-7 次数
R2.5 EX/S 首通：开放日落在本周 → 各关×1 必做，先占预算
R3 活动：按"商店要买总量"封顶，剩余预算反推次数
R3.5 培养：目标 RULE.train_targets(现「乌尔比安」)；商店能换的材料先抵扣；再用剩余预算刷
R4 1-7 填充：花光预算
R5 每日分配：活动只在窗口内；每天 ≤ day_cap = 240 + 药/天；**排不下就不排**
```

## 关键参数

| 项 | 值 |
|---|---|
| 连战 series | **活动关 10 / 普通关 6**（`MAA-INTERNALS.md:78`；不退化成单次） |
| 当前活动 | act52side（昨日海）：YW-6 开放 2026-10-09~10-23，EX 2026-10-16，S 2026-10-23 |
| EX/S 理智 | **往期 sidestory 口径估**（EX-1~8 = 15/15/18/18/21/21/24/30；S-1 = 30）**待实机核** |
| 基建分工 | **全部交给 MAA 自带的「队列轮换」**：`Infrast` `mode=20000`、`facility` = Mfg/Trade/Power/Control/Reception/Office/Dorm/Processing/Training。MAA 进基建 → 当前班有人心情 0 → 点游戏内「一键轮换」→ 各设施收菜（Rotation 下不换干员）。**自研 `infrast_rotation.py` 已归档**（`历史版本/基建改MAA轮换+队列按天-2026-10-12/`）。 |
| ⚠️ 队列口径 | **一天一天编辑**：`write`/`run` 默认只处理当天（读 `weekly_plan.daily`），非当天的 Fight 槽位在 GUI 里被**停用**；要整周才加 `--whole-week`。 |

## 命令

```bash
python scheduling/tools/plan_week.py --date 2026-10-13     # 生成周计划（确定性，含 daily）
python scripts/maa-week/maa_week.py show  --date 2026-10-13  # 看当天分到多少
python scripts/maa-week/maa_week.py write --date 2026-10-13  # 写 MAA GUI（只写当天，需关 MAA）
python scripts/maa-week/maa_week.py run   --date 2026-10-13  # 直驱当天
python scheduling/tools/build_site.py                      # 生成汇总网页
python scheduling/tools/site_server.py                     # 起后端（公招推荐框）
python scripts/skland/skland_cli.py status                  # 森空岛续期（401 时）
```

## 已修的坑（都踩过）

1. `--dry` 会真执行换班脚本 → 修（dry 只打印）。
2. `plan_week.py` R2.5 代码块顺序错/重复 → 修（`ev`/`extra_san` 提前、删重复块）。
3. 流程里同时有 MAA 收菜 + 换班收菜（重复）→ 去 MAA Infrast 任务。
4. 活动关/1-7 没带 `series` → 退化成单次刷 → 修（活动 10、普通 6）。
5. 每日 41 次（861 理智/天，打不完）→ 每日按 `day_cap=240+药/天` 封顶。
6. GUI「刷新数据/签到」不续期 → 森空岛 401 → 修（先 `refresh_token`）。
7. 「读理智药」做成了按钮 → 移除（它是每周定时的活）。

## ⚠️ 未稳定 / 待测试（**别当成熟的用**）

| 项 | 状态 |
|---|---|
| **EX/S 关代码与理智** | `YW-EX-1..8` / `YW-S-1` 是**往期 sidestory 口径估的**，未实机核；EX 2026-10-16 开、S 10-23 开，开了必须核 |
| **`side.if_due` 到期判定** | 新加（查 `state.json.triggers`），**未实跑验证**（只过了编译） |
| **`side.args` 支持** | 新加，**未实跑** |
| **每趟 `day_cap` 封顶** | 逻辑已改（自然+均摊药），**只做过 dry/计算验证**，未长时间实跑 |
| **培养成本** | ✅ 改用官方 `gamedata_const`（`characterExpMap`/`characterUpgradeCostMap`/`evolveGoldCost`），`oper_cost.py` 支持按当前练度只算剩余段。⚠ 仍：`plan_week` 调 `compute()` **未传 `from_skland`** → 技能等级按 1 算（高估）；「常用技能」仍假设技能 1 |
| **`series` 连战** | 活动 10 / 普通 6 已实测能跑通；但**余数批次**（如 123 = 12×10+3）未逐次确认 |
| **本周(W41)执行** | **只跑到一半**（用户中途放弃），账不完整 |
| **商店兑换 / 代币记录** | **未做**（需进游戏内商店 OCR） |
| **周报(收益账本)** | 目前只有示例行，真实采集链未接 |

## 待办

- [ ] EX/S 关代码与理智**实机核对**（现在是往期口径估）
- [x] ~~「升级(1→Lv)」的经验/龙门币未计入~~ **已修（2026-10-12）**：官方 `gamedata_const.json` 有 `characterExpMap`/`characterUpgradeCostMap`/`evolveGoldCost`，`oper_cost.py` 已接入，并按**当前练度**只算剩余段（`--from-skland`，含技能/专精）。
- [ ] 「常用技能」目前假设技能 1（该 M3 哪个待定）
- [ ] 本周(W41)只跑到一半（用户中途放弃），下周一(W42)按 `weekly_plan.W42.json` 重跑
- [ ] 商店兑换/代币记录（需进游戏内商店 OCR）

---

## 监工对账（2026-10-12 夜，脚本硬核不靠肉眼）

核对口径：`weekly_plan.json` 的 `daily` ↔ `tasks` 互相咬合、逐日 ≤ day_cap、≤ 预算、开放窗口、剿灭周上限、固源岩期末目标、商店代币。

**✅ 自洽的（算过账，不是看着像）**

- 逐日各关合计 == 计划次数（1-7 418、剿灭 5、YW-6 4、EX 各 1）；
- 逐日 `sanity` == Σ(次数×关卡单价)，且每天 ≤ `day_cap` 406；全周 2837 ≤ 预算 2840（预算 = 自然 1680 + 周常 240 + 药 920）；
- EX 关都排在开放日 2026-10-16 之后；S 关（10-23）本周不排；
- 剿灭每天 ≤1 次、全周 5 次（周上限 1800 玉）；
- 固源岩：1128 − 周耗 647 + 418×1.245 ≈ **1002 ≥ 目标 1000** ✓（下限 417 次，实排 418）。

**❌ 三个真问题（按严重度）**

1. **EX 关现在 MAA 根本导航不了** —— `YW-EX-1..8` 在 `tasks.json` / `tasks/Stages/*.json` / `stages.json` 三处**都没有定义**，
   MaaCore 的导航条件（有同名任务 / `SSReopen-XX` / 主线正则）**一条都不满足** → `append_task` 返回 0。
   - 远端 `MaaResource` 与本地同日（2026-10-09T23:31），且**只提供 `resource/tasks/hotfix/`** ⇒ `maa_update.py apply` **拿不到**关卡定义；
     关卡定义随 **MAA 软件版（release）** 走。
   - 已加**预检**：`run` 遇到导航不了的关**跳过**并留证（`--strict` 才失败），不再让一条 append=0 打死整天。
   - **10-16 前的动作**：①跑 `maa_update.py check`（若无更新就等 MAA 发版）②EX 首通改走 `scripts/event-copilot`（Copilot 用作业导航）或手点。
2. **「期末固源岩 ≥1000」把预算吃到 88%，活动商店基本搬不动** —— 1-7 下限 417 次（2508 理智）先占，活动只剩 4 次（84 理智），
   而商店非 skip 限购项要 **5110 代币**（≈244 次）→ 只够 ~2%。
   这是「合成玉最高优先」策略的**直接后果**，但与「活动有时间窗、搓玉无止境」冲突 ⇒ **需运筹层裁定**：
   `target=1000` 是否要在活动期让位（例如活动期按 `target=周耗` 或把 R3 提到 R2 之前）。
3. **`weekly_plan.json` 此前长期 stale**（旧口径：固源岩 1282/目标 500、剿灭 0、YW-6 123 次），与 `weekly_plan.W42.json` 不一致，
   而 `maa_week` 读的是前者 ⇒ 每次跑的都是旧账。本次已重新生成并把两者对齐（`W42` 现为镜像）。

**口径待复核（未标来源，沿用自 RULE）**：`shards.per_run=1.245`、`shards.daily_use=92.4`（搓玉日耗）、`annihilation.jade_per_run=370`（周上限 1800 下第 5 次实际只值 ~320）。
