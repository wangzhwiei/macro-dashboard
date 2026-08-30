#!/usr/bin/env python3
"""Refresh current forecast inputs and actuals without rerunning walk-forward backtests."""

from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from forecast_realtime import build_daily_nowcasts, build_pmi_daily_nowcasts
from generate_forecasts_model import build_high_frequency, ifind_series, merge_official_pmi, read_json

ROOT = Path(__file__).resolve().parents[1]
JUNE = pd.Timestamp("2026-06-30")
DASHBOARD_IDS = {"vegetable_price", "pork_price", "nanhua_industry", "brent", "qhd_coal_price", "rebar_price", "copper_price"}
OFFICIAL_KEYS = {"cpi": "actual_cpi_yoy", "cpi_mom": "actual_cpi_mom", "ppi": "actual_ppi_yoy", "ppi_mom": "actual_ppi_mom", "pmi": "cpi_pmi"}


def build_live_inputs(dashboard: dict[str, Any], ifind: dict[str, Any]) -> dict[str, Any]:
    selected = {
        item["id"]: {
            "name": item.get("name"), "frequency": item.get("frequency"),
            "unit": item.get("unit"), "source": item.get("source"),
            "series": [[row["date"], row["value"]] for row in item.get("series", [])],
        }
        for item in dashboard.get("indicators", []) if item.get("id") in DASHBOARD_IDS
    }
    missing = DASHBOARD_IDS.difference(selected)
    if missing:
        raise RuntimeError(f"dashboard 缺少实时预测序列：{sorted(missing)}")
    crb_meta, crb = ifind_series(ifind, "cpi_crb")
    return {
        "schemaVersion": 1, "dashboardGeneratedAt": dashboard.get("generatedAt"), "dashboard": selected,
        "ifindCrb": {
            "id": crb_meta["providerId"], "name": crb_meta.get("name") or crb_meta.get("queryName"),
            "frequency": "日频", "unit": crb_meta.get("unit"),
            "source": f"iFinD EDB · {crb_meta['providerId']}",
            "series": [[day.date().isoformat(), float(value)] for day, value in crb.items()],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "public" / "data" / "forecasts.json")
    args = parser.parse_args()
    ifind = read_json(ROOT / "data" / "forecast-model" / "ifind_latest_inputs.json")
    if ifind.get("errors"):
        raise RuntimeError(f"iFinD 输入仍有错误：{ifind['errors']}")
    payload = read_json(args.output)
    display_start = payload.get("backtestStart", "2023-01-31")
    payload["displayStart"] = display_start
    for key, rows in payload["history"].items():
        payload["history"][key] = [row for row in rows if row["date"] >= display_start]
    consensus = read_json(ROOT / "data" / "forecast-model" / "consensus.json")
    target_month = pd.Timestamp.now().normalize() + pd.offsets.MonthEnd(0)
    # A fast refresh may only update the current-month CPI/PPI/PMI groups.
    # Preserve locked historical consensus values and model-specific groups
    # already published in the page.
    payload.setdefault("highFrequency", {}).update(build_high_frequency(ifind, target_month))
    for history_key, ifind_key in OFFICIAL_KEYS.items():
        _, series = ifind_series(ifind, ifind_key)
        official = {
            day.date().isoformat(): round(float(value), 6)
            for day, value in series.resample("ME").last().dropna().items() if day > JUNE
        }
        for row in payload["history"][history_key]:
            if row["date"] in official:
                row["actual"] = official[row["date"]]
    source = read_json(ROOT / "data" / "forecast-model" / "model_inputs.json")
    merge_official_pmi(source, read_json(ROOT / "data" / "forecast-model" / "official_pmi_subindices.json"))
    locked = read_json(ROOT / "data" / "forecast-model" / "locked_nowcasts.json")
    locked_day = max(pd.Timestamp(day) for day in locked)
    live = build_live_inputs(read_json(ROOT / "public" / "data" / "dashboard.json"), ifind)
    (ROOT / "data" / "forecast-model" / "live_inputs.json").write_text(
        json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    previous = target_month - pd.offsets.MonthEnd(1)
    previous_actuals = {}
    for history_key, ifind_key in OFFICIAL_KEYS.items():
        _, values = ifind_series(ifind, ifind_key)
        monthly_values = values.resample("ME").last().dropna()
        if previous not in monthly_values.index:
            raise RuntimeError(f"{history_key} 缺少 {previous:%Y-%m} 官方值，不能生成实时路径")
        previous_actuals[history_key] = float(monthly_values.loc[previous])
    daily = build_daily_nowcasts(source, live, None, target_month, previous_actuals)
    daily["pmi"] = build_pmi_daily_nowcasts(source, ifind, target_month)
    target_day = target_month.date().isoformat()
    for key in ("cpi", "cpi_mom", "ppi", "ppi_mom", "pmi"):
        payload["history"][key] = [row for row in payload["history"][key]
                                   if row.get("forecastKind") != "live_nowcast" and row["date"] != target_day]
        consensus_row = next((row for row in consensus.get(key, []) if row["date"] == target_day), None)
        latest_value = float(daily[key][-1]["value"])
        payload["history"][key].append({
            "date": target_day, "forecast": round(latest_value, 6), "actual": None,
            "consensus": round(float(consensus_row["value"]), 6) if consensus_row else None,
            "consensusSource": consensus_row.get("source") if consensus_row else None,
            "forecastKind": "live_nowcast", "officialRounding": round(latest_value, 1),
        })
    payload["daily"] = daily
    payload["dailyAsOf"] = max(rows[-1]["date"] for rows in daily.values() if rows)
    for section in ("daily", "history", "models", "metrics"):
        for trade_key in ("imports", "exports"):
            payload.get(section, {}).pop(trade_key, None)
    payload.get("highFrequency", {}).pop("进出口", None)
    payload["generatedAt"] = datetime.now().astimezone().isoformat()
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"快速刷新完成：{args.output}；历史回测未重跑")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
