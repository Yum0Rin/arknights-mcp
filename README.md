# arknights-mcp

> 明日方舟 MCP 服务器 —— 借用 **MAA(MaaCore)** 的识别能力，把"看屏幕 + 操作游戏"封装成
> MCP 工具，让 LLM Agent 能**确定性**地观察和操作明日方舟。

**识别原理与 MAA 完全一致：模板匹配(template matching) + OCR，属于确定性计算机视觉；
本 MCP 自身不使用任何 AI 读图 / AI 图像识别。** Agent 只负责调用工具、读取结构化结果。

---

## ✨ 特性

- **零 AI 读图**：识别全部交给 MaaCore（MAA）的模板匹配 / OCR，输出结构化 JSON。
- **既能识别、也能操作**：`ark_operbox` / `ark_depot` 拿数据；`ark_tap` / `ark_swipe` / `ark_run_task` 操作游戏。
- **细粒度原语**：`ark_find` 直接复用 MAA 模板库做任意模板匹配，返回命中矩形与中心点。
- **一键跑 MAA 任务**：`StartUp / Fight / Infrast / Recruit / Mall / Award / Roguelike ...` 任意内置任务。
- **留痕**：所有 adb 调用与关键事件写入日志文件，可用 `ark_read_log` 回看。

## 🧠 原理

```
┌─────────────┐   adb screencap    ┌────────────────────┐
│  模拟器/游戏 │ ─────────────────▶ │  ark_find (OpenCV)  │  模板匹配 → 命中坐标
│  (明日方舟)  │                    │  MaaCore 任务流水线  │  OCR / 识别 → 结构化结果
└─────────────┘ ◀───────────────── └────────────────────┘
        ▲            adb input tap/swipe         │
        └────────────────────────────────────────┘
```

- 模板来源：`C:\MAA\resource\template\**.png`（MAA 自带）。
- 任务流水线：`C:\MAA\resource\tasks\tasks.json`（MAA 自带）。
- 设备操作：`adb shell input tap/swipe/keyevent`。

## 📁 目录结构

```
arknights-mcp/
├─ arknights_mcp.py     # MCP 服务器本体（stdio）
├─ requirements.txt
├─ CHANGELOG.md         # 版本迭代记录
├─ README.md
├─ docs/
│  └─ FINDINGS.md       # 开发过程中的关键发现（留痕）
└─ .gitignore
```

## 🔧 依赖

- Windows（本机为 Windows 11 + 雷电模拟器 LDPlayer9）
- Python 3.10+（实测 3.14）
- `mcp`（含 FastMCP）、`opencv-python-headless`、`numpy`
- 已安装 **MAA**（提供 `MaaCore.dll` 与 `resource/`；Python 绑定在 `C:\MAA\Python`）
- 已安装 **adb**（雷电自带：`C:\leidian\LDPlayer9\adb.exe`）

安装依赖：

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
    "C:\\Users\\user\\Desktop\\arknights-mcp\\arknights_mcp.py"
  ],
  "enabled": true,
  "environment": { "PYTHONIOENCODING": "utf-8" }
}
```

重启 opencode 后即可使用 `ark_*` 系列工具。

## 🧰 工具一览

| 工具 | 作用 |
|---|---|
| `ark_version` | 版本 / 后端信息（MaaCore 版本、依赖状态） |
| `ark_connect` | 连接模拟器（默认雷电 127.0.0.1:5555） |
| `ark_status` | 连接 / 运行状态 |
| `ark_screenshot` | 截图存 PNG，返回路径 |
| `ark_tap` / `ark_swipe` / `ark_key` | 点击 / 滑动 / 按键（adb 注入） |
| `ark_run_task` | 运行任意 MAA 任务（可带 params） |
| `ark_operbox` | 干员 box 识别（精英/等级/潜能） |
| `ark_depot` | 仓库识别（物品数量） |
| `ark_list_tasks` | 列出 MAA 内置任务名 |
| `ark_find` | 模板匹配（复用 MAA 模板库），返回命中矩形+中心点 |
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

3. 拿干员箱 / 仓库：

```
ark_operbox(save_to="C:\\Users\\user\\Desktop\\box.json")
ark_depot()
```

4. 跑日常任务：

```
ark_run_task("StartUp", {"enable": true, "client_type": "Official", "start_game_enabled": true})
ark_run_task("Fight",  {"enable": true, "stage": "CE-6", "times": 5})
```

## ⚠️ 已知限制

- `OperBox` / `Depot` 等识别任务依赖 MAA 与游戏 UI 版本匹配；若识别不全，先排查起始页面与
  游戏 UI 主题（详见 `docs/FINDINGS.md`）。
- 同一时刻**只应有一个客户端**（本 MCP 或 MAA GUI）在驱动同一台设备，否则会争抢 adb/触控。
- MCP 服务器为长驻进程，MaaCore 只加载一次。

## 📜 版本

见 [CHANGELOG.md](CHANGELOG.md)。当前 v0.1.0。
