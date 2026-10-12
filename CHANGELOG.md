# CHANGELOG

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，
版本号遵循 [语义化版本 SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]
### Fixed
- **培养成本：接入官方升级经验/龙门币，并支持按「当前练度」只算剩余段**（2026-10-12）：
  `fetch_gamedata.py` 增拉官方 `gamedata_const.json`；`oper_cost.py` 用其
  `characterExpMap` / `characterUpgradeCostMap` / `evolveGoldCost` / `maxLevel`
  替代原先的**星级常量估计**，并把经验/龙门币按 `LS-6`/`CE-6`（36 理智≈10000）折成理智计入缺口。
  新增 `--from-skland`（森空岛含 `skill_lvl`/`spec`）/ `--elite --level --skill-lvl --spec`，
  只算「当前练度 → 目标」的材料，不再从 E0L1 起算（高估）。
  ⚠ 仍存：`plan_week.py` 调 `oper_cost.compute()` **未传 `from_skland`** → 技能等级按 1 算（高估），待改。
- **逐日理智分配：补全非活动关单价（修「负载虚低」漏判）**（2026-10-12）：
  `plan_util.load_costs()` 原先只读 `event_*.json`，导致培养关（如 `MN-4`=12 理智）按 0 计，
  单日真实负载虚低（406 → 实际 418），自检探针漏判。现改为
  **本机关卡表（`C:\MAA\resource\stages.json` 的 `apCost`）铺底 → 内置已知 → 活动价目表覆盖 → 显式兜底**；
  活动关以 `event_*.json` 的 `sanity` 为权威。
- **逐日理智分配：修「末尾任务被静默丢弃」**（2026-10-12）：
  `day_cap` 旧版只算「自然 + 均摊药」，**漏了周常浓缩液 240**，且排不下的次数被 `continue` 静默丢弃
  （W42 丢了 417 理智）。现 `day_cap = ceil(周总预算/7)`（含周常 240 + 药），
  窄窗关（EX/S）在窗口内多天分摊，排不下的登记进 `unplaced`（不静默丢、不硬塞爆表）。
- **口径统一：固源岩 `target` 500 → 1000**（2026-10-12，运筹层裁定）：
  `plan_week.py` 的 `RULE.shards.target` 改为 1000，与 `MASTER-PLAN` / `state.json` / 每日清单一致。
- **剿灭改「每天 1 次」**（2026-10-12）：周一~周五各 1 次打满 1800 玉上限（旧版 `5 次/周` 分摊语义不清）；
  `plan_week.py` 组装任务时**显式排出剿灭**（`StartUp → 剿灭 → 活动 → EX/S → 1-7 → 培养 → 日常`）。

### Added
- **`.opencode/agent/` 子 agent 定义**（2026-10-12）：`ark-data`（取数）/ `ark-exec`（执行）/
  `ark-verify`（复盘对账）/ `ark-orchestrator`（总指挥），配合既有 `arknights-*` skills 分权。

### Changed
- **GUI 整体重做：CustomTkinter → PySide6 + PySide6-Fluent-Widgets**（2026-10-12）：
  Win11 Fluent Design（左 NavigationInterface 图标+文字导航 / CardWidget / TableWidget /
  InfoBar 吐司 / 明暗跟随系统）。`scripts/skland/skland_gui.py` 整份重写（约 1500 行）；
  `skland_client.py` / `gacha_client.py` / `ff_session.py` **一行没动**，只是换壳。
  - **配色改成「方舟风：深海蓝 + 金」**：底 `#0A121D` / 卡片 `#121E2E`（描边 `#27405F`）/
    标题与强调 `#E3BE63` / 主色 `#C9973B`；浅色主题另有一套（米白 + 暗金）。
    卡片是 `CardWidget` 自绘的，所以走 `GameCard.paintEvent` 覆盖 + 调色板 `GAME[]`，
    而不是框架主题；切主题时由 `_restyle_game()` 重新铺（含表格 QSS 与已注册的文字颜色）。
  - 关掉 Mica（改用纯色深海蓝，云母会把底色冲淡）：`setMicaEffectEnabled(False)` +
    `setCustomBackgroundColor(light, dark)`。
  - 新依赖：`PySide6-Essentials` + `PySide6-Fluent-Widgets`（+ `PySideSix-Frameless-Window`）。
  旧版快照见 `历史版本/Fluent界面重做-2026-10-12/`。

### Added
- **抽卡凭据免密码 + 打开即自动登录**（2026-10-12）：
  - `scripts/skland/ff_session.py`（新增，**仅标准库**）：直接从本机 Firefox 读登录态 ——
    `ak-user-center` 是**会话 cookie**（不在 `cookies.sqlite`，只在 `sessionstore*.jsonlz4`，
    自带纯 Python mozLz4 解码）、`x-role-token` 与角色 uid 在 `ak.hypergryph.com` 的 localStorage。
    实测两者**必须配对**：缺 token → `DETECTED_ROLE_CHANGED`；缺 cookie → `UN_LOGIN`。
  - `skland_cli.py gacha --from-firefox`；GUI「抽卡」页新增「从火狐导入」。
  - GUI 新增「**打开时自动登录**」开关（默认开）：有本机凭证就开界面即拉数据，
    抽卡顺带从火狐更新（留档超 6 小时才更新）。设置存 `~/.arknights_skland_gui.json`。
  - 实测：开界面后自动拉到本人数据（Lv99 / 341 干员 / 理智 133/205），并渲染 218 条抽卡留档。
- **抽卡记录（官方寻访记录）**（2026-10-12）：
  - 澄清口径：**森空岛没有抽卡记录**（原结论正确），但**鹰角官网「用户中心」有** ——
    `ak.hypergryph.com/user/api/inquiry/gacha/{cate,history}`，走 `x-role-token` + `ak-user-center` cookie，
    **不需要**森空岛的 `cred`/`sign`。两套共用 `as.hypergryph.com` 登录，分叉在 OAuth `grant` 的
    `appCode`（用户中心 `be36d44aa36bfb5b`+`type=1` vs 森空岛 `4ca99fa6b56cc2ba`+`type=0`）。
  - `scripts/skland/gacha_client.py`（新增，**仅标准库**）：6 步登录链、`cate`/`history` 分页
    （游标 `pos`+`gachaTs`）、本地留档（`~/.arknights_gacha_records.json`，只增不删）、
    统计（星级分布 / 出金水位按 限定·标准·中坚 三条结转链）、离线 `self_test()`。
  - GUI `skland_gui.py` 新增「**抽卡**」页签（拉取 / 只读留档 / 打开官网页 / 6★·全部两视图）；
    登录时顺带派生抽卡凭证。CLI `skland_cli.py` 新增 `gacha` 子命令。
  - 文档：`docs/DATA-SOURCES.md` 新增 **§8**；`FEATURES.md`/`FINDINGS.md`/`MASTER-PLAN.md`/`README.md`
    同步改正"官方无抽卡接口"的旧口径。

- **一键长草全链路**（2026-10-11）：
  - `scheduling/tools/plan_week.py` **周规划器**（规则写死 `RULE`）：预算(自然+周药+理智药) → 剿灭 → 固源岩下限
    → EX/S 首通 → 活动(按商店封顶) → 培养 → 1-7 填充 → 每日分配；产出 `weekly_plan.json`（单一事实源）。
  - `plan_util.py` **每日分配**：开放窗口、**连战 series**、`day_cap`(自然+均摊药) 封顶、上线建议（不浪费自动回复）。
  - `oper_cost.py` + `material_cost.py` **培养成本**：官方 `character_table` 材料清单 + 企鹅物流掉落率
    + 加工站 `workshopFormulas` **合成**（先用库存、能合就合）+ 精英化龙门币 → 折算理智。
  - `fetch_gamedata.py`：**可续传**下载官方 gamedata（绕开 raw.githubusercontent 超时截断）。
  - `build_site.py` **单页汇总站** + `site_server.py`（公招「贴词条 → 推荐」，含 CORS 与 `/api/reload`）。
  - `scripts/maa-week/maa_week.py`：`show/write/run/startup`；`run` **默认只跑当天那一份**、自动带连战、
    队列前跑附带脚本（基建换班）；`startup` **含拉起雷电模拟器**。
  - `scripts/sanity-potion/sanity_potion.py`：读主界面理智药（只读，自动 ✕）。
  - `scripts/anchor-runner/`、`scripts/depot-items/`：锚点录制/回放、仓库逐项读数。
- **一体化 GUI**：`skland_gui.py` 更名「**明日方舟·助手**」，新增「长草」tab、「快捷工具」卡（启动游戏/打开 MAA），
  「刷新数据 / 签到」**自动续期**森空岛 token（修 401）。
- **基建**：MAA `Infrast` 收菜任务取消 —— 收菜并入 `infrast_rotation.py`（在刷关前跑），避免重复收菜。
- **文档**：`docs/STATE-一键长草.md`（现状速查）、`docs/PLAN-一键长草.md`、`docs/PLAN-培养与规划逻辑.md`。

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
