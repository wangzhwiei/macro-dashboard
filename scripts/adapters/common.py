"""Shared helpers for data-provider adapters."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _code_map() -> dict[str, Any]:
    configured = os.environ.get("MACRO_API_CODE_MAP", "").strip()
    if not configured:
        return {}
    path = Path(configured)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"序列代码映射文件不存在：{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("序列代码映射文件必须是JSON对象")
    return payload


def resolve_series_code(series: dict[str, Any]) -> str:
    """Map the dashboard semantic code to the provider's actual code.

    Supported map values:
      "CJHX:FR007_IRS_1Y": "vendor_actual_code"
      "CJHX:FR007_IRS_1Y": {"provider_code": "vendor_actual_code"}
    Missing entries intentionally fall back to the configured semantic code.
    """

    semantic_code = str(series["code"])
    mapped = _code_map().get(semantic_code, semantic_code)
    if isinstance(mapped, dict):
        mapped = mapped.get("provider_code") or mapped.get("code")
    if not mapped:
        raise ValueError(f"{semantic_code} 的供应商代码映射为空")
    return str(mapped)
