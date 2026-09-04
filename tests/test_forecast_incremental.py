from __future__ import annotations

import unittest
import json
from pathlib import Path

from scripts.fetch_forecast_inputs_ifind import merge_records


class ForecastIncrementalTests(unittest.TestCase):
    def test_incremental_records_preserve_history_and_override_overlap(self) -> None:
        previous = {
            "providerId": "fixed",
            "records": [["2026-01-01", 1.0], ["2026-07-01", 2.0]],
        }
        candidate = {
            "providerId": "fixed",
            "records": [["2026-07-01", 2.5], ["2026-08-01", 3.0]],
        }
        merged = merge_records(previous, candidate)
        self.assertEqual(
            merged["records"],
            [["2026-01-01", 1.0], ["2026-07-01", 2.5], ["2026-08-01", 3.0]],
        )
        self.assertEqual(merged["startTime"], "2026-01-01")
        self.assertEqual(merged["endTime"], "2026-08-01")

    def test_daily_pipeline_uses_fast_path_by_default(self) -> None:
        source = (Path("scripts/run_pipeline.py")).read_text(encoding="utf-8-sig")
        self.assertIn("--full-forecast", source)
        self.assertIn("--allow-stale", source)
        self.assertIn('[] if args.allow_stale else ["--strict"]', source)
        self.assertIn("refresh_forecasts_fast.py", source)
        self.assertIn("timedelta(days=95)", source)
        manifest = json.loads(Path("data/forecast-model/ifind_forecast_manifest.json").read_text(encoding="utf-8-sig"))
        entries = {item["key"]: item for item in manifest["series"]}
        self.assertEqual(entries["cpi_pork"]["lookbackDays"], 70)
        self.assertEqual(entries["pmi_production"]["queryStart"], "2020-01-01")

    def test_forecast_page_starts_with_first_backtest_month(self) -> None:
        import json

        payload = json.loads(Path("public/data/forecasts.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(payload["displayStart"], "2023-01-31")
        for rows in payload["history"].values():
            self.assertEqual(rows[0]["date"], "2023-01-31")


if __name__ == "__main__":
    unittest.main()
