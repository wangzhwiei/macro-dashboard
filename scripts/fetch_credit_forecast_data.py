#!/usr/bin/env python3
"""Fetch fixed iFinD credit targets and consensus series with ID validation."""

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
DEFAULT_OUTPUT = ROOT / "data" / "credit-model" / "source_data.json"

SERIES = {
    "m2_yoy": {
        "providerId": "M001625222",
        "query": "M2(货币和准货币):同比（201001-202608）",
        "role": "target",
    },
    "m2_level": {
        "providerId": "M001625221",
        "query": "M2(货币和准货币):余额（201001-202608）",
        "role": "target_level",
    },
    "new_rmb_loans": {
        "providerId": "M002859879",
        "query": "金融机构:新增人民币贷款:当月值（201001-202608）",
        "role": "target",
    },
    "social_financing": {
        "providerId": "M004891015",
        "query": "中国:社会融资规模增量:当月值（201001-202608）",
        "role": "target",
    },
    "tsf_rmb_loans": {
        "providerId": "M002917567",
        "query": "社会融资规模增量:人民币贷款:当月值（201001-202608，指标ID M002917567）",
        "role": "component",
    },
    "tsf_foreign_currency_loans": {
        "providerId": "M036012505",
        "query": "社会融资规模增量:对实体经济发放的外币贷款折合人民币:当月值（201001-202608）",
        "role": "component",
    },
    "tsf_entrusted_loans": {
        "providerId": "M002917569",
        "query": "社会融资规模增量:委托贷款:当月值（201001-202608，指标ID M002917569）",
        "role": "component",
    },
    "tsf_trust_loans": {
        "providerId": "M002917570",
        "query": "社会融资规模增量:信托贷款:当月值（201001-202608，指标ID M002917570）",
        "role": "component",
    },
    "tsf_bank_acceptance": {
        "providerId": "M002917571",
        "query": "社会融资规模增量:未贴现银行承兑汇票:当月值（201001-202608，指标ID M002917571）",
        "role": "component",
    },
    "tsf_corporate_bonds": {
        "providerId": "M004734600",
        "query": "社会融资规模增量:企业债券融资:当月值（201001-202608，指标ID M002917572）",
        "role": "component",
    },
    "tsf_equity_financing": {
        "providerId": "M002917573",
        "query": "社会融资规模增量:非金融企业境内股票融资:当月值（201001-202608，指标ID M002917573）",
        "role": "component",
    },
    "tsf_government_bonds": {
        "providerId": "M004891011",
        "query": "社会融资规模增量:政府债券:当月值（201701-202608，指标ID M004891011）",
        "role": "component",
    },
    "tsf_asset_backed_securities": {
        "providerId": "M004734604",
        "query": "社会融资规模增量:存款类金融机构资产支持证券:当月值（201701-202608，指标ID M004734604）",
        "role": "component",
    },
    "tsf_loan_writeoffs": {
        "providerId": "M004734605",
        "query": "社会融资规模增量:贷款核销:当月值（201701-202608，指标ID M004734605）",
        "role": "component",
    },
    "bill_discount_6m": {
        "providerId": "M021397974",
        "query": "转贴(国股贴)半年国股（20180101-20260831，指标ID M021397974）",
        "role": "leading_indicator",
        "optional": True,
    },
    "bill_discount_3m": {
        "providerId": "M021397977",
        "query": "转贴(国股贴)3M国股（20180101-20260831，指标ID M021397977）",
        "role": "leading_indicator",
        "optional": True,
    },
    "local_government_bond_gross_issuance": {
        "providerId": "M004394055",
        "query": "地方政府债券发行额:当月值（201801-202608，指标ID M004394055）",
        "role": "leading_indicator",
    },
    "government_bond_gross_issuance": {
        "providerId": "S003660493",
        "query": "政府债券:发行额:当月值（201801-202608，指标ID S003660493）",
        "role": "leading_indicator",
    },
    "local_government_bond_principal_repayment": {
        "providerId": "M014885514",
        "query": "地方政府债券到期偿还本金金额:当月值（201801-202608，指标ID M014885514）",
        "role": "leading_indicator",
    },
    "corporate_credit_bond_gross_issuance": {
        "providerId": "S003660499",
        "query": "公司信用类债券:发行额:当月值（201801-202608，指标ID S003660499）",
        "role": "leading_indicator",
    },
    "m2_consensus": {
        "providerId": "M005682260",
        "query": "预测平均值:M2:同比（202001-202608）",
        "role": "comparison_only",
    },
    "new_rmb_loans_consensus": {
        "providerId": "M005682262",
        "query": "经济数据预测:新增人民币贷款:预测平均值（202001-202608）",
        "role": "comparison_only",
    },
    "social_financing_consensus": {
        "providerId": "M005682268",
        "query": "经济数据预测:社会融资规模增量:当月值:预测平均值，指标ID M005682268（202001-202608）",
        "role": "comparison_only",
    },
}


def find_call() -> Path:
    candidates = []
    if os.environ.get("IFIND_SKILL_DIR"):
        candidates.append(Path(os.environ["IFIND_SKILL_DIR"]) / "call.py")
    candidates.extend(Path.home().glob("Documents/*/skills/ifind-finance-data/call.py"))
    for path in candidates:
        if path.exists():
            return path
    raise RuntimeError("Cannot locate iFinD call.py; set IFIND_SKILL_DIR")


def load_call(path: Path):
    spec = importlib.util.spec_from_file_location("credit_ifind_call", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    previous = Path.cwd()
    try:
        os.chdir(path.parent)
        spec.loader.exec_module(module)
    finally:
        os.chdir(previous)
    return module.call


def parse(response: dict[str, Any], expected_id: str) -> dict[str, Any]:
    content = response.get("data", {}).get("result", {}).get("content", [])
    if not response.get("ok") or not content:
        raise RuntimeError(str(response.get("error") or "empty iFinD response"))
    payload = json.loads(content[0]["text"])
    matches = []
    observed = []
    for item in payload.get("data", {}).get("datas", []):
        data = item.get("data", {})
        for column, metadata in data.get("attrs", {}).items():
            provider_id = metadata.get("index_id")
            observed.append(provider_id)
            if provider_id == expected_id:
                matches.append((column, metadata, data.get("data", [])))
    if len(matches) != 1:
        raise RuntimeError(f"expected {expected_id}, observed {sorted(set(observed))}")
    column, metadata, observations = matches[0]
    return {
        "providerId": expected_id,
        "name": column,
        "unit": metadata.get("unit"),
        "frequency": metadata.get("freq"),
        "source": metadata.get("data_source"),
        "observations": observations,
    }


def fetch(checkpoint: Path | None = None, resume: bool = False) -> dict[str, Any]:
    call = load_call(find_call())
    result = {
        "schemaVersion": 1,
        "retrievedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "consensusPolicy": "comparison_only; excluded from features, training, tuning and model selection",
        "series": {},
    }
    previous_series: dict[str, Any] = {}
    if resume and checkpoint and checkpoint.exists():
        previous = json.loads(checkpoint.read_text(encoding="utf-8-sig"))
        for key, value in previous.get("series", {}).items():
            if key in SERIES and value.get("providerId") == SERIES[key]["providerId"]:
                previous_series[key] = value
    for key, config in SERIES.items():
        errors = []
        for attempt in range(3):
            try:
                response = call("edb", "get_edb_data", {"query": config["query"]})
                parsed = parse(response, config["providerId"])
                parsed["role"] = config["role"]
                result["series"][key] = parsed
                break
            except Exception as error:  # network retries are intentionally bounded
                errors.append(str(error))
                time.sleep(attempt + 1)
        if key not in result["series"] and key in previous_series:
            result["series"][key] = previous_series[key]
            result.setdefault("warnings", []).append(
                f"{key}/{config['providerId']} refresh failed; retained previously validated observations"
            )
            continue
        if key not in result["series"] and config.get("optional"):
            continue
        if key not in result["series"]:
            raise RuntimeError(f"failed to fetch {key}/{config['providerId']}: {' | '.join(errors)}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resume", action="store_true", help="refresh each series and retain its previously validated value only when the live query fails")
    args = parser.parse_args()
    payload = fetch(args.output, args.resume)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: len(value["observations"]) for key, value in payload["series"].items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
