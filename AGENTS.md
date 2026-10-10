# AGENTS.md

`arknights-mcp` —— 把 MAA(MaaCore) 的识别 + 操作封装成 MCP，让 Agent 能**确定性**观察/操作明日方舟
（识别全走 MAA 的模板匹配/OCR，不用 AI 读图）。子功能：智能基建排班（`scheduling/`）、
活动关作业自动化（`scripts/event-copilot/`，工作流见 `docs/WORKFLOW-活动关作业.md`）、
森空岛在线取数/看板（`scripts/skland/`，**免模拟器**读本人账号数据）。

> 详细的踩坑记录在 **`docs/FINDINGS.md`**（遇到问题先查它，§14 是活动关作业，§17 是森空岛接口）。
> 取数/数据来源与 API 用法看 **`docs/DATA-SOURCES.md`**（企鹅物流 API、PRTS 数值、一图流、MAA、森空岛）。
> 本仓库是 **monorepo**：`arknights_mcp.py`=MCP 本体；`scheduling/`=排班/报告/理智规划；
> `scripts/skland/`=森空岛在线取数；`scripts/maa-autoclose/`=MAA 跑完自动关雷电。

## 环境

| 项 | 值 |
|---|---|
| Python | `C:\Python314\python.exe` |
| MAA | `C:\MAA`（MaaCore v6.18.0，绑定 `C:\MAA\Python`） |
| 模拟器 | 雷电 `C:\leidian\LDPlayer9`（adb 同目录） |
| 设备 | `127.0.0.1:5555`（=`emulator-5554`，同一台） |
| 游戏 | `com.hypergryph.arknights`（官服） |

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

## 抄作业 & 基建：两条用户铁律（2026-10-10 定）

1. **作业筛选：只抄「全部干员槽都精二(E2)+」的作业**。个人槽必须 owned 且 `elite>=2`，备选组至少 1 名 E2+。
   取数**一律用森空岛**（`ark_operbox_online`，含技能/专精）；**仅当森空岛不可用**才退回 MAA 干员箱。
   森空岛 401 = 凭证过期 → `python scripts/skland/skland_cli.py status` 续期。
   **不许用 `ignore_requirements` 硬凑练度不齐的作业。**
2. **基建一律用《搓玉 · 合成玉》方案**（`C:\Users\39007\Desktop\明日方舟排班报告.html`，A/B 班各 720min）。
   核对：森空岛 `ark_infrast_status` 拉当前进驻 → 与方案逐设施比对（宿舍「自动填充」不校验）。
   > 详见 skill `arknights-event-copilot` 与 `docs/WORKFLOW-活动关作业.md`。

## 账号数据两条路：MAA 识别 vs 森空岛在线（**选之前先读这条**）

要拿"本人账号数据"，有**两套来源**，**优先用在线**（免模拟器、免等识别）：

| 路径 | MCP 工具 | 需要什么 | 给什么 |
|---|---|---|---|
| **MAA 识别** | `ark_operbox` / `ark_depot` | 开雷电 + 游戏 + MAA 空闲，干员 ~50s | 干员箱(elite/level/potential/rarity)、**仓库** |
| **森空岛在线** | `ark_operbox_online` / `ark_infrast_status` | 只联网 + 凭证 | 干员箱(**含技能等级/专精/模组/信赖**)、**基建状态**、可扩展公招/剿灭/肉鸽/签到 |

- **在线=官方服务器快照**，与游戏画面同源：实测与 MAA 对拷 337 干员 elite/level/rarity **全一致**
  （仅个别干员 potential 因 MAA 识别误差不同，**以在线为准**）。
- **仓库 Depot 只有 MAA 有**（森空岛接口不含仓库）；**改基建 / 打关**等操作仍必须走 MAA。
- 在线工具实现：`scripts/skland/skland_box.py`（把森空岛数据转成 `OperBoxData.json` **同构**，
  既有消费方 `event-copilot` / `oper_appearance` / `base_gap` / 一图流导入 **零改动**即可换源）。
- 取数细节（登录链、`sign` 签名、`dId`、字段映射）见 **`docs/DATA-SOURCES.md` §7**。
- **首次使用**：`python scripts/skland/skland_cli.py login` 存凭证到 `~/.arknights_skland.json`
  （会过期，重登即可）。GUI 看板：`scripts/skland/skland_gui.py`。
