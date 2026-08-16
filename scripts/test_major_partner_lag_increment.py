#!/usr/bin/env python3
"""Test whether lagged imports of major destinations improve export nowcasts.

All regressions are expanding-window and use only target observations before
the forecast month. Consensus is not loaded. EU lag 1 is retained only as a
publication-infeasible diagnostic; all other tested lags are release-safe.
"""

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
    spec = importlib.util.spec_from_file_location("trade_model_race", RACE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def score(frame: pd.DataFrame, column: str, mask: pd.Series | None = None) -> dict:
    sample = frame[["actual", column]].dropna()
    if mask is not None:
        sample = sample.loc[mask.reindex(sample.index).fillna(False)]
    error = sample[column] - sample["actual"]
    return {
        "n": int(len(sample)),
        "rmse": round(float(np.sqrt(np.mean(error**2))), 4),
        "mae": round(float(np.mean(np.abs(error))), 4),
        "bias": round(float(np.mean(error)), 4),
    }


def forced_prediction(race, target, day, factors, preferences, forced_column):
    """Use the same ridge bridge but force one candidate into the three-factor block."""
    prior = target.loc[target.index < day].dropna()
    correlations = {}
    for column in factors:
        joined = pd.concat(
            [prior.rename("y"), factors[column].rename("x")], axis=1, sort=False
        ).dropna()
        if len(joined) >= 24 and joined["x"].std() > 1e-12:
            value = joined["y"].corr(joined["x"])
            if pd.notna(value):
                correlations[column] = float(value)
    available = {}
    for family, preferred_lag in preferences.items():
        for lag in range(preferred_lag, preferred_lag + 3):
            column = f"{family}_lag{lag}"
            if column in factors and day in factors.index and pd.notna(factors.loc[day, column]):
                available[family] = column
                break
    forced_family = forced_column.rsplit("_lag", 1)[0]
    if forced_column not in factors or day not in factors.index or pd.isna(factors.loc[day, forced_column]):
        return None, []
    others = [column for family, column in available.items() if family != forced_family]
    others = sorted(others, key=lambda column: abs(correlations.get(column, 0.0)), reverse=True)
    selected = [forced_column] + others[:2]
    training = pd.concat([prior.rename("y"), factors[selected]], axis=1, sort=False).dropna()
    if len(training) < 24:
        return None, selected
    x = training[selected]
    means, stds = x.mean(), x.std().replace(0, 1.0)
    z = (x - means) / stds
    beta = race.ridge(
        np.column_stack([np.ones(len(z)), z.to_numpy()]), training["y"].to_numpy(), 1.0
    )
    now = (factors.loc[day, selected] - means) / stds
    return float(np.r_[1.0, now.to_numpy()] @ beta), selected


def main() -> int:
    race = load_race()
    base = race.load_base()
    dashboard = json.loads(race.DASHBOARD_PATH.read_text(encoding="utf-8-sig"))
    target = base.read_targets(race.TARGET_PATH)["exports"]
    end = base.build_features(dashboard, "exports").dropna(how="all").index.max()
    factors = race.read_partner_import_factors(end)
    # Counterfactual only: production deliberately starts EU at lag 2 because
    # lag 1 is not consistently released before China's customs cutoff.
    factors["eu27_imports_from_china_yoy_lag1"] = (
        factors["eu27_imports_from_china_yoy_lag2"].shift(-1)
    )
    race.read_partner_import_factors = lambda _end: factors

    baseline = dict(race.PARTNER_PREFERRED_LAGS)
    variants = {
        "baseline": baseline,
        "baseline_plus_us_lag1": {**baseline, "us_imports_from_china_yoy": 1},
        "baseline_plus_us_lag2": {**baseline, "us_imports_from_china_yoy": 2},
        "baseline_plus_japan_lag1": {**baseline, "japan_imports_from_china_yoy": 1},
        "baseline_plus_japan_lag2": {**baseline, "japan_imports_from_china_yoy": 2},
        "baseline_plus_us1_japan1": {
            **baseline,
            "us_imports_from_china_yoy": 1,
            "japan_imports_from_china_yoy": 1,
        },
        "baseline_plus_us2_japan2": {
            **baseline,
            "us_imports_from_china_yoy": 2,
            "japan_imports_from_china_yoy": 2,
        },
        "baseline_eu_lag1_diagnostic": {**baseline, "eu27_imports_from_china_yoy": 1},
    }

    rows = []
    forced_candidates = {
        "forced_us_lag1": "us_imports_from_china_yoy_lag1",
        "forced_us_lag2": "us_imports_from_china_yoy_lag2",
        "forced_japan_lag1": "japan_imports_from_china_yoy_lag1",
        "forced_japan_lag2": "japan_imports_from_china_yoy_lag2",
        "forced_eu_lag1_diagnostic": "eu27_imports_from_china_yoy_lag1",
        "forced_eu_lag2": "eu27_imports_from_china_yoy_lag2",
    }
    for day in pd.date_range(race.START, target.dropna().index.max(), freq="ME"):
        if day not in target.index or pd.isna(target.loc[day]):
            continue
        row = {"date": day, "actual": float(target.loc[day])}
        for name, preferences in variants.items():
            race.PARTNER_PREFERRED_LAGS = preferences
            prediction, selected, _, _ = race.destination_import_prediction(target, day, end)
            row[name] = prediction
            row[f"{name}__features"] = "|".join(selected)
        for name, candidate in forced_candidates.items():
            prediction, selected = forced_prediction(
                race, target, day, factors, baseline, candidate
            )
            row[name] = prediction
            row[f"{name}__features"] = "|".join(selected)
        rows.append(row)
    frame = pd.DataFrame(rows).set_index("date")
    prediction_columns = list(variants)
    common_mask = frame[prediction_columns].notna().all(axis=1)
    baseline_score = score(frame, "baseline", common_mask)
    metrics = {}
    for name in prediction_columns:
        result = score(frame, name, common_mask)
        result["rmse_change_vs_baseline"] = round(result["rmse"] - baseline_score["rmse"], 4)
        result["rmse_improvement_pct"] = round(
            (baseline_score["rmse"] - result["rmse"]) / baseline_score["rmse"] * 100, 2
        )
        result["release_safe"] = name != "baseline_eu_lag1_diagnostic"
        metrics[name] = result

    forced_metrics = {}
    for name in forced_candidates:
        paired = frame[["actual", "baseline", name]].dropna()
        if paired.empty:
            forced_metrics[name] = {"n": 0, "status": "insufficient_history"}
            continue
        baseline_error = paired["baseline"] - paired["actual"]
        augmented_error = paired[name] - paired["actual"]
        baseline_rmse = float(np.sqrt(np.mean(baseline_error**2)))
        augmented_rmse = float(np.sqrt(np.mean(augmented_error**2)))
        forced_metrics[name] = {
            "n": int(len(paired)),
            "sample_start": paired.index.min().strftime("%Y-%m"),
            "sample_end": paired.index.max().strftime("%Y-%m"),
            "paired_baseline_rmse": round(baseline_rmse, 4),
            "augmented_rmse": round(augmented_rmse, 4),
            "rmse_change_vs_paired_baseline": round(augmented_rmse - baseline_rmse, 4),
            "rmse_improvement_pct": round((baseline_rmse - augmented_rmse) / baseline_rmse * 100, 2),
            "release_safe": name != "forced_eu_lag1_diagnostic",
        }

    corr_rows = []
    for family, minimum in {
        "us_imports_from_china_yoy": 1,
        "japan_imports_from_china_yoy": 1,
        "eu27_imports_from_china_yoy": 2,
    }.items():
        for lag in (1, 2):
            column = f"{family}_lag{lag}"
            joined = pd.concat(
                [target.rename("actual"), factors[column].rename("factor")], axis=1, sort=False
            ).dropna()
            train = joined.loc[joined.index < race.START]
            evaluation = joined.loc[joined.index >= race.START]
            corr_rows.append({
                "family": family,
                "lag_months": lag,
                "release_safe": lag >= minimum,
                "train_n": int(len(train)),
                "train_corr": float(train["actual"].corr(train["factor"])) if len(train) >= 3 else None,
                "evaluation_n": int(len(evaluation)),
                "evaluation_corr": float(evaluation["actual"].corr(evaluation["factor"])) if len(evaluation) >= 3 else None,
            })

    payload = {
        "status": "RESEARCH_NOT_FOR_PUBLICATION",
        "method": "expanding-window marginal test; consensus excluded",
        "common_sample_months": [d.strftime("%Y-%m") for d in frame.index[common_mask]],
        "metrics": metrics,
        "forced_increment_metrics": forced_metrics,
        "factor_correlations": corr_rows,
        "limitations": [
            "US bilateral series returned by fuzzy MCP begins in 2023, leaving too little pre-backtest YoY history.",
            "EU lag 1 is not consistently published before the China customs cutoff and is diagnostic only.",
            "Current provider snapshots are final/revised values rather than archived first-release vintages.",
        ],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "major-partner-lag-increment.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    frame.to_csv(OUT_DIR / "major-partner-lag-increment-timeseries.csv", encoding="utf-8-sig")
    pd.DataFrame(corr_rows).to_csv(
        OUT_DIR / "major-partner-lag-correlations.csv", index=False, encoding="utf-8-sig"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
