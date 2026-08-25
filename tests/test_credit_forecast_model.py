import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("credit_forecast_model", ROOT / "scripts" / "credit_forecast_model.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CreditForecastModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = MODULE.build(
            ROOT / "data" / "credit-model" / "source_data.json",
            ROOT.parent / "release-gh-pages-v7-20260821" / "data" / "forecasts.json",
            ROOT / "data" / "industrial-value-model" / "forecast_results.json",
        )

    def test_three_targets_are_finite(self):
        self.assertEqual(set(self.payload["current"]), {"m2_yoy", "new_rmb_loans", "social_financing"})
        for result in self.payload["current"].values():
            self.assertIsInstance(result["model"], float)

    def test_production_model_is_frozen(self):
        self.assertTrue(self.payload["modelFrozen"])
        self.assertEqual(self.payload["modelVersion"], "credit-v1.0.0")
        self.assertEqual(self.payload["modelFrozenAt"], "2026-08-25")
        expected = {
            "seasonal_sparse_a20_w84": (["change_l12", "change_l24", "change_l36"], 20.0, 84),
            "credit_sparse_a20_w60": (["change_l12", "change_l24", "change_l36", "change_mean3_l1", "loan_model"], 20.0, 60),
            "credit_sparse_a50_w84": (["change_l12", "change_l24", "change_l36", "change_mean3_l1", "loan_model"], 50.0, 84),
            "bill_sparse_a50_w60": (["change_l12", "change_l24", "change_l36", "change_mean3_l1", "loan_model", "bill_yoy"], 50.0, 60),
        }
        actual = self.payload["diagnostics"]["m2_yoy"]["candidateSpecifications"]
        self.assertEqual(
            {key: (value["features"], value["alpha"], value["window"]) for key, value in actual.items()},
            expected,
        )

    def test_dashboard_adapter_exposes_all_three_frozen_targets(self):
        base = json.loads((ROOT / "docs" / "data" / "forecasts.json").read_text(encoding="utf-8"))
        adapted = MODULE.augment_forecast_payload(
            base, ROOT / "data" / "credit-model" / "forecast_results.json"
        )
        self.assertEqual(adapted["modelLocks"]["credit"]["version"], "credit-v1.0.0")
        for key in ("m2_yoy", "new_rmb_loans", "social_financing"):
            self.assertIn(key, adapted["history"])
            self.assertEqual(adapted["history"][key][-1]["forecastKind"], "live_nowcast")
            self.assertIsNone(adapted["history"][key][-1]["actual"])

    def test_consensus_is_comparison_only(self):
        self.assertIn("excluded", self.payload["consensusPolicy"])
        self.assertTrue(all(key.endswith("consensus") for key in self.payload["providerIds"] if "consensus" in key))
        source = json.loads((ROOT / "data" / "credit-model" / "source_data.json").read_text(encoding="utf-8-sig"))
        self.assertTrue(all(source["series"][key]["role"] == "comparison_only" for key in source["series"] if "consensus" in key))

    def test_forecasts_are_invariant_to_consensus_values(self):
        source_path = ROOT / "data" / "credit-model" / "source_data.json"
        source = json.loads(source_path.read_text(encoding="utf-8-sig"))
        for key in ("m2_consensus", "new_rmb_loans_consensus", "social_financing_consensus"):
            source["series"][key]["observations"] = [
                [date, float(value) + 999999999.0]
                for date, value in source["series"][key]["observations"]
            ]
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / "source.json"
            altered.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
            rebuilt = MODULE.build(
                altered,
                ROOT.parent / "release-gh-pages-v7-20260821" / "data" / "forecasts.json",
                ROOT / "data" / "industrial-value-model" / "forecast_results.json",
            )
        self.assertEqual(
            {key: value["model"] for key, value in rebuilt["current"].items()},
            {key: value["model"] for key, value in self.payload["current"].items()},
        )

    def test_backtest_has_real_history(self):
        for result in self.payload["comparisonOnCommonSample"].values():
            self.assertGreaterEqual(result["commonObservations"], 36)

    def test_target_specific_models_improve_legacy_backtest(self):
        comparison = self.payload["comparisonOnCommonSample"]
        self.assertLess(comparison["m2_yoy"]["model"]["rmse"], comparison["m2_yoy"]["consensus"]["rmse"])
        self.assertLess(comparison["new_rmb_loans"]["model"]["rmse"], 0.35)
        self.assertLess(comparison["social_financing"]["model"]["rmse"], 0.68)

    def test_m2_is_forecast_in_balance_space(self):
        diagnostics = self.payload["diagnostics"]["m2_yoy"]
        self.assertLess(diagnostics["final"]["rmse"], diagnostics["legacyPersistence"]["rmse"])
        self.assertGreater(diagnostics["turningPointHitRatePct"], diagnostics["legacyTurningPointHitRatePct"])
        self.assertGreater(diagnostics["latestForecastBalanceTrillion"], 0)
        self.assertEqual(self.payload["providerIds"]["m2_level"], "M001625221")

    def test_m2_candidates_are_sparse_and_do_not_recycle_tsf_forecast(self):
        specifications = self.payload["diagnostics"]["m2_yoy"]["candidateSpecifications"]
        self.assertLessEqual(max(len(item["features"]) for item in specifications.values()), 6)
        self.assertTrue(all("tsf_model" not in item["features"] for item in specifications.values()))
        self.assertTrue(all("m2_yoy" not in item["features"] for item in specifications.values()))

    def test_macro_information_set_matches_release_timing(self):
        current = MODULE.current_macro_forecasts(
            ROOT.parent / "release-gh-pages-v7-20260821" / "data" / "forecasts.json",
            ROOT / "data" / "industrial-value-model" / "forecast_results.json",
        )
        information = MODULE.macro_information_series(
            ROOT / "data" / "forecast-model" / "model_inputs.json",
            ROOT / "data" / "industrial-value-model" / "targets_consensus.json",
            current,
        )
        inputs = MODULE.read_json(ROOT / "data" / "forecast-model" / "model_inputs.json")
        for key in ("cpi", "ppi", "pmi"):
            actual = MODULE.series(inputs["targets"][key]["data"])
            historical_month = actual.index[actual.index < MODULE.TARGET_MONTH][-1]
            self.assertEqual(information[f"now_{key}"].loc[historical_month], actual.loc[historical_month])
            self.assertEqual(information[f"now_{key}"].loc[MODULE.TARGET_MONTH], current[key])
        industrial_source = MODULE.read_json(
            ROOT / "data" / "industrial-value-model" / "targets_consensus.json"
        )
        industrial = MODULE.series(industrial_source["series"]["actualMonthly"]["observations"])
        source_month = industrial.index[(industrial.index + pd.offsets.MonthEnd(1)) < MODULE.TARGET_MONTH][-1]
        historical_month = source_month + pd.offsets.MonthEnd(1)
        self.assertEqual(
            information["now_industrial_value"].loc[historical_month], industrial.loc[source_month]
        )

    def test_consensus_performance_gate_is_mechanical(self):
        for key, gate in self.payload["performanceGateVsConsensus"].items():
            self.assertEqual(gate["passed"], gate["modelRmse"] < gate["consensusRmse"])
            self.assertAlmostEqual(gate["remainingGap"], gate["modelRmse"] - gate["consensusRmse"], places=6)

    def test_tsf_component_bridge_uses_fixed_ids(self):
        provider_ids = self.payload["providerIds"]
        self.assertTrue(all(key in provider_ids for key in MODULE.TSF_COMPONENT_KEYS))
        self.assertEqual(provider_ids["tsf_rmb_loans"], "M002917567")
        self.assertEqual(provider_ids["tsf_government_bonds"], "M004891011")


if __name__ == "__main__":
    unittest.main()
