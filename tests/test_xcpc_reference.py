import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from cpc_integration import Integration
import xcpc_reference as xr


class XcpcReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = patch.multiple(app, DATA_DIR=root, DB_PATH=root/'test.sqlite', CACHE_DIR=root/'cache')
        self.paths.start()
        app.init_db()
        self.service = Integration(app)
        self.now = 1791800000
        self.clock = patch.object(xr.time, 'time', return_value=self.now)
        self.clock.start()
        self.member = {'id':'person', 'name':'测试选手', 'school':'测试大学'}
        self.key = xr.player_key(self.member)
        with self.service.db() as conn:
            subject = self.service.subject(conn, '1')
            self.remote = {'roster': {'members':[self.member], 'redirects':{}, 'participations':[]},
                'claims':[{'id':'claim', 'subject':subject, 'person':'person', 'status':'approved', 'updated':self.now-100}]}
            conn.execute('INSERT INTO cpc_remote VALUES(1,?,?)', (json.dumps(self.remote), self.now))
        self.axis = [1850, .5, 10, 'B', .8, 8, 0, 0, 6, None, None, 5, .8, 'established', True, None, 1850, 200, 42]
        tier = {'taxonomyVersion':'test-v4', 'scoreModel':'sequential-irt-v1', 'scoreScale':'rating',
                'contests':6, 'coverage':.8, 'uniqueProblems':72, 'axes':[self.axis]*13}
        self.player = {'key':self.key, 'name':self.member['name'], 'org':self.member['school'],
            'skillPanel':{'all':{'overall':tier}, 'official':{'overall':{**tier, 'contests':4}}},
            'history':[{'title':'区域赛', 'startAt':'2025-01-01', 'official':False, 'solved':7,
                        'rank':20, 'teamCount':300, 'firstATime':10.5, 'dirtWrong':4}]}
        self.meta = {'generatedAt':'2026-10-11T00:00:00Z'}
        self.linked = {'person':'user:1'}
        self.keys = ['user:1','user:2','user:3']
        self.principal = {'type':'user','id':'1'}

    def tearDown(self):
        self.clock.stop()
        self.paths.stop()
        self.temp.cleanup()

    def sync(self):
        with patch.object(xr, 'public_json', side_effect=[self.meta, {self.key:self.player}]) as fetch:
            xr.sync_references(self.service)
        self.assertEqual(fetch.call_args_list[1].args[0], 'data/players/'+hashlib.md5(self.key.encode()).hexdigest()[:2]+'.json')

    def reference(self, principal=None, keys=None, checked=None, linked=None):
        return xr.analysis_reference(self.service, principal or self.principal, keys or self.keys, self.remote,
            self.now if checked is None else checked, self.linked if linked is None else linked, self.now)

    def test_compact_axes_and_formal_starred_scopes_are_preserved(self):
        self.sync()
        data = self.reference()
        self.assertEqual(data['status'], 'ready')
        self.assertFalse(data['usedForPrediction'])
        self.assertEqual(data['panels']['all']['contests'], 6)
        self.assertEqual(data['panels']['official']['contests'], 4)
        self.assertEqual(len(data['panels']['all']['axes']), 13)
        a = data['panels']['all']['axes'][0]
        self.assertEqual((a['score'],a['topPercent'],a['uniqueProblems'],a['confidence']), (1850,10,8,.8))
        self.assertFalse(data['history'][0]['official'])
        self.assertEqual(data['history'][0]['solved'], 7)

    def test_read_only_handler_never_fetches_and_identity_scope_is_self_only(self):
        self.sync()
        with patch.object(xr,'public_json',side_effect=AssertionError('network in read handler')):
            self.assertEqual(self.reference()['status'], 'ready')
            for principal, keys in ((None,self.keys), ({'type':'user','id':'2'},self.keys), (self.principal,['user:2','user:3','user:4'])):
                result = xr.analysis_reference(self.service,principal,keys,self.remote,self.now,self.linked,self.now)
                self.assertNotIn('panels', result)
                self.assertNotIn('url', result)

    def test_expired_or_revoked_identity_hides_cached_reference(self):
        self.sync()
        self.assertNotIn('panels', self.reference(checked=self.now-86400))
        self.assertNotIn('panels', self.reference(linked={}))
        self.remote['claims'].append({**self.remote['claims'][0], 'id':'new', 'status':'revoked', 'updated':self.now})
        with self.service.db() as conn:
            conn.execute('UPDATE cpc_remote SET body=?', (json.dumps(self.remote),))
        with patch.object(xr,'public_json') as fetch:
            xr.sync_references(self.service, force=True)
        fetch.assert_not_called()

    def test_failed_refresh_keeps_same_identity_last_good_data(self):
        self.sync()
        before = self.reference()
        with patch.object(xr,'public_json',side_effect=OSError('offline')):
            xr.sync_references(self.service, force=True)
        after = self.reference()
        self.assertEqual(after['status'], 'stale')
        self.assertEqual(after['panels'], before['panels'])
        self.assertEqual(after['checkedAt'], before['checkedAt'])

    def test_changed_school_cannot_reuse_old_person_cache(self):
        self.sync()
        self.member['school'] = '另一学校'
        self.assertNotIn('panels', self.reference())
        with self.service.db() as conn:
            conn.execute('UPDATE cpc_remote SET body=?', (json.dumps(self.remote),))
        with patch.object(xr,'public_json',side_effect=OSError('offline')):
            xr.sync_references(self.service, force=True)
        self.assertNotIn('panels', self.reference())

    def test_exact_name_and_school_match_required(self):
        with patch.object(xr,'public_json',return_value={self.key:{**self.player, 'org':'同名的其他学校'}}):
            with self.assertRaisesRegex(ValueError,'完全一致'):
                xr.load_player(self.key,self.meta,{})

    def test_cache_throttles_success_and_expired_roster_skips_fetch(self):
        self.sync()
        with patch.object(xr,'public_json') as fetch:
            xr.sync_references(self.service)
        fetch.assert_not_called()
        with self.service.db() as conn:
            conn.execute('UPDATE cpc_remote SET checked=?',(self.now-86400,))
        with patch.object(xr,'public_json') as fetch:
            xr.sync_references(self.service,force=True)
        fetch.assert_not_called()

    def test_legacy_taxonomy_and_invalid_numbers_do_not_create_false_axes(self):
        self.assertEqual(xr.decode_panel({'all':{'overall':{'axes':[self.axis]*7}}}),{})
        axis = {**dict(zip(xr.FIELDS,self.axis)), 'score':float('nan'), 'confidence':2, 'topPercent':-1}
        data = xr.decode_panel({'all':{'overall':{'axes':{'adhoc':axis}}}})['all']['axes']
        self.assertIsNone(data[0]['score'])
        self.assertIsNone(data[0]['confidence'])
        self.assertIsNone(data[0]['topPercent'])
        self.assertIsNone(data[1]['score'])


if __name__ == '__main__':
    unittest.main()
