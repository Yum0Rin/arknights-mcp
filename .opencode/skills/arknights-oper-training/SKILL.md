---
name: arknights-oper-training
description: 明日方舟「干员培养推荐」——按 MAA 作业站挂机作业的出现率，排该优先精二/练哪些干员。当用户问「该练谁 / 培养推荐 / 优先精二哪个 / 干员榜」时使用。脚本 scheduling/tools/oper_appearance.py。
---

# 干员培养推荐（按挂机作业出现率）

脚本：`scheduling/tools/oper_appearance.py`；产出 `scheduling/tools/oper_appearance.json`。

## 思路
「出现率高」= 以后各关都能抄到 → 练它收益最大。所以从作业站抓大量**挂机作业**，统计每个干员出现频率，再和本人干员箱对照。

## 用法
```bash
python scheduling/tools/oper_appearance.py --pages 15 --top 25
# 产出 oper_appearance.json + 控制台排行（含"建议培养/缺"）
```

## 数据来源与口径
- 作业站 `https://prts.maa.plus/copilot/query`：
  - **`document=挂机`** 按标题/详情筛挂机作业（共约 1.2 万）；
  - `orderBy=views`（热门）/`hot`（近期热度）；
  - `limit=100` + `page` 翻页（每页 100，无需 `/copilot/get`，列表 content 已含 opers）。
- 出现率 = 该干员(作业**顶层必选** opers)出现次数 / 样本作业数；替选组(groups)成员单独统计。
- 对照 `C:\MAA\data\OperBoxData.json`：owned-not-E2 = 培养目标；缺 = 无法练。
  > 干员箱可换**在线源**（免模拟器，无需开雷电）：`ark_operbox_online`（MCP）或
  > `scripts/skland/skland_box.py` 的 `fetch_operbox()`，形态与 `OperBoxData.json` 同构。

## 实测结论（2026-10-09，1500 个热门挂机作业）
- 必选高频：煌34.5%、艾雅法拉33.1%、德克萨斯27%、乌尔比安23%、歌蕾蒂娅23%、塞雷娅22%、圣聆初雪19%…
- **建议精二**（我 owned 但未 E2）：德克萨斯、乌尔比安、伊芙利特、山、夜莺、拉普兰德、澄闪…
- **缺但高频**（值得抽/借）：煌、艾雅法拉、纯烬艾雅法拉、阿斯卡纶、黍…

## 注意
- 只看"挂机"会让结果偏"摆完挂机/低操作"取向；要泛用可去掉 `--kw`（全量 4 万+，样本更大更慢）。
- 当前活动的新作业会拉高"近期热度"；按 `views` 更能反映"长期出现率"。
