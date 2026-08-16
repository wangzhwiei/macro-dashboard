#!/usr/bin/env python3
"""Probe one fuzzy iFinD EDB field at a time, then validate returned metadata."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


SKILL = Path(os.environ["IFIND_SKILL_DIR"])
sys.path.insert(0, str(SKILL))
previous = Path.cwd()
os.chdir(SKILL)
try:
    from call import call
finally:
    os.chdir(previous)

QUERIES = [
    "出口总值(美元计价):当月同比",
    "进口总值(美元计价):当月同比",
    "出口总额(美元计价):当月同比",
    "进口总额(美元计价):当月同比",
]


def main() -> int:
    output = {}
    for query in QUERIES:
        print(f"QUERY {query}", flush=True)
        try:
            output[query] = call("edb", "get_edb_data", {"query": query})
        except Exception as error:
            output[query] = {"error": repr(error)}
    path = Path("outputs/trade-ifind-field-probes.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
