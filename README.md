# arknights-mcp

> **使命**：让 AI **每天接管你的《明日方舟》账号**——读账号状态 → 按判据决策 → 自动跑完日常与活动<br>
> → 把进度回写，形成**闭环、长期自主运转**。你不再需要"每天打开模拟器手动点方舟日常"。<br>
>
> 识别与操作全部走 **MAA(MaaCore) 的确定性模板匹配 / OCR**（不用 AI 读图），账号数据来自<br>
> **MAA 识别 + 森空岛官方接口**，操作只走 MAA 提供的官方能力。

---

## 🎯 这是什么（目的）

**把"每天打开模拟器手动点方舟日常"这件事，交给 AI 自动驾驶。**

明日方舟本质上是一个**运筹学 / 资源规划游戏**：理智 → 资源 → 练度 → 抄作业 → 再产出资源，循环往复。
本项目把这条决策链**工具化、自动化**——让 AI 读你的账号状态、按判据决策、执行日常与活动、再把进度回写，
形成闭环、长期自主运转。

- **演进目标**：从"agent 全程监工"逐步走到 **"一开始写好脚本 → 跑完发结束信号 → agent 只做简单验收"**——
  类似 MAA 的"一键长草"，但**更智能**：会依据你本人的库存 / 需求 / 活动期限做决策，而不是跑固定脚本。
- **为什么值得**：省下每天重复操作的时间；决策按"你现在缺什么、活动还剩几天"来，比把流程记死更贴合。

## 🔄 它怎么运转（闭环）

1. **读状态**：取本人账号快照——干员箱 / 基建进驻 / 库存（写入 `docs/state.json`）。
2. **判触发 · 决策**：到达周期点（每日兜底 / 基建换班 / 剿灭周重置 / 活动变动）就按判据重算计划——
   养谁、理智怎么分、刷哪关、换什么（判据见 [`docs/MASTER-PLAN.md`](docs/MASTER-PLAN.md)）。
3. **执行**：调 MAA 内置任务或子项目脚本（刷关 / 基建 / 公招 / 活动抄作业 / 签到…）。
4. **回写**：把进度写回 `docs/state.json`，并留痕到日志。
5. **循环**：下一轮从第 1 步继续——长期自主运转。

> 循环协议见 [`docs/STATE.md`](docs/STATE.md)。

## 🚀 快速开始

```powershell
# 1) 装依赖（Windows + Python 3.10+；已装 MAA 与雷电模拟器 LDPlayer9）
python -m pip install -r requirements.txt

# 2) 首次用在线取数：登录森空岛存一次凭证（免模拟器）
python scripts/skland/skland_cli.py login
```

3. 在 `~/.config/opencode/opencode.json` 的 `mcp` 下注册 `arknights`（完整片段见 [`docs/FEATURES.md`](docs/FEATURES.md)），重启 opencode。
4. 对 Agent 说一句"跑一下今天的方舟日常"，它便会读 `docs/state.json`、按判据执行、回写进度。

> 详细安装 / 环境变量 / 注册片段 / 全部 `ark_*` 工具与用法 → **[`docs/FEATURES.md`](docs/FEATURES.md)**。

## 🌿 一键长草（2026-10-11 新增）

把"今天 / 这周该打什么"变成**规则写死的确定性计划**，一键直驱 MaaCore 跑完。

- **入口**：桌面快捷方式「**明日方舟·助手**」→ `pythonw scripts/skland/skland_gui.py`
   - 「长草」tab：`直驱跑一键长草`（跑**当天那一份**，自动带**连战**）/ `写 MAA 配置`（也只写当天）
  - 「快捷工具」卡：`启动游戏`（含拉起雷电）/ `打开 MAA`
- **规划器**：`scheduling/tools/plan_week.py`（规则写死在文件顶部 `RULE`）
  ```
  预算(自然+周药+理智药) → R1 剿灭 → R2 固源岩下限 → R2.5 EX/S 首通
                        → R3 活动(按商店封顶) → R3.5 培养 → R4 1-7 填充 → R5 每日分配
  ```
  产出 **`scheduling/data/weekly_plan.json`**（单一事实源）。
- **培养成本**：`oper_cost.py` + `material_cost.py` —— 官方 `character_table` 给材料清单，
  企鹅物流给掉落率，加工站配方给**合成**（**先用库存、能合就合**），再折算理智 + 精英化龙门币。
- **汇总网页**：`build_site.py` → `scheduling/报告/汇总.html`（本周/每日/上线建议/培养进度/一键长草思路/周报/排班）；
  「公招贴词条 → 推荐」由 `site_server.py` 提供后端。
- 现状·坑·命令速查 → **[`docs/STATE-一键长草.md`](docs/STATE-一键长草.md)**（on-call 先读）；
  设计见 `docs/PLAN-一键长草.md`、`docs/PLAN-培养与规划逻辑.md`。

## 🧭 账号数据两条路（重要）

拿"本人账号数据"有两种来源，**只读查询优先走在线**：

| 路径 | 工具 | 需要什么 | 给什么 |
|---|---|---|---|
| **MAA 识别** | `ark_operbox` / `ark_depot` | 开雷电 + 游戏 + MAA，干员约 50s | 干员箱(精英/等级/潜能)、**仓库** |
| **森空岛在线** | `ark_operbox_online` / `ark_infrast_status` | **只联网 + 凭证，免模拟器** | 干员箱(**含技能等级/专精/模组/信赖**)、**基建状态**、可扩展公招/剿灭/肉鸽/签到 |

- **在线 = 官方服务器快照**，与游戏画面同源（实测与 MAA 对拷 337 干员精英/等级/星级全一致）。
- **仓库只有 MAA 有**；**改基建 / 打关**等操作仍走 MAA。详见 [`AGENTS.md`](AGENTS.md) 与 [`docs/DATA-SOURCES.md`](docs/DATA-SOURCES.md) §7。

## 🧠 原理（为什么不用 AI 读图）

```
┌─────────────┐   adb screencap    ┌────────────────────┐
│  模拟器/游戏 │ ─────────────────▶ │  ark_find (OpenCV)  │  模板匹配 → 命中坐标
│  (明日方舟)  │                    │  MaaCore 任务流水线  │  OCR / 识别 → 结构化结果
└─────────────┘ ◀───────────────── └────────────────────┘
        ▲            adb input tap/swipe         │
        └────────────────────────────────────────┘
```

- 模板来源：`C:\MAA\resource\template\**.png`（MAA 自带）；任务流水线：`C:\MAA\resource\tasks\tasks.json`。
- 识别结果是一串坐标 / 结构化 JSON，**不用把图片喂给模型**，省 token 也更稳。

## 📁 目录结构（monorepo）

```
arknights-mcp/
├─ arknights_mcp.py         # MCP 服务器本体（stdio）
├─ docs/                    # 文档（入口 = docs/README.md 索引）
│  ├─ README.md             # 文档索引
│  ├─ FEATURES.md           # 功能与用法手册（工具 / 示例 / 安装 / 配置 / 注册）
│  ├─ MASTER-PLAN.md        # 运筹总指挥：目标→数据→决策→执行→复盘 + 铁律 + 判据
│  ├─ STATE.md / state.json / ops_manual.json  # 循环协议 / 状态 / 操作手册
│  ├─ WORKFLOW-活动关作业.md · WORKFLOW-仓库取数.md  # 工作流
│  ├─ DAILY-CHECKLIST-act52side.md  # 当期活动每日清单
│  ├─ DATA-SOURCES.md       # 数据来源与取数方法
│  └─ FINDINGS.md           # 踩坑 / 留痕
├─ scripts/
│  ├─ event-copilot/        # 子项目：自动打活动关（抄作业）
│  ├─ skland/               # 子项目：森空岛在线取数（免模拟器）+ GUI 看板
│  └─ maa-autoclose/        # 子项目：MAA 跑完自动关雷电
├─ scheduling/              # 子项目：基建排班 + 报告 + 理智规划 + 活动经济
├─ .opencode/skills/        # opencode skills（可复用操作手册）
├─ CHANGELOG.md  README.md  requirements.txt  AGENTS.md
└─ .gitignore
```

## 📚 文档导航

| 从哪开始 | 看什么 |
|---|---|
| **功能 / 工具 / 用法 / 安装注册** | [`docs/FEATURES.md`](docs/FEATURES.md) |
| **全部文档索引（判据 / 循环 / 工作流）** | [`docs/README.md`](docs/README.md) |
| **运筹总指挥（怎么算）** | [`docs/MASTER-PLAN.md`](docs/MASTER-PLAN.md) |
| **当前状态 / 进度** | [`docs/state.json`](docs/state.json) |
| **踩坑留痕** | [`docs/FINDINGS.md`](docs/FINDINGS.md) |
| **数据源与取数** | [`docs/DATA-SOURCES.md`](docs/DATA-SOURCES.md) |

> `.opencode/skills/` 是 opencode 的 skill（agent 按需加载的操作手册），不在 `docs/` 下。

## 🚧 边界与限制

- **本人账号自用**：不涉及外挂 / 注入；操作只走 MAA 提供的官方能力。
- **确定性识别**：识别走 MAA 模板匹配 / OCR，**不用 AI 读图**。
- 同一时刻**只应有一个客户端**（本 MCP 或 MAA GUI）驱动设备；识别依赖 MAA 与游戏 UI 版本匹配。
- 在线取数**拿不到仓库、拿不到抽卡记录**，凭证会过期需重登。其余已知限制详见 [`docs/FEATURES.md`](docs/FEATURES.md)。

## 📜 版本

见 [CHANGELOG.md](CHANGELOG.md)。
