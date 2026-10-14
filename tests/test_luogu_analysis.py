import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import luogu_analysis as la
import team_analysis as ta


class LuoguMetadataTests(unittest.TestCase):
    def test_calibration_counts_and_empirical_ranges(self):
        self.assertEqual(len(la.CALIBRATION['bands']), 7)
        for band in la.CALIBRATION['bands'].values():
            counts = {int(k): v for k, v in band['counts'].items()}
            self.assertEqual(sum(counts.values()), band['samples'])
            self.assertEqual(round(sum(k*v for k, v in counts.items())/band['samples']), band['mean'])
            self.assertLessEqual(band['range'][0], band['mean'])
            self.assertGreaterEqual(band['range'][1], band['mean'])
            self.assertEqual(band['evidenceWeight'], .5)
        self.assertEqual(la.CALIBRATION['bands']['5']['range'], [1900, 2500])

    def test_official_algorithm_ids_only_and_reviewed_categories(self):
        self.assertEqual(la.algorithm_tags([2, 301, 108, 2023, 301]), ['luogu:301', 'strings'])
        self.assertEqual(la.algorithm_tags(['3', None, {}, True]), [])
        tags = ta.category_sources({'luogu:301', 'luogu:139', 'luogu:49', 'chinese remainder theorem', 'segment tree'})
        self.assertIn('luogu:301', tags['strings'])
        self.assertIn('luogu:139', tags['counting'])
        self.assertIn('luogu:49', tags['graphs-trees'])
        self.assertIn('chinese remainder theorem', tags['number-theory'])
        self.assertIn('segment tree', tags['data-structures'])
        self.assertEqual(tags['other'], set())

    def test_unknown_difficulty_does_not_get_fabricated_rating(self):
        for value in (0, 8, '5', True, None):
            self.assertIsNone(la.problem_metadata({'difficulty': value, 'tags': [3]})['rating'])
        result = la.problem_metadata({'difficulty': 5}, {'difficulty': 4, 'tags': [3]})
        self.assertEqual((result['rating'], result['tags'], result['source']), (1835, ['dp'], 'luogu-color'))

    def test_public_cache_scan_resumes_and_keeps_success_on_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch.multiple(app, CACHE_DIR=Path(folder), ROOT=Path(folder)):
            def page(pid):
                return json.dumps({'data': {'problems': {'result': [{'pid': pid, 'difficulty': 5, 'tags': [3]}], 'count': 100, 'perPage': 50}}}).encode(), 'application/json'
            with patch.object(app, 'http_get', side_effect=[page('P1001'), OSError('network')]) as fetch:
                with self.assertRaises(OSError):
                    la.refresh_once(app)
                self.assertEqual(fetch.call_count, 2)
                self.assertNotIn('headers', fetch.call_args.kwargs)  # No private session credentials.
            saved = json.loads((Path(folder)/'luogu-analysis.json').read_text())
            self.assertEqual(saved['nextPage'], 2)
            self.assertIn('P1001', saved['problems'])
            with patch.object(app, 'http_get', return_value=page('P1002')) as fetch:
                self.assertEqual(la.refresh_once(app), 1)
                self.assertIn('page=2', fetch.call_args.args[0])
                self.assertEqual(la.refresh_once(app), 0)
                self.assertEqual(fetch.call_count, 1)
            saved = json.loads((Path(folder)/'luogu-analysis.json').read_text())
            with patch.object(app, 'utcnow', return_value=saved['completedAt']+31*86400), patch.object(app, 'http_get', return_value=(b'<html>login</html>', 'text/html')):
                with self.assertRaises(RuntimeError):
                    la.refresh_once(app)
            self.assertEqual(json.loads((Path(folder)/'luogu-analysis.json').read_text()), saved)

    def test_fresh_release_snapshot_needs_no_startup_network(self):
        with tempfile.TemporaryDirectory() as folder, patch.multiple(app, CACHE_DIR=Path(folder), ROOT=Path(folder)):
            catalog = Path(folder)/'catalog'
            catalog.mkdir()
            (catalog/'luogu_problems.json').write_text(json.dumps({'fetchedAt': app.utcnow(), 'problems': {}}))
            with patch.object(app, 'http_get', side_effect=AssertionError('fresh release should be reused')):
                self.assertEqual(la.refresh_once(app), 0)

    def test_color_uncertainty_widens_prediction_bounds(self):
        timing = {'scale': 45, 'low': 20, 'high': 100, 'source': 'heuristic', 'samples': 0}
        direct = ta.predict(2200, .8, 2200, 300, timing)
        approx = ta.predict(2200, .8, 2200, 300, timing, calibration_uncertainty=300)
        self.assertEqual(direct['probability'], approx['probability'])
        self.assertLess(approx['probabilityRange'][0], direct['probabilityRange'][0])
        self.assertGreater(approx['probabilityRange'][1], direct['probabilityRange'][1])
