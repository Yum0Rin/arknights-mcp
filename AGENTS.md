# AGENTS.md —— arknights-mcp 项目工作笔记

本文件记录本项目的定位、环境、约定，以及**开发过程中踩过的坑**（务必先读，能省大量时间）。

## 项目定位

- **主功能**：`arknights-mcp` —— 把 MAA(MaaCore) 的识别能力 + adb 操作封装成 MCP 工具，
  让 LLM Agent 能"观察 + 操作"明日方舟；识别全部走 MAA 的确定性 CV（模板匹配/OCR），**不用 AI 读图**。
- **子功能**：智能基建排班（见 `scheduling/`），复用主功能的识别/操作能力。

## 运行环境（本机）

| 项 | 值 |
|---|---|
| 系统 | Windows 11（26200），桌面可能处于**锁屏**状态 |
| Python | `C:\Python314\python.exe` |
| MAA | `C:\MAA`（MaaCore **v6.18.0**；Python 绑定 `C:\MAA\Python`） |
| 模拟器 | 雷电 LDPlayer9，`C:\leidian\LDPlayer9`（adb 在 `C:\leidian\LDPlayer9\adb.exe`） |
| 设备序列号 | `emulator-5554` 与 `127.0.0.1:5555` 是**同一台** |
| 游戏 | 包名 `com.hypergryph.arknights`（官服 Official）；账号「博士」Lv99 |

---

## ⚠️ 踩过的坑（血泪）

### 1. adb 把同一台设备列两次 → `more than one device`
`adb devices` 同时列出 `127.0.0.1:5555` 与 `emulator-5554`（指向同一台雷电）。
不加 `-s` 就报 `more than one device/emulator`。
**处理**：优先用 `ARK_ADDR`(默认 `127.0.0.1:5555`)，其次 `emulator-*`，每次 adb 前 `_ensure_serial()`。

### 2. `exec-out screencap` 是二进制安全的，别做 `\r\n` 替换
`adb exec-out screencap -p` 返回的是 PNG 原始字节；若做 `\r\n → \n` 替换会**损坏 PNG**，
cv2 读出来是 `None`（表现为"图像读取失败"）。只有老的 `adb shell ... > file` 才需要替换。

### 3. 【最关键】游戏(Unity) **忽略 adb 注入的"滑动"**
- `adb shell input swipe` 在本游戏里**不生效**（`tap` 生效、`swipe` 失效）。
- 后果：干员箱 / 仓库这种需要**翻页**的识别都**只读到第一屏**（本例 14 个干员），翻不动。
- 连 MAA 自己的 control（maatouch）经 Python 脚本调用也没能翻动（实测）。
- **排查方向**：触控方式、MAA 的 swipe ROI(如 `OperBoxSlowlySwipeToTheRight` specificRect)、
  或游戏是否要求特殊手势。**未解决**——识别这类"多屏列表"时务必先验证能否翻页。

### 4. 纯 Python 调 MAA ≠ MAA GUI；识别结果只在 GUI 落盘
- 纯 `asst` 脚本跑 `OperBox`：只读 1 屏；偶发**抓到全黑图**(1280×720 全黑) → `SubTaskError`。
- MAA **GUI** 的「干员识别」入口更稳，但同样受"翻不动"影响 → 也只有 14 个。
- 只有 **GUI** 会把识别结果写到 `C:\MAA\data\OperBoxData.json` / `DepotData.json`；
  纯脚本调核心要**自己在回调里接 `SubTaskExtraInfo`(what=OperBoxInfo/DepotInfo) 并落盘**。

### 5. MAA 窗口会被"桌面锁屏"藏起来
锁屏后 MAA 主窗口 `IsWindowVisible=False`：`gui_shot.ps1` 找不到、`ImageGrab` 抓到的是锁屏画面、
`PrintWindow` 可能全黑。
- 找句柄：`EnumWindows` 按 pid 过滤（MAA 主窗口 class 形如 `HwndWrapper[MAA;;...]`）。
- 显示它：UIAutomation `WindowPattern.SetWindowVisualState(Normal)` +
  user32 `ShowWindow(SW_SHOW/SW_MAXIMIZE)` + `SetWindowPos(..., SWP_SHOWWINDOW)`。

### 6. **锁屏下仍可用 UIAutomation 点按钮**（不用真鼠标）
`InvokePattern.Invoke()` / `SelectionItemPattern.Select()` 是**无障碍 API**，
不需要真鼠标、不需要解锁，锁屏也能触发。
- MAA 的干员/仓库识别入口：顶栏页签 **`小工具`** → 子页签 **`干员识别` / `仓库识别`** → 按钮 **`开始识别`**。
- 取名字用 `AutomationElement.Current.Name`；**控制台输出中文会乱码**，要写 UTF-8 文件再读。
- 可用的顶层按钮：`ButtonMin/ButtonMax/ButtonClose`、`全选`、`清空`、`Link Start!`、`添加新任务`。

### 7. 一图流排班生成器（子功能相关）
- MAA 官方"基建排班协议"页贴的合作工具：
  - 一图流可视化排班：`https://ark.yituliu.cn/tools/scheduleV3`
  - 自动生成：`https://riic.autos/`
- MAA 自带 `C:\MAA\resource\custom_infrast\*.json`（243/153/252/333）**就是一图流生成的**（署名"公孙长乐"）。
- 页面要点：布局预设含 **`333 龙门币优先`** 与 **`333（搓玉）合成玉`**；有 **`执行深度排班`**(全局优化)；
  数据源有 **`导入 MAA JSON`**（隐藏 `input.operator-source-file-input`，accept `.json`）。
- **局部 vs 全局**：MAA 内置 autofill 只按**单干员效率贪心**（局部最优，见协议页原文）；
  一图流生成器考虑**组合/心情/轮换**（近全局最优）。补空缺式的"打补丁"会破坏组合与轮换，往往不如整份重排。

### 8. firefox-devtools MCP 在该 SPA 上快照退化
`ark.yituliu.cn` 上 `firefox_take_snapshot` 只返回 `body` → 拿不到 UID → `upload_file_by_uid` 用不了。
变通：页面内合成 `File` + `DataTransfer` 塞进 `input.files` 再 `dispatchEvent('change')`；
或本地起个带 CORS 的 HTTP 服务，让页面 `fetch` 本机文件。注意 https 页面请求 http://127.0.0.1 的混用内容策略。

---

## 约定

- **版本**：语义化版本（`__version__`）。每次可用改动进 `CHANGELOG.md`（Added/Changed/Fixed/Verified）并 git commit。
- **日志**：写 `%TEMP%\arknights-mcp.log`（UTF-8）。**stdout 留给 MCP 传输，绝不 print**。
- **删除文件**：一律送回收站（见全局 `AGENTS.md`）。
- **识别结果**：`OperBoxData.json` / `DepotData.json` 在 `C:\MAA\data`；注意 GUI 与脚本两种来源格式可能不同。
- **同一时刻**只让一个客户端（本 MCP 或 MAA GUI）驱动设备，避免争抢 adb/触控。
