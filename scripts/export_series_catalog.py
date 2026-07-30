#!/usr/bin/env python3
"""Export every raw series required by the dashboard for provider-code mapping."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def mapped_code(mapping: dict[str, Any], semantic_code: str) -> str:
    value = mapping.get(semantic_code, "")
    if isinstance(value, dict):
        value = value.get("provider_code") or value.get("code") or ""
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=ROOT / "config" / "indicators.json"
    )
    parser.add_argument(
        "--auxiliary",
        type=Path,
        default=ROOT / "config" / "auxiliary-indicators.csv",
    )
    parser.add_argument("--mapping", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "outputs" / "series-catalog.csv",
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    mapping = (
        json.loads(args.mapping.read_text(encoding="utf-8"))
        if args.mapping and args.mapping.exists()
        else {}
    )
    rows: list[dict[str, Any]] = []
    for indicator in config["indicators"]:
        for component in indicator["series"]:
            semantic_code = component["code"]
            provider_code = mapped_code(mapping, semantic_code)
            rows.append(
                {
                    "indicator_id": indicator["id"],
                    "indicator_name": indicator["name"],
                    "category": indicator["category"],
                    "family": indicator["family"],
                    "frequency": indicator["frequency"],
                    "unit": indicator.get("unit", ""),
                    "source": indicator.get("source", ""),
                    "semantic_code": semantic_code,
                    "provider_code": provider_code,
                    "mapping_status": "mapped" if provider_code else "pending",
                    "component_weight": component.get("weight", 1),
                    "core": "true" if indicator.get("core", True) else "false",
                    "aggregate": indicator.get("aggregate", ""),
                    "transform": indicator.get("transform", "pct_change"),
                    "bond_direction": indicator.get("bond_direction", -1),
                }
            )

    if args.auxiliary.exists():
        with args.auxiliary.open("r", encoding="utf-8-sig", newline="") as handle:
            for item in csv.DictReader(handle):
                semantic_code = item["code"]
                provider_code = mapped_code(mapping, semantic_code)
                rows.append(
                    {
                        "indicator_id": item["id"],
                        "indicator_name": item["name"],
                        "category": item["category"],
                        "family": item["family"],
                        "frequency": item["frequency"],
                        "unit": item.get("unit", ""),
                        "source": item.get("source", ""),
                        "semantic_code": semantic_code,
                        "provider_code": provider_code,
                        "mapping_status": "mapped" if provider_code else "pending",
                        "component_weight": 1,
                        "core": "false",
                        "aggregate": "",
                        "transform": item.get("transform") or "pct_change",
                        "bond_direction": item.get("bond_direction") or -1,
                    }
                )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0])
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"已导出 {len(rows)} 个指标分项：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
