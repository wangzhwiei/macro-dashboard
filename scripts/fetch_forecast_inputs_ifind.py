#!/usr/bin/env python3
"""Fetch and strictly identify every CPI/PPI/PMI model input from iFinD EDB."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def inner_payload(response: dict[str, Any]) -> dict[str, Any]:
    if not response.get("ok"):
        raise RuntimeError(str(response.get("error") or "iFinD 调用失败"))
    content = response.get("data", {}).get("result", {}).get("content", [])
    if not content or not isinstance(content[0], dict):
        raise RuntimeError("iFinD 响应缺少 content")
    parsed = json.loads(content[0].get("text", "{}"))
    if parsed.get("code") != 1:
        raise RuntimeError(str(parsed.get("msg") or "iFinD EDB 返回失败"))
    return parsed.get("data") or {}


def parse_candidate(item: dict[str, Any]) -> dict[str, Any]:
    structured = item.get("data") if isinstance(item.get("data"), dict) else {}
    attrs = structured.get("attrs") if isinstance(structured.get("attrs"), dict) else {}
    attr = next(iter(attrs.values()), {}) if attrs else {}
    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
    provider_id = extra.get("index_id") or attr.get("index_id")
    rows = structured.get("data") if isinstance(structured.get("data"), list) else []
    records = []
    for row in rows:
        if isinstance(row, list) and len(row) >= 2 and row[0] is not None and row[1] is not None:
            records.append([str(row[0])[:10], float(row[1])])
    records.sort(key=lambda row: row[0])
    return {
        "providerId": provider_id,
        "name": next(iter(attrs), None),
        "frequency": attr.get("freq"),
        "unit": attr.get("unit"),
        "startTime": attr.get("start_time"),
        "endTime": attr.get("end_time"),
        "description": item.get("description"),
        "records": records,
    }


def choose_candidate(entry: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    candidates = [parse_candidate(item) for item in payload.get("datas", []) if isinstance(item, dict)]
    candidates = [item for item in candidates if item["providerId"] and item["records"]]
    expected_id = entry.get("providerId")
    if expected_id:
        matches = [item for item in candidates if item["providerId"] == expected_id]
        if len(matches) != 1:
            raise RuntimeError(f"{entry['key']} 固定 ID {expected_id} 未唯一命中；候选={[x['providerId'] for x in candidates]}")
        return matches[0]
    if len(candidates) != 1:
        raise RuntimeError(f"{entry['key']} 未唯一命中；候选={[(x['providerId'], x['name']) for x in candidates]}")
    return candidates[0]


def merge_records(previous: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    """Merge an incremental response into the stored series, with new values winning."""
    if not previous:
        return candidate
    records = {
        str(row[0])[:10]: float(row[1])
        for row in previous.get("records", [])
        if isinstance(row, list) and len(row) >= 2
    }
    records.update({str(row[0])[:10]: float(row[1]) for row in candidate.get("records", [])})
    merged = {**candidate, "records": [[key, records[key]] for key in sorted(records)]}
    if merged["records"]:
        merged["startTime"] = merged["records"][0][0]
        merged["endTime"] = merged["records"][-1][0]
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", type=Path, default=os.environ.get("IFIND_SKILL_DIR"))
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "forecast-model" / "ifind_forecast_manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "forecast-model" / "ifind_latest_inputs.json")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--merge-existing", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()

    if args.skill_dir is None:
        raise RuntimeError("请设置 IFIND_SKILL_DIR 或传入 --skill-dir")
    skill_dir = args.skill_dir.resolve()
    if not (skill_dir / "call.py").exists() or not (skill_dir / "mcp_config.json").exists():
        raise RuntimeError("iFinD skill 目录缺少 call.py 或 mcp_config.json")
    sys.path.insert(0, str(skill_dir))
    previous_cwd = Path.cwd()
    os.chdir(skill_dir)
    try:
        from call import call as ifind_call
    finally:
        os.chdir(previous_cwd)

    manifest = read_json(args.manifest)
    selected = [entry for entry in manifest["series"] if not args.only or entry["key"] in args.only]
    output = read_json(args.output) if args.merge_existing and args.output.exists() else {
        "schemaVersion": 1, "start": args.start, "end": args.end,
        "series": {}, "errors": {}, "warnings": {},
    }
    output.setdefault("warnings", {})
    if not args.merge_existing:
        output["start"], output["end"] = args.start, args.end
    else:
        output["start"] = min(str(output.get("start") or args.start), args.start)
        output["end"] = max(str(output.get("end") or args.end), args.end)
    start, end = args.start.replace("-", ""), args.end.replace("-", "")
    for index, entry in enumerate(selected, 1):
        previous = output["series"].get(entry["key"])
        output["errors"].pop(entry["key"], None)
        output["warnings"].pop(entry["key"], None)
        # EDB search is name-driven; providerId is a strict response validator, not a query alias.
        query = entry["queryName"]
        entry_start = args.start
        if entry.get("queryStart"):
            entry_start = str(entry["queryStart"])
        elif entry.get("lookbackDays"):
            minimum_start = (date.fromisoformat(args.end) - timedelta(days=int(entry["lookbackDays"]))).isoformat()
            entry_start = max(entry_start, minimum_start)
        request_start = entry_start.replace("-", "")
        request = f"{query}（{request_start}-{end}）"
        print(f"[{index}/{len(selected)}] {entry['key']} -> {query}", flush=True)
        try:
            response = None
            for attempt in range(1, max(args.attempts, 1) + 1):
                try:
                    response = ifind_call("edb", "get_edb_data", {"query": request})
                    break
                except Exception:
                    if attempt >= max(args.attempts, 1):
                        raise
                    time.sleep(1.5 * attempt)
            candidate = choose_candidate(entry, inner_payload(response))
            if entry.get("frequency") and candidate.get("frequency") != entry["frequency"]:
                raise RuntimeError(f"频率不一致：期望 {entry['frequency']}，返回 {candidate.get('frequency')}")
            candidate = merge_records(previous if args.merge_existing else None, candidate)
            output["series"][entry["key"]] = {**entry, **candidate}
        except Exception as error:
            previous_is_valid = (
                args.merge_existing and previous
                and previous.get("providerId") == entry.get("providerId")
                and previous.get("frequency") == entry.get("frequency")
                and previous.get("unit") == entry.get("unit")
                and bool(previous.get("records"))
            )
            if previous_is_valid:
                latest = str(previous["records"][-1][0])[:10]
                output["warnings"][entry["key"]] = (
                    f"本次模糊召回失败，保留已通过固定ID校验的历史快照（最新{latest}）：{error}"
                )
            else:
                output["errors"][entry["key"]] = str(error)
        if index < len(selected):
            time.sleep(.35)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：成功 {len(output['series'])}，失败 {len(output['errors'])}，输出 {args.output}")
    return 2 if output["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
