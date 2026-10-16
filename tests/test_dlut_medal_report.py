import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('dlut_report', Path(__file__).resolve().parents[1]/'scripts/build_dlut_medal_report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class UpgradePlanTest(unittest.TestCase):
    def setUp(self):
        self.contest = {'problems': [{'id': p, 'index': p} for p in 'ABCD']}
        self.ratings = {p:{'rating':r} for p,r in zip('ABCD', (800,1200,2000,3000))}
        self.stats = {'medal_boundaries':{'gold':{'last_solved':3}}, 'medal_safety':{'gold':{'safe_solved':4}}}

    def test_retains_hard_solve_and_fills_easiest_missing(self):
        plan = report.plan_for({'accepted':['D']}, self.contest,self.stats,self.ratings,'gold','speed')
        self.assertEqual((plan['additional'],plan['new_rating'],plan['total_rating']), (2,1200,3000))
        self.assertEqual(plan['problems'],'A(800), B(1200)')

    def test_already_at_speed_count_requires_penalty_and_no_new_rating(self):
        plan = report.plan_for({'accepted':['A','B','C']},self.contest,self.stats,self.ratings,'gold','speed')
        self.assertEqual(plan['additional'],0)
        self.assertIsNone(plan['new_rating'])
        self.assertEqual(plan['total_rating'],2000)
        self.assertIn('降低罚时',plan['condition'])

    def test_safe_count_and_impossible_full_solve_threshold(self):
        row={'accepted':['A','B','C']}
        plan=report.plan_for(row,self.contest,self.stats,self.ratings,'gold','safe')
        self.assertEqual((plan['additional'],plan['new_rating']),(1,3000))
        self.stats['medal_safety']['gold']['safe_solved']=5
        plan=report.plan_for(row,self.contest,self.stats,self.ratings,'gold','safe')
        self.assertIsNone(plan['new_rating'])
        self.assertIsNone(plan['total_rating'])
        self.assertEqual(plan['problems'],'题数不可达')

    def test_overlapping_safe_stages_preserve_raw_guarantees(self):
        self.stats['medal_safety'].update(silver={'safe_solved':3},bronze={'safe_solved':3})
        plan=report.plan_for({'accepted':['A']},self.contest,self.stats,self.ratings,'bronze','safe')
        self.assertFalse(plan['stage_available'])
        self.assertEqual(plan['superseded_by'],'银牌')
        self.assertEqual((plan['count'],plan['new_rating']),(3,2000))
        self.stats['medal_safety']['gold']['safe_solved']=3
        self.assertEqual(report.superseding_safe_medal(self.stats,'bronze'),'gold')
        self.assertEqual(report.superseding_safe_medal(self.stats,'silver'),'gold')
        self.assertIsNone(report.superseding_safe_medal(self.stats,'gold'))

    def test_distinct_safe_stage_is_retained(self):
        self.stats['medal_safety'].update(silver={'safe_solved':3},bronze={'safe_solved':2})
        self.assertIsNone(report.superseding_safe_medal(self.stats,'bronze'))


if __name__=='__main__':
    unittest.main()
