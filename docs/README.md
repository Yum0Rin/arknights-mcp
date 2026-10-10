# docs 文档索引

> 本仓库的规划 / 决策 / 工作流 / 踩坑文档都在这里。<br>
> **读法**：先读根 [`README.md`](../README.md) 了解项目能做什么，再按下表顺序读；急用可直接跳到对应文件。<br>
> **建议阅读顺序**：根 README → MASTER-PLAN → STATE → state.json / ops_manual.json → DAILY-CHECKLIST → WORKFLOW-*；FINDINGS / DATA-SOURCES 当参考手册查，不用通读。

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

## 三、参考手册（查）

| 文件 | 定位 |
|---|---|
| [`DATA-SOURCES.md`](DATA-SOURCES.md) | 数据源与取数方法：企鹅物流 API / PRTS 数值 / 一图流 / MAA / 森空岛 |
| [`FINDINGS.md`](FINDINGS.md) | 踩坑留痕（§14/§15 活动关、§16 培养推荐、§17 森空岛接口） |

## 彼此关系

- **[`MASTER-PLAN.md`](MASTER-PLAN.md)**：怎么算、怎么选——判据与公式的唯一出处。
- **[`STATE.md`](STATE.md)**：什么时候算、算完干什么——把 MASTER-PLAN 的判据落成循环。
- **[`state.json`](state.json)**：当前状态存哪——循环每次读写它。
- **[`ops_manual.json`](ops_manual.json)**：MAA 没有内置的操作怎么点——B 类操作的坐标/模板。
- **[`DAILY-CHECKLIST-act52side.md`](DAILY-CHECKLIST-act52side.md)** + **`WORKFLOW-*.md`**：把上面的判据/协议落成"当天照做"的清单与流程。
- **[`DATA-SOURCES.md`](DATA-SOURCES.md)**、**[`FINDINGS.md`](FINDINGS.md)**：上游数据出处与踩过的坑，供上面各文档引用。

> 关键数据坑速记：森空岛 `status.ap`（理智）是**旧快照**，别信，**理智以实机为准**；仓库只有 MAA 有（森空岛接口无仓库、无抽卡记录）。详见 [`FINDINGS.md`](FINDINGS.md) §17 与 [`MASTER-PLAN.md`](MASTER-PLAN.md) §8。
