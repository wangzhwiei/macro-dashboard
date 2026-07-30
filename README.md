# 创金固收投资部宏观数据研究

这是一套配置驱动的宏观高频观测系统。它把原始序列分成“指标—指标族—大类”三层，先在指标族内合成，再计算九大类和总信号，避免多个期限、城市或同产业链指标重复投票。

项目包含：

- 响应式宏观面板；
- 40个核心指标与72个辅助研究指标；
- HTTP和自定义Python接口适配器；
- 方向、变化口径、历史标准化和数据新鲜度处理；
- GitHub Actions工作日自动更新与GitHub Pages发布；
- 每个指标的历史曲线、时间区间筛选、悬停读数与CSV下载；
- 本地示例数据生成器，未接接口时也能完整运行。

交给内部AI接入数据时，请从
[`INTERNAL_AI_INTEGRATION.md`](INTERNAL_AI_INTEGRATION.md)开始。该说明包含
接口参数、代码映射、单位检查、严格质量闸门、每日自动更新和可直接复制的AI提示词。

## 1. 本地运行

需要 Node.js 22+ 和 Python 3.10+。

```bash
npm install
python scripts/update_dashboard.py --adapter mock
npm run dev
```

打开终端显示的本地地址。示例数据是可重复生成的，仅用于验证页面和评分流程。

静态GitHub Pages版本：

```bash
npm run build:github
```

输出目录为 `docs/`。

## 2. 接入现有数据接口

### 方式A：通用HTTP接口

复制环境变量示例：

```bash
copy .env.example .env
```

设置：

```dotenv
MACRO_DATA_ADAPTER=http
MACRO_API_URL=https://your-api.example.com/timeseries
MACRO_API_KEY=your-secret
```

更新脚本会发送：

```text
GET {MACRO_API_URL}?code=...&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&frequency=daily
Authorization: Bearer {MACRO_API_KEY}
```

接口可返回以下任一结构：

```json
[
  {"date": "2026-07-29", "value": 101.2}
]
```

```json
{"data": [{"date": "2026-07-29", "value": 101.2}]}
```

```json
{"dates": ["2026-07-29"], "values": [101.2]}
```

日期和值字段名可通过 `MACRO_API_DATE_FIELD`、`MACRO_API_VALUE_FIELD` 修改。

### 方式B：直接复用已有 iFinD/CJHX Python 查询函数

编辑 `scripts/adapters/custom_adapter.py`，只实现：

```python
def fetch_series(indicator, series, start_date, end_date):
    return [
        {"date": "2026-07-28", "value": 100.0},
        {"date": "2026-07-29", "value": 101.2},
    ]
```

然后运行：

```bash
python scripts/update_dashboard.py --adapter custom
```

接口密钥不要写入代码或 `indicators.json`，应放在 `.env` 或 GitHub Secrets。

## 3. 配置指标

核心指标定义在 `config/indicators.json`，辅助指标定义在
`config/auxiliary-indicators.csv`。辅助指标可以展开研究，但不会重复影响
大类评分和扩散度。

关键字段：

| 字段 | 含义 |
|---|---|
| `category` | 所属九大类 |
| `family` | 指标族；同族指标先合成，避免重复投票 |
| `series[].code` | 传给数据接口的序列代码 |
| `core` | 是否进入主面板和大类评分 |
| `weight` | 指标在本指标族内部的权重 |
| `transform` | `pct_change`、`pp_change` 或 `level_change` |
| `bond_direction` | `-1`表示上涨对债市不利，`1`表示上涨对债市有利 |
| `aggregate` | 可选：多序列合成或滚动计算 |

支持的聚合：

- `standardized_mean`：多个原始序列标准化后加权平均；
- `rolling_7d_mean`：7日均值；
- `rolling_7d_sum`：7日合计；
- `rolling_4w_mean`：4周均值。

合成指标的具体公式、预处理步骤、权重和债市信号算法见
[`METHODOLOGY.md`](METHODOLOGY.md)。同样的信息也会随数据写入页面，点击指标名称即可查看。

页面默认展示核心指标，点击“全部指标”即可显示辅助序列。点击任一指标名称
可以打开历史走势，选择1个月、3个月、6个月、1年、全部或自定义日期，并可
下载当前区间CSV。

## 4. 每日自动更新

`.github/workflows/update-and-deploy.yml` 默认在工作日北京时间08:30运行：

1. 拉取最新指标；
2. 计算指标族、大类和综合信号；
3. 构建静态页面；
4. 发布到GitHub Pages。

首次使用时，在GitHub仓库中：

1. 打开 **Settings → Pages**，Source选择 **GitHub Actions**；
2. 在 **Settings → Secrets and variables → Actions** 添加：
   - Repository variable `MACRO_DATA_ADAPTER`：`http`或`custom`
   - Repository variable `MACRO_API_URL`：HTTP接口地址
   - Repository secret `MACRO_API_KEY`：接口密钥
3. 在Actions页面手动运行一次 `Update macro dashboard`。

如果使用 `custom` 适配器，需要确保其依赖已在工作流中安装。

## 5. 评分方法

每个指标使用最近一周变化，并根据自身历史波动标准化到 `-100～100`：

- 正分：对债市利多，页面使用红色；
- 负分：对债市利空，页面使用绿色；
- 绝对值小于15：中性。

计算顺序：

```text
原始序列 → 指标变换 → 指标信号 → 指标族内部加权 → 大类等权 → 综合信号
```

因此，FR007多个期限、地产城市能级、钢材各品种库存等不会再被当成多个完全独立的宏观证据。

“利多扩散度”定义为：

```text
利多指标族（或大类）数量 ÷（利多数量 + 利空数量）
```

中性项不进入分母。扩散度表示观点的覆盖面，不等同于信号强度。

## 6. 项目结构

```text
app/                         页面与样式
config/indicators.json       指标、方向、权重与接口代码
config/auxiliary-indicators.csv  辅助研究序列
scripts/update_dashboard.py  每日更新、标准化和评分
scripts/adapters/            HTTP及自定义数据接口
public/data/dashboard.json   前端读取的最终数据
.github/workflows/           定时更新和GitHub Pages发布
```

运行验证：

```bash
npm run pipeline:update -- --adapter http
npm run data:catalog
npm run data:validate
npm test
npm run build:github
```
