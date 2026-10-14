# 一键长草 · 现状速查（on-call 先读这份）

> 更新：2026-10-14（**规划支持「剩余 X 天」**（今天..本周日，非固定 7 天）+ **自然理智按上限 205/天**（1 次/天玩法）；
> 剿灭按**已完成合成玉扣减**；`session_advice` 改「1 次/天、花到 ~0」；**理智药整瓶 60 对齐 + 1-7 补零**（每天花到 ~0）；
> 药读数重测 760（原 920）→ 整瓶 720；W42 已重生成 `range 2026-10-14..10-18`、预算 1745、逐日 445/265/265/325/444）
> 前一版：2026-10-13 夜（执行链防御：今天不在计划里→报错停；GUI 子进程日志编码修 UTF-8；`run` 冷启动自动拉起模拟器；实跑验证 10-13 直驱跑通，925s）
> **单一事实源：`scheduling/data/weekly_plan.json`**（含 `daily` 逐日视图；`weekly_plan.W42.json` 只是镜像）

## 入口

- 桌面快捷方式 **「明日方舟·助手」** → `pythonw scripts/skland/skland_gui.py`
- GUI「**长草**」tab 按钮：`生成/刷新计划`（跑 `plan_week.py` 后自动刷新本页）/ `写 MAA 配置`（也**只写当天**）/ `直驱跑一键长草`（跑**当天那一份**）
- 「快捷工具」卡：`启动游戏`（含拉起雷电）/ `打开 MAA` / `生成汇总网页` / `打开汇总网页` / `刷新计划`
- 命令行：`python scripts/maa-week/maa_week.py show|write|run [--date YYYY-MM-DD] [--whole-week] [--strict] [--dry]`

## 规则（写死在 `scheduling/tools/plan_week.py` 的 `RULE`）

```
窗口 = **今天..本周日（剩余 X 天）**，不是固定 7 天（`plan_week.plan(date, start)`；CLI `--from`）
预算 = 自然(**205/天** × 剩余天数) + 理智药存量
      ⚠ 自然按 **205/天**（= 上限），**不是 240/天**：本机玩法「**1 次/天**、来时理智满、跑完下线」，
        24h 回 240 被上限 205 卡住 → 每天只能用 205，多出的 **35/天溢出**（2026-10-14 用户裁定）。
      ⚠ **不再另加周常浓缩液 240**：药存量由「每周日手动跑 scripts/sanity-potion/sanity_potion.py 测出」
        写入 scheduling/data/sanity.json，**该读数已包含周常药**，重复计入会把预算虚高（2026-10-12 用户裁定）。
R1 剿灭：满额 5 次×25=125，每天 1 次；**按已完成合成玉扣减**（progress.annihilation.jade，W=本周）
      → 剩余 = ceil((1800−已得)/370)；打满则 0
R2 固源岩下限（**条件 target**）：有活动要打 → 500；无活动 → 1000
      → 1-7 下限 = ceil((target + 日耗×7 − 库存)/单次产出)，**向上取整到 series 整倍数**（保库存底线）
R2.5 EX/S 首通链：读 docs/state.json.progress.event_<活动> 的**已通进度** → 只排**未通**的关、
      **从第一个未通起的前缀链**（EX-1→EX-8 依次解锁，前面未通则后面排不了；已通的不重复排）；
      进度缺失 → 当全未通。seq 保证「按序、跨天单调不减」
R2.6 突袭：**只有 EX 关和 S 关有突袭**（普通关 YW-1..8 没有）；突袭依赖「该关普通已通」，
      排在对应普通之后，按关顺序（task 类型 `Raid`；MAA `Fight` 做不了活动突袭）
R3 活动：**在 ann + EX/S首通+突袭 + 1-7下限 之后**吃**剩余预算**（活动让 1-7 让位）；
      上限仍是「商店要买总量反推的次数」cap_runs
R3.5 培养：再剩 → 培养刷材料
R4 1-7 填充：最后剩 → 1-7 填充（**理智尽量花光**）
R5 每日分配：活动只在窗口内；带 seq 的首通**按序跨天单调不减**；其余往"最空的天"填；
      **按「连战批次」分配 → 每天次数为该关 series 的整倍数**（消 GUI「余数无法用尽」警告）
R6 次数取整：Fight 次数按该关 series 取整（**下限向上**、活动/填充**向下**）；余数回流预算
R7 用药：逐日视图带 `medicine = max(0, 当天理智 − 205)`（205 = 上限 = 1 次/天可用自然量）；只**配上药的关**（1-7/活动关），
      剿灭/EX 首通不吃药。药是**整瓶 60**（`RULE.medicine_bottle`）→ 预算只算 `(存量//60)*60`；每天目标对齐到 `205+60k`，
      余数用 1-7 补零抹平（花到 ~0）。`maa_week` write 同步 `UseMedicine/MedicineCount/MedicineExpireDays`、run 传 `medicine`
```

## 关键参数

| 项 | 值 |
|---|---|
| 连战 series | **活动关 10 / 普通关 10**。上限**运行时按资源判定**：`plan_util.series_cap()`（resource 有 `FightSeries-OldMethodFlag`→旧列表 6；无→新列表 10，本机=10）；可用 `ARK_SERIES_CAP` 覆盖。`plan_week`/`maa_week` 全走它、**不再硬编码**，`show`/`rationale` 会打印判定行。**次数按 series 取整**，逐日也是整倍数。 |
| 当前活动 | act52side（昨日海）：YW-6 开放 2026-10-09~10-23，EX 2026-10-16，S 2026-10-23 |
| 固源岩下限 | **条件**：有活动要打 → **500**（1-7 让位）；无活动 → **1000**。W42 库存 1163 > 500 → 下限 0（仅填充）。 |
| EX/S 理智 | `event_act52side.json`：EX-1~8 = 10/10/15/15/15/15/20/20、S-1 = 15（往期 sidestory 口径，**待实机核**） |
| EX/S 突袭 | **只有 EX/S 有突袭**（普通关 YW-1..8 无）；突袭依赖「该关普通已通」，按关顺序排在普通之后。突袭理智**暂按普通关同价**计（待数据层核实）。MAA `Fight` 做不了 → 走 `event-copilot`（Copilot `is_raid`）或手点，`maa_week` 遇 `Raid` 只提示不 append。 |
| EX/S 解锁链 | EX-i 未通打不了 EX-(i+1)（**依次解锁**）。执行：`python scripts/event-copilot/event_copilot.py run act52side --chain ex --try`（EX 普通）/ `--chain raid --try`（EX 突袭）/ `--chain s|sraid`（S）。**遇挫即停**（某关无作业/失败 → 不打后面的），跑完回写 `progress.event_act52side`。 |
| 预算/药 | 预算 = 自然 **205/天 × 剩余天数** + 药**整瓶可用量**（W42 剩余 5 天 → 1025 + **720** = **1745**）。**药读数每周日手动测**：`python scripts/sanity-potion/sanity_potion.py`（写 `scheduling/data/sanity.json`）——该读数**已含周常药**，故不加 240。药**整瓶 60** → 预算只算 `(存量//60)*60`（读数 760 → 整瓶 720，余数 40 不计，避免超发）。 |
| 用药（R7） | `daily[].medicine = max(0, 当天理智−205)`；只配 1-7/活动关（`plan.medicine_stages`）。W42 剩余 5 天逐日药 240/60/60/120/239=719≤720。**补零**：`distribute_daily` 末尾把每天目标对齐到 `205+60k`，余数用 1-7（6 理智/次）抹平 → 每天跑完剩 ≈0；药不够按瓶数回收 1-7 次数。 |
| 补零（1-7） | 见上：目的不是刷固源岩，而是**把「整瓶药的余数」花光**（如某天 205+60=265，活动只吃 255 → 补 1-7 把 10 花掉）。保证**每天剩 ≈0**，不再留 60/35 尾巴。 |
| ⚠️ day_cap 口径 | `day_cap = ceil(周预算/剩余天数)` 是**软目标**（`over` 标记用）；连战批次粒度 210 理智，硬按 day_cap 会放不下第 2 批 → 硬上限 = day_cap+210，部分天会 `over`（靠药覆盖）。 |
| 基建分工 | **全部交给 MAA 自带的「队列轮换」**：`Infrast` `mode=20000`、`facility` = Mfg/Trade/Power/Control/Reception/Office/Dorm/Processing/Training。MAA 进基建 → 当前班有人心情 0 → 点游戏内「一键轮换」→ 各设施收菜（Rotation 下不换干员）。**自研 `infrast_rotation.py` 已归档**（`历史版本/基建改MAA轮换+队列按天-2026-10-12/`）。 |
| ⚠️ 队列口径 | **一天一天编辑**：`write`/`run` 默认只处理当天（读 `weekly_plan.daily`），非当天的 Fight 槽位在 GUI 里被**停用**；要整周才加 `--whole-week`。 |

## 命令

```bash
python scripts/sanity-potion/sanity_potion.py               # ★每周手动测理智药存量（写 scheduling/data/sanity.json，已含周常药）
python scheduling/tools/plan_week.py                        # 生成计划（默认 今天..本周日 = 剩余 X 天，含 daily）
python scheduling/tools/plan_week.py --from 2026-10-16      # 指定第一天（仍排到本周日）
python scripts/weekly-refresh/weekly_refresh.py             # ★每周刷新：重生成计划 + 弹窗提醒重测药（定时任务调它）
powershell -ExecutionPolicy Bypass -File scripts/weekly-refresh/install_task.ps1   # 注册/重设每周计划任务（-Uninstall 注销）
python scripts/maa-week/maa_week.py show  --date 2026-10-13  # 看当天分到多少
python scripts/maa-week/maa_week.py write --date 2026-10-13  # 写 MAA GUI（只写当天，需关 MAA）
python scripts/maa-week/maa_week.py run   --date 2026-10-13  # 直驱当天（Raid/EX 自动跳过并提示可复制命令）
python scripts/event-copilot/event_copilot.py run act52side --chain ex --try    # EX 首通解锁链（遇挫即停）
python scripts/event-copilot/event_copilot.py run act52side --chain raid --try  # EX 突袭链（需该关普通已通）
python scheduling/tools/build_site.py                      # 生成汇总网页
python scheduling/tools/site_server.py                     # 起后端（公招推荐框）
python scripts/skland/skland_cli.py status                  # 森空岛续期（401 时）
```

> **流程**：①跑 `sanity_potion.py` 测药存量（**只统计「到期 ≤7 天」的药**；>7 天的不读不用）→ ②`plan_week.py` 生成计划（**默认 今天..本周日**；预算 = **205/天 × 剩余天数** + 药**整瓶可用量**，**不加 240**）→ ③`maa_week.py write/run`。周中重生成只排剩余天数。
> **每周定时任务**「方舟·每周刷新计划」= **每周日 20:00**（错过开机补跑）自动跑 `weekly_refresh.py`：**先复测药**（`sanity_potion.py --ensure-main`：拉起模拟器 + StartUp 到主界面 → 测药 → 写 `sanity.json`）**再**重生成计划 + 弹窗报告。
> 周日跑时今天属于旧的一周 → 生成的是**下周**计划（`range` = 下周一..下周日，满 7 天，与原先「周一早上跑」等价）；**代价**：今天(周日)本身不在该计划内，周日日常先跑完再刷新，或手动 `plan_week.py` 补一份。
> **测药顺序=先测药后生成**（否则计划用的还是旧读数）；测药失败只记录不崩（`--no-measure` 可关）。⚠ 单一客户端：测药要驱动设备，跑时别同时用 MAA GUI 驱动同一台；测药脚本**绝不盲点**，最坏是这次没测到。

## 已修的坑（都踩过）

1. `--dry` 会真执行换班脚本 → 修（dry 只打印）。
2. `plan_week.py` R2.5 代码块顺序错/重复 → 修（`ev`/`extra_san` 提前、删重复块）。
3. 流程里同时有 MAA 收菜 + 换班收菜（重复）→ 去 MAA Infrast 任务。
4. 活动关/1-7 没带 `series` → 退化成单次刷 → 修（活动 10、普通 6）。
5. 每日 41 次（861 理智/天，打不完）→ 每日按 `day_cap = ceil(周预算/7)` 封顶（现 406）。
6. GUI「刷新数据/签到」不续期 → 森空岛 401 → 修（先 `refresh_token`）。
7. 「读理智药」做成了按钮 → 移除（它是每周定时的活）。
8. **签到后「今日」状态不更新** → 修（2026-10-12）：`checkin()` 成功后再拉一次 `attendance`，经队列 `attendance` 重渲染「签到」页。
9. **「长草」页计划区永远空白** → 修（2026-10-12）：`_render_longcao()` 定义了却从未被调用；现建页即渲染 + 切页钩子重渲染，并补相关按钮。
10. **今天不在计划里时静默跑** → 修（2026-10-13）：`plan_util.plan_day()` 统一判定（`ok/out_of_range/no_entry/no_daily`），
    `write`/`run` 遇非 `ok` **打印原因 + 修复命令并退出码 2**（`run` 加 `--force` 才越过后只跑日常）；`show`/GUI 长草页醒目提示。
    顺带修 `⚠` 在 GBK 控制台 `UnicodeEncodeError` 崩脚本（`main()` 给 stdout/stderr 加 `errors=replace`）。
11. **雷电广告浮层盖住游戏**（2026-10-14）→ 修：广告是独立包 `com.android.flysilkworm`（用户应用，`SYSTEM_ALERT_WINDOW`），
    会在游戏之上弹、干扰 MAA 识别/点击（实测测药拉起游戏时被盖）。**本机已 `--disable` 永久禁用**
    （`scripts/ldplayer-ad/ldplayer_ad_guard.py --disable`；`--enable` 可恢复）。踩坑见 [`FINDINGS.md`](FINDINGS.md) §23。

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
- [ ] **★ 2026-10-16 16:00 EX 开放后，由总指挥排一次 MAA GUI**：走 `event_copilot.py run act52side --chain ex`（再 `--chain raid`），或先把当天队列写成 EX 首通（MAA `Fight` 导航不了 EX，需 Copilot/手点）。已记进 `state.json.triggers.event_ex_open`。
  - **照做清单见 [`docs/RUNBOOK-EX开放排GUI.md`](RUNBOOK-EX开放排GUI.md)**（体检 → 选路径 A/B → 顺序/依赖 → 理智账/缺口补法 → 核对留痕 → GUI 点 `Link Start!`）。
- [x] ~~「升级(1→Lv)」的经验/龙门币未计入~~ **已修（2026-10-12）**：官方 `gamedata_const.json` 有 `characterExpMap`/`characterUpgradeCostMap`/`evolveGoldCost`，`oper_cost.py` 已接入，并按**当前练度**只算剩余段（`--from-skland`，含技能/专精）。
- [ ] 「常用技能」目前假设技能 1（该 M3 哪个待定）
- [x] ~~**`plan_week.py` R3.5 培养里 `train_budget` 未定义**（潜在 `NameError`）~~ **已修（2026-10-14）**：按 RULE 顺序显式给值 `train_budget = max(0, budget − ann_san − extra_san − san17 − ev_runs·ev_san)`（活动吃完的剩余给培养）。此前该名从未定义 → 一有可刷材料行就 `NameError` → 被 `except` 吞成「培养估值失败」→ 培养恒为 0。`--dry` 验证：不再报错，计划输出不变（当前材料缺口仅 6 理智，培养仍 0）。
- [ ] 本周(W41)只跑到一半（用户中途放弃），下周一(W42)按 `weekly_plan.W42.json` 重跑
- [ ] 商店兑换/代币记录（需进游戏内商店 OCR）

---

## 监工对账（2026-10-12 夜，脚本硬核不靠肉眼）

> ⚠ **2026-10-12 晚已修正口径**：预算 2840→**2600**、day_cap 406→**372**（去掉重复计入的周常 240），
> 且 EX 首通加 seq 顺序 + 突袭规则。**下面 §✅/❌ 里出现的 2840 / 406 / 418 次 1-7 是旧口径，仅存档**；
> 最新一轮见本节末尾「最新一轮（预算 2600）」。

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

---

### 最新一轮（2026-10-12 晚 · 口径修正：target 条件 + 预算让位 + series 10 + 用药）

**预算** 2600（自然 1680 + 药 920）；**固源岩下限** target=**500**（有活动要打）→ 库存 1163 已超 → 下行取 0。
**sanity_alloc**：剿灭 125 + EX/S首通 120 + EX/S突袭 120 + 1-7 120(下限 0 + 填充 20) + 活动 **2100** + 培养 0 = **2585**；**`unplaced = {}`**。

| 日期 | 星期 | 理智/软上限 | 药 | runs | 突袭 |
|---|---|---|---|---|---|
| 2026-10-12 | 周一 | 445/372 | 205 | Annihilation×1、**YW-6×20** | — |
| 2026-10-13 | 周二 | 445/372 | 205 | Annihilation×1、**YW-6×20** | — |
| 2026-10-14 | 周三 | 295/372 | 55 | Annihilation×1、YW-6×10、1-7×10 | — |
| 2026-10-15 | 周四 | 295/372 | 55 | Annihilation×1、YW-6×10、1-7×10 | — |
| 2026-10-16 | 周五 | 265/372 | 25 | Annihilation×1、**YW-EX-1..8 各×1** | **YW-EX-1..8** |
| 2026-10-17 | 周六 | 420/372 | 180 | YW-6×20 | — |
| 2026-10-18 | 周日 | 420/372 | 180 | YW-6×20 | — |

- **预算顺序**：剿灭 → EX/S首通+突袭 → 1-7下限 → **活动吃剩余（2100，占 80.8%）** → 培养 → 1-7填充；活动不再被压到 0；
- **1-7**：下限 0（库存 1163 > 500）+ 填充 20 = 20 次（120 理智）—— 活动期 1-7 让位；
- **次数取整**：YW-6 20/10、1-7 10 均为 **series=10 整倍数**（GUI 不再警告余数）；活动原始 106 次→向下对齐 100 次，余量回流给填充；
- **用药**：只配 1-7/活动关；`daily[].medicine = max(0, 当天理智−240)`，全周 905 ≤ 920。`maa_week write` 写 `UseMedicine/MedicineCount=药量/MedicineExpireDays=2`，`run` 传 `medicine`；
- **`day_cap=372` 是软目标**（连战批次 210 理智装不下 2 个/天 → 硬上限 372+210，部分天 `over`，靠 medicine 覆盖）；
- **EX 日缺口**：10-16 理智 265 > 自然 240，缺口 25 需在 Copilot/手点时段自补药（EX 不走 MAA Fight）；
- **❌ 已闭环**：上一轮的「1-7 下限吃穿预算」冲突由本轮 target 条件 + 让位顺序解决；`pending_decisions` 里留了「用药/EX 缺口待观察」。
