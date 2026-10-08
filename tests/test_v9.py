import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from v9.data import MANIFEST_PATH, load_verified
from v9.ledger import _append, load_events
from v9.model import FAIR_SINGLE, binomial_tail, candidate_scores, rank, replay
from v9.official_source import _parse
from v9 import watchdog


class OfficialRebuildTests(unittest.TestCase):
    def test_official_history_not_legacy_csv(self):
        draws = load_verified()
        self.assertGreaterEqual(len(draws), 3000)
        self.assertGreaterEqual(draws[0].draw_date, "2003-01-01")
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(draws[-1].period, manifest["latest_period"])

    def test_official_parser_rejects_invalid_draw(self):
        item = {"id": "2026107N", "year": "2026", "no": 107,
                "drawDate": "2026-10-08+08:00", "status": "Result",
                "drawResult": {"drawnNo": [18, 19, 24, 31, 40, 44], "xDrawnNo": 5}}
        self.assertEqual(_parse(item).period, "26/107")
        item["drawResult"]["xDrawnNo"] = 31
        with self.assertRaises(ValueError):
            _parse(item)

    def test_future_outcomes_cannot_change_current_scores(self):
        history = np.zeros((300, 49))
        history[:, :6] = 1
        original = candidate_scores(history)
        future = np.zeros((1, 49))
        future[0, -6:] = 1
        unchanged = candidate_scores(history)
        for name in original:
            self.assertTrue(np.array_equal(original[name], unchanged[name]))
        self.assertNotEqual(rank(original["bayes_60"]), rank(candidate_scores(np.vstack([history, future]))["bayes_60"]))

    def test_chance_baseline_and_full_replay(self):
        self.assertAlmostEqual(FAIR_SINGLE, 6 / 49)
        self.assertGreater(binomial_tail(120, 23), 0)
        result = replay(load_verified())
        self.assertEqual(sum(row["single_hit"] for row in result["selected_replay_rows"][-120:]),
                         result["models"][result["selected_model"]]["evaluation_hits"])
        self.assertEqual(len(result["rank"]), 49)

    def test_ledger_detects_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            _append({"kind": "forecast", "single": 7}, path)
            self.assertEqual(len(load_events(path)), 1)
            altered = path.read_text(encoding="utf-8").replace('"single": 7', '"single": 8')
            path.write_text(altered, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_events(path)

    def test_failed_refresh_marks_public_health_unhealthy(self):
        with tempfile.TemporaryDirectory() as directory:
            original = watchdog.ROOT
            try:
                watchdog.ROOT = Path(directory)
                watchdog._status({"self_repair": "failed", "checked_at": "2026-10-09T00:00:00+08:00"})
                for name in ("reports", "site", "docs"):
                    health = json.loads((Path(directory) / name / "health_status.json").read_text(encoding="utf-8"))
                    self.assertFalse(health["healthy"])
            finally:
                watchdog.ROOT = original


if __name__ == "__main__":
    unittest.main()
