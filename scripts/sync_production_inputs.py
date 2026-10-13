"""Reuse verified fixed-ID PMI feeds for industrial and investment models."""
import copy
import argparse
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPPING = {
    "blast_furnace": "pmi_blast_furnace",
    "rebar_rate": "pmi_rebar_steel_rate",
    "power_coal": "pmi_power_coal",
    "pta_rate": "pmi_pta",
    "methanol_rate": "pmi_methanol",
    "car_wholesale": "pmi_car_wholesale",
    "car_retail": "pmi_car_retail",
}


def synchronize(production, inputs):
    result = copy.deepcopy(production)
    for target, source in MAPPING.items():
        old = result["series"][target]
        fresh = inputs["series"][source]
        for field in ("providerId", "frequency", "unit"):
            if not old.get(field) or old[field] != fresh.get(field):
                raise ValueError(f"{target}: {field} mismatch; refusing synchronization")
        records = {}
        for day, value in fresh["records"]:
            date.fromisoformat(day)
            value = float(value)
            if not math.isfinite(value) or (day in records and records[day] != value):
                raise ValueError(f"{target}: invalid or conflicting observation")
            records[day] = value
        if not records:
            raise ValueError(f"{target}: empty source")
        old_last = max(d for d, _ in old["observations"])
        refresh_start = min(date.fromisoformat(old_last) + timedelta(days=1),
                            date.fromisoformat(inputs["end"]) - timedelta(days=45)).isoformat()
        records = {d: v for d, v in records.items() if d >= refresh_start}
        if not records:
            continue
        first, last = min(records), max(records)
        # Replace the covered interval rather than retaining phantom dates.
        history = {d: v for d, v in old["observations"] if d < first or d > last}
        history.update(records)
        old["observations"] = sorted(history.items())
        old["startTime"] = min(history)
        old["endTime"] = max(history)
        old["synchronizedFrom"] = f"forecast-model/ifind_latest_inputs.json:{source}"
        old["sourceRetrievedAt"] = inputs.get("retrievedAt") or inputs.get("end")
    result["synchronizedAt"] = datetime.now().astimezone().isoformat()
    return result


def main():
    path = ROOT / "data/industrial-value-model/production_inputs.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-source", type=Path, default=path)
    args = parser.parse_args()
    inputs = ROOT / "data/forecast-model/ifind_latest_inputs.json"
    result = synchronize(json.loads(args.production_source.read_text(encoding="utf-8-sig")),
                         json.loads(inputs.read_text(encoding="utf-8-sig")))
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result["series"][k]["endTime"] for k in MAPPING}))


if __name__ == "__main__":
    main()
