#!/usr/bin/env python3
"""Check that intramonth nowcast endpoints naturally converge to locked monthly values."""

import json
from pathlib import Path

import pandas as pd

from forecast_realtime import build_daily_nowcasts

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


source = read(ROOT / "data" / "forecast-model" / "model_inputs.json")
live = read(ROOT / "data" / "forecast-model" / "live_inputs.json")
locked = read(ROOT / "data" / "forecast-model" / "locked_nowcasts.json")["2026-07-31"]
result = build_daily_nowcasts(source, live, locked, pd.Timestamp("2026-07-31"))
print(json.dumps({key: rows[-1]["value"] for key, rows in result.items()}, ensure_ascii=False))
