#!/usr/bin/env python3
"""
生成 CJHX 数据质量报告 cjhx-data-quality-report.json。

读取 data/incoming/cjhx-YYYY-MM-DD.json，输出质量分析报告。
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
INCOMING_DIR = ROOT / "data" / "incoming"


def load_raw_data() -> Dict[str, Any]:
    """Load the latest CJHX raw data file (not the report)."""
    files = sorted(f for f in INCOMING_DIR.glob("cjhx-*.json")
                   if "data-quality-report" not in f.name)
    if not files:
        raise FileNotFoundError(f"No CJHX data files found in {INCOMING_DIR}")
    latest = files[-1]
    with open(latest) as f:
        return json.load(f)


def analyze_series(s: Dict) -> Dict:
    """Analyze a single series for quality metrics."""
    obs = s.get("observations", [])
    
    if not obs:
        return {
            "observationCount": 0,
            "dateRange": None,
            "latestDate": None,
            "staleDays": None,
            "hasGaps": None,
            "gapCount": 0,
            "minValue": None,
            "maxValue": None,
            "latestValue": None,
        }
    
    dates = [o["date"] for o in obs]
    values = [o["value"] for o in obs]
    earliest = min(dates)
    latest = max(dates)
    latest_val = max(obs, key=lambda o: o["date"])["value"]
    
    # Stale days
    today = date.today()
    latest_date_obj = date.fromisoformat(latest)
    stale = (today - latest_date_obj).days
    
    # Gap detection (based on inferred frequency)
    freq = s.get("providerFrequency")
    has_gaps = False
    gap_count = 0
    
    if len(dates) >= 2 and freq:
        sorted_dates = sorted([date.fromisoformat(d) for d in dates])
        
        for i in range(1, len(sorted_dates)):
            actual_gap = (sorted_dates[i] - sorted_dates[i-1]).days
            # CJHX daily data skips weekends/holidays (normal gaps of 2-3 days)
            # Flag only if gap exceeds 7 calendar days (suggests real data issue)
            if freq == "D" and actual_gap > 7:
                has_gaps = True
                gap_count += 1
            elif freq == "W" and actual_gap > 28:  # >4 weeks
                has_gaps = True
                gap_count += 1
            elif freq == "M" and actual_gap > 90:  # >3 months
                has_gaps = True
                gap_count += 1
    
    return {
        "observationCount": len(obs),
        "dateRange": f"{earliest} to {latest}",
        "latestDate": latest,
        "staleDays": stale,
        "hasGaps": has_gaps,
        "gapCount": gap_count,
        "minValue": min(values),
        "maxValue": max(values),
        "latestValue": latest_val,
    }


def generate_report() -> Dict:
    """Generate the full data quality report."""
    raw = load_raw_data()
    series_list = raw.get("series", [])
    
    today = date.today().isoformat()
    
    ok_series = [s for s in series_list if s["status"] == "ok"]
    empty_series = [s for s in series_list if s["status"] == "empty"]
    error_series = [s for s in series_list if s["status"] == "error"]
    
    # Per-series analysis
    series_reports = []
    for s in sorted(series_list, key=lambda x: x["seriesKey"]):
        analysis = analyze_series(s)
        series_reports.append({
            "seriesKey": s["seriesKey"],
            "source": s["source"],
            "queryName": s["queryName"],
            "providerId": s.get("providerId"),
            "providerFrequency": s.get("providerFrequency"),
            "providerUnit": s.get("providerUnit"),
            "status": s["status"],
            "error": s.get("error"),
            **analysis,
        })
    
    # Overall metrics
    total_obs = sum(len(s.get("observations", [])) for s in series_list)
    stale_series = [sr for sr in series_reports if sr.get("staleDays") and sr["staleDays"] > 7]
    gap_series = [sr for sr in series_reports if sr.get("hasGaps")]
    
    # Frequency distribution
    freq_dist = {}
    for s in series_list:
        f = s.get("providerFrequency") or "unknown"
        freq_dist[f] = freq_dist.get(f, 0) + 1
    
    report = {
        "reportType": "cjhx_data_quality",
        "generatedAt": f"{today}T00:00:00+08:00",
        "batchDate": raw.get("batchDate"),
        "mode": raw.get("mode"),
        "window": raw.get("window"),
        "summary": {
            "totalSeries": len(series_list),
            "okCount": len(ok_series),
            "emptyCount": len(empty_series),
            "errorCount": len(error_series),
            "successRate": round(len(ok_series) / len(series_list) * 100, 1) if series_list else 0,
            "totalObservations": total_obs,
            "avgObservationsPerSeries": round(total_obs / len(ok_series), 1) if ok_series else 0,
        },
        "frequencyDistribution": freq_dist,
        "staleSeries": [sr["seriesKey"] for sr in stale_series],
        "gapSeries": [sr["seriesKey"] for sr in gap_series],
        "errorDetails": [
            {
                "seriesKey": s["seriesKey"],
                "queryName": s["queryName"],
                "error": s.get("error"),
            }
            for s in error_series
        ],
        "seriesDetails": series_reports,
    }
    
    return report


def main():
    report = generate_report()
    
    # Write report next to the raw data file
    batch_date = report["batchDate"]
    out_path = INCOMING_DIR / f"cjhx-data-quality-report-{batch_date}.json"
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"Report saved: {out_path}")
    print(f"\nSummary:")
    print(f"  Total series: {report['summary']['totalSeries']}")
    print(f"  OK:           {report['summary']['okCount']}")
    print(f"  Empty:        {report['summary']['emptyCount']}")
    print(f"  Error:        {report['summary']['errorCount']}")
    print(f"  Success rate: {report['summary']['successRate']}%")
    print(f"  Total obs:    {report['summary']['totalObservations']}")
    print(f"  Avg obs/ser:  {report['summary']['avgObservationsPerSeries']}")
    
    if report["staleSeries"]:
        print(f"\n  Stale series (>7 days): {', '.join(report['staleSeries'])}")
    if report["gapSeries"]:
        print(f"\n  Series with gaps: {', '.join(report['gapSeries'])}")
    if report["errorDetails"]:
        print(f"\n  Errors:")
        for e in report["errorDetails"]:
            print(f"    {e['seriesKey']}: {e['error']}")


if __name__ == "__main__":
    main()
