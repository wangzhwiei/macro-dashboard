#!/usr/bin/env python3
"""Merge the frozen fixed-asset-investment model into forecast page data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from investment_level_forecast_model import augment_forecast_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "public" / "data" / "forecasts.json")
    parser.add_argument("--investment", type=Path, default=ROOT / "data" / "investment-model" / "forecast_results.json")
    parser.add_argument("--output", type=Path, default=ROOT / "public" / "data" / "forecasts.json")
    args = parser.parse_args()
    payload = json.loads(args.base.read_text(encoding="utf-8-sig"))
    payload = augment_forecast_payload(payload, args.investment)
    payload["generatedAt"] = datetime.now().astimezone().isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"已合并冻结版固定资产投资预测：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
