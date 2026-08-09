#!/usr/bin/env python3
"""Import the minimum locked data needed by the archived CPI/PPI/PMI models.

The source directory is the old ``宏观指标研究/data_store`` folder.  Only the
series named below are copied; unrelated research data and provider credentials
never enter the dashboard project.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "forecast-model" / "model_inputs.json"

CPI_KEYS = (
    "cpi_food_mom",
    "cpi_nonfood_mom",
    "cpi_mom_total",
    "food_weight",
    "veg",
    "pork",
    "crb",
    "pmi",
)
TARGET_KEYS = ("cpi", "ppi", "pmi", "ppi_mom")
PPI_PROXY_KEYS = (
    "南华工业品指数",
    "现货价:原油:英国布伦特Dtd",
    "动力煤价格",
    "螺纹钢",
    "铜价",
    "CRB现货指数:综合",
)
PMI_PROXY_KEYS = (
    "高炉开工率(247家):全国",
    "螺纹钢:主要钢厂开工率:全国",
    "日耗量:煤炭:6大发电集团",
    "PTA负荷率",
    "甲醇开工率",
    "乘用车批发销量",
    "乘用车市场零售",
    "30城商品房成交面积",
    "二手房成交面积",
    "螺纹钢表观消费",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def select(source: dict[str, Any], keys: tuple[str, ...], label: str) -> dict[str, Any]:
    missing = [key for key in keys if key not in source]
    if missing:
        raise KeyError(f"{label} 缺少序列: {', '.join(missing)}")
    return {key: source[key] for key in keys}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(os.environ.get("LEGACY_FORECAST_SOURCE", ".")),
        help="旧项目 data_store 目录",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    cpi = read_json(args.source / "dw_cpi_data.json")
    targets = read_json(args.source / "monthly_targets.json")
    raw = read_json(args.source / "raw_full.json")
    subindices = read_json(args.source / "pmi_subindices.json")

    payload = {
        "schemaVersion": 1,
        "provenance": {
            "source": "旧 WSL 宏观指标研究锁定数据",
            "modelVersion": "L0纯改 + 精确乘法同比；PMI五分项扩展窗",
            "backtestStart": "2023-01-31",
            "displayStart": "2020-01-31",
        },
        "cpi": select(cpi, CPI_KEYS, "CPI"),
        "targets": select(targets, TARGET_KEYS, "月频目标"),
        "raw": select(raw, PPI_PROXY_KEYS + PMI_PROXY_KEYS, "高频代理"),
        "pmiSubindices": subindices,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"已导入锁定模型数据：{args.output} ({args.output.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
