# 数据来源与取数方法（复用指南）

> 做 scheduling 的取数/建模时**先看这里**，别重新摸索。
> 数据源：**企鹅物流**（掉落）、**PRTS wiki**（规则/数值）、**一图流**（排班/关卡）、**MAA**（本人账号识别）。
> 最后更新：2026-10-09。

---

## 1. 企鹅物流 Penguin Statistics（**掉落率首选**）

- 站点：`https://penguin-stats.io`（国际）/ `https://penguin-stats.cn`（国内镜像）。
- **公开 API**（无需 key），本机用 `curl.exe -s -L --ssl-no-revoke` 取（`--ssl-no-revoke` 必加，否则 schannel 吊销检查报错）。
- 关键端点：

| 用途 | URL |
|---|---|
| 掉落矩阵（某关） | `https://penguin-stats.io/PenguinStats/api/v2/result/matrix?server=CN&stageFilter=<stageId>` |
| 关卡表 | `https://penguin-stats.io/PenguinStats/api/v2/stages?server=CN` |
| 物品表 | `https://penguin-stats.io/PenguinStats/api/v2/items` |

- 返回 `{matrix:[{stageId,itemId,quantity,times,dropRate}]}`；**平均掉落/次 = quantity / times**（`dropRate` 字段常为 null，别用）。
- **常用 ID**（实测）：

  | 名称 | itemId | | 关卡 | stageId |
  |---|---|---|---|---|
  | 固源岩 | `30012` | | 1-7 | `main_01-07` |
  | 源岩 | `30011` | | CE-5 / CE-6 | `wk_melee_5` / `wk_melee_6` |
  | 赤金 | `3003` | | LS-5 / LS-6 | `wk_kc_5` / `wk_kc_6` |
  | 基础/初级/中级/高级作战记录 | `2001`/`2002`/`2003`/`2004` | | 剿灭(长期) | 见 PRTS 关卡页 |

  （其它 itemId 自己抓 `/items` 搜名字。）

- **实测值快照（2026-10）**：
  - `main_01-07`：固源岩 `30012` avg **1.245/次**（6 理智）→ **4.82 理智/个**；另掉 基础记录≈1.24、少量源岩/糖/异铁等。
  - `wk_melee_6`(CE-6)：固定 龙门币 10000/36 理智（龙门币不在 matrix 里，是固定奖励）。
  - `wk_kc_6`(LS-6)：固定 **4 高级 + 2 中级** = 10000 经验/36 理智。

---

## 2. PRTS wiki（**规则/数值**）

- 站点：`https://prts.wiki`。用 `webfetch`；**页面极大**（导航+道具清单会灌爆输出），
  **建议交给子代理（copilot 便宜模型）提取所需数值**，只回传结果。
- 常用页面（URL 里中文按需 %编码）：

| 内容 | 页面 |
|---|---|
| 理智规则（回复/上限/药/源石） | `/w/理智` |
| 理智上限随等级表 | `/w/博士等级` |
| 每日/每周任务奖励 | `/w/任务列表` |
| 剿灭作战（周上限/关卡） | `/w/关卡一览/常态事务` 与各国剿灭关卡页 |
| 干员升级经验曲线 | `/w/干员升级数值` |
| 理智药各回复量 | `/w/应急理智浓缩液`、`/w/应急理智加强剂` 等各自页面 |

- **实测值快照（2026-10，国服）**：
  - 自然回复 **6 分钟/1 点 = 240/日**；药/源石补到 **999** 封顶；1 至纯源石 = **135 理智**。
  - 理智上限：**99 级 = 205**；117 级封顶 210（含历史 +45 / +30）。→ 每 12h 回复 120 < 205，**上线花到 ≤85 不溢出**。
  - 理智药：应急理智小样 **10** / 加强剂 **80** / 浓缩液 **120**（合剂60、顶液100 为旧版）。
  - 每周稳定额外理智：**周常 浓缩液×2 = 240**（每日任务不给理智、绿票商店不售理智）。
  - 剿灭：周合成玉上限 **1800**；当期(拉特兰 默祷圣祠) **25 理智/次 ≈370 合成玉/次**（打满约 5 次=125 理智）。
  - 每日任务合计：龙门币 9500、合成玉 100、采购凭证 5、作战记录(8基础+5初级+6中级=9600经验)。
  - 每周任务合计：龙门币 23000、合成玉 500、采购凭证 30、资质凭证 20、高级记录×9(=18000经验)、浓缩液×2。
  - 精英化 精0Lv1→精2Lv1：6★ 经验 361400 / 龙门币 589841（LMD:EXP≈**1.63**）；5★ 1.55；4★ 1.37；3★ 只能精一。
  - 作战记录经验：基础 200 / 初级 400 / 中级 1000 / 高级 2000。

---

## 3. 一图流 ark.yituliu.cn（**排班 + 关卡/材料收益**）

- 排班生成器 `https://ark.yituliu.cn/tools/scheduleV3`（用法/坑见 `docs/FINDINGS.md` §8–§11，尤其"导入 MAA JSON 要裸数组"）。
- 站点自带工具：`材料收益`、`关卡推荐`、`基建技能一览`、`精英化与专精性价比` 等（导航可进；SPA，`webfetch` 取不到动态数据，需 firefox MCP 操作）。

---

## 4. MAA（**本人账号识别**）

- `C:\MAA\data\OperBoxData.json`（干员箱）、`DepotData.json`（仓库）；识别流程见 `docs/FINDINGS.md` §5、附录。
- 读法：`OperBoxData.json` = `{done, own_opers[], source, syncTime}`；导入一图流需先抽成**裸数组**。

---

## 5. 本轮建立的模型/脚本（`scheduling/tools/`）

| 脚本 | 作用 | 产出 |
|---|---|---|
| `build_report.py` | 解析一图流产物（MAA JSON + 结果页文本） | `report_data.json` |
| `parse_training.py` | 解析"培养建议"卡片 → 逐干员培养前后技能加成 | `training.json` |
| `sanity_plan.py` | 周度理智规划（运筹模型） | `sanity_plan.json` |
| `render_report.py` | 组装自包含单文件报告 | `报告/index.html` |

- 报告里的**理智规划**=周度分配 LP：目标(养成产出/合成玉)，约束(周预算 1920、上限 205、剿灭周上限、LMD:EXP 配比)。
- 重新生成顺序：`build_report.py` → `parse_training.py` → `sanity_plan.py` → `render_report.py`。

## 6. 取数纪律（踩过）

- `curl.exe` 必须 `--ssl-no-revoke`。
- PRTS 页面巨大 → **交子代理提取**（用户有 copilot 额度，研究类走便宜模型）。
- 企鹅 `dropRate` 字段常为 null → 自己用 `quantity/times` 算均值。
- 一图流是 SPA：`webfetch` 拿不到动态表格；要交互/数据用 firefox MCP（作用域快照见 FINDINGS §10）。

---

## 7. 森空岛在线取数（**免模拟器**读本人账号）

- 接口：`https://zonai.skland.com`（鹰角官方社区 API）；登录走 `https://as.hypergryph.com`。
- 实现：`scripts/skland/skland_client.py`（**仅标准库**）。登录换 `cred` → 取数，凭证存
  `~/.arknights_skland.json`（含 `cred`/`token`/`uid`/`did`）。
- **登录链**：
  1. `POST as.hypergryph.com/user/auth/v1/token_by_phone_password` `{phone,password}`（或
     `general/v1/send_phone_code` + `user/auth/v2/token_by_phone_code`）→ `token`
  2. `POST as.hypergryph.com/user/oauth2/v2/grant` `{token, appCode:"4ca99fa6b56cc2ba", type:0}` → `code`
  3. `POST zonai.skland.com/api/v1/user/auth/generate_cred_by_code` `{code,kind:1}` → `cred` + `token`(签名密钥)
- **读数据必须带 `sign` 头**（不带 → `401 code=10000 请求异常`，**不是** `10002 未登录`，别误判）：
  ```
  sign = md5( hmac_sha256(sign_token, path + query/body + timestamp + json(header)) )
  header = {platform:"3", timestamp, dId, vName:"1.0.0"}
  ```
  **`dId` 用随机值即可**（服务端不校验真伪），本地生成一次持久化，无需数美/cryptography。
  POST 记得 `Content-Type: application/json`（漏了会 `400 参数错误`）。
- **关键端点**：

  | 用途 | 端点 |
  |---|---|
  | 绑定角色 | `GET /api/v1/game/player/binding` |
  | 全量玩家数据 | `GET /api/v1/game/player/info?uid=` → `status`/`chars`/`skins`/`building`/`recruit`/`campaign`/`tower`/`rogue`/`routine` |
  | 干员养成 | `GET /api/v1/game/cultivate/player?uid=`（与 chars 同源） |
  | 签到 | `GET/POST /api/v1/game/attendance` |

- **转 MAA 形态**：`scripts/skland/skland_box.py` → `fetch_operbox()`（`OperBoxData.json` **同构**）、
  `fetch_base()`（基建状态）。字段映射（**两处 off-by-one**）：
  `id=charId`、`name=charInfoMap[charId].name`、`elite=evolvePhase`、`level=level`、
  `rarity=charInfoMap.rarity **+1**`、`potential=potentialRank **+1**`、`own=True`；
  超集（MAA 无）：`skill_lvl=mainSkillLvl`、`spec=skills[].specializeLevel`、`favor`。
- **与 MAA 对拷**（本人账号 337 干员）：elite/level/rarity **全一致**；potential 332/337 一致，
  不一致的是 MAA 识别误差（**以在线为准**）。Skland 还会比 MAA 多出"本地资源未收录的新干员"。
- **拿不到**：抽卡记录（森空岛接口无此项 → 见 §8）、仓库 Depot（只有 MAA 有）。
- CLI：`python scripts/skland/skland_cli.py {login,status,dump,checkin,gacha}`；GUI：`scripts/skland/skland_gui.py`。
- 踩坑详见 `docs/FINDINGS.md` §17。

---

## 8. 抽卡记录（鹰角官网「用户中心」寻访记录 · **不是森空岛**）

> 2026-10-12 建立。**§7 说的"森空岛拿不到抽卡记录"仍然对**，但官方其实另有一套接口。
> 实现：`scripts/skland/gacha_client.py`（标准库）；GUI 页签「抽卡」；CLI `skland_cli.py gacha`。

- **官方入口**：官网 → 登录 → 个人中心 → **自助查询 → 寻访记录**（页面 `ak.hypergryph.com/user/headhunting`）。
- **两套接口共用 `as.hypergryph.com` 登录，分叉在 OAuth `grant`**（这是最关键的一处）：

  | 用途 | appCode | type | 结果 |
  |---|---|---|---|
  | 森空岛（§7） | `4ca99fa6b56cc2ba` | `0` | 一次性 `code` → 换 `cred` |
  | **用户中心（本节）** | `be36d44aa36bfb5b` | `1` | 直接返回 `token` |

  **用错就只能拿到一次性 code，拿不到抽卡记录**，且报错很隐晦。

- **6 步登录链**（前 3 步与森空岛同源，后 3 步是本节特有的）：

  | # | 端点 | 得到 |
  |---|---|---|
  | 1 | `POST as.hypergryph.com/user/auth/v2/token_by_phone_code`（或 `.../v1/token_by_phone_password`） | 账号 token |
  | 2 | `POST as.hypergryph.com/user/oauth2/v2/grant` `{token, appCode, type:1}` | OAuth token |
  | 3 | `GET binding-api-account-prod.hypergryph.com/account/binding/v1/binding_list?token=&appCode=arknights` | 角色 `uid`（含官服/B服渠道） |
  | 4 | `POST .../binding/v1/u8_token_by_uid` `{uid, token}` | `u8_token` |
  | 5 | `POST ak.hypergryph.com/user/api/role/login` `{token:u8_token, source_from:"", share_type:"", share_by:""}` | **`ak-user-center` cookie** |

- **取数据**（鉴权走**请求头 + cookie**，**不需要** §7 那套 `cred`/`sign` 签名）：

  | 用途 | 端点 |
  |---|---|
  | 卡池分类 | `GET ak.hypergryph.com/user/api/inquiry/gacha/cate?uid=` → `data` 直接是数组 |
  | 抽卡记录 | `GET ak.hypergryph.com/user/api/inquiry/gacha/history?uid=&category=&size=[&pos=&gachaTs=]` → `data.list` + `data.hasMore` |

  请求头：`x-role-token: <u8_token>`、`x-account-token: <账号token>`（可选）；
  Cookie：`ak-user-center=<值>`；`Referer: https://ak.hypergryph.com/user/headhunting`。

- **返回与分页（易错点）**：
  - 一条 = **一抽**；一次十连 = 10 条 `gachaTs` **完全相同**、`pos` 为 `0..9` 的记录。
  - `rarity` 是 **0 基**：`5` = 6★、`2` = 3★。
  - `gachaTs` 是**毫秒**，且常为**字符串**（`"1770697079082"`）。
  - 翻页游标 = 上一页最后一条的 **`pos` + `gachaTs`**（不是页码）。
  - 接口不提供唯一 ID → 去重键必须自己合成，**`pos` 不能省**（十连里同名同星只差 `pos`）。
  - 旧端点 `/user/api/inquiry/gacha?page=&token=` **已废弃**：现在落到前端 SPA，返回 HTML 不是 JSON。
  - 鉴权失败的是 `{"reason":"UN_LOGIN"}` / `{"reason":"MissingCookie"}` /
    `{"reason":"DETECTED_ROLE_CHANGED"}`，**没有 `code` 字段** ——
    不单独判会静默当成 `code=0`「成功」。
  - **实测（2026-10-12，不带任何凭证）**：`cate` / `history` 都返回
    `HTTP 401 {"message":"未登录","reason":"UN_LOGIN"}`（证明端点存活、需要登录）；
    旧端点返回 `HTTP 200 text/html`（证明已废弃）。
  - **cookie 与 `x-role-token` 必须配对**（2026-10-12 实测三组）：
    cookie+真 token → ✅；cookie+假/空 token → `DETECTED_ROLE_CHANGED`（服务端交叉校验）；
    无 cookie → `UN_LOGIN`。

- **能回溯多久？官方口径：90 日。**
  官网寻访记录页原话：「**可查询 90 日内寻访记录，查询结果可能存在 30 分钟延迟**」
  （2026-10-12 从页面正文抄录）。实测本人账号最早一条 2026-08-01、最新 2026-10-09，
  与 90 日窗口一致。因此：**拉到就本地留档**（`~/.arknights_gacha_records.json`，只增不删），
  这样超出 90 天的旧记录也不会丢；GUI 顶部会显示"记录区间"。
  （各开源实现都只靠 `hasMore` 收敛，没找到明确页数上限 —— 这就是原因：窗口是时间，不是页数。）

- **免密码取凭据（读本机浏览器）**：`scripts/skland/ff_session.py`。
  这两个凭据**都不在 `cookies.sqlite` 里**：
  | 凭据 | 在哪 |
  |---|---|
  | `ak-user-center`（cookie） | **会话 cookie** → 只在 `sessionstore*.jsonlz4`（自带纯 Python mozLz4 解码） |
  | `x-role-token` | `ak.hypergryph.com` 的 localStorage `ONE_ACCOUNT_ROLE_META.token` |
  | 角色 `uid` | 同 localStorage 的 `APP_CURRENT_ROLE:arknights` → `"218193258::"` |
  用法：`python scripts/skland/skland_cli.py gacha --from-firefox`，或 GUI「抽卡」页「从火狐导入」。
  局限：cookie 是会话级的，Firefox 关掉且未恢复会话就失效。

- **限制**：**仅官服**。B 服走 B 站账号、国际服（Yostar）没有这套接口。

- **旁证**：`inquiry/diamond` 是源石/合成玉消耗记录；`as.hypergryph.com/u8/pay/v1/recent` 是充值记录。
  终末地有更规范的官方记录接口 `ef-webview.hypergryph.com/api/record/char?pool_type=&token=<u8_token>&server_id=1`。

- **参考实现**（本节的端点/坑来自它们的源码与文档）：`Gordenghost/arklog`（Go，注释最全）、
  `AceDroidX/arknights-gacha-export`（`API.md` 最规整）、`RoLingG/Arknights_Gacha`、
  `DuskXi/ArkRecord`（浏览器插件，借已登录会话直接抓老接口）。
