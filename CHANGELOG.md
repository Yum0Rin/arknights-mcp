# CHANGELOG

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，
版本号遵循 [语义化版本 SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]
### Added
- **森空岛在线取数接入 MCP（免模拟器）**：新增 MCP 工具 `ark_operbox_online`（干员箱，**多带技能等级/专精**）
  与 `ark_infrast_status`（基建状态，原先没有此查询）。适配器 `scripts/skland/skland_box.py` 把森空岛数据转成
  MAA `OperBoxData.json` **同构**，`event-copilot` / `oper_appearance` / `base_gap` / 一图流导入 **零改动换源**。
  实测与 MAA 对拷 337 干员 elite/level/rarity 全一致。文档：`AGENTS.md`「账号数据两条路」+ `docs/DATA-SOURCES.md` §7。
- **森空岛看板**（`scripts/skland/`，本地自用工具）：登录森空岛（密码/验证码两法）→ 拉本人账号
  数据 → 看板渲染。核心 `skland_client.py`（仅标准库，登录/cred/取数/存凭证）+ GUI `skland_gui.py`
  （CustomTkinter，界面/线程/主题逻辑照搬 cx-downloader）+ CLI `skland_cli.py`（login/status/dump/checkin）。
  数据覆盖 概览 / 干员养成 / 基建 / 公招 / 剿灭·保全·肉鸽 / 任务 / 签到 / 原始 JSON。
  仅读自己账号，凭证存 `~/.arknights_skland.json`。**注意：森空岛接口无「抽卡记录」，本工具也拿不到。**
  - 读数据需带 `sign` 签名头（`md5(hmac_sha256(sign_token, path+query/body+ts+header))`）；`dId` 随机值即可（服务端不校验）。
  - 干员页支持按 **星级 / 职业** 筛选，按 **等级 / 技能等级 / 星级** 升降序排序；**专精按技能分别显示**
    （技能等级 1–7 是三个技能共享的一个数，专精每个技能独立）。列表用原生 `ttk.Treeview`
    （一行一数据项，筛选/排序 <10ms；此前每行 6 个 CTk 控件、341 行近 2000 控件，明显卡顿）。
- **活动关作业工作流**（`scripts/event-copilot/event_copilot.py` + `docs/WORKFLOW-活动关作业.md`）：
  抓 `prts.maa.plus` 作业 → 比对 `OperBoxData.json` 干员箱 → MAA **多作业**(`copilot_list`)自动战斗逐关通关。
  子命令 `events` / `sync`(补 MAA 资源) / `plan`(推荐) / `run`(执行，`--try` 逐候选重试，`--loop` 刷关) / `goto`(简易导航)。
  首次跑通 act52side（YW-5 通关、YW-6/7/8 三星）。踩坑详见 `docs/FINDINGS.md` §14。
- **活动经济规划器**（`scheduling/tools/event_economy.py` + `scheduling/data/event_act52side.json`）：
  按「关卡理智 / 每关代币产出 / 商店价与限购」算刷关次数、所需理智，对比活动期预算判断能否换完。
- `run` 默认 `formation_index=4`（只用第四编队，不动用户其它编队）、`ignore_requirements=true`（练度不足可用）。
- **opencode skills**（`.opencode/skills/`，分门别类留痕）：`arknights-event-copilot`、`arknights-event-economy`、
  `maa-resource-sync`、`maa-copilot-internals`、`arknights-oper-training` —— 把活动关/经济/资源/Copilot/培养 沉淀成可复用技能。
- **干员培养推荐**（`scheduling/tools/oper_appearance.py` + skill `arknights-oper-training`）：
  抓作业站 `document=挂机` 的挂机作业统计干员出现率，对照干员箱 → 排"该优先精二谁"。
- **保全派驻（SSS）操作手册**：`docs/ops_manual.json` 新增「保全派驻(SSS)」条目（完整入口链路 + 各按钮坐标：
  终端(1451,239)→底部「常态事务」(1120,1005)→保全派驻「进入」(1542,868)→#12 副本详情→**「开始保全作战」(1663,987)**
  →选导能元件(确认 1722,990)/装备确认(1721,989)/阵容确认(1721,988)）。MAA `SSSCopilot` 已验证可全自动跑通：
  自动选 buff→装备确认→阵容确认→开打（**编队 20 人必须手动选**，MAA 源码里 SSS 自动编队 `set_enable(false)`）。
  作业在 `C:\MAA\resource\copilot\`（含 `old/`，共 75 个）；#12 废都安保派驻 内为「日达诺夫园区」。
- **收益账本 + 周报**（`scheduling/tools/revenue_ledger.py`、`revenue_weekly.py`、`docs/收益账本与周报.md`）：
  按结算段(04:00~次日03:59)记「基建收益/刷关所得/资源消耗/练度变化」的**物品差额**（省 token，不存全量快照），
  周报三块：本周练度提升 / 本周踩坑 / 下周优化。
### Fixed
- **活动商店选择性兑换**：记录 MaaCore **v6.18.0 不支持** `params.event_shop.blacklist`（勿拿 dev-v2 源码当运行版接口依据），
  `SS@Store@Begin` 会按其固定 ROI 无脑买 → 选择性兑换改**手动 tap**（见 `FINDINGS.md §19`；本次 6 件家具 310 已手动买齐）。
- **`ark_run_task` 跑任务前自动 `connect`**：此前未 `ark_connect` 就 `ark_run_task` 时，MaaCore `Controller::swipe`
  报 `m_controller is not inited`，滑动/Copilot 等**静默失效**（`ark_screenshot` 走 adb 仍正常，极易误判）。
  `ark_status.connected` 也改为反映真实连接态。
- 活动商店数据全量录入 + 规划器支持"无限库存"道具（按需买，不计入"买满"）。
### 计划
- `ark_ocr`：接入 MAA 的 OCR，读取任意 ROI 文本。
- 任务序列编排（一次调用跑多个任务并返回分步结果）。
- `ark_find` 支持模板批量匹配与去重阈值。

## [0.3.0] - 2026-10-10
### Added
- **`ark_task_result`**：长任务轮询工具。返回 `running` / `done` / `elapsed` 与 TaskChain
  完成（`chains`）/ 出错（`errors`）列表，供自动战斗等长任务用。
### Changed
- **`ark_run_task` 超时不再掐断任务**：原实现在 `timeout_s`（默认 300s）到点即 `stop()`，
  会把已进队的自动战斗（导航→点关→编队→开打）掐在编队/战斗中间界面。
  新增 `wait`（`False`=启动即返回的**异步**模式，长战斗推荐）与 `stop_on_timeout`
  （仅当 `True` 才恢复旧"超时即停"）。默认 `stop_on_timeout=False`：超时后任务继续跑，
  改用 `ark_task_result()` 轮询结果。
### Fixed
- 长任务（`Copilot` 自动战斗）不再被 MCP 硬超时中断导致卡在中间画面。

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
