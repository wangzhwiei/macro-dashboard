#!/usr/bin/env python3
"""Add the approved fixed-factor trade forecasts to the website payload."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RACE_CSV = ROOT / "outputs" / "trade-model-research" / "model-race.csv"
RACE_JSON = ROOT / "outputs" / "trade-model-research" / "model-race.json"
TARGETS = ROOT / "data" / "trade-model" / "trade_targets_ifind.csv"
PARTNERS = ROOT / "data" / "trade-model" / "trade_partner_import_factors.json"
ANCHORS = ROOT / "data" / "trade-model" / "trade_anchor_factors.json"

CONFIG = {
    "exports": {
        "label": "出口同比", "field": "export_fixed_cny_gated",
        "factors": (
            ("partner", "korea_imports_from_china_yoy", "trade_korea_imports_china", "韩国自中国进口同比", "目标月当月值（lag0）"),
            ("partner", "taiwan_imports_from_mainland_value", "trade_taiwan_imports_mainland", "中国台湾自大陆进口额", "上月值计算同比（lag1）"),
            ("partner", "thailand_imports_from_china_value", "trade_thailand_imports_china", "泰国自中国进口额", "上月值计算同比（lag1）"),
        ),
    },
    "imports": {
        "label": "进口同比", "field": "import_fixed_cny_gated",
        "factors": (
            ("anchor", "korea_export_yoy", "trade_korea_exports", "韩国出口同比", "目标月当月变化（lag0）"),
        ),
    },
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def series_map(path: Path) -> dict[str, float]:
    payload = read_json(path)
    return {str(day)[:10]: float(value) for day, value in payload.get("data", [])}


def input_row(store: dict[str, Any], key: str, item_id: str, name: str, usage: str) -> dict[str, Any]:
    raw = store["series"][key]
    points = sorted(
        ({"date": str(day)[:10], "value": float(value)} for day, value in raw.get("data", [])),
        key=lambda row: row["date"],
    )
    return {
        "name": name, "id": item_id, "unit": raw["unit"],
        "source": raw["source"], "frequency": "月频",
        "role": "固定进出口预测因子", "aggregation": usage,
        "providerId": raw["providerId"],
        "latestAvailableDate": points[-1]["date"] if points else None,
        "modelUsageNote": "因子与滞后固定；缺少规定月份时停止预测，不替换因子、不回退滞后。",
        "series": points,
    }


def augment_payload(payload: dict[str, Any]) -> dict[str, Any]:
    race = read_json(RACE_JSON)
    frame = pd.read_csv(RACE_CSV)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    targets = pd.read_csv(TARGETS)
    targets["date"] = pd.to_datetime(targets["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    actual_maps = {
        "exports": dict(zip(targets["date"], targets["exports_yoy"])),
        "imports": dict(zip(targets["date"], targets["imports_yoy"])),
    }
    consensus_maps = {
        "exports": series_map(ROOT / "data" / "trade-model" / "baseline_export_yoy.json"),
        "imports": series_map(ROOT / "data" / "trade-model" / "baseline_import_yoy.json"),
    }
    partner, anchor = read_json(PARTNERS), read_json(ANCHORS)
    stores = {"partner": partner, "anchor": anchor}
    factor_rows: dict[str, list[dict[str, Any]]] = {key: [] for key in CONFIG}
    for key, config in CONFIG.items():
        for store_name, factor_key, item_id, name, usage in config["factors"]:
            factor_rows[key].append(input_row(stores[store_name], factor_key, item_id, name, usage))
        selected = frame.loc[frame["target"].eq(key), ["date", config["field"]]].dropna()
        forecasts = dict(zip(selected["date"], selected[config["field"]]))
        current = race["targets"][key]["current_forecast"]
        current_day = f"{current['month']}-01"
        current_day = (pd.Timestamp(current_day) + pd.offsets.MonthEnd(0)).date().isoformat()
        start = pd.Timestamp("2023-01-31")
        end = max(
            pd.Timestamp(current_day),
            pd.Timestamp(max(actual_maps[key])),
        )
        history = []
        prior_consensus = [
            (day, value) for day, value in consensus_maps[key].items()
            if day < start.date().isoformat()
        ]
        last_consensus = max(prior_consensus, default=("", None))[1]
        for day in pd.date_range(start, end, freq="ME"):
            date_key = day.date().isoformat()
            forecast = forecasts.get(date_key)
            if date_key == current_day:
                forecast = current.get("forecast")
            actual = actual_maps[key].get(date_key)
            raw_consensus = consensus_maps[key].get(date_key)
            consensus_carried_forward = raw_consensus is None and last_consensus is not None
            if raw_consensus is not None:
                last_consensus = raw_consensus
            consensus = last_consensus
            history.append({
                "date": date_key,
                "forecast": round(float(forecast), 6) if pd.notna(forecast) else None,
                "actual": round(float(actual), 6) if pd.notna(actual) else None,
                "consensus": round(float(consensus), 6) if consensus is not None else None,
                "consensusSource": (
                    "iFinD EDB · 预测平均值（沿用上期）"
                    if consensus_carried_forward else
                    "iFinD EDB · 预测平均值"
                    if consensus is not None else None
                ),
                "consensusCarriedForward": consensus_carried_forward,
                "forecastKind": "walk_forward" if pd.notna(forecast) and pd.notna(actual) else None,
                "officialRounding": round(float(forecast), 1) if pd.notna(forecast) else None,
            })
        payload.setdefault("history", {})[key] = history
        payload.setdefault("daily", {})[key] = []
        all_score = race["targets"][key]["all_available_scores"][config["field"]]
        payload.setdefault("metrics", {})[key] = {
            "rmse": all_score["rmse"], "mae": all_score["mae"],
            "sampleStart": all_score["sample_start"], "sampleEnd": all_score["sample_end"],
            "directionHit": all_score["direction_hit_pct"], "observations": all_score["observations"],
        }
        fixed_names = "、".join(row[3] for row in config["factors"])
        payload.setdefault("models", {})[key] = {
            "name": config["label"], "unit": "%",
            "description": f"{config['label']}采用固定因子结构、固定滞后与扩展窗口滚动估计系数；一致预期只用于评价。",
            "formula": f"固定因子：{fixed_names}；1—3月加入春节日历门控。任一固定因子未公布时不生成预测。",
            "status": current["status"], "forecastMonth": current["month"],
            "earliestForecastDate": current["earliest_factor_release_date"],
            "missingFactors": current["missing_factors"],
        }
    high_frequency = payload.setdefault("highFrequency", {})
    high_frequency.pop("进出口", None)
    high_frequency["出口"] = factor_rows["exports"]
    high_frequency["进口"] = factor_rows["imports"]
    payload["tradeModel"] = {
        "version": "trade-fixed-factors-cny-gated-v1",
        "factorPolicy": "fixed families and lags; rolling coefficients; no missing-factor fallback",
        "consensusRole": "evaluation only",
        "current": {key: race["targets"][key]["current_forecast"] for key in CONFIG},
    }
    return payload


def main() -> int:
    path = ROOT / "public" / "data" / "forecasts.json"
    payload = augment_payload(read_json(path))
    payload["generatedAt"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
