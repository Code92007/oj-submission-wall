import json
import os
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import app
from cpc_integration import Integration
from photo_sso import handle, challenge, db_for


class Handler:
    command = 'GET'
    request_version = 'HTTP/1.1'
    def __init__(self, path, headers=None):
        self.path = path; self.headers = headers or {}; self.sent = {}
    def send_response(self, status): self.status = status
    def send_header(self, key, value): self.sent[key] = value
    def end_headers(self): pass
    def send_json(self, status, body): self.status, self.body = status, body
    def send_error_json(self, status, message): self.send_json(status, {'error': message})
    def send_html(self, status, body, headers=None): self.status, self.body = status, body


class PhotoSSOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        self.paths = patch.multiple(app, DATA_DIR=root, DB_PATH=root / 'db.sqlite', CACHE_DIR=root / 'cache', HTTP_CACHE_DIR=root / 'http')
        self.paths.start(); app.init_db(); self.service = Integration(app)
        self.env = patch.dict(os.environ, {'CPC_PHOTO_PUBLIC_URL': 'https://cpc.example', 'CPC_DLUT_URL': 'https://cpc.example', 'CPC_SYNC_TOKEN': 'secret', 'CPC_DLUT_AUTHORITY_ID': 'authority'})
        self.env.start()
        with app.connect_db() as db:
            self.owner = str(db.execute("insert into users(username,email,display_name,password_hash,created_at) values ('member','member@example.com','Member','hash',?)", (app.utcnow(),)).lastrowid)
            self.session = app.create_session(db, 'user', self.owner, 1)
        self.verifier = secrets.token_urlsafe(48)

    def tearDown(self):
        self.env.stop(); self.paths.stop(); self.temp.cleanup()

    def authorize(self, cookie=True):
        query = 'state=' + secrets.token_urlsafe(32) + '&code_challenge=' + challenge(self.verifier) + '&redirect_uri=https://evil.example'
        handler = Handler('/api/cpc/photos/authorize?' + query, {'Cookie': 'ojwall_session=' + self.session} if cookie else {})
        handle(handler, self.service)
        return handler

    def exchange(self, code, verifier=None, token='secret'):
        handler = Handler('/api/integration/v1/photos/exchange', {'Authorization': 'Bearer ' + token})
        handler.command = 'POST'
        with patch.object(app, 'read_json_body', return_value={'code': code, 'verifier': verifier or self.verifier}):
            handle(handler, self.service, post=True)
        return handler

    def test_anonymous_and_guest_cannot_issue_codes(self):
        self.assertIn('登录', self.authorize(False).body)
        with patch.object(app, 'get_current_principal', return_value={'type': 'guest', 'id': 'guest'}):
            self.assertNotIn('Location', self.authorize().sent)

    def test_bound_single_use_code_requires_server_token_and_pkce(self):
        auth = self.authorize()
        self.assertEqual(auth.status, 302)
        self.assertTrue(auth.sent['Location'].startswith('https://cpc.example/api/photos/callback?'))
        self.assertNotIn('code=', auth.requestline)
        code = parse_qs(urlsplit(auth.sent['Location']).query)['code'][0]
        self.assertEqual(self.exchange(code, token='wrong').status, 403)
        self.assertEqual(self.exchange(code, verifier=secrets.token_urlsafe(48)).status, 400)
        success = self.exchange(code)
        self.assertEqual(success.status, 200)
        self.assertEqual(success.body['authority_id'], self.service.authority)
        self.assertNotIn('email', success.body)
        self.assertEqual(self.exchange(code).status, 400)

    def test_logged_out_and_expired_codes_cannot_be_redeemed(self):
        code = parse_qs(urlsplit(self.authorize().sent['Location']).query)['code'][0]
        with app.connect_db() as db:
            app.delete_session(db, self.session)
        self.assertEqual(self.exchange(code).status, 400)
        with db_for(self.service) as db:
            db.execute('update cpc_photo_codes set expires=0')
        self.assertEqual(self.exchange(code).status, 400)


if __name__ == '__main__':
    unittest.main()
