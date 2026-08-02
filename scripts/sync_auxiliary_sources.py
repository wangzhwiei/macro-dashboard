#!/usr/bin/env python3
"""Synchronize auxiliary source/frequency fields with authoritative routing metadata."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cjhx = json.loads(
        (ROOT / "config" / "cjhx-series-map.json").read_text(encoding="utf-8")
    )
    with (ROOT / "config" / "ifind-series.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        ifind = {row["semantic_code"]: row for row in csv.DictReader(handle)}

    path = ROOT / "config" / "auxiliary-indicators.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for row in rows:
        code = row["code"]
        if code in cjhx:
            row["source"] = "CJHX"
        elif code in ifind:
            row["source"] = "iFinD"
            row["frequency"] = "daily" if ifind[code]["frequency"] == "D" else "weekly"
        else:
            raise RuntimeError(f"辅助指标未配置数据源：{code}")

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"已同步{len(rows)}个辅助指标的数据源与频率：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
