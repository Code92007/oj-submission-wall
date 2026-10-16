import concurrent.futures
import io
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import app
import account_recovery as recovery


class AccountRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        settings = patch.multiple(app, DB_PATH=Path(self.tmp.name)/"wall.db",
                                  PUBLIC_BASE_URL="https://wall.example.org", APP_ENV="production")
        settings.start()
        self.addCleanup(settings.stop)
        self.mail = patch.object(app, "send_email", return_value=True).start()
        self.configured = patch.object(app, "smtp_configured", return_value=True).start()
        self.addCleanup(patch.stopall)
        app.init_db()
        with app.connect_db() as conn:
            conn.execute("""INSERT INTO users(id,username,email,display_name,password_hash,created_at)
                VALUES(1,'river','river@local.ojwall.invalid','River',?,?)""",
                (app.password_hash("old-password"), app.utcnow()))
            conn.execute("""INSERT INTO users(id,username,email,display_name,password_hash,created_at)
                VALUES(2,'other','other@example.org','Other',?,?)""",
                (app.password_hash("other-password"), app.utcnow()))
            self.session = app.create_session(conn, "user", "1", 30)
            self.other_session = app.create_session(conn, "user", "2", 30)

    def handler(self, path, data=None, session=None):
        handler = object.__new__(app.AppHandler)
        handler.path = path
        payload = json.dumps(data or {}).encode()
        handler.headers = {"Content-Length": str(len(payload)), "Host": "attacker.example.org"}
        if session:
            handler.headers["Cookie"] = f"{app.SESSION_COOKIE}={session}"
        handler.client_address = ("127.0.0.1", 12345)
        handler.rfile = io.BytesIO(payload)
        def respond(status, body, **kwargs):
            handler.response = (status, body, kwargs)
            return handler.response
        handler.send_json = respond
        handler.send_error_json = lambda status, message: respond(status, {"ok": False, "error": message})
        return handler

    def post(self, path, data=None, session=None):
        handler = self.handler(path, data, session)
        handler.do_POST()
        return handler.response

    def get(self, path, session=None):
        handler = self.handler(path, session=session)
        handler.do_GET()
        return handler.response

    def user(self):
        with app.connect_db() as conn:
            return conn.execute("SELECT * FROM users WHERE id=1").fetchone()

    def mailed_token(self):
        content = self.mail.call_args.args[2]
        url = re.search(r"https://\S+", content).group()
        parsed = urlsplit(url)
        self.assertEqual(parsed.netloc, "wall.example.org")
        self.assertFalse(parsed.query)
        return parse_qs(parsed.fragment)["token"][0]

    def bind_and_verify(self):
        response = self.post("/api/auth/bind-email", {"email": "River@Example.org", "password": "old-password"}, self.session)
        self.assertEqual(response[0], 200)
        token = self.mailed_token()
        self.assertEqual(self.post("/api/auth/verify-email", {"token": token})[0], 200)
        return token

    def request_reset(self):
        self.assertEqual(self.post("/api/auth/forgot-password", {"username": "RIVER", "email": "RIVER@EXAMPLE.ORG"})[0], 200)
        return self.mailed_token()

    def test_binding_requires_login_and_current_password_and_keeps_email_private(self):
        data = {"email": "river@example.org", "password": "wrong"}
        self.assertEqual(self.post("/api/auth/bind-email", data)[0], 401)
        self.assertEqual(self.post("/api/auth/bind-email", data, self.session)[0], 400)
        self.assertTrue(self.user()["email"].endswith(".invalid"))
        self.mail.assert_not_called()
        self.assertEqual(self.get("/api/me/email")[0], 401)
        self.assertEqual(self.get("/api/me/email", session=self.other_session)[1]["email"], "other@example.org")
        self.assertNotIn("email", app.get_current_principal(self.handler("/", session=self.session)))
        self.assertNotIn("river@example.org", json.dumps(app.build_overview_from_db(None)))

    def test_binding_verifies_email_with_hashed_single_use_token(self):
        response = self.post("/api/auth/bind-email", {"email": "River@Example.org", "password": "old-password"}, self.session)
        self.assertEqual(response[0], 200)
        token = self.mailed_token()
        with app.connect_db() as conn:
            row = conn.execute("SELECT * FROM account_recovery_tokens").fetchone()
            self.assertEqual(row["token_hash"], app.sha256_hex(token))
            self.assertNotIn(token, json.dumps(dict(row)))
        self.assertIsNone(self.user()["email_verified_at"])
        self.assertEqual(self.post("/api/auth/verify-email", {"token": token})[0], 200)
        self.assertEqual(self.user()["email"], "river@example.org")
        self.assertIsNotNone(self.user()["email_verified_at"])
        self.assertEqual(self.post("/api/auth/verify-email", {"token": token})[0], 400)

    def test_reset_changes_password_revokes_only_owner_sessions_and_cannot_replay(self):
        self.bind_and_verify()
        token = self.request_reset()
        self.assertEqual(self.post("/api/auth/reset-password", {"token": token, "password": "new-password"})[0], 200)
        self.assertTrue(app.verify_password("new-password", self.user()["password_hash"]))
        self.assertFalse(app.verify_password("old-password", self.user()["password_hash"]))
        self.assertIsNone(app.get_current_principal(self.handler("/", session=self.session)))
        self.assertIsNotNone(app.get_current_principal(self.handler("/", session=self.other_session)))
        self.assertEqual(self.post("/api/auth/reset-password", {"token": token, "password": "another-password"})[0], 400)
        self.assertEqual(self.post("/api/auth/login", {"username": "river", "password": "new-password"})[0], 200)

    def test_unknown_wrong_and_unverified_email_have_identical_reset_response(self):
        results = [self.post("/api/auth/forgot-password", {"username": username, "email": email})[:2]
                   for username, email in [("missing", "missing@example.org"), ("river", "river@example.org"), ("other", "wrong@example.org")]]
        self.assertTrue(all(result == results[0] for result in results))
        self.mail.assert_not_called()

    def test_expired_wrong_purpose_and_old_reset_links_are_rejected(self):
        bind_token = self.bind_and_verify()
        token = self.request_reset()
        self.assertEqual(self.post("/api/auth/verify-email", {"token": token})[0], 400)
        self.assertEqual(self.post("/api/auth/reset-password", {"token": bind_token, "password": "new-password"})[0], 400)
        with app.connect_db() as conn:
            conn.execute("UPDATE account_recovery_tokens SET expires_at=?", (app.utcnow(),))
        self.assertEqual(self.post("/api/auth/reset-password", {"token": token, "password": "new-password"})[0], 400)
        self.assertTrue(app.verify_password("old-password", self.user()["password_hash"]))

    def test_new_request_invalidates_previous_reset_and_mail_is_throttled(self):
        self.bind_and_verify()
        token = self.request_reset()
        count = self.mail.call_count
        self.request_reset()
        self.assertEqual(self.mail.call_count, count)
        with patch.object(app, "utcnow", return_value=app.utcnow()+61):
            new_token = self.request_reset()
        self.assertNotEqual(token, new_token)
        self.assertEqual(self.post("/api/auth/reset-password", {"token": token, "password": "new-password"})[0], 400)

    def test_editing_email_clears_verification_and_invalidates_reset(self):
        self.bind_and_verify()
        token = self.request_reset()
        result = self.post("/api/auth/bind-email", {"email": "new@example.org", "password": "old-password"}, self.session)
        self.assertEqual(result[0], 200)
        self.assertEqual(self.user()["email"], "new@example.org")
        self.assertIsNone(self.user()["email_verified_at"])
        self.assertEqual(self.post("/api/auth/reset-password", {"token": token, "password": "new-password"})[0], 400)

    def test_email_can_be_saved_without_smtp_then_verified_later(self):
        self.configured.return_value = False
        result = self.post("/api/auth/bind-email", {"email": "river@example.org", "password": "old-password"}, self.session)
        self.assertEqual(result[0], 200)
        self.assertIn("邮箱已保存", result[1]["message"])
        self.assertEqual(self.user()["email"], "river@example.org")
        self.assertIsNone(self.user()["email_verified_at"])
        self.mail.assert_not_called()
        self.assertEqual(self.post("/api/auth/forgot-password", {"username": "river", "email": "river@example.org"})[0], 503)
        self.configured.return_value = True
        self.bind_and_verify()

    def test_duplicate_email_and_header_injection_are_rejected(self):
        for email, status in [("OTHER@example.org", 409), ("x@example.org\r\nBcc: x@example.org", 400), ("x@local.ojwall.invalid", 400)]:
            self.assertEqual(self.post("/api/auth/bind-email", {"email": email, "password": "old-password"}, self.session)[0], status)
        self.assertTrue(self.user()["email"].endswith(".invalid"))
        self.mail.assert_not_called()

    def test_failed_password_attempts_are_counted_even_without_db_mutation(self):
        for _ in range(5):
            self.assertEqual(self.post("/api/auth/bind-email", {"email": "river@example.org", "password": "wrong"}, self.session)[0], 400)
        self.assertEqual(self.post("/api/auth/bind-email", {"email": "river@example.org", "password": "old-password"}, self.session)[0], 429)

    def test_smtp_failure_deletes_undelivered_tokens(self):
        self.mail.return_value = False
        result = self.post("/api/auth/bind-email", {"email": "river@example.org", "password": "old-password"}, self.session)
        self.assertEqual(result[0], 503)
        with app.connect_db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM account_recovery_tokens").fetchone()[0], 0)
        self.mail.return_value = True
        self.bind_and_verify()
        self.mail.return_value = False
        self.assertEqual(self.post("/api/auth/forgot-password", {"username": "river", "email": "river@example.org"})[1]["message"], recovery.RESET_MESSAGE)
        with app.connect_db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM account_recovery_tokens").fetchone()[0], 0)

    def test_registration_email_is_optional_saved_unverified_and_can_send_verification(self):
        self.configured.return_value = False
        response = self.post("/api/auth/register", {"username": "new-user", "password": "new-password", "email": "New@Example.org"})
        self.assertEqual(response[0], 201)
        with app.connect_db() as conn:
            row = conn.execute("SELECT email, email_verified_at FROM users WHERE username='new-user'").fetchone()
            self.assertEqual(row["email"], "new@example.org")
            self.assertIsNone(row["email_verified_at"])
        self.mail.assert_not_called()
        self.assertEqual(self.post("/api/auth/register", {"username": "no-email", "password": "new-password"})[0], 201)
        self.configured.return_value = True
        self.assertEqual(self.post("/api/auth/register", {"username": "with-mail", "password": "new-password", "email": "mail@example.org"})[0], 201)
        self.assertEqual(self.post("/api/auth/verify-email", {"token": self.mailed_token()})[0], 200)
        self.assertEqual(self.post("/api/auth/register", {"username": "duplicate", "password": "new-password", "email": "MAIL@example.org"})[0], 400)

    def test_migration_does_not_trust_legacy_verified_flag_or_replace_password(self):
        before = self.user()["password_hash"]
        with app.connect_db() as conn:
            conn.execute("UPDATE users SET verified=1, email='legacy@example.org' WHERE id=1")
        app.init_db()
        self.assertIsNone(self.user()["email_verified_at"])
        self.assertEqual(self.user()["password_hash"], before)

    def test_two_simultaneous_resets_only_allow_one_success(self):
        self.bind_and_verify()
        token = self.request_reset()
        barrier = threading.Barrier(2)
        password_hash = app.password_hash
        def hash_together(password):
            barrier.wait(timeout=5)
            return password_hash(password)
        with patch.object(app, "password_hash", side_effect=hash_together), concurrent.futures.ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda password: self.post("/api/auth/reset-password", {"token": token, "password": password})[0], ["new-password-a", "new-password-b"]))
        self.assertEqual(sorted(responses), [200, 400])

    def test_mail_configuration_never_uses_incoming_host_or_logs_link_secrets(self):
        with patch.object(app, "PUBLIC_BASE_URL", "http://wall.example.org"):
            self.assertEqual(self.post("/api/auth/forgot-password", {"username": "river", "email": "river@example.org"})[0], 503)
        # Exercise the real SMTP helper rather than the mock used in endpoint tests.
        self.configured.return_value = True
        with patch.dict(app.os.environ, {"SMTP_HOST": "smtp.example.org", "SMTP_PORT": "465", "SMTP_USER": "mail@example.org", "SMTP_FROM": "", "SMTP_PASSWORD": "secret"}), \
                patch.object(app.smtplib, "SMTP_SSL") as smtp:
            self.assertTrue(AccountRecoveryTests.real_send_email("river@example.org", "Subject", "token-secret"))
            smtp.return_value.__enter__.return_value.send_message.assert_called_once()
            message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertEqual(message["From"], "mail@example.org")
        with patch.object(app.smtplib, "SMTP", side_effect=RuntimeError("token-secret")), \
                patch.dict(app.os.environ, {"SMTP_PORT": "587"}), patch("builtins.print") as output:
            self.assertFalse(AccountRecoveryTests.real_send_email("river@example.org", "Subject", "token-secret"))
            self.assertNotIn("token-secret", str(output.call_args_list))


AccountRecoveryTests.real_send_email = staticmethod(app.send_email)


if __name__ == "__main__":
    unittest.main()
