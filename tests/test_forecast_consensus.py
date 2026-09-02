import unittest

from scripts.fetch_forecast_consensus import (
    CONFIG,
    build_query,
    candidate_to_records,
    forward_fill_months,
    merge_target_records,
    validate_candidate,
)


class ForecastConsensusTest(unittest.TestCase):
    def test_fixed_ids_and_chinese_names_are_in_query(self):
        expected = {
            "cpi": ("预测平均值:CPI:当月同比", "M005682252"),
            "ppi": ("预测平均值:PPI:当月同比", "M005682253"),
            "pmi": ("预测平均值:PMI", "M005779145"),
        }
        for key, (name, provider_id) in expected.items():
            config = CONFIG[key]
            self.assertEqual(config["queryName"], name)
            self.assertEqual(config["providerId"], provider_id)
            query = build_query(config, "2023-01-01", "2026-08-10")
            self.assertIn(name, query)
            self.assertIn(provider_id, query)

    def test_pmi_internal_missing_month_uses_previous_month(self):
        candidate = {
            "records": [["2026-03-31", 50.0], ["2026-05-31", 49.9]],
        }
        records = candidate_to_records(
            candidate, CONFIG["pmi"], "2026-03-01", "2026-08-10", "now"
        )
        filled = forward_fill_months(records)
        self.assertEqual(
            [row["date"] for row in filled],
            ["2026-03-31", "2026-04-30", "2026-05-31"],
        )
        self.assertEqual(filled[1]["value"], 50.0)
        self.assertTrue(filled[1]["imputed"])
        self.assertEqual(filled[1]["imputedFrom"], "2026-03-31")
        self.assertFalse(filled[2]["imputed"])

    def test_forward_fill_does_not_extend_beyond_latest_observation(self):
        records = [{"date": "2026-05-31", "value": 49.9, "imputed": False}]
        self.assertEqual(forward_fill_months(records), records)

    def test_provider_id_drift_is_rejected(self):
        candidate = {
            "providerId": "M002043802",
            "name": "PMI",
            "frequency": "M",
            "unit": "%",
        }
        with self.assertRaisesRegex(RuntimeError, "ID漂移"):
            validate_candidate(CONFIG["pmi"], candidate)

    def test_only_active_month_can_replace_a_historical_consensus_vintage(self):
        previous = [
            {"date": "2026-07-31", "value": 3.4},
            {"date": "2026-08-31", "value": 2.5},
        ]
        fresh = [
            {"date": "2026-07-31", "value": 3.1},
            {"date": "2026-08-31", "value": 2.3},
        ]
        merged = merge_target_records(previous, fresh, "2026-08-31")
        self.assertEqual(merged[0]["value"], 3.4)
        self.assertEqual(merged[1]["value"], 2.3)


if __name__ == "__main__":
    unittest.main()
