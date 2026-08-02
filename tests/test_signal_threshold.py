from __future__ import annotations

import unittest

from scripts.update_dashboard import signal_counts, signal_from_score


class DisplayThresholdTests(unittest.TestCase):
    def test_signal_uses_the_integer_strength_shown_on_page(self) -> None:
        self.assertEqual(signal_from_score(14.7, 15), "bullish")
        self.assertEqual(signal_from_score(-14.7, 15), "bearish")
        self.assertEqual(signal_from_score(14.4, 15), "neutral")

    def test_breadth_counts_use_the_same_display_threshold(self) -> None:
        self.assertEqual(
            signal_counts([14.7, -14.7, 14.4], 15),
            {"bullish": 1, "bearish": 1, "neutral": 1},
        )


if __name__ == "__main__":
    unittest.main()
