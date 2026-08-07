# 宏观网页面板工作交接与运维手册

> 最后更新：2026-08-07。首次接手优先阅读第 11 至 18 节；第 1 至 10 节保留 2026-08-06 的实施历史和故障背景。

## 1. 本次工作结果

宏观数据研究网页已完成生产构建，并发布到 GitHub Pages：

- 线上地址：https://wangzhwiei.github.io/macro-dashboard/
- GitHub 仓库：https://github.com/wangzhwiei/macro-dashboard
- 发布分支：`gh-pages`
- 发布提交：`5cbc0d8f8bacfb69a3b75a9bc9f2f67bfabb40b5`
- 提交说明：`data: publish 2026-08-06 dashboard`
- Pages 工作流运行：https://github.com/wangzhwiei/macro-dashboard/actions/runs/31094387991
- 线上数据生成时间：`2026-08-06T09:50:03.827612+00:00`
- 当前数据规模：9 个宏观大类、111 个指标

本次发布只更新了 `gh-pages` 分支根目录下的 `data/dashboard.json`。前端 JS、CSS 和 HTML 与上次线上版本内容一致，因此没有提交无意义的资源文件换行变化。

## 2. 本地目录说明

### 源码与数据处理目录

`C:\Users\wangzhiwei202307\Documents\宏观网页面板\macro-dashboard-main`

后续功能开发、数据更新、测试和构建都应在此目录进行。主要文件：

- `public/data/dashboard.json`：前端读取的生产数据
- `docs/`：`npm run build:github` 生成的静态站点
- `scripts/run_pipeline.py`：完整数据流水线入口
- `scripts/validate_dashboard.py`：数据质量校验
- `config/indicators.json`：核心指标配置
- `config/auxiliary-indicators.csv`：辅助指标配置
- `.github/workflows/`：CI 和 Pages 发布工作流

注意：该目录来自压缩包解压，本身没有可用的 `.git` 元数据，不能直接提交或推送。

### 临时发布副本

`C:\Users\wangzhiwei202307\Documents\宏观网页面板\release-gh-pages`

这是从远程仓库单独克隆的 `gh-pages` 分支，仅用于发布静态产物，不应在此目录开发业务代码。当前分支已与 `origin/gh-pages` 同步，工作区干净。

### 本地运行时

- Node.js：`C:\Users\wangzhiwei202307\Documents\宏观网页面板\runtime\node-v22.23.1-win-x64`
- Python：`C:\Users\wangzhiwei202307\Documents\宏观网页面板\runtime\python\python.exe`
- Git：`C:\Program Files\Git\cmd\git.exe`（本次已安装并完成 GitHub 授权）

## 3. 已完成验证

### Python 单元测试

显式把项目根目录加入嵌入式 Python 的模块路径后，20 个测试全部通过：

```powershell
$python = 'C:\Users\wangzhiwei202307\Documents\宏观网页面板\runtime\python\python.exe'
& $python -c "import sys,unittest; sys.path.insert(0, r'C:\Users\wangzhiwei202307\Documents\宏观网页面板\macro-dashboard-main'); suite=unittest.defaultTestLoader.discover('tests', pattern='test_*.py'); result=unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(not result.wasSuccessful())"
```

### GitHub Pages 生产构建

构建成功，输出到 `docs/`：

```powershell
$nodeDir = 'C:\Users\wangzhiwei202307\Documents\宏观网页面板\runtime\node-v22.23.1-win-x64'
$env:PATH = "$nodeDir;$env:PATH"
& "$nodeDir\node.exe" "$nodeDir\node_modules\npm\bin\npm-cli.js" run build:github
```

### 线上验收

发布完成后已直接检查以下资源，均返回 HTTP 200：

- `/`
- `/assets/index-BfUxUdVZ.js`
- `/assets/index-DzpImMt1.css`
- `/data/dashboard.json`

线上 `dashboard.json` 已确认：

- `generatedAt = 2026-08-06T09:50:03.827612+00:00`
- `indicators = 111`
- `categories = 9`

## 4. 已知问题和风险

### 数据新鲜度告警

严格质量校验没有结构、映射、覆盖率或重复数据错误，但以下 4 个供应商序列最新日期为 `2026-07-20`，截至本次生成日已滞后 17 天：

- `listing_price`
- `listing_tier1`
- `listing_tier2`
- `crude_steel`

默认非日频容忍阈值为 14 天，因此 `scripts/validate_dashboard.py --strict` 会失败。当前网页已发布，但后续自动流水线若继续使用严格模式，会被这 4 项告警阻止。

建议优先补齐供应商最新数据。若确认这些周频/旬频序列的正常发布时间确实超过 14 天，再为这几个指标单独配置 `stale_tolerance_days`，不要全局放宽阈值。

### 服务端渲染测试不适用于当前静态发布目标

`tests/rendered-html.test.mjs` 中有一个用例依赖 `dist/server/index.js`。当前 GitHub Pages 发布使用 Vite 静态构建，只生成 `docs/`，因此该服务端用例无法运行；其中“静态数据已生成且 starter 内容已移除”的用例通过。

### 浏览器自动化限制

本次环境中的浏览器自动化连接受到 Windows 沙箱凭据错误影响，未完成截图级桌面/移动端验收。已通过生产构建、HTTP 资源检查和线上数据解析完成发布验收。后续调整 UI 时仍建议补做真实浏览器的桌面和移动端检查。

## 5. 建议的后续推进顺序

1. 获取并导入 4 个滞后序列的最新数据，重新运行严格质量校验。
2. 在源码目录恢复或重新克隆完整 Git 仓库，避免继续使用无 Git 元数据的解压目录开发。
3. 将本地源码变化提交到开发分支或 `main`，不要只更新 `gh-pages`。
4. 确认内部自托管 runner 标签 `cjhx-internal` 可用，使 `.github/workflows/update-and-deploy.yml` 能按计划自动更新。
5. 做一次桌面端和移动端浏览器回归，重点检查指标弹窗、历史区间选择、悬停读数和 CSV 下载。

## 6. 后续手工发布流程

在源码目录完成数据更新和构建：

```powershell
Set-Location 'C:\Users\wangzhiwei202307\Documents\宏观网页面板\macro-dashboard-main'

$nodeDir = 'C:\Users\wangzhiwei202307\Documents\宏观网页面板\runtime\node-v22.23.1-win-x64'
$env:PATH = "$nodeDir;$env:PATH"
& "$nodeDir\node.exe" "$nodeDir\node_modules\npm\bin\npm-cli.js" run build:github
```

将静态产物复制到发布副本，并提交推送：

```powershell
$source = 'C:\Users\wangzhiwei202307\Documents\宏观网页面板\macro-dashboard-main\docs'
$release = 'C:\Users\wangzhiwei202307\Documents\宏观网页面板\release-gh-pages'
$git = 'C:\Program Files\Git\cmd\git.exe'

Copy-Item -Path "$source\*" -Destination $release -Recurse -Force
Set-Location $release
& $git status --short
& $git add -A
& $git commit -m 'data: publish YYYY-MM-DD dashboard'
& $git push origin gh-pages
```

推送后应等待 GitHub Pages 工作流完成，再访问带随机查询参数的数据地址，避免 CDN 缓存造成误判：

```text
https://wangzhwiei.github.io/macro-dashboard/data/dashboard.json?verify=TIMESTAMP
```

核对 `generatedAt` 后才能确认本次版本真正上线。

## 7. iFinD 接通与自动化更新（2026-08-06 追加）

本次已通过 WSL skill 实际完成 iFinD 增量更新：

- skill 路径：`/home/wangzhiwei202307/.openclaw/workspace/skills/ifind-finance-data/ifind-finance-data`
- MCP 调用返回 HTTP 200，认证有效
- 已取消 `IFIND_CACHE_ONLY`，实际查询并更新 `data_cache`
- 最新面板数据：`2026-08-06T12:19:12.361520+00:00`
- iFinD 指标最新日期：`2026-08-06`
- 严格质量校验：通过，无错误、无告警

自动工作流已提交到 `main`：`006ec16`。工作流会在 Windows runner 中调用 WSL iFinD，再使用 Windows Node 构建静态页面。当前仓库仍没有注册 self-hosted runner；注册 runner 会允许 GitHub 仓库代码在本机执行，需要项目负责人明确批准后再执行。未注册前，GitHub Actions 的每日调度不会真正抓取数据。

本次 iFinD 数据发布提交：`981c71b`。线上地址已验证为新数据版本。

## 8. 自动化端到端验证完成（2026-08-06 追加）

- self-hosted runner：`macro-dashboard-windows`
- runner 标签：`self-hosted`、`Windows`、`X64`、`cjhx-internal`
- iFinD 缓存：仅保存在本机 `github-runner/ifind-cache`，未提交供应商历史数据或 token 到 GitHub
- Pages 模式：已从 `legacy` 切换为 `workflow`，避免双重部署互相取消
- 完整验证运行：https://github.com/wangzhwiei/macro-dashboard/actions/runs/31107071046
- `update-and-build`：成功
- `deploy`：成功（run attempt 2）
- 线上生成时间：`2026-08-06T13:50:52.453380+00:00`

当前 runner 通过用户会话中的 `run.cmd` 进程运行，GitHub 显示 online。Windows 服务尚未安装；机器注销或重启后 runner 会离线，每日定时任务不会执行。安装持久 Windows 服务需要额外明确授权。

## 9. 日频数据源审计与南华金属修复（2026-08-06 追加）

本次严格按项目既有数据源配置审计，没有因指标代码前缀或数据日期较旧而跨源替换：

- 配置 `source=iFinD` 的日频指标中，只有 `nanhua_metals` 停在 `2026-07-31`。
- 根因是查询名 `南华期货:金属指数` 带日期后触发 iFinD 模糊匹配漂移，返回错误 provider ID `S005430044`。
- 将 iFinD 查询名改为 `南华金属指数` 后，稳定返回配置中的正确 provider ID `S004094486`。
- 线上结果：`nanhua_metals` 保持 `source=iFinD`，更新至 `2026-08-06`，最新值 `7065.47`。
- 修复提交：`ccff75b`。

仍早于 `2026-08-03` 的日频指标全部配置为 CJHX，不允许用 iFinD 补写：

- `2026-07-30`：`cement_east`、`cement_yangtze`、`iron_ore_62`
- `2026-07-31`：`brent`、`cement_national`、`dxy`、`eurusd`、`gold_spot`、`lme_zinc`、`silver_spot`、`usdjpy`、`wti`
- `2026-08-01`：`metro_composite`、`metro_guangzhou`、`metro_shanghai`、`newhome_30c`、`newhome_tier3`

这些日期与 CJHX 原始 `macro_extract_70_results.csv` 尾部一致。当前机器没有项目声明的 `cjhx-cais-bis-skill`，因此只能等待或接入 CJHX 上游更新，不能改走 iFinD。

自动更新与部署验证：

- 完整成功运行：https://github.com/wangzhwiei/macro-dashboard/actions/runs/31111357483
- Pages deployment：`5781602244`，状态 success
- 线上生成时间：`2026-08-06T14:43:49.566017+00:00`
- GitHub Pages JSON 缓存策略：`max-age=600`，部署成功后最多约 10 分钟才会看到新数据
- 最终线上验证：南华金属日期 `2026-08-06`，最新值 `7065.47`

## 10. 每日自动运行与持久 runner（2026-08-06 晚间追加）

已获得项目负责人授权，将本机注册为仓库的 `cjhx-internal` GitHub Actions runner。当前状态如下：

- runner 名称：`macro-dashboard-windows`
- 标签：`self-hosted`、`Windows`、`X64`、`cjhx-internal`
- runner 目录：`C:\Users\wangzhiwei202307\Documents\宏观网页面板\github-runner`
- iFinD 持久缓存：`github-runner\ifind-cache`，只保存在本机，不提交到 GitHub
- 自启动入口：当前 Windows 用户启动目录中的 `Macro Dashboard GitHub Runner.lnk`
- 启动目标：runner 官方 `run.cmd`，已实测出现 `Listening for Jobs`
- GitHub Actions 定时：每天北京时间 `08:30`（UTC cron：`30 0 * * *`）

Windows 服务安装需要管理员权限，且系统服务账户通常无法访问当前用户拥有的 WSL Ubuntu 和 iFinD skill。本机当前改用“用户登录时启动”方式，以保证 WSL 权限正确。因此每日自动更新的运行前提是：机器已开机、网络正常，并且 `wangzhiwei202307` 用户已登录 Windows。机器重启后只需登录，runner 会自动恢复；无需手工打开终端或执行脚本。

数据源边界保持不变：

- CJHX 指标只从 CJHX `macro_extract_70_results.csv` 读取；CJHX 上游未更新时保留其真实日期，不得改用 iFinD 补写。
- iFinD 只更新 `config/ifind-series.csv` 中配置的 41 个序列，通过 WSL `ifind-finance-data` skill 调用。
- `hybrid` adapter 按项目配置选择来源，不按数据新旧临时切换供应商。

本次端到端验证运行：

- Actions run：<https://github.com/wangzhwiei/macro-dashboard/actions/runs/31116483522>
- `Verify WSL iFinD skill`：成功
- `Fetch data with WSL iFinD skill`：成功，`15:36:04Z` 至 `15:45:16Z`，耗时 9 分 12 秒
- `Build static site`：成功，约 4 秒
- `update-and-build` 总耗时：11 分 26 秒
- 本次构建产物 `generatedAt=2026-08-06T15:45:15.295921+00:00`
- 日频 iFinD：15 项更新至 `2026-08-06`，5 项更新至 `2026-08-05`，没有早于 `2026-08-05` 的 iFinD 日频项
- 日频 CJHX：35 项为 `2026-08-05`；其余 17 项仍为上游真实的 `2026-07-30`、`2026-07-31` 或 `2026-08-01`
- 首次 `deploy` 在 GitHub 托管 runner 的 `Set up job` 阶段失败，部署代码未开始
- attempt 2 的 `deploy-pages` 因 GitHub OIDC 服务返回 HTTP 503（`upstream ... overflow`）失败；权限已确认包含 `Pages: write` 和 `id-token: write`
- attempt 3 在 GitHub 托管队列等待 15 分钟后被平台取消；attempt 4 仅重跑 `deploy` 并成功，没有重复抓取数据
- 最终 run 结论：`success`；线上 `generatedAt=2026-08-06T15:45:15.295921+00:00`

运行时间较长的原因不是人工发布：流程已经自动化，但当前有 41 个 iFinD 序列按顺序执行增量 API 请求，每个请求还保留最多 3 次重试。 首次当天运行仍需逐序列确认供应商是否有新观测；此前缓存只保存 records，无法记住“今天已查过但无新增”，所以兜底 run 会重复查询。现已增加 `last_checked_date` 元数据：同日后续 run 直接复用缓存，跨日才查增量。 对供应商明确返回“未返回可用数据”的增量请求只调用一次并记录当天；只有网络、认证等真正异常才最多重试 3 次。`--days 1310` 是面板历史保留窗口；本机缓存存在时只请求最后缓存日期之后的数据，并非每天全量下载 1310 天。正常情况下数据抓取约 5 至 10 分钟，随后页面构建只需数秒，Pages 上线时间还受 GitHub 托管队列和约 10 分钟 CDN 缓存影响。

## 11. 当前生产状态

| 项目 | 当前值 |
| --- | --- |
| 线上页面 | <https://wangzhwiei.github.io/macro-dashboard/> |
| 线上数据 | <https://wangzhwiei.github.io/macro-dashboard/data/dashboard.json> |
| GitHub 仓库 | <https://github.com/wangzhwiei/macro-dashboard> |
| 源码分支 | `main` |
| GitHub 默认分支 | `gh-pages` |
| 每日 workflow | `Update, validate and deploy macro dashboard`，ID `328604569` |
| 自动时间 | 每天北京时间 08:30，cron `30 0 * * *` |
| 本机 runner | `macro-dashboard-windows`，标签 `self-hosted, Windows, X64, cjhx-internal` |
| 最近完整验证 | run `31116483522`，attempt 4 最终成功 |
| 最近线上版本 | `generatedAt=2026-08-06T15:45:15.295921+00:00` |

每日自动运行的前提：Windows 机器开机、网络正常、`wangzhiwei202307` 已登录。runner 通过当前用户启动目录的快捷方式启动，从而能访问该用户的 WSL Ubuntu 和 iFinD skill。机器重启后必须先登录 Windows；不需要手工打开终端。

## 12. 端到端流程

生产流程只有一条主链：

1. GitHub 在每天北京时间 08:30 触发 `.github/workflows/update-and-deploy.yml`。由于仓库默认分支是 `gh-pages`，GitHub 实际读取默认分支上的 workflow 定义。
2. `update-and-build` 被标签为 `cjhx-internal` 的本机 Windows runner 接单，随后明确 checkout `main`，所以业务代码和配置来自 `main`。
3. workflow 安装 Node.js 22 和前端依赖，验证 WSL 中 iFinD skill 的 `call.py` 与 `mcp_config.json` 存在。
4. WSL 执行 `scripts/run_pipeline.py --adapter hybrid --days 1310 --data-only`。
5. `run_pipeline.py` 依次导出序列目录、生成页面数据、严格校验、运行 Python 单元测试。任一步失败都会阻止发布。
6. `hybrid_adapter.py` 按配置为每个语义代码选择 CJHX 或 iFinD。CJHX CSV 每次运行只下载一次；iFinD 使用本机持久缓存并按序列做增量请求。
7. `update_dashboard.py` 生成 `public/data/dashboard.json`；`validate_dashboard.py --strict` 生成 `outputs/data-quality-report.json` 并执行硬性质量门禁。
8. `npm run build:github` 由 Vite 将 `static/`、`app/` 和 `public/` 构建到 `docs/`。
9. workflow 将 `docs/` 打包为 `github-pages` artifact。GitHub 托管 Ubuntu runner 用 `actions/deploy-pages@v4` 发布。
10. 部署成功后，GitHub Pages CDN 最多可能继续缓存旧 JSON 约 10 分钟。验收必须读取带随机查询参数的 `dashboard.json` 并核对 `generatedAt`。

自动化消除了手工操作，但不会消除外部 API 和 GitHub 队列耗时。当前有 41 个实际使用的 iFinD 唯一序列顺序增量请求，供应商响应和重试会累计；最近实测 iFinD 抓取 9 分 12 秒，静态构建约 4 秒。

## 13. 本机目录

| 路径 | 用途 | 注意事项 |
| --- | --- | --- |
| `C:\Users\wangzhiwei202307\Documents\宏观网页面板\source-main` | 当前权威源码工作区，跟踪 `main` | 代码、配置、文档修改在这里完成 |
| `C:\Users\wangzhiwei202307\Documents\宏观网页面板\github-runner` | GitHub Actions runner 安装目录 | 不提交；包含 runner 凭据、日志、工作副本和 iFinD 缓存 |
| `github-runner\ifind-cache` | iFinD 持久历史缓存和 CJHX CSV 缓存 | 生产增量更新依赖此目录；不要清空或上传 |
| `github-runner\_work` | Actions 临时 checkout 和构建目录 | 不要在这里手工改源码，下一次 job 会覆盖 |
| `C:\Users\wangzhiwei202307\Documents\宏观网页面板\macro-dashboard-main` | 前期实施工作副本 | 仅供历史比对，不作为后续权威源码 |
| `C:\Users\wangzhiwei202307\Documents\宏观网页面板\release-gh-pages` | 旧的手工发布副本 | 当前 artifact 部署链不依赖它 |
| `C:\Users\wangzhiwei202307\Documents\宏观网页面板\runtime` | 本地 Python/Node 运行时 | 手工运行时可用，workflow 主要使用 runner 与 WSL 环境 |
| `/home/wangzhiwei202307/.openclaw/workspace/skills/ifind-finance-data/ifind-finance-data` | WSL iFinD 调用 skill | `mcp_config.json` 是本机敏感配置，不得进仓库 |

runner 登录自启文件：

```text
C:\Users\wangzhiwei202307\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\Macro Dashboard GitHub Runner.lnk
```

它直接指向 `github-runner\run.cmd`。runner 注册文件 `.runner`、`.credentials`、`.credentials_rsaparams` 都属于敏感本机状态，不能复制进项目或日志。

## 14. 关键文件职责

### 自动化与发布

| 文件 | 职责 |
| --- | --- |
| `.github/workflows/update-and-deploy.yml` | 每日数据更新、质量校验、静态构建、artifact 上传和 Pages 部署的主 workflow |
| `.github/workflows/pages.yml` | 仅存在于 `main` 的备用/防护模板；默认分支 `gh-pages` 未包含它，因此当前不会被 GitHub 注册或触发 |
| `.github/workflows/quality-guard-ci.yml` | pull request 和指定质量分支的 CI，不负责生产定时更新 |
| `.github/workflows.disabled/update-and-deploy.yml` | 历史禁用副本，仅供参考，不会运行 |
| `vite.github.config.ts` | GitHub Pages 构建配置；入口 `static/`、基础路径 `./`、产物目录 `docs/` |
| `package.json` | Node 依赖和 `dev`、`test`、`build:github`、`pipeline:update` 命令 |

### 数据配置

| 文件 | 职责 |
| --- | --- |
| `config/indicators.json` | 39 个主指标定义：分类、频率、单位、展示来源、组件、权重、变换、债市方向 |
| `config/auxiliary-indicators.csv` | 72 个辅助指标定义；与主指标一起进入最终 dashboard，总计 111 个唯一指标 |
| `config/cjhx-series-map.json` | CJHX 路由表，语义代码映射到 CJHX CSV 的 `series_key`，可配置 `scale` 和 `exclude_dates` |
| `config/ifind-series.csv` | iFinD 路由与身份表：`semantic_code`、`query_name`、`provider_id`、频率、原始单位、缩放 |
| `config/provider-code-map.json` | 供应商代码映射和碰撞校验基线 |
| `config/provider-code-map.example.json` | 映射格式示例，不是生产路由 |

### 数据处理

| 文件 | 职责 |
| --- | --- |
| `scripts/run_pipeline.py` | 一键编排入口；失败即返回非零退出码 |
| `scripts/update_dashboard.py` | 拉取所有组件、计算指标/评分/历史、生成 `public/data/dashboard.json` |
| `scripts/validate_dashboard.py` | 严格质量门禁，检查配置、映射、数值、日期、新鲜度和输出结构 |
| `scripts/export_series_catalog.py` | 导出 `outputs/series-catalog.csv`，用于审计 121 个组件行和供应商代码 |
| `scripts/adapters/hybrid_adapter.py` | 当前生产 adapter；CJHX 优先路由，iFinD 增量调用和缓存 |
| `scripts/adapters/common.py` | adapter 共用代码解析和 provider code 映射 |
| `scripts/adapters/http_adapter.py` | 通用 HTTP 接口备选方案，当前生产不用 |
| `scripts/adapters/custom_adapter.py` | 旧的直接 CJHX/iFinD 函数方案，当前生产 workflow 不用 |
| `scripts/fetch_cjhx_raw.py` | 在具备 `cjhx-cais-bis-skill` 时直接抓 CJHX 原始数据；当前机器缺该 skill |
| `scripts/generate_cjhx_report.py` | CJHX 原始数据质量报告工具 |
| `scripts/incremental_update.py` | 早期增量更新工具，不是当前每日入口 |
| `scripts/sync_auxiliary_sources.py` | 辅助指标来源同步维护工具，运行后必须审查 diff |
| `scripts/sync_provider_code_map.py` | provider code 映射同步工具，运行后必须跑严格校验 |
| `scripts/generate_static_html.py` | 旧静态 HTML 生成工具；当前生产使用 Vite |

### 前端与产物

| 文件或目录 | 职责 |
| --- | --- |
| `static/index.html`、`static/main.tsx` | Vite 静态页面入口 |
| `app/Dashboard.tsx` | 面板主界面和交互 |
| `app/SignalDrilldownModal.tsx` | 指标详情/信号下钻弹窗 |
| `app/globals.css` | 页面全局样式 |
| `app/types.ts` | dashboard JSON 的 TypeScript 类型 |
| `public/data/dashboard.json` | 数据管线生成的前端输入源 |
| `public/cjhx-logo.png` | 构建时复制的品牌资源 |
| `docs/` | `build:github` 生成的可发布静态站点；不要只手改这里 |
| `outputs/data-quality-report.json` | 最近一次严格校验报告 |
| `outputs/series-catalog.csv` | 完整序列目录审计产物 |
| `outputs/provider-code-collisions.csv` | provider code 冲突审计产物 |

### 测试与说明

| 文件或目录 | 职责 |
| --- | --- |
| `tests/test_hybrid_adapter.py` | CJHX/iFinD 路由、缓存和 provider 身份保护测试 |
| `tests/test_data_quality_guards.py` | 严格质量门禁测试 |
| `tests/test_data_pipeline.py` | 数据生成主流程测试 |
| `tests/test_latest_observation_anchor.py` | 最新观测日期锚定测试 |
| `tests/test_full_history_range.py` | 历史窗口覆盖测试 |
| `tests/test_scoring_direction.py`、`test_signal_threshold.py` | 评分方向和阈值测试 |
| `tests/rendered-html.test.mjs` | 旧渲染测试；当前 `npm test` 实际映射到 Python unittest |
| `README.md` | 开发、接口和基础结构说明 |
| `METHODOLOGY.md` | 指标计算和评分方法 |
| `INTERNAL_AI_INTEGRATION.md` | 内部 AI 集成说明，不参与 Pages 生产运行 |
| `db/`、`worker/`、`examples/`、`next.config.ts` | 其他部署/示例脚手架；当前 GitHub Pages 生产链不使用 |

## 15. 数据源边界和路由真相

这是本项目最重要的约束：不要根据语义代码的文本前缀判断真实来源，也不要因为某个 CJHX 日期旧就临时改走 iFinD。

`hybrid_adapter.fetch_series()` 的真实顺序是：

1. 如果代码存在于 `config/cjhx-series-map.json`，走 CJHX。
2. 否则如果代码存在于 `config/ifind-series.csv`，走 iFinD。
3. 两边都没有就立即失败。

因此类似 `IFIND:BRENT` 的代码也可能因存在于 CJHX 路由表而实际走 CJHX。文本前缀是历史语义标识，不是运行时路由开关。

2026-08-07 机械审计结果：

- 111 个唯一指标，121 个组件行。
- 111 个唯一语义代码中，70 个路由到 CJHX，41 个路由到 iFinD。
- 缺失路由 0 个，同时存在于两张路由表的代码 0 个。
- 主配置有 39 个主指标、49 个组件：27 个组件走 CJHX，22 个组件走 iFinD。
- `steel_inventory` 是显式 `CJHX+iFinD` 复合指标：螺纹库存走 CJHX，热卷/冷轧/中板库存走 iFinD。只能按组件分别取数，不能互相补写。

修改来源时必须同时审查：指标定义中的 `source` 展示值、组件 `code`、CJHX 路由表、iFinD 路由表、provider code 映射和相关测试。禁止让同一个代码同时出现在两张路由表；因为 CJHX 优先，这会静默遮蔽 iFinD 配置。

### CJHX

- 默认上游：`https://raw.githubusercontent.com/wangzhwiei/macro-data/main/macro_extract_70_results.csv`。
- 每次 pipeline 运行下载一次并缓存到 `github-runner\ifind-cache\macro_extract_70_results.csv`。
- 下载失败且存在旧缓存时会继续使用旧 CSV，并写 warning；验收必须看 `updatedAt`，不能只看 workflow success。
- 当前机器没有 `cjhx-cais-bis-skill`，不能直接刷新 CJHX API。CJHX 旧日期只能等待 `macro-data` 上游更新，不能用 iFinD 补齐。

### iFinD

- 调用入口是 WSL skill 的 `call.py`，workflow 会先验证 `call.py` 和 `mcp_config.json`。
- `ifind-series.csv` 的 `provider_id` 是身份断言。返回数据出现不同 provider ID 时必须失败，防止模糊匹配漂移。
- 本机缓存存在时，从最后缓存日期加一天开始请求；`--days 1310` 是最终历史窗口，不代表每天全量抓 1310 天。
- 单序列最多重试 3 次；如果增量区间无新观测且已有验证缓存，会保留缓存。因此节假日/非交易日不应强行制造新日期。
- `nanhua_metals` 的正确查询名是 `南华金属指数`，正确 provider ID 是 `S004094486`。不要恢复为 `南华期货:金属指数`，否则会漂移到错误序列。

## 16. 日常运行和验收

### 正常自动运行

- 07:00 左右等待 CJHX 上游更新。
- 08:30 GitHub schedule 触发。
- 本机 runner 完成数据和构建，正常约 5 至 15 分钟。
- GitHub Pages 部署通常再需 1 至数分钟；CDN 最多约 10 分钟。

不要在前一轮尚未结束时反复点 `Run workflow`。workflow 的 concurrency 为 `macro-dashboard-production` 且 `cancel-in-progress: false`，重复运行会排队并延长总时间。

### 本机手工验证

在 `source-main` 中执行：

```powershell
$env:PYTHONUTF8 = '1'
wsl.exe -d Ubuntu -- bash -lc "export PYTHONUTF8=1; export IFIND_SKILL_DIR='/home/wangzhiwei202307/.openclaw/workspace/skills/ifind-finance-data/ifind-finance-data'; export MACRO_DATA_CACHE_DIR='/mnt/c/Users/wangzhiwei202307/Documents/宏观网页面板/github-runner/ifind-cache'; unset IFIND_CACHE_ONLY; python3 scripts/run_pipeline.py --adapter hybrid --days 1310 --data-only"
npm ci --no-audit --no-fund
npm run build:github
```

只做离线缓存验证时才可临时设置 `IFIND_CACHE_ONLY=1`；生产每日 workflow 必须 `unset IFIND_CACHE_ONLY`，否则 iFinD 不会查询最新数据。

### 必查验收项

1. Actions 的 `update-and-build` 和 `deploy` 都是 `success`。
2. `outputs/data-quality-report.json` 无 error；warning 必须逐条理解，不能机械忽略。
3. 线上 JSON 的 `generatedAt` 等于本次构建值。
4. 按 `source, updatedAt` 汇总日频指标，分别判断 CJHX 与 iFinD 新鲜度。
5. 核对 `nanhua_metals.source=iFinD`、provider 身份未漂移、日期和值合理。
6. 打开线上页面检查静态资源和交互，不要只验证 JSON。

绕过 CDN 的验证地址格式：

```text
https://wangzhwiei.github.io/macro-dashboard/data/dashboard.json?verify=UNIX_TIMESTAMP
```

## 17. 故障恢复手册

| 现象 | 最可能原因 | 处理 |
| --- | --- | --- |
| `update-and-build` 一直 queued | 本机 runner offline 或用户未登录 | 登录 Windows；检查 `Runner.Listener`；必要时运行 `github-runner\run.cmd` |
| `Verify WSL iFinD skill` 失败 | 服务账户/用户不对、WSL 未启动、skill 路径或配置缺失 | 确保由当前用户 runner 启动；验证 Ubuntu、`call.py`、`mcp_config.json` |
| iFinD 步骤慢 | 41 个序列顺序请求、网络延迟、重试 | 先看具体 step；正常 5 至 10 分钟，不要并发触发第二轮 |
| iFinD provider 漂移 | 查询名模糊匹配到其他序列 | 修正 `query_name`，保留/核实 `provider_id`，添加回归测试；不能接受错误 ID |
| CJHX 日期旧但 workflow success | 上游 CSV 本身旧，或下载失败后使用本地缓存 | 对比 `macro-data` CSV 尾部和缓存；不能改走 iFinD |
| strict validation 失败 | 配置、日期、数值、映射或输出不满足门禁 | 修复根因后重跑全 pipeline；禁止跳过校验发布 |
| `deploy` 的 `Set up job` 失败 | GitHub hosted runner provisioning 故障 | 只重跑 failed jobs，不重复 iFinD 抓取 |
| `deploy-pages` 报 OIDC 503 | GitHub OIDC/Pages 外部故障 | 确认权限仍有 `pages: write`、`id-token: write`；只重跑 failed jobs |
| deploy success 但线上仍旧 | CDN `max-age=600` | 等待并用随机查询参数核对 `generatedAt` |
| 两条 Pages workflow 同时运行 | 有人 push 了 `gh-pages`，触发 `pages.yml` | 保持当前 artifact 主链；不要日常 push `gh-pages` |
| 改了 main workflow 但 schedule 未变化 | 默认分支是 `gh-pages`，GitHub 从默认分支读 schedule | 将主 workflow 同步到 `gh-pages`，或经过评审后把默认分支改为 `main` |

2026-08-06/07 实际故障样本：run `31116483522` 的数据与构建一次成功；deploy attempt 1 在 hosted runner setup 失败，attempt 2 因 OIDC HTTP 503 失败，attempt 3 排队后被取消，attempt 4 成功。恢复过程只重跑 failed jobs，没有重复抓取 iFinD。

## 18. 安全边界和禁止事项

- 不提交 `github-runner` 目录、`ifind-cache`、runner `.credentials*`、iFinD `mcp_config.json`、token、密码或供应商历史缓存。
- 不在命令输出、Actions 日志、Markdown 或 issue 中打印 GitHub token。runner 注册 token 只能短期存在于进程内存。
- 不清空 `github-runner\ifind-cache`。清空会丢失增量基线并显著增加供应商调用量。
- 不直接编辑 `github-runner\_work`、`docs/assets` 或 `docs/data/dashboard.json` 来修数据。应改配置/adapter，重新生成 `public/data/dashboard.json`，再构建。
- 不因数据日期旧跨源补写。CJHX 与 iFinD 的来源边界由项目配置决定，不由当日数据新鲜度决定。
- 不只看语义代码前缀判断来源；必须按 CJHX 路由表优先规则核对。
- 不把 Windows runner 改为默认系统服务账户后直接认为可用；该账户通常访问不到当前用户的 WSL Ubuntu。
- 不在 Pages workflow 模式和 legacy branch 模式之间来回切换。切换前必须先设计唯一发布链并停用另一条。
- 不把 `workflow success` 等同于所有日频指标当天有值。交易日、频率、上游发布时间和缓存回退都可能让日期不同。
- 不随意并行化 41 个 iFinD 请求。供应商并发限制未知，贸然并发可能触发限流、认证异常或结果错配。

### 修改后最低检查清单

```powershell
python -m unittest discover -s tests -p "test_*.py"
python scripts/validate_dashboard.py --strict --report outputs/data-quality-report.json
npm run build:github
git diff --check
git status --short
```

涉及真实数据源、workflow 或发布行为的修改，还必须完成一次 `workflow_dispatch` 端到端运行并核对线上 `generatedAt`。涉及 workflow 的修改需要特别确认默认分支 `gh-pages` 上的定义是否同步。
## 19. 2026-08-07 定时与频率审计

### 08:30 未更新的直接原因

北京时间 09:21 检查时，GitHub 没有创建任何 `event=schedule` 的 run；workflow 状态为 `active`，本机 `macro-dashboard-windows` runner 同时为 `online/idle`。因此不是 runner 离线或任务排队，而是 GitHub 的 schedule 事件没有入队。该 workflow 于 2026-08-06 20:42 才在默认分支激活，GitHub schedule 是 best-effort，首次运行和高负载时可能延迟或丢失。

修复：保留 08:30 主 cron `30 0 * * *`，新增 09:10 兜底 cron `10 1 * * *`。 `main` 修复提交为 `39de2b0`，默认分支 workflow 同步提交为 `9bef837`。同一天重复运行会命中本机增量缓存，iFinD 已有当天数据时不再重复请求完整历史。 `main` 中的备用 `pages.yml` 已配置忽略仅修改 `.github/**` 的 push，但它没有同步到默认分支，因此当前生产不会注册第二条 Pages workflow。

### 当天补跑

- 手工补跑：<https://github.com/wangzhwiei/macro-dashboard/actions/runs/31137940333>
- runner、WSL skill、CJHX 下载和 iFinD 调用均实际执行。
- 数据产物：`generatedAt=2026-08-07T01:36:52.673391+00:00`。
- 旧版严格校验发现 `iron_ore_62`、`cement_east`、`cement_yangtze` 最新仍为 `2026-07-30`，滞后 8 天，因此阻止构建和发布。
- 线上页面保持上一版是质量门禁的预期行为，不是部署遗漏。

### 频率与新鲜度审计

新增 `scripts/audit_freshness.py`，每次 pipeline 生成 `outputs/frequency-freshness-audit.csv`。报告逐项记录配置频率、页面频率、历史观测间隔中位数、最新日期、滞后天数、容忍天数和状态。

2026-08-07 真实补跑数据审计：

- 指标总数：111。
- 日频：72；周频：39。
- 频率节奏异常：0。所有日频旧数据的历史间隔中位数都是 1 天，说明“日频”标注正确，问题是上游停止供新记录。
- 过期：24，全部为 CJHX；iFinD 过期 0。
- CJHX 日频过期 17：`cement_east`、`cement_yangtze`、`iron_ore_62`、`brent`、`cement_national`、`dxy`、`eurusd`、`gold_spot`、`lme_zinc`、`silver_spot`、`usdjpy`、`wti`、`metro_composite`、`metro_guangzhou`、`metro_shanghai`、`newhome_30c`、`newhome_tier3`。
- CJHX 周频过期 7：`car_retail_yoy`、`car_wholesale_yoy`、`land_4w`、`land_premium`、`land_tier1`、`land_tier2`、`land_tier3`。

日频最新日期分布：

- `2026-07-30`：3 项。
- `2026-07-31`：9 项。
- `2026-08-01`：5 项。
- 其余日频已更新到 `2026-08-06` 或符合交易日/发布节奏。

CJHX GitHub 上游核验：

- `macro-data` 仓库在 2026-08-07 07:01 左右有新的 main push，最新提交 `d9cc84c62d35a0b0aefbb207e062f8589b27164f`。
- 生产使用的 `macro_extract_70_results.csv` 是正确文件，最新 blob `d8a7b2eaa0406412138f82ea4ab0bd6e35b29b17`，含 70 个 `series_key`、52682 行。
- 文件整体每天更新不等于每个序列每天都有新记录：该 blob 中 38 个序列已到 `2026-08-06`，其余序列仍分别停在 `2026-07-20`、`2026-07-26`、`2026-07-30`、`2026-07-31` 或 `2026-08-01`。
- `macro_extract_71_results.csv` 更旧，多数序列只到 7 月 31，不可切换过去。
- adapter 已给 Raw GitHub URL 添加 `cache_bust` 时间戳与 `Cache-Control: no-cache`，避免固定 URL 命中 CDN 旧内容。

本机和 WSL 均未找到 `cjhx-cais-bis-skill` 或 CJHX API 凭据，只有仓库抓取脚本。项目会继续读取 GitHub `macro-data` 的每日 70 文件；如果文件内单个序列没有新行，只能按真实日期告警，禁止把上述 CJHX 指标临时改走 iFinD。

### 质量门禁修复

- 页面生成器与校验器统一默认新鲜度阈值：日频 4 天、周频 14 天。
- 两处都尊重单指标 `stale_tolerance_days` 显式配置。
- 新增日频过稀、周频过密和周频过稀的双向节奏检查。
- 质量报告新增 `stale_indicators` 和 `cadence_issues` 计数。
- `--strict` 会阻止过期数据以零 warning 发布。
- Actions artifact 同时上传 JSON 质量报告和完整频率/新鲜度 CSV。

验证结果：Python 单元测试 22 项全部通过；Python 语法检查通过；Vite 生产构建通过；`git diff --check` 通过。