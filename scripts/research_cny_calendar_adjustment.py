#!/usr/bin/env python3
"""Research a release-safe Chinese New Year calendar adjustment for exports."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RACE_PATH = ROOT / "scripts" / "research_trade_model_race.py"
OUT_DIR = ROOT / "outputs" / "trade-model-research"

# Publicly known lunar-new-year dates. The feature is deterministic and known
# before every forecast month; no realized trade observation enters it.
CNY = {
    2020: "2020-01-25", 2021: "2021-02-12", 2022: "2022-02-01",
    2023: "2023-01-22", 2024: "2024-02-10", 2025: "2025-01-29",
    2026: "2026-02-17", 2027: "2027-02-06",
}


def load_race():
    spec = importlib.util.spec_from_file_location("trade_model_race_cny", RACE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def weekday_count(start: pd.Timestamp, end: pd.Timestamp, month: pd.Timestamp) -> int:
    days = pd.date_range(start, end, freq="D")
    return int(((days.weekday < 5) & (days.to_period("M") == month.to_period("M"))).sum())


def calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    raw = []
    for day in index:
        year = day.year
        current, previous = pd.Timestamp(CNY[year]), pd.Timestamp(CNY[year - 1])
        def counts(cny: pd.Timestamp, reference: pd.Timestamp) -> tuple[int, int, int]:
            return (
                weekday_count(cny - pd.Timedelta(days=14), cny - pd.Timedelta(days=1), reference),
                weekday_count(cny, cny + pd.Timedelta(days=13), reference),
                weekday_count(cny + pd.Timedelta(days=14), cny + pd.Timedelta(days=27), reference),
            )
        now = counts(current, day)
        prior_reference = day - pd.DateOffset(years=1)
        old = counts(previous, prior_reference)
        raw.append({
            "date": day,
            "jan": float(day.month == 1),
            "feb": float(day.month == 2),
            "mar": float(day.month == 3),
            "cny_rush_weekdays_yoy": float(now[0] - old[0]),
            "cny_shutdown_weekdays_yoy": float(now[1] - old[1]),
            "cny_recovery_weekdays_yoy": float(now[2] - old[2]),
            "cny_doy_shift_jan": float((current.dayofyear - previous.dayofyear) / 10) * (day.month == 1),
            "cny_doy_shift_feb": float((current.dayofyear - previous.dayofyear) / 10) * (day.month == 2),
            "cny_doy_shift_mar": float((current.dayofyear - previous.dayofyear) / 10) * (day.month == 3),
        })
    return pd.DataFrame(raw).set_index("date")


def predict(race, target, partner, calendar, day, columns, alpha):
    prior = target.loc[target.index < day].dropna()
    correlations = {}
    for column in partner:
        joined = pd.concat([prior.rename("y"), partner[column].rename("x")], axis=1, sort=False).dropna()
        if len(joined) >= 24 and joined["x"].std() > 1e-12:
            value = joined["y"].corr(joined["x"])
            if pd.notna(value):
                correlations[column] = float(value)
    available = {}
    for family, preferred_lag in race.PARTNER_PREFERRED_LAGS.items():
        for lag in range(preferred_lag, preferred_lag + 3):
            column = f"{family}_lag{lag}"
            if column in partner and pd.notna(partner.loc[day, column]):
                available[family] = column
                break
    selected = sorted(
        available.values(), key=lambda name: abs(correlations.get(name, 0.0)), reverse=True
    )[:3]
    x_all = pd.concat([partner[selected], calendar[columns]], axis=1, sort=False)
    training = pd.concat([prior.rename("y"), x_all], axis=1, sort=False).dropna()
    if len(training) < 24:
        return None
    x = training.drop(columns="y")
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = race.ridge(
        np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha
    )
    now = (x_all.loc[day] - means) / stds
    return float(np.r_[1.0, now.to_numpy()] @ beta)


def metric(frame, column, mask):
    sample = frame.loc[mask, ["actual", column]].dropna()
    error = sample[column] - sample["actual"]
    return {
        "n": int(len(sample)),
        "rmse": round(float(np.sqrt(np.mean(error**2))), 4),
        "mae": round(float(np.mean(np.abs(error))), 4),
        "bias": round(float(np.mean(error)), 4),
    }


def main() -> int:
    race = load_race()
    base = race.load_base()
    dashboard = json.loads(race.DASHBOARD_PATH.read_text(encoding="utf-8-sig"))
    target = base.read_targets(race.TARGET_PATH)["exports"]
    end = base.build_features(dashboard, "exports").dropna(how="all").index.max()
    partner = race.read_partner_import_factors(end)
    index = pd.date_range(target.index.min(), end, freq="ME")
    calendar = calendar_features(index)
    specs = {
        "month_dummies": ["jan", "feb", "mar"],
        "cny_windows": [
            "cny_rush_weekdays_yoy", "cny_shutdown_weekdays_yoy",
            "cny_recovery_weekdays_yoy",
        ],
        "cny_timing_interactions": [
            "cny_doy_shift_jan", "cny_doy_shift_feb", "cny_doy_shift_mar",
        ],
        "cny_windows_plus_month": [
            "jan", "feb", "mar", "cny_rush_weekdays_yoy",
            "cny_shutdown_weekdays_yoy", "cny_recovery_weekdays_yoy",
        ],
    }
    rows = []
    development_start = target.index.min() + pd.offsets.MonthEnd(24)
    for day in pd.date_range(development_start, target.dropna().index.max(), freq="ME"):
        if day not in target.index or pd.isna(target.loc[day]):
            continue
        baseline, _, _, _ = race.destination_import_prediction(target, day, end)
        row = {"date": day, "actual": float(target.loc[day]), "baseline": baseline}
        for spec, columns in specs.items():
            for alpha in (5.0, 10.0, 30.0, 100.0):
                row[f"{spec}_a{int(alpha)}"] = predict(
                    race, target, partner, calendar, day, columns, alpha
                )
        rows.append(row)
    frame = pd.DataFrame(rows).set_index("date")
    evaluation = frame.index >= race.START
    development = frame.index < race.START
    q1 = frame.index.month <= 3
    result = {}
    for column in ["baseline"] + [c for c in frame if c not in ("actual", "baseline")]:
        result[column] = {
            "development": metric(frame, column, development),
            "development_jan_mar": metric(frame, column, development & q1),
            "all": metric(frame, column, evaluation),
            "jan_mar": metric(frame, column, evaluation & q1),
            "other_months": metric(frame, column, evaluation & ~q1),
        }
    ranked_development = sorted(result, key=lambda name: result[name]["development"]["rmse"])
    ranked = sorted(result, key=lambda name: result[name]["all"]["rmse"])
    payload = {
        "status": "RESEARCH_NOT_FOR_PUBLICATION",
        "method": "expanding-window destination-import ridge with deterministic CNY calendar factors",
        "results": result,
        "ranked_by_all_rmse": ranked,
        "ranked_by_pre_backtest_rmse": ranked_development,
        "preselected_model": ranked_development[0],
        "preselected_model_evaluation": result[ranked_development[0]],
        "ex_post_best": ranked[0],
        "cny_dates": CNY,
        "note": "Calendar dates are known ex ante; consensus is not used.",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT_DIR / "cny-calendar-adjustment-timeseries.csv", encoding="utf-8-sig")
    (OUT_DIR / "cny-calendar-adjustment.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "preselected": ranked_development[:6],
        "ex_post_best": ranked[:6],
        "preselected_metrics": {k: result[k] for k in ranked_development[:3]},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
