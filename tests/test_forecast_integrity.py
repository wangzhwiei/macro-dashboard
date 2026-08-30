import json
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ForecastIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(
            (ROOT / "public" / "data" / "forecasts.json").read_text(encoding="utf-8")
        )

    def test_history_covers_2023_to_confirmed_july_nowcast(self) -> None:
        for key in ("cpi", "ppi", "pmi"):
            rows = self.data["history"][key]
            self.assertEqual(rows[0]["date"], "2023-01-31")
            self.assertEqual(rows[-1]["date"], "2026-08-31")
            self.assertEqual(rows[-1]["forecastKind"], "live_nowcast")
            self.assertTrue(all(row["forecast"] is None for row in rows if row["date"] < "2023-01-01"))

    def test_locked_july_values_match_final_review(self) -> None:
        expected = {"cpi": 1.0477663882968669, "ppi": 3.981353718814007, "pmi": 48.98}
        actuals = {"cpi": .5, "ppi": 3.5, "pmi": 49.2}
        for key, value in expected.items():
            row = next(row for row in self.data["history"][key] if row["date"] == "2026-07-31")
            self.assertEqual(row["forecastKind"], "confirmed_nowcast")
            self.assertTrue(math.isclose(row["forecast"], value, abs_tol=1e-6))
            self.assertTrue(math.isclose(row["actual"], actuals[key], abs_tol=1e-6))

    def test_locked_backtest_metrics_have_not_drifted(self) -> None:
        expected = {"cpi": 0.223, "ppi": 0.291, "pmi": 0.604}
        for key, value in expected.items():
            metric = self.data["metrics"][key]
            self.assertTrue(math.isclose(metric["rmse"], value, abs_tol=.006))
            self.assertEqual(metric["sampleStart"], "2023-01")
            self.assertEqual(metric["sampleEnd"], "2026-05")

    def test_forecast_months_are_complete_and_never_use_future_actuals(self) -> None:
        for key in ("cpi", "ppi", "pmi"):
            rows = [row for row in self.data["history"][key] if "2023-01-01" <= row["date"] <= "2026-05-31"]
            self.assertEqual(len(rows), 41)
            self.assertTrue(all(row["forecastKind"] == "walk_forward" for row in rows))
            self.assertTrue(all(row["forecast"] is not None and row["actual"] is not None for row in rows))

    def test_all_historical_forecasts_have_official_rounding(self) -> None:
        for key in ("cpi", "cpi_mom", "ppi", "ppi_mom", "pmi"):
            for row in self.data["history"][key]:
                if row["forecast"] is not None:
                    self.assertEqual(row["officialRounding"], round(row["forecast"], 1), f"{key}/{row['date']}")

    def test_history_table_is_not_hard_limited_to_twelve_rows(self) -> None:
        component = (ROOT / "app" / "ForecastPanelV3.tsx").read_text(encoding="utf-8")
        self.assertNotIn("rows.slice(-12)", component)
        self.assertIn("<ComparisonTable rows={rows}", component)
    def test_inputs_are_unique_and_consensus_is_strictly_sourced(self) -> None:
        for group, rows in self.data["highFrequency"].items():
            ids = [row["id"] for row in rows]
            self.assertEqual(len(ids), len(set(ids)), group)
            self.assertTrue(all(row["frequency"] and row["role"] and row["aggregation"] for row in rows))
        expected = {"cpi": .74, "ppi": 3.463636, "pmi": 49.9}
        for key, value in expected.items():
            row = next(row for row in self.data["history"][key] if row["date"] == "2026-07-31")
            self.assertEqual(row["consensusSource"], "iFinD EDB")
            self.assertTrue(math.isclose(row["consensus"], value, abs_tol=1e-9))

    def test_trade_inputs_are_split_by_model(self) -> None:
        groups = self.data["highFrequency"]
        self.assertNotIn("进出口", groups)
        self.assertEqual(
            {row["id"] for row in groups["出口"]},
            {
                "trade_korea_imports_china",
                "trade_taiwan_imports_mainland",
                "trade_thailand_imports_china",
            },
        )
        self.assertEqual(
            {row["id"] for row in groups["进口"]},
            {"trade_korea_exports"},
        )

    def test_trade_consensus_gaps_are_filled_from_previous_month(self) -> None:
        for key in ("exports", "imports"):
            rows = self.data["history"][key]
            by_date = {row["date"]: row for row in rows}
            self.assertTrue(all(row["consensus"] is not None for row in rows))
            for current, previous in (
                ("2026-01-31", "2025-12-31"),
                ("2026-02-28", "2026-01-31"),
                ("2026-08-31", "2026-07-31"),
            ):
                self.assertEqual(by_date[current]["consensus"], by_date[previous]["consensus"])
                self.assertTrue(by_date[current]["consensusCarriedForward"])
                self.assertIn("沿用上期", by_date[current]["consensusSource"])


    def test_frozen_credit_models_are_available_in_forecast_module(self) -> None:
        keys = ("m2_yoy", "new_rmb_loans", "social_financing")
        self.assertEqual(self.data["modelLocks"]["credit"]["version"], "credit-v1.0.0")
        self.assertEqual(self.data["modelLocks"]["credit"]["frozenAt"], "2026-08-25")
        for key in keys:
            self.assertIn(key, self.data["models"])
            self.assertIn(key, self.data["metrics"])
            self.assertGreaterEqual(len(self.data["history"][key]), 43)
            self.assertEqual(self.data["history"][key][0]["date"], "2023-01-31")
            self.assertEqual(self.data["history"][key][-1]["date"], "2026-08-31")
            self.assertEqual(self.data["history"][key][-1]["forecastKind"], "live_nowcast")
            self.assertIsNone(self.data["history"][key][-1]["actual"])
        credit_inputs = self.data["highFrequency"]["信用"]
        self.assertEqual(len(credit_inputs), 1)
        self.assertEqual(credit_inputs[0]["providerId"], "M021397977")

    def test_forecast_page_has_credit_tabs(self) -> None:
        component = (ROOT / "app" / "ForecastPanelV3.tsx").read_text(encoding="utf-8")
        for key in ("m2_yoy", "new_rmb_loans", "social_financing"):
            self.assertIn(key, component)

    def test_frozen_industrial_value_model_is_published(self) -> None:
        key = "industrial_value"
        lock = self.data["modelLocks"]["industrialValue"]
        self.assertEqual(lock["version"], "industrial-fixed-carry-hf-v1.0.0")
        self.assertEqual(lock["frozenAt"], "2026-08-29")
        self.assertEqual(lock["targets"], [key])
        self.assertEqual(self.data["models"][key]["status"], "READY")
        self.assertTrue(math.isclose(self.data["metrics"][key]["rmse"], 0.663432, abs_tol=2e-6))
        self.assertTrue(math.isclose(self.data["metrics"][key]["directionHit"], 72.73, abs_tol=1e-6))
        self.assertTrue(math.isclose(self.data["metrics"][key]["benchmarkRmse"], 1.119724, abs_tol=1e-6))
        latest = self.data["history"][key][-1]
        self.assertEqual(latest["date"], "2026-08-31")
        self.assertEqual(latest["forecastKind"], "live_nowcast")
        self.assertIsNone(latest["actual"])
        self.assertTrue(math.isfinite(latest["forecast"]))
        self.assertEqual(latest["officialRounding"], round(latest["forecast"], 1))
        inputs = self.data["highFrequency"]["工业"]
        self.assertEqual(
            {row["id"] for row in inputs},
            {"power_coal", "blast_furnace", "rebar_rate", "pta_rate", "methanol_rate", "car_wholesale", "car_retail"},
        )
        self.assertFalse(self.data["industrialValueModel"]["laggedIndustrialValueIncluded"])
        self.assertFalse(self.data["industrialValueModel"]["monthlyFactorReplacement"])
        component = (ROOT / "app" / "ForecastPanelV3.tsx").read_text(encoding="utf-8")
        self.assertIn("industrial_value", component)
        self.assertIn("工业增加值", component)


if __name__ == "__main__":
    unittest.main()
