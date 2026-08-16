#!/usr/bin/env python3
"""Probe destination-market import indicators through the iFinD EDB MCP.

The endpoint has fuzzy-search permission only, so every response is retained
for post-response validation.  No returned series is admitted to a model until
its exact name, provider id, frequency, unit, geography and source are checked.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ["IFIND_SKILL_DIR"])
sys.path.insert(0, str(SKILL))
previous = Path.cwd()
os.chdir(SKILL)
try:
    from call import call
finally:
    os.chdir(previous)


QUERIES = [
    "美国:进口金额:中国:当月值",
    "美国:自中国进口金额:当月值",
    "日本:进口金额:中国:当月值",
    "日本:从中国进口金额:当月值",
    "日本:自中国进口金额:当月值",
    "美国:自中国进口金额:当月同比",
    "美国:进口金额:中国:当月同比",
    "欧盟27国:自中国进口金额:当月同比",
    "欧盟:进口金额:中国:当月同比",
    "日本:自中国进口金额:当月同比",
    "韩国:自中国进口金额:当月同比",
    "韩国:进口金额:中国:当月同比",
    "中国台湾:自中国大陆进口金额:当月同比",
    "中国台湾:进口金额:中国大陆:当月同比",
    "巴西:自中国进口金额:当月同比",
    "巴西:进口金额:中国:当月同比",
    "越南:自中国进口金额:当月同比",
    "越南:进口金额:中国:当月同比",
    "中国香港:进口金额:中国内地:当月同比",
    "新加坡:进口金额:中国:当月同比",
    "马来西亚:进口金额:中国:当月同比",
    "印度尼西亚:进口金额:中国:当月同比",
    "泰国:进口金额:中国:当月同比",
    "美国:进口金额:中国:所有产品:当月同比",
    "日本:进口金额:中国:所有产品:当月同比",
    "中国台湾:进口金额:中国大陆:所有产品:当月同比",
    "马来西亚:进口金额:中国:所有产品:当月同比",
    "泰国:进口金额:中国:所有产品:当月同比",
    "中国台湾:进口总额:美元:大陆:当月同比",
]


def main() -> int:
    path = ROOT / "outputs" / "trade-partner-import-ifind-probes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    output = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for query in QUERIES:
        if query in output:
            continue
        print(f"QUERY {query}", flush=True)
        try:
            output[query] = call("edb", "get_edb_data", {"query": query})
        except Exception as error:
            output[query] = {"error": repr(error)}
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(0.35)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
