from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "investment_level_forecast_model.py"
SOURCE = ROOT / "data" / "investment-model" / "source_data.json"
OUTPUT = ROOT / "data" / "investment-model" / "forecast_results.json"


def load_module():
    spec = importlib.util.spec_from_file_location("investment_level_forecast_model", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load investment level model")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InvestmentForecastModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.source = json.loads(SOURCE.read_text(encoding="utf-8-sig"))
        cls.result = json.loads(OUTPUT.read_text(encoding="utf-8-sig"))
        cls.frame, cls.raw_amount, cls.level, cls.flow, cls.actual, cls.consensus = cls.module.build_frame(
            cls.source,
            cls.module.read_json(cls.module.DEFAULT_PRODUCTION),
            cls.module.read_json(cls.module.DEFAULT_DASHBOARD),
            cls.module.read_json(cls.module.DEFAULT_INDUSTRIAL),
            cls.module.read_json(cls.module.DEFAULT_CREDIT),
        )

    def test_fixed_provider_ids_and_roles(self):
        series = self.source["series"]
        self.assertEqual(series["fixed_asset_investment_ytd_yoy"]["providerId"], "M001620575")
        self.assertEqual(series["fixed_asset_investment_ytd_amount"]["providerId"], "M001620537")
        self.assertEqual(series["fixed_asset_investment_ytd_amount"]["role"], "target_level")
        self.assertEqual(series["fixed_asset_investment_consensus"]["providerId"], "M005682259")
        self.assertEqual(series["fixed_asset_investment_consensus"]["role"], "comparison_only")
        self.assertEqual(series["infrastructure_investment_ytd_amount"]["role"], "lagged_component_level_only")
        self.assertEqual(series["real_estate_investment_ytd_amount"]["role"], "lagged_component_level_only")

    def test_consensus_is_physically_separate_from_model_frame(self):
        self.assertNotIn("consensus", self.frame.columns)
        self.assertTrue(all("consensus" not in column.lower() for column in self.frame.columns))
        self.assertGreater(self.consensus.notna().sum(), 0)

    def test_comparable_fixed_level_reproduces_official_yoy(self):
        rebuilt = (self.level / self.level.shift(12) - 1.0) * 100.0
        joined = pd.concat([rebuilt.rename("rebuilt"), self.actual.rename("actual")], axis=1).dropna()
        self.assertGreater(len(joined), 100)
        self.assertLess(float((joined["rebuilt"] - joined["actual"]).abs().max()), 1e-9)

    def test_previous_cumulative_yoy_is_not_a_predictor(self):
        forbidden = {"target_l1", "actual_l1", "yoy_l1", "previous_yoy", "persistence"}
        self.assertTrue(forbidden.isdisjoint(self.frame.columns))
        self.assertEqual(self.result["notes"][0], "上一期累计同比不进入金额流量方程，也不作为预测锚。")

    def test_february_is_a_separate_combined_period(self):
        history = {row["date"]: row for row in self.result["history"]}
        self.assertNotAlmostEqual(history["2026-02"]["model"], history["2025-02"]["actual"])
        old_error = abs(history["2025-02"]["actual"] - history["2026-02"]["actual"])
        new_error = abs(history["2026-02"]["model"] - history["2026-02"]["actual"])
        self.assertLess(new_error, old_error)

    def test_bridge_debias_uses_only_preceding_ordinary_months(self):
        index = pd.to_datetime(["2025-01-31", "2025-03-31", "2025-04-30"])
        candidates = pd.DataFrame({"bridge": [2.0, 2.0, 2.0]}, index=index)
        actual_flow = pd.Series([1.0, 1.0, 100.0], index=index)
        adjusted = self.module.debias_bridge_candidates(
            candidates,
            actual_flow,
            keys=("bridge",),
            window=2,
            shrinkage=1.0,
        )
        self.assertAlmostEqual(float(adjusted.loc[pd.Timestamp("2025-04-30"), "bridge"]), 1.0)

    def test_high_frequency_monthly_cutoff_is_day_24(self):
        values = pd.Series(
            [1.0, 3.0, 100.0],
            index=pd.to_datetime(["2026-08-10", "2026-08-24", "2026-08-25"]),
        )
        monthly = self.module.monthly_partial_mean(values)
        self.assertAlmostEqual(float(monthly.loc[pd.Timestamp("2026-08-31")]), 2.0)

    def test_performance_gate_and_lag_diagnostic_pass(self):
        gate = self.result["performanceGateVsConsensus"]
        comparison = self.result["comparisonOnCommonSample"]
        lag = self.result["lagDiagnostics"]
        self.assertTrue(gate["passed"])
        self.assertLess(gate["modelRmse"], gate["consensusRmse"])
        self.assertEqual(comparison["model"]["sampleStart"], "2023-03")
        self.assertEqual(comparison["model"]["observations"], comparison["consensus"]["observations"])
        self.assertGreater(lag["actualCorrelation"], lag["previousActualCorrelation"])
        self.assertLess(abs(comparison["model"]["bias"]), 0.05)

    def test_bias_corrected_model_configuration_is_serialized(self):
        calibration = self.result["featureGroups"]["bridgeCalibration"]
        self.assertEqual(self.result["modelVersion"], "investment-level-flow-bridge-v4-bias-corrected")
        self.assertTrue(self.result["modelFrozen"])
        self.assertEqual(self.result["modelFrozenAt"], "2026-08-27")
        self.assertEqual(calibration["trainingWindowMonths"], 24)
        self.assertEqual(calibration["ordinaryMonthResidualWindow"], 9)
        self.assertEqual(calibration["residualShrinkage"], 0.5)
        self.assertEqual(calibration["onlineBiasPenalty"], 1.0)

    def test_dashboard_payload_uses_frozen_model_and_separates_consensus(self):
        payload = {"displayStart": "2023-01-31"}
        published = self.module.augment_forecast_payload(payload)
        key = "fixed_asset_investment"
        latest = published["history"][key][-1]
        inputs = published["highFrequency"]["投资"]
        lock = published["modelLocks"]["investment"]

        self.assertEqual(latest["forecast"], self.result["current"]["model"])
        self.assertEqual(published["history"][key][0]["date"], "2023-01-31")
        self.assertEqual(published["history"][key][0]["forecastKind"], "structural_gap")
        self.assertIsNone(latest["actual"])
        self.assertEqual(latest["consensus"], self.result["current"]["consensus"])
        self.assertEqual(lock["version"], self.result["modelVersion"])
        self.assertEqual(lock["frozenAt"], self.result["modelFrozenAt"])
        self.assertEqual(lock["targets"], [key])
        self.assertEqual(len(inputs), 7)
        self.assertEqual(
            {item["id"] for item in inputs},
            {"blast_furnace", "rebar_rate", "power_coal", "pta_rate", "methanol_rate", "car_wholesale", "car_retail"},
        )
        self.assertTrue(all("一致预期不进入" in item["modelUsageNote"] for item in inputs))
        self.assertIn("一致预期仅用于事后比较", published["models"][key]["formula"])


if __name__ == "__main__":
    unittest.main()
