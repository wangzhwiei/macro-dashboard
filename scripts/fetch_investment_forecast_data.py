#!/usr/bin/env python3
"""Fetch fixed-ID investment target, components, and isolated consensus data."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "investment-model" / "source_data.json"

SERIES = {
    "fixed_asset_investment_ytd_amount": {
        "providerId": "M001620537",
        "query": "固定资产投资(不含农户)完成额:累计值（201001-202608）",
        "role": "target_level",
    },
    "fixed_asset_investment_ytd_yoy": {
        "providerId": "M001620575",
        "query": "固定资产投资(不含农户):累计同比（201001-202608）",
        "role": "target",
    },
    "manufacturing_investment_ytd_yoy": {
        "providerId": "M003811042",
        "query": "固定资产投资(不含农户)完成额:制造业:累计同比（201001-202608）",
        "role": "lagged_component_only",
    },
    "infrastructure_investment_ytd_yoy": {
        "providerId": "M004385772",
        "query": "固定资产投资(不含农户)完成额:基础设施建设(不含电力):累计同比（201001-202608）",
        "role": "lagged_component_only",
    },
    "infrastructure_investment_ytd_amount": {
        "providerId": "M004385771",
        "query": "固定资产投资(不含农户)完成额:基础设施建设投资:累计值（201001-202608）",
        "role": "lagged_component_level_only",
    },
    "real_estate_investment_ytd_yoy": {
        "providerId": "S000047961",
        "query": "房地产开发投资完成额:累计同比（201001-202608）",
        "role": "lagged_component_only",
    },
    "real_estate_investment_ytd_amount": {
        "providerId": "M001620723",
        "query": "房地产开发投资完成额:累计值（201001-202608）",
        "role": "lagged_component_level_only",
    },
    "private_investment_ytd_yoy": {
        "providerId": "M002965395",
        "query": "民间固定资产投资完成额:累计同比（201203-202608）",
        "role": "lagged_component_only",
    },
    "fixed_asset_investment_consensus": {
        "providerId": "M005682259",
        "query": "经济数据预测:固定资产投资:预测平均值（202001-202608）",
        "role": "comparison_only",
    },
}


def find_call(explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("IFIND_SKILL_DIR"):
        candidates.append(Path(os.environ["IFIND_SKILL_DIR"]) / "call.py")
    candidates.extend(Path.home().glob("Documents/*/skills/ifind-finance-data/call.py"))
    for path in candidates:
        if path.exists():
            return path
    raise RuntimeError("cannot locate iFinD call.py; pass --call-py or set IFIND_SKILL_DIR")


def load_call(path: Path):
    spec = importlib.util.spec_from_file_location("investment_ifind_call", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load iFinD client: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.call


def parse(response: dict[str, Any], expected_id: str) -> dict[str, Any]:
    if not response.get("ok"):
        raise RuntimeError(str(response.get("error") or "iFinD request failed"))
    content = response.get("data", {}).get("result", {}).get("content", [])
    if not content:
        raise RuntimeError("empty iFinD response")
    payload = json.loads(content[0].get("text", "{}"))
    matches = []
    observed = []
    for item in payload.get("data", {}).get("datas", []):
        table = item.get("data", {})
        for column, metadata in table.get("attrs", {}).items():
            provider_id = metadata.get("index_id")
            if provider_id:
                observed.append(provider_id)
            if provider_id == expected_id:
                matches.append((column, metadata, table.get("data", [])))
    if len(matches) != 1:
        raise RuntimeError(f"expected {expected_id}, observed {sorted(set(observed))}")
    column, metadata, observations = matches[0]
    return {
        "providerId": expected_id,
        "name": column,
        "unit": metadata.get("unit"),
        "frequency": metadata.get("freq"),
        "source": metadata.get("data_source"),
        "startTime": metadata.get("start_time"),
        "endTime": metadata.get("end_time"),
        "observations": observations,
    }


def fetch(call_py: Path, checkpoint: Path | None = None, resume: bool = False) -> dict[str, Any]:
    call = load_call(call_py)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "retrievedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "consensusPolicy": "comparison_only; excluded from features, training, tuning, candidate selection and weights",
        "releasePolicy": "structural investment components are same-release data and may enter forecasts only with lag >= 1 month",
        "series": {},
    }
    if resume and checkpoint and checkpoint.exists():
        previous = json.loads(checkpoint.read_text(encoding="utf-8-sig"))
        for key, value in previous.get("series", {}).items():
            if key in SERIES and value.get("providerId") == SERIES[key]["providerId"]:
                result["series"][key] = value
    for key, config in SERIES.items():
        if key in result["series"]:
            continue
        errors = []
        for attempt in range(3):
            try:
                parsed = parse(call("edb", "get_edb_data", {"query": config["query"]}), config["providerId"])
                parsed["role"] = config["role"]
                result["series"][key] = parsed
                if checkpoint:
                    checkpoint.parent.mkdir(parents=True, exist_ok=True)
                    checkpoint.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                break
            except Exception as error:
                errors.append(str(error))
                time.sleep(attempt + 1)
        if key not in result["series"]:
            raise RuntimeError(f"failed to fetch {key}/{config['providerId']}: {' | '.join(errors)}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--call-py", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    payload = fetch(find_call(args.call_py), args.output, args.resume)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: len(value["observations"]) for key, value in payload["series"].items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
