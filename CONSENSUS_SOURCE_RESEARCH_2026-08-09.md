# CPI/PPI/PMI 一致预期稳定数据源研究（2026-08-09）

## 结论

推荐优先级：

1. **Trading Economics Calendar API**：当前最容易独立接入、同时覆盖中国 CPI 同比、PPI 同比和官方 NBS 制造业 PMI 的稳定接口。
2. **Wind Client API**：如果现有机构账号包含宏观一致预期权限，优先于新增外部采购；需先取得三个固定 Wind 指标代码并安装 WindPy。
3. **Bloomberg SAPI/B-Pipe**：稳定但授权和部署成本高；当前机器没有 Bloomberg API 环境。
4. **Reuters Poll**：适合作为人工复核来源，不适合作为每日自动化主数据源。

## Trading Economics 可用性

官方经济日历返回：

- `Forecast`：代表性经济学家调查的一致预期；
- `TEForecast`：Trading Economics 自有预测，禁止混用；
- `CalendarID`、`Ticker`、`Symbol`、`ReferenceDate`、`LastUpdate`：用于固定事件身份和审计；
- `values=true` 时返回数值字段，减少字符串解析歧义；
- Point-in-Time 数据可保存发布前当时的一致预期，满足无未来信息回测。

公开页面已经确认覆盖：

- China Inflation Rate YoY（CPI 同比）；
- China PPI YoY；
- China NBS Manufacturing PMI（官方 PMI，不是 RatingDog/S&P 私营 PMI）。

## 建议接入规则

1. 仅读取 `ForecastValue`，绝不读取 `TEForecastValue`。
2. 固定国家、事件名、Ticker、Symbol、单位和频率；首次授权查询后将代码写入配置。
3. 每条记录保存 `CalendarID`、参考月份、发布日期、抓取时间和 `LastUpdate`。
4. 发布前一天固定一次 PIT 快照；发布后不得用修订后的预期覆盖历史快照。
5. 缺失、重复、单位漂移或事件名漂移时失败并保留旧缓存，不回退为模型建议报数。
6. 页面来源标记为“Trading Economics 调查一致预期”，与“模型建议报数”分开。
7. GitHub Pages 属于公开展示，采购前需确认数据再分发授权；标准单用户 API 方案未明确包含公开再分发，企业方案明确包含 Data Distribution/White Label。

## 授权与本机环境

- Trading Economics API 需要 API key；当前 guest 接口返回 HTTP 410。
- 当前机器未发现 WindPy 或 Bloomberg blpapi。
- Wind/Bloomberg 若已有机构授权，需要用户提供可用终端/API环境和三个固定指标代码。
- 在正式授权前，页面继续显示模型建议报数和“待接口数据”，不抓取免费 HTML、不伪造一致预期。

## 参考

- https://docs.tradingeconomics.com/economic_calendar/schema/
- https://docs.tradingeconomics.com/economic_calendar/ticker/
- https://tradingeconomics.com/api/calendar.aspx
- https://tradingeconomics.com/china/inflation-cpi
- https://tradingeconomics.com/china/producer-prices-change
- https://tradingeconomics.com/china/business-confidence
- https://tradingeconomics.com/api/pricing.aspx
- https://www.wind.com.cn/portal/zh/ClientApi/index.html
- https://professional.bloomberg.com/support/api-library/



## 无付费 API 的公开页面实测

2026-08-09 直接请求三个公开页面，均返回 HTTP 200，且经济日历表格在服务端 HTML 中，不依赖浏览器执行 JavaScript。每行包含：

- `data-id` 事件 ID；
- 国家、分类、发布日期、参考月份和事件名；
- Actual、Previous、Consensus、TEForecast 四列。

实测 2026 年 7 月：

| 指标 | Actual | Previous | Consensus | TEForecast |
|---|---:|---:|---:|---:|
| CPI 同比 | 0.5% | 1.0% | 0.8% | 0.9% |
| PPI 同比 | 3.5% | 4.1% | 3.8% | 4.3% |
| 官方 NBS 制造业 PMI | 49.2 | 50.3 | 50.0 | 50.2 |

技术上可用标准 HTML 解析器严格提取，并能明确排除 TEForecast。Reuters 对 2026 年 7 月官方 PMI 的 31 位经济学家调查中位数同为 50.0，可作为交叉验证。

## 免费公开抓取的授权结论

Trading Economics 服务条款只提供有限、个人、不可转让、可撤销的分析许可；未提供将数据自动重新发布到公开 GitHub Pages 的再分发授权。robots.txt 没有列出禁止路径，但 robots.txt 不能替代使用条款。

因此：

- 可以用于一次性技术验证和本地研究；
- 未取得书面再分发许可前，不接入公开生产页面的每日自动任务；
- 免费、稳定、自动、三项同口径且允许公开再分发的来源，目前没有找到；
- Reuters 文章可人工复核，但没有稳定公开 API，也不适合作为每日自动主源。
