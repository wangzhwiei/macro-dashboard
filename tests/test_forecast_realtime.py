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
            self.assertEqual(rows[-1]["date"], "2026-07-31")

    def test_daily_paths_use_observation_dates_and_converge(self) -> None:
        expected = {"cpi": 1.0477663882968669, "cpi_mom": .4474826275742958,
                    "ppi": 3.981353718814007, "ppi_mom": -.31374542615142326}
        for key, endpoint in expected.items():
            rows = self.data["daily"][key]
            self.assertGreater(len(rows), 20)
            self.assertEqual(rows[0]["date"], "2026-07-01")
            self.assertEqual(rows[-1]["date"], "2026-07-31")
            self.assertEqual(len({row["date"] for row in rows}), len(rows))
            self.assertTrue(math.isclose(rows[-1]["value"], endpoint, abs_tol=1e-6))

    def test_high_frequency_rows_are_not_monthly_aggregates(self) -> None:
        expected_frequency = {
            "cpi_veg": "日频", "ppi_nanhua": "周频", "ppi_brent": "日频",
            "pmi_proxy_1": "周频", "pmi_proxy_3": "日频",
        }
        rows = {row["id"]: row for group in self.data["highFrequency"].values() for row in group}
        for key, frequency in expected_frequency.items():
            self.assertEqual(rows[key]["frequency"], frequency)
            self.assertGreater(len(rows[key]["series"]), 300)

    def test_pmi_july_lags_use_official_june_subindices(self) -> None:
        expected = {"pmi_sub_从业人员": 48.5, "pmi_sub_配送": 49.9, "pmi_sub_库存": 48.4}
        rows = {row["id"]: row for row in self.data["highFrequency"]["PMI"]}
        for key, value in expected.items():
            june = next(point for point in rows[key]["series"] if point["date"] == "2026-06-30")
            self.assertEqual(june["value"], value)
            self.assertEqual(rows[key]["series"][-1]["date"], "2026-07-31")
            self.assertIn("实际使用2026年6月值", rows[key]["modelUsageNote"])

    def test_all_inputs_have_fixed_ifind_provider_and_latest_date(self) -> None:
        for group, inputs in self.data["highFrequency"].items():
            for row in inputs:
                self.assertRegex(row["providerId"], r"^[SM]\d{9}$", f"{group}/{row['id']}")
                self.assertEqual(row["latestAvailableDate"], row["series"][-1]["date"])
                self.assertGreaterEqual(row["latestAvailableDate"], "2026-07-31")


if __name__ == "__main__":
    unittest.main()
