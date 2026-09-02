#!/usr/bin/env python3
"""Merge fresh observations while freezing already-published Friday signals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FROZEN_INDICATOR_FIELDS = (
    "signal",
    "score",
    "reason",
    "scoreAsOf",
    "scoreObservationAt",
    "scoreChange",
    "scoreScale",
)
FROZEN_WEEKLY_FIELDS = (
    "history",
    "scoreChanges",
    "scoreScales",
    "scoreObservationDates",
)


def merge_weekly_history(
    generated_dates: list[str],
    generated_values: list[object],
    published_dates: list[str],
    published_values: list[object],
    freeze_dates: set[str] | None = None,
) -> list[object]:
    """Freeze published dates without truncating a longer generated history."""
    if len(generated_dates) != len(generated_values):
        raise RuntimeError("生成数据的周度日期与数值长度不一致")
    if len(published_dates) != len(published_values):
        raise RuntimeError("已发布数据的周度日期与数值长度不一致")
    merged = dict(zip(generated_dates, generated_values))
    missing = [day for day in published_dates if day not in merged]
    if missing:
        raise RuntimeError(f"生成数据缺少已发布周五日期：{missing[:3]}")
    frozen = freeze_dates if freeze_dates is not None else set(published_dates)
    merged.update(
        (day, value)
        for day, value in zip(published_dates, published_values)
        if day in frozen
    )
    return [merged[day] for day in generated_dates]


def trusted_latest_indicator(indicator: dict, snapshot_day: str) -> bool:
    required = set(FROZEN_INDICATOR_FIELDS) | set(FROZEN_WEEKLY_FIELDS)
    if not required.issubset(indicator):
        return False
    history = indicator.get("history", [])
    if (
        not history
        or indicator.get("scoreAsOf") != snapshot_day
        or any(len(indicator[field]) != len(history) for field in FROZEN_WEEKLY_FIELDS)
    ):
        return False
    return (
        abs(float(indicator["score"]) - float(history[-1])) <= 0.11
        and abs(float(indicator["scoreChange"]) - float(indicator["scoreChanges"][-1])) <= 1e-7
        and abs(float(indicator["scoreScale"]) - float(indicator["scoreScales"][-1])) <= 1e-7
        and indicator["scoreObservationAt"] == indicator["scoreObservationDates"][-1]
    )


def freeze_snapshot(published: dict, generated: dict) -> dict:
    if published["dates"][-1] > generated["dates"][-1]:
        raise RuntimeError(
            "生成数据的周五快照早于已发布快照："
            f"{published['dates'][-1]} -> {generated['dates'][-1]}"
        )

    published_dates = published["dates"]
    generated_dates = generated["dates"]
    published_indicators = {item["id"]: item for item in published["indicators"]}
    same_snapshot = published_dates[-1] == generated_dates[-1]
    if same_snapshot:
        generated_ids = {item["id"] for item in generated["indicators"]}
        generated["indicators"].extend(
            item for item in published["indicators"] if item["id"] not in generated_ids
        )
    freeze_latest = same_snapshot and all(
        trusted_latest_indicator(item, published_dates[-1])
        for item in published_indicators.values()
    )
    freeze_dates = set(published_dates)
    if same_snapshot and not freeze_latest:
        # Legacy or internally inconsistent payloads cannot be allowed to
        # overwrite a correctly regenerated latest Friday. Older Friday
        # snapshots remain frozen.
        freeze_dates.discard(published_dates[-1])

    for indicator in generated["indicators"]:
        old = published_indicators[indicator["id"]]
        if freeze_latest:
            for field in FROZEN_INDICATOR_FIELDS:
                indicator[field] = old[field]
        for field in FROZEN_WEEKLY_FIELDS:
            old_values = old.get(field)
            if old_values is None:
                continue
            indicator[field] = merge_weekly_history(
                generated_dates,
                indicator[field],
                published_dates,
                old_values,
                freeze_dates,
            )

    published_categories = {item["id"]: item for item in published["categories"]}
    for category in generated["categories"]:
        old = published_categories[category["id"]]
        weekly_scores = merge_weekly_history(
            generated_dates,
            category["weeklyScores"],
            published_dates,
            old["weeklyScores"],
            freeze_dates,
        )
        if freeze_latest:
            category.update(old)
        category["weeklyScores"] = weekly_scores

    overall_weekly = merge_weekly_history(
        generated_dates,
        generated["overall"]["weeklyScores"],
        published_dates,
        published["overall"]["weeklyScores"],
        freeze_dates,
    )
    if freeze_latest:
        generated["overall"].update(published["overall"])
    generated["overall"]["weeklyScores"] = overall_weekly
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    published = json.loads(args.published.read_text(encoding="utf-8"))
    generated = json.loads(args.generated.read_text(encoding="utf-8"))
    generated = freeze_snapshot(published, generated)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(generated, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
