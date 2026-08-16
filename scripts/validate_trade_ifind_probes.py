#!/usr/bin/env python3
"""Summarize and strictly validate field-based iFinD MCP candidates."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "trade-ifind-field-probes.json"
OUTPUT = ROOT / "outputs" / "trade-ifind-field-validation.json"

EXPECTED = {
    "consensus_imports": {"id": "M005682257", "name": "预测平均值:进口金额(美元计价):当月同比", "source": "同花顺金融"},
    "consensus_exports": {"id": "M005682256", "name": "预测平均值:出口金额(美元计价):当月同比", "source": "同花顺金融"},
    "actual_exports": {"id": "M002888330", "name": "出口总额(美元计价):当月同比", "source": "海关总署"},
}


def inner(response: dict) -> dict:
    try:
        text = response["data"]["result"]["content"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return {}


def classify(query: str) -> str:
    consensus = any(token in query for token in ("预测平均值", "一致预期", "市场预测", "预测均值"))
    direction = "imports" if "进口" in query else "exports"
    return f"consensus_{direction}" if consensus else f"actual_{direction}"


def main() -> int:
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    report = {"queries": [], "accepted": {}}
    for query, response in raw.items():
        parsed = inner(response)
        datasets = parsed.get("data", {}).get("datas", [])
        item = {"query": query, "requested": classify(query), "candidates": []}
        for dataset in datasets:
            data = dataset.get("data", {})
            columns = data.get("columns", [])
            attrs = data.get("attrs", {})
            for name in columns[1:]:
                meta = attrs.get(name, {})
                candidate = {
                    "name": name, "providerId": meta.get("index_id"), "frequency": meta.get("freq"),
                    "unit": meta.get("unit"), "source": meta.get("data_source"), "country": meta.get("country"),
                    "rows": len(data.get("data", [])),
                }
                requested = item["requested"]
                expected = EXPECTED.get(requested)
                candidate["accepted"] = bool(expected and
                    candidate["providerId"] == expected["id"] and candidate["name"] == expected["name"] and
                    str(candidate["frequency"]).upper() == "M" and candidate["unit"] == "%" and
                    candidate["source"] == expected["source"] and candidate["country"] == "中国")
                if candidate["accepted"]:
                    report["accepted"][requested] = candidate
                item["candidates"].append(candidate)
        report["queries"].append(item)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
