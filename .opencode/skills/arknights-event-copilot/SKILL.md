---
name: arknights-event-copilot
description: 用 MAA 自动打明日方舟「当期活动关」（抄作业自动化）——抓 prts.maa.plus 作业、比对本人干员箱、用 MAA 多作业(copilot_list)自动战斗逐关通关。当用户说「打活动关 / 清活动图 / 抄作业 / 用 MAA 过 YW-xx 活动」时使用。脚本 scripts/event-copilot/event_copilot.py。
---

# 用 MAA 打活动关（活动关作业工作流）

主文档：`docs/WORKFLOW-活动关作业.md`；脚本：`scripts/event-copilot/event_copilot.py`。
踩坑：`docs/FINDINGS.md` §14、§15。

## 一句话
`sync`(补资源) → `plan`(抓作业+比干员) → `goto`/手动(游戏停在活动关卡列表) → `run`(MAA 逐关自动战斗)。

## 命令
```bash
python scripts/event-copilot/event_copilot.py events                 # 列活动 id 与关卡代号
python scripts/event-copilot/event_copilot.py sync   act52side       # 补 MAA 资源(新活动必需)
python scripts/event-copilot/event_copilot.py plan   act52side --top 3
python scripts/event-copilot/event_copilot.py run    act52side --stages 5,6,7,8 --try
python scripts/event-copilot/event_copilot.py run    act52side --stages 8 --loop 30   # 刷代币
```

## 铁律（都踩过）
1. **单客户端**：跑前关掉 MAA GUI / 其它 arknights MCP，否则 MaaTouch 抢占、连接错乱。
2. **MAA 必须先认识该活动**：否则 `Not support stage` / `UnsupportedLevel` → 先 `sync`（见 skill `maa-resource-sync`）。补完资源要**重启在跑的 MCP/MAA**。
3. **游戏必须停在「活动关卡列表」页**：MAA Copilot 只从这里往后接管（它不导航进活动）。
4. **导航只在多作业路径**：单作业 `filename` 模式**不导航**。脚本用的就是 `copilot_list`。
5. **作业必须有非空 `actions`**：列表接口不返回，须 `/copilot/get/<id>`。
6. **练度不足**：脚本固定带 `ignore_requirements=true`。
7. **编队**：脚本固定 `formation_index=4`（**只用第四编队，不动用户其它编队**）。
8. **失败退理智**：非三星=失败但退理智，可换候选重试（`--try`）。
9. **同关首个候选未必过**：实测 YW-5 首候选失败，"挂件兼容/单核低配"系列才过。

## 干员比对口径
- 干员箱 `C:\MAA\data\OperBoxData.json` 只有 elite/level（**无技能等级**）→ 能否过只能实跑验证。
- 排序键：`(未拥有干员数, 无可用成员的组数, 低练(E<2)数, ...)`。用户口径：**精二(E2) 算可用**；缺的干员 ≤1 可借。
