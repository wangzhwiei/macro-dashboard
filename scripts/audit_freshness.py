#!/usr/bin/env python3
"""Export configured frequency, observed cadence and freshness for every indicator."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime
from pathlib import Path

from validate_dashboard import (
    DEFAULT_AUXILIARY,
    DEFAULT_CONFIG,
    DEFAULT_DATA,
    cadence_issue,
    load_definitions,
    median_gap_days,
    stale_age_days,
    stale_tolerance_days,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs" / "frequency-freshness-audit.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--auxiliary", type=Path, default=DEFAULT_AUXILIARY)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    _, definitions = load_definitions(args.config, args.auxiliary)
    by_id = {item["id"]: item for item in definitions}
    dashboard = json.loads(args.data.read_text(encoding="utf-8"))
    generated_day = datetime.fromisoformat(
        dashboard["generatedAt"].replace("Z", "+00:00")
    ).date()

    rows: list[dict[str, object]] = []
    for indicator in dashboard.get("indicators", []):
        definition = by_id[indicator["id"]]
        series = indicator.get("series", [])
        updated_day = date.fromisoformat(indicator["updatedAt"])
        stale_days = stale_age_days(definition, updated_day, generated_day)
        tolerance = stale_tolerance_days(definition)
        issue = cadence_issue(definition["frequency"], series)
        rows.append(
            {
                "indicator_id": indicator["id"],
                "name": indicator["name"],
                "source": indicator["source"],
                "configured_frequency": definition["frequency"],
                "page_frequency": indicator["frequency"],
                "updated_at": indicator["updatedAt"],
                "generated_date": generated_day.isoformat(),
                "stale_days": stale_days,
                "tolerance_days": tolerance,
                "median_gap_days": median_gap_days(series),
                "cadence_status": "warning" if issue else "ok",
                "cadence_issue": issue or "",
                "freshness_status": "stale" if stale_days > tolerance else "fresh",
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "output": str(args.output),
        "indicators": len(rows),
        "stale": sum(row["freshness_status"] == "stale" for row in rows),
        "cadence_issues": sum(row["cadence_status"] == "warning" for row in rows),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
