# 明日方舟运筹规划 · 总指挥文档（MASTER-PLAN）

> 版本：v1 · 2026-10-10（由 plan 子 agent 通读本仓库后产出，主 agent 落盘）
> 用途：本仓库 arknights-mcp 的"总指挥"决策主文档。让 Agent 独立完成
> **跑日常拿资源 → 用理智换资源 → 用资源凑练度 → 用练度抄作业 → 作业/活动再产资源** 的闭环。
> 依赖链用编号列表，不画 ASCII 图。
> 数据口径/踩坑见 `docs/DATA-SOURCES.md`、`docs/FINDINGS.md`；活动关流程见 `docs/WORKFLOW-活动关作业.md`。
> **每日执行入口 → `docs/STATE.md`**（决策状态快照 + 每日决策入口；agent 每次醒来先读 STATE 再读本档）。

## 0. 一句定位

把"玩明日方舟"拆成 **目标 → 数据 → 决策 → 执行 → 复盘** 五层。识别与操作**确定性**（走 MAA 模板/OCR，不用 AI 读图）；本人账号数据**优先森空岛在线**（免模拟器）。Agent 的职责 = 在每层按判据算、按脚本执行、按留痕复盘。

## 1. 五层决策链（总览）

1. 目标层：定本轮要达成什么。
2. 数据层：取本人账号快照 + 库存 + 需求清单。
3. 决策层：按公式算"养谁 / 理智怎么分 / 刷哪关 / 换什么"。
4. 执行层：把决策落成 MAA 任务/脚本调用。
5. 复盘层：留痕、轮换、数据刷新、下一轮触发。

## 2. 铁律（不可违背，逐条写死）

1. 操作游戏只用 MAA 功能，不用 adb 注入；识别走 MAA 模板/OCR，不自造 CV。
2. 跑识别/任务前确认 MAA 空闲（`RunDirectly=True` 会先跑日常队列 → 识别按钮 disabled）。
3. 触控模式 = `MaaTouch`（本机 MiniTouch 损坏）。
4. 日志写 `%TEMP%\arknights-mcp.log`；stdout 留给 MCP，绝不 print。
5. adb 带 `-s 127.0.0.1:5555`（否则 `more than one device`）。
6. 删文件走回收站；同一时刻只让一个客户端驱动设备。
7. 作业只抄"全部干员槽都 E2+"；取数优先森空岛；**不许** `ignore_requirements` 硬凑练度不齐。
8. 基建一律《搓玉·合成玉》方案，A/B 班各 720min 轮换，搓玉长期优先。
9. 合成玉（抽卡）最高优先。
10. 活动商店家具必满；干员信物首发必换满拿黄票。

---

## 3. 第一层：目标层

**目标 = 优先级排队，不是互斥。** 本号当前硬目标排序（用户已定）：

1. 合成玉（抽卡）—— 最高优先，搓玉不停。
2. 龙门币 —— 最缺（口径见 §5.2）。
3. 当期活动首通 + 商店（act52side 昨日海）。**时间已双证（官方 `activity_table` + PRTS）：作战/关卡结束 2026-10-23 03:59；活动/商店结束 2026-10-30 03:59**。→ 关卡只能打到 10-23，代币要在这之前刷够；10-23~10-30 只留兑换。
4. 抄作业刚需干员的精二/专精（补练度）。
5. 往期活动补打（剩余理智，排在活动与 1-7 之后）。

每个目标都能落到数据层 → 决策层 → 执行层的一条编号路径（见下）。

---

## 4. 第二层：数据层

### 4.1 本人账号两条路（选之前先读）

| 路径 | 工具 | 需要 | 给 |
|---|---|---|---|
| 森空岛在线（优先） | `ark_operbox_online` / `ark_infrast_status` | 联网 + 凭证 | 干员箱（**含技能等级/专精/模组/信赖**）、基建状态 |
| MAA 识别（兜底） | `ark_operbox` / `ark_depot` | 开雷电 + 游戏 + MAA 空闲 | 干员箱（无技能/专精）、**仓库（唯一来源）** |

判据：**只读查询 → 森空岛；需要仓库 or 改基建/打关 → MAA。**

### 4.2 取数要点

1. 森空岛 401 = 凭证过期 → `python scripts/skland/skland_cli.py status` 续期；首次 `... login`。
2. 森空岛 `sign` 签名：`md5(hmac_sha256(sign_token, path+query/body+ts+json(header)))`，`header={platform:3,timestamp,dId,vName}`；`dId` 随机值即可。
3. 字段映射两处 off-by-one：`rarity=charInfoMap.rarity+1`、`potential=potentialRank+1`。
4. 仓库 `DepotData.json` 只有 MAA 有，森空岛接口无；理智药存量森空岛无、MAA 识别项也不含 `ap_supply_lt_*` → 只能游戏内仓库页看（流程已固化，见 `docs/WORKFLOW-仓库取数.md`）。
5. 库存 `DepotData.json = {data:{itemId:数量}}`，itemId 与官方/企鹅一致。

### 4.3 需求/供给数据源

| 数据 | 来源 |
|---|---|
| 抄作业出现率 | `scheduling/tools/oper_appearance.json`（作业站 `document=挂机` 统计） |
| 基建培养建议 | `scheduling/tools/report_data.json.advice` / `training.json` |
| 干员培养成本（专精/精英/模组） | ArknightsGameData `character_table.json` / `uniequip_table.json` |
| 关卡掉落率 | 企鹅物流 `/result/matrix`（`quantity/times`，别用 dropRate） |
| 关卡理智/商店价 | PRTS wiki（滞后几天）/ 游戏内 OCR |
| 活动经济 | `scheduling/data/event_<id>.json` |

---

## 5. 第三层：决策层

### 5.1 养谁

**判据：目标集 = 基建刚需 ∪ 抄作业刚需；按 `required_rate` 降序，截前 N（用户：不养那么多）。**

1. 抄作业刚需：`oper_appearance.json` 中 `status ∈ {E0,E1}` 且 `required_rate` 高者。
2. 基建刚需：`training.json` / `report_data.json.advice` 中推荐且属《搓玉》方案核心者。
3. 取并集 → 按"出现率/推荐度"截前 N。

**需求 D 怎么算（专精为主 > 模组次之 > 精英化）：**

1. 技能专精（权重最高）：常用干员常用技能 → `levelUpCostCond`（专一~专三）。
2. 模组升级（次高）：常用干员模组 → `uniequip_table` 1/2/3 级。
3. 精英化：仅目标集里未精二者 → `phases[1|2].evolveCost`（E0 走 1+2 段，E1 只 2 段）。
4. 统计每材料"需求量 + 用人数"——用人数少的料，需求再低也别刷。

**实测高频要养（2026-10-10，1500 挂机作业，status E0/E1）：** 德克萨斯 27%、乌尔比安 23%、伊芙利特 14%、山 12%、夜莺 12%、拉普兰德 8.6%、澄闪 7.4%。

### 5.2 理智怎么排

**周预算口径：** 自然 240×7 + 周常浓缩液×2 = **1920 理智**；上限 205，每 12h 回复 120 < 205 → 上线花到 ≤85 不溢出。

**优先级（搓玉向，本号主口径）：**

1. 剿灭周上限 1800 玉 → 打满。
2. 1-7 刷固源岩养搓玉（搓玉日耗固源岩 92.4，需 1-7 出 ≈377 理智/天）。
3. 当期活动首通 + 刷代币（活动期插入，见 §5.4）。
4. 剩余理智：活动期刷最优关换商店；长草期按缺口补 CE-6（龙门币）/芯片/红票/技巧概要/经验。

**关键数字（判据）：**

| 项 | 每理智产出 |
|---|---|
| 活动商店龙门币 | **714 LMD/理智**（7 代币=5000，代币:理智=1:1） |
| CE-6 | 278 LMD/理智（36 理智=10000） |
| 基建（钱书均衡） | 55855/日（低于活动商店，高于 CE-6） |
| 1-7 固源岩 | 1.245/次，4.82 理智/个 |

**理智药何时吃：** 活动期刷代币缺口、或搓玉固源岩日缺（20 天约需 1212 理智药）时吃；平时囤到上限 999 不溢出即可。

### 5.3 每天打什么（每日清单模板）

**判据链（固定顺序，别跳步）：** 先算需求 D → 再看库存 S → 缺口 G = D − S → 最后挑供给性价比。

```
每日清单模板：
1. 收基建 + 换班检查（森空岛 ark_infrast_status 逐设施比对《搓玉》A/B 班）
2. 森空岛签到（skland_cli.py checkin）
3. 剿灭（周上限内打满）
4. 活动期：首通未打关 → 刷最优关换商店
   长草期：按 G 补 CE-6 / 芯片 / 红票 / 技巧概要 / 经验
5. 1-7 刷固源岩保库存 ≥1000
6. 更新数据文件（活动变动时）
```

活动期 vs 平时差异：活动期刷关产出代币=商店价值（> 常规图），应优先挤占理智；平时回到"CE-6 补龙门币 + 1-7 养搓玉"。

### 5.4 活动经济（选关刷 + 商店兑换）

**选关判据：** 代币/理智各关相同（1:1 三星）→ 看**该关掉落材料的用人数**；刷"用人数最多"的关。

**act52side 实测：** YW-6 全新装置 14 人用（且是改量装置 31 人用的前置）→ **刷 YW-6**；YW-8 液化高能气体 0 人用（不刷）；YW-7 转质盐组 4 人（不值）。

**商店兑换优先级（按需求×性价比）：**

1. 家具必满（act52side 6 件 310 代币）。
2. 干员信物：首发必换满拿黄票；复刻已换过则再换满多拿黄票（阶梯计价，先核价）。
3. 龙门币（714 LMD/理智，最高性价比）。
4. 寻访凭证、模组数据块、聚合剂、技巧概要卷3、高级作战记录。
5. 精英材料（按缺口 G ÷ 代币价排序）。

**首通 vs 刷关：** 首通（`run`，作业）→ 刷代币（`run --loop N`）。**代币=理智×星，刷代币必须三星**（二星只给一半）。

### 5.5 往期活动补打

判据：优先级排在当期活动与 1-7 之后，用剩余理智；作业适配仍按 E2 准入（`score==(0,0,0,0)`）；先 `sync` 补 MAA 资源再 `plan`/`run`。

### 5.6 基建（搓玉铁律）

1. 一律《搓玉·合成玉》方案（A/B 班各 720min，两班轮换）。
2. 贸易站 2 卖源石碎片→合成玉；制造站 2 产源石碎片；其余制造站产经验书/赤金。
3. 核对：森空岛 `ark_infrast_status` 逐设施比对（宿舍自动填充不校验）。
4. 轮换：每 ~12h，先菲亚梅塔置换"但书"心情，再 13 个房间逐个切队列（方向每轮交替），打时间戳进 `scheduling/data/infrast_rotation_log.jsonl`，间隔 ≥12h。

---

## 6. 第四层：执行层（工具/脚本调用）

### 6.1 MCP 工具（arknights_mcp.py）

| 工具 | 用途 |
|---|---|
| `ark_connect` / `ark_status` | 连模拟器（跑设备任务前必 connect） |
| `ark_screenshot` / `ark_where` / `ark_find` / `ark_tap` / `ark_key` | 观察/导航原语 |
| `ark_run_task` / `ark_task_result` | 跑 MAA 任务（长任务用 `wait=False` + 轮询） |
| `ark_operbox` / `ark_depot` | MAA 识别（需模拟器） |
| `ark_operbox_online` / `ark_infrast_status` | 森空岛在线（免模拟器） |
| `ark_read_log` | 排障 |

### 6.2 活动关（抄作业）

```bash
python scripts/event-copilot/event_copilot.py events          # 找活动 id
python scripts/event-copilot/event_copilot.py sync act52side  # 补 MAA 资源（新活动必需）
python scripts/event-copilot/event_copilot.py plan act52side --top 3
python scripts/event-copilot/event_copilot.py run act52side --stages 5,6,7,8 --try
python scripts/event-copilot/event_copilot.py run act52side --stages 6 --loop 30   # 刷代币
python scripts/event-copilot/event_copilot.py shop --pages 8   # 翻商店 OCR
```

**抄作业铁律：** 只抄 `score==(0,0,0,0)`（全员/全组 E2+）；导航只在多作业 `copilot_list` 路径（单作业 `filename` 不导航）；作业必须含非空 `actions`（列表接口不含，须 `/copilot/get/<id>`）；编队 `formation_index=4`（只用第四编队）；游戏停在活动关卡列表页。

### 6.3 基建 / 日常 / 剿灭 / 1-7 / CE-6

```bash
# 基建：Mode=Custom + 绝对 ASCII 路径（一图流导出 MAA JSON）；否则 Mode=Normal 一键换班
ark_run_task("Infrast", {"enable": true, "mode": 0, "filename": "<绝对路径>"})

# 刷关
ark_run_task("Fight", {"enable": true, "stage": "CE-6", "times": 5})
ark_run_task("Fight", {"enable": true, "stage": "1-7", "times": N})

# 剿灭 / 日常
ark_run_task("Fight", {"stage": "Annihilation", ...})   # 或对应剿灭任务
ark_run_task("StartUp", {"enable": true, "client_type": "Official", "start_game_enabled": true})
```

### 6.4 活动经济 / 培养

```bash
python scheduling/tools/event_economy.py scheduling/data/event_act52side.json --min-priority 高 --tokens-owned 206 --farm YW-6
python scheduling/tools/oper_appearance.py --pages 15 --top 25
```

---

## 7. 第五层：复盘层

1. 留痕：所有 adb/MaaCore 调用写 `%TEMP%\arknights-mcp.log`；基建换班写 `infrast_rotation_log.jsonl`（带时间戳）。
2. 数据刷新节奏：活动有变动（EX 开放/商店补货/代币变化）→ 重刷 `event_<id>.json` + 重跑 `event_economy.py`；干员箱变动 → 重跑 `oper_appearance.py`；森空岛 401 → 续期。
3. 轮换：基建 A/B 班每 ≥12h 换一次，方向交替。
4. 报告：改大件走 `build_report.py → parse_training.py → sanity_plan.py → render_report.py`。
5. 失败退理智：活动关失败退理智不亏，`--try` 逐个候选重试划算。

---

## 8. 数据口径与坑（速查）

1. 在线 vs MAA：elite/level/rarity 实测一致；potential 以在线为准；Skland 多出新干员。
2. 仓库只有 MAA 有（`DepotData.json`）；森空岛无仓库、无抽卡记录。
3. 森空岛 `sign` 不带 → `401 code=10000`（非"未登录"，别误判）；POST 漏 Content-Type → 400。
4. 单客户端；adb 滑动本机失效 → 用 MAA(MaaTouch) 滑动（`Custom`+`SlowlySwipeToThe*`）；tap 可用。
5. MAA 资源不认新活动 → `Not support stage` → `sync` 补，改完重启 MCP/MAA 实例。
6. **森空岛的 `status.ap`（理智）是旧快照，会明显偏低（实测实机 171 而接口 15）→ 理智一律以实机/游戏内为准**；森空岛的干员箱/基建可信度高，理智不可信。
7. 理智药**到期自动转理智**（上限 999），只要 理智<999 就不会浪费；`仓库→消耗物品` 详情页可看到期时间。
6. 一图流导入要裸干员数组（顶层 `own_opers`），不能直接喂 `OperBoxData.json` 对象。

---

## 9. 仍不确定 / 需用户确认

1. ~~理智药存量~~ **已实测（2026-10-10）**：浓缩液(+120)×5 + 加强剂(+60)×10 ≈ **1200 理智** + 流金影×1（流程与实测见 `docs/WORKFLOW-仓库取数.md`）。拼清单时按此数算活动刷关 + 搓玉缺口。
2. EX/突袭各关理智单价（act52side_09..16）：待企鹅 `stages?server=CN` 取，决定 24 次首通总理智。
3. 干员信物阶梯价明细：每档价格待核（首发已换过的话，复刻再换满的黄票收益需具体数）。
4. 基建队列换班的两按钮语义（⇄ 与 ⟫）本轮是用户口述 + 截图，未实机复核，首轮执行前需截图确认。
5. 活动商店第 1 屏之后的价格/限购部分"看图核准"，建议 PRTS/企鹅最终核对。
6. 养谁截"前 N"的具体 N 值：未定，需用户拍板（建议 5~8 名）。
7. 搓玉是否导成 MAA custom_infrast 全自动换班：目前走游戏内手点；若要全自动需另做导出。
