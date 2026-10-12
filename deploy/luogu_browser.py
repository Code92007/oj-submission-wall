"""A single-threaded persistent browser shared by the private Luogu proxy.

Browser APIs stay on their owning thread. Callers only exchange plain dicts.
The same visible browser can be logged in through the local VNC console.
"""
from __future__ import annotations

import base64
import concurrent.futures
import json
from html.parser import HTMLParser
import os
import queue
import threading
import time
from pathlib import Path

ORIGIN = "https://www.luogu.com.cn"


def parse_payload(body: str) -> dict:
    try:
        value = json.loads(body)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        # Luogu may return HTML even for content-only requests. Its embedded
        # context contains the same top-level session user as the JSON API.
        class ContextParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.active = False
                self.parts = []

            def handle_starttag(self, tag, attrs):
                if tag == "script" and dict(attrs).get("id") == "lentille-context":
                    self.active = True

            def handle_endtag(self, tag):
                if tag == "script":
                    self.active = False

            def handle_data(self, data):
                if self.active:
                    self.parts.append(data)

        parser = ContextParser()
        parser.feed(body or "")
        try:
            value = json.loads("".join(parser.parts))
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}


def login_required(status: int, body: str) -> bool:
    payload = parse_payload(body)
    nested = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    template = payload.get("template") or payload.get("currentTemplate") or nested.get("currentTemplate")
    return status == 401 or str(template or "").lower() == "login"


class BrowserSession:
    def __init__(self, profile_path: str, timeout_seconds: int = 20):
        self.profile_path = Path(profile_path)
        self.timeout_seconds = timeout_seconds
        self.jobs = queue.Queue(maxsize=32)
        self.status = {"state": "starting", "checkedAt": None}
        self.status_lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, name="luogu-browser", daemon=True)
        self.thread.start()
        self.jobs.put(({"action": "session"}, concurrent.futures.Future()))

    def snapshot(self):
        with self.status_lock:
            return dict(self.status)

    def _set_status(self, state, **extra):
        with self.status_lock:
            self.status = {"state": state, "checkedAt": int(time.time()), **extra}

    def call(self, payload):
        future = concurrent.futures.Future()
        try:
            self.jobs.put_nowait((payload, future))
        except queue.Full:
            return {"ok": False, "status": 503, "error": "洛谷浏览器繁忙，请稍后重试"}
        try:
            return future.result(timeout=self.timeout_seconds * 3 + 15)
        except concurrent.futures.TimeoutError:
            future.cancel()
            return {"ok": False, "status": 504, "error": "洛谷浏览器请求超时"}

    def close(self):
        self.call({"action": "close"})
        self.thread.join(timeout=5)

    def _fetch(self, page, url, headers):
        # Never replay the main site's static Cookie or impersonated browser UA.
        # Chromium owns cookies, redirects, CSRF and the actual browser headers.
        headers = {k: v for k, v in headers.items() if k.lower() in {"accept", "x-luogu-type", "x-requested-with", "x-lentille-request"}}
        return page.evaluate("""async ({url, headers, timeout}) => {
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
            if (csrf) headers['X-CSRF-Token'] = csrf;
            const response = await fetch(url, {headers, credentials: 'include',
                signal: AbortSignal.timeout(timeout)});
            return {status: response.status, body: await response.text(),
                contentType: response.headers.get('content-type') || ''};
        }""", {"url": url, "headers": headers, "timeout": self.timeout_seconds * 1000})

    def _probe(self, page, context):
        if not page.url.startswith(ORIGIN):
            page.goto(ORIGIN, wait_until="domcontentloaded", timeout=self.timeout_seconds * 1000)
        result = self._fetch(page, ORIGIN + "/?_contentOnly=1", {"Accept": "application/json"})
        payload = parse_payload(result["body"])
        user = payload.get("user")
        if result["status"] == 403:
            self._set_status("blocked", retryAfterSeconds=900)
        elif result["status"] == 200 and isinstance(user, dict) and (user.get("uid") or user.get("id")):
            self._set_status("authenticated")
        elif (result["status"] == 200 and "user" in payload) or login_required(result["status"], result["body"]):
            self._set_status("login_required", retryAfterSeconds=60)
        else:
            self._set_status("unavailable", retryAfterSeconds=60)
        self._persist(context)
        return self.snapshot()

    def _persist(self, context):
        # Save replacements atomically without logging any credential values.
        state_path = self.profile_path / "session-state.json"
        temp_path = self.profile_path / "session-state.tmp"
        context.storage_state(path=str(temp_path))
        temp_path.chmod(0o600)
        temp_path.replace(state_path)

    def _handle(self, payload, page, context):
        status = self.snapshot()
        age = time.time() - (status.get("checkedAt") or 0)
        if payload.get("action") == "session":
            if age >= 60 or status["state"] == "starting":
                status = self._probe(page, context)
            return {"ok": True, "backend": "browser", "session": status}
        url = payload["url"]
        is_record = "/record/list" in url
        if is_record:
            if age >= status.get("retryAfterSeconds", 60) or status["state"] == "starting":
                status = self._probe(page, context)
            if status["state"] != "authenticated":
                return {"ok": False, "status": 401 if status["state"] == "login_required" else 503,
                        "sessionRequired": status["state"] == "login_required", "session": status,
                        "error": "洛谷登录会话失效，请在代理浏览器完成登录；程序会自动检测恢复并补抓" if status["state"] == "login_required" else "洛谷会话暂不可用，已暂停记录页请求"}
        result = self._fetch(page, url, payload.get("headers") or {})
        self._persist(context)
        if login_required(result["status"], result["body"]):
            self._set_status("login_required", retryAfterSeconds=60)
            return {"ok": False, "status": 401, "sessionRequired": True,
                    "session": self.snapshot(), "error": "洛谷登录会话失效，记录同步已暂停；恢复后自动补抓"}
        if result["status"] >= 400:
            if result["status"] == 403:
                self._set_status("blocked", retryAfterSeconds=900)
            return {"ok": False, "status": result["status"], "session": self.snapshot(),
                    "error": f"洛谷上游 HTTP {result['status']}"}
        return {"ok": True, "status": result["status"], "contentType": result["contentType"],
                "bodyBase64": base64.b64encode(result["body"].encode()).decode(), "backend": "browser"}

    def _run(self):
        context = page = playwright = None
        while True:
            try:
                payload, future = self.jobs.get(timeout=30)
            except queue.Empty:
                # Probe periodically so a manual login is noticed without a
                # refresh click, and Chromium receives refreshed cookies.
                if page is not None:
                    status = self.snapshot()
                    if time.time() - (status.get("checkedAt") or 0) >= status.get("retryAfterSeconds", 300):
                        try:
                            self._probe(page, context)
                        except Exception:
                            self._set_status("unavailable", retryAfterSeconds=60)
                continue
            if not future.set_running_or_notify_cancel():
                continue
            try:
                if payload.get("action") == "close":
                    if context is not None:
                        self._persist(context)
                        context.close()
                    if playwright is not None:
                        playwright.stop()
                    future.set_result({"ok": True})
                    return
                if context is None:
                    from playwright.sync_api import sync_playwright
                    self.profile_path.mkdir(parents=True, exist_ok=True, mode=0o700)
                    playwright = sync_playwright().start()
                    context = playwright.chromium.launch_persistent_context(
                        str(self.profile_path), headless=os.environ.get("LUOGU_BROWSER_HEADLESS", "false").lower() == "true",
                        locale="zh-CN", viewport={"width": 1280, "height": 900},
                        channel=os.environ.get("LUOGU_BROWSER_CHANNEL") or None,
                        args=["--disable-dev-shm-usage"],
                    )
                    relay_url = os.environ.get("LUOGU_BROWSER_RELAY_URL", "").strip()
                    if relay_url:
                        from luogu_browser_relay import install_relay
                        relay_token = os.environ.get("LUOGU_BROWSER_RELAY_TOKEN", "").strip()
                        if not relay_token:
                            raise RuntimeError("Browser relay token is required")
                        install_relay(context, relay_url, relay_token, self.timeout_seconds)
                    saved_state = self.profile_path / "session-state.json"
                    if saved_state.exists() and not context.cookies():
                        try:
                            context.add_cookies(json.loads(saved_state.read_text()).get("cookies", []))
                        except (ValueError, OSError):
                            pass
                    page = context.pages[0] if context.pages else context.new_page()
                    page.goto(ORIGIN, wait_until="domcontentloaded", timeout=self.timeout_seconds * 1000)
                future.set_result(self._handle(payload, page, context))
            except Exception as exc:
                # The browser's raw exception may contain URLs or credentials.
                self._set_status("unavailable", retryAfterSeconds=60)
                future.set_result({"ok": False, "status": 503, "session": self.snapshot(),
                                   "error": "洛谷浏览器暂不可用：" + type(exc).__name__})
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass
                if playwright is not None:
                    try:
                        playwright.stop()
                    except Exception:
                        pass
                context = page = playwright = None
