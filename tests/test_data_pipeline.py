from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.adapters import common
from scripts.adapters.http_adapter import _extract_records


class HttpPayloadTests(unittest.TestCase):
    def test_extracts_supported_payload_shapes(self) -> None:
        records = [{"date": "2026-07-30", "value": 1.2}]
        self.assertEqual(_extract_records(records), records)
        self.assertEqual(_extract_records({"data": records}), records)
        self.assertEqual(
            _extract_records(
                {"dates": ["2026-07-30"], "values": [1.2]},
            ),
            records,
        )

    def test_extracts_nested_data_path(self) -> None:
        payload = {
            "code": 0,
            "result": {"rows": [{"trade_date": "2026-07-30", "close": 1.2}]},
        }
        self.assertEqual(
            _extract_records(payload, "result.rows"),
            [{"trade_date": "2026-07-30", "close": 1.2}],
        )

    def test_rejects_unknown_payload(self) -> None:
        with self.assertRaises(ValueError):
            _extract_records({"message": "ok"})


class ProviderCodeMappingTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("MACRO_API_CODE_MAP", None)
        common._code_map.cache_clear()

    def test_falls_back_to_semantic_code(self) -> None:
        self.assertEqual(
            common.resolve_series_code({"code": "CJHX:TEST"}),
            "CJHX:TEST",
        )

    def test_reads_string_and_object_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.json"
            path.write_text(
                json.dumps(
                    {
                        "CJHX:A": "vendor-a",
                        "CJHX:B": {"provider_code": "vendor-b"},
                    }
                ),
                encoding="utf-8",
            )
            os.environ["MACRO_API_CODE_MAP"] = str(path)
            common._code_map.cache_clear()
            self.assertEqual(
                common.resolve_series_code({"code": "CJHX:A"}),
                "vendor-a",
            )
            self.assertEqual(
                common.resolve_series_code({"code": "CJHX:B"}),
                "vendor-b",
            )


if __name__ == "__main__":
    unittest.main()
