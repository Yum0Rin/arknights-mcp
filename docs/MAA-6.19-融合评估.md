# MAA 6.19.0 更新扒取与融合评估

> 触发：本机 MAA 已从 **MaaCore v6.18.0 → v6.19.0**（Release 2026-10-11），需盘点「新版本给了什么、怎么并进我们的流程」。<br>
> 核对方式（三证）：GitHub Release v6.19.0 正文 + **本机 DLL 字符串实测**（`C:\MAA\MaaCore.dll` vs `C:\MAA\.old\MaaCore.dll`=6.18.0）<br>
> + **dev-v2 源码**（`src/MaaCore/Task/Interface/OperProgressTask.cpp`、`src/MaaWpfGui/Models/AsstTasks/AsstOperProgressTask.cs`）。<br>
> 相关手册：[`MAA-INTERNALS.md`](MAA-INTERNALS.md)（任务/参数）、[`FINDINGS.md`](FINDINGS.md) §19/§21（踩坑）、[`MASTER-PLAN.md`](MASTER-PLAN.md)（判据）。<br>
> 留痕时间：2026-10-12。凡未实测者一律标 **未确认**。

---

## 一、结论摘要（先看这段）

| # | 6.19.0 更新 | 对我们 | 结论 |
|---|---|---|---|
| 1 | 新增 **`OperProgress` 干员培养任务** | ⭐⭐⭐ 最高 | 我们手算「材料缺口 + 逐关 Fight」的培养链，MAA 现在能整条代跑（含即缺即合、芯片、专精） |
| 2 | **`params.event_shop.blacklist` 现已可用** | ⭐⭐⭐ | [FINDINGS §19](FINDINGS.md) 的旧结论**作废**：活动商店选择性兑换可从「手点」改回自动 |
| 3 | 库存保持「当前活动预设」+「按达成率排序」 | ⭐⭐ | 与我们 `plan_week`（目标库存→逐日刷）等价；属 GUI 组装层，可作「极简模式」备选 |
| 4 | 定时启动前**唤醒计算机**并拉起 MAA | ⭐⭐ | 直接对上我们「定时执行未配」这条 pending decision |
| 5 | 基建换班**周计划**（按星期几）+ 入驻优先级调整 | ⭐⭐ | 基建相关；2026-10-12 用户改定：**基建交回 MAA**（`mode=20000` 队列轮换），手搓脚本归档 → 这些修复对我们**直接生效** |
| 6 | 复盘类：失败自动存图、任务用时、截图尺寸修复、旧资源清理 | ⭐ | 提复盘质量；「旧资源清理」暴露我们 `maa_update.py` 的 `robocopy /E` 不删旧文件 |
| 7 | OCR 纠错规则**热修复化**（随资源更新即时分发） | ⭐ | 资源 `version.json` 会更频繁 bump → 我们 `maa_update.py check` 语义仍成立，但「需更新」概率变高 |

**不建议动**：PC 端（我们是雷电安卓）、黑流树海/界园肉鸽细节、YostarKR/JP/EN 模板、界面主题外观。

---

## 二、逐条：是什么 / 我们现状 / 怎么融合

### 2.1 `OperProgress` 干员培养任务（新增，测试功能）

**是什么**：给定干员 + 精英化/技能等级/专精目标，MAA 自动逐步完成培养流程；材料**即缺即合**自动合成；
芯片（dualchip）自动去制造站合、催化剂缺了自动去**红票商店**补；训练室专精**自动选协助者**；支持拖拽排序。

**接口（已从源码核实，可直接调）** —— `Interface/OperProgressTask.cpp:25-27, 87-132`：

```json
{"plans": [
  {"role": "Warrior", "name": "乌尔比安", "elite": 2, "skill_level": 7, "skill_mastery": [3,0,0]}
]}
```

| 字段 | 类型 | 必填 | 校验 |
|---|---|---|---|
| `role` | string（`battle::Role`：`Caster`/`Medic`/`Pioneer`/`Sniper`/`Special`/`Support`/`Tank`/`Warrior`） | 否 | 缺省则按 `name` 查表；**查不到或同名多职业 → 拒绝**；`Drone`（装置/召唤物）→ 拒绝 |
| `name` | string | **是** | 非空（全空格也拒） |
| `elite` | int | 否 | 只能 1 或 2（**不能填 0**；不要精英化就别带这个 key） |
| `skill_level` | int | 否 | 2–7 |
| `skill_mastery` | int[3] | 否 | 每位 0–3（对应 1/2/3 技能，如 `[3,0,0]`=一技能专三） |

- **key 白名单严格**：出现 `role/name/elite/skill_level/skill_mastery` 之外任何 key → 直接 `set_params` 失败（返回 0）。
- 运行中不可改参数（`task is running, cannot set params`）。
- 结果码（DLL 字符串）：`AlreadySatisfied` / `OperatorNotFound` / `PrerequisiteNotMet` / `RecognitionFailed` / `ResourceInsufficient` / `TrainingRoomBusy` / `ChipNotCraftable` / `FormulaLocked` / `Completed` / `Unsupported`。
- **不是** MaaCore v6.18.0 的既有能力：6.19 的 `MaaCore.dll` 中 `OperProgress` 出现 **92 次**，`.old`(6.18.0) 为 **0 次** ⇒ 真·新增。

**我们现状**：`scheduling/tools/oper_cost.py` 算「当前练度 → 目标」的材料/龙门币/经验缺口（已接官方
`gamedata_const.json`），`plan_week.py` 把它折成逐关 `Fight`（如 `MN-4` 刷聚合剂）。**这条路要自己管**：
哪天刷哪关、次数、合成、芯片、红票购买、专精排队，全是我们的活儿。

**融合建议（分两步，别一步到位）**：

1. **先当「培养执行器」并行验证**（低风险）：对我们当前目标干员（乌尔比安 → E2L60 一技能专三）单独跑一次
   `OperProgress`，只给 plan 不改我们的 `weekly_plan`；跑完用 `ark_operbox_online` 对照练度是否达标，
   并记录 MAA 实际花了多少理智/材料（`StageDrops` 日志）。
2. **验证通过后再决定谁主导**：
   - 若 MAA 做得稳 → `plan_week` 的「培养刷材」段从「自算逐关」改为「一条 `OperProgress`」，
     `oper_cost.py` 降级为**预检/对账**工具（算缺口 → 与 MAA 结果比对，不进 `tasks`）。
   - 若不稳（测试功能，可能有 bug）→ 保持现状，只把 `OperProgress` 当「补做零碎专精/芯片」的补刀任务。
3. **注意口径冲突**：我们的目标是「E2L60 + 指定技能专三」，`OperProgress` 的 `elite=2` **不含等级目标**
   （无 `level` 字段）。等级（Lv）仍得靠 `plan_week` 的龙门币/经验规划或 MAA 的其他手段 ⇒ **融合后
   「等级段」归我们，「精英/技能/专精段」归 MAA**，账要分开记。

**验证清单**：`ark_run_task("OperProgress", {...})` 先拿一个**已达标**干员试（应立刻 `AlreadySatisfied`，不消耗资源）；
再拿一个「只差 1 个技能等级」的干员试真实流程。

### 2.2 `params.event_shop.blacklist` 现在能用了（旧结论作废）

**是什么**：`Custom` 任务跑 `task_names:["SS@Store@Begin"]` + `params.event_shop.blacklist`，
可**按商品名/物品 ID 排除**自动购买（6.19 GUI 同步加了黑名单勾选框 + 材料图标）。

**实测证据**：`event_shop` 字符串在 6.19 `MaaCore.dll` 出现 **1 次**（含
`CustomTask::parse_and_register_event_shop`、`SS@Store@Begin`、`set_params failed, event shop blacklist item is not string`、
`registered EventShop task`），6.18.0 为 **0 次**。

**我们现状**：[FINDINGS §19](FINDINGS.md) 记录 2026-10-10 在 v6.18.0 上传 `blacklist` **无任何注册日志、被静默忽略**，
于是当次改为**手动点**买 6 件家具；`state.json` 里「商店兑换/代币记录」至今是**未做**。

**融合建议**：

1. 重跑 §19 那次实验：`Custom` + `SS@Store@Begin` + `blacklist`，**先看日志**有没有
   `registered EventShop task` / `Parsed and registered EventShop task`；没有就立即停（别让它无脑买）。
2. 有日志 → 把「只买白名单/排除黑名单」接进 `event_act52side.json` 的 `skip:true` 口径
   （当前 `skip` 是**运筹层**标记，MAA 侧的黑名单是**执行层**，两者要**同源生成**，避免各写一份）。
3. 顺带解决「商店兑换/代币记录未做」：MAA 下单后由 `StageDrops`/商店日志回填 `state.json`。

### 2.3 库存保持（DepotMaintain）：当前活动预设 + 按达成率排序

**是什么**：库存保持新增「当前活动」预设（一键导入当前活动关卡掉落为目标）+「按库存达成率排序执行」
（每次运行把理智优先投给缺口比例最大的计划）。

**核实**：**不是** Core 任务（6.19 `MaaCore.dll` 里 `DepotMaintain` = **0** 次，只在 GUI `MAA.dll` 里）。
它就是 GUI 组装层：先跑 `Depot`（仓库识别）→ 对每个计划生成 `AsstFightTask{stage, drops:{itemId:目标}}`
（源码 `DepotMaintainTaskUserControlModel.cs`），再用 Fight 的 `drops`「任一达标即停」语义收尾。

**我们现状**：`plan_week.py` + `Fight.params.drops` 已是**同一套底层语义**（我们自己也用 `drops`），
且我们的目标是**代币/理智口径**（商店封顶、EX/S 首通、连战 `series`）——比「库存保持」表达力更强。

**融合建议**：**不替换**，把它当**长草期极简模式**备选（懒得算周计划时，用 GUI「当前活动预设 + 达成率排序」
兜底）；同时借鉴它的两个细节：
- 「**仅下发第一个不符且当日可执行的计划**」（`OnlyFirstInsufficientPlan`）——避免一次塞满队列；
- 「**临期药阈值 2 天**」（`ExpiringMedicineDays`）——我们排药时可以对齐这个口径（先用将过期的）。

### 2.4 定时启动前唤醒计算机（GUI 定时设置）

**是什么**：每个启用的定时项前 5 分钟用 **Windows 任务计划程序**唤醒计算机并拉起 MAA（仅支持从睡眠唤醒，
不支持从休眠唤醒）。

**我们现状**：`state.json.pending_decisions` 明写「定时执行未配：每天需手动 `python scripts/maa-week/maa_week.py run --date <日期>`」。

**融合建议**（三选一，待定，别默认上 GUI）：
- **A（推荐，最小改动）**：本机 Windows 任务计划，直接跑我们的 `maa_week.py run`（我们控制队列，MAA 只当执行器）；
- **B**：用 MAA GUI 的定时项 + 唤醒（省事，但队列由 GUI 配置驱动，与 `weekly_plan.json` 有**双写风险**）；
- **C**：paseo schedule（跨机、可观测，但多一层依赖）。

> 铁律不破：**任何时刻只让一个客户端驱动设备**（AGENTS.md 铁律 6）⇒ 选 A/B/C 之一，绝不能叠加。

### 2.5 基建：换班周计划 + 入驻优先级 + 换肤设施识别

**是什么**：①基建换班新增**周计划**（方案按星期几勾选启用，当日未勾选则跳过基建）；②调整会客室与控制中枢的
入驻优先级；③基建生产状态识别**兼容活动主题（换肤）设施**；④修「常规换班把本轮已安排干员重复分配到其他设施」、
修「宿舍入驻」、修训练室「专精完成」模板。

**我们现状（2026-10-12 已改）**：基建《搓玉 · 合成玉》A/B 班（游戏内队列 1/2 承载）**改由 MAA `Infrast` `mode=20000`
（队列轮换）驱动**；自研 `scripts/infrast-rotation/infrast_rotation.py` 已归档 `历史版本/`（用户 2026-10-12 裁定）。

**融合建议**：
- 周计划**不采用**（与 A/B 12h 轮换模型不同构）；
- **优先**采用 ③（换肤设施识别）：活动期基建换主题更容易被 MAA 认错 → 我们脚本里凡是走 MAA `Infrast`
  的环节（会客室/线索）都会受益，属**免费修复**；
- ④的两个修复只在用 MAA 自带换班时才相关 → 对我们**无影响**（记录备查）。

### 2.6 复盘与排障类（提升我们「复盘层」的观测质量）

| 更新 | 对我们的用法 |
|---|---|
| 任务链失败时**统一保存现场截图**至 `debug/interface` | 复盘/排障时直接取图，不用我们另截 |
| 任务日志**输出各任务用时** | 对账「计划 vs 实际」时可量化每关耗时（排 `series`/理智药节奏） |
| 修复 Python 集成接口**截图返回尺寸与实际图像不一致** | 我们的 `ark_screenshot`/`ark_find`/`ark_where` 直接受益；**需实测确认 ROI/模板仍对齐**（见 §四） |
| 各任务开始阶段遇**掉线弹窗立即停止队列** | 长任务链不再「逐个任务报错」刷屏，复盘日志更干净 |
| 修复**物品模板无效时仓库识别继续运行** | `ark_depot` 结果可信度提升（少一次「假成功」） |
| Python 集成接口更新时**清理新版本已移除的旧资源文件** | ⚠ 暴露我们 `maa_update.py` 用 `robocopy /E`（**不删**旧文件）⇒ 旧任务定义可能残留（见 §三 建议 3） |

### 2.7 OCR 纠错规则热修复化

**是什么**：干员名/关卡名的 OCR 纠错规则拆到**独立热修复资源**，随资源更新即时分发；配套「资源同步脚本支持
hotfix 变更自动 bump `version.json` + 单跳同步」。

**对我们的影响**：`maa_update.py check` 判据是 `resource/version.json.last_updated` 的**字符串比较**（本地 vs 远端），
hotfix 会 bump 它 ⇒ **语义仍成立**，但「资源需更新」会**更频繁**出现（好事：新活动/纠错到得更快）。
⇒ 只需把「资源已更新后**要重启 MCP/MAA 才生效**」这条提示保持在输出里（脚本已有）。

---

## 三、融合建议（按优先级 + 具体动作）

1. **P0｜先验证 `event_shop.blacklist`**（成本最低、收益明确、旧结论必须先作废或确认）：跑一次
   带 `blacklist` 的 `Custom(SS@Store@Begin)`，只买 1 件、看日志。**验证失败就别碰**。
2. **P1｜`OperProgress` 试点**：单个干员 + 已达标干员双测（见 2.1 验证清单），产出「MAA 实际消耗 vs 我们预算」
   对账表；据此裁定「培养段」谁主导。
3. **P2｜定时执行选型**：A/B/C 三选一（推荐 A），写回 `state.json`，并明确「单客户端」约束。
4. **P3｜`maa_update.py` 的删除语义**：给 `apply_resource` 增加可选的「按 MAA 官方清单清理被移除资源」
   （默认关闭）或至少**报告**「本地有、远端无」的文件列表，避免旧任务定义残留污染识别。
5. **P4｜复盘增强**：把「任务用时」「失败现场截图路径(`debug/interface`)」纳入我们复盘脚本的输入。

---

## 四、待实测 / 未确认（下一轮要闭环的）

- [ ] `OperProgress` 实跑：`set_params` 是否成功、`AlreadySatisfied` 是否即刻返回、材料合成是否真走制造站。
- [ ] `params.event_shop.blacklist` 在 **6.19.0 运行版**是否注册成功（看日志关键字）。
- [ ] 截图尺寸修复后，`ark_find`/`ark_where` 的 ROI 与模板匹配是否仍对齐（本机现截图 = **1920×1080**，模板基准 1280×720）。
- [ ] 一图流数据预检（Copilot）：6.19 `MaaCore.dll` 里 `yituliu` 出现 8 次，但**是否**新增 Core 侧预检参数 **未确认**
      （Release 说「需在设置中配置一图流 Token」→ 疑为 GUI 侧取数后下发给 Core）。
- [ ] `AutoRaisePotential`（自动提升潜能）在 6.19 是否可直接走 `Custom`（`params.auto_raise_potential.use_normal_token`）。

---

## 五、留痕与下一步

- 本评估已落盘：`docs/MAA-6.19-融合评估.md`（本文件）；
- [`MAA-INTERNALS.md`](MAA-INTERNALS.md)：版本号 6.18.0 → **6.19.0**，§2.18 标注「已在 release 生效」，新增 §2.20 库存保持（GUI 组装层）；
- [`FINDINGS.md`](FINDINGS.md) §21：§19 结论作废说明；
- `docs/state.json`：`pending_decisions` 增「培养执行器选型」「定时执行选型」，`resolved_2026-10-12` 增「MAA 已升 6.19.0」。
