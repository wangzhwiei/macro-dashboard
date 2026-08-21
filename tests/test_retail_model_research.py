import json
import math
import unittest
from pathlib import Path

import pandas as pd

from scripts import research_retail_forecast as model


ROOT = Path(__file__).resolve().parents[1]


class RetailModelResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "scripts" / "research_retail_forecast.py").read_text(encoding="utf-8")
        cls.data = json.loads(
            (ROOT / "data" / "forecast-model" / "research_retail_ifind.json").read_text(encoding="utf-8")
        )
        cls.result = json.loads(
            (ROOT / "data" / "forecast-model" / "retail_model_research.json").read_text(encoding="utf-8")
        )

    def test_monthly_yoy_does_not_publish_a_trailing_partial_month(self):
        index = pd.to_datetime(["2025-07-31", "2025-08-31", "2026-07-31", "2026-08-09"])
        raw = pd.Series([100.0, 100.0, 110.0, 60.0], index=index)
        result = model.monthly_yoy(raw, "last")
        self.assertAlmostEqual(result.loc[pd.Timestamp("2026-07-31")], 10.0)
        self.assertTrue(pd.isna(result.loc[pd.Timestamp("2026-08-31")]))

    def test_fixed_ifind_series_are_exact(self):
        expected = {
            "actual_retail_yoy": ("M001625520", "社会消费品零售总额:当月同比"),
            "consensus_retail_yoy": ("M005682254", "预测平均值:社会消费品零售总额:当月同比"),
        }
        for key, (provider_id, name) in expected.items():
            item = self.data["series"][key]
            self.assertEqual(provider_id, item["providerId"])
            self.assertEqual(name, item["name"])
            self.assertEqual("M", item["frequency"])
            self.assertEqual("%", item["unit"])

    def test_consensus_is_comparison_only(self):
        self.assertEqual("comparison_only", self.result["consensus"]["modelUse"])
        forecast_position = self.source.index("corrected_series =")
        consensus_load_position = self.source.index('checked_series(data, "consensus_retail_yoy")')
        self.assertGreater(consensus_load_position, forecast_position)

    def test_consumption_detail_series_are_fixed(self):
        expected = {
            "cpi_food_yoy": "M002826732",
            "cpi_services_yoy": "M002840898",
            "pmi_services_business": "M004369936",
            "pmi_services_new_orders": "M005933612",
            "pmi_services_expectations": "M005933616",
        }
        for key, provider_id in expected.items():
            item = self.data["series"][key]
            self.assertEqual(provider_id, item["providerId"])
            self.assertEqual("M", item["frequency"])
            self.assertEqual("%", item["unit"])

    def test_reported_rmse_matches_walk_forward_history(self):
        primary = self.result["productionDecision"]["primaryCandidate"]
        rows = [row for row in self.result["history"] if row["actual"] is not None and row[primary] is not None]
        rmse = math.sqrt(sum((row[primary] - row["actual"]) ** 2 for row in rows) / len(rows))
        self.assertAlmostEqual(self.result["metrics"][primary]["rmse"], rmse, places=4)
        self.assertEqual("2020-03", self.result["metrics"][primary]["sampleStart"])

    def test_research_candidate_is_not_marked_production_ready(self):
        self.assertEqual("research_only", self.result["productionDecision"]["status"])
        self.assertEqual(
            self.result["rankedTopKRace"]["selectedModel"],
            self.result["productionDecision"]["primaryCandidate"],
        )

    def test_scope_screen_excludes_real_estate_and_general_services(self):
        candidates = set(self.result["factorCandidates"])
        excluded = self.result["factorScreeningDecision"]["scopeExclusions"]
        for key in (
            "newhome_30_area_yoy", "secondhand_shenzhen_area_yoy",
            "metro_composite_yoy", "boxoffice_yoy", "movie_audience_yoy",
            "flights_yoy",
        ):
            self.assertNotIn(key, candidates)
            self.assertIn(key, excluded)

    def test_collinearity_screen_is_pre_backtest_only(self):
        screen = self.result["scopeCompliantCorrelationScreen"]
        self.assertEqual("2019-12", self.result["method"]["factorScreenEnd"])
        self.assertEqual("2022-12", self.result["method"]["selectionEnd"])
        self.assertEqual("2023-03", self.result["method"]["holdoutStart"])
        self.assertEqual(0.75, screen["pairwiseThreshold"])
        car_retail = next(row for row in screen["audit"] if row["key"] == "car_retail_level_yoy")
        self.assertTrue(car_retail["accepted"])
        cpi_goods = next(row for row in screen["audit"] if row["key"] == "cpi_consumer_goods_detail_yoy")
        self.assertFalse(cpi_goods["accepted"])
        self.assertEqual("cpi_yoy", cpi_goods["blockedBy"])
        self.assertGreaterEqual(abs(cpi_goods["pairwiseChangeCorrelation"]), 0.75)

    def test_top_k_selection_does_not_use_holdout(self):
        race = self.result["rankedTopKRace"]
        expected = min(
            race["selectionPeriod"],
            key=lambda key: race["selectionPeriod"][key]["rmse"],
        )
        self.assertEqual(expected, race["selectedModel"])
        self.assertIn("2023+ is untouched holdout", race["selectionRule"])

    def test_ranked_candidate_stability_gate_matches_metrics(self):
        stability = self.result["stabilityAnalysis"]
        decision = self.result["productionDecision"]
        race = self.result["rankedTopKRace"]
        candidate = race["selectedModel"]
        passes = (
            race["selectionPeriod"][candidate]["rmse"]
            < race["scopeBaseline"]["selectionPeriod"]["rmse"]
            and race["holdoutPeriod"][candidate]["rmse"]
            < race["scopeBaseline"]["holdoutPeriod"]["rmse"]
            and stability["holdoutYearWins"] >= stability["requiredHoldoutYearWins"]
        )
        self.assertEqual(passes, stability["candidatePassesStabilityGate"])
        self.assertEqual("accepted" if passes else "rejected_unstable", decision["robustnessStatus"])

    def test_annual_and_rolling_stability_are_reported(self):
        stability = self.result["stabilityAnalysis"]
        self.assertEqual(
            ["2020", "2021", "2022", "2023", "2024", "2025", "2026"],
            list(stability["annual"]),
        )
        self.assertGreater(len(stability["rollingTwelveCalendarMonths"]), 20)
        self.assertEqual(10, stability["rollingTwelveCalendarMonths"][0]["publishedObservations"])

    def test_calendar_is_complete_and_structural_gaps_are_labeled(self):
        rows = self.result["history"]
        periods = [row["date"][:7] for row in rows]
        self.assertEqual(len(periods), len(set(periods)))
        for previous, current in zip(periods, periods[1:]):
            py, pm = map(int, previous.split("-"))
            cy, cm = map(int, current.split("-"))
            self.assertEqual(py * 12 + pm + 1, cy * 12 + cm)
        for row in rows:
            month = int(row["date"][5:7])
            if month in (1, 2):
                self.assertEqual("not_applicable", row["actualStatus"])
                self.assertEqual("not_applicable", row["forecastStatus"])
            elif row["date"] <= "2026-07-31":
                self.assertEqual("published", row["actualStatus"])

    def test_partial_current_month_is_not_published_as_forecast(self):
        latest = self.result["latestForecast"]
        self.assertIsNone(latest["model"])
        self.assertEqual(
            "waiting_for_complete_or_same_window_hf",
            latest["stages"]["preliminary"]["status"],
        )
        self.assertEqual(
            "waiting_for_complete_current_month_inputs",
            latest["stages"]["preReleaseReview"]["status"],
        )


if __name__ == "__main__":
    unittest.main()
