# 决策循环协议（STATE）

> 让"玩方舟"自动运转的**自治循环**。三件事分开存，别混：
> - **状态**在 `docs/state.json`（机器可读，单一事实源，每次读写）；
> - **知识/判据**在 `docs/MASTER-PLAN.md`（怎么算、怎么选）；
> - **操作**在 `docs/ops_manual.json`（怎么点，边做边记）。
> agent 每次醒来：**读状态 → 判触发 → 执行（A 类调任务 / B 类查手册或现学）→ 回读 → 调整 → 回写**。

---

## 1. 什么时候决策（DECIDE）

决策 = 重新计算"接下来做什么"，产出/更新 `state.json.plan`。任一触发即决策：

1. **周期兜底**：每天醒来第一次（每天至少决策一次）。
2. **基建**：交给 MAA `Infrast` `mode=20000`（队列轮换）自己按「当前班心情 0」触发；`triggers.infra_next_swap_at` 仅作参考/核对用，不再是我们的动作触发点。
3. **剿灭周重置**：每周一（周上限 1800 玉）。
4. **活动数据变动**：EX 开放 / 商店补货 / 代币变化 / 活动开始或结束。
5. **森空岛凭证 401**：先 `skland_cli.py status` 续期，再决策。
6. **干员箱变化**：抽到新干员（重跑 `oper_appearance.py`）。
7. **偏差触发**：执行结果 ≠ 计划预期（见 §3）。

决策动作：按 MASTER-PLAN 判据链「定目标集 → 算需求 D → 减库存 S → 缺口 G → 挑供给」，更新 `state.json` 的 plan / progress / triggers。

---

## 2. 什么时候执行（EXECUTE）

决策产出 plan 后，按 `state.json.plan.daily_todo_priority` 顺序执行。执行分两类：

- **A 类（MAA 内置任务）**：直接 `ark_run_task(...)`。刷关 Fight / 基建 Infrast / 公招 Recruit / 领奖 Award / 寻访 Gacha / 信用商店 Mall / 剿灭 / Copilot / Depot / OperBox。长任务用 `wait=False` + `ark_task_result()` 轮询。
- **B 类（无内置，须手点）**：查 `docs/ops_manual.json`。
  - 已学 → 按 `ops[].steps` 复用（判据→坐标/模板→tap→验证）。
  - 未学 → 走 §4 学习模式，现做现记。

执行前提（每次都要核对）：

1. 单客户端（关 MAA GUI / 其它 arknights MCP）。
2. MAA 空闲；跑设备任务前先 `ark_connect`。
3. 活动关：游戏停在活动关卡列表页。
4. 失败可重试：活动关失败退理智不亏，`--try` 换候选划算。

---

## 3. 什么时候调整计划（ADJUST）

调整 = 因偏差/新信息重算 plan 或改参数。触发条件：

1. 执行回读 ≠ 预期：作业失败、代币不足、库存不足、掉落不符、练度卡编队。
2. 数据源刷新：企鹅/PRTS 出新掉落率或商店价。
3. 用户改铁律 / 新目标。

调整动作：按 MASTER-PLAN 判据链重算，更新 `state.json.plan` + `progress`；若属于"数据文件过期"，重刷 `event_<id>.json` 并重跑 `event_economy.py`。

---

## 4. 操作学习（LEARN）—— 培养干员这类操作的核心机制

B 类操作（培养干员：升级/精英化/技能/模组；进商店翻页；活动切栏）**第一次做 = 学习模式**，五步闭环：

> 注：**基建已不算 B 类**——2026-10-12 起交给 MAA 自带 `Infrast` `mode=20000`（队列轮换）承担，无需现学/记坐标（旧 `infrast_rotation.py` 已归档 `历史版本/`）。若 MAA 队列轮换失效，才回退手点（此时按学习模式补记）。

1. `ark_screenshot` 截图，看当前画面。
2. `ark_where` / `ark_find` / 本地 OCR 定位目标按钮（坐标或模板）。
3. `ark_tap` 点击。
4. `ark_screenshot` 验证生效（页面变了 / 数值变了）。
5. 把这一步写进 `docs/ops_manual.json` 的 `ops[].steps`（判据 + 坐标/模板 + 动作 + 验证）。

> 原则：**识别成功一次就记下来复用**（同 `scheduling/data/event_tab_switch.json` 的做法）。
> 坐标基于 1920×1080；翻页用 MAA `Custom` + `SlowlySwipeToThe*`（本机 adb swipe 失效）。
> 每个操作记完整后，`status` 从「待学」→「已会」，下次直接按 steps 复用，不再现学。

---

## 5. 记录（RECORD）

每次决策/执行/学习/调整后回写 `state.json`：

- `cycle.last_decision_at` / `cycle.last_execution_at`。
- `progress`（首通、代币、兑换、待养、剿灭）。
- `inventory`（库存快照，能取到就填）。
- `log` 追加一条 `{ts, action, result}`。
- 基建改由 MAA `Infrast` `mode=20000` 承担后**不再单独写** `infrast_rotation_log.jsonl`（该文件仅存历史）。

---

## 6. 标准序列（每次醒来的动作）

0. **MAA 更新检查**：`python scripts/maa-update/maa_update.py check`；有更新则 `apply`（资源更新后**需重启 MCP 生效**）。
1. 读 `docs/state.json` + 本协议 + `scheduling/data/weekly_plan.json`（含 `daily`）+ `run_report.jsonl`。
2. 森空岛取数：`ark_infrast_status`（基建当前班）+ `ark_operbox_online`（干员箱）。
3. 判 §1 触发 → 触发就跑 MASTER-PLAN 决策链，更新 plan。
4. 按 plan 执行（§2）：A 类调任务；B 类查 `ops_manual.json`，未学则 §4 学习。
5. 回读结果，判 §3 → 偏差则调整。
6. 回写 `state.json`（§5）。

---

## 7. 存储与快照纪律（防"信息滚雪球"）

> 原则：**状态小、快照大，两者分开；大快照不入库、只留最近 N 份。**
> 用户担忧：进度快照越堆越多会拖垮上下文 → 一律"只留摘要 + 定期清理"。

| 类别 | 例子 | 位置 | 入库 | 保留 |
|---|---|---|---|---|
| **权威状态（小、人读）** | 进度/触发/计划/库存摘要 | `docs/state.json` | ✅ | 只有一份，原地覆盖 |
| 操作知识 | UI 坐标/步骤 | `docs/ops_manual.json` | ✅ | 只有一份 |
| 决策知识 | 判据/公式 | `docs/MASTER-PLAN.md` | ✅ | 只有一份 |
| 事件日志（追加） | 换班/演练/执行 | `scheduling/data/*.jsonl`、`%TEMP%\arknights-mcp.log` | jsonl ✅ | 追加，定期归档 |
| **大快照（易膨胀）** | 干员箱 / 仓库 / 作业候选 / 商店 OCR | `scheduling/data/snapshots/` 或 `%TEMP%\opencode\ark\` | ❌ gitignore | **最近 3~5 份** |

**纪律（必须遵守）**：
1. agent 只把**结论 / 差分**写进 `state.json`，**绝不把整份快照贴进对话或 state.json**。
2. 快照命名 `<类型>-<YYYYMMDD-HHMM>.json`；写入前清理超量旧文件（**走回收站**，先列确切清单再逐项删，禁通配删）。
3. 长期要留的关键数字只存**摘要**（如 "E2 共 58 名 + 名单"），不存原始全量 API 响应。
4. 森空岛 `dump` 默认落 `%TEMP%\opencode\skland-dump`，**不入库**。
5. 任务过程留痕落 `scheduling/data/*.jsonl`（追加一行），不要新建一堆 md。
