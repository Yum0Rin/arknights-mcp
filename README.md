# arknights-mcp

> **它是干什么的**：给 AI Agent（比如 opencode / 各种 LLM）装一双"**看得懂明日方舟画面**"的眼睛
> 和一双"**能点方舟按钮**"的手，再配一套"**查你自己账号数据**"的能力，把日常方舟操作交给 AI 去跑。
>
> **目标**：让 Agent **确定性地**观察和操作明日方舟。所谓"确定性"——识别全部走
> **MAA(MaaCore) 的模板匹配 / OCR**，**不用 AI 读图**；Agent 只负责调用工具、读结构化 JSON。

---

## 🎯 它能干什么（先看这个）

| 你想干嘛 | 它会怎么帮你 | 相关工具 / 脚本 |
|---|---|---|
| **让 AI 看懂当前画面** | 截图 → MAA 模板/OCR → 说出"现在在哪一屏、按钮在哪、识别到什么" | `ark_screenshot` / `ark_where` / `ark_find` |
| **让 AI 操作游戏** | 点按 / 滑动 / 按键，或整段交给 MAA 跑 | `ark_tap` / `ark_swipe` / `ark_key` / `ark_run_task` |
| **挂日常** | 一条调用跑 MAA 内置任务：刷理智 / 收菜 / 公招 / 领奖励 / 肉鸽… | `ark_run_task("Fight"/"StartUp"/"Infrast"/…)` |
| **查自己的账号数据** | 干员箱（含精英/等级/潜能，在线版还有技能/专精）、仓库、基建状态 | `ark_operbox` / `ark_depot` / **`ark_operbox_online`** / **`ark_infrast_status`** |
| **自动打活动关（抄作业）** | 抓作业站 → 比对本人干员箱 → MAA 逐关自动战斗通关 | `scripts/event-copilot/` |
| **基建智能排班 + 收益报告** | 一图流算最优排班、精二收益、理智规划，输出单文件报告 | `scheduling/` |
| **该练谁** | 按作业站挂机作业的干员出现率，排"优先精二/培养"名单 | `scheduling/tools/oper_appearance.py` |

一句话：**把"打开模拟器手动点方舟"这件事，变成 AI 能帮你做的工具调用。**

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

## 🧰 工具一览

| 工具 | 作用 |
|---|---|
| `ark_version` | 版本 / 后端信息（MaaCore 版本、依赖状态） |
| `ark_connect` | 连接模拟器（默认雷电 `127.0.0.1:5555`） |
| `ark_status` | 连接 / 运行状态 |
| `ark_screenshot` | 截图存 PNG，返回路径 |
| `ark_tap` / `ark_swipe` / `ark_key` | 点击 / 滑动 / 按键 |
| `ark_run_task` | 运行任意 MAA 任务（可带 params） |
| `ark_operbox` | 干员箱识别（MAA，精英/等级/潜能） |
| `ark_depot` | 仓库识别（MAA，物品数量） |
| `ark_operbox_online` | **在线**干员箱（森空岛，**免模拟器**，含技能/专精） |
| `ark_infrast_status` | **在线**基建状态（森空岛，免模拟器） |
| `ark_list_tasks` | 列出 MAA 内置任务名 |
| `ark_find` | 模板匹配（复用 MAA 模板库），返回命中矩形 + 中心点 |
| `ark_where` | 页面识别：对一组"页面锚点"模板做匹配，判断当前在哪一屏 |
| `ark_read_log` | 读取本 MCP 日志尾部 |

## 📝 用法示例

1. 连接并看当前画面：

```
ark_connect()
ark_screenshot()            # → {path: "...\ark_shot_...png"}
```

2. 复用 MAA 模板定位并点击（Agent 无需读图）：

```
ark_find("OperBox/OperBoxFlagElite2.png", threshold=0.85)
# → {matches:[{cx:..., cy:..., score:...}]}
ark_tap(cx, cy)
```

3. 拿干员箱 / 仓库（二选一：MAA 识别 or 在线）：

```
ark_operbox(save_to="box.json")   # MAA 识别（需模拟器）
ark_operbox_online()              # 在线（免模拟器，含技能/专精）
ark_depot()                       # 仓库（仅 MAA 有）
```

4. 跑日常任务：

```
ark_run_task("StartUp", {"enable": true, "client_type": "Official", "start_game_enabled": true})
ark_run_task("Fight",  {"enable": true, "stage": "CE-6", "times": 5})
```

## 📁 目录结构（monorepo）

```
arknights-mcp/
├─ arknights_mcp.py         # MCP 服务器本体（stdio）
├─ docs/
│  ├─ FINDINGS.md           # 踩坑 / 留痕
│  ├─ DATA-SOURCES.md       # 数据来源与取数方法（企鹅物流 / PRTS / 一图流 / 森空岛）
│  └─ WORKFLOW-活动关作业.md
├─ scripts/
│  ├─ event-copilot/        # 子项目：自动打活动关（抄作业）
│  ├─ skland/               # 子项目：森空岛在线取数（免模拟器）+ GUI 看板
│  └─ maa-autoclose/        # 子项目：MAA 跑完自动关雷电
├─ scheduling/              # 子项目：基建排班 + 报告 + 理智规划
├─ CHANGELOG.md  README.md  requirements.txt  AGENTS.md
└─ .gitignore
```

## 🔧 依赖

- Windows（本机为 Windows 11 + 雷电模拟器 LDPlayer9）
- Python 3.10+（实测 3.14）
- `mcp`（含 FastMCP）、`opencv-python-headless`、`numpy`
- 已安装 **MAA**（提供 `MaaCore.dll` 与 `resource/`；Python 绑定在 `C:\MAA\Python`）
- 已安装 **adb**（雷电自带：`C:\leidian\LDPlayer9\adb.exe`）

> 只用**在线取数 / GUI 看板**（`scripts/skland/`）：不需要 MAA / 模拟器，核心仅标准库；界面需 `customtkinter`。

```powershell
python -m pip install -r requirements.txt
```

## ⚙️ 配置（环境变量，均可选）

| 变量 | 默认 | 说明 |
|---|---|---|
| `ARK_MAA_PATH` | `C:\MAA` | MAA 安装目录（含 MaaCore.dll、resource、Python） |
| `ARK_ADB` | `C:\leidian\LDPlayer9\adb.exe` | adb 可执行文件 |
| `ARK_ADDR` | `127.0.0.1:5555` | 设备地址 |
| `ARK_TOUCH` | `maatouch` | 触控方式：`maatouch` / `minitouch` / `adb` |
| `ARK_LOG` | `%TEMP%\arknights-mcp.log` | 日志文件 |

## 🚀 在 opencode 中注册

编辑 `~/.config/opencode/opencode.json`，在 `mcp` 下加入：

```json
"arknights": {
  "type": "local",
  "command": [
    "C:\\Python314\\python.exe",
    "C:\\path\\to\\arknights-mcp\\arknights_mcp.py"
  ],
  "enabled": true,
  "environment": { "PYTHONIOENCODING": "utf-8" }
}
```

重启 opencode 后即可使用 `ark_*` 系列工具。**首次用在线取数**：`python scripts/skland/skland_cli.py login` 存一次凭证。

## ⚠️ 已知限制

- `OperBox` / `Depot` 等识别依赖 MAA 与游戏 UI 版本匹配；识别不全时先排查起始页面与游戏 UI 主题（见 `docs/FINDINGS.md`）。
- 同一时刻**只应有一个客户端**（本 MCP 或 MAA GUI）驱动同一台设备，否则会争抢 adb / 触控。
- 在线取数**拿不到抽卡记录**（接口无此项），也**拿不到仓库**（只有 MAA 有）；凭证会过期，需重新登录。
- MCP 服务器为长驻进程，MaaCore 只加载一次。

## 📜 版本

见 [CHANGELOG.md](CHANGELOG.md)。
