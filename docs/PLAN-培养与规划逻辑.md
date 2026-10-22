# 干员培养 × 每周规划 —— 逻辑总纲

> 目的：把「该练谁」变成「刷多少材料、花多少理智」，再和 **活动/搓玉/剿灭** 一起排进同一份周预算。
> 配套实现：`scheduling/tools/plan_week.py`（周规划器）、`plan_util.py`（每日分配）、`recruit_combo.py`（公招，旁支）。
> 数据口径见 `docs/DATA-SOURCES.md`；运筹判据见 `docs/MASTER-PLAN.md`。

## 0. 一句话

**目标集 → 需求 D → 库存 S → 缺口 G → 最优供给（刷哪关、多少理智）→ 按优先级排进周预算。**

---

## 1. 数据源总表（每项都写清"从哪拿"）

| 数据 | 来源 | 具体字段 / 接口 | 状态 |
|---|---|---|---|
| **精英/技能/专精** 的材料+龙门币 | **官方** `character_table.json` | `phases[].evolveCost`、`allSkillLvlup[].lvlUpCost`、`skills[].levelUpCostCond[].levelUpCost` → `[{id,count,type}]` | ✓ 已下（~15MB，**直连易超时截断**，见 §5） |
| **模组** 的材料+龙门币 | **官方** `uniequip_table.json` | `charEquip[charId]`→模组 id；`equipDict[id].itemCost{"1"/"2"/"3"}`→升到 1/2/3 级的 `[{id,count,type}]`（`type=GOLD` 折龙门币） | ✓ 已下（`fetch_gamedata.py` 含此表） |
| **升级(1→Lv)** 的经验+龙门币 | 一图流 培养卡片 或 公式 | 卡片 `cost` 文本："经验 239,400；龙门币 371,947；约 3,275.9 理智" | ✓ 一图流卡片在 `一图流产物/243-培养建议-cards.json`（**仅覆盖基建向目标**） |
| **材料 → 理智 / 关卡掉落率** | **企鹅物流** | `/result/matrix`，用 `quantity/times`（**别用 dropRate**） | ⏳ 待接 |
| 材料 id ↔ 名称 | 官方 `item_table.json` 或 MAA `resource/item_index.json` | `30012`=固源岩、`3141`=源石碎片… | ✓ MAA 本地有 |
| 干员库存（材料/芯片/龙门币） | MAA 仓库识别 | `C:\MAA\data\DepotData.json` → `{itemId: 数量}` | ✓ |
| owned 干员（练度） | 森空岛在线 | `ark_operbox_online` / `scripts/skland/skland_box.py` | ✓（401 时 `skland_cli.py status` 续期） |
| 抄作业刚需 | MAA 作业站统计 | `scheduling/tools/oper_appearance.json`（`required_rate`/`status`） | ✓ |
| 基建刚需 | 一图流培养建议 | `scheduling/tools/training.json`（含 `cost_exp/cost_lmd/sanity`） | ✓ |
| 活动关卡/理智/窗口 | 官方 `activity_table` + PRTS + 本地 | `scheduling/data/event_<id>.json`（`stages[].sanity`、`start`、`combat_end`、`farm`） | ✓ |
| 干员升级经验/龙门币曲线 | 需补 | 官方**没有**单表；用一图流/公式 | ⏳ 待定 |

> **回答"找材料是不是去 wiki"**：**不是**。官方 `character_table.json` 直接有"精英化/技能/专精"的要哪些材料、各几个（`id+count`）；**掉落与理智估值**用企鹅物流。wiki 只当交叉校验。

---

## 2. 训练标准（用户 2026-10-11 定，写死）

| 类型 | 目标 |
|---|---|
| **六星** | 精二 **60 级**、技能 **7 级** + 常用技能 **专三(M3)** |
| **五星** | 精二 **50 级**、技能 **7 级** + 常用技能 **专三(M3)** |
| **基建用** | 精二 **1 级**、技能无要求 |

> "常用技能"= 该干员在抄作业里最常被使用的那一个技能（`oper_appearance` 目前只有出现率，技能维度待补）。

---

## 3. 计算链（逐步、可执行）

1. **定目标集**：抄作业刚需（`oper_appearance` 中 `status∈{E0,E1}`，按 `required_rate` 降序）∪ 基建刚需（`training.json` 推荐）。
   用户口径：截前 **N=4** → 当前为 **德克萨斯(5★E1) / 乌尔比安(6★E1) / 伊芙利特(6★E0) / 山(6★E0)**。
2. **算需求 D**：对每个目标，按 §2 标准，从 `character_table` 取：
   - 精英化：`phases[1].evolveCost` + `phases[2].evolveCost`（E0→E1→E2）；
   - 技能 1→7：`allSkillLvlup[0..6].lvlUpCost`；
   - 专精 M3：常用技能的 `levelUpCostCond[0..2].levelUpCost`；
   - 模组：`equipDict[模组id].itemCost["1"/"2"/"3"]`（按当前模组级→目标级，只算剩余段）；
   - 升级 Lv：经验/龙门币（§1 的一图流/公式）。
3. **取库存 S**：`DepotData.json`（材料/芯片/龙门币）。
4. **缺口 G = D − S**（按 itemId 逐项，负数取 0）。
5. **最优供给**：每种缺口材料 → 选**每理智产出最高**的常驻关（企鹅 `quantity/times`）→ 该材料所需理智；合计 = 该干员的"培养理智成本"。
6. **排期**：把"培养理智"与 **剿灭/固源岩/活动** 一起，按 §4 优先级塞进**周预算**。

---

## 4. 周预算与优先级（`plan_week.py` 的 `RULE`，写死）

```
预算 budget = 自然(240×7=1680) + 周常浓缩液(240，若读数周≠计划周才加) + 理智药存量
```

| 优先级 | 规则 | 说明 |
|---|---|---|
| **R1 剿灭** | 打满周上限：`ceil(1800/370)=5 次 ×25 = 125` | **每天 1 次**（剿灭券是每日任务当天领） |
| **R2 固源岩 ≥1000** | `1-7 次数 = ceil((1000 + 92.4×7 − 库存)/1.245)` | 搓玉原料下限（**合成玉最高优先**） |
| **R3 活动** | 扣掉 R1/R2 后，**剩余预算反推次数**；只在开放窗口内 | 性价比高但有时限 |
| **R3.5 培养** | 剩余预算拨给 G 里**性价比最高**的材料关 | 通常**不够**，按"多周项目"推进 |
| **R4 填充** | 还有零头 → 刷 **1-7** | **理智必须花光** |
| **R5 每日分配** | 窗口约束 + 每天往"最空的天"填（自然上限 240） | 超上限的天 → 提醒吃理智药 |

**优先级理由**：合成玉（搓玉）> 龙门币 > 活动 > 练度（`MASTER-PLAN` §3）。所以**培养排在活动之后**，一周往往只剩零头。
按此规则算，一个六星 E2L60+技能专三 ≈ **3000~6000 理智** → **单独一个就要 2~3 周**。

---

## 5. 落地与现状

| 模块 | 作用 | 状态 |
|---|---|---|
| `plan_week.py` | 规则写死的周规划器 → `weekly_plan.json` | ✅ R1/R2/R3/R4 已实现；**R3.5 培养 待加** |
| `plan_util.py` | 每日分配（窗口/每日上限/花光预算/上线建议） | ✅ |
| `build_site.py` + 森空岛GUI「长草」tab | 展示计划/每日安排/上线建议 | ✅ |
| `sanity_potion.py` | 读理智药存量 | ✅ |
| `recruit_combo.py` + `site_server.py` | 公招推荐（贴词条） | ✅ |

### 已知坑
1. **官方 gamedata 直连易超时/截断**（实测 9.5MB/15MB 就断）→ 需**断点续传/镜像**（jsdelivr 也不稳）。
2. **一图流培养卡片只覆盖基建向目标**，战斗向（E2L60+专三）要自己从 `character_table` 算。
3. **等级经验/龙门币**不在官方单表里，需补口径。
4. **"常用技能"** 的具体技能未定（`oper_appearance` 无技能维度）。

---

## 6. 待补清单（按顺序做）

1. ✅ `fetch_gamedata.py`：**可续传**下载 `character_table.json`（+`item_table.json`、`uniequip_table.json`），校验 JSON 完整 + 大小。
2. ✅ `oper_cost.py`：输入干员+标准 → 输出材料清单（itemId+数量）与龙门币/经验。
   - ✅ **自定义目标**：`compute_custom` / CLI `--target-elite/--target-level/--mastery/--module` /
     MCP `ark_oper_cost`，可按「选中干员 + 目标精英/等级 + 一/二/三技能专精 + 模组等级」精确算账。
   - ✅ **模组成本**：接入 `uniequip_table.itemCost`（材料 + `type=GOLD` 龙门币），按当前模组级只算剩余段。
3. 企鹅物流接入：`材料 → (最优关, 理智)` 映射表。
4. `plan_week.py` 加 **R3.5 培养**：算缺口 G → 折算理智 → 排进预算；输出"本周投 X 理智，A 还需 Y 天"。
5. 网页/GUI 增「培养进度」页。
