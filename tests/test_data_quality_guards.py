from __future__ import annotations

import unittest

from scripts.validate_dashboard import (
    duplicate_series_groups,
    median_gap_days,
    provider_code_collisions,
    rate_bound_violations,
)


class DataQualityGuardTests(unittest.TestCase):
    def test_provider_code_collisions_are_reported(self) -> None:
        definitions = [
            {"series": [{"code": "CJHX:A"}]},
            {"series": [{"code": "CJHX:B"}]},
        ]
        collisions = provider_code_collisions(
            {"CJHX:A": "S100", "CJHX:B": "S100"}, definitions
        )
        self.assertEqual(collisions, [("S100", ["CJHX:A", "CJHX:B"])])

    def test_exact_duplicate_series_are_reported(self) -> None:
        series = [
            {"date": "2026-07-01", "value": 1.0},
            {"date": "2026-07-08", "value": 2.0},
        ]
        groups = duplicate_series_groups(
            [
                {"id": "first", "series": series},
                {"id": "second", "series": list(series)},
                {"id": "different", "series": [{"date": "2026-07-01", "value": 3.0}]},
            ]
        )
        self.assertEqual(groups, [["first", "second"]])

    def test_weekly_cadence_helper_distinguishes_daily_data(self) -> None:
        daily = [
            {"date": "2026-07-01", "value": 1},
            {"date": "2026-07-02", "value": 2},
            {"date": "2026-07-03", "value": 3},
        ]
        self.assertEqual(median_gap_days(daily), 1.0)

    def test_operating_rate_must_stay_between_zero_and_one_hundred(self) -> None:
        indicator = {
            "name": "PVC开工率",
            "unit": "%",
            "series": [
                {"date": "2026-07-01", "value": 81.2},
                {"date": "2026-07-08", "value": 24591.7},
            ],
        }
        violations = rate_bound_violations(indicator)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["value"], 24591.7)


if __name__ == "__main__":
    unittest.main()
