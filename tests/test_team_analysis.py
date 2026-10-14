import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import team_analysis as ta
from cpc_integration import Integration


class TeamAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patch = patch.multiple(app, DATA_DIR=root, DB_PATH=root/'test.sqlite', CACHE_DIR=root/'cache')
        self.patch.start()
        app.init_db()
        self.service = Integration(app)
        self.now = app.utcnow()
        self.date = (dt.datetime.fromtimestamp(self.now, app.DISPLAY_TZ)-dt.timedelta(days=90)).date()
        self.cutoff = int(dt.datetime.combine(self.date, dt.time.min, tzinfo=app.DISPLAY_TZ).timestamp())
        self.cid = 'icpc-test'
        self.keys = ['user:1', 'user:2', 'user:3']
        self.principal = {'type': 'user', 'id': '1'}
        contest = {'id': self.cid, 'name': '测试区域赛', 'year': self.date.year, 'problems': [
            {'id': self.cid+':A', 'name': 'A', 'index': 'A', 'tags': ['dp']},
            {'id': self.cid+':B', 'name': 'B', 'index': 'B'}]}
        self.service.contests = {self.cid: contest}
        self.service.aliases = {'codeforces:100001A': self.cid+':A', 'qoj:1': self.cid+':A'}
        self.release = {'method': 'fixture', 'source_revision': 'f'*40,
            'contests': {self.cid: {'duration_seconds': 18000}},
            'problems': {self.cid+':A': {'rating': 1800, 'range': [1600, 2000]}, self.cid+':B': {'rating': 2100}}}
        self.rating_patch = patch.object(ta, 'load_release', return_value=self.release)
        self.rating_patch.start()
        self.remote = {'roster': {'members': [], 'redirects': {}, 'participations': [
            {'id': 'part', 'members': ['p1','p2','p3'], 'team': '原队伍', 'date': self.date.isoformat()}]}, 'claims': []}
        with app.connect_db() as conn:
            for i in range(1, 4):
                conn.execute("INSERT INTO users(id,username,email,display_name,password_hash,created_at) VALUES(?,?,?,?,?,?)",
                    (i, f'u{i}', f'u{i}@local.test', f'成员{i}', 'test', self.now))
                conn.execute("INSERT INTO handles(owner_type,owner_id,platform,handle,created_at) VALUES('user',?,'codeforces',?,?)",
                    (str(i), f'cf{i}', self.now))
        with self.service.db() as conn:
            for i in range(1,4):
                subject = self.service.subject(conn, str(i))
                self.remote['claims'].append({'id': f'claim{i}', 'subject': subject, 'person': f'p{i}', 'status': 'approved', 'updated': self.now})
            conn.execute('INSERT INTO cpc_remote VALUES(1,?,?)', (json.dumps(self.remote), self.now))
            conn.execute('INSERT INTO cpc_onsite VALUES(?,?,?,?,1)', ('evidence', 'part', self.cid, json.dumps({
                'accepted': [self.cid+':A'], 'source_team': {'official': True},
                'accepted_runs': [{'problem':'A','elapsed_seconds':2400}, {'problem':'A','elapsed_seconds':1800}]})))
        for i in range(1,4):
            for j in range(12):
                self.add(i, f'{i}-{j}', f'{100+j}A', self.cutoff-20*86400+j*100, rating=2000,
                    raw_extra={'relativeTimeSeconds': 1800+j*60, 'author': {'participantType':'CONTESTANT','members':[{'handle':f'cf{i}'}]}})

    def tearDown(self):
        self.rating_patch.stop()
        self.patch.stop()
        self.temp.cleanup()

    def add(self, owner, sid, pid, timestamp, verdict='AC', rating=1800, tags=None, platform='codeforces', handle=None, raw_extra=None):
        raw = {'problem': {'rating': rating, 'tags': ['dp'] if tags is None else tags}, **(raw_extra or {})}
        with app.connect_db() as conn:
            conn.execute("""INSERT INTO submissions(owner_type,owner_id,platform,handle,remote_id,problem_id,
                problem_name,verdict,submitted_at,raw_json,created_at) VALUES('user',?,?,?,?,?,?,?,?,?,?)""",
                (str(owner), platform, handle or f'cf{owner}', sid, pid, pid, verdict, timestamp, json.dumps(raw), self.now))

    def analysis(self, **kwargs):
        return ta.build_analysis(app, self.service, self.principal, self.keys, **kwargs)

    def luogu_binding(self, owner=1):
        with app.connect_db() as conn:
            conn.execute("INSERT INTO handles(owner_type,owner_id,platform,handle,created_at) VALUES('user',?,'luogu',?,?)",
                         (str(owner), f'lg{owner}', self.now))

    def luogu_record(self, owner, sid, pid, timestamp, difficulty=5, tags=None, verdict='AC'):
        self.add(owner, sid, pid, timestamp, verdict=verdict, platform='luogu', handle=f'lg{owner}',
                 raw_extra={'problem': {'pid': pid, 'difficulty': difficulty, 'tags': [3] if tags is None else tags}})

    def test_all_sources_uses_real_luogu_training_without_changing_cf_only(self):
        before = self.analysis(platform='codeforces')
        self.luogu_binding()
        for j in range(20):
            self.luogu_record(1, f'lg-{j}', f'P9900{j}', self.now-10000+j)
        self.luogu_record(1, 'lg-wa', 'P99000', self.now-11000, verdict='WA')
        with patch.object(app, 'http_get', side_effect=AssertionError('analysis must read local snapshots')):
            cf = self.analysis(platform='codeforces')
            all_sources = self.analysis(platform='all')
        self.assertEqual(before['members'], cf['members'])
        self.assertEqual(before['forecast'], cf['forecast'])
        m = all_sources['members'][0]
        self.assertEqual(m['coverage']['approximate'], 20)
        self.assertEqual(m['coverage']['byPlatform']['luogu']['usable'], 20)
        self.assertEqual(m['overall']['luoguMomentum']['recent20Mean'], 2208)
        self.assertAlmostEqual(m['overall']['luoguMomentum']['confidence'], .5, delta=.002)
        self.assertEqual(m['overall']['momentum'], cf['members'][0]['overall']['momentum'])
        self.assertGreater(m['overall']['rating'], cf['members'][0]['overall']['rating'])
        dp = next(t for t in all_sources['tags'] if t['key']=='dp')['members'][0]
        self.assertEqual(dp['approximateSolved'], 20)
        self.assertGreater(dp['calibrationUncertainty'], 0)
        self.assertEqual(dp['wa'], 1)
        self.assertAlmostEqual(dp['effectiveSolved']-next(t for t in cf['tags'] if t['key']=='dp')['members'][0]['effectiveSolved'], 10, delta=.01)

    def test_luogu_cf_mirror_reuses_original_metadata_and_is_deduplicated(self):
        self.luogu_binding()
        self.luogu_record(1, 'mirror-1', 'CF100A', self.now-1000, difficulty=7, tags=[8])
        data = self.analysis(platform='all')['members'][0]
        self.assertEqual(data['coverage']['problems'], 12)
        self.assertEqual(data['coverage']['approximate'], 0)
        self.assertEqual(data['overall']['solved'], 12)
        self.assertEqual(data['overall']['momentum']['recent20Mean'], 2000)

    def test_luogu_unknown_metadata_and_profile_lists_do_not_fabricate_evidence(self):
        self.luogu_binding()
        self.luogu_record(1, 'unknown', 'P99111', self.now-200, difficulty=0)
        self.luogu_record(1, 'untagged', 'P99112', self.now-100, tags=[])
        with app.connect_db() as conn:
            conn.execute("UPDATE handles SET stats_json=? WHERE platform='luogu'", (json.dumps({'solvedProblems': [{'problemId':'P99113'}]}),))
        m = self.analysis(platform='all')['members'][0]
        self.assertEqual(m['coverage']['problems'], 14)
        self.assertEqual(m['coverage']['unrated'], 1)
        self.assertEqual(m['coverage']['untagged'], 1)
        self.assertEqual(m['overall']['luoguMomentum']['recent20Count'], 1)

    def test_luogu_future_ac_and_repeated_ac_cannot_leak_into_past(self):
        self.luogu_binding()
        self.luogu_record(1, 'before', 'P99200', self.cutoff-100, verdict='WA')
        self.luogu_record(1, 'after', 'P99200', self.cutoff+100)
        self.luogu_record(1, 'repeat', 'P99200', self.now-100)
        with app.connect_db() as conn:
            rows = conn.execute("SELECT * FROM submissions WHERE owner_id='1' ORDER BY submitted_at,id").fetchall()
            handles = ta.personal_handles(conn)
        meta = ta.metadata(self.service, self.release, rows, app)
        past, _ = ta.problem_records(app, self.service, rows, handles, meta, 'all', self.cutoff)
        current, _ = ta.problem_records(app, self.service, rows, handles, meta, 'all', self.now+1)
        p = next(p for p in past if p['id']=='luogu:P99200')
        self.assertFalse(p['solved'])
        self.assertEqual(p['wa'], 1)
        self.assertEqual(ta.training_momentum(past, self.cutoff, 'luogu-color')['recent20Count'], 0)
        self.assertEqual(ta.training_momentum(current, self.now, 'luogu-color')['recent20Count'], 1)
        self.assertEqual(next(p for p in current if p['id']=='luogu:P99200')['firstAc'], self.cutoff+100)

    def official(self, owner, cid, rating, updated, handle=None, participated=None):
        raw = {'ratingChange': {'contestId': cid, 'newRating': rating, 'ratingUpdateTimeSeconds': updated}}
        with app.connect_db() as conn:
            conn.execute("""INSERT INTO contests(owner_type,owner_id,platform,handle,remote_id,contest_name,
                category,participated_at,url,raw_json,created_at) VALUES('user',?,'codeforces',?,?,?,'codeforces',?,'',?,?)""",
                (str(owner), handle or f'cf{owner}', str(cid), f'contest {cid}', participated or updated-7200, json.dumps(raw), self.now))

    def test_peak_retention_and_recent_hard_solves_survive_current_rating_drop(self):
        self.official(1, 1, 2200, self.now-3*365*86400)
        self.official(1, 2, 1750, self.now-30*86400)
        self.official(1, 3, 1700, self.now-20*86400)
        for j in range(20):
            self.add(1, f'hard-{j}', f'{600+j}A', self.now-86400+j, rating=2300)
        m = self.analysis()['members'][0]['overall']
        self.assertEqual((m['officialRating'], m['peakRating']), (1700, 2200))
        self.assertEqual(m['momentum']['recent20Mean'], 2300)
        self.assertGreater(m['rating'], 2100)
        self.assertEqual(m['ratingSource'], 'cf-training-hybrid')
        self.assertGreater(m['trainingUplift'], 100)

    def test_easy_warmups_do_not_erase_peak_supported_baseline(self):
        for cid, rating in enumerate((2200, 1800, 1700)):
            self.official(1, cid, rating, self.now-(30-cid)*86400)
        for j in range(25):
            self.add(1, f'easy-{j}', f'{600+j}A', self.now-1000+j, rating=800)
        data = self.analysis()
        m = data['members'][0]['overall']
        self.assertEqual(m['momentum']['recent20Mean'], 800)
        self.assertGreaterEqual(m['rating'], 1990)
        self.assertEqual(m['trainingUplift'], 0)
        self.assertEqual(data['peakForecast']['ratingBasis'], 'peak')

    def test_repeat_ac_cannot_refresh_moving_average_or_unique_sample_confidence(self):
        before = self.analysis()['members'][0]['overall']['momentum']
        for j in range(25):
            self.add(1, f'repeat-{j}', '100A', self.now-100+j, rating=2000)
        after = self.analysis()['members'][0]['overall']['momentum']
        self.assertEqual(before, after)

    def test_moving_average_uses_months_weights_and_excludes_regional_rating_scale(self):
        def problem(i, rating, age):
            return {'id': str(i), 'solved': True, 'rating': rating, 'source': 'codeforces',
                'firstAc': self.now-age*86400, 'errors': 0}
        old = [problem(i, 1800, 150-i) for i in range(20)]
        new = [problem(i+20, 2400, 20-i) for i in range(20)]
        m = ta.training_momentum(old+new, self.now)
        self.assertEqual(m['recent20Mean'], 2400)
        self.assertGreater(m['monthsWeightedMean'], 2000)
        self.assertLess(m['monthsWeightedMean'], 2400)
        self.assertLess(m['trend'], 2400)
        self.assertGreater(m['trend'], m['monthsWeightedMean'])
        self.assertEqual(m, ta.training_momentum(old+new+[{**problem(100, 4000, 0), 'source': 'cf-bot'}], self.now))
        self.assertEqual(m, ta.training_momentum(old+new+[problem(101, 4000, -1)], self.now))

    def test_official_rating_update_time_prevents_historical_leakage(self):
        for i in range(1,4):
            for cid, rating in enumerate((2000, 2100, 2200)):
                self.official(i, cid, rating, self.cutoff-(40-cid)*86400)
        before = self.analysis()['backtest']
        for i in range(1,4):
            self.official(i, 10, 3500, self.cutoff+86400, participated=self.cutoff-86400)
            self.official(i, 11, 3600, self.cutoff, participated=self.cutoff-86400)
        self.assertEqual(before, self.analysis()['backtest'])

    def test_multiple_accounts_take_latest_per_account_and_keep_peak_separate(self):
        self.bind(1, 'codeforces', 'other')
        self.official(1, 1, 2500, self.now-30*86400)
        self.official(1, 2, 1700, self.now-20*86400)
        self.official(1, 3, 1900, self.now-10*86400, handle='other')
        m = self.analysis()['members'][0]['overall']
        self.assertEqual(m['officialRating'], 1900)
        self.assertEqual(m['peakRating'], 2500)
        self.assertGreater(m['rating'], 2200)

    def test_later_rating_change_does_not_rewrite_historical_timing_scale(self):
        for i in range(1,4):
            self.official(i, 1, 1900, self.cutoff-30*86400)
        before = self.analysis()['forecast']['timing']
        for i in range(1,4):
            self.official(i, 2, 2500, self.cutoff+30*86400)
        self.assertEqual(before, self.analysis()['forecast']['timing'])

    def test_training_only_fallback_is_explicit_and_unknown_tags_stay_unknown(self):
        data = self.analysis()
        m = data['members'][0]['overall']
        self.assertEqual(m['ratingSource'], 'recent-training')
        self.assertEqual(m['momentum']['recent20Count'], 12)
        self.assertNotIn('officialRating', m)
        self.assertIsNone(data['peakForecast'])
        self.assertIsNone(next(t for t in data['tags'] if t['key']=='geometry')['rating'])

    def test_retrospective_external_panel_never_changes_forecast_or_backtest(self):
        before = self.analysis()
        self.remote['roster']['members'] = [{'id':'p1','name':'成员一','school':'大学'}]
        body = {'panels':{'all':{'contests':10}}, 'history':[], 'usedForPrediction':False}
        with self.service.db() as conn:
            conn.execute('UPDATE cpc_remote SET body=?',(json.dumps(self.remote),))
            conn.execute('INSERT INTO cpc_xcpc_reference VALUES(?,?,?,?,?,?)',
                ('p1','成员一@大学',json.dumps(body),self.now,self.now,''))
        after = self.analysis()
        self.assertEqual(after['onsiteReference']['status'],'ready')
        self.assertEqual(before['forecast'],after['forecast'])
        self.assertEqual(before['backtest'],after['backtest'])

    def test_team_radar_forecast_and_historical_time(self):
        data = self.analysis()
        self.assertEqual(len(data['families']), 12)
        self.assertEqual(next(t for t in data['families'] if t['key']=='counting')['label'], '计数')
        self.assertEqual(data['families'], data['categories'])
        dp = next(t for t in data['tags'] if t['key'] == 'dp')
        self.assertEqual(dp['label'], '动态规划')
        self.assertEqual(dp['coverageLabel'], '双人覆盖')
        self.assertEqual(dp['status'], 'covered')
        self.assertGreater(dp['rating'], 1900)
        self.assertEqual(data['backtest']['metrics']['count'], 2)
        self.assertEqual(data['backtest']['timeMetrics']['count'], 1)
        self.assertEqual(data['backtest']['contests'][0]['problems'][0]['actualMinutes'], 30)
        self.assertEqual(sum(r['count'] for r in data['backtest']['probabilityCalibration']), 2)
        self.assertEqual(sum(r['count'] for r in data['backtest']['ratingCohorts']), 2)
        self.assertEqual(sum(r['timedSolves'] for r in data['backtest']['ratingCohorts']), 1)
        self.assertIsNotNone(data['backtest']['timeMetrics']['budgetedMaeMinutes'])
        self.assertEqual(data['forecast']['timing']['source'], 'personal-contest-history')
        self.assertFalse(data['forecast']['problems'][1]['tagged'])
        self.assertTrue(all(r['signal']=='样本不足' for r in data['backtest']['ratingReview']))

    def test_future_training_and_target_practice_never_change_backtest(self):
        before = self.analysis()['backtest']
        for i in range(1,4):
            for j in range(15):
                self.add(i, f'future-{i}-{j}', f'{500+j}A', self.cutoff+86400+j*100, rating=3500)
                self.add(i, f'target-{i}-{j}', '100001A', self.cutoff-86400+j*100, rating=3500)
        self.assertEqual(before, self.analysis()['backtest'])

    def test_forecast_excludes_target_practice_at_all_dates(self):
        before = self.analysis()['forecast']
        for i in range(1,4):
            for j in range(20):
                self.add(i, f'target-{i}-{j}', '100001A', self.now-1000+j, rating=3500)
        self.assertEqual(before, self.analysis()['forecast'])

    def test_duplicates_and_post_ac_wa_do_not_inflate_evidence(self):
        before = self.analysis()['members'][0]['overall']
        for j in range(5):
            self.add(1, f'duplicate-{j}', '100A', self.cutoff-20*86400+50+j)
        self.add(1, 'after-wa', '100A', self.cutoff-20*86400+80, verdict='WA')
        after = self.analysis()['members'][0]['overall']
        self.assertEqual(before['solved'], after['solved'])
        self.assertEqual(before['errors'], after['errors'])
        self.assertEqual(before['confidence'], after['confidence'])

    def test_team_submissions_and_compilation_errors_are_excluded(self):
        before = self.analysis()['members'][0]['overall']
        self.add(1,'team','900A',self.now-60,raw_extra={'author':{'members':[{'handle':'a'},{'handle':'b'}]}})
        self.add(1,'ce','901A',self.now-60,verdict='COMPILATION_ERROR')
        after = self.analysis()['members'][0]['overall']
        self.assertEqual(before, after)

    def test_cross_platform_aliases_deduplicate_solved_problem(self):
        self.add(1,'gym','100001A',self.now-200)
        self.add(1,'qoj','1',self.now-100,platform='qoj',handle='qoj1')
        with app.connect_db() as conn:
            conn.execute("INSERT INTO handles(owner_type,owner_id,platform,handle,created_at) VALUES('user','1','qoj','qoj1',?)",(self.now,))
        self.assertEqual(self.analysis(platform='all')['members'][0]['overall']['solved'], 13)

    def test_historical_team_requires_all_three_linked_people(self):
        self.remote['roster']['participations'][0]['members'][2] = 'unlinked'
        with self.service.db() as conn:
            conn.execute('UPDATE cpc_remote SET body=?',(json.dumps(self.remote),))
        b = self.analysis()['backtest']
        self.assertEqual(b['metrics']['count'], 0)
        self.assertIn('三位队员', b['skipped'][0]['reason'])

    def test_revoked_or_expired_identity_does_not_attribute_results(self):
        self.remote['claims'].append({**self.remote['claims'][0], 'id':'new', 'status':'revoked','updated':self.now+1})
        with self.service.db() as conn:
            conn.execute('UPDATE cpc_remote SET body=?',(json.dumps(self.remote),))
        self.assertEqual(self.analysis()['backtest']['metrics']['count'], 0)
        with self.service.db() as conn:
            conn.execute('UPDATE cpc_remote SET checked=?',(self.now-86401,))
        self.assertIn('过期',self.analysis()['backtest']['message'])

    def test_anonymous_or_unselected_identity_does_not_reveal_history(self):
        d=ta.build_analysis(app,self.service,None,self.keys)
        self.assertEqual(d['backtest']['contests'], [])
        self.assertEqual(d['backtest']['skipped'], [])

    def test_unknown_tag_is_not_a_weakness(self):
        data=self.analysis()
        geometry=next(t for t in data['tags'] if t['key']=='geometry')
        self.assertIsNone(geometry['rating'])
        self.assertEqual(geometry['status'],'unknown')

    def test_personal_shared_account_cannot_create_three_people(self):
        with app.connect_db() as conn:
            conn.execute("UPDATE handles SET handle='CF1' WHERE owner_id='2'")
        with self.assertRaisesRegex(ValueError,'相同'):
            self.analysis()

    def bind(self, owner, platform, handle, kind=None, active=1):
        with app.connect_db() as conn:
            row = conn.execute("INSERT INTO handles(owner_type,owner_id,platform,handle,active,created_at) VALUES('user',?,?,?,?,?)",
                (str(owner), platform, handle, active, self.now))
            if kind:
                conn.execute('INSERT INTO cpc_handle_kinds VALUES(?,?)',(row.lastrowid,kind))

    def test_shared_nowcoder_team_is_counted_once_and_never_becomes_personal_power(self):
        before = self.analysis(platform='all')
        self.service.aliases['nowcoder:900'] = self.cid+':A'
        for i in range(1,4):
            self.bind(i,'nowcoder','778088490')
            self.add(i, '778088490-60001' if i==2 else '60001', '900', self.cutoff-100,
                verdict='WA', platform='nowcoder', handle='778088490', raw_extra={'nowcoderSourceId':'778088490'})
            self.add(i, '60002', '900', self.cutoff-50,
                platform='nowcoder', handle='778088490', raw_extra={'nowcoderSourceId':'778088490'})
        # Both CF-only and all comparable sources accept the shared team binding.
        cf = self.analysis()
        data = self.analysis(platform='all')
        self.assertEqual(before['members'], data['members'])
        self.assertEqual(before['overall'], data['overall'])
        self.assertEqual(before['backtest'], data['backtest'])
        self.assertEqual(before['forecast'], data['forecast'])
        self.assertEqual(len(data['teamAccounts']), 1)
        team = data['teamAccounts'][0]
        self.assertEqual(team['members'], ['成员1','成员2','成员3'])
        self.assertEqual(team['coverage']['submissions'], 2)
        self.assertEqual(team['coverage']['problems'], 1)
        self.assertEqual(team['solved'], 1)
        self.assertEqual(team['wa'], 1)
        self.assertTrue(team['inSelectedSource'])
        self.assertFalse(cf['teamAccounts'][0]['inSelectedSource'])

    def test_nowcoder_combined_bindings_keep_personal_sources_and_merge_team_sources(self):
        self.service.aliases.update({'nowcoder:900':self.cid+':A','nowcoder:901':self.cid+':B'})
        self.bind(1,'nowcoder','111111+778088490')
        self.bind(2,'nowcoder','222222+778088490')
        for i, handle in ((1,'111111+778088490'),(2,'222222+778088490')):
            self.add(i,'778088490-70001','900',self.now-50,platform='nowcoder',handle=handle,
                raw_extra={'nowcoderSourceId':'778088490'})
        self.add(1,'70002','901',self.now-40,platform='nowcoder',handle='111111+778088490',
            raw_extra={'nowcoderSourceId':'111111'})
        self.add(1,'unknown-source','900',self.now-30,platform='nowcoder',handle='111111+778088490')
        data = self.analysis(platform='all')
        self.assertEqual(data['members'][0]['overall']['solved'], 13)
        self.assertEqual(data['members'][1]['overall']['solved'], 12)
        self.assertEqual(data['teamAccounts'][0]['coverage']['submissions'], 1)
        self.assertEqual(data['teamAccounts'][0]['solved'], 1)

    def test_marked_team_and_inactive_bindings_are_classified_consistently(self):
        self.bind(1,'nowcoder','778088490',kind='team')
        self.bind(2,'nowcoder','778088490')
        self.bind(1,'nowcoder','111111')
        self.bind(2,'nowcoder','111111',active=0)
        self.add(1,'personal-only','900',self.now-20,platform='nowcoder',handle='111111')
        data = self.analysis(platform='all')
        self.assertEqual(len(data['teamAccounts']), 1)
        self.assertEqual(data['members'][0]['overall']['solved'], 13)
        self.assertEqual(data['members'][1]['overall']['solved'], 12)

    def test_explicit_cf_team_evidence_stays_separate_from_personal_training(self):
        self.bind(1,'codeforces','cf-team',kind='team')
        self.add(1,'cf-team-ac','900A',self.now-20,handle='cf-team',
            raw_extra={'author':{'members':[{'handle':'a'},{'handle':'b'}]}})
        data = self.analysis()
        self.assertEqual(data['members'][0]['overall']['solved'], 12)
        self.assertEqual(data['teamAccounts'][0]['solved'], 1)

    def test_duplicate_validation_only_checks_selected_platform(self):
        self.bind(1,'atcoder','same-person')
        self.bind(2,'atcoder','same-person')
        self.assertEqual(self.analysis()['overall']['reliableMembers'], 3)
        with self.assertRaisesRegex(ValueError,'相同'):
            self.analysis(platform='all')

    def test_training_target_only_changes_coverage_not_predictions(self):
        low, high = self.analysis(target=1500), self.analysis(target=3000)
        self.assertEqual(low['members'], high['members'])
        self.assertEqual(low['overall']['rating'], high['overall']['rating'])
        self.assertEqual(low['forecast'], high['forecast'])
        self.assertEqual(low['backtest'], high['backtest'])
        self.assertNotEqual(low['overall']['status'], high['overall']['status'])

    def test_invalid_inputs(self):
        for kwargs in [{'platform':'atcoder'},{'target':'nan'},{'target':9000},{'budget':0},{'budget':'nan'},{'contest_id':'unknown'}]:
            with self.assertRaises(ValueError): self.analysis(**kwargs)
        with self.assertRaises(ValueError):ta.build_analysis(app,self.service,None,['user:1']*3)

    def test_probability_time_ranges_and_budget_are_ordered(self):
        timing={'scale':45,'low':20,'high':100,'source':'heuristic','samples':0}
        for ability in (800,1800,3500):
            for difficulty in (800,1900,4000):
                for budget in (30,300,600):
                    p=ta.predict(ability,.3,difficulty,budget,timing)
                    self.assertLessEqual(0,p['probabilityRange'][0])
                    self.assertLessEqual(p['probabilityRange'][0],p['probability'])
                    self.assertLessEqual(p['probability'],p['probabilityRange'][1])
                    self.assertLessEqual(p['probabilityRange'][1],1)
                    self.assertLessEqual(0,p['timeRangeMinutes'][0])
                    self.assertLessEqual(p['timeRangeMinutes'][0],p['timeRangeMinutes'][1])
                    self.assertLessEqual(p['timeRangeMinutes'][1],budget)
                    self.assertLessEqual(p['conditionalMinutes'],p['budgetedMinutes'])
                    self.assertLessEqual(p['budgetedMinutes'],budget)
        self.assertLess(ta.predict(1800,.5,1800,30,timing)['probability'],ta.predict(1800,.5,1800,300,timing)['probability'])
        self.assertGreater(ta.predict(2400,.5,1800,300,timing)['probability'],ta.predict(1800,.5,1800,300,timing)['probability'])

    def test_memory_is_bounded_and_multitag_evidence_is_split(self):
        p={'solved':True,'rating':2000,'tags':['dp'],'errors':0,'wa':0,'lastAc':self.now-10*365*86400,'lastPractice':self.now}
        old=ta.estimate([p]*12,self.now)
        self.assertLessEqual(old['memoryPenalty'],100)
        self.assertGreaterEqual(old['memoryPenalty'],99)
        multi=ta.estimate([{**p,'tags':['dp','math']}]*12,self.now)
        self.assertLess(multi['confidence'],old['confidence'])

    def test_specialist_and_third_member_backup(self):
        def person(rating):return {'rating':rating,'reliable':True,'confidence':.9,'ratedSolved':20}
        duo=ta.combine([person(2300),person(2100)],1900)
        trio=ta.combine([person(2300),person(2100),person(2100)],1900)
        self.assertGreater(trio['rating'],duo['rating'])
        lone=ta.combine([person(2500)],1900)
        self.assertEqual(lone['status'],'specialist')
        self.assertEqual(lone['rating'],2250)

    def test_single_reliable_member_keeps_reference_without_claiming_team_coverage(self):
        members = [
            {'rating':1898, 'reliable':False, 'confidence':.113, 'ratedSolved':3},
            {'rating':1717, 'reliable':False, 'confidence':.103, 'ratedSolved':4},
            {'rating':2004, 'reliable':True, 'confidence':.413, 'ratedSolved':14},
        ]
        result = ta.combine(members, 1900)
        self.assertIsNone(result['rating'])
        self.assertEqual(result['referenceRating'], 2004)
        self.assertEqual(result['referenceMember'], 2)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['reliableMembers'], 1)
        self.assertIn('仅一人', result['evidenceReason'])
        result = ta.combine(members[:2], 1900)
        self.assertIsNone(result['referenceRating'])

    def test_selectable_categories_group_source_tags_and_deduplicate_each_problem(self):
        def problem(tags):
            return {'solved':True, 'rating':2000, 'tags':tags, 'errors':0, 'wa':0,
                'lastAc':self.now-100, 'lastPractice':self.now-100, 'firstAc':self.now-100,
                'source':'codeforces', 'id':'fixture'}
        p = ta.profile([problem(['dp','combinatorics'])], self.now, 1900)
        self.assertEqual(p['categories']['counting']['practiced'], 1)
        self.assertEqual(p['categories']['counting']['ratedSolved'], 1)
        self.assertEqual(p['categories']['number-theory']['practiced'], 0)
        for tags, category in [(['number theory','chinese remainder theorem'],'number-theory'),
                (['games'],'games'), (['constructive algorithms'],'constructive'),
                (['greedy'],'thinking'), (['probabilities','expectation'],'probability'), (['trees','graphs'],'graphs-trees'),
                (['segment tree','data structures'],'data-structures'), (['geometry'],'geometry')]:
            p = ta.profile([problem(tags)], self.now, 1900)
            self.assertEqual(p['categories'][category]['practiced'], 1)
        self.assertEqual(len(p['categories']), 12)
        self.assertEqual(p['families'], p['categories'])
        p = ta.profile([problem(['segment tree','data structures'])], self.now, 1900)
        self.assertEqual(p['families']['data-structures']['practiced'], 1)
        p = ta.profile([problem(['custom new tag','math']), problem(['dp']), problem([])], self.now, 1900)
        self.assertEqual(p['families']['other']['practiced'], 1)
        result = ta.team_profiles([p,p,p],1900)
        other = next(c for c in result['families'] if c['key']=='other')
        self.assertIn('custom new tag', other['sourceTags'])
        self.assertIn('math', other['sourceTags'])
        self.assertNotIn('dp', other['sourceTags'])
        self.assertEqual(result['families'], result['categories'])

    def test_single_person_reference_is_not_used_as_a_team_forecast(self):
        for j in range(14):
            self.add(1, f'geometry-{j}', f'{200+j}A', self.cutoff-86400+j,
                tags=['geometry','math','greedy'])
        self.service.contests[self.cid]['problems'][0]['tags'] = ['geometry']
        data = self.analysis()
        geometry = next(t for t in data['tags'] if t['key']=='geometry')
        self.assertIsNotNone(geometry['referenceRating'])
        self.assertIsNone(geometry['rating'])
        first = data['forecast']['problems'][0]
        self.assertFalse(first['tagged'])
        self.assertEqual(first['ability'], data['overall']['rating'])

    def test_missing_time_is_not_zero_and_rankland_units(self):
        contest=self.service.contests[self.cid]
        self.assertEqual(ta.onsite_times({'accepted':[self.cid+':A']},contest),{})
        times=ta.onsite_times({'source_type':'rankland','problem_labels':['A','B'],
            'source_statuses':[{'result':'AC','time':[30,'min']},{'result':'RJ'}]},contest)
        self.assertEqual(times,{self.cid+':A':30})


if __name__ == '__main__':
    unittest.main()
