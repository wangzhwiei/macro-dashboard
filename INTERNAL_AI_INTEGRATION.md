# 内部AI数据接入与页面补全说明

适用项目：**创金固收投资部宏观数据研究**

本说明用于把整个项目交给内部AI后，让其在不破坏页面、评分口径和合成公式的前提下，正确调用内部数据接口，补齐全部宏观序列，生成 `public/data/dashboard.json`，完成质量校验并构建页面。

## 1. 内部AI必须先理解的架构

数据流只有一条：

```text
内部数据接口
  → scripts/adapters/http_adapter.py 或 custom_adapter.py
  → scripts/update_dashboard.py
  → public/data/dashboard.json
  → app/Dashboard.tsx
  → 页面
```

权威配置：

| 文件 | 作用 | 内部AI是否可修改 |
|---|---|---|
| `config/indicators.json` | 40个核心指标、大类、指标族、权重、方向、合成方法 | 映射确认后谨慎修改 |
| `config/auxiliary-indicators.csv` | 72个辅助研究序列 | 可以按列追加 |
| `config/provider-code-map.json` | 页面语义代码到内部接口真实代码的映射 | 接口接入时主要填写 |
| `scripts/update_dashboard.py` | 清洗、滚动、合成、标准化和评分 | 除非修改模型，否则不要改 |
| `scripts/adapters/http_adapter.py` | 通用GET/POST JSON接口 | 优先通过环境变量配置，不要直接改 |
| `scripts/adapters/custom_adapter.py` | iFinD、数据库SDK或内部Python客户端 | HTTP不适用时在这里实现 |
| `scripts/validate_dashboard.py` | 发布前数据质量闸门 | 不要绕过 |
| `METHODOLOGY.md` | 合成指标与信号公式 | 修改公式时同步更新 |

页面不直接调用供应商接口。每天先由Python生成统一数据文件，页面只读取生成结果。这样可以避免在浏览器中暴露密钥，也能保证同一批数据经过完整校验后再展示。

完成接口配置后，推荐使用一个入口脚本执行全流程：

```bash
python scripts/run_pipeline.py --adapter http --days 600
```

它会依次导出序列目录、调用接口、生成页面数据、严格校验、测试适配器、测试页面并构建静态站点。任一步失败都会立即停止。

## 2. 接口接入前必须向数据负责人确认

内部AI不能猜测以下内容：

1. 接口基础地址、GET或POST方法。
2. 鉴权方式：Bearer Token、API Key、自定义请求头、Cookie、SDK或数据库连接。
3. 请求参数名称：序列代码、开始日期、结束日期、频率。
4. 响应记录所在路径，例如 `data`、`result.rows`。
5. 日期字段和值字段名称。
6. 所有语义代码对应的真实供应商代码。
7. 原始单位：百分数是 `2.35` 还是小数 `0.0235`；金额是元、万元还是亿元。
8. 数据频率、公布日、节假日处理、是否允许向前填充。
9. 接口是否分页，以及单次是否能返回至少600天历史。
10. 哪些序列已经停更或被新口径替代。

任何一项未知时，内部AI应输出“待确认清单”，不能用近似序列或虚构代码填充。

## 3. 第一步：导出完整序列目录

运行：

```bash
python scripts/export_series_catalog.py
```

输出 `outputs/series-catalog.csv`，包含核心与辅助指标所需的每个原始分项：

- 指标ID和中文名
- 大类、指标族、频率和单位
- 页面语义代码
- 供应商真实代码待填列
- 核心/辅助属性
- 聚合、变化方法和债市方向

内部AI应以该目录为接口代码核对清单，不要只处理页面上默认展开的40个核心指标。

## 4. 第二步：建立代码映射

复制示例文件：

Windows PowerShell：

```powershell
Copy-Item config\provider-code-map.example.json config\provider-code-map.json
```

Linux/macOS：

```bash
cp config/provider-code-map.example.json config/provider-code-map.json
```

映射支持两种写法：

```json
{
  "CJHX:FR007_IRS_1Y": "内部真实代码",
  "CJHX:METRO_SHANGHAI": {
    "provider_code": "内部真实代码"
  }
}
```

左侧语义代码必须保持不变。右侧填写真实代码。映射表没有出现的序列会继续把语义代码原样传给接口。

映射原则：

- 不得因为名称相似就映射；必须核对指标定义、单位、频率和口径。
- 同一个原始序列可被核心合成指标与辅助拆分指标共同使用。
- 月累计、年累计数据不能替代当日或当周流量数据。
- 同比已经是百分比数值的序列，配置通常使用 `pp_change`，不要再次计算同比。
- 库存、价格和需求指标的 `bond_direction` 含义不同，不能按“上涨都是利多”处理。

## 5. 方式A：通用HTTP接口

复制环境变量：

```powershell
Copy-Item .env.example .env
```

最低配置：

```dotenv
MACRO_DATA_ADAPTER=http
MACRO_API_URL=https://internal-api.example.com/timeseries
MACRO_API_METHOD=GET
MACRO_API_KEY=真实密钥
MACRO_API_CODE_MAP=config/provider-code-map.json
```

完整可配置项：

```dotenv
# GET或POST
MACRO_API_METHOD=GET

# 鉴权
MACRO_API_AUTH_HEADER=Authorization
MACRO_API_AUTH_PREFIX=Bearer
MACRO_API_KEY=

# 额外固定请求头，必须是单行JSON
MACRO_API_HEADERS_JSON={"X-Department":"fixed-income"}

# 请求参数名
MACRO_API_CODE_PARAM=code
MACRO_API_START_PARAM=start_date
MACRO_API_END_PARAM=end_date
MACRO_API_FREQUENCY_PARAM=frequency

# 响应位置和字段
MACRO_API_DATA_PATH=result.rows
MACRO_API_DATE_FIELD=trade_date
MACRO_API_VALUE_FIELD=close
```

GET请求示例：

```text
GET {URL}?code={真实代码}&start_date=2025-01-01&end_date=2026-07-30&frequency=daily
```

POST请求体示例：

```json
{
  "code": "真实代码",
  "start_date": "2025-01-01",
  "end_date": "2026-07-30",
  "frequency": "daily"
}
```

接口响应可以是：

```json
[
  {"date": "2026-07-29", "value": 101.2}
]
```

```json
{
  "data": [
    {"date": "2026-07-29", "value": 101.2}
  ]
}
```

```json
{
  "dates": ["2026-07-28", "2026-07-29"],
  "values": [100.8, 101.2]
}
```

或通过 `MACRO_API_DATA_PATH=result.rows` 读取：

```json
{
  "code": 0,
  "result": {
    "rows": [
      {"trade_date": "2026-07-29", "close": 101.2}
    ]
  }
}
```

HTTP接口必须一次返回所请求区间的完整记录。当前通用适配器不自动翻页；如果接口强制分页，应使用自定义适配器完成全部分页后再返回。

## 6. 方式B：iFinD、数据库或内部Python SDK

编辑 `scripts/adapters/custom_adapter.py`，只需要实现：

```python
def fetch_series(indicator, series, start_date, end_date):
    return [
        {"date": "2026-07-28", "value": 100.0},
        {"date": "2026-07-29", "value": 101.2},
    ]
```

建议实现结构：

```python
from scripts.adapters.common import resolve_series_code


def fetch_series(indicator, series, start_date, end_date):
    provider_code = resolve_series_code(series)

    raw = internal_client.query_timeseries(
        code=provider_code,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        frequency=indicator["frequency"],
    )

    return [
        {
            "date": str(row["日期"])[:10],
            "value": float(row["数值"]),
        }
        for row in raw
        if row.get("日期") is not None and row.get("数值") is not None
    ]
```

要求：

- 函数必须返回列表，不要返回DataFrame、数据库游标或SDK对象。
- 每条记录只能包含可解析日期和有限数值。
- 可以乱序，主脚本会排序；同日重复值会保留最后一条。
- 不要在适配器中计算信号、周变化或合成指标。
- SDK密钥必须使用环境变量或供应商凭据存储，不得写入项目。
- 如果需要分页、重试、限流或会话登录，应全部封装在适配器内部。

运行：

```bash
python scripts/update_dashboard.py --adapter custom --days 600
```

## 7. 数据单位和口径检查

接口首次接入时，每个指标至少人工抽查最近5个数据点。

重点检查：

| 类型 | 正确口径 |
|---|---|
| 利率、开工率、同比 | 页面单位为 `%` 时通常传入 `2.35`，不是 `0.0235` |
| `pp_change` | 原始值已经是百分数或比例水平，周变化用百分点差 |
| `pct_change` | 原始值是价格、数量、指数或金额，周变化用百分比 |
| `level_change` | 原始值按水平差变化 |
| 日度流量 | 如票房，先按配置做7日合计或均值 |
| 周度指标 | 日期应代表该周有效观测日，不能把月度数据伪装成周频 |
| 合成指标 | 各分项分别标准化后再按权重合成 |

四个已配置合成指标的公式见 `METHODOLOGY.md`，包括地铁客流、轮胎开工、钢材库存和铜库存。内部AI不得在适配器中重复做这些计算。

## 8. 生成完整页面数据

首次接入和每日更新统一执行：

```bash
python scripts/update_dashboard.py --adapter http --days 600
```

或：

```bash
python scripts/update_dashboard.py --adapter custom --days 600
```

也可以直接执行完整流水线：

```bash
python scripts/run_pipeline.py --adapter http --days 600
```

脚本会：

1. 逐一请求所有配置分项。
2. 清洗非法日期和数值。
3. 同日去重并升序排列。
4. 执行滚动均值、滚动合计或标准化合成。
5. 计算每个指标周变化和历史标准化信号。
6. 在指标族内去重加权。
7. 计算九大类和综合宏观观点。
8. 生成页面读取的 `public/data/dashboard.json`。

## 9. 发布前必须通过质量闸门

运行：

```bash
python scripts/validate_dashboard.py --strict
```

也可以生成机器可读报告：

```bash
python scripts/validate_dashboard.py --strict \
  --report outputs/data-quality-report.json
```

严格校验包括：

- 所有配置字段、方向、频率、权重和聚合方法是否合法。
- 所有核心指标是否生成。
- 总指标覆盖率是否达到95%以上。
- 日频指标是否至少有120个历史点，周频至少26个。
- 2023年至今的周度矩阵日期、指标历史、大类历史和综合历史是否完全对齐。
- 历史日期是否升序且无重复。
- `latest`、`updatedAt` 是否与历史末值一致。
- 是否包含非有限数值。
- 日频或周频数据是否明显过期。
- 每个指标是否带有页面可展示的计算方法。

出现任何错误时禁止构建和发布。警告在 `--strict` 模式下同样禁止发布。

## 10. 构建页面

安装依赖并验证：

```bash
npm install
npm run data:validate
npm test
npm run build:github
```

通过标准：

- `data:validate` 退出码为0；
- `npm test` 全部通过；
- `docs/` 中生成静态页面、Logo、脚本资源和 `data/dashboard.json`；
- 页面显示全部指标、九大类和2023年至今周度历史完整；
- 任一指标历史弹窗可正常打开并显示数据与计算方法。

## 11. 每日自动更新

`.github/workflows/update-and-deploy.yml` 默认在工作日北京时间08:30运行：

```text
调用数据接口
→ 生成dashboard.json
→ 严格数据校验
→ 构建静态页面
→ 发布
```

在GitHub Actions中配置：

Repository variables：

- `MACRO_DATA_ADAPTER=http`
- `MACRO_API_URL`
- `MACRO_API_METHOD`
- `MACRO_API_AUTH_HEADER`
- `MACRO_API_AUTH_PREFIX`
- `MACRO_API_DATE_FIELD`
- `MACRO_API_VALUE_FIELD`
- `MACRO_API_CODE_MAP=config/provider-code-map.json`

Repository secret：

- `MACRO_API_KEY`

如果真实代码映射含敏感信息，不应提交 `provider-code-map.json`；可由工作流从安全存储生成，或由内部接口直接接受语义代码。

## 12. 内部AI的验收清单

内部AI必须逐项报告：

```text
[ ] 已确认接口请求方法和鉴权
[ ] 已确认日期、数值字段和响应路径
[ ] 已导出完整序列目录
[ ] 已完成所有核心指标代码映射
[ ] 已完成辅助指标映射或列出待补清单
[ ] 已确认百分数、金额和数量单位
[ ] 已成功拉取2023-01-01至今的完整历史
[ ] 已生成public/data/dashboard.json
[ ] 严格校验无错误、无警告
[ ] 112个指标全部生成
[ ] 9个大类全部生成
[ ] 2023年至今周度历史完全对齐
[ ] npm test通过
[ ] 静态页面构建通过
```

不得用以下方式“完成”任务：

- 使用随机数、前值或手填值替代接口缺失数据。
- 把月频序列复制成日频或周频。
- 用名称相似但口径不同的指标替代。
- 删除校验失败的核心指标来提高覆盖率。
- 把接口密钥写入代码、JSON、CSV或提交记录。
- 绕过 `--strict` 校验直接发布。

## 13. 可直接复制给内部AI的提示词

```text
你正在维护“创金固收投资部宏观数据研究”项目。

目标：
调用我提供的内部数据接口，补齐config/indicators.json和
config/auxiliary-indicators.csv所需的全部原始序列，生成经过严格校验的
public/data/dashboard.json，并构建现有页面。不得改变页面交互、信号颜色、
指标族去重逻辑、合成公式或债市方向，除非我明确批准。

执行顺序：
1. 阅读INTERNAL_AI_INTEGRATION.md、METHODOLOGY.md、.env.example。
2. 运行python scripts/export_series_catalog.py，输出完整待映射目录。
3. 向我确认接口URL、GET/POST、鉴权、请求参数、响应路径、日期字段、
   数值字段、单位和真实序列代码。未知信息必须列为待确认，禁止猜测。
4. 优先通过.env和config/provider-code-map.json接入http_adapter.py；
   只有接口分页、SDK或数据库调用无法通用配置时才实现custom_adapter.py。
5. 先用一个日频和一个周频序列做小样本调用，检查日期、单位、排序和缺失。
6. 拉取全部序列自2023-01-01至今的完整历史。
7. 运行python scripts/update_dashboard.py --adapter <http或custom> --days 1310（脚本仍会按配置保留2023年至今）。
8. 运行python scripts/validate_dashboard.py --strict
   --report outputs/data-quality-report.json。
9. 如果有错误或警告，修复接口映射或数据口径；不得删除核心指标或伪造数据。
10. 运行npm test和npm run build:github。
11. 输出验收清单、缺失序列清单、单位转换说明、校验摘要和构建结果。

完成标准：
核心指标零缺失；总覆盖率100%；9个大类；2023年至今周度历史对齐；
严格校验零错误零警告；所有测试和构建通过。

安全要求：
密钥只能放环境变量或安全凭据存储；不得输出、记录或提交密钥。
```

## 14. 常见错误排查

### 接口响应中未找到记录

设置：

```dotenv
MACRO_API_DATA_PATH=result.rows
```

### 日期或数值字段不叫date/value

设置：

```dotenv
MACRO_API_DATE_FIELD=trade_date
MACRO_API_VALUE_FIELD=close
```

### 接口使用POST

设置：

```dotenv
MACRO_API_METHOD=POST
```

### 接口参数名不同

设置：

```dotenv
MACRO_API_CODE_PARAM=indicatorCode
MACRO_API_START_PARAM=start
MACRO_API_END_PARAM=end
MACRO_API_FREQUENCY_PARAM=freq
```

### 百分比放大100倍或缩小100倍

不要在页面代码修正。应在适配器返回数据前统一单位，并记录转换原因。

### 只有少量指标成功

检查 `provider-code-map.json`、接口权限、请求限流和错误日志。主脚本会继续处理其他指标，因此必须依赖严格校验阻止不完整数据发布。

### 历史点不足

确认接口没有默认只返回最近30/90天，使用 `--days 600`，并处理接口分页。

### 周末或节假日重复

返回真实有效观测日期即可。主脚本会在周末评估日读取此前最近有效值，不需要人为补周末记录。
