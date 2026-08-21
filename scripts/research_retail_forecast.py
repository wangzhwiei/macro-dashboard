#!/usr/bin/env python3
"""Leakage-safe research model for monthly China retail-sales YoY.

The iFinD consensus series is loaded only after all standalone forecasts have
been generated. It is a benchmark, never a regressor or a selection target.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "forecast-model" / "research_retail_ifind.json"
INPUT_PATH = ROOT / "data" / "forecast-model" / "ifind_latest_inputs.json"
DASHBOARD_PATH = ROOT / "public" / "data" / "dashboard.json"
OUTPUT_PATH = ROOT / "data" / "forecast-model" / "retail_model_research.json"
BACKTEST_START = pd.Timestamp("2020-03-31")
SCREENING_END = pd.Timestamp("2019-12-31")
SELECTION_END = pd.Timestamp("2022-12-31")
HOLDOUT_START = pd.Timestamp("2023-03-31")
EXCEPTIONAL_BASE_YEARS = {2021, 2023}
MIN_BASE_TRAIN = 72
MIN_HF_TRAIN = 18
EXPECTED = {
    "actual_retail_yoy": ("M001625520", "社会消费品零售总额:当月同比", "M", "%"),
    "consensus_retail_yoy": ("M005682254", "预测平均值:社会消费品零售总额:当月同比", "M", "%"),
}
SPRING_MONTH = {
    2010: 2, 2011: 2, 2012: 1, 2013: 2, 2014: 1, 2015: 2,
    2016: 2, 2017: 1, 2018: 2, 2019: 2, 2020: 1, 2021: 2,
    2022: 2, 2023: 1, 2024: 2, 2025: 1, 2026: 2, 2027: 2,
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def checked_series(payload: dict[str, Any], key: str) -> pd.Series:
    item = payload.get("series", {}).get(key)
    if not isinstance(item, dict):
        raise RuntimeError(f"缺少固定序列：{key}")
    provider_id, name, frequency, unit = EXPECTED[key]
    actual = (item.get("providerId"), item.get("name"), item.get("frequency"), item.get("unit"))
    if actual != (provider_id, name, frequency, unit):
        raise RuntimeError(f"{key} 元数据不一致：{actual}")
    rows = item.get("records", [])
    series = pd.Series(
        {pd.Timestamp(row[0]).to_period("M").to_timestamp("M"): float(row[1]) for row in rows},
        dtype=float,
    ).sort_index()
    if series.empty:
        raise RuntimeError(f"{key} 没有有效记录")
    return series


def records_series(item: dict[str, Any]) -> pd.Series:
    return pd.Series(
        {pd.Timestamp(row[0]): float(row[1]) for row in item.get("records", [])},
        dtype=float,
    ).sort_index()


def dashboard_series(payload: dict[str, Any], key: str) -> pd.Series:
    item = next((row for row in payload.get("indicators", []) if row.get("id") == key), None)
    if item is None:
        return pd.Series(dtype=float)
    return pd.Series(
        {pd.Timestamp(row["date"]): float(row["value"]) for row in item.get("series", [])},
        dtype=float,
    ).sort_index()


def monthly_yoy(series: pd.Series, aggregation: str) -> pd.Series:
    monthly = series.resample("ME").agg(aggregation)
    return monthly.pct_change(12, fill_method=None) * 100


def build_factors(
    ifind: dict[str, Any], dashboard: dict[str, Any], research: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    source = {**ifind.get("series", {}), **((research or {}).get("series", {}))}
    factors: dict[str, pd.Series] = {}
    meta: dict[str, dict[str, Any]] = {}

    specs = (
        ("car_retail_level_yoy", "pmi_car_retail", "last", "乘用车厂家日均零售销量同比", "月末值计算12个月同比"),
        ("car_wholesale_level_yoy", "pmi_car_wholesale", "last", "乘用车厂家日均批发销量同比", "月末值计算12个月同比"),
        ("newhome_30_area_yoy", "pmi_newhome_30", "sum", "30城商品房成交面积同比", "日值月度求和后计算12个月同比"),
        ("secondhand_shenzhen_area_yoy", "pmi_secondhand_shenzhen", "sum", "深圳二手房成交面积同比", "日值月度求和后计算12个月同比"),
    )
    for factor_key, source_key, aggregation, name, transform in specs:
        item = source.get(source_key)
        if not isinstance(item, dict):
            continue
        factors[factor_key] = monthly_yoy(records_series(item), aggregation)
        meta[factor_key] = {
            "name": name, "sourceKey": source_key, "providerId": item.get("providerId"),
            "source": "iFinD", "transform": transform,
        }

    monthly_specs = (
        ("cpi_yoy", "actual_cpi_yoy", "CPI当月同比", "当月官方值；社零发布前已公布"),
        ("pmi_headline", "cpi_pmi", "制造业PMI", "当月官方值；月末已公布"),
        ("pmi_production_official", "pmi_production", "制造业PMI生产", "当月官方分项；月末已公布"),
        ("pmi_new_orders_official", "pmi_new_orders", "制造业PMI新订单", "当月官方分项；月末已公布"),
        ("pmi_employment_official", "pmi_employment", "制造业PMI从业人员", "当月官方分项；月末已公布"),
        ("pmi_delivery_official", "pmi_delivery", "制造业PMI供应商配送时间", "当月官方分项；月末已公布"),
        ("pmi_inventory_official", "pmi_inventory", "制造业PMI原材料库存", "当月官方分项；月末已公布"),
        ("cpi_food_detail_yoy", "cpi_food_yoy", "CPI食品当月同比", "当月官方食品分项；社零发布前已公布"),
        ("cpi_nonfood_detail_yoy", "cpi_nonfood_yoy", "CPI非食品当月同比", "当月官方非食品分项；社零发布前已公布"),
        ("cpi_consumer_goods_detail_yoy", "cpi_consumer_goods_yoy", "CPI消费品当月同比", "当月官方消费品分项；社零发布前已公布"),
        ("cpi_services_detail_yoy", "cpi_services_yoy", "CPI服务项目当月同比", "当月官方服务项目分项；社零发布前已公布"),
        ("pmi_nonmanufacturing_business", "pmi_nonmanufacturing_business", "非制造业PMI商务活动", "当月官方值；月末已公布"),
        ("pmi_nonmanufacturing_new_orders", "pmi_nonmanufacturing_new_orders", "非制造业PMI新订单", "当月官方值；月末已公布"),
        ("pmi_services_business", "pmi_services_business", "服务业PMI商务活动", "当月服务业分项；月末已公布"),
        ("pmi_services_new_orders", "pmi_services_new_orders", "服务业PMI新订单", "当月服务业分项；月末已公布"),
        ("pmi_services_expectations", "pmi_services_expectations", "服务业PMI业务活动预期", "当月服务业分项；月末已公布"),
    )
    for factor_key, source_key, name, transform in monthly_specs:
        item = source.get(source_key)
        if not isinstance(item, dict):
            continue
        factors[factor_key] = records_series(item).resample("ME").last()
        meta[factor_key] = {
            "name": name, "sourceKey": source_key, "providerId": item.get("providerId"),
            "source": "iFinD", "transform": transform,
            "releaseTiming": "available_before_retail_release",
        }

    dashboard_specs = (
        ("car_retail_weekly_yoy", "car_retail_yoy", "mean", "乘用车厂家零售当周同比", "周度同比月均"),
        ("car_wholesale_weekly_yoy", "car_wholesale_yoy", "mean", "乘用车厂家批发当周同比", "周度同比月均"),
        ("metro_composite_yoy", "metro_composite", "mean", "重点城市地铁客流同比", "日频指数月均后计算12个月同比"),
        ("boxoffice_yoy", "boxoffice_7d", "mean", "全国电影票房同比", "7日合计日值月均后计算12个月同比"),
        ("movie_audience_yoy", "movie_audience", "sum", "全国观影人次同比", "日值月度求和后计算12个月同比"),
        ("flights_yoy", "flights_7d", "mean", "国内航班执行量同比", "7日均日值月均后计算12个月同比"),
    )
    for factor_key, source_key, aggregation, name, transform in dashboard_specs:
        raw = dashboard_series(dashboard, source_key)
        if raw.empty:
            continue
        if source_key.endswith("_yoy"):
            factors[factor_key] = raw.resample("ME").mean()
        else:
            factors[factor_key] = monthly_yoy(raw, aggregation)
        meta[factor_key] = {
            "name": name, "sourceKey": source_key, "providerId": source_key,
            "source": "dashboard/CJHX", "transform": transform,
        }
    return pd.DataFrame(factors).sort_index(), meta


def deterministic_exog(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({
        "spring": [float(SPRING_MONTH.get(day.year) == day.month) for day in index],
        "march_release": [float(day.month == 3) for day in index],
    }, index=index)


def uses_direct_base_gate(day: pd.Timestamp) -> bool:
    """Use the direct model when the prior year has a known lockdown base."""
    return day.year in EXCEPTIONAL_BASE_YEARS


def direct_hf_arx_forecast(
    target: pd.Series, factors: pd.DataFrame, day: pd.Timestamp, selected: list[str],
    alpha: float = 10.0,
) -> float:
    """Fast direct-factor race using expanding-window regularized ARX."""
    index = pd.date_range(target.index.min(), day, freq="ME")
    training_index = index[index < day]
    aligned = target.reindex(index)
    if aligned.loc[training_index].notna().sum() < MIN_BASE_TRAIN or factors.reindex([day])[selected].isna().any(axis=None):
        return math.nan
    design = deterministic_exog(index)
    design["last_release"] = aligned.ffill().shift(1)
    design["target_l12"] = aligned.shift(12)
    for key in selected:
        design[key] = factors[key].reindex(index)
    training = pd.concat([aligned.rename("target"), design], axis=1, sort=False)
    training = training.loc[training.index < day].dropna()
    if len(training) < MIN_HF_TRAIN:
        return math.nan
    x_train, y_train = training.drop(columns="target"), training["target"]
    means, stds = x_train.mean(), x_train.std().replace(0, 1.0)
    z = (x_train - means) / stds
    beta = ridge_fit(np.column_stack([np.ones(len(z)), z.to_numpy()]), y_train.to_numpy(), alpha)
    now = design.loc[day]
    if now.isna().any():
        return math.nan
    return float(np.r_[1.0, ((now - means) / stds).to_numpy()] @ beta)


def ridge_fit(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    penalty = np.eye(x.shape[1]) * alpha
    penalty[0, 0] = 0.0
    return np.linalg.pinv(x.T @ x + penalty) @ x.T @ y


def seasonal_backbone_forecast(target: pd.Series, day: pd.Timestamp, alpha: float = 100.0) -> float:
    """Trade-style seasonal backbone: predict the YoY change over t-12."""
    index = pd.date_range(target.index.min(), day, freq="ME")
    training_index = index[index < day]
    aligned = target.reindex(index)
    yoy_change = aligned - aligned.shift(12)
    release_level = aligned.ffill().shift(1)
    features = pd.DataFrame(index=index)
    for lag in (1, 2, 3, 6, 12):
        features[f"target_l{lag}"] = release_level.shift(lag - 1)
    features["month_sin"] = np.sin(2 * np.pi * index.month / 12)
    features["month_cos"] = np.cos(2 * np.pi * index.month / 12)
    features = pd.concat([features, deterministic_exog(index)], axis=1, sort=False)
    train = pd.concat([yoy_change.rename("target"), features], axis=1, sort=False)
    train = train.loc[training_index].dropna()
    if len(train) < MIN_HF_TRAIN:
        return math.nan
    x_train = train.drop(columns="target")
    means, stds = x_train.mean(), x_train.std().replace(0, 1.0)
    z = (x_train - means) / stds
    beta = ridge_fit(np.column_stack([np.ones(len(z)), z.to_numpy()]), train["target"].to_numpy(), alpha)
    now = features.loc[day]
    if now.isna().any():
        return math.nan
    change_prediction = float(np.r_[1.0, ((now - means) / stds).to_numpy()] @ beta)
    base = aligned.shift(12).loc[day]
    if pd.isna(base):
        base = aligned.ffill().shift(12).loc[day]
    return float(base + change_prediction) if pd.notna(base) else math.nan


def anchored_change_forecast(
    target: pd.Series, factors: pd.DataFrame, day: pd.Timestamp, selected: list[str],
    alpha: float = 100.0, cap: float = 2.0,
) -> float:
    """Import-model-style bridge anchored on the latest released target."""
    prior_target = target.loc[target.index < day].dropna()
    if len(prior_target) < MIN_HF_TRAIN:
        return math.nan
    event_index = target.dropna().index
    design = pd.DataFrame(index=event_index)
    design["target_change_l1"] = target.dropna().diff().shift(1)
    design["month_sin"] = np.sin(2 * np.pi * event_index.month / 12)
    design["month_cos"] = np.cos(2 * np.pi * event_index.month / 12)
    design["spring"] = [float(SPRING_MONTH.get(value.year) == value.month) for value in event_index]
    design["march_release"] = [float(value.month == 3) for value in event_index]
    for key in selected:
        values = factors[key].reindex(event_index)
        design[f"{key}_change"] = values.diff()
    response = target.dropna().diff().rename("target_change")
    train = pd.concat([response, design], axis=1, sort=False)
    train = train.loc[train.index < day].dropna()
    if len(train) < MIN_HF_TRAIN:
        return math.nan
    current = {
        "target_change_l1": float(target.dropna().diff().loc[prior_target.index[-1]]),
        "month_sin": float(np.sin(2 * np.pi * day.month / 12)),
        "month_cos": float(np.cos(2 * np.pi * day.month / 12)),
        "spring": float(SPRING_MONTH.get(day.year) == day.month),
        "march_release": float(day.month == 3),
    }
    previous_day = prior_target.index[-1]
    for key in selected:
        current_value = factors[key].get(day)
        previous_value = factors[key].get(previous_day)
        if pd.isna(current_value) or pd.isna(previous_value):
            return math.nan
        current[f"{key}_change"] = float(current_value - previous_value)
    x_train = train.drop(columns="target_change")
    means, stds = x_train.mean(), x_train.std().replace(0, 1.0)
    z = (x_train - means) / stds
    beta = ridge_fit(np.column_stack([np.ones(len(z)), z.to_numpy()]), train["target_change"].to_numpy(), alpha)
    now = pd.Series(current).reindex(x_train.columns)
    change = float(np.r_[1.0, ((now - means) / stds).to_numpy()] @ beta)
    return float(prior_target.iloc[-1] + np.clip(change, -cap, cap))


def correction_forecast(
    day: pd.Timestamp, baseline: float, baseline_errors: pd.Series,
    factors: pd.DataFrame, candidates: list[str], alpha: float = 100.0, cap: float = 1.0,
) -> tuple[float, list[str], float]:
    prior_errors = baseline_errors.loc[baseline_errors.index < day].dropna()
    scored: list[tuple[float, str]] = []
    for key in candidates:
        joined = pd.concat([prior_errors.rename("error"), factors[key].rename("factor")], axis=1, sort=False).dropna()
        if len(joined) >= MIN_HF_TRAIN and joined["factor"].std() > 1e-9:
            corr = joined["error"].corr(joined["factor"])
            if pd.notna(corr):
                scored.append((abs(float(corr)), key))
    # Keep one factor per economic family and at most two regressors.
    selected: list[str] = []
    used_families: set[str] = set()
    for _, key in sorted(scored, reverse=True):
        family = "car" if key.startswith("car_") else key.split("_")[0]
        if family in used_families or pd.isna(factors[key].get(day)):
            continue
        selected.append(key)
        used_families.add(family)
        if len(selected) == 2:
            break
    if not selected:
        return baseline, [], 0.0
    train = pd.concat([prior_errors.rename("error"), factors[selected]], axis=1, sort=False).dropna()
    if len(train) < MIN_HF_TRAIN:
        return baseline, [], 0.0
    means, stds = train[selected].mean(), train[selected].std().replace(0, 1.0)
    z = (train[selected] - means) / stds
    x = np.column_stack([np.ones(len(z)), z.to_numpy()])
    beta = ridge_fit(x, train["error"].to_numpy(), alpha)
    now = (factors.loc[day, selected] - means) / stds
    correction = float(np.clip(np.r_[1.0, now.to_numpy()] @ beta, -cap, cap))
    return baseline + correction, selected, correction


def metrics(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    sample = frame[[column, "actual"]].dropna()
    if sample.empty:
        return {
            "rmse": None, "mae": None, "directionHitPct": None,
            "observations": 0, "sampleStart": None, "sampleEnd": None,
        }
    error = sample[column] - sample["actual"]
    prior = sample["actual"].shift(1)
    direction = (np.sign(sample[column] - prior) == np.sign(sample["actual"] - prior)).iloc[1:]
    return {
        "rmse": round(float(np.sqrt(np.mean(error ** 2))), 4),
        "mae": round(float(np.mean(np.abs(error))), 4),
        "directionHitPct": round(float(direction.mean() * 100), 2) if len(direction) else None,
        "observations": int(len(sample)),
        "sampleStart": sample.index.min().strftime("%Y-%m"),
        "sampleEnd": sample.index.max().strftime("%Y-%m"),
    }


def correlation_rows(target: pd.Series, factors: pd.DataFrame, meta: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for key in factors:
        joined = pd.concat([target.rename("target"), factors[key].rename("factor")], axis=1, sort=False).dropna()
        if len(joined) < 12:
            continue
        rows.append({
            "key": key, **meta[key], "observations": int(len(joined)),
            "sampleStart": joined.index.min().strftime("%Y-%m"),
            "sampleEnd": joined.index.max().strftime("%Y-%m"),
            "pearson": round(float(joined["target"].corr(joined["factor"])), 4),
            "spearman": round(float(joined["target"].corr(joined["factor"], method="spearman")), 4),
        })
    return sorted(rows, key=lambda row: abs(row["pearson"]), reverse=True)


def change_correlation_rows(
    target: pd.Series, factors: pd.DataFrame, meta: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Correlate release-to-release changes, matching the anchor model target."""
    event_target = target.dropna().sort_index()
    target_change = event_target.diff()
    rows = []
    for key in factors:
        factor_change = factors[key].reindex(event_target.index).diff()
        joined = pd.concat(
            [target_change.rename("target"), factor_change.rename("factor")],
            axis=1, sort=False,
        ).dropna()
        if len(joined) < 12:
            continue
        rows.append({
            "key": key, **meta[key], "observations": int(len(joined)),
            "sampleStart": joined.index.min().strftime("%Y-%m"),
            "sampleEnd": joined.index.max().strftime("%Y-%m"),
            "pearson": round(float(joined["target"].corr(joined["factor"])), 4),
            "spearman": round(float(joined["target"].corr(joined["factor"], method="spearman")), 4),
        })
    return sorted(rows, key=lambda row: abs(row["pearson"]), reverse=True)


def rank_and_filter_factors(
    target: pd.Series, factors: pd.DataFrame, meta: dict[str, dict[str, Any]],
    correlation_threshold: float = 0.75, max_factors: int = 6,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Greedy pre-backtest ranking with pairwise change-correlation control."""
    ranking = change_correlation_rows(target, factors, meta)
    event_index = target.dropna().index
    changes = factors.reindex(event_index).diff()
    selected: list[str] = []
    audit: list[dict[str, Any]] = []
    for rank, row in enumerate(ranking, 1):
        key = row["key"]
        blocked_by, blocked_correlation = None, None
        for existing in selected:
            joined = pd.concat(
                [changes[key].rename("candidate"), changes[existing].rename("selected")],
                axis=1, sort=False,
            ).dropna()
            pairwise = joined["candidate"].corr(joined["selected"]) if len(joined) >= 12 else math.nan
            if pd.notna(pairwise) and abs(float(pairwise)) >= correlation_threshold:
                blocked_by, blocked_correlation = existing, float(pairwise)
                break
        accepted = blocked_by is None and len(selected) < max_factors
        if accepted:
            selected.append(key)
        audit.append({
            "rank": rank, "key": key, "name": row["name"],
            "targetPearson": row["pearson"], "targetSpearman": row["spearman"],
            "observations": row["observations"], "accepted": accepted,
            "blockedBy": blocked_by,
            "pairwiseChangeCorrelation": round(blocked_correlation, 4) if blocked_correlation is not None else None,
            "reason": (
                "selected" if accepted else
                (f"pairwise change correlation >= {correlation_threshold}" if blocked_by else "maximum factor count reached")
            ),
        })
    return selected, audit


def point_rows(
    frame: pd.DataFrame, selections: dict[pd.Timestamp, list[str]],
    corrections: dict[pd.Timestamp, float], primary_key: str,
) -> list[dict[str, Any]]:
    rows = []
    for day, row in frame.iterrows():
        no_separate_release = day.year >= 2012 and day.month in (1, 2)
        if pd.notna(row.get("actual")):
            actual_status, missing_reason = "published", None
        elif no_separate_release:
            actual_status, missing_reason = "not_applicable", "国家统计局1-2月合并发布累计值，不公布单月社零同比"
        else:
            actual_status, missing_reason = "pending_or_unavailable", "尚未公布或上游序列缺失"
        if no_separate_release:
            forecast_status = "not_applicable"
        elif day < BACKTEST_START:
            forecast_status = "outside_backtest"
        elif pd.notna(row.get(primary_key)):
            forecast_status = "available"
        else:
            forecast_status = "waiting_inputs"
        rows.append({
            "date": day.date().isoformat(),
            **{key: (round(float(row[key]), 6) if pd.notna(row[key]) else None) for key in frame.columns},
            "actualStatus": actual_status,
            "forecastStatus": forecast_status,
            "missingReason": missing_reason,
            "consensusComparable": bool(pd.notna(row.get("actual")) and pd.notna(row.get("consensus"))),
            "selectedFactors": selections.get(day, []),
            "hfCorrection": round(corrections.get(day, 0.0), 6),
        })
    return rows


def build() -> dict[str, Any]:
    data, inputs, dashboard = read_json(DATA_PATH), read_json(INPUT_PATH), read_json(DASHBOARD_PATH)
    actual = checked_series(data, "actual_retail_yoy")
    factors, factor_meta = build_factors(inputs, dashboard, data)
    evaluation_days = actual.index[actual.index >= BACKTEST_START]
    future_month = actual.index.max() + pd.offsets.MonthEnd(1)
    forecast_days = evaluation_days.append(pd.DatetimeIndex([future_month]))

    baseline: dict[pd.Timestamp, float] = {}
    for day in forecast_days:
        baseline[day] = seasonal_backbone_forecast(actual, day)
    baseline_series = pd.Series(baseline, dtype=float)
    historical_errors = (actual.reindex(baseline_series.index) - baseline_series).dropna()

    # Keep the screen consistent with the NBS retail definition: goods retail
    # plus catering revenue. Real-estate transactions and general service
    # volumes are outside that definition, even when their sample correlation
    # is high. CPI/PMI series remain eligible only as price or leading proxies.
    scope_exclusions = {
        "newhome_30_area_yoy": "Real-estate transactions are outside total retail sales of consumer goods.",
        "secondhand_shenzhen_area_yoy": "Second-hand home transactions are outside total retail sales of consumer goods.",
        "metro_composite_yoy": "Passenger traffic is general service activity, not goods retail or catering revenue.",
        "boxoffice_yoy": "Cinema ticket revenue is service consumption outside the retail-sales definition.",
        "movie_audience_yoy": "Cinema attendance is service consumption outside the retail-sales definition.",
        "flights_yoy": "Air travel is service consumption outside the retail-sales definition.",
    }
    history_counts = {key: int(factors[key].loc[:SCREENING_END].notna().sum()) for key in factors}
    scope_candidates = [key for key in factors if key not in scope_exclusions]
    candidates = [key for key in scope_candidates if history_counts[key] >= 12]
    history_exclusions = {
        key: f"Only {history_counts[key]} observations are available through {SCREENING_END:%Y-%m}; at least 12 are required."
        for key in scope_candidates if history_counts[key] < 12
    }
    screening_target = actual.loc[:SCREENING_END]
    screening_factors = factors.loc[:SCREENING_END, candidates]
    ranked_selected, ranked_audit = rank_and_filter_factors(
        screening_target, screening_factors,
        {key: factor_meta[key] for key in candidates},
        correlation_threshold=0.75, max_factors=6,
    )
    ranked_topk_sets = {
        f"RankedTop{size}": ranked_selected[:size]
        for size in range(1, len(ranked_selected) + 1)
    }
    direct_factor_sets = {
        "directCarArx": ["car_retail_level_yoy"],
        "directCarHomeArx": ["car_retail_level_yoy", "newhome_30_area_yoy"],
        "directMacroArx": [
            "car_retail_level_yoy", "cpi_yoy", "pmi_new_orders_official",
            "pmi_employment_official",
        ],
        "directSelectedMacroArx": [
            "car_retail_level_yoy", "newhome_30_area_yoy", "cpi_yoy",
            "pmi_new_orders_official", "pmi_headline", "pmi_delivery_official",
        ],
        "directConsumptionDetailArx": [
            "car_retail_level_yoy", "newhome_30_area_yoy",
            "cpi_food_detail_yoy", "cpi_services_detail_yoy",
            "pmi_services_business", "pmi_services_new_orders",
        ],
        "directConsumptionSelectedArx": [
            "car_retail_level_yoy", "newhome_30_area_yoy",
            "cpi_services_detail_yoy", "pmi_nonmanufacturing_business",
            "pmi_services_expectations", "pmi_nonmanufacturing_new_orders",
        ],
    }
    incremental_specs = {
        "ServiceExpectations": ["pmi_services_expectations"],
        "ServiceNewOrders": ["pmi_services_new_orders"],
        "NonmanufacturingNewOrders": ["pmi_nonmanufacturing_new_orders"],
        "NonmanufacturingBusiness": ["pmi_nonmanufacturing_business"],
        "ServicesBusiness": ["pmi_services_business"],
        "CpiNonfood": ["cpi_nonfood_detail_yoy"],
        "Top2Service": ["pmi_services_expectations", "pmi_services_new_orders"],
        "Top3Service": [
            "pmi_services_expectations", "pmi_services_new_orders",
            "pmi_nonmanufacturing_new_orders",
        ],
        "Top4Service": [
            "pmi_services_expectations", "pmi_services_new_orders",
            "pmi_nonmanufacturing_new_orders", "pmi_nonmanufacturing_business",
        ],
    }
    incremental_base = ["car_retail_level_yoy", "newhome_30_area_yoy"]
    direct_factor_sets.update({
        f"directInc{name}": [*incremental_base, *extra]
        for name, extra in incremental_specs.items()
    })
    direct_factor_sets.update({
        f"direct{name}": selected for name, selected in ranked_topk_sets.items()
    })
    direct_series = {
        name: pd.Series({
            day: direct_hf_arx_forecast(actual, factors, day, selected)
            for day in forecast_days
        }, dtype=float)
        for name, selected in direct_factor_sets.items()
    }
    anchor_factor_sets = {
        "anchorCarBridge": ["car_retail_level_yoy"],
        "anchorCarHomeBridge": ["car_retail_level_yoy", "newhome_30_area_yoy"],
        "anchorMacroBridge": [
            "car_retail_level_yoy", "cpi_yoy", "pmi_new_orders_official",
            "pmi_employment_official",
        ],
        "anchorFullMacroBridge": [
            "car_retail_level_yoy", "newhome_30_area_yoy", "cpi_yoy",
            "pmi_production_official", "pmi_new_orders_official",
            "pmi_employment_official",
        ],
        "anchorSelectedMacroBridge": [
            "car_retail_level_yoy", "newhome_30_area_yoy", "cpi_yoy",
            "pmi_new_orders_official", "pmi_headline", "pmi_delivery_official",
        ],
        "anchorConsumptionDetailBridge": [
            "car_retail_level_yoy", "newhome_30_area_yoy",
            "cpi_food_detail_yoy", "cpi_services_detail_yoy",
            "pmi_services_business", "pmi_services_new_orders",
        ],
        "anchorConsumptionSelectedBridge": [
            "car_retail_level_yoy", "newhome_30_area_yoy",
            "cpi_services_detail_yoy", "pmi_nonmanufacturing_business",
            "pmi_services_expectations", "pmi_nonmanufacturing_new_orders",
        ],
    }
    anchor_factor_sets.update({
        f"anchorInc{name}": [*incremental_base, *extra]
        for name, extra in incremental_specs.items()
    })
    anchor_factor_sets.update({
        f"anchor{name}": selected for name, selected in ranked_topk_sets.items()
    })
    anchor_series = {
        name: pd.Series({
            day: anchored_change_forecast(actual, factors, day, selected)
            for day in forecast_days
        }, dtype=float)
        for name, selected in anchor_factor_sets.items()
    }
    # Fixed exceptional-base gate: 2021 and 2023 releases compare against
    # known lockdown bases. Normal periods use the smoother anchored bridge.
    gated_series = pd.Series({
        day: (
            direct_series["directCarHomeArx"].get(day)
            if uses_direct_base_gate(day)
            else anchor_series["anchorCarHomeBridge"].get(day)
        )
        for day in forecast_days
    }, dtype=float)
    scope_car_retail_series = pd.Series({
        day: (
            direct_series["directCarArx"].get(day)
            if uses_direct_base_gate(day)
            else anchor_series["anchorCarBridge"].get(day)
        )
        for day in forecast_days
    }, dtype=float)
    preliminary_required = ("pmi_car_retail", "pmi_newhome_30")
    preliminary_ends = [
        pd.Timestamp(inputs["series"][key]["endTime"])
        for key in preliminary_required
        if inputs.get("series", {}).get(key, {}).get("endTime")
    ]
    preliminary_complete = bool(preliminary_ends) and min(preliminary_ends) >= future_month
    if not preliminary_complete:
        gated_series.loc[future_month] = math.nan
        scope_car_retail_series.loc[future_month] = math.nan
    gated_macro_series = pd.Series({
        day: (
            direct_series["directMacroArx"].get(day)
            if uses_direct_base_gate(day)
            else anchor_series["anchorMacroBridge"].get(day)
        )
        for day in forecast_days
    }, dtype=float)
    gated_full_macro_series = pd.Series({
        day: (
            direct_series["directMacroArx"].get(day)
            if uses_direct_base_gate(day)
            else anchor_series["anchorFullMacroBridge"].get(day)
        )
        for day in forecast_days
    }, dtype=float)
    gated_selected_macro_series = pd.Series({
        day: (
            direct_series["directSelectedMacroArx"].get(day)
            if uses_direct_base_gate(day)
            else anchor_series["anchorSelectedMacroBridge"].get(day)
        )
        for day in forecast_days
    }, dtype=float)
    gated_consumption_detail_series = pd.Series({
        day: (
            direct_series["directConsumptionDetailArx"].get(day)
            if uses_direct_base_gate(day)
            else anchor_series["anchorConsumptionDetailBridge"].get(day)
        )
        for day in forecast_days
    }, dtype=float)
    gated_consumption_selected_series = pd.Series({
        day: (
            direct_series["directConsumptionSelectedArx"].get(day)
            if uses_direct_base_gate(day)
            else anchor_series["anchorConsumptionSelectedBridge"].get(day)
        )
        for day in forecast_days
    }, dtype=float)
    incremental_gated_series = {
        f"seasonalGatedInc{name}": pd.Series({
            day: (
                direct_series[f"directInc{name}"].get(day)
                if uses_direct_base_gate(day)
                else anchor_series[f"anchorInc{name}"].get(day)
            )
            for day in forecast_days
        }, dtype=float)
        for name in incremental_specs
    }
    ranked_gated_series = {
        f"seasonalGated{name}": pd.Series({
            day: (
                direct_series[f"direct{name}"].get(day)
                if uses_direct_base_gate(day)
                else anchor_series[f"anchor{name}"].get(day)
            )
            for day in forecast_days
        }, dtype=float)
        for name in ranked_topk_sets
    }
    source_payloads = {**inputs.get("series", {}), **data.get("series", {})}
    selected_source_ends = []
    for key in ranked_selected:
        source_key = factor_meta[key]["sourceKey"]
        end_time = source_payloads.get(source_key, {}).get("endTime")
        if end_time:
            selected_source_ends.append(pd.Timestamp(end_time))
    ranked_current_month_complete = (
        bool(ranked_selected)
        and len(selected_source_ends) == len(ranked_selected)
        and min(selected_source_ends) >= future_month
    )
    if not ranked_current_month_complete:
        for series in ranked_gated_series.values():
            series.loc[future_month] = math.nan
    corrected, selections, corrections = {}, {}, {}
    bias_corrected, bias_corrections = {}, {}
    for day in forecast_days:
        prediction, selected, correction = correction_forecast(
            day, float(baseline_series.loc[day]), historical_errors, factors, candidates,
            alpha=100.0, cap=1.0,
        )
        corrected[day], selections[day], corrections[day] = prediction, selected, correction
        prior_errors = historical_errors.loc[historical_errors.index < day].dropna()
        bias = float(np.clip(prior_errors.mean(), -3.0, 3.0)) if len(prior_errors) >= MIN_HF_TRAIN else 0.0
        bias_corrected[day], bias_corrections[day] = float(baseline_series.loc[day]) + bias, bias
    corrected_series = pd.Series(corrected, dtype=float)

    frame = pd.DataFrame({
        "actual": actual.reindex(forecast_days),
        "previousMonth": actual.shift(1).reindex(forecast_days),
        "seasonalNaive": actual.shift(12).reindex(forecast_days),
        "seasonalBackbone": baseline_series,
        "seasonalBias": pd.Series(bias_corrected, dtype=float),
        **direct_series,
        **anchor_series,
        "seasonalGatedBridge": gated_series,
        "seasonalGatedCarRetail": scope_car_retail_series,
        "seasonalGatedMacroBridge": gated_macro_series,
        "seasonalGatedFullMacroBridge": gated_full_macro_series,
        "seasonalGatedSelectedMacroBridge": gated_selected_macro_series,
        "seasonalGatedConsumptionDetailBridge": gated_consumption_detail_series,
        "seasonalGatedConsumptionSelectedBridge": gated_consumption_selected_series,
        **incremental_gated_series,
        **ranked_gated_series,
        "seasonalHf": corrected_series,
    })

    # Consensus is intentionally loaded only after forecasts and model choices exist.
    consensus = checked_series(data, "consensus_retail_yoy")
    frame["consensus"] = consensus.reindex(frame.index)
    metric_columns = [
        "previousMonth", "seasonalNaive", "seasonalBackbone", "seasonalBias",
        *direct_factor_sets, *anchor_factor_sets,
        "seasonalGatedBridge", "seasonalGatedMacroBridge",
        "seasonalGatedCarRetail",
        "seasonalGatedFullMacroBridge", "seasonalHf",
        "seasonalGatedSelectedMacroBridge",
        "seasonalGatedConsumptionDetailBridge",
        "seasonalGatedConsumptionSelectedBridge",
        *incremental_gated_series,
        *ranked_gated_series,
    ]
    model_metrics = {key: metrics(frame.iloc[:-1], key) for key in metric_columns}
    ranked_selection_metrics = {
        key: metrics(frame.loc[BACKTEST_START:SELECTION_END], key)
        for key in ranked_gated_series
    }
    valid_ranked = {
        key: value for key, value in ranked_selection_metrics.items()
        if value.get("rmse") is not None
    }
    primary_key = min(valid_ranked, key=lambda key: valid_ranked[key]["rmse"])
    scope_baseline_selection = metrics(
        frame.loc[BACKTEST_START:SELECTION_END], "seasonalGatedCarRetail",
    )
    scope_baseline_holdout = metrics(
        frame.loc[HOLDOUT_START:].iloc[:-1], "seasonalGatedCarRetail",
    )
    candidate_holdout = metrics(frame.loc[HOLDOUT_START:].iloc[:-1], primary_key)
    holdout_year_comparison = {}
    for year in range(HOLDOUT_START.year, actual.index.max().year + 1):
        year_frame = frame.loc[str(year)]
        candidate_year = metrics(year_frame, primary_key)
        baseline_year = metrics(year_frame, "seasonalGatedCarRetail")
        holdout_year_comparison[str(year)] = {
            "candidate": candidate_year, "scopeBaseline": baseline_year,
            "candidateWins": (
                candidate_year["rmse"] is not None
                and baseline_year["rmse"] is not None
                and candidate_year["rmse"] < baseline_year["rmse"]
            ),
        }
    holdout_year_wins = sum(row["candidateWins"] for row in holdout_year_comparison.values())
    required_holdout_year_wins = math.ceil(len(holdout_year_comparison) * 0.75)
    candidate_passes_stability = (
        ranked_selection_metrics[primary_key]["rmse"] < scope_baseline_selection["rmse"]
        and candidate_holdout["rmse"] < scope_baseline_holdout["rmse"]
        and holdout_year_wins >= required_holdout_year_wins
    )
    common = frame.iloc[:-1].dropna(subset=["actual", primary_key, "consensus"])
    common_metrics = {
        "model": metrics(common, primary_key),
        "consensus": metrics(common, "consensus"),
    }
    stable_common = common.loc["2024-01-31":]
    stable_common_metrics = {
        "model": metrics(stable_common, primary_key),
        "consensus": metrics(stable_common, "consensus"),
    }
    stability_keys = [
        "seasonalGatedCarRetail", primary_key,
        "seasonalGatedIncCpiNonfood", "consensus",
    ]
    annual_stability = {
        str(year): {
            key: metrics(frame.loc[str(year)].iloc[:-1] if year == future_month.year else frame.loc[str(year)], key)
            for key in stability_keys
        }
        for year in range(BACKTEST_START.year, actual.index.max().year + 1)
    }
    published = frame.iloc[:-1].dropna(subset=["actual"]).copy()
    rolling_stability = []
    for end_position in range(9, len(published)):
        sample = published.iloc[end_position - 9:end_position + 1]
        row = {"date": sample.index[-1].date().isoformat(), "publishedObservations": 10}
        for key in stability_keys:
            valid = sample.dropna(subset=[key])
            row[key] = metrics(valid, key).get("rmse") if len(valid) == 10 else None
        rolling_stability.append(row)
    latest = frame.iloc[-1]
    display_index = pd.date_range("2020-01-31", future_month, freq="ME")
    display_frame = frame.reindex(display_index)
    display_frame["actual"] = actual.reindex(display_index)
    display_frame["consensus"] = consensus.reindex(display_index)
    display_rows = point_rows(display_frame, selections, corrections, primary_key)
    published_count = sum(row["actualStatus"] == "published" for row in display_rows)
    not_applicable_count = sum(row["actualStatus"] == "not_applicable" for row in display_rows)
    pending_count = sum(row["actualStatus"] == "pending_or_unavailable" for row in display_rows)
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now().astimezone().isoformat(),
        "modelVersion": "retail-long-history-scope-ranked-v6-research",
        "target": {"providerId": EXPECTED["actual_retail_yoy"][0], "name": EXPECTED["actual_retail_yoy"][1], "unit": "%"},
        "consensus": {"providerId": EXPECTED["consensus_retail_yoy"][0], "name": EXPECTED["consensus_retail_yoy"][1], "modelUse": "comparison_only"},
        "method": {
            "backbone": "Trade-style seasonal ridge: forecast y_t-y_(t-12) from release-safe lags, month sin/cos, Spring Festival and March-release controls; add y_(t-12)",
            "primary": "NBS-retail-scope factor screen ranked through 2019, trained and selected on 2020-2022, with 2023+ reserved as untouched holdout; known lockdown-base years use the direct-factor ARX gate",
            "directFactorRace": "Expanding-window ridge ARX using last release, 12-month lag, calendar controls and contemporaneous factors; train-window scaling only",
            "highFrequency": "expanding-window ridge correction of prior out-of-sample backbone errors; alpha=100; cap=1pp; max 2 non-duplicate families",
            "backtestStart": BACKTEST_START.strftime("%Y-%m"),
            "informationSet": "Each prediction uses target values and model errors strictly before the forecast month. Factor transforms are contemporaneous L0 monthly aggregates.",
            "factorScreenEnd": SCREENING_END.strftime("%Y-%m"),
            "selectionEnd": SELECTION_END.strftime("%Y-%m"),
            "holdoutStart": HOLDOUT_START.strftime("%Y-%m"),
            "collinearityThreshold": 0.75,
        },
        "factorCandidates": candidates,
        "factorScreeningDecision": {
            "statisticalScope": "NBS total retail sales of consumer goods covers goods retail and catering revenue; general service consumption and real-estate transactions are outside the target definition.",
            "acceptedPrimary": ranked_topk_sets[primary_key.removeprefix("seasonalGated")],
            "rankedAfterCollinearityFilter": ranked_selected,
            "candidateRoles": {
                "directRetailOrPriceMeasures": [
                    "car_retail_level_yoy", "cpi_food_detail_yoy",
                    "cpi_consumer_goods_detail_yoy",
                ],
                "leadingOrMixedScopeProxies": [
                    "car_wholesale_level_yoy", "cpi_yoy", "cpi_nonfood_detail_yoy",
                    "cpi_services_detail_yoy", "pmi_headline",
                    "pmi_production_official", "pmi_new_orders_official",
                    "pmi_employment_official", "pmi_delivery_official",
                    "pmi_inventory_official", "pmi_nonmanufacturing_business",
                    "pmi_nonmanufacturing_new_orders", "pmi_services_business",
                    "pmi_services_new_orders", "pmi_services_expectations",
                ],
                "primaryFactorNote": "Passenger-car wholesale is not counted directly in retail sales; it is retained only as a leading proxy for subsequent vehicle retail.",
            },
            "scopeExclusions": scope_exclusions,
            "historyExclusions": history_exclusions,
            "legacyHousingModelStatus": "invalid_scope_comparator_only",
        },
        "directFactorRace": direct_factor_sets,
        "anchorBridgeRace": anchor_factor_sets,
        "correlations": correlation_rows(actual, factors, factor_meta),
        "preBacktestCorrelations": correlation_rows(
            screening_target, screening_factors,
            {key: factor_meta[key] for key in candidates},
        ),
        "preBacktestChangeCorrelations": change_correlation_rows(
            screening_target, screening_factors,
            {key: factor_meta[key] for key in candidates},
        ),
        "scopeCompliantCorrelationScreen": {
            "rankingBasis": "Absolute Pearson correlation between release-to-release changes through 2019-12.",
            "pairwiseThreshold": 0.75,
            "audit": ranked_audit,
            "selectedOrder": ranked_selected,
        },
        "stablePeriodCorrelations": correlation_rows(actual.loc["2024-01-31":], factors.loc["2024-01-31":], factor_meta),
        "metrics": model_metrics,
        "stablePeriodMetrics": {key: metrics(frame.loc["2024-01-31":].iloc[:-1], key) for key in metric_columns},
        "incrementalFactorRace": {
            "factorSets": incremental_specs,
            "baseline": {
                "selectionPeriod": metrics(frame.loc[BACKTEST_START:SELECTION_END], "seasonalGatedBridge"),
                "holdoutPeriod": metrics(frame.loc[HOLDOUT_START:].iloc[:-1], "seasonalGatedBridge"),
            },
            "selectionPeriod": {
                key: metrics(frame.loc[BACKTEST_START:SELECTION_END], key)
                for key in incremental_gated_series
            },
            "holdoutPeriod": {
                key: metrics(frame.loc[HOLDOUT_START:].iloc[:-1], key)
                for key in incremental_gated_series
            },
        },
        "rankedTopKRace": {
            "selectionRule": "Choose the lowest 2020-03 to 2022-12 RMSE; 2023+ is untouched holdout and is not used for factor or K selection.",
            "factorSets": ranked_topk_sets,
            "selectedModel": primary_key,
            "selectionPeriod": ranked_selection_metrics,
            "holdoutPeriod": {
                key: metrics(frame.loc[HOLDOUT_START:].iloc[:-1], key)
                for key in ranked_gated_series
            },
            "fullPeriod": {key: model_metrics[key] for key in ranked_gated_series},
            "scopeBaseline": {
                "key": "seasonalGatedCarRetail",
                "selectionPeriod": scope_baseline_selection,
                "holdoutPeriod": scope_baseline_holdout,
            },
        },
        "stabilityAnalysis": {
            "annual": annual_stability,
            "rollingTwelveCalendarMonths": rolling_stability,
            "rollingWindowDefinition": "10 published observations, corresponding to 12 calendar months because January and February have no separate release.",
            "scopeBaseline": "seasonalGatedCarRetail",
            "candidate": primary_key,
            "candidatePassesStabilityGate": candidate_passes_stability,
            "holdoutYearComparison": holdout_year_comparison,
            "holdoutYearWins": holdout_year_wins,
            "requiredHoldoutYearWins": required_holdout_year_wins,
            "stabilityGate": "A replacement must improve the 2020-2022 selection period, improve the untouched 2023+ holdout overall, and beat the scope-compliant car-retail baseline in at least 75% of holdout calendar years.",
        },
        "consensusCommonSample": common_metrics,
        "stableConsensusCommonSample": stable_common_metrics,
        "productionDecision": {
            "status": "research_only",
            "primaryCandidate": primary_key,
            "deploymentCandidate": primary_key if candidate_passes_stability else None,
            "robustnessStatus": "accepted" if candidate_passes_stability else "rejected_unstable",
            "reason": (
                "The longer-history candidate improves selection, untouched holdout, and the required share of holdout calendar years."
                if candidate_passes_stability else
                f"The candidate wins only {holdout_year_wins} of {len(holdout_year_comparison)} untouched holdout years; {required_holdout_year_wins} are required, so no deployment candidate is accepted."
            ),
        },
        "dataCompleteness": {
            "calendarStart": display_index.min().strftime("%Y-%m"),
            "calendarEnd": display_index.max().strftime("%Y-%m"),
            "calendarMonths": int(len(display_index)),
            "publishedMonths": int(published_count),
            "notApplicableMonths": int(not_applicable_count),
            "pendingOrUnavailableMonths": int(pending_count),
            "structuralRule": "From 2012 onward, January and February have no separate official monthly retail-sales YoY; NBS publishes a combined Jan-Feb cumulative figure.",
        },
        "latestForecast": {
            "month": frame.index[-1].strftime("%Y-%m"),
            "model": round(float(latest[primary_key]), 4) if pd.notna(latest[primary_key]) else None,
            "consensus": round(float(latest["consensus"]), 4) if pd.notna(latest["consensus"]) else None,
            "selectedFactors": ranked_topk_sets[primary_key.removeprefix("seasonalGated")] if ranked_current_month_complete else [],
            "hfCorrection": round(corrections.get(frame.index[-1], 0.0), 4) if preliminary_complete else None,
            "alternatives": {
                key: (
                    round(float(latest[key]), 4)
                    if pd.notna(latest[key]) and (preliminary_complete or key in ("seasonalBackbone", "seasonalBias", "seasonalHf"))
                    else None
                )
                for key in (
                    "seasonalBackbone", "seasonalBias", "directCarArx", "directCarHomeArx",
                    "anchorCarBridge", "anchorCarHomeBridge", "seasonalHf",
                )
            },
            "stages": {
                "preliminary": {
                    "key": "seasonalGatedBridge",
                    "value": round(float(latest["seasonalGatedBridge"]), 4) if pd.notna(latest["seasonalGatedBridge"]) else None,
                    "status": "available" if pd.notna(latest["seasonalGatedBridge"]) else "waiting_for_complete_or_same_window_hf",
                },
                "preReleaseReview": {
                    "key": primary_key,
                    "value": round(float(latest[primary_key]), 4) if pd.notna(latest[primary_key]) else None,
                    "status": "available" if pd.notna(latest[primary_key]) else "waiting_for_complete_current_month_inputs",
                },
            },
        },
        "history": display_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    result = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "modelVersion": result["modelVersion"], "metrics": result["metrics"],
        "consensusCommonSample": result["consensusCommonSample"],
        "latestForecast": result["latestForecast"],
        "topCorrelations": result["correlations"][:5],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
