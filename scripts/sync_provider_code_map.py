#!/usr/bin/env python3
"""Build the validator-facing provider map from the authoritative routing files."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    config = json.loads((ROOT / "config" / "indicators.json").read_text(encoding="utf-8"))
    required = {
        component["code"]
        for indicator in config["indicators"]
        for component in indicator["series"]
    }
    auxiliary_path = ROOT / "config" / "auxiliary-indicators.csv"
    with auxiliary_path.open("r", encoding="utf-8-sig", newline="") as handle:
        required.update(row["code"] for row in csv.DictReader(handle))

    cjhx = json.loads(
        (ROOT / "config" / "cjhx-series-map.json").read_text(encoding="utf-8")
    )
    with (ROOT / "config" / "ifind-series.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        ifind = {row["semantic_code"]: row for row in csv.DictReader(handle)}

    overlap = sorted(set(cjhx) & set(ifind))
    if overlap:
        raise RuntimeError(f"同一语义代码同时路由到CJHX和iFinD：{', '.join(overlap)}")

    routed = set(cjhx) | set(ifind)
    missing = sorted(required - routed)
    extra = sorted(routed - required)
    if missing or extra:
        raise RuntimeError(
            "数据源路由与页面配置不一致。"
            f" missing={missing or '[]'} extra={extra or '[]'}"
        )

    provider_map = {}
    for code in sorted(required):
        if code in cjhx:
            provider_map[code] = {
                "provider": "CJHX",
                "provider_code": f"CJHX:{cjhx[code]['series_key']}",
            }
        else:
            provider_map[code] = {
                "provider": "iFinD",
                "provider_code": f"iFinD:{ifind[code]['provider_id']}",
                "query_name": ifind[code]["query_name"],
            }

    output = ROOT / "config" / "provider-code-map.json"
    output.write_text(
        json.dumps(provider_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"已同步{len(provider_map)}个语义代码："
        f"CJHX {len(cjhx)}项，iFinD {len(ifind)}项 -> {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
