"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import type { ForecastData, ForecastHistoryPoint, ForecastInput, ForecastPoint } from "./forecast-v3-types";
import "./forecast-v2.css";
import "./forecast-v3.css";

type ModelKey = "cpi" | "ppi" | "pmi" | "exports" | "imports";
type ViewMode = "yoy" | "mom";

function seriesKey(metric: ModelKey, mode: ViewMode) {
  return metric === "pmi" || metric === "exports" || metric === "imports" || mode === "yoy" ? metric : `${metric}_mom`;
}

const MODEL_LABELS: Record<ModelKey,string> = {cpi:"CPI",ppi:"PPI",pmi:"制造业PMI",exports:"出口同比",imports:"进口同比"};

function niceStep(raw: number) {
  const power = 10 ** Math.floor(Math.log10(Math.max(raw, .0001)));
  const normalized = raw / power;
  return (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * power;
}

function geometry(rows: ForecastHistoryPoint[], width: number, height: number) {
  const padding = { left: 68, right: 24, top: 30, bottom: 46 };
  const values = rows.flatMap((row) => [row.forecast, row.actual, row.consensus]).filter((value): value is number => value !== null && Number.isFinite(value));
  const rawMin = values.length ? Math.min(...values) : 0;
  const rawMax = values.length ? Math.max(...values) : 1;
  const step = niceStep(Math.max(rawMax - rawMin, .1) / 5);
  const lower = Math.floor((rawMin - step * .4) / step) * step;
  const upper = Math.ceil((rawMax + step * .4) / step) * step;
  const span = Math.max(upper - lower, step);
  const x = (index: number) => padding.left + index / Math.max(rows.length - 1, 1) * (width - padding.left - padding.right);
  const y = (value: number) => padding.top + (1 - (value - lower) / span) * (height - padding.top - padding.bottom);
  const ticks = Array.from({ length: Math.round(span / step) + 1 }, (_, index) => lower + index * step);
  const path = (field: "forecast" | "actual" | "consensus") => rows.reduce((parts, row, index) => {
    const value = row[field];
    if (value === null || !Number.isFinite(value)) return parts;
    const previous = index > 0 ? rows[index - 1][field] : null;
    parts.push(`${previous === null ? "M" : "L"}${x(index).toFixed(1)},${y(value).toFixed(1)}`);
    return parts;
  }, [] as string[]).join(" ");
  return { padding, x, y, ticks, path };
}

function HistoryChart({ rows, precision }: { rows: ForecastHistoryPoint[]; precision: number }) {
  const [hover, setHover] = useState<ForecastHistoryPoint | null>(null);
  const width = 1040, height = 430;
  const { padding, x, y, ticks, path } = geometry(rows, width, height);
  const yearTicks = rows.map((row, index) => ({ row, index })).filter(({ row }, index) => row.date.slice(5, 7) === "01" || index === rows.length - 1);
  const backtestIndex = rows.findIndex((row) => row.date >= "2023-01-01");
  const latest = [...rows].reverse().find((row) => row.forecast !== null || row.actual !== null);
  return <>
    <div className="forecast-v2-legend" aria-label="图例"><span><i className="actual" />真实公布值</span><span><i className="model" />月末无前视模型值</span><span><i className="locked" />当前确认点预测</span><span><i className="consensus" />市场一致预期（有数据时）</span></div>
    <div className="forecast-v2-chart-shell">
      <div className="forecast-v2-reading"><span>{(hover ?? latest)?.date.slice(0, 7)}</span><strong>{(hover ? hover.actual : (latest?.actual ?? latest?.forecast))?.toFixed(precision) ?? "—"}</strong><small>{hover ? `一致预期 ${hover.consensus?.toFixed(precision) ?? "—"} / 模型 ${hover.forecast?.toFixed(precision) ?? "—"}` : "最新月度读数"}</small></div>
      <svg viewBox={`0 0 ${width} ${height}`} className="forecast-v2-chart" onMouseLeave={() => setHover(null)} role="img" aria-label="2023年至今实际值与无前视预测对比图">
        {ticks.map((tick) => <g key={tick}><line x1={padding.left} x2={width-padding.right} y1={y(tick)} y2={y(tick)} className="grid"/><text x={padding.left-9} y={y(tick)+4} textAnchor="end">{tick.toFixed(precision)}</text></g>)}
        {backtestIndex >= 0 && <g><line x1={x(backtestIndex)} x2={x(backtestIndex)} y1={padding.top} y2={height-padding.bottom} className="backtest-start"/><text x={x(backtestIndex)+6} y={padding.top+13} className="backtest-label">无前视回测起点</text></g>}
        <path d={path("actual")} className="series-actual"/><path d={path("forecast")} className="series-model"/><path d={path("consensus")} className="series-consensus"/>
        {rows.map((row,index)=><g key={row.date}><rect x={x(index)-6} y={padding.top} width="12" height={height-padding.top-padding.bottom} className="hover-band" onMouseEnter={()=>setHover(row)}/>{row.forecastKind==="confirmed_nowcast"&&row.forecast!==null&&<polygon points={`${x(index)},${y(row.forecast)-7} ${x(index)+7},${y(row.forecast)} ${x(index)},${y(row.forecast)+7} ${x(index)-7},${y(row.forecast)}`} className="locked-marker"/>}</g>)}
        {yearTicks.map(({row,index})=><text key={row.date} x={x(index)} y={height-15} textAnchor={index===0?"start":index===rows.length-1?"end":"middle"}>{row.date.slice(0,4)}</text>)}
      </svg>
    </div>
  </>;
}

function RealtimeChart({ points, label, unit }: { points: ForecastPoint[]; label: string; unit: string }) {
  const [hover, setHover] = useState<ForecastPoint | null>(null);
  const rows = points.map((point) => ({ date: point.date, actual: point.value, forecast: null, consensus: null }));
  const width=1040,height=260,{padding,x,y,ticks,path}=geometry(rows,width,height);
  const latest=points.at(-1), first=points[0];
  const move=latest&&first?latest.value-first.value:null;
  return <section className="forecast-live">
    <div className="forecast-live-heading"><div><span className="eyebrow">当月日度实时预测</span><h3>{label}实时路径</h3><p>每个日期只使用当时已到达的高频数据；模型参数固定，月内均值随新增观测更新。</p></div><div className="forecast-live-kpi"><span>最新 / 月末收敛值</span><strong>{latest?.value.toFixed(3) ?? "-"}{unit}</strong><small>{latest?.date} · 较月初 {move===null?"—":`${move>=0?"+":""}${move.toFixed(3)}`} 个百分点</small></div></div>
    <div className="forecast-live-chart"><div className="forecast-v2-input-reading">{hover?`${hover.date} · ${hover.value.toFixed(3)}${unit}`:`${latest?.date} · ${latest?.value.toFixed(3)}${unit}`}</div><svg viewBox={`0 0 ${width} ${height}`} onMouseLeave={()=>setHover(null)}>{ticks.map((tick)=><g key={tick}><line x1={padding.left} x2={width-padding.right} y1={y(tick)} y2={y(tick)}/><text x={padding.left-8} y={y(tick)+4} textAnchor="end">{tick.toFixed(3)}</text></g>)}<path d={path("actual")}/>{points.map((point,index)=><circle key={point.date} cx={x(index)} cy={y(point.value)} r="7" className="input-hit" onMouseEnter={()=>setHover(point)}/>)}<text x={padding.left} y={height-12}>{points[0]?.date}</text><text x={width-padding.right} y={height-12} textAnchor="end">{latest?.date}</text></svg></div>
  </section>;
}

function ComparisonTable({ rows, precision, hasConsensus }: { rows: ForecastHistoryPoint[]; precision: number; hasConsensus: boolean }) {
  return <div className="forecast-v2-table"><div className="forecast-v2-row head"><span>月份</span><span>模型值</span><span>建议报数</span><span>市场一致预期</span><span>真实值</span></div>{[...rows].reverse().map((row)=><div className="forecast-v2-row" key={row.date}><strong>{row.date.slice(0,7)}</strong><span>{row.forecast?.toFixed(precision)??"—"}</span><span>{row.officialRounding?.toFixed(1)??"—"}</span><span title={row.consensusSource??undefined}>{hasConsensus?(row.consensus?.toFixed(precision)??"暂无公开数据"):"环比无一致预期"}</span><span>{row.actual?.toFixed(1)??"尚未公布"}</span></div>)}</div>;
}

function inputChange(item: ForecastInput) {
  const latest=item.series.at(-1); if(!latest) return { value:null, label:"—" };
  const month=latest.date.slice(0,7),same=item.series.filter((point)=>point.date.startsWith(month)),monthly=item.frequency==="月频";
  const previous=[...item.series].reverse().find((point)=>point.date<`${month}-01`);
  const first=monthly?previous:(same.length>1?same[0]:previous),prefix=monthly?"较上期":"较月初";
  if(!first) return { value:null, label:"—" };
  if(item.unit==="%") return {value:latest.value-first.value,label:`${prefix} ${latest.value-first.value>=0?"+":""}${(latest.value-first.value).toFixed(2)} 个百分点`};
  if(first.value===0) return {value:null,label:"—"};
  const value=(latest.value/first.value-1)*100;
  return {value,label:`${prefix} ${value>=0?"+":""}${value.toFixed(2)}%`};
}

function filterPoints(item: ForecastInput, range: string) {
  if(range==="all"||!item.series.length)return item.series;
  const end=new Date(item.series.at(-1)!.date),start=new Date(end);start.setMonth(start.getMonth()-Number(range));
  return item.series.filter((point)=>new Date(point.date)>=start);
}

function InputHistoryModal({item,onClose}:{item:ForecastInput;onClose:()=>void}) {
  const [range,setRange]=useState("12"),[hoverIndex,setHoverIndex]=useState<number|null>(null);
  useEffect(()=>{const close=(event:KeyboardEvent)=>event.key==="Escape"&&onClose();const previous=document.body.style.overflow;document.body.style.overflow="hidden";window.addEventListener("keydown",close);return()=>{window.removeEventListener("keydown",close);document.body.style.overflow=previous}},[onClose]);
  const points=filterPoints(item,range),rows=points.map((point)=>({date:point.date,actual:point.value,forecast:null,consensus:null}));
  const width=940,height=330,{padding,x,y,ticks,path}=geometry(rows,width,height),latest=points.at(-1),change=inputChange(item);
  const hovered=hoverIndex===null?null:points[hoverIndex],hoverX=hoverIndex===null?null:x(hoverIndex),hoverY=hovered?y(hovered.value):null;
  const download=()=>{const csv=["date,value",...item.series.map((point)=>`${point.date},${point.value}`)].join("\n");const url=URL.createObjectURL(new Blob([`\uFEFF${csv}`],{type:"text/csv;charset=utf-8"}));const link=document.createElement("a");link.href=url;link.download=`${item.id}.csv`;link.click();URL.revokeObjectURL(url)};
  const modal=<div className="forecast-input-modal-backdrop" onMouseDown={(event)=>event.currentTarget===event.target&&onClose()}><section className="history-modal forecast-v2-modal forecast-v3-modal" role="dialog" aria-modal="true" aria-label={`${item.name}高频历史`}><header className="history-header"><div><span className="eyebrow">原始频率入模指标</span><h2>{item.name}</h2><p>{item.source} · {item.frequency} · {item.id}</p></div><button className="modal-close" onClick={onClose} aria-label="关闭">×</button></header>
    <div className="history-kpis"><div><span>最新高频值</span><strong>{latest?.value.toFixed(2)??"-"}</strong><small>{item.unit} · {latest?.date}</small></div><div><span>{item.frequency==="月频"?"较上期变化":"相比月初"}</span><strong>{change.label}</strong><small>按原始频率直接比较，未月频化</small></div><div><span>模型用途</span><strong>{item.role}</strong><small>{item.aggregation}</small></div></div>
    {item.modelUsageNote&&<div className="forecast-v3-usage-note"><strong>2026年7月使用口径</strong><span>{item.modelUsageNote}</span></div>}
    <div className="history-toolbar"><div className="range-tabs">{[["1","近1个月"],["3","近3个月"],["12","近1年"],["all","全部"]].map(([value,label])=><button key={value} className={range===value?"active":""} onClick={()=>{setRange(value);setHoverIndex(null)}}>{label}</button>)}</div><button className="forecast-v2-download" onClick={download}>下载 CSV</button></div>
    <div className="forecast-v2-input-chart"><div className="forecast-v2-input-reading">{hovered?`${hovered.date} · ${hovered.value.toFixed(2)} ${item.unit}`:`${latest?.date??"-"} · ${latest?.value.toFixed(2)??"-"} ${item.unit}`}</div><svg viewBox={`0 0 ${width} ${height}`} onMouseLeave={()=>setHoverIndex(null)}>{ticks.map((tick)=><g key={tick}><line x1={padding.left} x2={width-padding.right} y1={y(tick)} y2={y(tick)}/><text x={padding.left-8} y={y(tick)+4} textAnchor="end">{tick.toFixed(2)}</text></g>)}<path d={path("actual")}/>{hovered&&hoverX!==null&&hoverY!==null&&<g className="forecast-v3-crosshair"><line x1={hoverX} x2={hoverX} y1={padding.top} y2={height-padding.bottom}/><line x1={padding.left} x2={width-padding.right} y1={hoverY} y2={hoverY}/><circle cx={hoverX} cy={hoverY} r="5"/><rect className="axis-label-bg" x={Math.min(Math.max(hoverX-44,padding.left),width-padding.right-88)} y={height-padding.bottom+5} width="88" height="22" rx="2"/><text className="axis-label" x={Math.min(Math.max(hoverX,padding.left+44),width-padding.right-44)} y={height-padding.bottom+20} textAnchor="middle">{hovered.date}</text><rect className="axis-label-bg" x={padding.left+5} y={Math.min(Math.max(hoverY-12,padding.top),height-padding.bottom-24)} width="106" height="24" rx="2"/><text className="axis-label" x={padding.left+58} y={Math.min(Math.max(hoverY+4,padding.top+16),height-padding.bottom-8)} textAnchor="middle">{hovered.value.toFixed(2)} {item.unit}</text></g>}<rect className="forecast-v3-hover-overlay" x={padding.left} y={padding.top} width={width-padding.left-padding.right} height={height-padding.top-padding.bottom} onPointerMove={(event)=>{const bounds=event.currentTarget.getBoundingClientRect();const local=(event.clientX-bounds.left)/bounds.width;setHoverIndex(Math.min(points.length-1,Math.max(0,Math.round(local*Math.max(points.length-1,0)))));}}/><text x={padding.left} y={height-12}>{points[0]?.date}</text><text x={width-padding.right} y={height-12} textAnchor="end">{latest?.date}</text></svg></div>
  </section></div>;
  return typeof document==="undefined"?null:createPortal(modal,document.body);
}
function ForecastInputs({data}:{data:ForecastData}) {
  const [group,setGroup]=useState("CPI"),[selected,setSelected]=useState<ForecastInput|null>(null),items=data.highFrequency[group]??[];
  const groups=["CPI","PPI","PMI","出口","进口"];
  return <section className="panel forecast-v2-inputs"><div className="section-heading"><div><span className="eyebrow">模型输入 · 原始更新频率</span><h2>真实入模指标</h2><p>点击后查看日频、周频或月频原值；出口与进口模型的固定因子分别列示。</p></div></div><div className="forecast-group-tabs">{groups.map((value)=><button key={value} className={group===value?"active":""} onClick={()=>setGroup(value)}>{value} 入模指标</button>)}</div><div className="forecast-v2-input-list">{items.map((item)=>{const latest=item.series.at(-1),change=inputChange(item);return <button className="forecast-v2-input-row forecast-v3-input-row" key={item.id} onClick={()=>setSelected(item)}><div><strong>{item.name}</strong><small>{item.id}</small></div><div><span>最新值</span><strong>{latest?.value.toFixed(2)??"-"} {item.unit}</strong><small>{latest?.date}</small></div><div><span>月内变化</span><strong>{change.label}</strong><small>{item.frequency} · {item.source}</small></div><div><span>入模方式</span><strong>{item.role}</strong><small>{item.aggregation}</small></div><b>查看原频率历史 ›</b></button>})}</div>{selected&&<InputHistoryModal item={selected} onClose={()=>setSelected(null)}/>}</section>;
}

export default function ForecastWorkspace() {
  const [data,setData]=useState<ForecastData|null>(null),[error,setError]=useState(""),[metric,setMetric]=useState<ModelKey>("cpi"),[mode,setMode]=useState<ViewMode>("yoy"),[range,setRange]=useState("all");
  useEffect(()=>{fetch("./data/forecasts.json",{cache:"no-store"}).then((response)=>{if(!response.ok)throw new Error("预测数据读取失败");return response.json()}).then((payload:ForecastData)=>{if(payload.schemaVersion!==3)throw new Error("预测数据版本不匹配，请重新生成");setData(payload)}).catch((reason:Error)=>setError(reason.message))},[]);
  const key=seriesKey(metric,mode);
  const rows=useMemo(()=>{const all=data?.history[key]??[];if(range==="1y")return all.slice(-12);if(range==="3y")return all.slice(-36);return all},[data,key,range]);
  if(error)return <div className="forecast-workspace shell"><section className="panel"><h2>预测数据暂不可用</h2><p>{error}</p></section></div>;
  if(!data)return <div className="forecast-workspace shell"><section className="panel"><h2>正在加载月频预测</h2></section></div>;
  const model=data.models[key],score=data.metrics[key],latest=[...rows].reverse().find((row)=>row.forecast!==null),latestActual=[...rows].reverse().find((row)=>row.actual!==null),precision=metric==="pmi"?2:3;
  const tradePending=(metric==="exports"||metric==="imports")&&model.status==="WAITING_FOR_FIXED_FACTORS";
  const latestLabel=latest?.officialRounding==null?model.name:`建议报数 ${latest.officialRounding.toFixed(1)}`;
  const currentNote=tradePending?`${model.forecastMonth} · 最早 ${model.earliestForecastDate}`:`${latest?.date.slice(0,7)} · ${latestLabel}`;
  return <div className="forecast-workspace shell"><section className="panel forecast-v2-panel"><div className="section-heading forecast-heading"><div><span className="eyebrow">月频预测 · 无前视回测与当月数据更新</span><h1>CPI / PPI / PMI / 进出口预测</h1><p>{model.description}</p></div><div className="forecast-source">模型数据更新：{new Date(data.generatedAt).toLocaleString("zh-CN")}</div></div>
    <div className="forecast-toolbar"><div className="forecast-tabs">{(["cpi","ppi","pmi","exports","imports"] as ModelKey[]).map((value)=><button key={value} className={metric===value?"active":""} onClick={()=>{setMetric(value);if(value!=="cpi"&&value!=="ppi")setMode("yoy")}}>{MODEL_LABELS[value]}</button>)}</div><div className="forecast-range-tabs">{[["all","2023年至今"],["3y","近3年"],["1y","近1年"]].map(([value,label])=><button key={value} className={range===value?"active":""} onClick={()=>setRange(value)}>{label}</button>)}</div></div>
    {(metric==="cpi"||metric==="ppi")&&<div className="forecast-mode-tabs"><button className={mode==="yoy"?"active":""} onClick={()=>setMode("yoy")}>同比预测</button><button className={mode==="mom"?"active":""} onClick={()=>setMode("mom")}>环比预测</button></div>}
    <div className="forecast-v2-method"><strong>模型口径</strong><span>{model.formula}</span><small>历史预测自 {data.backtestStart.slice(0,7)} 显示；月内实时值不使用当日之后的数据。一致预期来自 iFinD EDB“预测平均值”月频序列，按中文名称查询并锁定指标 ID；PMI 缺失月份沿用上月值。</small></div>
    <div className="forecast-kpis"><div><span>当前确认点预测</span><strong>{tradePending?"待因子公布":latest?.forecast?.toFixed(precision)??"-"}</strong><small>{currentNote}</small></div><div><span>回测误差</span><strong>{score.rmse.toFixed(3)}</strong><small>RMSE · {score.sampleStart} 至 {score.sampleEnd}</small></div><div><span>最近真实公布</span><strong>{latestActual?.actual?.toFixed(1)??"-"}</strong><small>{latestActual?.date.slice(0,7)} · 官方值</small></div></div>
    <HistoryChart rows={rows} precision={precision}/>{(data.daily[key]?.length??0)>0&&<RealtimeChart points={data.daily[key]} label={model.name} unit={model.unit}/>}<ComparisonTable rows={rows} precision={precision} hasConsensus={mode==="yoy"}/>
  </section><ForecastInputs data={data}/></div>;
}
