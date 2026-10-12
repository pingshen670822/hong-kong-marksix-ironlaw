"""Regression coverage for report metadata used by the live fallback."""
import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from v9 import report
from v9.data import load_verified, MANIFEST_PATH, ROOT
from v9.ledger import load_events
from v9.model import replay

class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('name'):
            self.values[values['name']] = values.get('content')

class ReportConsistencyTests(unittest.TestCase):
    def test_generated_report_exposes_exact_fallback_identity(self):
        draws = load_verified()
        manifest = json.loads(MANIFEST_PATH.read_text())
        events = load_events()
        forecasts = [e for e in events if e['kind'] == 'forecast']
        settled = [e for e in events if e['kind'] == 'settlement']
        ledger = {'forecasts':len(forecasts),'settled':len(settled),
                  'hits':sum(e['single_hit'] for e in settled),
                  'latest_forecast':forecasts[-1],'chain_tip':events[-1]['hash']}
        upcoming = json.loads((ROOT/'tests/fixtures/v9_reports/latest_analysis.json').read_text())['next_draw_evidence']
        with tempfile.TemporaryDirectory() as directory:
            outputs = tuple(Path(directory)/name for name in ('reports','site','docs'))
            with patch.object(report,'OUTPUTS',outputs):
                analysis = report.build_report(draws,manifest,replay(draws),ledger,upcoming)
            for output in outputs:
                version = json.loads((output/'version.json').read_text())
                for filename in ('index.html','latest_battle_report.html'):
                    text = (output/filename).read_text()
                    parsed = Metadata(); parsed.feed(text)
                    self.assertEqual(parsed.values['marksix-report-version'],version['hash'])
                    self.assertEqual(parsed.values['marksix-report-period'],version['latest_period'])
                    self.assertEqual(analysis['generated_at'],version['updated_at'])
                    self.assertIn('version.updated_at!==analysis.generated_at',text)
                    self.assertNotIn('report.includes(version.hash)',text)

    def test_changed_calculation_cannot_replace_existing_seal(self):
        draws = load_verified()
        manifest = json.loads(MANIFEST_PATH.read_text())
        forecasts = [e for e in load_events() if e['kind'] == 'forecast']
        model = replay(draws)
        model['rank'] = model['rank'][1:] + model['rank'][:1]
        model['single'] = model['rank'][0]
        model['top9'] = model['rank'][:9]
        ledger = {'latest_forecast': forecasts[-1]}
        with tempfile.TemporaryDirectory() as directory:
            outputs = (Path(directory)/'reports',)
            with patch.object(report, 'OUTPUTS', outputs):
                with self.assertRaisesRegex(ValueError, 'differs from sealed forecast'):
                    report.build_report(draws,manifest,model,ledger)
            self.assertFalse(outputs[0].exists())

if __name__ == '__main__': unittest.main()
