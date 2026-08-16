#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch validated iFinD/GACC China export and import actual YoY series."""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = Path(os.environ.get(
    "IFIND_SKILL_DIR",
    "/home/wangzhiwei202307/.openclaw/workspace/skills/ifind-finance-data/ifind-finance-data",
))
EXPECTED = {
    "exports": {"query": "出口总额(美元计价):当月同比", "name": "出口总额(美元计价):当月同比", "id": "M002888330"},
    "imports": {"query": "进口总额(美元计价):当月同比", "name": "进口总额(美元计价):当月同比", "id": "M002888203"},
}


def load_client():
    sys.path.insert(0, str(SKILL_DIR))
    previous = Path.cwd()
    os.chdir(SKILL_DIR)
    try:
        from call import call
    finally:
        os.chdir(previous)
    return call


def fetch(call, spec: dict) -> tuple[list[list], dict]:
    response = call("edb", "get_edb_data", {"query": spec["query"]})
    if not response.get("ok"):
        raise RuntimeError(response.get("error"))
    inner = json.loads(response["data"]["result"]["content"][0]["text"])
    datasets = inner.get("data", {}).get("datas", [])
    if not datasets:
        raise RuntimeError(f"模糊召回为空: {spec['query']}")
    info = datasets[0]["data"]
    columns, attrs = info.get("columns", []), info.get("attrs", {})
    meta = attrs.get(columns[1], {}) if len(columns) == 2 else {}
    checks = {
        "name": columns[1] if len(columns) == 2 else None,
        "id": meta.get("index_id"), "freq": meta.get("freq"), "unit": meta.get("unit"),
        "country": meta.get("country"), "source": meta.get("data_source"),
    }
    expected = {"name": spec["name"], "id": spec["id"], "freq": "M", "unit": "%", "country": "中国", "source": "海关总署"}
    if checks != expected:
        raise RuntimeError(f"实际值元数据校验失败: expected={expected}, actual={checks}")
    return info.get("data", []), meta


def main() -> int:
    call = load_client()
    series = {}
    metadata = {}
    for index, (key, spec) in enumerate(EXPECTED.items()):
        if index:
            time.sleep(0.5)
        rows, meta = fetch(call, spec)
        series[key] = {row[0]: row[1] for row in rows}
        metadata[key] = {"query": spec["query"], "attrs": meta, "rows": len(rows), "latest": rows[0]}
        print(f"[OK] {key}: {len(rows)}条, 最新={rows[0]}")
    dates = sorted(set(series["exports"]) | set(series["imports"]))
    out = ROOT / "data" / "trade-model"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "trade_targets_ifind.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "exports_yoy", "imports_yoy"])
        for date in dates:
            writer.writerow([date, series["exports"].get(date), series["imports"].get(date)])
    (out / "trade_targets_ifind.meta.json").write_text(
        json.dumps({"source": "iFinD EDB / 海关总署", "series": metadata}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
