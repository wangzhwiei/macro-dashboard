#!/usr/bin/env python3
"""Build the validated non-consensus factor file used by the anchored trade model."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ROOT / "outputs" / "trade-external-factor-probes.json",
    ROOT / "outputs" / "trade-factor-ifind-probes.json",
]
EXPECTED = {
    "韩国:出口金额:当月同比": ("korea_export_yoy", "G012203163", "韩国:出口金额:当月同比"),
    "越南:出口金额:当月同比": ("vietnam_export_yoy", "W011330012", "越南:商品出口额:当月同比"),
    "制造业PMI:新出口订单": ("pmi_new_export_orders", "M002043805", "制造业PMI:新出口订单"),
    "制造业PMI:进口": ("pmi_imports", "M002043809", "制造业PMI:进口"),
}


def main() -> int:
    probes = {}
    for path in SOURCES:
        probes.update(json.loads(path.read_text(encoding="utf-8")))
    output = {"_meta": {"source": "iFinD EDB", "consensusUsed": False}, "series": {}}
    for query, (key, provider_id, exact_name) in EXPECTED.items():
        response = probes[query]
        text = response["data"]["result"]["content"][0]["text"]
        payload = json.loads(text)
        dataset = payload["data"]["datas"][0]["data"]
        columns = dataset["columns"]
        attrs = dataset["attrs"][columns[1]]
        checks = {
            "index_id": provider_id, "freq": "M", "unit": "%",
        }
        for field, expected in checks.items():
            if attrs.get(field) != expected:
                raise RuntimeError(f"{query}: {field}={attrs.get(field)!r}, expected {expected!r}")
        if columns[1] != exact_name:
            raise RuntimeError(f"{query}: name={columns[1]!r}, expected {exact_name!r}")
        output["series"][key] = {
            "query": query, "providerId": provider_id, "name": exact_name,
            "frequency": "M", "unit": "%", "country": attrs.get("country"),
            "source": attrs.get("data_source"), "data": dataset["data"],
        }
    path = ROOT / "data" / "trade-model" / "trade_anchor_factors.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
