#!/usr/bin/env python3
"""Real-time China export/import nowcasts using an approximate monthly DFM ensemble."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TRADE_DISPLAY_START = pd.Timestamp("2023-01-31")
TRADE_BACKTEST_START = pd.Timestamp("2024-07-31")
MAX_FEATURES = 8
MIN_FACTOR_TRAIN = 12

INDICATORS: dict[str, dict[str, str]] = {
    "scfi": {"name": "SCFI", "family": "集装箱出口运价", "role": "出口集装箱景气代理"},
    "ccfi": {"name": "CCFI", "family": "集装箱出口运价", "role": "出口集装箱景气代理"},
    "port_container": {"name": "港口集装箱吞吐量", "family": "港口数量", "role": "进出口实物流量代理"},
    "bdi": {"name": "BDI", "family": "干散货运价", "role": "大宗商品进口与全球需求代理"},
    "usdcny": {"name": "USD/CNY", "family": "人民币汇率", "role": "价格折算与竞争力代理"},
    "cfets": {"name": "CFETS人民币汇率指数", "family": "人民币汇率", "role": "实际贸易条件代理"},
    "dxy": {"name": "美元指数", "family": "全球金融条件", "role": "美元计价与外需环境代理"},
    "brent": {"name": "布伦特原油", "family": "进口商品价格", "role": "能源进口价格代理"},
    "copper_price": {"name": "铜价", "family": "进口商品价格", "role": "工业需求与进口价格代理"},
}

POOLS = {
    "exports": ("scfi", "ccfi", "port_container", "usdcny", "cfets", "dxy", "bdi"),
    "imports": ("bdi", "port_container", "brent", "copper_price", "usdcny", "cfets", "dxy"),
}


@dataclass
class FitResult:
    bridge: float | None
    ar: float
    selected: list[str]
    factor_count: int


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_targets(path: Path) -> dict[str, pd.Series]:
    frame = pd.read_csv(path)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce") + pd.offsets.MonthEnd(0)
    frame = frame.dropna(subset=["date"]).set_index("date").sort_index()
    return {
        key.removesuffix("_yoy"): pd.to_numeric(frame[key], errors="coerce").dropna()
        for key in ("exports_yoy", "imports_yoy")
    }


def dashboard_series(dashboard: dict[str, Any], indicator_id: str, as_of: pd.Timestamp | None = None) -> pd.Series:
    item = next((row for row in dashboard.get("indicators", []) if row.get("id") == indicator_id), None)
    if not item:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(item.get("series", []))
    if frame.empty or not {"date", "value"}.issubset(frame.columns):
        return pd.Series(dtype=float)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    series = frame.dropna().drop_duplicates("date", keep="last").set_index("date")["value"].sort_index()
    return series.loc[:as_of] if as_of is not None else series


def build_features(dashboard: dict[str, Any], pool: str, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Month-average high-frequency data, converted to stationary 1m/3m momentum."""
    output: dict[str, pd.Series] = {}
    for indicator_id in POOLS[pool]:
        raw = dashboard_series(dashboard, indicator_id, as_of)
        if raw.empty:
            continue
        monthly = raw.resample("ME").mean().where(lambda values: values > 0)
        logged = np.log(monthly)
        output[f"{indicator_id}_m1"] = logged.diff() * 100
        output[f"{indicator_id}_m3"] = logged.diff(3) / 3 * 100
    return pd.DataFrame(output).replace([np.inf, -np.inf], np.nan).sort_index()


def _ridge(design: np.ndarray, target: np.ndarray, alpha: float = 2.0) -> np.ndarray:
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    return np.linalg.pinv(design.T @ design + penalty) @ design.T @ target


def _ar_prediction(target: pd.Series, lag_value: float) -> float:
    recent = target.dropna().iloc[-60:]
    pairs = pd.concat([recent.rename("y"), recent.shift(1).rename("lag")], axis=1).dropna()
    if len(pairs) < 8:
        return float(recent.iloc[-1])
    design = np.column_stack([np.ones(len(pairs)), pairs["lag"].to_numpy()])
    beta = _ridge(design, pairs["y"].to_numpy(), alpha=1.0)
    return float(np.array([1.0, lag_value]) @ beta)


def _select_features(target: pd.Series, features: pd.DataFrame) -> list[str]:
    scored: list[tuple[float, str]] = []
    for column in features:
        joined = pd.concat([target.rename("y"), features[column].rename("x")], axis=1).dropna()
        if len(joined) < MIN_FACTOR_TRAIN or joined["x"].std() <= 1e-12:
            continue
        correlation = joined["y"].corr(joined["x"])
        if pd.notna(correlation):
            scored.append((abs(float(correlation)), column))
    selected, used_base = [], set()
    for _, column in sorted(scored, reverse=True):
        base = column.rsplit("_", 1)[0]
        if base in used_base:
            continue
        selected.append(column)
        used_base.add(base)
        if len(selected) >= MAX_FEATURES:
            break
    return selected


def _fit_at(target: pd.Series, features: pd.DataFrame, day: pd.Timestamp, lag_value: float) -> FitResult:
    training_target = target.loc[target.index < day].dropna()
    ar = _ar_prediction(training_target, lag_value)
    training_features = features.loc[features.index < day]
    selected = _select_features(training_target, training_features)
    if len(selected) < 2:
        return FitResult(None, ar, selected, 0)

    x_train = training_features[selected].reindex(training_target.index)
    usable = x_train.notna().sum(axis=1) >= max(2, len(selected) // 2)
    x_train, y_train = x_train.loc[usable], training_target.loc[usable]
    if len(y_train) < MIN_FACTOR_TRAIN:
        return FitResult(None, ar, selected, 0)
    means = x_train.mean()
    stds = x_train.std().replace(0, np.nan)
    z_train = ((x_train.fillna(means) - means) / stds).fillna(0.0)
    _, singular, rotation_t = np.linalg.svd(z_train.to_numpy(), full_matrices=False)
    explained = singular ** 2
    explained = explained / explained.sum() if explained.sum() else explained
    factor_count = 2 if len(explained) > 1 and explained[0] < .70 and len(y_train) >= 20 else 1
    factor_count = min(factor_count, rotation_t.shape[0])
    loadings = rotation_t[:factor_count].T

    z_all = ((features[selected].fillna(means) - means) / stds).fillna(0.0)
    factors = pd.DataFrame(z_all.to_numpy() @ loadings, index=z_all.index)
    regressors = pd.concat([
        training_target.shift(1).rename("target_l1"),
        factors.add_prefix("factor_").reindex(training_target.index),
        factors.shift(1).add_prefix("factor_l1_").reindex(training_target.index),
    ], axis=1).dropna()
    y_reg = training_target.reindex(regressors.index)
    if len(y_reg) < MIN_FACTOR_TRAIN:
        return FitResult(None, ar, selected, factor_count)
    design = np.column_stack([np.ones(len(regressors)), regressors.to_numpy()])
    beta = _ridge(design, y_reg.to_numpy(), alpha=2.0)
    factor_now = factors.reindex([day]).fillna(0.0).iloc[0].to_numpy()
    previous_day = day - pd.offsets.MonthEnd(1)
    factor_lag = factors.reindex([previous_day]).fillna(0.0).iloc[0].to_numpy()
    bridge = float(np.r_[1.0, lag_value, factor_now, factor_lag] @ beta)
    return FitResult(bridge, ar, selected, factor_count)


def forecast_trade(target: pd.Series, features: pd.DataFrame,
                   backtest_start: pd.Timestamp = TRADE_BACKTEST_START) -> dict[str, Any]:
    if features.empty:
        raise RuntimeError("贸易模型没有可用高频特征")
    target = target.copy().sort_index()
    end = features.dropna(how="all").index.max()
    start = max(backtest_start, features.dropna(how="all").index.min() + pd.offsets.MonthEnd(MIN_FACTOR_TRAIN))
    state = target.copy()
    predictions, ar_predictions = {}, {}
    bridge_errors: list[float] = []
    ar_errors: list[float] = []
    latest_fit: FitResult | None = None
    latest_weight = 0.0
    for day in pd.date_range(start, end, freq="ME"):
        previous = day - pd.offsets.MonthEnd(1)
        if previous not in state.index or pd.isna(state.loc[previous]):
            available = state.loc[state.index < day].dropna()
            if available.empty:
                continue
            lag_value = float(available.iloc[-1])
        else:
            lag_value = float(state.loc[previous])
        latest_fit = _fit_at(target, features.loc[:day], day, lag_value)
        if latest_fit.bridge is None:
            bridge_weight = 0.0
        elif len(bridge_errors) >= 6 and len(ar_errors) >= 6:
            bridge_rmse = max(float(np.sqrt(np.mean(np.square(bridge_errors[-12:])))), .05)
            ar_rmse = max(float(np.sqrt(np.mean(np.square(ar_errors[-12:])))), .05)
            bridge_weight = float(np.clip((1 / bridge_rmse) / (1 / bridge_rmse + 1 / ar_rmse), .2, .8))
        else:
            bridge_weight = .5
        latest_weight = bridge_weight
        prediction = latest_fit.ar if latest_fit.bridge is None else (
            bridge_weight * latest_fit.bridge + (1 - bridge_weight) * latest_fit.ar
        )
        predictions[day] = prediction
        ar_predictions[day] = latest_fit.ar
        if day in target.index and pd.notna(target.loc[day]):
            actual = float(target.loc[day])
            if latest_fit.bridge is not None:
                bridge_errors.append(latest_fit.bridge - actual)
            ar_errors.append(latest_fit.ar - actual)
            state.loc[day] = actual
        else:
            state.loc[day] = prediction
    prediction_series = pd.Series(predictions, dtype=float).sort_index()
    ar_series = pd.Series(ar_predictions, dtype=float).sort_index()
    joined = pd.concat([prediction_series.rename("p"), target.rename("a"), ar_series.rename("ar")], axis=1, sort=False).dropna()
    errors = joined["p"] - joined["a"]
    ar_errors_series = joined["ar"] - joined["a"]
    metrics = {
        "rmse": float(np.sqrt(np.mean(errors ** 2))) if len(joined) else float("nan"),
        "mae": float(np.mean(abs(errors))) if len(joined) else float("nan"),
        "benchmarkRmse": float(np.sqrt(np.mean(ar_errors_series ** 2))) if len(joined) else float("nan"),
        "directionHit": float(np.mean(np.sign(joined["p"]) == np.sign(joined["a"])) * 100) if len(joined) else float("nan"),
        "sampleStart": joined.index.min().strftime("%Y-%m") if len(joined) else None,
        "sampleEnd": joined.index.max().strftime("%Y-%m") if len(joined) else None,
        "observations": int(len(joined)),
    }
    return {
        "prediction": prediction_series,
        "arPrediction": ar_series,
        "metrics": metrics,
        "selected": latest_fit.selected if latest_fit else [],
        "factorCount": latest_fit.factor_count if latest_fit else 0,
        "bridgeWeight": latest_weight,
    }


def _history_rows(result: dict[str, Any], actual: pd.Series) -> list[dict[str, Any]]:
    prediction: pd.Series = result["prediction"]
    start, end = TRADE_DISPLAY_START, max(prediction.index.max(), actual.index.max())
    rows = []
    for day in pd.date_range(start, end, freq="ME"):
        forecast = float(prediction.loc[day]) if day in prediction.index else None
        actual_value = float(actual.loc[day]) if day in actual.index and pd.notna(actual.loc[day]) else None
        rows.append({
            "date": day.date().isoformat(), "forecast": round(forecast, 6) if forecast is not None else None,
            "actual": round(actual_value, 6) if actual_value is not None else None,
            "consensus": None, "consensusSource": None,
            "forecastKind": ("walk_forward" if actual_value is not None else "live_nowcast") if forecast is not None else None,
            "officialRounding": round(forecast, 1) if forecast is not None else None,
        })
    return rows


def _daily_path(dashboard: dict[str, Any], target: pd.Series, pool: str) -> list[dict[str, Any]]:
    raw = [dashboard_series(dashboard, key) for key in POOLS[pool]]
    latest = max((series.index.max() for series in raw if not series.empty), default=None)
    if latest is None:
        return []
    month_start = latest.to_period("M").to_timestamp()
    month_end = latest + pd.offsets.MonthEnd(0)
    observation_days = sorted({day for series in raw for day in series.loc[month_start:latest].index})
    full_features = build_features(dashboard, pool)
    full_result = forecast_trade(target, full_features)
    previous = month_end - pd.offsets.MonthEnd(1)
    if previous in target.index and pd.notna(target.loc[previous]):
        lag_value = float(target.loc[previous])
    else:
        lag_value = float(full_result["prediction"].loc[previous])
    weight = float(full_result["bridgeWeight"])
    points = []
    for day in observation_days:
        fit = _fit_at(target, build_features(dashboard, pool, day), month_end, lag_value)
        value = fit.ar if fit.bridge is None else weight * fit.bridge + (1 - weight) * fit.ar
        points.append({"date": day.date().isoformat(), "value": round(float(value), 6)})
    return points

def _input_rows(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for indicator_id, spec in INDICATORS.items():
        item = next((row for row in dashboard.get("indicators", []) if row.get("id") == indicator_id), None)
        if not item:
            continue
        series = [{"date": point["date"], "value": float(point["value"])} for point in item.get("series", [])]
        rows.append({
            "name": spec["name"], "id": f"trade_{indicator_id}", "unit": item.get("unit") or "指数",
            "source": item.get("source") or "dashboard", "sourceId": indicator_id,
            "providerId": None, "frequency": item.get("frequency") or "未知",
            "role": spec["role"], "aggregation": "月内均值；构造1个月与3个月对数动量",
            "latestAvailableDate": series[-1]["date"] if series else None,
            "modelUsageNote": "每个回测月仅使用当时已经到达的观测；PCA与筛选在扩展窗内重估",
            "series": series,
        })
    return rows


def augment_payload(payload: dict[str, Any], dashboard_path: Path, target_path: Path,
                    metadata_path: Path | None = None, include_daily: bool = True) -> dict[str, Any]:
    dashboard, targets = read_json(dashboard_path), read_targets(target_path)
    metadata = read_json(metadata_path) if metadata_path and metadata_path.exists() else {}
    output = copy.deepcopy(payload)
    results = {}
    for key in ("exports", "imports"):
        features = build_features(dashboard, key)
        result = forecast_trade(targets[key], features)
        results[key] = result
        output["history"][key] = _history_rows(result, targets[key])
        metric = result["metrics"]
        output["metrics"][key] = {
            name: (round(value, 4) if isinstance(value, float) and np.isfinite(value) else value)
            for name, value in metric.items()
        }
        label = "出口" if key == "exports" else "进口"
        drivers = "、".join(column.rsplit("_", 1)[0] for column in result["selected"])
        output["models"][key] = {
            "name": f"{label}同比", "unit": "%",
            "description": f"{label}同比由实时高频指标公共因子、目标AR项与AR基准动态加权得到。",
            "formula": f"扩展窗筛选 → PCA近似MDFM（{result['factorCount']}个因子）→ Ridge桥接回归 → 按历史样本外RMSE与AR基准加权。当前驱动：{drivers or '数据不足时退回AR'}。",
        }
        output["daily"][key] = _daily_path(dashboard, targets[key], key) if include_daily else []
    output["highFrequency"]["进出口"] = _input_rows(dashboard)
    output["tradeModel"] = {
        "version": "trade-mdfm-ensemble-v1", "targetSource": metadata.get("source", "OECD/FRED"),
        "targetLastObservation": max(series.index.max() for series in targets.values()).date().isoformat(),
        "targetRole": metadata.get("role"),
        "featurePolicy": "training-window-only selection; max 8 base indicators; 1-2 PCA factors; no future actuals",
        "results": {key: {"selectedFeatures": value["selected"], "factorCount": value["factorCount"]} for key, value in results.items()},
    }
    daily_dates = [row["date"] for rows in output["daily"].values() for row in rows]
    if daily_dates:
        output["dailyAsOf"] = max(daily_dates)
    return output

