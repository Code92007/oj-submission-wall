#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787"))
TOKEN = os.environ.get("LUOGU_PROXY_TOKEN", "").strip()
UPSTREAM_COOKIE = os.environ.get("LUOGU_PROXY_UPSTREAM_COOKIE", "").strip()
UPSTREAM_CSRF_TOKEN = os.environ.get("LUOGU_PROXY_UPSTREAM_CSRF_TOKEN", "").strip()
TIMEOUT_SECONDS = int(os.environ.get("LUOGU_PROXY_TIMEOUT_SECONDS", "20"))
MAX_BODY_BYTES = int(os.environ.get("LUOGU_PROXY_MAX_BODY_BYTES", str(5 * 1024 * 1024)))
ALLOWED_HOSTS = {"www.luogu.com.cn", "luogu.com.cn"}
HEADER_ALLOWLIST = {
    "accept",
    "accept-language",
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
            return send_json(self, 200, {"ok": True, "app": "luogu-proxy"})
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
            url = str(payload.get("url") or "")
            if not allowed_url(url):
                return send_json(self, 400, {"ok": False, "error": "只允许代理洛谷 HTTPS URL"})

            raw_headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
            headers = {
                str(key): str(value)
                for key, value in raw_headers.items()
                if str(key).lower() in HEADER_ALLOWLIST and value is not None
            }
            header_keys = {key.lower() for key in headers}
            if UPSTREAM_COOKIE and "cookie" not in header_keys:
                headers["Cookie"] = UPSTREAM_COOKIE
            if UPSTREAM_CSRF_TOKEN and "x-csrf-token" not in header_keys:
                headers["X-CSRF-Token"] = UPSTREAM_CSRF_TOKEN
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                body = resp.read(MAX_BODY_BYTES + 1)
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
                    },
                )
        except urllib.error.HTTPError as exc:
            return send_json(self, 200, {"ok": False, "status": exc.code, "error": f"HTTP Error {exc.code}: {exc.reason}"})
        except Exception as exc:
            return send_json(self, 502, {"ok": False, "error": str(exc) or exc.__class__.__name__})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), LuoguProxyHandler)
    print(f"Luogu proxy listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
