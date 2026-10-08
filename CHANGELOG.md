# CHANGELOG

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，
版本号遵循 [语义化版本 SemVer](https://semver.org/lang/zh-CN/)。

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
