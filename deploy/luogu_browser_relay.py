"""Route a browser's Luogu traffic through the authenticated domestic relay."""
import base64
import json
import re
import time
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie


def browser_cookies(header_values, url):
    result = []
    hostname = urllib.parse.urlparse(url).hostname
    for value in header_values:
        parsed = SimpleCookie()
        try:
            parsed.load(value)
        except Exception:
            continue
        for name, item in parsed.items():
            domain = item["domain"] or hostname
            if domain.lstrip(".") not in {"luogu.com.cn", "www.luogu.com.cn"}:
                continue
            cookie = {"name": name, "value": item.value, "domain": domain, "path": item["path"] or "/",
                      "secure": bool(item["secure"]), "httpOnly": bool(item["httponly"])}
            if item["max-age"]:
                try:
                    age = int(item["max-age"])
                    cookie["expires"] = time.time() + age if age > 0 else 1
                except ValueError:
                    pass
            elif item["expires"]:
                try:
                    cookie["expires"] = max(1, parsedate_to_datetime(item["expires"]).timestamp())
                except (ValueError, TypeError, OverflowError):
                    pass
            if item["samesite"].lower() in {"strict", "lax", "none"}:
                cookie["sameSite"] = item["samesite"].capitalize()
            result.append(cookie)
    return result


def install_relay(context, relay_url, token, timeout_seconds):
    def handle(route):
        request = route.request
        payload = {"url": request.url, "method": request.method, "headers": request.all_headers(), "browserRelay": True}
        if request.post_data_buffer is not None:
            payload["bodyBase64"] = base64.b64encode(request.post_data_buffer).decode()
        try:
            call = urllib.request.Request(relay_url, data=json.dumps(payload).encode(),
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(call, timeout=timeout_seconds) as response:
                data = json.load(response)
            if data.get("bodyBase64") is None:
                # Old proxies cannot support a browser login or cookie renewal.
                route.abort("failed")
                return
            headers = data.get("responseHeaders")
            if not isinstance(headers, list):
                route.abort("failed")
                return
            cookies = browser_cookies([str(value) for name, value in headers if name.lower() == "set-cookie"], request.url)
            if cookies:
                context.add_cookies(cookies)
            response_headers = {str(name): str(value) for name, value in headers
                if name.lower() not in {"set-cookie", "content-length", "transfer-encoding", "connection"}}
            route.fulfill(status=int(data.get("status") or 200), headers=response_headers,
                          body=base64.b64decode(data["bodyBase64"]))
        except Exception:
            # Never log browser request bodies, cookies, or the relay token.
            route.abort("failed")
    context.route(re.compile(r"https://(?:www\.)?luogu\.com\.cn/.*"), handle)
