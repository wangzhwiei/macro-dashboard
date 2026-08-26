#!/usr/bin/env python3
"""Compare published Friday strengths with a no-future recomputation."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def audit(published: dict, recomputed: dict, tolerance: float = 0.11) -> dict:
    if published["dates"] != recomputed["dates"]:
        raise RuntimeError("两份数据的周五日期轴不一致")
    dates = published["dates"]
    new_by_id = {item["id"]: item for item in recomputed["indicators"]}
    differences: list[dict] = []
    by_indicator: dict[str, list[float]] = defaultdict(list)
    by_date: Counter[str] = Counter()

    for old in published["indicators"]:
        new = new_by_id[old["id"]]
        for day, old_score, new_score in zip(dates, old["history"], new["history"]):
            absolute_difference = abs(float(old_score) - float(new_score))
            if absolute_difference <= tolerance:
                continue
            by_indicator[old["id"]].append(absolute_difference)
            by_date[day] += 1
            differences.append(
                {
                    "date": day,
                    "id": old["id"],
                    "name": old["name"],
                    "published": old_score,
                    "recomputed": new_score,
                    "absoluteDifference": round(absolute_difference, 1),
                    "directionReversed": float(old_score) * float(new_score) < 0,
                }
            )

    category_old = {item["id"]: item for item in published["categories"]}
    category_new = {item["id"]: item for item in recomputed["categories"]}
    category_mismatches = sum(
        abs(float(old_score) - float(new_score)) > tolerance
        for category_id in category_old
        for old_score, new_score in zip(
            category_old[category_id]["weeklyScores"],
            category_new[category_id]["weeklyScores"],
        )
    )
    overall_mismatches = sum(
        abs(float(old_score) - float(new_score)) > tolerance
        for old_score, new_score in zip(
            published["overall"]["weeklyScores"],
            recomputed["overall"]["weeklyScores"],
        )
    )
    total_cells = len(dates) * len(published["indicators"])
    return {
        "summary": {
            "indicatorWeekCells": total_cells,
            "mismatchCells": len(differences),
            "mismatchRate": round(len(differences) / max(1, total_cells), 6),
            "affectedIndicators": len(by_indicator),
            "affectedDates": len(by_date),
            "directionReversals": sum(item["directionReversed"] for item in differences),
            "medianAbsoluteDifference": round(
                statistics.median(item["absoluteDifference"] for item in differences), 1
            ) if differences else 0,
            "categoryMismatchCells": category_mismatches,
            "overallMismatchWeeks": overall_mismatches,
        },
        "byIndicator": [
            {
                "id": indicator_id,
                "mismatchWeeks": len(values),
                "meanAbsoluteDifference": round(statistics.fmean(values), 1),
                "maxAbsoluteDifference": round(max(values), 1),
            }
            for indicator_id, values in sorted(
                by_indicator.items(), key=lambda item: (-len(item[1]), item[0])
            )
        ],
        "byDate": [
            {"date": day, "mismatchIndicators": count}
            for day, count in by_date.most_common()
        ],
        "largestDifferences": sorted(
            differences,
            key=lambda item: (-item["absoluteDifference"], item["date"], item["id"]),
        )[:100],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--recomputed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(
        json.loads(args.published.read_text(encoding="utf-8")),
        json.loads(args.recomputed.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
