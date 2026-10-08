# 开发发现（留痕）

> 记录开发/调试过程中的关键事实与踩坑，供后续迭代与排障参考。
> 时间：2026-10-09

## 1. MAA 的识别原理（本 MCP 所"借用"的）

- MAA(MaaAssistantArknights) 是"看屏幕 + 模拟点击"的机器人：截屏 → 模板匹配/OCR 识别 →
  按流水线决策 → 发模拟触摸。**不读内存、不改游戏**。
- 组成（本机 `C:\MAA`）：
  - `MAA.exe` / `MAA.dll`：C# 界面；`MaaCore.dll`：C++ 核心引擎。
  - `MaaAdbControlUnit.dll`（ADB 连接）/ `MaaWin32ControlUnit.dll`（窗口截取）。
  - `opencv_world4_maa.dll`：**模板匹配**；`onnxruntime_maa.dll` + `fastdeploy_ppocr_maa.dll`：**OCR**。
  - `resource/template/**.png`：模板图；`resource/tasks/tasks.json`：任务流水线。
- Python 绑定在 `C:\MAA\Python`（`asst` 包），核心 API：`Asst.load(path)` / `Asst(callback)` /
  `set_instance_option` / `connect(adb,addr,config)` / `append_task(name,params)` / `start` / `running` / `stop`。
- 识别结果是**回调**（`SubTaskExtraInfo`，msg=20003）：
  - `what:"OperBoxInfo"` → `details.own_opers`（含 elite/level/potential/rarity）。
  - `what:"DepotInfo"` → `details.data`（`{"物品ID":数量}`）。
- 只有 GUI 会把回调结果写成 `data/OperBoxData.json` / `data/DepotData.json`；**纯脚本调用需自行落盘**。

## 2. 本机设备信息

- 模拟器：雷电 LDPlayer9，主页 `C:\leidian\LDPlayer9`；实例 0 = `emulator-5554`。
- `ldconsole.exe` 命令：`list2` / `launch --index 0` / `quit --index 0` / `quitall`。
- MAA 连接地址用 `127.0.0.1:5555`（映射到 `emulator-5554`）。
- adb 路径：`C:\leidian\LDPlayer9\adb.exe`。
- 游戏包名：`com.hypergryph.arknights`（官服 Official）。
- 账号：**博士（Lv99）**，龙门币/合成玉等数据正常（非小号）。

## 3. 关键坑：OperBox 只识别到 13 个（未解决）

- 现象：脚本跑 `StartUp + OperBox`，`own_opers` 只返回 **11~13** 个（应约 300+）。
- 观察：
  - MAA 日志里对干员箱执行了**横向**滑动 `input swipe 1644 532 465 549 2000`
    （任务 `OperBoxSlowlySwipeToTheRight`，`specificRect [1090,350]` → `rectMove [100,350]`，
    doc 注明"6个横向干员防止识别不全990px"）。
  - 手动用 adb 横向/竖向、快/慢滑动箱子，画面均**无变化**；MAA 同样没有读到更多。
  - 干员箱截图显示按"等级升序"排的最前若干 Lv1 干员（属正常排序）。
- 待排查方向：
  1. **扫描起始页面**是否正确（任务是否从"干员"界面正确进入并从头开始）。
  2. 游戏 UI 主题 / 版本与 MAA 模板是否匹配。
  3. 触控方式（`maatouch` / `adb` 均试过，均只读一屏）。
  4. 该干员箱的滚动轴向（横向 vs 纵向）与 MAA 预期是否一致。
- 影响：`ark_operbox` 依赖此识别，需先解决；也可改为 MAA GUI 的"干员识别"入口产出 JSON。

## 4. 一图流排班生成器（后续智能排班任务用）

- MAA 官方"基建排班协议"页贴了两个合作工具：
  - 一图流可视化排班生成器：`https://ark.yituliu.cn/tools/scheduleV3`
  - 自动生成基建排班表：`https://riic.autos/`
- MAA 自带 `resource/custom_infrast/*.json`（243/153/252/333）即一图流生成（署名"公孙长乐"）。
- 页面结构：布局预设含 **333 龙门币优先** 与 **333（搓玉）合成玉**；有"执行深度排班"（全局优化）；
  "导入 MAA JSON"（`input.operator-source-file-input`，accept `.json`）导入干员箱；输出含"干员培养建议"。
- **局部 vs 全局**：MAA 内置自动换班/autofill 仅按单干员效率贪心（局部最优，见协议页原文）；
  一图流生成器考虑组合/心情/轮换（近全局最优）。

## 5. 浏览器侧

- `firefox_*` MCP 连接 `127.0.0.1:2828`（火狐 AI 可读模式）。
- 该 SPA（`ark.yituliu.cn`）上 `firefox_take_snapshot` 退化（只返回 body）→ 拿不到 UID，
  文件上传需另想办法（如页面内合成 File + DataTransfer，或本地 HTTP+fetch）。
