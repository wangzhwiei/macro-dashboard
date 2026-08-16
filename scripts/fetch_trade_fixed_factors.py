#!/usr/bin/env python3
"""Refresh the four fixed monthly trade factors through fuzzy iFinD EDB search."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ["IFIND_SKILL_DIR"])
ANCHOR_PATH = ROOT / "data" / "trade-model" / "trade_anchor_factors.json"
PARTNER_PATH = ROOT / "data" / "trade-model" / "trade_partner_import_factors.json"

SPECS = (
    {
        "file": "partner", "key": "korea_imports_from_china_yoy",
        "query": "韩国:自中国进口金额:当月同比", "id": "G022252836",
        "name": "韩国:进口金额:中国:当月同比", "unit": "%", "source": "同花顺金融",
    },
    {
        "file": "partner", "key": "taiwan_imports_from_mainland_value",
        "query": "中国台湾:进口金额:中国大陆:所有产品:当月同比", "id": "G002610107",
        "name": "中国台湾:进口总额:美元:大陆", "unit": "美元", "source": "台湾统计局",
    },
    {
        "file": "partner", "key": "thailand_imports_from_china_value",
        "query": "泰国:进口金额:中国:当月同比", "id": "G019713134",
        "name": "泰国:进口金额:中国:总计:当月值", "unit": "泰铢", "source": "泰国海关",
    },
    {
        "file": "anchor", "key": "korea_export_yoy",
        "query": "韩国:出口金额:当月同比", "id": "G012203163",
        "name": "韩国:出口金额:当月同比", "unit": "%", "source": "同花顺金融",
    },
)


def load_client():
    sys.path.insert(0, str(SKILL))
    previous = Path.cwd()
    os.chdir(SKILL)
    try:
        from call import call
    finally:
        os.chdir(previous)
    return call


def fetch(call, spec: dict) -> tuple[list[list], dict]:
    response = None
    for attempt in range(1, 4):
        try:
            response = call("edb", "get_edb_data", {"query": spec["query"]})
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1.5 * attempt)
    if not response or not response.get("ok"):
        raise RuntimeError(str((response or {}).get("error") or "iFinD call failed"))
    payload = json.loads(response["data"]["result"]["content"][0]["text"])
    datasets = payload.get("data", {}).get("datas", [])
    if not datasets:
        raise RuntimeError("模糊召回为空")
    info = datasets[0]["data"]
    columns = info.get("columns", [])
    if len(columns) != 2:
        raise RuntimeError(f"返回列异常：{columns}")
    attrs = info.get("attrs", {}).get(columns[1], {})
    actual = {
        "id": attrs.get("index_id"), "name": columns[1],
        "freq": attrs.get("freq"), "unit": attrs.get("unit"),
        "source": attrs.get("data_source"),
    }
    expected = {
        "id": spec["id"], "name": spec["name"], "freq": "M",
        "unit": spec["unit"], "source": spec["source"],
    }
    if actual != expected:
        raise RuntimeError(f"固定字段校验失败：expected={expected}, actual={actual}")
    rows = info.get("data", [])
    if not rows:
        raise RuntimeError("返回数据为空")
    return rows, attrs


def main() -> int:
    call = load_client()
    anchor = json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))
    partner = json.loads(PARTNER_PATH.read_text(encoding="utf-8"))
    payloads = {"anchor": anchor, "partner": partner}
    errors = []
    for index, spec in enumerate(SPECS, 1):
        try:
            rows, attrs = fetch(call, spec)
            item = payloads[spec["file"]]["series"][spec["key"]]
            item["data"] = rows
            item["providerId"] = spec["id"]
            item["name"] = spec["name"]
            item["frequency"] = "M"
            item["unit"] = spec["unit"]
            item["source"] = spec["source"]
            item["query"] = spec["query"]
            print(f"[OK] {spec['key']}: latest={rows[0]}", flush=True)
        except Exception as error:
            errors.append(f"{spec['key']}: {error}")
        if index < len(SPECS):
            time.sleep(.5)
    if errors:
        raise RuntimeError("；".join(errors))
    ANCHOR_PATH.write_text(json.dumps(anchor, ensure_ascii=False, indent=2), encoding="utf-8")
    PARTNER_PATH.write_text(json.dumps(partner, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
