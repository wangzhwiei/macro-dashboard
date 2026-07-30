#!/usr/bin/env python3
"""
增量数据更新脚本 — 只拉取新增数据点，合并历史缓存。

用法：
  python scripts/incremental_update.py [--days 30] [--end-date 2026-07-31]

增量缓存目录: data_cache/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "indicators.json"
DEFAULT_AUXILIARY = ROOT / "config" / "auxiliary-indicators.csv"
DEFAULT_OUTPUT = ROOT / "public" / "data" / "dashboard.json"
CACHE_DIR = ROOT / "data_cache"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def load_auxiliary_indicators(aux_path: Path) -> list[dict[str, Any]]:
    """Load auxiliary indicators from CSV."""
    definitions = []
    if not aux_path.exists():
        return definitions
    import csv
    with aux_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            definitions.append({
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
            })
    return definitions


def get_series_cache_key(series_code: str) -> str:
    """Generate cache file name for a series."""
    import hashlib
    safe = series_code.replace(":", "_").replace("/", "_").replace(" ", "_")
    return safe + ".json"


def load_cached_series(series_code: str) -> list[dict]:
    """Load cached time series data."""
    cache_file = CACHE_DIR / get_series_cache_key(series_code)
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    return []


def save_cached_series(series_code: str, records: list[dict]) -> None:
    """Save time series data to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / get_series_cache_key(series_code)
    cache_file.write_text(
        json.dumps(records, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def merge_records(existing: list[dict], new_records: list[dict]) -> list[dict]:
    """Merge and deduplicate records, keeping latest value per date."""
    merged = {rec["date"]: rec["value"] for rec in existing}
    for rec in new_records:
        merged[rec["date"]] = rec["value"]
    return [{"date": d, "value": v} for d, v in sorted(merged.items())]


def main() -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--auxiliary", type=Path, default=DEFAULT_AUXILIARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--adapter", default=os.environ.get("MACRO_DATA_ADAPTER", "custom"))
    parser.add_argument("--days", type=int, default=30, help="增量拉取天数（默认30天）")
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--full-scan-days", type=int, default=1300,
                        help="生成面板时使用的历史天数（默认1300天，约3.5年）")
    args = parser.parse_args()

    # Load indicator definitions
    config = json.loads(args.config.read_text(encoding="utf-8"))
    config["indicators"].extend(load_auxiliary_indicators(args.auxiliary))

    # Collect all unique series
    all_series = []
    for indicator in config["indicators"]:
        for series in indicator.get("series", []):
            all_series.append({
                "indicator": indicator,
                "series": series,
            })

    # Import fetcher
    sys.path.insert(0, str(ROOT))
    import importlib
    fetcher = importlib.import_module(f"scripts.adapters.{args.adapter}_adapter").fetch_series

    # Incremental fetch
    end_date = args.end_date
    incremental_start = end_date - timedelta(days=args.days)

    print(f"增量更新: 拉取 {args.days} 天数据 ({incremental_start} ~ {end_date})")
    print(f"共 {len(all_series)} 个序列")

    fetched_count = 0
    for item in all_series:
        semantic_code = item["series"]["code"]
        source = item["indicator"].get("source", "")

        # Load existing cache
        existing = load_cached_series(semantic_code)

        # Determine incremental start (only fetch from last known date)
        if existing:
            last_date = date.fromisoformat(existing[-1]["date"])
            fetch_start = min(last_date + timedelta(days=1), incremental_start)
            if fetch_start > end_date:
                # Already up to date
                continue
        else:
            fetch_start = incremental_start

        # Fetch incremental data
        new_records = fetcher(item["indicator"], item["series"], fetch_start, end_date)

        if new_records:
            merged = merge_records(existing, new_records)
            save_cached_series(semantic_code, merged)
            fetched_count += 1

    print(f"完成: {fetched_count} 个序列有增量数据")

    # Now build dashboard using full historical data from cache
    full_start = end_date - timedelta(days=args.full_scan_days)
    print(f"生成面板: 使用 {args.full_scan_days} 天历史数据 ({full_start} ~ {end_date})")

    from scripts.update_dashboard import build_dashboard
    dashboard = build_dashboard(config, args.adapter, full_start, end_date)

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
