import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from v9.data import MANIFEST_PATH, load_verified
from v9.ledger import _append, load_events
from v9.model import FAIR_SINGLE, binomial_tail, candidate_scores, rank, replay
from v9.official_source import _parse
from v9 import schedule_guard, watchdog
from v9.full_official_audit import compare
from v9.official_source import OfficialDraw


class OfficialRebuildTests(unittest.TestCase):
    def test_full_official_audit_detects_missing_or_changed_draw(self):
        draw = OfficialDraw("26/108", "2026-10-10", (12, 14, 20, 33, 34, 37), 31, "2026108N")
        self.assertTrue(compare([draw], [draw], "sha")["matched"])
        altered = OfficialDraw("26/108", "2026-10-10", (12, 14, 20, 33, 34, 38), 31, "2026108N")
        result = compare([draw], [altered], "sha")
        self.assertFalse(result["matched"])
        self.assertEqual(result["mismatched_dates"], ["2026-10-10"])

    def test_independent_repair_schedule_runs_only_when_stale(self):
        now = datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc)
        version = {"schema": "marksix_official_v9", "latest_period": "26/108",
                   "latest_date": "2026-10-10",
                   "updated_at": (now - timedelta(minutes=20)).isoformat()}
        health = {"healthy": True, "latest_period": "26/108", "latest_date": "2026-10-10"}
        self_test = {"operational_passed": True, "latest_period": "26/108",
                     "latest_date": "2026-10-10"}
        self.assertFalse(schedule_guard.should_repair("schedule", version, health, self_test, now))
        health["healthy"] = False
        self.assertTrue(schedule_guard.should_repair("schedule", version, health, self_test, now))
        health["healthy"] = True
        version["updated_at"] = (now - timedelta(minutes=90)).isoformat()
        self.assertTrue(schedule_guard.should_repair("schedule", version, health, self_test, now))
        version["updated_at"] = "invalid"
        self.assertTrue(schedule_guard.should_repair("schedule", version, health, self_test, now))
        self.assertTrue(schedule_guard.should_repair("workflow_dispatch", {}, {}, {}, now))

    def test_mobile_report_has_read_only_public_fallback(self):
        root = Path(__file__).resolve().parents[1]
        report = (root / "tests" / "fixtures" / "v9_reports" / "index.html").read_text(encoding="utf-8")
        self.assertIn("raw.githubusercontent.com/pingshen670822/hong-kong-marksix-ironlaw/main/reports/", report)
        self.assertIn("health.operational_passed!==true", report)
        self.assertIn('meta[name="marksix-report-version"]', report)
        self.assertIn("document.open();document.write(report);document.close();", report)
        self.assertIn("checkVersion();", report)

    def test_active_entrypoints_do_not_load_legacy_data(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("engine.py", "update.py", "watchdog.py", "verify.py",
                     "health_check.py", "daily_integrity_audit.py", "report.py"):
            source = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("official_marksix.csv", source, name)
            self.assertNotIn("prediction_history.json", source, name)
            self.assertIn("v10.", source, name)

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
