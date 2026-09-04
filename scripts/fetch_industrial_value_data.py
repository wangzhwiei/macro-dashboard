#!/usr/bin/env python3
"""Fetch fixed-provider industrial-value actuals and consensus from iFinD EDB."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "industrial-value-model" / "targets_consensus.json"
DEFAULT_PRODUCTION_OUTPUT = ROOT / "data" / "industrial-value-model" / "production_inputs.json"

SERIES = {
    "actualMonthly": {
        "queries": [
            "中国:工业增加值:规模以上工业企业:当月同比（201201-202608）",
            "规模以上工业增加值:当月同比，工业节点，指标ID M001622302（201201-202608）",
        ],
        "providerId": "M001622302",
        "name": "规模以上工业增加值:当月同比",
    },
    "actualYtd": {
        "queries": [
            "中国:规模以上工业增加值:累计同比，工业节点（201201-202608）",
            "规模以上工业增加值:累计同比，指标ID M001622303（201201-202608）",
        ],
        "providerId": "M001622303",
        "name": "规模以上工业增加值:累计同比",
    },
    "actualMomSa": {
        "queries": [
            "中国:规模以上工业增加值:季调:环比（201201-202608）",
            "规模以上工业增加值:季调:环比，指标ID M002822189（201201-202608）",
        ],
        "providerId": "M002822189",
        "name": "规模以上工业增加值:季调:环比",
    },
    "consensus": {
        "queries": [
            "中国:工业增加值:当月同比:一致预期（201201-202608）",
            "预测平均值:规模以上工业增加值:当月同比，指标ID M005682255（201201-202608）",
        ],
        "providerId": "M005682255",
        "name": "预测平均值:规模以上工业增加值:当月同比",
    },
}

PRODUCTION_SERIES = {
    "blast_furnace": ("高炉开工率:全国(样本数247家):当周值", "S005653695"),
    "rebar_rate": ("建材钢厂:螺纹钢:开工率:全国:当周值", "S005580571"),
    "power_coal": ("煤炭:日均耗煤量:六大发电集团:总计", "S003839324"),
    "pta_rate": ("开工率:PTA装置", "S019765727"),
    "methanol_rate": ("开工率:甲醇:全国:小计", "S005439668"),
    "car_wholesale": ("乘用车:当月厂家日均批发销量", "S023782827"),
    "car_retail": ("乘用车:当月厂家日均零售销量", "S023782829"),
    "broad_car_output_yoy": ("乘用车:产量:广义乘用车:当月同比", "S002811623"),
    "excavator_sales_yoy": ("销量:液压挖掘机:主要企业:总计:当月同比", "S002850744"),
    # Official component accounts and physical-output checks.  These series are
    # released with (or after) aggregate industrial value added, so the model
    # only uses observations dated strictly before the month being forecast.
    "sector_mining_yoy": ("规模以上工业增加值:采矿业:当月同比", "M004369927"),
    "sector_manufacturing_yoy": ("规模以上工业增加值:制造业:当月同比", "M004369928"),
    "sector_utility_yoy": ("规模以上工业增加值:电力、热力、燃气及水生产和供应业:当月同比", "M004369929"),
    "output_coal_yoy": ("原煤:产量:当月同比", "S000006804"),
    "output_power_yoy": ("规模以上工业发电量:当月同比", "M001622862"),
    "output_crude_steel_yoy": ("粗钢:产量:当月同比", "M001622691"),
    "output_steel_yoy": ("钢材:产量:当月同比", "S000021534"),
    "output_cement_yoy": ("水泥:产量:当月同比", "M005382983"),
    "output_ethylene_yoy": ("乙烯:产量:当月同比", "S000014891"),
    "output_chemical_fiber_yoy": ("化学纤维:产量:当月同比", "S000014895"),
    "output_nonferrous_yoy": ("十种有色金属:产量:当月同比", "M005383041"),
    "output_ic_yoy": ("集成电路:产量:当月同比", "M005383779"),
    "output_robot_yoy": ("工业机器人:产量:当月同比", "S018402443"),
    "output_gas_yoy": ("天然气:产量:当月同比", "S000006820"),
}


def find_ifind_call() -> Path:
    candidates = []
    if os.environ.get("IFIND_SKILL_DIR"):
        candidates.append(Path(os.environ["IFIND_SKILL_DIR"]) / "call.py")
    candidates.extend(
        [
            Path.home() / ".codex" / "skills" / "iFinD-Finance-Data" / "call.py",
            Path.home() / "Documents" / "固收投委会" / "skills" / "ifind-finance-data" / "call.py",
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    raise RuntimeError("找不到 iFinD call.py；请设置 IFIND_SKILL_DIR")


def load_ifind_call(path: Path):
    spec = importlib.util.spec_from_file_location("industrial_value_ifind_call", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 iFinD 调用模块：{path}")
    module = importlib.util.module_from_spec(spec)
    previous = Path.cwd()
    try:
        os.chdir(path.parent)
        spec.loader.exec_module(module)
    finally:
        os.chdir(previous)
    return module.call


def parse_payload(response: dict[str, Any], expected_id: str) -> dict[str, Any]:
    if not response.get("ok"):
        raise RuntimeError(str(response.get("error") or "iFinD 调用失败"))
    content = response.get("data", {}).get("result", {}).get("content", [])
    if not content:
        raise RuntimeError("iFinD 响应缺少 content")
    payload = json.loads(content[0]["text"])
    if payload.get("code") != 1:
        raise RuntimeError(str(payload.get("msg") or "iFinD EDB 返回失败"))
    matches = []
    for item in payload.get("data", {}).get("datas", []):
        data = item.get("data", {})
        attrs = data.get("attrs", {})
        for column, metadata in attrs.items():
            if metadata.get("index_id") == expected_id:
                matches.append((column, metadata, data.get("data", [])))
    if len(matches) != 1:
        observed = sorted(
            {
                meta.get("index_id")
                for item in payload.get("data", {}).get("datas", [])
                for meta in item.get("data", {}).get("attrs", {}).values()
                if meta.get("index_id")
            }
        )
        raise RuntimeError(f"iFinD 指标漂移：期望 {expected_id}，实际 {observed}")
    column, metadata, observations = matches[0]
    return {
        "providerId": expected_id,
        "name": column,
        "frequency": metadata.get("freq"),
        "unit": metadata.get("unit"),
        "source": metadata.get("data_source"),
        "observations": observations,
    }


def fetch(
    output: Path,
    production_output: Path,
    production_only: bool = False,
    production_keys: set[str] | None = None,
    targets_only: bool = False,
) -> dict[str, Any]:
    ifind_call = load_ifind_call(find_ifind_call())
    cached = json.loads(output.read_text(encoding="utf-8-sig")) if output.exists() else {"series": {}}
    if production_only:
        payload = json.loads(output.read_text(encoding="utf-8-sig"))
    else:
        payload = {
            "schemaVersion": 1,
            "retrievedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "trainingPolicy": "一致预期与模型输入物理隔离，仅用于预测结果评估",
            "series": {},
        }
        for key, config in SERIES.items():
            errors = []
            end_month = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m")
            queries = [query.replace("202608", end_month) for query in config["queries"]]
            for query in queries * 2:
                try:
                    response = ifind_call("edb", "get_edb_data", {"query": query})
                    payload["series"][key] = parse_payload(response, config["providerId"])
                    break
                except Exception as error:
                    errors.append(str(error))
            if key not in payload["series"]:
                cached_series = cached.get("series", {}).get(key, {})
                if cached_series.get("providerId") == config["providerId"] and cached_series.get("observations"):
                    payload["series"][key] = cached_series
                    payload.setdefault("warnings", []).append(f"{key} 实时查询失败，保留已验证缓存 {config['providerId']}")
                else:
                    raise RuntimeError(f"无法锁定 {key}/{config['providerId']}：{' | '.join(errors)}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if targets_only:
        return payload
    production_cached = json.loads(production_output.read_text(encoding="utf-8-sig")) if production_output.exists() else {"series": {}}
    production = {
        "schemaVersion": 1,
        "retrievedAt": payload["retrievedAt"],
        "series": dict(production_cached.get("series", {})) if production_keys else {},
    }
    for key, (name, provider_id) in PRODUCTION_SERIES.items():
        if production_keys and key not in production_keys:
            continue
        errors = []
        end_day = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        queries = [
            f"{name}（20200101-{end_day}），指标ID {provider_id}",
            f"{name}（20200101-{end_day}）",
        ]
        for query in queries * 2:
            try:
                response = ifind_call("edb", "get_edb_data", {"query": query})
                production["series"][key] = parse_payload(response, provider_id)
                break
            except Exception as error:
                errors.append(str(error))
        if key not in production["series"]:
            cached_series = production_cached.get("series", {}).get(key, {})
            if cached_series.get("providerId") == provider_id and cached_series.get("observations"):
                production["series"][key] = cached_series
                production.setdefault("warnings", []).append(f"{key} 实时查询失败，保留已验证缓存 {provider_id}")
            else:
                raise RuntimeError(f"无法锁定生产因子 {key}/{provider_id}：{' | '.join(errors)}")
    production_output.parent.mkdir(parents=True, exist_ok=True)
    production_output.write_text(json.dumps(production, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--production-output", type=Path, default=DEFAULT_PRODUCTION_OUTPUT)
    parser.add_argument("--production-only", action="store_true")
    parser.add_argument("--targets-only", action="store_true")
    parser.add_argument("--production-key", action="append", choices=sorted(PRODUCTION_SERIES))
    args = parser.parse_args()
    payload = fetch(
        args.output,
        args.production_output,
        args.production_only,
        set(args.production_key) if args.production_key else None,
        args.targets_only,
    )
    counts = {key: len(value["observations"]) for key, value in payload["series"].items()}
    print(f"工业增加值数据已写入 {args.output}: {counts}；生产因子写入 {args.production_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
