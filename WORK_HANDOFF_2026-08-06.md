# 工作交接记录（2026-08-06）

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
