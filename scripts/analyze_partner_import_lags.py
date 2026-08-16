#!/usr/bin/env python3
"""Measure transport/publication lags for destination imports from China."""

from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("research_trade_model_race", ROOT / "scripts" / "research_trade_model_race.py")
race = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = race
SPEC.loader.exec_module(race)
OUTPUT_CSV = ROOT / "outputs" / "trade-model-research" / "partner-import-lag-correlations.csv"
OUTPUT_JSON = ROOT / "outputs" / "trade-model-research" / "partner-import-lag-correlations.json"


def correlation(target: pd.Series, factor: pd.Series, mask=None) -> tuple[int, float | None]:
    joined = pd.concat([target.rename("y"), factor.rename("x")], axis=1, sort=False).dropna()
    if mask is not None:
        joined = joined.loc[mask(joined.index)]
    value = joined["y"].corr(joined["x"]) if len(joined) >= 6 else None
    return len(joined), None if pd.isna(value) else float(value)


def main() -> int:
    base = race.load_base()
    target = base.read_targets(race.TARGET_PATH)["exports"]
    payload = json.loads(race.PARTNER_IMPORT_FACTOR_PATH.read_text(encoding="utf-8"))
    rows = []
    for key, item in payload["series"].items():
        series = pd.Series(
            {pd.Timestamp(row[0]) + pd.offsets.MonthEnd(0): float(row[1]) for row in item["data"]},
            dtype=float,
        ).sort_index()
        if item.get("transform") == "yoy_from_monthly_value":
            series = series.pct_change(12, fill_method=None) * 100
        minimum = int(item["availabilityLagMonths"])
        for lag in range(-1, 4):
            shifted = series.shift(lag)
            train_n, train_corr = correlation(target, shifted, lambda index: index < race.START)
            full_n, full_corr = correlation(target, shifted)
            eval_n, eval_corr = correlation(target, shifted, lambda index: index >= race.START)
            early_n, early_corr = correlation(
                target, shifted, lambda index: (index >= race.START) & (index < pd.Timestamp("2025-07-31"))
            )
            late_n, late_corr = correlation(
                target, shifted, lambda index: index >= pd.Timestamp("2025-07-31")
            )
            rows.append({
                "family": key.replace("_value", "_yoy"),
                "provider_id": item["providerId"], "name": item["name"],
                "lag_months": lag, "minimum_release_lag": minimum,
                "release_feasible": lag >= minimum,
                "train_n": train_n, "train_corr": train_corr,
                "full_n": full_n, "full_corr": full_corr,
                "evaluation_n": eval_n, "evaluation_corr": eval_corr,
                "early_evaluation_n": early_n, "early_evaluation_corr": early_corr,
                "late_evaluation_n": late_n, "late_evaluation_corr": late_corr,
            })
    frame = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT_CSV, index=False)
    summary = {}
    for family, group in frame.groupby("family"):
        feasible = group.loc[group["release_feasible"] & group["train_corr"].notna()]
        diagnostic = group.loc[group["full_corr"].notna()]
        chosen = (
            feasible.loc[feasible["train_corr"].abs().idxmax()].to_dict()
            if not feasible.empty else None
        )
        full_best = (
            diagnostic.loc[diagnostic["full_corr"].abs().idxmax()].to_dict()
            if not diagnostic.empty else None
        )
        summary[family] = {"past_only_choice": chosen, "full_sample_diagnostic_best": full_best}
    OUTPUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT_CSV)
    print(OUTPUT_JSON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
