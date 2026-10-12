import copy
import base64
import json
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import app
from deploy.luogu_browser import BrowserSession, login_required
from deploy.luogu_browser_relay import browser_cookies, install_relay
from deploy import luogu_proxy


class SharedSyncTest(unittest.TestCase):
    def setUp(self):
        self.saved = (app.SYNC_RUNNING_JOB, app.SYNC_PENDING_JOBS, app.SYNC_JOB_COUNTER)
        app.SYNC_RUNNING_JOB = None
        app.SYNC_PENDING_JOBS = []
        app.SYNC_QUEUE_EVENT.clear()

    def tearDown(self):
        app.SYNC_RUNNING_JOB, app.SYNC_PENDING_JOBS, app.SYNC_JOB_COUNTER = self.saved
        app.SYNC_QUEUE_EVENT.clear()

    def test_second_user_joins_running_refresh_without_mutating_it(self):
        app.enqueue_sync_job(principal={"type": "user", "id": "a"}, force=True,
                             luogu_auth={"cookie": "original"})
        first = app.pop_next_sync_job(0)
        before = copy.deepcopy(first)
        joined = app.enqueue_sync_job(principal={"type": "user", "id": "b"}, force=True,
                                      luogu_auth={"cookie": "replacement"})
        self.assertTrue(joined["alreadyRunning"])
        self.assertEqual(first, before)
        self.assertEqual(app.SYNC_PENDING_JOBS, [])

    def test_concurrent_users_create_only_one_pending_refresh(self):
        barrier = threading.Barrier(8)
        results = []
        def enqueue(index):
            barrier.wait()
            results.append(app.enqueue_sync_job(principal={"type": "user", "id": str(index)}, force=True))
        threads = [threading.Thread(target=enqueue, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(app.SYNC_PENDING_JOBS), 1)
        self.assertEqual(sum(bool(result.get("alreadyQueued")) for result in results), 7)

    def test_dequeue_reserves_running_job_before_execution(self):
        app.enqueue_sync_job(principal={"type": "user", "id": "a"}, force=True)
        job = app.pop_next_sync_job(0)
        self.assertIs(app.SYNC_RUNNING_JOB, job)
        self.assertTrue(app.enqueue_sync_job(principal={"type": "user", "id": "b"})["alreadyRunning"])

    def test_uncovered_full_refresh_and_guest_remain_queued(self):
        app.enqueue_sync_job(principal={"type": "user", "id": "a"}, force=True)
        app.pop_next_sync_job(0)
        self.assertTrue(app.enqueue_sync_job(principal={"type": "user", "id": "b"}, full=True)["queued"])
        self.assertTrue(app.enqueue_sync_job(principal={"type": "guest", "id": "c"})["queued"])
        self.assertEqual(len(app.SYNC_PENDING_JOBS), 2)


class LuoguCatchupTest(unittest.TestCase):
    def test_capped_catchup_resumes_gap_after_new_records_shift_pages(self):
        adapter = app.LuoguAdapter()
        now = app.utcnow()
        watermark = now - 1000
        records = [{"remote_id": str(i), "submitted_at": watermark + 200 - i * 10} for i in range(1, 31)]
        adapter._previous_stats["1"] = {"recordSync": {"newestSubmitTime": watermark,
                                                       "historyComplete": True, "syncedAt": watermark}}
        seen = set()
        pages = []
        def fetch(uid, user, page):
            pages.append(page)
            return {"records": {"result": records[(page - 1) * 2:page * 2], "count": len(records), "perPage": 2}}
        with mock.patch.object(adapter, "_record_delay"), mock.patch.object(adapter, "_fetch_record_page", side_effect=fetch), \
                mock.patch.object(adapter, "_record_to_submission", side_effect=lambda uid, name, item: item), \
                mock.patch.object(app, "LUOGU_RECORD_RECENT_PAGES_PER_SYNC", 3), \
                mock.patch.object(app, "LUOGU_RECORD_INCREMENTAL_OVERLAP_SECONDS", 0):
            submissions, state = adapter._fetch_record_submissions("1", "1", "Alice", watermark)
            seen.update(item["remote_id"] for item in submissions)
            self.assertFalse(state["incrementalComplete"])
            self.assertEqual(state["newestSubmitTime"], watermark)
            self.assertEqual(state["syncedAt"], watermark)
            records[:0] = [{"remote_id": f"new{i}", "submitted_at": now - i} for i in range(6)]
            for _ in range(30):
                adapter._previous_stats["1"] = {"recordSync": state}
                submissions, state = adapter._fetch_record_submissions("1", "1", "Alice", now)
                seen.update(item["remote_id"] for item in submissions)
                if state["incrementalComplete"] and state["newestSubmitTime"] == now:
                    break
            self.assertTrue(state["incrementalComplete"])
            self.assertEqual(state["newestSubmitTime"], now)
            expected = {item["remote_id"] for item in records if item["submitted_at"] >= watermark}
            self.assertTrue(expected.issubset(seen), expected - seen)
            self.assertNotIn("catchupPage", state)

    def test_unauthorized_does_not_retry_username_or_next_account(self):
        adapter = app.LuoguAdapter()
        error = app.LuoguSessionUnavailable("登录会话失效", 300)
        with mock.patch.object(app, "proxy_http_get", side_effect=error) as fetch:
            for uid in ["1", "2"]:
                with self.assertRaises(app.LuoguSessionUnavailable):
                    adapter._fetch_record_page(uid, "Alice", 1)
            self.assertEqual(fetch.call_count, 1)

    def test_history_only_cli_still_advances_backfill(self):
        adapter = app.LuoguAdapter()
        now = app.utcnow()
        adapter._previous_stats["1"] = {"recordSync": {"nextBackfillPage": 3, "newestSubmitTime": now, "historyComplete": False}}
        def fetch(uid, user, page):
            return {"records": {"result": [{"remote_id": str(page), "submitted_at": now - page * 100}], "count": 20, "perPage": 2}}
        with mock.patch.object(adapter, "_record_delay"), mock.patch.object(adapter, "_fetch_record_page", side_effect=fetch), \
                mock.patch.object(adapter, "_record_to_submission", side_effect=lambda uid, name, item: item), \
                mock.patch.object(app, "LUOGU_RECORD_RECENT_PAGES_PER_SYNC", 0), \
                mock.patch.object(app, "LUOGU_RECORD_BACKFILL_PAGES_PER_SYNC", 2):
            submissions, state = adapter._fetch_record_submissions("1", "1", "Alice", now - 1000)
        self.assertEqual(state["pagesFetched"], [3, 4])
        self.assertEqual(state["nextBackfillPage"], 5)
        self.assertEqual(state["newestSubmitTime"], now)
        self.assertFalse(state["incrementalComplete"])
        self.assertNotIn("catchupPage", state)

    def test_record_failure_preserves_success_time_in_database(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(app, "DB_PATH", Path(directory) / "test.db"):
            app.init_db()
            old_time = app.utcnow() - 10000
            with app.connect_db() as conn:
                conn.execute("INSERT INTO handles(owner_type,owner_id,platform,handle,active,created_at,last_sync_at) VALUES('user','1','luogu','123',1,?,?)", (old_time, old_time))
                row = conn.execute("SELECT * FROM handles").fetchone()
                adapter = app.LuoguAdapter()
                with mock.patch.dict(app.ADAPTERS, {"luogu": adapter}), \
                        mock.patch.object(app, "LUOGU_BROWSER_IMPORT", False), \
                        mock.patch.object(adapter, "fetch_submissions", return_value=[]), \
                        mock.patch.object(adapter, "fetch_profile_stats", return_value={"source": "luogu-profile+record-list", "_warning": "洛谷记录页同步失败", "recordSync": {"lastError": "401"}}), \
                        mock.patch.object(adapter, "fetch_contests", return_value=[]):
                    result = app.sync_handle_row(conn, row, force=True)
                current = conn.execute("SELECT * FROM handles").fetchone()
                self.assertEqual(current["last_sync_at"], old_time)
                self.assertIn("同步失败", current["last_error"])
                self.assertTrue(result["partial"])


class BrowserSessionTest(unittest.TestCase):
    def test_proxy_upgrade_forwards_post_and_keeps_relay_cookies_isolated(self):
        handler = luogu_proxy.LuoguProxyHandler.__new__(luogu_proxy.LuoguProxyHandler)
        handler.headers = {"Authorization": "Bearer fake-token"}
        payload = {"url": "https://www.luogu.com.cn/auth/login", "method": "POST", "browserRelay": True,
                   "headers": {"Content-Type": "application/json"}, "bodyBase64": base64.b64encode(b'{}').decode()}
        response = mock.Mock()
        response.status = 200
        response.headers.get.return_value = "application/json"
        response.headers.items.return_value = [("Set-Cookie", "session=new; Path=/")]
        response.read.return_value = b'{"ok":true}'
        with mock.patch.object(luogu_proxy, "TOKEN", "fake-token"), \
                mock.patch.object(luogu_proxy, "BROWSER", None), \
                mock.patch.object(luogu_proxy, "UPSTREAM_COOKIE", "other-client-cookie"), \
                mock.patch.object(luogu_proxy, "read_json_body", return_value=payload), \
                mock.patch.object(luogu_proxy, "send_json") as send, \
                mock.patch.object(luogu_proxy, "save_cookie_jar"), \
                mock.patch.object(luogu_proxy.RELAY_OPENER, "open") as relay, \
                mock.patch.object(luogu_proxy.OPENER, "open") as legacy:
            relay.return_value.__enter__.return_value = response
            handler.do_POST()
        request = relay.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, b'{}')
        self.assertFalse(request.has_header("Cookie"))
        legacy.assert_not_called()
        self.assertEqual(send.call_args.args[2]["responseHeaders"], response.headers.items.return_value)

    def test_domestic_relay_returns_updated_cookies_to_browser(self):
        context = mock.Mock()
        install_relay(context, "http://private-relay/", "fake-token", 10)
        handler = context.route.call_args.args[1]
        route = mock.Mock()
        route.request.url = "https://www.luogu.com.cn/auth/login"
        route.request.method = "POST"
        route.request.post_data_buffer = b'{"example":"test"}'
        route.request.all_headers.return_value = {"Content-Type": "application/json"}
        response = {"status": 302, "bodyBase64": base64.b64encode(b'').decode(),
                    "responseHeaders": [["Set-Cookie", "session=new; Path=/; HttpOnly; Secure; SameSite=None"], ["Location", "/"]]}
        with mock.patch("deploy.luogu_browser_relay.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as send:
            handler(route)
        payload = json.loads(send.call_args.args[0].data)
        self.assertEqual(payload["method"], "POST")
        self.assertEqual(base64.b64decode(payload["bodyBase64"]), route.request.post_data_buffer)
        self.assertTrue(payload["browserRelay"])
        cookie = context.add_cookies.call_args.args[0][0]
        self.assertTrue(cookie["httpOnly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["sameSite"], "None")
        self.assertEqual(route.fulfill.call_args.kwargs["status"], 302)
        self.assertEqual(route.fulfill.call_args.kwargs["headers"], {"Location": "/"})

    def test_cookie_relay_limits_domain_and_preserves_deletion(self):
        cookies = browser_cookies(["session=; Max-Age=0; Path=/", "bad=value; Domain=example.com"], "https://www.luogu.com.cn/")
        self.assertEqual(len(cookies), 1)
        self.assertLessEqual(cookies[0]["expires"], app.utcnow() + 1)

    def test_recovered_browser_queues_saved_gap_without_waiting_for_full_schedule(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(app, "DB_PATH", Path(directory) / "test.db"), \
                mock.patch.object(app, "LUOGU_PROXY_URL", "http://private-proxy/"), \
                mock.patch.object(app, "LUOGU_BROWSER_IMPORT", False), \
                mock.patch.object(app, "LUOGU_RECOVERY_QUEUED_AT", {}):
            app.init_db()
            with app.connect_db() as conn:
                conn.execute("INSERT INTO handles(owner_type,owner_id,platform,handle,active,created_at,stats_json) VALUES('user','123','luogu','456',1,0,?)",
                             (json.dumps({"recordSync": {"catchupPage": 4, "historyComplete": True}}),))
            def health(state):
                return io.BytesIO(json.dumps({"backend": "browser", "session": {"state": state}}).encode())
            with mock.patch.object(app.urllib.request, "urlopen", return_value=health("login_required")), \
                    mock.patch.object(app, "enqueue_sync_job") as enqueue:
                self.assertEqual(app.queue_luogu_recovery_once(), 0)
                enqueue.assert_not_called()
            with mock.patch.object(app.urllib.request, "urlopen", return_value=health("authenticated")), \
                    mock.patch.object(app, "enqueue_sync_job", return_value={"queued": True}) as enqueue:
                self.assertEqual(app.queue_luogu_recovery_once(), 1)
                self.assertEqual(enqueue.call_args.kwargs["principal"], {"type": "user", "id": "123"})
                self.assertTrue(enqueue.call_args.kwargs["force"])

    def test_static_cookie_and_user_agent_never_override_browser_session(self):
        browser = BrowserSession.__new__(BrowserSession)
        browser.timeout_seconds = 10
        page = mock.Mock()
        browser._fetch(page, "https://www.luogu.com.cn/record/list", {"Cookie": "stale", "User-Agent": "wrong", "X-CSRF-Token": "stale", "Accept": "application/json"})
        headers = page.evaluate.call_args.args[1]["headers"]
        self.assertEqual(headers, {"Accept": "application/json"})

    def test_detects_unauthorized_and_nested_login_response(self):
        self.assertTrue(login_required(401, ""))
        self.assertTrue(login_required(200, json.dumps({"data": {"currentTemplate": "login"}})))
        self.assertFalse(login_required(200, json.dumps({"template": "record.list"})))

    def test_session_probe_accepts_html_context_without_confusing_profile_user(self):
        from deploy.luogu_browser import parse_payload
        body = '<html><script type="application/json" id="lentille-context">' + json.dumps({"user": None, "data": {"user": {"uid": 1}}}) + '</script></html>'
        self.assertIsNone(parse_payload(body)["user"])
        body = body.replace('"user": null', '"user": {"uid": 123}')
        self.assertEqual(parse_payload(body)["user"]["uid"], 123)
        self.assertTrue(login_required(200, '<script id="lentille-context">{"template":"login"}</script>'))


if __name__ == "__main__":
    unittest.main()
