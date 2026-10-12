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
