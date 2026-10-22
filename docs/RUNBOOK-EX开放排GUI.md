# RUNBOOK：2026-10-16 EX 开放后，怎么排 MAA GUI / 打 EX

> 触发：**2026-10-16 16:00** 当期活动 `act52side` 的 EX 关开放（`state.json.triggers.event_ex_open`）。
> 目标：把 **EX-1→EX-8 普通首通 + 各自突袭** 打完（依次解锁、遇挫即停），并把进度回写。
> 关联：`docs/WORKFLOW-活动关作业.md`（作业工作流）、`docs/STATE-一键长草.md`（规则 R2.5/R2.6）、
> `docs/MAA-INTERNALS.md`（§2.10 Copilot `is_raid`、§3 关卡导航）。
> **单客户端铁律**：同一时刻只让一个程序驱动设备（MAA GUI / MCP / 脚本三选一）。

---

## Step 0　体检（开放前或当天，先跑这三条）

```powershell
# ① MAA 资源/软件有没有收录 EX 关（本机 resource 现在没有 → 需要 MAA 发版）
python scripts/maa-update/maa_update.py check

# ② 直接验「MAA Fight 导航能不能用」（resource 里有同名任务 = 能）
python -c "import json,pathlib;d=json.load(pathlib.Path(r'C:\MAA\resource\tasks\tasks.json').open(encoding='utf-8'));print('YW-EX-1 in tasks.json ->', 'YW-EX-1' in d)"

# ③ 作业站有没有 EX 关的可抄作业（E2+ 准入）
python scripts/event-copilot/event_copilot.py plan act52side
```

判据：
- **② 为 True**（resource 收录了 `YW-EX-*`）→ 可以走 **路径 A（MAA Fight 直刷）**。
- **② 为 False**（本机现状）→ 只能走 **路径 B（Copilot 链）**；A 不可用。
- ③ 某关 `候选 0` → 该关无作业，链会在那里停（见 Step 3）。

> 补充：`series` 上限不影响 EX（EX 首通是单次 `times=1`，不连战）。

---

## Step 1　选路径

| 路径 | 何时用 | 命令 |
|---|---|---|
| **A｜MAA Fight 直刷** | 仅当 Step 0② 为 `True`（resource 收录了 EX 关） | `python scripts/maa-week/maa_week.py write --date <当天>` → GUI 点开始（Step 6） |
| **B｜Copilot 链**（**主路**） | Step 0② 为 `False`（本机现状）或 A 跑不动 | `python scripts/event-copilot/event_copilot.py run act52side --chain ex --try` → 再 `--chain raid --try` |

- **路径 A 注意事项**：EX 关**不配药**（`weekly_plan.json.medicine_stages` 只有 `1-7`/`YW-6`）；`maa_week` 遇 MAA 导航不了的关会跳过并打印可复制命令。
- **路径 B 前置**：**游戏必须已停在活动关卡列表页**（能看到 YW-N 的地图）——脚本**不做**「从首页进活动」那一步；由上层 MCP/Agent 用 `ark_where`/`ark_find`/`ark_tap` 导航（见 `WORKFLOW-活动关作业.md` §3bis），或人工点到关卡列表。

---

## Step 2　排队顺序与依赖（**硬规则**）

1. **EX 必须 EX-1→EX-8 依次打**：EX-i 未通就打不了 EX-(i+1)（依次解锁）。`--chain ex` 已按此，且**遇挫即停**（某关无作业/失败 → 不打后面的）。
2. **每关普通通完，才排该关突袭**：`--chain raid` 只对「普通已通」的关排突袭，同样遇挫即停。
3. **只有 EX/S 有突袭**，普通关（YW-1..8）没有。
4. 计划侧同口径：`plan_week` 读 `progress.event_act52side`，只排**未通**的关、从第一个未通起的前缀链。

---

## Step 3　理智账（EX 首通 120 + 突袭 120 = 240）

- EX-1..8 每关理智 = 10/10/15/15/15/15/20/20（**待数据层用官方表复核**）。
- **首通 120 + 突袭 120 = 240 理智**；开放日（10-16）自然理智只有 **240**，且 **EX 不配药**（不吃药/少药）。
- 当天如果还排了剿灭（25），缺口约 **25**（见 `state.json.plan.pending_decisions` 那条「EX 日缺口 25」）。补法（三选一）：
  1. **提前留理智**：10-15 晚把理智花到 ≤ 低值，10-16 攒满 240 再打；
  2. **当天先用药刷别处再回来**：把当天 `1-7/YW-6` 的药量用完（`maa_week` 已同步 `medicine`），再手动/Copilot 打 EX；
  3. **分两天**：10-16 打 EX-1..4 普通+突袭，10-17 打 EX-5..8（`--chain` 会自动从「第一个未通」续）。
- 打完 EX 后如仍有理智，按 `weekly_plan.daily` 补 YW-6/1-7。

---

## Step 4　执行

### 路径 B（Copilot 链，主路）
```powershell
# 先确保：MAA GUI / 其它 MCP 已关；游戏停在活动关卡列表页
python scripts/event-copilot/event_copilot.py run act52side --chain ex  --try   # EX 普通首通（1→8）
python scripts/event-copilot/event_copilot.py run act52side --chain raid --try  # EX 突袭（需该关普通已通）
```
- 脚本**遇挫即停**并打印「卡在 EX-k」；若某关**无作业** → 该关手点/换作业，再从头跑 `--chain`（会自动跳过已通的）。
- 跑完/失败都会**回写** `docs/state.json.progress.event_act52side`（`ex_clear_done`/`raid_clear_done`/`*_pending`/`last_chain_note`）。

### 路径 A（MAA Fight 直刷）
```powershell
python scheduling/tools/plan_week.py --date 2026-10-16      # 重生成当天计划（EX 会进槽位，前提 resource 已收录）
python scripts/maa-week/maa_week.py write --date 2026-10-16 # 写 GUI（**先关 MAA**）
# → 打开 MAA GUI → 点「Link Start!」（见 Step 6）
```

---

## Step 5　核对与留痕（必做）

```powershell
# ① 对账：森空岛在线干员箱 + 进度字段
#    （MCP 工具）ark_operbox_online
python -c "import json;d=json.load(open(r'docs/state.json',encoding='utf-8'));print(d['progress']['event_act52side'])"

# ② 把结果写进 state.json.log + scheduling/data/run_report.jsonl
```
- 核对项：`ex_clear_done`（EX 普通已通清单）、`raid_clear_done`（突袭）、`ex_pending`/`raid_pending`（应为 0）。
- 留痕：`docs/state.json` 的 `log` 追加一条（做了什么/结果/证据），`scheduling/data/run_report.jsonl` 追加执行结果。
- 若用了 `--chain`，`last_chain_note` 已自动写入（如 `EX普通链：成功[…]；卡在 YW-EX-5`）。

---

## Step 6　MAA GUI 侧（要用户/我在 GUI 点开始时）

1. **先关 MAA**（`tasklist /FI "IMAGENAME eq MAA.exe"` 确认无），再写配置——运行中写会被覆盖：
   ```powershell
   python scripts/maa-week/maa_week.py write --date 2026-10-16
   ```
   （`write` 只刷当天：Fight 槽按关卡匹配、非当天槽 `IsEnable=false`；`Infrast.Mode=Custom`（`plan_index` 14:00→1 A班）；空 `OperProgress` 停用；`UseMedicine/MedicineCount` 同步当天药量。）
2. 启动 `C:\MAA\MAA.exe`，等主窗口就绪。
3. **点开始**（两种）：
   - 人工点界面右上角 **「Link Start!」**；
   - 或自动化（锁屏/后台也行，见 `FINDINGS.md` §7）：
     ```powershell
     # 用 UIAutomation 找主窗（class HwndWrapper[MAA;;…]）里的 Button 'Link Start!' → InvokePattern.Invoke()
     #   · 主窗 class 名：HwndWrapper[MAA;;…]；按钮 Name：'Link Start!'
     #   · Invoke 仅在按钮 IsEnabled=True 时有效（MAA 忙时 disabled → 报错）
     #   · 元素名用 Current.Name；中文乱码 → 写 UTF-8 文件再读
     ```
     脚本参考：`C:\Users\39007\.config\opencode\tools\gui-shot\gui_shot.ps1`（截图复核）。
4. 跑完看 `C:\MAA\debug\gui.log` 的「所有任务全部完成！」；**核对是否真吃到药**（Fight 槽 `UseMedicine=True`、日志有用药记录）。

> 实测参考（`state.json.log` 2026-10-12 20:08）：GUI 点「Link Start!」跑通当天队列；但当时 `UseMedicine=False` → 1-7 只跑 34/57（理智 205→1）。本轮已修（计划带药 + write 同步）。

---

## 失败 / 回滚

- **`--chain` 卡在 EX-k**：属预期（无作业/练度/未解锁）。先看日志的「无作业」提示 → 换作业站作业或手点该关，再重跑 `--chain`（自动续）。
- **MAA 导航不了 EX**（Fight `append_task` 返回 0）：确认 Step 0②，改走路径 B。
- **进度写坏**：`progress.event_act52side` 是普通 JSON；改坏了照 `first_clear_done/ex_clear_done/s_clear_done` 手工补即可（`plan_week` 缺失时当全未通）。
- **配置写坏**：`write` 会自动备份 `gui.new.json.bak-<时间戳>`，回滚即重命名。

---

## 相关文件

| 文件 | 作用 |
|---|---|
| `scripts/event-copilot/event_copilot.py` | 抓作业 + Copilot 链执行（`--chain ex/raid`，`is_raid`） |
| `scripts/maa-week/maa_week.py` | `show/write/run`（按天编辑队列、同步用药） |
| `scheduling/tools/plan_week.py` | 周计划（target 条件、活动让位、series 取整、逐日药量） |
| `scheduling/data/weekly_plan.json` | 计划唯一事实源（含 `daily`） |
| `docs/state.json` | 进度（`progress.event_act52side`）+ 触发 + 留痕 |
| `docs/WORKFLOW-活动关作业.md` | 作业工作流与坑（§2bis 解锁链、字段约定） |
