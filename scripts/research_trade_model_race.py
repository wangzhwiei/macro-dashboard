#!/usr/bin/env python3
"""No-look-ahead model race for China trade nowcasting research.

Consensus is loaded only after standalone model predictions have been produced
and is used solely as an evaluation benchmark.  It is never a regressor,
training target, residual target, model-selection signal, or forecast anchor.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "scripts" / "trade_forecast_model.py"
TARGET_PATH = ROOT / "data" / "trade-model" / "trade_targets_ifind.csv"
ANCHOR_FACTOR_PATH = ROOT / "data" / "trade-model" / "trade_anchor_factors.json"
PARTNER_IMPORT_FACTOR_PATH = ROOT / "data" / "trade-model" / "trade_partner_import_factors.json"
DASHBOARD_PATH = ROOT / "public" / "data" / "dashboard.json"
START = pd.Timestamp("2024-07-31")
PARTNER_PREFERRED_LAGS = {
    # Locked using correlations available before START; larger lags are used
    # only as real-time fallbacks when the preferred observation is unpublished.
    "korea_imports_from_china_yoy": 0,
    "brazil_imports_from_china_yoy": 0,
    "eu27_imports_from_china_yoy": 2,
    "taiwan_imports_from_mainland_yoy": 1,
    "thailand_imports_from_china_yoy": 1,
}
EXPORT_FIXED_FACTORS = (
    "korea_imports_from_china_yoy_lag0",
    "taiwan_imports_from_mainland_yoy_lag1",
    "thailand_imports_from_china_yoy_lag1",
)
IMPORT_FIXED_FACTORS = ("korea_export_yoy_d1",)
CNY_DATES = {
    2020: "2020-01-25", 2021: "2021-02-12", 2022: "2022-02-01",
    2023: "2023-01-22", 2024: "2024-02-10", 2025: "2025-01-29",
    2026: "2026-02-17", 2027: "2027-02-06",
}


def load_base():
    spec = importlib.util.spec_from_file_location("trade_forecast_model", MODEL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ridge(design: np.ndarray, target: np.ndarray, alpha: float) -> np.ndarray:
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    return np.linalg.pinv(design.T @ design + penalty) @ design.T @ target


def direct_bridge(base, target: pd.Series, features: pd.DataFrame, day: pd.Timestamp,
                  alpha: float = 4.0) -> tuple[float | None, list[str], dict[str, float]]:
    train_y = target.loc[target.index < day].dropna()
    train_x = features.loc[features.index < day]
    selected = base._select_features(train_y, train_x)
    if len(selected) < 2:
        return None, selected, {}
    x = train_x[selected].reindex(train_y.index)
    usable = x.notna().sum(axis=1) >= max(2, len(selected) // 2)
    x, y = x.loc[usable], train_y.loc[usable]
    if len(y) < base.MIN_FACTOR_TRAIN:
        return None, selected, {}
    means, stds = x.mean(), x.std().replace(0, np.nan)
    z = ((x.fillna(means) - means) / stds).fillna(0.0)
    regressors = pd.concat([y.shift(1).rename("lag"), z], axis=1).dropna()
    y_reg = y.reindex(regressors.index)
    beta = ridge(np.column_stack([np.ones(len(regressors)), regressors.to_numpy()]),
                 y_reg.to_numpy(), alpha)
    lag = float(train_y.iloc[-1])
    now = ((features[selected].reindex([day]).fillna(means) - means) / stds).fillna(0.0).iloc[0]
    prediction = float(np.r_[1.0, lag, now.to_numpy()] @ beta)
    contributions = {name: float(value * weight) for name, value, weight in zip(selected, now, beta[2:])}
    return prediction, selected, contributions


def seasonal_backbone(target: pd.Series, day: pd.Timestamp, key: str) -> tuple[float, pd.Series]:
    """Regularized seasonal autoregression fitted using observations before day."""
    if key == "exports":
        mode, lags, alpha = "level", (1, 2, 3), 100.0
    else:
        mode, lags, alpha = "y12_change", (1, 2, 3, 6, 12), 1.0
    index = pd.date_range(target.index.min(), day, freq="ME")
    aligned_target = target.reindex(index)
    design = pd.DataFrame(index=index)
    for lag in lags:
        design[f"target_l{lag}"] = aligned_target.shift(lag)
    design["month_sin"] = np.sin(2 * np.pi * design.index.month / 12)
    design["month_cos"] = np.cos(2 * np.pi * design.index.month / 12)
    regression_target = aligned_target if mode == "level" else aligned_target - aligned_target.shift(12)
    training = pd.concat([regression_target.rename("y"), design], axis=1)
    training = training.loc[training.index < day].dropna()
    x = training.drop(columns="y")
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = ridge(np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha)
    now = (design.loc[day] - means) / stds
    prediction = float(np.r_[1.0, now.to_numpy()] @ beta)
    fitted = pd.Series(
        np.column_stack([np.ones(len(z)), z.to_numpy()]) @ beta,
        index=training.index,
    )
    if mode == "y12_change":
        prediction += float(target.loc[day - pd.offsets.MonthEnd(12)])
        fitted = fitted + aligned_target.shift(12).reindex(fitted.index)
    residuals = aligned_target.reindex(fitted.index) - fitted
    return prediction, residuals.dropna()


def high_frequency_residual_correction(
    residuals: pd.Series, features: pd.DataFrame, day: pd.Timestamp,
    alpha: float = 30.0, cap: float = 2.5, max_features: int = 3,
) -> tuple[float, list[str], dict[str, float]]:
    """Explain the backbone residual with a small, heavily regularized HF block."""
    scored: list[tuple[float, str]] = []
    for column in features:
        joined = pd.concat(
            [residuals.rename("y"), features[column].rename("x")], axis=1, sort=False
        ).dropna()
        if len(joined) >= 12 and joined["x"].std() > 1e-12:
            correlation = joined["y"].corr(joined["x"])
            if pd.notna(correlation):
                scored.append((abs(float(correlation)), column))
    selected, used = [], set()
    for _, column in sorted(scored, reverse=True):
        family = column.rsplit("_", 1)[0]
        if family in used:
            continue
        selected.append(column)
        used.add(family)
        if len(selected) >= max_features:
            break
    if not selected or day not in features.index or features.loc[day, selected].isna().any():
        return 0.0, selected, {}
    training = pd.concat(
        [residuals.rename("y"), features[selected]], axis=1, sort=False
    ).dropna()
    means, stds = training[selected].mean(), training[selected].std().replace(0, 1.0)
    z = (training[selected] - means) / stds
    beta = ridge(np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha)
    now = (features.loc[day, selected] - means) / stds
    raw = float(np.r_[1.0, now.to_numpy()] @ beta)
    correction = float(np.clip(raw, -cap, cap))
    contributions = {
        name: float(value * weight) for name, value, weight in zip(selected, now, beta[1:])
    }
    return correction, selected, contributions


def factor_bridge(base, target: pd.Series, features: pd.DataFrame, day: pd.Timestamp):
    train = target.loc[target.index < day].dropna()
    lag = float(train.iloc[-1])
    fit = base._fit_at(target, features.loc[:day], day, lag)
    return fit


def metrics(frame: pd.DataFrame, column: str) -> dict[str, float | int | str]:
    sample = frame[[column, "actual"]].dropna()
    error = sample[column] - sample["actual"]
    return {
        "rmse": round(float(np.sqrt(np.mean(error ** 2))), 4),
        "mae": round(float(np.mean(np.abs(error))), 4),
        "direction_hit_pct": round(float(np.mean(np.sign(sample[column]) == np.sign(sample["actual"])) * 100), 2),
        "observations": int(len(sample)),
        "sample_start": sample.index.min().strftime("%Y-%m"),
        "sample_end": sample.index.max().strftime("%Y-%m"),
    }


def read_consensus(key: str) -> pd.Series:
    path = ROOT / "data" / "trade-model" / f"baseline_{key[:-1] if key.endswith('s') else key}_yoy.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("data", [])
    series = pd.Series({pd.Timestamp(row[0]) + pd.offsets.MonthEnd(0): float(row[1]) for row in rows}, dtype=float)
    return series.sort_index()


def read_anchor_factors(end: pd.Timestamp) -> dict[str, pd.Series]:
    payload = json.loads(ANCHOR_FACTOR_PATH.read_text(encoding="utf-8"))
    output = {}
    for key, item in payload["series"].items():
        series = pd.Series(
            {pd.Timestamp(row[0]) + pd.offsets.MonthEnd(0): float(row[1]) for row in item["data"]},
            dtype=float,
        ).sort_index()
        output[key] = series.reindex(pd.date_range(series.index.min(), end, freq="ME"))
    return output


def read_partner_import_factors(end: pd.Timestamp) -> pd.DataFrame:
    """Return release-safe bilateral-import YoY candidates at multiple lags."""
    payload = json.loads(PARTNER_IMPORT_FACTOR_PATH.read_text(encoding="utf-8"))
    output = {}
    for key, item in payload["series"].items():
        series = pd.Series(
            {pd.Timestamp(row[0]) + pd.offsets.MonthEnd(0): float(row[1]) for row in item["data"]},
            dtype=float,
        ).sort_index()
        series = series.reindex(pd.date_range(series.index.min(), end, freq="ME"))
        if item.get("transform") == "yoy_from_monthly_value":
            series = series.pct_change(12, fill_method=None) * 100
        minimum_lag = int(item["availabilityLagMonths"])
        family = key.replace("_value", "_yoy")
        for lag in range(minimum_lag, minimum_lag + 3):
            output[f"{family}_lag{lag}"] = series.shift(lag)
    start = min(series.index.min() for series in output.values())
    return pd.DataFrame(output).reindex(pd.date_range(start, end, freq="ME"))


def destination_import_prediction(
    target: pd.Series, day: pd.Timestamp, end: pd.Timestamp,
    alpha: float = 1.0, max_features: int = 3,
) -> tuple[float | None, list[str], dict[str, float], dict[str, float]]:
    """Predict exports from release-safe destination imports using past data only."""
    features = read_partner_import_factors(end)
    prior_target = target.loc[target.index < day].dropna()
    correlations = {}
    for column in features:
        joined = pd.concat(
            [prior_target.rename("y"), features[column].rename("x")], axis=1, sort=False
        ).dropna()
        if len(joined) >= 24 and joined["x"].std() > 1e-12:
            value = joined["y"].corr(joined["x"])
            if pd.notna(value):
                correlations[column] = float(value)
    available_by_family = {}
    for family, preferred_lag in PARTNER_PREFERRED_LAGS.items():
        for lag in range(preferred_lag, preferred_lag + 3):
            column = f"{family}_lag{lag}"
            if column in features and day in features.index and pd.notna(features.loc[day, column]):
                available_by_family[family] = column
                break
    selected = sorted(
        available_by_family.values(),
        key=lambda column: abs(correlations.get(column, 0.0)),
        reverse=True,
    )[:max_features]
    if not selected:
        return None, [], {}, correlations
    training = pd.concat(
        [prior_target.rename("y"), features[selected]], axis=1, sort=False
    ).dropna()
    if len(training) < 24:
        return None, selected, {}, correlations
    x = training[selected]
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = ridge(
        np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha
    )
    now = (features.loc[day, selected] - means) / stds
    prediction = float(np.r_[1.0, now.to_numpy()] @ beta)
    contributions = {
        name: float(value * weight) for name, value, weight in zip(selected, now, beta[1:])
    }
    return prediction, selected, contributions, correlations


def destination_import_fixed_prediction(
    target: pd.Series, day: pd.Timestamp, end: pd.Timestamp, alpha: float = 1.0,
) -> tuple[float | None, list[str], dict[str, float]]:
    """Fixed export factor structure; return no forecast if any factor is unpublished."""
    features = read_partner_import_factors(end)
    selected = list(EXPORT_FIXED_FACTORS)
    if day not in features.index or any(name not in features for name in selected):
        return None, selected, {}
    if features.loc[day, selected].isna().any():
        return None, selected, {}
    prior = target.loc[target.index < day].dropna()
    training = pd.concat([prior.rename("y"), features[selected]], axis=1, sort=False).dropna()
    if len(training) < 24:
        return None, selected, {}
    x = training[selected]
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = ridge(
        np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha
    )
    now = (features.loc[day, selected] - means) / stds
    prediction = float(np.r_[1.0, now.to_numpy()] @ beta)
    contributions = {
        name: float(value * weight) for name, value, weight in zip(selected, now, beta[1:])
    }
    return prediction, selected, contributions


def destination_import_fixed_cny_prediction(
    target: pd.Series, day: pd.Timestamp, end: pd.Timestamp, alpha: float = 5.0,
) -> tuple[float | None, bool, list[str], dict[str, float]]:
    """Final fixed export structure with a Q1-only deterministic CNY block."""
    baseline, selected, baseline_contributions = destination_import_fixed_prediction(target, day, end)
    if baseline is None or day.month not in (1, 2, 3):
        return baseline, False, selected, baseline_contributions
    partner = read_partner_import_factors(end)
    calendar_columns = [
        "cny_rush_weekdays_yoy", "cny_shutdown_weekdays_yoy", "cny_recovery_weekdays_yoy",
    ]
    calendar = cny_calendar_features(pd.date_range(target.index.min(), end, freq="ME"))
    x_all = pd.concat([partner[selected], calendar[calendar_columns]], axis=1, sort=False)
    prior = target.loc[target.index < day].dropna()
    training = pd.concat([prior.rename("y"), x_all], axis=1, sort=False).dropna()
    if len(training) < 24:
        return baseline, False, selected, baseline_contributions
    x = training.drop(columns="y")
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = ridge(
        np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha
    )
    now = (x_all.loc[day] - means) / stds
    prediction = float(np.r_[1.0, now.to_numpy()] @ beta)
    contributions = {
        name: float(value * weight) for name, value, weight in zip(x.columns, now, beta[1:])
    }
    return prediction, True, selected + calendar_columns, contributions


def _cny_weekday_count(start: pd.Timestamp, end: pd.Timestamp, month: pd.Timestamp) -> int:
    days = pd.date_range(start, end, freq="D")
    return int(((days.weekday < 5) & (days.to_period("M") == month.to_period("M"))).sum())


def cny_calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Known-in-advance YoY shifts in pre-CNY rush, shutdown and recovery windows."""
    rows = []
    for day in index:
        current = pd.Timestamp(CNY_DATES[day.year])
        previous = pd.Timestamp(CNY_DATES[day.year - 1])

        def counts(cny: pd.Timestamp, reference: pd.Timestamp) -> tuple[int, int, int]:
            return (
                _cny_weekday_count(cny - pd.Timedelta(days=14), cny - pd.Timedelta(days=1), reference),
                _cny_weekday_count(cny, cny + pd.Timedelta(days=13), reference),
                _cny_weekday_count(cny + pd.Timedelta(days=14), cny + pd.Timedelta(days=27), reference),
            )

        now = counts(current, day)
        old = counts(previous, day - pd.DateOffset(years=1))
        rows.append({
            "date": day,
            "cny_rush_weekdays_yoy": float(now[0] - old[0]),
            "cny_shutdown_weekdays_yoy": float(now[1] - old[1]),
            "cny_recovery_weekdays_yoy": float(now[2] - old[2]),
        })
    return pd.DataFrame(rows).set_index("date")


def destination_import_cny_gated_prediction(
    target: pd.Series, day: pd.Timestamp, end: pd.Timestamp, alpha: float = 5.0,
) -> tuple[float | None, bool, list[str], dict[str, float]]:
    """Apply a calendar-augmented partner bridge only in January-March."""
    baseline, baseline_selected, baseline_contributions, _ = destination_import_prediction(
        target, day, end
    )
    if day.month not in (1, 2, 3):
        return baseline, False, [], {}

    partner = read_partner_import_factors(end)
    prior = target.loc[target.index < day].dropna()
    correlations = {}
    for column in partner:
        joined = pd.concat(
            [prior.rename("y"), partner[column].rename("x")], axis=1, sort=False
        ).dropna()
        if len(joined) >= 24 and joined["x"].std() > 1e-12:
            value = joined["y"].corr(joined["x"])
            if pd.notna(value):
                correlations[column] = float(value)
    available = {}
    for family, preferred_lag in PARTNER_PREFERRED_LAGS.items():
        for lag in range(preferred_lag, preferred_lag + 3):
            column = f"{family}_lag{lag}"
            if column in partner and day in partner.index and pd.notna(partner.loc[day, column]):
                available[family] = column
                break
    selected = sorted(
        available.values(), key=lambda name: abs(correlations.get(name, 0.0)), reverse=True
    )[:3]
    calendar = cny_calendar_features(pd.date_range(target.index.min(), end, freq="ME"))
    calendar_columns = [
        "cny_rush_weekdays_yoy", "cny_shutdown_weekdays_yoy", "cny_recovery_weekdays_yoy",
    ]
    x_all = pd.concat([partner[selected], calendar[calendar_columns]], axis=1, sort=False)
    training = pd.concat([prior.rename("y"), x_all], axis=1, sort=False).dropna()
    if len(training) < 24:
        return baseline, False, baseline_selected, baseline_contributions
    x = training.drop(columns="y")
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = ridge(
        np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha
    )
    now = (x_all.loc[day] - means) / stds
    prediction = float(np.r_[1.0, now.to_numpy()] @ beta)
    contributions = {
        name: float(value * weight) for name, value, weight in zip(x.columns, now, beta[1:])
    }
    return prediction, True, selected + calendar_columns, contributions


def anchor_feature_pool(key: str, end: pd.Timestamp) -> pd.DataFrame:
    factors = read_anchor_factors(end)
    if key == "exports":
        return pd.DataFrame({
            "vietnam_export_yoy_l1_d1": factors["vietnam_export_yoy"].shift(1).diff(),
            "pmi_new_export_orders_m3": factors["pmi_new_export_orders"].diff(3) / 3,
        })
    return pd.DataFrame({
        "korea_export_yoy_d1": factors["korea_export_yoy"].diff(),
        "pmi_new_export_orders_d1": factors["pmi_new_export_orders"].diff(),
        "pmi_imports_d1": factors["pmi_imports"].diff(),
    })


def export_residual_feature_pool(end: pd.Timestamp) -> pd.DataFrame:
    """Release-safe export levels used to explain the seasonal-model residual.

    Vietnam is deliberately lagged one month.  Its same-month value is not
    consistently present in the stored real-time snapshot, and the lag-zero
    walk-forward experiment performs worse than the lag-one specification.
    """
    factors = read_anchor_factors(end)
    return pd.DataFrame({
        "vietnam_export_yoy_l1_level": factors["vietnam_export_yoy"].shift(1),
        "pmi_new_export_orders_level": factors["pmi_new_export_orders"],
    })


def corrected_export_prediction(
    target: pd.Series, day: pd.Timestamp, end: pd.Timestamp,
) -> tuple[float, float, float, list[str], dict[str, float]]:
    """Seasonal export backbone plus a bounded, past-only factor residual."""
    seasonal, residuals = seasonal_backbone(target, day, "exports")
    feature_pool = export_residual_feature_pool(end)
    correction, selected, contributions = high_frequency_residual_correction(
        residuals, feature_pool.loc[:day], day,
        alpha=10.0, cap=5.0, max_features=2,
    )
    return seasonal + correction, seasonal, correction, selected, contributions


def anchored_factor_prediction(
    target: pd.Series, feature_pool: pd.DataFrame, day: pd.Timestamp, key: str,
    min_abs_correlation: float = 0.25, alpha: float = 1.0, cap: float = 15.0,
) -> tuple[float, float, list[str], dict[str, float], dict[str, float]]:
    """Previous official value plus a past-only, high-correlation factor change."""
    prior = target.loc[target.index < day].dropna()
    anchor = float(prior.iloc[-1])
    target_change = target.diff().loc[target.index < day].dropna()
    correlations = {}
    for column in feature_pool:
        joined = pd.concat(
            [target_change.rename("y"), feature_pool[column].rename("x")], axis=1, sort=False
        ).dropna()
        if len(joined) >= 24 and joined["x"].std() > 1e-12:
            value = joined["y"].corr(joined["x"])
            if pd.notna(value):
                correlations[column] = float(value)
    max_features = 2 if key == "exports" else 1
    selected = [
        column for column, value in sorted(correlations.items(), key=lambda item: abs(item[1]), reverse=True)
        if abs(value) >= min_abs_correlation and day in feature_pool.index
        and pd.notna(feature_pool.loc[day, column])
    ][:max_features]
    if not selected:
        return anchor, 0.0, [], {}, correlations
    training = pd.concat(
        [target_change.rename("y"), feature_pool[selected]], axis=1, sort=False
    ).loc[lambda frame: frame.index < day].dropna()
    if len(training) < 24:
        return anchor, 0.0, [], {}, correlations
    x = training[selected]
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = ridge(
        np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha
    )
    now = (feature_pool.loc[day, selected] - means) / stds
    raw_change = float(np.r_[1.0, now.to_numpy()] @ beta)
    predicted_change = float(np.clip(raw_change, -cap, cap))
    contributions = {
        name: float(value * weight) for name, value, weight in zip(selected, now, beta[1:])
    }
    return anchor + predicted_change, predicted_change, selected, contributions, correlations


def import_cny_gated_prediction(
    target: pd.Series, feature_pool: pd.DataFrame, day: pd.Timestamp,
    alpha: float = 10.0, cap: float = 15.0,
) -> tuple[float, bool, float, list[str], dict[str, float]]:
    """Parallel import candidate; the original anchored model remains untouched."""
    baseline, baseline_change, baseline_selected, baseline_contributions, _ = (
        anchored_factor_prediction(target, feature_pool, day, "imports")
    )
    if day.month not in (1, 2, 3):
        return baseline, False, baseline_change, baseline_selected, baseline_contributions

    prior = target.loc[target.index < day].dropna()
    anchor = float(prior.iloc[-1])
    target_change = target.diff().loc[target.index < day].dropna()
    correlations = {}
    for column in feature_pool:
        joined = pd.concat(
            [target_change.rename("y"), feature_pool[column].rename("x")], axis=1, sort=False
        ).dropna()
        if len(joined) >= 24 and joined["x"].std() > 1e-12:
            value = joined["y"].corr(joined["x"])
            if pd.notna(value):
                correlations[column] = float(value)
    original_selected = [
        name for name, value in sorted(correlations.items(), key=lambda item: abs(item[1]), reverse=True)
        if abs(value) >= 0.25 and day in feature_pool.index and pd.notna(feature_pool.loc[day, name])
    ][:1]
    calendar_columns = [
        "cny_rush_weekdays_yoy", "cny_shutdown_weekdays_yoy", "cny_recovery_weekdays_yoy",
    ]
    calendar = cny_calendar_features(pd.date_range(target.index.min(), feature_pool.index.max(), freq="ME"))
    x_all = pd.concat([feature_pool[original_selected], calendar[calendar_columns]], axis=1, sort=False)
    training = pd.concat([target_change.rename("y"), x_all], axis=1, sort=False)
    training = training.loc[training.index < day].dropna()
    if len(training) < 24:
        return baseline, False, baseline_change, baseline_selected, baseline_contributions
    x = training.drop(columns="y")
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = ridge(
        np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha
    )
    now = (x_all.loc[day] - means) / stds
    predicted_change = float(np.clip(np.r_[1.0, now.to_numpy()] @ beta, -cap, cap))
    contributions = {
        name: float(value * weight) for name, value, weight in zip(x.columns, now, beta[1:])
    }
    return anchor + predicted_change, True, predicted_change, original_selected + calendar_columns, contributions


def import_fixed_prediction(
    target: pd.Series, feature_pool: pd.DataFrame, day: pd.Timestamp,
    alpha: float = 1.0, cap: float = 15.0,
) -> tuple[float | None, float | None, list[str], dict[str, float]]:
    """Fixed Korea-export bridge; missing current data means no import forecast."""
    selected = list(IMPORT_FIXED_FACTORS)
    if day not in feature_pool.index or any(name not in feature_pool for name in selected):
        return None, None, selected, {}
    if feature_pool.loc[day, selected].isna().any():
        return None, None, selected, {}
    prior = target.loc[target.index < day].dropna()
    anchor = float(prior.iloc[-1])
    target_change = target.diff().loc[target.index < day].dropna()
    training = pd.concat(
        [target_change.rename("y"), feature_pool[selected]], axis=1, sort=False
    ).dropna()
    if len(training) < 24:
        return None, None, selected, {}
    x = training[selected]
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = ridge(
        np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha
    )
    now = (feature_pool.loc[day, selected] - means) / stds
    predicted_change = float(np.clip(np.r_[1.0, now.to_numpy()] @ beta, -cap, cap))
    contributions = {
        name: float(value * weight) for name, value, weight in zip(selected, now, beta[1:])
    }
    return anchor + predicted_change, predicted_change, selected, contributions


def import_fixed_cny_prediction(
    target: pd.Series, feature_pool: pd.DataFrame, day: pd.Timestamp,
    alpha: float = 10.0, cap: float = 15.0,
) -> tuple[float | None, bool, float | None, list[str], dict[str, float]]:
    """Final fixed import structure with a Q1-only deterministic CNY block."""
    baseline, baseline_change, selected, baseline_contributions = import_fixed_prediction(
        target, feature_pool, day
    )
    if baseline is None or day.month not in (1, 2, 3):
        return baseline, False, baseline_change, selected, baseline_contributions
    calendar_columns = [
        "cny_rush_weekdays_yoy", "cny_shutdown_weekdays_yoy", "cny_recovery_weekdays_yoy",
    ]
    calendar = cny_calendar_features(
        pd.date_range(target.index.min(), feature_pool.index.max(), freq="ME")
    )
    x_all = pd.concat([feature_pool[selected], calendar[calendar_columns]], axis=1, sort=False)
    prior = target.loc[target.index < day].dropna()
    anchor = float(prior.iloc[-1])
    target_change = target.diff().loc[target.index < day].dropna()
    training = pd.concat([target_change.rename("y"), x_all], axis=1, sort=False)
    training = training.loc[training.index < day].dropna()
    if len(training) < 24:
        return baseline, False, baseline_change, selected, baseline_contributions
    x = training.drop(columns="y")
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = ridge(
        np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha
    )
    now = (x_all.loc[day] - means) / stds
    predicted_change = float(np.clip(np.r_[1.0, now.to_numpy()] @ beta, -cap, cap))
    contributions = {
        name: float(value * weight) for name, value, weight in zip(x.columns, now, beta[1:])
    }
    return anchor + predicted_change, True, predicted_change, selected + calendar_columns, contributions


def run_target(base, dashboard: dict, target: pd.Series, key: str):
    features = base.build_features(dashboard, key)
    anchor_features = anchor_feature_pool(key, features.dropna(how="all").index.max())
    consensus_series = read_consensus(key)
    rows, latest_attribution = [], {}
    bridge_errors, ar_errors = [], []
    for day in pd.date_range(START, features.dropna(how="all").index.max(), freq="ME"):
        if day not in target.index or pd.isna(target.loc[day]):
            continue
        fit = factor_bridge(base, target, features, day)
        direct, selected, attribution = direct_bridge(base, target, features, day)
        seasonal, backbone_residuals = seasonal_backbone(target, day, key)
        hf_correction, hf_features, hf_attribution = high_frequency_residual_correction(
            backbone_residuals, features.loc[:day], day
        )
        # Development validation rejects the HF increment for exports; imports
        # retain it because it improves standalone RMSE. Consensus is not used.
        hf_enabled = key == "imports"
        seasonal_hf = seasonal + hf_correction if hf_enabled else seasonal
        anchored, anchored_change, anchored_features, anchored_attribution, factor_correlations = (
            anchored_factor_prediction(target, anchor_features, day, key)
        )
        if key == "imports":
            import_cny, import_cny_active, import_cny_change, import_cny_features, import_cny_attribution = (
                import_cny_gated_prediction(target, anchor_features, day)
            )
            import_fixed, import_fixed_change, import_fixed_features, import_fixed_attribution = (
                import_fixed_prediction(target, anchor_features, day)
            )
            import_fixed_cny, import_fixed_cny_active, import_fixed_cny_change, import_fixed_cny_features, import_fixed_cny_attribution = (
                import_fixed_cny_prediction(target, anchor_features, day)
            )
        else:
            import_cny, import_cny_active, import_cny_change = np.nan, False, np.nan
            import_cny_features, import_cny_attribution = [], {}
            import_fixed, import_fixed_change, import_fixed_cny, import_fixed_cny_change = np.nan, np.nan, np.nan, np.nan
            import_fixed_features, import_fixed_attribution = [], {}
            import_fixed_cny_active, import_fixed_cny_features, import_fixed_cny_attribution = False, [], {}
        if key == "exports":
            corrected_export, export_seasonal, export_correction, export_features, export_attribution = (
                corrected_export_prediction(target, day, anchor_features.index.max())
            )
            destination_import, destination_features, destination_attribution, destination_correlations = (
                destination_import_prediction(target, day, anchor_features.index.max())
            )
            cny_gated, cny_gate_active, cny_features, cny_attribution = (
                destination_import_cny_gated_prediction(target, day, anchor_features.index.max())
            )
            export_fixed, export_fixed_features, export_fixed_attribution = (
                destination_import_fixed_prediction(target, day, anchor_features.index.max())
            )
            export_fixed_cny, export_fixed_cny_active, export_fixed_cny_features, export_fixed_cny_attribution = (
                destination_import_fixed_cny_prediction(target, day, anchor_features.index.max())
            )
        else:
            corrected_export, export_seasonal, export_correction = np.nan, np.nan, np.nan
            export_features, export_attribution = [], {}
            destination_import, destination_features = np.nan, []
            destination_attribution, destination_correlations = {}, {}
            cny_gated, cny_gate_active, cny_features, cny_attribution = np.nan, False, [], {}
            export_fixed, export_fixed_cny = np.nan, np.nan
            export_fixed_features, export_fixed_attribution = [], {}
            export_fixed_cny_active, export_fixed_cny_features, export_fixed_cny_attribution = False, [], {}
        consensus_now = float(consensus_series.loc[day]) if day in consensus_series.index else np.nan
        if fit.bridge is None:
            weight = 0.0
        elif len(bridge_errors) >= 6:
            br = max(float(np.sqrt(np.mean(np.square(bridge_errors[-12:])))), .05)
            ar = max(float(np.sqrt(np.mean(np.square(ar_errors[-12:])))), .05)
            weight = float(np.clip((1 / br) / (1 / br + 1 / ar), .2, .8))
        else:
            weight = .5
        ensemble = fit.ar if fit.bridge is None else weight * fit.bridge + (1 - weight) * fit.ar
        actual = float(target.loc[day])
        rows.append({
            "date": day, "actual": actual, "ar": fit.ar,
            "dfm_bridge": fit.bridge, "dfm_ar_ensemble": ensemble,
            "direct_ridge_bridge": direct, "seasonal_ridge": seasonal,
            "seasonal_hf_gated": seasonal_hf, "anchored_factor": anchored,
            "seasonal_factor_corrected": corrected_export,
            "destination_import_bridge": destination_import,
            "destination_import_cny_gated": cny_gated,
            "export_fixed_bridge": export_fixed,
            "export_fixed_cny_gated": export_fixed_cny,
            "import_cny_gated": import_cny,
            "import_fixed_bridge": import_fixed,
            "import_fixed_cny_gated": import_fixed_cny,
            "consensus": consensus_now,
        })
        if fit.bridge is not None:
            bridge_errors.append(fit.bridge - actual)
        ar_errors.append(fit.ar - actual)
        latest_attribution = {
            "month": day.strftime("%Y-%m"), "features": selected,
            "feature_contributions": attribution,
            "hf_gate_enabled": hf_enabled,
            "standalone_residual_features": hf_features,
            "standalone_residual_contributions": hf_attribution,
            "standalone_residual_correction": hf_correction if hf_enabled else 0.0,
            "anchor_factor_features": anchored_features,
            "anchor_factor_correlations": factor_correlations,
            "anchor_factor_contributions": anchored_attribution,
            "anchor_factor_predicted_change": anchored_change,
            "corrected_export_seasonal_backbone": export_seasonal,
            "corrected_export_residual_features": export_features,
            "corrected_export_residual_contributions": export_attribution,
            "corrected_export_residual_correction": export_correction,
            "destination_import_features": destination_features,
            "destination_import_correlations": destination_correlations,
            "destination_import_contributions": destination_attribution,
            "cny_calendar_gate_active": cny_gate_active,
            "cny_calendar_features": cny_features,
            "cny_calendar_contributions": cny_attribution,
            "import_cny_gate_active": import_cny_active,
            "import_cny_predicted_change": import_cny_change,
            "import_cny_features": import_cny_features,
            "import_cny_contributions": import_cny_attribution,
            "export_fixed_features": export_fixed_features,
            "export_fixed_contributions": export_fixed_attribution,
            "export_fixed_cny_gate_active": export_fixed_cny_active,
            "export_fixed_cny_features": export_fixed_cny_features,
            "export_fixed_cny_contributions": export_fixed_cny_attribution,
            "import_fixed_features": import_fixed_features,
            "import_fixed_contributions": import_fixed_attribution,
            "import_fixed_cny_gate_active": import_fixed_cny_active,
            "import_fixed_cny_features": import_fixed_cny_features,
            "import_fixed_cny_contributions": import_fixed_cny_attribution,
        }
    frame = pd.DataFrame(rows).set_index("date")
    columns = [
        "ar", "dfm_bridge", "dfm_ar_ensemble", "direct_ridge_bridge",
        "seasonal_ridge", "seasonal_hf_gated", "anchored_factor",
    ]
    if key == "exports":
        columns.extend([
            "seasonal_factor_corrected", "destination_import_bridge",
            "destination_import_cny_gated",
            "export_fixed_bridge", "export_fixed_cny_gated",
        ])
    else:
        columns.extend(["import_cny_gated", "import_fixed_bridge", "import_fixed_cny_gated"])
    columns.append("consensus")
    scores = {column: metrics(frame, column) for column in columns}
    common = frame.loc[frame["consensus"].notna()].copy()
    common_scores = {column: metrics(common, column) for column in columns}
    standalone = [column for column in columns if column != "consensus"]
    winner = min(standalone, key=lambda column: common_scores[column]["rmse"])
    missing_consensus = [day.strftime("%Y-%m") for day in frame.index[frame["consensus"].isna()]]
    return frame, scores, common_scores, winner, missing_consensus, latest_attribution


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-month",
        help="Optional forecast month in YYYY-MM format; defaults to the first month without an official target.",
    )
    args = parser.parse_args()
    target_day = None
    if args.target_month:
        try:
            target_day = pd.Timestamp(f"{args.target_month}-01") + pd.offsets.MonthEnd(0)
        except ValueError as error:
            raise SystemExit(f"invalid --target-month {args.target_month!r}; expected YYYY-MM") from error

    base = load_base()
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8-sig"))
    targets = base.read_targets(TARGET_PATH)
    output = {
        "status": "IFIND_FIXED_FACTOR_MODEL_APPROVED_FOR_PUBLICATION",
        "target_source": "iFinD EDB / GACC USD current-month YoY",
        "consensus_role": "evaluation_benchmark_only",
        "forecast_factor_policy": "fixed factor families and fixed lags; coefficients re-estimated on an expanding window using only prior target observations; any missing fixed factor means no forecast and no fallback; both targets use Q1 CNY calendar gates; consensus prohibited",
        "partner_import_preferred_lags": PARTNER_PREFERRED_LAGS,
        "partner_import_lag_selection": "fixed from pre-2024-07 correlations; no older-lag fallback when a required observation is unavailable",
        "ifind_consensus": {
            "exports": {"id": "M005682256", "name": "预测平均值:出口金额(美元计价):当月同比"},
            "imports": {"id": "M005682257", "name": "预测平均值:进口金额(美元计价):当月同比"},
        },
        "targets": {},
    }
    csv_rows = []
    for key in ("exports", "imports"):
        frame, scores, common_scores, winner, missing_consensus, attribution = run_target(base, dashboard, targets[key], key)
        live_features = base.build_features(dashboard, key)
        # Forecast the first month without an official target.  Using the latest
        # daily feature month can jump ahead before the pending trade release is
        # published (for example, September 1 data while August is still due).
        default_live_day = targets[key].dropna().index.max() + pd.offsets.MonthEnd(1)
        live_day = target_day if target_day is not None else default_live_day
        live_backbone, live_residuals = seasonal_backbone(targets[key], live_day, key)
        live_correction, live_selected, live_contributions = high_frequency_residual_correction(
            live_residuals, live_features.loc[:live_day], live_day
        )
        live_hf_enabled = key == "imports"
        live_anchor_features = anchor_feature_pool(key, live_day)
        live_anchored, live_anchor_change, live_anchor_selected, live_anchor_contributions, live_correlations = (
            anchored_factor_prediction(targets[key], live_anchor_features, live_day, key)
        )
        if key == "exports":
            _, export_seasonal, export_correction, export_selected, export_contributions = (
                corrected_export_prediction(targets[key], live_day, live_day)
            )
            dynamic_forecast, destination_selected, destination_contributions, destination_correlations = (
                destination_import_prediction(targets[key], live_day, live_day)
            )
            fixed_forecast, fixed_selected, fixed_contributions = (
                destination_import_fixed_prediction(targets[key], live_day, live_day)
            )
            live_forecast, cny_gate_active, cny_selected, cny_contributions = (
                destination_import_fixed_cny_prediction(targets[key], live_day, live_day)
            )
            ungated_model_forecast = fixed_forecast
            legacy_dynamic_forecast = dynamic_forecast
            method = "export_fixed_factors_cny_gated"
            reported_selected = cny_selected
            reported_contributions = cny_contributions
            reported_correlations = destination_correlations
            partner_live = read_partner_import_factors(live_day)
            missing_factors = [
                name for name in EXPORT_FIXED_FACTORS
                if name not in partner_live or live_day not in partner_live.index
                or pd.isna(partner_live.loc[live_day, name])
            ]
        else:
            legacy_dynamic_forecast = live_anchored
            import_cny_forecast, import_cny_active, import_cny_change, import_cny_selected, import_cny_contributions = (
                import_cny_gated_prediction(targets[key], live_anchor_features, live_day)
            )
            fixed_forecast, fixed_change, fixed_selected, fixed_contributions = (
                import_fixed_prediction(targets[key], live_anchor_features, live_day)
            )
            live_forecast, import_cny_active, import_cny_change, import_cny_selected, import_cny_contributions = (
                import_fixed_cny_prediction(targets[key], live_anchor_features, live_day)
            )
            ungated_model_forecast = fixed_forecast
            export_seasonal, export_correction = live_backbone, 0.0
            export_selected, export_contributions = [], {}
            method = "import_fixed_factors_cny_gated"
            reported_selected = import_cny_selected
            reported_contributions = import_cny_contributions
            reported_correlations = live_correlations
            cny_gate_active, cny_selected, cny_contributions = (
                import_cny_active, import_cny_selected, import_cny_contributions
            )
            missing_factors = [
                name for name in IMPORT_FIXED_FACTORS
                if name not in live_anchor_features or live_day not in live_anchor_features.index
                or pd.isna(live_anchor_features.loc[live_day, name])
            ]
        if key == "exports":
            import_cny_forecast, import_cny_active, import_cny_change = np.nan, False, np.nan
            import_cny_selected, import_cny_contributions = [], {}
        output["targets"][key] = {
            "all_available_scores": scores,
            "common_sample_scores": common_scores,
            "common_sample_winner": winner,
            "missing_consensus_months": missing_consensus,
            "latest_attribution": attribution,
            "current_forecast": {
                "month": live_day.strftime("%Y-%m"),
                "forecast": round(float(live_forecast), 6) if live_forecast is not None else None,
                "status": "READY" if live_forecast is not None else "WAITING_FOR_FIXED_FACTORS",
                "missing_factors": missing_factors,
                "earliest_factor_release_date": (live_day + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                "method": method,
                "model_version": "fixed_factors_cny_gated_v1",
                "ungated_model_forecast": round(float(ungated_model_forecast), 6) if ungated_model_forecast is not None else None,
                "legacy_dynamic_model_forecast": round(float(legacy_dynamic_forecast), 6) if legacy_dynamic_forecast is not None else None,
                "previous_actual_anchor": round(float(targets[key].dropna().iloc[-1]), 6),
                "predicted_change": round(float(live_anchor_change), 6),
                "selected_factors": reported_selected,
                "factor_correlations": reported_correlations,
                "factor_contributions": reported_contributions,
                "seasonal_backbone": round(float(live_backbone), 6),
                "hf_gate_enabled": live_hf_enabled,
                "hf_correction": round(float(live_correction if live_hf_enabled else 0.0), 6),
                "hf_features": live_selected,
                "hf_contributions": live_contributions,
                "export_seasonal_backbone": round(float(export_seasonal), 6),
                "export_factor_correction": round(float(export_correction), 6),
                "export_factor_features": export_selected,
                "export_factor_contributions": export_contributions,
                "destination_import_features": destination_selected if key == "exports" else [],
                "destination_import_contributions": destination_contributions if key == "exports" else {},
                "cny_calendar_gate_active": cny_gate_active,
                "cny_calendar_features": cny_selected,
                "cny_calendar_contributions": cny_contributions,
                "parallel_import_cny_candidate": {
                    "forecast": round(float(import_cny_forecast), 6) if key == "imports" and import_cny_forecast is not None else None,
                    "gate_active": import_cny_active,
                    "predicted_change": (
                        round(float(import_cny_change), 6)
                        if key == "imports" and import_cny_change is not None else None
                    ),
                    "features": import_cny_selected,
                    "contributions": import_cny_contributions,
                    "original_model_preserved": True,
                },
                "data_as_of": dashboard.get("generatedAt"),
            },
        }
        table = frame.reset_index()
        table.insert(0, "target", key)
        csv_rows.append(table)
    out = ROOT / "outputs" / "trade-model-research"
    out.mkdir(parents=True, exist_ok=True)
    (out / "model-race.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.concat(csv_rows).to_csv(out / "model-race.csv", index=False)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def validate_ifind_series(meta: dict, expected: dict) -> None:
    """Fail closed on fuzzy iFinD matches before a series reaches a backtest."""
    actual_id = meta.get("index_id") or meta.get("providerId")
    actual_name = meta.get("name") or meta.get("series_name")
    actual_freq = str(meta.get("freq") or meta.get("frequency") or "").lower()
    if actual_id != expected["providerId"]:
        raise ValueError(f"iFinD providerId mismatch: {actual_id!r}")
    if actual_name != expected["name"]:
        raise ValueError(f"iFinD series name mismatch: {actual_name!r}")
    if actual_freq not in {"m", "month", "monthly", "月", "月频"}:
        raise ValueError(f"iFinD frequency mismatch: {actual_freq!r}")
    if meta.get("unit") != "%":
        raise ValueError(f"iFinD unit mismatch: {meta.get('unit')!r}")


if __name__ == "__main__":
    raise SystemExit(main())
