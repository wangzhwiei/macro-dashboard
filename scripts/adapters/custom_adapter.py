"""Replace this adapter body with the user's existing iFinD/CJHX client calls."""

from __future__ import annotations

from datetime import date
from typing import Any


def fetch_series(
    indicator: dict[str, Any],
    series: dict[str, Any],
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Return [{"date": "YYYY-MM-DD", "value": number}, ...].

    `indicator` contains the dashboard metadata. `series["code"]` is the code
    configured in config/indicators.json. Keep credentials in environment
    variables or the vendor SDK's own credential store.
    """

    raise NotImplementedError(
        "请在 scripts/adapters/custom_adapter.py 中接入现有 iFinD/CJHX 查询函数"
    )
