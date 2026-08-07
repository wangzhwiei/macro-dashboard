from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.adapters import hybrid_adapter


ROOT = Path(__file__).resolve().parents[1]


class HybridRoutingTests(unittest.TestCase):
    def test_cjhx_url_cache_buster_preserves_existing_query(self):
        self.assertEqual(
            hybrid_adapter._cache_busted_url("https://example.test/data.csv", 123),
            "https://example.test/data.csv?cache_bust=123",
        )
        self.assertEqual(
            hybrid_adapter._cache_busted_url("https://example.test/data.csv?raw=1", 123),
            "https://example.test/data.csv?raw=1&cache_bust=123",
        )

    def test_routing_exactly_covers_required_semantic_codes(self):
        config = json.loads(
            (ROOT / "config" / "indicators.json").read_text(encoding="utf-8")
        )
        required = {
            component["code"]
            for indicator in config["indicators"]
            for component in indicator["series"]
        }
        with (ROOT / "config" / "auxiliary-indicators.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            required.update(row["code"] for row in csv.DictReader(handle))

        cjhx = hybrid_adapter._load_cjhx_map()
        ifind = hybrid_adapter._load_ifind_map()
        self.assertEqual(len(cjhx), 70)
        self.assertEqual(len(ifind), 41)
        self.assertFalse(set(cjhx) & set(ifind))
        self.assertEqual(required, set(cjhx) | set(ifind))

    def test_cjhx_scale_and_declared_bad_date_exclusion(self):
        original = hybrid_adapter._cjhx_index
        try:
            hybrid_adapter._cjhx_index = {
                "box_office_daily": [
                    {"date": "2026-08-01", "value": 20000.0}
                ],
                "new_home_30_cities_daily": [
                    {"date": "2023-10-26", "value": 27685.801099},
                    {"date": "2023-10-27", "value": 52.966446},
                ],
            }
            box = hybrid_adapter._fetch_cjhx(
                "CJHX:BOX_OFFICE_DAILY",
                date(2026, 8, 1),
                date(2026, 8, 1),
            )
            self.assertEqual(box, [{"date": "2026-08-01", "value": 2.0}])
            homes = hybrid_adapter._fetch_cjhx(
                "CJHX:NEW_HOME_30_CITIES",
                date(2023, 10, 26),
                date(2023, 10, 27),
            )
            self.assertEqual(homes, [{"date": "2023-10-27", "value": 52.966446}])
        finally:
            hybrid_adapter._cjhx_index = original

    def test_ifind_provider_id_drift_is_rejected(self):
        data = {
            "datas": [
                {
                    "data": {
                        "data": [["2026-07-31", 1.0]],
                        "attrs": {"candidate": {"index_id": "WRONG"}},
                    }
                }
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "模糊匹配漂移"):
            hybrid_adapter._parse_ifind_records(
                data,
                "EXPECTED",
                date(2026, 7, 1),
                date(2026, 8, 2),
            )

    def test_same_day_checked_cache_skips_ifind_call(self):
        original_dir = hybrid_adapter.CACHE_DIR
        original_call = hybrid_adapter._ifind_call
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                hybrid_adapter.CACHE_DIR = Path(temp_dir)
                hybrid_adapter._save_cache(
                    "IFIND:BILL_DISCOUNT_6M",
                    [{"date": "2026-08-06", "value": 1.23}],
                    "2026-08-07",
                )
                calls = []
                hybrid_adapter._ifind_call = lambda *args: calls.append(args)
                records = hybrid_adapter._fetch_ifind(
                    "IFIND:BILL_DISCOUNT_6M",
                    date(2026, 8, 1),
                    date(2026, 8, 7),
                )
                self.assertEqual(records, [{"date": "2026-08-06", "value": 1.23}])
                self.assertEqual(calls, [])
        finally:
            hybrid_adapter.CACHE_DIR = original_dir
            hybrid_adapter._ifind_call = original_call

    def test_no_new_data_is_checked_once_and_cached_for_the_day(self):
        original_dir = hybrid_adapter.CACHE_DIR
        original_call = hybrid_adapter._ifind_call
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                hybrid_adapter.CACHE_DIR = Path(temp_dir)
                hybrid_adapter._save_cache(
                    "IFIND:BILL_DISCOUNT_6M",
                    [{"date": "2026-08-06", "value": 1.23}],
                )
                calls = []

                def no_data(*args):
                    calls.append(args)
                    raise RuntimeError("未返回可用数据")

                hybrid_adapter._ifind_call = no_data
                records = hybrid_adapter._fetch_ifind(
                    "IFIND:BILL_DISCOUNT_6M",
                    date(2026, 8, 1),
                    date(2026, 8, 7),
                )
                self.assertEqual(records, [{"date": "2026-08-06", "value": 1.23}])
                self.assertEqual(len(calls), 1)
                _, checked = hybrid_adapter._load_cache(
                    "IFIND:BILL_DISCOUNT_6M"
                )
                self.assertEqual(checked, "2026-08-07")
        finally:
            hybrid_adapter.CACHE_DIR = original_dir
            hybrid_adapter._ifind_call = original_call

    def test_cache_only_mode_never_calls_ifind(self):
        original_dir = hybrid_adapter.CACHE_DIR
        original_env = os.environ.get("IFIND_CACHE_ONLY")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                hybrid_adapter.CACHE_DIR = Path(temp_dir)
                hybrid_adapter._save_cache(
                    "IFIND:BILL_DISCOUNT_6M",
                    [{"date": "2026-07-31", "value": 1.23}],
                )
                os.environ["IFIND_CACHE_ONLY"] = "1"
                records = hybrid_adapter._fetch_ifind(
                    "IFIND:BILL_DISCOUNT_6M",
                    date(2026, 7, 1),
                    date(2026, 8, 2),
                )
                self.assertEqual(
                    records, [{"date": "2026-07-31", "value": 1.23}]
                )
        finally:
            hybrid_adapter.CACHE_DIR = original_dir
            if original_env is None:
                os.environ.pop("IFIND_CACHE_ONLY", None)
            else:
                os.environ["IFIND_CACHE_ONLY"] = original_env


if __name__ == "__main__":
    unittest.main()
