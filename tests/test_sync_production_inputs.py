import unittest
from scripts.sync_production_inputs import MAPPING, synchronize


class ProductionSyncTests(unittest.TestCase):
    def fixtures(self):
        old, fresh = {"series": {}}, {"series": {}, "end": "2026-10-13"}
        for key, source in MAPPING.items():
            meta = {"providerId": key, "unit": "%", "frequency": "W"}
            old["series"][key] = dict(meta, observations=[["2026-07-01", 1], ["2026-09-02", 2]])
            fresh["series"][source] = dict(meta, records=[["2026-07-01", 999], ["2026-09-01", 3], ["2026-10-09", 4]])
        return old, fresh

    def test_refresh_all_seven_and_preserve_older_history(self):
        old, fresh = self.fixtures()
        result = synchronize(old, fresh)
        for key in MAPPING:
            self.assertEqual(result["series"][key]["observations"],
                             [("2026-07-01", 1), ("2026-09-01", 3.0), ("2026-10-09", 4.0)])
        self.assertEqual(old["series"]["pta_rate"]["observations"][-1][0], "2026-09-02")

    def test_identity_frequency_and_unit_must_match(self):
        for field in ("providerId", "frequency", "unit"):
            old, fresh = self.fixtures()
            fresh["series"]["pmi_pta"][field] = "wrong"
            with self.assertRaises(ValueError):
                synchronize(old, fresh)

    def test_invalid_values_rejected(self):
        for records in ([], [["2026-10-09", float("nan")]],
                        [["2026-10-09", 1], ["2026-10-09", 2]]):
            old, fresh = self.fixtures()
            fresh["series"]["pmi_pta"]["records"] = records
            with self.assertRaises(ValueError):
                synchronize(old, fresh)
