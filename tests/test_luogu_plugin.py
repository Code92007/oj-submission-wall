import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app


class LuoguPluginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = patch.object(app, 'DB_PATH', Path(self.tmp.name) / 'wall.db')
        self.db.start()
        app.init_db()
        with app.connect_db() as conn:
            conn.execute("INSERT INTO handles(owner_type,owner_id,platform,handle,created_at) VALUES ('user','1','luogu','123',?)", (app.utcnow(),))
            self.row = conn.execute('SELECT * FROM handles').fetchone()

    def tearDown(self):
        self.db.stop()
        self.tmp.cleanup()

    def record(self, **fields):
        return dict(id=456, submitTime=app.utcnow(), status=12, score=100,
                    user={'uid': 123}, problem={'pid': 'P1000', 'title': 'test', 'fullScore': 100}, **fields)

    def test_import_is_idempotent_and_filters_private_fields(self):
        record = self.record(sourceCode='secret', cookie='secret')
        with app.connect_db() as conn:
            app.import_luogu_records(conn, self.row, [record])
            record['status'], record['score'] = 14, 0
            app.import_luogu_records(conn, self.row, [record])
            rows = conn.execute('SELECT * FROM submissions').fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['verdict'], 'WRONG_ANSWER')
            self.assertNotIn('secret', rows[0]['raw_json'])

    def test_wrong_account_rejects_entire_batch(self):
        wrong = self.record(); wrong['user']['uid'] = 789
        with app.connect_db() as conn:
            with self.assertRaises(ValueError):
                app.import_luogu_records(conn, self.row, [self.record(), wrong])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM submissions').fetchone()[0], 0)

    def test_manual_mode_never_fetches(self):
        with patch.object(app, 'LUOGU_BROWSER_IMPORT', True), patch.object(app.LuoguAdapter, 'fetch_submissions', side_effect=AssertionError('network')):
            with app.connect_db() as conn:
                self.assertTrue(app.sync_handle_row(conn, self.row, force=True)['manual'])

    def handler(self, path, data, token=''):
        handler = object.__new__(app.AppHandler)
        handler.path = path
        body = json.dumps(data).encode()
        handler.headers = {'Content-Length': str(len(body)), 'Authorization': 'Bearer ' + token}
        handler.send_error_json = lambda status, message: (status, {"error": message})
        handler.rfile = io.BytesIO(body)
        handler.send_json = lambda status, data, **kw: (status, data)
        return handler

    def test_import_endpoint_rejects_expired_and_unbound_token(self):
        with app.connect_db() as conn:
            conn.execute('INSERT INTO luogu_plugin_tokens VALUES (?, ?, ?)', (app.sha256_hex('token'), self.row['id'], app.utcnow()+60))
        handler = self.handler('/api/luogu-plugin/import', {'uid': '123', 'records': [self.record()]}, 'token')
        self.assertEqual(handler.do_POST()[0], 200)
        with app.connect_db() as conn:
            conn.execute('UPDATE handles SET active=0')
        self.assertEqual(self.handler('/api/luogu-plugin/import', {'uid': '123', 'records': []}, 'token').do_POST()[0], 401)

    def test_authorization_requires_login(self):
        handler = self.handler('/api/luogu-plugin/authorize', {'uid': '123'})
        with patch.object(app, 'get_current_principal', return_value=None):
            self.assertEqual(handler.do_POST()[0], 401)

    def test_token_expiry_and_owner_scope(self):
        with app.connect_db() as conn:
            conn.execute('INSERT INTO luogu_plugin_tokens VALUES (?, ?, ?)', (app.sha256_hex('token'), self.row['id'], app.utcnow()-1))
            rows = conn.execute('SELECT h.* FROM handles h JOIN luogu_plugin_tokens t ON t.handle_id=h.id WHERE t.token_hash=? AND t.expires_at>? AND h.active=1', (app.sha256_hex('token'), app.utcnow())).fetchall()
            self.assertFalse(rows)

class QOJPluginTest(LuoguPluginTest):
    def setUp(self):
        super().setUp()
        with app.connect_db() as conn:
            conn.execute("INSERT INTO handles(owner_type,owner_id,platform,handle,created_at) VALUES ('user','1','qoj','ucup-team123',?)", (app.utcnow(),))
            self.qoj = conn.execute("SELECT * FROM handles WHERE platform='qoj'").fetchone()

    def qoj_record(self):
        return dict(id='789',problemId='42',problemTitle='#42. Test',submitter='ucup-team123',
                    verdict='100 ✓',language='C++20',submittedAt=app.utcnow(),sourceCode='secret')

    def test_qoj_import_updates_and_filters_private_fields(self):
        with app.connect_db() as conn:
            record = self.qoj_record()
            app.import_qoj_records(conn,self.qoj,[record])
            record['verdict']='Wrong Answer'
            app.import_qoj_records(conn,self.qoj,[record])
            rows=conn.execute("SELECT * FROM submissions WHERE platform='qoj'").fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['verdict'],'WA')
            self.assertNotIn('secret',rows[0]['raw_json'])
            self.assertEqual(rows[0]['url'],'https://qoj.ac/submission/789')

    def test_qoj_import_rejects_other_account_atomically(self):
        record=self.qoj_record(); record['submitter']='other'
        with app.connect_db() as conn:
            with self.assertRaises(ValueError):
                app.import_qoj_records(conn,self.qoj,[self.qoj_record(),record])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM submissions').fetchone()[0],0)

    def test_qoj_authorization_and_platform_isolation(self):
        handler=self.handler('/api/qoj-plugin/authorize',{'uid':'ucup-team123'})
        with patch.object(app,'get_current_principal',return_value={'type':'user','id':'1'}):
            status,result=handler.do_POST()
        self.assertEqual(status,200)
        token=result['token']
        data={'uid':'ucup-team123','records':[self.qoj_record()]}
        self.assertEqual(self.handler('/api/qoj-plugin/import',data,token).do_POST()[0],200)
        self.assertEqual(self.handler('/api/luogu-plugin/import',data,token).do_POST()[0],401)
        with app.connect_db() as conn:
            stored=conn.execute('SELECT token_hash FROM luogu_plugin_tokens WHERE handle_id=?',(self.qoj['id'],)).fetchone()[0]
            self.assertEqual(stored,app.sha256_hex(token))
        with patch.object(app,'get_current_principal',return_value={'type':'user','id':'1'}):
            self.handler('/api/qoj-plugin/authorize',{'uid':'ucup-team123'}).do_POST()
        self.assertEqual(self.handler('/api/qoj-plugin/import',data,token).do_POST()[0],401)

    def test_global_sync_excludes_browser_platforms_even_in_legacy_mode(self):
        with app.connect_db() as conn:
            conn.execute("INSERT INTO handles(owner_type,owner_id,platform,handle,created_at) VALUES ('user','1','codeforces','test',?)", (app.utcnow(),))
        with patch.object(app,'LUOGU_BROWSER_IMPORT',False), patch.object(app,'sync_handle_row',return_value={}) as sync:
            results=app.sync_targets(force=True)
            self.assertEqual(len(results),1)
            self.assertEqual(sync.call_args.args[1]['platform'],'codeforces')
        snapshot={'_runningInternal':{'principal':None,'handle_id':None},
                  '_pendingInternal':[{'principal':{'type':'user','id':'1'},'handle_id':None}]}
        self.assertEqual(app.sync_status_for_handle(self.row,snapshot),'')
        self.assertEqual(app.sync_status_for_handle(self.qoj,snapshot),'')

    def test_disconnect_revokes_only_matching_platform_and_keeps_data(self):
        with app.connect_db() as conn:
            app.import_qoj_records(conn,self.qoj,[self.qoj_record()])
            conn.execute('INSERT INTO luogu_plugin_tokens VALUES (?,?,?)',(app.sha256_hex('qoj-token'),self.qoj['id'],app.utcnow()+100))
            conn.execute('INSERT INTO luogu_plugin_tokens VALUES (?,?,?)',(app.sha256_hex('luogu-token'),self.row['id'],app.utcnow()+100))
        self.assertEqual(self.handler('/api/luogu-plugin/revoke',{},'qoj-token').do_POST()[0],200)
        with app.connect_db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM luogu_plugin_tokens').fetchone()[0],2)
        for _ in range(2):
            self.assertEqual(self.handler('/api/qoj-plugin/revoke',{},'qoj-token').do_POST()[0],200)
        self.assertEqual(self.handler('/api/qoj-plugin/import',{'uid':'ucup-team123','records':[]},'qoj-token').do_POST()[0],401)
        with app.connect_db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM luogu_plugin_tokens').fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM submissions WHERE platform='qoj'").fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT active FROM handles WHERE id=?',(self.qoj['id'],)).fetchone()[0],1)

    def test_qoj_normalization_and_numeric_scores(self):
        self.assertEqual(app.ADAPTERS['qoj'].normalize_handle('https://qoj.ac/user/profile/ucup-team123'),'ucup-team123')
        self.assertEqual(app.qoj_verdict('100'),'WA')
        self.assertEqual(app.qoj_verdict('100 ✓'),'AC')
        self.assertEqual(app.qoj_verdict('Time Limit Exceeded'),'TLE')
        with self.assertRaises(ValueError): app.qoj_verdict('NaN')
        with self.assertRaises(ValueError): app.ADAPTERS['qoj'].normalize_handle('bad/name')

    def test_qoj_never_uses_server_fetch(self):
        with app.connect_db() as conn:
            self.assertTrue(app.sync_handle_row(conn,self.qoj,force=True)['manual'])


if __name__ == '__main__':
    unittest.main()
