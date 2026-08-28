#!/usr/bin/env python3
"""Level-and-flow bridge for China's monthly published FAI cumulative growth."""

from __future__ import annotations

import argparse
import calendar
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "investment-model" / "source_data.json"
DEFAULT_PRODUCTION = ROOT / "data" / "industrial-value-model" / "production_inputs.json"
DEFAULT_DASHBOARD = ROOT / "public" / "data" / "dashboard.json"
DEFAULT_INDUSTRIAL = ROOT / "data" / "industrial-value-model" / "forecast_results.json"
DEFAULT_CREDIT = ROOT / "data" / "credit-model" / "forecast_results.json"
DEFAULT_LEGACY = ROOT / "data" / "investment-model" / "forecast_results_yoy_anchor_legacy.json"
DEFAULT_OUTPUT = ROOT / "data" / "investment-model" / "forecast_results.json"
DEFAULT_CSV = ROOT / "outputs" / "investment-model" / "investment_forecast_timeseries.csv"

TARGET_MONTH = pd.Timestamp("2026-08-31")
BACKTEST_START = pd.Timestamp("2023-03-31")
AS_OF_DAY = 24
MODEL_VERSION = "investment-level-flow-bridge-v4-bias-corrected"
MODEL_FROZEN_AT = "2026-08-27"
MODEL_FREEZE_POLICY = "parameters, candidate sets, calibration windows and information cutoff are frozen; future updates may add only newly available observations"
BRIDGE_WINDOW = 24
FLOW_DEBIAS_WINDOW = 9
FLOW_DEBIAS_SHRINKAGE = 0.5
ONLINE_BIAS_PENALTY = 1.0
FEB_SAME_PERIOD_WEIGHT = 0.875
FEB_RECENT_FLOW_WINDOW = 3
AMOUNT_KEY = "fixed_asset_investment_ytd_amount"
YOY_KEY = "fixed_asset_investment_ytd_yoy"
CONSENSUS_KEY = "fixed_asset_investment_consensus"

PRODUCTION_FACTORS = (
    "blast_furnace",
    "rebar_rate",
    "power_coal",
    "pta_rate",
    "methanol_rate",
    "car_wholesale",
    "car_retail",
)
DASHBOARD_FACTORS = (
    "asphalt_rate",
    "newhome_30c",
    "cement_national",
    "rebar_price",
    "rebar_inventory",
)
RATE_FACTORS = {"blast_furnace", "rebar_rate", "pta_rate", "methanol_rate", "asphalt_rate"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def observations(rows: list[Any], scale: float = 1.0) -> pd.Series:
    parsed: dict[pd.Timestamp, float] = {}
    for row in rows:
        if isinstance(row, dict):
            date, value = row.get("date"), row.get("value")
        else:
            date, value = row[0], row[1]
        day = pd.to_datetime(date, errors="coerce")
        number = pd.to_numeric(value, errors="coerce")
        if pd.notna(day) and pd.notna(number):
            parsed[pd.Timestamp(day)] = float(number) / scale
    return pd.Series(parsed, dtype=float).sort_index()


def month_end_series(rows: list[Any], scale: float = 1.0) -> pd.Series:
    values = observations(rows, scale)
    values.index = values.index + pd.offsets.MonthEnd(0)
    return values[~values.index.duplicated(keep="last")].sort_index()


def monthly_flow(cumulative: pd.Series) -> pd.Series:
    result: dict[pd.Timestamp, float] = {}
    for day, value in cumulative.dropna().items():
        if day.month == 2:
            result[day] = float(value)
            continue
        previous = day - pd.offsets.MonthEnd(1)
        if previous in cumulative.index and pd.notna(cumulative.get(previous)):
            result[day] = float(value - cumulative.loc[previous])
    return pd.Series(result, dtype=float).sort_index()


def reconstruct_comparable_level(raw_amount: pd.Series, official_yoy: pd.Series) -> pd.Series:
    """Chain each calendar month's official YoY into a fixed comparable level."""
    output = pd.Series(index=raw_amount.index, dtype=float)
    first_year = int(raw_amount.dropna().index.min().year)
    output.loc[raw_amount.index.year == first_year] = raw_amount.loc[raw_amount.index.year == first_year]
    for day in raw_amount.index:
        if day.year == first_year or pd.isna(official_yoy.get(day)):
            continue
        previous_year = day - pd.DateOffset(years=1) + pd.offsets.MonthEnd(0)
        if pd.notna(output.get(previous_year)):
            output.loc[day] = float(output.loc[previous_year] * (1.0 + official_yoy.loc[day] / 100.0))
    return output


def monthly_partial_mean(values: pd.Series, cutoff_day: int = AS_OF_DAY) -> pd.Series:
    selected = values.loc[values.index.day <= cutoff_day]
    if selected.empty:
        return pd.Series(dtype=float)
    periods = selected.index.to_period("M")
    output = selected.groupby(periods).mean()
    output.index = output.index.to_timestamp("M")
    return output.sort_index()


def realtime_zscore(change: pd.Series, window: int = 36, min_history: int = 12) -> pd.Series:
    mean = change.shift(1).rolling(window, min_periods=min_history).mean()
    std = change.shift(1).rolling(window, min_periods=min_history).std(ddof=0).replace(0.0, np.nan)
    return ((change - mean) / std).clip(-4.0, 4.0)


def factor_signal(key: str, values: pd.Series) -> pd.Series:
    monthly = monthly_partial_mean(values)
    if key in RATE_FACTORS:
        change = monthly - monthly.shift(12)
    else:
        positive = monthly.where(monthly > 0)
        change = np.log(positive / positive.shift(12)) * 100.0
    return realtime_zscore(change)


def industrial_history(payload: dict[str, Any]) -> pd.Series:
    return pd.Series(
        {
            pd.Timestamp(row["date"]) + pd.offsets.MonthEnd(0): float(row["model"])
            for row in payload.get("history", [])
            if row.get("model") is not None
        },
        dtype=float,
    ).sort_index()


def credit_history(payload: dict[str, Any], key: str) -> pd.Series:
    return pd.Series(
        {
            pd.Timestamp(row["date"]) + pd.offsets.MonthEnd(0): float(row["model"])
            for row in payload.get("history", {}).get(key, [])
            if row.get("model") is not None
        },
        dtype=float,
    ).sort_index()


def load_high_frequency(production: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, pd.Series]:
    signals: dict[str, pd.Series] = {}
    for key in PRODUCTION_FACTORS:
        item = production.get("series", {}).get(key, {})
        signals[key] = factor_signal(key, observations(item.get("observations", [])))
    lookup = {item.get("id"): item for item in dashboard.get("indicators", [])}
    for key in DASHBOARD_FACTORS:
        item = lookup.get(key, {})
        signals[key] = factor_signal(key, observations(item.get("series", [])))
    return signals


def component_flow_growth(rows: list[Any]) -> pd.Series:
    amount = month_end_series(rows, 1e12)
    flow = monthly_flow(amount)
    return np.log(flow.where(flow > 0) / flow.where(flow > 0).shift(12)) * 100.0


def build_frame(
    source: dict[str, Any],
    production: dict[str, Any],
    dashboard: dict[str, Any],
    industrial: dict[str, Any],
    credit: dict[str, Any],
) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    series_data = source["series"]
    amount = month_end_series(series_data[AMOUNT_KEY]["observations"], 1e12)
    actual = month_end_series(series_data[YOY_KEY]["observations"])
    consensus = month_end_series(series_data[CONSENSUS_KEY]["observations"])
    index = pd.date_range(amount.index.min(), TARGET_MONTH, freq="ME")
    amount = amount.reindex(index)
    actual = actual.reindex(index)
    comparable_level = reconstruct_comparable_level(amount, actual)
    flow = monthly_flow(comparable_level).reindex(index)
    flow_growth = np.log(flow.where(flow > 0) / flow.where(flow > 0).shift(12)) * 100.0

    frame = pd.DataFrame(index=index)
    frame["flow_log_growth"] = flow_growth
    signals = load_high_frequency(production, dashboard)
    for key, value in signals.items():
        frame[f"hf_{key}"] = value.reindex(index)
    core_hf = [f"hf_{key}" for key in ("blast_furnace", "rebar_rate", "power_coal", "asphalt_rate", "cement_national", "rebar_price")]
    frame["hf_construction_diffusion"] = frame[core_hf].mean(axis=1, skipna=True)
    frame.loc[frame[core_hf].notna().sum(axis=1) < 3, "hf_construction_diffusion"] = np.nan
    # A zero standardized value is an explicit neutral/no-signal observation
    # before the dashboard housing history begins.
    frame["hf_real_estate_demand"] = frame["hf_newhome_30c"].fillna(0.0)
    frame["industrial_nowcast"] = industrial_history(industrial).reindex(index)
    for key in ("m2_yoy", "new_rmb_loans", "social_financing"):
        frame[f"credit_{key}"] = credit_history(credit, key).reindex(index)
    infra_growth = component_flow_growth(series_data["infrastructure_investment_ytd_amount"]["observations"])
    estate_growth = component_flow_growth(series_data["real_estate_investment_ytd_amount"]["observations"])
    frame["infra_flow_growth_l1"] = infra_growth.reindex(index).ffill().shift(1)
    frame["estate_flow_growth_l1"] = estate_growth.reindex(index).ffill().shift(1)
    return frame, amount, comparable_level, flow, actual, consensus


def ridge_predict(train: pd.DataFrame, row: pd.Series, features: list[str], alpha: float) -> float:
    x = train[features].astype(float)
    y = train["flow_log_growth"].astype(float).to_numpy()
    means = x.mean()
    stds = x.std(ddof=0).replace(0.0, np.nan)
    xz = ((x - means) / stds).fillna(0.0).to_numpy()
    rz = ((row[features].astype(float) - means) / stds).fillna(0.0).to_numpy()
    design = np.column_stack([np.ones(len(xz)), xz])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    beta = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y
    prediction = float(np.r_[1.0, rz] @ beta)
    lower, upper = np.quantile(y, [0.05, 0.95])
    return float(np.clip(prediction, lower, upper))


def walk_forward_growth(
    frame: pd.DataFrame,
    features: list[str],
    alpha: float,
    window: int = 48,
    min_train: int = 18,
) -> pd.Series:
    output: dict[pd.Timestamp, float] = {}
    for day in frame.loc[BACKTEST_START:].index:
        if frame.loc[day, features].isna().any():
            continue
        train = frame.loc[frame.index < day].dropna(subset=["flow_log_growth", *features]).iloc[-window:]
        if len(train) >= min_train:
            output[day] = ridge_predict(train, frame.loc[day], features, alpha)
    return pd.Series(output, dtype=float)


def recent_growth_candidate(flow_growth: pd.Series, index: pd.DatetimeIndex, lookback: int = 6) -> pd.Series:
    output: dict[pd.Timestamp, float] = {}
    for day in index:
        # February is the combined January-February published period, not a
        # one-month flow. Mixing it into recent monthly-flow history creates a
        # mechanical lag in March and the following months.
        history = flow_growth.loc[(flow_growth.index < day) & (flow_growth.index.month != 2)].dropna().iloc[-lookback:]
        if len(history) >= 3:
            output[day] = float(history.median())
    return pd.Series(output, dtype=float)


def growth_to_flow(growth: pd.Series, flow: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    prior_year = flow.shift(12).reindex(index)
    return prior_year * np.exp(growth.reindex(index) / 100.0)


def online_flow_blend(
    candidates: pd.DataFrame,
    actual_flow: pd.Series,
    lookback: int = 24,
    min_history: int = 9,
) -> tuple[pd.Series, dict[str, dict[str, float]]]:
    output: dict[pd.Timestamp, float] = {}
    weight_history: dict[str, dict[str, float]] = {}
    actual_log = np.log(actual_flow.where(actual_flow > 0))
    for day, row in candidates.iterrows():
        available = row.dropna()
        if available.empty:
            continue
        scores: dict[str, float] = {}
        for key in available.index:
            ordinary_history = (candidates.index < day) & (candidates.index.month != 2)
            prediction_log = np.log(candidates.loc[ordinary_history, key].where(lambda value: value > 0))
            ordinary_actual_log = actual_log.loc[actual_log.index.month != 2]
            history = pd.concat(
                [prediction_log.rename("prediction"), ordinary_actual_log.rename("actual")],
                axis=1,
                sort=False,
            ).dropna().iloc[-lookback:]
            if len(history) >= min_history:
                residual = history["prediction"] - history["actual"]
                rmse = float(np.sqrt(np.mean(residual**2)))
                signed_bias = float(residual.mean())
                scores[key] = max(float(np.sqrt(rmse**2 + ONLINE_BIAS_PENALTY * signed_bias**2)), 0.01)
        if not scores:
            fallback = "same_month_amount" if "same_month_amount" in available else available.index[0]
            output[day] = float(available[fallback])
            weight_history[day.strftime("%Y-%m")] = {fallback: 1.0}
            continue
        rmse = pd.Series(scores)
        weights = 1.0 / rmse**2
        weights /= weights.sum()
        output[day] = float((available[weights.index] * weights).sum())
        weight_history[day.strftime("%Y-%m")] = {key: round(float(value), 6) for key, value in weights.items()}
    return pd.Series(output, dtype=float), weight_history


def debias_bridge_candidates(
    candidates: pd.DataFrame,
    actual_flow: pd.Series,
    keys: tuple[str, ...] = ("high_frequency_bridge", "monthly_model_bridge"),
    window: int = FLOW_DEBIAS_WINDOW,
    shrinkage: float = FLOW_DEBIAS_SHRINKAGE,
) -> pd.DataFrame:
    """Recenter bridge flows using only their preceding ordinary-month errors."""
    output = candidates.copy()
    for key in keys:
        if key not in candidates:
            continue
        for day in candidates.index:
            if day.month == 2 or pd.isna(candidates.at[day, key]):
                continue
            history = pd.concat(
                [candidates[key].rename("prediction"), actual_flow.rename("actual")],
                axis=1,
                sort=False,
            )
            history = history.loc[(history.index < day) & (history.index.month != 2)].dropna().iloc[-window:]
            if len(history) < window:
                continue
            log_correction = float(np.log(history["actual"] / history["prediction"]).mean())
            output.at[day, key] = float(candidates.at[day, key] * np.exp(shrinkage * log_correction))
    return output


def replace_february_with_period_level(
    predicted_flow: pd.Series,
    comparable_level: pd.Series,
    official_yoy: pd.Series,
    flow_growth: pd.Series,
) -> pd.Series:
    """Forecast the combined January-February fixed period separately."""
    output = predicted_flow.copy()
    comparable_base = comparable_level.shift(12)
    for day in output.index[output.index.month == 2]:
        previous_year = day - pd.DateOffset(years=1) + pd.offsets.MonthEnd(0)
        if pd.notna(comparable_base.get(day)) and pd.notna(official_yoy.get(previous_year)):
            recent = flow_growth.loc[(flow_growth.index < day) & (flow_growth.index.month != 2)].dropna().iloc[-FEB_RECENT_FLOW_WINDOW:]
            recent_simple_growth = (
                float((np.exp(float(recent.median()) / 100.0) - 1.0) * 100.0)
                if len(recent) == FEB_RECENT_FLOW_WINDOW
                else float(official_yoy.loc[previous_year])
            )
            period_growth = (
                FEB_SAME_PERIOD_WEIGHT * float(official_yoy.loc[previous_year])
                + (1.0 - FEB_SAME_PERIOD_WEIGHT) * recent_simple_growth
            )
            output.loc[day] = float(comparable_base.loc[day] * (1.0 + period_growth / 100.0))
    return output


def cumulative_from_flow(predicted_flow: pd.Series, amount: pd.Series) -> pd.Series:
    output: dict[pd.Timestamp, float] = {}
    for day, value in predicted_flow.dropna().items():
        if day.month == 2:
            output[day] = float(value)
            continue
        previous = day - pd.offsets.MonthEnd(1)
        if pd.notna(amount.get(previous)):
            output[day] = float(amount.loc[previous] + value)
    return pd.Series(output, dtype=float)


def metrics(prediction: pd.Series, actual: pd.Series) -> dict[str, Any]:
    joined = pd.concat([prediction.rename("prediction"), actual.rename("actual")], axis=1, sort=False).dropna()
    error = joined["prediction"] - joined["actual"]
    prior_actual = actual.ffill().shift(1).reindex(joined.index)
    direction_valid = prior_actual.notna() & ((joined["actual"] - prior_actual).abs() > 1e-12)
    direction_hit = np.sign(joined.loc[direction_valid, "prediction"] - prior_actual.loc[direction_valid]) == np.sign(
        joined.loc[direction_valid, "actual"] - prior_actual.loc[direction_valid]
    )
    actual_change = joined["actual"].diff().dropna()
    prediction_change = joined["prediction"].diff().reindex(actual_change.index)
    return {
        "rmse": round(float(np.sqrt(np.mean(error**2))), 6),
        "mae": round(float(np.mean(abs(error))), 6),
        "bias": round(float(np.mean(error)), 6),
        "directionHitPct": round(float(direction_hit.mean() * 100), 2) if len(direction_hit) else None,
        "changeCaptureRatio": round(float(prediction_change.std(ddof=0) / actual_change.std(ddof=0)), 6) if actual_change.std(ddof=0) else None,
        "observations": int(len(joined)),
        "sampleStart": joined.index.min().strftime("%Y-%m") if len(joined) else None,
        "sampleEnd": joined.index.max().strftime("%Y-%m") if len(joined) else None,
    }


def lag_diagnostics(prediction: pd.Series, actual: pd.Series) -> dict[str, Any]:
    joined = pd.concat([prediction.rename("prediction"), actual.rename("actual")], axis=1, sort=False).dropna()
    joined["actual_lag1"] = actual.ffill().shift(1).reindex(joined.index)
    valid = joined.dropna()
    current_corr = float(valid["prediction"].corr(valid["actual"]))
    lag_corr = float(valid["prediction"].corr(valid["actual_lag1"]))
    return {
        "actualCorrelation": round(current_corr, 6),
        "previousActualCorrelation": round(lag_corr, 6),
        "previousMinusCurrentCorrelation": round(lag_corr - current_corr, 6),
    }


def common_comparison(model: pd.Series, consensus: pd.Series, actual: pd.Series) -> dict[str, Any]:
    joined = pd.concat([model.rename("model"), consensus.rename("consensus"), actual.rename("actual")], axis=1, sort=False).loc[BACKTEST_START:].dropna()
    model_metrics = metrics(joined["model"], joined["actual"])
    consensus_metrics = metrics(joined["consensus"], joined["actual"])
    model_error = abs(joined["model"] - joined["actual"])
    consensus_error = abs(joined["consensus"] - joined["actual"])
    return {
        "model": model_metrics,
        "consensus": consensus_metrics,
        "modelWinRatePct": round(float((model_error < consensus_error).mean() * 100), 2),
        "rmseImprovementPct": round(float((consensus_metrics["rmse"] - model_metrics["rmse"]) / consensus_metrics["rmse"] * 100), 2),
        "maeImprovementPct": round(float((consensus_metrics["mae"] - model_metrics["mae"]) / consensus_metrics["mae"] * 100), 2),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    source = read_json(args.source)
    frame, raw_amount, comparable_level, flow, actual, consensus = build_frame(
        source,
        read_json(args.production),
        read_json(args.dashboard),
        read_json(args.industrial),
        read_json(args.credit),
    )
    index = frame.loc[BACKTEST_START:].index
    same_month_growth = pd.Series(0.0, index=index)
    recent_growth = recent_growth_candidate(frame["flow_log_growth"], index)
    hf_features = ["hf_construction_diffusion", "industrial_nowcast"]
    full_features = [
        *hf_features,
        "hf_real_estate_demand",
        "credit_new_rmb_loans",
        "credit_social_financing",
        "infra_flow_growth_l1",
        "estate_flow_growth_l1",
    ]
    hf_growth = walk_forward_growth(frame, hf_features, alpha=18.0, window=BRIDGE_WINDOW, min_train=12).reindex(index)
    full_growth = walk_forward_growth(frame, full_features, alpha=28.0, window=BRIDGE_WINDOW, min_train=12).reindex(index)
    growth_candidates = {
        "same_month_amount": same_month_growth,
        "recent_flow_growth": recent_growth,
        "high_frequency_bridge": hf_growth,
        "monthly_model_bridge": full_growth,
    }
    flow_candidates = pd.DataFrame(
        {key: growth_to_flow(value, flow, index) for key, value in growth_candidates.items()},
        index=index,
    )
    flow_candidates = debias_bridge_candidates(flow_candidates, flow)
    predicted_flow, weight_history = online_flow_blend(flow_candidates, flow)
    predicted_flow = replace_february_with_period_level(predicted_flow, comparable_level, actual, frame["flow_log_growth"])
    predicted_amount = cumulative_from_flow(predicted_flow, comparable_level)
    comparable_base = comparable_level.shift(12).reindex(index)
    model = (predicted_amount / comparable_base - 1.0) * 100.0
    comparison = common_comparison(model, consensus, actual)
    recent_regime_comparison = common_comparison(
        model.loc[pd.Timestamp("2025-02-28"):],
        consensus.loc[pd.Timestamp("2025-02-28"):],
        actual.loc[pd.Timestamp("2025-02-28"):],
    )

    legacy_payload = read_json(args.legacy) if args.legacy.exists() else {}
    legacy_series = pd.Series(
        {
            pd.Timestamp(row["date"]) + pd.offsets.MonthEnd(0): float(row["model"])
            for row in legacy_payload.get("history", [])
            if row.get("model") is not None
        },
        dtype=float,
    )
    legacy_common = legacy_series.reindex(model.index)
    uncertainty = comparison["model"]["rmse"]
    rows = []
    for day in index:
        if day != TARGET_MONTH and pd.isna(actual.get(day)):
            continue
        rows.append(
            {
                "date": day.strftime("%Y-%m"),
                "model": None if pd.isna(model.get(day)) else round(float(model.loc[day]), 6),
                "legacyModel": None if pd.isna(legacy_common.get(day)) else round(float(legacy_common.loc[day]), 6),
                "consensus": None if pd.isna(consensus.get(day)) else round(float(consensus.loc[day]), 6),
                "actual": None if pd.isna(actual.get(day)) else round(float(actual.loc[day]), 6),
                "predictedMonthlyFlowTrillion": None if pd.isna(predicted_flow.get(day)) else round(float(predicted_flow.loc[day]), 6),
                "predictedComparableCumulativeTrillion": None if pd.isna(predicted_amount.get(day)) else round(float(predicted_amount.loc[day]), 6),
                "comparableBaseTrillion": None if pd.isna(comparable_base.get(day)) else round(float(comparable_base.loc[day]), 6),
                "kind": "live_nowcast" if day == TARGET_MONTH else "walk_forward",
            }
        )

    current = float(model.loc[TARGET_MONTH])
    result = {
        "schemaVersion": 2,
        "modelVersion": MODEL_VERSION,
        "modelFrozen": True,
        "modelFrozenAt": MODEL_FROZEN_AT,
        "modelFreezePolicy": MODEL_FREEZE_POLICY,
        "target": "固定资产投资(不含农户)完成额累计同比",
        "forecastMonth": TARGET_MONTH.strftime("%Y-%m"),
        "method": "forecast bias-corrected monthly fixed investment amount from high-frequency and existing monthly-model signals, accumulate to a fixed amount, then convert with a walk-forward comparable base",
        "consensusPolicy": source["consensusPolicy"],
        "current": {
            "model": round(current, 6),
            "unit": "%",
            "approx68PctRange": [round(current - uncertainty, 2), round(current + uncertainty, 2)],
            "predictedMonthlyFlowTrillion": round(float(predicted_flow.loc[TARGET_MONTH]), 6),
            "predictedComparableCumulativeTrillion": round(float(predicted_amount.loc[TARGET_MONTH]), 6),
            "comparableBaseTrillion": round(float(comparable_base.loc[TARGET_MONTH]), 6),
            "consensus": None if pd.isna(consensus.get(TARGET_MONTH)) else round(float(consensus.loc[TARGET_MONTH]), 6),
            "onlineFlowWeights": weight_history.get(TARGET_MONTH.strftime("%Y-%m"), {}),
        },
        "backtest": metrics(model.loc[: actual.dropna().index.max()], actual),
        "lagDiagnostics": lag_diagnostics(model.loc[: actual.dropna().index.max()], actual),
        "legacyLagDiagnostics": lag_diagnostics(legacy_common, actual),
        "comparisonOnCommonSample": comparison,
        "recentRegimeComparison": recent_regime_comparison,
        "legacyModelOnCommonSample": metrics(legacy_common.loc[BACKTEST_START:], actual.loc[BACKTEST_START:]),
        "performanceGateVsConsensus": {
            "passed": comparison["model"]["rmse"] < comparison["consensus"]["rmse"],
            "modelRmse": comparison["model"]["rmse"],
            "consensusRmse": comparison["consensus"]["rmse"],
            "rmseImprovementPct": comparison["rmseImprovementPct"],
        },
        "flowCandidateDiagnostics": {
            key: metrics(value, flow) for key, value in flow_candidates.items()
        },
        "featureGroups": {
            "fixedAmountBridge": "chain official YoY into a fixed comparable level, forecast its monthly flow, add it to the previous comparable cumulative level, then convert to cumulative YoY",
            "bridgeCalibration": {
                "trainingWindowMonths": BRIDGE_WINDOW,
                "ordinaryMonthResidualWindow": FLOW_DEBIAS_WINDOW,
                "residualShrinkage": FLOW_DEBIAS_SHRINKAGE,
                "onlineBiasPenalty": ONLINE_BIAS_PENALTY,
                "februarySamePeriodWeight": FEB_SAME_PERIOD_WEIGHT,
                "februaryRecentFlowWeight": 1.0 - FEB_SAME_PERIOD_WEIGHT,
            },
            "highFrequency": list(PRODUCTION_FACTORS + DASHBOARD_FACTORS),
            "monthlyForecastModels": ["industrial_value", "new_rmb_loans", "social_financing"],
            "laggedComponentLevels": ["infrastructure monthly amount", "real-estate monthly amount"],
        },
        "providerIds": {key: value["providerId"] for key, value in source["series"].items()},
        "history": rows,
        "notes": [
            "上一期累计同比不进入金额流量方程，也不作为预测锚。",
            "高频桥和月频桥用此前9个普通月份的固定增量残差做50%收缩校准；在线权重额外惩罚持续同向偏差。",
            "1—2月按合并固定期间额单独预测，基准由上年同期间额状态与最近3个普通月固定增量状态组合，不与普通月训练或评分混合。",
            "同月高频历史统一截取每月24日及以前的观测，匹配当前2026-08-24的实时信息集。",
            "官方累计同比采用可比口径；历史金额链按各年同月官方同比递推，避免把统计范围调整误当成真实投资流量。",
            "一致预期只在全部金额预测、可比基数预测和同比换算完成后合并评估。",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.csv, index=False, encoding="utf-8-sig")
    return result


def points_for_dashboard(values: pd.Series) -> list[dict[str, Any]]:
    return [
        {"date": day.date().isoformat(), "value": round(float(value), 6)}
        for day, value in values.dropna().items()
    ]


def investment_input_rows(
    production_path: Path = DEFAULT_PRODUCTION,
    dashboard_path: Path = DEFAULT_DASHBOARD,
) -> list[dict[str, Any]]:
    production = read_json(production_path)
    dashboard = read_json(dashboard_path)
    dashboard_lookup = {item.get("id"): item for item in dashboard.get("indicators", [])}
    selected = (
        "blast_furnace",
        "rebar_rate",
        "power_coal",
        "pta_rate",
        "methanol_rate",
        "car_wholesale",
        "car_retail",
    )
    roles = {
        "blast_furnace": "建设施工扩散指标：钢铁生产与施工强度",
        "rebar_rate": "建设施工扩散指标：建筑钢材生产",
        "power_coal": "建设施工扩散指标：工业生产与用电强度",
        "pta_rate": "工业施工扩散指标：化工开工与中间品需求",
        "methanol_rate": "工业施工扩散指标：化工开工与中间品需求",
        "car_wholesale": "设备制造扩散指标：汽车批发景气",
        "car_retail": "设备制造扩散指标：汽车终端需求",
    }
    rows: list[dict[str, Any]] = []
    for key in selected:
        if key in production.get("series", {}):
            item = production["series"][key]
            raw = observations(item.get("observations", []))
            source = item.get("source") or "iFinD EDB"
            provider_id = item.get("providerId")
        else:
            item = dashboard_lookup.get(key, {})
            raw = observations(item.get("series", []))
            source = item.get("source") or "dashboard"
            provider_id = item.get("providerId")
        rate_factor = key in RATE_FACTORS
        rows.append({
            "name": item.get("name") or key,
            "id": key,
            "unit": item.get("unit") or "",
            "source": f"{source} · {provider_id}" if provider_id else source,
            "frequency": item.get("frequency") or "未知",
            "role": roles[key],
            "aggregation": (
                f"每月仅取{AS_OF_DAY}日及以前均值；计算同比百分点变化并做36个月实时标准化"
                if rate_factor else
                f"每月仅取{AS_OF_DAY}日及以前均值；计算对数同比并做36个月实时标准化"
            ),
            "providerId": provider_id,
            "latestAvailableDate": raw.index.max().date().isoformat() if len(raw) else None,
            "modelUsageNote": "每个历史预测月使用相同日历截点；一致预期不进入该信号。",
            "series": points_for_dashboard(raw),
        })
    return rows


def augment_forecast_payload(
    payload: dict[str, Any],
    results_path: Path = DEFAULT_OUTPUT,
    production_path: Path = DEFAULT_PRODUCTION,
    dashboard_path: Path = DEFAULT_DASHBOARD,
    source_path: Path = DEFAULT_SOURCE,
) -> dict[str, Any]:
    """Expose the frozen investment forecast through the dashboard schema."""
    result = read_json(results_path)
    if result.get("modelVersion") != MODEL_VERSION or not result.get("modelFrozen"):
        raise RuntimeError("investment forecast result is not the frozen production model")
    if not result.get("performanceGateVsConsensus", {}).get("passed"):
        raise RuntimeError("investment forecast did not pass the consensus performance gate")

    key = "fixed_asset_investment"
    display_start = payload.get("displayStart", "2023-01-31")
    history = []
    consensus_id = result.get("providerIds", {}).get(CONSENSUS_KEY)
    source = read_json(source_path)
    actual_by_month = {
        day.strftime("%Y-%m"): float(value)
        for day, value in observations(source["series"][YOY_KEY].get("observations", [])).items()
    }
    consensus_by_month = {
        day.strftime("%Y-%m"): float(value)
        for day, value in observations(source["series"][CONSENSUS_KEY].get("observations", [])).items()
    }
    first_model_month = result.get("history", [{}])[0].get("date")
    cursor = pd.Timestamp(display_start)
    while first_model_month and cursor.strftime("%Y-%m") < first_model_month:
        month = cursor.strftime("%Y-%m")
        consensus_value = consensus_by_month.get(month)
        history.append({
            "date": cursor.date().isoformat(),
            "forecast": None,
            "actual": actual_by_month.get(month),
            "consensus": consensus_value,
            "consensusSource": f"iFinD EDB · {consensus_id}" if consensus_value is not None else None,
            "forecastKind": "structural_gap",
            "officialRounding": None,
        })
        cursor = cursor + pd.offsets.MonthEnd(1)
    for row in result.get("history", []):
        year, month = (int(value) for value in row["date"].split("-"))
        dashboard_date = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        if dashboard_date < display_start:
            continue
        forecast = row.get("model")
        history.append({
            "date": dashboard_date,
            "forecast": forecast,
            "actual": row.get("actual"),
            "consensus": row.get("consensus"),
            "consensusSource": f"iFinD EDB · {consensus_id}" if row.get("consensus") is not None else None,
            "forecastKind": row.get("kind") or ("live_nowcast" if row.get("actual") is None else "walk_forward"),
            "officialRounding": round(float(forecast), 1) if forecast is not None else None,
        })

    comparison = result["comparisonOnCommonSample"]
    model_metrics = comparison["model"]
    payload.setdefault("history", {})[key] = history
    payload.setdefault("daily", {})[key] = []
    payload.setdefault("models", {})[key] = {
        "name": "固定资产投资累计同比",
        "unit": "%",
        "description": "冻结版固定额—月度增量桥：先预测可比固定投资额，再换算累计同比，避免以上一期同比作为预测底座。",
        "formula": "可比固定额链 + 24个月高频/月频桥 + 9个月固定增量残差收缩 + 1—2月独立期间额模型；一致预期仅用于事后比较。",
        "status": "READY",
        "forecastMonth": result.get("forecastMonth"),
    }
    payload.setdefault("metrics", {})[key] = {
        "rmse": model_metrics["rmse"],
        "mae": model_metrics["mae"],
        "sampleStart": model_metrics["sampleStart"],
        "sampleEnd": model_metrics["sampleEnd"],
        "directionHit": model_metrics.get("directionHitPct"),
        "benchmarkRmse": comparison["consensus"]["rmse"],
        "observations": model_metrics["observations"],
    }
    payload.setdefault("highFrequency", {})["投资"] = investment_input_rows(production_path, dashboard_path)
    payload.setdefault("modelLocks", {})["investment"] = {
        "version": MODEL_VERSION,
        "frozenAt": MODEL_FROZEN_AT,
        "targets": [key],
        "policy": MODEL_FREEZE_POLICY,
    }
    payload["investmentModel"] = {
        "version": MODEL_VERSION,
        "forecastMonth": result.get("forecastMonth"),
        "informationCutoffDay": AS_OF_DAY,
        "consensusPolicy": result.get("consensusPolicy"),
        "performanceGateVsConsensus": result.get("performanceGateVsConsensus"),
        "bridgeCalibration": result.get("featureGroups", {}).get("bridgeCalibration"),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--production", type=Path, default=DEFAULT_PRODUCTION)
    parser.add_argument("--dashboard", type=Path, default=DEFAULT_DASHBOARD)
    parser.add_argument("--industrial", type=Path, default=DEFAULT_INDUSTRIAL)
    parser.add_argument("--credit", type=Path, default=DEFAULT_CREDIT)
    parser.add_argument("--legacy", type=Path, default=DEFAULT_LEGACY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({
        "current": result["current"],
        "comparison": result["comparisonOnCommonSample"],
        "lagDiagnostics": result["lagDiagnostics"],
        "legacyLagDiagnostics": result["legacyLagDiagnostics"],
        "gate": result["performanceGateVsConsensus"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
