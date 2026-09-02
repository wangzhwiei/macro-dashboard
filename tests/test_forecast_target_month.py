import unittest
from unittest.mock import patch

import pandas as pd

from scripts.refresh_forecasts_fast import resolve_target_month


class ForecastTargetMonthTests(unittest.TestCase):
    def test_previous_month_is_retained_until_price_actuals_arrive(self) -> None:
        july = pd.Series([1.0], index=[pd.Timestamp("2026-07-31")])
        with patch("scripts.refresh_forecasts_fast.ifind_series", return_value=({}, july)):
            self.assertEqual(resolve_target_month({}, as_of="2026-09-02"), pd.Timestamp("2026-08-31"))

    def test_calendar_month_begins_after_previous_price_release(self) -> None:
        august = pd.Series([1.0], index=[pd.Timestamp("2026-08-31")])
        with patch("scripts.refresh_forecasts_fast.ifind_series", return_value=({}, august)):
            self.assertEqual(resolve_target_month({}, as_of="2026-09-09"), pd.Timestamp("2026-09-30"))

    def test_explicit_target_month_is_normalized_to_month_end(self) -> None:
        self.assertEqual(resolve_target_month({}, "2026-08-01"), pd.Timestamp("2026-08-31"))


if __name__ == "__main__":
    unittest.main()
