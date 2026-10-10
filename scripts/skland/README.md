# 森空岛看板（scripts/skland）

登录森空岛账号，把**本人**明日方舟账号的数据拉到本地看：概览 / 干员养成 / 基建 / 公招 /
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

**拿不到「抽卡记录」**：森空岛接口里没有这项；原版明日方舟官方也没有公开的抽卡查询接口。

## 用法

### 图形界面（推荐）

```powershell
& C:\Python314\pythonw.exe "C:\Users\<user>\Desktop\arknights-mcp\scripts\skland\skland_gui.py"
```

- 填手机号 → 选「验证码 / 密码」→（验证码的话点「发送验证码」）→ 登录；
- 登录后自动拉数据；之后「刷新数据」重新拉，「森空岛签到」签到；
- 没有账号想先看界面：点「载入样例数据」（用仓库自带的真实结构样例）。

依赖：`customtkinter`（界面）。核心 `skland_client.py` 只用标准库。

### 命令行

```powershell
python scripts\skland\skland_cli.py login           # 交互式选 验证码 / 密码
python scripts\skland\skland_cli.py status          # 校验凭证 + 列角色
python scripts\skland\skland_cli.py dump            # 拉全量存 JSON（默认 %TEMP%\opencode\skland-dump）
python scripts\skland\skland_cli.py checkin         # 森空岛签到
```

## 文件

| 文件 | 职责 |
| --- | --- |
| `skland_client.py` | 核心：登录两法 / cred 换取 / 取数 / 本地凭证存取。**仅标准库**，可当库用 |
| `skland_box.py` | **适配器**：把森空岛数据转成 MAA `OperBoxData.json` **同构** + 基建状态。给 MCP/既有脚本用 |
| `skland_gui.py` | CustomTkinter 界面（照着 cx-downloader 的逻辑写：配色 / 线程 / 主题 / 标题栏） |
| `skland_cli.py` | 命令行探针：login / status / dump / checkin |

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

## 合规

仅供**查自己的账号**。请遵守鹰角网络用户协议，不要把账号凭证交给第三方，不要用于自动化操作或传播。
