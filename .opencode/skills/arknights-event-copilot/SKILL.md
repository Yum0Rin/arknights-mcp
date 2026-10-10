---
name: arknights-event-copilot
description: 用 MAA 自动打明日方舟「当期活动关」（抄作业自动化）——抓 prts.maa.plus 作业、比对本人干员箱、用 MAA 多作业(copilot_list)自动战斗逐关通关。当用户说「打活动关 / 清活动图 / 抄作业 / 用 MAA 过 YW-xx 活动」时使用。脚本 scripts/event-copilot/event_copilot.py。
---

# 用 MAA 打活动关（活动关作业工作流）

主文档：`docs/WORKFLOW-活动关作业.md`；脚本：`scripts/event-copilot/event_copilot.py`。
踩坑：`docs/FINDINGS.md` §14、§15。

## 一句话
`sync`(补资源) → `plan`(抓作业+比干员) → `goto`/手动(游戏停在活动关卡列表) → `run`(MAA 逐关自动战斗)。

## 命令
```bash
python scripts/event-copilot/event_copilot.py events                 # 列活动 id 与关卡代号
python scripts/event-copilot/event_copilot.py sync   act52side       # 补 MAA 资源(新活动必需)
python scripts/event-copilot/event_copilot.py plan   act52side --top 3
python scripts/event-copilot/event_copilot.py run    act52side --stages 5,6,7,8 --try
python scripts/event-copilot/event_copilot.py run    act52side --stages 8 --loop 30   # 刷代币
```

## 铁律（都踩过）
1. **单客户端**：跑前关掉 MAA GUI / 其它 arknights MCP，否则 MaaTouch 抢占、连接错乱。
2. **MAA 必须先认识该活动**：否则 `Not support stage` / `UnsupportedLevel` → 先 `sync`（见 skill `maa-resource-sync`）。补完资源要**重启在跑的 MCP/MAA**。
3. **游戏必须停在「活动关卡列表」页**：MAA Copilot 只从这里往后接管（它不导航进活动）。
4. **导航只在多作业路径**：单作业 `filename` 模式**不导航**。脚本用的就是 `copilot_list`。
5. **作业必须有非空 `actions`**：列表接口不返回，须 `/copilot/get/<id>`。
6. **练度不足**：脚本固定带 `ignore_requirements=true`。
7. **编队**：脚本固定 `formation_index=4`（**只用第四编队，不动用户其它编队**）。
8. **失败退理智**：非三星=失败但退理智，可换候选重试（`--try`）。
9. **同关首个候选未必过**：实测 YW-5 首候选失败，"挂件兼容/单核低配"系列才过。

## 干员比对口径（**用户铁律，2026-10-10 定**）
- **能不能抄的唯一标准 = 作业要求的每个干员槽都是「精二(E2)及以上」**：
  - 个人干员槽：必须 owned 且 `elite >= 2`；**缺 / 非精二 → 这套作业不抄**。
  - 备选组 `groups`：组内**至少 1 名** E2+ 才算满足；否则不抄。
  - 等价于 `score(own, c) == (0, 0, 0, 0)`（未拥有=0、空组=0、低练=0、低练组=0）。
- **不要用 `ignore_requirements` 兜底**硬凑练度不齐的作业（实测：核心 `澄闪` Lv1 硬打 GO-EX-4 会卡在编队/翻车）。
- **数据源：默认走森空岛在线**（MCP `ark_operbox_online` 或 `skland_box.fetch_operbox()`，
  含 elite/skill_lvl/spec/favor）。森空岛 401 = 凭证过期，先 `python scripts/skland/skland_cli.py status` 续期；
  **仅当森空岛不可用**才退回 MAA 干员箱 `C:\MAA\data\OperBoxData.json`（只有 elite/level，无技能/专精）。
  > 两者 elite/level 实测一致；但森空岛更全，优先。
- 本号现状（2026-10-10，森空岛 341 条 / 337 owned）：**精二+ 共 58 名**，
  名单落盘 `%TEMP%\opencode\e2set_online.json`（键 `e2`/`e1`）。以后比作业/练度直接用这份。

## 基建口径（**用户铁律**）
- **每次基建都按 `C:\Users\39007\Desktop\明日方舟排班报告.html` 的《搓玉 · 合成玉》方案**执行
  （A 班 / B 班 各 720 分钟；两班轮换）。这是"要合成玉"时的方案。
- **核对方法**：森空岛 MCP `ark_infrast_status` 拉当前各设施进驻干员 → 与方案**逐设施比对**
  （宿舍=「自动填充」，不校验；其余：控制中枢/贸易站×2/制造站×4/发电站×3/会客室/办公室）。
- 2026-10-10 核对：当前基建 **= 《搓玉 · 合成玉》A 班，逐设施完全一致**。
- 方案关键：贸易站 2 卖**源石碎片→合成玉**；制造站 2 产**源石碎片**；其余制造站产经验书/赤金。
  理智侧配套：固源岩日缺 ≈92.4 → 刷 **1-7**（详见报告「理智规划」）。

### 队列轮换（每 ~12h 一次；**用户安排：由我执行**，2026-10-10 定）
**前提**：MAA 支持「菲亚梅塔置换心情值」。《搓玉》里 **但书 两班都在**、心情掉得快 →
每轮换班前**先用菲亚梅塔置换「但书」的心情**。

**步骤（最快路径）**：
1. 先用**菲亚梅塔**置换**但书**的心情（MAA 的菲亚梅塔功能）。
2. 游戏进入：**基建 → 进驻总览 → 第一行的「编辑队列」**。
3. 面板一次显示一个房间（标题右侧 `房间 n/13`）。**每个房间依次点两个框**：
   - **目标队列行右端的 `⇄`**（青色高亮，如「队列2」行右端的 ⇄）→ 把该房间切到目标队列；
   - **面板右侧的大 `⟫`** → 进入下一个房间。
   > 执行前**先截图确认这两个按钮的语义**（本次是用户口述 + 截图，未实机复核）。
4. 重复到**全部 13 个房间**都换完；**所有房间必须同步换**（同一轮方向一致）。
5. **方向每轮交替**：本轮 `队列1→队列2`，下轮 `队列2→队列1`，再下轮又 `1→2`…
6. 换完**打时间戳**进 `scheduling/data/infrast_rotation_log.jsonl`；**必须间隔 ≥12h** 才换下一轮。

**判断当前跑的是哪个队列**：森空岛 `ark_infrast_status` 看控制中枢/贸易站进驻，与方案 A/B 班名单比对
（A、B 班名单见本 skill 上方与报告 HTML）。

> 时间线：**2026-10-10 13:15 用户手动完成**（队列1→队列2）→ **下一轮到期 ≥ 2026-10-11 01:15**，
> 方向 `队列2→队列1`。
>
> MAA 侧佐证：`C:\MAA\resource\custom_infrast\*.json` 是一图流导出的**自定义排班**，每套含
> `plans[].Fiammetta`（**菲亚梅塔心情置换**）块 → MAA 确实支持；本号《搓玉》方案未导出成该格式，
> 故每轮换班走「游戏内 UI 手点」。若以后想全自动，可把这套 A/B 排班导成 custom_infrast json。
