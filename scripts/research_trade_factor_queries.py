#!/usr/bin/env python3
"""Probe non-consensus trade indicators through the fuzzy iFinD EDB MCP."""

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
    "制造业PMI:新出口订单",
    "制造业PMI:进口",
    "美国零售销售:同比",
    "韩国:出口金额:当月同比",
    "越南:出口金额:当月同比",
]


def main() -> int:
    output = {}
    for query in QUERIES:
        print(f"QUERY {query}", flush=True)
        try:
            output[query] = call("edb", "get_edb_data", {"query": query})
        except Exception as error:
            output[query] = {"error": repr(error)}
    path = Path("outputs/trade-factor-ifind-probes.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
