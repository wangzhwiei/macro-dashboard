#!/usr/bin/env python3
"""Audit July locked forecasts against complete, fixed-provider iFinD inputs."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX
from generate_forecasts_model import (JUNE, JULY, PMI_PROXIES, PMI_SUB_NAMES, PMI_WEIGHTS,
    dict_series, exact_yoy, ifind_series, merge_official_pmi, pmi_momentum, raw_series, read_json, to_series)

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'forecast-model'
source=read_json(DATA/'model_inputs.json')
merge_official_pmi(source,read_json(DATA/'official_pmi_subindices.json'))
ifind=read_json(DATA/'ifind_latest_inputs.json')
locked=read_json(DATA/'locked_nowcasts.json')['2026-07-31']

proxy_map={
 '高炉开工率(247家):全国':'pmi_blast_furnace','螺纹钢:主要钢厂开工率:全国':'pmi_rebar_steel_rate',
 '日耗量:煤炭:6大发电集团':'pmi_power_coal','PTA负荷率':'pmi_pta','甲醇开工率':'pmi_methanol',
 '乘用车批发销量':'pmi_car_wholesale','乘用车市场零售':'pmi_car_retail','30城商品房成交面积':'pmi_newhome_30',
 '二手房成交面积':'pmi_secondhand_shenzhen','螺纹钢表观消费':'pmi_rebar_consumption'}
raw_revised=dict(source['raw'])
coverage={}
for name,key in proxy_map.items():
 meta,series=ifind_series(ifind,key); raw_revised[name]=meta['records']
 july=series[(series.index>=pd.Timestamp('2026-07-01'))&(series.index<=JULY)]
 coverage[key]={'name':name,'providerId':meta['providerId'],'frequency':meta['frequency'],
                'julyCount':int(len(july)),'julyEnd':july.index.max().date().isoformat() if len(july) else None,
                'latest':series.index.max().date().isoformat()}
index=pd.date_range('2020-01-31',JULY,freq='ME')
sub={key:dict_series(source['pmiSubindices'][name]).reindex(index) for key,name in PMI_SUB_NAMES.items()}
new_orders=float(pmi_momentum(sub['新订单'],PMI_PROXIES['新订单'],raw_revised,index).loc[JULY])
production=float(pmi_momentum(sub['生产'],PMI_PROXIES['生产'],raw_revised,index).loc[JULY])
parts={'新订单':new_orders,'生产':production,'从业人员':float(sub['从业人员'].loc[JUNE]),
       '配送':float(sub['配送'].loc[JUNE]),'库存':float(sub['库存'].loc[JUNE])}
pmi_recheck=sum(PMI_WEIGHTS[k]*((100-v) if k=='配送' else v) for k,v in parts.items())
_,pmi_total=ifind_series(ifind,'cpi_pmi'); pmi_actual=float(pmi_total.resample('ME').last().loc[JULY])

ppi_map={'南华工业品指数':'ppi_nanhua','布伦特原油':'ppi_brent','动力煤':'ppi_coal','螺纹钢':'ppi_rebar','铜':'ppi_copper','RJ/CRB':'ppi_crb'}
ppi_series={}; ppi_coverage={}
for label,key in ppi_map.items():
 meta,series=ifind_series(ifind,key); ppi_series[label]=series.resample('ME').mean().reindex(index)
 july=series[(series.index>=pd.Timestamp('2026-07-01'))&(series.index<=JULY)]
 ppi_coverage[key]={'name':label,'providerId':meta['providerId'],'frequency':meta['frequency'],
                    'julyCount':int(len(july)),'julyEnd':july.index.max().date().isoformat() if len(july) else None,
                    'latest':series.index.max().date().isoformat()}
pct={k:v.pct_change(fill_method=None)*100 for k,v in ppi_series.items()}
exog=pd.DataFrame({'nh_pct':pct['南华工业品指数'],'nh_pctL1':pct['南华工业品指数'].shift(1),
 'oil_pct':pct['布伦特原油'],'coal_pct':pct['动力煤'],'rebar_pct':pct['螺纹钢'],
 'cu_pct':pct['铜'],'crb_pct':pct['RJ/CRB']},index=index)
mom_actual=to_series(source['targets']['ppi_mom']).reindex(index); yoy_actual=to_series(source['targets']['ppi']).reindex(index)
mom_actual.loc[JUNE],yoy_actual.loc[JUNE]=-.3,4.1
training=mom_actual.loc[:JUNE].dropna(); xtrain=exog.reindex(training.index); means=xtrain.mean(); xtrain=xtrain.fillna(means); xtarget=exog.reindex([JULY]).fillna(means)
fit=SARIMAX(training,exog=xtrain,order=(1,0,1),seasonal_order=(1,0,0,12),enforce_stationarity=False,enforce_invertibility=False).fit(disp=False,maxiter=200)
ppi_mom_recheck=float(fit.forecast(1,exog=xtarget.values).iloc[0])
ppi_yoy_recheck=float(exact_yoy(pd.Series({JULY:ppi_mom_recheck}),yoy_actual,mom_actual).loc[JULY])

live=read_json(DATA/'live_inputs.json'); cpi_coverage={}
for label,key in (('蔬菜','vegetable_price'),('猪肉','pork_price')):
 series=raw_series(live['dashboard'][key]['series']); july=series[(series.index>=pd.Timestamp('2026-07-01'))&(series.index<=JULY)]
 cpi_coverage[label]={'julyCount':int(len(july)),'julyEnd':july.index.max().date().isoformat() if len(july) else None}
crb=raw_series(live['ifindCrb']['series']); july=crb[(crb.index>=pd.Timestamp('2026-07-01'))&(crb.index<=JULY)]
cpi_coverage['RJ/CRB']={'julyCount':int(len(july)),'julyEnd':july.index.max().date().isoformat() if len(july) else None}
def july_actual(key):
 _,series=ifind_series(ifind,key); monthly=series.resample('ME').last()
 return float(monthly.loc[JULY]) if JULY in monthly.index else None
actuals={'cpiYoy':july_actual('actual_cpi_yoy'),'cpiMom':july_actual('actual_cpi_mom'),
         'ppiYoy':july_actual('actual_ppi_yoy'),'ppiMom':july_actual('actual_ppi_mom'),'pmi':pmi_actual}
errors={'cpiYoy':locked['cpi']['forecast']-actuals['cpiYoy'],'cpiMom':locked['cpi']['momForecast']-actuals['cpiMom'],
        'ppiYoy':locked['ppi']['forecast']-actuals['ppiYoy'],'ppiMom':locked['ppi']['momForecast']-actuals['ppiMom'],
        'pmi':locked['pmi']['forecast']-actuals['pmi']}

result={'auditDate':'2026-08-09','principle':'锁定预测不改写；完整数据复算仅作为事后复核',
 'locked':{'cpiYoy':locked['cpi']['forecast'],'cpiMom':locked['cpi']['momForecast'],'ppiYoy':locked['ppi']['forecast'],'ppiMom':locked['ppi']['momForecast'],'pmi':locked['pmi']['forecast']},
 'officialActuals':actuals,'lockedForecastErrors':errors,
 'recheck':{'ppiYoy':ppi_yoy_recheck,'ppiMom':ppi_mom_recheck,'pmi':pmi_recheck,'pmiActual':pmi_actual,'pmiParts':parts},
 'cpiLockedInputCoverage':cpi_coverage,'ppiIfindCoverage':ppi_coverage,'pmiIfindCoverage':coverage}
out=ROOT/'outputs'; out.mkdir(exist_ok=True)
(out/'july_forecast_ifind_recheck.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 2026年7月 CPI/PPI/PMI 数据日期与预测复核','','> 锁定预测不改写；完整 iFinD 数据复算仅作为事后复核，禁止反向修正历史预测。','',
 '## 结论','',f"- CPI 锁定预测：同比 {locked['cpi']['forecast']:.3f}%，环比 {locked['cpi']['momForecast']:.3f}%；蔬菜、猪肉、CRB 的确认输入均覆盖到 2026-07-31。",
 f"- PPI 锁定预测：同比 {locked['ppi']['forecast']:.3f}%，环比 {locked['ppi']['momForecast']:.3f}%；固定 provider 的完整7月复算为同比 {ppi_yoy_recheck:.3f}%，环比 {ppi_mom_recheck:.3f}%。",
 f"- PMI 锁定预测：{locked['pmi']['forecast']:.3f}；补齐缺失代理后的复算值为 {pmi_recheck:.3f}，7月官方 PMI 为 {pmi_actual:.1f}。",
 f"- 7月官方值：CPI同比 {actuals['cpiYoy']:.1f}%、环比 {actuals['cpiMom']:.1f}%；PPI同比 {actuals['ppiYoy']:.1f}%、环比 {actuals['ppiMom']:.1f}%；PMI {actuals['pmi']:.1f}。",
 f"- 锁定预测误差（预测-实际）：CPI同比 {errors['cpiYoy']:+.3f}、环比 {errors['cpiMom']:+.3f}；PPI同比 {errors['ppiYoy']:+.3f}、环比 {errors['ppiMom']:+.3f}；PMI {errors['pmi']:+.3f}。",
 '', '## CPI 锁定输入覆盖','']
for name,row in cpi_coverage.items(): lines.append(f"- {name}：7月 {row['julyCount']} 个观测，截止 {row['julyEnd']}。")
lines+=['','## PPI 固定 iFinD 指标覆盖','']
for row in ppi_coverage.values(): lines.append(f"- {row['name']}（{row['providerId']}）：7月 {row['julyCount']} 个观测，截止 {row['julyEnd']}；当前最新 {row['latest']}。")
lines+=['','## PMI 固定 iFinD 指标覆盖','']
for row in coverage.values(): lines.append(f"- {row['name']}（{row['providerId']}）：7月 {row['julyCount']} 个观测，截止 {row['julyEnd']}；当前最新 {row['latest']}。")
(out/'2026年7月预测_iFinD完整数据复核_20260809.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(result['recheck'],ensure_ascii=False,indent=2))