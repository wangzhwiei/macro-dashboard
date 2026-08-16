#!/usr/bin/env python3
"""Validate and normalize destination-market imports from China.

Only exact bilateral series are retained.  `availability_lag_months` is a
conservative real-time rule relative to China's early-next-month customs
release; it is applied by the forecasting model, not baked into raw values.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / "outputs" / "trade-partner-import-ifind-probes.json"
OUTPUT = ROOT / "data" / "trade-model" / "trade_partner_import_factors.json"

EXPECTED = {
    "美国:进口金额:中国:当月同比": {
        "key": "us_imports_from_china_value", "id": "W034560213",
        "name": "美国:进口金额:中国:当月值", "unit": "美元", "source": "国际贸易中心",
        "availability_lag_months": 1, "transform": "yoy_from_monthly_value",
    },
    "日本:进口金额:中国:当月值": {
        "key": "japan_imports_from_china_value", "id": "G019341325",
        "name": "日本:进口金额:中国:当月值", "unit": "日元", "source": "日本财务省",
        "availability_lag_months": 1, "transform": "yoy_from_monthly_value",
    },
    "韩国:自中国进口金额:当月同比": {
        "key": "korea_imports_from_china_yoy", "id": "G022252836",
        "name": "韩国:进口金额:中国:当月同比", "unit": "%", "source": "同花顺金融",
        "availability_lag_months": 0,
    },
    "巴西:自中国进口金额:当月同比": {
        "key": "brazil_imports_from_china_yoy", "id": "G020023687",
        "name": "巴西:进口金额:中国:当月同比", "unit": "%", "source": "巴西海关",
        "availability_lag_months": 0,
    },
    "欧盟27国:自中国进口金额:当月同比": {
        "key": "eu27_imports_from_china_yoy", "id": "G020059950",
        "name": "欧盟27国:进口金额:中国:所有产品:当月同比", "unit": "%", "source": "欧盟统计局",
        "availability_lag_months": 2,
    },
    "中国台湾:进口金额:中国大陆:所有产品:当月同比": {
        "key": "taiwan_imports_from_mainland_value", "id": "G002610107",
        "name": "中国台湾:进口总额:美元:大陆", "unit": "美元", "source": "台湾统计局",
        "availability_lag_months": 1, "transform": "yoy_from_monthly_value",
    },
    "马来西亚:进口金额:中国:所有产品:当月同比": {
        "key": "malaysia_imports_from_china_value", "id": "G019589311",
        "name": "马来西亚:进口金额:中国:当月值", "unit": "马来西亚林吉特", "source": "马来西亚统计局",
        "availability_lag_months": 1, "transform": "yoy_from_monthly_value",
    },
    "泰国:进口金额:中国:当月同比": {
        "key": "thailand_imports_from_china_value", "id": "G019713134",
        "name": "泰国:进口金额:中国:总计:当月值", "unit": "泰铢", "source": "泰国海关",
        "availability_lag_months": 1, "transform": "yoy_from_monthly_value",
    },
}


def extract(response: dict) -> tuple[dict, list]:
    text = response["data"]["result"]["content"][0]["text"]
    payload = json.loads(text)
    datasets = payload.get("data", {}).get("datas", [])
    if not datasets:
        raise RuntimeError("iFinD fuzzy recall returned no dataset")
    info = datasets[0]["data"]
    name = info["columns"][1]
    return info["attrs"][name], info["data"]


def main() -> int:
    probes = json.loads(PROBES.read_text(encoding="utf-8"))
    output = {
        "_meta": {
            "source": "iFinD EDB fuzzy MCP with exact post-response validation",
            "consensusUsed": False,
            "availabilityRule": "lags are conservative relative to the China customs preliminary-release cutoff",
        },
        "series": {},
    }
    for query, expected in EXPECTED.items():
        attrs, rows = extract(probes[query])
        checks = {
            "index_id": expected["id"], "freq": "M", "unit": expected["unit"],
            "data_source": expected["source"],
        }
        for field, wanted in checks.items():
            if attrs.get(field) != wanted:
                raise RuntimeError(f"{query}: {field}={attrs.get(field)!r}, expected {wanted!r}")
        response_name = json.loads(
            probes[query]["data"]["result"]["content"][0]["text"]
        )["data"]["datas"][0]["data"]["columns"][1]
        if response_name != expected["name"]:
            raise RuntimeError(f"{query}: name={response_name!r}, expected {expected['name']!r}")
        output["series"][expected["key"]] = {
            "query": query, "providerId": expected["id"], "name": expected["name"],
            "frequency": "M", "unit": expected["unit"], "source": expected["source"],
            "availabilityLagMonths": expected["availability_lag_months"],
            "transform": expected.get("transform", "identity"), "data": rows,
        }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
