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
2. **基建换班到期**：`state.json.triggers.infra_next_swap_at` 已过且未执行。
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

B 类操作（培养干员：升级/精英化/技能/模组；进商店翻页；活动切栏；基建换班）**第一次做 = 学习模式**，五步闭环：

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
- 基建换班另写 `scheduling/data/infrast_rotation_log.jsonl`（带时间戳）。

---

## 6. 标准序列（每次醒来的动作）

1. 读 `docs/state.json` + 本协议 + `infrast_rotation_log.jsonl`。
2. 森空岛取数：`ark_infrast_status`（基建当前班）+ `ark_operbox_online`（干员箱）。
3. 判 §1 触发 → 触发就跑 MASTER-PLAN 决策链，更新 plan。
4. 按 plan 执行（§2）：A 类调任务；B 类查 `ops_manual.json`，未学则 §4 学习。
5. 回读结果，判 §3 → 偏差则调整。
6. 回写 `state.json`（§5）。
