# 数据来源与取数方法（复用指南）

> 做 scheduling 的取数/建模时**先看这里**，别重新摸索。
> 数据源：**企鹅物流**（掉落）、**PRTS wiki**（规则/数值）、**一图流**（排班/关卡）、**MAA**（本人账号识别）。
> 最后更新：2026-10-09。

---

## 1. 企鹅物流 Penguin Statistics（**掉落率首选**）

- 站点：`https://penguin-stats.io`（国际）/ `https://penguin-stats.cn`（国内镜像）。
- **公开 API**（无需 key），本机用 `curl.exe -s -L --ssl-no-revoke` 取（`--ssl-no-revoke` 必加，否则 schannel 吊销检查报错）。
- 关键端点：

| 用途 | URL |
|---|---|
| 掉落矩阵（某关） | `https://penguin-stats.io/PenguinStats/api/v2/result/matrix?server=CN&stageFilter=<stageId>` |
| 关卡表 | `https://penguin-stats.io/PenguinStats/api/v2/stages?server=CN` |
| 物品表 | `https://penguin-stats.io/PenguinStats/api/v2/items` |

- 返回 `{matrix:[{stageId,itemId,quantity,times,dropRate}]}`；**平均掉落/次 = quantity / times**（`dropRate` 字段常为 null，别用）。
- **常用 ID**（实测）：

  | 名称 | itemId | | 关卡 | stageId |
  |---|---|---|---|---|
  | 固源岩 | `30012` | | 1-7 | `main_01-07` |
  | 源岩 | `30011` | | CE-5 / CE-6 | `wk_melee_5` / `wk_melee_6` |
  | 赤金 | `3003` | | LS-5 / LS-6 | `wk_kc_5` / `wk_kc_6` |
  | 基础/初级/中级/高级作战记录 | `2001`/`2002`/`2003`/`2004` | | 剿灭(长期) | 见 PRTS 关卡页 |

  （其它 itemId 自己抓 `/items` 搜名字。）

- **实测值快照（2026-10）**：
  - `main_01-07`：固源岩 `30012` avg **1.245/次**（6 理智）→ **4.82 理智/个**；另掉 基础记录≈1.24、少量源岩/糖/异铁等。
  - `wk_melee_6`(CE-6)：固定 龙门币 10000/36 理智（龙门币不在 matrix 里，是固定奖励）。
  - `wk_kc_6`(LS-6)：固定 **4 高级 + 2 中级** = 10000 经验/36 理智。

---

## 2. PRTS wiki（**规则/数值**）

- 站点：`https://prts.wiki`。用 `webfetch`；**页面极大**（导航+道具清单会灌爆输出），
  **建议交给子代理（copilot 便宜模型）提取所需数值**，只回传结果。
- 常用页面（URL 里中文按需 %编码）：

| 内容 | 页面 |
|---|---|
| 理智规则（回复/上限/药/源石） | `/w/理智` |
| 理智上限随等级表 | `/w/博士等级` |
| 每日/每周任务奖励 | `/w/任务列表` |
| 剿灭作战（周上限/关卡） | `/w/关卡一览/常态事务` 与各国剿灭关卡页 |
| 干员升级经验曲线 | `/w/干员升级数值` |
| 理智药各回复量 | `/w/应急理智浓缩液`、`/w/应急理智加强剂` 等各自页面 |

- **实测值快照（2026-10，国服）**：
  - 自然回复 **6 分钟/1 点 = 240/日**；药/源石补到 **999** 封顶；1 至纯源石 = **135 理智**。
  - 理智上限：**99 级 = 205**；117 级封顶 210（含历史 +45 / +30）。→ 每 12h 回复 120 < 205，**上线花到 ≤85 不溢出**。
  - 理智药：应急理智小样 **10** / 加强剂 **80** / 浓缩液 **120**（合剂60、顶液100 为旧版）。
  - 每周稳定额外理智：**周常 浓缩液×2 = 240**（每日任务不给理智、绿票商店不售理智）。
  - 剿灭：周合成玉上限 **1800**；当期(拉特兰 默祷圣祠) **25 理智/次 ≈370 合成玉/次**（打满约 5 次=125 理智）。
  - 每日任务合计：龙门币 9500、合成玉 100、采购凭证 5、作战记录(8基础+5初级+6中级=9600经验)。
  - 每周任务合计：龙门币 23000、合成玉 500、采购凭证 30、资质凭证 20、高级记录×9(=18000经验)、浓缩液×2。
  - 精英化 精0Lv1→精2Lv1：6★ 经验 361400 / 龙门币 589841（LMD:EXP≈**1.63**）；5★ 1.55；4★ 1.37；3★ 只能精一。
  - 作战记录经验：基础 200 / 初级 400 / 中级 1000 / 高级 2000。

---

## 3. 一图流 ark.yituliu.cn（**排班 + 关卡/材料收益**）

- 排班生成器 `https://ark.yituliu.cn/tools/scheduleV3`（用法/坑见 `docs/FINDINGS.md` §8–§11，尤其"导入 MAA JSON 要裸数组"）。
- 站点自带工具：`材料收益`、`关卡推荐`、`基建技能一览`、`精英化与专精性价比` 等（导航可进；SPA，`webfetch` 取不到动态数据，需 firefox MCP 操作）。

---

## 4. MAA（**本人账号识别**）

- `C:\MAA\data\OperBoxData.json`（干员箱）、`DepotData.json`（仓库）；识别流程见 `docs/FINDINGS.md` §5、附录。
- 读法：`OperBoxData.json` = `{done, own_opers[], source, syncTime}`；导入一图流需先抽成**裸数组**。

---

## 5. 本轮建立的模型/脚本（`scheduling/tools/`）

| 脚本 | 作用 | 产出 |
|---|---|---|
| `build_report.py` | 解析一图流产物（MAA JSON + 结果页文本） | `report_data.json` |
| `parse_training.py` | 解析"培养建议"卡片 → 逐干员培养前后技能加成 | `training.json` |
| `sanity_plan.py` | 周度理智规划（运筹模型） | `sanity_plan.json` |
| `render_report.py` | 组装自包含单文件报告 | `报告/index.html` |

- 报告里的**理智规划**=周度分配 LP：目标(养成产出/合成玉)，约束(周预算 1920、上限 205、剿灭周上限、LMD:EXP 配比)。
- 重新生成顺序：`build_report.py` → `parse_training.py` → `sanity_plan.py` → `render_report.py`。

## 6. 取数纪律（踩过）

- `curl.exe` 必须 `--ssl-no-revoke`。
- PRTS 页面巨大 → **交子代理提取**（用户有 copilot 额度，研究类走便宜模型）。
- 企鹅 `dropRate` 字段常为 null → 自己用 `quantity/times` 算均值。
- 一图流是 SPA：`webfetch` 拿不到动态表格；要交互/数据用 firefox MCP（作用域快照见 FINDINGS §10）。
