#!/usr/bin/env python3
"""Publish the frozen industrial-value nowcast into the shared forecast payload."""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from industrial_value_forecast_model import (
    MODEL_FREEZE_POLICY,
    MODEL_FROZEN_AT,
    MODEL_VERSION,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULT = ROOT / "data" / "industrial-value-model" / "forecast_results.json"
DEFAULT_PRODUCTION = ROOT / "data" / "industrial-value-model" / "production_inputs.json"
DEFAULT_OUTPUT = ROOT / "public" / "data" / "forecasts.json"

WEB_FACTOR_KEYS = (
    "power_coal",
    "blast_furnace",
    "rebar_rate",
    "pta_rate",
    "methanol_rate",
    "car_wholesale",
    "car_retail",
)

FACTOR_META = {
    "power_coal": ("六大发电集团日耗煤", "能源与工业负荷代理", "月内日均值转同比"),
    "blast_furnace": ("247家高炉开工率", "黑色金属生产代理", "月内均值转同比百分点变化"),
    "rebar_rate": ("螺纹钢开工率", "黑色金属生产补充代理", "月内均值转同比百分点变化"),
    "pta_rate": ("PTA装置开工率", "化工生产代理", "月内均值转同比百分点变化"),
    "methanol_rate": ("甲醇开工率", "化工生产补充代理", "月内均值转同比百分点变化"),
    "car_wholesale": ("乘用车厂家日均批发销量", "汽车生产与出货代理", "月内日均值转同比"),
    "car_retail": ("乘用车厂家日均零售销量", "汽车需求验证代理", "月内日均值转同比"),
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def month_key(value: str) -> str:
    return value[:7]


def previous_month(month: str) -> str:
    year, value = (int(part) for part in month.split("-"))
    if value == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{value - 1:02d}"


def strict_direction_hit(history: list[dict[str, Any]]) -> dict[str, float | int]:
    """Direction versus the last released actual, excluding flat actual moves."""
    actual = {
        month_key(row["date"]): float(row["actual"])
        for row in history
        if row.get("actual") is not None
    }
    hits = 0
    observations = 0
    for row in history:
        if row.get("actual") is None or row.get("model") is None:
            continue
        month = month_key(row["date"])
        prior = actual.get(previous_month(month))
        if prior is None:
            continue
        actual_change = float(row["actual"]) - prior
        if actual_change == 0:
            continue
        predicted_change = float(row["model"]) - prior
        observations += 1
        hits += int((actual_change > 0) == (predicted_change > 0))
    return {
        "hits": hits,
        "observations": observations,
        "ratePct": round(100.0 * hits / observations, 2) if observations else 0.0,
    }


def factor_rows(production: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for key in WEB_FACTOR_KEYS:
        item = production.get("series", {}).get(key)
        if not item:
            raise RuntimeError(f"industrial production input is missing: {key}")
        observations = sorted(
            (
                {"date": str(date)[:10], "value": float(value)}
                for date, value in item.get("observations", [])
                if value is not None
            ),
            key=lambda row: row["date"],
        )
        if not observations:
            raise RuntimeError(f"industrial production input has no observations: {key}")
        name, role, aggregation = FACTOR_META[key]
        frequency = {"D": "日频", "W": "周频", "M": "月频"}.get(
            item.get("frequency"), item.get("frequency") or "未知"
        )
        output.append({
            "name": name,
            "id": key,
            "unit": item.get("unit") or "",
            "source": f"{item.get('source') or 'iFinD EDB'} · {item.get('providerId')}",
            "frequency": frequency,
            "role": role,
            "aggregation": aggregation,
            "providerId": item.get("providerId"),
            "latestAvailableDate": observations[-1]["date"],
            "modelUsageNote": "固定因子身份不按月替换；一致预期和同批公布的官方产量不进入模型。",
            "series": observations,
        })
    return output


def augment_forecast_payload(
    payload: dict[str, Any],
    result_path: Path = DEFAULT_RESULT,
    production_path: Path = DEFAULT_PRODUCTION,
) -> dict[str, Any]:
    result = read_json(result_path)
    if result.get("modelVersion") != MODEL_VERSION or not result.get("modelFrozen"):
        raise RuntimeError("industrial-value forecast is not the frozen production model")
    comparison = result["comparisonOnCommonSample"]
    if comparison["model"]["rmse"] >= comparison["consensus"]["rmse"]:
        raise RuntimeError("industrial-value forecast did not pass the consensus RMSE gate")

    key = "industrial_value"
    consensus_id = result.get("providerIds", {}).get("consensus")
    history = []
    # Industrial output is not published separately for January and February.
    # Keep explicit null rows so the shared chart retains its 2023-01 display
    # range without inventing either an official value or a historical forecast.
    display_start = payload.get("displayStart")
    first_result_date = result.get("history", [{}])[0].get("date")
    if display_start and first_result_date:
        cursor = datetime.strptime(display_start, "%Y-%m-%d")
        first = datetime.strptime(first_result_date, "%Y-%m-%d")
        while cursor < first:
            history.append({
                "date": cursor.strftime("%Y-%m-%d"),
                "forecast": None,
                "actual": None,
                "consensus": None,
                "consensusSource": None,
                "forecastKind": "not_published",
                "officialRounding": None,
            })
            year = cursor.year + (1 if cursor.month == 12 else 0)
            month = 1 if cursor.month == 12 else cursor.month + 1
            cursor = datetime(year, month, calendar.monthrange(year, month)[1])
    for row in result.get("history", []):
        if row["date"][5:7] == "01":
            continue
        forecast = row.get("model")
        history.append({
            "date": row["date"],
            "forecast": forecast,
            "actual": row.get("actual"),
            "consensus": row.get("consensus"),
            "consensusSource": (
                f"iFinD EDB · {consensus_id}" if row.get("consensus") is not None else None
            ),
            "forecastKind": row.get("kind") or (
                "live_nowcast" if row.get("actual") is None else "walk_forward"
            ),
            "officialRounding": round(float(forecast), 1) if forecast is not None else None,
        })

    direction = strict_direction_hit(result.get("history", []))
    backtest = result["backtest"]
    latest = result["latest"]
    production = read_json(production_path)
    payload.setdefault("history", {})[key] = history
    payload.setdefault("daily", {})[key] = []
    payload.setdefault("models", {})[key] = {
        "name": "规模以上工业增加值同比",
        "unit": "%",
        "description": "定稿版固定量本底模型：先用已公布季调环比构造固定量指数本底，再由固定生产高频因子估计当月增量；不以上月同比作为预测基础。",
        "formula": "I[t-1]/I[t-12] 固定量本底 + 能源、黑色、化工、汽车和需求固定因子残差桥 + 仅用历史误差的在线权重与校准；一致预期不入模。",
        "status": "READY",
        "forecastMonth": month_key(latest["date"]),
    }
    payload.setdefault("metrics", {})[key] = {
        "rmse": backtest["rmse"],
        "mae": backtest["mae"],
        "sampleStart": month_key(backtest["sampleStart"]),
        "sampleEnd": month_key(backtest["sampleEnd"]),
        "directionHit": direction["ratePct"],
        "benchmarkRmse": comparison["consensus"]["rmse"],
        "observations": backtest["observations"],
    }
    payload.setdefault("highFrequency", {})["工业"] = factor_rows(production)
    payload.setdefault("modelLocks", {})["industrialValue"] = {
        "version": MODEL_VERSION,
        "frozenAt": MODEL_FROZEN_AT,
        "targets": [key],
        "policy": MODEL_FREEZE_POLICY,
    }
    payload["industrialValueModel"] = {
        "version": MODEL_VERSION,
        "forecastMonth": month_key(latest["date"]),
        "latestForecast": latest["model"],
        "informationAsOf": result.get("asOf"),
        "directionHit": direction,
        "consensusPolicy": result.get("consensusPolicy"),
        "performanceGateVsConsensus": {
            "passed": True,
            "modelRmse": comparison["model"]["rmse"],
            "consensusRmse": comparison["consensus"]["rmse"],
        },
        "laggedIndustrialValueIncluded": result["modelSpecification"].get(
            "laggedIndustrialValueIncluded"
        ),
        "monthlyFactorReplacement": result["modelSpecification"].get(
            "monthlyFactorReplacement"
        ),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--production", type=Path, default=DEFAULT_PRODUCTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = read_json(args.base)
    payload = augment_forecast_payload(payload, args.result, args.production)
    payload["generatedAt"] = datetime.now().astimezone().isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"已写入工业增加值定稿模型：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
