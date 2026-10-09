import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cpc_scoreboard import prepare_xcpc
from cpc_sources import Scoreboards, rankland_body, public_bytes


class ScoreboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        start = dt.datetime(2024, 12, 1, 3, tzinfo=dt.timezone.utc).timestamp()
        self.config = {'start_time': start, 'end_time': start + 18000,
                       'problems': [{'id': '0', 'label': 'A'}, {'id': '1', 'label': 'B'}],
                       'options': {'submission_timestamp_unit': 'millisecond'}}
        self.team = {'team_id': 'B01', 'name': '打星队', 'organization': '大连理工大学', 'group': ['unofficial']}
        self.contest = {'id': 'icpc-2024-昆明', 'year': 2024, 'problems': [{'index': 'A'}, {'index': 'B'}]}
        self.participation = {'id': 'participation', 'team': '打星队', 'school': '大连理工大学', 'date': '2024-12-01'}

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, runs, teams=None):
        for name, body in [('config', self.config), ('team', teams or [self.team]), ('run', runs)]:
            (self.root / (name + '.json')).write_text(json.dumps(body))
        return prepare_xcpc(self.root, self.contest, self.participation, 'B01', 'https://board.xcpcio.com/test')

    def run_row(self, rid='1', problem='0', status='ACCEPTED', timestamp=1000, **extra):
        return {'submission_id': rid, 'team_id': 'B01', 'problem_id': problem, 'status': status, 'timestamp': timestamp, **extra}

    def test_starred_solve_is_included_with_audit_evidence(self):
        body = self.prepare([self.run_row()])
        self.assertEqual(body['accepted'], ['A'])
        self.assertEqual(body['source_team']['group'], ['unofficial'])
        self.assertEqual(body['accepted_runs'][0]['elapsed_seconds'], 1)
        self.assertEqual(set(body['source_sha256']), {'config', 'team', 'run'})
        self.assertFalse(body['confirmed'])

    def test_final_rejudge_replaces_old_ac_and_other_teams_do_not_leak(self):
        body = self.prepare([self.run_row(), self.run_row(status='WRONG_ANSWER'),
                             self.run_row('2', '1'), self.run_row('3', '0', team_id='other')])
        self.assertEqual(body['accepted'], ['B'])

    def test_practice_after_finish_ignored_and_negative_runs_do_not_count(self):
        self.assertEqual(self.prepare([self.run_row(timestamp=18000000), self.run_row('2', timestamp=-1),
                                       self.run_row('3', ignore=True)])['accepted'], [])

    def test_seconds_and_milliseconds_follow_declared_units(self):
        self.config['options']['submission_timestamp_unit'] = 'second'
        self.config['start_time'] *= 1000
        self.config['end_time'] *= 1000
        self.assertEqual(self.prepare([self.run_row(timestamp=17999)])['accepted'], ['A'])
        self.assertEqual(self.prepare([self.run_row(timestamp=18000)])['accepted'], [])

    def test_ambiguous_team_wrong_school_date_and_question_mapping_are_rejected(self):
        with self.assertRaises(ValueError): self.prepare([], [self.team, self.team])
        self.participation['school'] = '其他学校'
        with self.assertRaises(ValueError): self.prepare([])
        self.participation['school'] = '大连理工大学'
        self.participation['date'] = '2024-12-02'
        with self.assertRaises(ValueError): self.prepare([])
        self.participation['date'] = '2024-12-01'
        self.contest['problems'].append({'index': 'C'})
        with self.assertRaises(ValueError): self.prepare([])

    def test_pending_verdict_and_unmapped_submission_block_import(self):
        with self.assertRaises(ValueError): self.prepare([self.run_row(status='PENDING')])
        with self.assertRaises(ValueError): self.prepare([self.run_row(problem='unknown')])

    def test_rankland_final_problem_status_includes_starred_first_blood(self):
        srk={'type':'general','contest':{'startAt':'2024-12-01T11:00:00+08:00','duration':[5,'h']},
             'problems':[{'alias':'A'},{'alias':'B'}], 'rows':[{'user':{'id':'row','name':'打星队','organization':'大连理工大学','official':False},
             'statuses':[{'result':'FB','time':[1,'min']},{'result':None}]}]}
        raw=('<script>window.__INITIAL_STATE__='+json.dumps(json.dumps({'ranklistData':{'srk':srk}}))+';</script>').encode()
        body=rankland_body(raw,{},self.participation,[], 'https://rl.algoux.cn/ranklist/test')
        self.assertEqual(body['accepted'],['A'])
        self.assertFalse(body['source_team']['official'])
        srk['rows'][0]['statuses'][1]['result']='FZ'
        raw=('<script>window.__INITIAL_STATE__='+json.dumps(json.dumps({'ranklistData':{'srk':srk}}))+';</script>').encode()
        with self.assertRaises(ValueError): rankland_body(raw,{},self.participation,[], 'https://rl.algoux.cn/ranklist/test')

    def test_public_scoreboard_requests_never_accept_private_or_credential_urls(self):
        for url in ['http://rl.algoux.cn/a','https://127.0.0.1/admin','https://cpcfinder.com:8000/api','https://name:password@cpcfinder.com/api']:
            with self.assertRaises(ValueError): public_bytes(url)

    def test_dlut_rankland_link_works_without_cpcfinder_and_preserves_school_aliases(self):
        srk={'type':'general','contest':{'startAt':'2024-12-01T11:00:00+08:00','duration':[5,'h']},
             'problems':[{'alias':'A'},{'alias':'B'}], 'rows':[{'user':{'id':'row','name':'打星队',
             'organization':'Dalian University of Technology','official':False},
             'statuses':[{'result':'AC','time':[120,'min']},{'result':None}]}]}
        raw=('<script>window.__INITIAL_STATE__='+json.dumps(json.dumps({'ranklistData':{'srk':srk}}))+';</script>').encode()
        participation={**self.participation,'event':'昆明站','ranklist_url':'https://rl.algoux.cn/ranklist/icpc2024kunming',
                       'school_names':['大连理工大学','Dalian University of Technology']}
        contest={**self.contest,'series':'ICPC','site':'昆明'}
        with patch('cpc_sources.public_bytes',return_value=raw) as fetch:
            body=Scoreboards(self.root).prepare(None,participation,[],{contest['id']:contest})
        self.assertEqual(body['contest_id'],contest['id'])
        self.assertEqual(body['accepted'],['A'])
        self.assertEqual(fetch.call_count,1)
        self.assertTrue(list((self.root/'rankland').glob('*.html')))
        srk['rows'][0]['statuses'][0]['time']=[301,'min']
        raw=('<script>window.__INITIAL_STATE__='+json.dumps(json.dumps({'ranklistData':{'srk':srk}}))+';</script>').encode()
        with self.assertRaises(ValueError):rankland_body(raw,{},participation,[],participation['ranklist_url'])
