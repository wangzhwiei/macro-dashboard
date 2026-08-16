import json
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ForecastRealtimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads((ROOT / "public" / "data" / "forecasts.json").read_text(encoding="utf-8"))

    def test_schema_and_mom_history(self) -> None:
        self.assertEqual(self.data["schemaVersion"], 3)
        for key in ("cpi_mom", "ppi_mom"):
            rows = self.data["history"][key]
            self.assertEqual(rows[0]["date"], "2023-01-31")
            self.assertEqual(rows[-1]["date"], "2026-08-31")

    def test_daily_paths_use_current_month_observation_dates(self) -> None:
        for key in ("cpi", "cpi_mom", "ppi", "ppi_mom", "pmi"):
            rows = self.data["daily"][key]
            self.assertGreater(len(rows), 2)
            self.assertTrue(all(row["date"].startswith("2026-08-") for row in rows))
            self.assertEqual(len({row["date"] for row in rows}), len(rows))
            self.assertTrue(all(math.isfinite(row["value"]) for row in rows))
        self.assertGreaterEqual(self.data["dailyAsOf"], "2026-08-14")

    def test_current_month_nowcasts_are_appended_without_actuals(self) -> None:
        for key in ("cpi", "cpi_mom", "ppi", "ppi_mom", "pmi"):
            row = self.data["history"][key][-1]
            self.assertEqual(row["date"], "2026-08-31")
            self.assertEqual(row["forecastKind"], "live_nowcast")
            self.assertIsNone(row["actual"])
            self.assertTrue(math.isclose(row["forecast"], self.data["daily"][key][-1]["value"], abs_tol=1e-6))

    def test_approved_fixed_trade_models_are_published(self) -> None:
        for section in ("daily", "history", "models", "metrics"):
            self.assertIn("imports", self.data[section])
            self.assertIn("exports", self.data[section])
        self.assertIn("进出口", self.data["highFrequency"])
        self.assertEqual(self.data["tradeModel"]["version"], "trade-fixed-factors-cny-gated-v1")
        for key in ("exports", "imports"):
            self.assertEqual(self.data["models"][key]["status"], "WAITING_FOR_FIXED_FACTORS")
            self.assertIsNone(self.data["history"][key][-1]["forecast"])

    def test_high_frequency_rows_are_not_monthly_aggregates(self) -> None:
        expected_frequency = {
            "cpi_veg": "日频", "ppi_nanhua": "周频", "ppi_brent": "日频",
            "pmi_proxy_1": "周频", "pmi_proxy_3": "日频",
        }
        rows = {row["id"]: row for group in self.data["highFrequency"].values() for row in group}
        for key, frequency in expected_frequency.items():
            self.assertEqual(rows[key]["frequency"], frequency)
            self.assertGreater(len(rows[key]["series"]), 300)

    def test_pmi_august_lags_use_official_july_subindices(self) -> None:
        expected = {"pmi_sub_从业人员": 49.0, "pmi_sub_配送": 49.5, "pmi_sub_库存": 48.3}
        rows = {row["id"]: row for row in self.data["highFrequency"]["PMI"]}
        for key, value in expected.items():
            july = next(point for point in rows[key]["series"] if point["date"] == "2026-07-31")
            self.assertEqual(july["value"], value)
            self.assertEqual(rows[key]["series"][-1]["date"], "2026-07-31")
            self.assertIn("2026年8月预测使用2026年7月值", rows[key]["modelUsageNote"])

    def test_all_inputs_have_fixed_ifind_provider_and_latest_date(self) -> None:
        for group, inputs in self.data["highFrequency"].items():
            for row in inputs:
                self.assertRegex(row["providerId"], r"^[SMGW]\d{9}$", f"{group}/{row['id']}")
                self.assertEqual(row["latestAvailableDate"], row["series"][-1]["date"])
                if group == "进出口" and row["id"] == "trade_thailand_imports_china":
                    self.assertEqual(row["latestAvailableDate"], "2026-06-30")
                else:
                    self.assertGreaterEqual(row["latestAvailableDate"], "2026-07-31")


if __name__ == "__main__":
    unittest.main()
