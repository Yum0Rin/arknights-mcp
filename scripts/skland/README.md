# 森空岛看板（scripts/skland）

登录森空岛账号，把**本人**明日方舟账号的数据拉到本地看：概览 / 干员养成 / 基建 / 公招 / **抽卡记录** /
剿灭·保全·肉鸽 / 任务 / 签到 / 原始 JSON。

> **只读自己账号。** 凭证（cred）等同账号访问权，存本机 `~/.arknights_skland.json`，别外传。

## 它怎么拿到数据

明日方舟官服走「鹰角通行证」，官网 / 游戏 / 森空岛是同一套账号。登录换到森空岛凭证 `cred` 后，
调 `zonai.skland.com` 的角色数据接口（就是官方社区 App「森空岛」自己用的那套）：

| 接口 | 数据 |
|---|---|
| `GET /api/v1/game/player/binding` | 绑定角色（uid / 官服B服 / 昵称） |
| `GET /api/v1/game/player/info?uid=` | 全量：`status` `chars` `skins` `building` `recruit` `campaign` `tower` `rogue` `routine` `assistChars` … |
| `GET /api/v1/game/cultivate/player?uid=` | 干员养成 |
| `GET/POST /api/v1/game/attendance` | 签到状态 / 执行签到 |

**拿不到「抽卡记录」——但抽卡记录另有官方来源**：森空岛接口里确实没有这项，
它在**鹰角官网「用户中心」的寻访记录自助查询**（`ak.hypergryph.com`，走请求头 + cookie，不用 cred/sign）。
两套共用同一套鹰角通行证登录，分叉在 OAuth `grant` 的 `appCode`（详见 `gacha_client.py` 与
`docs/DATA-SOURCES.md` §8）。

## 用法

### 图形界面（推荐）

```powershell
& C:\Python314\pythonw.exe "%USERPROFILE%\Desktop\arknights-mcp\scripts\skland\skland_gui.py"
```

界面是 **PySide6 + PySide6-Fluent-Widgets**（Win11 Fluent：左侧导航 / 明暗跟随系统），
配色是**方舟风的「深海蓝 + 金」**（底 `#0A121D`、卡片 `#121E2E`、强调金 `#E3BE63`/`#C9973B`）。

- 左侧「账号」页：填手机号 → 选「验证码 / 密码」→（验证码的话点「发送验证码」）→ 登录；
- **打开时自动登录**（默认开）：只要有本机凭证，开界面就直接拉数据，不用再点；
  抽卡也会顺带从火狐更新（留档超过 6 小时才更新）。开关在「账号」页，设置存 `~/.arknights_skland_gui.json`；
- 登录后自动拉数据；之后「刷新数据」重新拉，「每日签到」签到；
- 「抽卡」页：点「拉取 / 更新」或「**从火狐导入**」（浏览器已登录官网时**免密码**），
  拉完自动本地留档；「只看 6★ / 全部记录」切换视图，「打开官网记录页」跳官网；
- 没有账号想先看界面：点「载入样例数据」（用仓库自带的真实结构样例）。

依赖：`PySide6-Essentials` + `PySide6-Fluent-Widgets`（界面）。核心
`skland_client.py` / `gacha_client.py` / `ff_session.py` 只用标准库。

```powershell
# PyPI 直连慢的话用镜像；只装 Essentials，避开 300MB 的 WebEngine
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple PySide6-Essentials PySideSix-Frameless-Window
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --no-deps PySide6-Fluent-Widgets
```

### 命令行

```powershell
python scripts\skland\skland_cli.py login           # 交互式选 验证码 / 密码（会顺带取抽卡凭证）
python scripts\skland\skland_cli.py status          # 校验凭证 + 列角色
python scripts\skland\skland_cli.py dump            # 拉全量存 JSON（默认 %TEMP%\opencode\skland-dump）
python scripts\skland\skland_cli.py checkin         # 森空岛签到
python scripts\skland\skland_cli.py gacha           # 拉官方寻访记录（抽卡），并合并进本地留档
python scripts\skland\skland_cli.py gacha --category normal --out d:\gacha.json
```

## 文件

| 文件 | 职责 |
| --- | --- |
| `skland_client.py` | 核心：登录两法 / cred 换取 / 取数 / 本地凭证存取。**仅标准库**，可当库用 |
| `gacha_client.py` | **抽卡记录**：鹰角官网用户中心寻访记录（6 步登录链 / 分页 / 本地留档 / 统计 / `self_test`）。**仅标准库** |
| `skland_box.py` | **适配器**：把森空岛数据转成 MAA `OperBoxData.json` **同构** + 基建状态。给 MCP/既有脚本用 |
| `skland_gui.py` | 界面：**PySide6 + PySide6-Fluent-Widgets**（Mica 窗口 / 左侧导航 / 明暗跟随系统 / 打开即自动登录） |
| `ff_session.py` | **免密码取抽卡凭据**：从本机 Firefox 的 sessionstore（会话 cookie，含 HttpOnly）与 localStorage 里读登录态。仅标准库 |
| `skland_cli.py` | 命令行探针：login / status / dump / checkin / gacha |

## 接入 MCP / 复用既有脚本（**免模拟器**）

既有的活动关作业、培养推荐、一图流导入等消费方都读 `OperBoxData.json`。`skland_box.py` 把在线数据转成
**同构**形态，所以这些消费方**一行都不用改**就能换数据源：

```python
import sys; sys.path.insert(0, r"...\scripts\skland")
import skland_box as sb
sb.fetch_operbox()            # -> {done, own_opers:[{id,name,elite,level,potential,rarity,own,skill_lvl,spec,favor}], ...}
sb.fetch_base()               # -> 基建状态（rooms/drone/furniture/tiredChars）
sb.save_operbox(r"C:\MAA\data\OperBoxData.json")   # 覆盖 MAA 那份，既有脚本直接吃在线数据
```

MCP 侧已暴露两个工具（实现在仓库根 `arknights_mcp.py`，惰性加载本目录，不依赖 MAA/雷电）：

| MCP 工具 | 作用 |
|---|---|
| `ark_operbox_online(save_to="")` | 在线干员箱（同 `ark_operbox` 形态，**多带技能等级/专精**） |
| `ark_infrast_status()` | 基建状态（各设施槽位 + 进驻干员、无人机、家具） |

字段映射与"两条数据路径怎么选"见仓库根 **`AGENTS.md`** 与 **`docs/DATA-SOURCES.md` §7**。

## 纪律 & 踩坑

- **tkinter 非线程安全**：网络请求全在工作线程，结果经 `queue` 回主线程 `_drain()` 渲染。
- **窗口尺寸 + 位置一起按 DPI 夹在屏幕内**（`_fit_geometry`），只设尺寸会被摆到屏幕外。
- `status.charCnt / skinCnt / furnitureCnt` 可能是 `0`；**家具数在 `building.furniture.total`**，
  干员/时装数用 `chars` / `skins` 长度兜底。
- 干员中文名来自 `charInfoMap[charId].name`；`rarity` 是 **0 起算**（+1 才是星级）。
- 登录换 cred 的链路：`token_by_phone_password/code` → `oauth2/v2/grant` → `generate_cred_by_code`。
- **读数据必须带 `sign` 签名头**：`sign = md5(hmac_sha256(sign_token, path + query/body + timestamp + json(header)))`，
  `header = {platform,timestamp,dId,vName}`；`sign_token` 是换 cred 时一起返回的。
  **dId 本地生成一次持久化即可**——实测随机 `dId` 就能过，服务端不校验其真伪，无需数美那套。
  cred-only 会返回 `401 code=10000 请求异常`（不是 `10002 未登录`，别误判成凭证过期）。
- 凭证过期：重跑 `login`，或 `status` 里走 `auth/refresh` 续期。

### 抽卡记录（`gacha_client.py`）专有坑

- **两套接口别混**：抽卡记录在 `ak.hypergryph.com`（用户中心），不在 `zonai.skland.com`（森空岛）。
  共用 `as.hypergryph.com` 登录，分叉在 `grant` 的 `appCode`：
  用户中心 `be36d44aa36bfb5b` + `type=1`（返回 token） vs 森空岛 `4ca99fa6b56cc2ba` + `type=0`（返回一次性 code）。
  **用错 appCode 拿不到抽卡记录**。
- **`ak-user-center` cookie 必须有**：少走 `role/login` 那步，接口只回 `{"reason":"MissingCookie"}`。
- 鉴权失败响应**没有 `code` 字段**（只有 `reason`/`message`），不单独判会静默当成"成功、0 条记录"。
- 一条 = **一抽**；十连 = 10 条 `gachaTs` 相同、`pos` 0..9 的记录；`rarity` **0 基**；`gachaTs` 是**毫秒字符串**。
- 翻页游标是 `pos` + `gachaTs`，不是页码；去重键必须带 `pos`（十连里同名同星只差它）。
- 旧端点 `/user/api/inquiry/gacha?page=&token=` **已废弃**（现在返回 HTML）；新端点是 `.../gacha/{cate,history}`。
- **仅官服**；B 服 / 国际服没有这套接口。
- **接口能回溯多久官方没说明**（未确证）→ 拉到就本地留档（`~/.arknights_gacha_records.json`，只增不删）。
- 离线自测（不联网、不用账号）：`python scripts/skland/gacha_client.py` → 跑 `self_test()`。

## 合规

仅供**查自己的账号**。请遵守鹰角网络用户协议，不要把账号凭证交给第三方，不要用于自动化操作或传播。
