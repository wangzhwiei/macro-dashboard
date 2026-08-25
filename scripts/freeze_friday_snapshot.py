#!/usr/bin/env python3
"""Merge fresh observations while freezing already-published Friday signals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FROZEN_INDICATOR_FIELDS = ("signal", "score", "reason")


def merge_weekly_history(
    generated_dates: list[str],
    generated_values: list[object],
    published_dates: list[str],
    published_values: list[object],
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
    merged.update(zip(published_dates, published_values))
    return [merged[day] for day in generated_dates]


def freeze_snapshot(published: dict, generated: dict) -> dict:
    if published["dates"][-1] != generated["dates"][-1]:
        raise RuntimeError(
            "周五快照日期已变化，不能冻结旧信号："
            f"{published['dates'][-1]} -> {generated['dates'][-1]}"
        )

    published_dates = published["dates"]
    generated_dates = generated["dates"]
    published_indicators = {item["id"]: item for item in published["indicators"]}
    for indicator in generated["indicators"]:
        old = published_indicators[indicator["id"]]
        for field in FROZEN_INDICATOR_FIELDS:
            indicator[field] = old[field]
        indicator["history"] = merge_weekly_history(
            generated_dates,
            indicator["history"],
            published_dates,
            old["history"],
        )

    published_categories = {item["id"]: item for item in published["categories"]}
    for category in generated["categories"]:
        old = published_categories[category["id"]]
        weekly_scores = merge_weekly_history(
            generated_dates,
            category["weeklyScores"],
            published_dates,
            old["weeklyScores"],
        )
        category.update(old)
        category["weeklyScores"] = weekly_scores

    overall_weekly = merge_weekly_history(
        generated_dates,
        generated["overall"]["weeklyScores"],
        published_dates,
        published["overall"]["weeklyScores"],
    )
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
