"""Custom adapter for CJHX internal API and iFinD EDB."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from scripts.adapters.common import resolve_series_code

logger = logging.getLogger(__name__)

# ── DNS patch for CJHX internal API ──────────────────────────────────────
_ORIG_GETADDRINFO = socket.getaddrinfo

def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host == "ai.cjhxfund.com":
        host = "10.202.9.103"
    return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)

socket.getaddrinfo = _patched_getaddrinfo

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
CJHX_SCRIPT_DIR = Path("/app/working/workspaces/wangzhiwei/skills/cjhx-cais-bis-skill/scripts")
IFIND_SCRIPT_DIR = Path("/app/working/workspaces/wangzhiwei/skills/iFinD-Finance-Data")
CACHE_DIR = ROOT / "data_cache"

# ── Local persistent cache ────────────────────────────────────────────────

def _cache_key(series_code: str) -> Path:
    safe = series_code.replace(":", "_").replace("/", "_").replace(" ", "_")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / (safe + ".json")


def _load_cache(series_code: str) -> list[dict]:
    path = _cache_key(series_code)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def _save_cache(series_code: str, records: list[dict]) -> None:
    path = _cache_key(series_code)
    path.write_text(
        json.dumps(records, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _merge_records(existing: list[dict], new_records: list[dict]) -> list[dict]:
    merged = {rec["date"]: rec["value"] for rec in existing}
    for rec in new_records:
        merged[rec["date"]] = rec["value"]
    return [{"date": d, "value": v} for d, v in sorted(merged.items())]

# ── CJHX API ──────────────────────────────────────────────────────────────

def _get_cjhx_api_key() -> str:
    """Decrypt and return CJHX API key."""
    from cryptography.fernet import Fernet
    cred_key_path = CJHX_SCRIPT_DIR / ".cred_key"
    cred_enc_path = CJHX_SCRIPT_DIR / ".cred_encrypted"
    if not cred_key_path.exists() or not cred_enc_path.exists():
        raise RuntimeError("CJHX API key files not found")
    key = cred_key_path.read_bytes()
    encrypted = cred_enc_path.read_bytes()
    fernet = Fernet(key)
    return fernet.decrypt(encrypted).decode("utf-8")

def _cjhx_post(endpoint: str, payload: dict) -> Any:
    """Post to CJHX API and return parsed response body."""
    api_key = _get_cjhx_api_key()
    url = "https://10.202.9.103/ai-gateway" + endpoint
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Host": "ai.cjhxfund.com",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=90, verify=False)
    resp.raise_for_status()
    data = resp.json()
    return data.get("body", data)

def _cjhx_fetch_all_macro(start_date: date, end_date: date) -> list[dict]:
    """Fetch ALL macroeconomic indicators for a date range."""
    all_records = []
    page = 1
    page_size = 5000
    
    while True:
        payload = {
            "page": page,
            "pageSize": page_size,
            "startDate": start_date.strftime("%Y%m%d"),
            "endDate": end_date.strftime("%Y%m%d"),
        }
        body = _cjhx_post(
            "/admin/dataquery/execute/cais_dc_macroeconomic_indicators",
            payload
        )
        
        records = body if isinstance(body, list) else []
        if not records:
            break
        
        all_records.extend(records)
        
        if len(records) < page_size:
            break
        page += 1
        time.sleep(0.5)
    
    parsed = []
    for rec in all_records:
        if not isinstance(rec, dict):
            continue
        f3 = str(rec.get("f3", ""))
        f4 = str(rec.get("f4", ""))
        f1 = str(rec.get("f1", ""))
        f2 = rec.get("f2")
        f5 = rec.get("f5")
        
        try:
            if f2 is None or f5 is None:
                continue
            day_str = str(f2)
            if len(day_str) >= 8:
                day = date(int(day_str[:4]), int(day_str[4:6]), int(day_str[6:8]))
            else:
                continue
            val = float(f5)
        except (ValueError, TypeError):
            continue
        
        parsed.append({
            "code": f3,
            "name": f4,
            "category": f1,
            "date": day.isoformat(),
            "value": val,
        })
    
    return parsed

# ── iFinD EDB ─────────────────────────────────────────────────────────────

def _parse_ifind_markdown_table(text: str) -> list[dict]:
    """Parse iFinD markdown table format.
    
    Format: |日期|指标名|\n|---|---|\n|2026-07-30|1.43|\n...
    Returns list of {"date": str, "value": float}
    """
    records = []
    lines = text.strip().split("\n")
    
    if len(lines) < 3:
        return records
    
    def split_row(line):
        parts = [p.strip() for p in line.split("|")]
        return [p for p in parts if p]
    
    header_parts = split_row(lines[0])
    if not header_parts:
        return records
    
    date_col = 0
    for i, h in enumerate(header_parts):
        if "日期" in h:
            date_col = i
            break
    
    value_col = len(header_parts) - 1 if len(header_parts) > 1 else 0
    
    for line in lines[2:]:
        if not line.strip():
            continue
        parts = split_row(line)
        if len(parts) <= max(date_col, value_col):
            continue
        
        date_str = parts[date_col]
        value_str = parts[value_col]
        
        try:
            if "-" in date_str:
                day = date.fromisoformat(date_str)
            elif len(date_str) == 8 and date_str.isdigit():
                day = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
            else:
                continue
            
            val = float(value_str) if value_str and value_str != "-" else None
            if val is not None:
                records.append({"date": day.isoformat(), "value": val})
        except (ValueError, TypeError):
            continue
    
    return records


def _parse_ifind_structured_data(datas: list, start_date: date, end_date: date) -> list[dict]:
    """Parse iFinD structured data from datas field.
    
    datas is a list of dicts, each with data.data = [[date_str, value], ...]
    """
    records = []
    
    for item in datas:
        if not isinstance(item, dict):
            continue
        data_chain = item.get("data", {})
        if isinstance(data_chain, dict):
            data_array = data_chain.get("data", [])
        else:
            data_array = data_chain
        
        if not isinstance(data_array, list):
            continue
        
        for point in data_array:
            if not isinstance(point, list) or len(point) < 2:
                continue
            try:
                date_str = str(point[0])
                if "-" in date_str:
                    day = date.fromisoformat(date_str)
                elif len(date_str) == 8 and date_str.isdigit():
                    day = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
                else:
                    continue
                
                if day < start_date or day > end_date:
                    continue
                
                val = float(point[1]) if point[1] is not None else None
                if val is not None:
                    records.append({"date": day.isoformat(), "value": val})
            except (ValueError, TypeError):
                continue
    
    return records

def _ifind_get_edb(query_str: str, start_date: date, end_date: date) -> list[dict]:
    """Fetch data from iFinD EDB.
    
    iFinD EDB returns data in markdown table format nested in JSON.
    If data is truncated (>100 rows), it provides a CSV download URL.
    """
    if not IFIND_SCRIPT_DIR.exists():
        raise RuntimeError(f"iFinD skill directory not found")
    
    call_path = IFIND_SCRIPT_DIR / "call.py"
    if not call_path.exists():
        raise RuntimeError(f"iFinD call.py not found")
    
    if str(IFIND_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(IFIND_SCRIPT_DIR))
    
    old_cwd = os.getcwd()
    os.chdir(str(IFIND_SCRIPT_DIR))
    try:
        if "call" in sys.modules:
            del sys.modules["call"]
        from call import call as ifind_call
    except ImportError as e:
        os.chdir(old_cwd)
        raise RuntimeError(f"Cannot import iFinD call module: {e}")
    finally:
        os.chdir(old_cwd)
    
    # Try with date range first, then without
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    
    for use_date_range in [True, False]:
        query = f"{query_str}（{start_str}-{end_str}）" if use_date_range else query_str
        
        result = ifind_call("edb", "get_edb_data", {"query": query})
        
        if not result.get("ok"):
            logger.warning(f"iFinD EDB query failed for '{query}': {result.get('error', '')}")
            continue
        
        data = result.get("data", {})
        if not data:
            continue
        
        content = None
        if isinstance(data, dict):
            if "result" in data and isinstance(data["result"], dict):
                content_list = data["result"].get("content", [])
                if content_list and isinstance(content_list[0], dict):
                    content = content_list[0].get("text", "")
            
            if not content:
                if "content" in data:
                    content_list = data.get("content", [])
                    if content_list and isinstance(content_list[0], dict):
                        content = content_list[0].get("text", "")
        
        if content and isinstance(content, str):
            # Parse as JSON (iFinD wraps data in JSON)
            try:
                inner = json.loads(content)
                if isinstance(inner, dict) and "data" in inner:
                    inner_data = inner["data"]
                    if isinstance(inner_data, dict):
                        # Check for structured data (full dataset, not truncated)
                        if "datas" in inner_data:
                            records = _parse_ifind_structured_data(
                                inner_data["datas"], start_date, end_date
                            )
                            if records:
                                return records
                        
                        answer = inner_data.get("answer", "")
                        if answer:
                            content = answer
                        else:
                            # Check data_markdown
                            content = inner_data.get("data_markdown", "")
            except (json.JSONDecodeError, KeyError):
                pass
        
        if content and isinstance(content, str):
            records = _parse_ifind_markdown_table(content)
            if records:
                return records
    
    logger.warning(f"iFinD EDB returned no parseable data for '{query_str}'")
    return []

# ── Main adapter ──────────────────────────────────────────────────────────

_cjhx_cache = {}

def _get_cjhx_cached(start_date: date, end_date: date) -> list[dict]:
    """Get CJHX data with caching."""
    cache_key = (start_date.isoformat(), end_date.isoformat())
    if cache_key not in _cjhx_cache:
        logger.info(f"CJHX: fetching all indicators for {start_date} to {end_date}")
        _cjhx_cache[cache_key] = _cjhx_fetch_all_macro(start_date, end_date)
    return _cjhx_cache[cache_key]

def fetch_series(
    indicator: dict[str, Any],
    series: dict[str, Any],
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Fetch time series data with local persistent cache.
    
    - Loads existing cache for the series
    - Fetches only incremental data from the last cached date
    - Merges and saves back to cache
    - Returns full merged series (not filtered by date range)
    """
    semantic_code = series.get("code", "")
    source = indicator.get("source", "")
    
    # Load existing cache
    cached = _load_cache(semantic_code)
    
    # Determine incremental fetch range
    if cached:
        last_cached_date = date.fromisoformat(cached[-1]["date"])
        if last_cached_date >= end_date:
            # Cache is up-to-date
            logger.info(f"Cache hit: {semantic_code} ({len(cached)} pts, latest={last_cached_date})")
            return cached
        
        # Fetch incremental data from last cached date + 1 day
        fetch_start = last_cached_date + timedelta(days=1)
    else:
        fetch_start = start_date
    
    logger.info(f"Fetching {semantic_code} ({source}) [{fetch_start} ~ {end_date}]")
    
    if source == "CJHX":
        new_records = _fetch_cjhx_api(semantic_code, fetch_start, end_date)
    elif source == "iFinD":
        new_records = _ifind_get_edb(
            resolve_series_code({"code": semantic_code}), fetch_start, end_date
        )
    else:
        raise NotImplementedError(f"Unknown source: {source}")
    
    # Merge and save full cache
    merged = _merge_records(cached, new_records)
    _save_cache(semantic_code, merged)
    
    # Return full merged data (dashboard script will filter as needed)
    return merged


def _fetch_cjhx_api(semantic_code: str, start_date: date, end_date: date) -> list[dict]:
    """Fetch from CJHX API (single call, returns incremental data)."""
    cjhx_code = resolve_series_code({"code": semantic_code})
    
    # For CJHX, we need to fetch the date range we need
    # Since CJHX returns all indicators at once, we use the bulk cache
    # but only fetch the incremental date range
    all_data = _get_cjhx_cached(start_date, end_date)
    
    matched = []
    for rec in all_data:
        if rec["code"] == cjhx_code:
            matched.append({"date": rec["date"], "value": rec["value"]})
    
    if not matched:
        logger.warning(f"CJHX: No data for {cjhx_code} ({semantic_code})")
    
    return matched
