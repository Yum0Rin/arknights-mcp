---
name: arknights-event-economy
description: 明日方舟活动「商店/理智/代币」规划——按关卡理智、每关代币产出、商店道具价格与限购，算要刷多少关、换哪些道具、理智够不够。当用户问「这次活动要打多少关 / 换什么划算 / 理智够换完吗 / 代币怎么花」时使用。脚本 scheduling/tools/event_economy.py。
---

# 活动经济规划（刷多少关、换哪些道具）

工具：`scheduling/tools/event_economy.py`；数据：`scheduling/data/event_<id>.json`。
方法文档：`docs/WORKFLOW-活动关作业.md` §7。

## 用法
```bash
python scheduling/tools/event_economy.py scheduling/data/event_act52side.json --min-priority 高 --tokens-owned 206 --farm YW-8
```
算：各关「代币/理智」排名 → 最优刷关；目标道具集所需代币 → 刷几次/多少理智；对比活动期预算判断能否换完。
`--min-priority {高,中,低}` 选目标集；`--tokens-owned` 已有代币；`--medicine/--med-per` 加药。

## 数据来源（每次活动都要更新 —— **先查 PRTS / 企鹅物流**，它们会记，只是滞后几天）
| 字段 | 来源 |
|---|---|
| 关卡理智 | PRTS 关卡页「作战消耗」 |
| 代币/次 | **企鹅物流**掉落矩阵（`/result/matrix?server=CN&stageFilter=actNNside_XX`，`quantity/times`）；PRTS 只写"固定掉落"不给数；**都没出**再游戏内实测（打一关看代币余额增量） |
| 商店价/限购 | **PRTS 活动商店页**（活动开几天后才有）；没出再游戏内商店 OCR |

> **游戏内翻商店（商店/干员/仓库都是左右翻页）**：先 `ark_connect`（否则 MaaCore `m_controller is not inited`，滑动无效），
> 再用 `ark_run_task("Custom", {"task_names":["SlowlySwipeToTheLeft","SlowlySwipeToTheLeft"]})` 连续翻页 + OCR。
> 详见 `docs/FINDINGS.md` §15。

> 实测 act52side **开活动当天**：PRTS 无商店页、企鹅 stages/matrix 均无 act52、PRTS 搜索 0 命中 → 只能游戏内实测。**隔几天再查 PRTS/企鹅**就能拿到。

## 关键经验（实测 act52side）
- **代币 = 理智 × 星数**：三星 ≈ 代币 = 理智（YW-8 三星 +21）；二星只给一半（YW-5 二星 +6）。→ **刷代币必须三星**。
- 新活动**当天** PRTS 无商店页、企鹅物流 matrix 为空、关卡详情不给代币数 → 只能游戏内实测。
- **商店按"库存算满"**：需代币 = Σ(单价 × 限购)，注意信物类限购常为 5（卡上大写数字）。
- 活动期理智预算 ≈ 天数×240 + 周数×240(周常浓缩液) + 药。

## 纪律（留痕）
活动一有变动（EX 开放 / 商店补货 / 代币变化）就**重刷数据文件** + 重跑脚本；结果记进报告。
