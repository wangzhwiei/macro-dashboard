#!/usr/bin/env python3
"""Supplement 2026-08 official releases when the iFinD quota is exhausted.

The values below are taken from the 2026-09-15 NBS release and the
2026-09-14 PBOC release.  Upserts are idempotent, so this can safely run in
the daily pipeline until iFinD itself contains the same observations.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-08-31"
NBS_URL = "https://www.stats.gov.cn/sj/zxfb/202609/t20260915_1965307.html"
PBOC_NOTE = "中国人民银行2026年8月金融统计与社会融资规模发布（2026-09-14）"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upsert(rows: list[list], value: float, *, descending: bool = False) -> None:
    rows[:] = [row for row in rows if row[0] != DAY]
    rows.append([DAY, value])
    rows.sort(key=lambda row: row[0], reverse=descending)


def mark(payload: dict, source: str, keys: list[str]) -> None:
    payload.setdefault("officialSupplements", {})[DAY] = {
        "source": source,
        "keys": keys,
        "recordedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "reason": "iFinD quota exhausted before the official release was mirrored",
    }


def main() -> int:
    retail_path = ROOT / "data" / "forecast-model" / "research_retail_ifind.json"
    retail = load(retail_path)
    upsert(retail["series"]["actual_retail_yoy"]["records"], 0.4)
    mark(retail, NBS_URL, ["actual_retail_yoy"])
    save(retail_path, retail)

    industrial_path = ROOT / "data" / "industrial-value-model" / "targets_consensus.json"
    industrial = load(industrial_path)
    for key, value in {"actualMonthly": 5.2, "actualYtd": 5.3, "actualMomSa": 0.54}.items():
        upsert(industrial["series"][key]["observations"], value, descending=True)
    mark(industrial, NBS_URL, ["actualMonthly", "actualYtd", "actualMomSa"])
    save(industrial_path, industrial)

    investment_path = ROOT / "data" / "investment-model" / "source_data.json"
    investment = load(investment_path)
    investment_values = {
        "fixed_asset_investment_ytd_amount": 29_309_200_000_000.0,
        "fixed_asset_investment_ytd_yoy": -7.2,
        "manufacturing_investment_ytd_yoy": -2.3,
        "infrastructure_investment_ytd_yoy": -4.0,
        "real_estate_investment_ytd_yoy": -19.9,
        "private_investment_ytd_yoy": -10.1,
    }
    for key, value in investment_values.items():
        upsert(investment["series"][key]["observations"], value, descending=True)
    mark(investment, NBS_URL, list(investment_values))
    save(investment_path, investment)

    credit_path = ROOT / "data" / "credit-model" / "source_data.json"
    credit = load(credit_path)
    credit_values = {
        "m2_yoy": 7.5,
        "m2_level": 356_810_000_000_000.0,
        "new_rmb_loans": 60_000_000_000.0,
        "social_financing": 1_657_700_000_000.0,
    }
    for key, value in credit_values.items():
        upsert(credit["series"][key]["observations"], value, descending=True)
    mark(credit, PBOC_NOTE, list(credit_values))
    save(credit_path, credit)

    print("已补录2026年8月国家统计局与人民银行正式值")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
