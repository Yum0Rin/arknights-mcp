# 一键长草 · 现状速查（on-call 先读这份）

> 更新：2026-10-12（oper_cost 按当前练度 + 官方升级经验/龙门币；剿灭改每天 1 次）
> **单一事实源：`scheduling/data/weekly_plan.json`**（别读别的快照/旧对话）

## 入口

- 桌面快捷方式 **「明日方舟·助手」** → `pythonw scripts/skland/skland_gui.py`
- GUI「**长草**」tab 按钮：`直驱跑一键长草`（跑**当天那一份**）/ `基建换班` / `写 MAA 配置` / `生成汇总网页` / `打开汇总网页`
- 「快捷工具」卡：`启动游戏`（含拉起雷电）/ `打开 MAA`
- 命令行：`python scripts/maa-week/maa_week.py run [--date YYYY-MM-DD] [--whole-week] [--no-side] [--dry]`

## 规则（写死在 `scheduling/tools/plan_week.py` 的 `RULE`）

```
预算 = 自然(240×7) + 周常浓缩液(240，仅当"理智药读数不在本计划周"才加) + 理智药存量
R1 剿灭：5 次×25=125，每天 1 次；若 state.json.progress.annihilation.done(W=本周) → 跳过
R2 固源岩：期末 ≥ RULE.shards.target(现 1000) → 1-7 次数
R2.5 EX/S 首通：开放日落在本周 → 各关×1 必做，先占预算
R3 活动：按"商店要买总量"封顶，剩余预算反推次数
R3.5 培养：目标 RULE.train_targets(现「乌尔比安」)；商店能换的材料先抵扣；再用剩余预算刷
R4 1-7 填充：花光预算
R5 每日分配：活动只在窗口内；每天 ≤ day_cap = 240 + 药/天；**排不下就不排**
```

## 关键参数

| 项 | 值 |
|---|---|
| 连战 series | **活动关 10 / 普通关 6**（`MAA-INTERNALS.md:78`；不退化成单次） |
| 当前活动 | act52side（昨日海）：YW-6 开放 2026-10-09~10-23，EX 2026-10-16，S 2026-10-23 |
| EX/S 理智 | **往期 sidestory 口径估**（EX-1~8 = 15/15/18/18/21/21/24/30；S-1 = 30）**待实机核** |
| 基建分工 | **换班脚本**（`infrast_rotation.py all`）：收菜→菲亚梅塔→切队列→再收菜，`run` 时**到期才跑**（`side.if_due=infra_next_swap_at`）；**MAA `Infrast`（mode=20000, `facility=["Reception"]`）只管会客室/线索搜集**（换班脚本不含这个）。 |
| ⚠️ 收菜时点 | 收菜**跟着换班走**（约 12h 一次）；线索由 MAA 每次 run 都做。 |

## 命令

```bash
python scheduling/tools/plan_week.py --date 2026-10-13     # 生成周计划（确定性）
python scripts/maa-week/maa_week.py run --date 2026-10-11  # 跑当天
python scripts/maa-week/maa_week.py write                  # 写 MAA GUI 配置（需关 MAA）
python scheduling/tools/build_site.py                      # 生成汇总网页
python scheduling/tools/site_server.py                     # 起后端（公招推荐框）
python scripts/infrast-rotation/infrast_rotation.py all     # 基建换班
python scripts/skland/skland_cli.py status                  # 森空岛续期（401 时）
```

## 已修的坑（都踩过）

1. `--dry` 会真执行换班脚本 → 修（dry 只打印）。
2. `plan_week.py` R2.5 代码块顺序错/重复 → 修（`ev`/`extra_san` 提前、删重复块）。
3. 流程里同时有 MAA 收菜 + 换班收菜（重复）→ 去 MAA Infrast 任务。
4. 活动关/1-7 没带 `series` → 退化成单次刷 → 修（活动 10、普通 6）。
5. 每日 41 次（861 理智/天，打不完）→ 每日按 `day_cap=240+药/天` 封顶。
6. GUI「刷新数据/签到」不续期 → 森空岛 401 → 修（先 `refresh_token`）。
7. 「读理智药」做成了按钮 → 移除（它是每周定时的活）。

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
- [x] ~~「升级(1→Lv)」的经验/龙门币未计入~~ **已修（2026-10-12）**：官方 `gamedata_const.json` 有 `characterExpMap`/`characterUpgradeCostMap`/`evolveGoldCost`，`oper_cost.py` 已接入，并按**当前练度**只算剩余段（`--from-skland`，含技能/专精）。
- [ ] 「常用技能」目前假设技能 1（该 M3 哪个待定）
- [ ] 本周(W41)只跑到一半（用户中途放弃），下周一(W42)按 `weekly_plan.W42.json` 重跑
- [ ] 商店兑换/代币记录（需进游戏内商店 OCR）
