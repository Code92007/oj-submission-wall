#!/usr/bin/env python3
from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import signal
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787"))
TOKEN = os.environ.get("LUOGU_PROXY_TOKEN", "").strip()
UPSTREAM_COOKIE = os.environ.get("LUOGU_PROXY_UPSTREAM_COOKIE", "").strip()
UPSTREAM_CSRF_TOKEN = os.environ.get("LUOGU_PROXY_UPSTREAM_CSRF_TOKEN", "").strip()
COOKIE_JAR_PATH = os.environ.get("LUOGU_PROXY_COOKIE_JAR_PATH", "/tmp/luogu-proxy-cookies.txt").strip()
BACKEND = os.environ.get("LUOGU_PROXY_BACKEND", "urllib").strip().lower()
TIMEOUT_SECONDS = int(os.environ.get("LUOGU_PROXY_TIMEOUT_SECONDS", "20"))
MAX_BODY_BYTES = int(os.environ.get("LUOGU_PROXY_MAX_BODY_BYTES", str(5 * 1024 * 1024)))
ALLOWED_HOSTS = {"www.luogu.com.cn", "luogu.com.cn"}
HEADER_ALLOWLIST = {
    "accept",
    "accept-language",
    "content-type",
    "cookie",
    "origin",
    "priority",
    "referer",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "user-agent",
    "x-csrf-token",
    "x-lentille-request",
    "x-luogu-type",
    "x-requested-with",
}


def make_cookie_jar():
    if COOKIE_JAR_PATH:
        jar = http.cookiejar.MozillaCookieJar(COOKIE_JAR_PATH)
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"failed to load cookie jar: {exc}", flush=True)
        return jar
    return http.cookiejar.CookieJar()


COOKIE_JAR = make_cookie_jar()
COOKIE_LOCK = threading.Lock()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIE_JAR))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Browser relay clients own their cookies and redirects. They must not inherit
# another client's cookies from the legacy proxy's shared cookie jar.
RELAY_OPENER = urllib.request.build_opener(NoRedirect())
BROWSER = None
if BACKEND == "browser":
    from luogu_browser import BrowserSession
    BROWSER = BrowserSession(os.environ.get("LUOGU_BROWSER_PROFILE", "/data/browser-profile"), TIMEOUT_SECONDS)


def save_cookie_jar() -> None:
    if isinstance(COOKIE_JAR, http.cookiejar.FileCookieJar) and COOKIE_JAR_PATH:
        try:
            COOKIE_JAR.save(ignore_discard=True, ignore_expires=True)
        except Exception as exc:
            print(f"failed to save cookie jar: {exc}", flush=True)


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0 or length > 64 * 1024:
        raise ValueError("请求体大小异常")
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def allowed_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in ALLOWED_HOSTS


class LuoguProxyHandler(BaseHTTPRequestHandler):
    server_version = "OJWallLuoguProxy/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def do_GET(self) -> None:
        if self.path == "/health":
            return send_json(self, 200, {"ok": True, "app": "luogu-proxy", "backend": BACKEND,
                                       "browserRelay": BACKEND == "urllib",
                                       **({"session": BROWSER.snapshot()} if BROWSER else {"cookies": len(COOKIE_JAR)})})
        return send_json(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if TOKEN:
            expected = f"Bearer {TOKEN}"
            if self.headers.get("Authorization", "") != expected:
                return send_json(self, 401, {"ok": False, "error": "unauthorized"})
        else:
            return send_json(self, 500, {"ok": False, "error": "LUOGU_PROXY_TOKEN is required"})

        try:
            payload = read_json_body(self)
            if BROWSER and payload.get("action") == "session":
                return send_json(self, 200, BROWSER.call(payload))
            url = str(payload.get("url") or "")
            if not allowed_url(url):
                return send_json(self, 400, {"ok": False, "error": "只允许代理洛谷 HTTPS URL"})
            if BROWSER:
                return send_json(self, 200, BROWSER.call(payload))

            raw_headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
            headers = {
                str(key): str(value)
                for key, value in raw_headers.items()
                if str(key).lower() in HEADER_ALLOWLIST and value is not None
            }
            header_keys = {key.lower() for key in headers}
            relay = bool(payload.get("browserRelay"))
            method = str(payload.get("method") or "GET").upper()
            if method not in {"GET", "POST", "HEAD", "OPTIONS"}:
                return send_json(self, 400, {"ok": False, "error": "不支持的代理请求方法"})
            request_body = None
            if payload.get("bodyBase64") is not None:
                request_body = base64.b64decode(str(payload["bodyBase64"]), validate=True)
            if UPSTREAM_COOKIE and "cookie" not in header_keys and not relay:
                headers["Cookie"] = UPSTREAM_COOKIE
            if UPSTREAM_CSRF_TOKEN and "x-csrf-token" not in header_keys and not relay:
                headers["X-CSRF-Token"] = UPSTREAM_CSRF_TOKEN
            req = urllib.request.Request(url, headers=headers, data=request_body, method=method)
            opener = RELAY_OPENER if relay else OPENER
            with COOKIE_LOCK, opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
                body = resp.read(MAX_BODY_BYTES + 1)
                save_cookie_jar()
                if len(body) > MAX_BODY_BYTES:
                    return send_json(self, 502, {"ok": False, "error": "洛谷响应过大"})
                return send_json(
                    self,
                    200,
                    {
                        "ok": True,
                        "status": resp.status,
                        "contentType": resp.headers.get("content-type", ""),
                        "bodyBase64": base64.b64encode(body).decode("ascii"),
                        "responseHeaders": list(resp.headers.items()) if relay else [],
                    },
                )
        except urllib.error.HTTPError as exc:
            save_cookie_jar()
            if payload.get("browserRelay"):
                body = exc.read(MAX_BODY_BYTES + 1)
                if len(body) > MAX_BODY_BYTES:
                    return send_json(self, 502, {"ok": False, "error": "洛谷响应过大"})
                return send_json(self, 200, {"ok": exc.code < 400, "status": exc.code,
                    "error": f"HTTP Error {exc.code}: {exc.reason}",
                    "contentType": exc.headers.get("content-type", ""),
                    "bodyBase64": base64.b64encode(body).decode("ascii"),
                    "responseHeaders": list(exc.headers.items())})
            return send_json(self, 200, {"ok": False, "status": exc.code, "error": f"HTTP Error {exc.code}: {exc.reason}"})
        except Exception as exc:
            return send_json(self, 502, {"ok": False, "error": str(exc) or exc.__class__.__name__})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), LuoguProxyHandler)
    def stop_server(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    print(f"Luogu proxy listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if BROWSER:
            BROWSER.close()


if __name__ == "__main__":
    main()
