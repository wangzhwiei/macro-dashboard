#!/usr/bin/env python3
"""Fetch CPI, PPI and PMI consensus from iFinD EDB with fixed provider IDs."""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.fetch_forecast_inputs_ifind import choose_candidate, inner_payload

OUTPUT = ROOT / "data" / "forecast-model" / "consensus.json"
SOURCE = "iFinD EDB"
CONFIG: dict[str, dict[str, Any]] = {
    "cpi": {
        "key": "consensus_cpi_yoy",
        "queryName": "预测平均值:CPI:当月同比",
        "providerId": "M005682252",
        "frequency": "M",
        "unit": "%",
    },
    "ppi": {
        "key": "consensus_ppi_yoy",
        "queryName": "预测平均值:PPI:当月同比",
        "providerId": "M005682253",
        "frequency": "M",
        "unit": "%",
    },
    "pmi": {
        "key": "consensus_pmi",
        "queryName": "预测平均值:PMI",
        "providerId": "M005779145",
        "frequency": "M",
        "unit": "%",
        "forwardFillMissingMonths": True,
    },
}


def month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 31)
    return month_end(date(day.year, day.month + 1, 1))


def build_query(config: dict[str, Any], start: str, end: str) -> str:
    """Use the Chinese name for discovery and the provider ID as a strict hint."""
    return (
        f"中国:{config['queryName']}:同花顺iFinD，指标ID:{config['providerId']}"
        f"（{start.replace('-', '')}-{end.replace('-', '')}）"
    )


def validate_candidate(config: dict[str, Any], candidate: dict[str, Any]) -> None:
    if candidate.get("providerId") != config["providerId"]:
        raise RuntimeError(
            f"{config['key']} ID漂移：期望{config['providerId']}，返回{candidate.get('providerId')}"
        )
    if candidate.get("name") != config["queryName"]:
        raise RuntimeError(
            f"{config['key']} 名称不一致：期望{config['queryName']!r}，返回{candidate.get('name')!r}"
        )
    if candidate.get("frequency") != config["frequency"]:
        raise RuntimeError(
            f"{config['key']} 频率不一致：期望{config['frequency']}，返回{candidate.get('frequency')}"
        )
    if candidate.get("unit") != config["unit"]:
        raise RuntimeError(
            f"{config['key']} 单位不一致：期望{config['unit']}，返回{candidate.get('unit')}"
        )


def candidate_to_records(
    candidate: dict[str, Any],
    config: dict[str, Any],
    start: str,
    end: str,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    by_month: dict[str, dict[str, Any]] = {}
    for raw_day, raw_value in candidate.get("records", []):
        observed_day = date.fromisoformat(str(raw_day)[:10])
        if not start_day <= observed_day <= end_day:
            continue
        normalized_day = month_end(observed_day).isoformat()
        by_month[normalized_day] = {
            "date": normalized_day,
            "value": float(raw_value),
            "source": SOURCE,
            "queryName": config["queryName"],
            "providerId": config["providerId"],
            "frequency": config["frequency"],
            "unit": config["unit"],
            "retrievedAt": retrieved_at,
            "imputed": False,
        }
    return [by_month[key] for key in sorted(by_month)]


def forward_fill_months(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill only internal PMI gaps; never extend beyond the last observed month."""
    if not records:
        return []
    observed = {row["date"]: row for row in records}
    cursor = date.fromisoformat(records[0]["date"])
    final_day = date.fromisoformat(records[-1]["date"])
    result: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    while cursor <= final_day:
        key = cursor.isoformat()
        if key in observed:
            current = dict(observed[key])
        elif previous is not None:
            current = {
                **previous,
                "date": key,
                "imputed": True,
                "imputation": "previous_month_forward_fill",
                "imputedFrom": previous["date"],
            }
        else:  # pragma: no cover
            cursor = next_month(cursor)
            continue
        result.append(current)
        previous = current
        cursor = next_month(cursor)
    return result


def load_ifind_call(skill_dir: Path) -> Callable[..., dict[str, Any]]:
    if not (skill_dir / "call.py").exists() or not (skill_dir / "mcp_config.json").exists():
        raise RuntimeError("iFinD skill 目录缺少 call.py 或 mcp_config.json")
    sys.path.insert(0, str(skill_dir))
    previous_cwd = Path.cwd()
    os.chdir(skill_dir)
    try:
        from call import call as ifind_call
    finally:
        os.chdir(previous_cwd)
    return ifind_call


def fetch_candidate(
    ifind_call: Callable[..., dict[str, Any]],
    config: dict[str, Any],
    start: str,
    end: str,
    attempts: int,
) -> dict[str, Any]:
    query = build_query(config, start, end)
    last_error: Exception | None = None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            response = ifind_call("edb", "get_edb_data", {"query": query})
            candidate = choose_candidate(config, inner_payload(response))
            validate_candidate(config, candidate)
            return candidate
        except Exception as error:
            last_error = error
            if attempt < max(attempts, 1):
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"{config['key']} iFinD查询失败：{last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", type=Path, default=os.environ.get("IFIND_SKILL_DIR"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()
    if args.skill_dir is None:
        raise RuntimeError("请设置 IFIND_SKILL_DIR 或传入 --skill-dir")

    retrieved_at = datetime.now().astimezone().isoformat()
    ifind_call = load_ifind_call(args.skill_dir.resolve())
    result: dict[str, Any] = {
        "_meta": {
            "source": SOURCE,
            "retrievedAt": retrieved_at,
            "usage": "personal research",
            "field": "iFinD 预测平均值",
            "queryMode": "Chinese name discovery + fixed provider ID validation",
            "providerIds": {key: config["providerId"] for key, config in CONFIG.items()},
            "pmiMissingPolicy": "internal missing months use previous month value",
        }
    }
    for key, config in CONFIG.items():
        candidate = fetch_candidate(ifind_call, config, args.start, args.end, args.attempts)
        records = candidate_to_records(candidate, config, args.start, args.end, retrieved_at)
        if not records:
            raise RuntimeError(f"{key.upper()} 固定ID已命中，但没有可用数据")
        if config.get("forwardFillMissingMonths"):
            records = forward_fill_months(records)
        result[key] = records
        filled = sum(bool(row.get("imputed")) for row in records)
        latest = records[-1]
        print(
            f"{key.upper()} 一致预期已核验：{latest['date']}={latest['value']} "
            f"ID={latest['providerId']} fill={filled}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())