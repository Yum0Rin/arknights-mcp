# docs 文档索引

> **本仓库做什么**：让 AI 每天接管你的《明日方舟》账号——读账号状态 → 按判据决策 → 执行日常/活动 → 回写进度，形成闭环、长期自主运转。<br>
> 本仓库的规划 / 决策 / 工作流 / 踩坑文档都在这里。<br>
> **读法**：先读根 [`README.md`](../README.md) 了解项目能做什么，再按下表顺序读；急用可直接跳到对应文件。<br>
> **建议阅读顺序**：根 README → FEATURES（功能/用法）→ MASTER-PLAN → STATE → state.json / ops_manual.json → DAILY-CHECKLIST → WORKFLOW-*；FINDINGS / DATA-SOURCES 当参考手册查，不用通读。

## 〇、功能与用法

| 文件 | 定位 |
|---|---|
| [`FEATURES.md`](FEATURES.md) | 能做什么 / `ark_*` 工具一览 / 用法示例（含异步长任务）/ 依赖·配置·注册 / 已知限制 |

## 一、先读（决策主链）

| 文件 | 定位 | 什么时候读 |
|---|---|---|
| [`MASTER-PLAN.md`](MASTER-PLAN.md) | 运筹总指挥：目标 → 数据 → 决策 → 执行 → 复盘五层闭环，铁律与养谁/理智/活动/基建/抄作业判据 | 要决策、算攻略 |
| [`STATE.md`](STATE.md) | 决策循环协议：何时决策 / 执行 / 调整 + 操作学习模式 | 每次"醒来"先读 |
| [`state.json`](state.json) | 机器可读状态（**单一事实源**：triggers / plan / progress / inventory / log） | 读写状态 |
| [`ops_manual.json`](ops_manual.json) | 游戏 UI 操作手册（A 类 = MAA 内置；B 类 = 手点，边做边记坐标/模板） | 执行 B 类手点时 |

一句话记法：**MASTER-PLAN = 知识/判据，STATE = 循环协议，state.json = 状态，ops_manual.json = 操作。**

## 二、当期执行（照做）

| 文件 | 定位 |
|---|---|
| [`DAILY-CHECKLIST-act52side.md`](DAILY-CHECKLIST-act52side.md) | 当期活动每日清单（预算 / 刷关 / 商店兑换 / 一页速查） |
| [`WORKFLOW-活动关作业.md`](WORKFLOW-活动关作业.md) | MAA 抄作业打活动关工作流（抓作业 → 比对干员箱 → 逐关自动战斗） |
| [`WORKFLOW-仓库取数.md`](WORKFLOW-仓库取数.md) | 游戏内仓库 OCR 读库存（理智药存量实测 ≈1200 理智） |

## 二·五、复盘

| 文件 | 定位 |
|---|---|
| [`收益账本与周报.md`](收益账本与周报.md) | 每日收益/消耗/练度变化的账本 schema（`scheduling/data/revenue_ledger.jsonl`）+ 周报三块模板（练度提升/踩坑/下周优化）+ 设备采集 bundle 接口。**已接自动采集**：`revenue_ledger.py settle --auto`（MAA 仓库 + 森空岛干员箱 + 理智读数 + 当日计划）→ 汇总网页「账本」页 |

## 二·七、一键长草（2026-10-11 新增）

| 文件 | 定位 |
|---|---|
| [`STATE-一键长草.md`](STATE-一键长草.md) | **现状速查（on-call 先读）**：入口 / 规则 / 参数 / 命令 / 已修的坑 / 待办 |
| [`PLAN-一键长草.md`](PLAN-一键长草.md) | 方案：执行层任务顺序 + 双落地方案 + 意图层运筹 + 本地汇总网站 + 定时 |
| [`PLAN-培养与规划逻辑.md`](PLAN-培养与规划逻辑.md) | 培养 × 规划：数据源总表 / 训练标准 / 计算链（D−S=G）/ 优先级 / 待补 |
| [`PLAN-汇总网页改版.md`](PLAN-汇总网页改版.md) | 汇总网页改版规划（**今天/本周/培养·工具/账本** 4 页；删设计文档页/旧基建报告；接收益账本） |

> 代码：`scheduling/tools/plan_week.py`（规划器）、`plan_util.py`（每日分配）、`oper_cost.py` + `material_cost.py`（培养成本）、
> `build_site.py`（汇总网页：今天/本周/培养·工具/账本）+ `site_server.py`（公招推荐 API）、
> `revenue_ledger.py`（收益账本，`settle --auto` 自动采集）+ `revenue_weekly.py`（周报 HTML）、
> `scripts/maa-week/maa_week.py`（执行器）、`scripts/skland/skland_gui.py`（一体化 GUI「明日方舟·助手」）。

## 三、参考手册（查）

| 文件 | 定位 |
|---|---|
| [`DATA-SOURCES.md`](DATA-SOURCES.md) | 数据源与取数方法：企鹅物流 API / PRTS 数值 / 一图流 / MAA / 森空岛 |
| [`FINDINGS.md`](FINDINGS.md) | 踩坑留痕（§14/§15 活动关、§16 培养推荐、§17 森空岛接口、§23 雷电广告包 `com.android.flysilkworm`） |
| [`MAA-INTERNALS.md`](MAA-INTERNALS.md) | MAA 内部机制参考（全部任务参数 / 关卡导航 / 资源结构 / 回调码 / 配方）——以 MaaCore 源码为准 |
| [`MAA-6.19-融合评估.md`](MAA-6.19-融合评估.md) | **MaaCore 6.18.0→6.19.0 更新扒取与融合建议**（新增 `OperProgress` 培养任务 / `event_shop` 黑名单解禁 / 库存保持 / 定时唤醒；含接口与验证清单） |

## 另见：`.opencode/skills/`（不在 docs 下）

`.opencode/skills/` 是 **opencode 的 skill**——agent **按需加载**的操作手册，**不在 `docs/` 下**，故不列入本索引。
每个 skill 把一类流程沉淀成可复用步骤，用到哪条加载哪条：<br>

- `arknights-data-library`：明日方舟靠谱数据源总目录（查资料时用）。
- `arknights-event-copilot`：用 MAA 抄作业打活动关。
- `arknights-event-economy`：活动商店 / 理智 / 代币规划。
- `arknights-oper-training`：干员培养推荐（按作业出现率排）。
- `maa-copilot-internals`：MAA 自动战斗内部机制与踩坑。
- `maa-resource-sync`：MAA 不认当期新活动时补本地资源。

## 彼此关系

- **[`MASTER-PLAN.md`](MASTER-PLAN.md)**：怎么算、怎么选——判据与公式的唯一出处。
- **[`STATE.md`](STATE.md)**：什么时候算、算完干什么——把 MASTER-PLAN 的判据落成循环。
- **[`state.json`](state.json)**：当前状态存哪——循环每次读写它。
- **[`ops_manual.json`](ops_manual.json)**：MAA 没有内置的操作怎么点——B 类操作的坐标/模板。
- **[`DAILY-CHECKLIST-act52side.md`](DAILY-CHECKLIST-act52side.md)** + **`WORKFLOW-*.md`**：把上面的判据/协议落成"当天照做"的清单与流程。
- **[`DATA-SOURCES.md`](DATA-SOURCES.md)**、**[`FINDINGS.md`](FINDINGS.md)**：上游数据出处与踩过的坑，供上面各文档引用。

> 关键数据坑速记：森空岛 `status.ap`（理智）是**旧快照**，别信，**理智以实机为准**；仓库只有 MAA 有（森空岛接口无仓库）。抽卡记录**森空岛没有**，但在**鹰角官网用户中心**（`ak.hypergryph.com`），见 [`DATA-SOURCES.md`](DATA-SOURCES.md) §8。详见 [`FINDINGS.md`](FINDINGS.md) §17 与 [`MASTER-PLAN.md`](MASTER-PLAN.md) §8。
