#!/usr/bin/env python3
"""Bundle the dashboard high-frequency series and the locked iFinD CRB snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_IDS = {
    "vegetable_price",
    "pork_price",
    "nanhua_industry",
    "brent",
    "qhd_coal_price",
    "rebar_price",
    "copper_price",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def parse_ifind_crb(payload: dict[str, Any]) -> list[list[Any]]:
    text = payload["data"]["result"]["content"][0]["text"]
    inner = json.loads(text)
    records = inner["data"]["datas"][0]["data"]["data"]
    cleaned: list[list[Any]] = []
    for row in records:
        if isinstance(row, dict):
            date = row.get("date") or row.get("time")
            value = row.get("value")
            if value is None:
                values = [value for key, value in row.items() if key not in {"date", "time"}]
                value = values[0] if values else None
        else:
            date, value = row[0], row[1]
        if date is not None and value is not None:
            cleaned.append([str(date)[:10], float(value)])
    return sorted(cleaned, key=lambda row: row[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", type=Path, default=ROOT / "public" / "data" / "dashboard.json")
    parser.add_argument("--crb-raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "forecast-model" / "live_inputs.json")
    args = parser.parse_args()

    dashboard = read_json(args.dashboard)
    selected = {
        item["id"]: {
            "name": item.get("name"),
            "frequency": item.get("frequency"),
            "unit": item.get("unit"),
            "source": item.get("source"),
            "series": [[row["date"], row["value"]] for row in item.get("series", [])],
        }
        for item in dashboard.get("indicators", [])
        if item.get("id") in DASHBOARD_IDS
    }
    missing = DASHBOARD_IDS.difference(selected)
    if missing:
        raise RuntimeError(f"dashboard 缺少实时预测序列：{sorted(missing)}")

    output = {
        "schemaVersion": 1,
        "dashboardGeneratedAt": dashboard.get("generatedAt"),
        "dashboard": selected,
        "ifindCrb": {
            "id": "S004370158",
            "name": "RJ/CRB商品价格指数",
            "frequency": "日频",
            "unit": "指数",
            "source": "iFinD EDB（锁定快照）",
            "series": parse_ifind_crb(read_json(args.crb_raw)),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入实时预测输入：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
