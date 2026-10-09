# AGENTS.md

`arknights-mcp` —— 把 MAA(MaaCore) 的识别 + 操作封装成 MCP，让 Agent 能**确定性**观察/操作明日方舟
（识别全走 MAA 的模板匹配/OCR，不用 AI 读图）。子功能：智能基建排班（`scheduling/`）。

> 详细的踩坑记录在 **`docs/FINDINGS.md`**（遇到问题先查它）。
> 取数/数据来源与 API 用法看 **`docs/DATA-SOURCES.md`**（企鹅物流 API、PRTS 数值、一图流、MAA）。
> 本仓库是 **monorepo**：`arknights_mcp.py`=MCP 本体；`scheduling/`=排班/报告/理智规划；
> `scripts/maa-autoclose/`=MAA 跑完自动关雷电（桌面有快捷方式 `MAA跑完自动关雷电.lnk`）。

## 环境

| 项 | 值 |
|---|---|
| Python | `C:\Python314\python.exe` |
| MAA | `C:\MAA`（MaaCore v6.18.0，绑定 `C:\MAA\Python`） |
| 模拟器 | 雷电 `C:\leidian\LDPlayer9`（adb 同目录） |
| 设备 | `127.0.0.1:5555`（=`emulator-5554`，同一台） |
| 游戏 | `com.hypergryph.arknights`（官服）；账号「博士」 |

## 铁律（违反就出问题，务必遵守）

1. **操作游戏只用 MAA 本身的功能，别用 adb 注入**：`adb input swipe` 滑动会失效；
   识别也要用 MAA 的模板/OCR，不要自己造 CV。
2. **跑识别前确认 MAA 处于"空闲"态**：`StartUpSettings.RunDirectly=True` 会让 MAA 一启动就
   自动跑日常队列 → 识别按钮 disabled、点不动。需要识别时先停下任务（或等其跑完）。
3. **触控模式必须 `MaaTouch`**（`ConnectSettings.TouchMode`）：本机 `MiniTouch` 已损坏
   （日志 `MinitouchController ... read timeout`），会导致所有翻页失效。
4. **日志写文件**（`%TEMP%\arknights-mcp.log`）；**stdout 留给 MCP 传输，绝不 print**。
5. **adb 命令带 `-s 127.0.0.1:5555`**（否则报 `more than one device`）。
6. **删文件走回收站**（见全局 `AGENTS.md`）；同一时刻只让**一个**客户端驱动设备。

## 约定

- 版本：`__version__` 语义化；可用改动进 `CHANGELOG.md`（Added/Changed/Fixed/Verified）并 git commit。
- 识别产物：`C:\MAA\data\OperBoxData.json` / `DepotData.json`（仅 MAA GUI 会写）。
- 改 MAA 配置：改 `C:\MAA\config\gui.new.json`（活动的连接/设置都在这），**MAA 运行中改会被覆盖**，
  需先退出再改。
