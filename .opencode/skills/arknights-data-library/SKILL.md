---
name: arknights-data-library
description: 资料库——明日方舟靠谱民间数据源总目录（PRTS wiki、一图流 yituliu、企鹅物流、MAA 作业站 prts.maa.plus、ArknightsGameData 官方数据表、MaaResource、森空岛等）。当需要查明日方舟的关卡/数值/掉落/作业/活动id↔名称，或要「补充/更新数据源」时使用。
---

# 资料库（Arknights 民间数据源）

> 目标：把「查明日方舟数据」要用的**靠谱民间来源**集中记在这，遇到新的就补进来。
> 本仓库还有 `docs/DATA-SOURCES.md`（取数方法）与 `docs/FINDINGS.md`（踩坑）；本 skill 是它们的**来源总目录 + 快捷入口**。

## 铁律

1. 只用**靠谱**来源；新增前尽量用 PRTS / 官方数据表交叉验证。
2. 优先**可程序化**来源（API / JSON 直链），其次才网页抓取。
3. `curl.exe` 必须加 `--ssl-no-revoke`（否则 schannel 吊销检查报错连不上）。
4. PRTS wiki 页面极大 → 交**子代理**提取，只回传所需数值（见 DATA-SOURCES.md §2）。
5. 民间站点可能改版/挂；坏了先换镜像（如 `penguin-stats.cn`），再把坑记这里。

## 数据源总表

| 名称 | 地址 | 用途 | 取数 / 备注 |
|---|---|---|---|
| **PRTS wiki** | https://prts.wiki | 关卡数值、理智、规则、活动一览、商店价/限购 | 页面巨大，走子代理；URL 中文按需 %编码 |
| **一图流** | https://ark.yituliu.cn | 排班生成、关卡推荐、材料收益、精英化性价比 | SPA，`webfetch` 取不到动态数据，需 firefox MCP |
| **企鹅物流** | https://penguin-stats.io（镜像 .cn） | 关卡掉落率（首选） | 公开 API，见下 |
| **MAA 作业站** | https://prts.maa.plus | 抄作业/自动战斗作业（含部署轴 actions） | API 见下 |
| **ArknightsGameData** | https://github.com/Kengxxiao/ArknightsGameData | 官方游戏数据表（繁/简/英），最权威的静态数据 | 读 `zh_CN/gamedata/excel/*.json` |
| **MaaResource** | https://github.com/MaaAssistantArknights/MaaResource | MAA 关卡 tile-pos、模板、任务 | 新活动补资源用（见 skill `maa-resource-sync`） |
| **MaaAssistantArknights** | https://github.com/MaaAssistantArknights/MaaAssistantArknights | MAA 本体源码（查 Copilot/任务机制） | 读 `src/MaaCore/Task/...` |
| **森空岛** | https://zonai.skland.com | 鹰角官方社区 API —— **本人账号数据**：干员(含技能/专精/模组)、基建、公招、剿灭、肉鸽、签到 | **本仓库已实现**（`scripts/skland/`，免模拟器）；需 cred + `sign` 签名；**无抽卡、无仓库**。见 `docs/DATA-SOURCES.md` §7 |
| **PRTS 数据查询** | https://prts.wiki/w/关卡一览 / w/活动一览 | 活动↔关卡代号对照 | 大表，走子代理 |

## 常用 API / 直链（实测可用）

**企鹅物流（掉落）**
- 掉落矩阵：`https://penguin-stats.io/PenguinStats/api/v2/result/matrix?server=CN&stageFilter=<stageId>`
- 关卡表：`https://penguin-stats.io/PenguinStats/api/v2/stages?server=CN`
- 物品表：`https://penguin-stats.io/PenguinStats/api/v2/items`
- 平均掉落 = `quantity / times`（`dropRate` 常为 null，别用）。

**MAA 作业站（抄作业）**
- 搜索作业：`https://prts.maa.plus/copilot/query?page=1&limit=80&levelKeyword=<关卡代号/名>&type=PRTS`
  - 列表里的 `content` **不含 `actions`**（部署轴），须再取详情。
- 取完整作业：`https://prts.maa.plus/copilot/get/<id>` → `data.content`（含 `actions`，MAA 必需）。

**官方游戏数据表（ArknightsGameData，权威静态数据）**
- 基址：`https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/`
- 关键文件：
  - `activity_table.json` → **`basicInfo` 是 活动id ↔ 中文名**（如 `act52side=昨日海`、`act3d0=火蓝之心`、`act13d5=玛莉娅·临光`）。老活动是 `actNdM` 式命名，新活动是 `actNNside` 式。
  - `stage_table.json` → 关卡（code、stageId、理智、关联活动）
  - `character_table.json` → 干员；`item_table.json` → 物品；`handbook_info_table.json`/`charword_table.json` → 剧情文本
- 单文件较大（activity_table ≈ 14MB），`curl.exe -L --ssl-no-revoke -o` 落盘再解析。

**MaaResource（关卡资源）**
- `https://raw.githubusercontent.com/MaaAssistantArknights/MaaResource/main/resource/Arknights-Tile-Pos/overview.json`
- 单活动 tile-pos：同目录 `Arknights-Tile-Pos/<filename>`
- 本地缓存：`C:\MAA\resource\Arknights-Tile-Pos\`

## 本地资产（本仓库/本机已有）

| 资产 | 路径 | 说明 |
|---|---|---|
| 活动关作业脚本 | `scripts/event-copilot/event_copilot.py` | `events/sync/plan/run/goto/shop`，抓作业+比干员箱+自动战斗 |
| 干员箱 | `C:\MAA\data\OperBoxData.json` | MAA 识别产出（own/elite/level/potential，**无技能等级**） |
| **在线干员箱/基建** | `scripts/skland/` | **免模拟器**：`ark_operbox_online`（含技能/专精）、`ark_infrast_status`；核心 `skland_client.py`、适配器 `skland_box.py` |
| MAA 资源 | `C:\MAA\resource\` | `stages.json`(关卡) / `template\`(模板) / `Arknights-Tile-Pos\` |
| 取数方法 | `docs/DATA-SOURCES.md` | 各源用法与实测值快照 |
| 踩坑 | `docs/FINDINGS.md` | §14/§15 是活动关作业 |

## 活动 id ↔ 名称：快速查法

```bash
# 1) 取官方活动表并抽出 act* 的 名称
curl.exe -s -L --ssl-no-revoke -o act.json ^
  "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/activity_table.json"
python -c "import json;d=json.load(open('act.json',encoding='utf-8'))['basicInfo'];print({k:v.get('name') for k,v in d.items() if k.startswith('act')})"
```
（PowerShell 里多行用反引号续行；控制台中文乱码不代表文件坏了，用 `PYTHONIOENCODING=utf-8` 或直接读文件。）

## 新增来源时（务必）

按「数据源总表」补一行，写清 **名称 / 地址 / 用途 / 取数方式 / 坑**；
若是 API，附上实测可用的完整 URL。改完提醒用户**重启 opencode** 生效（skill 不热加载）。
