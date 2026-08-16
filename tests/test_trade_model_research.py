from __future__ import annotations

import sys
import unittest
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from research_trade_model_race import validate_ifind_series  # noqa: E402


class TradeResearchValidationTests(unittest.TestCase):
    EXPECTED = {
        "providerId": "M005682256",
        "name": "预测平均值:出口金额(美元计价):当月同比",
    }

    def test_exact_ifind_metadata_is_accepted(self) -> None:
        validate_ifind_series({
            "index_id": "M005682256", "name": self.EXPECTED["name"],
            "freq": "M", "unit": "%",
        }, self.EXPECTED)

    def test_fuzzy_m0_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "providerId mismatch"):
            validate_ifind_series({
                "index_id": "M001625226", "name": "M0(流通中货币):同比",
                "freq": "M", "unit": "%",
            }, self.EXPECTED)

    def test_manifest_keeps_consensus_ids_and_validated_export_actual(self) -> None:
        manifest = json.loads((ROOT / "data" / "trade-model" / "ifind-series-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["consensus"]["exports"]["providerId"], "M005682256")
        self.assertEqual(manifest["consensus"]["imports"]["providerId"], "M005682257")
        self.assertEqual(manifest["actual"]["exports"]["providerId"], "M002888330")
        self.assertEqual(manifest["actual"]["imports"]["providerId"], "M002888203")
        self.assertIn("only get_edb_data", manifest["mcpCapability"])
        self.assertIn("post-response validation", manifest["mcpCapability"])

    def test_saved_baselines_have_exact_provider_ids(self) -> None:
        for side, provider_id in (("export", "M005682256"), ("import", "M005682257")):
            payload = json.loads(
                (ROOT / "data" / "trade-model" / f"baseline_{side}_yoy.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["_meta"]["validatedProviderId"], provider_id)
            self.assertEqual(payload["_meta"]["attrs"]["index_id"], provider_id)
            self.assertNotIn("至", payload["_meta"]["query"])
            self.assertEqual(len(payload["data"]), 60)

    def test_consensus_is_benchmark_only(self) -> None:
        source = (ROOT / "scripts" / "research_trade_model_race.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, re.compile(r"target\s*-\s*consensus"))
        self.assertNotIn("consensus_bias_corrected", source)
        self.assertNotIn("consensus_hf_residual", source)
        result = json.loads(
            (ROOT / "outputs" / "trade-model-research" / "model-race.json").read_text(encoding="utf-8")
        )
        self.assertEqual(result["consensus_role"], "evaluation_benchmark_only")
        self.assertIn("consensus prohibited", result["forecast_factor_policy"])

    def test_corrected_standalone_model_improves_old_ar(self) -> None:
        result = json.loads(
            (ROOT / "outputs" / "trade-model-research" / "model-race.json").read_text(encoding="utf-8")
        )
        for key in ("exports", "imports"):
            scores = result["targets"][key]["common_sample_scores"]
            self.assertLess(scores["seasonal_hf_gated"]["rmse"], scores["ar"]["rmse"])
        import_scores = result["targets"]["imports"]["common_sample_scores"]
        self.assertLess(import_scores["seasonal_hf_gated"]["rmse"], import_scores["consensus"]["rmse"])

    def test_current_forecast_waits_for_every_fixed_factor(self) -> None:
        result = json.loads(
            (ROOT / "outputs" / "trade-model-research" / "model-race.json").read_text(encoding="utf-8")
        )
        for key in ("exports", "imports"):
            current = result["targets"][key]["current_forecast"]
            self.assertIsNone(current["forecast"])
            self.assertEqual(current["status"], "WAITING_FOR_FIXED_FACTORS")
            self.assertTrue(current["missing_factors"])
            self.assertRegex(current["earliest_factor_release_date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertNotIn("consensus", current)

    def test_export_uses_seasonal_factor_model_without_lag_zero_vietnam(self) -> None:
        source = (ROOT / "scripts" / "research_trade_model_race.py").read_text(encoding="utf-8")
        self.assertIn("vietnam_export_yoy_l1_level", source)
        self.assertNotIn('"vietnam_export_yoy_l0_level"', source)
        result = json.loads(
            (ROOT / "outputs" / "trade-model-research" / "model-race.json").read_text(encoding="utf-8")
        )
        export_scores = result["targets"]["exports"]["all_available_scores"]
        self.assertLess(
            export_scores["seasonal_factor_corrected"]["rmse"],
            export_scores["anchored_factor"]["rmse"],
        )
        self.assertEqual(
            result["targets"]["exports"]["current_forecast"]["method"],
            "export_fixed_factors_cny_gated",
        )

    def test_destination_import_bridge_is_validated_and_improves_export(self) -> None:
        factors = json.loads(
            (ROOT / "data" / "trade-model" / "trade_partner_import_factors.json").read_text(encoding="utf-8")
        )
        self.assertEqual(factors["series"]["korea_imports_from_china_yoy"]["providerId"], "G022252836")
        self.assertEqual(factors["series"]["brazil_imports_from_china_yoy"]["providerId"], "G020023687")
        self.assertEqual(factors["series"]["korea_imports_from_china_yoy"]["availabilityLagMonths"], 0)
        self.assertEqual(factors["series"]["eu27_imports_from_china_yoy"]["availabilityLagMonths"], 2)
        result = json.loads(
            (ROOT / "outputs" / "trade-model-research" / "model-race.json").read_text(encoding="utf-8")
        )
        scores = result["targets"]["exports"]["all_available_scores"]
        self.assertLess(scores["destination_import_bridge"]["rmse"], scores["seasonal_factor_corrected"]["rmse"])
        source = (ROOT / "scripts" / "research_trade_model_race.py").read_text(encoding="utf-8")
        self.assertIn('"korea_imports_from_china_yoy": 0', source)
        self.assertIn('"taiwan_imports_from_mainland_yoy": 1', source)
        self.assertIn('"eu27_imports_from_china_yoy": 2', source)
        self.assertNotIn('"malaysia_imports_from_china_yoy":', source.split("PARTNER_PREFERRED_LAGS", 1)[1].split("}", 1)[0])

    def test_major_partner_lags_are_research_only_until_increment_is_proven(self) -> None:
        factors = json.loads(
            (ROOT / "data" / "trade-model" / "trade_partner_import_factors.json").read_text(encoding="utf-8")
        )["series"]
        self.assertEqual(factors["us_imports_from_china_value"]["providerId"], "W034560213")
        self.assertEqual(factors["japan_imports_from_china_value"]["providerId"], "G019341325")
        self.assertEqual(factors["us_imports_from_china_value"]["availabilityLagMonths"], 1)
        self.assertEqual(factors["japan_imports_from_china_value"]["availabilityLagMonths"], 1)
        result = json.loads(
            (ROOT / "outputs" / "trade-model-research" / "major-partner-lag-increment.json").read_text(encoding="utf-8")
        )
        self.assertEqual(result["metrics"]["baseline_plus_us1_japan1"]["rmse"], 6.644)
        self.assertLess(
            result["forced_increment_metrics"]["forced_japan_lag1"]["rmse_improvement_pct"], 0
        )

    def test_cny_gate_reduces_export_tail_error_without_consensus(self) -> None:
        result = json.loads(
            (ROOT / "outputs" / "trade-model-research" / "model-race.json").read_text(encoding="utf-8")
        )
        scores = result["targets"]["exports"]["all_available_scores"]
        common = result["targets"]["exports"]["common_sample_scores"]
        self.assertLess(
            scores["destination_import_cny_gated"]["rmse"],
            scores["destination_import_bridge"]["rmse"],
        )
        self.assertLess(
            common["destination_import_cny_gated"]["rmse"], common["consensus"]["rmse"]
        )
        source = (ROOT / "scripts" / "research_trade_model_race.py").read_text(encoding="utf-8")
        cny_block = source.split("def destination_import_cny_gated_prediction", 1)[1].split("def ", 1)[0]
        self.assertNotIn("consensus", cny_block)

    def test_fixed_import_cny_model_improves_ungated_model(self) -> None:
        result = json.loads(
            (ROOT / "outputs" / "trade-model-research" / "model-race.json").read_text(encoding="utf-8")
        )["targets"]["imports"]
        scores = result["all_available_scores"]
        self.assertIn("anchored_factor", scores)
        self.assertIn("import_fixed_cny_gated", scores)
        self.assertLess(scores["import_fixed_cny_gated"]["rmse"], scores["import_fixed_bridge"]["rmse"])
        self.assertLess(scores["import_fixed_cny_gated"]["mae"], scores["import_fixed_bridge"]["mae"])
        current = result["current_forecast"]
        self.assertEqual(current["method"], "import_fixed_factors_cny_gated")
        self.assertTrue(current["parallel_import_cny_candidate"]["original_model_preserved"])
        self.assertIsNone(current["forecast"])
        self.assertIn("ungated_model_forecast", current)

    def test_anchor_model_uses_validated_non_consensus_factors(self) -> None:
        factors = json.loads(
            (ROOT / "data" / "trade-model" / "trade_anchor_factors.json").read_text(encoding="utf-8")
        )
        self.assertFalse(factors["_meta"]["consensusUsed"])
        self.assertEqual(factors["series"]["korea_export_yoy"]["providerId"], "G012203163")
        self.assertEqual(factors["series"]["vietnam_export_yoy"]["providerId"], "W011330012")
        result = json.loads(
            (ROOT / "outputs" / "trade-model-research" / "model-race.json").read_text(encoding="utf-8")
        )
        import_scores = result["targets"]["imports"]["common_sample_scores"]
        self.assertLess(import_scores["anchored_factor"]["rmse"], import_scores["consensus"]["rmse"])
        current = result["targets"]["imports"]["current_forecast"]
        self.assertEqual(current["method"], "import_fixed_factors_cny_gated")
        self.assertEqual(current["selected_factors"], ["korea_export_yoy_d1"])
        self.assertEqual(current["missing_factors"], ["korea_export_yoy_d1"])

    def test_fixed_factor_sets_and_no_fallback_policy(self) -> None:
        source = (ROOT / "scripts" / "research_trade_model_race.py").read_text(encoding="utf-8")
        self.assertIn('EXPORT_FIXED_FACTORS = (', source)
        self.assertIn('"korea_imports_from_china_yoy_lag0"', source)
        self.assertIn('"taiwan_imports_from_mainland_yoy_lag1"', source)
        self.assertIn('"thailand_imports_from_china_yoy_lag1"', source)
        self.assertIn('IMPORT_FIXED_FACTORS = ("korea_export_yoy_d1",)', source)
        result = json.loads(
            (ROOT / "outputs" / "trade-model-research" / "model-race.json").read_text(encoding="utf-8")
        )
        self.assertIn("no fallback", result["forecast_factor_policy"])


if __name__ == "__main__":
    unittest.main()
