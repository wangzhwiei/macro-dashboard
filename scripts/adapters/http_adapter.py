from __future__ import annotations

import json
import os
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts.adapters.common import resolve_series_code


def _extract_records(payload: Any, data_path: str = "") -> list[dict[str, Any]]:
    if data_path:
        current = payload
        for part in data_path.split("."):
            if not isinstance(current, dict) or part not in current:
                raise ValueError(f"接口响应中未找到 MACRO_API_DATA_PATH={data_path}")
            current = current[part]
        payload = current
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

    params = {
        os.environ.get("MACRO_API_CODE_PARAM", "code"): resolve_series_code(series),
        os.environ.get("MACRO_API_START_PARAM", "start_date"): start_date.isoformat(),
        os.environ.get("MACRO_API_END_PARAM", "end_date"): end_date.isoformat(),
        os.environ.get("MACRO_API_FREQUENCY_PARAM", "frequency"): indicator[
            "frequency"
        ],
    }
    headers = {"Accept": "application/json"}
    extra_headers = os.environ.get("MACRO_API_HEADERS_JSON", "").strip()
    if extra_headers:
        parsed_headers = json.loads(extra_headers)
        if not isinstance(parsed_headers, dict):
            raise ValueError("MACRO_API_HEADERS_JSON 必须是JSON对象")
        headers.update({str(key): str(value) for key, value in parsed_headers.items()})
    api_key = os.environ.get("MACRO_API_KEY", "")
    if api_key:
        header_name = os.environ.get("MACRO_API_AUTH_HEADER", "Authorization")
        prefix = os.environ.get("MACRO_API_AUTH_PREFIX", "Bearer").strip()
        headers[header_name] = f"{prefix} {api_key}".strip()

    method = os.environ.get("MACRO_API_METHOD", "GET").strip().upper()
    if method == "POST":
        headers.setdefault("Content-Type", "application/json")
        request = Request(
            base_url,
            data=json.dumps(params).encode("utf-8"),
            headers=headers,
            method="POST",
        )
    elif method == "GET":
        query = urlencode(params)
        separator = "&" if "?" in base_url else "?"
        request = Request(f"{base_url}{separator}{query}", headers=headers)
    else:
        raise ValueError("MACRO_API_METHOD 仅支持 GET 或 POST")

    with urlopen(request, timeout=45) as response:
        payload = json.load(response)

    date_field = os.environ.get("MACRO_API_DATE_FIELD", "date")
    value_field = os.environ.get("MACRO_API_VALUE_FIELD", "value")
    records = _extract_records(
        payload,
        os.environ.get("MACRO_API_DATA_PATH", "").strip(),
    )
    return [
        {"date": str(record[date_field])[:10], "value": float(record[value_field])}
        for record in records
        if record.get(date_field) is not None and record.get(value_field) is not None
    ]
