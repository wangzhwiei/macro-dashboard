#!/usr/bin/env python3
"""Merge the frozen credit models into an already validated forecast payload."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from credit_forecast_model import augment_forecast_payload


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "docs" / "data" / "forecasts.json")
    parser.add_argument("--credit", type=Path, default=ROOT / "data" / "credit-model" / "forecast_results.json")
    parser.add_argument("--output", type=Path, default=ROOT / "public" / "data" / "forecasts.json")
    args = parser.parse_args()
    payload = json.loads(args.base.read_text(encoding="utf-8-sig"))
    payload = augment_forecast_payload(payload, args.credit)
    payload["generatedAt"] = datetime.now().astimezone().isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"已合并固定版信用预测：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
