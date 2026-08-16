#!/usr/bin/env python3
"""Test a CNY-gated import model while preserving the original import model."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RACE_PATH = ROOT / "scripts" / "research_trade_model_race.py"
OUT_DIR = ROOT / "outputs" / "trade-model-research"


def load_race():
    spec = importlib.util.spec_from_file_location("trade_model_race_import_cny", RACE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def augmented_change_prediction(race, target, base_features, calendar, day, alpha, cap):
    """Previous actual plus original import factor and three deterministic CNY windows."""
    prior = target.loc[target.index < day].dropna()
    anchor = float(prior.iloc[-1])
    target_change = target.diff().loc[target.index < day].dropna()
    correlations = {}
    for column in base_features:
        joined = pd.concat(
            [target_change.rename("y"), base_features[column].rename("x")], axis=1, sort=False
        ).dropna()
        if len(joined) >= 24 and joined["x"].std() > 1e-12:
            value = joined["y"].corr(joined["x"])
            if pd.notna(value):
                correlations[column] = float(value)
    original = [
        name for name, value in sorted(correlations.items(), key=lambda item: abs(item[1]), reverse=True)
        if abs(value) >= 0.25 and day in base_features.index and pd.notna(base_features.loc[day, name])
    ][:1]
    cny_columns = [
        "cny_rush_weekdays_yoy", "cny_shutdown_weekdays_yoy", "cny_recovery_weekdays_yoy",
    ]
    features = pd.concat([base_features[original], calendar[cny_columns]], axis=1, sort=False)
    training = pd.concat([target_change.rename("y"), features], axis=1, sort=False)
    training = training.loc[training.index < day].dropna()
    if len(training) < 24:
        return None, [], 0.0
    x = training.drop(columns="y")
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = race.ridge(
        np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), alpha
    )
    now = (features.loc[day] - means) / stds
    change = float(np.clip(np.r_[1.0, now.to_numpy()] @ beta, -cap, cap))
    return anchor + change, original + cny_columns, change


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
    target = base.read_targets(race.TARGET_PATH)["imports"]
    end = base.build_features(dashboard, "imports").dropna(how="all").index.max()
    base_features = race.anchor_feature_pool("imports", end)
    calendar = race.cny_calendar_features(pd.date_range(target.index.min(), end, freq="ME"))
    variants = [(alpha, cap) for alpha in (1.0, 5.0, 10.0, 30.0, 100.0) for cap in (15.0, 30.0)]
    rows = []
    development_start = target.index.min() + pd.offsets.MonthEnd(24)
    for day in pd.date_range(development_start, target.dropna().index.max(), freq="ME"):
        if day not in target.index or pd.isna(target.loc[day]):
            continue
        baseline, _, _, _, _ = race.anchored_factor_prediction(
            target, base_features, day, "imports"
        )
        row = {"date": day, "actual": float(target.loc[day]), "original_import_model": baseline}
        for alpha, cap in variants:
            prediction, _, _ = augmented_change_prediction(
                race, target, base_features, calendar, day, alpha, cap
            )
            name = f"import_cny_a{int(alpha)}_cap{int(cap)}"
            row[name] = prediction if day.month in (1, 2, 3) else baseline
        rows.append(row)
    frame = pd.DataFrame(rows).set_index("date")
    development = frame.index < race.START
    evaluation = frame.index >= race.START
    q1 = frame.index.month <= 3
    results = {}
    for column in frame.columns.drop("actual"):
        results[column] = {
            "development": metric(frame, column, development),
            "development_jan_mar": metric(frame, column, development & q1),
            "all": metric(frame, column, evaluation),
            "jan_mar": metric(frame, column, evaluation & q1),
            "other_months": metric(frame, column, evaluation & ~q1),
        }
    candidates = [name for name in results if name != "original_import_model"]
    ranked_development = sorted(candidates, key=lambda name: results[name]["development"]["rmse"])
    ranked_evaluation = sorted(candidates, key=lambda name: results[name]["all"]["rmse"])
    payload = {
        "status": "RESEARCH_NOT_FOR_PUBLICATION",
        "original_model_preserved": True,
        "method": "Q1-only deterministic CNY augmentation of previous-actual import anchor",
        "results": results,
        "ranked_by_pre_backtest_rmse": ranked_development,
        "ranked_by_evaluation_rmse": ranked_evaluation,
        "preselected_model": ranked_development[0],
        "preselected_model_evaluation": results[ranked_development[0]],
        "note": "Consensus is excluded from fitting and selection.",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT_DIR / "import-cny-calendar-adjustment-timeseries.csv", encoding="utf-8-sig")
    (OUT_DIR / "import-cny-calendar-adjustment.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "original": results["original_import_model"],
        "preselected": ranked_development[:5],
        "preselected_metrics": results[ranked_development[0]],
        "ex_post": ranked_evaluation[:5],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
