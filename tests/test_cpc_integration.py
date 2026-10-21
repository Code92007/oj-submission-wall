import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import app
from cpc_integration import Integration, handle, problem_key


class CpcTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        self.patch=patch.multiple(app,DATA_DIR=root,DB_PATH=root/'db.sqlite',CACHE_DIR=root/'cache',HTTP_CACHE_DIR=root/'cache/http')
        self.patch.start();app.init_db();self.service=Integration(app)

    def tearDown(self):
        self.patch.stop();self.temp.cleanup()

    def test_platform_aliases_match_existing_catalog(self):
        for platform,value in [('codeforces','105657A'),('vjudge','Gym-105657A'),('luogu','CF105657A')]:
            self.assertEqual(problem_key(platform,value),'codeforces:105657A')
        self.assertEqual(self.service.aliases['qoj:9726'],self.service.aliases['codeforces:105657A'])

    def test_read_token_rotation_and_unknown_owner(self):
        first=self.service.issue_token('1')['token']
        second=self.service.issue_token('1')['token']
        self.assertIsNone(self.service.token_owner(first))
        self.assertEqual(self.service.token_owner(second),'1')
        self.assertIsNone(self.service.token_owner('invalid'))

    def test_regional_page_exposes_release_without_changing_ac_snapshot(self):
        class Handler:
            path='/api/cpc/me'
            headers={}
            def send_json(self,status,body):self.status,self.body=status,body
        handler=Handler()
        release=json.loads((app.ROOT/'catalog/regional_ratings.json').read_text())
        self.service.rating_release['problems']['unknown:A']={'rating':3000}
        before=self.service.progress('1')
        with patch.object(app,'get_current_principal',return_value={'type':'user','id':'1'}):
            self.assertTrue(handle(handler,self.service))
        self.assertEqual(handler.status,200)
        self.assertEqual(handler.body['difficulty'],{pid:d for pid,d in release['problems'].items() if pid in self.service.problem_ids})
        self.assertEqual(handler.body['ratingRelease']['source_revision'],release['source_revision'])
        self.assertEqual(handler.body['problems'],before['problems'])
        self.assertEqual(handler.body['record_count'],before['record_count'])
        handler.path='/api/integration/v1/me/progress/snapshot'
        handler.headers={'Authorization':'Bearer '+self.service.issue_token('1')['token']}
        self.assertTrue(handle(handler,self.service))
        self.assertNotIn('difficulty',handler.body)
        self.assertEqual(handler.body['problems'],before['problems'])

    def test_cross_origin_write_does_not_issue_token(self):
        class Handler:
            path='/api/cpc/token'
            headers={'Origin':'https://evil.example','Host':'wall.example'}
            def send_error_json(self,status,message):self.status=status
        handler=Handler()
        with patch.object(app,'get_current_principal',return_value={'type':'user','id':'1'}):
            handle(handler,self.service,post=True)
        self.assertEqual(handler.status,403)
        with self.service.db() as db:self.assertEqual(db.execute('select count(*) from cpc_read_tokens').fetchone()[0],0)

    def test_unknown_scoreboard_problem_is_atomic(self):
        body={'confirmed':True,'contest_id':'icpc-2024-杭州','accepted':['A','INVALID'],
              'source_url':'https://example.com/final','source_row':'1'}
        with self.assertRaises(ValueError):self.service.import_onsite(body)
        with self.service.db() as db:self.assertEqual(db.execute('select count(*) from cpc_onsite').fetchone()[0],0)

    def test_catalog_mapping_overrides_replay_link_with_a_missing_gym_letter(self):
        cid='ccpc-2020-秦皇岛'
        participation={'id':'historical','team':'原队伍','date':'2020-10-18'}
        body={'contest_id':cid,'problem_labels':list('ABCDEFGHIJKL'),'accepted':['A','C'],
              'reference_urls':['https://codeforces.com/gym/102769'],
              'participation_id':participation['id'],'team':participation['team'],
              'contest_date':participation['date'],'source_url':'https://rl.algoux.cn/ranklist/ccpc2020qinhuangdao'}
        with patch.object(self.service,'remote',return_value=({'roster':{'participations':[participation]}},0)):
            key=self.service.import_auto_onsite(body)
        with self.service.db() as db:
            saved=json.loads(db.execute('select body from cpc_onsite where id=?',(key,)).fetchone()[0])
        self.assertEqual(saved['accepted'],[cid+':A',cid+':C'])
        self.assertEqual(saved['problem_aliases'][cid+':A'],'codeforces:102769A')
        self.assertNotIn(cid+':C',saved['problem_aliases'])

    def test_pending_problem_list_keeps_verified_onsite_evidence_without_inventing_catalog(self):
        cid='icpc-2018-香港'
        participation={'id':'pending-list','team':'原队伍','date':'2018-11-04'}
        body={'contest_id':cid,'problem_labels':['A','B'],'accepted':['B'],
              'reference_urls':[], 'participation_id':participation['id'],'team':participation['team'],
              'contest_date':participation['date'],'source_url':'https://organizer.example/final'}
        remote={'roster':{'participations':[participation]}}
        with patch.object(self.service,'remote',return_value=(remote,0)):
            key=self.service.import_auto_onsite(body)
        with self.service.db() as db:
            saved=json.loads(db.execute('select body from cpc_onsite where id=?',(key,)).fetchone()[0])
        self.assertEqual(saved['accepted'],[cid+':B'])
        self.assertEqual(saved['problem_aliases'],{})
        self.assertEqual(self.service.contests[cid]['problems'],[])
        self.assertNotIn(cid+':B',self.service.problem_ids)

    def seed_wall_onsite(self):
        self.person = 'person'
        self.contest = {**self.service.contests['icpc-2024-杭州'], 'date': '2024-11-17'}
        with self.service.db() as db:
            db.execute("insert into users(id,username,email,display_name,password_hash,created_at) values(1,'member','member@example.com','成员','unused',0)")
            subject = self.service.subject(db, '1')
            self.remote = {'roster': {'members': [], 'redirects': {}, 'participations': [
                {'id': 'participation', 'members': [self.person], 'team': '现场队伍',
                 'date': self.contest['date'], 'event': self.contest['name'], 'official': False}]},
                'claims': [{'id': 'claim', 'subject': subject, 'person': self.person, 'status': 'approved', 'updated': 1}]}
        self.save_wall_remote()
        self.evidence = {'confirmed': True, 'contest_id': self.contest['id'], 'accepted': ['A', 'B'],
            'source_url': 'https://example.com/final', 'source_row': 'team-row',
            'participation_id': 'participation', 'team': '现场队伍'}
        self.evidence_id = self.service.import_onsite(self.evidence)

    def save_wall_remote(self, checked=None):
        with self.service.db() as db:
            db.execute('insert or replace into cpc_remote values(1,?,?)',
                       (json.dumps(self.remote), int(time.time()) if checked is None else checked))

    def wall_overview(self, feed_limit=0):
        with patch.object(app, 'get_cpc_service', return_value=self.service), patch.object(app, 'OVERVIEW_FEED_LIMIT', feed_limit):
            return app.build_overview_from_db(None)

    def test_verified_onsite_appears_in_feed_statistics_and_handle_filter(self):
        self.seed_wall_onsite()
        overview = self.wall_overview()
        member = overview['members'][0]
        self.assertEqual(member['stats']['allTimeAccepted'], 2)
        self.assertEqual(member['days'][self.contest['date']], {'accepted': 2, 'total': 2})
        self.assertEqual(member['handles'][0]['activity']['stats']['allTimeAccepted'], 2)
        self.assertEqual(len(overview['feed']), 2)
        row = overview['feed'][0]
        self.assertEqual((row['platformLabel'], row['handle'], row['source']), ('区域赛现场', '现场队伍', 'cpc-onsite'))
        self.assertEqual((row['submittedDate'], row['submittedPrecision']), (self.contest['date'], 'date'))
        self.assertEqual(row['url'], self.evidence['source_url'])
        with patch.object(app, 'get_cpc_service', return_value=self.service):
            insights = app.build_insights(None, 'user:1')
        self.assertEqual(insights['summaries']['all']['careerSolved'], 2)
        self.assertEqual(insights['summaries']['regional']['acceptedSubmissions'], 2)
        self.assertIn({'key': 'regional', 'label': '区域赛现场'}, insights['platforms'])
        # The regional API must retain its onsite attribution and team eligibility.
        progress = self.service.progress('1')
        self.assertTrue(progress['problems'][self.contest['id'] + ':A']['onsite'])
        self.assertFalse(progress['problems'][self.contest['id'] + ':A']['personal'])
        self.assertFalse(progress['onsite_contests'][0]['official'])

    def test_online_and_onsite_ac_share_solved_key_but_keep_both_records(self):
        self.seed_wall_onsite()
        problem = self.contest['problems'][0]
        aliases = [alias.split(':', 1) for alias in problem['aliases']]
        for platform, pid in aliases:
            self.assertEqual(app.canonical_problem_key(platform, pid), app.canonical_problem_key('regional', problem['id']))
        platform, pid = aliases[0]
        with self.service.db() as db:
            db.execute("insert into handles(owner_type,owner_id,platform,handle,created_at) values('user','1',?,'online',0)", (platform,))
            db.execute("insert into submissions(owner_type,owner_id,platform,handle,remote_id,problem_id,verdict,submitted_at,created_at) values('user','1',?,'online','online-ac',?,'AC',?,0)",
                       (platform, pid, int(time.time())))
        overview = self.wall_overview(feed_limit=1)
        self.assertEqual(len(overview['feed']), 3)
        self.assertEqual(overview['members'][0]['stats']['allTimeAccepted'], 2)
        with patch.object(app, 'get_cpc_service', return_value=self.service):
            insights = app.build_insights(None, 'user:1')
        self.assertEqual(insights['summaries']['all']['careerSolved'], 2)
        self.assertEqual(insights['summaries']['all']['acceptedSubmissions'], 3)

    def test_duplicate_evidence_is_idempotent_and_rejudging_removes_old_ac(self):
        self.seed_wall_onsite()
        extra = self.service.import_onsite({**self.evidence, 'source_row': 'second-audit'})
        first = self.wall_overview()['feed']
        self.assertEqual(len(first), 2)
        self.assertEqual(self.wall_overview()['feed'], first)
        self.service.import_onsite({**self.evidence, 'accepted': ['A']})
        self.assertEqual(len(self.wall_overview()['feed']), 2)
        self.service.revoke_onsite(extra)
        rows = self.wall_overview()['feed']
        self.assertEqual([r['problemId'] for r in rows], [self.contest['id'] + ':A'])
        with self.service.db() as db:
            self.assertEqual(db.execute('select count(*) from submissions').fetchone()[0], 0)

    def test_revoked_expired_and_pending_identity_remove_onsite_records(self):
        self.seed_wall_onsite()
        with self.service.db() as db:
            db.execute("insert into submissions(owner_type,owner_id,platform,handle,remote_id,problem_id,verdict,submitted_at,created_at) values('user','1','codeforces','personal','42','1A','AC',1,1)")
        for status in ['revoked', 'pending', 'rejected']:
            self.remote['claims'][0]['status'] = status
            self.save_wall_remote()
            self.assertEqual([r['remoteId'] for r in self.wall_overview()['feed']], ['42'])
        self.remote['claims'][0]['status'] = 'approved'
        self.save_wall_remote(checked=int(time.time()) - 86401)
        self.assertEqual([r['remoteId'] for r in self.wall_overview()['feed']], ['42'])
        self.save_wall_remote()
        self.assertEqual(len(self.wall_overview()['feed']), 3)

    def test_onsite_attribution_is_limited_to_the_approved_account(self):
        self.seed_wall_onsite()
        with self.service.db() as db:
            db.execute("insert into users(id,username,email,display_name,password_hash,created_at) values(2,'other','other@example.com','其他成员','unused',1)")
            self.service.subject(db, '2')
        overview = self.wall_overview()
        members = {m['ownerId']: m for m in overview['members']}
        self.assertEqual(members['1']['stats']['allTimeAccepted'], 2)
        self.assertEqual(members['2']['stats']['allTimeAccepted'], 0)
        self.assertTrue(all(r['ownerId'] == '1' for r in overview['feed']))

    def test_identity_redirect_and_unmapped_problem_keep_verified_onsite_coverage(self):
        self.seed_wall_onsite()
        self.remote['roster']['redirects'] = {self.person: 'merged-person'}
        self.remote['roster']['participations'][0]['members'] = ['merged-person']
        self.save_wall_remote()
        with self.service.db() as db:
            body = {**self.evidence, 'accepted': ['unmapped-contest:Z']}
            db.execute('update cpc_onsite set body=? where id=?', (json.dumps(body), self.evidence_id))
        overview = self.wall_overview()
        self.assertEqual(overview['members'][0]['stats']['allTimeAccepted'], 1)
        self.assertEqual(overview['feed'][0]['problemId'], 'unmapped-contest:Z')
