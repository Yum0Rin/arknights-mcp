# MAA 内部机制参考（MAA-INTERNALS）

> 依据：**MaaCore 源码（dev-v2）** 本地浅克隆 `C:\Users\39007\AppData\Local\Temp\MaaAssistantArknights` +<br>
> 资源 `C:\Users\39007\AppData\Local\Temp\MaaResource-main`；本机运行版 **MaaCore v6.19.0**（`C:\MAA`，上一版 6.18.0 在 `C:\MAA\.old`）。<br>
> 版本升级差异见 [`MAA-6.19-融合评估.md`](MAA-6.19-融合评估.md)。<br>
> 本文以**源码为准**，尽量标到文件+行号。凡源码/实测未覆盖的，标 **未确认**。用到时配合<br>
> [`AGENTS.md`](../AGENTS.md) 的源码路径与 [`FINDINGS.md`](FINDINGS.md) §14/§15 一起看。<br>
> 目的：说清"**MAA 支持哪些任务、参数是什么、关卡怎么导航、资源怎么组织、`append_task` 为什么返回 0**"。

---

## 1. 仓库结构总览

| 目录 / 文件 | 职责 |
|---|---|
| `src/MaaCore/` | **核心库**（C++，编译成 `MaaCore.dll`）。任务系统、识别、控制器都在这 |
| `src/MaaCore/Task/Interface/*` | **对外任务类型**（`StartUp`/`Fight`/`Infrast`… 各一个类，实现 `set_params`/`run`） |
| `src/MaaCore/Task/**` | 子任务/插件（`ProcessTask`、`Fight/*`、`Infrast/*`、`Miscellaneous/MultiCopilotTaskPlugin`…） |
| `src/MaaCore/Assistant.cpp` | `AsstAppendTask` 入口：解析 JSON → 建任务对象 → `set_params` → 入队（见 §7） |
| `src/MaaCore/Common/AsstMsg.h` | 回调消息码 `AsstMsg`（见 §5） |
| `src/MaaCore/Config/**` | 资源解析器（`ResourceLoader`、`TaskData`、`BattleDataConfig`…） |
| `src/MaaWpfGui/` / `src/Python/asst/asst.py` | GUI 集成 / Python 绑定（我们经 `C:\MAA\Python` 用的就是后者） |
| `resource/` | **静态资源**（随 MaaCore 版本走）：`tasks/tasks.json`、`template/`、`Arknights-Tile-Pos/`、`stages.json` 等 |
| `docs/zh-cn/protocol/integration.md` | **官方集成文档**（任务类型 + 参数字段表，与源码基本同步，本机在 MaaAssistantArknights/docs） |
| MaaResource 仓库 | **动态资源增量**（新活动地图/关卡任务/数值）：与 Core 版本解耦，单独更新；release 版把两者合并到 `C:\MAA\resource` |

**本机 release 的实际资源根** = `C:\MAA\resource`（= MaaAssistantArknights 的 `resource/` 静态部分 + MaaResource 覆盖的动态部分）。
Python 绑定：`Asst.load(path=C:\MAA)` 加载 `MaaCore.dll` 与 `resource/`；`C:\MAA\Python\asst\asst.py`。

> 浅克隆差异（**别被误导**）：`MaaResource-main/resource` 里**没有**大而全的 `tasks.json`（只有 `tasks/hotfix/`），
> 也没有完整 `template/`（只有 `infrast/`、`items/` 两个子目录）。完整 `resource/tasks/tasks.json` 与主模板库在
> **MaaAssistantArknights 仓库的 `resource/`** 里（dev-v2 仍保留，我们已确认存在 `...\resource\tasks\tasks.json`）；
> release 的资源目录是两者合并结果。

---

## 2. `AsstAppendTask` 全部任务类型

**通用规则**（`Assistant.cpp:303-369`）：

1. `AsstAppendTask(handle, type, params_json)`。成功返回 `task_id`（>0），失败返回 **0**。
2. `params` 先 `json::parse`，失败 → 0（`Assistant.cpp:307-311`）。
3. 按 `type` 字符串匹配任务类；**未知 type → 0**（`Assistant.cpp:345-349`，日志 `invalid type`）。
4. 建对象后先 `set_enable(json.get("enable", true))`（**所有任务都吃 `enable`，默认 true**），再 `set_params(json)`；
   `set_params` 返回 false → 记录 `invalid params` → 0（`Assistant.cpp:354-360`）。
5. 注册的全部 type（`Assistant.cpp:323-344`）：
   `Fight`、`StartUp`、`CloseDown`、`Award`、`Mall`、`Infrast`、`OperProgress`、`Recruit`、`Roguelike`、`Copilot`、
   `SSSCopilot`、`ParadoxCopilot`、`SingleStep`、`VideoRecognition`、`Depot`、`OperBox`、`Reclamation`、`SwitchTheme`、`Custom`
   （`Debug` 仅 `ASST_DEBUG` 编译时存在）。
6. `type` 字符串常量：`Task/Interface/*.h` 里的 `TaskType`（如 `FightTask.h:19` = `"Fight"`）。

> 参数默认值以**源码 `params.get(...)` 为准**；下表缺失行 = 该任务无其它参数。标注"运行中不可设"的字段另见官方文档。

### 2.1 StartUp（`StartUpTask.cpp:83-99`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `client_type` | string | `""` | **是** | `Config.get_package_name(client_type)` 查不到 → **返回 false**（空串查不到）。`Official`/`Bilibili`/`txwy`/`YoStarEN`/`YoStarJP`/`YoStarKR` |
| `start_game_enabled` | bool | `false` | 否 | 是否自动启动客户端（`StartGameTaskPlugin`） |
| `account_name` | string | `""` | 否 | 非空才启用切号（`AccountSwitchTask`） |

> 关键：`StartUp` 的**真正必填是 `client_type`**（不是 `enable`）。`{}` → `client_type=""` → `get_package_name` 返回 `nullopt` → 0。

### 2.2 CloseDown（`CloseDownTask.cpp:16-22`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `client_type` | string | `""` | 否* | 传给 `StopGameTaskPlugin`；**空则不执行**（文档口吻），`set_params` 本身恒返回 true |

### 2.3 Fight（理智作战，`FightTask.cpp:65-193`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `stage` | string | `""` | 否 | 空 = 上次/当前作战（`LastOrCurBattleBegin`）；否则走关卡导航（见 §3）。**运行中不可改** |
| `medicine` | int | `0` | 否 | 最多吃理智药数 |
| `medicine_expire_days` | int | `0` | 否 | 用过期≤N天的药；**<0 → 返回 false** |
| `stone` | int | `0` | 否 | 最多碎石数 |
| `times` | int | `INT_MAX` | 否 | 战斗次数；**`times=0` = 跳过本任务**（禁用全部子任务，`FightTask.cpp:158`） |
| `series` | int | `1` | 否 | 代理倍率；校验见下 |
| `drops` | object | 无 | 否 | `{item_id: qty}`，任一达标即停 |
| `report_to_penguin` / `penguin_id` | bool/string | `false`/`""` | 否 | 掉落上报企鹅 |
| `report_to_yituliu` / `yituliu_id` | bool/string | `false`/`""` | 否 | 掉落上报一图流 |
| `server` | string | `"CN"` | 否 | `CN`/`US`/`JP`/`KR`，影响掉落识别与上传 |
| `client_type` | string | `""` | 否 | 游戏崩溃后重启续刷；空则不启用 |
| `DrGrandet` | bool | `false` | 否 | 省理智碎石（等 1 点理智恢复再碎） |

- `series` 校验（`FightTask.cpp:95-103`）：`<-1` 或 `>10`（新列表）或 `>6`（旧列表，资源含 `FightSeries-OldMethodFlag`）→ **返回 false**。
- `expiring_medicine`（旧名）已弃用，传它会映射到 `medicine_expire_days`（`FightTask.cpp:72-80`）。

### 2.4 Recruit（公招，`RecruitTask.cpp:16-101`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `select` | array\<int\> | — | **是** | 会去点选的 Tag 星级（整数！）。缺失或非数字数组 → **返回 false** |
| `confirm` | array\<int\> | — | **是** | 会确认的 Tag 星级（整数）。只想"算"不给确认可给 `[]` |
| `refresh` | bool | `false` | 否 | 刷新三星 Tag |
| `extra_tags_mode` | int | `0` | 否 | 0/1/2；非法值回落到 0 |
| `times` | int | `0` | 否 | 招募次数，0 = 只计算 |
| `set_time` | bool | `true` | 否 | 是否设招募时限（仅 `times=0` 生效） |
| `force_refresh` | bool | `true` | 否 | 强制刷新（源码默认 true） |
| `expedite` | bool | `false` | 否 | 用加急许可 |
| `first_tags` | array\<string\> | `[]` | 否 | 首选 Tag（仅 3 星位） |
| `preserve_tags` | array\<string\> | `[]` | 否 | 命中即保留并跳过该槽位 |
| `level3_recruitment_permit_reserve` | int | `0` | 否 | 3 星自动确认保留的许可数 |
| `recruitment_time` | object | `{3/4/5/6: 540}` | 否 | 各星级期望时限（分钟） |
| `report_to_penguin`/`penguin_id`、`report_to_yituliu`/`yituliu_id`、`server` | — | false/""、false/""、"CN" | 否 | 上报与服务器 |

> 实测坑：`select`/`confirm` **必须是整数数组**，传字符串 tag 名 → `set_params` false → 0。

### 2.5 Infrast（基建，`InfrastTask.cpp:68-282`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `mode` | int | `0` | 否 | `0` Default 自动换班 / `10000` Custom 自定义 / `20000` Rotation 一键轮换 |
| `facility` | array\<string\> | — | **是** | 未运行时 `find<json::array>` 失败 → **返回 false**。设施名见下 |
| `drones` | string | `"_NotUse"` | 否 | 无人机用途（`mode=Custom` 时无效）：`Money`/`SyntheticJade`/`CombatRecord`/`PureGold`/`OriginStone`/`Chip` |
| `threshold` | number | `0.3` | 否 | 心情阈值 [0,1]（Custom 下只对 autofill；Rotation 下无效） |
| `replenish` | bool | `false` | 否 | 贸易站源石碎片自动补货 |
| `dorm_notstationed_enabled` | bool | `false` | 否 | 宿舍"未进驻"选项 |
| `dorm_trust_enabled` | bool | `false` | 否 | 宿舍空位填信赖未满 |
| `fiammetta_recovery_enabled` | bool | `false` | 否 | 菲亚梅塔恢复心情（仅 mode=0） |
| `fiammetta_targets` | array\<string\> | `["清流","可露希尔","但书"]` | 否 | 菲亚梅塔恢复目标（仅 mode=0 且上项 true） |
| `use_pinus_sylvestris`/`use_perception_information`/`use_worldly_plight`/`use_abyssal_hunter` | bool | `false` | 否 | 跨设施组合（仅 mode=0） |
| `reception_message_board`/`reception_clue_exchange`/`reception_send_clue` | bool | `true` | 否 | 会客室：信息板/线索交流/赠送线索 |
| `filename` | string | — | Custom 必填 | `mode=Custom` 未运行时缺失 → **返回 false**；文件不存在/JSON 坏/index 越界 → **返回 false** |
| `plan_index` | int | `0` | Custom | 方案序号 |
| `continue_training` | bool | `false` | 否 | 训练室继续未完成专精 |

- `facility` 取值：`Mfg`/`Trade`/`Power`/`Control`/`Reception`/`Office`/`Dorm`/`Processing`/`Training`/`AssistantChange`。
  元素非字符串 → **返回 false**（`InfrastTask.cpp:170-174`）；未知设施 → **返回 false**（`:182-187`）。

### 2.6 Mall（信用购物，`MallTask.cpp:37-129`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `visit_friends` | bool | `true` | 否 | 访问好友基建 |
| `shopping` | bool | `true` | 否 | 是否购物 |
| `buy_first` | array\<string\> | `[]` | 否 | 优先购买商品名 |
| `blacklist` | array\<string\> | `[]` | 否 | 购物黑名单 |
| `only_buy_discount` | bool | `false` | 否 | 只买折扣（第二轮） |
| `reserve_max_credit` | bool | `false` | 否 | 信用低于 300 停买（第二轮） |
| `force_shopping_if_credit_full` | bool | `false` | 否 | 信用溢出时无视黑名单 |
| `credit_fight` | bool | `false` | 否 | 借助战打 OF-1 攒信用 |
| `formation_index` | int | `0` | 否 | 打 OF-1 的编队（0=当前,1-4） |

- `set_params` 恒返回 true；但 `credit_fight` 开启时 `CreditFightTask::set_params(formation_index)` 失败 → **返回 false**（`MallTask.cpp:124-126`）。`select_formation` 已弃用。

### 2.7 Award（领奖，`AwardTask.cpp:42-62`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `award` | bool | `true` | 否 | 每日/每周任务奖励 |
| `mail` | bool | `false` | 否 | 邮件奖励 |
| `recruit` | bool | `false` | 否 | 限定池每日免费单抽 |
| `orundum` | bool | `false` | 否 | 幸运墙合成玉 |
| `mining` | bool | `false` | 否 | 限时开采许可 |
| `specialaccess` | bool | `false` | 否 | 月卡类奖励 |
| `signinevent` | bool | `false` | 否 | 限时签到活动（横向版） |

- 恒返回 true；`{}` 可用（`award` 默认 true）。→ 无必填项。

### 2.8 SwitchTheme（`SwitchThemeTask.cpp:16-41`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `themes` | array\<string\> | — | **是** | 缺失 → **false**；非数组 → **false**。空数组 = 跳过（返回 true 但不动） |

### 2.9 Roguelike（肉鸽，`RoguelikeTask.cpp:220-307` + `RoguelikeConfig.cpp:6-117`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `theme` | string | `"Phantom"` | 否 | `Phantom`/`Mizuki`/`Sami`/`Sarkaz`/`JieGarden`/`BlackFlow`；未知 → false |
| `mode` | int | `0` | 否 | 0 刷分/1 投资/4 凹开局/5 坍缩(仅Sami)/6 月度/7 深入调查/10001 速通(仅Sarkaz)/20001 常乐(仅JieGarden)/30001 襁褓动物(仅BlackFlow)；与主题不符 → false |
| `squad` | string | `"指挥分队"` | 否 | 开局分队 |
| `roles` | string | `"取长补短"` | 否 | 开局职业组 |
| `core_char` | string | `""` | 否 | 开局干员（中文名，等价 `core_char_list[0]`） |
| `core_char_list` | array\<object\> | — | 否 | `[{"name":...,"use_support":bool}]`，对应第 1/2/3 次招募（以本字段为准） |
| `use_support`/`use_nonfriend_support` | bool | `false` | 否 | 开局助战 / 允许非好友助战 |
| `starts_count` | int | `INT_MAX` | 否 | 开始探索次数 |
| `difficulty` | int | `-1` | 否 | 指定难度，-1 不指定 |
| `stop_at_final_boss` | bool | `false` | 否 | 第 5 层险路恶敌前停（非 Phantom） |
| `investment_enabled` | bool | `true` | 否 | 投资源石锭 |
| `investment_with_more_score` | bool | `false` | 否 | 投资后购物（mode=1） |
| `start_with_elite_two`/`only_start_with_elite_two` | bool | `false` | 否 | 凹精二直升（仅 mode=4；后者需前者 true，否则 **false**） |
| `collectible_mode_shopping` | bool | `false` | 否 | 烧水时购物 |
| `first_floor_foldartal` | string | `""` | 否 | 远见密文板（Sami，非空即启用） |
| `start_foldartal_list` | array\<string\> | — | 否 | 空列表且传了 → **false**（Sami mode=4） |
| `find_playTime_target` | int | — | 否 | JieGarden mode=20001 **必填**且 1~3，否则 **false** |
| 其余 | — | — | 否 | `stop_at_max_level`/`investments_count`/`stop_when_investment_full`/`refresh_trader_with_dice`/`collectible_mode_start_list`/`use_foldartal`/`check_collapsal_paradigms`/`double_check_collapsal_paradigms`/`expected_collapsal_paradigms`/`monthly_squad_*`/`deep_exploration_auto_iterate`/`collectible_mode_squad`/`start_with_seed`/`blackflow_strategy`/`blackflow_cultivation_target` |

- 参数校验细节见 `RoguelikeConfig::verify_and_load_params`；插件级参数由各 `*TaskPlugin::load_params` 处理。

### 2.10 Copilot（自动战斗，`CopilotTask.cpp:59-253`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `filename` | string | — | 二选一 | 单个作业路径（**不导航**，见 §3.4）。与 `copilot_list` 同传时忽略后者 |
| `copilot_list` | array\<object\> | — | 二选一 | `[{"filename":...,"nav_name_override"?:...,"is_raid"?:bool}]`，**每条会导航**；`filename`/`copilot_list` 都没有 → **false** |
| `loop_times` | size_t | `1` | 否 | 循环（仅单作业模式有效） |
| `use_sanity_potion` | bool | `false` | 否 | 理智不足时用理智药 |
| `formation` | bool | `false` | 否 | 自动编队 |
| `formation_index` | int | `0` | 否 | 0=当前编队，1-4=第 N 队（仅 formation） |
| `user_additional` | array\<object\> | — | 否 | `[{"name","skill"}]`，仅 formation+该字段存在 |
| `add_trust` | bool | `false` | 否 | 自动补信赖（仅 formation） |
| `ignore_requirements` | bool | `false` | 否 | 跳过属性/技能要求（仅 formation） |
| `support_unit_usage` | int | `0` | 否 | 0-3 助战模式 |
| `support_unit_name` | string | `""` | 否 | 指定助战（usage=2） |
| `operbox_data_path` | string | `""` | 否 | 干员箱辅助编队；加载失败 → **false** |

- 失败点：`copilot_list` 时可**只允许 set_params 一次**（二次 → `already set params` → **false**，`CopilotTask.cpp:66-69`）；作业文件解析失败 → false；多作业里某关 `set_stage_name` 不支持 → false（`CopilotTask.cpp:156-160, 121-127`）；`is_paradox` 已弃用 → false。

### 2.11 SSSCopilot（保全作业，`SSSCopilotTask.cpp:38-89`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `filename` | string | — | **是** | 缺失 → **false**，JSON 解析失败 → **false** |
| `loop_times` | size_t | `1` | 否 | 循环次数 |

- 运行中 `set_params` → **false**；保全**不支持自动编队**（`m_formation_task_ptr->set_enable(false)`）。

### 2.12 ParadoxCopilot（悖论模拟，`ParadoxCopilotTask.cpp:29-79`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `filename` | string | — | 二选一 | 单作业 |
| `list` | array\<object\>｜array\<string\> | — | 二选一 | 对象含 `id`/`filename`；解析失败 → **false** |

### 2.13 Depot / OperBox（识别，`DepotTask.cpp` / `OperBoxTask.cpp`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `enable` | bool | `true` | 否 | **无其它参数**；`{}` 可用。识别结果经 `SubTaskExtraInfo`（`DepotInfo`/`OperBoxInfo`）回调 |

### 2.14 Reclamation（生息演算，`ReclamationTask.cpp:28-94` + `ReclamationConfig.cpp:5-57`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `theme` | string | `"Tales"` | 否 | `Tales`/`RelaunchAnchor`（`Fire` 已关闭）；未知 → false |
| `mode` | int | `0` | 否 | Tales：0 无存档 / 1 有存档；RelaunchAnchor：16(RA1)/32(RA15)/48(RA4)；不符 → false |
| `tools_to_craft` | array\<string\> | `[]` | 否 | 自动制造物品（Tales mode=1） |
| `clear_store` | bool | `false` | 否 | 完成后清商店（Tales mode=0） |
| `increment_mode` | int | `0` | 否 | 0 连点 / 1 长按（Tales） |
| `num_craft_batches` | int | `16` | 否 | 单次最大制造轮数（Tales） |

### 2.15 Custom（自定义任务，`CustomTask.cpp:21-67`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `task_names` | array\<string\> | — | **是** | 缺失 → **false**；元素非 string → **false**；任务名在 tasks 资源里找不到 → **false** |
| `params` | object | — | 否 | 仅特定任务用：`pixel_paint.*`、`auto_raise_potential.use_normal_token`、`event_shop.blacklist` |

- 用法：跑 tasks.json 里**任意**任务（绕过 Interface 白名单）。如翻页：`{"task_names":["SlowlySwipeToTheLeft"]}`。
- 活动商店兑换：`task_names:["SS@Store@Begin"]` + `params.event_shop.blacklist`（可为空则 false）。

### 2.16 SingleStep（`SingleStepTask.cpp:14-78`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `type` | string | `""` | 是 | 仅 `"copilot"` |
| `subtype` | string | `""` | 是 | `stage`（需 `details.stage_name`）/ `start` / `action`（需单个 action） |
| `details` | object | — | 视 subtype | 非法/缺失 → **false** |

### 2.17 VideoRecognition（`VideoRecognitionTask.cpp:14-39`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `filename` | string | — | **是** | 缺失/路径设置失败 → **false**；运行中 → **false** |

### 2.18 OperProgress（`OperProgressTask.cpp:87-132`）

| 参数 | 类型 | 默认 | 必填 | 备注 |
|---|---|---|---|---|
| `plans` | array\<object\> | — | **是** | 每项 `{role?, name, elite?, skill_level?, skill_mastery?}` |

- 校验：`name` 非空；`elite` ∈ {1,2}（**不能填 0**）；`skill_level` ∈ [2,7]；`skill_mastery` 三项 ∈ [0,3]；key 只允许 `role/name/elite/skill_level/skill_mastery`（多一个 key → **false**）；`role` 不明且多义 → **false**；装置/召唤物 → false；运行中 → false。

> **release 版本界**：`OperProgress` 字符串在 **6.19.0** 的 `MaaCore.dll` 出现 92 次、在 **6.18.0**（`C:\MAA\.old`）出现 **0** 次
> ⇒ **6.19.0 才真正可用**（dev-v2 源码里早有，但 6.18 release 没有）。`skill_mastery` 是**长度 3 的 int 数组**（1/2/3 技能各自的专精等级）。
> 结果码：`AlreadySatisfied`/`OperatorNotFound`/`PrerequisiteNotMet`/`RecognitionFailed`/`ResourceInsufficient`/`TrainingRoomBusy`/`ChipNotCraftable`/`FormulaLocked`/`Completed`/`Unsupported`。
> **不支持 Drone**（装置/召唤物无专精）；**培养目标不含等级 Lv**（无 `level` 字段），等级段仍要自己排。

### 2.19 Debug（`DebugTask`，仅 `ASST_DEBUG`）

- 编译期开关；release 不含。类型字符串 `"Debug"`。

### 2.20 DepotMaintain 库存保持（**GUI 组装层，不是 Core 任务**）

- **不是** `AsstAppendTask` 的任务类型：`DepotMaintain` 字符串在 6.19.0 `MaaCore.dll` 出现 **0** 次，只在 GUI `MAA.dll` 里。
- GUI 组装方式（`src/MaaWpfGui/ViewModels/UserControl/TaskQueue/DepotMaintainTaskUserControlModel.cs`）：
  先跑 `Depot`（仓库识别）→ 对每个 `Plan(stage, drop_id, drop_count)` 生成 `AsstFightTask{stage, drops:{drop_id:drop_count}}`
  → 靠 **Fight 的 `drops`「任一达标即停」** 收尾（见 §2.3）。
- 6.19.0 新增：预设「当前活动」（一键导入当期活动关卡掉落为目标）、`SortByProgress`（按库存达成率升序、缺口最大的计划先拿理智）。
- 其他字段（`DepotMaintainTask.cs`）：`UpdateDepot`、`SkipDuringActivity`、`SkipDuringResourceCollection`、
  `OnlyFirstInsufficientPlan`（只下发第一个不足且当日可执行的计划）、`UseAutoSeries`（AUTO 倍率）、`UseMedicine`、`UseStone`、
  `UseExpiringMedicine` + `ExpiringMedicineDays=2`（**临期药固定 2 天阈值**）。
- ⇒ 我们**不需要**用它：`plan_week` + `Fight.drops` 是同一底层语义且表达力更强（见 `MAA-6.19-融合评估.md` §2.3）。

### 2.21 AutoRaisePotential / event_shop（6.19.0 起可用）

- `AutoRaisePotential`（自动提升潜能）：走 `Custom` 任务，`params.auto_raise_potential.use_normal_token`（见 §2.15）。
- `params.event_shop.blacklist`（活动商店黑名单，`Custom` + `task_names:["SS@Store@Begin"]`）：
  `event_shop` 字符串在 **6.19.0** 出现 1 次、**6.18.0** 出现 **0** 次 — 见 [`FINDINGS.md`](FINDINGS.md) §19/§21。

---

## 3. 关卡导航机制（Fight / Copilot）

### 3.1 Fight 的 stage 分流（`FightTask.cpp:124-168`）

1. `stage == ""`（且未运行）→ 子任务切 `{ "LastOrCurBattleBegin" }`，`GoLastBattle` 限次 `INT_MAX`：**点"上次/当前作战"→ 代理指挥重放**。不导航到具体关。
2. `stage` 以 `SSReopen-` 开头且**总长 11**（前缀恰好 2 字符，如 `SSReopen-IC`）→ 走 `SideStoryReopenTask`：一次性刷 `XX-1..XX-9`（`SideStoryReopenTask.cpp:70` 强校验前缀长=2；`_run` 从第 1 关起按序打，遇"代不了/没有"即收尾）。导航名用 `<前缀>-OpenOpt`。
3. 其余 → `StageNavigationTask::set_stage_name(stage)`，失败 → **返回 false**（日志 `Cannot set stage`）。

### 3.2 `StageNavigationTask::set_stage_name`（`Task/Fight/StageNavigationTask.cpp:43-139`）

1. **先查 `Task.get(stage_name)`**：资源里定义了同名任务 → `directly` 模式，直接按该任务导航。
2. 否则用正则 `^([A-Za-z]{0,3})(\d{1,2})-(\d{1,2})(?:-?(\w+))*$` 匹配主线关（`10-1`、`JT8-2`、`H10-1-Hard`…）；
   取 `chapter` 拼 `Episode<chapter>` 任务，**不存在 → 返回 false**。
3. 难度后缀：第 10-14 章 `-NORMAL`/`-HARD`（赛前切）；第 15+ 章对应常规/险地（赛后切）；其它章带难度 → false。
4. `_run`（`:141-169`）：先试 `LastBattleStageName` 快路径（上次作战名 == 目标关就直接点，**资源关复刷很快**）；否则 `directly` 或
   `chapter_wayfinding → swipe_and_find_stage → switch_difficulty`。找关优先**模板匹配**（`StageNavigationHelper` 有模板时），否则 **OCR 关卡代号**并点击、找不到就 `SlowlySwipe`。

> **结论修正**：`set_stage_name` 并非"只认主线关"——它**优先认资源里定义了任务名的关卡**（主线各章、`Stages/Supplies.json` 的
> `CE-5/6`、`LS-5/6`、`CA-5`、`AP-5`、`SK-5`、`PR-A/B/C/D-1/2`、`Annihilation` 与各剿灭变体、`Stages/OF.json` 的 `OF-1/OF-F3`、
> 当期活动 `Stages/YW.json` 的 `YW-4/6/7/8` 等），**再**用正则兜底主线。没有任务定义的活动关（如 YW-1..3）→ 导航会失败。

### 3.3 各 stage 任务来自哪

- `resource/tasks/tasks.json`：核型流水线 + 各章 `Episode0..17` + `Stage<code>` OCR 节点（例：`"1-7"` 定义在 `tasks.json:463`，其 `sub:["Episode1"]`、`next:["Stage1-7", ...]`）。
- `resource/tasks/Stages/Supplies.json`：物资/芯片本（`CE-6`、`LS-6`、`CA-5`、`AP-5`、`SK-5`、`PR-*-*`）。
- `resource/tasks/Stages/<前缀>.json`：活动/别传关卡（`YW.json`、`OF.json`…）。**只放当期需要的关**（当前活动放"后三关 + 个别"）。
- `resource/tasks/Stages/base.json`：通用片段（`SS-Open`、`SS-OpenOcr`、`SS@Store@*` 活动商店流水线）。

### 3.4 Copilot 的 `filename` vs `copilot_list`

| 模式 | 参数 | 是否导航 | 说明 |
|---|---|---|---|
| 单作业 | `filename` | **否** | `m_multi_copilot_plugin` 被禁用（`CopilotTask.cpp:103`），子任务第 2 个直接找 `BattleStartPre`（=**必须已站在关卡准备界面**）。`loop_times` 有效 |
| 多作业 | `copilot_list` | **是** | 启用 `MultiCopilotTaskPlugin`，每条作业执行 `navigate_to_stage(nav_name)` |

`navigate_to_stage`（`Task/Miscellaneous/MultiCopilotTaskPlugin.cpp:76-166`）：有 `StageNavigation` 模板 → 模板匹配；否则
**HSV 掩膜 + OCR** 找关卡代号（`nav_name`，缺省取 `overview.json` 里该关的 `code`，如 `YW-5`）并点击，找不到就
`Copilot@StageNavigationSlowlySwipeLeft` 翻页，最后兜底 `Copilot@ChapterSwipeToTheRightAndPlot`。⇒ **游戏必须先停在目标活动的关卡列表页**。

---

## 4. 资源结构：谁读、怎么更新

加载入口 `ResourceLoader::load`（`src/MaaCore/Config/ResourceLoader.cpp`）。release 资源根 = `C:\MAA\resource`。

| 资源 | 消费者（源码） | 作用 |
|---|---|---|
| `tasks/*.json`（含 `tasks.json`、`Stages/*.json`、`Roguelike/*.json`、`RA/*.json`、`UiTheme/*.json`、`MiniGame/*.json`、`Copilot/*.json`、`hotfix/*.json`） | `TaskData`（`ResourceLoader.cpp:172-185`） | 任务流水线定义（`ProcessTask` 执行）。**`resource/tasks.json` 旧布局已弃用**（`:176-179`），改用 `tasks/*.json` |
| `template/**/*.png` | `TaskData` / `Matcher`（`:172`、`:188`） | 模板匹配图库（递归搜索）。活动关模板在 `template/StageNavigation/...` |
| `item_index.json` | `ItemConfig`（`:189`） | 物品 id ↔ 名称（掉落识别用） |
| `stages.json` | `StageDropsConfig`（`:190`） | 关卡列表与掉落池（`apCost`/`code`/`dropInfos`…） |
| `Arknights-Tile-Pos/overview.json` + 每关 `*.json` | `TilePack`（`:191`） | 地图格点/坐标；Copilot 导航取 `code`，自动战斗摆位用 |
| `battle_data.json` | `BattleDataConfig`（`:162`） | 干员/技能/敌人数据 |
| `recruitment.json` | `RecruitConfig`（`:161`） | 公招 Tag 与组合 |
| `infrast.json` | 基建技能/效率 | 基建排班数据 |
| `ocr_config.json` | `OcrConfig`（`:163`） | OCR 参数 |
| `onnx/`、`PaddleOCR/`、`PaddleCharOCR/` | OCR 模型（`:148-155`） | 文字/字符识别模型 |
| `roguelike/`、`RA/` 相关 config | 各 `*Config`（`:207-367`） | 肉鸽/生息演算 招募/购物/地图等 |
| `global/<client>/resource/**` | 按客户端覆盖 | 外服差异（`txwy`/`YoStarEN`/`YoStarJP`/`YoStarKR`） |
| `platform_diff/<platform>/resource/**` | 按平台覆盖 | `iOS`/`PC` 差异 |
| `version.json` | 资源版本/当期活动信息 | `{activity, gacha, last_updated}`——判"资源是否认识当前活动"的旁证 |
| `config.json` | `GeneralConfig`（`:160`） | 全局参数（`taskDelay`、上报 URL 等） |

**加载/更新方式**

1. `Asst.load(path, incremental_path=None, user_dir=None)`：`path` = 主资源目录，`incremental_path` = 增量资源目录（后加载覆盖前加载，多文件任务规则见 `docs/zh-cn/protocol/task-schema.md`）。
2. **动态部分靠 MaaResource 仓库**：MaaResource 只放"与 Core 版本无关、需动态更新"的文件（新活动地图、任务数据等），README 明说。
3. GUI 的在线更新走 OTA（`api.maa.plus` / `ota.maa.plus`）；**本机 `ota.maa.plus` 不可达**（见 `FINDINGS.md` §14），所以补资源走 **GitHub `MaaResource`**（`scripts/event-copilot/` 的 `sync` 子命令已封装：拉 `Arknights-Tile-Pos/overview.json` 与对应活动 `*.json`）。
4. 改完资源后，**运行中的 MaaCore 实例仍用旧内存缓存**，需重启该实例（MCP 重启）。

---

## 5. `AsstMsg` 回调码全表（`Common/AsstMsg.h:11-34`）

| 码 | 名称 | 含义 | details 关键字段 |
|---|---|---|---|
| 0 | `InternalError` | 内部错误 | 空 |
| 1 | `InitFailed` | 初始化失败 | `what`/`why`/`details` |
| 2 | `ConnectionInfo` | 连接相关 | `what`/`why`/`uuid`/`details`（`what` 如 `Connected`/`Reconnected`/`ResolutionChanged`…） |
| 3 | `AllTasksCompleted` | 全部任务完成 | `taskchain`/`taskid`/`finished_tasks` |
| 4 | `AsyncCallInfo` | 外部异步调用信息 | `what`/`async_call_id`/`details{ret,cost,error}` |
| 5 | `Destroyed` | 实例已销毁 | — |
| 10000 | `TaskChainError` | 任务链执行/识别错误 | `taskchain`/`taskid`；异常中断时 `details.error`（`OpenCVException`/`OutOfMemory`/`UnhandledException`/`UnknownException`） |
| 10001 | `TaskChainStart` | 任务链开始 | `taskchain`/`taskid` |
| 10002 | `TaskChainCompleted` | 任务链完成 | 同上 |
| 10003 | `TaskChainExtraInfo` | 任务链额外信息 | 同上（如肉鸽 `RoutingRestart`） |
| 10004 | `TaskChainStopped` | 任务链手动停止 | 同上 |
| 20000 | `SubTaskError` | 原子任务错误 | `subtask`/`class`/`taskchain`/`details` |
| 20001 | `SubTaskStart` | 原子任务开始 | 同上 |
| 20002 | `SubTaskCompleted` | 原子任务完成 | 同上 |
| 20003 | `SubTaskExtraInfo` | 原子任务额外信息 | `what`+`details`（见下） |
| 20004 | `SubTaskStopped` | 原子任务停止 | 同上 |
| 30000 | `ReportRequest` | 上报请求（交给 UI 发 HTTP） | `url`/`headers`/`body`/`subtask` |

**我们（MCP / 自动化）该重点关注**：

- `10000 TaskChainError` / `10002 TaskChainCompleted` **（判任务成败）**：`errors` 非空 = 失败（我们的 `_collect` 就是把 10000 收进 `errors`）。
- `10003 TaskChainExtraInfo` / `20003 SubTaskExtraInfo`：结构化结果——
  `StageDrops`（掉落/三星）、`RecruitResult`/`RecruitTagsDetected`、`DepotInfo`（仓库）、`OperBoxInfo`（干员箱）、`StageInfo`。
- `20000 SubTaskError`：抄作业常见 `OperatorMissing`（编队缺人，`details` 带干员与 `reason`）。
- `2 ConnectionInfo`：`what`=`ResolutionChanged` / `Reconnected` 等连接态（MaaCore 会在 `ResolutionChanged` 时自动 stop）。
- `3 AllTasksCompleted`：整批任务结束（`finished_tasks`）。

> `TaskChainError` 的 `details.error` 只在**异常中断**时给出；普通"没识别到/失败"只有 `taskchain` 字段。判三星看 `StageDrops.stars`。

---

## 6. 可执行配方（给 `ark_run_task(type, params)` 的 JSON）

> 我们的 `TASK_DEFAULTS` 会先合并默认值（见 §8），下面写的是**建议显式传入**的参数。`enable` 恒可省（默认 true）。

### 6.1 日常

```json
// 启动游戏 + 唤醒
["StartUp", {"client_type": "Official", "start_game_enabled": true}]

// 领奖（先跑任务再领，见 docs/DAILY-CHECKLIST-* 的顺序铁律）
["Award",   {"award": true, "mail": true, "orundum": false}]

// 信用点 + 购物
["Mall",    {"visit_friends": true, "shopping": true, "buy_first": ["招聘许可", "龙门币"]}]

// 公招（select/confirm 必须整数数组！）
["Recruit", {"select": [3, 4, 5, 6], "confirm": [3, 4, 5, 6], "times": 4}]
```
> `Award`/`Mall` 的 `{}` 也可用（`award`/`visit_friends`/`shopping` 默认 true）。

### 6.2 刷主线 / 资源关

```json
["Fight", {"stage": "1-7",  "times": 38, "medicine": 0, "stone": 0, "series": 1}]
["Fight", {"stage": "CE-6", "times": 5,  "series": 3}]          // series 0=自动最大倍率
["Fight", {"stage": "",     "times": 5}]                        // 上次/当前作战重放（代理指挥）
```
> `stage` 仅支持资源里定义了任务名的关（见 §3.3）：主线、`CE-5/6`、`LS-5/6`、`CA-5`、`AP-5`、`SK-5`、`PR-*-*`、剿灭等。

### 6.3 刷活动关（≥2 种方案）

**方案 A：Copilot 抄作业（推荐，能自动编队 + 逐关导航）**
```json
["Copilot", {
  "copilot_list": [
    {"filename": "C:\\path\\to\\YW-6.json", "nav_name_override": null, "is_raid": false}
  ],
  "formation": true, "formation_index": 4, "add_trust": false,
  "ignore_requirements": false, "support_unit_usage": 0
}]
```
> 前置：游戏停在活动关卡列表页；作业 JSON 必须含非空 `actions`；`copilot_list` 只能 set_params 一次。

**方案 B：上次作战重放（最省事，代理指挥）**
```json
["Fight", {"stage": "", "times": 8}]
```
> 先在游戏里手动把目标关打到"开始行动"页（或打过一次），MAA 点"上次作战"直接重放；**不导航**，稳但需人工就位。

**方案 C：活动关直导航（当资源已定义该关任务时）**
```json
["Fight", {"stage": "YW-6", "times": 8}]
```
> 仅当 `resource/tasks/Stages/YW.json`（或对应活动文件）定义了该关、且游戏在活动关卡列表页时可用；未定义的关（如 YW-1..3）会 `Cannot set stage` → append 0。

**方案 D：复刻活动一键刷 XX-1..XX-9**
```json
["Fight", {"stage": "SSReopen-IC", "times": 1}]
```
> 前缀必须**恰好 2 字符**（总长 11）；一次性把该活动 1..9 关依次打完。

### 6.4 基建（**只收菜/无人机、不想换班**）

- 现状：MAA **没有**"只收菜/只无人机"的专用开关。`mode` 只三选一（`0/10000/20000`）。
- 最接近的做法 = **`mode=20000` 一键轮换**（会跳过 控制中枢/发电站/宿舍/办公室；Mfg/Trade/Reception **不换班**但保留基本操作如无人机、会客室逻辑）：
```json
["Infrast", {"enable": true, "mode": 20000,
             "facility": ["Mfg", "Trade", "Reception"],
             "drones": "PureGold"}]
```
> 注意：20000 仍会跑会客室线索逻辑；`drones` 可选 `PureGold`/`SyntheticJade`/`CombatRecord`/`Money`/`OriginStone`/`Chip`/`_NotUse`。
- 若确实要"连会客室都不动"，只能走 `mode=Custom(10000)` + 自写配置（把各房间 `skip:true`，只留想要的无人机动作）——**未实机确认**，建议实测。
- 我们当前的 `TASK_DEFAULTS["Infrast"]={"enable":True}` **不够**：`{}` 会因缺 `facility` → append 0（§7）。

### 6.5 识别

```json
["Depot",   {}]   // 仓库：SubTaskExtraInfo.DepotInfo -> {itemId: qty}
["OperBox", {}]   // 干员箱：SubTaskExtraInfo.OperBoxInfo -> all_opers/own_opers
```

---

## 7. `append_task` 返回 0 的原因与排查

按 `Assistant.cpp:303-369` 与各 `set_params`，返回 0 的**全部常见原因**：

1. **未知 `type`**：不在 §2 白名单 → 日志 `invalid type`。例：`append_task("SlowlySwipeToTheUp")` 必 0。
2. **params 不是合法 JSON**：`json::parse` 失败 → 0（`Assistant.cpp:307-311`）。
3. **`set_params` 返回 false**（逐个任务，见 §2 备注），典型：
   - `StartUp`：`client_type` 空/invalid（`get_package_name` 查不到）。
   - `Infrast`：缺 `facility`；或 `facility` 含非字符串/未知设施；`mode=Custom` 缺 `filename`/文件坏。
   - `Recruit`：缺 `select`/`confirm`，或其中含非整数。
   - `Fight`：`medicine_expire_days<0`；`series` 越界；`stage` 无法导航（`Cannot set stage`）。
   - `Copilot`：缺 `filename` 且缺 `copilot_list`；作业解析失败；`copilot_list` 二次 set_params；`operbox_data_path` 坏。
   - `SSSCopilot`/`VideoRecognition`：缺 `filename`；运行中再 set。
   - `Custom`：缺 `task_names`/元素非串/任务名不存在。
   - `Roguelike`/`Reclamation`：theme/mode 组合非法；`find_playTime_target` 缺或越界；`only_start_with_elite_two` 未配 `start_with_elite_two`。
4. **（Python 侧）** `json.dumps` 序列化失败 / 传了非 dict 的 `params`——但绑定会把 `params` dump 成字符串，Core 侧仍按 1~3 判。

**排查法**：

1. 立刻读日志：**`<user_dir>/debug/asst.log`**。MaaCore 会把每条 `AsstAppendTask`、`set_params failed/invalid params`、`Cannot set stage`、`Not support stage`、`CopilotConfig parse failed` 写进去。
   - 我们 MCP 未传 `user_dir`（`Asst.load(path=...)` 只给主资源目录），日志落在**进程 cwd 的 `debug/asst.log`**（AGENTS 里记的 `%TEMP%` 是 MCP 自己的日志，不是 MaaCore 的）。
2. 对照本表 §2 核对**必填**字段与类型（尤其 `select/confirm` 是整数数组、`client_type` 不能空）。
3. 关卡导航类失败：确认该关在 `resource/tasks/`（含 `Stages/*.json`）里**有任务定义**；活动新关需先 `sync` 补资源并**重启实例**。
4. 抄作业失败：确认作业含 `actions`（用 `https://prts.maa.plus/copilot/get/<id>` 取完整版）、`stage` 被支持、游戏停在正确的关卡列表页。

---

## 8. 对 `arknights_mcp.py` `TASK_DEFAULTS` 的改进建议

现状（`arknights_mcp.py:312-318`）：
```python
TASK_DEFAULTS = {
    "Recruit": {"select": [3,4,5,6], "confirm": [3,4,5,6], "times": 4},
    "StartUp": {"enable": True, "client_type": "Official"},
    "Infrast": {"enable": True},
    "Depot":   {"enable": True},
    "OperBox": {"enable": True},
}
```

建议（**仅文档建议，未改代码**）：

1. **修正代码注释**（`arknights_mcp.py:310-311`）：现在写"StartUp/Infrast/Recruit 需要 enable"**不准确**。按源码：
   `StartUp` 需要 **`client_type`**（非空且合法）；`Infrast` 需要 **`facility`**；`Recruit` 需要 **`select`/`confirm` 整数数组**。
   `enable` 由 Core 默认 `true`，并非它们返回 0 的原因。
2. **`Infrast` 默认值补齐**：`{"enable": True}` 下 `{}` 必 0。建议给一个安全默认，如
   `{"enable": True, "mode": 0, "facility": ["Mfg","Trade","Power","Reception","Office","Dorm","Processing","Training","Control"]}`；
   若走"只收菜/不换班"取向，另留 `mode=20000` 配方（见 §6.4）。**前提**：我们的基建已改由 **MAA 自带的「队列轮换」**（`Infrast` `mode=20000`）承担——MAA 进基建 → 当前班有人心情 0 → 点游戏内「一键轮换」→ 各设施收菜（Rotation 下 MAA 不换干员、不由 MAA 自动排班），所以默认值取 `mode=20000`（不触发 MAA 自动换班）。
3. **`Recruit` 默认 `confirm` 建议改 `[]`**：默认 `[3,4,5,6]` 会**自动确认**高星（真消耗许可/加急），对"只想看能不能出"的场景有副作用；若确实自动公招，可保留，但建议在注释里写明"会真实招募"。
4. **`StartUp` 补 `start_game_enabled`**：当前默认不含该项（默认 false），需要自动开游戏时调用方还要手动传。可考虑默认 `{"client_type":"Official","start_game_enabled":True}`（与我们 `ark_operbox` 内部一致）。
5. **`Fight` 建议加最小默认**（可选）：如 `{"medicine":0, "stone":0, "series":1}`，避免调用方漏传导致 `series` 语义不明；但 `stage` 必须调用方给，别设默认。
6. **`ark_list_tasks` 的扫描范围**（`arknights_mcp.py:35,296-305`）只读 `resource/tasks/tasks.json`，**漏掉** `resource/tasks/Stages/*.json`、`Roguelike/*.json`、`MiniGame/*.json` 等子目录任务。
   建议改为递归扫描 `resource/tasks/**/*.json`（并兼容 `tasks.json` 与拆分文件两种布局）。注意它现在用正则粗解析、且注释提到"大小写重复键"，直接 `json.load` 可能失败——递归扫描时仍需容错。
7. **可选**：为 `Copilot` 预置 `{"formation_index": 4, "add_trust": false}`（只写第四编队，符合本仓库约定），减少调用方遗漏。

---

> 备注：本文件基于 dev-v2 源码与本地资源整理；若 MaaCore 升版，请优先回看
> `src/MaaCore/Task/Interface/*.cpp` 的 `set_params`、`Assistant.cpp` 的注册分支、`StageNavigationTask.cpp`、
> `MultiCopilotTaskPlugin.cpp`，以及 `docs/zh-cn/protocol/integration.md`。
