#!/usr/bin/env python3
"""No-consensus industrial-value nowcast inspired by GF Macro's diffusion method."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "industrial-value-model" / "targets_consensus.json"
DEFAULT_MODEL_INPUTS = ROOT / "data" / "forecast-model" / "model_inputs.json"
DEFAULT_DASHBOARD = ROOT / "public" / "data" / "dashboard.json"
DEFAULT_PRODUCTION_INPUTS = ROOT / "data" / "industrial-value-model" / "production_inputs.json"
DEFAULT_OUTPUT = ROOT / "data" / "industrial-value-model" / "forecast_results.json"
BACKTEST_START = pd.Timestamp("2023-03-31")
BRIDGE_TRAIN_START = pd.Timestamp("2020-01-31")
BRIDGE_TRAIN_WINDOW = 48
BRIDGE_WEIGHT = 0.40
RIDGE_ALPHA = 32.0
STANDARDIZATION_WINDOW = 36
STANDARDIZATION_MIN_PERIODS = 12

BRIDGE_FEATURES = [
    "diffusion",
    "diffusion_change",
    "pmi_production",
    "pmi_production_yoy_diff",
    "black_acceleration",
    "energy_acceleration",
    "chemical_acceleration",
    "auto_acceleration",
    "broad_car_output_yoy",
    "broad_car_output_yoy_change",
]

CALENDAR_FEATURES = ["february", "march", "october", "year_end"]
ROBUST_ENSEMBLE_WEIGHTS = {
    "gfFast": 0.25,
    "turningPoint": 0.50,
    "calendarAdjusted": 0.25,
}

ARDL_FEATURES = ["lag1", "diffusion_ii", "diffusion_ii_lag1", "diffusion", "diffusion_lag1"]
ARDL_ALPHA = 32.0
ARDL_BRIDGE_WEIGHT = 0.60
ARDL_TRAIN_START = pd.Timestamp("2020-01-31")

FEATURES = {
    "blast_furnace": {"legacy": "高炉开工率(247家):全国", "dashboard": "blast_furnace", "family": "black", "kind": "rate"},
    "rebar_rate": {"legacy": "螺纹钢:主要钢厂开工率:全国", "dashboard": None, "family": "black", "kind": "rate"},
    "crude_steel": {"legacy": None, "dashboard": "crude_steel", "family": "black", "kind": "volume"},
    "construction_steel": {"legacy": None, "dashboard": "construction_steel", "family": "black", "kind": "volume"},
    "power_coal": {"legacy": "日耗量:煤炭:6大发电集团", "dashboard": "power_coal", "family": "energy", "kind": "volume"},
    "pta_rate": {"legacy": "PTA负荷率", "dashboard": "pta_rate", "family": "chemical", "kind": "rate"},
    "methanol_rate": {"legacy": "甲醇开工率", "dashboard": None, "family": "chemical", "kind": "rate"},
    "polyester_rate": {"legacy": None, "dashboard": "polyester_rate", "family": "chemical", "kind": "rate"},
    "car_wholesale": {"legacy": "乘用车批发销量", "dashboard": None, "family": "auto", "kind": "volume"},
    "car_retail": {"legacy": "乘用车市场零售", "dashboard": None, "family": "auto", "kind": "volume"},
    "broad_car_output_yoy": {"legacy": None, "dashboard": None, "family": "auto", "kind": "yoy", "role": "amplitude"},
    "excavator_sales_yoy": {"legacy": None, "dashboard": None, "family": "demand", "kind": "yoy", "role": "amplitude"},
    "full_tire": {"legacy": None, "dashboard": "full_tire_rate", "family": "auto", "kind": "rate"},
    "semi_tire": {"legacy": None, "dashboard": "semi_tire_rate", "family": "auto", "kind": "rate"},
}

# Bottom-up candidates are deliberately broader than the production diffusion
# basket.  They cover upstream production, inventories, downstream demand and
# transport.  Selection is re-run inside every walk-forward month, so this list
# is a research universe rather than a fixed, full-sample-picked model.
BOTTOM_UP_CANDIDATES = {
    "car_retail_yoy": {"dashboard": "car_retail_yoy", "family": "auto", "kind": "yoy"},
    "car_wholesale_yoy": {"dashboard": "car_wholesale_yoy", "family": "auto", "kind": "yoy"},
    "construction_steel": {"dashboard": "construction_steel", "raw": "construction_steel", "family": "black", "kind": "volume"},
    "asphalt_rate": {"dashboard": "asphalt_rate", "family": "demand", "kind": "rate"},
    "power_coal": {"dashboard": "power_coal", "raw": "power_coal", "family": "energy", "kind": "volume"},
    "blast_furnace": {"dashboard": "blast_furnace", "raw": "blast_furnace", "family": "black", "kind": "rate"},
    "crude_steel": {"dashboard": "crude_steel", "raw": "crude_steel", "family": "black", "kind": "volume"},
    "tire_composite": {"dashboard": "tire_composite", "family": "auto", "kind": "rate"},
    "polyester_rate": {"dashboard": "polyester_rate", "raw": "polyester_rate", "family": "chemical", "kind": "rate"},
    "steel_inventory": {"dashboard": "steel_inventory", "family": "black", "kind": "volume"},
    "power_inventory": {"dashboard": "power_inventory", "family": "energy", "kind": "volume"},
    "port_coal_inventory": {"dashboard": "port_coal_inventory", "family": "energy", "kind": "volume"},
    "port_container": {"dashboard": "port_container", "family": "demand", "kind": "volume"},
    "pvc_rate": {"dashboard": "pvc_rate", "family": "chemical", "kind": "rate"},
    "cold_rolled_rate": {"dashboard": "cold_rolled_rate", "family": "black", "kind": "rate"},
    "glass_rate": {"dashboard": "glass_rate", "family": "demand", "kind": "rate"},
    "pta_rate": {"dashboard": "pta_rate", "raw": "pta_rate", "family": "chemical", "kind": "rate"},
    "px_rate": {"dashboard": "px_rate", "family": "chemical", "kind": "rate"},
    "full_tire_rate": {"dashboard": "full_tire_rate", "raw": "full_tire", "family": "auto", "kind": "rate"},
    "semi_tire_rate": {"dashboard": "semi_tire_rate", "raw": "semi_tire", "family": "auto", "kind": "rate"},
    "daqin_volume": {"dashboard": "daqin_volume", "family": "mining", "kind": "volume"},
    "filament_rate": {"dashboard": "filament_rate", "family": "chemical", "kind": "rate"},
    "staple_rate": {"dashboard": "staple_rate", "family": "chemical", "kind": "rate"},
    "coking_rate": {"dashboard": "coking_rate", "family": "black", "kind": "rate"},
    "methanol_rate": {"dashboard": "methanol_rate", "raw": "methanol_rate", "family": "chemical", "kind": "rate"},
    "styrene_rate": {"dashboard": "styrene_rate", "family": "chemical", "kind": "rate"},
    "medium_plate_inventory": {"dashboard": "medium_plate_inventory", "family": "black", "kind": "volume"},
    "cold_rolled_inventory": {"dashboard": "cold_rolled_inventory", "family": "black", "kind": "volume"},
    "rebar_inventory": {"dashboard": "rebar_inventory", "family": "black", "kind": "volume"},
    "hrc_inventory": {"dashboard": "hrc_inventory", "family": "black", "kind": "volume"},
    "wire_inventory": {"dashboard": "wire_inventory", "family": "black", "kind": "volume"},
    "newhome_30c": {"dashboard": "newhome_30c", "family": "demand", "kind": "volume"},
    "land_4w": {"dashboard": "land_4w", "family": "demand", "kind": "volume"},
    "metro_composite": {"dashboard": "metro_composite", "family": "demand", "kind": "volume"},
    "flights_7d": {"dashboard": "flights_7d", "family": "demand", "kind": "volume"},
}

BOTTOM_UP_MIN_OBSERVATIONS = 18
BOTTOM_UP_MAX_FACTORS = 3
BOTTOM_UP_ALPHA = 32.0
# The factor branch keeps no extra persistence anchor: the core model already
# supplies inertia, while this branch exists specifically to react to turns.
BOTTOM_UP_PURE_WEIGHT = 1.00
BOTTOM_UP_ENSEMBLE_WEIGHT = 0.25
RESPONSIVE_CORE_PERSISTENCE_WEIGHT = 0.45
LEGACY_CORE_PERSISTENCE_WEIGHT = 0.55
FIXED_VOLUME_ALPHA = 32.0
FIXED_VOLUME_HIGH_FREQUENCY_WEIGHT = 0.70

# Production correlation model.  It contains no lagged target and no
# persistence anchor.  Every forecast month recomputes rankings using target
# observations strictly before that month.
CORRELATION_MIN_OBSERVATIONS = 18
CORRELATION_MAX_FACTORS = 3
CORRELATION_RECENT_WINDOW = 24
CORRELATION_FIT_WINDOW = 48
CORRELATION_RIDGE_ALPHA = 64.0

FIXED_FACTOR_NAMES = (
    "power_coal",
    "blast_furnace",
    "methanol_rate",
    "full_tire_rate",
    "asphalt_rate",
)
FIXED_FACTOR_MINIMUM_AVAILABLE = 2
FIXED_FACTOR_FIT_WINDOW = 36
FIXED_FACTOR_RIDGE_ALPHA = 32.0
STATISTICAL_CARRY_NAME = "known_fixed_volume_carry"

# Fixed GF-report proxy basket.  The factor identities never change by month.
# The 19 series are grouped into five production/demand channels and each
# channel contributes three distinct pieces of information: level, breadth of
# YoY acceleration, and standardized acceleration.  Official product-output
# series released with industrial value (including official generation YoY)
# are intentionally excluded to prevent same-release leakage.
REPORT_PROXY_EXTRA = {
    "newhome": {"dashboard": "newhome_30c", "family": "demand", "kind": "volume"},
    "rebar_consumption": {"dashboard": None, "family": "black", "kind": "volume"},
    "asphalt_rate": {"dashboard": "asphalt_rate", "family": "demand", "kind": "rate"},
    "steel_inventory": {"dashboard": "steel_inventory", "family": "black", "kind": "volume"},
    "car_retail_yoy": {"dashboard": "car_retail_yoy", "family": "auto", "kind": "yoy"},
}
REPORT_FAMILIES = ("black", "chemical", "auto", "energy", "demand")
REPORT_PROXY_FACTOR_NAMES = (*FEATURES.keys(), *REPORT_PROXY_EXTRA.keys())
PRODUCTION_FACTOR_NAMES = tuple(dict.fromkeys((*FIXED_FACTOR_NAMES, *REPORT_PROXY_FACTOR_NAMES)))
REPORT_HYBRID_FEATURES = tuple(
    [f"{family}_breadth" for family in REPORT_FAMILIES]
    + [f"{family}_level" for family in REPORT_FAMILIES]
    + [f"{family}_acceleration" for family in REPORT_FAMILIES]
)
REPORT_HYBRID_TRAIN_WINDOW = 48
REPORT_HYBRID_RIDGE_ALPHA = 32.0
REPORT_HYBRID_MIN_TRAIN = 18
REPORT_ONLINE_MIN_ERRORS = 6
INDIVIDUAL_REPORT_TRAIN_WINDOW = 24
INDIVIDUAL_REPORT_RIDGE_ALPHA = 512.0
INDIVIDUAL_REPORT_MIN_TRAIN = 24
INDIVIDUAL_REPORT_INITIAL_WEIGHT = 0.25
CALIBRATION_OVERALL_WEIGHT = 0.75
CALIBRATION_SAME_MONTH_WEIGHT = 0.25
CALIBRATION_MIN_ERRORS = 6


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def series_from_rows(rows: list[list[Any]]) -> pd.Series:
    frame = pd.DataFrame(rows, columns=["date", "value"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame.dropna().drop_duplicates("date", keep="last").set_index("date")["value"].sort_index()


def monthly_target(source: dict[str, Any]) -> pd.Series:
    monthly = series_from_rows(source["series"]["actualMonthly"]["observations"])
    ytd = series_from_rows(source["series"]["actualYtd"]["observations"])
    monthly = monthly.copy()
    monthly.loc[monthly.index.month == 1] = np.nan
    february = ytd.loc[ytd.index.month == 2]
    monthly.loc[february.index] = february
    return monthly.dropna().sort_index()


def dashboard_series(dashboard: dict[str, Any], indicator_id: str) -> pd.Series:
    item = next((row for row in dashboard.get("indicators", []) if row.get("id") == indicator_id), None)
    return series_from_rows([[row["date"], row["value"]] for row in item.get("series", [])]) if item else pd.Series(dtype=float)


def merge_series(old: pd.Series, new: pd.Series) -> pd.Series:
    combined = pd.concat([old.rename("old"), new.rename("new")], axis=1, sort=True)
    return combined["new"].combine_first(combined["old"]).dropna().sort_index()


def build_raw_features(model_inputs: dict[str, Any], dashboard: dict[str, Any], production: dict[str, Any]) -> tuple[dict[str, pd.Series], dict[str, Any]]:
    legacy = model_inputs.get("raw", {})
    raw: dict[str, pd.Series] = {}
    provenance: dict[str, Any] = {}
    for key, config in FEATURES.items():
        old = series_from_rows(legacy[config["legacy"]]["data"]) if config["legacy"] in legacy else pd.Series(dtype=float)
        new = dashboard_series(dashboard, config["dashboard"]) if config["dashboard"] else pd.Series(dtype=float)
        live_config = production.get("series", {}).get(key)
        live = series_from_rows(live_config["observations"]) if live_config else pd.Series(dtype=float)
        raw[key] = merge_series(merge_series(old, new), live)
        provenance[key] = {
            "family": config["family"], "kind": config["kind"],
            "role": config.get("role", "diffusion"),
            "providerId": live_config.get("providerId") if live_config else None,
            "start": raw[key].index.min().date().isoformat() if not raw[key].empty else None,
            "end": raw[key].index.max().date().isoformat() if not raw[key].empty else None,
            "observations": int(len(raw[key])),
        }
    return raw, provenance


def build_monthly_features(raw: dict[str, pd.Series], model_inputs: dict[str, Any]) -> pd.DataFrame:
    signals: dict[str, pd.Series] = {}
    for key, values in raw.items():
        monthly = values.resample("ME").mean()
        if FEATURES[key]["kind"] == "yoy":
            signals[key] = monthly
        elif FEATURES[key]["kind"] == "rate":
            signals[key] = monthly.diff(12)
        else:
            signals[key] = monthly.pct_change(12, fill_method=None) * 100
    signal_frame = pd.DataFrame(signals).replace([np.inf, -np.inf], np.nan)
    directions = signal_frame.diff().gt(0).where(signal_frame.diff().notna())
    family_scores = {}
    rolling_mean = signal_frame.rolling(STANDARDIZATION_WINDOW, min_periods=STANDARDIZATION_MIN_PERIODS).mean()
    rolling_std = signal_frame.rolling(STANDARDIZATION_WINDOW, min_periods=STANDARDIZATION_MIN_PERIODS).std().replace(0, np.nan)
    standardized_signal = (signal_frame - rolling_mean) / rolling_std
    family_acceleration = {}
    core_features = {key: config for key, config in FEATURES.items() if config.get("role", "diffusion") == "diffusion"}
    for family in sorted({config["family"] for config in core_features.values()}):
        columns = [key for key, config in core_features.items() if config["family"] == family]
        family_scores[family] = directions[columns].mean(axis=1, skipna=True) * 100
        family_acceleration[family] = standardized_signal[columns].diff().mean(axis=1, skipna=True)
    diffusion = pd.DataFrame(family_scores).mean(axis=1, skipna=True)
    diffusion_ii = ((diffusion - 50.0) / 50.0).fillna(0.0).cumsum()

    pmi_rows = model_inputs["pmiSubindices"]["制造业PMI:生产（单位：%）"]
    pmi = pd.Series({pd.Timestamp(day): float(value) for day, value in pmi_rows.items()}).sort_index()
    features = pd.DataFrame({
        "diffusion": diffusion,
        "diffusion_change": diffusion.diff(),
        "diffusion_lag1": diffusion.shift(1),
        "diffusion_ii": diffusion_ii,
        "diffusion_ii_lag1": diffusion_ii.shift(1),
        "pmi_production": pmi,
        "pmi_production_yoy_diff": pmi.diff(12),
    })
    for family, values in family_acceleration.items():
        features[f"{family}_acceleration"] = values
    for key in ("broad_car_output_yoy", "excavator_sales_yoy"):
        features[key] = signal_frame.get(key)
        features[f"{key}_change"] = signal_frame.get(key).diff() if key in signal_frame else np.nan
    features["february"] = (features.index.month == 2).astype(float)
    features["march"] = (features.index.month == 3).astype(float)
    features["october"] = (features.index.month == 10).astype(float)
    features["year_end"] = features.index.month.isin([11, 12]).astype(float)
    return features.sort_index()


def build_bottom_up_signals(raw: dict[str, pd.Series], dashboard: dict[str, Any]) -> pd.DataFrame:
    """Convert heterogeneous high-frequency levels into comparable YoY signals."""
    signals: dict[str, pd.Series] = {}
    for name, config in BOTTOM_UP_CANDIDATES.items():
        values = dashboard_series(dashboard, config["dashboard"])
        raw_name = config.get("raw")
        if raw_name in raw:
            values = merge_series(raw[raw_name], values)
        if values.empty:
            signals[name] = pd.Series(dtype=float)
            continue
        monthly = values.resample("ME").mean()
        if config["kind"] == "yoy":
            signal = monthly
        elif config["kind"] == "rate":
            signal = monthly.diff(12)
        else:
            signal = monthly.pct_change(12, fill_method=None) * 100.0
        # The official February target is January-February cumulative growth,
        # not a February-only monthly observation.  Match the factor window to
        # that release by recomputing every February from the full two-month
        # high-frequency sample and the comparable prior-year sample.
        for year in range(values.index.min().year + 1, values.index.max().year + 1):
            february_end = pd.Timestamp(year, 2, 1) + pd.offsets.MonthEnd(0)
            current = values.loc[
                (values.index >= pd.Timestamp(year, 1, 1))
                & (values.index <= february_end)
            ].mean()
            prior = values.loc[
                (values.index >= pd.Timestamp(year - 1, 1, 1))
                & (values.index <= pd.Timestamp(year - 1, 2, 1) + pd.offsets.MonthEnd(0))
            ].mean()
            if pd.isna(current):
                continue
            if config["kind"] == "yoy":
                combined = current
            elif config["kind"] == "rate":
                combined = current - prior if pd.notna(prior) else np.nan
            else:
                combined = (current / prior - 1.0) * 100.0 if pd.notna(prior) and prior != 0 else np.nan
            signal.loc[february_end] = combined
        signals[name] = signal
    return pd.DataFrame(signals).replace([np.inf, -np.inf], np.nan).sort_index()


def rank_correlated_factors(
    train: pd.DataFrame,
    current: pd.Series | None = None,
    max_factors: int = CORRELATION_MAX_FACTORS,
    enforce_family_diversity: bool = True,
) -> list[dict[str, Any]]:
    """Rank contemporaneous high-frequency signals using prior targets only."""
    ranked: list[dict[str, Any]] = []
    for name, config in BOTTOM_UP_CANDIDATES.items():
        if name not in train or (current is not None and pd.isna(current.get(name))):
            continue
        paired = train[["target", name]].dropna()
        if len(paired) < CORRELATION_MIN_OBSERVATIONS or paired[name].std() == 0:
            continue
        full_corr = paired["target"].corr(paired[name])
        recent = paired.iloc[-CORRELATION_RECENT_WINDOW:]
        recent_corr = recent["target"].corr(recent[name]) if len(recent) >= 12 else full_corr
        midpoint = len(paired) // 2
        first_corr = paired.iloc[:midpoint]["target"].corr(paired.iloc[:midpoint][name])
        second_corr = paired.iloc[midpoint:]["target"].corr(paired.iloc[midpoint:][name])
        stable_abs = (
            min(abs(float(first_corr)), abs(float(second_corr)))
            if pd.notna(first_corr) and pd.notna(second_corr) and np.sign(first_corr) == np.sign(second_corr)
            else 0.0
        )
        score = 0.50 * abs(float(full_corr)) + 0.40 * abs(float(recent_corr)) + 0.10 * stable_abs
        ranked.append({
            "name": name,
            "family": config["family"],
            "score": score,
            "fullCorrelation": float(full_corr),
            "recentCorrelation": float(recent_corr),
            "stableAbsCorrelation": stable_abs,
            "observations": int(len(paired)),
        })
    selected: list[dict[str, Any]] = []
    used_families: set[str] = set()
    for item in sorted(ranked, key=lambda row: (-row["score"], row["name"])):
        if enforce_family_diversity and item["family"] in used_families:
            continue
        selected.append(item)
        used_families.add(item["family"])
        if len(selected) >= max_factors:
            break
    return selected


def correlation_walk_forward(
    target: pd.Series,
    signals: pd.DataFrame,
) -> tuple[pd.Series, dict[pd.Timestamp, list[dict[str, Any]]]]:
    """Forecast target levels from correlation-selected current signals."""
    calendar = pd.date_range(min(target.index.min(), signals.index.min()), max(target.index.max(), signals.index.max()), freq="ME")
    frame = signals.reindex(calendar)
    frame["target"] = target.reindex(calendar)
    predictions: dict[pd.Timestamp, float] = {}
    selections: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for day in calendar[calendar >= BACKTEST_START]:
        train = frame.loc[frame.index < day].dropna(subset=["target"])
        chosen = rank_correlated_factors(train, frame.loc[day])
        columns = [item["name"] for item in chosen]
        if len(columns) < 2:
            continue
        fit_train = train.loc[train[columns].notna().sum(axis=1) >= 2].iloc[-CORRELATION_FIT_WINDOW:]
        if len(fit_train) < CORRELATION_MIN_OBSERVATIONS:
            continue
        predictions[day] = ridge_fit_predict(fit_train, frame.loc[day], CORRELATION_RIDGE_ALPHA, columns)
        selections[day] = chosen
    return pd.Series(predictions, dtype=float).sort_index(), selections


def fixed_factor_walk_forward(target: pd.Series, signals: pd.DataFrame) -> pd.Series:
    """Forecast with an unchanged, economically defined five-factor set."""
    factors = list(FIXED_FACTOR_NAMES)
    calendar = pd.date_range(min(target.index.min(), signals.index.min()), max(target.index.max(), signals.index.max()), freq="ME")
    frame = signals.reindex(calendar)
    frame["target"] = target.reindex(calendar)
    predictions: dict[pd.Timestamp, float] = {}
    for day in calendar[calendar >= BACKTEST_START]:
        if frame.loc[day, factors].notna().sum() < FIXED_FACTOR_MINIMUM_AVAILABLE:
            continue
        train = frame.loc[frame.index < day].dropna(subset=["target"])
        train = train.loc[
            train[factors].notna().sum(axis=1) >= FIXED_FACTOR_MINIMUM_AVAILABLE
        ].iloc[-FIXED_FACTOR_FIT_WINDOW:]
        if len(train) < CORRELATION_MIN_OBSERVATIONS:
            continue
        predictions[day] = ridge_fit_predict(
            train,
            frame.loc[day],
            FIXED_FACTOR_RIDGE_ALPHA,
            factors,
        )
    return pd.Series(predictions, dtype=float).sort_index()


def known_fixed_volume_carry(industrial_mom_sa: pd.Series) -> pd.Series:
    """Known contribution of the preceding 11 months to current YoY growth.

    For month t, the index ratio I[t-1] / I[t-12] contains only observations
    released before t.  February is intentionally blank because its official
    target is a January-February cumulative release and the January MoM value
    is not independently available before that release.
    """
    level = (1.0 + industrial_mom_sa.sort_index() / 100.0).cumprod() * 100.0
    calendar = pd.date_range(
        level.index.min(),
        level.index.max() + pd.offsets.MonthEnd(1),
        freq="ME",
    )
    level = level.reindex(calendar)
    carry = (level.shift(1) / level.shift(12) - 1.0) * 100.0
    carry.loc[carry.index.month == 2] = np.nan
    return carry.rename(STATISTICAL_CARRY_NAME)


def statistical_bridge_walk_forward(
    target: pd.Series,
    signals: pd.DataFrame,
    industrial_mom_sa: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Fixed-factor bridge with an explicit, already-known base contribution.

    Non-February forecasts combine the preceding 11-month fixed-volume carry
    with the unchanged five current high-frequency production signals.
    February falls back to the same fixed factors computed over January and
    February together, avoiding same-release MoM leakage.
    """
    carry = known_fixed_volume_carry(industrial_mom_sa)
    factors = list(FIXED_FACTOR_NAMES)
    bridge_columns = [STATISTICAL_CARRY_NAME, *factors]
    calendar = pd.date_range(
        min(target.index.min(), signals.index.min(), carry.index.min()),
        max(target.index.max(), signals.index.max(), carry.index.max()),
        freq="ME",
    )
    frame = signals.reindex(calendar)
    frame[STATISTICAL_CARRY_NAME] = carry.reindex(calendar)
    frame["target"] = target.reindex(calendar)
    predictions: dict[pd.Timestamp, float] = {}
    for day in calendar[calendar >= BACKTEST_START]:
        columns = factors if day.month == 2 else bridge_columns
        if frame.loc[day, columns].notna().sum() < FIXED_FACTOR_MINIMUM_AVAILABLE:
            continue
        train = frame.loc[frame.index < day].dropna(subset=["target"])
        train = train.loc[
            train[columns].notna().sum(axis=1) >= FIXED_FACTOR_MINIMUM_AVAILABLE
        ].iloc[-FIXED_FACTOR_FIT_WINDOW:]
        if len(train) < CORRELATION_MIN_OBSERVATIONS:
            continue
        predictions[day] = ridge_fit_predict(
            train,
            frame.loc[day],
            FIXED_FACTOR_RIDGE_ALPHA,
            columns,
        )
    return pd.Series(predictions, dtype=float).sort_index(), carry


def build_report_family_features(
    raw: dict[str, pd.Series],
    model_inputs: dict[str, Any],
    dashboard: dict[str, Any],
) -> pd.DataFrame:
    """Build the fixed 19-series GF-style level/breadth/acceleration panel."""
    legacy = model_inputs.get("raw", {})
    report_raw = dict(raw)
    report_raw.update({
        "newhome": merge_series(
            series_from_rows(legacy.get("30城商品房成交面积", {}).get("data", [])),
            dashboard_series(dashboard, "newhome_30c"),
        ),
        "rebar_consumption": series_from_rows(
            legacy.get("螺纹钢表观消费", {}).get("data", [])
        ),
        "asphalt_rate": dashboard_series(dashboard, "asphalt_rate"),
        "steel_inventory": dashboard_series(dashboard, "steel_inventory"),
        "car_retail_yoy": dashboard_series(dashboard, "car_retail_yoy"),
    })
    configurations = {
        **{name: {"family": item["family"], "kind": item["kind"]} for name, item in FEATURES.items()},
        **REPORT_PROXY_EXTRA,
    }
    signals: dict[str, pd.Series] = {}
    for name in REPORT_PROXY_FACTOR_NAMES:
        values = report_raw.get(name, pd.Series(dtype=float))
        if values.empty:
            signals[name] = pd.Series(dtype=float)
            continue
        monthly = values.resample("ME").mean()
        kind = configurations[name]["kind"]
        if kind == "yoy":
            signals[name] = monthly
        elif kind == "rate":
            signals[name] = monthly.diff(12)
        else:
            signals[name] = monthly.pct_change(12, fill_method=None) * 100.0
    signal_frame = pd.DataFrame(signals).replace([np.inf, -np.inf], np.nan).sort_index()
    direction = signal_frame.diff().gt(0).where(signal_frame.diff().notna())
    rolling_mean = signal_frame.rolling(
        STANDARDIZATION_WINDOW,
        min_periods=STANDARDIZATION_MIN_PERIODS,
    ).mean()
    rolling_std = signal_frame.rolling(
        STANDARDIZATION_WINDOW,
        min_periods=STANDARDIZATION_MIN_PERIODS,
    ).std().replace(0, np.nan)
    standardized = (signal_frame - rolling_mean) / rolling_std
    result = pd.DataFrame(index=signal_frame.index)
    for family in REPORT_FAMILIES:
        columns = [
            name for name in REPORT_PROXY_FACTOR_NAMES
            if configurations[name]["family"] == family
        ]
        result[f"{family}_breadth"] = direction[columns].mean(axis=1, skipna=True) * 100.0
        result[f"{family}_level"] = standardized[columns].mean(axis=1, skipna=True)
        result[f"{family}_acceleration"] = standardized[columns].diff().mean(axis=1, skipna=True)
    return result


def build_individual_report_features(
    raw: dict[str, pd.Series],
    model_inputs: dict[str, Any],
    dashboard: dict[str, Any],
) -> pd.DataFrame:
    """Keep the fixed report proxies separate so opposite sector moves survive.

    Each series is converted to a year-on-year production signal and then
    standardized against observations strictly before the current month.  The
    factor identities are fixed; no monthly correlation ranking is performed.
    """
    legacy = model_inputs.get("raw", {})
    report_raw = dict(raw)
    report_raw.update({
        "newhome": merge_series(
            series_from_rows(legacy.get("30城商品房成交面积", {}).get("data", [])),
            dashboard_series(dashboard, "newhome_30c"),
        ),
        "rebar_consumption": series_from_rows(
            legacy.get("螺纹钢表观消费", {}).get("data", [])
        ),
        "asphalt_rate": dashboard_series(dashboard, "asphalt_rate"),
        "steel_inventory": dashboard_series(dashboard, "steel_inventory"),
        "car_retail_yoy": dashboard_series(dashboard, "car_retail_yoy"),
    })
    configurations = {
        **{name: {"family": item["family"], "kind": item["kind"]} for name, item in FEATURES.items()},
        **REPORT_PROXY_EXTRA,
    }
    transformed: dict[str, pd.Series] = {}
    for name in REPORT_PROXY_FACTOR_NAMES:
        values = report_raw.get(name, pd.Series(dtype=float))
        if values.empty:
            continue
        monthly = values.resample("ME").mean()
        kind = configurations[name]["kind"]
        if kind == "yoy":
            transformed[name] = monthly
        elif kind == "rate":
            transformed[name] = monthly.diff(12)
        else:
            transformed[name] = monthly.pct_change(12, fill_method=None) * 100.0
    panel = pd.DataFrame(transformed).replace([np.inf, -np.inf], np.nan).sort_index()
    result: dict[str, pd.Series] = {}
    for name in panel.columns:
        prior = panel[name].shift(1)
        rolling_mean = prior.rolling(
            STANDARDIZATION_WINDOW,
            min_periods=STANDARDIZATION_MIN_PERIODS,
        ).mean()
        rolling_std = prior.rolling(
            STANDARDIZATION_WINDOW,
            min_periods=STANDARDIZATION_MIN_PERIODS,
        ).std().replace(0, np.nan)
        result[f"{name}_level"] = ((panel[name] - rolling_mean) / rolling_std).clip(-3.0, 3.0)
    return pd.DataFrame(result).replace([np.inf, -np.inf], np.nan).sort_index()


def individual_residual_walk_forward(
    target: pd.Series,
    carry: pd.Series,
    individual_features: pd.DataFrame,
    forecast_index: pd.Index,
) -> pd.Series:
    """Fit a high-shrinkage fixed-factor challenger using only prior targets."""
    calendar = individual_features.index.union(target.index).union(carry.index).sort_values()
    frame = individual_features.reindex(calendar)
    frame["carry"] = carry.reindex(calendar)
    frame["target_level"] = target.reindex(calendar)
    columns = list(individual_features.columns)
    minimum_available = max(4, len(columns) // 3)
    predictions: dict[pd.Timestamp, float] = {}
    for day in forecast_index:
        if day not in frame.index or frame.loc[day, columns].notna().sum() < minimum_available:
            continue
        if day.month == 2:
            train = frame.loc[frame.index < day].dropna(subset=["target_level"])
            train = train.loc[
                train[columns].notna().sum(axis=1) >= minimum_available
            ].iloc[-INDIVIDUAL_REPORT_TRAIN_WINDOW:]
            if len(train) < INDIVIDUAL_REPORT_MIN_TRAIN:
                continue
            fit = train.copy()
            fit["target"] = fit["target_level"]
            predictions[day] = ridge_fit_predict(
                fit,
                frame.loc[day],
                INDIVIDUAL_REPORT_RIDGE_ALPHA,
                columns,
            )
            continue
        if pd.isna(frame.loc[day, "carry"]):
            continue
        train = frame.loc[
            (frame.index < day) & (frame.index >= BRIDGE_TRAIN_START)
        ].dropna(subset=["target_level", "carry"])
        train = train.loc[
            train[columns].notna().sum(axis=1) >= minimum_available
        ].iloc[-INDIVIDUAL_REPORT_TRAIN_WINDOW:]
        if len(train) < INDIVIDUAL_REPORT_MIN_TRAIN:
            continue
        fit = train.copy()
        fit["target"] = fit["target_level"] - fit["carry"]
        increment = ridge_fit_predict(
            fit,
            frame.loc[day],
            INDIVIDUAL_REPORT_RIDGE_ALPHA,
            columns,
        )
        predictions[day] = float(frame.loc[day, "carry"] + increment)
    return pd.Series(predictions, dtype=float).sort_index()


def challenger_online_blend(
    base: pd.Series,
    challenger: pd.Series,
    target: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Add a challenger only when its prior OOS errors justify the weight."""
    blended = base.copy()
    weights: dict[pd.Timestamp, float] = {}
    common = base.index.intersection(challenger.index)
    for day in common:
        history_days = common[
            (common < day) & target.reindex(common).notna().to_numpy()
        ]
        if len(history_days) < REPORT_ONLINE_MIN_ERRORS:
            weight = INDIVIDUAL_REPORT_INITIAL_WEIGHT
        else:
            delta = challenger.reindex(history_days) - base.reindex(history_days)
            realized_gap = target.reindex(history_days) - base.reindex(history_days)
            valid = pd.concat(
                [delta.rename("delta"), realized_gap.rename("gap")], axis=1
            ).dropna()
            denominator = float((valid["delta"] ** 2).sum())
            weight = (
                float((valid["delta"] * valid["gap"]).sum() / denominator)
                if denominator else 0.0
            )
            weight = float(np.clip(weight, 0.0, 1.0))
        weights[day] = weight
        blended.loc[day] = float(
            base.loc[day] + weight * (challenger.loc[day] - base.loc[day])
        )
    return blended.sort_index(), pd.Series(weights, dtype=float).sort_index()


def report_residual_walk_forward(
    target: pd.Series,
    carry: pd.Series,
    report_features: pd.DataFrame,
    base_prediction: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Estimate the current-month increment, then combine using past OOS errors.

    The carry is an accounting offset and is never shrunk by the regression.
    The online blend weight for month t is estimated only from forecast errors
    whose targets were observable before t.
    """
    calendar = pd.date_range(
        min(target.index.min(), carry.index.min(), report_features.index.min()),
        max(target.index.max(), carry.index.max(), report_features.index.max()),
        freq="ME",
    )
    frame = report_features.reindex(calendar)
    frame["carry"] = carry.reindex(calendar)
    frame["target"] = target.reindex(calendar)
    columns = list(REPORT_HYBRID_FEATURES)
    pure: dict[pd.Timestamp, float] = {}
    for day in base_prediction.index:
        if day.month == 2:
            pure[day] = float(base_prediction.loc[day])
            continue
        if day not in frame.index or pd.isna(frame.loc[day, "carry"]):
            continue
        train = frame.loc[
            (frame.index < day) & (frame.index >= BRIDGE_TRAIN_START)
        ].dropna(subset=["target", "carry"])
        minimum_available = max(2, len(columns) // 3)
        train = train.loc[
            train[columns].notna().sum(axis=1) >= minimum_available
        ].iloc[-REPORT_HYBRID_TRAIN_WINDOW:]
        if len(train) < REPORT_HYBRID_MIN_TRAIN:
            continue
        train = train.copy()
        train["response"] = train["target"] - train["carry"]
        current_increment = ridge_fit_predict(
            train.rename(columns={"target": "target_level", "response": "target"}),
            frame.loc[day],
            REPORT_HYBRID_RIDGE_ALPHA,
            columns,
        )
        pure[day] = float(frame.loc[day, "carry"] + current_increment)
    pure_prediction = pd.Series(pure, dtype=float).sort_index()

    blended: dict[pd.Timestamp, float] = {}
    weights: dict[pd.Timestamp, float] = {}
    for day in pure_prediction.index:
        history_days = pure_prediction.index[
            (pure_prediction.index < day)
            & target.reindex(pure_prediction.index).notna().to_numpy()
        ]
        if len(history_days) < REPORT_ONLINE_MIN_ERRORS:
            weight = 0.5
        else:
            base_history = base_prediction.reindex(history_days)
            delta = pure_prediction.reindex(history_days) - base_history
            realized_gap = target.reindex(history_days) - base_history
            valid = pd.concat(
                [delta.rename("delta"), realized_gap.rename("gap")], axis=1
            ).dropna()
            denominator = float((valid["delta"] ** 2).sum())
            weight = (
                float((valid["delta"] * valid["gap"]).sum() / denominator)
                if denominator else 0.0
            )
            weight = float(np.clip(weight, 0.0, 1.0))
        weights[day] = weight
        blended[day] = float(
            base_prediction.loc[day]
            + weight * (pure_prediction.loc[day] - base_prediction.loc[day])
        )
    return (
        pd.Series(blended, dtype=float).sort_index(),
        pure_prediction,
        pd.Series(weights, dtype=float).sort_index(),
    )


def historical_error_calibration(
    prediction: pd.Series,
    target: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Correct systematic and calendar bias using prior OOS errors only."""
    calibrated: dict[pd.Timestamp, float] = {}
    corrections: dict[pd.Timestamp, float] = {}
    for day, value in prediction.sort_index().items():
        prior_days = prediction.index[prediction.index < day]
        prior_errors = (
            target.reindex(prior_days) - prediction.reindex(prior_days)
        ).dropna()
        overall = (
            float(prior_errors.mean())
            if len(prior_errors) >= CALIBRATION_MIN_ERRORS else 0.0
        )
        same_month_days = prior_days[prior_days.month == day.month]
        same_month_errors = (
            target.reindex(same_month_days) - prediction.reindex(same_month_days)
        ).dropna()
        same_month = float(same_month_errors.iloc[-1]) if len(same_month_errors) else 0.0
        correction = (
            CALIBRATION_OVERALL_WEIGHT * overall
            + CALIBRATION_SAME_MONTH_WEIGHT * same_month
        )
        corrections[day] = correction
        calibrated[day] = float(value + correction)
    return (
        pd.Series(calibrated, dtype=float).sort_index(),
        pd.Series(corrections, dtype=float).sort_index(),
    )


def build_bottom_up_monthly_changes(raw: dict[str, pd.Series], dashboard: dict[str, Any]) -> pd.DataFrame:
    """Build current-month physical changes for the fixed-volume branch."""
    changes: dict[str, pd.Series] = {}
    for name, config in BOTTOM_UP_CANDIDATES.items():
        values = dashboard_series(dashboard, config["dashboard"])
        raw_name = config.get("raw")
        if raw_name in raw:
            values = merge_series(raw[raw_name], values)
        monthly = values.resample("ME").mean()
        if config["kind"] in {"rate", "yoy"}:
            changes[name] = monthly.diff()
        else:
            changes[name] = monthly.pct_change(fill_method=None) * 100.0
    return pd.DataFrame(changes).replace([np.inf, -np.inf], np.nan).sort_index()


def rank_bottom_up_factors(
    train: pd.DataFrame,
    current: pd.Series | None = None,
    max_factors: int = BOTTOM_UP_MAX_FACTORS,
) -> list[dict[str, Any]]:
    """Rank factors on prior observations only and keep at most one per family."""
    ranked: list[dict[str, Any]] = []
    for name, config in BOTTOM_UP_CANDIDATES.items():
        if name not in train or (current is not None and pd.isna(current.get(name))):
            continue
        paired = train[["target", name]].dropna()
        if len(paired) < BOTTOM_UP_MIN_OBSERVATIONS:
            continue
        level_corr = paired["target"].corr(paired[name])
        changed = paired.diff().dropna()
        change_corr = changed["target"].corr(changed[name]) if len(changed) >= 8 else np.nan
        midpoint = len(paired) // 2
        first_corr = paired.iloc[:midpoint]["target"].corr(paired.iloc[:midpoint][name]) if midpoint >= 8 else np.nan
        second_corr = paired.iloc[midpoint:]["target"].corr(paired.iloc[midpoint:][name]) if len(paired) - midpoint >= 8 else np.nan
        stable_abs = 0.0
        if pd.notna(first_corr) and pd.notna(second_corr) and np.sign(first_corr) == np.sign(second_corr):
            stable_abs = min(abs(float(first_corr)), abs(float(second_corr)))
        score = (
            0.55 * abs(float(level_corr))
            + 0.25 * (abs(float(change_corr)) if pd.notna(change_corr) else 0.0)
            + 0.20 * stable_abs
        )
        ranked.append({
            "name": name,
            "family": config["family"],
            "score": score,
            "levelCorrelation": float(level_corr),
            "changeCorrelation": float(change_corr) if pd.notna(change_corr) else None,
            "stableAbsCorrelation": stable_abs,
            "observations": int(len(paired)),
        })
    selected, used_families = [], set()
    for item in sorted(ranked, key=lambda row: (-row["score"], row["name"])):
        if item["family"] in used_families:
            continue
        selected.append(item)
        used_families.add(item["family"])
        if len(selected) >= max_factors:
            break
    return selected


def bottom_up_walk_forward(
    target: pd.Series,
    signals: pd.DataFrame,
    forecast_index: pd.Index,
) -> tuple[pd.Series, pd.Series, dict[pd.Timestamp, list[dict[str, Any]]]]:
    """Nested walk-forward factor selection and ridge prediction."""
    calendar = pd.date_range(min(target.index.min(), signals.index.min()), max(target.index.max(), signals.index.max()), freq="ME")
    frame = signals.reindex(calendar)
    frame["target"] = target.reindex(calendar)
    frame["lag1"] = frame["target"].ffill().shift(1)
    anchors, pure_predictions, selections = {}, {}, {}
    for day in forecast_index:
        train = frame.loc[(frame.index < day) & (frame.index >= BRIDGE_TRAIN_START)].dropna(subset=["target"])
        chosen = rank_bottom_up_factors(train, frame.loc[day])
        columns = [item["name"] for item in chosen]
        if len(columns) < 2 or pd.isna(frame.loc[day, "lag1"]):
            continue
        required = min(2, len(columns))
        fit_train = train.loc[train[columns].notna().sum(axis=1) >= required].iloc[-BRIDGE_TRAIN_WINDOW:]
        if len(fit_train) < BOTTOM_UP_MIN_OBSERVATIONS:
            continue
        pure = ridge_fit_predict(fit_train, frame.loc[day], BOTTOM_UP_ALPHA, columns)
        pure_predictions[day] = pure
        anchors[day] = BOTTOM_UP_PURE_WEIGHT * pure + (1.0 - BOTTOM_UP_PURE_WEIGHT) * float(frame.loc[day, "lag1"])
        selections[day] = chosen
    return (
        pd.Series(anchors, dtype=float).sort_index(),
        pd.Series(pure_predictions, dtype=float).sort_index(),
        selections,
    )


def fixed_volume_walk_forward(
    industrial_mom_sa: pd.Series,
    monthly_changes: pd.DataFrame,
    forecast_index: pd.Index,
) -> tuple[pd.Series, pd.Series, dict[pd.Timestamp, list[dict[str, Any]]]]:
    """Forecast a fixed-volume index first, then convert its level to YoY.

    The fixed-volume index is recursively constructed from the official
    seasonally-adjusted MoM growth series.  No lagged industrial YoY value is a
    regressor or weighted forecast anchor in this branch.
    """
    level = (1.0 + industrial_mom_sa.sort_index() / 100.0).cumprod() * 100.0
    calendar = pd.date_range(
        min(industrial_mom_sa.index.min(), monthly_changes.index.min()),
        max(industrial_mom_sa.index.max(), monthly_changes.index.max()),
        freq="ME",
    )
    frame = monthly_changes.reindex(calendar)
    frame["target"] = industrial_mom_sa.reindex(calendar)
    predictions, predicted_mom, selections = {}, {}, {}
    for day in forecast_index:
        train = frame.loc[(frame.index < day) & (frame.index >= BRIDGE_TRAIN_START)].dropna(subset=["target"])
        chosen = rank_bottom_up_factors(train, frame.loc[day])
        columns = [item["name"] for item in chosen]
        if len(columns) < 2:
            continue
        fit_train = train.loc[train[columns].notna().sum(axis=1) >= 2].iloc[-BRIDGE_TRAIN_WINDOW:]
        if len(fit_train) < BOTTOM_UP_MIN_OBSERVATIONS:
            continue
        pure_mom = ridge_fit_predict(fit_train, frame.loc[day], FIXED_VOLUME_ALPHA, columns)
        recent_mom = float(fit_train["target"].iloc[-12:].mean())
        mom_hat = (
            FIXED_VOLUME_HIGH_FREQUENCY_WEIGHT * pure_mom
            + (1.0 - FIXED_VOLUME_HIGH_FREQUENCY_WEIGHT) * recent_mom
        )
        previous_month = day - pd.offsets.MonthEnd(1)
        previous_year = day - pd.offsets.MonthEnd(12)
        if previous_month not in level.index or previous_year not in level.index:
            continue
        level_hat = float(level.loc[previous_month]) * (1.0 + mom_hat / 100.0)
        predictions[day] = (level_hat / float(level.loc[previous_year]) - 1.0) * 100.0
        predicted_mom[day] = mom_hat
        selections[day] = chosen
    return (
        pd.Series(predictions, dtype=float).sort_index(),
        pd.Series(predicted_mom, dtype=float).sort_index(),
        selections,
    )


def ridge_fit_predict(
    train: pd.DataFrame,
    row: pd.Series,
    alpha: float = RIDGE_ALPHA,
    columns: list[str] | None = None,
) -> float:
    columns = columns or BRIDGE_FEATURES
    x = train[columns].apply(pd.to_numeric, errors="coerce").astype(float)
    y = train["target"].to_numpy(dtype=float)
    means = x.mean()
    stds = x.std().replace(0, np.nan)
    xz = ((x.fillna(means) - means) / stds).fillna(0.0)
    numeric_row = pd.to_numeric(row[columns], errors="coerce").astype(float)
    rz = ((numeric_row.fillna(means) - means) / stds).fillna(0.0)
    design = np.column_stack([np.ones(len(xz)), xz.to_numpy()])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    beta = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y
    return float(np.r_[1.0, rz.to_numpy()] @ beta)


def model_frame(target: pd.Series, features: pd.DataFrame) -> pd.DataFrame:
    calendar = pd.date_range(min(target.index.min(), features.index.min()), max(target.index.max(), features.index.max()), freq="ME")
    frame = features.reindex(calendar)
    frame["target"] = target.reindex(calendar)
    frame["lag1"] = frame["target"].ffill().shift(1)
    frame["lag12"] = frame["target"].shift(12)
    return frame


def valid_bridge_train(frame: pd.DataFrame, day: pd.Timestamp, columns: list[str]) -> pd.DataFrame:
    train = frame.loc[
        (frame.index < day) & (frame.index >= BRIDGE_TRAIN_START)
    ].dropna(subset=["target", "lag1"])
    minimum_available = max(2, len(columns) // 4)
    train = train.loc[train[columns].notna().sum(axis=1) >= minimum_available]
    return train.iloc[-BRIDGE_TRAIN_WINDOW:]


def walk_forward(
    frame: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    predictions, gf_fast, turning_point, calendar_adjusted = {}, {}, {}, {}
    persistences, ardl_auxiliary = {}, {}
    end = frame.dropna(subset=["diffusion", "pmi_production"], how="all").index.max()
    for day in pd.date_range(BACKTEST_START, end, freq="ME"):
        if day.month == 1:
            continue
        train = valid_bridge_train(frame, day, BRIDGE_FEATURES)
        if len(train) < 24 or pd.isna(frame.loc[day, "lag1"]):
            continue
        persistence = float(frame.loc[day, "lag1"])
        fast_bridge = ridge_fit_predict(train, frame.loc[day], 32.0, BRIDGE_FEATURES)
        turning_bridge = ridge_fit_predict(train, frame.loc[day], 64.0, BRIDGE_FEATURES)
        calendar_columns = BRIDGE_FEATURES + CALENDAR_FEATURES
        calendar_train = valid_bridge_train(frame, day, calendar_columns)
        calendar_bridge = ridge_fit_predict(calendar_train, frame.loc[day], 32.0, calendar_columns)
        gf_fast[day] = 0.40 * fast_bridge + 0.60 * persistence
        turning_point[day] = 0.50 * turning_bridge + 0.50 * persistence
        calendar_adjusted[day] = 0.40 * calendar_bridge + 0.60 * persistence
        predictions[day] = (
            ROBUST_ENSEMBLE_WEIGHTS["gfFast"] * gf_fast[day]
            + ROBUST_ENSEMBLE_WEIGHTS["turningPoint"] * turning_point[day]
            + ROBUST_ENSEMBLE_WEIGHTS["calendarAdjusted"] * calendar_adjusted[day]
        )
        ardl_train = frame.loc[
            (frame.index < day) & (frame.index >= ARDL_TRAIN_START)
        ].dropna(subset=["target", "lag1"]).iloc[-48:]
        ardl_bridge = ridge_fit_predict(ardl_train, frame.loc[day], ARDL_ALPHA, ARDL_FEATURES)
        ardl_auxiliary[day] = ARDL_BRIDGE_WEIGHT * ardl_bridge + (1.0 - ARDL_BRIDGE_WEIGHT) * persistence
        persistences[day] = persistence
    return (
        pd.Series(predictions, dtype=float).sort_index(),
        pd.Series(gf_fast, dtype=float).sort_index(),
        pd.Series(turning_point, dtype=float).sort_index(),
        pd.Series(calendar_adjusted, dtype=float).sort_index(),
        pd.Series(persistences, dtype=float).sort_index(),
        pd.Series(ardl_auxiliary, dtype=float).sort_index(),
    )


def metrics(prediction: pd.Series, actual: pd.Series) -> dict[str, Any]:
    joined = pd.concat([prediction.rename("prediction"), actual.rename("actual")], axis=1, sort=True).dropna()
    errors = joined["prediction"] - joined["actual"]
    prior = pd.Series({
        day: actual.loc[actual.index < day].iloc[-1] if (actual.index < day).any() else np.nan
        for day in joined.index
    }, dtype=float)
    direction = np.sign(joined["prediction"] - prior) == np.sign(joined["actual"] - prior)
    actual_change = actual.sort_index().diff().reindex(joined.index)
    prior_change = pd.Series({
        day: actual_change.loc[actual_change.index < day].dropna().iloc[-1]
        if not actual_change.loc[actual_change.index < day].dropna().empty else np.nan
        for day in joined.index
    }, dtype=float)
    turning = np.sign(actual_change) != np.sign(prior_change)
    turning_direction = direction[turning & actual_change.notna() & prior_change.notna()]
    actual_correlation = joined["prediction"].corr(joined["actual"])
    lag_correlation = joined["prediction"].corr(prior)
    return {
        "rmse": round(float(np.sqrt(np.mean(errors ** 2))), 6),
        "mae": round(float(np.mean(np.abs(errors))), 6),
        "bias": round(float(np.mean(errors)), 6),
        "directionHitPct": round(float(direction.dropna().mean() * 100), 2),
        "turningPointHitPct": round(float(turning_direction.mean() * 100), 2) if len(turning_direction) else None,
        "turningPoints": int(len(turning_direction)),
        "actualCorrelation": round(float(actual_correlation), 6) if pd.notna(actual_correlation) else None,
        "lagCorrelation": round(float(lag_correlation), 6) if pd.notna(lag_correlation) else None,
        "lagCorrelationGap": round(float(lag_correlation - actual_correlation), 6)
        if pd.notna(lag_correlation) and pd.notna(actual_correlation) else None,
        "observations": int(len(joined)),
        "sampleStart": joined.index.min().date().isoformat() if len(joined) else None,
        "sampleEnd": joined.index.max().date().isoformat() if len(joined) else None,
    }


def sharp_change_metrics(prediction: pd.Series, actual: pd.Series, threshold: float = 1.0) -> dict[str, Any]:
    joined = pd.concat([prediction.rename("prediction"), actual.rename("actual")], axis=1, sort=True).dropna()
    prior = actual.sort_index().shift(1).reindex(joined.index)
    actual_change = joined["actual"] - prior
    sharp = joined.loc[actual_change.abs() >= threshold]
    if sharp.empty:
        return {"thresholdPctPoint": threshold, "observations": 0}
    errors = sharp["prediction"] - sharp["actual"]
    direction = np.sign(sharp["prediction"] - prior.reindex(sharp.index)) == np.sign(actual_change.reindex(sharp.index))
    return {
        "thresholdPctPoint": threshold,
        "observations": int(len(sharp)),
        "rmse": round(float(np.sqrt(np.mean(errors ** 2))), 6),
        "mae": round(float(np.mean(np.abs(errors))), 6),
        "directionHitPct": round(float(direction.mean() * 100), 2),
        "months": [day.date().isoformat() for day in sharp.index],
    }


def volatility_metrics(prediction: pd.Series, actual: pd.Series, threshold: float = 1.0) -> dict[str, Any]:
    """Measure whether a model follows month-to-month movement and amplitude."""
    joined = pd.concat(
        [prediction.rename("prediction"), actual.rename("actual")],
        axis=1,
        sort=True,
    ).dropna()
    changes = joined.diff().dropna()
    sharp = changes.loc[changes["actual"].abs() >= threshold]
    level_ratio = joined["prediction"].std() / joined["actual"].std()
    change_ratio = changes["prediction"].std() / changes["actual"].std()
    change_correlation = changes["prediction"].corr(changes["actual"])
    change_direction = np.sign(changes["prediction"]) == np.sign(changes["actual"])
    amplitude = sharp["prediction"].abs() / sharp["actual"].abs()
    return {
        "levelStdRatio": round(float(level_ratio), 6) if pd.notna(level_ratio) else None,
        "changeStdRatio": round(float(change_ratio), 6) if pd.notna(change_ratio) else None,
        "changeCorrelation": round(float(change_correlation), 6) if pd.notna(change_correlation) else None,
        "changeDirectionHitPct": round(float(change_direction.mean() * 100.0), 2) if len(changes) else None,
        "sharpChangeThresholdPctPoint": threshold,
        "sharpChangeObservations": int(len(sharp)),
        "sharpMedianAmplitudeCapture": round(float(amplitude.median()), 6) if len(amplitude) else None,
    }


def project_simplex(values: np.ndarray) -> np.ndarray:
    """Project weights onto the non-negative unit simplex."""
    ordered = np.sort(values)[::-1]
    cumulative = np.cumsum(ordered)
    candidates = np.flatnonzero(ordered * np.arange(1, len(values) + 1) > cumulative - 1.0)
    if not len(candidates):
        return np.full(len(values), 1.0 / len(values))
    rho = int(candidates[-1])
    threshold = (cumulative[rho] - 1.0) / (rho + 1)
    return np.maximum(values - threshold, 0.0)


def fit_accounting_weights(train: pd.DataFrame) -> tuple[np.ndarray, float]:
    components = train[["mining", "manufacturing", "utility"]].to_numpy(dtype=float)
    target = train["target"].to_numpy(dtype=float)
    relative = components[:, :2] - components[:, [2]]
    unconstrained = np.linalg.lstsq(relative, target - components[:, 2], rcond=None)[0]
    weights = project_simplex(np.r_[unconstrained, 1.0 - unconstrained.sum()])
    residual = float(np.mean(target - components @ weights))
    return weights, residual


def accounting_reconstruction(
    target: pd.Series,
    production: dict[str, Any],
) -> tuple[pd.Series, dict[str, Any]]:
    required = {
        "mining": "sector_mining_yoy",
        "manufacturing": "sector_manufacturing_yoy",
        "utility": "sector_utility_yoy",
    }
    available = production.get("series", {})
    if any(key not in available for key in required.values()):
        return pd.Series(dtype=float), {"available": False}
    components = {
        name: series_from_rows(available[key]["observations"])
        for name, key in required.items()
    }
    frame = pd.concat([target.rename("target"), *[series.rename(name) for name, series in components.items()]], axis=1).dropna()
    reconstruction: dict[pd.Timestamp, float] = {}
    for day in frame.loc[frame.index >= BACKTEST_START].index:
        train = frame.loc[frame.index < day].iloc[-48:]
        if len(train) < 24:
            continue
        weights, residual = fit_accounting_weights(train)
        current = frame.loc[day, ["mining", "manufacturing", "utility"]].to_numpy(dtype=float)
        reconstruction[day] = float(current @ weights + residual)
    latest_train = frame.iloc[-48:]
    latest_weights, latest_residual = fit_accounting_weights(latest_train)
    latest_day = frame.index.max()
    latest_components = frame.loc[latest_day, ["mining", "manufacturing", "utility"]]
    latest_anchor = float(latest_components.to_numpy(dtype=float) @ latest_weights + latest_residual)
    details = {
        "available": True,
        "purpose": "post-release accounting reconstruction and real-time coherence check; contemporaneous sector actuals never enter forecasts",
        "weights": {
            "mining": round(float(latest_weights[0]), 6),
            "manufacturing": round(float(latest_weights[1]), 6),
            "utility": round(float(latest_weights[2]), 6),
        },
        "residual": round(latest_residual, 6),
        "latestObservedMonth": latest_day.date().isoformat(),
        "latestObservedComponents": {
            key: round(float(value), 6) for key, value in latest_components.items()
        },
        "latestReconstructedAnchor": round(latest_anchor, 6),
        "backtest": metrics(pd.Series(reconstruction, dtype=float), target),
        "providerIds": {name: available[key].get("providerId") for name, key in required.items()},
    }
    return pd.Series(reconstruction, dtype=float).sort_index(), details


def physical_output_snapshot(production: dict[str, Any]) -> dict[str, Any]:
    keys = [key for key in production.get("series", {}) if key.startswith("output_")]
    snapshot = {}
    for key in sorted(keys):
        item = production["series"][key]
        values = series_from_rows(item.get("observations", []))
        if values.empty:
            continue
        day = values.index.max()
        snapshot[key] = {
            "date": day.date().isoformat(),
            "value": round(float(values.loc[day]), 6),
            "providerId": item.get("providerId"),
        }
    return snapshot


def build_legacy(source_path: Path, model_inputs_path: Path, dashboard_path: Path, production_path: Path) -> dict[str, Any]:
    source, model_inputs, dashboard = map(read_json, (source_path, model_inputs_path, dashboard_path))
    production = read_json(production_path) if production_path.exists() else {}
    target = monthly_target(source)
    consensus = series_from_rows(source["series"]["consensus"]["observations"])
    raw, provenance = build_raw_features(model_inputs, dashboard, production)
    features = build_monthly_features(raw, model_inputs)
    frame = model_frame(target, features)
    core_prediction, gf_fast, turning_point, calendar_adjusted, persistence, ardl_auxiliary = walk_forward(frame)
    bottom_up_signals = build_bottom_up_signals(raw, dashboard)
    bottom_up_anchor, bottom_up_pure, factor_selections = bottom_up_walk_forward(
        target, bottom_up_signals, core_prediction.index
    )
    industrial_mom_sa = series_from_rows(source["series"]["actualMomSa"]["observations"])
    fixed_volume_prediction, predicted_mom_sa, fixed_volume_selections = fixed_volume_walk_forward(
        industrial_mom_sa,
        build_bottom_up_monthly_changes(raw, dashboard),
        core_prediction.index,
    )
    high_frequency_response = (
        core_prediction - LEGACY_CORE_PERSISTENCE_WEIGHT * persistence
    ) / (1.0 - LEGACY_CORE_PERSISTENCE_WEIGHT)
    responsive_core = (
        RESPONSIVE_CORE_PERSISTENCE_WEIGHT * persistence
        + (1.0 - RESPONSIVE_CORE_PERSISTENCE_WEIGHT) * high_frequency_response
    )
    common_prediction_index = responsive_core.index.intersection(bottom_up_anchor.index)
    prediction = (
        (1.0 - BOTTOM_UP_ENSEMBLE_WEIGHT) * responsive_core.reindex(common_prediction_index)
        + BOTTOM_UP_ENSEMBLE_WEIGHT * bottom_up_anchor.reindex(common_prediction_index)
    )
    _, accounting = accounting_reconstruction(target, production)

    comparable = pd.concat([prediction.rename("model"), consensus.rename("consensus"), target.rename("actual")], axis=1, sort=True).dropna()
    comparison = {
        "model": metrics(comparable["model"], comparable["actual"]),
        "consensus": metrics(comparable["consensus"], comparable["actual"]),
        "modelWinRatePct": round(float((abs(comparable["model"] - comparable["actual"]) < abs(comparable["consensus"] - comparable["actual"])).mean() * 100), 2),
        "ties": int((abs(comparable["model"] - comparable["actual"]) == abs(comparable["consensus"] - comparable["actual"])).sum()),
    }
    rows = []
    for day in prediction.index:
        rows.append({
            "date": day.date().isoformat(),
            "model": round(float(prediction.loc[day]), 6),
            "coreModel": round(float(core_prediction.loc[day]), 6),
            "responsiveCore": round(float(responsive_core.loc[day]), 6),
            "highFrequencyResponse": round(float(high_frequency_response.loc[day]), 6),
            "bottomUpFactor": round(float(bottom_up_anchor.loc[day]), 6),
            "bottomUpPure": round(float(bottom_up_pure.loc[day]), 6),
            "fixedVolumeModel": round(float(fixed_volume_prediction.loc[day]), 6) if day in fixed_volume_prediction else None,
            "predictedMomSa": round(float(predicted_mom_sa.loc[day]), 6) if day in predicted_mom_sa else None,
            "gfFast": round(float(gf_fast.loc[day]), 6),
            "turningPoint": round(float(turning_point.loc[day]), 6),
            "calendarAdjusted": round(float(calendar_adjusted.loc[day]), 6),
            "persistence": round(float(persistence.loc[day]), 6),
            "ardlAuxiliary": round(float(ardl_auxiliary.loc[day]), 6),
            "consensus": round(float(consensus.loc[day]), 6) if day in consensus.index else None,
            "actual": round(float(target.loc[day]), 6) if day in target.index else None,
            "kind": "walk_forward" if day in target.index else "live_nowcast",
        })
    latest = rows[-1]
    latest_day = prediction.index.max()
    latest_selection = factor_selections.get(latest_day, [])
    selection_frequency: dict[str, int] = {}
    for selected in factor_selections.values():
        for item in selected:
            selection_frequency[item["name"]] = selection_frequency.get(item["name"], 0) + 1
    diagnostic_train = pd.concat([target.rename("target"), bottom_up_signals], axis=1, sort=True).dropna(subset=["target"])
    diagnostic_ranking = rank_bottom_up_factors(diagnostic_train, max_factors=len(BOTTOM_UP_CANDIDATES))
    return {
        "schemaVersion": 6,
        "target": "规模以上工业增加值同比；2月使用1-2月累计同比，1月不单列",
        "method": "responsive high-frequency bridge with reduced prior-YoY regularization, nested bottom-up factor selection, and an independent fixed-volume-index diagnostic built from official seasonally-adjusted MoM growth",
        "consensusPolicy": "M005682255仅在模型完成后合并评估，未进入任何特征或训练矩阵",
        "asOf": max((item["end"] for item in provenance.values() if item["end"]), default=None),
        "latest": latest,
        "latestSignals": {
            key: round(float(value), 6) if pd.notna(value) else None
            for key, value in frame.loc[prediction.index.max(), BRIDGE_FEATURES + ["diffusion_ii"]].items()
        },
        "latestBottomUpFactors": [
            {
                **{
                    key: (round(value, 6) if isinstance(value, float) else value)
                    for key, value in item.items()
                },
                "latestSignal": round(float(bottom_up_signals.loc[latest_day, item["name"]]), 6),
            }
            for item in latest_selection
        ],
        "latestFixedVolumeDiagnostic": {
            "prediction": round(float(fixed_volume_prediction.loc[latest_day]), 6)
            if latest_day in fixed_volume_prediction else None,
            "predictedMomSa": round(float(predicted_mom_sa.loc[latest_day]), 6)
            if latest_day in predicted_mom_sa else None,
            "selectedFactors": [item["name"] for item in fixed_volume_selections.get(latest_day, [])],
            "productionWeight": 0.0,
        },
        "modelSpecification": {
            "bridgeTrainStart": BRIDGE_TRAIN_START.date().isoformat(),
            "bridgeTrainWindow": BRIDGE_TRAIN_WINDOW,
            "minimumFeatureCoverageRule": "at least max(2, one quarter of requested features) observed",
            "robustEnsembleWeights": ROBUST_ENSEMBLE_WEIGHTS,
            "gfFast": {"ridgeAlpha": 32.0, "bridgeWeight": 0.40, "persistenceWeight": 0.60},
            "turningPoint": {"ridgeAlpha": 64.0, "bridgeWeight": 0.50, "persistenceWeight": 0.50},
            "calendarAdjusted": {"ridgeAlpha": 32.0, "bridgeWeight": 0.40, "persistenceWeight": 0.60},
            "standardizationWindowMonths": STANDARDIZATION_WINDOW,
            "bridgeFeatures": BRIDGE_FEATURES,
            "calendarFeatures": CALENDAR_FEATURES,
            "ardlAuxiliaryFeatures": ARDL_FEATURES,
            "ardlAuxiliaryAlpha": ARDL_ALPHA,
            "ardlAuxiliaryBridgeWeight": ARDL_BRIDGE_WEIGHT,
            "responsiveCore": {
                "highFrequencyResponseWeight": 1.0 - RESPONSIVE_CORE_PERSISTENCE_WEIGHT,
                "priorYoYRegularizationWeight": RESPONSIVE_CORE_PERSISTENCE_WEIGHT,
                "finalWeight": 1.0 - BOTTOM_UP_ENSEMBLE_WEIGHT,
                "effectivePriorYoYWeight": (1.0 - BOTTOM_UP_ENSEMBLE_WEIGHT) * RESPONSIVE_CORE_PERSISTENCE_WEIGHT,
                "previousEffectivePriorYoYWeight": (1.0 - 0.20) * LEGACY_CORE_PERSISTENCE_WEIGHT,
            },
            "bottomUp": {
                "candidateCount": len(BOTTOM_UP_CANDIDATES),
                "minimumPriorObservations": BOTTOM_UP_MIN_OBSERVATIONS,
                "maximumFactors": BOTTOM_UP_MAX_FACTORS,
                "familyDiversityRule": "at most one selected factor per family",
                "rankingScore": "55% absolute level correlation + 25% absolute change correlation + 20% stable half-sample absolute correlation",
                "selectionTiming": "nested walk-forward; target observations and correlations are restricted to months before each forecast month",
                "ridgeAlpha": BOTTOM_UP_ALPHA,
                "factorAnchorWeights": {"pureFactorModel": BOTTOM_UP_PURE_WEIGHT, "priorActual": 1.0 - BOTTOM_UP_PURE_WEIGHT},
                "finalEnsembleWeights": {"responsiveCore": 1.0 - BOTTOM_UP_ENSEMBLE_WEIGHT, "bottomUpFactor": BOTTOM_UP_ENSEMBLE_WEIGHT},
                "candidateFamilies": sorted({config["family"] for config in BOTTOM_UP_CANDIDATES.values()}),
            },
            "fixedVolumeDiagnostic": {
                "officialMomProviderId": source["series"]["actualMomSa"].get("providerId"),
                "indexConstruction": "index[t] = index[t-1] * (1 + official seasonally-adjusted MoM[t] / 100)",
                "forecastConstruction": "forecast index[t] from predicted MoM, then convert index[t] / index[t-12] - 1 to YoY",
                "ridgeAlpha": FIXED_VOLUME_ALPHA,
                "predictedMomWeights": {
                    "highFrequencyModel": FIXED_VOLUME_HIGH_FREQUENCY_WEIGHT,
                    "recentMomMean": 1.0 - FIXED_VOLUME_HIGH_FREQUENCY_WEIGHT,
                },
                "laggedIndustrialYoYIncluded": False,
                "productionWeight": 0.0,
                "reasonNotInProduction": "official seasonally-adjusted MoM and published unadjusted YoY are not an exact accounting identity; standalone walk-forward accuracy is weaker",
            },
            "consensusIncluded": False,
            "reportReference": "广发宏观：工业增加值如何预测？（2023-08-30）",
        },
        "ardlAuxiliaryBacktest": metrics(ardl_auxiliary, target),
        "backtest": metrics(prediction, target),
        "coreModelBacktest": metrics(core_prediction, target),
        "responsiveCoreBacktest": metrics(responsive_core, target),
        "fixedVolumeDiagnosticBacktestExFebruary": metrics(
            fixed_volume_prediction.loc[fixed_volume_prediction.index.month != 2],
            target.loc[target.index.month != 2],
        ),
        "sharpChangeBacktest": {
            "enhancedModel": sharp_change_metrics(prediction, target),
            "coreModel": sharp_change_metrics(core_prediction, target),
        },
        "comparisonOnCommonSample": comparison,
        "accountingReconstruction": accounting,
        "latestPhysicalOutputs": physical_output_snapshot(production),
        "history": rows,
        "bottomUpResearch": {
            "note": "full available sample ranking is descriptive only; production selection is recomputed using prior months inside each walk-forward forecast",
            "selectionFrequency": dict(sorted(selection_frequency.items(), key=lambda item: (-item[1], item[0]))),
            "descriptiveFamilyLeaders": [
                {
                    key: (round(value, 6) if isinstance(value, float) else value)
                    for key, value in item.items()
                }
                for item in diagnostic_ranking
            ],
        },
        "featureProvenance": provenance,
        "providerIds": {key: value["providerId"] for key, value in source["series"].items()},
    }


def build(source_path: Path, model_inputs_path: Path, dashboard_path: Path, production_path: Path) -> dict[str, Any]:
    """Build the production nowcast from fixed-volume carry and fixed factors."""
    source, model_inputs, dashboard = map(read_json, (source_path, model_inputs_path, dashboard_path))
    production = read_json(production_path) if production_path.exists() else {}
    target = monthly_target(source)
    consensus = series_from_rows(source["series"]["consensus"]["observations"])
    raw, provenance = build_raw_features(model_inputs, dashboard, production)
    signals = build_bottom_up_signals(raw, dashboard)
    industrial_mom_sa = series_from_rows(source["series"]["actualMomSa"]["observations"])
    base_prediction, carry = statistical_bridge_walk_forward(target, signals, industrial_mom_sa)
    report_features = build_report_family_features(raw, model_inputs, dashboard)
    family_prediction, report_pure, report_weights = report_residual_walk_forward(
        target,
        carry,
        report_features,
        base_prediction,
    )
    individual_features = build_individual_report_features(raw, model_inputs, dashboard)
    individual_prediction = individual_residual_walk_forward(
        target,
        carry,
        individual_features,
        family_prediction.index,
    )
    uncalibrated_prediction, individual_weights = challenger_online_blend(
        family_prediction,
        individual_prediction,
        target,
    )
    prediction, calibration_correction = historical_error_calibration(
        uncalibrated_prediction,
        target,
    )
    _, accounting = accounting_reconstruction(target, production)

    comparable = pd.concat(
        [prediction.rename("model"), consensus.rename("consensus"), target.rename("actual")],
        axis=1,
        sort=True,
    ).dropna()
    comparison = {
        "model": metrics(comparable["model"], comparable["actual"]),
        "consensus": metrics(comparable["consensus"], comparable["actual"]),
        "modelWinRatePct": round(float((abs(comparable["model"] - comparable["actual"]) < abs(comparable["consensus"] - comparable["actual"])).mean() * 100), 2),
        "ties": int((abs(comparable["model"] - comparable["actual"]) == abs(comparable["consensus"] - comparable["actual"])).sum()),
    }
    rows = []
    for day in prediction.index:
        rows.append({
            "date": day.date().isoformat(),
            "model": round(float(prediction.loc[day]), 6),
            "selectedFactors": list(FIXED_FACTOR_NAMES)
            if day.month == 2 else [
                STATISTICAL_CARRY_NAME,
                *PRODUCTION_FACTOR_NAMES,
            ],
            "availableFactors": [name for name in FIXED_FACTOR_NAMES if pd.notna(signals.loc[day, name])]
            + ([STATISTICAL_CARRY_NAME] if day in carry.index and pd.notna(carry.loc[day]) else []),
            "availableReportFeatureChannels": [
                name for name in REPORT_HYBRID_FEATURES
                if day in report_features.index and pd.notna(report_features.loc[day, name])
            ],
            "availableIndividualReportFactors": [
                name for name in individual_features.columns
                if day in individual_features.index and pd.notna(individual_features.loc[day, name])
            ],
            "knownFixedVolumeCarry": round(float(carry.loc[day]), 6)
            if day in carry.index and pd.notna(carry.loc[day]) else None,
            "baseModel": round(float(base_prediction.loc[day]), 6)
            if day in base_prediction.index else None,
            "uncalibratedModel": round(float(uncalibrated_prediction.loc[day]), 6)
            if day in uncalibrated_prediction.index else None,
            "historicalErrorCorrection": round(float(calibration_correction.loc[day]), 6)
            if day in calibration_correction.index else None,
            "reportResidualModel": round(float(report_pure.loc[day]), 6)
            if day in report_pure.index else None,
            "reportOnlineWeight": round(float(report_weights.loc[day]), 6)
            if day in report_weights.index else None,
            "individualResidualModel": round(float(individual_prediction.loc[day]), 6)
            if day in individual_prediction.index else None,
            "individualOnlineWeight": round(float(individual_weights.loc[day]), 6)
            if day in individual_weights.index else None,
            "consensus": round(float(consensus.loc[day]), 6) if day in consensus.index else None,
            "actual": round(float(target.loc[day]), 6) if day in target.index else None,
            "kind": "walk_forward" if day in target.index else "live_nowcast",
        })
    if not rows:
        raise RuntimeError("No correlation-model forecast could be produced from the available high-frequency data")
    latest = rows[-1]
    latest_day = prediction.index.max()
    diagnostic_train = pd.concat([target.rename("target"), signals], axis=1, sort=True).dropna(subset=["target"])
    descriptive_ranking = rank_correlated_factors(
        diagnostic_train,
        max_factors=len(BOTTOM_UP_CANDIDATES),
        enforce_family_diversity=False,
    )
    ranking_by_name = {item["name"]: item for item in descriptive_ranking}
    latest_factors = []
    for name in FIXED_FACTOR_NAMES:
        item = ranking_by_name.get(name, {
            "name": name,
            "family": BOTTOM_UP_CANDIDATES[name]["family"],
            "score": None,
            "fullCorrelation": None,
            "recentCorrelation": None,
            "stableAbsCorrelation": None,
            "observations": int(diagnostic_train[["target", name]].dropna().shape[0]),
        })
        latest_factors.append({
            **{
                key: round(value, 6) if isinstance(value, float) else value
                for key, value in item.items()
            },
            "latestSignal": round(float(signals.loc[latest_day, name]), 6)
            if pd.notna(signals.loc[latest_day, name]) else None,
        })
    return {
        "schemaVersion": 12,
        "target": "规模以上工业增加值同比；2月使用1-2月累计同比，1月不单列",
        "method": "strict walk-forward fixed-volume carry plus fixed 19-series family and individual residual bridges, two prior-error-only online weights and historical calibration",
        "consensusPolicy": "一致预期仅在模型预测完成后合并用于对比，不参与因子、筛选、拟合或参数选择",
        "asOf": max((item["end"] for item in provenance.values() if item["end"]), default=None),
        "latest": latest,
        "latestFixedFactors": latest_factors,
        "modelSpecification": {
            "candidateCount": len(BOTTOM_UP_CANDIDATES),
            "fixedFactors": list(FIXED_FACTOR_NAMES),
            "reportProxyFactors": list(REPORT_PROXY_FACTOR_NAMES),
            "reportFamilies": list(REPORT_FAMILIES),
            "reportHybridFeatures": list(REPORT_HYBRID_FEATURES),
            "individualReportFeatures": list(individual_features.columns),
            "statisticalCarryFactor": STATISTICAL_CARRY_NAME,
            "fixedFactorFamilies": [BOTTOM_UP_CANDIDATES[name]["family"] for name in FIXED_FACTOR_NAMES],
            "signalConversion": {
                "volume": "monthly mean year-on-year percent change",
                "rate": "monthly mean year-on-year percentage-point change",
                "alreadyYoY": "retain the published year-on-year rate",
            },
            "factorSelection": "fixed before walk-forward evaluation from economic coverage: power, ferrous, chemical, auto and demand",
            "monthlyFactorReplacement": False,
            "targetDecomposition": "for non-February month t, I[t-1] / I[t-12] - 1 is the already-known fixed-volume carry; current high-frequency factors estimate the remaining current-month production contribution",
            "knownCarryConstruction": "cumulate official seasonally-adjusted industrial MoM into a fixed-volume index, then calculate I[t-1] / I[t-12] - 1; no current-month MoM is used",
            "februaryTreatment": "the target and all fixed high-frequency signals are calculated over January-February together; the fixed-volume carry is excluded because January MoM is not independently available before the combined release",
            "officialMomProviderId": source["series"]["actualMomSa"].get("providerId"),
            "coefficientTiming": "coefficients for month t use industrial-value targets strictly before t",
            "minimumPriorObservations": CORRELATION_MIN_OBSERVATIONS,
            "minimumAvailableFactors": FIXED_FACTOR_MINIMUM_AVAILABLE,
            "fitWindowMonths": FIXED_FACTOR_FIT_WINDOW,
            "ridgeAlpha": FIXED_FACTOR_RIDGE_ALPHA,
            "reportResidualTrainWindowMonths": REPORT_HYBRID_TRAIN_WINDOW,
            "reportResidualRidgeAlpha": REPORT_HYBRID_RIDGE_ALPHA,
            "reportOnlineWeight": "estimated for month t from prior strict walk-forward forecast errors only and constrained to [0,1]",
            "individualResidualTrainWindowMonths": INDIVIDUAL_REPORT_TRAIN_WINDOW,
            "individualResidualRidgeAlpha": INDIVIDUAL_REPORT_RIDGE_ALPHA,
            "individualInitialWeight": INDIVIDUAL_REPORT_INITIAL_WEIGHT,
            "individualOnlineWeight": "the fixed individual-factor challenger is activated only after 24 prior training observations; its month-t weight uses prior OOS errors only and is constrained to [0,1]",
            "historicalErrorCalibration": "75% expanding mean prior OOS error plus 25% most recent same-calendar-month OOS error; no previous-month target or error is used",
            "calibrationOverallWeight": CALIBRATION_OVERALL_WEIGHT,
            "calibrationSameMonthWeight": CALIBRATION_SAME_MONTH_WEIGHT,
            "calibrationMinimumPriorErrors": CALIBRATION_MIN_ERRORS,
            "laggedIndustrialValueIncluded": False,
            "persistenceAnchorWeight": 0.0,
            "consensusIncluded": False,
        },
        "backtest": metrics(prediction, target),
        "preCalibrationBacktest": metrics(uncalibrated_prediction, target),
        "baseModelBacktest": metrics(base_prediction, target),
        "sharpChangeBacktest": sharp_change_metrics(prediction, target),
        "volatilityBacktest": volatility_metrics(prediction, target),
        "preCalibrationVolatilityBacktest": volatility_metrics(uncalibrated_prediction, target),
        "baseModelVolatilityBacktest": volatility_metrics(base_prediction, target),
        "comparisonOnCommonSample": comparison,
        "history": rows,
        "fixedFactorResearch": {
            "note": "the production factor names never change across months; correlations below are descriptive diagnostics only",
            "economicCoverage": {
                "power_coal": "electricity and industrial load proxy",
                "blast_furnace": "ferrous production operating rate",
                "methanol_rate": "chemical production operating rate",
                "full_tire_rate": "auto supply-chain production operating rate",
                "asphalt_rate": "infrastructure and construction demand operating rate",
            },
            "descriptiveRanking": [
                {
                    key: round(value, 6) if isinstance(value, float) else value
                    for key, value in item.items()
                }
                for item in descriptive_ranking
            ],
        },
        "accountingReconstruction": accounting,
        "latestPhysicalOutputs": physical_output_snapshot(production),
        "featureProvenance": provenance,
        "providerIds": {key: value["providerId"] for key, value in source["series"].items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--model-inputs", type=Path, default=DEFAULT_MODEL_INPUTS)
    parser.add_argument("--dashboard", type=Path, default=DEFAULT_DASHBOARD)
    parser.add_argument("--production-inputs", type=Path, default=DEFAULT_PRODUCTION_INPUTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build(args.source, args.model_inputs, args.dashboard, args.production_inputs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"latest": payload["latest"], "backtest": payload["backtest"], "comparison": payload["comparisonOnCommonSample"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
