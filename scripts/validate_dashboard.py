#!/usr/bin/env python3
"""Validate indicator configuration and generated dashboard data before release."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "indicators.json"
DEFAULT_AUXILIARY = ROOT / "config" / "auxiliary-indicators.csv"
DEFAULT_DATA = ROOT / "public" / "data" / "dashboard.json"

ALLOWED_FREQUENCIES = {"daily", "weekly"}
ALLOWED_TRANSFORMS = {"pct_change", "pp_change", "level_change"}
ALLOWED_AGGREGATES = {
    "",
    "standardized_mean",
    "rolling_7d_mean",
    "rolling_7d_sum",
    "rolling_4w_mean",
}
ALLOWED_PREPROCESS = {"", "rolling_7d_mean", "rolling_4w_mean"}


def load_definitions(
    config_path: Path, auxiliary_path: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    definitions = list(config["indicators"])
    if auxiliary_path.exists():
        with auxiliary_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                definitions.append(
                    {
                        "id": row["id"],
                        "category": row["category"],
                        "family": row["family"],
                        "name": row["name"],
                        "frequency": row["frequency"],
                        "unit": row.get("unit", ""),
                        "source": row["source"],
                        "series": [{"code": row["code"], "weight": 1}],
                        "transform": row.get("transform") or "pct_change",
                        "bond_direction": float(row.get("bond_direction") or -1),
                        "core": False,
                        "weight": float(row.get("weight") or 0.3),
                    }
                )
    return config, definitions


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def validate_configuration(
    config: dict[str, Any],
    definitions: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> None:
    category_ids = [item["id"] for item in config.get("categories", [])]
    if len(category_ids) != len(set(category_ids)):
        errors.append("config/indicators.json 存在重复大类ID")
    if len(category_ids) != 9:
        warnings.append(f"当前配置为{len(category_ids)}个大类，页面设计基准为9类")

    ids = [item.get("id") for item in definitions]
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    if duplicate_ids:
        errors.append(f"指标ID重复：{', '.join(duplicate_ids)}")

    for item in definitions:
        prefix = f"{item.get('id', '<missing-id>')}"
        required = ("id", "category", "family", "name", "frequency", "series")
        missing = [field for field in required if not item.get(field)]
        if missing:
            errors.append(f"{prefix} 缺少字段：{', '.join(missing)}")
            continue
        if item["category"] not in category_ids:
            errors.append(f"{prefix} 使用未知大类：{item['category']}")
        if item["frequency"] not in ALLOWED_FREQUENCIES:
            errors.append(f"{prefix} frequency不支持：{item['frequency']}")
        transform = item.get("transform", "pct_change")
        if transform not in ALLOWED_TRANSFORMS:
            errors.append(f"{prefix} transform不支持：{transform}")
        aggregate = item.get("aggregate", "")
        if aggregate not in ALLOWED_AGGREGATES:
            errors.append(f"{prefix} aggregate不支持：{aggregate}")
        preprocess = item.get("component_preprocess", "")
        if preprocess not in ALLOWED_PREPROCESS:
            errors.append(f"{prefix} component_preprocess不支持：{preprocess}")
        if float(item.get("weight", 1)) <= 0:
            errors.append(f"{prefix} 指标权重必须大于0")
        if float(item.get("bond_direction", 0)) not in {-1, 1}:
            errors.append(f"{prefix} bond_direction必须为-1或1")
        series = item.get("series", [])
        if aggregate == "standardized_mean" and len(series) < 2:
            errors.append(f"{prefix} standardized_mean至少需要两个原始分项")
        for component in series:
            if not component.get("code"):
                errors.append(f"{prefix} 存在空的series.code")
            if float(component.get("weight", 1)) <= 0:
                errors.append(f"{prefix} 原始分项权重必须大于0")
        if len(series) > 1 and not item.get("methodology"):
            warnings.append(f"{prefix} 是合成指标但未配置methodology页面说明")


def validate_generated_data(
    dashboard: dict[str, Any],
    definitions: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    dates = dashboard.get("dates", [])
    if len(dates) < 52:
        errors.append(f"趋势历史只有{len(dates)}周，至少需要52周")
    if dates != sorted(set(dates)):
        errors.append("dashboard.dates 必须按日期升序且不能重复")

    overall = dashboard.get("overall", {})
    if len(overall.get("weeklyScores", [])) != len(dates):
        errors.append("综合观点weeklyScores长度与dates不一致")
    elif dates and abs(
        float(overall.get("score", 0)) - float(overall["weeklyScores"][-1])
    ) > 0.11:
        errors.append("综合观点最新score与weeklyScores末值不一致")

    categories = dashboard.get("categories", [])
    for category in categories:
        if len(category.get("weeklyScores", [])) != len(dates):
            errors.append(f"{category.get('id')} 大类历史长度与dates不一致")
        elif dates and abs(
            float(category.get("score", 0)) - float(category["weeklyScores"][-1])
        ) > 0.11:
            errors.append(f"{category.get('id')} 最新score与历史末值不一致")

    expected = {item["id"]: item for item in definitions}
    indicators = dashboard.get("indicators", [])
    actual = {item.get("id"): item for item in indicators}
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    missing_core = [item for item in missing if expected[item].get("core", True)]
    if missing_core:
        errors.append(f"缺少核心指标：{', '.join(missing_core)}")
    if missing:
        warnings.append(
            f"共缺少{len(missing)}个已配置指标"
            + (f"：{', '.join(missing[:12])}" if missing else "")
        )
    if extra:
        warnings.append(f"输出含{len(extra)}个配置中不存在的指标")

    coverage = len(set(actual) & set(expected)) / max(1, len(expected))
    if coverage < 0.95:
        errors.append(f"指标覆盖率只有{coverage:.1%}，低于95%发布门槛")

    generated_day = datetime.fromisoformat(
        dashboard["generatedAt"].replace("Z", "+00:00")
    ).date()
    for item_id, indicator in actual.items():
        definition = expected.get(item_id)
        if not definition:
            continue
        prefix = item_id
        series = indicator.get("series", [])
        min_points = 120 if definition["frequency"] == "daily" else 26
        if len(series) < min_points:
            errors.append(
                f"{prefix} 只有{len(series)}个历史点，至少需要{min_points}个"
            )
            continue
        series_dates = [point.get("date") for point in series]
        if series_dates != sorted(set(series_dates)):
            errors.append(f"{prefix} 历史日期未升序或存在重复")
        if any(not finite_number(point.get("value")) for point in series):
            errors.append(f"{prefix} 历史序列含非有限数值")
        if indicator.get("updatedAt") != series_dates[-1]:
            errors.append(f"{prefix} updatedAt与历史末日不一致")
        if abs(float(indicator.get("latest", 0)) - float(series[-1]["value"])) > 1e-3:
            errors.append(f"{prefix} latest与历史末值不一致")
        if len(indicator.get("history", [])) != len(dates):
            errors.append(f"{prefix} 信号历史长度与dates不一致")
        methodology = indicator.get("methodology", {})
        if not methodology.get("formula") or not methodology.get("steps"):
            errors.append(f"{prefix} 缺少页面计算方法说明")
        stale_days = (generated_day - date.fromisoformat(series_dates[-1])).days
        stale_limit = 7 if definition["frequency"] == "daily" else 14
        if stale_days > stale_limit:
            warnings.append(
                f"{prefix} 最新数据为{series_dates[-1]}，已滞后{stale_days}天"
            )

    return {
        "configured_indicators": len(expected),
        "generated_indicators": len(actual),
        "coverage": round(coverage, 4),
        "history_weeks": len(dates),
        "categories": len(categories),
        "mode": dashboard.get("mode", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--auxiliary", type=Path, default=DEFAULT_AUXILIARY)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="把新鲜度、缺少辅助指标等警告也视为发布失败",
    )
    parser.add_argument("--report", type=Path, help="可选：输出JSON质量报告")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    try:
        config, definitions = load_definitions(args.config, args.auxiliary)
        validate_configuration(config, definitions, errors, warnings)
        dashboard = json.loads(args.data.read_text(encoding="utf-8"))
        summary = validate_generated_data(dashboard, definitions, errors, warnings)
    except Exception as error:
        errors.append(f"校验器无法读取输入：{error}")
        summary = {}

    report = {
        "ok": not errors and not (args.strict and warnings),
        "strict": args.strict,
        "summary": summary,
        "errors": errors,
        "warnings": warnings,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
