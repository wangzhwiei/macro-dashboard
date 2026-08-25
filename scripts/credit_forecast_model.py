#!/usr/bin/env python3
"""Target-specific, no-consensus forecasts for M2, RMB loans and TSF."""

from __future__ import annotations

import argparse
import calendar
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "credit-model" / "source_data.json"
DEFAULT_FORECASTS = ROOT / "public" / "data" / "forecasts.json"
DEFAULT_INDUSTRIAL = ROOT / "data" / "industrial-value-model" / "forecast_results.json"
DEFAULT_MODEL_INPUTS = ROOT / "data" / "forecast-model" / "model_inputs.json"
DEFAULT_INDUSTRIAL_SOURCE = ROOT / "data" / "industrial-value-model" / "targets_consensus.json"
DEFAULT_OUTPUT = ROOT / "data" / "credit-model" / "forecast_results.json"
TARGET_MONTH = pd.Timestamp("2026-08-31")
BACKTEST_START = pd.Timestamp("2018-01-31")
MODEL_VERSION = "credit-v1.0.0"
MODEL_FROZEN_AT = "2026-08-25"
TSF_COMPONENT_KEYS = (
    "tsf_rmb_loans",
    "tsf_foreign_currency_loans",
    "tsf_entrusted_loans",
    "tsf_trust_loans",
    "tsf_bank_acceptance",
    "tsf_corporate_bonds",
    "tsf_equity_financing",
    "tsf_government_bonds",
    "tsf_asset_backed_securities",
    "tsf_loan_writeoffs",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def series(rows: list[list[Any]], scale: float = 1.0) -> pd.Series:
    frame = pd.DataFrame(rows, columns=["date", "value"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce") / scale
    return frame.dropna().drop_duplicates("date", keep="last").set_index("date")["value"].sort_index()


def forecast_index(*values: pd.Series) -> pd.DatetimeIndex:
    return pd.date_range(min(value.index.min() for value in values), TARGET_MONTH, freq="ME")


def latest_daily_forecast(payload: dict[str, Any], key: str) -> float | None:
    rows = payload.get("daily", {}).get(key, [])
    return float(rows[-1]["value"]) if rows else None


def current_macro_forecasts(forecasts_path: Path, industrial_path: Path) -> dict[str, float | None]:
    payload = read_json(forecasts_path)
    industrial = read_json(industrial_path)
    return {
        "cpi": latest_daily_forecast(payload, "cpi"),
        "ppi": latest_daily_forecast(payload, "ppi"),
        "pmi": latest_daily_forecast(payload, "pmi"),
        "industrial_value": industrial.get("latest", {}).get("model"),
    }


def macro_information_series(
    model_inputs_path: Path,
    industrial_source_path: Path,
    current: dict[str, float | None],
) -> dict[str, pd.Series]:
    """Reconstruct the information available immediately before each credit release.

    Same-month CPI, PPI and PMI are normally published before the PBOC credit
    release, so their historical rows use the released values. Industrial
    value added is published later and therefore remains lagged one month. For
    the still-open live month, generated forecasts fill variables whose actual
    release is not yet available as of the source retrieval date.
    """
    inputs = read_json(model_inputs_path)
    actuals = {key: series(inputs["targets"][key]["data"]) for key in ("cpi", "ppi", "pmi")}
    industrial_source = read_json(industrial_source_path)
    actuals["industrial_value"] = series(industrial_source["series"]["actualMonthly"]["observations"])
    result: dict[str, pd.Series] = {}
    for key, actual in actuals.items():
        available = actual.shift(1).copy() if key == "industrial_value" else actual.copy()
        same_month_released = key != "industrial_value" and pd.notna(actual.get(TARGET_MONTH, np.nan))
        if not same_month_released and current.get(key) is not None:
            available.loc[TARGET_MONTH] = float(current[key])
        result[f"now_{key}"] = available.sort_index()
    return result


# Backward-compatible alias for callers outside this script.
macro_nowcast_series = macro_information_series


def metrics(prediction: pd.Series, actual: pd.Series) -> dict[str, Any]:
    joined = pd.concat([prediction.rename("prediction"), actual.rename("actual")], axis=1, sort=False).dropna()
    error = joined["prediction"] - joined["actual"]
    return {
        "rmse": round(float(np.sqrt(np.mean(error**2))), 6),
        "mae": round(float(np.mean(abs(error))), 6),
        "bias": round(float(np.mean(error)), 6),
        "observations": int(len(joined)),
        "sampleStart": joined.index.min().strftime("%Y-%m") if len(joined) else None,
        "sampleEnd": joined.index.max().strftime("%Y-%m") if len(joined) else None,
    }


def m2_persistence(target: pd.Series) -> pd.Series:
    """Legacy benchmark retained only for diagnostics."""
    index = forecast_index(target)
    return target.reindex(index).shift(1).loc[BACKTEST_START:]


def m2_level_feature_frame(
    level: pd.Series,
    loan_model: pd.Series,
    bill_rate_daily: pd.Series,
) -> pd.DataFrame:
    """Build a stock-flow bridge without using lagged M2 YoY as the forecast base."""
    index = forecast_index(level, loan_model)
    levels = level.reindex(index)
    change = levels.diff()
    frame = pd.DataFrame({"target": change}, index=index)
    for lag in (1, 2, 3, 12, 24, 36):
        frame[f"change_l{lag}"] = change.shift(lag)
    frame["change_mean3_l1"] = change.shift(1).rolling(3).mean()
    frame["loan_model"] = loan_model.reindex(index)
    bill_yoy = daily_monthly_mean(bill_rate_daily).reindex(index).diff(12)
    frame["bill_yoy"] = bill_yoy.fillna(0.0)
    return frame


def walk_forward_m2_level_bridge(
    frame: pd.DataFrame,
    level: pd.Series,
    features: list[str],
    alpha: float,
    window: int = 60,
    min_train: int = 30,
) -> tuple[pd.Series, pd.Series]:
    """Forecast the M2 balance change first, then convert the balance to YoY."""
    levels = level.reindex(frame.index)
    yoy_output: dict[pd.Timestamp, float] = {}
    level_output: dict[pd.Timestamp, float] = {}
    for day in frame.loc[BACKTEST_START:].index:
        previous_month = day - pd.offsets.MonthEnd(1)
        previous_year = day - pd.DateOffset(years=1)
        if frame.loc[day, features].isna().any():
            continue
        if previous_month not in levels.index or previous_year not in levels.index:
            continue
        if pd.isna(levels.loc[previous_month]) or pd.isna(levels.loc[previous_year]):
            continue
        train = frame.loc[frame.index < day].dropna(subset=["target", *features]).iloc[-window:]
        if len(train) < min_train:
            continue
        predicted_change = ridge_row(train, frame.loc[day], features, alpha)
        predicted_level = float(levels.loc[previous_month]) + predicted_change
        level_output[day] = predicted_level
        yoy_output[day] = (predicted_level / float(levels.loc[previous_year]) - 1.0) * 100.0
    return pd.Series(yoy_output, dtype=float), pd.Series(level_output, dtype=float)


def m2_seasonal_level_fallback(level: pd.Series) -> tuple[pd.Series, pd.Series]:
    """History-only fallback used before the multivariate bridge has enough training rows."""
    index = forecast_index(level)
    levels = level.reindex(index)
    change = levels.diff()
    predicted_change = 0.5 * change.shift(12) + 0.3 * change.shift(24) + 0.2 * change.shift(36)
    predicted_level = levels.shift(1) + predicted_change
    predicted_yoy = (predicted_level / levels.shift(12) - 1.0) * 100.0
    return predicted_yoy.loc[BACKTEST_START:], predicted_level.loc[BACKTEST_START:]


def rolling_two_model_blend(
    primary: pd.Series,
    high_frequency: pd.Series,
    actual: pd.Series,
    lookback: int = 24,
    min_history: int = 12,
) -> tuple[pd.Series, pd.Series]:
    """Choose a high-frequency weight from earlier forecast errors only."""
    output: dict[pd.Timestamp, float] = {}
    chosen_weights: dict[pd.Timestamp, float] = {}
    weight_grid = np.linspace(0.0, 1.0, 11)
    candidates = pd.concat(
        [primary.rename("primary"), high_frequency.rename("high_frequency")], axis=1, sort=False
    )
    for day, row in candidates.loc[BACKTEST_START:].iterrows():
        if row.isna().all():
            continue
        history = candidates.loc[candidates.index < day].join(actual.rename("actual")).dropna().iloc[-lookback:]
        if len(history) < min_history:
            weight = 0.0
        else:
            errors = {
                float(weight): float(
                    np.sqrt(
                        np.mean(
                            (
                                (1.0 - weight) * history["primary"]
                                + weight * history["high_frequency"]
                                - history["actual"]
                            )
                            ** 2
                        )
                    )
                )
                for weight in weight_grid
            }
            weight = min(errors, key=errors.get)
        primary_value = row.get("primary")
        high_frequency_value = row.get("high_frequency")
        if pd.isna(primary_value):
            value = high_frequency_value
            weight = 1.0
        elif pd.isna(high_frequency_value):
            value = primary_value
            weight = 0.0
        else:
            value = (1.0 - weight) * float(primary_value) + weight * float(high_frequency_value)
        output[day] = float(value)
        chosen_weights[day] = float(weight)
    return pd.Series(output, dtype=float), pd.Series(chosen_weights, dtype=float)


def turning_point_hit_rate(prediction: pd.Series, actual: pd.Series) -> float | None:
    joined = pd.concat(
        [prediction.diff().rename("prediction"), actual.diff().rename("actual")], axis=1, sort=False
    ).sort_index().dropna()
    if not len(joined):
        return None
    return round(float((np.sign(joined["prediction"]) == np.sign(joined["actual"])).mean() * 100), 2)


def loan_candidates(target: pd.Series) -> pd.DataFrame:
    index = forecast_index(target)
    values = target.reindex(index)
    annual_level_change = values.shift(1).rolling(12).mean() - values.shift(13).rolling(12).mean()
    return pd.DataFrame(
        {
            f"seasonal_drift_{coefficient:g}": values.shift(12) + coefficient * annual_level_change
            for coefficient in (0.0, 0.25, 0.5, 0.75, 1.0)
        },
        index=index,
    )


def daily_monthly_mean(values: pd.Series) -> pd.Series:
    monthly = values.groupby(values.index.to_period("M")).mean()
    monthly.index = monthly.index.to_timestamp("M")
    return monthly.sort_index()


def bill_rate_overlay(
    base: pd.Series,
    target: pd.Series,
    bill_rate_daily: pd.Series,
    min_history: int = 2,
    beta_limit: float = 0.5,
) -> tuple[pd.Series, pd.Series]:
    """Correct loan forecasts with the observable same-month bill-rate YoY move.

    The slope is re-estimated at every origin using only earlier released loan
    outcomes. A tight sign-agnostic cap prevents the short bill-rate history
    from dominating the structural forecast.
    """
    bill_yoy = daily_monthly_mean(bill_rate_daily).diff(12)
    output = base.copy()
    adjustments: dict[pd.Timestamp, float] = {}
    for day in base.index:
        if day not in bill_yoy.index or pd.isna(base.loc[day]) or pd.isna(bill_yoy.loc[day]):
            continue
        history = pd.concat(
            [base.rename("base"), target.rename("actual"), bill_yoy.rename("bill_yoy")],
            axis=1,
            sort=False,
        ).sort_index()
        history = history.loc[history.index < day].dropna()
        if len(history) < min_history:
            continue
        residual = history["actual"] - history["base"]
        denominator = max(float(np.sum(history["bill_yoy"] ** 2)), 1e-9)
        beta = float(np.clip(np.sum(history["bill_yoy"] * residual) / denominator, -beta_limit, beta_limit))
        adjustment = beta * float(bill_yoy.loc[day])
        output.loc[day] = float(base.loc[day]) + adjustment
        adjustments[day] = adjustment
    return output, pd.Series(adjustments, dtype=float)


def rolling_candidate_selection(
    candidates: pd.DataFrame,
    actual: pd.Series,
    lookback: int = 48,
    min_history: int = 12,
) -> tuple[pd.Series, dict[str, int]]:
    """Select using only candidate errors observed strictly before each forecast month."""
    output: dict[pd.Timestamp, float] = {}
    choices: dict[str, int] = {column: 0 for column in candidates}
    for day in candidates.loc[BACKTEST_START:].index:
        available = candidates.loc[day].dropna()
        if available.empty:
            continue
        history = candidates.loc[candidates.index < day].join(actual.rename("actual")).dropna().iloc[-lookback:]
        if len(history) < min_history:
            choice = available.index[0]
        else:
            errors = history.drop(columns="actual").sub(history["actual"], axis=0)
            choice = np.sqrt((errors**2).mean()).reindex(available.index).idxmin()
        output[day] = float(available[choice])
        choices[choice] += 1
    return pd.Series(output, dtype=float), choices


def tsf_feature_frame(target: pd.Series, macro: dict[str, pd.Series] | None = None) -> pd.DataFrame:
    index = forecast_index(target, *(macro or {}).values())
    values = target.reindex(index)
    frame = pd.DataFrame({"target": values}, index=index)
    for lag in (12, 24, 36):
        frame[f"target_l{lag}"] = values.shift(lag)
    frame["mean12_l1"] = values.shift(1).rolling(12).mean()
    frame["annual_level_change"] = frame["mean12_l1"] - values.shift(13).rolling(12).mean()
    for key, value in (macro or {}).items():
        frame[key] = value.reindex(index)
    return frame


def ridge_row(train: pd.DataFrame, row: pd.Series, features: list[str], alpha: float) -> float:
    x = train[features].astype(float)
    y = train["target"].astype(float).to_numpy()
    means = x.mean()
    stds = x.std(ddof=0).replace(0, np.nan)
    xz = ((x - means) / stds).fillna(0.0).to_numpy()
    rz = ((row[features].astype(float) - means) / stds).fillna(0.0).to_numpy()
    design = np.column_stack([np.ones(len(xz)), xz])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return float(np.r_[1.0, rz] @ beta)


def walk_forward_ridge(
    frame: pd.DataFrame,
    features: list[str],
    alpha: float = 20.0,
    window: int = 84,
    min_train: int = 30,
) -> pd.Series:
    output = {}
    for day in frame.loc[BACKTEST_START:].index:
        if frame.loc[day, features].isna().any():
            continue
        train = frame.loc[frame.index < day].dropna(subset=["target", *features]).iloc[-window:]
        if len(train) >= min_train:
            output[day] = ridge_row(train, frame.loc[day], features, alpha)
    return pd.Series(output, dtype=float)


def component_bridge(data: dict[str, Any], total: pd.Series) -> pd.Series:
    """Forecast official TSF components and an exact historical reconciliation residual."""
    index = pd.date_range("2017-01-31", TARGET_MONTH, freq="ME")
    components = pd.DataFrame(
        {key: series(data[key]["observations"], 1e12).reindex(index) for key in TSF_COMPONENT_KEYS},
        index=index,
    )
    components["other_reconciliation"] = total.reindex(index) - components.sum(axis=1, min_count=len(TSF_COMPONENT_KEYS))
    predictions = []
    for column in components:
        values = components[column]
        predictions.append((0.5 * values.shift(12) + values.shift(24) / 3 + values.shift(36) / 6).rename(column))
    return pd.concat(predictions, axis=1, sort=False).sum(axis=1, min_count=len(predictions)).loc[BACKTEST_START:]


def expanding_challenger_blend(candidates: pd.DataFrame, actual: pd.Series, lookback: int = 36) -> pd.Series:
    """Inverse-RMSE blend; all weights are based strictly on earlier released targets."""
    output = {}
    for day in candidates.loc[BACKTEST_START:].index:
        available = candidates.loc[day].dropna()
        if available.empty:
            continue
        history = candidates.loc[candidates.index < day].join(actual.rename("actual")).dropna().iloc[-lookback:]
        if len(history) < 12 or len(available) == 1:
            output[day] = float(available.get("structural", available.iloc[0]))
            continue
        rmse = np.sqrt((history.drop(columns="actual").sub(history["actual"], axis=0) ** 2).mean())
        rmse = rmse.reindex(available.index).dropna().clip(lower=0.05)
        weights = (1.0 / rmse**2)
        weights /= weights.sum()
        output[day] = float((available[weights.index] * weights).sum())
    return pd.Series(output, dtype=float)


def trailing_candidate_weights(
    candidates: pd.DataFrame,
    actual: pd.Series,
    day: pd.Timestamp,
    lookback: int = 36,
) -> dict[str, float]:
    """Expose the same prior-error weights used by the challenger blend."""
    available = candidates.loc[day].dropna()
    history = candidates.loc[candidates.index < day].join(actual.rename("actual")).dropna().iloc[-lookback:]
    if len(history) < 12 or len(available) == 1:
        return {name: float(name == "structural") for name in available.index}
    rmse = np.sqrt((history.drop(columns="actual").sub(history["actual"], axis=0) ** 2).mean())
    rmse = rmse.reindex(available.index).dropna().clip(lower=0.05)
    weights = 1.0 / rmse**2
    weights /= weights.sum()
    return {name: round(float(weight), 4) for name, weight in weights.items()}


def robust_same_month_shrink(
    base: pd.Series,
    actual: pd.Series,
    base_weight: float = 0.75,
    history_years: int = 3,
) -> pd.Series:
    """Shrink TSF extremes toward the median of the three previously released same months."""
    output = {}
    for day, prediction in base.items():
        history = [actual.get(day - pd.DateOffset(years=year), np.nan) for year in range(1, history_years + 1)]
        available = [float(value) for value in history if pd.notna(value)]
        if pd.isna(prediction):
            continue
        if len(available) < history_years:
            output[day] = float(prediction)
        else:
            anchor = float(np.median(available))
            output[day] = base_weight * float(prediction) + (1.0 - base_weight) * anchor
    return pd.Series(output, dtype=float)


def online_residual_adjustment(
    base: pd.Series,
    actual: pd.Series,
    same_month_weight: float,
    global_weight: float,
    same_month_years: int,
    global_window: int,
    use_median: bool = True,
) -> pd.Series:
    """Apply a bounded calendar/global bias correction learned strictly before each month."""
    residual = actual - base
    reducer = "median" if use_median else "mean"
    same_month = residual.groupby(residual.index.month).transform(
        lambda values: getattr(
            values.shift(1).rolling(same_month_years, min_periods=2), reducer
        )()
    )
    global_bias = getattr(residual.shift(1).rolling(global_window, min_periods=2), reducer)()
    return (
        base
        + same_month_weight * same_month.fillna(0.0)
        + global_weight * global_bias.fillna(0.0)
    ).sort_index()


def consensus_metrics(consensus: pd.Series, actual: pd.Series, model: pd.Series) -> dict[str, Any]:
    common = pd.concat(
        [consensus.rename("consensus"), actual.rename("actual"), model.rename("model")], axis=1, sort=False
    ).dropna()
    result: dict[str, Any] = {"commonObservations": int(len(common))}
    if len(common):
        result["model"] = metrics(common["model"], common["actual"])
        result["consensus"] = metrics(common["consensus"], common["actual"])
        result["modelWinRatePct"] = round(
            float((abs(common["model"] - common["actual"]) < abs(common["consensus"] - common["actual"])).mean() * 100), 2
        )
    return result


def current_consensus(values: pd.Series) -> float | None:
    return float(values.loc[TARGET_MONTH]) if TARGET_MONTH in values.index and pd.notna(values.loc[TARGET_MONTH]) else None


def points_for_dashboard(values: pd.Series) -> list[dict[str, Any]]:
    return [
        {"date": day.date().isoformat(), "value": round(float(value), 6)}
        for day, value in values.dropna().items()
    ]


def augment_forecast_payload(payload: dict[str, Any], results_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    """Expose the frozen credit forecasts through the dashboard's forecast schema."""
    credit = read_json(results_path)
    if credit.get("modelVersion") != MODEL_VERSION or not credit.get("modelFrozen"):
        raise RuntimeError("credit forecast result is not the frozen production model")
    labels = {
        "m2_yoy": ("M2同比", "%", 2),
        "new_rmb_loans": ("新增人民币贷款", "万亿元", 2),
        "social_financing": ("社会融资规模增量", "万亿元", 2),
    }
    descriptions = {
        "m2_yoy": "固定版余额增量模型：先预测M2余额，再换算同比；不以上月同比为预测底座。",
        "new_rmb_loans": "固定版季节与信用水位模型，并使用3个月国股票据转贴利率进行实时修正。",
        "social_financing": "固定版结构、发布前宏观信息与央行十大社融分项组合模型。",
    }
    formulas = {
        "m2_yoy": "M2余额增量L12/L24/L36 + 近3月增量 + 贷款模型；票据利率仅作为稀疏候选。",
        "new_rmb_loans": "上年同月 + 25%×年度信用水位变化 + 票据利率修正 + 滞后残差校正。",
        "social_financing": "结构Ridge + CPI/PPI/PMI发布前信息 + 十大社融分项桥接，再做稳健收缩。",
    }
    consensus_provider_keys = {
        "m2_yoy": "m2_consensus",
        "new_rmb_loans": "new_rmb_loans_consensus",
        "social_financing": "social_financing_consensus",
    }
    for key, (name, unit, precision) in labels.items():
        rows = []
        for row in credit["history"][key]:
            year, month = (int(value) for value in row["date"].split("-"))
            day = calendar.monthrange(year, month)[1]
            dashboard_date = f"{year:04d}-{month:02d}-{day:02d}"
            if dashboard_date < payload.get("displayStart", "2023-01-31"):
                continue
            forecast = row.get("model")
            rows.append({
                "date": dashboard_date,
                "forecast": forecast,
                "actual": row.get("actual"),
                "consensus": row.get("consensus"),
                "consensusSource": (
                    f"iFinD EDB · {credit['providerIds'].get(consensus_provider_keys[key])}"
                    if row.get("consensus") is not None else None
                ),
                "forecastKind": "live_nowcast" if row.get("actual") is None else "walk_forward",
                "officialRounding": round(float(forecast), precision) if forecast is not None else None,
            })
        comparison = credit["comparisonOnCommonSample"][key]
        payload["history"][key] = rows
        payload["models"][key] = {
            "name": name,
            "unit": unit,
            "description": descriptions[key],
            "formula": formulas[key],
        }
        payload["metrics"][key] = {
            **comparison["model"],
            "benchmarkRmse": comparison["consensus"]["rmse"],
            "observations": comparison["commonObservations"],
        }
    source = read_json(DEFAULT_SOURCE)
    bill = series(source["series"]["bill_discount_3m"]["observations"])
    payload.setdefault("highFrequency", {})["信用"] = [{
        "name": "3个月国股票据转贴利率",
        "id": "credit_bill_discount_3m",
        "unit": "%",
        "source": f"iFinD EDB · {credit['providerIds']['bill_discount_3m']}",
        "frequency": "日频",
        "role": "新增人民币贷款直接修正；M2间接及稀疏候选",
        "aggregation": "当月日均值相对上年同月变化",
        "providerId": credit["providerIds"]["bill_discount_3m"],
        "latestAvailableDate": bill.index.max().date().isoformat(),
        "modelUsageNote": "固定模型只使用预测时点已经发生的市场利率，不使用一致预期。",
        "series": points_for_dashboard(bill),
    }]
    payload.setdefault("modelLocks", {})["credit"] = {
        "version": MODEL_VERSION,
        "frozenAt": MODEL_FROZEN_AT,
        "targets": list(labels),
        "policy": "parameters and candidate sets are frozen; monthly updates may add only newly released observations",
    }
    return payload


def build(
    source_path: Path,
    forecasts_path: Path,
    industrial_path: Path,
    model_inputs_path: Path = DEFAULT_MODEL_INPUTS,
    industrial_source_path: Path = DEFAULT_INDUSTRIAL_SOURCE,
) -> dict[str, Any]:
    source = read_json(source_path)
    data = source["series"]
    m2 = series(data["m2_yoy"]["observations"])
    m2_level = series(data["m2_level"]["observations"], 1e12)
    loans = series(data["new_rmb_loans"]["observations"], 1e12)
    tsf = series(data["social_financing"]["observations"], 1e12)

    macro_forecasts = current_macro_forecasts(forecasts_path, industrial_path)
    macro_series = macro_information_series(model_inputs_path, industrial_source_path, macro_forecasts)

    m2_legacy = m2_persistence(m2)
    loan_candidate_frame = loan_candidates(loans)
    loan_dynamic, loan_choices = rolling_candidate_selection(loan_candidate_frame, loans)
    # The 0.25 annual-level coefficient is frozen from the pre-consensus validation era.
    loan_structural = loan_candidate_frame["seasonal_drift_0.25"].loc[BACKTEST_START:]
    bill_daily = series(data["bill_discount_3m"]["observations"])
    loan_pre_residual, bill_adjustments = bill_rate_overlay(loan_structural, loans, bill_daily)
    loan_model = online_residual_adjustment(
        loan_pre_residual,
        loans,
        same_month_weight=0.25,
        global_weight=0.25,
        same_month_years=8,
        global_window=6,
    )

    structural_frame = tsf_feature_frame(tsf)
    structural_features = ["target_l12", "target_l24", "target_l36", "mean12_l1", "annual_level_change"]
    tsf_structural = walk_forward_ridge(structural_frame, structural_features)
    macro_frame = tsf_feature_frame(tsf, macro_series)
    macro_features = structural_features + list(macro_series)
    tsf_macro = walk_forward_ridge(macro_frame, macro_features)
    tsf_components = component_bridge(data, tsf)
    tsf_candidates = pd.concat(
        [
            tsf_structural.rename("structural"),
            tsf_macro.rename("release_information_macro"),
            tsf_components.rename("component_bridge"),
        ],
        axis=1,
        sort=False,
    )
    tsf_pre_shrink = expanding_challenger_blend(tsf_candidates, tsf)
    tsf_pre_residual = robust_same_month_shrink(tsf_pre_shrink, tsf)
    tsf_model = online_residual_adjustment(
        tsf_pre_residual,
        tsf,
        same_month_weight=0.25,
        global_weight=-0.25,
        same_month_years=2,
        global_window=12,
    )

    m2_frame = m2_level_feature_frame(m2_level, loan_model, bill_daily)
    m2_sparse_features = [
        "change_l12",
        "change_l24",
        "change_l36",
        "change_mean3_l1",
        "loan_model",
    ]
    m2_candidate_specs = {
        "seasonal_sparse_a20_w84": (m2_sparse_features[:3], 20.0, 84),
        "credit_sparse_a20_w60": (m2_sparse_features, 20.0, 60),
        "credit_sparse_a50_w84": (m2_sparse_features, 50.0, 84),
        "bill_sparse_a50_w60": (m2_sparse_features + ["bill_yoy"], 50.0, 60),
    }
    m2_candidate_yoy: dict[str, pd.Series] = {}
    m2_candidate_levels: dict[str, pd.Series] = {}
    for name, (features, alpha, window) in m2_candidate_specs.items():
        candidate_yoy, candidate_level = walk_forward_m2_level_bridge(
            m2_frame, m2_level, features, alpha=alpha, window=window
        )
        m2_candidate_yoy[name] = candidate_yoy
        m2_candidate_levels[name] = candidate_level
    m2_candidate_frame = pd.concat(m2_candidate_yoy, axis=1, sort=False)
    m2_model, m2_candidate_choices = rolling_candidate_selection(
        m2_candidate_frame, m2, lookback=48, min_history=12
    )
    m2_level_model = pd.Series(dtype=float)
    for day in m2_model.index:
        history = m2_candidate_frame.loc[m2_candidate_frame.index < day].join(m2.rename("actual")).dropna().iloc[-48:]
        available = m2_candidate_frame.loc[day].dropna()
        if available.empty:
            continue
        if len(history) < 12:
            choice = available.index[0]
        else:
            errors = history.drop(columns="actual").sub(history["actual"], axis=0)
            choice = np.sqrt((errors**2).mean()).reindex(available.index).idxmin()
        m2_level_model.loc[day] = m2_candidate_levels[choice].loc[day]
    m2_fallback, m2_fallback_level = m2_seasonal_level_fallback(m2_level)
    m2_model = m2_model.combine_first(m2_fallback).sort_index()
    m2_level_model = m2_level_model.combine_first(m2_fallback_level).sort_index()

    final_models = {"m2_yoy": m2_model, "new_rmb_loans": loan_model, "social_financing": tsf_model}
    actuals = {"m2_yoy": m2, "new_rmb_loans": loans, "social_financing": tsf}
    consensus = {
        "m2_yoy": series(data["m2_consensus"]["observations"]),
        "new_rmb_loans": series(data["new_rmb_loans_consensus"]["observations"], 1e12),
        "social_financing": series(data["social_financing_consensus"]["observations"], 1e12),
    }

    comparisons = {key: consensus_metrics(consensus[key], actuals[key], final_models[key]) for key in final_models}
    diagnostics = {
        "m2_yoy": {
            "final": metrics(m2_model, m2),
            "legacyPersistence": metrics(m2_legacy, m2),
            "candidateMetrics": {name: metrics(value, m2) for name, value in m2_candidate_yoy.items()},
            "candidateSelectionCounts": m2_candidate_choices,
            "candidateSpecifications": {
                name: {"features": features, "alpha": alpha, "window": window}
                for name, (features, alpha, window) in m2_candidate_specs.items()
            },
            "seasonalBalanceFallback": metrics(m2_fallback, m2),
            "turningPointHitRatePct": turning_point_hit_rate(m2_model, m2),
            "legacyTurningPointHitRatePct": turning_point_hit_rate(m2_legacy, m2),
            "latestForecastBalanceTrillion": round(float(m2_level_model.loc[TARGET_MONTH]), 3),
            "previousMonthBalanceTrillion": round(float(m2_level.loc[TARGET_MONTH - pd.offsets.MonthEnd(1)]), 3),
        },
        "new_rmb_loans": {
            "final": metrics(loan_model, loans),
            "preResidualAdjustment": metrics(loan_pre_residual, loans),
            "preBillStructural": metrics(loan_structural, loans),
            "dynamicSeasonalChallenger": metrics(loan_dynamic, loans),
            "candidateSelectionCounts": loan_choices,
            "billOverlay": {
                "providerId": data["bill_discount_3m"]["providerId"],
                "firstAppliedMonth": bill_adjustments.index.min().strftime("%Y-%m") if len(bill_adjustments) else None,
                "latestAdjustment": round(float(bill_adjustments.iloc[-1]), 6) if len(bill_adjustments) else None,
            },
            "plainSeasonal": metrics(loan_candidate_frame["seasonal_drift_0"].loc[BACKTEST_START:], loans),
        },
        "social_financing": {
            "final": metrics(tsf_model, tsf),
            "preResidualAdjustment": metrics(tsf_pre_residual, tsf),
            "preRobustShrink": metrics(tsf_pre_shrink, tsf),
            "structural": metrics(tsf_structural, tsf),
            "monthlyMacroAugmented": metrics(tsf_macro, tsf),
            "componentBridge": metrics(tsf_components, tsf),
            "candidateSet": list(tsf_candidates.columns),
            "latestCandidateWeights": trailing_candidate_weights(tsf_candidates, tsf, TARGET_MONTH),
        },
    }

    history = {}
    for key in final_models:
        joined = pd.concat(
            [
                final_models[key].rename("model"),
                consensus[key].rename("consensus"),
                actuals[key].rename("actual"),
            ],
            axis=1,
            sort=False,
        ).sort_index().loc["2020-01-31":TARGET_MONTH]
        history[key] = [
            {
                "date": day.strftime("%Y-%m"),
                "model": round(float(row["model"]), 6) if pd.notna(row["model"]) else None,
                "consensus": round(float(row["consensus"]), 6) if pd.notna(row["consensus"]) else None,
                "actual": round(float(row["actual"]), 6) if pd.notna(row["actual"]) else None,
            }
            for day, row in joined.iterrows()
        ]

    current = {}
    units = {"m2_yoy": "%", "new_rmb_loans": "万亿元", "social_financing": "万亿元"}
    for key in final_models:
        point = round(float(final_models[key].loc[TARGET_MONTH]), 2)
        expected = current_consensus(consensus[key])
        rmse = float(diagnostics[key]["final"]["rmse"])
        current[key] = {
            "model": point,
            "consensus": expected,
            "unit": units[key],
            "gapVsConsensus": round(point - expected, 2) if expected is not None else None,
            "consensusStatus": "available" if expected is not None else "not_yet_published",
            "approx68PctRange": [round(point - rmse, 2), round(point + rmse, 2)],
        }

    performance_gate = {}
    for key in ("new_rmb_loans", "social_financing"):
        model_rmse = float(comparisons[key]["model"]["rmse"])
        consensus_rmse = float(comparisons[key]["consensus"]["rmse"])
        performance_gate[key] = {
            "passed": model_rmse < consensus_rmse,
            "modelRmse": model_rmse,
            "consensusRmse": consensus_rmse,
            "remainingGap": round(model_rmse - consensus_rmse, 6),
        }

    return {
        "schemaVersion": 5,
        "modelVersion": MODEL_VERSION,
        "modelFrozen": True,
        "modelFrozenAt": MODEL_FROZEN_AT,
        "forecastMonth": TARGET_MONTH.strftime("%Y-%m"),
        "dataRetrievedAt": source["retrievedAt"],
        "method": "target-specific no-leakage models: M2 balance-change bridge converted back to YoY; seasonal-drift, bill-rate overlay and online residual correction for loans; structural and official-component TSF challengers with robust same-month shrinkage and online residual correction",
        "consensusPolicy": source["consensusPolicy"],
        "current": current,
        "monthlyModelInputs": macro_forecasts,
        "informationSet": {
            "historicalBacktest": {
                "timing": "immediately_before_each_credit_release",
                "sameMonthActual": ["cpi", "ppi", "pmi"],
                "priorMonthActual": ["industrial_value"],
            },
            "liveMonth": {
                "asOf": source["retrievedAt"],
                "policy": "use released actual when available; otherwise use the project's generated no-consensus forecast",
            },
        },
        "diagnostics": diagnostics,
        "comparisonOnCommonSample": comparisons,
        "performanceGateVsConsensus": performance_gate,
        "history": history,
        "providerIds": {key: value["providerId"] for key, value in data.items()},
        "notes": [
            "Consensus is merged only after every forecast and model weight has been fixed.",
            "Every historical prediction is walk-forward: only observations dated before the predicted month enter training, candidate selection or challenger weights.",
            "M2 is forecast in balance space: the prior-month balance is advanced with a predicted monthly stock change, then divided by the prior-year same-month balance to obtain YoY; lagged M2 YoY is diagnostic only.",
            "M2 uses no TSF forecast and no lagged M2 YoY predictor: four predeclared sparse balance-change candidates contain at most six inputs, and the candidate for each month is selected only from the previous 48 months of out-of-sample errors.",
            "Historical TSF diagnostics use same-month released CPI/PPI/PMI values because they are available before the credit release; industrial value added remains lagged. The live month uses generated forecasts only where the actual is not yet released.",
            "The component bridge covers ten official PBOC categories plus an exact other/reconciliation residual; it is retained only when trailing OOS errors justify weight.",
            "The loan bill-rate overlay uses contemporaneous market prices, never survey expectations; its coefficient uses only earlier forecast residuals and is capped at 0.5.",
            "Loan and TSF calendar/global residual corrections use only errors observed before each forecast month; the release-information macro TSF challenger is weighted only when its prior out-of-sample errors justify it.",
            "The performance gate is reported honestly: a lower RMSE than consensus is required for passed=true, and consensus never enters the forecast itself.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--forecasts", type=Path, default=DEFAULT_FORECASTS)
    parser.add_argument("--industrial", type=Path, default=DEFAULT_INDUSTRIAL)
    parser.add_argument("--model-inputs", type=Path, default=DEFAULT_MODEL_INPUTS)
    parser.add_argument("--industrial-source", type=Path, default=DEFAULT_INDUSTRIAL_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build(args.source, args.forecasts, args.industrial, args.model_inputs, args.industrial_source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["current"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
