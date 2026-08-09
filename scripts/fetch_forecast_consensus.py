#!/usr/bin/env python3
"""Fetch public survey consensus for China CPI, PPI and official PMI.

The public calendar exposes survey ``Consensus`` and the provider's own
``TEForecast`` in adjacent columns. This parser deliberately accepts only the
survey column and validates the event name/category before updating the cache.
"""

from __future__ import annotations

import calendar
import json
import re
import time
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "forecast-model" / "consensus.json"
SOURCE = "Trading Economics public calendar"
CONFIG = {
    "cpi": {
        "url": "https://tradingeconomics.com/china/inflation-cpi",
        "category": "Inflation Rate",
        "event": "Inflation Rate YoY",
        "unit": "%",
    },
    "ppi": {
        "url": "https://tradingeconomics.com/china/producer-prices-change",
        "category": "Producer Prices Change",
        "event": "PPI YoY",
        "unit": "%",
    },
    "pmi": {
        "url": "https://tradingeconomics.com/china/business-confidence",
        "category": "Business Confidence",
        "event": "NBS Manufacturing PMI",
        "unit": "点",
    },
}
MONTHS = {name: number for number, name in enumerate(calendar.month_abbr) if name}


class CalendarTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self._row: dict[str, Any] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "tr" and values.get("data-id"):
            self._row = {"attrs": values, "cells": []}
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row["cells"].append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None


def parse_number(raw: str) -> float | None:
    cleaned = raw.strip().replace(",", "").replace("%", "")
    if not cleaned:
        return None
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cleaned):
        raise ValueError(f"无法解析数值：{raw!r}")
    return float(cleaned)


def reference_month(release_date: str, reference: str) -> str:
    released = date.fromisoformat(release_date)
    month = MONTHS.get(reference[:3].title())
    if month is None:
        raise ValueError(f"无法解析参考月份：{reference!r}")
    year = released.year - 1 if month > released.month + 1 else released.year
    return date(year, month, calendar.monthrange(year, month)[1]).isoformat()


def parse_consensus(html: str, config: dict[str, str], retrieved_at: str) -> list[dict[str, Any]]:
    parser = CalendarTableParser()
    parser.feed(html)
    records: list[dict[str, Any]] = []
    for row in parser.rows:
        attrs, cells = row["attrs"], row["cells"]
        if attrs.get("data-country") != "China" or attrs.get("data-category") != config["category"]:
            continue
        if len(cells) < 8 or cells[2] != config["event"]:
            continue
        consensus = parse_number(cells[6])
        if consensus is None:
            continue
        records.append({
            "date": reference_month(cells[0], cells[3]),
            "value": consensus,
            "source": SOURCE,
            "sourceUrl": config["url"],
            "eventId": attrs["data-id"],
            "event": config["event"],
            "releaseDate": cells[0],
            "reference": cells[3],
            "actualAtFetch": parse_number(cells[4]),
            "previousAtFetch": parse_number(cells[5]),
            "retrievedAt": retrieved_at,
        })
    return sorted(records, key=lambda item: item["date"])


def fetch_page(url: str, attempts: int = 3) -> str:
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 macro-dashboard-personal-research/1.0"})
            with urlopen(request, timeout=25) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                return response.read().decode("utf-8", errors="replace")
        except Exception as caught:  # pragma: no cover - depends on network
            error = caught
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"公开日历请求失败：{url} ({error})")


def merge_records(existing: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_month = {item["date"]: item for item in existing if item.get("date") and item.get("value") is not None}
    by_month.update({item["date"]: item for item in fresh})
    return [by_month[key] for key in sorted(by_month)]


def main() -> int:
    retrieved_at = datetime.now().astimezone().isoformat()
    existing = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    result: dict[str, Any] = {"_meta": {
        "source": SOURCE,
        "retrievedAt": retrieved_at,
        "usage": "personal research",
        "field": "Consensus (survey); TEForecast is explicitly excluded",
    }}
    for key, config in CONFIG.items():
        records = parse_consensus(fetch_page(config["url"]), config, retrieved_at)
        if not records:
            raise RuntimeError(f"{key.upper()} 未找到经严格匹配的一致预期，缓存未覆盖")
        result[key] = merge_records(existing.get(key, []), records)
        latest = records[-1]
        print(f"{key.upper()} 一致预期已核验：{latest['date']}={latest['value']} event={latest['eventId']}")

    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(OUTPUT)
    print("仅写入市场调查 Consensus 列；已明确排除 TEForecast。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())