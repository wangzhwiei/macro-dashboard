#!/usr/bin/env python3
"""Merge fresh observations while freezing the latest published Friday signals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FROZEN_INDICATOR_FIELDS = ("signal", "score", "reason", "history")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    published = json.loads(args.published.read_text(encoding="utf-8"))
    generated = json.loads(args.generated.read_text(encoding="utf-8"))

    if published["dates"][-1] != generated["dates"][-1]:
        raise RuntimeError(
            "周五快照日期已变化，不能冻结旧信号："
            f"{published['dates'][-1]} -> {generated['dates'][-1]}"
        )

    published_indicators = {item["id"]: item for item in published["indicators"]}
    for indicator in generated["indicators"]:
        old = published_indicators[indicator["id"]]
        for field in FROZEN_INDICATOR_FIELDS:
            indicator[field] = old[field]

    generated["dates"] = published["dates"]
    generated["categories"] = published["categories"]
    generated["overall"] = published["overall"]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(generated, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
