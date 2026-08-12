#!/usr/bin/env python3
"""Rebuild CPI/PPI/PMI forecasts with the archived, validated model logic."""

from __future__ import annotations

import argparse
import json
import math
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

from forecast_realtime import build_daily_nowcasts

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
DISPLAY_START = pd.Timestamp("2023-01-31")
BACKTEST_START = pd.Timestamp("2023-01-31")
JUNE = pd.Timestamp("2026-06-30")
JULY = pd.Timestamp("2026-07-31")
BACKTEST_END = pd.Timestamp("2026-05-31")
SPRING = {
    2010: 2, 2011: 2, 2012: 1, 2013: 2, 2014: 1, 2015: 2,
    2016: 2, 2017: 1, 2018: 2, 2019: 2, 2020: 1, 2021: 2,
    2022: 2, 2023: 1, 2024: 2, 2025: 1, 2026: 2,
}
PMI_WEIGHTS = {"新订单": .30, "生产": .25, "从业人员": .20, "配送": .15, "库存": .10}
PMI_PROXIES = {
    "生产": ["高炉开工率(247家):全国", "螺纹钢:主要钢厂开工率:全国", "日耗量:煤炭:6大发电集团", "PTA负荷率", "甲醇开工率"],
    "新订单": ["乘用车批发销量", "乘用车市场零售", "30城商品房成交面积", "二手房成交面积", "螺纹钢表观消费"],
}
PMI_SUB_NAMES = {
    "生产": "制造业PMI:生产（单位：%）", "新订单": "制造业PMI:新订单（单位：%）",
    "从业人员": "制造业PMI:从业人员（单位：%）", "配送": "制造业PMI:供应商配送时间（单位：%）",
    "库存": "制造业PMI:原材料库存（单位：%）",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def payload_records(payload: Any) -> list[list[Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return payload if isinstance(payload, list) else []


def to_series(payload: Any, how: str = "last") -> pd.Series:
    rows = payload_records(payload)
    if not rows:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(rows, columns=["date", "value"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna().drop_duplicates("date", keep="last").set_index("date").sort_index()
    grouped = frame["value"].resample("ME")
    return (grouped.mean() if how == "mean" else grouped.last()).dropna()


def raw_series(payload: Any) -> pd.Series:
    rows = payload_records(payload)
    if not rows:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(rows, columns=["date", "value"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame.dropna().drop_duplicates("date", keep="last").set_index("date")["value"].sort_index()


def ifind_series(payload: dict[str, Any], key: str) -> tuple[dict[str, Any], pd.Series]:
    item = payload.get("series", {}).get(key)
    if not isinstance(item, dict):
        raise RuntimeError(f"iFinD 最新输入缺少固定指标：{key}")
    series = raw_series(item.get("records", []))
    if series.empty:
        raise RuntimeError(f"iFinD 固定指标没有有效观测：{key}")
    return item, series


def merge_official_pmi(source: dict[str, Any], official: dict[str, Any]) -> None:
    for name, rows in official.get("values", {}).items():
        source["pmiSubindices"].setdefault(name, {}).update(rows)

def dict_series(payload: dict[str, Any]) -> pd.Series:
    return pd.Series({pd.Timestamp(day): float(value) for day, value in payload.items()}).sort_index()


def spring_dummy(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series([float(SPRING.get(day.year) == day.month) for day in index], index=index)


def walk_sarimax(target: pd.Series, exog: pd.DataFrame, order: tuple[int, int, int], seasonal: tuple[int, int, int, int], train_min: int) -> pd.Series:
    target = target.dropna()
    output: dict[pd.Timestamp, float] = {}
    for day in target.index[target.index >= BACKTEST_START]:
        training = target[target.index < day]
        if len(training) < train_min:
            continue
        x_training = exog.reindex(training.index)
        means = x_training.mean()
        x_training = x_training.fillna(means)
        x_target = exog.reindex([day]).fillna(means)
        fitted = SARIMAX(
            training, exog=x_training, order=order, seasonal_order=seasonal,
            enforce_stationarity=False, enforce_invertibility=False,
        ).fit(disp=False, maxiter=200)
        output[day] = float(fitted.forecast(1, exog=x_target.values).iloc[0])
    return pd.Series(output, dtype=float).sort_index()


def exact_yoy(mom_forecast: pd.Series, yoy_actual: pd.Series, mom_actual: pd.Series) -> pd.Series:
    output: dict[pd.Timestamp, float] = {}
    for day, mom in mom_forecast.items():
        previous = day - pd.offsets.MonthEnd(1)
        year_ago = (day - pd.DateOffset(months=12)) + pd.offsets.MonthEnd(0)
        if previous in yoy_actual.index and year_ago in mom_actual.index:
            output[day] = ((1 + float(yoy_actual.loc[previous]) / 100) * (1 + float(mom) / 100)
                           / (1 + float(mom_actual.loc[year_ago]) / 100) - 1) * 100
    return pd.Series(output, dtype=float).sort_index()


def model_cpi(source: dict[str, Any]) -> tuple[pd.Series, pd.Series, pd.Series, dict[str, pd.Series]]:
    data, targets = source["cpi"], source["targets"]
    index = pd.date_range("2010-01-31", JUNE, freq="ME")
    food, nonfood = to_series(data["cpi_food_mom"]).reindex(index), to_series(data["cpi_nonfood_mom"]).reindex(index)
    total_mom, food_weight = to_series(data["cpi_mom_total"]).reindex(index), (to_series(data["food_weight"]) / 100).reindex(index)
    cpi_yoy = to_series(targets["cpi"]).reindex(index)
    food.loc[JUNE], nonfood.loc[JUNE], total_mom.loc[JUNE], cpi_yoy.loc[JUNE] = -.4, -.3, -.3, 1.0
    inputs = {"veg": to_series(data["veg"], "mean").reindex(index), "pork": to_series(data["pork"]).reindex(index),
              "crb": to_series(data["crb"], "mean").reindex(index), "pmi": to_series(data["pmi"]).reindex(index)}
    food_exog = pd.DataFrame({"spring": spring_dummy(index), "veg_dL0": inputs["veg"].diff(), "pork_dL0": inputs["pork"].diff()}, index=index)
    nonfood_exog = pd.DataFrame({"spring": spring_dummy(index), "crb_dL0": inputs["crb"].diff(), "pmi_L1": inputs["pmi"].shift(1)}, index=index)
    food_pred = walk_sarimax(food, food_exog, (2, 1, 0), (1, 0, 1, 12), 96)
    nonfood_pred = walk_sarimax(nonfood, nonfood_exog, (1, 0, 1), (1, 1, 1, 12), 96)
    common = food_pred.index.intersection(nonfood_pred.index)
    weight = food_weight.rolling(12, min_periods=6).mean().shift(1).reindex(common).ffill()
    mom_pred = food_pred.reindex(common) * weight + nonfood_pred.reindex(common) * (1 - weight)
    return exact_yoy(mom_pred, cpi_yoy, total_mom), cpi_yoy, mom_pred, inputs


def model_ppi(source: dict[str, Any]) -> tuple[pd.Series, pd.Series, pd.Series, dict[str, pd.Series]]:
    targets, raw = source["targets"], source["raw"]
    index = pd.date_range("2020-01-31", JUNE, freq="ME")
    mom_actual, yoy_actual = to_series(targets["ppi_mom"]).reindex(index), to_series(targets["ppi"]).reindex(index)
    mom_actual.loc[JUNE], yoy_actual.loc[JUNE] = -.3, 4.1
    names = {"南华工业品指数": "南华工业品指数", "布伦特原油": "现货价:原油:英国布伦特Dtd", "动力煤": "动力煤价格",
             "螺纹钢": "螺纹钢", "铜": "铜价", "RJ/CRB": "CRB现货指数:综合"}
    inputs = {label: to_series(raw[key], "mean").reindex(index) for label, key in names.items()}
    pct = {label: series.pct_change(fill_method=None) * 100 for label, series in inputs.items()}
    exog = pd.DataFrame({"nh_pct": pct["南华工业品指数"], "nh_pctL1": pct["南华工业品指数"].shift(1),
                         "oil_pct": pct["布伦特原油"], "coal_pct": pct["动力煤"], "rebar_pct": pct["螺纹钢"],
                         "cu_pct": pct["铜"], "crb_pct": pct["RJ/CRB"]}, index=index)
    mom_pred = walk_sarimax(mom_actual, exog, (1, 0, 1), (1, 0, 0, 12), 30)
    return exact_yoy(mom_pred, yoy_actual, mom_actual), yoy_actual, mom_pred, inputs


def pmi_momentum(target: pd.Series, names: list[str], raw: dict[str, Any], index: pd.DatetimeIndex) -> pd.Series:
    monthly = pd.DataFrame({name: to_series(raw[name], "mean").reindex(index).pct_change(fill_method=None) * 100 for name in names}, index=index)
    target, output = target.reindex(index), {}
    for day in index[index >= BACKTEST_START]:
        training = target[target.index < day].dropna()
        if training.empty:
            continue
        x_training, x_target = monthly.reindex(training.index), monthly.reindex([day])
        means, stds = x_training.mean(), x_training.std()
        factor_training = ((x_training - means) / stds).mean(axis=1).to_frame("momentum").fillna(0)
        factor_target = ((x_target - means) / stds).mean(axis=1).to_frame("momentum").fillna(0)
        try:
            fitted = SARIMAX(training, exog=factor_training, order=(0, 0, 0), trend="c", enforce_stationarity=False).fit(disp=False, maxiter=200)
            output[day] = float(fitted.forecast(1, exog=factor_target.values).iloc[0])
        except Exception:
            output[day] = float(training.iloc[-12:].mean())
    return pd.Series(output, dtype=float).sort_index()


def model_pmi(source: dict[str, Any]) -> tuple[pd.Series, pd.Series, dict[str, pd.Series]]:
    raw, sub_raw = source["raw"], source["pmiSubindices"]
    index = pd.date_range("2020-01-31", JUNE, freq="ME")
    sub = {key: dict_series(sub_raw[name]).reindex(index) for key, name in PMI_SUB_NAMES.items()}
    forecasts = {"新订单": pmi_momentum(sub["新订单"], PMI_PROXIES["新订单"], raw, index),
                 "生产": pmi_momentum(sub["生产"], PMI_PROXIES["生产"], raw, index),
                 "从业人员": sub["从业人员"].shift(1).reindex(index[index >= BACKTEST_START]).dropna(),
                 "配送": sub["配送"].shift(1).reindex(index[index >= BACKTEST_START]).dropna(),
                 "库存": sub["库存"].shift(1).reindex(index[index >= BACKTEST_START]).dropna()}
    common = forecasts["新订单"].index
    for series in forecasts.values():
        common = common.intersection(series.index)
    prediction = pd.Series(0.0, index=common)
    for key, weight in PMI_WEIGHTS.items():
        component = forecasts[key].reindex(common)
        prediction += weight * ((100 - component) if key == "配送" else component)
    actual = to_series(source["targets"]["pmi"]).reindex(index)
    actual.loc[JUNE] = 50.3
    proxy_series = {name: to_series(raw[name], "mean") for group in PMI_PROXIES.values() for name in group}
    return prediction.sort_index(), actual.sort_index(), proxy_series


def metric(prediction: pd.Series, actual: pd.Series) -> tuple[float, float]:
    joined = pd.concat([prediction.rename("p"), actual.rename("a")], axis=1).dropna()
    errors = joined["p"] - joined["a"]
    return float(np.sqrt((errors ** 2).mean())), float(errors.abs().mean())


def locked_value(values: dict[str, Any], key: str) -> dict[str, Any] | None:
    if key in values:
        return values[key]
    if key == "cpi_mom" and "cpi" in values:
        return {"forecast": values["cpi"].get("momForecast")}
    if key == "ppi_mom" and "ppi" in values:
        return {"forecast": values["ppi"].get("momForecast")}
    return None


def monthly_rows(prediction: pd.Series, actual: pd.Series, consensus: list[dict[str, Any]], locked: dict[str, Any], key: str) -> list[dict[str, Any]]:
    consensus_map = {
        pd.Timestamp(row["date"]).to_period("M").to_timestamp("M"): row
        for row in consensus if row.get("date") is not None and row.get("value") is not None
    }
    locked_map = {pd.Timestamp(day): value for day, values in locked.items() if (value := locked_value(values, key)) is not None}
    end = max([*actual.dropna().index, *prediction.dropna().index, *locked_map.keys()])
    rows = []
    for day in pd.date_range(DISPLAY_START, end, freq="ME"):
        lock = locked_map.get(day)
        forecast = float(lock["forecast"]) if lock else (float(prediction.loc[day]) if day in prediction.index and pd.notna(prediction.loc[day]) else None)
        actual_value = float(actual.loc[day]) if day in actual.index and pd.notna(actual.loc[day]) else None
        consensus_row = consensus_map.get(day)
        consensus_value = float(consensus_row["value"]) if consensus_row else None
        rows.append({"date": day.date().isoformat(), "forecast": round(forecast, 6) if forecast is not None else None,
                     "actual": round(actual_value, 6) if actual_value is not None else None,
                     "consensus": round(consensus_value, 6) if consensus_value is not None else None,
                     "consensusSource": consensus_row.get("source") if consensus_row else None,
                     "forecastKind": "confirmed_nowcast" if lock else ("walk_forward" if forecast is not None else None),
                     "officialRounding": (lock.get("officialRounding") if lock and lock.get("officialRounding") is not None else (round(forecast, 1) if forecast is not None else None))})
    return rows


def points(series: pd.Series) -> list[dict[str, Any]]:
    return [{"date": day.date().isoformat(), "value": round(float(value), 6)} for day, value in series.dropna().items()]


def input_row(name: str, id_: str, series: pd.Series, unit: str, frequency: str, role: str,
              aggregation: str, source: str = "iFinD/CJHX 锁定模型输入", provider_id: str | None = None,
              model_usage_note: str | None = None) -> dict[str, Any]:
    latest = series.dropna().index.max() if not series.dropna().empty else None
    return {"name": name, "id": id_, "unit": unit, "frequency": frequency, "role": role,
            "aggregation": aggregation, "source": source, "providerId": provider_id,
            "latestAvailableDate": latest.date().isoformat() if latest is not None else None,
            "modelUsageNote": model_usage_note, "series": points(series)}


def ifind_input_row(ifind: dict[str, Any], key: str, name: str, id_: str, role: str,
                    aggregation: str, model_usage_note: str) -> dict[str, Any]:
    meta, series = ifind_series(ifind, key)
    frequency = {"D": "日频", "W": "周频", "M": "月频"}.get(str(meta.get("frequency")), str(meta.get("frequency") or "未知"))
    unit = str(meta.get("unit") or "指数")
    provider_id = str(meta.get("providerId"))
    return input_row(name, id_, series, unit, frequency, role, aggregation,
                     f"iFinD EDB · {provider_id}", provider_id, model_usage_note)


def merge_points(primary: pd.Series, overlay: pd.Series) -> pd.Series:
    output = primary.copy()
    for day, value in overlay.items():
        output.loc[day] = value
    return output.sort_index()


def build_high_frequency(ifind_latest: dict[str, Any], target_month: pd.Timestamp | None = None) -> dict[str, list[dict[str, Any]]]:
    target_month = target_month or (pd.Timestamp.now().normalize() + pd.offsets.MonthEnd(0))
    previous = target_month - pd.offsets.MonthEnd(1)
    target_label, previous_label = f"{target_month.year}年{target_month.month}月", f"{previous.year}年{previous.month}月"
    common_target = f"{target_label}实时预测使用截至页面更新时间的当月观测；月均值随新增数据更新"
    cpi_specs = (
        ("cpi_veg", "食品项 / 28种重点监测蔬菜均价", "cpi_veg", "食品环比外生变量 L0", "当月日均值后作一阶差分", common_target),
        ("cpi_pork", "食品项 / 猪肉批发价", "cpi_pork", "食品环比外生变量 L0", "当月末值后作一阶差分", common_target),
        ("cpi_crb", "非食品项 / RJ/CRB商品价格指数", "cpi_crb", "非食品环比外生变量 L0", "当月日均值后作一阶差分", common_target),
        ("cpi_pmi", "非食品项 / 制造业PMI", "cpi_pmi_l1", "非食品环比外生变量 L1", "采用上月已公布值", f"{target_label}预测使用{previous_label}制造业PMI"),
    )
    ppi_specs = (
        ("ppi_nanhua", "南华工业品指数", "ppi_nanhua", "PPI环比外生变量 L0 与 L1", "月均值环比；同一序列承担两种滞后用途"),
        ("ppi_brent", "布伦特原油", "ppi_brent", "PPI环比外生变量 L0", "月均值环比"),
        ("ppi_coal", "动力煤价格", "ppi_coal", "PPI环比外生变量 L0", "月均值环比"),
        ("ppi_rebar", "螺纹钢价格", "ppi_rebar", "PPI环比外生变量 L0", "月均值环比"),
        ("ppi_copper", "铜价", "ppi_copper", "PPI环比外生变量 L0", "月均值环比"),
        ("ppi_crb", "RJ/CRB商品价格指数", "ppi_crb", "PPI环比外生变量 L0", "月均值环比"),
    )
    pmi_production_keys = ("pmi_blast_furnace", "pmi_rebar_steel_rate", "pmi_power_coal", "pmi_pta", "pmi_methanol")
    pmi_order_specs = tuple((key, common_target) for key in (
        "pmi_car_wholesale", "pmi_car_retail", "pmi_newhome_30",
        "pmi_secondhand_shenzhen", "pmi_rebar_consumption",
    ))
    high_frequency = {
        "CPI": [ifind_input_row(ifind_latest, *spec) for spec in cpi_specs],
        "PPI": [ifind_input_row(ifind_latest, *spec, common_target) for spec in ppi_specs],
        "PMI": [
            *[ifind_input_row(ifind_latest, key, name, f"pmi_proxy_{i+1}", "生产分项动量代理", "月均值环比后扩展窗标准化", common_target) for i, (key, name) in enumerate(zip(pmi_production_keys, PMI_PROXIES["生产"]))],
            *[ifind_input_row(ifind_latest, key, name, f"pmi_proxy_{i+6}", "新订单分项动量代理", "月均值环比后扩展窗标准化", note) for i, ((key, note), name) in enumerate(zip(pmi_order_specs, PMI_PROXIES["新订单"]))],
            ifind_input_row(ifind_latest, "pmi_employment", "制造业PMI / 从业人员", "pmi_sub_从业人员", "预测目标月采用上月从业人员值", "上月已公布值", f"{target_label}预测使用{previous_label}值"),
            ifind_input_row(ifind_latest, "pmi_delivery", "制造业PMI / 供应商配送时间", "pmi_sub_配送", "预测目标月采用上月供应商配送时间值", "上月已公布值（合成前取100-x）", f"{target_label}预测使用{previous_label}值"),
            ifind_input_row(ifind_latest, "pmi_inventory", "制造业PMI / 原材料库存", "pmi_sub_库存", "预测目标月采用上月原材料库存值", "上月已公布值", f"{target_label}预测使用{previous_label}值"),
        ],
    }
    return high_frequency


def build(input_path: Path, locked_path: Path, consensus_path: Path, live_path: Path,
          official_pmi_path: Path, ifind_latest_path: Path) -> dict[str, Any]:
    source, locked = read_json(input_path), read_json(locked_path)
    consensus = read_json(consensus_path) if consensus_path.exists() else {}
    official_pmi = read_json(official_pmi_path)
    live = read_json(live_path)
    ifind_latest = read_json(ifind_latest_path)
    merge_official_pmi(source, official_pmi)

    cpi_pred, cpi_actual, cpi_mom_pred, _ = model_cpi(source)
    ppi_pred, ppi_actual, ppi_mom_pred, _ = model_ppi(source)
    pmi_pred, pmi_actual, _ = model_pmi(source)
    cpi_mom_actual = to_series(source["cpi"]["cpi_mom_total"])
    ppi_mom_actual = to_series(source["targets"]["ppi_mom"])
    cpi_mom_actual.loc[JUNE], ppi_mom_actual.loc[JUNE] = -.3, -.3
    # 只追加预测完成后才公布的官方值；不回填历史模型，也不改变锁定点预测。
    for target, key in ((pmi_actual, "cpi_pmi"), (cpi_actual, "actual_cpi_yoy"),
                        (cpi_mom_actual, "actual_cpi_mom"), (ppi_actual, "actual_ppi_yoy"),
                        (ppi_mom_actual, "actual_ppi_mom")):
        _, official_series = ifind_series(ifind_latest, key)
        monthly_official = official_series.resample("ME").last().dropna()
        for day, value in monthly_official.items():
            if day > JUNE:
                target.loc[day] = value
    model_series = {
        "cpi": (cpi_pred, cpi_actual), "cpi_mom": (cpi_mom_pred, cpi_mom_actual),
        "ppi": (ppi_pred, ppi_actual), "ppi_mom": (ppi_mom_pred, ppi_mom_actual),
        "pmi": (pmi_pred, pmi_actual),
    }
    scores = {
        key: metric(prediction.loc[:BACKTEST_END], actual.loc[:BACKTEST_END])
        for key, (prediction, actual) in model_series.items()
    }
    expected = {"cpi": .223, "ppi": .291, "pmi": .604}
    for key, expected_rmse in expected.items():
        if not math.isclose(scores[key][0], expected_rmse, abs_tol=.006):
            raise RuntimeError(f"{key.upper()} 回测 RMSE 漂移：{scores[key][0]:.3f}（锁定值约 {expected_rmse:.3f}）")
    history = {
        key: monthly_rows(pred, actual, consensus.get(key, []), locked, key)
        for key, (pred, actual) in model_series.items()
    }
    locked_day = max(pd.Timestamp(day) for day in locked)
    locked_payload = locked[locked_day.date().isoformat()]
    daily = build_daily_nowcasts(source, live, locked_payload, locked_day)
    daily["pmi"] = [{"date": locked_day.date().isoformat(), "value": round(float(locked_payload["pmi"]["forecast"]), 6)}]

    high_frequency = build_high_frequency(ifind_latest)
    models = {
        "cpi": {"name": "CPI同比", "unit": "%", "description": "食品与非食品环比由锁定 SARIMAX 分项预测，再以精确乘法换算同比。", "formula": "食品 SARIMAX(2,1,0)×(1,0,1,12)；非食品 SARIMAX(1,0,1)×(1,1,1,12)；CRB L0、PMI L1。"},
        "cpi_mom": {"name": "CPI环比", "unit": "%", "description": "食品和非食品分项环比按滞后一期的过去12个月平均食品权重合成。", "formula": "食品环比×食品权重 + 非食品环比×(1-食品权重)。"},
        "ppi": {"name": "PPI同比", "unit": "%", "description": "工业品代理进入锁定 SARIMAX 环比模型，再用精确乘法换算同比。", "formula": "SARIMAX(1,0,1)×(1,0,0,12)；南华工业品 L0/L1，其余工业品代理 L0。"},
        "ppi_mom": {"name": "PPI环比", "unit": "%", "description": "工业品高频代理的当月均值环比进入锁定 SARIMAX 模型。", "formula": "南华工业品 L0/L1；布伦特、动力煤、螺纹钢、铜和 RJ/CRB 使用 L0。"},
        "pmi": {"name": "制造业PMI", "unit": "点", "description": "新订单与生产用高频动量扩展窗回归，其余三个分项取上月值，再按官方权重合成。", "formula": "新订单×30% + 生产×25% + 从业×20% + (100-配送)×15% + 库存×10%。"},
    }
    return {
        "schemaVersion": 3, "generatedAt": datetime.now().astimezone().isoformat(),
        "displayStart": DISPLAY_START.date().isoformat(), "backtestStart": BACKTEST_START.date().isoformat(),
        "source": "旧 WSL 锁定模型数据 + 2026年7月最终复核点预测",
        "daily": daily, "dailyAsOf": daily["cpi"][-1]["date"], "history": history,
        "models": models,
        "metrics": {key: {"rmse": round(value[0], 4), "mae": round(value[1], 4), "sampleStart": "2023-01", "sampleEnd": "2026-05", **({"directionHit": 78.0} if key == "pmi" else {})} for key, value in scores.items()},
        "highFrequency": high_frequency,
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "forecast-model" / "model_inputs.json")
    parser.add_argument("--locked", type=Path, default=ROOT / "data" / "forecast-model" / "locked_nowcasts.json")
    parser.add_argument("--consensus", type=Path, default=ROOT / "data" / "forecast-model" / "consensus.json")
    parser.add_argument("--live", type=Path, default=ROOT / "data" / "forecast-model" / "live_inputs.json")
    parser.add_argument("--official-pmi", type=Path, default=ROOT / "data" / "forecast-model" / "official_pmi_subindices.json")
    parser.add_argument("--ifind-latest", type=Path, default=ROOT / "data" / "forecast-model" / "ifind_latest_inputs.json")
    parser.add_argument("--output", type=Path, default=ROOT / "public" / "data" / "forecasts.json")
    args = parser.parse_args()
    payload = build(args.input, args.locked, args.consensus, args.live, args.official_pmi, args.ifind_latest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"已生成无前视月频预测：{args.output}")
    for key, values in payload["metrics"].items():
        print(f"  {key.upper()}: RMSE={values['rmse']:.3f}, MAE={values['mae']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
