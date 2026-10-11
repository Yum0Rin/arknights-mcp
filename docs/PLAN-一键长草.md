# 方案：MAA「一键长草」升级（意图层运筹 + 双路径落地 + 本地汇总网站）

> 版本：v1 草案 · 2026-10-11 · 状态：**待用户过要素**（§3.3 是重点）
> 目标：把「每周玩方舟」变成 —— **运筹算出本周怎么打 → 写进 MAA 或直驱 MaaCore → 本地网站汇总留痕**。
> 关联：`docs/MASTER-PLAN.md`（判据）、`docs/STATE.md`（循环）、`docs/收益账本与周报.md`（账本）、
> `scheduling/tools/{event_economy,sanity_plan,revenue_weekly,render_report}.py`、`scripts/infrast-rotation/infrast_rotation.py`。

## 0. 一句话

**意图层**（运筹判据，产出 `weekly_plan.json`）→ **应用层**（`maa_week.py` 双路径）→ **执行层**（MaaCore / MAA GUI）；
外加 **本地网站**（汇总每周安排 + 收益周报 + 排班报告）与 **paseo 每周定时**。

## 1. 端到端流程

1. 取数：森空岛 `ark_operbox_online` / `ark_infrast_status` + MAA `Depot`（仓库）。
2. 运筹：按 §3 判据算本周 理智分配 / 各关次数 / 商店兑换 → 写 `scheduling/data/weekly_plan.json`。
3. 应用：`python scripts/maa-week/maa_week.py write`（写 MAA 配置）**或** `... run`（直驱 MaaCore）。
4. 执行：MAA GUI 点「开始」；或 MaaCore 直接跑。
5. 留痕：跑完更新账本 / 生成本周网站页。
6. 定时：paseo 每周一自动跑 2→5。

## 2. 执行层

### 2.1 任务顺序（**修正版**：先剿灭，后活动）

```
StartUp(唤醒/启动客户端)
  → Fight(剿灭 Annihilation)          # 先剿灭
  → Fight(活动关 ×N)                   # 再活动
  → Fight(1-7 ×M)                      # 搓玉固源岩
  → Recruit(公招)
  → Infrast(mode=20000，只收菜)         # 换班不由 MAA 做
  → [infrast_rotation.py 换班，脚本另跑]
  → Mall(信用商店)
  → Award(领取奖励)                     # 必须最后（先产出才有奖领）
```

- **基建口径（已确认）**：MAA `Infrast` 只收菜（`mode=20000`，避免覆盖《搓玉》手排）；换班仍由 `infrast_rotation.py` 单独跑。
- **公招口径（已定）**：日常 `times=4`（攒许可）、`select/confirm=[3,4,5]`、**6 星不自动**。
  - **出 6★ 词条时给推荐**：网页「概览」有 **贴词条 → 推荐** 框，把公招刷出的词条粘进去即可。后端 `scheduling/tools/site_server.py` 按本人 owned（森空岛，取数前自动续期；失败回退 MAA）现算最优组合（含高级资深/资深优先 → P(新)）。
    启动：`python scheduling/tools/site_server.py` → 浏览器开 `http://127.0.0.1:8787/`。
    命令行即席：`python scheduling/tools/recruit_combo.py --tags "高级资深干员 输出 …"`。
    （不做日志监听——贴词条更省事。）
  - **攒黄票的批量刷：不自动化**（用户定，偶尔才需要）——需要时**直接把任务发给 MAA**：`Recruit` + `expedite:true`，`MaxTimes = 仓库招聘许可数 − 50`（保底留 50）。核心参数名 `expedite`（`MAA-INTERNALS.md:100`）；GUI 加急字段 `AutoUseExpedited` 默认关、不序列化。

### 2.2 两条落地路径（**都要**）

| 路径 | 命令 | 用途 | 前提 |
|---|---|---|---|
| **A 写 MAA 配置** | `maa_week.py write` | 你不想开 agent 时，直接开 MAA 点「开始」 | **MAA 必须关闭**（运行中改会被覆盖）；写入前备份 `gui.new.json` |
| **B 直驱 MaaCore** | `maa_week.py run` | agent/MCP 在场时，全自动跑 | 复用 `arknights_mcp._run_sequence` 的逻辑与任务默认参数 |

两路径的**唯一事实源**都是 `weekly_plan.json`；`write` 把 `tasks[]` 渲染进 `gui.new.json` 的 `TaskQueue`，`run` 把 `tasks[]` 顺序 append+start。

### 2.3 剿灭：新关先手工通关一次

- 当期剿灭若**从未打过** → 无法「快速扫荡」。
- 处理：**先抄作业打一遍**（用 `scripts/event-copilot/`）——**不允许借干员**，否则不解锁扫荡。
- 通关一次后即可 `Fight(stage="Annihilation")` 扫荡。
- 判据：`state.json` 记 `annihilation_cleared_<期>`；未清则本周计划把"剿灭抄作业"列为前置。

### 2.4 仓库识别（MAA `Depot`）

- **停在「主界面」开始**：`DepotBegin` 内含 `QuickSwitch@ToHome`，**MAA 自己导航到仓库**；要求 **游戏在主界面 + MAA 空闲 + 单客户端**。跑完游戏停在仓库页（~50s）。
- 调用：`ark_depot()`（= `ark_run_task("Depot")`，无参）。
- **注意**：`Depot` 只识别「基础物品」那批模板，**拿不到理智药/消耗品** → 理智药另走「消耗物品」tab 截图 OCR（`docs/WORKFLOW-仓库取数.md`）。

## 3. 意图层：运筹模型（**核心**）

### 3.1 建模

- **决策变量** `x_i` = 第 i 个关卡本周刷的次数（含 1-7、活动关、CE-6 等）。
- **目标** 最大化总效用：`Σ u_i · x_i`，`u_i` = 每理智边际收益（见 §3.2 的价值尺度）。
- **约束**：
  1. 理智：`Σ cost_i·x_i ≤ 周预算`（自然 1680 + 周常 240 = **1920**，可动用理智药 ≈1200 作缓冲）。
  2. 剿灭：`x_annih ≤ 5`（周上限 1800 玉，25 理智/次）。
  3. 活动：代币产出 `≥ 目标集缺口`；活动时间窗 `≤ 作战截止`。
  4. 搓玉：1-7 产出固源岩 `≥ 库存保底缺口`（默认可累积，非硬下限，看库存）。
  5. 各资源缺口 `≥ 0`（不超刷）。
- **本质是"下限满足 + 边际性价比贪心填满"的 LP**：先钉死必须项，余额按 `u_i` 降序填。

### 3.2 价值尺度（怎么比"合成玉 vs 龙门币 vs 材料"）

统一折算为 **每理智收益**，按用户铁律的优先级加权：

| 项 | 每理智收益（参考） | 说明 |
|---|---|---|
| 剿灭合成玉 | 打满 1800玉/周 ≈ 14.4 玉/理智 | 硬性打满 |
| 活动商店龙门币 | **714 LMD/理智** | 最高性价比，活动期优先 |
| CE-6 龙门币 | 278 LMD/理智 | 长草期补龙门币 |
| 1-7 固源岩 | ~0.258 固源岩/理智 | 搓玉原料，长期刚需 |
| 经验 LS-6 / 芯片 / 红票 / 技巧概要 | 按缺口补 | 具体值待补进表 |

> 数值以 `sanity_plan.py` / `event_economy.py` 重算为准；本表是口径占位。

### 3.3 要素清单（**★ 请逐项确认是否周全**）

**A. 预算侧**
1. 周理智预算：自然 1680 + 周常浓缩液×2 = 1920。
2. 理智上限 205、每 12h 回 120 → **溢出约束**（每天至少花 2 次、花到 ≤85）→ 影响"节奏"不只"总量"。
3. 可动用理智药存量：**每 7 天从仓库读一次**（保质期≈14 天，7 天刷新足够）；过期会自动转理智（上限 999）。
   数据源：MAA `Depot` 只认「基础物品」模板、**不含理智药** → 理智药要走「消耗物品」tab 截图 OCR（见 `docs/WORKFLOW-仓库取数.md` §3/§6）。

**B. 硬性下限（必须满足）**
4. 剿灭打满（1800 玉/周）。
5. 活动商店**目标集**刷够（家具必满；信物拿黄票；龙门币；寻访凭证；模组块；聚合剂；技巧概要卷3；作战记录；精英材料按缺口）。
6. 搓玉固源岩库存保底（建议 ≥1000）。
7. 森空岛签到 / 基建收菜；**公招**日常 `times=4` 攒许可（6 星不自动）；攒黄票的批量刷**不自动化**，需要时把任务发给 MAA。

**C. 活动侧**
8. 活动**作战截止** vs **商店截止**（两个不同日期，代币只在作战期刷得到）。
9. 各关 `代币/理智`（一般 1:1，三星才全额）+ **该关掉落材料的用人数** → 选关。
10. 已有代币 / 已换道具 → 剩余需求。
11. MAA 资源是否认识本次活动（新活动要先 `maa_update.py apply` / `sync`）。

**D. 长草侧**
12. 库存缺口 G = 需求 D − 库存 S：龙门币 / 经验 / 固源岩 / 芯片 / 红票 / 技巧概要。
13. 各缺口对应的最优供给关与性价比（CE-6 / LS-6 / 芯片关 / 红票关 / 技巧概要关）。

**E. 练度侧**
14. 抄作业刚需干员（`oper_appearance.json`，status E0/E1 高出现率）+ 基建刚需 → 材料需求 D。
15. 是否把"补练度"的刷料关排进本周（用户口径：不养那么多，截前 N=4）。
16. 材料需求量 / 合成链：**去 wiki 查现成表**（已有人做过，含芯片）；**芯片、精英材料的「合成」环节需在本仓库录成模板**（`scheduling/data/materials.json`：材料 → 合成配方 / 来源关卡）。

**F. 时间/冲突侧**
17. 活动期 vs 长草期的不同排法（活动期挤占 1-7）。
18. 往期活动补打（排在当期活动与 1-7 之后）。
19. 剿灭新关需先手工通关（§2.3）→ 属"前置任务"，占时间不占理智。

**G. 数据/口径侧**
20. 理智以**实机截图**为准（森空岛 `status.ap` 不可信）。
21. 仓库只有 MAA 有；练度优先森空岛。
22. 掉落率用企鹅物流 `quantity/times`。

### 3.4 判据链（可执行算法）

1. 取数（森空岛 + 仓库 + 活动 `event_<id>.json`）。
2. 算硬性下限：剿灭次数、活动目标集缺口→代币→次数、搓玉固源岩保底。
3. 扣掉硬性下限占用的理智。
4. 余额按 §3.2 边际性价比降序填（活动剩余代币 > CE-6 > 1-7 …）。
5. 溢出检查：把总量摊到每天，保证不溢出。
6. 产出 `weekly_plan.json` + 人类可读 `rationale`。

## 4. 基建换班脚本优化（`infrast_rotation.py`）

现状：坐标硬编码、每步固定 `sleep`、逐卡裁剪 OCR 猜位置。
优化（**增量、先备份**）：
1. 截图已换 gzip 快通道（已完成）。
2. 用新 `scripts/anchor-runner/` 的模板匹配替掉"网格裁剪 OCR"定位。
3. 固定 `sleep` 改"轮询到位"（截图确认状态变了才继续）。
4. 每步加回执校验（点完读回），失败可定位到步。
5. 抽成可被 `maa_week` 调用的函数（换班作为 `side` 任务）。

> 纪律：改前先快照旧版到 `历史版本/`；保持单客户端。

## 5. 本地汇总网站

**站点收进仓库，桌面只留一个入口快捷方式**：

```
scheduling/报告/
  汇总.html     # 单文件站（build_site.py 生成；内联样式；含"贴词条→推荐"框）
  index.html    # 基建排班报告（render_report.py 产出，被汇总页 iframe 内嵌）
```

- 后端：`python scheduling/tools/site_server.py` → 浏览器开 `http://127.0.0.1:8787/`（也可直接双击 `汇总.html`，只要后端在跑，推荐框照样能用）。
- **桌面入口**：快捷方式「明日方舟·助手」→ `pythonw scripts/skland/skland_gui.py`；GUI「长草」tab 里有「生成/打开汇总网页」。
- 复用了 Pico 主题（内联，离线可开）。

## 6. paseo 每周定时

- `paseo_create_schedule`，cron **每周日 18:00**（`0 18 * * 0`，时区 Asia/Shanghai）。
- 该 schedule 启动的 agent 干：
  1. MAA 更新检查（`maa_update.py check/apply`）；
  2. 取数（含**每 7 天一次的理智药仓库读数**）→ 跑 §3.4 判据 → 写 `weekly_plan.json`；
  3. 生成本周网站页 + 更新首页；
  4. `maa_week.py run`（**自动跑**，用户定）→ 跑完写结果进网站；
  5. 用消息渠道通知你"本周安排已生成/已跑完"。
- **防御性报告（用户定，必须）**：
  - 全程留痕 `scheduling/data/run_report.jsonl`；网站 `weeks/<周>.html` 记执行结果。
  - 任一步失败（`append_task` 返回 0 / `TaskChainError` / 超时 / 识别不到页面）→ **立即停止后续、截图存证**，并在网站首页顶部挂**红色告警** + 消息渠道推给你（**失败任务名 + 截图路径 + 日志片段**）。
  - 原则：**宁可半途停下报告，也不带病硬跑**。跑之前先验"MAA 空闲 + 单客户端 + 游戏在前台"。
- 模型纪律：定时 agent 用 `deepseek/deepseek-flash`。

## 7. 文件布局

```
scripts/maa-week/
  maa_week.py          # show / write / run 三子命令
  plan_schema.py       # weekly_plan.json 校验
scheduling/data/weekly_plan.json      # 本周意图（唯一事实源）
scheduling/data/weekly_plan_log.jsonl # 每周归档（追加）
```

`weekly_plan.json`（草案）：

```json
{
  "week": "2026-W42", "range": "2026-10-13..2026-10-19",
  "generated_at": "2026-10-13T04:30", "by": "paseo-schedule",
  "budget": {"sanity_natural": 1680, "weekly_potion": 240, "meds_available": 1200},
  "tasks": [
    {"type": "StartUp", "params": {"client_type": "Official", "start_game_enabled": true}},
    {"type": "Fight", "params": {"stage": "Annihilation", "times": 5}},
    {"type": "Fight", "params": {"stage": "YW-6", "times": 60}},
    {"type": "Fight", "params": {"stage": "1-7", "times": 50}},
    {"type": "Recruit", "params": {"select": [3,4,5,6], "confirm": [4,5], "times": 50}},
    {"type": "Infrast", "params": {"mode": 20000, "facility": ["Mfg","Trade","Reception"]}},
    {"type": "Mall", "params": {"enable": true}},
    {"type": "Award", "params": {"enable": true}}
  ],
  "side": [{"script": "scripts/infrast-rotation/infrast_rotation.py", "when": "after Infrast"}],
  "rationale": {
    "sanity_alloc": {"annihilation": 125, "event": 1260, "1-7": 535},
    "notes": ["活动作战截止 10-23 → 代币本周刷够", "1-7 补固源岩至保底 1000"]
  }
}
```

## 8. 分期落地

| 期 | 内容 | 依赖 |
|---|---|---|
| **P0** | `weekly_plan.json` schema + `maa_week.py show/write/run`（先用 §3 手算数字） | 无 |
| **P1** | 意图层自动化：取数→判据链→写 plan（接 `event_economy`/`sanity_plan`） | P0 |
| **P2** | 本地网站（首页 + 每周页 + 周报归档） | P0 |
| **P3** | paseo 每周定时 + 换班脚本优化 | P1,P2 |

## 8bis. 一体化工具（森空岛 GUI 总控台）

`scripts/skland/skland_gui.py` 扩成总控台（`pythonw scripts/skland/skland_gui.py` 启动）：
1. 「公招」tab：栏位状态 + **贴词条 → 推荐**（复用 `recruit_combo`，后台线程不卡界面）。
2. 新增「长草」tab：本周计划（读 `weekly_plan.json`）+ 按钮：`生成汇总网页` / `打开汇总网页` / `读理智药` / `写 MAA 配置` / `直驱跑一键长草`（后两者二次确认）/ **`打开 MAA`**。
3. 汇总网页与公招后端仍是独立脚本（`build_site.py` / `site_server.py`），GUI 负责一键调用。

## 9. 决策记录（2026-10-11 用户拍板）

1. ✅ §3.3 要素清单、§3.2 价值尺度：**通过**。
2. ✅ 理智药：**我每 7 天从仓库读一次**（保质期 14 天）。
3. ✅ 材料：**wiki 查现成数据**（含芯片）；芯片/精英材料**合成**录模板（§3.3 E.16）。
4. ✅ 网站：**收进仓库** `scheduling/报告/汇总.html`（桌面只留「明日方舟·助手」快捷方式入口）。
5. ✅ 定时：**每周日 18:00**，agent **自动 `run`**，必须带**防御性报告**（§6）。
6. ✅ 公招口径：日常 `times=4`；`select/confirm=[3,4,5]`，**6 星不自动**；网页给推荐词条组合。攒黄票批量刷**不自动化**（偶尔才要），需要时把任务发给 MAA（`expedite:true`，`MaxTimes=许可−50`）。
8. ✅ 仓库识别用 MAA `Depot`（停主界面，自己导航）；理智药需另走"消耗物品"tab OCR。
7. ✅ 路径 A（写 MAA 配置）：`maa_week.py write` 已就绪，**待 MAA 关闭后写入**（运行中写会被覆盖）。
