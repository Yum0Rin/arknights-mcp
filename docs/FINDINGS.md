# 开发发现 / 踩坑记录（留痕）

> AGENTS.md 只保留铁律；详细踩坑、证据、复现步骤都放这里。
> 最后更新：2026-10-10（新增 §17 森空岛在线接口）。

## 1. MAA 原理与组成（本 MCP 借用其能力）

- MAA 是"截屏 → 模板匹配/OCR 识别 → 按流水线决策 → 模拟触摸"的机器人；**不读内存、不改游戏**。
- `C:\MAA`：`MaaCore.dll`(核心) / `MaaAdbControlUnit.dll`(ADB) / `openCV_world4_maa.dll`(模板匹配) /
  `onnxruntime + fastdeploy_ppocr`(OCR)；`resource/template/**.png`(模板)、`resource/tasks/tasks.json`(流水线)。
- Python 绑定在 `C:\MAA\Python`：`Asst.load / Asst(cb) / set_instance_option / connect / append_task / start / running / stop`。
- 识别结果是回调 `SubTaskExtraInfo`(msg=20003)：`what=OperBoxInfo`(own_opers) / `what=DepotInfo`(data)。

## 2. 设备信息

- 雷电 LDPlayer9；实例 0 = `emulator-5554`；adb：`C:\leidian\LDPlayer9\adb.exe`。
- MAA 连接地址 `127.0.0.1:5555`；游戏 `com.hypergryph.arknights`（官服）。
- ⚠️ **雷电不要常开**（用户电脑会发烫）：识别产物已落盘，日常无需游戏常驻；
  用完即关 `ldconsole quit --index 0`（`C:\leidian\LDPlayer9\ldconsole.exe`）；只在需要重新识别时才开。
- ⚠️ **基建实际是 243**（贸易站 2 / 制造站 4 / 发电站 3）：MAA `gui.log` 三次独立运行
  （10-02、10-05、10-08）"当前设施"记录一致。用户一度记成 333，以日志为准。

## 3. 坑：设备列两次 → `more than one device`
`adb devices` 同时列 `127.0.0.1:5555` 与 `emulator-5554`（同一台）。不加 `-s` 报错。
→ 优先 `ARK_ADDR`，其次 `emulator-*`。

## 4. 坑：`exec-out screencap` 是二进制安全的
`adb exec-out screencap -p` 返回 PNG 原字节；做 `\r\n→\n` 替换会**损坏 PNG**（cv2 读成 None）。
只有老式 `adb shell ... > file` 才需替换。

## 5. 【最关键】识别只读到一屏 —— 两个真根因（曾误判为"游戏忽略滑动"）

### (A) `TouchMode=MiniTouch` 在本机损坏 → 翻页/滑动全废
- 症状：干员/仓库识别**只读第一屏**（干员 14 个）；`adb shell input swipe` 也翻不动箱子。
- 证据：MAA 日志 `MinitouchController::call_and_hup_minitouch ... read timeout`、
  `... syntax error: unexpected ')'`。
- 修复：`gui.new.json → Configurations.Default.Gui.ConnectSettings.TouchMode` = **`MaaTouch`**，重启 MAA。
- 效果：干员识别 **14 → 337**（~53s 翻页正常）；仓库识别正常（60 项）。

### (B) `StartUpSettings.RunDirectly=True` → MAA 启动即跑日常队列 → 识别按钮 disabled
- 用户**有意**设置（目的：开机自动跑任务），所以**不是错误**，但要理解它的副作用：
  MAA 一直"忙" → 小工具里的「开始识别」按钮 `IsEnabled=False`，点击无效/`Invoke` 报 `E_UNEXPECTED`。
- 需要识别时：**先让 MAA 空闲**（点「停止」停下队列，或等其跑完）再识别。
- 相关：`Gui.MinimizeOnStartup=True` 会让 MAA 启动即最小化（窗口隐藏）。

## 6. GUI 识别 vs 纯脚本调核心；结果只在 GUI 落盘
- 纯 `asst` 脚本跑 `OperBox`：受 (A)(B) 影响易只读 1 屏，偶发**全黑图**(1280×720) → `SubTaskError`。
- MAA **GUI** 的路子（`小工具 → 干员识别/仓库识别 → 开始识别`）是**已验证可行**的方式。
- 只有 GUI 会把结果写 `C:\MAA\data\OperBoxData.json` / `DepotData.json`。
  - `OperBoxData.json = {done, own_opers[], source, syncTime}`（own 含 elite/level/potential/rarity）。
  - `DepotData.json = {done, data:{"物品ID":数量}, syncTime}`。
- 纯脚本要自己在回调里接 `SubTaskExtraInfo` 落盘。

## 7. 锁屏 + 隐藏窗口下的自动化点按钮
- 锁屏后 MAA 主窗口 `IsWindowVisible=False`：`gui_shot.ps1` 找不到、`ImageGrab` 抓到锁屏画面、
  `PrintWindow` 可能全黑。
- 找句柄：`EnumWindows` 按 pid 过滤（主窗口 class `HwndWrapper[MAA;;...]`）。
- 显示：UIAutomation `WindowPattern.SetWindowVisualState(Normal)` + `ShowWindow(SW_SHOW/SW_MAXIMIZE)` +
  `SetWindowPos(...,SWP_SHOWWINDOW)`。
- **锁屏下 UIAutomation 仍能用**：`InvokePattern.Invoke()` / `SelectionItemPattern.Select()` 不需要真鼠标。
  但 **`Invoke` 仅在按钮 `IsEnabled=True` 时有效**（MAA 忙时按钮 disabled → 报错）。
- 点按钮可行路径（已验证）：`小工具(顶层 Tab) → 干员识别/仓库识别(子 Tab) → 开始识别(Button)`。
- 元素名用 `Current.Name`；控制台中文乱码 → 写 UTF-8 文件再读。
- 也可用 `PostMessage(WM_LBUTTONDOWN/UP)` 点窗口坐标（实测有效，曾误点到「Link Start!」启动了整个队列）。

## 8. 一图流排班生成器（scheduling 子功能）
- 一图流 `https://ark.yituliu.cn/tools/scheduleV3`；备选 `https://riic.autos/`。
- MAA 自带 `C:\MAA\resource\custom_infrast\*.json`（243/153/252/333）**即一图流生成**（署名"公孙长乐"）。
- **布局预设**（须与实际基地一致才能用）：`153` / `243 钱书均衡·龙门币优先` / `243（搓玉）合成玉` /
  `333 龙门币优先` / `333（搓玉）` / `252（2·3 赤金）` / `342`。
- 有 `执行深度排班`（全局优化）；数据源 `导入 MAA JSON`（隐藏 `input.operator-source-file-input`，accept `.json`）。
- **局部 vs 全局**：MAA 内置 autofill 只按单干员效率贪心（局部最优）；一图流考虑组合/心情/轮换（近全局）。
  "补空缺"式打补丁会破坏组合与轮换，往往不如整份重排。

## 9. 【关键坑】一图流"导入 MAA JSON"要求**顶层是干员数组**
- 一图流解析器（`l79-preview-efficiency-settlement` chunk 的 `vo()`）第一句就校验：
  `if(!Array.isArray(e)) throw new Error("MAA JSON 顶层必须是干员数组")`。
- 而 MAA `OperBoxData.json` 顶层是**对象** `{done, own_opers:[…], source, syncTime}` → 直接抛错、导入失败
  （现象：Toast 一闪而过、数据源仍 `0/3`，控制台 `handleMaaFileChange failed`）。
- **修复**：把 `own_opers`（仅 `own:true` 的项）抽成**裸 JSON 数组**另存再导，即可成功（本例 337 条）。
  - 每条字段：`id`(str) / `name`(str) / `own`(bool) / `rarity`(int 1-6) / `elite`(int 0-2) /
    `level`(int 0-90) / `potential`(int 0-6)；非 `own:true` 的被丢弃。
  - 生成：`arr=[o for o in d['own_opers'] if o.get('own')]; json.dump(arr,…,ensure_ascii=False)`。
- 该 chunk 带 hash 后缀、会变；按报错堆栈里的文件名现 `curl` 即可取当前源码。

## 10. firefox-devtools MCP 在该 SPA 上的正确用法（**修正** §9 早期结论）
- **快照没坏**：`firefox_take_snapshot` 加 `selector` 限定作用域即正常返回 UID；只有**不加 selector**
  的全页快照才退化成只返回 body。
- **原生上传可用**：拿到 `input.operator-source-file-input` 的 UID 后 `firefox_upload_file_by_uid` 即可
  （会真正触发 `change` → 应用 `import-maa`）。
  - 注意：该 input 的 onChange 结尾 `v.target.value=""`，所以**上传后 `files.length` 立刻 = 0 是正常的**，
    别据此判定"没挂上"；要看 UI 是否 `1 / 3` + 出现"持有干员"。
- **https 页面 `fetch http://127.0.0.1` 会被混合内容拦截**（请求挂起 → 超时）→ 本地 CORS 服务这条路走不通；
  数据只能经 file input 上传。
- **取证技巧**：上传前 `evaluate` 挂钩 `console.error` + `window.onerror/unhandledrejection` 存进
  `window.__errs`，上传后再读 → 直接拿到抛错堆栈，定位到解析器。
- **点按钮**：`[...document.querySelectorAll('button')].find(b=>b.innerText.includes('执行深度排班')).click()`
  比 UID 稳（DOM 会重排）。

## 11. 本轮已产出的排班（2026-10-09）
- 输入：`OperBoxData.json` 337 → 裸数组 `MAA_OperBox_array.json` → 一图流导入成功（`1/3`、出现"持有干员"）。
- 一图流布局预设与基地一致：**243**（2贸易 / 4制造 / 3发电）。
- 两方案（导出的"一图流排班协议"JSON，存 `scheduling/一图流产物/`）：

  | 方案 | 一图流预设 | 总产出 | 关键产出/消耗 |
  |---|---|---|---|
  | 钱书均衡·龙门币优先 | `243 钱书均衡/龙门币优先` | **55,855** | 赤金 +73.85 / 赤金消耗 -106.86（2贸易=龙门币；制造=经验书×2＋赤金×2） |
  | 搓玉 | `243（搓玉）合成玉` | 34,642 | 合成玉 +486、源石碎片 +46.2、**固源岩 -92.4**（1贸易=龙门币、1贸易=合成玉；制造=经验书/源石碎片/赤金×2） |

- 结论：按一图流"总产出"口径，**钱书均衡 > 搓玉**（55,855 vs 34,642）；搓玉以总价值换合成玉，且**额外耗固源岩**（需理智刷取）。
- 精二培养建议（含 经验/龙门币/理智 成本）见结果页文本；综合产出面板在"每日综合产出"（总产出/净产出可切）。
- **培养前后收益提升（按技能效果算）**：`tools/parse_training.py` 解析培养建议卡片 → `training.json`；
  报告里逐干员给"培养前(当前技能)→培养后(解锁/升级的技能)"，取技能文本里的**最大百分数**（设施级，
  如"每小时+2%…最终+20%"取 +20%）。条件/按数量叠加类（每发电站+15%、每格仓库+3%、仓库容量+19、+1 设施数量等）
  以技能文本为准。**"设施级"≠"全基地"**：一个设施只占基地一部分，折算到总产出更小；要精确的全基地% 只能重跑模拟（用户暂不跑）。
  另按产出类型（龙门币/经验书/合成玉/通用制造/发电/办公）分组、按收益率排名生成 **"干员榜"**（规则见 `parse_training.py::classify`）。
- 前端接口要点：本地 https 页面 `fetch http://127.0.0.1` 被拦；`input.operator-source-file-input` 的 onChange 读完即清空 value。

## 12. 理智经济 / 周度规划（运筹模型）
- **数据来源与取数方法见 `docs/DATA-SOURCES.md`**（企鹅物流 API、PRTS 数值）——以后取数先看它。
- 模型：`scheduling/tools/sanity_plan.py` → `sanity_plan.json`；报告"理智规划（运筹模型）"段。
- 参数：周预算 = 自然 240×7 + 周常浓缩液×2 = **1920 理智**；上限(99级) **205**（每 12h 回复 120 → 上线花到 ≤85 不溢出）；
  剿灭周上限 1800（当期 25 理智/次 ≈370 玉，约 5 次 = 125 理智）；CE-6 = 36 理智/10000 龙门币、LS-6 = 36 理智/10000 经验、
  1-7 ≈ 4.82 理智/固源岩；养成 LMD:EXP ≈ 1.63(6★)。
- 结果：**养成向** ≈ 剿灭 125 + CE 1132 + LS 663 理智 → 周产 龙门币≈79.5 万 / 经验≈48.8 万 ≈ **1.35 个 6★/周**；
  **搓玉向** ≈ 剿灭 125 + 1-7 1795 理智 → 合成玉合计 ≈ **4862/周**（搓玉受固源岩供给约束）。

## 13. 【关键坑】让 MAA 基建换班用"一图流"自定义排班
- **必须设 `Mode="Custom"`**（枚举 `Normal`/`Rotation`/`Custom`，值从 `MAA.dll`(UTF-16)里找）：只设 `Filename` 而 `Mode=Normal`，
  MaaCore 日志会报 `InfrastAbstractTask::current_room_config custom is not enabled` → 用的是**默认换班**（会按 MAA 逻辑把你的基地改掉）。
- **`Filename` 必须是绝对路径**：只给文件名 → `custom infrast file does not exist: 243-….json`。
- **文件名用 ASCII**：中文名（`243-钱书均衡-龙门币优先.json`）会找不到；改成 `maa-243-custom.json` 即可。
- **一图流导出的 MAA JSON 可直接喂 MAA**（schema 兼容），不一定要转换（`tools/convert_to_maa.py` 可加 `skip/autofill/id`，非必需）。
- 结果：`Mode=Custom` + 绝对 ASCII 路径后，日志 `InfrastTask::parse_and_set_custom_config | custom json: {...}` → 正常按方案换班。
- ⚠️ **仍会卡**：本次跑到"制造站1（作战记录）"时反复翻页、`select_custom_opers ... no custom operators found`，
  在列表里找不到目标干员（食铁兽/铅踝/娜斯提，均已持有）→ 卡死。疑似与"干员被派驻在别处/列表排序过滤"有关，**未解决**；
  可能要先把目标干员从别处撤下，或改方案。**放弃该路线时：把 `Mode` 改回 `Normal`（一键换班）。**
- 改 MAA 配置前先停 MAA（运行中改会被覆盖），备份到 `%TEMP%\opencode\gui.new.json.bak-*`。

## 附：正确跑一次"干员识别 / 仓库识别"的步骤（已跑通）

1. 确认 MAA **空闲**（没在跑日常队列；有的话先点「停止」）。
2. 触控模式 = `MaaTouch`（`gui.new.json` 的 `ConnectSettings.TouchMode`）。
3. （锁屏下）找 MAA 主窗口句柄 → `WindowPattern.SetWindowVisualState(Normal)` 显示。
4. UIAutomation：选 `小工具` Tab → 选 `干员识别`/`仓库识别` 子 Tab → `Invoke` `开始识别` 按钮
   （按钮须 enabled）。
5. 等待：干员识别 ~50s；结果落 `C:\MAA\data\OperBoxData.json`（本轮 337 个）/ `DepotData.json`（60 项）。

## 14. 活动关作业工作流（MAA Copilot，2026-10-09 跑通）
> 完整工作流文档见 **`docs/WORKFLOW-活动关作业.md`**；脚本 `scripts/event-copilot/event_copilot.py`。

- **MAA Copilot 任务本身不含关卡导航**（读 `Interface/CopilotTask.cpp`）：8 个子任务第 2 个就是找 `BattleStartPre`，
  即"你已站在关卡准备界面"。**导航只在多作业路径** `params["copilot_list"]=[{id,filename,nav_name_override,is_raid}]`，
  由 `MultiCopilotTaskPlugin::navigate_to_stage` 实现：有模板走模板，否则**图像分析+OCR 找关卡代号**（如 `YW-5`）点击、
  找不到就 `Copilot@StageNavigationSlowlySwipeLeft` 翻页。⇒ **单作业 `filename` 模式不会自动走到关卡**。
- **`Not support stage` 根因**：`BattleProcessTask::set_stage_name` 用 `resource/Arknights-Tile-Pos/overview.json` 索引校验关卡；
  MAA 资源只随 OTA 更新而 `ota.maa.plus` 本机不可达(000) → 资源停在旧版、不认识新活动。
  修复：从 **GitHub `MaaResource/main/resource`** 整体替换 `overview.json` + 补该活动 Tile-Pos。改完要**重启已在跑的 MCP/MAA 实例**（缓存）。
- **作业必须带非空 `actions`**：`/copilot/query` 列表接口的 `content` **不含 actions**，须用 **`/copilot/get/<id>`** 取完整版，
  否则 MaaCore `Json parse failed ... invalid map<K,T> key`、`append_task` 返回 0。
- **练度不够** → 自动编队 `OperatorMissing`（`reason=Unavailable`）：`check_oper_level` 不过。加 `"ignore_requirements":true` 跳过。
- **失败退理智**：非三星时 MAA 找不到 `StageDrops-Stars-3` → `TaskChainError`(msg 10000)；游戏显示"理智返还"。失败不亏，可换候选重试。
- 作业站 API 基址 `https://prts.maa.plus`；MAA GUI 代码里写死的就是它（`MAA.dll` 字符串 `https://prts.maa.plus/copilot/get/`）。
- 本轮 act52side：YW-5 通关(2星)、YW-6/7/8 三星；同一关首个候选未必过（YW-5 首候选失败，换"挂件兼容"系列才过）。
- **活动经济**（刷多少关换道具）：见 `scheduling/tools/event_economy.py` + `scheduling/data/event_<id>.json`。
  数据来源：关卡理智→PRTS 关卡页；**代币/次 游戏内不显示**，只能"打一关看余额增量"或等 PRTS/一图流；商店价/限购→游戏内活动商店。
  新活动当天 web/PRTS/企鹅都还没有商店与代币数据（本轮 act52side 实测：PRTS 无商店页、企鹅 matrix 为空）。
  **实测代币规律**：代币=理智×星——YW-8 三星 +21(=理智21)、YW-5 二星 +6(=理智12 的一半) → **刷代币必须三星**。
- **刷关**：`run --loop N`（Copilot `loop_times=N`）。**编队**：`formation_index=4`（只用第四编队，避免覆盖用户其它编队）。

## 15. MAA 任务/操作 补充（2026-10-09）
- **adb 滑动在本机彻底失效**：`adb shell input swipe` 与 `input touchscreen swipe` 都**不滚动**（实测商店纹丝不动）。翻页/滑动只能用 **MAA（MaaTouch）**。→ 别再用 `ark_swipe` 那类 adb 滑动。
- **MaaCore 只认注册过的任务类型**：`append_task("SlowlySwipeToTheUp", {})` 报 `invalid type`（ProcessTask 名字不能直接 append）。
- **`Custom` 类型可以跑 tasks.json 里的任意任务**：`append_task("Custom", {"task_names": ["SwipeToTheUp"]})` → MaaCore 用 ProcessTask 执行这些任务（内部 `CustomTask::set_params` 校验 `task_names` 存在）。
  于是可用 MAA 的 `SwipeToTheUp/Down/Left/Right`、`SlowlySwipeToThe*`、`ChapterSlowlySwipeToThe*` 等**通用滑动任务**，走 MaaTouch 完成 adb 做不到的滑动。
  实测：`Custom`+`SwipeToTheUp` 对活动商店**未翻动**（疑商店非该方向/仅一屏），翻页方案待定。
- **作业站 prts.maa.plus 的 `query` 列表接口 content 不含 `actions`**，完整版在 `/copilot/get/<id>`（见 §14）。
- 活动商店（act52side「劳工配给所」）第 1 屏 12 件已录（见 `scheduling/data/event_act52side.json`）；翻页未解决。
- **【关键】MCP 跑"驱动设备"的任务前必须先 `ark_connect`**：否则 MaaCore `Controller::swipe` 报 **`m_controller is not inited`**，滑动手势/Copilot 等**静默无效**（`ark_screenshot` 走 adb 仍正常，易误判）。
- **活动商店/干员/仓库都是左右翻页**（用户口径）。翻页用 `Custom` + `SlowlySwipeToTheLeft/Right`（**先 connect**）：
  `ark_run_task("Custom", {"task_names":["SlowlySwipeToTheLeft","SlowlySwipeToTheLeft"]})`，实测可连续翻动商店。

## 16. 干员培养推荐（按挂机作业出现率，2026-10-09）
- 脚本 `scheduling/tools/oper_appearance.py`；skill `arknights-oper-training`。
- 口径：从 `https://prts.maa.plus/copilot/query` 抓 **`document=挂机`** 的作业（`orderBy=views`，`limit=100` 翻页），
  统计**顶层必选 opers** 出现次数 / 样本数 = 出现率；对照 `OperBoxData.json` → owned-not-E2 = 培养目标。
- 实测 1500 作业：必选高频 煌34.5%/艾雅法拉33%/德克萨斯27%/乌尔比安23%/歌蕾蒂娅23%/塞雷娅22%/圣聆初雪19%；
  **建议精二**(owned 未 E2)：德克萨斯、乌尔比安、伊芙利特、山、夜莺、拉普兰德、澄闪…；
  **缺但高频**：煌、艾雅法拉、纯烬艾雅法拉、阿斯卡纶、黍。
- 作业站 `document=` 参数 = 按标题/详情关键字筛（实测可用）；`orderBy=views|hot|hot_score`。

## 17. 森空岛在线接口（免模拟器读本人账号，2026-10-10）
- 实现 `scripts/skland/skland_client.py`（**仅标准库**）；适配 MAA 形态 `scripts/skland/skland_box.py`；
  MCP 工具 `ark_operbox_online` / `ark_infrast_status`。用法/映射见 `docs/DATA-SOURCES.md` §7。
- 登录：手机号+密码 / 短信验证码 → 鹰角 `token` → `oauth2/v2/grant` → `generate_cred_by_code` 换 `cred` + 签名密钥 `token`。
- **三个必踩的坑**：
  1. 数据请求**必须带 `sign`**：不带 → `401 code=10000 请求异常`（**不是** `10002 未登录`，
     极易误判成"凭证过期"而白折腾）。`sign = md5(hmac_sha256(sign_token, path + query/body + ts + json(header)))`，
     `header = {platform,timestamp,dId,vName}`。
  2. **`dId` 用随机值就能过**（服务端不校验真伪）→ 不必引数美 / `cryptography`；本地生成一次持久化即可。
  3. POST 漏 `Content-Type: application/json` → `400 参数错误`（`generate_cred_by_code`、签到都中招）。
- **签到/取数前先续期 `sign_token`**（2026-10-14 实测）：长期没跑时签名密钥 `token` 会过期，
  `attendance` POST 同样报 `401 code=10000 请求异常`（**与「缺 sign」表现一模一样，别只往缺 sign 上想**）。
  修法：**先跑 `skland_cli.py status`**（内部 `refresh_token(cred)` 换新 token 并落盘）**再 `checkin` 即可**。
  `scripts/daily-auto/daily_auto.py` 的签到步骤已固定「先 status 续期 → 再 checkin」。
- 数据与 MAA 同源：对拷本人账号 337 干员，elite/level/rarity **全一致**；potential 5/337 不一致
  （MAA 识别误差，**以在线为准**）。Skland 还会多出"本地资源未收录的新干员"。
- **接口没有**：抽卡记录、仓库 Depot（Depot 仍只能靠 MAA）。
  → 但抽卡记录**不是没有官方接口**，而是**不在森空岛**：在鹰角官网用户中心
  `ak.hypergryph.com/user/api/inquiry/gacha/*`（走 `x-role-token`+`ak-user-center` cookie，
  无需 cred/sign）。两套共用 `as.hypergryph.com` 登录，分叉在 OAuth `grant` 的 `appCode`。
  详见 [`DATA-SOURCES.md`](DATA-SOURCES.md) §8 与 `scripts/skland/gacha_client.py`。
- GUI `scripts/skland/skland_gui.py`（照 cx-downloader：配色/线程/主题/标题栏）。**干员列表别用 CTk 控件逐行渲染**
  （341 行 × 每行 6 控件 ≈ 2000 控件，明显卡顿）；改用原生 `ttk.Treeview`（一行一 item）→ 筛选/排序 <10ms。

## 18. 「arknights 工具从会话里消失」的根因与恢复（2026-10-10）
- **症状**：主会话与 `task` 委派的 game 子 agent 里**都没有** `arknights_ark_*` 工具（`godot_*` 正常、agent 配置没动），
  但 `arknights_mcp.py` 进程仍在跑。工具名实际是 **`arknights_ark_connect` / `arknights_ark_run_task` …**
  （opencode 给 MCP 工具加 **server key 前缀**：`<mcp配置key>_<函数名>`，不是裸 `ark_*`）。
- **根因**：上一会话为让 MCP 重载资源 **kill 了 MCP 子进程**；opencode **不会自动重启**该 MCP server
  （实测 kill 后 8s+ 无新进程），且即便 MCP 进程「健康」（`opencode mcp list` 显示 connected），
  **已断开的 serve 也不会把工具重新注入新会话**。工具是在 **opencode 进程启动时**建立连接并注入的，
  之后不会再动态重连 → 新会话拿不到工具。
- **误判排行（别浪费时间）**：
  1. `opencode mcp list` 显示 `arknights connected` **不代表当前会话能用**——它是**独立进程**自己新起的连接，只是证明 server 本身健康。
  2. 把工具名当成 `ark_*` 去改 `tools` 前缀 → 无用。opencode 的前缀是 `<server key>_`，即 `arknights_`，配置里本来就写对了。
  3. 反复 kill MCP 进程 → 只会让状态更坏。
- **唯一恢复**：**重启 opencode**（关掉重开 opencode 进程；serve 重新启动会重新起 MCP 子进程并注入工具）。
  重启后 `%TEMP%\arknights-mcp.log` 会新增一行 `===== arknights-mcp 0.3.0 启动 =====`，且新 `arknights_mcp.py` 的父进程 = 新 `opencode serve`。
- **快速自检**（判断当前会话有没有工具）：直接在会话里看有没有 `arknights_ark_*` 工具（或让其 `ark_version`）；
  外部验证：`Get-CimInstance Win32_Process` 看 `opencode.exe serve` 与 `arknights_mcp.py` 是否**成对、同启动时刻**。
- **教训**：改完 MAA 资源别急着手动 kill MCP；要重载就**整体重启 opencode**，一步到位。

## 19. 活动商店：MaaCore v6.18.0 **不支持** `params.event_shop.blacklist`（2026-10-10 实测踩坑；**6.19.0 已解除 → 见 §21**）
- **做了什么**：想「只买 6 件家具(310)」，按 dev-v2 源码 `CustomTask::parse_and_register_event_shop` 的读法传
  `ark_run_task("Custom", {"task_names":["SS@Store@Begin"], "params":{"event_shop":{"blacklist":[...]}}})`。
- **结果**：`CustomTask::set_params` 只跑 1ms、**无 `Parsed and registered EventShop task` 日志**、**无 `EventShop` 插件日志** →
  黑名单没注册；跑的是**原生 `SS@Store` 流水线**（ClickItem→ChooseMaxAmount→Purchase→PurchasedConfirm），
  **按 MAA 固定 ROI（`SS@Store@ClickItem` roi x∈[0,690]，只有左半屏）无脑买**，花掉约 424 代币（773→349）买了 2 件，
  第 3 件遇到「货币不足(ReceivedAllMail)」才 Stop。
- **根因（推断）**：本机运行 **MaaCore v6.18.0**，而 `blacklist` 特性只在 **dev-v2 源码**（比 release 新）。
  → **别拿 dev-v2 源码当运行版的接口依据**；用某个 param 前先确认运行版是否支持（看日志有没有对应注册行）。
- **对策/教训**：
  1. 选择性买活动商店**不要**用 `SS@Store@Begin`(+blacklist)——v6.18.0 会**按 ROI 无脑买**。
  2. 想精确买：**手动点**（tap 商品卡→选数量→支付），或升级 MAA 到支持 blacklist 的版本再评估。
   3. 用 `SS@Store` 前先看日志有没有 `Parsed and registered EventShop task`——没有就别放它自己跑。

## 20. 坑：`plan_util.load_costs()` 只含活动关 → 非活动关按 **0 理智**参与逐日分配（2026-10-12 修复）
- **症状（复盘层发现）**：培养关 `MN-4`（12 理智）在 `plan_util.distribute_daily` 里 `cost.get('MN-4', 0) = 0`，
  于是这天真实负载 406+12=**418 > day_cap 406** 却被当成 406 → `over` 判 false、自检探针漏判。
- **根因**：`load_costs()` 只合并 `BUILTIN_COST`（Annihilation/1-7）+ `event_*.json` 的 `stages[].sanity`，
  **主线/材料/资源关**（MN-4 等培养关、CE-6 等）根本没有价目，一律按 0。
- **修复**：新增 `_load_stage_apcost()`，读本机关卡表 **`C:\MAA\resource\stages.json`** 的 `apCost`
  （结构：`[{code, apCost, ...}]`；兼容 ArknightsGameData 的 `{stages:{id:{code,apCost}}}`），
  `load_costs()` 优先级：关卡表 → 内置已知 → 活动价目表（活动关权威）；再对 `EXPLICIT_COST={"MN-4":12}` 兜底。
  结果 `lru_cache(maxsize=1)` 缓存（`distribute_daily` 在自检循环里反复调用，别每次重解析 807KB）。
- **探针核对**：`plan_week._fit_to_schedule` 读的是 `daily[0].get("unplaced")`（**正确**，`distribute_daily` 返回 **list**）；
  全仓无 `getattr(x,'unplaced')` 写法 → **未踩**，未改。（`getattr(list,'unplaced')` 会恒返回默认值，是无效探针。）
- **修复后 W42**：day_cap=406，逐日 406/406/406/406/406/402/405，**全部 ≤ cap**，`unplaced` 空；
  代价：自检触发 5 次（YW-6 39→34 次，释放的理智回流 1-7 填充），total 2837 ≤ 预算 2840。
  ⚠️ 待观察：容量卡满（预算 2840 ≈ 7×406=2842）时自检**优先砍活动**换 1-7 填充，是否该反着来（保活动）需运筹层定。

## 21. MaaCore **6.19.0** 更新盘点：§19 的 `event_shop` 黑名单**已被官方支持**（2026-10-12，旧结论作废）

- **背景**：本机 MAA 已从 **6.18.0 升到 6.19.0**（Release 2026-10-11；上一版留在 `C:\MAA\.old`）。
  按仓库纪律先扒差异，再定怎么并进流程 → 完整评估见 [`MAA-6.19-融合评估.md`](MAA-6.19-融合评估.md)。
- **核对方法（三证）**：GitHub Release 正文 + **本机 DLL 字符串实测**（`C:\MAA\MaaCore.dll` vs `C:\MAA\.old\MaaCore.dll`）
  + dev-v2 源码。**别只信 Release 正文**（正文不写接口）**，也别只信 dev-v2 源码**（可能比 release 新）。
- **实测关键差分**（`MaaCore.dll` 字符串计数）：

  | 字符串 | 6.18.0（`.old`） | 6.19.0 | 含义 |
  |---|---|---|---|
  | `OperProgress` | **0** | **92** | 新增「干员培养」任务真·可用 |
  | `event_shop` | **0** | **1** | **§19 作废**：`params.event_shop.blacklist` 现在能被解析 |
  | `AutoRaisePotential` | 18 | 18 | 旧版就有（非新） |
  | `DepotMaintain`（Core） | 0 | **0** | 库存保持**不是** Core 任务，只在 GUI（组装 `Fight`+`drops`） |

- **§19 的旧结论**：v6.18.0 上传 `Custom(SS@Store@Begin, params.event_shop.blacklist)` **无任何注册日志、被静默忽略**，
  于是当次改**手动点**买商店。**现状**：6.19.0 的 DLL 里已有
  `CustomTask::parse_and_register_event_shop` / `SS@Store@Begin` / `registered EventShop task` /
  `set_params failed, event shop blacklist item is not string` ⇒ **能力已落地**。
  ⚠️ **但「DLL 有字符串」≠「已跑通」**：仍需实跑一次看日志有没有 `registered EventShop task`（见评估文档 §三 P0）。
- **教训（复用 §19 的）**：升级后再评估一次是有价值的动作 —— 本次就是升级把一条旧限制解掉了；
  同时提醒**接口要以运行版 DLL/源码为准**，`params` 用前先看日志有没有对应注册行。

## 22. 【口径错数据】连战上限我们写死成 6，其实是 **10**（2026-10-12，用户当场指出）

- **现象**：`plan_week.RULE` 一直用 `normal_series = 6`（活动关用 10）。用户指出「连战上限是 10 不是 6，
  你去 MAA GUI 版本搜也是一样的，可能 maa cli 没及时维护」。核对：**用户对**。
- **源码判据**（dev-v2 `src/MaaCore/Task/Interface/FightTask.cpp:91-97`）：
  ```cpp
  const int series = params.get("series", 1);
  bool is_new_series_list = Task.get("FightSeries-OldMethodFlag") == nullptr;
  if (series < -1 || (series > 10 && is_new_series_list) || (series > 6 && !is_new_series_list)) { ... }
  ```
  ⇒ **资源里没有 `FightSeries-OldMethodFlag` 这个任务 = 新列表（上限 10）**；有 = 旧列表（上限 6）。
- **本机属哪一支（实测）**：`C:\MAA\resource\tasks\tasks.json` **无** 该键（`FightSeries-OldMethodFlag in d == False`），
  `asst.log` 也报过 `Unknown task: FightSeries-OldMethodFlag` ⇒ **新列表，上限 10**。
- **根因（不是"抄错一个数"这么简单）**：
  1. `MAA-INTERNALS.md` 其实**两条都写了**（`>10`（新列表）/`>6`（旧列表））—— 信息是全的；
  2. 但 `RULE` 把「旧列表的上限 6」当**通用值**写死，**从没核过本机属于哪一支**；
  3. **最该抓的信号是自相矛盾**：同一份 `RULE` 里活动关用 `series=10` —— 若真是旧列表，活动关第一次
     `set_params` 就该失败；而活动关 `series=10` **早就实测跑通过**（10-11 刷 YW-6 就是 10）。
     **两个互斥口径同时存在，却没人拿去交叉验证**。
- **纪律修正（写死进流程）**：
  1. 写进代码/文档的**外部数字必须绑「判据 + 证据」**：出自哪个版本、哪一行源码、哪次实测；
  2. **同一规则里出现互斥口径 = 立即核实的信号**（不是"取个保守值先跑"）；
  3. **能用现成实验自证的必须交叉验证**（本例：`series=10` 已跑通即等于"本机是新列表"）；
  4. **别写死上限** —— 改成按运行版资源判定（`FightSeries-OldMethodFlag` 在不在），代码自己判分支。
- **修**：`RULE.normal_series` 6 → 10（`maa_week` 的 `ARK_SERIES` 默认同改）；`MAA-INTERNALS.md` 的 series 说明
  补「本机无 OldMethodFlag → 上限 10」；待办：把上限做成**运行时按资源判定**而不是常量。

## 23. 雷电模拟器「有概率出现」的广告 = 独立包 `com.android.flysilkworm`（2026-10-14）

- **现象**：雷电有时在启动器 / **游戏之上**弹全屏广告（如「剑侠世界4 · 预下载」），会盖住明日方舟，
  干扰 MAA 的识别与点击（实测：`sanity_potion` 拉起游戏时就被它盖住）。它是「有概率出现」的，不是每次都弹。
- **定位**（`dumpsys window | grep mCurrentFocus`）→ `Window{… com.android.flysilkworm}`。
  它是**独立包**：`pm path com.android.flysilkworm` → `/data/app/…/base.apk`，**用户应用**（非系统应用，可正常禁用/卸载）；
  窗口 `appop=SYSTEM_ALERT_WINDOW`（悬浮窗权限）→ 所以能盖在**任意界面**之上（包括游戏）。
- **检测信号（确定性）**：`dumpsys window windows` 里存在 **`isVisible=true`** 的该包窗口 ——
  在屏→有该窗口、杀掉→整份 dump 里没有。⚠ 别只 grep `mCurrentFocus`（广告不一定抢焦点）。
- **处理**：
  - 治标：`am force-stop com.android.flysilkworm` → **立即消失**（`mCurrentFocus` 从它回到游戏）；但会自启。
  - **治本**：`pm disable-user --user 0 com.android.flysilkworm`（`new state=disabled-user`）→ 不再出现；
    `pm enable` 可恢复。**本机已于 2026-10-14 执行 --disable 永久禁用**。
- **坑**：别靠「点广告上的 ✕」——✕ 位置随广告素材变，盲点会误触主界面按钮；**按包名/窗口处理**确定性高得多。
- **落地**：`scripts/ldplayer-ad/ldplayer_ad_guard.py`（`--status` / `--once`(默认,force-stop) / `--watch` /
  `--disable` / `--enable` / `--uninstall`）。注：禁用是 **per-user**，模拟器**重置/重装后需重跑 `--disable`**。

## 24. 基建 `Infrast` **Rotation（队列轮换）** 到底做了什么 —— 「换班没换成 + 菲亚梅塔没置换」的根因（2026-10-14，源码+日志双证）

- **起因**：用户反馈上次基建「有一些换班没换成，菲亚梅塔也没有置换」，问 `gui.new.json` 里的 `InfrastTask` 是不是配错了。
- **结论：配置没错，这是 `Mode=Rotation` 的**能力边界** —— 那两件事它天生做不到，不是配错。**
- **源码依据**（MaaCore 6.19；本地 clone 在 `%TEMP%\MaaAssistantArknights`，与 GitHub 同源）：

  | 事实 | 出处 | 含义 |
  |---|---|---|
  | `fiammetta_recovery_enabled = (mode == Default) && …` | `InfrastTask.cpp:74` | **菲亚梅塔只在 `mode=0` 生效**；Rotation/Custom 下永不置换 |
  | `task->set_skip_shift(mode == Rotation)`（Mfg/Trade/Reception） | `InfrastTask.cpp:81` | **Rotation 下 MAA 不摆干员** |
  | `rotation_skips = { "Dorm","Power","Office","Control" }` 直接 `continue` | `AsstInfrastDef.h:85-91` | Rotation **整个跳过**宿舍/发电站/办公室/控制中枢 |
  | `if (mode == Rotation) m_subtasks.emplace_back(m_queue_rotation_task)` | `InfrastTask.cpp:126-127` | Rotation 唯一的「换班」= 点一次游戏内**「队列轮换」** |
  | `filename` 只在 Custom 用（`if (mode != Custom) …` / `:259`） | `InfrastTask.cpp:203,259` | Rotation 下 `Filename` 指向的 `maa-243-custom.json` **根本没被读** |
  | Custom 模式读 plan 的 `Fiammetta` 块，插一个 DormTask 放 `[target, 菲亚梅塔]` | `InfrastTask.cpp:420-464` | **想做菲亚梅塔置换 → 必须 `mode=10000 (Custom)` + 带 `Fiammetta` 的排班表** |

- **日志实证**（`C:\MAA\debug\asst.log`，最后一次 Rotation 运行 2026-10-12 19:29–19:32）：
  - `run subtask 2 / 13` = `InfrastEnterRotation`：点 `InfrastOverviewEnter.png` → **点 `InfrastQueueRotation.png`(1070,644)**
    （= 游戏内「队列轮换」按钮）→ `InfrastEnterTrim` → `InfrastTrimClick` → Return。**这就是全部的「换班」动作。**
  - `skip shift in rotation mode` **出现 7 次** = 制造站 4 + 贸易站 2 + 会客室 1（正好对上 243 布局）→ 生产/贸易/会客室**一个干员都没换**。
  - 13 个子任务里**没有** Power/Office/Control/Dorm（被 `rotation_skips` 砍掉）→「有些设施没换」是结构性的。
  - 全日志 `Fiammetta` **0 次命中** → MAA 从没做过菲亚梅塔置换。
- **所以**：
  - 「有些换班没换成」= Rotation 只点一次「队列轮换」，**整基地一次性切到另一套队列**；切完哪些设施变了，
    完全取决于**游戏内队列 1/2 各自的进驻表**（哪边没配/配空，那边就不变）。要「每个设施都换」得把**游戏内两套队列都配满**。
  - 「菲亚梅塔没置换」= Rotation 能力边界；2026-10-12 归档说明（`历史版本/基建改MAA轮换+队列按天-2026-10-12/README-历史版本说明.md`）
    里已写明「菲亚梅塔恢复：**不再做**（MAA Rotation 下 `skip_shift=true`）」。
- **⚠ 配置自相矛盾（待用户裁定）**：`gui.new.json` 里 `Mode=Rotation` **却**把 `Filename` 指向
  `C:\MAA\resource\custom_infrast\maa-243-custom.json`（一图流 243 两换，**两份 plan 都 `Fiammetta.enable=true, target=但书`**）
  —— Rotation 下这文件是死的。要它生效必须 `Mode=Custom`。
- **⚠ 改 Mode 的坑**：`scripts/maa-week/maa_week.py` 的 `cmd_write` **硬把 `Infrast.Mode` 写回 `Rotation`**
  （`maa_week.py:331-334`）→ 只改 `gui.new.json` 会被下次 `maa_week write` 覆盖，**必须同时改 `maa_week` / `plan_week` 的口径**。
- **三条可选（供裁定）**：

  1. **保持 Rotation**（现状）：换班全靠游戏内队列 1/2；要「逐设施都能换」→ 去游戏里把**两套队列都补满**。
  2. **`Mode=Custom(10000)` + `maa-243-custom.json`**：MAA 按一图流 A/B 方案**逐设施摆干员**并**执行菲亚梅塔置换**
     （`Fiammetta.target=但书`）—— 这才是这个文件存在的意义；代价 = MAA 排班覆盖游戏内队列、方案里的干员要齐。
  3. **`Mode=Default(0)` + `FiammettaRecoveryEnabled=true` + `FiammettaTarget1/2/3`**：MAA 自带算法换班 + 菲亚梅塔恢复；
     代价 = MAA 会按它自己的逻辑改你的基地（见 §13）。

### 24.1 裁定与落地（2026-10-14 当日执行「选 2」）

**用户裁定：选 2** —— `Mode=Custom(10000)` + `C:\MAA\resource\custom_infrast\maa-243-custom.json`。

**先取证降风险**：用森空岛干员箱比对方案表 → 两份 plan 各 29 名干员，**缺失 0**（`菲亚梅塔`、`但书` 均在 box 内）。
⇒ 「方案里有你没的干员，摆不上」这条风险**排除**。

**关键坑（写代码前必须知道）**：
- `plan_index` **必须显式传**：MAA 不读 plan 的 `period`（那是 GUI `PlanSelect=-1`「按时间自动」才用的逻辑，
  且我们 14:00/02:00 落在文件的 08:00-10:00 / 20:00-22:00 窗口**之外**，GUI 那条路会 fallback 到 plan 0 + 报错）；
  更致命的是 `index < 0` → `set_params` false → **append 0 打死整队**（`InfrastTask.cpp:302`）。
- `filename` 只在 `mode=Custom` 时被读（`:259-279`）；GUI 的 `PlanSelect == -1` 在 Serialize 时**不传** `plan_index`。
- Custom 下 `drones` / `threshold` 由**方案表**决定（Core 侧 `if (mode != Custom)` 才吃 `drones` 参数）。

**班次映射**（各 720min，对齐 12h）：
| 时刻 | 任务 | `plan_index` | 理由 |
|---|---|---|---|
| 14:00 | 「方舟·每日日常」 | **1（A班）** | A班 `period` 20:00-22:00 落在 14:00→02:00 这一班内 |
| 02:00 | 「方舟·凌晨基建换班」 | **0（B班）** | B班 `period` 08:00-10:00 落在 02:00→14:00 这一班内 |

（映射本身是**约定**，两份 plan 质量等价；要翻只需改 `maa_week.INFRAST_PLAN_DAY / INFRAST_PLAN_NIGHT`。）

**落地清单（唯一事实源 = `maa_week.INFRAST_*` / `infrast_params()`）**：
| 文件 | 改动 |
|---|---|
| `scripts/maa-week/maa_week.py` | 新增 `INFRAST_CUSTOM_FILE / INFRAST_PLAN_DAY=1 / INFRAST_PLAN_NIGHT=0 / INFRAST_FACILITY / infrast_params()`；`TASK_DEFAULTS["Infrast"]` 与 `cmd_write` 的 `Infrast` 分支从强制 Rotation 改为写 Custom+Filename+PlanSelect |
| `scheduling/tools/plan_week.py` | `RULE` 新增 `infra_mode/infra_custom_file/infra_plan_day/infra_plan_night`；生成的 Infrast 任务 params 改 Custom 口径 |
| `scheduling/data/weekly_plan.json` | 原地把 `Infrast` 任务 params 改成 Custom 口径（**没重新生成整份计划**，保住 W42 逐日分配） |
| `scripts/night-infrast/night_infrast.py` | Infrast params 改走 `mw.infrast_params(mw.INFRAST_PLAN_NIGHT)`；新增 `_custom_plan_check()` 前置校验（坏方案表/越界 → 返回 4，**连模拟器都不拉**） |
| `C:\MAA\config\gui.new.json` | `InfrastTask.Mode: Rotation → Custom`、`PlanSelect: -1 → 1`（备份 `gui.new.json.bak-20261014-220126`） |
| 文档 | `AGENTS.md` 铁律 2、`docs/state.json`、`CHANGELOG.md`、以及 MASTER-PLAN / STATE-一键长草 / DAILY-CHECKLIST / PLAN-一键长草 / ops_manual 等口径同步 |

**离线验证（未碰模拟器）**：
- `maa_week run --dry` → `Infrast {'mode': 10000}`；`_today_tasks` 展开 = `plan_index 1`，夜间 = `plan_index 0` ✓
- `maa_week write --dry` → **只剩 3 条 Fight 改动、无 Infrast 改动** ⇒ `gui.new.json` 与代码口径已一致，
  且 `write` **不会再把 Mode 写回 Rotation** ✓
- `_custom_plan_check(1)` → `plan[1]=A班（29 名干员，Fiammetta 开→但书）`；`(0)` → `plan[0]=B班（…）` ✓
- `InfrastTask.cpp:302` 的越界分支 ⇒ **绝不能**给 `plan_index` 传 `-1`（判据已写进代码注释与本文档）

**待实测（2026-10-15 02:00 首次真跑）**：看 `scripts/night-infrast/运行日志.txt` + `%TEMP%\maa-week\` 截图 +
`C:\MAA\debug\asst.log` 是否出现 `custom json:` / `Fiammetta's target:`，以及**不再**出现 `skip shift in rotation mode`。

### 24.2 方案表换成《搓玉·合成玉》版（2026-10-14，用户「更新方案表」）

**⚠ 承上：改成 Custom 才暴露出的坑** —— `Filename` 一旦生效，就发现它指的是**错的方案**：
- `C:\MAA\resource\custom_infrast\maa-243-custom.json` 与 `scheduling/一图流产物/243-钱书均衡-龙门币优先-MAA.json`
  **sha256 完全相同**（`fbf144b2…`）⇒ 它是**钱书均衡·龙门币优先**版（制造 `[BR,PG,BR,PG]`、贸易 `[LMD,LMD]`），
  **不是《搓玉·合成玉》方案**（搓玉 = 制造产**源石碎片** + 贸易卖**合成玉**）。`MASTER-PLAN.md §5.6` 早就标注了这个坑，
  但 Rotation 时代该文件根本不参与运行，所以一直没暴露；`Mode=Custom` 一开就会**真的按龙门币优先摆**。
- 结论：不改就违反「基建一律《搓玉·合成玉》」这条铁律。

**处理**：
1. `scheduling/tools/convert_to_maa.py` 增强后，把一图流导出转成 MAA `custom_infrast`：
   `243-搓玉-合成玉-MAA.json` → **`scheduling/MAA基建排班/243_搓玉_定制.json`**。
2. **方案表放仓库**（`scheduling/MAA基建排班/`）而不是 MAA 的 `resource/custom_infrast/`：防 MAA 更新覆盖 + 可版本管理。
3. 三处引用 + yuMAArin GUI 全部改指这一份：`maa_week.INFRAST_CUSTOM_FILE`、`plan_week.RULE["infra_custom_file"]`、
   `C:\MAA\config\gui.new.json` 的 `Infrast.Filename`、`skland_gui.py` 的 `MAA_CUSTOM_INFRAST`（原硬编码 MAA resource 路径，
   会和自动化**打架**，一并统一）。
4. **`period` 按我们的换班时刻改写**（用户要求「方案表的时间改成我们现在商量的」）：源文件是 08:00-10:00 / 20:00-22:00
   （一图流建议窗口），与我们 14:00/02:00 不符 → 改成 **B班 `02:00-04:00` / A班 `14:00-16:00`**
   （生成时用 `--periods "B班=02:00-04:00,A班=14:00-16:00"`）。⚠ MaaCore 不读 `period`，只有 **GUI 的「按时间自动」**用它；
   我们的自动化一律显式传 `plan_index`，所以 `period` 改动不影响自动化，只是让 GUI 显示/自动模式与我们一致。

**转换器顺带修的两点**（一图流导出不是直接可用）：
- 一图流的 `plans[]` **没有 `index`** → MAA GUI 读 `CustomInfrastConfig.Plan.Index` 时每份方案都是 0，
  方案下拉里选哪个都等于 plan 0（`InfrastSettingsUserControlModel` 用 `Index` 当 `Value`）→ 转换时补 `index = 0..n-1`。
- **透传** `period` / `duration` / `scheduleType` / `description_post`（原版转换器把它们丢了）。

**产物核对**（`scheduling/MAA基建排班/243_搓玉_定制.json`）：
| 项 | 值 |
|---|---|
| plans | 2 份：`index 0 = B班`（period 02:00-04:00, duration 720）、`index 1 = A班`（14:00-16:00, 720） |
| manufacture | `["Battle Record", "Originium Shard", "Pure Gold", "Pure Gold"]` → 1 站产**源石碎片** ✓ |
| trading | `["LMD", "Orundum"]` → 1 站卖**合成玉** ✓ |
| 产物合法性 | 全部落在 MaaCore `ProductNames` 白名单内（`Originium Shard` / `Orundum` 都是**合法值**，
不会被当成 Unknown 而「不校验不更换」） |
| Fiammetta | `{"enable": true, "target": "但书", "order": "pre"}`（A/B 两班都是） |
| drones | `trading` index **1**（= 卖合成玉那个贸易站） |
| 干员 | 每班 29 名，**29/29 全持有**；⚠ 名单与钱书均衡版**不同**（差集 B班 8 个 / A班 6 个）⇒ 换表确实改变了排班 |

**离线验证**：`maa_week run --dry` / `_today_tasks` → `mode=10000 + filename=仓库方案表 + plan_index 14:00→1 / 02:00→0`；
`maa_week write --dry` → **只剩 3 条 Fight 改动、无 Infrast**（说明 gui.new.json 与代码口径一致）；
`_custom_plan_check(1)/(0)` → `plan[1]=A班 / plan[0]=B班（29 名干员，Fiammetta 开→但书）`，而 `(-1)` → **正确报越界**（守卫生效）；
`plan_week.py --dry` exit 0 且 Infrast params 已带新路径；`py_compile` 全过。

**快照**：`历史版本/基建方案表-钱书均衡改搓玉-2026-10-14/`（含改动前的 `convert_to_maa.py`、旧方案表、gui config）。

### 24.3 yuMAArin「基建配置」：保存前先预览排班表 → 确认（2026-10-14）

**起因**：GUI 的「保存」原本是**一步落盘**（贴 JSON → 点保存 → 直接覆盖方案表）。贴错内容（尤其**原始一图流导出**：
没有 `plans[].index`、`period` 也不是我们商量的窗口）会**静默覆盖**生产方案表；而「方案份数不足 / 产物名不在白名单 /
干员没持有」这些**肉眼看不出来**，却会让 14:00/02:00 的自动化「看着跑了却没换成」。用户要求：**先预览排班表，再确认**。

**改法**（`scripts/skland/skland_gui.py`，见 `历史版本/yuMAArin-基建保存加预览确认-2026-10-14/`）：
- 新增「预览排班表」按钮 + 只读预览框；新增 `_infra_parse / _infra_render_preview / _infra_preview / _infra_summary_lines / _infra_owned_names`。
- `_infra_save` 三步：**① 预览（解析不过就一个字节都不写）→ ② MessageBox 确认（路径 + 每班要点 + 提醒）→ ③ 才备份+写入**。
- **致命项判据 = 与转换器共用同一份**：`scheduling/tools/convert_to_maa.py` 的 `plan_fatals(cfg, room_cn=…, owned=…)`
  （纯 stdlib，`skland_gui.py` 直接 import —— 避免 GUI 与转换器两处判据漂移）。
- **校验分两级**（用户 2026-10-14 追加要求：致命项**直接禁止保存**；又问「干员未持有」是否也硬拦 → 用户答**也硬拦**）：
  | 级别 | 判据（会让 MAA 出问题的**机制**） | 项 |
  |---|---|---|
  | **✗ 致命 → 禁止保存** | 会让整队废掉 / 方案结构性无效 / **静默失效** | ① 方案份数 < 2（自动化 `plan_index=1` 越界 → `set_params` false → `append 0` **打死整队**）② 产物名不在 MaaCore 白名单（`InfrastTask.cpp:330-337` → 该房间**照常换人但不切换产物**，静默失效）③ 某班在 制造/贸易/发电/控制中枢/会客室/办公室 **一个人都没写**（等于没换班）④ **有干员未持有**（含菲亚梅塔目标 → 摆不上/置换失败，换不齐） |
  | ⚠ 提醒 → 可保存 | 只影响 GUI 显示 | 缺 `plans[].index`（GUI 方案下拉全 0）、`index` 为负 |
  （`plans` 缺失 / 不是数组 / 某 plan 缺 `rooms` 属**解析层**错误 → 更早就挡住，连预览都不给。
  ④ 只在 caller 传了 `owned` 时判 —— **转换器没有账号数据 → 自动跳过这条**，GUI 传当前 box。）
- 致命项判定与落盘在**同一处**（`_infra_save` 第 1.5 步）：`fatals` 非空 → toast「禁止保存：N 项致命问题」+ 日志 `err` + **return，不写任何字节**，且**连确认框都不弹**。

**两个写方案表的入口都拦住了**：
| 入口 | 拦法 |
|---|---|
| yuMAArin GUI「保存」 | `plan_fatals(..., owned=当前box)` → 非空即拒绝（见上） |
| `scheduling/tools/convert_to_maa.py`（脚本直写） | `convert()` 落盘前调 `plan_fatals(out)` → 打印每条 `!! 致命：…` 后 **`SystemExit`（退出码 2）拒绝写出**（**不给 `--force` 绕过**；要单班方案请另说） |


**顺带核对到的事实**（都可复用）：
- MaaCore 的 `drones` 只读 **`enable` / `index` / `order` / `room`** 四个键（`InfrastTask.cpp:466-515`），
  且 `index` 是 **1-based**（Core 里 `-1`）；一图流导出里的 `rule` 是**一图流特有**字段，MAA 不读
  —— MAA 自带排班文件（`243_layout_*.json`）的 `drones` 也只有这四个键。⇒ 转换器丢掉 `rule` **无影响**。
- 产物白名单（`InfrastTask.cpp:330-337`）：`Battle Record` / `Pure Gold` / `Dualchip` / `Originium Shard` / `LMD` / `Orundum`；
  不在其中 → 该房间**照常换人，但不校验、不更换产物**（只留一行 warning，极易漏）—— 故把它列为**致命项**。

**离线验证**：`py_compile` 过。
- **致命闸 + 确认框三条路径**（把 `MAA_CUSTOM_INFRAST`/`INFRA_CFG_LOCAL` 指到临时目录、用假 `MessageBox`，**不启动 GUI**，5 条断言全过）：
  | 用例 | 期望 | 实测 |
  |---|---|---|
  | A 只有 1 份方案 + 点「确定」 | **不写**、无确认框 | ✅ 禁止保存 |
  | B 产物写成 `OriginStone`（非法） | **不写** | ✅ 禁止保存 |
  | C 某班关键设施全空 | **不写** | ✅ 禁止保存 |
  | D 合法方案 + 点「取消」 | 弹确认框但**不写** | ✅ 已取消保存 |
  | E 合法方案 + 点「确认」 | **写入**（目标 + 留档） | ✅ 已保存 |
  （A 特意让确认框返回「确定」，证明**不是靠用户点取消**挡住的，而是闸本身拦下。）
- **`plan_fatals` 的 ownership 分支**：不传 `owned` → 致命 0 条（转换器路径）；传一个小 `owned` → **1 条致命**
  「有 N 名干员未持有…」（消息已**截断到前 8 名 + 共 N 名**，实测 238 字符，不会撑爆 toast）；传全量 owned → 致命 0 条。
- **转换器也在落盘前拦**（同 4 条规则，`convert()` 直调）：正常源 → 写出；`bad_product` / `one_plan` / `empty_plan`
  三种篡改源 → 各打印 `!! 致命：…` 后 `SystemExit`，**输出文件不产生**。
- 预览渲染：真方案表 → **致命 0 / 提醒 0**；**原始一图流导出** → 致命 0 / 提醒 2（缺 `index`）⇒ 可保存（只提醒）；
  6 种坏输入（空/非 JSON/是数组/无 plans/plans 空/plan 无 rooms）→ 各自给出可读原因。
- **离屏 Qt 实跑**（`QT_QPA_PLATFORM=offscreen` + 裸 `QWidget` 绑 `App` 的方法，**不显示窗口、不登录、不抢实例**）：
  这一节真能构建 → 按钮 `['载入当前配置', '预览排班表', '保存', '应用']`、预览框 `TextEdit` 且只读、摘要 label 正确；
  把真方案表塞进编辑框调 `_infra_preview()` → 预览框 45 行、含 `Originium Shard`/`Orundum`、结论行「✓ 校验通过」、
  致命/提醒 = 0/0；坏 JSON → 预览框显示 `✗ 无法预览：JSON 解析失败…` 且不标记为已预览。
- ⚠ 仍未验的只有**视觉观感**（「基建」页要点导航才能到，无法程序化截图那一页）。




## 25. 活动 EX 关：MAA 能打，但要注意「导航名」和「专精」（2026-10-18 实测纠正）

**结论：MAA Copilot 完全能打活动 EX 关**（`event_copilot run <event> --chain ex`）。踩过的三个坑：

1. **tile-pos/overview 才是导航依据，不是 stages.json**
   - `stages.json`（616 关）里 **0 条 `-EX-`** —— 它只服务「理智/掉落」相关逻辑（Fight 需要），不代表不能导航。
   - Copilot 的导航走 `Copilot@FullStageNavigation` + `ClickStageName`：扫关卡列表、**按 OCR 关卡名点关**，
     关卡名来自 `Arknights-Tile-Pos/overview.json`（`code` 字段，如 `YW-EX-1`）。
   - 所以 `sync`（补 overview + tile-pos）之后 EX 就能导航；**资源更新必须重启 MCP/MAA 才生效**（10-18 我就是
     在资源刚落地前跑的，误判成「MAA 不支持 EX」）。

2. **`nav_name_override` 不能传 null**
   - `append_task("Copilot", {"copilot_list":[{..., "nav_name_override": None}]})` → MaaCore 抛 C++
     异常（`OSError 0xe06d7363 / WinError -529697949`），append 直接崩。
   - 而且活动 EX **必须给值**：作业里的 `stage_name` 是 level id（`act52side_ex01`），MAA 靠 stages.json 把
     level id 映射成显示名；EX 不在 stages.json → 不给 `nav_name_override=\"YW-EX-1\"` 就找不到关。
   - 已在 `event_copilot.run_plan` 里改成固定传 `stage[0]`（关卡代号）。

3. **「全员 E2」不等于能抄：极限作业还要看专精**
   - 10-18 实测：YW-EX-1 用 3 人作业（凛御银灰/圣聆初雪/结城理）**一次通过**；
     YW-EX-2 三个「全员 E2」候选（2-3 人极限作业）**全败**。
   - 原因：`凛御银灰 专0`、`予愿安洁莉娜 专0` —— 2~3 人极限作业靠技能等级跑时间轴，专0 基本必崩。
   - **现状**（10-18 22:05 更新）：`score()` 已扩成 6 元组，加「专精总缺口 / 缺专三人数」；
     但**只用于排序**，`copyable()` 仍只看「未拥有/空组/低练/低练组」四项 → 专0 的作业照样会试。
     因此 YW-EX-2 这类 2~3 人极限作业仍可能反复失败（10-19 突袭链再次卡在 EX-2 即此原因）。


## 26. 2026-10-19 每日自动化两处失败：理智锚点误匹配 + 坏仓库基线永久卡死

当天 14:00 的每日日常 `maa_rc=0`，但 `理智rc=3`、`账本rc=4`（`运行日志.txt:364-389`）。
不是设备/网络问题，是两段代码各自的逻辑缺陷；已在同一天修掉。

### 26.1 `sanity` 把结算界面的「理智返还」当成主界面理智条 → 点进加载

- **现象**：`14:55:51` 日志「点理智条「+」(79,910)」→ 紧接着「没打开药剂面板」；
  `%TEMP%\maa-week\sanity.png` OCR 出来是 **YW-EX-2 行动结束（MISSION RESULTS）**，
  底部有「理智返还」四个字。
- **根因**：`_parse_sanity()` 旧逻辑只要 OCR 文本里含「理智」就返回锚点。结算界面的
  「理智返还」box 中心 `(203,974)` → 按 `(Δ-124, Δ-64)` 算出 `(79,910)`，直接点在结算界面上；
  随后 `sanity_panel.png` 是 `RHODESISLAND` 加载画面（游戏被打进加载）。
  为什么会在结算界面：EX 突袭链在 YW-EX-2 全候选失败（专精/练度，见 §25），
  `ex_auto` 停在结算界面没退回主界面。
- **修法**（`scripts/maa-week/maa_week.py`）：
  - `_parse_sanity()` 收紧：优先认独立 `/205` 框 / 合并「理智/205」框 / 拆框「理智+相邻 /205」，
    排除「返还/恢复/药剂/消耗…」；锚点只接受 `0.12H~0.60H`（主界面理智条约 0.32H，
    结算界面的「理智返还」在 ~0.90H）；容量数字没被 OCR 到时，只认 `sanity_potion.PLUS=(1107,282)`
    推出的已知主界面坐标带（右侧中部），不再全屏模糊匹配。
  - `cmd_sanity()` 改成状态机：结算/关卡界面 → **只按 BACK**（不点击）；加载/无文字 → **只等待**；
    认不出主界面 → 按 BACK，次数用完就退出；点了 `+` 但面板没开 → **等 2s 重试**（不再一次失败就退出）。
    仍然只有「点 +」和「点 ✕」两条点击路径，**没有点 ✓ 的路径**。
  - `daily_auto.py`：`sanity --tries 5 --back 4`（原 2/1），步骤超时 180s→480s。
- **验证**：用当天 `sanity.png` 的 OCR 框跑新 `_parse_sanity` → 返回 `None`（旧逻辑会返回 `(203,974)`）；
  按 `sanity_potion` 的真实坐标造主界面框（`/205` @ `(1231,346)`、合并框、拆框、只有「理智」）→ 均返回锚点；
  「理智返还」即使放在同一坐标 → `None`；1280×720 缩放同样命中。

### 26.2 仓库基线是「78 项缺货币」的坏快照 → 每天都会判新出现 12 种、永远不推进

- **现象**：`14:56:35` 账本 `rc=4`：「一天内新出现 12 种物品（赤金、近卫芯片…）→ 作废」。
- **证据**：`%TEMP%\opencode\ark\bundle-last.json`（10-18 18:51 建立）只有 **78** 类目，
  **连 `4001 龙门币`、`4002 至纯源石`、`4003 合成玉`、`4006 采购凭证` 都没有**；
  10-19 的 `DepotData.json` 是 **90** 类目，新增 12 项 = 4 种货币 + 赤金 + 7 种芯片，且
  **旧 78 项一个没少** → 说明上次读数不全，不是今天真「凭空多了 12 种」。
- **根因**：`revenue_ledger.build_entry()` 的护栏只判断「新出现 ≥8 种 → 作废」，而
  `cmd_settle()` 在 `depot_incomplete` 时**不推进快照**。坏基线因此永远留着：
  第二天仍与 78 项比、仍判 12 种新物品、仍 rc=4 —— **自我锁死**。
- **修法**（`scheduling/tools/revenue_ledger.py`）：
  - 护栏分岔：本次是上次的**严格超集**（原有物品一个没丢、类目更多）→ 判「上次读数不全」，
    `depot_rebased=True`；否则（物品有丢失/类目更少）仍按「本次可疑」处理。
  - `cmd_settle()`：`depot_rebased` 时虽然**本次差分仍作废**（写 `invalid` 语义、rc=4），
    但**用本次读数重建 `bundle-last.json`** → 下一次即可正常差分。
  - 账本行新增 `depot_rebased` 字段（纯追加），issues 文案区分「上次读数不全，本次重建基线」。
- **验证**：用 10-18 的 78 项快照 + 10-19 的 90 项 DepotData 跑 `cmd_settle`：
  `depot_incomplete=True / depot_rebased=True`，`bundle-last.json` 推进到 90 项，
  账本行 farm/spend 清空、无假收益；反向用 10 项残缺读数测试 → **不推进**快照。

### 26.3 后续口径

- 今天的账本行依旧是 `invalid`（诚实缺口），但基线已在 **10-19 16:32** 用当天 90 项读数
  （`revenue_ledger collect`，理智仍取 `sanity.json` 的 64）重建为 `bundle-last.json`
  → **10-19→10-20 这一窗可以从 10-20 起正常差分**，不会再白丢一天。
- 若下次仍出现「新出现 ≥8 种」且 `rebased=False`，说明本次读数反而更差（或两次都坏），
  仍会保留旧快照并 rc=4 —— 这是有意保守，不要改成无条件推进。
- EX 链失败后停在结算界面属于正常结果；现在 `sanity` 会自己按 BACK 回主界面，不再需要额外兜底。

### 26.4 长草页「今天跑完了」≠ 突袭打完了（2026-10-19 用户指出）

- **现象**：同屏出现「今日日常 ✅ 14:56」+ 日卡「突袭：YW-EX-1..8」+「需要处理：突袭 8 关」——
  看着像自相矛盾。
- **原因**：`daily_run.ok` 只由 `daily_auto` 的 `maa_rc` 决定；计划里的 Raid 槽在 `maa_week run`
  里被改道给 `ex_auto`。10-19 `ex_auto` 在 YW-EX-2 全候选失败 → 突袭没打完，但 MAA 日常主体**确实** ok。
  两边说的都是真话，UI 把它们并排展示却没说明「完成」的范围。
- **修法**（`scripts/skland/skland_gui.py`）：
  - 新增 `_today_raid_progress()`：今日计划 `raids` vs `state.json.raid_clear_done`。
  - 未清完时「今日日常」磁贴显示 `⚠ 部分完成`（不再光秃秃 ✅）；今日日卡标「突袭已通 x/n」；
    计划下加一行「日常主体完成 ≠ 今天全部跑完」。
  - 10-19 的 `daily_run` / 账本最后一条加 `repaired_at` / `repaired_note`（只加标注，不改 rc/invalid），
    GUI 把这两条历史失败降为灰字 `info` 并写「已修复，明日生效」；突袭未清仍是橙字 `warn`。
  - **`daily_run.ok` 语义不动**：改成「突袭没清就不 ok」会让 `_already_ran_today()` 失效，
    手动/补跑可能重跑一遍 MAA、多花理智。状态只改展示层。
- **验证**：离屏 Qt 渲染 10-19 长草页 → 磁贴「⚠ 14:56 部分完成」、日卡「已通 1/8」、
  告警首条仍是突袭 8 关（warn），另两条为灰字 info；`collect_alerts()` 直接调用同样输出。

### 26.5 突袭链「一关失败就整链停」是错的（2026-10-19 用户指出）

- **现象**：10-19 突袭链打通 YW-EX-1 后，EX-2 的 5 个候选全败，日志写
  「链停，不再打后面的关（后面本来就没解锁）」→ EX-3..8 突袭一次都没试。
- **为什么错**：**突袭的解锁只看「该关普通是否已通」**，与前一关突袭是否通过无关。
  当时普通 EX 已经 8/8 全通 → EX-3..8 突袭本来就都开着，不该停。
  （普通 EX 关才是顺序解锁：EX-3 普通要等 EX-2 普通通，所以普通链失败即停是对的。）
- **EX-2 为什么败**：不是脚本没启动。`%TEMP%\arknights-mcp-maa\debug\asst.log` 14:51-14:52
  显示编队完成、正常部署（遥/凛御银灰放技能），最后 OCR 到「任务失败」→ `TaskChainError`。
  5 个候选分别有 6/15 点专精缺口、2/5 人缺专三 → 2~3 人极限轴打不过（见 §25）。
- **修法**（`scripts/event-copilot/ex_auto.py`）：
  - `run_chain` 里 `not ok` 分岔：`is_raid` → 记录失败后 **continue**，继续试后面的突袭；
    普通链仍 `break`（顺序解锁）。
  - `无候选` 同样：突袭跳过继续，普通停。
  - 新增 `--budget`（默认 4800s）：本次 ex_auto 总预算，避免 7 关 × 单候选 900s 把 14:00 日常的
    外层 5400s 直接顶爆（被 kill 会停在战斗中途）；预算用完只记日志，剩余下次再打。
  - `event_copilot.run_plan` 里误导性的「链停…后面本来就没解锁」改为中性文案，链决策只由 `ex_auto` 打。
- **验证**（mock，不动设备）：EX-2 失败 → 实际调用序列 `EX-2,3,4,5,6,7,8`，EX-3..8 继续；
  普通链同样的失败 → 只到 `EX-1,EX-2`；deadline 已过 → 一关不打。

### 26.6 10-19 实跑：普通补 3 星 + 突袭 6/8 + 预算空转修复

- **普通 EX：8/8 全 3 星**。EX-4 从 2 星补到 3 星（候选 106940，262s）；EX-5~8 从 0 星补到 3 星
  （EX-5 448s、EX-6 356s、EX-7 658s、EX-8 539s），各换过 1~2 次作业。
- **突袭：已过 EX-1/2/3/4/6/7**；EX-5 连试 15 个作业（含 relaxed）未过，EX-8 只跑了第一遍。
  二者已排入 10-20 计划（`raids=[YW-EX-5,YW-EX-8]`，sanity 300、medicine 120）。
- **口径纠正**：突袭理智 = **普通同价**（EX 10/15/15/20…），**不是双倍**（2026-10-19 用户实机确认）；
  普通 2 星 = 未过（突袭解锁要普通 3 星）；突袭本身**只判过/不过**（2 星结束也算过）。
- **修复**：
  - `run_plan`：普通 2 星=失败、**超时=失败**（旧逻辑把 900s 超时当 MAA 完成）；
    `deadline` 改为**每个候选前**检查（旧逻辑只在关卡之间检查 → EX-5 第二遍 17 个候选 ×900s，
    空转近 3 小时）。
  - `ex_auto`：两遍策略（第一遍每关 1 个候选，第二遍回头换作业）；新增
    `--stages / --skip-ids / --candidate-offset / --relaxed / --second-pass-max`；
    第二遍默认每关最多再试 6 个，防止单关刷几小时。
  - 日常 `ex_auto`：单候选 900→600s，总预算 3600s（外层 5400s）。
- **留痕**：18:05 那条 EX-4「超时误判成功」在 `ex_run.jsonl` 标 `invalid`；真实 3 星记录保留。
