#!/usr/bin/env python3
"""Fetch, normalize, deduplicate, score and publish macro dashboard data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_CONFIG = ROOT / "config" / "indicators.json"
DEFAULT_AUXILIARY = ROOT / "config" / "auxiliary-indicators.csv"
DEFAULT_OUTPUT = ROOT / "public" / "data" / "dashboard.json"
Point = tuple[date, float]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def clamp(value: float, low: float = -100, high: float = 100) -> float:
    return max(low, min(high, value))


def parse_day(value: Any) -> date:
    return datetime.fromisoformat(str(value)[:10]).date()


def normalize_records(records: list[dict[str, Any]]) -> list[Point]:
    values: dict[date, float] = {}
    for record in records:
        try:
            day = parse_day(record["date"])
            value = float(record["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value):
            values[day] = value
    return sorted(values.items())


def value_at(points: list[Point], target: date) -> tuple[date, float] | None:
    for day, value in reversed(points):
        if day <= target:
            return day, value
    return None


def rolling(points: list[Point], window: int, operation: str) -> list[Point]:
    if window <= 1:
        return points
    result: list[Point] = []
    bucket: list[Point] = []
    for point in points:
        bucket.append(point)
        bucket = [
            item for item in bucket if (point[0] - item[0]).days <= window - 1
        ]
        if operation == "sum":
            value = sum(item[1] for item in bucket)
        else:
            value = statistics.fmean(item[1] for item in bucket)
        result.append((point[0], value))
    return result


def standardized_mean(
    components: list[tuple[list[Point], float]],
) -> list[Point]:
    normalized: list[tuple[dict[date, float], float]] = []
    all_dates: set[date] = set()
    for points, weight in components:
        raw = [value for _, value in points]
        if not raw:
            continue
        mean = statistics.fmean(raw)
        std = statistics.pstdev(raw) or 1.0
        mapping = {day: (value - mean) / std for day, value in points}
        normalized.append((mapping, weight))
        all_dates.update(mapping)

    result: list[Point] = []
    latest_values: list[tuple[dict[date, float], float]] = normalized
    for day in sorted(all_dates):
        weighted_values: list[tuple[float, float]] = []
        for mapping, weight in latest_values:
            eligible = [known for known in mapping if known <= day]
            if not eligible:
                continue
            latest_day = max(eligible)
            if (day - latest_day).days <= 10:
                weighted_values.append((mapping[latest_day], weight))
        if weighted_values:
            numerator = sum(value * weight for value, weight in weighted_values)
            denominator = sum(weight for _, weight in weighted_values)
            result.append((day, 100 + numerator / denominator * 10))
    return result


def aggregate_points(
    indicator: dict[str, Any],
    components: list[tuple[list[Point], float]],
) -> list[Point]:
    operation = indicator.get("aggregate", "")
    if operation == "standardized_mean":
        preprocess = indicator.get("component_preprocess", "")
        if preprocess == "rolling_7d_mean":
            components = [
                (rolling(points, 7, "mean"), weight)
                for points, weight in components
            ]
        elif preprocess == "rolling_4w_mean":
            components = [
                (rolling(points, 28, "mean"), weight)
                for points, weight in components
            ]
        return standardized_mean(components)

    points = components[0][0] if components else []
    if operation == "rolling_7d_sum":
        return rolling(points, 7, "sum")
    if operation == "rolling_7d_mean":
        return rolling(points, 7, "mean")
    if operation == "rolling_4w_mean":
        return rolling(points, 28, "mean")
    return points


def methodology_for(indicator: dict[str, Any]) -> dict[str, Any]:
    components = [
        {
            "code": series["code"],
            "weight": float(series.get("weight", 1)),
        }
        for series in indicator["series"]
    ]
    configured = indicator.get("methodology")
    if configured:
        return {
            "title": configured["title"],
            "formula": configured["formula"],
            "calibration": configured["calibration"],
            "steps": configured["steps"],
            "components": components,
        }

    operation = indicator.get("aggregate", "")
    if operation == "rolling_7d_sum":
        title = "原始日度序列滚动7日合计"
        formula = "X_t = Σ(x_d)，d ∈ [t-6, t]"
        steps = [
            "按日期清洗、去重并剔除非数值记录。",
            "把当日及此前6个自然日内的有效观测相加。",
            "用本周值相对7日前的变化计算信号。",
        ]
    elif operation == "rolling_7d_mean":
        title = "原始日度序列滚动7日均值"
        formula = "X_t = mean(x_d)，d ∈ [t-6, t]"
        steps = [
            "按日期清洗、去重并剔除非数值记录。",
            "计算当日及此前6个自然日内有效观测的算术平均。",
            "用本周值相对7日前的变化计算信号。",
        ]
    elif operation == "rolling_4w_mean":
        title = "原始序列滚动4周均值"
        formula = "X_t = mean(x_d)，d ∈ [t-27, t]"
        steps = [
            "按日期清洗、去重并剔除非数值记录。",
            "计算当日及此前27个自然日内有效观测的算术平均。",
            "用本周值相对7日前的变化计算信号。",
        ]
    elif operation == "standardized_mean":
        weights = " + ".join(
            f"{item['weight']:g}×z({item['code']})" for item in components
        )
        denominator = sum(item["weight"] for item in components)
        title = "多序列标准化加权合成"
        formula = f"Index_t = 100 + 10 × ({weights}) ÷ {denominator:g}"
        steps = [
            "各分项分别按日期清洗、去重。",
            "各分项独立计算 z=(x-历史均值)÷历史标准差。",
            "按配置权重合成；短暂缺数最多向前填充10天。",
            "将合成 z 分数映射为基准100的指数。",
        ]
    else:
        method = indicator.get("transform", "pct_change")
        title = "单一原始序列"
        formula = (
            "Δ_t = X_t - X_{t-7}"
            if method in {"pp_change", "level_change"}
            else "Δ_t = (X_t ÷ X_{t-7} - 1) × 100%"
        )
        steps = [
            "按日期清洗、去重并剔除非数值记录。",
            "读取最新有效值和7日前最近有效值。",
            "按配置的周变化方法计算信号输入。",
        ]

    return {
        "title": title,
        "formula": formula,
        "calibration": "信号标准化使用当前数据文件覆盖的历史区间，并在每日更新时重估。",
        "steps": steps,
        "components": components,
    }


def transformed_change(
    current: float, previous: float, method: str
) -> tuple[float, str]:
    if method in {"pp_change", "level_change"}:
        change = current - previous
        suffix = "个百分点" if method == "pp_change" else ""
        return change, f"{change:+.2f}{suffix}"
    if previous == 0:
        return 0.0, "—"
    change = (current / previous - 1) * 100
    return change, f"{change:+.2f}%"


def weekly_scores(
    points: list[Point],
    evaluation_dates: list[date],
    method: str,
    bond_direction: float,
) -> tuple[list[float], list[float]]:
    historical_changes: list[float] = []
    weekly_values: list[float] = []
    all_week_ends = sorted(
        {
            day - timedelta(days=(day.weekday() - 4) % 7)
            for day, _ in points
        }
    )
    for week_end in all_week_ends:
        current = value_at(points, week_end)
        previous = value_at(points, week_end - timedelta(days=7))
        if current and previous:
            historical_changes.append(
                transformed_change(current[1], previous[1], method)[0]
            )

    # Zero change is the economic direction anchor. Historical RMS only
    # calibrates magnitude, so de-meaning can never reverse a raw decline/rise.
    scale = (
        math.sqrt(statistics.fmean(change**2 for change in historical_changes))
        if historical_changes
        else 1
    )
    if scale < 1e-8:
        scale = 1

    latest_observation_day = points[-1][0]
    for week_end in evaluation_dates:
        # Do not turn a weekly series into a false zero-change signal merely
        # because the global dashboard date is later than its latest release.
        anchor_day = min(week_end, latest_observation_day)
        current = value_at(points, anchor_day)
        previous = value_at(points, anchor_day - timedelta(days=7))
        if not current or not previous:
            weekly_values.append(0)
            continue
        change = transformed_change(current[1], previous[1], method)[0]
        score = change / scale * 35 * bond_direction
        weekly_values.append(round(clamp(score), 1))
    return weekly_values, historical_changes


def percentile(values: list[float], current: float) -> int:
    if not values:
        return 50
    return round(sum(value <= current for value in values) / len(values) * 100)


def signal_from_score(score: float, threshold: float) -> str:
    # Classify the same integer strength shown on the page, avoiding cases
    # where +14.7 is displayed as +15 but labelled neutral.
    displayed_score = round(score)
    if displayed_score >= threshold:
        return "bullish"
    if displayed_score <= -threshold:
        return "bearish"
    return "neutral"


def signal_counts(scores: list[float], threshold: float) -> dict[str, int]:
    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    for score in scores:
        counts[signal_from_score(score, threshold)] += 1
    return counts


def stable_seed(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:12], 16)


def mock_fetcher(
    indicator: dict[str, Any],
    series: dict[str, Any],
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    seed = stable_seed(f"{indicator['category']}:{series['code']}")
    rng = random.Random(seed)
    frequency = indicator["frequency"]
    step = 7 if frequency == "weekly" else 1
    unit = indicator.get("unit", "")
    if unit == "%":
        base = 20 + seed % 600 / 10
    elif unit in {"亿元", "架次", "套", "万吨", "万㎡", "万TEU"}:
        base = 80 + seed % 900
    elif "元/" in unit:
        base = 300 + seed % 6000
    elif "美元/" in unit:
        base = 55 + seed % 140
    else:
        base = 80 + seed % 180

    category_bias = {
        "liquidity": -0.07,
        "consumption": -0.12,
        "real_estate": -0.28,
        "infrastructure": 0.08,
        "production": 0.05,
        "inventory": 0.1,
        "prices": 0.14,
        "trade": -0.08,
        "fx": 0.04,
    }.get(indicator["category"], 0)

    records: list[dict[str, Any]] = []
    current = start_date
    index = 0
    value = float(base)
    while current <= end_date:
        if frequency == "daily" and current.weekday() >= 5:
            current += timedelta(days=1)
            continue
        seasonal = math.sin(index / 17 + seed % 13) * base * 0.006
        recent = category_bias * base * max(0, (index - 250) / 1800)
        noise = rng.gauss(0, base * (0.006 if frequency == "daily" else 0.014))
        value = max(0.01, value + seasonal * 0.04 + recent + noise)
        records.append({"date": current.isoformat(), "value": round(value, 4)})
        current += timedelta(days=step)
        index += 1
    return records


def get_fetcher(adapter: str) -> Callable[..., list[dict[str, Any]]]:
    if adapter == "mock":
        return mock_fetcher
    if adapter not in {"http", "custom", "hybrid"}:
        raise ValueError(f"不支持的数据适配器: {adapter}")
    module = importlib.import_module(f"scripts.adapters.{adapter}_adapter")
    return module.fetch_series


def build_indicator(
    definition: dict[str, Any],
    fetcher: Callable[..., list[dict[str, Any]]],
    start_date: date,
    end_date: date,
    evaluation_dates: list[date],
    threshold: float,
) -> dict[str, Any] | None:
    components: list[tuple[list[Point], float]] = []
    for series in definition["series"]:
        records = fetcher(definition, series, start_date, end_date)
        points = normalize_records(records)
        if points:
            components.append((points, float(series.get("weight", 1))))
    points = aggregate_points(definition, components)
    if len(points) < 2:
        return None

    latest_day, latest_value = points[-1]
    previous = value_at(points, latest_day - timedelta(days=7))
    if not previous:
        return None
    previous_value = previous[1]
    method = definition.get("transform", "pct_change")
    change, change_label = transformed_change(latest_value, previous_value, method)
    scores, _ = weekly_scores(
        points,
        evaluation_dates,
        method,
        float(definition.get("bond_direction", -1)),
    )
    score = scores[-1] if scores else 0
    signal = signal_from_score(score, threshold)
    direction_word = "上升" if change > 0 else "下降" if change < 0 else "持平"
    signal_word = {"bullish": "利多", "bearish": "利空", "neutral": "中性"}[signal]
    stale_days = (end_date - latest_day).days
    stale_limit = 10 if definition["frequency"] == "weekly" else 4

    return {
        "id": definition["id"],
        "category": definition["category"],
        "family": definition["family"],
        "name": definition["name"],
        "frequency": "周频" if definition["frequency"] == "weekly" else "日频",
        "unit": definition.get("unit", ""),
        "latest": round(latest_value, 4),
        "previous": round(previous_value, 4),
        "change": round(change, 4),
        "changeLabel": f"近1周 {change_label}",
        "signal": signal,
        "score": round(score, 1),
        "percentile": percentile([value for _, value in points], latest_value),
        "updatedAt": latest_day.isoformat(),
        "source": definition.get("source", ""),
        "core": bool(definition.get("core", True)),
        "weight": float(definition.get("weight", 1)),
        "fresh": stale_days <= stale_limit,
        "reason": (
            f"近一周指标{direction_word}{abs(change):.2f}"
            f"{'个百分点' if method == 'pp_change' else '%'}；"
            f"以零变化为方向中轴并按历史波动校准后，当前对债市{signal_word}。"
        ),
        "history": scores,
        "series": [
            {"date": day.isoformat(), "value": round(value, 4)}
            for day, value in points
        ],
        "methodology": methodology_for(definition),
    }


def weighted_mean(items: list[tuple[float, float]]) -> float:
    if not items:
        return 0
    denominator = sum(weight for _, weight in items)
    if denominator == 0:
        return 0
    return sum(value * weight for value, weight in items) / denominator


def scores_by_family(
    indicators: list[dict[str, Any]], history_index: int | None = None
) -> dict[str, float]:
    families: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for indicator in indicators:
        if not indicator["core"]:
            continue
        value = (
            indicator["score"]
            if history_index is None
            else indicator["history"][history_index]
        )
        families[indicator["family"]].append((value, indicator["weight"]))
    return {family: weighted_mean(values) for family, values in families.items()}


def aggregate_by_family(
    indicators: list[dict[str, Any]], history_index: int | None = None
) -> float:
    family_scores = list(scores_by_family(indicators, history_index).values())
    return statistics.fmean(family_scores) if family_scores else 0


def category_title(category_scores: list[dict[str, Any]], overall_score: float) -> str:
    if overall_score >= 35:
        prefix = "增长与价格信号偏弱，债市环境较友好"
    elif overall_score >= 15:
        prefix = "宏观动能温和偏弱，债市略占优"
    elif overall_score <= -35:
        prefix = "增长与价格压力共振，债市面临逆风"
    elif overall_score <= -15:
        prefix = "宏观动能边际回升，债市略承压"
    else:
        prefix = "宏观信号分化，债市方向暂不明确"
    return prefix


def weekly_evaluation_dates(start_date: date, end_date: date) -> list[date]:
    """Return every Friday in the requested inclusive date range."""
    if start_date > end_date:
        raise ValueError("历史起始日不能晚于结束日")
    first_friday = start_date + timedelta(days=(4 - start_date.weekday()) % 7)
    last_friday = end_date - timedelta(days=(end_date.weekday() - 4) % 7)
    if first_friday > last_friday:
        return []
    week_count = (last_friday - first_friday).days // 7 + 1
    return [first_friday + timedelta(days=7 * offset) for offset in range(week_count)]


def build_dashboard(
    config: dict[str, Any],
    adapter: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    threshold = float(config.get("score_threshold", 15))
    configured_start = date.fromisoformat(
        str(config.get("history_start_date", start_date.isoformat()))
    )
    evaluation_start = max(start_date, configured_start)
    evaluation_dates = weekly_evaluation_dates(evaluation_start, end_date)
    if not evaluation_dates:
        raise ValueError("历史区间内没有可用的周五评价日")
    fetcher = get_fetcher(adapter)
    indicators: list[dict[str, Any]] = []
    failures: list[str] = []

    for definition in config["indicators"]:
        try:
            indicator = build_indicator(
                definition,
                fetcher,
                start_date,
                end_date,
                evaluation_dates,
                threshold,
            )
            if indicator:
                indicators.append(indicator)
            else:
                failures.append(f"{definition['id']}: 无有效数据")
        except Exception as error:  # continue other indicators on one API failure
            failures.append(f"{definition['id']}: {error}")

    if not indicators:
        raise RuntimeError("没有任何指标成功更新：" + "; ".join(failures[:10]))

    categories: list[dict[str, Any]] = []
    for category in config["categories"]:
        category_indicators = [
            item for item in indicators if item["category"] == category["id"]
        ]
        expected = [
            item for item in config["indicators"] if item["category"] == category["id"]
        ]
        category_core = [item for item in category_indicators if item["core"]]
        expected_core = [item for item in expected if item.get("core", True)]
        weekly = [
            round(aggregate_by_family(category_indicators, index), 1)
            for index in range(len(evaluation_dates))
        ]
        score = weekly[-1] if weekly else 0
        family_scores = list(scores_by_family(category_indicators).values())
        family_signal_counts = signal_counts(family_scores, threshold)
        bullish = family_signal_counts["bullish"]
        bearish = family_signal_counts["bearish"]
        neutral = family_signal_counts["neutral"]
        directional_count = bullish + bearish
        breadth = (
            round(bullish / directional_count * 100)
            if directional_count
            else 50
        )
        fresh = sum(item["fresh"] for item in category_core)
        confidence = round(
            100
            * len(category_core)
            / max(1, len(expected_core))
            * fresh
            / max(1, len(category_core))
        )
        latest_day = max(
            (item["updatedAt"] for item in category_indicators),
            default=end_date.isoformat(),
        )
        categories.append(
            {
                "id": category["id"],
                "name": category["name"],
                "code": category["code"],
                "score": round(score, 1),
                "signal": signal_from_score(score, threshold),
                "breadth": breadth,
                "breadthDetail": {
                    "bullish": bullish,
                    "bearish": bearish,
                    "neutral": neutral,
                    "total": len(family_scores),
                },
                "confidence": confidence,
                "updatedAt": latest_day,
                "summary": category["summary"],
                "validCount": len(category_core),
                "totalCount": len(expected_core),
                "weeklyScores": weekly,
                "weight": float(category.get("weight", 1)),
            }
        )

    overall_score = weighted_mean(
        [(category["score"], category["weight"]) for category in categories]
    )
    overall_weekly = [
        round(
            weighted_mean(
                [
                    (category["weeklyScores"][index], category["weight"])
                    for category in categories
                ]
            ),
            1,
        )
        for index in range(len(evaluation_dates))
    ]
    overall_signal = signal_from_score(overall_score, threshold)
    category_signal_counts = signal_counts(
        [category["score"] for category in categories], threshold
    )
    bullish_categories = category_signal_counts["bullish"]
    bearish_categories = category_signal_counts["bearish"]
    neutral_categories = category_signal_counts["neutral"]
    directional_categories = bullish_categories + bearish_categories
    overall_breadth = (
        round(bullish_categories / directional_categories * 100)
        if directional_categories
        else 50
    )
    confidence = round(statistics.fmean(item["confidence"] for item in categories))
    freshness = round(
        sum(item["fresh"] for item in indicators) / max(1, len(indicators)) * 100
    )
    supportive = sorted(categories, key=lambda item: item["score"], reverse=True)[:2]
    headwinds = sorted(categories, key=lambda item: item["score"])[:2]
    narrative = (
        f"{'、'.join(item['name'] for item in supportive)}对债市相对友好；"
        f"{'、'.join(item['name'] for item in headwinds)}构成主要反向力量。"
        "信号先在指标族内合成，再对九大类等权汇总。"
    )

    clean_indicators = []
    for item in indicators:
        clean_indicators.append(
            {key: value for key, value in item.items() if key not in {"weight", "fresh"}}
        )
    clean_categories = []
    for item in categories:
        clean_categories.append(
            {key: value for key, value in item.items() if key != "weight"}
        )

    if failures:
        print("以下指标未更新：", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mode": {
            "mock": "示例数据",
            "http": "HTTP接口",
            "custom": "自定义接口",
            "hybrid": "CJHX+iFinD生产数据",
        }[adapter],
        "dates": [day.isoformat() for day in evaluation_dates],
        "overall": {
            "score": round(overall_score, 1),
            "signal": overall_signal,
            "weeklyScores": overall_weekly,
            "title": category_title(categories, overall_score),
            "narrative": narrative,
            "breadth": overall_breadth,
            "breadthDetail": {
                "bullish": bullish_categories,
                "bearish": bearish_categories,
                "neutral": neutral_categories,
                "total": len(categories),
            },
            "confidence": confidence,
            "freshness": freshness,
        },
        "categories": clean_categories,
        "indicators": clean_indicators,
    }


def load_auxiliary_indicators(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    definitions: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
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
    return definitions


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--auxiliary", type=Path, default=DEFAULT_AUXILIARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--adapter",
        choices=["mock", "http", "custom", "hybrid"],
        default=os.environ.get("MACRO_DATA_ADAPTER", "mock"),
    )
    parser.add_argument("--days", type=int, default=600)
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    config["indicators"].extend(load_auxiliary_indicators(args.auxiliary))
    requested_start = args.end_date - timedelta(days=args.days)
    configured_start = date.fromisoformat(
        str(config.get("history_start_date", requested_start.isoformat()))
    )
    start_date = min(requested_start, configured_start)
    dashboard = build_dashboard(config, args.adapter, start_date, args.end_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dashboard, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"已生成 {args.output}："
        f"{len(dashboard['categories'])} 个分类，"
        f"{len(dashboard['indicators'])} 个指标"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
