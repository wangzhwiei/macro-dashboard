#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch validated iFinD/GACC China export and import actual YoY series."""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import date, timedelta
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
    try:
        from scripts.ifind_request_cache import wrap_ifind_call
    except ModuleNotFoundError:
        from ifind_request_cache import wrap_ifind_call
    return wrap_ifind_call(call)


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
    path = ROOT / 'data/trade-model/trade_targets_ifind.csv'
    previous = list(csv.DictReader(path.open(encoding='utf-8-sig'))) if path.exists() else []
    for index, (key, spec) in enumerate(EXPECTED.items()):
        if index:
            time.sleep(0.5)
        start = (date.fromisoformat(max(r['date'][:10] for r in previous)) - timedelta(days=45)).strftime('%Y%m%d') if previous else '20200101'
        query = (f"中国:{spec['name']}（{start}-{date.today():%Y%m%d}），唯一编码{spec['id']}，月频，海关总署，非出口总值。" if key == 'exports'
                 else f"{spec['name']}，指标ID {spec['id']}（{start}-{date.today():%Y%m%d}）")
        request = dict(spec, query=query)
        rows, meta = fetch(call, request)
        series[key] = {r['date']: float(r[key+'_yoy']) for r in previous if r.get(key+'_yoy')}
        series[key].update({row[0]: row[1] for row in rows})
        latest = max(rows, key=lambda r: r[0])
        metadata[key] = {"query": spec["query"], "attrs": meta, "rows": len(series[key]), "latest": latest}
        print(f"[OK] {key}: {len(rows)}条, 最新={latest}")
    dates = sorted(set(series["exports"]) | set(series["imports"]))
    out = ROOT / "data" / "trade-model"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "trade_targets_ifind.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "exports_yoy", "imports_yoy"])
        for observed_day in dates:
            writer.writerow([observed_day, series["exports"].get(observed_day), series["imports"].get(observed_day)])
    (out / "trade_targets_ifind.meta.json").write_text(
        json.dumps({"source": "iFinD EDB / 海关总署", "series": metadata}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
