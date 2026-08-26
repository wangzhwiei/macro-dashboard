#!/usr/bin/env python3
"""Validate indicator configuration and generated dashboard data before release."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime
from statistics import median
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "indicators.json"
DEFAULT_AUXILIARY = ROOT / "config" / "auxiliary-indicators.csv"
DEFAULT_DATA = ROOT / "public" / "data" / "dashboard.json"
DEFAULT_PROVIDER_MAP = ROOT / "config" / "provider-code-map.json"

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
DEFAULT_STALE_TOLERANCE_DAYS = {"daily": 4, "weekly": 14}


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
                        "stale_tolerance_days": int(
                            row.get("stale_tolerance_days") or 0
                        ),
                    }
                )
    return config, definitions


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def stale_tolerance_days(definition: dict[str, Any]) -> int:
    configured = int(definition.get("stale_tolerance_days") or 0)
    return configured or DEFAULT_STALE_TOLERANCE_DAYS[definition["frequency"]]


def cadence_issue(frequency: str, series: list[dict[str, Any]]) -> str | None:
    gap = median_gap_days(series)
    if gap is None:
        return None
    if frequency == "daily" and gap > 3:
        return f"标记为日频但历史观测间隔中位数为{gap:g}天"
    if frequency == "weekly" and gap < 4:
        return f"标记为周频但历史观测间隔中位数仅{gap:g}天"
    if frequency == "weekly" and gap > 14:
        return f"标记为周频但历史观测间隔中位数为{gap:g}天"
    return None


def _provider_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("provider_code") or value.get("code") or "").strip()
    return ""


def provider_code_collisions(
    provider_map: dict[str, Any], definitions: list[dict[str, Any]]
) -> list[tuple[str, list[str]]]:
    required_codes = {
        component.get("code", "")
        for item in definitions
        for component in item.get("series", [])
        if component.get("code")
    }
    by_provider: dict[str, list[str]] = defaultdict(list)
    for semantic_code in sorted(required_codes):
        provider_code = _provider_value(provider_map.get(semantic_code))
        if provider_code:
            by_provider[provider_code].append(semantic_code)
    return sorted(
        (
            (provider_code, semantic_codes)
            for provider_code, semantic_codes in by_provider.items()
            if len(semantic_codes) > 1
        ),
        key=lambda item: item[0],
    )


def validate_provider_code_map(
    provider_map_path: Path,
    definitions: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    required_codes = sorted(
        {
            component.get("code", "")
            for item in definitions
            for component in item.get("series", [])
            if component.get("code")
        }
    )
    if not provider_map_path.exists():
        warnings.append(f"供应商代码映射不存在：{provider_map_path}")
        return {
            "required_provider_codes": len(required_codes),
            "mapped_provider_codes": 0,
            "provider_code_collisions": 0,
        }

    provider_map = json.loads(provider_map_path.read_text(encoding="utf-8"))
    missing = [
        code
        for code in required_codes
        if not _provider_value(provider_map.get(code))
        or "请替换" in _provider_value(provider_map.get(code))
    ]
    if missing:
        errors.append(
            f"供应商代码缺失或仍为占位符，共{len(missing)}项："
            + ", ".join(missing[:20])
        )

    collisions = provider_code_collisions(provider_map, definitions)
    for provider_code, semantic_codes in collisions:
        errors.append(
            "不同语义序列不得共用供应商代码 "
            f"{provider_code}：{', '.join(semantic_codes)}"
        )

    extra = sorted(set(provider_map) - set(required_codes))
    if extra:
        warnings.append(f"供应商映射含{len(extra)}个配置未使用代码")

    return {
        "required_provider_codes": len(required_codes),
        "mapped_provider_codes": len(required_codes) - len(missing),
        "provider_code_collisions": len(collisions),
    }


def median_gap_days(series: list[dict[str, Any]]) -> float | None:
    parsed_dates: list[date] = []
    for point in series:
        try:
            parsed_dates.append(date.fromisoformat(str(point.get("date"))))
        except ValueError:
            continue
    gaps = [
        (current - previous).days
        for previous, current in zip(parsed_dates, parsed_dates[1:])
        if current > previous
    ]
    return float(median(gaps)) if gaps else None


def duplicate_series_groups(
    indicators: list[dict[str, Any]],
) -> list[list[str]]:
    signatures: dict[str, list[str]] = defaultdict(list)
    for indicator in indicators:
        series = indicator.get("series", [])
        if not series:
            continue
        signature = json.dumps(
            [
                [point.get("date"), point.get("value")]
                for point in series
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        signatures[signature].append(str(indicator.get("id")))
    return sorted(
        (ids for ids in signatures.values() if len(ids) > 1),
        key=lambda ids: (-len(ids), ids),
    )


def rate_bound_violations(
    indicator: dict[str, Any],
) -> list[dict[str, Any]]:
    name = str(indicator.get("name", ""))
    if indicator.get("unit") != "%" or not any(
        token in name for token in ("开工率", "产能利用率")
    ):
        return []
    return [
        point
        for point in indicator.get("series", [])
        if finite_number(point.get("value"))
        and not 0 <= float(point["value"]) <= 100
    ]


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
    stale_indicators = 0
    cadence_issues = 0
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
        expected_unit = definition.get("unit", "")
        if indicator.get("unit", "") != expected_unit:
            errors.append(
                f"{prefix} 页面单位{indicator.get('unit', '')!r}与配置{expected_unit!r}不一致"
            )
        if indicator.get("source") != definition.get("source"):
            errors.append(
                f"{prefix} 页面来源{indicator.get('source')!r}与配置"
                f"{definition.get('source')!r}不一致"
            )
        expected_frequency = (
            "日频" if definition["frequency"] == "daily" else "周频"
        )
        if indicator.get("frequency") != expected_frequency:
            errors.append(
                f"{prefix} 页面频率{indicator.get('frequency')!r}与配置"
                f"{expected_frequency!r}不一致"
            )
        issue = cadence_issue(definition["frequency"], series)
        if issue:
            cadence_issues += 1
            warnings.append(f"{prefix} {issue}")
        bound_violations = rate_bound_violations(indicator)
        if bound_violations:
            samples = ", ".join(
                f"{point.get('date')}={point.get('value')}"
                for point in bound_violations[-3:]
            )
            errors.append(
                f"{prefix} 百分比率指标超出0～100，共"
                f"{len(bound_violations)}个点；末尾样本：{samples}"
            )
        if abs(float(indicator.get("latest", 0)) - float(series[-1]["value"])) > 1e-3:
            errors.append(f"{prefix} latest与历史末值不一致")
        if len(indicator.get("history", [])) != len(dates):
            errors.append(f"{prefix} 信号历史长度与dates不一致")
        elif dates and abs(
            float(indicator.get("score", 0)) - float(indicator["history"][-1])
        ) > 0.11:
            errors.append(f"{prefix} 最新score与信号历史末值不一致")
        if dates and indicator.get("scoreAsOf") != dates[-1]:
            errors.append(f"{prefix} scoreAsOf与最新周五快照不一致")
        score_observation_at = indicator.get("scoreObservationAt")
        if not score_observation_at:
            errors.append(f"{prefix} 缺少周五评分观测日期")
        elif dates and score_observation_at > dates[-1]:
            errors.append(f"{prefix} 周五评分使用了快照日之后的数据")
        score_change = indicator.get("scoreChange")
        score_scale = indicator.get("scoreScale")
        if not finite_number(score_change):
            errors.append(f"{prefix} 缺少有效的周五评分变化")
        if not finite_number(score_scale) or float(score_scale or 0) <= 0:
            errors.append(f"{prefix} 缺少有效的周五评分波动尺度")
        if finite_number(score_change) and finite_number(score_scale) and float(score_scale) > 0:
            raw_score = (
                float(score_change) / float(score_scale) * 35
                * float(definition.get("bond_direction", -1))
            )
            expected_score = max(-100, min(100, raw_score))
            if abs(float(indicator.get("score", 0)) - expected_score) > 0.16:
                errors.append(
                    f"{prefix} 周五强度无法由评分变化和历史尺度复算："
                    f"页面{indicator.get('score')}，复算{expected_score:.1f}"
                )
        if "周五快照" not in str(indicator.get("reason", "")):
            errors.append(f"{prefix} 评分解释未标明周五快照口径")
        methodology = indicator.get("methodology", {})
        if not methodology.get("formula") or not methodology.get("steps"):
            errors.append(f"{prefix} 缺少页面计算方法说明")
        stale_days = (generated_day - date.fromisoformat(series_dates[-1])).days
        stale_limit = stale_tolerance_days(definition)
        if stale_days > stale_limit:
            stale_indicators += 1
            warnings.append(
                f"{prefix} 最新数据为{series_dates[-1]}，已滞后{stale_days}天"
                f"（{definition['frequency']}容忍{stale_limit}天）"
            )

    duplicates = duplicate_series_groups(indicators)
    for ids in duplicates:
        errors.append(
            "不同指标历史序列完全相同，疑似代码映射错误："
            + ", ".join(ids)
        )

    return {
        "configured_indicators": len(expected),
        "generated_indicators": len(actual),
        "coverage": round(coverage, 4),
        "history_weeks": len(dates),
        "categories": len(categories),
        "mode": dashboard.get("mode", ""),
        "stale_indicators": stale_indicators,
        "cadence_issues": cadence_issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--auxiliary", type=Path, default=DEFAULT_AUXILIARY)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument(
        "--provider-map",
        type=Path,
        default=DEFAULT_PROVIDER_MAP,
        help="语义代码到供应商真实代码的映射文件",
    )
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
        mapping_summary = validate_provider_code_map(
            args.provider_map, definitions, errors, warnings
        )
        dashboard = json.loads(args.data.read_text(encoding="utf-8"))
        summary = validate_generated_data(dashboard, definitions, errors, warnings)
        summary.update(mapping_summary)
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
