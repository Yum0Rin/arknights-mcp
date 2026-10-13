# CHANGELOG

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，
版本号遵循 [语义化版本 SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]
### Changed
- **规划支持「剩余 X 天」+ 自然理智按上限 205/天**（2026-10-14，用户裁定）：
  - `plan_week.plan(date, start=None)` 新增 `start`（默认=今天）→ **只排 `start..本周日`**（按现状算剩余 X 天），
    不再固定整周 7 天；CLI 加 `--from`。周一跑=7 天、周三跑=5 天、周日跑=1 天。
  - `RULE.natural_per_day` **240 → 205**：本机玩法是「**1 次/天**、来时理智满、跑完下线」，24h 回 240 被上限 205
    卡住，每天实际只能用 205，多出的 **35/天溢出** → 预算不再按 240/天虚高（每天 `medicine` 也少算 35）。
  - 剿灭按**已完成合成玉**扣减（`state.json.progress.annihilation.jade`）：W42 已 370 → 只排 **4 次**（原固定 5）。
  - `plan_util`：删死代码 `KEEP_AFTER`（定义了没人用）；`session_advice()` 重写为「1 次/天、花到 ~0」口径
    （不再提「每 12h 上线、花到 ≤85」）；`shard_requirement()` 的 days 改从 `range` 取（不再硬编码 7）；
    `daily_cap()`/`budget_total()` 兜底 240 → 205。
  - `build_site.py`「上线建议」文案同步。
  - 快照：`历史版本/剩余X天规划+自然205-2026-10-14/`。W42 已重生成（`range 2026-10-14..10-18`、预算 1745、逐日 445/265/265/325/444）。
- **理智药「整瓶对齐 + 1-7 补零」**（2026-10-14）：
  - 药是**整瓶 60**，只能整瓶吃 → `RULE.medicine_bottle = 60`；预算里新增 `meds_usable`（=存量对齐到 60 的整数倍，
    读数 760 → 整瓶 720），不再把「凑不满一瓶的余数」算进可支配理智，避免**计划吃 839 但实际只有 760** 的超发。
  - `plan_util.distribute_daily()` 末尾加**补零**：每天目标对齐到 `205 + 60k`（k=当天该吃几瓶），
    差的那点余数用**填充关 1-7**（6 理智/次）抹平 → 每天跑完剩 ≈0，不再剩 60/35 这种尾巴。
    药不够时按瓶数回收（`_trim` 逐次砍 1-7 次数）保证**总用药 = 整瓶可用量**。
  - 效果：W42 五天 = 12 瓶（720），逐日剩 ≈0/0/0/0/1。
- **测药脚本 `sanity_potion.py` 重写为「面向自动化的容错版」**（2026-10-14）：
  - **不盲点**：先判「是不是主界面」（OCR 到『理智』/`/205`）→ 不是就**不点 +**，默认直接报错退出（退出码 3）并留证截图；
    加 `--recover` 才做**有界** BACK 恢复（最多 N 次，遇「确认退出游戏」弹窗**只点『取消』、绝不点『确认』**）。
  - **开面板校验 + 重试**（`--tries`）；读数用**整帧 OCR**（面板大号白字压活动 banner，裁剪+放大反而糊 → 整张 1920×1080 才准）
    + **按 y 分行/行内按 x 拼接**（面板把 `当前》总量` 拆成两个 OCR 框，必须拼回）+ **两路交叉校验**
    （顶部 `当前》总量` vs 底部 `提升 N 理智`，不一致就重试）。
  - **卡片定位**：面板常把多张卡的「X天」徽章并成一框 → 改用「卡片行内数字框按 x 聚类」+ **已验证卡中心兜底**
    （`[1146,1350,1578]`；⚠ 别用整行宽栅格——点卡片右侧/间隙会**关掉面板**再误触主界面）。
  - 退出码：`0` OK / `2` 无设备 / `3` 不在主界面 / `4` 面板没开 / `5` 读数失败（供定时任务/自动化判成败）。
  - 新增 `--addr` / `--json` / `--ensure-main`（先 `maa_week startup` 带游戏到主界面）等选项；**绝无点 ✓ 的代码路径**。

### Added
- **每周刷新计划（Windows 计划任务「方舟·每周刷新计划」）**（2026-10-14）：
  - 新增 `scripts/weekly-refresh/weekly_refresh.py`：重新生成本周计划（`plan_week.plan(today)` → `weekly_plan.json`，
    窗口=今天..本周日）+ 检查理智药读数是否过期（默认 >7 天）+ **弹 Windows 原生提示**（`MessageBoxTimeoutW`，超时自动关）
    报告窗口/预算/逐日 + 是否要重测药；结果写 `scheduling/data/weekly_refresh.json` + 追加 `%TEMP%\arknights-mcp.log`。
    **不自动测药**（测药要求游戏停在主界面且只有 MAA 一个客户端驱动 → 定时任务无法保证游戏状态，误点有风险）。
    选项：`--no-popup` / `--dry` / `--stale-days N`。
  - 新增 `scripts/weekly-refresh/install_task.ps1`：注册/注销计划任务（默认**每周日 20:00**，`-StartWhenAvailable`
    → 周日没开机则开机后补跑；`-Uninstall` 注销；`-Day`/`-At` 可改）。已注册并实跑验证（NextRunTime 2026-10-18 20:00）。
  - **定时从「周一 09:00」改到「周日 20:00」**（2026-10-14 用户要求）：周日跑时今天属于旧的一周 →
    `weekly_refresh.py` 用「明天(下周一)」算所属周 → 生成**下周**计划（`range` = 下周一..下周日，满 7 天，与「周一早上跑」等价）。
    代价：今天(周日)本身不在该计划内 —— 周日日常先跑完再刷新，或手动 `plan_week.py`（默认今天..本周日）补一份。
  - GBK 控制台编码：`main()` 给 stdout/stderr 加 `errors=replace`（同 `maa_week` 口径）。
- **一键长草执行链防御：今天不在计划里 → 报错停，不静默跑**（2026-10-13）：
  新增 `plan_util.plan_day(plan, today)` 统一判定（`maa_week` 执行器与 GUI 长草页**共用一份口径**），
  status = `ok` / `out_of_range`（计划过期或未覆盖本周）/ `no_entry`（区间内缺这一天）/ `no_daily`（老/损坏计划）。
  - `maa_week.py run` / `write`：今天不在计划里时打印**原因 + 修复命令**（`plan_week.py`）并 **SystemExit(2)**，
    **不再**静默只跑日常杂活 / 悄悄停用所有 Fight 槽位；`run` 新增 `--force` 才越过后只跑非理智任务。
  - `maa_week.py show`：今天不在计划里时醒目提示。
  - `load_plan`：计划缺失 / JSON 损坏给出可操作提示（不再甩 traceback）。
  - GUI 长草页：今天不在计划里时页面顶部红字提示「点『生成/刷新计划』重新生成」。
  - **修 `⚠`(U+26A0) 在 GBK 控制台 UnicodeEncodeError 崩脚本**：`main()` 给 stdout/stderr 加 `errors=replace`。
  - **`run` 冷启动自动拉起模拟器**：`cmd_run` 连接前先 `_ensure_device()`（设备不在线就 `ldconsole launch` 并等上线），
    使 GUI「直驱跑一键长草」从"模拟器没开"状态也能一键跑通（原来 connect 必失败直接退出）；`cmd_startup` 同源复用。
  - **GUI 子进程输出乱码**：`_popen_log` 以 utf-8 读子进程，但 Windows 下 Python 子进程默认按 GBK 写 stdout →
    中文全变替换符。现给子进程注入 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`（只影响子进程，不改全局）。

### Verified
- **2026-10-13 直驱 `maa_week run` 实跑跑通当天**（GUI「直驱跑一键长草」按钮同一条命令）：
  StartUp + 剿灭×1（+370 玉，1480/1800）+ YW-6×20（420 代币，理智 205→60）+ 公招 + 基建(Rotation) + 信用商店 + 领奖，
  MaaCore `AllTasksCompleted`（finished_tasks [1..7]），用时 925s，`run_report.jsonl` ok=true。
  注：本机 tool 会话对 >2min 的子进程会杀（实测 120s 定点），故执行以 **detached** 方式启动（等价于 GUI 按钮的 spawn）。

### Fixed
- **`plan_week.py` R3.5 培养的 `train_budget` 未定义（潜在 `NameError`）**（2026-10-14）：该名此前从未赋值 →
  一旦有可刷材料行就 `NameError` → 被 `except` 吞成「培养估值失败」→ **培养恒为 0**（当前场景 `rows` 为空才侥幸没炸）。
  按 RULE 顺序显式给值 `train_budget = max(0, budget − ann_san − extra_san − san17 − ev_runs·ev_san)`（活动吃完的剩余给培养）。
  `--dry` 验证：不再报错，计划输出不变（当前材料缺口仅 6 理智，培养仍 0）。
- **预算口径修正：理智药存量已含周常药，不再另加 240**（2026-10-12，用户裁定）：`plan_week.RULE.weekly_potion`
  整段删除（不是「条件加」而是**永不加**）。理由：药存量由**每周日手动跑** `scripts/sanity-potion/sanity_potion.py`
  测出写进 `scheduling/data/sanity.json`，该读数**已包含周常药**，重复计入会把预算虚高。
  W42 预算因此从 2840 修正为 **2600**（自然 1680 + 药 920），`day_cap` 406 → **372**。
  ⚠ 暴露冲突：2600 装不下 `1-7 下限 2502 + 剿灭 125`（+EX/S 240）→ `unplaced={1-7:48}`，已升用户裁定。
- **EX/S 首通与突袭改为「解锁依赖链」**（2026-10-12，用户裁定）：用户指出「EX 关必须按 EX-1→EX-8 顺序，
  是因为**还没打过的关需要依次解锁**」。故不只是排序：
  - `plan_week` R2.5 改为读 `docs/state.json.progress.event_act52side` 的 `ex_clear_done`/`raid_clear_done`，
    **只排未通的关、取前缀链（从第一个未通开始）**，已通的关不再重复排首通；进度字段缺失时按「全未通」保守处理；
  - 新增 **`Raid` 任务型**（每关普通首通后紧跟该关突袭）；规则 `raid.only=[EX,S]`、`after_normal=true`
    ⇒ **普通关 YW-1..8 不产生任何突袭**；
  - 突袭**不走** MAA `Fight`（已核实 `is_raid` 只存在于 Copilot 的 `copilot_list` 条目）→ `maa_week` 遇到
    `Raid`/不可导航的 EX **不 append、只提示**，并直接打印可复制的交棒命令；
  - `scripts/event-copilot/event_copilot.py` 新增 `run --raid` 与 `run --chain {ex,raid,s,sraid}`：
    **依次解锁、遇挫即停（不跳关）、跑完回写进度**（新增 `ex_clear_done`/`s_clear_done`/`raid_clear_done`/`last_chain_note`）。
- **GUI 配置写盘也过关卡预检**（2026-10-12，复盘层发现）：`maa_week.write` 若把 MAA 导航不了的关写进
  `gui.new.json` 的 Fight 槽位，用户在 GUI 点「开始」就会 append=0 打死整队。现 `cmd_write` 同样过滤
  并打印提示 + 交棒命令。
- **`_shot` 留证截图 0 字节**（2026-10-12）：硬编码 `-s 127.0.0.1:5555`（未注册）→ 改用 `_devices()` 探测实际设备，
  并校验返回码与文件大小。
- **MCP `TASK_DEFAULTS["Infrast"]` 只收 3 个设施**（2026-10-12）：统一为 9 项，与新口径一致。
- **GUI「签到」页今日状态不即时更新**（2026-10-12）：`checkin()` 签到成功后只弹吐司，**不重拉状态**，
  「今日」一直显示签到前的旧值，须手动「刷新数据」才变。现签到后立即 `core.attendance_status()` 重拉，
  经新增队列类型 `attendance` 回主线程重渲染「签到」页（`App.attendance` 缓存）。
- **GUI「长草」页计划区永远空白（页面没做完）**（2026-10-12）：`_render_longcao()` 早已写好却**从未被调用**
  （全文件无调用点，也无切页钩子），故该页只剩两个按钮、看不到周计划。现：①建页时先渲染一次；
  ②挂 `stackedWidget.currentChanged`，切到「长草」页重读盘渲染；③补「生成/刷新计划」（跑 `plan_week.py`，
  完成后 `reload_plan` 回主线程刷新）与「刷新计划」按钮 + 「快捷工具」卡（启动游戏/打开 MAA/生成·打开汇总网页）；
  `_popen_log` 增 `reload_plan` 回调。
- **`weekly_plan.json` 长期 stale**（2026-10-12）：它还是旧口径（固源岩 1282/目标 500、剿灭 0、YW-6 123 次），
  而 `weekly_plan.W42.json` 已是新口径，且 `maa_week` 读的是前者 ⇒ 每天跑的都是旧账。现已重新生成并把 W42 对齐为镜像；
  追加留痕到 `weekly_plan_log.jsonl`。
- **关卡通不了航会打死整天队列**（2026-10-12）：`maa_week.run` 增 **预检**，`Fight` 关卡若 MAA resource 无定义
  （如 `YW-EX-1`）则**跳过并留证**（`--strict` 才失败），不再因一条 `append=0` 让整天跑不动。
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
- **活动商店选择性兑换**：记录 MaaCore **v6.18.0 不支持** `params.event_shop.blacklist`（勿拿 dev-v2 源码当运行版接口依据），
  `SS@Store@Begin` 会按其固定 ROI 无脑买 → 选择性兑换改**手动 tap**（见 `FINDINGS.md §19`；本次 6 件家具 310 已手动买齐）。
  > **2026-10-12 更新**：6.19.0 的 `MaaCore.dll` 已含 `event_shop` 解析 ⇒ 该限制**已解除**（`FINDINGS.md §21`），待实跑确认日志有 `registered EventShop task` 后改回自动。
- **`ark_run_task` 跑任务前自动 `connect`**：此前未 `ark_connect` 就 `ark_run_task` 时，MaaCore `Controller::swipe`
  报 `m_controller is not inited`，滑动/Copilot 等**静默失效**（`ark_screenshot` 走 adb 仍正常，极易误判）。
  `ark_status.connected` 也改为反映真实连接态。
### Changed
- **基建改交 MAA 自带的「队列轮换」**（2026-10-12，用户裁定）：`plan_week.RULE.infra_facilities` 新增
  （Mfg/Trade/Power/Control/Reception/Office/Dorm/Processing/Training），`Infrast` 任务参数改为 `mode=20000` + 全设施；
  `plan["side"]` 清空。自研 `scripts/infrast-rotation/infrast_rotation.py` 与 skill `arknights-infrast-rotation`
  归档到 `历史版本/基建改MAA轮换+队列按天-2026-10-12/`（含回退说明）并从工作区删除；GUI「基建换班」按钮移除；
  `AGENTS.md` 铁律 2、`MASTER-PLAN` §5.6、`STATE.md`/`PLAN-一键长草`/`DAILY-CHECKLIST`/`ops_manual.json` 口径同步。
- **MAA 队列改「一天一天编辑」**（2026-10-12，用户裁定）：`maa_week.write` 从「把整周刷关量刷进 GUI」改为
  **只写当天**（`--date`，默认今天）：Fight 槽位**按关卡匹配**、当天的新关克隆槽位插入、**不在当天计划里的槽位 `IsEnable=false`**；
  固定任务（StartUp/Recruit/Infrast/Mall/Award）确保启用并同步次数，`Infrast.Mode` 强制 `Rotation`；
  空 `Plans` 的 `OperProgress` 自动停用（否则 `set_params` 失败会拖垮整条队列）。
  `plan_week` 产出新增 **`daily` 逐日视图**，`_today_tasks` 改为优先读它（口径唯一）；`show` 打印逐日表。
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
- **监工对账**（2026-10-12）：`docs/STATE-一键长草.md` 文末新增「监工对账」节 —— 逐日↔计划次数、逐日理智 ≤ day_cap、
  全周 ≤ 预算、开放窗口、剿灭周上限、固源岩期末目标、商店代币全部脚本核算；3 个真问题记入 `state.json.plan.audit_findings_2026-10-12`。
- **MaaCore 6.18.0 → 6.19.0 更新扒取与融合评估**（2026-10-12）：新增
  `docs/MAA-6.19-融合评估.md`；核对方式 = Release 正文 + **本机 DLL 字符串实测**
  + dev-v2 源码。要点：
  - 新增 **`OperProgress`（干员培养）** 任务（6.19 `MaaCore.dll` 出现 92 次 / 6.18 为 0）：`{"plans":[{"role"?,"name","elite"?,"skill_level"?,"skill_mastery"?[3]}]}`，
    材料即缺即合、芯片自动制造、缺催化剂自动补红票商店、专精自动选协助者；**不含等级 Lv 目标**。
  - **`params.event_shop.blacklist` 现已可用** ⇒ `docs/FINDINGS.md` §19 旧结论**作废**（§21 记录），
    活动商店选择性兑换可从手点改回自动（**待实跑确认**：日志出现 `registered EventShop task`）。
  - 库存保持（DepotMaintain）是 **GUI 组装层**（非 Core 任务，核心仍是 `Fight.drops`），新增「当前活动预设」+「按达成率排序」。
  - 其他：定时启动前唤醒计算机（对应「定时执行未配」待定项）、基建换班周计划、任务链失败自动存图 `debug/interface`、任务日志输出用时、
    Python 接口截图尺寸修复、MAA 自清理被移除的旧资源文件（⚠ 我们 `maa_update.py` 的 `robocopy /E` 不删旧文件）。
  - 文档同步：`MAA-INTERNALS.md`（版本 6.19.0 + §2.20 库存保持 + §2.21）、`FINDINGS.md` §21、`docs/README.md` 索引、`AGENTS.md` 版本。
- **`.opencode/agent/` 子 agent 定义**（2026-10-12）：`ark-data`（取数）/ `ark-exec`（执行）/
  `ark-verify`（复盘对账）/ `ark-orchestrator`（总指挥），配合既有 `arknights-*` skills 分权。
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
### 计划
- `ark_ocr`：接入 MAA 的 OCR，读取任意 ROI 文本。
- 任务序列编排（一次调用跑多个任务并返回分步结果）。
- `ark_find` 支持模板批量匹配与去重阈值。

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
