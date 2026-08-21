#!/usr/bin/env python3
"""Publish the locked V7 retail model into the forecast-page JSON contract."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import research_retail_forecast as v7


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "data" / "forecast-model" / "retail_model_research.json"
PRODUCTION_PATH = ROOT / "data" / "forecast-model" / "retail_v7_production.json"
FORECAST_PATH = ROOT / "public" / "data" / "forecasts.json"
MODEL_KEY = "seasonalGatedRankedTop5"
FACTOR_ROLES = {
    "cpi_services_detail_yoy": "名义消费价格代理",
    "pmi_services_new_orders": "服务消费需求领先代理",
    "car_retail_level_yoy": "汽车类零售直接代理",
    "cpi_nonfood_detail_yoy": "非食品商品价格代理",
    "cpi_yoy": "总体名义价格环境",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def input_rows(factors: pd.DataFrame, metadata: dict[str, dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    rows = []
    for key in keys:
        item = metadata[key]
        values = factors[key].loc["2023-01-01":].dropna()
        unit = "点" if key.startswith("pmi_") else "%"
        rows.append({
            "name": item["name"],
            "id": key,
            "unit": unit,
            "source": item["source"],
            "frequency": "月频",
            "role": FACTOR_ROLES[key],
            "aggregation": item["transform"],
            "providerId": item.get("providerId"),
            "latestAvailableDate": values.index.max().date().isoformat() if len(values) else None,
            "sourceAsOf": item.get("sourceAsOf"),
            "latestCompleteMonth": item.get("latestCompleteMonth"),
            "currentMonthStatus": item.get("currentMonthStatus"),
            "modelUsageNote": "V7正式模型使用当月可获得值；一致预期不参与训练或选参。",
            "series": [
                {"date": day.date().isoformat(), "value": round(float(value), 6)}
                for day, value in values.items()
            ],
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--output", type=Path, default=FORECAST_PATH)
    args = parser.parse_args()
    research = read_json(args.model)
    if research.get("rankedTopKRace", {}).get("selectedModel") != MODEL_KEY:
        raise RuntimeError(f"V7候选模型漂移：{research.get('rankedTopKRace', {}).get('selectedModel')}")
    model = {**research}
    model["modelVersion"] = "retail-v7-production"
    model["productionDecision"] = {
        "status": "production",
        "primaryCandidate": MODEL_KEY,
        "deploymentCandidate": MODEL_KEY,
        "robustnessStatus": "accepted_by_user_decision_with_monitoring",
        "promotionDate": "2026-08-21",
        "researchWarning": research.get("productionDecision", {}).get("reason"),
        "reason": "V7 was explicitly approved by the user as the production retail-sales model on 2026-08-21.",
        "monitoringRule": "Track monthly absolute error against iFinD consensus; do not auto-switch models without a new locked backtest.",
    }
    PRODUCTION_PATH.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    decision = model["productionDecision"]

    payload = read_json(args.output)
    data = v7.read_json(v7.DATA_PATH)
    factors, metadata = v7.build_factors(v7.read_json(v7.INPUT_PATH), v7.read_json(v7.DASHBOARD_PATH), data)
    selected = model["rankedTopKRace"]["factorSets"]["RankedTop5"]
    if selected != [
        "cpi_services_detail_yoy", "pmi_services_new_orders", "car_retail_level_yoy",
        "cpi_nonfood_detail_yoy", "cpi_yoy",
    ]:
        raise RuntimeError(f"V7因子集合漂移：{selected}")

    history = []
    for row in model["history"]:
        if row["date"] < "2023-01-01":
            continue
        forecast = row.get(MODEL_KEY)
        history.append({
            "date": row["date"],
            "forecast": round(float(forecast), 6) if forecast is not None else None,
            "actual": round(float(row["actual"]), 6) if row.get("actual") is not None else None,
            "consensus": round(float(row["consensus"]), 6) if row.get("consensus") is not None else None,
            "consensusSource": "iFinD EDB · M005682254" if row.get("consensus") is not None else None,
            "forecastKind": "walk_forward" if forecast is not None else None,
            "officialRounding": round(float(forecast), 1) if forecast is not None else None,
        })

    latest = model["latestForecast"]
    current_month = pd.Timestamp(f"{latest['month']}-01") + pd.offsets.MonthEnd(0)
    missing = [metadata[key]["name"] for key in selected if pd.isna(factors[key].get(current_month))]
    holdout = model["rankedTopKRace"]["holdoutPeriod"][MODEL_KEY]
    payload.setdefault("daily", {})["retail"] = []
    payload.setdefault("history", {})["retail"] = history
    payload.setdefault("models", {})["retail"] = {
        "name": "社零同比V7（正式版）",
        "unit": "%",
        "description": "V7采用无前视扩展窗口模型；一致预期只用于网页比较，不参与训练、因子筛选或模型定稿。",
        "formula": "季节与春节/3月发布控制 + 上期社零锚定；五因子为服务CPI、服务业新订单PMI、乘用车零售同比、非食品CPI和CPI同比；2021与2023使用异常基数门控。",
        "status": "WAITING_FOR_MONTHLY_FACTORS" if latest.get("model") is None else "READY",
        "forecastMonth": latest["month"],
        "earliestForecastDate": "2026-09-09",
        "missingFactors": missing,
    }
    payload.setdefault("metrics", {})["retail"] = {
        "rmse": holdout["rmse"],
        "mae": holdout["mae"],
        "sampleStart": holdout["sampleStart"],
        "sampleEnd": holdout["sampleEnd"],
        "directionHit": holdout["directionHitPct"],
        "observations": holdout["observations"],
    }
    payload.setdefault("highFrequency", {})["社零"] = input_rows(factors, metadata, selected)
    payload.setdefault("productionModels", {})["retail"] = {
        "version": model["modelVersion"],
        "deploymentCandidate": MODEL_KEY,
        "promotedAt": decision["promotionDate"],
        "consensusRole": "comparison_only",
        "monitoringRule": decision["monitoringRule"],
    }
    source_parts = [part.strip() for part in str(payload.get("source", "")).split("+") if part.strip()]
    source_parts = [part for part in source_parts if part != "社零V7正式模型"]
    payload["source"] = " + ".join([*source_parts, "社零V7正式模型"])
    payload["generatedAt"] = datetime.now().astimezone().isoformat()
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "model": payload["models"]["retail"],
        "metric": payload["metrics"]["retail"],
        "historyRows": len(history),
        "inputFactors": selected,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
