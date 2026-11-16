import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import './admin.css';
import settings from '../config/cloud-admin.json';

const REPO='wangzhwiei/macro-dashboard';
const STAGING=settings.phase!=='production';
const BRANCH=STAGING?'cloud-admin-staging':'main';
const WORKFLOW=STAGING?'cloud-staging.yml':'cloud-update.yml';
const API=`https://api.github.com/repos/${REPO}`;
type Config={schemaVersion:number;phase:string;schedule:{enabled:boolean;hourShanghai:number;minute:number};maxProviderCalls:number;refreshMonthlyInputs:boolean};
type Run={id:number;status:string;conclusion:string|null;html_url:string;created_at:string};
const paths=[
 ['高频指标定义','config/indicators.json','指标、单位、频率及评分逻辑'],
 ['iFinD 唯一编码','config/ifind-series.csv','固定编码映射；变更必须通过口径校验'],
 ['公开数据映射','config/cjhx-series-map.json','macro-data 仓库 CSV → 标准指标'],
 ['CPI / PPI / PMI','data/forecast-model/ifind_forecast_manifest.json','月频预测的固定入模数据'],
 ['社零','data/forecast-model/research_retail_manifest.json','社零固定因子与查询口径'],
 ['完整增量流程','scripts/run_pipeline.py','高频取数 → 月频重算 → 校验 → 构建'],
];
function Admin(){
 const [token,setToken]=useState(''); const [connected,setConnected]=useState(false);
 const [busy,setBusy]=useState(false); const [message,setMessage]=useState('');
 const [config,setConfig]=useState<Config|null>(null); const [sha,setSha]=useState('');
 const [runs,setRuns]=useState<Run[]>([]); const [search,setSearch]=useState('');
 async function api(path:string,init:RequestInit={}){
  const response=await fetch(API+path,{...init,cache:'no-store',headers:{Accept:'application/vnd.github+json',Authorization:`Bearer ${token}`,'Content-Type':'application/json'}});
  if(!response.ok)throw new Error(`GitHub 请求失败（${response.status}）。请检查令牌有效期及本仓库的 Contents / Actions 权限。`);
  return response.status===204?null:response.json();
 }
 async function load(){
  const repo=await api(''); if(!repo.permissions?.push)throw new Error('需要此仓库的写入权限。');
  const file=await api(`/contents/config/cloud-admin.json?ref=${BRANCH}`);
  const bytes=Uint8Array.from(atob(file.content.replace(/\s/g,'')),c=>c.charCodeAt(0));
  setConfig(JSON.parse(new TextDecoder().decode(bytes)));setSha(file.sha);
  const result=await api(`/actions/workflows/${WORKFLOW}/runs?per_page=10`);setRuns(result.workflow_runs);
  setConnected(true);
 }
 async function perform(action:()=>Promise<void>){setBusy(true);setMessage('');try{await action();}catch(e){setMessage(e instanceof Error?e.message:'操作失败');}finally{setBusy(false);}}
 function logout(){setToken('');setConnected(false);setConfig(null);setRuns([]);setSha('');setMessage('已清除当前会话令牌。');}
 async function save(){
  if(!config)return;
  if(STAGING&&(config.phase!=='staging'||config.schedule.enabled))throw new Error('试运行阶段不允许开启生产定时发布。');
  if(!Number.isInteger(config.maxProviderCalls)||config.maxProviderCalls<1||config.maxProviderCalls>100)throw new Error('调用上限须为 1—100 的整数。');
  if(!Number.isInteger(config.schedule.hourShanghai)||config.schedule.hourShanghai<0||config.schedule.hourShanghai>23)throw new Error('请选择有效小时。');
  const content=btoa(JSON.stringify(config,null,2)+'\n');
  await api('/contents/config/cloud-admin.json',{method:'PUT',body:JSON.stringify({branch:BRANCH,sha,message:'admin: save cloud staging settings',content})});
  await load();setMessage(STAGING?'设置已保存到测试分支；正式页面和自动发布保持不变。':'设置已保存。定时任务按北京时间所选小时的第 45 分钟执行，GitHub 调度可能延迟。');
 }
 const active=runs.some(r=>['queued','in_progress','waiting','pending','requested'].includes(r.status));
 return <main className="admin-shell">
  <header><a className="back" href="./index.html">← 返回研究面板</a><span className="pill">{STAGING?'独立试运行 · 正式版保留':'云端执行 · 旧版可回滚'}</span><h1>云端管理中心</h1><p>管理数据来源、云端取数与运行记录。无需保持个人电脑开机。</p></header>
  <aside className="notice">{STAGING?'生产切换尚未放行。当前任务只生成测试产物，不写正式数据、不部署正式网页、不启用定时取数。':'取数、预测、校验和发布均在 GitHub 托管执行器运行。校验失败时不替换正式页面。'}</aside>
  {!connected?<section><h2>管理员连接</h2><p>使用仅授权此仓库的 GitHub 细粒度令牌，授予 Contents 和 Actions 读写权限。令牌仅保留在本页内存，刷新或退出后清除；不要输入 iFinD 密钥。</p><form onSubmit={e=>{e.preventDefault();void perform(load);}}><label htmlFor="token">GitHub 访问令牌</label><input id="token" type="password" autoComplete="off" value={token} onChange={e=>setToken(e.target.value)} required/><button disabled={busy||!token}>验证并连接</button></form><a href={`https://github.com/settings/personal-access-tokens/new`} target="_blank" rel="noreferrer">在 GitHub 创建限定权限令牌 ↗</a></section>:<>
  <section><div className="section-title"><h2>云端执行</h2><button className="secondary" onClick={logout} disabled={busy}>退出管理</button></div><p>执行器：GitHub 托管 Linux · 接口：get_edb_data · 仅增量取数 · iFinD 凭据保存在 GitHub Secrets</p><div className="actions"><button disabled={busy||active} onClick={()=>void perform(async()=>{if(!window.confirm(STAGING?'运行云端增量测试？会消耗接口额度，但不会覆盖正式网页。':'执行增量取数、月频重算并发布？会消耗接口额度。'))return;await api(`/actions/workflows/${WORKFLOW}/dispatches`,{method:'POST',body:JSON.stringify(STAGING?{ref:BRANCH}:{ref:'gh-pages',inputs:{mode:'refresh'}})});setMessage('任务已提交，请稍后刷新运行状态。');})}>{STAGING?'运行高频 + 月频增量测试':'增量更新并发布'}</button>{!STAGING&&<button className="secondary" disabled={busy||active} onClick={()=>void perform(async()=>{if(!window.confirm('只发布仓库已有数据，不调用 iFinD，是否继续？'))return;await api(`/actions/workflows/${WORKFLOW}/dispatches`,{method:'POST',body:JSON.stringify({ref:'gh-pages',inputs:{mode:'publish_only'}})});setMessage('仅发布任务已提交。');})}>仅重新发布</button>}<button className="secondary" disabled={busy} onClick={()=>void perform(load)}>刷新运行状态</button></div>{active&&<p>已有任务运行或排队中，暂不重复提交。</p>}</section>
  {config&&<section><h2>自动更新与调用控制</h2><p>{STAGING?'迁移验证完成前，自动更新保持关闭。可保存设置草稿，但不会启动定时任务。':'启用后，每天按所选北京时间更新高频数据和月频预测。GitHub 调度可能延迟，并非精确定时服务。'}</p><div className="fields"><label>每日计划时间（北京时间）<select value={config.schedule.hourShanghai} onChange={e=>setConfig({...config,schedule:{...config.schedule,hourShanghai:Number(e.target.value)}})}>{Array.from({length:24},(_,h)=><option key={h} value={h}>{String(h).padStart(2,'0')}:45</option>)}</select></label><label>单次接口调用上限<input type="number" min="1" max="100" value={config.maxProviderCalls} onChange={e=>setConfig({...config,maxProviderCalls:Number(e.target.value)})}/></label></div><label><input style={{display:'inline',width:'auto',marginRight:10}} type="checkbox" disabled={STAGING} checked={config.schedule.enabled} onChange={e=>setConfig({...config,schedule:{...config.schedule,enabled:e.target.checked}})}/>启用每日云端自动更新{STAGING?'（待验收）':''}</label><p>包含月频入模数据：是</p><button disabled={busy} onClick={()=>void perform(save)}>保存设置</button></section>}
  <section><h2>最近运行</h2>{runs.length===0?<p>暂无运行记录。</p>:<div className="table-wrap"><table><thead><tr><th>时间</th><th>状态</th><th>记录</th></tr></thead><tbody>{runs.map(run=><tr key={run.id}><td>{new Date(run.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</td><td>{run.conclusion??run.status}</td><td><a href={run.html_url} target="_blank" rel="noreferrer">日志与测试产物 ↗</a></td></tr>)}</tbody></table></div>}</section>
  </>}
  {message&&<p role="status" className="notice">{message}</p>}
  <section><h2>数据提取路径</h2><p>以下为实际脚本和编码配置。为防止错码及凭据外泄，页面不接受任意外部接口地址；配置变更必须经测试校验。</p><input aria-label="筛选数据路径" placeholder="搜索指标、数据路径…" value={search} onChange={e=>setSearch(e.target.value)}/><div className="table-wrap"><table><thead><tr><th>数据模块</th><th>配置路径</th><th>说明</th></tr></thead><tbody>{paths.filter(row=>row.join(' ').toLowerCase().includes(search.toLowerCase())).map(([name,path,note])=><tr key={path}><td>{name}</td><td><a href={`https://github.com/${REPO}/blob/${BRANCH}/${path}`} target="_blank" rel="noreferrer">{path}</a></td><td>{note}</td></tr>)}</tbody></table></div></section>
  <footer>回滚快照：backup/pre-cloud-main-20261116 / backup/pre-cloud-pages-20261116</footer>
 </main>;
}
createRoot(document.getElementById('root')!).render(<Admin/>);
