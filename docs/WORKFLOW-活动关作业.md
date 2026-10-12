# 工作流：用 MAA 打「当期活动关」（抄作业自动化）

> 定位：和 `scheduling/`（基建排班）并列的另一条固化流程。
> 一句话：**抓作业站(prts.maa.plus)的作业 → 比对本人干员箱 → MAA 多作业自动战斗逐关通关**。
> 首次跑通：2026-10-09，当期活动 `act52side`（「昨日海 / YW」，雷亚-伊比利亚）。

---

## 0. 一句话现状

MAA **能**自动打活动关，但前提是三件事都做对：
1. MAA 本地资源**认识该活动**（否则 `Not support stage`）；
2. 作业 JSON 带**非空 `actions`**（列表接口取到的 content 不带）；
3. 用**多作业模式 `copilot_list`**（单作业 `filename` 模式**不做关卡导航**），且游戏停在**活动关卡列表**。

---

## 1. 依赖与环境

| 项 | 值 |
|---|---|
| MaaCore | `C:\MAA`（本机 v6.19.0，Python 绑 `C:\MAA\Python`） |
| 作业站 API | `https://prts.maa.plus`（国内可达；`ota.maa.plus` 本机不可达，资源更新走 GitHub） |
| 资源源 | `https://raw.githubusercontent.com/MaaAssistantArknights/MaaResource/main/resource` |
| 干员箱 | `C:\MAA\data\OperBoxData.json`（MAA GUI 识别产出；仅 own/elite/level/potential，**无技能等级**） |
| 设备 | 雷电 `127.0.0.1:5555`，adb `C:\leidian\LDPlayer9\adb.exe` |

**单客户端纪律**：同一时刻只让一个程序驱动设备。跑脚本前**先关 MAA GUI / 其它 arknights MCP**，否则 MaaTouch 抢占、连接错乱（AGENTS.md 铁律）。

---

## 2. 脚本

`scripts/event-copilot/event_copilot.py`

```
python event_copilot.py events                         # 列出已知 side story 活动(actNNside)与关卡代号
python event_copilot.py sync  act52side                # 补齐 MAA 资源(overview.json + 该活动 Tile-Pos)
python event_copilot.py plan  act52side [--top N]      # 抓作业+比对干员箱，打印每关推荐与候选
python event_copilot.py goto                           # (可选)简易导航到活动关卡列表
python event_copilot.py run   act52side --stages 5,6,7,8   # 执行(单关失败逐候选换，失败退理智代价低)
python event_copilot.py run   act52side --all --try
python event_copilot.py run   act52side --stages 8 --loop 30   # 刷代币：同一关重复 30 次
python event_copilot.py run   act52side --chain ex --try         # ★EX 首通解锁链（依次解锁、遇挫即停）
python event_copilot.py run   act52side --chain raid --try       # ★EX 突袭链（需该关普通已通）
python event_copilot.py run   act52side --stages 1,2 --raid      # 打指定关的突袭（is_raid=true）
```

- 可选环境变量覆盖：`ARK_MAA_PATH` / `ARK_ADB` / `ARK_ADDR` / `ARK_TOUCH` / `ARK_FORMATION_INDEX`。
- **编队**：`run` 默认 `formation_index=4` —— **自动编队只会写「第四编队」**，绝不碰其它编队（默认约定）。要改用 `--formation N`。
- `plan` 的排序键：`(未拥有干员数, 无可用成员的组数, 低练(E<2)干员数, 低练组数, -热度)` —— 越靠前越"能凑齐"。
- **准入（用户铁律）**：只有 `score == (0,0,0,0)`（全员/组都 E2+）的候选才算"**可抄**"；其余一律跳过。
  干员箱以**森空岛在线**为准（见坑 4）。
- 选关时游戏**必须停在活动地图(关卡列表)**；`run` 里 MAA 用 OCR 找关卡代号（如 `YW-5`）并点击，找不到会左右翻页。

---

## 2bis. EX/S 解锁链与突袭（`--chain`，2026-10-12 用户口径）

**依赖语义**：活动 **只有 EX / S 关有突袭**（普通关 YW-1..8 没有）；EX-i **未通就打不了 EX-(i+1)**
（依次解锁）；突袭依赖「**该关普通已通**」。

`run <event> --chain <kind>` 据此执行：

| kind | 含义 |
|---|---|
| `ex` | EX 普通首通链（EX-1→EX-8，**只打未通的、从第一个未通起**） |
| `raid` | EX 突袭链（仅「该关普通已通」的关；按关顺序） |
| `s` / `sraid` | S 关普通 / 突袭，同理 |

规则：
1. **只排未通**：读 `docs/state.json.progress.event_<活动>`，已通的关不再打（省理智）；
2. **遇挫即停**：某关**没有可抄作业**（或不在 MAA 资源）/ 执行失败 → **不再打后面的关**（后面本来没解锁），
   日志明确写「卡在 EX-k」并给手点提示；
3. `--try` 保留（该关逐候选重试）；链模式下「该关所有候选都失败」= 链停；
4. **跑完/失败都回写** `docs/state.json.progress.event_act52side`。

**突袭机制**：MAA 活动突袭只能走 Copilot（`copilot_list` 条目带 `is_raid: true`；MAA `Fight` 不支持），
见 `MAA-INTERNALS.md` §2.10。本脚本把 `is_raid` 传进作业条目。

**`progress.event_act52side` 字段约定**（`--chain` 会写）：

| 字段 | 含义 |
|---|---|
| `first_clear_done` | 故事关（YW-1..8）已通代号，如 `["YW-8","YW-5(2星)"]`（脏后缀容错，只取代号前缀） |
| `ex_clear_done` / `s_clear_done` | EX / S **普通**已通代号（本工作流新增） |
| `raid_clear_done` | **突袭**已通代号（EX/S 共用；本工作流新增） |
| `ex_pending` / `raid_pending` | 未通计数（由上面列表 + `event_<id>.json` 的关卡总数算出） |
| `last_chain_note` | 最近一次 `--chain` 的结果串（本工作流新增），如 `EX突袭链：成功[YW-EX-1]；卡在 YW-EX-2（该关普通未通）` |

> 字段缺失/格式意外时，计划层（`plan_week`）与链执行层都**当全未通**（宁可多排一次首通，也别漏排）。
> 规划侧对应规则见 `docs/STATE-一键长草.md` 的 R2.5 / R2.6。

---

## 3. 工作流步骤（照做即可）

1. **开模拟器 + 游戏**，进到**该活动的关卡列表页**（能看到 YW-1…YW-N 的地图）。
2. 确认 MAA **空闲**、无其它客户端在连设备。
3. `events` 找活动 id（当期是 `act52side`）。
4. `sync <活动>`：若 MAA 报 `Not support stage`，就是缺资源 —— 脚本会从 GitHub 拉最新 `overview.json`（备份旧的）并补下载该活动的 `Arknights-Tile-Pos\*.json`。
5. `plan <活动>` 看每关推荐作业；确认没有需要"借 2 个以上干员"的关。
6. `run <活动> --stages ... --try` 执行。跑完看游戏结算（三星/通关）。
7. 记录结果；失败关可换候选重跑（失败退理智，不亏）。

### 3bis. 导航层（首页 → 活动关卡列表）—— 归 MCP/Agent，不在脚本里

MAA Copilot **只从"活动关卡列表页"往后接管**，它自己**不会从首页走进活动**（见坑 3）。这一步由**上层的 MCP/Agent** 用「视觉原语」完成：

```
ark_where()                      # 判当前在哪一屏（MAA 模板锚点）
  -> 不在主界面？ark_key BACK 逐级退回，直到 ark_where 命中「终端」
ark_find(<活动 banner 模板>) / OCR  # 主界面右侧的当期活动 banner（新活动无模板则用坐标/OCR）
  -> ark_tap(...)                # 进入活动主页
ark_tap(<活动主页的"关卡/地图"入口>)  # 如本轮「雷亚-伊比利亚」节点
  -> 停在 YW-N 关卡列表
ark_run_task("Copilot", {copilot_list:[...], formation:true, ignore_requirements:true})
```

- 为什么放上层：入口**因活动而异**（banner 位置、活动主页节点名），且需要"看"当前画面；这是 Agent 擅长、脚本不擅长的。
- 约束：尽量用 MAA 能做的件；**避免 adb 滑动**（本机 adb swipe 失效），翻页交给 MAA Copilot 的 MaaTouch。`ark_tap` 一般可用。
- 也可**人工**把游戏点到活动关卡列表，再跑 `run`（脚本对这点是"假设已就位"）。

> 相关 MCP 工具：`ark_where`（页面识别）、`ark_find`（模板匹配）、`ark_tap` / `ark_swipe` / `ark_key`、`ark_screenshot`。

---

## 4. 关键坑（**都踩过，务必记住**）

### 坑 1：MAA 旧资源不认识新活动 → `Not support stage`
- 症状：`ark_run_task("Copilot", {...})` 返回 `id=0`；MaaCore 日志 `BattleProcessTask::set_stage_name` → **`UnsupportedLevel`** / `Not support stage`。
- 根因：Copilot 的 `BattleProcessTask::set_stage_name` 会校验关卡是否在 `resource/Arknights-Tile-Pos/overview.json` 索引里；MAA 资源只随 OTA 更新，`ota.maa.plus` 本机不可达（curl 返回 000），资源停在旧版本。
- 修复：从 **GitHub `MaaResource`** 拉 `Arknights-Tile-Pos/overview.json`（整体替换，含新活动条目）**并**补齐该活动的 `actNNside_XX-activities-....json`。`sync` 子命令已封装。
- 注意：改完资源后，**已在运行的 MCP/MAA 实例仍用旧缓存**，要重启该实例（本轮重启了 arknights MCP 进程）。

### 坑 2：作业 JSON 必须带非空 `actions`
- 症状：MaaCore 日志 `CopilotConfig parse failed` / `Json parse failed ... invalid map<K,T> key`；`append_task` 返回 0。
- 根因：`/copilot/query` 列表接口返回的 `content` 字段**不含 `actions`（部署轴）**；MAA 需要 `actions`。
- 修复：用 **`https://prts.maa.plus/copilot/get/<id>`** 取完整作业（含 `actions`），跳过 `actions` 为空的作业。脚本 `candidates_for` 已处理。

### 坑 3：单作业 `filename` 模式**不导航**（最关键）
- 读 MAA 源码（`Interface/CopilotTask.cpp`）：`filename` 模式的 8 个子任务里**没有关卡导航**，第 2 个就直接找 `BattleStartPre`。它是"你已经站在关卡准备界面"才能用。
- 导航只在**多作业**路径：`params["copilot_list"] = [{"id":0,"filename":...,"nav_name_override":可空,"is_raid":false}]`，由 `MultiCopilotTaskPlugin` 实现（`_run` → `navigate_to_stage`）。
- 导航原理：优先用 `StageNavigation` 模板；无模板则**图像分析+OCR** 找关卡代号（`nav_name`，缺省取 overview 里的 `code`，如 `YW-5`）并点击；找不到就 `Copilot@StageNavigationSlowlySwipeLeft` 翻页。
- 所以 `run` 里游戏**必须停在活动关卡列表**，否则 OCR 找不到、导航失败。

### 坑 4：练度/技能不够 → 自动编队 `Unavailable`/`Missing`；**用户口径：练度不齐的作业一律不抄**
- 症状：`BattleFormationTask` 报 `why=OperatorMissing`，细节如 `{"奶盾":[{"name":"塞雷娅","reason":"Unavailable"}]}`。
- 根因：`check_oper_level()` / 技能检查不通过 → `OperStatus::Unavailable`；名字不在名单 → `Missing`。
- **口径（2026-10-10 用户铁律）**：**只抄"作业要求的每个干员槽都是精二(E2)+"的作业**。个人槽必须 owned 且
  `elite>=2`；备选组至少 1 名成员 E2+。即 `score == (0,0,0,0)`。**不用 `ignore_requirements` 硬凑**
  （实测核心 `澄闪` Lv1 硬打 GO-EX-4 → 卡编队/翻车）。
- 数据源用**森空岛在线**（`ark_operbox_online`）；401 先 `python scripts/skland/skland_cli.py status` 续期。
  兜底才用 MAA 干员箱 `C:\MAA\data\OperBoxData.json`（无技能/专精）。
- `ignore_requirements` 仍保留在 `run` 里作**执行层**开关（避免作业里极小练度差异被 MAA 卡住），
  但**选作业的准入**由上面的 E2 口径把关。

### 坑 5：失败**退理智**，可以放心换作业重试
- 战斗失败/非三星时 MAA 找不到 `StageDrops-Stars-3`（相似度不足）→ `TaskChainError`；游戏结算显示"理智返还"。
- 失败不亏理智，所以 `--try` 逐个候选重试是划算的。
- 判成功：任务链**没有** `TaskChainError`（msg 10000）= 三星；出现即视为该候选未过。

### 坑 6：干员箱没有技能等级
- `OperBoxData.json` 只有 elite/level。作业常要求核心 `skill_level:10(专三) + module`。所以"能不能过"**最终只能实跑验证**，`plan` 的排序只是"能不能凑齐人"。

### 坑 7：自动编队会**覆盖编队**，别选错槽
- `formation:true` 时 MAA 会把指定的编队槽**重写成作业要求的阵容**。`formation_index=0`（默认"不选择"）行为不可控，**别用**。
- **本工作流固定 `formation_index=4`（只写第四编队）**，避免动到第二编队等（用户约定）。改槽位用 `--formation N`。

---

## 5. 本轮成果（act52side，2026-10-09）

- 干员箱 337 个，其中精二 58 个；活动两个单核核心均在：**圣聆初雪 E2L60**、**予愿安洁莉娜 E2L60**。
- 8 个战斗关均有"未拥有=0 / 空组=0"的候选；最终执行：

  | 关 | 作业(候选) | 结果 |
  |---|---|---|
  | YW-5 | `[YW-5] 圣聆初雪单核 挂件兼容高中低配` | 通关(2星) |
  | YW-6 | `[YW-6] 圣聆初雪单核 挂件兼容高中低配` | **3星** |
  | YW-7 | `[YW-7] 圣聆初雪单核 挂件兼容高中低配` | **3星** |
  | YW-8 | `[YW-8] 圣聆初雪单核 挂件兼容高中低配` | **3星** |

- 经验：**同一关首个候选未必能过**（YW-5 的 `id=105708` 失败，换成"挂件兼容"系列才过）→ 需要 `--try` 或人工换候选。
- "魔道孑然"的 `[YW-N] 圣聆初雪单核 挂件兼容高中低配` 系列对本账号最稳。

---

## 6. 待办 / 可增强

- `run` 目前"是否三星"靠 `TaskChainError` 判定；可再解析 `StageDrops` 回调拿掉落。
- 自动识别"当前活动 id"（现在要手动 `events` 找）。
- 把结果写进报告（复用 `scheduling/` 的报告框架）。
- EX 关在活动中期才开，届时 `sync` 即可拿到新关（注意别把"未开"当失败）。

---

## 7. 活动经济：刷多少关、换哪些道具（A 项）

工具：`scheduling/tools/event_economy.py`，数据：`scheduling/data/event_<id>.json`。

```
python scheduling/tools/event_economy.py scheduling/data/event_act52side.json --min-priority 高
```

它算：各关「代币/理智」排名 → 选最优刷关；目标道具集需要多少代币 → 刷几次、多少理智；对比活动期自然+周常预算，判断**够不够换完 / 缺口多少**。

**数据来源（每次活动都要更新，务必常看；PRTS/企鹅会记但滞后几天）**：
| 字段 | 来源 |
|---|---|
| 关卡理智 | PRTS 关卡页「作战消耗」 |
| 代币/次 | **企鹅物流**掉落矩阵(`/result/matrix?server=CN&stageFilter=actNNside_XX`，quantity/times)；没出再**游戏内**打一关看余额增量 |
| 商店道具价/限购 | **PRTS 活动商店页**（活动开几天后才有）；没出再**游戏内**活动商店 OCR |

> 实测：act52side **开活动当天** PRTS 无商店页、企鹅 stages/matrix 无 act52、PRTS 搜索 0 命中 → 当天只能游戏内实测；隔几天再查 PRTS/企鹅 就有。

**游戏内翻商店（一键）**：`python scripts/event-copilot/event_copilot.py shop --pages 8`
→ 逐页截图+OCR 落盘到 `%TEMP%\event-shop`（**商店/干员/仓库都是左右翻页**，用 MAA `Custom`+`SlowlySwipeToTheLeft`；本机 adb 滑动失效）。
前提：游戏停在活动商店页 + 单客户端。翻出来的文本再整理进 `scheduling/data/event_<id>.json` 的 `shop`。

**当前 act52side 已知**：理智 YW-1/2=9、YW-3/4/5=12、YW-6/7/8=21；**代币=理智 1:1（三星）**——实测 YW-8 三星 +21、YW-5 二星 +6（≈半）→ **刷代币必须三星**（二星只给一半）。商店第 1 屏已录入（旅骨的信物360/模组数据块75/精炼溶剂35/聚合剂100/寻访凭证150…），其余翻页待补。

**样例行**：高优先级 4 件需 1460 代币（已有 206）→ 差 1254 → 刷 YW-8 **60 次 = 1260 理智**；活动期自然+周常预算 ≈ 5760 理智 → 够换完。

**首通 vs 刷关**：
- 首通：用 `event_copilot.py`（作业）。
- 刷代币：`event_copilot.py run <活动> --stages <最优关> --loop N`（`loop_times=N`，重复打同一关）。

**纪律**：活动期间常看 wiki（PRTS 关卡页 / 一图流「关卡推荐」「材料收益」）——EX 开放、商店补货、代币获取变化都要重刷数据文件。

---

## 8. 一键闭环（C 项：`goto`）
`event_copilot.py goto`（默认坐标 `主页370,45 → banner1770,205 → 关卡入口1400,860`）是**简易**导航，换活动/分辨率用 `--home-xy/--banner-xy/--hub-xy` 覆盖。更稳的做法仍是 MCP 层 `ark_where`/`ark_find`/`ark_tap`（§3bis）。
