"""Hybrid adapter: public CJHX CSV first, iFinD EDB only for configured gaps."""

from __future__ import annotations

import csv
import importlib.util
import json
import logging
import math
import os
import re
import time
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
CJHX_DATA_URL = os.environ.get(
    "CJHX_DATA_URL",
    "https://raw.githubusercontent.com/wangzhwiei/macro-data/main/"
    "macro_extract_70_results.csv",
)
CJHX_MAP_PATH = ROOT / "config" / "cjhx-series-map.json"
IFIND_MAP_PATH = ROOT / "config" / "ifind-series.csv"
CACHE_DIR = Path(os.environ.get("MACRO_DATA_CACHE_DIR", ROOT / "data_cache"))
IFIND_SKILL_DIR = Path(
    os.environ.get(
        "IFIND_SKILL_DIR",
        "/home/wangzhiwei202307/.openclaw/workspace/skills/"
        "ifind-finance-data/ifind-finance-data",
    )
)

_cjhx_index: dict[str, list[dict[str, Any]]] | None = None
_ifind_call: Callable[..., dict[str, Any]] | None = None


def _parse_day(value: Any) -> date:
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text[:10])


def _load_cjhx_map() -> dict[str, dict[str, Any]]:
    return json.loads(CJHX_MAP_PATH.read_text(encoding="utf-8"))


def _load_ifind_map() -> dict[str, dict[str, str]]:
    with IFIND_MAP_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["semantic_code"]: row for row in csv.DictReader(handle)}


def _cache_path(semantic_code: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", semantic_code)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{safe}.json"


def _load_cache(semantic_code: str) -> tuple[list[dict[str, Any]], str | None]:
    path = _cache_path(semantic_code)
    if not path.exists():
        return [], None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload, None
    return payload.get("records", []), payload.get("last_checked_date")


def _save_cache(
    semantic_code: str,
    records: list[dict[str, Any]],
    last_checked_date: str | None = None,
) -> None:
    payload: object = records
    if last_checked_date is not None:
        payload = {"records": records, "last_checked_date": last_checked_date}
    _cache_path(semantic_code).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _merge_records(
    existing: list[dict[str, Any]], new_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = {str(item["date"]): float(item["value"]) for item in existing}
    for item in new_records:
        merged[str(item["date"])] = float(item["value"])
    return [
        {"date": day, "value": value}
        for day, value in sorted(merged.items())
        if math.isfinite(value)
    ]


def _cache_busted_url(url: str, nonce: int | None = None) -> str:
    separator = "&" if "?" in url else "?"
    value = int(time.time()) if nonce is None else nonce
    return f"{url}{separator}cache_bust={value}"


def _download_cjhx_csv() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / "macro_extract_70_results.csv"
    # The upstream file is already an incremental consolidated snapshot and is
    # downloaded only once per process. Reusing it across daily runs silently
    # froze all CJHX-backed indicators at the date of the first local cache.
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(
            _cache_busted_url(CJHX_DATA_URL, int(time.time()) + attempt),
            headers={
                "User-Agent": "macro-dashboard-data-pipeline/1.0",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = response.read()
            if len(payload) < 1000:
                raise RuntimeError("CJHX CSV下载内容异常小")
            temporary = cached.with_suffix(".csv.tmp")
            temporary.write_bytes(payload)
            temporary.replace(cached)
            return cached
        except Exception as error:
            last_error = error
            if attempt < 2:
                logger.warning("CJHX远程CSV第%d次下载失败，将重试：%s", attempt + 1, error)
                time.sleep(2 * (attempt + 1))
    if not cached.exists():
        raise RuntimeError(f"CJHX远程CSV下载失败：{last_error}") from last_error
    logger.warning(
        "CJHX远程CSV下载失败，使用本地缓存：%s (%s)",
        cached,
        last_error,
    )
    return cached


def _get_cjhx_index() -> dict[str, list[dict[str, Any]]]:
    global _cjhx_index
    if _cjhx_index is not None:
        return _cjhx_index

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with _download_cjhx_csv().open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("error", "").strip():
                raise RuntimeError(
                    f"CJHX供应商错误：{row.get('series_key')} {row.get('date')} "
                    f"{row.get('error')}"
                )
            try:
                day = _parse_day(row["date"])
                value = float(row["value"])
            except (KeyError, TypeError, ValueError):
                raise RuntimeError(f"CJHX CSV含非法记录：{row}") from None
            if not math.isfinite(value):
                raise RuntimeError(f"CJHX CSV含非有限数值：{row}")
            grouped[row["series_key"]].append(
                {"date": day.isoformat(), "value": value}
            )

    _cjhx_index = {
        key: _merge_records([], records) for key, records in grouped.items()
    }
    return _cjhx_index


def _fetch_cjhx(
    semantic_code: str, start_date: date, end_date: date
) -> list[dict[str, Any]]:
    metadata = _load_cjhx_map()[semantic_code]
    series_key = metadata["series_key"]
    scale = float(metadata.get("scale", 1))
    excluded = set(metadata.get("exclude_dates", []))
    records = _get_cjhx_index().get(series_key, [])
    if not records:
        raise RuntimeError(f"CJHX CSV缺少series_key={series_key}")
    return [
        {"date": item["date"], "value": float(item["value"]) * scale}
        for item in records
        if start_date <= date.fromisoformat(item["date"]) <= end_date
        and item["date"] not in excluded
    ]


def _get_ifind_call() -> Callable[..., dict[str, Any]]:
    global _ifind_call
    if _ifind_call is not None:
        return _ifind_call
    module_path = IFIND_SKILL_DIR / "call.py"
    if not module_path.exists():
        raise RuntimeError(
            "找不到iFinD调用模块；请设置IFIND_SKILL_DIR指向含call.py和mcp_config.json的目录"
        )
    spec = importlib.util.spec_from_file_location("macro_dashboard_ifind_call", module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"无法加载iFinD调用模块：{module_path}")
    module = importlib.util.module_from_spec(spec)
    previous = Path.cwd()
    try:
        os.chdir(IFIND_SKILL_DIR)
        spec.loader.exec_module(module)
    finally:
        os.chdir(previous)
    _ifind_call = module.call
    return _ifind_call


def _extract_ifind_payload(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        raise RuntimeError(f"iFinD EDB请求失败：{result.get('error')}")
    envelope = result.get("data", {})
    content = envelope.get("result", {}).get("content", [])
    if not content or not isinstance(content[0], dict):
        raise RuntimeError("iFinD EDB响应缺少result.content")
    text = content[0].get("text", "")
    payload = json.loads(text) if isinstance(text, str) else text
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError(f"iFinD EDB响应缺少data对象：{payload}")
    return data


UNIT_FACTORS: dict[str, tuple[str, float]] = {
    "元": ("currency", 1.0),
    "万元": ("currency", 1e4),
    "亿元": ("currency", 1e8),
    "万亿元": ("currency", 1e12),
    "桶": ("barrel", 1.0),
    "千桶": ("barrel", 1e3),
    "万桶": ("barrel", 1e4),
    "吨": ("tonne", 1.0),
    "千吨": ("tonne", 1e3),
    "万吨": ("tonne", 1e4),
}


def _convert_provider_unit(value: float, returned_unit: str, expected_unit: str) -> float:
    if not returned_unit or not expected_unit or returned_unit == expected_unit:
        return value
    if expected_unit == "指数" and "=100" in returned_unit:
        return value
    returned = UNIT_FACTORS.get(returned_unit)
    expected = UNIT_FACTORS.get(expected_unit)
    if not returned or not expected or returned[0] != expected[0]:
        raise RuntimeError(f"iFinD单位漂移：期望{expected_unit!r}，实际{returned_unit!r}")
    return value * returned[1] / expected[1]


def _parse_ifind_records(
    data: dict[str, Any],
    expected_id: str,
    start_date: date,
    end_date: date,
    expected_unit: str = "",
) -> list[dict[str, Any]]:
    observed_ids: set[str] = set()
    extra = data.get("extra", {})
    if isinstance(extra, dict) and extra.get("index_id"):
        observed_ids.add(str(extra["index_id"]))

    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in data.get("datas", []):
        container = item.get("data", {}) if isinstance(item, dict) else {}
        attrs = container.get("attrs", {}) if isinstance(container, dict) else {}
        expected_metadata = []
        for metadata in attrs.values() if isinstance(attrs, dict) else []:
            if isinstance(metadata, dict) and metadata.get("index_id"):
                provider_id = str(metadata["index_id"])
                observed_ids.add(provider_id)
                if provider_id == expected_id:
                    expected_metadata.append(metadata)
        if expected_metadata:
            if len(expected_metadata) != 1:
                raise RuntimeError(f"iFinD固定ID {expected_id} 在单个候选中重复")
            matches.append((container, expected_metadata[0]))

    if len(matches) != 1:
        raise RuntimeError(
            f"iFinD模糊匹配漂移：期望{expected_id}唯一命中，实际{sorted(observed_ids)}"
        )

    container, metadata = matches[0]
    returned_unit = str(metadata.get("unit") or "")
    records: dict[str, float] = {}
    points = container.get("data", []) if isinstance(container, dict) else []
    for point in points:
        if not isinstance(point, list) or len(point) < 2 or point[1] is None:
            continue
        try:
            day = _parse_day(point[0])
            value = _convert_provider_unit(float(point[1]), returned_unit, expected_unit)
        except (TypeError, ValueError):
            continue
        if start_date <= day <= end_date and math.isfinite(value):
            records[day.isoformat()] = value
    if not records:
        raise RuntimeError(f"iFinD {expected_id} 未返回可用数据")
    return [{"date": day, "value": value} for day, value in sorted(records.items())]


def _harmonize_legacy_cache_units(
    cached: list[dict[str, Any]], fresh: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Rescale legacy cache when an overlapping provider window proves a unit switch."""
    old = {str(item["date"]): float(item["value"]) for item in cached}
    ratios = [
        old[str(item["date"])] / float(item["value"])
        for item in fresh
        if str(item["date"]) in old and abs(float(item["value"])) > 1e-12
    ]
    if len(ratios) < 3:
        return cached
    ratios.sort()
    median_ratio = ratios[len(ratios) // 2]
    if median_ratio <= 0:
        return cached
    factors = (1e-6, 1e-4, 1e-3, 1e-2, 1e-1, 10.0, 100.0, 1e3, 1e4, 1e6)
    factor = min(factors, key=lambda value: abs(math.log10(median_ratio / value)))
    if abs(median_ratio / factor - 1.0) > 0.05:
        return cached
    return [
        {"date": str(item["date"]), "value": float(item["value"]) / factor}
        for item in cached
    ]


def _fetch_ifind(
    semantic_code: str, start_date: date, end_date: date
) -> list[dict[str, Any]]:
    metadata = _load_ifind_map()[semantic_code]
    cached, last_checked_date = _load_cache(semantic_code)
    if (
        cached
        and last_checked_date
        and last_checked_date >= end_date.isoformat()
    ):
        return [
            item
            for item in cached
            if start_date <= date.fromisoformat(item["date"]) <= end_date
        ]
    if cached and os.environ.get("IFIND_CACHE_ONLY", "").lower() in {"1", "true", "yes"}:
        return [
            item
            for item in cached
            if start_date <= date.fromisoformat(item["date"]) <= end_date
        ]
    if cached:
        latest = date.fromisoformat(cached[-1]["date"])
        # Re-query an overlap so provider revisions, delayed observations and
        # transient bad values can be corrected instead of becoming permanent.
        fetch_start = max(start_date, latest - timedelta(days=35))
        if fetch_start > end_date:
            return [
                item
                for item in cached
                if start_date <= date.fromisoformat(item["date"]) <= end_date
            ]
    else:
        fetch_start = start_date

    query = (
        f"{metadata['query_name']}"
        f"（{fetch_start.isoformat()}至{end_date.isoformat()}）"
    )
    fresh = None
    last_error = None
    for attempt in range(3):
        try:
            result = _get_ifind_call()("edb", "get_edb_data", {"query": query})
            data = _extract_ifind_payload(result)
            fresh = _parse_ifind_records(
                data,
                metadata["provider_id"],
                fetch_start,
                end_date,
                str(metadata.get("raw_unit") or ""),
            )
            break
        except Exception as error:
            last_error = error
            if "模糊匹配漂移" in str(error):
                if cached and os.environ.get("MACRO_INCREMENTAL", "").lower() in {
                    "1",
                    "true",
                    "yes",
                }:
                    logger.warning(
                        "iFinD provider ID drift; retaining validated cache: %s (%s)",
                        semantic_code,
                        error,
                    )
                    _save_cache(semantic_code, cached, end_date.isoformat())
                    return [
                        item
                        for item in cached
                        if start_date <= date.fromisoformat(item["date"]) <= end_date
                    ]
                raise
            if cached and "未返回可用数据" in str(error):
                logger.info(
                    "iFinD增量区间无新观测，记录当天检查：%s",
                    semantic_code,
                )
                _save_cache(semantic_code, cached, end_date.isoformat())
                return [
                    item
                    for item in cached
                    if start_date <= date.fromisoformat(item["date"]) <= end_date
                ]
            if attempt == 2:
                if cached:
                    logger.info(
                        "iFinD增量区间无新观测，保留已验证缓存：%s (%s)",
                        semantic_code,
                        error,
                    )
                    return [
                        item
                        for item in cached
                        if start_date <= date.fromisoformat(item["date"]) <= end_date
                    ]
                raise
            logger.warning(
                "iFinD查询第%d次失败，将重试：%s (%s)",
                attempt + 1,
                semantic_code,
                error,
            )
            time.sleep(2 * (attempt + 1))
    if fresh is None:
        raise RuntimeError(f"iFinD查询失败：{semantic_code}: {last_error}")
    scale = float(metadata.get("scale") or 1)
    fresh = [
        {"date": item["date"], "value": float(item["value"]) * scale}
        for item in fresh
    ]
    cached = _harmonize_legacy_cache_units(cached, fresh)
    merged = _merge_records(cached, fresh)
    _save_cache(semantic_code, merged, end_date.isoformat())
    return [
        item
        for item in merged
        if start_date <= date.fromisoformat(item["date"]) <= end_date
    ]


def fetch_series(
    indicator: dict[str, Any],
    series: dict[str, Any],
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Return normalized records for one semantic series."""
    del indicator
    semantic_code = str(series["code"])
    if semantic_code in _load_cjhx_map():
        return _fetch_cjhx(semantic_code, start_date, end_date)
    if semantic_code in _load_ifind_map():
        return _fetch_ifind(semantic_code, start_date, end_date)
    raise RuntimeError(f"未配置数据源路由：{semantic_code}")
