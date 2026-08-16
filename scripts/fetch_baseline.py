#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch iFinD consensus baselines for China export/import YoY."""

from __future__ import annotations

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
    "baseline_export_yoy": {
        "query": "出口金额:预测平均值:当月同比",
        "name": "预测平均值:出口金额(美元计价):当月同比",
        "provider_id": "M005682256",
    },
    "baseline_import_yoy": {
        "query": "进口金额:预测平均值:当月同比",
        "name": "预测平均值:进口金额(美元计价):当月同比",
        "provider_id": "M005682257",
    },
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


def fetch(call, query: str) -> tuple[list[str], list[list], dict]:
    """Return columns, rows, and metadata from the first MCP dataset."""
    response = call("edb", "get_edb_data", {"query": query})
    if not response.get("ok"):
        raise RuntimeError(f"FAIL {query}: {response.get('error')}")
    text = response["data"]["result"]["content"][0]["text"]
    inner = json.loads(text)
    datasets = inner.get("data", {}).get("datas", [])
    if not datasets:
        answer = inner.get("data", {}).get("answer", "")
        raise RuntimeError(f"模糊召回为空: {query} — answer={answer[:100]!r}")
    info = datasets[0]["data"]
    columns = info.get("columns", [])
    rows = info.get("data", [])
    attrs = info.get("attrs", {})
    if len(columns) != 2:
        raise RuntimeError(f"返回列数异常: {query}: {columns!r}")
    return columns, rows, attrs.get(columns[1], {})


def validate(name: str, columns: list[str], rows: list[list], attrs: dict) -> None:
    expected = EXPECTED[name]
    failures = []
    if columns[1] != expected["name"]:
        failures.append(f"name={columns[1]!r}")
    if attrs.get("index_id") != expected["provider_id"]:
        failures.append(f"index_id={attrs.get('index_id')!r}")
    if str(attrs.get("freq", "")).upper() != "M":
        failures.append(f"freq={attrs.get('freq')!r}")
    if attrs.get("unit") != "%":
        failures.append(f"unit={attrs.get('unit')!r}")
    if attrs.get("country") != "中国":
        failures.append(f"country={attrs.get('country')!r}")
    if attrs.get("data_source") != "同花顺金融":
        failures.append(f"source={attrs.get('data_source')!r}")
    if not rows:
        failures.append("rows=empty")
    if failures:
        raise RuntimeError(f"iFinD元数据校验失败 {name}: " + ", ".join(failures))


def save(call, name: str) -> None:
    expected = EXPECTED[name]
    columns, rows, attrs = fetch(call, expected["query"])
    validate(name, columns, rows, attrs)
    output = {
        "_meta": {
            "source": "iFinD EDB",
            "query": expected["query"],
            "columns": columns,
            "attrs": attrs,
            "validatedProviderId": expected["provider_id"],
        },
        "data": rows,
    }
    path = ROOT / "data" / "trade-model" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {name}: {len(rows)}条, columns={columns}, 最新={rows[0]}")


def main() -> int:
    call = load_client()
    save(call, "baseline_export_yoy")
    time.sleep(0.5)
    save(call, "baseline_import_yoy")
    print("全部基准数据已保存到 data/trade-model/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
