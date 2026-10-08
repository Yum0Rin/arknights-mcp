# 开发发现 / 踩坑记录（留痕）

> AGENTS.md 只保留铁律；详细踩坑、证据、复现步骤都放这里。
> 最后更新：2026-10-09。

## 1. MAA 原理与组成（本 MCP 借用其能力）

- MAA 是"截屏 → 模板匹配/OCR 识别 → 按流水线决策 → 模拟触摸"的机器人；**不读内存、不改游戏**。
- `C:\MAA`：`MaaCore.dll`(核心) / `MaaAdbControlUnit.dll`(ADB) / `openCV_world4_maa.dll`(模板匹配) /
  `onnxruntime + fastdeploy_ppocr`(OCR)；`resource/template/**.png`(模板)、`resource/tasks/tasks.json`(流水线)。
- Python 绑定在 `C:\MAA\Python`：`Asst.load / Asst(cb) / set_instance_option / connect / append_task / start / running / stop`。
- 识别结果是回调 `SubTaskExtraInfo`(msg=20003)：`what=OperBoxInfo`(own_opers) / `what=DepotInfo`(data)。

## 2. 设备信息

- 雷电 LDPlayer9；实例 0 = `emulator-5554`；adb：`C:\leidian\LDPlayer9\adb.exe`。
- MAA 连接地址 `127.0.0.1:5555`；游戏 `com.hypergryph.arknights`（官服）；账号「博士」Lv99。

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
- MAA"基建排班协议"页贴的合作工具：一图流 `https://ark.yituliu.cn/tools/scheduleV3`；自动生成 `https://riic.autos/`。
- MAA 自带 `C:\MAA\resource\custom_infrast\*.json`（243/153/252/333）**即一图流生成**（署名"公孙长乐"）。
- 页面：布局预设含 `333 龙门币优先` / `333（搓玉）合成玉`；有 `执行深度排班`(全局优化)；
  数据源有 `导入 MAA JSON`（隐藏 `input.operator-source-file-input`，accept `.json`）。
- **局部 vs 全局**：MAA 内置 autofill 只按单干员效率贪心（局部最优）；一图流考虑组合/心情/轮换（近全局）。
  "补空缺"式打补丁会破坏组合与轮换，往往不如整份重排。

## 9. firefox-devtools MCP 在该 SPA 上快照退化
`ark.yituliu.cn` 上 `firefox_take_snapshot` 只返回 `body` → 拿不到 UID → `upload_file_by_uid` 用不了。
变通：页面内合成 `File` + `DataTransfer` 塞进 `input.files` 再 `dispatchEvent('change')`；
或本地起带 CORS 的 HTTP 服务让页面 `fetch` 本机文件（注意 https 页面请求 http://127.0.0.1）。

---

## 附：正确跑一次"干员识别 / 仓库识别"的步骤（已跑通）

1. 确认 MAA **空闲**（没在跑日常队列；有的话先点「停止」）。
2. 触控模式 = `MaaTouch`（`gui.new.json` 的 `ConnectSettings.TouchMode`）。
3. （锁屏下）找 MAA 主窗口句柄 → `WindowPattern.SetWindowVisualState(Normal)` 显示。
4. UIAutomation：选 `小工具` Tab → 选 `干员识别`/`仓库识别` 子 Tab → `Invoke` `开始识别` 按钮
   （按钮须 enabled）。
5. 等待：干员识别 ~50s；结果落 `C:\MAA\data\OperBoxData.json`（本轮 337 个）/ `DepotData.json`（60 项）。
