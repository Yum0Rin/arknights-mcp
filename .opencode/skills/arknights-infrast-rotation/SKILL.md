---
name: arknights-infrast-rotation
description: 明日方舟「基建换班」（搓玉 A/B 班轮换）自动化——收菜/干员休整、菲亚梅塔置换但书心情、13 房间切队列、写日志，一条命令跑完。当用户说「基建换班 / 收菜 / 队列轮换 / 菲亚梅塔置换 / 基建到期了」时使用。脚本 scripts/infrast-rotation/infrast_rotation.py。
---

# 基建换班自动化（搓玉 A/B 轮换）

脚本：`scripts/infrast-rotation/infrast_rotation.py`（MaaCore Custom 滑动 + adb 点击 + cv2 模板/颜色 + 本地 OCR）。
方案：`C:\Users\39007\Desktop\明日方舟排班报告.html` 的《搓玉 · 合成玉》A/B 班，每 ~12h 交替。

## 一句话
```bash
python scripts/infrast-rotation/infrast_rotation.py all
```
= 收菜（可收获+干员休整）→ 菲亚梅塔置换但书心情 → 13 房间切到当前未生效队列 → 换班后再收菜 → 写 `scheduling/data/infrast_rotation_log.jsonl`。

## 命令
```bash
python scripts/infrast-rotation/infrast_rotation.py all       # 全流程（默认）
python scripts/infrast-rotation/infrast_rotation.py check     # 只侦察不改状态（验识别）
python scripts/infrast-rotation/infrast_rotation.py collect   # 只收菜
python scripts/infrast-rotation/infrast_rotation.py fia       # 只菲亚梅塔置换
python scripts/infrast-rotation/infrast_rotation.py swap      # 只切队列
# 加 --dry-run 不改状态；加 --update-state 同时回写 docs/state.json
```

## 铁律
1. **单客户端**：跑前关 MAA GUI / 其它 arknights MCP（同刻只一个程序驱动设备）。
2. **只用用户方法，禁用 MAA 自带排班**（`mode=0` 会覆盖《搓玉》方案）。
3. **滑动只用 MAA**：干员列表翻找用 `InfrastOperListSlowlySwipeToTheRight` / `InfrastOperListSwipeToTheLeft`（通用 `SlowlySwipeToThe*`、adb swipe 无效）；点击/截图走 adb。
4. **不改队列的按钮**：别点行右侧独立 ⇄、别点底部「队列轮换」。脚本只点编辑队列面板里的青块 ⇄。

## 关键锚点（1920×1080，脚本常量 C）
- 主界面「基建」(1455,845)；基建页「进驻总览」(175,156)。
- 进驻总览页签：工作区 (1420,59) / 非工作区 (1696,59)。
- 待办蓝角标 (1841,139)（红=EMERGENCY 别点）；待办卡片第一张 (295,995)（横向排列，逐张点）。
- 第一行「编辑队列」按钮 **(763,340)**（点 (740,297) 只会选中房间行！）。
- 编辑队列面板：`⇄` 竖条 x≈1565，**青色行=可切的目标行、灰色行=当前生效行**（y 约 623/848，**每次像素扫青块定位，别写死**）；`⟫` 下一房间 (1727,500)。
- 菲亚梅塔：进宿舍房间→「进驻信息」(65,410)→点成员行 (1535,215)→编辑界面；「清空选择」(763,995)、「确认」(1670,1000)、二次确认用模板 `InfrastOperConflictConfirm.png`。

## 命名口径（重要）
`infrast_rotation_log.jsonl` 里的「队列1/队列2」**与游戏内行标签相反**（log 按 A/B 班顺序）。脚本日志用 `direction`（沿用旧口径）+ 自动翻转；写人工记录时补 `direction_game_labels`/`roster` 字段。

## 已知/待完善
- `fia` 步骤：宿舍建筑用模板 `InfrastPic/Facilities/Dorm(Mini).png` 匹配（坐标随视角漂移），**选中的可能是任一间宿舍**；干员点名靠逐卡片裁剪 OCR，命中率需实跑校验。首次全实跑请人在旁盯。
- 无人机满 250/250 会溢出，脚本不处理（另议）。
