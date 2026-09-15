import json
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RetailV7PublishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = json.loads((ROOT / "data" / "forecast-model" / "retail_v7_production.json").read_text(encoding="utf-8"))
        cls.page = json.loads((ROOT / "public" / "data" / "forecasts.json").read_text(encoding="utf-8"))

    def test_v7_is_locked_as_production_model(self) -> None:
        self.assertEqual(self.model["modelVersion"], "retail-v7-production")
        decision = self.model["productionDecision"]
        self.assertEqual(decision["status"], "production")
        self.assertEqual(decision["deploymentCandidate"], "seasonalGatedRankedTop5")

    def test_page_contains_exact_v7_history(self) -> None:
        source = {row["date"]: row for row in self.model["history"]}
        rows = self.page["history"]["retail"]
        self.assertEqual(rows[0]["date"], "2023-01-31")
        self.assertIsNone(rows[0]["forecast"])
        self.assertIsNone(rows[1]["forecast"])
        self.assertEqual(rows[-1]["date"], "2026-09-30")
        for row in rows:
            expected = source[row["date"]].get("seasonalGatedRankedTop5")
            if expected is None:
                self.assertIsNone(row["forecast"])
            elif expected is not None:
                self.assertTrue(math.isclose(row["forecast"], expected, abs_tol=1e-6))

    def test_consensus_is_comparison_only_and_released_august_is_preserved(self) -> None:
        self.assertEqual(self.page["productionModels"]["retail"]["consensusRole"], "comparison_only")
        self.assertEqual(self.page["source"].count("社零V7正式模型"), 1)
        august = next(row for row in self.page["history"]["retail"] if row["date"] == "2026-08-31")
        self.assertEqual(august["date"], "2026-08-31")
        self.assertTrue(math.isclose(august["forecast"], 0.624187, abs_tol=1e-6))
        self.assertTrue(math.isclose(august["actual"], 0.4, abs_tol=1e-6))
        self.assertEqual(august["forecastKind"], "walk_forward")
        september = self.page["history"]["retail"][-1]
        self.assertEqual(september["date"], "2026-09-30")
        self.assertIsNone(september["forecast"])
        self.assertEqual(self.page["models"]["retail"]["status"], "WAITING_FOR_MONTHLY_FACTORS")

    def test_v7_metrics_and_factor_set_are_published(self) -> None:
        metric = self.page["metrics"]["retail"]
        self.assertTrue(math.isclose(metric["rmse"], 1.6429, abs_tol=1e-6))
        self.assertTrue(math.isclose(metric["mae"], 1.1956, abs_tol=1e-6))
        self.assertEqual(metric["observations"], 36)
        self.assertEqual(
            [item["id"] for item in self.page["highFrequency"]["社零"]],
            [
                "cpi_services_detail_yoy", "pmi_services_new_orders", "car_retail_level_yoy",
                "cpi_nonfood_detail_yoy", "cpi_yoy",
            ],
        )

    def test_car_factor_uses_last_complete_month_and_keeps_raw_as_of_date(self) -> None:
        car = next(item for item in self.page["highFrequency"]["社零"] if item["id"] == "car_retail_level_yoy")
        self.assertEqual(car["series"][-1]["date"], car["latestCompleteMonth"])
        self.assertIn(car["currentMonthStatus"], {"partial", "complete"})
        if car["currentMonthStatus"] == "complete":
            self.assertEqual(car["latestCompleteMonth"], car["sourceAsOf"])
        else:
            self.assertLess(car["latestCompleteMonth"], car["sourceAsOf"])


if __name__ == "__main__":
    unittest.main()
