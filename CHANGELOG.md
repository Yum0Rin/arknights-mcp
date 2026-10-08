# CHANGELOG

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，
版本号遵循 [语义化版本 SemVer](https://semver.org/lang/zh-CN/)。

## [0.2.0] - 2026-10-09
### Added
- **`ark_where`**：页面识别工具。用 MAA 模板做"页面锚点"（`QuickSwitch/*` 底部导航 +
  `Depot/DepotAllTab` + `InfrastPic/InfrastOverview` 等），模板匹配判断"当前在哪一屏"，
  返回命中页面与分数字段；支持 `custom` 传入 `{页面名: 模板名}` 覆盖/追加锚点。
  → Agent 无需 AI 读图即可知道所处页面。
- `DEFAULT_ANCHORS` 锚点表（首页/终端/干员/基建/采购中心/公开招募/干员寻访/菜单/仓库/基建总览）。
### Changed
- 抽出 `_grab_screen()` / `_match()` 复用逻辑，`ark_find` 改为调用之（行为不变）。

## [0.1.1] - 2026-10-09
### Fixed
- **序列号自动探测**：雷电同时暴露 `127.0.0.1:5555` 与 `emulator-5554`（同一设备），
  导致 adb 报 `more than one device`；现优先选 `ARK_ADDR`，其次 `emulator-*`，并在每次 adb
  调用前确保已选定（`_ensure_serial`）。
- **修复截图损坏**：`exec-out screencap -p` 为二进制安全，去掉误加的 `\r\n → \n` 替换
  （此前会损坏 PNG，导致 cv2 读取失败）。
### Verified
- MCP 客户端联调通过：`ark_version`(MaaCore v6.18.0) / `ark_list_tasks` / `ark_screenshot`(有效 PNG)
  / `ark_find`（模板匹配阳性验证 score=1.0，位置精确）。

## [Unreleased]
### 计划
- `ark_ocr`：接入 MAA 的 OCR，读取任意 ROI 文本。
- 任务序列编排（一次调用跑多个任务并返回分步结果）。
- `ark_find` 支持模板批量匹配与去重阈值。

## [0.1.0] - 2026-10-09
### Added
- 初版 MCP 服务器 `arknights_mcp.py`（stdio）。
- 基于 MaaCore 的识别封装：
  - `ark_operbox` 干员 box 识别（精英/等级/潜能/稀有度）。
  - `ark_depot` 仓库识别（物品数量）。
  - `ark_run_task` / `ark_list_tasks` 运行任意 MAA 内置任务。
- 基于 adb 的操作原语：`ark_tap` / `ark_swipe` / `ark_key` / `ark_screenshot`。
- 复用 MAA 模板库的确定性模板匹配：`ark_find`（OpenCV `matchTemplate`，支持 alpha 掩膜）。
- 连接与状态：`ark_connect` / `ark_status` / `ark_version`。
- 留痕：所有 adb 调用与关键事件写入日志文件，`ark_read_log` 回看。
- 工程要素：README、CHANGELOG、requirements.txt、.gitignore、docs/FINDINGS.md。
