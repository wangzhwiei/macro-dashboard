#!/usr/bin/env python3
"""Refresh current forecast inputs and actuals without rerunning walk-forward backtests."""

from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
import pandas as pd
from forecast_realtime import build_daily_nowcasts
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
    for key in ("cpi", "ppi", "pmi"):
        by_month = {row["date"]: row for row in consensus.get(key, [])}
        for row in payload["history"][key]:
            matched = by_month.get(row["date"])
            row["consensus"] = round(float(matched["value"]), 6) if matched else None
            row["consensusSource"] = matched.get("source") if matched else None
    payload["highFrequency"] = build_high_frequency(ifind)
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
    locked_payload = locked[locked_day.date().isoformat()]
    daily = build_daily_nowcasts(source, live, locked_payload, locked_day)
    daily["pmi"] = [{"date": locked_day.date().isoformat(), "value": round(float(locked_payload["pmi"]["forecast"]), 6)}]
    payload["daily"], payload["dailyAsOf"] = daily, daily["cpi"][-1]["date"]
    payload["generatedAt"] = datetime.now().astimezone().isoformat()
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"快速刷新完成：{args.output}；历史回测未重跑")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
