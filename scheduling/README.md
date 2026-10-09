# scheduling —— 智能基建排班子功能

> `arknights-mcp` 的子功能：基于 MAA 识别（干员箱 / 仓库）+ 一图流生成器，
> 为玩家产出**最优基建排班**、**精二提升收益建议**、**理智分配建议**。

## 基地现状（已核准）

**243**：贸易站 **2** / 制造站 **4** / 发电站 **3**
（另有 控制中枢 / 会客室 / 办公室 / 加工站 / 训练室 各 1、宿舍 4）。

依据：MAA `debug/gui.log` 三次独立运行（2026-10-02、10-05、10-08）的"当前设施"记录完全一致，
2026-10-09 02:11 运行亦吻合。

> ⚠️ 早期曾误记为 333（3贸易/3制造/3发电）——**以 MAA 日志为准 = 243**。

## 目标产物

1. **两份排班**：按现状 243 生成，含 `搓玉` 与 `龙门币优先` 两种取向
   （一图流 scheduleV3 的"执行深度排班"导出 JSON）。
2. **精二建议 + 量化收益**：哪些干员精二能提升基建收益、提升多少（一图流"干员培养建议"）。
3. **本地网页**：用成熟 GitHub 框架呈现"两份排班 + 精二建议 + 量化收益"。
4. **理智分配建议**：结合现有刷图方法、理智恢复速度、仓库材料，给出理智怎么花。

## 输入（依赖 MAA 识别）

| 输入 | 来源 | 文件 |
|---|---|---|
| 干员箱（含精英/等级/潜能） | MAA 干员识别 | `C:\MAA\data\OperBoxData.json` |
| 仓库材料 | MAA 仓库识别 | `C:\MAA\data\DepotData.json` |
| 基建技能/效率数据 | MAA 资源库 | `C:\MAA\resource\infrast.json` |
| 排班模板 | MAA 自带 | `C:\MAA\resource\custom_infrast\*.json` |

## 流程

1. MAA 识别 → 拿到 `OperBoxData.json` + `DepotData.json`。
2. 打开一图流 `https://ark.yituliu.cn/tools/scheduleV3`，`导入 MAA JSON`，
   选与现状一致的 **243** 预设（`搓玉` / `龙门币优先`），`执行深度排班`，导出两份 JSON。
3. 抓"干员培养建议"的量化结果。
4. 组装本地网页。
5. 据仓库材料 + 理智恢复速度给理智分配建议。

## 现状（已跑通，2026-10-09）

- ✅ **基地布局核准为 243**（MAA 日志三次一致）。
- ✅ **干员箱识别 337 / 仓库 60 项**（根因见 `docs/FINDINGS.md` §5）。
- ✅ **两方案已生成并导出**（一图流 scheduleV3，深度排班）：

  | 方案 | 总产出(龙门币)/日 | 经验/日 | 合成玉/日 | 备注 |
  |---|---|---|---|---|
  | 钱书均衡·龙门币优先 | **55,855** | 30,303 | 0 | 赤金净结余为负（卖赤金换钱） |
  | 搓玉·合成玉 | 34,642 | 15,703 | **486** | 每日另耗 固源岩 ≈92.4 |

- ✅ **精二培养建议 26 条**（含经验/龙门币/理智成本）。
- ✅ **本地报告**：`报告/index.html`（自包含单文件，可离线/手机看）。

### 关键坑（务必照做）
- 一图流「导入 MAA JSON」要求**顶层是裸干员数组**，不能直接喂 `OperBoxData.json`（其顶层是对象）。
  需先抽 `own_opers`（仅 `own:true`）成数组 —— 见 `docs/FINDINGS.md` §9。
- 详见 `docs/FINDINGS.md` §8–§11。

### 如何再生成
```powershell
# 1) 抽裸数组（MAA 识别产物 → 一图流可导入）
python -c "import json;d=json.load(open(r'C:\MAA\data\OperBoxData.json',encoding='utf-8'));json.dump([o for o in d['own_opers'] if o.get('own')],open('OperBox_array.json','w',encoding='utf-8'),ensure_ascii=False)"
# 2) 一图流页面：导入上面的数组 → 选 243 预设 → 执行深度排班 → 导出 MAA/图片
# 3) 解析 + 渲染报告
python scheduling/tools/build_report.py     # 一图流产物 → report_data.json
python scheduling/tools/render_report.py    # → 报告/index.html
# 4) 手机看：lan 服务器
python -m http.server 8123 --bind 0.0.0.0 --directory scheduling\报告
```

- 📌 `tools/base_gap.py` / `tools/gen_plan*.py`：早期"差距分析/自动生成"尝试，**结论是不如用一图流**（见 FINDINGS §8）。

## 目录

```
scheduling/
├─ README.md            # 本文件
├─ 一图流产物/           # 导出：两方案 MAA JSON、结果页文本、预览图
├─ 报告/                 # index.html 自包含单文件报告（手机可看）
├─ tools/               # build_report.py / render_report.py（解析+渲染）
├─ MAA基建排班/          # 早期手搓生成器产物（仅参考）
└─ tools/(早期)          # base_gap.py / gen_plan*.py（不如一图流，弃用参考）
```
