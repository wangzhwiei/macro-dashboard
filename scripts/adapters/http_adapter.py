from __future__ import annotations

import json
import os
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("接口响应必须是数组或JSON对象")
    for key in ("data", "records", "rows", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    dates, values = payload.get("dates"), payload.get("values")
    if isinstance(dates, list) and isinstance(values, list):
        return [{"date": day, "value": value} for day, value in zip(dates, values)]
    raise ValueError("接口响应中未找到 data/records/rows/result 或 dates+values")


def fetch_series(
    indicator: dict[str, Any],
    series: dict[str, Any],
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    base_url = os.environ.get("MACRO_API_URL", "").strip()
    if not base_url:
        raise RuntimeError("MACRO_API_URL 未配置")

    query = urlencode(
        {
            "code": series["code"],
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "frequency": indicator["frequency"],
        }
    )
    separator = "&" if "?" in base_url else "?"
    headers = {"Accept": "application/json"}
    api_key = os.environ.get("MACRO_API_KEY", "")
    if api_key:
        header_name = os.environ.get("MACRO_API_AUTH_HEADER", "Authorization")
        prefix = os.environ.get("MACRO_API_AUTH_PREFIX", "Bearer").strip()
        headers[header_name] = f"{prefix} {api_key}".strip()

    request = Request(f"{base_url}{separator}{query}", headers=headers)
    with urlopen(request, timeout=45) as response:
        payload = json.load(response)

    date_field = os.environ.get("MACRO_API_DATE_FIELD", "date")
    value_field = os.environ.get("MACRO_API_VALUE_FIELD", "value")
    records = _extract_records(payload)
    return [
        {"date": str(record[date_field])[:10], "value": float(record[value_field])}
        for record in records
        if record.get(date_field) is not None and record.get(value_field) is not None
    ]
