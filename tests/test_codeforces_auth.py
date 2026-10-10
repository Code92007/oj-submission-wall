import hashlib
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import app
import codeforces_auth as auth_module
from codeforces_auth import CodeforcesAuth, ManagerAccessUnavailable, load_auth, signed_api_get, signed_url
from cpc_integration import Integration


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.auth = CodeforcesAuth('3', 'Yzm007', 'test-key', 'test-secret')

    def test_signature_matches_official_sorted_parameter_algorithm(self):
        url = signed_url('user.status', {'handle': 'Yzm007', 'from': 1, 'count': 1000}, self.auth,
                         timestamp=1700000000, nonce='123456')
        query = parse_qs(urlparse(url).query)
        expected = hashlib.sha512(b'123456/user.status?apiKey=test-key&count=1000&from=1&handle=Yzm007&time=1700000000#test-secret').hexdigest()
        self.assertEqual(query['apiSig'], ['123456' + expected])
        self.assertNotIn('test-secret', url)
        self.assertNotIn('test-key', repr(self.auth))

    def test_owner_and_handle_both_required_and_file_reload_supports_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'codeforces-auth.json'
            self.assertIsNone(load_auth(path, 'user', '3', 'Yzm007'))
            path.write_text(json.dumps({'accounts': [{'ownerId': '3', 'handle': 'Yzm007', 'key': 'one', 'secret': 'secret'}]}))
            first = load_auth(path, 'user', '3', 'yzm007')
            self.assertIsNotNone(first)
            for owner_type, owner_id, handle in [('user', '4', 'Yzm007'), ('guest', '3', 'Yzm007'), ('user', '3', 'other')]:
                self.assertIsNone(load_auth(path, owner_type, owner_id, handle))
            path.write_text(path.read_text().replace('one', 'two'))
            self.assertNotEqual(first.history_token, load_auth(path, 'user', '3', 'Yzm007').history_token)

    def test_private_request_cannot_query_another_handle_or_source_codes(self):
        for params in [{'handle': 'other'}, {'handle': 'Yzm007', 'includeSources': True}]:
            with self.assertRaises(ValueError):
                signed_url('user.status', params, self.auth, timestamp=1, nonce='123456')

    def test_gym_manager_signature_requires_own_handle_gym_and_no_source_codes(self):
        valid = {'handle': 'Yzm007', 'contestId': 104076, 'asManager': 'true', 'from': 1, 'count': 1000}
        url = signed_url('contest.status', valid, self.auth, timestamp=1, nonce='123456')
        self.assertEqual(parse_qs(urlparse(url).query)['asManager'], ['true'])
        for params in [{**valid, 'handle': 'other'}, {**valid, 'contestId': 2000}, {**valid, 'includeSources': 'true'}, {k:v for k,v in valid.items() if k!='handle'}]:
            with self.assertRaises(ValueError):
                signed_url('contest.status', params, self.auth, timestamp=1, nonce='123456')

    def test_explicit_manager_permission_error_remains_distinct_from_bad_api_key(self):
        params = {'handle':'Yzm007','contestId':104076,'asManager':'true'}
        with patch.object(auth_module.time, 'sleep'):
            with self.assertRaises(ManagerAccessUnavailable):
                signed_api_get('contest.status', params, self.auth,
                               lambda *a,**k:(b'{"status":"FAILED","comment":"asManager: You should be a manager of the contest"}', ''))
            with self.assertRaises(RuntimeError) as error:
                signed_api_get('contest.status', params, self.auth,
                               lambda *a,**k:(b'{"status":"FAILED","comment":"apiKey: Invalid API key"}', ''))
            self.assertNotIsInstance(error.exception, ManagerAccessUnavailable)

    def test_signed_http_disables_shared_cache_and_sanitizes_errors(self):
        calls = []
        def fetch(url, **kwargs):
            calls.append(kwargs)
            return b'{"status":"OK","result":[]}', 'application/json'
        with patch.object(auth_module.time, 'sleep'):
            self.assertEqual(signed_api_get('user.status', {'handle': 'Yzm007'}, self.auth, fetch)['result'], [])
            def broken(url, **kwargs):
                raise RuntimeError(url + ' test-secret')
            with self.assertRaises(RuntimeError) as error:
                signed_api_get('user.status', {'handle': 'Yzm007'}, self.auth, broken)
            self.assertNotIn('test-key', str(error.exception))
            self.assertNotIn('test-secret', str(error.exception))
            self.assertNotIn('apiSig', str(error.exception))
        self.assertEqual(calls, [{'allow_stale_cache': False, 'cache_write': False}])


class CoachHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = patch.multiple(app, DATA_DIR=root, DB_PATH=root/'db.sqlite3',
                                     CACHE_DIR=root/'cache', HTTP_CACHE_DIR=root/'cache/http',
                                     CODEFORCES_AUTH_FILE=root/'codeforces-auth.json', FETCH_LIMIT=4)
        self.patches.start()
        app.init_db()
        self.service = Integration(app)
        self.now = app.utcnow()
        with app.connect_db() as db:
            db.execute("INSERT INTO handles(id,owner_type,owner_id,platform,handle,created_at) VALUES(3,'user','3','codeforces','Yzm007',?)", (self.now,))
        self.auth_data = {'accounts': [{'ownerId': '3', 'handle': 'Yzm007', 'key': 'key', 'secret': 'secret'}]}
        self.old = self.now - 3 * 365 * 86400
        self.vp = [self.sub(100+i, p, 'VIRTUAL', self.old) for i, p in enumerate('AEKM')]
        self.coach = [self.sub(200+i, p, 'MANAGER', self.old+86400) for i, p in enumerate('CDGJ')]
        self.newest = self.sub(300, 'A', 'PRACTICE', self.now-10, contest=2000)

    def tearDown(self):
        self.patches.stop()
        self.temp.cleanup()

    def sub(self, remote_id, index, kind, timestamp, contest=104076):
        return {'id': remote_id, 'contestId': contest, 'creationTimeSeconds': timestamp,
                'problem': {'contestId': contest, 'index': index, 'name': index},
                'verdict': 'OK', 'author': {'participantType': kind, 'members': [{'handle': 'Yzm007'}],
                                           'teamId': 98797 if kind == 'VIRTUAL' else None,
                                           'startTimeSeconds': self.old}}

    def sync(self, records, *, fail=False, deny=False, wrong_owner=False):
        pages = []
        def status(method, params, auth, getter):
            pages.append((method,params['from']))
            if method == 'contest.status' and deny:
                raise ManagerAccessUnavailable()
            if method == 'contest.status' and fail and params['from'] > 1:
                raise RuntimeError('授权读取失败')
            source = [r for r in records if (r['author']['participantType']!='MANAGER' if method=='user.status' else r['contestId']==params['contestId'])]
            if method == 'contest.status' and wrong_owner:
                source = [{**self.coach[0], 'author': {'participantType':'MANAGER','members':[{'handle':'other'}]}}]
            start = params['from'] - 1
            return {'status': 'OK', 'result': source[start:start+params['count']]}
        def public(url, **kwargs):
            if '/user.rating?' in url:
                return {'status': 'OK', 'result': []}
            query = parse_qs(urlparse(url).query)
            start = int(query['from'][0])-1
            return {'status': 'OK', 'result': records[start:start+int(query['count'][0])]}
        with patch.object(app, 'signed_api_get', side_effect=status), \
                patch.object(app, 'http_get_json', side_effect=public), \
                patch.object(app, 'codeforces_contest_lookup', return_value={}):
            with app.connect_db() as db:
                row = db.execute('SELECT * FROM handles WHERE id=3').fetchone()
                result = app.sync_handle_row(db, row, force=True)
        return result, pages

    def test_first_authorization_backfills_old_coach_ac_merges_vp_and_then_is_incremental(self):
        self.sync([self.newest]+self.vp)
        app.CODEFORCES_AUTH_FILE.write_text(json.dumps(self.auth_data))
        result, pages = self.sync([self.newest]+self.coach+self.vp)
        self.assertEqual(pages, [('user.status',1),('user.status',5),('contest.status',1),('contest.status',5),('contest.status',9)])
        self.assertEqual(result['inserted'], 4)
        progress = self.service.progress('3')['problems']
        self.assertEqual({p for p in 'ABCDEFGHIJKLM' if progress.get('icpc-2022-济南:'+p, {}).get('personal')}, set('ACDEGJKM'))
        with app.connect_db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM submissions WHERE owner_id="3"').fetchone()[0], 9)
            contests = db.execute('SELECT raw_json FROM contests WHERE owner_id="3"').fetchall()
            self.assertEqual(len(contests), 1)
            self.assertNotIn('MANAGER', contests[0]['raw_json'])
            self.assertIn('codeforcesAuthHistory', json.loads(db.execute('SELECT stats_json FROM handles WHERE id=3').fetchone()[0]))
        second, pages = self.sync([self.newest]+self.coach+self.vp)
        self.assertEqual(pages, [('user.status',1),('contest.status',1),('contest.status',5),('contest.status',9)])
        self.assertEqual(second['inserted'], 0)
        self.assertEqual(self.service.progress('4')['problems'], {})

    def test_failed_gym_page_discards_its_partial_data_then_retries_full_gym(self):
        self.sync([self.newest]+self.vp)
        app.CODEFORCES_AUTH_FILE.write_text(json.dumps(self.auth_data))
        result, _ = self.sync([self.newest]+self.coach+self.vp, fail=True)
        self.assertIn('Gym 104076 Coach 提交读取失败', result['warning'])
        with app.connect_db() as db:
            row = db.execute('SELECT stats_json FROM handles WHERE id=3').fetchone()
            self.assertIn('codeforcesAuthHistory', json.loads(row['stats_json'] or '{}'))
            self.assertEqual(db.execute('SELECT count(*) FROM submissions').fetchone()[0], 5)
        result, pages = self.sync([self.newest]+self.coach+self.vp)
        self.assertEqual(result['inserted'], 4)
        self.assertEqual(pages, [('user.status',1),('contest.status',1),('contest.status',5),('contest.status',9)])

    def test_manager_permission_denial_keeps_public_history_and_warns(self):
        self.sync([self.newest]+self.vp)
        app.CODEFORCES_AUTH_FILE.write_text(json.dumps(self.auth_data))
        result, _ = self.sync([self.newest]+self.coach+self.vp, deny=True)
        self.assertIn('Coach 记录不可读', result['warning'])
        with app.connect_db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM submissions').fetchone()[0], 5)
        retried, _ = self.sync([self.newest]+self.coach+self.vp)
        self.assertEqual(retried['inserted'], 4)

    def test_unavailable_old_gym_does_not_block_other_gyms_coach_history(self):
        self.sync([self.newest]+self.vp)
        app.CODEFORCES_AUTH_FILE.write_text(json.dumps(self.auth_data))
        adapter=app.ADAPTERS['codeforces']
        def fetch(method,params,auth,getter):
            if method=='user.status':
                return {'status':'OK','result':[self.newest]}
            if params['contestId']==100371:
                raise RuntimeError('historical API HTTP 400')
            start=params['from']-1
            return {'status':'OK','result':(self.coach+self.vp)[start:start+params['count']]}
        warnings=[]
        with patch.object(app,'signed_api_get',side_effect=fetch):
            records=adapter.fetch_submissions('Yzm007',self.now-100,auth=load_auth(app.CODEFORCES_AUTH_FILE,'user','3','Yzm007'),
                                               known_gym_ids={100371,104076},gym_warnings=warnings)
        self.assertEqual({r['problem_id'] for r in records if r['problem_id'].startswith('104076')}, {'104076'+p for p in 'ACDEGJKM'})
        self.assertEqual(len(warnings),1)
        self.assertIn('100371',warnings[0])

    def test_manager_api_returning_other_users_rows_is_rejected(self):
        self.sync([self.newest]+self.vp)
        app.CODEFORCES_AUTH_FILE.write_text(json.dumps(self.auth_data))
        result, _ = self.sync([self.newest]+self.coach+self.vp, wrong_owner=True)
        self.assertIn('归属不匹配',result['error'])
        with app.connect_db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM submissions').fetchone()[0], 5)

    def test_coach_submission_never_counts_as_a_contest_solve(self):
        row = {'handle': 'Yzm007', 'platform': 'codeforces', 'raw_json': json.dumps(self.coach[0]),
               'submitted_at': self.old+86400, 'problem_id': '104076C'}
        entry = {'handle': 'Yzm007', 'remoteId': '104076', '_startTimestamp': self.old,
                 '_endTimestamp': self.old+2*86400}
        self.assertIsNone(app.battle_in_contest_solve(row, entry))

    def test_interactive_configuration_preserves_other_accounts_and_private_permissions(self):
        path = app.CODEFORCES_AUTH_FILE
        other = {'ownerId': '4', 'handle': 'other', 'key': 'other-key', 'secret': 'other-secret'}
        path.write_text(json.dumps({'accounts': [other]}))
        with patch('sys.argv', ['configure_codeforces.py', '--owner-id', '3', '--handle', 'Yzm007']), \
                patch('getpass.getpass', side_effect=['key', 'secret']), patch('builtins.print'):
            runpy.run_path(str(Path(app.__file__).parent/'tools/configure_codeforces.py'), run_name='__main__')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertIn(other, json.loads(path.read_text())['accounts'])
        self.assertIsNotNone(load_auth(path, 'user', '3', 'Yzm007'))


if __name__ == '__main__':
    unittest.main()
