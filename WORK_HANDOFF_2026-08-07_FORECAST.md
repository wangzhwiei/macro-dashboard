# 预测模块工作交接记录（2026-08-07）

## 1. 交接结论

本轮在 `macro-dashboard-main` 中完成了 CPI/PPI/PMI 月频预测模块的第一轮页面重构和数据生成修正，但用户明确反馈“仍存在大量问题”，本模块不能视为最终交付版本。

后续接手者应优先继续 UI 和模型结果核验，不要直接发布当前 `docs/` 到线上。

用户最新明确意见：

1. “月频预测 · 每日滚动 nowcast”不能和宏观研究页面内容混在同一页面流中；应与今日观点、观点走势、趋势矩阵、数据研究并列，通过点击“月频预测”进入完整独立页面。
2. 历史预测结果有误，需要继续检查模型口径和历史回测结果。
3. 模型输入高频指标的切换和展示混乱；每个指标应单独成横排，沿用原高频指标研究页面的展示方式，点击后显示完整历史走势，而不是简陋卡片。
4. 预测图中的模型建议报数、真实公布值、月末模型值标记混乱，颜色和点的含义必须明确标注。

## 2. 当前已修改内容

### 页面结构

- `app/Dashboard.tsx`
  - 增加 `activeView: "macro" | "forecast"` 页面状态。
  - 顶部导航增加“月频预测”入口。
  - 宏观研究页面和预测页面通过条件渲染分开。
  - 当前默认仍进入宏观研究页面。

- `app/ForecastPanel.tsx`
  - 独立预测工作区组件。
  - CPI/PPI/PMI 切换。
  - 每日预测时间序列图。
  - 月末模型值、iFinD 一致预期/模型建议报数、真实公布值标记。
  - 月末对照表。
  - 高频模型输入按 CPI/PPI/PMI 分组。
  - 输入指标单行展示最新值、月初变动、来源、日期。
  - 点击指标打开历史走势弹窗。

- `app/globals.css`
  - 增加独立预测工作区、稳定坐标轴、月末标记、横向输入列表和历史弹窗样式。
  - 文件末尾存在多轮预测样式追加，后续最好统一整理，避免旧 `.forecast-*` 规则覆盖新规则。

### 数据和模型

- `scripts/generate_forecasts.py`
  - 生成 `public/data/forecasts.json`。
  - 历史预测改为当月以前的扩展窗口，不使用未来月份真实值。
  - 上月真实值作为主要锚点，高频回归作为边际修正。
  - 2026 年 7 月每日预测逐步收敛到旧模型确认值：
    - CPI：`1.048`
    - PPI：`3.981`
    - PMI：`48.98`
  - 输入指标按 ID 去重，并补充单位和来源。

- `scripts/fetch_forecast_consensus.py`
  - 新增 iFinD EDB 一致预期抓取器。
  - 默认查询：`CPI一致预期`、`PPI一致预期`、`制造业PMI一致预期`。
  - 成功时写入 `data/forecast-model/consensus.json`。
  - 失败时保留缓存，不阻塞预测生成。

- `scripts/run_pipeline.py`
  - 已加入“一致预期抓取”和“生成月频每日预测”步骤。

- `data/forecast-model/monthly_actuals.json`
  - 项目内归档的月频 CPI/PPI/PMI 真实值。

- `public/data/forecasts.json`
  - 前端使用的预测结果和高频输入数据。
  - 构建后同步到 `docs/data/forecasts.json`。

## 3. 当前已知问题（必须继续处理）

### A. 页面切换仍需实际浏览器验收

代码已经增加页面状态和导航，但当前环境浏览器自动化受到 Windows 沙箱凭据错误影响，未完成截图级检查。必须在可用浏览器中验证：

- 默认打开时只显示宏观研究页面。
- 点击“月频预测”后，宏观页面内容不应继续显示在预测页上。
- 点击“今日观点/观点走势/趋势矩阵/数据研究”后，能返回宏观页面并滚动到正确位置。
- 移动端导航不应横向溢出或遮挡更新时间。

### B. 历史预测结果仍需与旧模型逐月对账

当前扩展窗口预测已经明显降低误差，但它是对旧 SARIMAX 模型的可运行近似，不等于旧账号原始模型的完整复刻。后续必须：

- 找回旧 WSL 项目中的 `macro_nowcast_engine.py`、`run_pmi_subindex.py` 等原始模块。
- 用旧模型逐月回测结果对比 `forecasts.json`。
- 明确每个指标的训练窗口、外生变量滞后、月内均值/月底值处理。
- 对 CPI 食品/非食品、PPI 工业品代理、PMI 五个分项分别核对，而不是只看总指标。
- 不要用未来真实值修正历史预测。

当前已知月份 MAE（仅作诊断，不代表最终模型质量）：

- CPI：约 `0.369`
- PPI：约 `0.732`
- PMI：约 `0.436`

### C. 高频输入展示需要继续贴合原高频指标研究页

当前已改为单行列表和弹窗，但仍需与原 `HistoryModal` 视觉和交互完全统一：

- 使用原有历史区间按钮、悬停读数、CSV 下载和方法说明布局。
- 高频指标每行必须显示真实单位、来源、最新日期、较月初变动。
- 对月频或无高频数据的输入（例如 PMI 滞后项）要明确显示“月频输入”，不能伪装成日频。
- PPI 中共用同一序列的代理项必须在模型说明中区分用途，不能只靠名称展示。

### D. 图表标记和一致预期来源

当前图例会根据 `consensusSource` 在 iFinD 一致预期和模型建议报数之间切换，但必须在浏览器实际检查：

- 月末竖线、方块、菱形、圆点不重叠到无法识别。
- 真实公布值为空时不绘制黑色圆点。
- 一致预期缺失时显示“待接口数据”，不能默认为市场一致预期。
- 图下月度对照表和图例含义一致。
- 坐标轴必须覆盖每日预测和全部月末标记值。

### E. iFinD 一致预期当前仍未在本机成功抓取

本机运行 `fetch_forecast_consensus.py` 时提示缺少：

```text
IFIND_SKILL_DIR/call.py
IFIND_SKILL_DIR/mcp_config.json
```

因此当前本地 `consensus.json` 为空，页面回退到模型官方取整建议报数。部署到内部 runner 前必须：

1. 确认 `IFIND_SKILL_DIR` 指向可用的 iFinD skill。
2. 确认三个 EDB 查询名返回的是预期的 CPI/PPI/PMI 共识序列，而不是实际公布值或模糊匹配的其他指标。
3. 对返回的 provider ID 做固定映射和漂移校验。
4. 保存并检查 `consensus.json` 的日期和值范围。
5. 只有确认独立一致预期返回成功后，才能把图例正式称为“iFinD 一致预期”。

## 4. 验证状态

已通过：

- `npm run build:github`
- 20 项 Python 单元测试
- `public/data/forecasts.json` HTTP 访问检查
- CPI/PPI/PMI 输入 ID 去重检查
- 历史预测 MAE 诊断

未完成：

- 桌面端和移动端真实浏览器截图验收。
- 线上 GitHub Pages 发布。
- iFinD 一致预期真实数据抓取验收。
- 旧账号原始 SARIMAX/PMI 分项模型逐月复刻验收。

## 5. 关键运行命令

```powershell
Set-Location 'C:\Users\wangzhiwei202307\Documents\宏观网页面板\macro-dashboard-main'

$python = 'C:\Users\wangzhiwei202307\Documents\宏观网页面板\runtime\python\python.exe'
$nodeDir = 'C:\Users\wangzhiwei202307\Documents\宏观网页面板\runtime\node-v22.23.1-win-x64'

& $python scripts/fetch_forecast_consensus.py
& $python scripts/generate_forecasts.py

$env:Path = "$nodeDir;$env:Path"
& "$nodeDir\npm.cmd" run build:github
```

本地预览：`http://127.0.0.1:4173/`

## 6. 交接原则

- 用户已经明确认为当前预测模块仍有大量问题，后续不能只做小幅 CSS 调整后宣称完成。
- 任何历史预测修正都必须先对照旧账号模型逻辑和回测结果。
- 任何“iFinD 一致预期”标签都必须有独立接口返回数据支撑。
- 在浏览器截图验收、模型逐月对账和 iFinD 接口验证完成前，不要推送或发布当前预测页面。
