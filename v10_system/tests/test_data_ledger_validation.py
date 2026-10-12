import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from v9 import data
from v9.data import _validate
from v9.ledger import _append, load_events, update_ledger
from v9.official_source import OfficialDraw


class DataLedgerValidationTests(unittest.TestCase):
    def setUp(self):
        self.basis = OfficialDraw("26/107", "2026-10-08", (18, 19, 24, 31, 40, 44), 5, "2026107N")
        self.actual = OfficialDraw("26/108", "2026-10-10", (12, 14, 20, 33, 34, 37), 31, "2026108N")

    def test_current_verified_data_remains_valid(self):
        self.assertGreater(len(data.load_verified()), 3000)

    def test_official_unpadded_source_ids_remain_valid(self):
        _validate([replace(self.basis, period="25/001", draw_date="2025-01-02", source_id="20251N")])

    def test_invalid_date_and_identity_fail_closed(self):
        for changes in (
            {"draw_date": "2026-99-99"},
            {"draw_date": "20261008"},
            {"draw_date": "2099-10-08", "period": "99/107", "source_id": "2099107N"},
            {"period": "26/108"},
            {"source_id": "2025107N"},
            {"source_id": "nonsense"},
            {"period": "26/000", "source_id": "2026000N"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _validate([replace(self.basis, **changes)])

    def test_existing_csv_requires_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "verified.csv"
            csv_path.write_text("period,draw_date\n", encoding="utf-8")
            with patch.object(data, "DATA_PATH", csv_path), patch.object(data, "MANIFEST_PATH", Path(directory) / "absent.json"):
                with self.assertRaisesRegex(ValueError, "no provenance manifest"):
                    data.load_verified()

    def _settled_at(self, created_at):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            ranking = [7] + [n for n in range(1, 50) if n != 7]
            _append({"kind": "forecast", "created_at_utc": created_at,
                     "based_on_period": self.basis.period, "based_on_date": self.basis.draw_date,
                     "single": 7, "top9": ranking[:9], "ranking": ranking,
                     "model": "bayes_60", "official_data_sha256": "fixture"}, path)
            original_line = path.read_bytes().splitlines()[0]
            result = update_ledger([self.basis, self.actual], ranking, "bayes_60", "fixture", path=path)
            self.assertEqual(path.read_bytes().splitlines()[0], original_line)
            load_events(path)
            return result["settled"]

    def test_same_hkt_day_is_consistently_excluded(self):
        # Both are before the evening draw but neither has verified cutoff evidence.
        self.assertEqual(self._settled_at("2026-10-09T17:00:00+00:00"), 0)
        self.assertEqual(self._settled_at("2026-10-10T01:00:00+00:00"), 0)
        self.assertEqual(self._settled_at("2026-10-10T01:00:00+08:00"), 0)

    def test_prior_hkt_day_remains_eligible(self):
        self.assertEqual(self._settled_at("2026-10-09T15:59:59+00:00"), 1)

    def test_naive_forecast_timestamp_rejected(self):
        with self.assertRaisesRegex(ValueError, "include a timezone"):
            self._settled_at("2026-10-09T01:00:00")


if __name__ == "__main__":
    unittest.main()
