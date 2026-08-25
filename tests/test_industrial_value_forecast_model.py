import unittest
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.industrial_value_forecast_model import (
    ARDL_FEATURES,
    BOTTOM_UP_CANDIDATES,
    BRIDGE_FEATURES,
    CORRELATION_MAX_FACTORS,
    FEATURES,
    FIXED_FACTOR_NAMES,
    bottom_up_walk_forward,
    correlation_walk_forward,
    fixed_volume_walk_forward,
    fit_accounting_weights,
    fixed_factor_walk_forward,
    monthly_target,
    project_simplex,
    rank_bottom_up_factors,
    rank_correlated_factors,
    valid_bridge_train,
)
from scripts.fetch_industrial_value_data import SERIES as FETCH_SERIES


class IndustrialValueForecastModelTest(unittest.TestCase):
    def test_consensus_is_not_a_model_feature(self) -> None:
        self.assertNotIn("consensus", FEATURES)
        self.assertTrue(all("consensus" not in config for config in FEATURES.values()))
        self.assertNotIn("consensus", BRIDGE_FEATURES)
        self.assertNotIn("consensus", ARDL_FEATURES)
        self.assertNotIn("consensus", BOTTOM_UP_CANDIDATES)
        self.assertNotIn("consensus", FIXED_FACTOR_NAMES)

    def test_production_factor_set_is_fixed_and_contains_power_proxy(self) -> None:
        self.assertEqual(FIXED_FACTOR_NAMES, (
            "power_coal",
            "blast_furnace",
            "methanol_rate",
            "full_tire_rate",
            "asphalt_rate",
        ))

    def test_fixed_volume_source_is_locked_to_verified_provider_id(self) -> None:
        self.assertEqual(FETCH_SERIES["actualMomSa"]["providerId"], "M002822189")

    def test_fast_bridge_does_not_use_lagged_actuals(self) -> None:
        self.assertNotIn("lag1", BRIDGE_FEATURES)
        self.assertNotIn("lag12", BRIDGE_FEATURES)
        self.assertEqual(
            {name for name in BRIDGE_FEATURES if name.endswith("_acceleration")},
            {"black_acceleration", "energy_acceleration", "chemical_acceleration", "auto_acceleration"},
        )

    def test_monthly_amplitude_is_separate_from_diffusion_vote(self) -> None:
        self.assertEqual(FEATURES["broad_car_output_yoy"]["role"], "amplitude")
        self.assertIn("broad_car_output_yoy", BRIDGE_FEATURES)
        self.assertNotIn("excavator_sales_yoy", BRIDGE_FEATURES)

    def test_invalid_pre_high_frequency_rows_are_excluded(self) -> None:
        index = pd.date_range("2019-10-31", "2022-12-31", freq="ME")
        frame = pd.DataFrame(index=index)
        frame["target"] = 5.0
        frame["lag1"] = 5.0
        for feature in BRIDGE_FEATURES:
            frame[feature] = np.nan
        frame.loc[frame.index >= pd.Timestamp("2020-03-31"), "diffusion"] = 50.0
        frame.loc[frame.index >= pd.Timestamp("2020-03-31"), "pmi_production"] = 50.0
        train = valid_bridge_train(frame, pd.Timestamp("2023-01-31"), BRIDGE_FEATURES)
        self.assertGreater(len(train), 0)
        self.assertGreaterEqual(train.index.min(), pd.Timestamp("2020-03-31"))

    def test_accounting_weights_are_nonnegative_and_sum_to_one(self) -> None:
        weights = project_simplex(np.array([-0.2, 0.9, 0.5]))
        self.assertTrue(np.all(weights >= 0.0))
        self.assertAlmostEqual(float(weights.sum()), 1.0)
        frame = pd.DataFrame({
            "mining": [1.0, 2.0, 3.0, 4.0],
            "manufacturing": [4.0, 5.0, 6.0, 7.0],
            "utility": [2.0, 1.0, 2.0, 1.0],
        })
        frame["target"] = 0.1 * frame["mining"] + 0.8 * frame["manufacturing"] + 0.1 * frame["utility"]
        fitted, residual = fit_accounting_weights(frame)
        np.testing.assert_allclose(fitted, [0.1, 0.8, 0.1], atol=1e-9)
        self.assertAlmostEqual(residual, 0.0)

    def test_january_is_removed_and_february_uses_combined_release(self) -> None:
        source = {"series": {
            "actualMonthly": {"observations": [["2025-01-31", -11.1], ["2025-02-28", 18.7], ["2025-03-31", 7.7]]},
            "actualYtd": {"observations": [["2025-01-31", -11.1], ["2025-02-28", 5.9], ["2025-03-31", 6.5]]},
        }}
        target = monthly_target(source)
        self.assertNotIn(pd.Timestamp("2025-01-31"), target.index)
        self.assertEqual(target.loc[pd.Timestamp("2025-02-28")], 5.9)
        self.assertEqual(target.loc[pd.Timestamp("2025-03-31")], 7.7)

    def test_bottom_up_selection_limits_each_family_to_one_factor(self) -> None:
        index = pd.date_range("2020-01-31", periods=24, freq="ME")
        x = np.linspace(-2.0, 2.0, len(index))
        train = pd.DataFrame({
            "target": 5.0 + x,
            "wire_inventory": -x,
            "steel_inventory": -x * 0.9,
            "polyester_rate": x * 0.8,
            "asphalt_rate": x * 0.7,
        }, index=index)
        selected = rank_bottom_up_factors(train)
        families = [item["family"] for item in selected]
        self.assertEqual(len(families), len(set(families)))
        self.assertLessEqual(len(selected), 3)

    def test_bottom_up_walk_forward_does_not_read_future_targets(self) -> None:
        index = pd.date_range("2020-01-31", periods=48, freq="ME")
        x = np.sin(np.arange(len(index)) / 3.0)
        target = pd.Series(5.0 + x, index=index)
        signals = pd.DataFrame({
            "wire_inventory": -x,
            "polyester_rate": x * 0.8,
            "asphalt_rate": x * 0.6,
        }, index=index)
        forecast_days = pd.DatetimeIndex([index[30], index[40]])
        original, _, _ = bottom_up_walk_forward(target, signals, forecast_days)
        revised_target = target.copy()
        revised_target.loc[index[31]:] += 20.0
        revised, _, _ = bottom_up_walk_forward(revised_target, signals, forecast_days)
        self.assertAlmostEqual(float(original.loc[index[30]]), float(revised.loc[index[30]]))

    def test_correlation_model_selects_one_factor_per_family(self) -> None:
        index = pd.date_range("2020-01-31", periods=30, freq="ME")
        x = np.sin(np.arange(len(index)) / 4.0)
        train = pd.DataFrame({
            "target": 5.0 + x,
            "wire_inventory": -x,
            "steel_inventory": -0.9 * x,
            "polyester_rate": 0.8 * x,
            "asphalt_rate": 0.7 * x,
        }, index=index)
        selected = rank_correlated_factors(train, train.iloc[-1])
        families = [item["family"] for item in selected]
        self.assertEqual(len(families), len(set(families)))
        self.assertLessEqual(len(selected), CORRELATION_MAX_FACTORS)

    def test_correlation_walk_forward_does_not_read_future_targets(self) -> None:
        index = pd.date_range("2020-01-31", periods=60, freq="ME")
        x = np.sin(np.arange(len(index)) / 3.0)
        target = pd.Series(5.0 + x, index=index)
        signals = pd.DataFrame({
            "wire_inventory": -x,
            "polyester_rate": x * 0.8,
            "asphalt_rate": x * 0.6,
        }, index=index)
        original, _ = correlation_walk_forward(target, signals)
        revised_target = target.copy()
        forecast_day = pd.Timestamp("2023-03-31")
        revised_target.loc[revised_target.index >= forecast_day] += 20.0
        revised, _ = correlation_walk_forward(revised_target, signals)
        self.assertAlmostEqual(float(original.loc[forecast_day]), float(revised.loc[forecast_day]))

    def test_fixed_factor_walk_forward_does_not_read_current_or_future_targets(self) -> None:
        index = pd.date_range("2020-01-31", periods=60, freq="ME")
        x = np.sin(np.arange(len(index)) / 3.0)
        target = pd.Series(5.0 + x, index=index)
        signals = pd.DataFrame({
            "power_coal": x,
            "blast_furnace": x * 0.9,
            "methanol_rate": x * 0.8,
            "full_tire_rate": x * 0.7,
            "asphalt_rate": x * 0.6,
        }, index=index)
        original = fixed_factor_walk_forward(target, signals)
        forecast_day = pd.Timestamp("2023-03-31")
        revised_target = target.copy()
        revised_target.loc[revised_target.index >= forecast_day] += 20.0
        revised = fixed_factor_walk_forward(revised_target, signals)
        self.assertAlmostEqual(float(original.loc[forecast_day]), float(revised.loc[forecast_day]))

    def test_fixed_volume_branch_does_not_read_future_mom_or_lagged_yoy(self) -> None:
        index = pd.date_range("2020-01-31", periods=48, freq="ME")
        mom = pd.Series(0.4 + 0.1 * np.sin(np.arange(len(index)) / 3.0), index=index)
        signals = pd.DataFrame({
            "wire_inventory": -mom.to_numpy(),
            "polyester_rate": mom.to_numpy() * 0.8,
            "asphalt_rate": mom.to_numpy() * 0.6,
        }, index=index)
        forecast_days = pd.DatetimeIndex([index[30], index[40]])
        original, _, _ = fixed_volume_walk_forward(mom, signals, forecast_days)
        revised_mom = mom.copy()
        revised_mom.loc[index[31]:] += 20.0
        revised, _, _ = fixed_volume_walk_forward(revised_mom, signals, forecast_days)
        self.assertAlmostEqual(float(original.loc[index[30]]), float(revised.loc[index[30]]))


if __name__ == "__main__":
    unittest.main()
