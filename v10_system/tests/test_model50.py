"""Independent checks for the 50-rule V10.1 research experiment."""
import json
import unittest
from collections import Counter
from datetime import datetime, timezone

import numpy as np

from v10 import core
from v10.model50 import CATALOG, MODEL_NAMES, candidate_scores, replay
from v9.model import as_matrix, binomial_tail, rank


class FiftyRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = core.ROOT / 'data'
        raw = (root / 'hkjc_verified_v9.csv').read_bytes().replace(b'\r\n', b'\n')
        manifest = json.loads((root / 'hkjc_verified_v9_manifest.json').read_text(encoding='utf-8'))
        cls.draws, _ = core.validate(raw, manifest, datetime.now(timezone.utc))
        cls.matrix = as_matrix(cls.draws)
        cls.replayed = replay(cls.draws)

    def test_registered_families_and_actual_score_vectors(self):
        self.assertEqual(len(MODEL_NAMES), 50)
        self.assertEqual(len(set(MODEL_NAMES)), 50)
        self.assertEqual(Counter(row['family'] for row in CATALOG),
                         {'baseline': 5, 'frequency_window': 9, 'exponential_recency': 9,
                          'cross_draw_transition': 9, 'same_draw_cooccurrence': 9,
                          'fixed_weight_blend': 9})
        scores = candidate_scores(self.matrix)
        self.assertEqual(tuple(scores), MODEL_NAMES)
        self.assertEqual(len({values.tobytes() for values in scores.values()}), 50)
        for name, values in scores.items():
            with self.subTest(name=name):
                self.assertEqual(values.shape, (49,))
                self.assertTrue(np.isfinite(values).all())
                self.assertTrue((values >= 0).all())
                self.assertAlmostEqual(float(values.sum()), 1)
                self.assertEqual(sorted(rank(values)), list(range(1, 50)))

    def test_all_fifty_rules_are_causal(self):
        original = candidate_scores(self.matrix[:-1])
        changed = self.matrix.copy()
        changed[-1] = 0
        changed[-1, -6:] = 1
        future_independent = candidate_scores(changed[:-1])
        for name in MODEL_NAMES:
            np.testing.assert_array_equal(original[name], future_independent[name])

    def test_separated_replay_and_fifty_way_correction(self):
        result = self.replayed
        self.assertEqual(result['candidate_count'], 50)
        self.assertEqual(set(result['models']), set(MODEL_NAMES))
        self.assertEqual(len(result['selected_replay_rows']), 520)
        selected = result['selected_model']
        self.assertEqual(selected,
                         max(MODEL_NAMES, key=lambda name:
                             (result['models'][name]['development_hits'], -MODEL_NAMES.index(name))))
        for model in result['models'].values():
            self.assertEqual((model['development_rounds'], model['evaluation_rounds']), (400, 120))
            self.assertEqual(len(model['rank_sha256']), 64)
            self.assertIn(model['current_first'], range(1, 50))
        hits = result['models'][selected]['evaluation_hits']
        self.assertAlmostEqual(result['evaluation_adjusted_p'],
                               round(min(1, binomial_tail(120, hits) * 50), 8))
        self.assertEqual(result['rank'][0], result['single'])

    def test_public_result_is_recomputed_and_tampering_rejected(self):
        result = self.replayed
        selected = result['models'][result['selected_model']]
        analysis = {'version': '10.1.0',
                    'research': {'candidate_count': 50, 'catalog': result['catalog'],
                                 'model_results': result['models'], 'model': result['selected_model'],
                                 'rank': result['rank'], 'top9': result['top9'],
                                 'single': result['single'], 'adjusted_p': result['evaluation_adjusted_p'],
                                 'selection_rule': result['rule']},
                    'evidence': {key: selected[key] for key in
                                 ('development_rounds','development_hits','evaluation_rounds','evaluation_hits')}}
        self.assertTrue(core.verify_model_computation(analysis, self.draws))
        analysis['research']['model_results'] = dict(analysis['research']['model_results'])
        analysis['research']['model_results'][result['selected_model']] = dict(selected)
        analysis['research']['model_results'][result['selected_model']]['evaluation_hits'] += 1
        with self.assertRaisesRegex(ValueError, 'independent rerun'):
            core.verify_model_computation(analysis, self.draws)


if __name__ == '__main__':
    unittest.main()
