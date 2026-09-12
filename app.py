#!/usr/bin/env python3
from __future__ import annotations
import base64
import argparse
import contextlib
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import random
import re
import secrets
import socket
import smtplib
import sqlite3
import ssl
import sys
import threading
import time
import traceback
import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


APP_NAME = "OJ Submission Wall"
ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
DB_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "ojwall.sqlite3")).resolve()
CACHE_DIR = Path(os.environ.get("CACHE_DIR", DATA_DIR / "cache")).resolve()
HTTP_CACHE_DIR = CACHE_DIR / "http"
CODEFORCES_STANDINGS_CACHE_DIR = CACHE_DIR / "codeforces-standings"
OVERVIEW_CACHE_PATH = CACHE_DIR / "overview.json"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
APP_ENV = os.environ.get("APP_ENV", "development").lower()
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")
SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", "900"))
SYNC_MIN_AGE_SECONDS = int(os.environ.get("SYNC_MIN_AGE_SECONDS", "120"))
SYNC_INCREMENTAL_OVERLAP_SECONDS = int(os.environ.get("SYNC_INCREMENTAL_OVERLAP_SECONDS", "7200"))
FETCH_LOOKBACK_DAYS = int(os.environ.get("FETCH_LOOKBACK_DAYS", "3650"))
FETCH_LIMIT = int(os.environ.get("FETCH_LIMIT", "1000"))
CODEFORCES_VP_RANKS_PER_SYNC = max(1, int(os.environ.get("CODEFORCES_VP_RANKS_PER_SYNC", "4")))
HTTP_TIMEOUT_SECONDS = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "15"))
HTTP_RETRY_COUNT = int(os.environ.get("HTTP_RETRY_COUNT", "2"))
HTTP_RETRY_BACKOFF_SECONDS = float(os.environ.get("HTTP_RETRY_BACKOFF_SECONDS", "0.8"))
DISPLAY_TZ_OFFSET_HOURS = int(os.environ.get("DISPLAY_TZ_OFFSET_HOURS", "8"))
DISPLAY_TZ = dt.timezone(dt.timedelta(hours=DISPLAY_TZ_OFFSET_HOURS), f"UTC{DISPLAY_TZ_OFFSET_HOURS:+03d}:00")
HISTORICAL_CACHE_AFTER_DAYS = int(os.environ.get("HISTORICAL_CACHE_AFTER_DAYS", "30"))
HISTORICAL_CACHE_TTL_SECONDS = int(os.environ.get("HISTORICAL_CACHE_TTL_SECONDS", str(3650 * 86400)))
OVERVIEW_CACHE_TTL_SECONDS = int(os.environ.get("OVERVIEW_CACHE_TTL_SECONDS", "20"))
OVERVIEW_FEED_LIMIT = int(os.environ.get("OVERVIEW_FEED_LIMIT", "1000"))
BATTLE_MEMORY_CACHE_LIMIT = max(8, int(os.environ.get("BATTLE_MEMORY_CACHE_LIMIT", "128")))
BATTLE_INITIAL_RATING = 1500
BATTLE_DUEL_K_FACTOR = 16
BATTLE_ABSOLUTE_K_FACTOR = 24
BATTLE_DUEL_DIRECTION_LIMIT = 0.8
BATTLE_MIN_RATING = 800
BATTLE_MAX_RATING = 2400
SESSION_COOKIE = "ojwall_session"
DEFAULT_TEAM_NAME = "未分组"
GUEST_TEAM_NAME = "游客"
USER_AGENT = os.environ.get(
    "OJ_USER_AGENT",
    "OJSubmissionWall/1.0 (+https://github.com/your-name/oj-submission-wall)",
)
LUOGU_USER_AGENT = os.environ.get(
    "LUOGU_USER_AGENT",
    f"OJSubmissionWall/1.0 (+{PUBLIC_BASE_URL})" if PUBLIC_BASE_URL else "OJSubmissionWall/1.0",
)
LUOGU_CF_CLEARANCE = os.environ.get("LUOGU_CF_CLEARANCE", "").strip()
LUOGU_COOKIE = os.environ.get("LUOGU_COOKIE", "").strip()
LUOGU_CSRF_TOKEN = os.environ.get("LUOGU_CSRF_TOKEN", "").strip()
LUOGU_PROXY_URL = os.environ.get("LUOGU_PROXY_URL", "").strip()
LUOGU_PROXY_TOKEN = os.environ.get("LUOGU_PROXY_TOKEN", "").strip()
LUOGU_THIRD_PARTY_FALLBACK = os.environ.get("LUOGU_THIRD_PARTY_FALLBACK", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DEFAULT_LUOGU_FALLBACK_URLS = (
    "https://api.jerryz.com.cn/practice?id={uid}",
    "https://api.jerryz.com.cn/api/practice?id={uid}",
    "https://api.jerryz.com.cn/shields?id={uid}",
    "https://api.jerryz.com.cn/api/shields?id={uid}",
    "https://luogu.wao3.cn/api/practice?id={uid}",
    "https://luogu.wao3.cn/api/shield?id={uid}",
)
LUOGU_FALLBACK_URLS = tuple(
    item.strip()
    for item in os.environ.get("LUOGU_FALLBACK_URLS", "").split(",")
    if item.strip()
) or DEFAULT_LUOGU_FALLBACK_URLS
LUOGU_RECORD_SYNC = os.environ.get("LUOGU_RECORD_SYNC", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LUOGU_RECORD_RECENT_PAGES_PER_SYNC = int(os.environ.get("LUOGU_RECORD_RECENT_PAGES_PER_SYNC", "10"))
LUOGU_RECORD_BACKFILL_PAGES_PER_SYNC = int(os.environ.get("LUOGU_RECORD_BACKFILL_PAGES_PER_SYNC", "8"))
LUOGU_RECORD_SLEEP_MIN_SECONDS = float(os.environ.get("LUOGU_RECORD_SLEEP_MIN_SECONDS", "0.4"))
LUOGU_RECORD_SLEEP_MAX_SECONDS = float(os.environ.get("LUOGU_RECORD_SLEEP_MAX_SECONDS", "1.4"))
LUOGU_RECORD_INCREMENTAL_OVERLAP_SECONDS = int(
    os.environ.get("LUOGU_RECORD_INCREMENTAL_OVERLAP_SECONDS", str(SYNC_INCREMENTAL_OVERLAP_SECONDS))
)
SMTP_PLACEHOLDERS = {
    "smtp.example.com",
    "noreply@example.com",
    "change-me",
    "your-email@example.com",
}


DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
HTTP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
CODEFORCES_STANDINGS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
SYNC_LOCK = threading.Lock()
SYNC_QUEUE_LOCK = threading.Lock()
SYNC_QUEUE_EVENT = threading.Event()
SYNC_PENDING_JOBS: list[dict] = []
SYNC_RUNNING_JOB: dict | None = None
SYNC_LAST_FINISHED_JOB: dict | None = None
SYNC_JOB_COUNTER = 0
OVERVIEW_CACHE_LOCK = threading.Lock()
CODEFORCES_STANDINGS_LOCK = threading.Lock()
OVERVIEW_MEMORY_CACHE: dict[tuple[str, str, str, int], tuple[int, dict]] = {}
BATTLE_MEMORY_CACHE: dict[tuple[str, ...], tuple[int, dict]] = {}
HTTP_STALE_HITS = threading.local()
LUOGU_REQUEST_AUTH = threading.local()
TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def utcnow() -> int:
    return int(time.time())


def utc_date_from_ts(ts: int) -> str:
    return dt.datetime.fromtimestamp(int(ts), DISPLAY_TZ).date().isoformat()


def iso_from_ts(ts: int | None) -> str | None:
    if not ts:
        return None
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def local_account_email(username: str) -> str:
    return f"{username}@local.ojwall.invalid"


def normalize_username(username: str) -> str:
    username = re.sub(r"\s+", "", username.strip()).lower()
    if not re.match(r"^[0-9a-zA-Z_\-\u4e00-\u9fff]{2,30}$", username):
        raise ValueError("用户名只能包含中文、字母、数字、下划线或短横线，长度 2-30 位")
    return username


def normalize_team_name(value: str | None, fallback: str = DEFAULT_TEAM_NAME) -> str:
    team_name = re.sub(r"\s+", " ", str(value or "").strip())[:40]
    return team_name or fallback


def normalize_display_name(value: str | None, fallback: str) -> str:
    display_name = re.sub(r"\s+", " ", str(value or "").strip())[:40]
    return display_name or fallback


def normalize_real_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:40]


def username_base(value: str) -> str:
    value = re.sub(r"\s+", "", value.strip()).lower()
    value = re.sub(r"[^0-9a-zA-Z_\-\u4e00-\u9fff]", "", value)
    if len(value) < 2:
        value = "user"
    return value[:24]


def json_dumps(data) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def http_cache_paths(url: str) -> tuple[Path, Path]:
    digest = sha256_hex(url)
    return HTTP_CACHE_DIR / f"{digest}.body", HTTP_CACHE_DIR / f"{digest}.json"


def read_http_cache(url: str, max_age_seconds: int | None = None) -> tuple[bytes, str, int] | None:
    body_path, meta_path = http_cache_paths(url)
    if not body_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text("utf-8"))
        fetched_at = int(meta.get("fetched_at") or 0)
        if max_age_seconds is not None and utcnow() - fetched_at > max_age_seconds:
            return None
        return body_path.read_bytes(), str(meta.get("content_type") or ""), fetched_at
    except Exception:
        return None


def write_http_cache(url: str, body: bytes, content_type: str) -> None:
    body_path, meta_path = http_cache_paths(url)
    tmp_body = body_path.with_name(f"{body_path.name}.{threading.get_ident()}.tmp")
    tmp_meta = meta_path.with_name(f"{meta_path.name}.{threading.get_ident()}.tmp")
    tmp_body.write_bytes(body)
    tmp_meta.write_text(
        json.dumps(
            {
                "url": url,
                "content_type": content_type,
                "fetched_at": utcnow(),
            },
            ensure_ascii=False,
        ),
        "utf-8",
    )
    os.replace(tmp_body, body_path)
    os.replace(tmp_meta, meta_path)


def has_cookie_header(headers: dict[str, str] | None) -> bool:
    return any(str(key).lower() == "cookie" and str(value).strip() for key, value in (headers or {}).items())


def reset_http_stale_hits() -> None:
    HTTP_STALE_HITS.items = []


def record_http_stale_hit(url: str, fetched_at: int) -> None:
    items = getattr(HTTP_STALE_HITS, "items", None)
    if items is None:
        items = []
        HTTP_STALE_HITS.items = items
    items.append({"url": url, "fetchedAt": fetched_at})


def http_stale_hits() -> list[dict]:
    return list(getattr(HTTP_STALE_HITS, "items", []))


def current_luogu_cookie() -> str:
    return str(getattr(LUOGU_REQUEST_AUTH, "cookie", "") or "").strip()


def current_luogu_csrf_token() -> str:
    return str(getattr(LUOGU_REQUEST_AUTH, "csrf_token", "") or "").strip()


@contextlib.contextmanager
def luogu_request_auth(auth: dict | None):
    previous_cookie = getattr(LUOGU_REQUEST_AUTH, "cookie", None)
    previous_csrf_token = getattr(LUOGU_REQUEST_AUTH, "csrf_token", None)
    if auth:
        LUOGU_REQUEST_AUTH.cookie = str(auth.get("cookie") or "").strip()
        LUOGU_REQUEST_AUTH.csrf_token = str(auth.get("csrfToken") or auth.get("csrf_token") or "").strip()
    try:
        yield
    finally:
        if previous_cookie is None:
            with contextlib.suppress(AttributeError):
                del LUOGU_REQUEST_AUTH.cookie
        else:
            LUOGU_REQUEST_AUTH.cookie = previous_cookie
        if previous_csrf_token is None:
            with contextlib.suppress(AttributeError):
                del LUOGU_REQUEST_AUTH.csrf_token
        else:
            LUOGU_REQUEST_AUTH.csrf_token = previous_csrf_token


def is_transient_http_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in TRANSIENT_HTTP_STATUSES
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return True
        return "timed out" in str(reason).lower() or "temporarily unavailable" in str(reason).lower()
    return "timed out" in str(exc).lower()


def retry_delay(attempt: int) -> float:
    return max(0.0, HTTP_RETRY_BACKOFF_SECONDS) * (2 ** attempt)


def is_database_locked_error(exc: Exception) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower()


def password_hash(password: str, salt: bytes | None = None, iterations: int = 210_000) -> str:
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        urllib.parse.quote_from_bytes(salt),
        urllib.parse.quote_from_bytes(digest),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = urllib.parse.unquote_to_bytes(salt_text)
        expected = urllib.parse.unquote_to_bytes(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_text))
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=120000")
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                real_name TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                team_name TEXT NOT NULL DEFAULT '未分组',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guests (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                real_name TEXT NOT NULL DEFAULT '',
                team_name TEXT NOT NULL DEFAULT '游客',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS verification_tokens (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                used_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                owner_type TEXT NOT NULL CHECK(owner_type IN ('user', 'guest')),
                owner_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS handles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_type TEXT NOT NULL CHECK(owner_type IN ('user', 'guest')),
                owner_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                handle TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                last_sync_at INTEGER,
                last_error TEXT,
                stats_json TEXT,
                UNIQUE(owner_type, owner_id, platform, handle)
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_type TEXT NOT NULL CHECK(owner_type IN ('user', 'guest')),
                owner_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                handle TEXT NOT NULL,
                remote_id TEXT NOT NULL,
                problem_id TEXT,
                problem_name TEXT,
                verdict TEXT,
                language TEXT,
                submitted_at INTEGER NOT NULL,
                url TEXT,
                raw_json TEXT,
                created_at INTEGER NOT NULL,
                UNIQUE(owner_type, owner_id, platform, handle, remote_id)
            );

            CREATE TABLE IF NOT EXISTS contests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_type TEXT NOT NULL CHECK(owner_type IN ('user', 'guest')),
                owner_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                handle TEXT NOT NULL,
                remote_id TEXT NOT NULL,
                contest_name TEXT NOT NULL,
                category TEXT NOT NULL,
                participated_at INTEGER NOT NULL,
                url TEXT,
                raw_json TEXT,
                created_at INTEGER NOT NULL,
                UNIQUE(owner_type, owner_id, platform, handle, remote_id)
            );

            CREATE INDEX IF NOT EXISTS idx_handles_owner ON handles(owner_type, owner_id, active);
            CREATE INDEX IF NOT EXISTS idx_submissions_owner_time ON submissions(owner_type, owner_id, submitted_at DESC);
            CREATE INDEX IF NOT EXISTS idx_submissions_time ON submissions(submitted_at DESC);
            CREATE INDEX IF NOT EXISTS idx_contests_owner_time ON contests(owner_type, owner_id, participated_at DESC);
            """
        )
        migrate_db(conn)


def migrate_db(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "username" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
    if "team_name" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN team_name TEXT")
    if "real_name" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN real_name TEXT")

    rows = conn.execute(
        "SELECT id, email, display_name, username FROM users WHERE username IS NULL OR username = '' ORDER BY id"
    ).fetchall()
    used = {
        row["username"]
        for row in conn.execute("SELECT username FROM users WHERE username IS NOT NULL AND username != ''").fetchall()
    }
    for row in rows:
        base = username_base(row["display_name"] or row["email"].split("@", 1)[0])
        candidate = base
        suffix = 1
        while candidate in used:
            suffix += 1
            candidate = f"{base[:24]}{suffix}"
        used.add(candidate)
        conn.execute("UPDATE users SET username = ? WHERE id = ?", (candidate, row["id"]))

    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    conn.execute("UPDATE users SET verified = 1 WHERE verified != 1")
    conn.execute(
        "UPDATE users SET team_name = ? WHERE team_name IS NULL OR TRIM(team_name) = ''",
        (DEFAULT_TEAM_NAME,),
    )
    conn.execute("UPDATE users SET real_name = '' WHERE real_name IS NULL")

    guest_columns = {row["name"] for row in conn.execute("PRAGMA table_info(guests)").fetchall()}
    if "team_name" not in guest_columns:
        conn.execute("ALTER TABLE guests ADD COLUMN team_name TEXT")
    if "real_name" not in guest_columns:
        conn.execute("ALTER TABLE guests ADD COLUMN real_name TEXT")
    conn.execute(
        "UPDATE guests SET team_name = ? WHERE team_name IS NULL OR TRIM(team_name) = ''",
        (GUEST_TEAM_NAME,),
    )
    conn.execute("UPDATE guests SET real_name = '' WHERE real_name IS NULL")

    handle_columns = {row["name"] for row in conn.execute("PRAGMA table_info(handles)").fetchall()}
    if "stats_json" not in handle_columns:
        conn.execute("ALTER TABLE handles ADD COLUMN stats_json TEXT")

    backfill_nowcoder_submission_times(conn)


def backfill_nowcoder_submission_times(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, submitted_at, raw_json
        FROM submissions
        WHERE platform = 'nowcoder'
          AND raw_json IS NOT NULL
          AND raw_json != ''
        """
    ).fetchall()
    fixed = 0
    for row in rows:
        try:
            raw = json.loads(row["raw_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "")
        if not text:
            continue
        parsed_at = parse_datetime_text(text, DISPLAY_TZ)
        if not parsed_at or int(row["submitted_at"] or 0) == parsed_at:
            continue
        conn.execute("UPDATE submissions SET submitted_at = ? WHERE id = ?", (parsed_at, row["id"]))
        fixed += 1
    if fixed:
        print(f"Backfilled {fixed} Nowcoder submission timestamps", flush=True)


def http_get(
    url: str,
    headers: dict[str, str] | None = None,
    cache_ttl_seconds: int | None = None,
    allow_stale_cache: bool = True,
    cache_write: bool = True,
) -> tuple[bytes, str]:
    use_cache = not has_cookie_header(headers)
    cached = read_http_cache(url, cache_ttl_seconds) if use_cache and cache_ttl_seconds is not None else None
    if cached:
        body, content_type, _ = cached
        return body, content_type

    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    }
    if headers:
        request_headers.update(headers)
    attempts = max(1, HTTP_RETRY_COUNT + 1)
    last_exc: Exception | None = None
    for attempt in range(attempts):
        req = urllib.request.Request(url, headers=request_headers)
        try:
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with opener.open(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                content_type = resp.headers.get("content-type", "")
                body = resp.read()
                with contextlib.suppress(Exception):
                    if cache_write and use_cache:
                        write_http_cache(url, body, content_type)
                return body, content_type
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1 and is_transient_http_error(exc):
                time.sleep(retry_delay(attempt))
                continue
            break
    if allow_stale_cache and use_cache:
        stale = read_http_cache(url)
        if stale:
            body, content_type, fetched_at = stale
            record_http_stale_hit(url, fetched_at)
            return body, content_type
    if last_exc:
        raise last_exc
    raise RuntimeError("HTTP request failed")


def proxy_http_get(
    url: str,
    headers: dict[str, str] | None,
    proxy_url: str,
    proxy_token: str,
    cache_ttl_seconds: int | None = None,
    allow_stale_cache: bool = True,
    cache_write: bool = True,
) -> tuple[bytes, str]:
    if not proxy_url:
        return http_get(
            url,
            headers=headers,
            cache_ttl_seconds=cache_ttl_seconds,
            allow_stale_cache=allow_stale_cache,
            cache_write=cache_write,
        )

    use_cache = not has_cookie_header(headers)
    cached = read_http_cache(url, cache_ttl_seconds) if use_cache and cache_ttl_seconds is not None else None
    if cached:
        body, content_type, _ = cached
        return body, content_type

    request_headers = {"Accept": "application/json"}
    if proxy_token:
        request_headers["Authorization"] = f"Bearer {proxy_token}"

    try:
        data = http_post_json(
            proxy_url,
            {"url": url, "headers": headers or {}},
            headers=request_headers,
        )
        if not isinstance(data, dict):
            raise RuntimeError("代理返回格式异常")
        status = int(data.get("status") or 200)
        if not data.get("ok") or status >= 400:
            detail = str(data.get("error") or data.get("message") or "").strip()
            raise RuntimeError(detail or f"代理请求失败：HTTP {status}")
        content_type = str(data.get("contentType") or data.get("content_type") or "")
        if data.get("bodyBase64") is not None:
            body = base64.b64decode(str(data.get("bodyBase64") or ""))
        else:
            body = str(data.get("body") or "").encode("utf-8")
        with contextlib.suppress(Exception):
            if cache_write and use_cache:
                write_http_cache(url, body, content_type)
        return body, content_type
    except Exception as exc:
        if allow_stale_cache and use_cache:
            stale = read_http_cache(url)
            if stale:
                body, content_type, fetched_at = stale
                record_http_stale_hit(url, fetched_at)
                return body, content_type
        raise exc


def proxy_http_get_json(
    url: str,
    headers: dict[str, str] | None,
    proxy_url: str,
    proxy_token: str,
    cache_ttl_seconds: int | None = None,
    allow_stale_cache: bool = True,
):
    body, _ = proxy_http_get(
        url,
        headers=headers,
        proxy_url=proxy_url,
        proxy_token=proxy_token,
        cache_ttl_seconds=cache_ttl_seconds,
        allow_stale_cache=allow_stale_cache,
    )
    return json.loads(body.decode("utf-8"))


def normalize_cookie_header(value: str, default_name: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if re.search(r"(^|;)\s*[A-Za-z0-9_\-.]+=", value):
        return value
    return f"{default_name}={value}"


def luogu_cookie_header() -> str:
    parts = []
    clearance = normalize_cookie_header(LUOGU_CF_CLEARANCE, "cf_clearance")
    if clearance:
        parts.append(clearance)
    cookie = current_luogu_cookie() or LUOGU_COOKIE
    if cookie:
        if re.search(r"(^|;)\s*[A-Za-z0-9_\-.]+=", cookie):
            parts.append(cookie)
        else:
            parts.append(f"cf_clearance={cookie}")
    return "; ".join(parts)


def luogu_csrf_token() -> str:
    return current_luogu_csrf_token() or LUOGU_CSRF_TOKEN


def parse_datetime_text(value: str, source_tz: dt.tzinfo = dt.timezone.utc) -> int | None:
    value = value.strip()
    patterns = [
        ("%Y-%m-%d %H:%M:%S", r"20\d\d-\d\d-\d\d\s+\d\d:\d\d:\d\d"),
        ("%Y-%m-%d %H:%M", r"20\d\d-\d\d-\d\d\s+\d\d:\d\d"),
        ("%Y/%m/%d %H:%M:%S", r"20\d\d/\d\d/\d\d\s+\d\d:\d\d:\d\d"),
        ("%Y/%m/%d %H:%M", r"20\d\d/\d\d/\d\d\s+\d\d:\d\d"),
    ]
    for fmt, pattern in patterns:
        match = re.search(pattern, value)
        if not match:
            continue
        try:
            parsed = dt.datetime.strptime(match.group(0), fmt)
            return int(parsed.replace(tzinfo=source_tz).timestamp())
        except ValueError:
            pass
    return None


def http_get_json(
    url: str,
    headers: dict[str, str] | None = None,
    cache_ttl_seconds: int | None = None,
    allow_stale_cache: bool = True,
):
    body, _ = http_get(
        url,
        headers=headers,
        cache_ttl_seconds=cache_ttl_seconds,
        allow_stale_cache=allow_stale_cache,
    )
    return json.loads(body.decode("utf-8"))


def http_post_json(url: str, payload: dict, headers: dict[str, str] | None = None):
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Content-Type": "application/json",
    }
    if headers:
        request_headers.update(headers)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    attempts = max(1, HTTP_RETRY_COUNT + 1)
    last_exc: Exception | None = None
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1 and is_transient_http_error(exc):
                time.sleep(retry_delay(attempt))
                continue
            break
    if last_exc:
        raise last_exc
    raise RuntimeError("HTTP POST request failed")


def strip_tags(fragment: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", fragment, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_iso_datetime(value: str) -> int | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.timestamp())


def normalize_verdict(value) -> str:
    if value is None:
        return "UNKNOWN"
    text = str(value).strip()
    upper = text.upper()
    accepted_aliases = {"AC", "OK", "ACCEPTED", "答案正确", "通过"}
    if upper in accepted_aliases or text in accepted_aliases:
        return "AC"
    if text == "12":
        return "AC"
    camel = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", text)
    camel = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", camel).upper()
    normalized = re.sub(r"[^0-9A-Z]+", "_", camel).strip("_")
    return normalized or upper or "UNKNOWN"


CONTEST_CATEGORY_LABELS = {
    "codeforces.div1": "Codeforces Div.1",
    "codeforces.div2": "Codeforces Div.2",
    "codeforces.div3": "Codeforces Div.3",
    "codeforces.div4": "Codeforces Div.4",
    "codeforces.div1_2": "Codeforces Div.1+2",
    "codeforces.educational": "Codeforces Educational",
    "codeforces.global": "Codeforces Global",
    "codeforces.gym": "Codeforces Gym",
    "codeforces.special": "Codeforces 特别赛",
    "codeforces.other": "Codeforces 其他",
    "atcoder.abc": "AtCoder Beginner",
    "atcoder.arc": "AtCoder Regular",
    "atcoder.agc": "AtCoder Grand",
    "atcoder.ahc": "AtCoder Heuristic",
    "atcoder.other": "AtCoder 其他",
    "nowcoder.multi_school": "牛客多校",
    "nowcoder.weekly": "牛客周赛",
    "nowcoder.monthly": "牛客月赛",
    "nowcoder.newbie_monthly": "牛客小白月赛",
    "nowcoder.icpc_ccpc": "牛客 ICPC/CCPC",
    "nowcoder.school": "牛客校赛/同步赛",
    "nowcoder.seasonal": "牛客寒暑假",
    "nowcoder.practice": "牛客练习赛",
    "nowcoder.challenge": "牛客挑战赛",
    "nowcoder.other": "牛客其他",
    "luogu.monthly": "洛谷月赛",
    "luogu.weekly": "洛谷周赛",
    "luogu.beginner": "洛谷入门赛",
    "luogu.other": "洛谷其他",
    "vjudge.contest": "VJudge 比赛",
    "vjudge.ucup": "VJudge / UCup",
    "qoj.ucup": "QOJ / UCup",
    "qoj.contest": "QOJ 比赛",
    "other": "其他比赛",
}

CONTEST_CATEGORY_ORDER = {key: index for index, key in enumerate(CONTEST_CATEGORY_LABELS)}


def contest_category_label(category: str) -> str:
    return CONTEST_CATEGORY_LABELS.get(category, category or "其他比赛")


def classify_contest(platform: str, name: str = "", remote_id: str = "", raw: dict | None = None) -> str:
    raw = raw or {}
    lower = name.lower()
    remote_int = int(remote_id) if str(remote_id).isdigit() else 0
    if platform == "codeforces":
        if remote_int >= 100000 or "gym" in lower:
            return "codeforces.gym"
        if "educational codeforces round" in lower:
            return "codeforces.educational"
        if "global round" in lower:
            return "codeforces.global"
        div_text = re.sub(r"\s+", " ", lower.replace("division", "div"))
        if re.search(r"div\.?\s*1\s*(\+|and|&)\s*(div\.?\s*)?2|div\.?\s*1\s*\+\s*2", div_text):
            return "codeforces.div1_2"
        if re.search(r"div\.?\s*1\b", div_text):
            return "codeforces.div1"
        if re.search(r"div\.?\s*2\b", div_text):
            return "codeforces.div2"
        if re.search(r"div\.?\s*3\b", div_text):
            return "codeforces.div3"
        if re.search(r"div\.?\s*4\b", div_text):
            return "codeforces.div4"
        if any(token in lower for token in ["good bye", "hello", "april fools", "kotlin heroes"]):
            return "codeforces.special"
        return "codeforces.other"
    if platform == "atcoder":
        contest_id = str(raw.get("id") or remote_id or "").lower()
        if contest_id.startswith("abc"):
            return "atcoder.abc"
        if contest_id.startswith("arc"):
            return "atcoder.arc"
        if contest_id.startswith("agc"):
            return "atcoder.agc"
        if contest_id.startswith("ahc") or "heuristic" in lower:
            return "atcoder.ahc"
        return "atcoder.other"
    if platform == "nowcoder":
        compact_name = re.sub(r"\s+", "", name)
        if "多校" in name:
            return "nowcoder.multi_school"
        if "小白月赛" in name:
            return "nowcoder.newbie_monthly"
        if "周赛" in name:
            return "nowcoder.weekly"
        if "月赛" in name:
            return "nowcoder.monthly"
        if "icpc" in lower or "ccpc" in lower:
            return "nowcoder.icpc_ccpc"
        if any(token in name for token in ["校赛", "新生赛", "同步赛"]):
            return "nowcoder.school"
        if any(token in name for token in ["寒假", "暑假"]):
            return "nowcoder.seasonal"
        if "牛客练习赛" in compact_name:
            return "nowcoder.practice"
        if "牛客挑战赛" in compact_name or "wannafly挑战赛" in lower:
            return "nowcoder.challenge"
        return "nowcoder.other"
    if platform == "luogu":
        if "月赛" in name:
            return "luogu.monthly"
        if "周赛" in name:
            return "luogu.weekly"
        if "入门" in name:
            return "luogu.beginner"
        return "luogu.other"
    if platform == "vjudge":
        if "ucup" in lower or "universal cup" in lower:
            return "vjudge.ucup"
        return "vjudge.contest"
    if platform == "qoj":
        if "ucup" in lower or "universal cup" in lower:
            return "qoj.ucup"
        return "qoj.contest"
    return "other"


def normalize_problem_code(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def normalize_problem_text_key(value: str) -> str:
    text = strip_tags(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", text).strip("-")
    return text[:160] or "unknown"


def source_oj_key(value: str) -> str:
    text = re.sub(r"[^0-9a-z]+", "", str(value or "").lower())
    aliases = {
        "cf": "codeforces",
        "codeforce": "codeforces",
        "codeforces": "codeforces",
        "codeforcesgym": "codeforces",
        "gym": "codeforces",
        "vjudge": "vjudge",
        "vj": "vjudge",
        "at": "atcoder",
        "atcoder": "atcoder",
        "atcoderjp": "atcoder",
        "lg": "luogu",
        "luogu": "luogu",
        "loj": "loj",
        "libreoj": "loj",
        "qoj": "qoj",
        "hdu": "hdu",
        "poj": "poj",
        "zoj": "zoj",
        "uva": "uva",
        "spoj": "spoj",
        "lightoj": "lightoj",
    }
    return aliases.get(text, text or "unknown")


def codeforces_problem_code(value: str) -> str:
    code = normalize_problem_code(value).upper()
    code = re.sub(r"^(?:CODEFORCES|CF)[-_]?", "", code)
    match = re.match(r"^0*([1-9][0-9]{0,6})([A-Z][0-9A-Z]*)$", code)
    if not match:
        return ""
    return f"{int(match.group(1))}{match.group(2)}"


def source_problem_key(source: str, problem_code: str) -> str:
    oj = source_oj_key(source)
    code = normalize_problem_code(problem_code)
    if not code:
        return ""
    if oj == "codeforces":
        cf_code = codeforces_problem_code(code)
        return f"codeforces:{cf_code}" if cf_code else f"codeforces:{code.upper()}"
    if oj == "atcoder":
        return f"atcoder:{code.lower()}"
    if oj == "luogu":
        return luogu_problem_key(code)
    if oj in {"loj", "qoj"}:
        return f"{oj}:{code.upper()}"
    return f"{oj}:{code.upper()}"


def luogu_problem_key(pid: str, problem_type: str = "") -> str:
    code = normalize_problem_code(pid).upper()
    kind = str(problem_type or "").strip().upper()
    if not code:
        return ""
    if kind == "CF" or code.startswith("CF"):
        return source_problem_key("codeforces", code)
    if code.startswith("AT_"):
        return source_problem_key("atcoder", code[3:])
    return f"luogu:{code}"


def split_source_problem_id(problem_id: str) -> tuple[str, str] | None:
    text = normalize_problem_code(problem_id)
    match = re.match(r"^([A-Za-z][0-9A-Za-z]*?)[-_](.+)$", text)
    if not match:
        return None
    return match.group(1), match.group(2)


def raw_json_dict(row: sqlite3.Row) -> dict:
    if "raw_json" not in row.keys():
        return {}
    try:
        value = row["raw_json"]
    except Exception:
        return {}
    if not value:
        return {}
    with contextlib.suppress(Exception):
        data = json.loads(value)
        if isinstance(data, dict):
            return data
    return {}


def is_activity_placeholder(row: sqlite3.Row, raw: dict | None = None) -> bool:
    raw = raw if raw is not None else raw_json_dict(row)
    problem_id = str(row["problem_id"] or "")
    return bool(row["platform"] == "luogu" and raw.get("syntheticFromProfile") and problem_id.startswith("luogu-activity-"))


def canonical_problem_key(
    platform: str,
    problem_id: str = "",
    problem_name: str = "",
    remote_id: str = "",
    raw: dict | None = None,
) -> str:
    platform = str(platform or "").lower()
    problem_id = str(problem_id or "")
    problem_name = str(problem_name or "")
    remote_id = str(remote_id or "")
    raw = raw or {}

    if platform == "codeforces":
        problem = raw.get("problem") if isinstance(raw.get("problem"), dict) else {}
        contest_id = raw.get("contestId") or problem.get("contestId")
        index = problem.get("index")
        if contest_id and index:
            key = source_problem_key("codeforces", f"{contest_id}{index}")
            if key:
                return key
        key = source_problem_key("codeforces", problem_id)
        if key:
            return key

    if platform == "atcoder":
        problem = raw.get("problem_id") or problem_id
        if problem:
            return source_problem_key("atcoder", str(problem))

    if platform == "vjudge":
        source = raw.get("oj") or raw.get("OJId") or raw.get("ojName")
        number = raw.get("probNum") or raw.get("problemNum") or raw.get("pid")
        if source and number:
            key = source_problem_key(str(source), str(number))
            if key:
                return key
        split = split_source_problem_id(problem_id)
        if split:
            key = source_problem_key(split[0], split[1])
            if key:
                return key

    if platform == "luogu":
        raw_pid = raw.get("pid") if isinstance(raw, dict) else ""
        raw_type = raw.get("type") if isinstance(raw, dict) else ""
        if raw_pid:
            return luogu_problem_key(str(raw_pid), str(raw_type or ""))
        if problem_id.startswith("luogu-activity-"):
            return f"luogu-activity:{problem_id}"
        return luogu_problem_key(problem_id)

    if platform in {"loj", "qoj"} and problem_id:
        return source_problem_key(platform, problem_id)

    fallback = problem_id or problem_name or remote_id
    return f"{platform}:{normalize_problem_text_key(fallback)}"


class OJAdapter:
    key = ""
    label = ""
    handle_hint = ""

    def normalize_handle(self, handle: str) -> str:
        handle = handle.strip()
        if not handle:
            raise ValueError("账号不能为空")
        return handle

    def fetch_submissions(self, handle: str, since_ts: int) -> list[dict]:
        raise NotImplementedError

    def fetch_contests(self, handle: str, since_ts: int, submissions: list[dict]) -> list[dict]:
        return []

    def fetch_profile_stats(self, handle: str, submissions: list[dict]) -> dict:
        return {}


def codeforces_contest_lookup() -> dict[int, dict]:
    lookup: dict[int, dict] = {}
    for url in [
        "https://codeforces.com/api/contest.list",
        "https://codeforces.com/api/contest.list?gym=true",
    ]:
        data = http_get_json(url, cache_ttl_seconds=24 * 3600)
        if data.get("status") != "OK":
            raise RuntimeError(data.get("comment") or "Codeforces contest.list 返回失败")
        for item in data.get("result") or []:
            if item.get("id") is not None:
                lookup[int(item["id"])] = item
    return lookup


def atcoder_contest_lookup() -> dict[str, dict]:
    data = http_get_json(
        "https://kenkoooo.com/atcoder/resources/contests.json",
        cache_ttl_seconds=24 * 3600,
    )
    if not isinstance(data, list):
        raise RuntimeError("AtCoder contest resource 返回格式异常")
    return {str(item.get("id")): item for item in data if item.get("id")}


CODEFORCES_UNOFFICIAL_PARTICIPANT_TYPES = {"VIRTUAL", "OUT_OF_COMPETITION"}
CODEFORCES_NON_PENALTY_VERDICTS = {"COMPILATION_ERROR", "TESTING", "SKIPPED"}


def codeforces_standings_cache_path(contest_id: int) -> Path:
    return CODEFORCES_STANDINGS_CACHE_DIR / f"{int(contest_id)}.json"


def read_codeforces_standings_summary(contest_id: int) -> dict | None:
    path = codeforces_standings_cache_path(contest_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    return data


def infer_codeforces_icpc_penalty_minutes(rows: list[dict]) -> int:
    candidates = []
    for row in rows[:500]:
        problem_results = row.get("problemResults") or []
        solved = [item for item in problem_results if float(item.get("points") or 0) > 0]
        rejected = sum(int(item.get("rejectedAttemptCount") or 0) for item in solved)
        if not rejected:
            continue
        solve_minutes = sum(int(item.get("bestSubmissionTimeSeconds") or 0) // 60 for item in solved)
        extra = int(row.get("penalty") or 0) - solve_minutes
        if extra > 0 and extra % rejected == 0 and extra // rejected in {10, 20}:
            candidates.append(extra // rejected)
    if not candidates:
        return 20
    return max({value: candidates.count(value) for value in set(candidates)}, key=lambda value: candidates.count(value))


def codeforces_standings_summary(contest_id: int) -> dict:
    cached = read_codeforces_standings_summary(contest_id)
    if cached:
        return cached
    with CODEFORCES_STANDINGS_LOCK:
        cached = read_codeforces_standings_summary(contest_id)
        if cached:
            return cached
        url = f"https://codeforces.com/api/contest.standings?contestId={int(contest_id)}"
        body, _ = http_get(url, allow_stale_cache=False, cache_write=False)
        payload = json.loads(body.decode("utf-8"))
        if payload.get("status") != "OK" or not isinstance(payload.get("result"), dict):
            raise RuntimeError(payload.get("comment") or "Codeforces standings 返回失败")
        result = payload["result"]
        contest = result.get("contest") if isinstance(result.get("contest"), dict) else {}
        rows = result.get("rows") if isinstance(result.get("rows"), list) else []
        problems = result.get("problems") if isinstance(result.get("problems"), list) else []
        summary = {
            "version": 1,
            "fetchedAt": utcnow(),
            "contest": {
                "id": contest.get("id"),
                "name": contest.get("name"),
                "type": contest.get("type"),
                "startTimeSeconds": contest.get("startTimeSeconds"),
                "durationSeconds": contest.get("durationSeconds"),
            },
            "problems": [
                {"index": item.get("index"), "points": item.get("points")}
                for item in problems
                if item.get("index")
            ],
            "rows": [
                [float(item.get("points") or 0), int(item.get("penalty") or 0)]
                for item in rows
            ],
            "icpcPenaltyMinutes": infer_codeforces_icpc_penalty_minutes(rows),
        }
        path = codeforces_standings_cache_path(contest_id)
        tmp_path = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
        tmp_path.write_text(json.dumps(summary, ensure_ascii=False, separators=(",", ":")), "utf-8")
        os.replace(tmp_path, path)
        return summary


def codeforces_unofficial_result(summary: dict, submissions: list[dict]) -> dict | None:
    raw_submissions = []
    for item in submissions:
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        participant_type = str((raw.get("author") or {}).get("participantType") or "").upper()
        if participant_type not in CODEFORCES_UNOFFICIAL_PARTICIPANT_TYPES:
            continue
        submitted_at = int(item.get("submitted_at") or raw.get("creationTimeSeconds") or 0)
        if submitted_at:
            raw_submissions.append((submitted_at, participant_type, raw))
    if not raw_submissions:
        return None

    raw_submissions.sort(key=lambda item: item[0])
    _, participant_type, first_raw = raw_submissions[0]
    members = (first_raw.get("author") or {}).get("members") or []
    if len(members) > 1:
        return None
    contest = summary.get("contest") if isinstance(summary.get("contest"), dict) else {}
    start_timestamp = int(
        (first_raw.get("author") or {}).get("startTimeSeconds")
        or contest.get("startTimeSeconds")
        or raw_submissions[0][0]
    )
    duration_seconds = int(contest.get("durationSeconds") or 0)
    end_timestamp = start_timestamp + duration_seconds if duration_seconds else None
    attempts: dict[str, int] = {}
    solved: dict[str, tuple[int, int]] = {}
    for submitted_at, item_type, raw in raw_submissions:
        if item_type != participant_type or submitted_at < start_timestamp:
            continue
        if end_timestamp and submitted_at > end_timestamp:
            continue
        problem = raw.get("problem") if isinstance(raw.get("problem"), dict) else {}
        problem_index = str(problem.get("index") or "")
        if not problem_index or problem_index in solved:
            continue
        verdict = str(raw.get("verdict") or "").upper()
        elapsed_seconds = int(raw.get("relativeTimeSeconds") or submitted_at - start_timestamp)
        if elapsed_seconds < 0 or (duration_seconds and elapsed_seconds > duration_seconds):
            continue
        if verdict == "OK":
            solved[problem_index] = (elapsed_seconds // 60, attempts.get(problem_index, 0))
        elif verdict not in CODEFORCES_NON_PENALTY_VERDICTS:
            attempts[problem_index] = attempts.get(problem_index, 0) + 1

    contest_type = str(contest.get("type") or "CF").upper()
    penalty = 0
    if contest_type == "ICPC":
        points = float(len(solved))
        penalty_minutes = int(summary.get("icpcPenaltyMinutes") or 20)
        penalty = sum(minutes + wrong * penalty_minutes for minutes, wrong in solved.values())
    else:
        maximums = {
            str(item.get("index") or ""): float(item.get("points") or 0)
            for item in summary.get("problems") or []
        }
        points = 0.0
        for problem_index, (minutes, wrong) in solved.items():
            maximum = maximums.get(problem_index, 0)
            if maximum <= 0:
                continue
            wrong_penalty = 0 if participant_type == "OUT_OF_COMPETITION" else 50 * wrong
            points += max(maximum * 0.3, maximum - (maximum / 250) * minutes - wrong_penalty)

    better = 0
    for row in summary.get("rows") or []:
        row_points = float(row[0] or 0)
        row_penalty = int(row[1] or 0)
        if row_points > points or (contest_type == "ICPC" and row_points == points and row_penalty < penalty):
            better += 1
    normalized_points = int(points) if points.is_integer() else round(points, 2)
    return {
        "rank": better + 1,
        "score": normalized_points,
        "solved": len(solved),
        "penalty": penalty,
        "participants": len(summary.get("rows") or []),
        "participantType": participant_type,
        "rankKind": "virtual-equivalent",
        "startTimeSeconds": start_timestamp,
    }


class CodeforcesAdapter(OJAdapter):
    key = "codeforces"
    label = "Codeforces"
    handle_hint = "Codeforces handle，例如 tourist"

    def fetch_submissions(self, handle: str, since_ts: int) -> list[dict]:
        submissions = []
        page_size = min(max(FETCH_LIMIT, 1), 1000)
        start = 1
        while True:
            params = urllib.parse.urlencode({"handle": handle, "from": start, "count": page_size})
            data = http_get_json(f"https://codeforces.com/api/user.status?{params}")
            if data.get("status") != "OK":
                raise RuntimeError(data.get("comment") or "Codeforces API 返回失败")
            items = data.get("result", [])
            if not items:
                break

            reached_older = False
            for item in items:
                submitted_at = int(item.get("creationTimeSeconds") or 0)
                if submitted_at and submitted_at < since_ts:
                    reached_older = True
                    continue
                problem = item.get("problem") or {}
                contest_id = item.get("contestId") or problem.get("contestId")
                index = problem.get("index") or ""
                name = problem.get("name") or ""
                problem_id = f"{contest_id}{index}" if contest_id and index else (name or "")
                url = None
                if contest_id and item.get("id"):
                    url = f"https://codeforces.com/contest/{contest_id}/submission/{item['id']}"
                submissions.append(
                    {
                        "remote_id": str(item.get("id")),
                        "problem_id": problem_id,
                        "problem_name": f"{problem_id} {name}".strip() if name else problem_id,
                        "verdict": normalize_verdict(item.get("verdict") or "TESTING"),
                        "language": item.get("programmingLanguage") or "",
                        "submitted_at": submitted_at,
                        "url": url,
                        "raw": item,
                    }
                )

            if reached_older or len(items) < page_size:
                break
            start += page_size
        return submissions

    def fetch_contests(self, handle: str, since_ts: int, submissions: list[dict]) -> list[dict]:
        lookup = codeforces_contest_lookup()
        history_floor = utcnow() - FETCH_LOOKBACK_DAYS * 86400
        rating_changes: dict[int, dict] = {}
        with contextlib.suppress(Exception):
            params = urllib.parse.urlencode({"handle": handle})
            rating_data = http_get_json(
                f"https://codeforces.com/api/user.rating?{params}",
                cache_ttl_seconds=6 * 3600,
            )
            if rating_data.get("status") == "OK":
                rating_changes = {
                    int(item["contestId"]): item
                    for item in rating_data.get("result") or []
                    if item.get("contestId") is not None
                }
        contests = {}
        unofficial_submissions: dict[int, list[dict]] = {}
        for item in submissions:
            raw = item.get("raw") or {}
            problem = raw.get("problem") or {}
            contest_id = raw.get("contestId") or problem.get("contestId")
            submitted_at = int(item.get("submitted_at") or 0)
            if not contest_id or submitted_at < history_floor:
                continue
            participant_type = str((raw.get("author") or {}).get("participantType") or "")
            if participant_type.upper() == "PRACTICE":
                continue
            contest_id = int(contest_id)
            if participant_type.upper() in CODEFORCES_UNOFFICIAL_PARTICIPANT_TYPES:
                unofficial_submissions.setdefault(contest_id, []).append(item)
            contest = lookup.get(contest_id) or {}
            name = str(contest.get("name") or f"Codeforces {contest_id}")
            start_at = int((raw.get("author") or {}).get("startTimeSeconds") or contest.get("startTimeSeconds") or submitted_at)
            remote_id = str(contest_id)
            existing = contests.get(remote_id)
            if existing and existing["participated_at"] <= start_at:
                continue
            url = f"https://codeforces.com/gym/{contest_id}" if contest_id >= 100000 else f"https://codeforces.com/contest/{contest_id}"
            contests[remote_id] = {
                "remote_id": remote_id,
                "contest_name": name,
                "category": classify_contest(self.key, name, remote_id, contest),
                "participated_at": start_at,
                "url": url,
                "raw": {
                    "contest": contest,
                    "ratingChange": rating_changes.get(contest_id),
                    "source": "user.status",
                },
            }

        for contest_id, rating_change in rating_changes.items():
            contest = lookup.get(contest_id) or {}
            start_at = int(contest.get("startTimeSeconds") or rating_change.get("ratingUpdateTimeSeconds") or 0)
            if not start_at or start_at < history_floor:
                continue
            remote_id = str(contest_id)
            name = str(contest.get("name") or rating_change.get("contestName") or f"Codeforces {contest_id}")
            url = f"https://codeforces.com/gym/{contest_id}" if contest_id >= 100000 else f"https://codeforces.com/contest/{contest_id}"
            existing = contests.get(remote_id)
            if existing:
                existing["raw"]["ratingChange"] = rating_change
                continue
            contests[remote_id] = {
                "remote_id": remote_id,
                "contest_name": name,
                "category": classify_contest(self.key, name, remote_id, contest),
                "participated_at": start_at,
                "url": url,
                "raw": {"contest": contest, "ratingChange": rating_change, "source": "user.rating"},
            }

        standings_fetches = 0
        ranked_unofficial = sorted(
            unofficial_submissions.items(),
            key=lambda pair: max(int(item.get("submitted_at") or 0) for item in pair[1]),
            reverse=True,
        )
        for contest_id, contest_submissions in ranked_unofficial:
            if contest_id >= 100000 or contest_id in rating_changes:
                continue
            remote_id = str(contest_id)
            existing = contests.get(remote_id)
            contest = lookup.get(contest_id) or {}
            if not existing or str(contest.get("phase") or "").upper() != "FINISHED":
                continue
            has_cached_standings = read_codeforces_standings_summary(contest_id) is not None
            if not has_cached_standings and standings_fetches >= CODEFORCES_VP_RANKS_PER_SYNC:
                continue
            if not has_cached_standings:
                standings_fetches += 1
            try:
                summary = codeforces_standings_summary(contest_id)
                virtual_result = codeforces_unofficial_result(summary, contest_submissions)
            except Exception:
                continue
            if virtual_result:
                existing["raw"]["virtualResult"] = virtual_result
        return list(contests.values())


class AtCoderAdapter(OJAdapter):
    key = "atcoder"
    label = "AtCoder"
    handle_hint = "AtCoder 用户名，例如 tourist"

    def fetch_submissions(self, handle: str, since_ts: int) -> list[dict]:
        submissions = []
        cursor = max(0, since_ts)
        while True:
            params = urllib.parse.urlencode({"user": handle, "from_second": cursor})
            cache_ttl = (
                HISTORICAL_CACHE_TTL_SECONDS
                if cursor < utcnow() - HISTORICAL_CACHE_AFTER_DAYS * 86400
                else None
            )
            data = http_get_json(
                f"https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?{params}",
                cache_ttl_seconds=cache_ttl,
            )
            if not data:
                break
            latest_ts = cursor
            for item in data:
                submitted_at = int(item.get("epoch_second") or 0)
                latest_ts = max(latest_ts, submitted_at)
                if submitted_at and submitted_at < since_ts:
                    continue
                contest_id = item.get("contest_id") or ""
                remote_id = str(item.get("id") or hashlib.sha1(json.dumps(item, sort_keys=True).encode()).hexdigest())
                problem_id = item.get("problem_id") or ""
                url = f"https://atcoder.jp/contests/{contest_id}/submissions/{remote_id}" if contest_id else None
                submissions.append(
                    {
                        "remote_id": remote_id,
                        "problem_id": problem_id,
                        "problem_name": problem_id,
                        "verdict": normalize_verdict(item.get("result")),
                        "language": item.get("language") or "",
                        "submitted_at": submitted_at,
                        "url": url,
                        "raw": item,
                    }
                )
            if len(data) < 500 or latest_ts <= cursor:
                break
            cursor = latest_ts + 1
        return submissions

    def fetch_contests(self, handle: str, since_ts: int, submissions: list[dict]) -> list[dict]:
        data = http_get_json(
            f"https://atcoder.jp/users/{urllib.parse.quote(handle)}/history/json",
            headers={"Referer": f"https://atcoder.jp/users/{urllib.parse.quote(handle)}/history"},
            cache_ttl_seconds=6 * 3600,
        )
        if not isinstance(data, list):
            raise RuntimeError("AtCoder 参赛历史返回格式异常")
        history_floor = utcnow() - FETCH_LOOKBACK_DAYS * 86400
        contest_lookup = {}
        with contextlib.suppress(Exception):
            contest_lookup = atcoder_contest_lookup()
        contests = []
        for item in data:
            contest_screen = str(item.get("ContestScreenName") or "")
            contest_id = contest_screen.split(".", 1)[0]
            name = str(item.get("ContestName") or item.get("ContestNameEn") or contest_id.upper())
            participated_at = parse_iso_datetime(str(item.get("EndTime") or "")) or 0
            if not contest_id or not participated_at or participated_at < history_floor:
                continue
            raw = {**item, "id": contest_id, "contest": contest_lookup.get(contest_id) or {}}
            contests.append(
                {
                    "remote_id": contest_id,
                    "contest_name": name,
                    "category": classify_contest(self.key, name, contest_id, raw),
                    "participated_at": participated_at,
                    "url": f"https://atcoder.jp/contests/{contest_id}",
                    "raw": raw,
                }
            )
        return contests


class LuoguAdapter(OJAdapter):
    key = "luogu"
    label = "洛谷"
    handle_hint = "洛谷用户名或数字 UID，例如 example_user / 123456"

    def __init__(self):
        self._profile_stats: dict[str, dict] = {}
        self._previous_stats: dict[str, dict] = {}

    def set_previous_stats(self, handle: str, stats_json: str | None) -> None:
        stats = {}
        if stats_json:
            with contextlib.suppress(Exception):
                parsed = json.loads(stats_json)
                if isinstance(parsed, dict):
                    stats = parsed
        self._previous_stats[handle] = stats

    def normalize_handle(self, handle: str) -> str:
        handle = handle.strip()
        if not handle:
            raise ValueError("洛谷账号不能为空")
        user_path = re.search(r"luogu\.com\.cn/user/([0-9A-Za-z_\-]+)", handle)
        if user_path:
            handle = user_path.group(1)
        if not re.match(r"^[0-9A-Za-z_\-]{2,32}$", handle):
            raise ValueError("洛谷请填写用户名、数字 UID 或用户主页链接")
        if not handle.isdigit():
            with contextlib.suppress(Exception):
                uid, _ = self._resolve_user(handle)
                if uid:
                    return uid
        return handle

    def canonicalize_handle(self, handle: str) -> tuple[str, str] | None:
        if handle.isdigit():
            return None
        uid, name = self._resolve_user(handle)
        if not uid or uid == handle:
            return None
        return uid, name

    def fetch_submissions(self, handle: str, since_ts: int) -> list[dict]:
        self._profile_stats[handle] = {}
        uid = ""
        profile_name = handle
        try:
            uid, profile_name = self._resolve_user(handle)
            profile_url = f"https://www.luogu.com.cn/user/{uid}"
            context = self._fetch_profile_context(uid)
            data = self._context_data(context)
            user = data.get("user") if isinstance(data.get("user"), dict) else {}
            profile_name = str(user.get("name") or profile_name)
            practice_data = {}
            with contextlib.suppress(Exception):
                practice_data = self._context_data(self._fetch_profile_context(uid, "/practice"))
            self._profile_stats[handle] = self._extract_profile_stats(uid, profile_name, data, practice_data)
            daily_counts = self._daily_counts(data)
        except Exception as exc:
            self._profile_stats[handle] = self._fetch_fallback_profile_stats(handle, uid, profile_name, exc)
            return []

        record_submissions: list[dict] = []
        if LUOGU_RECORD_SYNC:
            try:
                record_submissions, record_sync = self._fetch_record_submissions(handle, uid, profile_name, since_ts)
                if record_sync:
                    self._profile_stats[handle]["recordSync"] = record_sync
                if record_sync.get("lastError"):
                    self._profile_stats[handle]["_warning"] = (
                        "洛谷记录页部分同步失败，已保存本轮已抓到页面，下次会从失败页附近继续"
                    )
                if record_submissions or record_sync.get("historyComplete") or record_sync.get("source"):
                    self._profile_stats[handle]["source"] = "luogu-profile+record-list"
                    return record_submissions
            except Exception as exc:
                previous_record_sync = (self._previous_stats.get(handle) or {}).get("recordSync") or {}
                self._profile_stats[handle]["recordSync"] = {
                    **previous_record_sync,
                    "source": "luogu-record-list",
                    "lastError": str(exc)[:240] or exc.__class__.__name__,
                    "lastErrorAt": utcnow(),
                }
                if previous_record_sync:
                    self._profile_stats[handle]["_warning"] = "洛谷记录页同步失败，已保留本地历史记录并继续使用缓存"
                    self._profile_stats[handle]["source"] = "luogu-profile+record-list"
                    return []

        submissions = []
        for date_key, counts in sorted(daily_counts.items()):
            submitted_at = self._date_to_ts(date_key)
            if not submitted_at or submitted_at < since_ts:
                continue
            accepted_count, total_count = self._daily_count_pair(counts)
            total_count = max(total_count, accepted_count)
            for index in range(total_count):
                verdict = "AC" if index < accepted_count else "SUBMITTED"
                submissions.append(
                    {
                        "remote_id": f"profile-{uid}-{date_key}-{index + 1}",
                        "problem_id": f"luogu-activity-{date_key}-{index + 1}",
                        "problem_name": f"洛谷公开活动 {date_key}",
                        "verdict": verdict,
                        "language": "",
                        "submitted_at": submitted_at + index,
                        "url": profile_url,
                        "raw": {
                            "uid": uid,
                            "name": profile_name,
                            "date": date_key,
                            "accepted": accepted_count,
                            "total": total_count,
                            "syntheticFromProfile": True,
                        },
                    }
                )
        return submissions

    def _fetch_record_submissions(self, handle: str, uid: str, profile_name: str, since_ts: int) -> tuple[list[dict], dict]:
        previous = self._previous_stats.get(handle) or {}
        previous_sync = previous.get("recordSync") if isinstance(previous.get("recordSync"), dict) else {}
        previous_newest = int(previous_sync.get("newestSubmitTime") or 0)
        previous_oldest = int(previous_sync.get("oldestFetchedTime") or 0)
        history_complete = bool(previous_sync.get("historyComplete"))
        history_since = utcnow() - FETCH_LOOKBACK_DAYS * 86400
        incremental_since = since_ts
        if previous_newest:
            overlap_seconds = max(0, LUOGU_RECORD_INCREMENTAL_OVERLAP_SECONDS)
            incremental_since = max(incremental_since, previous_newest - overlap_seconds)
        record_query_user = profile_name or uid

        submissions_by_id: dict[str, dict] = {}
        pages_fetched: set[int] = set()
        total_count = int(previous_sync.get("totalRecordCount") or 0)
        per_page = int(previous_sync.get("perPage") or 20)
        page_count = int(previous_sync.get("pageCount") or 0)
        newest_seen = previous_newest
        oldest_seen = previous_oldest or 0
        request_index = 0
        fetch_error = ""

        def fetch_page(page_no: int) -> tuple[list[dict], dict]:
            nonlocal request_index, total_count, per_page, page_count, newest_seen, oldest_seen
            if page_no in pages_fetched:
                return [], {}
            request_index += 1
            self._record_delay(request_index)
            data = self._fetch_record_page(uid, record_query_user, page_no)
            records = data.get("records") if isinstance(data.get("records"), dict) else {}
            items = records.get("result") if isinstance(records.get("result"), list) else []
            if records.get("count") is not None:
                with contextlib.suppress(Exception):
                    total_count = int(records.get("count") or 0)
            if records.get("perPage") is not None:
                with contextlib.suppress(Exception):
                    per_page = int(records.get("perPage") or per_page or 20)
            if per_page and total_count:
                page_count = max(1, (total_count + per_page - 1) // per_page)
            parsed = [self._record_to_submission(uid, profile_name, item) for item in items if isinstance(item, dict)]
            parsed = [item for item in parsed if item]
            pages_fetched.add(page_no)
            for item in parsed:
                submitted_at = int(item.get("submitted_at") or 0)
                if submitted_at:
                    newest_seen = max(newest_seen, submitted_at)
                    oldest_seen = submitted_at if not oldest_seen else min(oldest_seen, submitted_at)
                    submissions_by_id[str(item["remote_id"])] = item
            return parsed, records

        recent_pages = max(0, LUOGU_RECORD_RECENT_PAGES_PER_SYNC)
        recent_reached_old = False
        last_recent_page = 0
        for page_no in range(1, recent_pages + 1):
            try:
                parsed, _ = fetch_page(page_no)
            except Exception as exc:
                fetch_error = str(exc)[:240] or exc.__class__.__name__
                break
            last_recent_page = page_no
            if not parsed:
                history_complete = True
                break
            oldest_page_ts = min(int(item.get("submitted_at") or 0) for item in parsed)
            if oldest_page_ts < incremental_since:
                recent_reached_old = True
                break
            if page_count and page_no >= page_count:
                history_complete = True
                break

        next_backfill_page = int(previous_sync.get("nextBackfillPage") or max(2, last_recent_page + 1))
        if next_backfill_page <= last_recent_page:
            next_backfill_page = last_recent_page + 1
        backfill_pages = 0 if history_complete else max(0, LUOGU_RECORD_BACKFILL_PAGES_PER_SYNC)
        for _ in range(backfill_pages):
            if page_count and next_backfill_page > page_count:
                history_complete = True
                break
            try:
                parsed, _ = fetch_page(next_backfill_page)
            except Exception as exc:
                fetch_error = str(exc)[:240] or exc.__class__.__name__
                break
            if not parsed:
                history_complete = True
                break
            oldest_page_ts = min(int(item.get("submitted_at") or 0) for item in parsed)
            next_backfill_page += 1
            if oldest_page_ts < history_since:
                history_complete = True
                break

        filtered = [
            item
            for item in submissions_by_id.values()
            if int(item.get("submitted_at") or 0) >= history_since
        ]
        filtered.sort(key=lambda item: int(item.get("submitted_at") or 0))
        sync_state = {
            "source": "luogu-record-list",
            "syncedAt": utcnow(),
            "pagesFetched": sorted(pages_fetched),
            "nextBackfillPage": next_backfill_page,
            "historyComplete": bool(history_complete or recent_reached_old and not previous_sync),
            "totalRecordCount": total_count,
            "perPage": per_page,
            "pageCount": page_count,
            "newestSubmitTime": newest_seen,
            "oldestFetchedTime": oldest_seen,
            "queryUser": record_query_user,
        }
        if recent_reached_old:
            sync_state["incrementalComplete"] = True
        if fetch_error:
            if not submissions_by_id and not pages_fetched:
                raise RuntimeError(fetch_error)
            sync_state.update({"partial": True, "lastError": fetch_error, "lastErrorAt": utcnow()})
        return filtered, sync_state

    def _fetch_record_page(self, uid: str, query_user: str, page_no: int) -> dict:
        query_user = str(query_user or uid)
        candidates = [query_user]
        if str(uid) and str(uid) not in candidates:
            candidates.append(str(uid))

        errors = []
        for candidate in candidates:
            try:
                return self._fetch_record_page_once(uid, candidate, page_no)
            except Exception as exc:
                errors.append(str(exc)[:240] or exc.__class__.__name__)
        raise RuntimeError("；".join(errors))

    @staticmethod
    def _record_payload_summary(payload: dict) -> str:
        if not isinstance(payload, dict):
            return f"payload={type(payload).__name__}"
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        current_data = data.get("currentData") if isinstance(data.get("currentData"), dict) else payload.get("currentData")
        if not isinstance(current_data, dict):
            current_data = {}
        records = current_data.get("records")
        parts = [
            f"code={payload.get('code')}",
            f"template={payload.get('currentTemplate') or payload.get('template') or data.get('currentTemplate') or data.get('template')}",
            f"topKeys={','.join(list(payload.keys())[:8])}",
            f"dataKeys={','.join(list(data.keys())[:8])}",
            f"currentDataKeys={','.join(list(current_data.keys())[:8])}",
            f"recordsType={type(records).__name__}",
        ]
        message = payload.get("message") or payload.get("error") or data.get("message") or data.get("error")
        if message:
            parts.append(f"message={str(message)[:80]}")
        return "，".join(parts)

    @classmethod
    def _record_data(cls, payload: dict) -> dict:
        data = cls._context_data(payload)
        if isinstance(data.get("records"), dict):
            return data

        seen: set[int] = set()

        def search(value, depth: int = 0) -> dict | None:
            if depth > 5 or not isinstance(value, dict):
                return None
            value_id = id(value)
            if value_id in seen:
                return None
            seen.add(value_id)

            records = value.get("records")
            if isinstance(records, dict):
                result = records.get("result")
                if isinstance(result, list) or records.get("count") is not None or records.get("perPage") is not None:
                    return value

            preferred_keys = ["currentData", "data", "props", "page", "recordList", "RecordList"]
            for key in preferred_keys:
                found = search(value.get(key), depth + 1)
                if found is not None:
                    return found
            for child in value.values():
                found = search(child, depth + 1)
                if found is not None:
                    return found
            return None

        return search(payload) or data

    def _fetch_record_page_once(self, uid: str, query_user: str, page_no: int) -> dict:
        query_user = str(query_user or uid)
        params = urllib.parse.urlencode({"user": query_user, "page": page_no, "_contentOnly": 1})
        referer = f"https://www.luogu.com.cn/record/list?user={urllib.parse.quote(query_user, safe='')}"
        url = f"https://www.luogu.com.cn/record/list?{params}"
        headers = self._headers(referer)
        headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Priority": "u=1, i",
                "Sec-Fetch-Site": "same-origin",
            }
        )
        body, _ = proxy_http_get(
            url,
            headers=headers,
            proxy_url=LUOGU_PROXY_URL,
            proxy_token=LUOGU_PROXY_TOKEN,
            cache_ttl_seconds=None,
            allow_stale_cache=False,
            cache_write=False,
        )
        payload = self._parse_luogu_payload(body.decode("utf-8", errors="ignore"))
        data = self._record_data(payload)
        if not isinstance(data.get("records"), dict):
            template = str(payload.get("currentTemplate") or payload.get("template") or "").lower()
            nested = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            template = template or str(nested.get("currentTemplate") or nested.get("template") or "").lower()
            if template == "login":
                raise RuntimeError(
                    f"洛谷 record/list 返回登录页（user={query_user}, page={page_no}），"
                    "请确认国内 luogu_proxy.py 已更新并重启，代理需要保留洛谷临时 CookieJar"
                )
            raise RuntimeError(
                f"洛谷记录页没有返回 records（user={query_user}, page={page_no}；{self._record_payload_summary(payload)}）"
            )
        return data

    @classmethod
    def _record_to_submission(cls, uid: str, profile_name: str, item: dict) -> dict | None:
        remote_id = str(item.get("id") or "")
        submitted_at = int(item.get("submitTime") or 0)
        problem = item.get("problem") if isinstance(item.get("problem"), dict) else {}
        pid = str(problem.get("pid") or "")
        if not remote_id or not submitted_at or not pid:
            return None
        problem_type = str(problem.get("type") or "")
        problem_title = str(problem.get("title") or pid)
        score = item.get("score")
        full_score = problem.get("fullScore")
        status = item.get("status")
        verdict = cls._record_verdict(status, score, full_score)
        language = cls._record_language(item.get("language"), bool(item.get("enableO2")))
        return {
            "remote_id": remote_id,
            "problem_id": pid,
            "problem_name": f"{pid} {problem_title}".strip(),
            "verdict": verdict,
            "language": language,
            "submitted_at": submitted_at,
            "url": f"https://www.luogu.com.cn/record/{remote_id}",
            "raw": {
                **item,
                "uid": uid,
                "name": profile_name,
                "pid": pid,
                "type": problem_type,
                "source": "luogu-record-list",
            },
        }

    @staticmethod
    def _record_verdict(status, score, full_score) -> str:
        with contextlib.suppress(Exception):
            if full_score is not None and score is not None and int(score) >= int(full_score):
                return "AC"
        text = str(status if status is not None else "").strip()
        if text == "12":
            return "AC"
        aliases = {
            "2": "COMPILE_ERROR",
            "3": "COMPILE_ERROR",
            "4": "RUNTIME_ERROR",
            "5": "TIME_LIMIT_EXCEEDED",
            "6": "MEMORY_LIMIT_EXCEEDED",
            "7": "WRONG_ANSWER",
            "8": "OUTPUT_LIMIT_EXCEEDED",
            "9": "RUNTIME_ERROR",
            "10": "SYSTEM_ERROR",
            "14": "WRONG_ANSWER",
        }
        if text in aliases:
            return aliases[text]
        return normalize_verdict(text or "UNKNOWN")

    @staticmethod
    def _record_language(language, enable_o2: bool) -> str:
        aliases = {
            "3": "C++",
            "4": "C",
            "7": "Python 3",
            "8": "Java",
            "34": "C++23",
        }
        value = aliases.get(str(language), f"语言 {language}" if language is not None else "")
        if enable_o2 and value and "O2" not in value:
            value = f"{value} O2"
        return value

    @staticmethod
    def _record_delay(request_index: int) -> None:
        if request_index <= 1:
            return
        low = max(0.0, LUOGU_RECORD_SLEEP_MIN_SECONDS)
        high = max(low, LUOGU_RECORD_SLEEP_MAX_SECONDS)
        if high <= 0:
            return
        time.sleep(random.uniform(low, high))

    def fetch_contests(self, handle: str, since_ts: int, submissions: list[dict]) -> list[dict]:
        stats = self._profile_stats.get(handle) or {}
        contests = []
        for item in stats.get("ratingContests") or []:
            contest = item.get("contest") if isinstance(item, dict) else {}
            if not isinstance(contest, dict):
                continue
            contest_id = str(contest.get("id") or "")
            participated_at = int(contest.get("endTime") or item.get("time") or 0)
            if not contest_id or not participated_at or participated_at < since_ts:
                continue
            name = str(contest.get("name") or f"洛谷比赛 {contest_id}")
            contests.append(
                {
                    "remote_id": contest_id,
                    "contest_name": name,
                    "category": classify_contest(self.key, name, contest_id, item),
                    "participated_at": participated_at,
                    "url": f"https://www.luogu.com.cn/contest/{contest_id}",
                    "raw": item,
                }
            )
        return contests

    def fetch_profile_stats(self, handle: str, submissions: list[dict]) -> dict:
        return self._profile_stats.pop(handle, {})

    def _fetch_fallback_profile_stats(self, handle: str, uid: str, profile_name: str, source_exc: Exception) -> dict:
        if not LUOGU_THIRD_PARTY_FALLBACK:
            raise source_exc

        previous = self._previous_stats.get(handle) or {}
        uid = str(uid or previous.get("uid") or (handle if handle.isdigit() else "")).strip()
        if not uid:
            raise RuntimeError(
                f"{source_exc}；当前服务器无法把洛谷用户名解析成数字 UID，第三方降级统计无法继续。"
                "服务端会在下次同步继续尝试自动解析；若仍失败，请配置 LUOGU_CF_CLEARANCE 或 LUOGU_PROXY_URL"
            ) from source_exc

        profile_name = str(previous.get("name") or profile_name or handle)
        errors = []
        for template in LUOGU_FALLBACK_URLS:
            try:
                url = template.format(
                    uid=urllib.parse.quote(uid, safe=""),
                    handle=urllib.parse.quote(handle, safe=""),
                    name=urllib.parse.quote(profile_name, safe=""),
                )
            except Exception as exc:
                errors.append(f"{template}: {exc}")
                continue

            try:
                body, _ = http_get(
                    url,
                    headers={
                        "User-Agent": LUOGU_USER_AGENT,
                        "Accept": "image/svg+xml,application/json,text/plain,*/*;q=0.8",
                        "Referer": "https://www.luogu.com.cn/",
                    },
                    cache_ttl_seconds=12 * 3600,
                    allow_stale_cache=True,
                )
                stats = self._extract_third_party_profile_stats(body, uid)
                stats.update(
                    {
                        "uid": uid,
                        "name": profile_name,
                        "ratingContests": previous.get("ratingContests") or [],
                        "solvedProblems": [],
                        "source": "luogu-third-party-fallback",
                        "fallbackSource": url,
                        "fallbackSyncedAt": utcnow(),
                        "_fallback": True,
                        "_warning": (
                            "洛谷主源失败，已使用第三方公开统计源降级；"
                            "仅更新总题数/难度分布，逐题、日期和比赛记录沿用本地缓存"
                        ),
                    }
                )
                return stats
            except Exception as exc:
                detail = str(exc).strip() or exc.__class__.__name__
                errors.append(f"{url}: {detail}")

        fallback_detail = "；".join(errors[:2]) if errors else "没有配置可用的第三方源"
        raise RuntimeError(f"{source_exc}；第三方降级统计也失败：{fallback_detail}") from source_exc

    @classmethod
    def _extract_third_party_profile_stats(cls, body: bytes, uid: str) -> dict:
        text = body.decode("utf-8", errors="ignore").strip()
        json_stats = cls._extract_third_party_json_stats(text)
        if json_stats:
            return json_stats

        plain = cls._plain_card_text(text)
        error_markers = [
            "FUNCTION_INVOCATION_FAILED",
            "server error",
            "数据获取异常",
            "无法获取练习数据",
            "不是一个合法uid",
            "隐私保护",
        ]
        has_error = any(marker.lower() in plain.lower() for marker in error_markers)

        passed_sum = cls._extract_labeled_count(plain, r"已通过")
        unpassed = cls._extract_labeled_count(plain, r"未通过")
        if passed_sum is None:
            passed_sum = cls._extract_labeled_count(plain, r"通过题数")

        labels = [
            "暂无评定",
            "入门",
            "普及-",
            "普及",
            "普及+/提高-",
            "提高",
            "提高+/省选-",
            "省选/NOI-",
            "NOI/NOI+/CTS",
        ]
        difficulty_counts: dict[str, int] = {}
        for index, label in enumerate(labels):
            count = cls._extract_labeled_count(plain, re.escape(label))
            if count is not None:
                difficulty_counts[str(index)] = count

        if passed_sum is None and difficulty_counts:
            passed_sum = sum(difficulty_counts.values())
        if passed_sum is None:
            if has_error:
                raise RuntimeError(plain[:180] or "第三方接口返回错误")
            raise RuntimeError("第三方接口没有返回可用的洛谷通过题数")

        stats = {
            "allTimeAccepted": int(passed_sum),
            "allTimeTried": int(passed_sum + max(0, unpassed or 0)),
            "difficultyCounts": difficulty_counts,
        }
        return stats

    @staticmethod
    def _extract_third_party_json_stats(text: str) -> dict:
        with contextlib.suppress(Exception):
            data = json.loads(text)
            if not isinstance(data, dict):
                return {}
            current_data = data.get("currentData") if isinstance(data.get("currentData"), dict) else data
            user = current_data.get("user") if isinstance(current_data.get("user"), dict) else {}
            passed = current_data.get("passed") or current_data.get("passedProblems")
            submitted = current_data.get("submitted") or current_data.get("submittedProblems")
            difficulty_counts: dict[str, int] = {}
            solved_count = int(user.get("passedProblemCount") or 0)
            if isinstance(passed, list):
                solved_count = max(solved_count, len(passed))
                for item in passed:
                    if isinstance(item, dict):
                        difficulty = str(item.get("difficulty") if item.get("difficulty") is not None else "unknown")
                        difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1
            tried_count = int(user.get("submittedProblemCount") or 0)
            if isinstance(submitted, list):
                tried_count = max(tried_count, len(submitted))
            if solved_count:
                return {
                    "allTimeAccepted": solved_count,
                    "allTimeTried": max(tried_count, solved_count),
                    "difficultyCounts": difficulty_counts,
                }
        return {}

    @staticmethod
    def _plain_card_text(text: str) -> str:
        text = html.unescape(text)
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _extract_labeled_count(text: str, label_pattern: str) -> int | None:
        patterns = [
            rf"{label_pattern}\s*[:：]?\s*([0-9][0-9,]*)\s*题?",
            rf"{label_pattern}\s+([0-9][0-9,]*)\s*题?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return int(match.group(1).replace(",", ""))
        return None

    def _resolve_user(self, handle: str) -> tuple[str, str]:
        if handle.isdigit():
            return handle, handle

        params = urllib.parse.urlencode({"keyword": handle})
        data = self._fetch_json(
            f"https://www.luogu.com.cn/api/user/search?{params}",
            headers=self._json_headers(),
            cache_ttl_seconds=24 * 3600,
        )
        users = self._search_users(data)
        exact = None
        for user in users:
            if str(user.get("name") or "").lower() == handle.lower():
                exact = user
                break
        selected = exact or (users[0] if users else None)
        if not selected or not selected.get("uid"):
            raise ValueError(f"没有找到洛谷用户：{handle}")
        return str(selected["uid"]), str(selected.get("name") or handle)

    def _fetch_profile_context(self, uid: str, path_suffix: str = "") -> dict:
        path = f"/user/{uid}{path_suffix}"
        separator = "&" if "?" in path else "?"
        body, _ = self._fetch_url(
            f"https://www.luogu.com.cn{path}{separator}_contentOnly=1",
            headers=self._headers(f"https://www.luogu.com.cn/user/{uid}"),
        )
        return self._parse_luogu_payload(body.decode("utf-8", errors="ignore"))

    def _fetch_json(self, url: str, headers: dict[str, str], cache_ttl_seconds: int | None = None):
        body, _ = self._fetch_url(url, headers=headers, cache_ttl_seconds=cache_ttl_seconds)
        return json.loads(body.decode("utf-8"))

    @staticmethod
    def _fetch_url(
        url: str,
        headers: dict[str, str],
        cache_ttl_seconds: int | None = None,
    ) -> tuple[bytes, str]:
        try:
            return proxy_http_get(
                url,
                headers=headers,
                proxy_url=LUOGU_PROXY_URL,
                proxy_token=LUOGU_PROXY_TOKEN,
                cache_ttl_seconds=cache_ttl_seconds,
                allow_stale_cache=True,
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 403 and not LUOGU_PROXY_URL:
                raise RuntimeError("洛谷 HTTP 403：当前服务器出口被拦截，请配置 LUOGU_CF_CLEARANCE 或 LUOGU_PROXY_URL") from exc
            raise
        except Exception as exc:
            if "403" in str(exc) and not LUOGU_PROXY_URL:
                raise RuntimeError("洛谷 HTTP 403：当前服务器出口被拦截，请配置 LUOGU_CF_CLEARANCE 或 LUOGU_PROXY_URL") from exc
            raise

    @staticmethod
    def _browser_headers(referer: str = "https://www.luogu.com.cn/") -> dict[str, str]:
        headers = {
            "User-Agent": LUOGU_USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": referer,
            "Sec-CH-UA": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"macOS"',
        }
        cookie = luogu_cookie_header()
        if cookie:
            headers["Cookie"] = cookie
        csrf_token = luogu_csrf_token()
        if csrf_token:
            headers["X-CSRF-Token"] = csrf_token
        return headers

    @classmethod
    def _json_headers(cls, referer: str = "https://www.luogu.com.cn/") -> dict[str, str]:
        headers = cls._browser_headers(referer)
        headers.update(
            {
                "Accept": "application/json,text/plain,*/*",
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
            }
        )
        return headers

    @classmethod
    def _headers(cls, referer: str = "https://www.luogu.com.cn/") -> dict[str, str]:
        headers = cls._browser_headers(referer)
        headers.update(
            {
                "Accept": "application/json,text/plain,*/*",
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
            }
        )
        headers.update(
            {
                "x-lentille-request": "content-only",
                "x-luogu-type": "content-only",
            }
        )
        return headers

    @classmethod
    def _parse_luogu_payload(cls, page: str) -> dict:
        text = page.strip()
        for candidate in [text, html.unescape(text)]:
            with contextlib.suppress(json.JSONDecodeError):
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data

        match = re.search(
            r'<script id="lentille-context" type="application/json">(.*?)</script>',
            page,
            flags=re.S,
        )
        if match:
            return json.loads(html.unescape(match.group(1)))

        for match in re.finditer(r"decodeURIComponent\((\"(?:[^\"\\]|\\.)*\")\)", page, flags=re.S):
            with contextlib.suppress(Exception):
                encoded = json.loads(match.group(1))
                decoded = urllib.parse.unquote(encoded)
                data = json.loads(decoded)
                if isinstance(data, dict):
                    return data

        limited_markers = ["验证码", "访问频繁", "禁止访问", "forbidden", "captcha", "challenge"]
        if any(marker in page.lower() for marker in limited_markers):
            raise RuntimeError("洛谷触发反爬或验证码，已保留本地缓存，稍后会自动重试")
        raise RuntimeError("洛谷公开页没有返回可解析的数据")

    @staticmethod
    def _context_data(context: dict) -> dict:
        data = context.get("data") if isinstance(context, dict) else {}
        if not isinstance(data, dict):
            data = {}
        current_data = data.get("currentData")
        if isinstance(current_data, dict):
            data = current_data
        elif isinstance(context.get("currentData"), dict):
            data = context["currentData"]
        return data

    @staticmethod
    def _daily_counts(data: dict) -> dict:
        daily_counts = data.get("dailyCounts") if isinstance(data, dict) else {}
        return daily_counts if isinstance(daily_counts, dict) else {}

    @staticmethod
    def _extract_profile_stats(uid: str, profile_name: str, data: dict, practice_data: dict) -> dict:
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        practice_user = practice_data.get("user") if isinstance(practice_data.get("user"), dict) else {}
        passed = practice_data.get("passed")
        submitted = practice_data.get("submitted")
        passed_items = passed if isinstance(passed, list) else []
        submitted_items = submitted if isinstance(submitted, list) else []
        solved_problem_keys: set[str] = set()
        solved_problems: list[dict] = []
        for item in passed_items:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("pid") or item.get("id") or "")
            if not pid:
                continue
            problem_type = str(item.get("type") or "")
            canonical_key = luogu_problem_key(pid, problem_type)
            if canonical_key:
                solved_problem_keys.add(canonical_key)
            solved_problems.append(
                {
                    "problemId": pid,
                    "source": problem_type or "luogu",
                    "name": str(item.get("name") or pid),
                    "canonicalKey": canonical_key,
                }
            )
        submitted_ids = {
            str(item.get("pid") or item.get("id") or "")
            for item in submitted_items
            if isinstance(item, dict) and (item.get("pid") or item.get("id"))
        }
        difficulty_counts: dict[str, int] = {}
        for item in passed_items:
            if not isinstance(item, dict):
                continue
            difficulty = str(item.get("difficulty") if item.get("difficulty") is not None else "unknown")
            difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1

        solved_count = len(solved_problem_keys) or int(practice_user.get("passedProblemCount") or user.get("passedProblemCount") or 0)
        submitted_count = len(submitted_ids) or int(practice_user.get("submittedProblemCount") or user.get("submittedProblemCount") or 0)
        return {
            "uid": uid,
            "name": str(practice_user.get("name") or user.get("name") or profile_name),
            "allTimeAccepted": solved_count,
            "allTimeTried": submitted_count,
            "difficultyCounts": difficulty_counts,
            "ratingContests": practice_data.get("elo") if isinstance(practice_data.get("elo"), list) else data.get("elo") or [],
            "solvedProblems": solved_problems,
            "source": "luogu-profile",
        }

    @classmethod
    def _search_users(cls, data) -> list[dict]:
        users: list[dict] = []

        def visit(value) -> None:
            if isinstance(value, dict):
                if value.get("uid") and value.get("name"):
                    users.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(data)
        unique = {}
        for user in users:
            unique[str(user.get("uid"))] = user
        return list(unique.values())

    @staticmethod
    def _date_to_ts(date_key: str) -> int | None:
        try:
            date = dt.date.fromisoformat(date_key)
        except ValueError:
            return None
        return int(dt.datetime(date.year, date.month, date.day, 12, tzinfo=dt.timezone.utc).timestamp())

    @staticmethod
    def _daily_count_pair(counts) -> tuple[int, int]:
        if isinstance(counts, list) and counts:
            accepted = int(counts[0] or 0)
            total = int(counts[1] if len(counts) > 1 else counts[0] or 0)
            return accepted, total
        if isinstance(counts, dict):
            accepted = int(counts.get("accepted") or counts.get("ac") or counts.get("passed") or 0)
            total = int(counts.get("total") or counts.get("submitted") or accepted)
            return accepted, total
        return 0, 0


class NowcoderAdapter(OJAdapter):
    key = "nowcoder"
    label = "牛客"
    handle_hint = "牛客竞赛个人 ID；可追加团队 ID，例如 2959795+307927467"

    def normalize_handle(self, handle: str) -> str:
        ids = self._extract_ids(handle)
        if not ids:
            raise ValueError("牛客请填写竞赛个人页数字 ID、团队 ID 或 profile/team 链接")
        return "+".join(ids)

    def fetch_submissions(self, handle: str, since_ts: int) -> list[dict]:
        submissions = []
        source_ids = self._submission_source_ids(handle)
        primary_id = source_ids[0]
        for source_id in source_ids:
            try:
                submissions.extend(self._fetch_practice_source(source_id, since_ts, primary_id))
            except Exception:
                if source_id == primary_id and not submissions:
                    raise
        return submissions

    def fetch_contests(self, handle: str, since_ts: int, submissions: list[dict]) -> list[dict]:
        contests = {}
        for source_id in self._submission_source_ids(handle):
            for finished in ["true", "false"]:
                page_no = 1
                while True:
                    params = urllib.parse.urlencode(
                        {
                            "uid": source_id,
                            "page": page_no,
                            "pageSize": 100,
                            "onlyJoinedFilter": "true",
                            "searchContestName": "",
                            "onlyRatingFilter": "false",
                            "contestEndFilter": finished,
                        }
                    )
                    try:
                        data = http_get_json(
                            f"https://ac.nowcoder.com/acm-heavy/acm/contest/profile/contest-joined-history?{params}",
                            headers=self._headers(f"https://ac.nowcoder.com/acm/contest/profile/{source_id}"),
                        )
                    except Exception:
                        break
                    if int(data.get("code") or 0) != 0:
                        break
                    payload = data.get("data") or {}
                    items = payload.get("dataList") or []
                    if not isinstance(items, list) or not items:
                        break

                    reached_older = False
                    for item in items:
                        contest_id = str(item.get("contestId") or "")
                        start_ms = int(item.get("startTime") or 0)
                        participated_at = start_ms // 1000 if start_ms > 10_000_000_000 else start_ms
                        if not contest_id or not participated_at:
                            continue
                        if participated_at < since_ts:
                            reached_older = True
                            continue
                        name = str(item.get("contestName") or f"牛客比赛 {contest_id}")
                        raw = {**item, "nowcoderSourceId": source_id}
                        contests[contest_id] = {
                            "remote_id": contest_id,
                            "contest_name": name,
                            "category": classify_contest(self.key, name, contest_id, raw),
                            "participated_at": participated_at,
                            "url": f"https://ac.nowcoder.com/acm/contest/{contest_id}",
                            "raw": raw,
                        }

                    page_info = payload.get("pageInfo") or {}
                    page_count = int(page_info.get("pageCount") or page_no)
                    if reached_older or page_no >= page_count:
                        break
                    page_no += 1
        return list(contests.values())

    def _fetch_practice_source(self, source_id: str, since_ts: int, primary_id: str) -> list[dict]:
        submissions = []
        page_no = 1
        last_page = None
        page_size = 200
        while True:
            params = urllib.parse.urlencode(
                {
                    "pageSize": page_size,
                    "search": "",
                    "statusTypeFilter": -1,
                    "languageCategoryFilter": -1,
                    "orderType": "DESC",
                    "page": page_no,
                }
            )
            url = f"https://ac.nowcoder.com/acm/contest/profile/{source_id}/practice-coding?{params}"
            body, _ = http_get(
                url,
                headers=self._headers(f"https://ac.nowcoder.com/acm/contest/profile/{source_id}"),
            )
            page = body.decode("utf-8", errors="ignore")
            page_submissions, reached_older = self._parse_practice_page(page, since_ts, source_id, primary_id)
            submissions.extend(page_submissions)
            last_page = last_page or self._last_page(page)
            if reached_older or page_no >= last_page:
                break
            page_no += 1
        return submissions

    def _parse_practice_page(
        self,
        page: str,
        since_ts: int,
        source_id: str | None = None,
        primary_id: str | None = None,
    ) -> tuple[list[dict], bool]:
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, flags=re.I | re.S)
        submissions = []
        reached_older = False
        for row in rows:
            text = strip_tags(row)
            if not re.search(r"20\d\d[-/]\d\d[-/]\d\d", text):
                continue
            submitted_at = parse_datetime_text(text, DISPLAY_TZ)
            if not submitted_at:
                continue
            if submitted_at < since_ts:
                reached_older = True
                continue
            id_match = re.search(r"(?:submissionId|submitId|id)=([0-9]+)", row)
            if not id_match:
                id_match = re.search(r"/(?:submission|view-submission)[^\"']*?([0-9]{5,})", row)
            problem_match = re.search(r"/acm/problem/([0-9A-Za-z_\\-]+)[^>]*>(.*?)</a>", row, flags=re.I | re.S)
            original_remote_id = id_match.group(1) if id_match else hashlib.sha1(text.encode("utf-8")).hexdigest()
            remote_id = original_remote_id
            if source_id and primary_id and source_id != primary_id:
                remote_id = f"{source_id}-{original_remote_id}"
            problem_id = problem_match.group(1) if problem_match else ""
            problem_name = strip_tags(problem_match.group(2)) if problem_match else self._guess_problem_name(text)
            verdict = "AC" if re.search(r"答案正确|通过|Accepted|AC\b", text, flags=re.I) else self._guess_verdict(text)
            submissions.append(
                {
                    "remote_id": remote_id,
                    "problem_id": problem_id,
                    "problem_name": f"{problem_id} {problem_name}".strip(),
                    "verdict": verdict,
                    "language": self._guess_language(text),
                    "submitted_at": submitted_at,
                    "url": f"https://ac.nowcoder.com/acm/contest/view-submission?submissionId={original_remote_id}&uid={source_id}" if original_remote_id.isdigit() else None,
                    "raw": {"text": text, "nowcoderSourceId": source_id or primary_id or ""},
                }
            )
        return submissions, reached_older

    @classmethod
    def _submission_source_ids(cls, handle: str) -> list[str]:
        ids = cls._extract_ids(handle)
        if not ids:
            return []
        primary_id = ids[0]
        for team_id in cls._discover_team_ids(primary_id):
            if team_id not in ids:
                ids.append(team_id)
        return ids[:8]

    @staticmethod
    def _headers(referer: str) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36 OJSubmissionWall/1.0",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": referer,
        }

    @classmethod
    def _discover_team_ids(cls, user_id: str) -> list[str]:
        params = urllib.parse.urlencode({"uid": user_id})
        try:
            data = http_get_json(
                f"https://ac.nowcoder.com/acm/contest/profile/user-team-list?{params}",
                headers=cls._headers(f"https://ac.nowcoder.com/acm/contest/profile/{user_id}/join-index"),
                cache_ttl_seconds=86400,
            )
        except Exception:
            return []
        team_ids: list[str] = []

        def visit(value) -> None:
            if isinstance(value, dict):
                team_id = value.get("teamId")
                if team_id:
                    team_ids.append(str(team_id))
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(data)
        unique = []
        for team_id in team_ids:
            if team_id != user_id and team_id not in unique:
                unique.append(team_id)
        return unique

    @staticmethod
    def _extract_ids(handle: str) -> list[str]:
        text = handle.strip()
        ids: list[str] = []
        for pattern in [
            r"/acm/contest/profile/(\d+)",
            r"/acm/team/view\?id=(\d+)",
            r"(?:^|[+,\s;])(\d{2,})(?=$|[+,\s;])",
        ]:
            for match in re.finditer(pattern, text):
                value = match.group(1)
                if value not in ids:
                    ids.append(value)
        if not ids:
            for value in re.findall(r"\d{3,}", text):
                if value not in ids:
                    ids.append(value)
        return ids[:8]

    @staticmethod
    def _last_page(page: str) -> int:
        pages = [int(value) for value in re.findall(r'data-page="([0-9]+)"', page)]
        return max(pages) if pages else 1

    @staticmethod
    def _guess_problem_name(text: str) -> str:
        cleaned = re.sub(r"20\d\d[-/]\d\d[-/]\d\d\s+\d\d:\d\d(?::\d\d)?", " ", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:80]

    @staticmethod
    def _guess_verdict(text: str) -> str:
        for token in ["编译错误", "答案错误", "运行错误", "超时", "格式错误", "部分正确"]:
            if token in text:
                return token
        return "UNKNOWN"

    @staticmethod
    def _guess_language(text: str) -> str:
        for token in ["GNU C++", "C++", "Python", "Java", "Go", "Rust", "C#"]:
            if token.lower() in text.lower():
                return token
        return ""


class VJudgeAdapter(OJAdapter):
    key = "vjudge"
    label = "VJudge"
    handle_hint = "VJudge 用户名，例如 tourist"

    def normalize_handle(self, handle: str) -> str:
        handle = handle.strip()
        if not re.match(r"^[0-9A-Za-z_\-]{2,64}$", handle):
            raise ValueError("VJudge 请填写用户名")
        return handle

    def fetch_submissions(self, handle: str, since_ts: int) -> list[dict]:
        submissions = self._fetch_recent_submissions(handle, since_ts)
        recent_solved = {
            item["problem_id"]
            for item in submissions
            if item.get("problem_id") and normalize_verdict(item.get("verdict")) == "AC"
        }
        for item in self._fetch_solve_detail(handle, since_ts):
            if item["problem_id"] in recent_solved:
                continue
            submissions.append(item)
        return submissions

    def _fetch_recent_submissions(self, handle: str, since_ts: int) -> list[dict]:
        submissions = []
        page_size = 100
        start = 0
        while True:
            params = urllib.parse.urlencode(
                {
                    "draw": 1,
                    "start": start,
                    "length": page_size,
                    "un": handle,
                    "OJId": "All",
                    "probNum": "",
                    "res": "all",
                    "language": "",
                    "onlyFollowee": "false",
                }
            )
            data = http_get_json(f"https://vjudge.net/status/data?{params}")
            items = data.get("data") if isinstance(data, dict) else []
            if not isinstance(items, list) or not items:
                break

            reached_older = False
            for item in items:
                submitted_ms = int(item.get("time") or 0)
                submitted_at = submitted_ms // 1000 if submitted_ms > 10_000_000_000 else submitted_ms
                if submitted_at and submitted_at < since_ts:
                    reached_older = True
                    continue
                run_id = str(item.get("runId") or "")
                oj = str(item.get("oj") or "")
                prob_num = str(item.get("probNum") or "")
                problem_id = f"{oj}-{prob_num}".strip("-")
                status_type = item.get("statusType")
                verdict = "AC" if status_type == 0 else normalize_verdict(item.get("status"))
                submissions.append(
                    {
                        "remote_id": run_id,
                        "problem_id": problem_id,
                        "problem_name": problem_id,
                        "verdict": verdict,
                        "language": item.get("language") or "",
                        "submitted_at": submitted_at,
                        "url": f"https://vjudge.net/solution/{run_id}" if run_id else "",
                        "raw": item,
                    }
                )

            if reached_older or len(items) < page_size:
                break
            start += page_size
        return submissions

    def _fetch_solve_detail(self, handle: str, since_ts: int) -> list[dict]:
        data = http_get_json(
            f"https://vjudge.net/user/solveDetail2/{urllib.parse.quote(handle)}",
            cache_ttl_seconds=3600,
        )
        if not isinstance(data, list):
            raise RuntimeError("VJudge solveDetail2 返回格式异常")

        submissions = []
        seen = set()
        for item in data:
            if not isinstance(item, list) or len(item) < 3 or not item[2]:
                continue
            oj = str(item[0] or "").strip()
            prob_num = str(item[1] or "").strip()
            if not oj or not prob_num:
                continue
            submitted_ms = int(item[2] or 0)
            submitted_at = submitted_ms // 1000 if submitted_ms > 10_000_000_000 else submitted_ms
            if submitted_at < since_ts:
                continue
            problem_id = f"{oj}-{prob_num}"
            if problem_id in seen:
                continue
            seen.add(problem_id)
            submissions.append(
                {
                    "remote_id": f"solve-{problem_id}",
                    "problem_id": problem_id,
                    "problem_name": problem_id,
                    "verdict": "AC",
                    "language": "",
                    "submitted_at": submitted_at,
                    "url": f"https://vjudge.net/problem/{urllib.parse.quote(problem_id)}",
                    "raw": {
                        "oj": oj,
                        "probNum": prob_num,
                        "firstAcceptedAt": submitted_ms,
                        "syntheticFromSolveDetail2": True,
                    },
                }
            )
        return submissions

    def fetch_contests(self, handle: str, since_ts: int, submissions: list[dict]) -> list[dict]:
        contests = {}
        for item in submissions:
            raw = item.get("raw") or {}
            contest_id = str(raw.get("contestId") or "")
            submitted_at = int(item.get("submitted_at") or 0)
            if not contest_id or submitted_at < since_ts:
                continue
            name = f"VJudge Contest {contest_id}"
            contests[contest_id] = {
                "remote_id": contest_id,
                "contest_name": name,
                "category": classify_contest(self.key, name, contest_id, raw),
                "participated_at": submitted_at,
                "url": f"https://vjudge.net/contest/{contest_id}",
                "raw": raw,
            }
        return list(contests.values())


class LOJAdapter(OJAdapter):
    key = "loj"
    label = "LOJ"
    handle_hint = "LOJ 用户名，例如 example_user"

    def normalize_handle(self, handle: str) -> str:
        handle = handle.strip()
        if not re.match(r"^[0-9A-Za-z_\-.]{2,64}$", handle):
            raise ValueError("LOJ 请填写用户名")
        return handle

    def fetch_submissions(self, handle: str, since_ts: int) -> list[dict]:
        submissions = []
        page_size = min(max(FETCH_LIMIT, 1), 100)
        max_id = None
        while True:
            payload = {
                "submitter": handle,
                "locale": "zh_CN",
                "takeCount": page_size,
            }
            if max_id is not None:
                payload["maxId"] = max_id
            data = http_post_json("https://api.loj.ac/api/submission/querySubmission", payload)
            if data.get("error"):
                raise RuntimeError(f"LOJ 返回失败：{data.get('error')}")
            items = data.get("submissions") if isinstance(data, dict) else []
            if not isinstance(items, list) or not items:
                break

            reached_older = False
            for item in items:
                submitted_at = parse_iso_datetime(str(item.get("submitTime") or "")) or 0
                if submitted_at and submitted_at < since_ts:
                    reached_older = True
                    continue
                problem = item.get("problem") or {}
                display_id = problem.get("displayId") or problem.get("id") or ""
                problem_id = f"P{display_id}" if display_id else ""
                title = str(item.get("problemTitle") or problem_id)
                remote_id = str(item.get("id") or "")
                if not remote_id or not submitted_at:
                    continue
                submissions.append(
                    {
                        "remote_id": remote_id,
                        "problem_id": problem_id,
                        "problem_name": f"{problem_id} {title}".strip(),
                        "verdict": normalize_verdict(item.get("status")),
                        "language": str(item.get("codeLanguage") or "").upper(),
                        "submitted_at": submitted_at,
                        "url": f"https://loj.ac/s/{remote_id}",
                        "raw": item,
                    }
                )

            if reached_older or not data.get("hasSmallerId"):
                break
            last_id = items[-1].get("id")
            if not last_id:
                break
            max_id = int(last_id) - 1
        return submissions


class QOJAdapter(OJAdapter):
    key = "qoj"
    label = "QOJ"
    handle_hint = "QOJ 用户名；Cloudflare 下需管理员配置专用 Cookie，公开站不建议收集用户登录态"

    def normalize_handle(self, handle: str) -> str:
        handle = handle.strip()
        if not re.match(r"^[0-9A-Za-z_\-.]{2,64}$", handle):
            raise ValueError("QOJ 请填写用户名")
        return handle

    def fetch_submissions(self, handle: str, since_ts: int) -> list[dict]:
        cookie = normalize_cookie_header(os.environ.get("QOJ_COOKIE", "").strip(), "UOJSESSID")
        if not cookie:
            raise RuntimeError("QOJ 当前有 Cloudflare 校验；公开部署不建议收集用户登录态，未配置管理员专用 Cookie 时无法精确同步")

        submissions = []
        seen = set()
        for page_no in range(1, 201):
            params = urllib.parse.urlencode({"submitter": handle, "page": page_no, "locale": "en"})
            body, _ = http_get(
                f"https://qoj.ac/submissions?{params}",
                headers={
                    "Cookie": cookie,
                    "Referer": "https://qoj.ac/",
                    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
                },
            )
            page = body.decode("utf-8", errors="ignore")
            if "Just a moment" in page or "__cf_chl" in page or "challenge-platform" in page:
                raise RuntimeError("QOJ_COOKIE 未通过 Cloudflare 校验，无法精确同步 QOJ")
            page_submissions, reached_older = self._parse_submissions_page(page, since_ts)
            fresh = [item for item in page_submissions if item["remote_id"] not in seen]
            for item in fresh:
                seen.add(item["remote_id"])
            submissions.extend(fresh)
            if reached_older or not fresh:
                break
        return submissions

    def fetch_contests(self, handle: str, since_ts: int, submissions: list[dict]) -> list[dict]:
        contests = {}
        for item in submissions:
            raw = item.get("raw") or {}
            contest_id = str(raw.get("contest_id") or "")
            submitted_at = int(item.get("submitted_at") or 0)
            if not contest_id or submitted_at < since_ts:
                continue
            name = str(raw.get("contest_name") or f"QOJ Contest {contest_id}")
            contests[contest_id] = {
                "remote_id": contest_id,
                "contest_name": name,
                "category": classify_contest(self.key, name, contest_id, raw),
                "participated_at": submitted_at,
                "url": f"https://qoj.ac/contest/{contest_id}",
                "raw": raw,
            }
        return list(contests.values())

    def _parse_submissions_page(self, page: str, since_ts: int) -> tuple[list[dict], bool]:
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, flags=re.I | re.S)
        submissions = []
        reached_older = False
        for row in rows:
            text = strip_tags(row)
            submitted_at = parse_datetime_text(text)
            if not submitted_at:
                continue
            if submitted_at < since_ts:
                reached_older = True
                continue
            links = re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', row, flags=re.I | re.S)
            submission_id = ""
            problem_id = ""
            problem_name = ""
            contest_id = ""
            contest_name = ""
            for href, label in links:
                clean_label = strip_tags(label)
                if not submission_id:
                    match = re.search(r"/submission[s]?/([0-9]+)", href)
                    if match:
                        submission_id = match.group(1)
                match = re.search(r"/problem/([0-9A-Za-z_\-.]+)", href)
                if match and not problem_id:
                    problem_id = match.group(1)
                    problem_name = clean_label or problem_id
                match = re.search(r"/contest/([0-9A-Za-z_\-.]+)", href)
                if match and not contest_id:
                    contest_id = match.group(1)
                    contest_name = clean_label or contest_id
            remote_id = submission_id or hashlib.sha1(row.encode("utf-8")).hexdigest()
            verdict = self._guess_verdict(text)
            language = self._guess_language(text)
            submissions.append(
                {
                    "remote_id": remote_id,
                    "problem_id": problem_id,
                    "problem_name": problem_name or problem_id or "QOJ Problem",
                    "verdict": verdict,
                    "language": language,
                    "submitted_at": submitted_at,
                    "url": f"https://qoj.ac/submission/{remote_id}" if submission_id else "https://qoj.ac/submissions",
                    "raw": {
                        "text": text,
                        "contest_id": contest_id,
                        "contest_name": contest_name,
                    },
                }
            )
        return submissions, reached_older

    @staticmethod
    def _guess_verdict(text: str) -> str:
        aliases = [
            ("Accepted", "AC"),
            ("Wrong Answer", "WRONG_ANSWER"),
            ("Runtime Error", "RUNTIME_ERROR"),
            ("Compile Error", "COMPILATION_ERROR"),
            ("Compilation Error", "COMPILATION_ERROR"),
            ("Time Limit Exceeded", "TIME_LIMIT_EXCEEDED"),
            ("Memory Limit Exceeded", "MEMORY_LIMIT_EXCEEDED"),
            ("Output Limit Exceeded", "OUTPUT_LIMIT_EXCEEDED"),
            ("Presentation Error", "PRESENTATION_ERROR"),
        ]
        for token, verdict in aliases:
            if token.lower() in text.lower():
                return verdict
        return "UNKNOWN"

    @staticmethod
    def _guess_language(text: str) -> str:
        for token in ["C++", "GNU", "Python", "PyPy", "Java", "Rust", "Go", "Kotlin", "C#"]:
            if token.lower() in text.lower():
                return token
        return ""


ADAPTERS: dict[str, OJAdapter] = {
    "codeforces": CodeforcesAdapter(),
    "atcoder": AtCoderAdapter(),
    "nowcoder": NowcoderAdapter(),
    "luogu": LuoguAdapter(),
    "vjudge": VJudgeAdapter(),
    "loj": LOJAdapter(),
    "qoj": QOJAdapter(),
}


def platform_meta() -> list[dict]:
    return [
        {"key": adapter.key, "label": adapter.label, "hint": adapter.handle_hint}
        for adapter in ADAPTERS.values()
    ]


def create_session(conn: sqlite3.Connection, owner_type: str, owner_id: str, days: int) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    conn.execute(
        """
        INSERT INTO sessions(token_hash, owner_type, owner_id, created_at, expires_at)
        VALUES(?, ?, ?, ?, ?)
        """,
        (sha256_hex(token), owner_type, str(owner_id), now, now + days * 86400),
    )
    return token


def delete_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (sha256_hex(token),))


def create_verification_token(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    conn.execute(
        """
        INSERT INTO verification_tokens(token_hash, user_id, expires_at, created_at)
        VALUES(?, ?, ?, ?)
        """,
        (sha256_hex(token), user_id, now + 24 * 3600, now),
    )
    return token


def env_value(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def is_placeholder_env(value: str) -> bool:
    text = value.strip()
    return not text or text.lower() in SMTP_PLACEHOLDERS


def send_verification_email(email: str, display_name: str, verify_url: str) -> bool:
    smtp_host = env_value("SMTP_HOST")
    smtp_user = env_value("SMTP_USER")
    smtp_password = env_value("SMTP_PASSWORD")
    smtp_from = env_value("SMTP_FROM", smtp_user)
    if is_placeholder_env(smtp_host) or is_placeholder_env(smtp_from) or is_placeholder_env(smtp_password):
        print(f"[mail] SMTP 未配置或仍是占位值，验证链接: {verify_url}", flush=True)
        return False
    try:
        smtp_port = int(env_value("SMTP_PORT", "587"))
    except ValueError:
        print(f"[mail] SMTP_PORT 配置错误，验证链接: {verify_url}", flush=True)
        return False
    smtp_ssl = env_value("SMTP_SSL").lower() in {"1", "true", "yes"} or smtp_port == 465
    smtp_tls = env_value("SMTP_TLS", "true").lower() not in {"0", "false", "no"}

    msg = EmailMessage()
    msg["Subject"] = "验证你的 OJ Submission Wall 邮箱"
    msg["From"] = smtp_from
    msg["To"] = email
    msg.set_content(
        f"{display_name}，你好：\n\n"
        f"请打开下面的链接完成邮箱验证，链接 24 小时内有效：\n{verify_url}\n\n"
        f"如果不是你本人注册，可以忽略这封邮件。\n"
    )

    context = ssl.create_default_context()
    smtp_cls = smtplib.SMTP_SSL if smtp_ssl else smtplib.SMTP
    try:
        with smtp_cls(smtp_host, smtp_port, timeout=20, context=context) if smtp_ssl else smtp_cls(smtp_host, smtp_port, timeout=20) as smtp:
            if not smtp_ssl and smtp_tls:
                smtp.starttls(context=context)
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        return True
    except Exception as exc:
        print(f"[mail] SMTP 发送失败: {exc}; 验证链接: {verify_url}", flush=True)
        return False



def owner_display_name(conn: sqlite3.Connection, owner_type: str, owner_id: str) -> str:
    if owner_type == "user":
        row = conn.execute("SELECT display_name FROM users WHERE id = ?", (owner_id,)).fetchone()
    else:
        row = conn.execute("SELECT display_name FROM guests WHERE id = ?", (owner_id,)).fetchone()
    return row["display_name"] if row else "未知成员"


def can_view_real_name(principal: dict | None, owner: dict) -> bool:
    if not principal:
        return False
    if principal["type"] == owner["ownerType"] and str(principal["id"]) == str(owner["ownerId"]):
        return True
    viewer_team = normalize_team_name(principal.get("teamName"), "")
    owner_team = normalize_team_name(owner.get("teamName"), "")
    if not viewer_team or viewer_team in {DEFAULT_TEAM_NAME, GUEST_TEAM_NAME}:
        return False
    return viewer_team == owner_team


def get_current_principal(handler) -> dict | None:
    cookie_header = handler.headers.get("Cookie", "")
    jar = cookies.SimpleCookie()
    with contextlib.suppress(cookies.CookieError):
        jar.load(cookie_header)
    morsel = jar.get(SESSION_COOKIE)
    if not morsel:
        return None
    token = morsel.value
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT owner_type, owner_id, expires_at
            FROM sessions
            WHERE token_hash = ?
            """,
            (sha256_hex(token),),
        ).fetchone()
        if not row or row["expires_at"] < utcnow():
            delete_session(conn, token)
            return None
        if row["owner_type"] == "user":
            user = conn.execute(
                "SELECT id, username, email, display_name, real_name, verified, team_name FROM users WHERE id = ?",
                (row["owner_id"],),
            ).fetchone()
            if not user:
                return None
            return {
                "type": "user",
                "id": str(user["id"]),
                "username": user["username"],
                "displayName": user["display_name"],
                "realName": user["real_name"] or "",
                "teamName": user["team_name"] or DEFAULT_TEAM_NAME,
                "verified": True,
            }
        guest = conn.execute(
            "SELECT id, display_name, real_name, team_name FROM guests WHERE id = ?",
            (row["owner_id"],),
        ).fetchone()
        if not guest:
            return None
        return {
            "type": "guest",
            "id": guest["id"],
            "displayName": guest["display_name"],
            "realName": guest["real_name"] or "",
            "teamName": guest["team_name"] or GUEST_TEAM_NAME,
            "verified": False,
        }


def set_session_cookie(handler, token: str, max_age: int) -> None:
    attrs = [
        f"{SESSION_COOKIE}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={max_age}",
    ]
    if os.environ.get("COOKIE_SECURE", "").lower() in {"1", "true", "yes"}:
        attrs.append("Secure")
    handler.send_header("Set-Cookie", "; ".join(attrs))


def clear_session_cookie(handler) -> None:
    handler.send_header(
        "Set-Cookie",
        f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
    )


def read_json_body(handler) -> dict:
    length = int(handler.headers.get("Content-Length") or "0")
    if length > 64 * 1024:
        raise ValueError("请求体过大")
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        raise ValueError("JSON 格式不正确")
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return data


def luogu_auth_from_payload(handler, data: dict) -> dict | None:
    cookie = str(
        data.get("luoguCookie")
        or data.get("luogu_cookie")
        or handler.headers.get("X-Luogu-Cookie", "")
        or ""
    ).strip()
    csrf_token = str(
        data.get("luoguCsrfToken")
        or data.get("luogu_csrf_token")
        or data.get("luoguCsrf")
        or handler.headers.get("X-Luogu-CSRF-Token", "")
        or ""
    ).strip()
    return compact_luogu_auth({"cookie": cookie, "csrfToken": csrf_token})


def add_or_restore_handle(conn: sqlite3.Connection, principal: dict, platform: str, handle: str) -> sqlite3.Row:
    if platform not in ADAPTERS:
        raise ValueError("暂不支持该 OJ")
    normalized = ADAPTERS[platform].normalize_handle(handle)
    now = utcnow()
    conn.execute(
        """
        INSERT INTO handles(owner_type, owner_id, platform, handle, active, created_at)
        VALUES(?, ?, ?, ?, 1, ?)
        ON CONFLICT(owner_type, owner_id, platform, handle)
        DO UPDATE SET active = 1, last_error = NULL
        """,
        (principal["type"], str(principal["id"]), platform, normalized, now),
    )
    return conn.execute(
        """
        SELECT * FROM handles
        WHERE owner_type = ? AND owner_id = ? AND platform = ? AND handle = ?
        """,
        (principal["type"], str(principal["id"]), platform, normalized),
    ).fetchone()


def get_handle_rows(conn: sqlite3.Connection, principal: dict | None = None, include_guests: bool = False):
    if include_guests:
        return conn.execute("SELECT * FROM handles WHERE active = 1 ORDER BY created_at").fetchall()
    if principal and principal["type"] == "guest":
        return conn.execute(
            """
            SELECT * FROM handles
            WHERE active = 1 AND (owner_type = 'user' OR (owner_type = 'guest' AND owner_id = ?))
            ORDER BY created_at
            """,
            (principal["id"],),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM handles WHERE active = 1 AND owner_type = 'user' ORDER BY created_at"
    ).fetchall()


def sync_handle_row(conn: sqlite3.Connection, row: sqlite3.Row, force: bool = False, full: bool = False) -> dict:
    now = utcnow()
    has_error = bool(row["last_error"])
    if not force and not has_error and row["last_sync_at"] and now - int(row["last_sync_at"]) < SYNC_MIN_AGE_SECONDS:
        return {"handleId": row["id"], "platform": row["platform"], "handle": row["handle"], "skipped": True}

    adapter = ADAPTERS[row["platform"]]
    row = canonicalize_handle_row(conn, row, adapter)
    conn.commit()
    max_row = conn.execute(
        """
        SELECT MAX(submitted_at) AS max_submitted_at
        FROM submissions
        WHERE owner_type = ? AND owner_id = ? AND platform = ? AND handle = ?
        """,
        (row["owner_type"], row["owner_id"], row["platform"], row["handle"]),
    ).fetchone()
    default_since = now - FETCH_LOOKBACK_DAYS * 86400
    previous_error = str(row["last_error"] or "")
    needs_full_retry = "比赛记录同步失败" in previous_error
    newest_local_submission_at = int(max_row["max_submitted_at"] or 0)
    overlap_seconds = max(0, SYNC_INCREMENTAL_OVERLAP_SECONDS)
    incremental_since = (
        max(default_since, newest_local_submission_at - overlap_seconds)
        if newest_local_submission_at
        else default_since
    )
    since_ts = default_since if full or (force and needs_full_retry) else incremental_since
    previous_stats_json = row["stats_json"] if "stats_json" in row.keys() else None
    previous_profile_stats = {}
    if previous_stats_json:
        with contextlib.suppress(Exception):
            parsed_stats = json.loads(previous_stats_json)
            if isinstance(parsed_stats, dict):
                previous_profile_stats = parsed_stats

    try:
        reset_http_stale_hits()
        if hasattr(adapter, "set_previous_stats"):
            adapter.set_previous_stats(row["handle"], previous_stats_json)
        submissions = adapter.fetch_submissions(row["handle"], since_ts)
        profile_stats = adapter.fetch_profile_stats(row["handle"], submissions)
        profile_warning = ""
        profile_is_fallback = False
        if isinstance(profile_stats, dict):
            profile_warning = str(profile_stats.pop("_warning", "") or "")
            profile_is_fallback = bool(profile_stats.pop("_fallback", False))
        use_previous_exact_stats = (
            profile_is_fallback
            and bool(previous_stats_json)
            and previous_profile_stats.get("source") != "luogu-third-party-fallback"
        )
        if profile_stats and not use_previous_exact_stats:
            stats_json = json.dumps(profile_stats, ensure_ascii=False)
        else:
            stats_json = previous_stats_json

        contests = []
        contest_error = ""
        try:
            contest_submissions = submissions
            previous_codeforces_results = {}
            if adapter.key == "codeforces":
                stored_submissions = conn.execute(
                    """
                    SELECT remote_id, submitted_at, raw_json
                    FROM submissions
                    WHERE owner_type = ? AND owner_id = ? AND platform = ? AND handle = ?
                      AND submitted_at >= ?
                    """,
                    (
                        row["owner_type"],
                        row["owner_id"],
                        row["platform"],
                        row["handle"],
                        default_since,
                    ),
                ).fetchall()
                merged_submissions = {
                    str(item.get("remote_id") or ""): item
                    for item in submissions
                    if item.get("remote_id")
                }
                for stored in stored_submissions:
                    remote_id = str(stored["remote_id"] or "")
                    if not remote_id or remote_id in merged_submissions:
                        continue
                    with contextlib.suppress(Exception):
                        raw = json.loads(stored["raw_json"] or "{}")
                        if isinstance(raw, dict):
                            merged_submissions[remote_id] = {
                                "remote_id": remote_id,
                                "submitted_at": int(stored["submitted_at"] or 0),
                                "raw": raw,
                            }
                contest_submissions = list(merged_submissions.values())
                stored_contests = conn.execute(
                    """
                    SELECT remote_id, raw_json
                    FROM contests
                    WHERE owner_type = ? AND owner_id = ? AND platform = ? AND handle = ?
                    """,
                    (row["owner_type"], row["owner_id"], row["platform"], row["handle"]),
                ).fetchall()
                for stored in stored_contests:
                    with contextlib.suppress(Exception):
                        raw = json.loads(stored["raw_json"] or "{}")
                        if isinstance(raw, dict) and isinstance(raw.get("virtualResult"), dict):
                            previous_codeforces_results[str(stored["remote_id"])] = raw["virtualResult"]
            contests = adapter.fetch_contests(row["handle"], since_ts, contest_submissions)
            for item in contests:
                raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
                previous_result = previous_codeforces_results.get(str(item.get("remote_id") or ""))
                if previous_result and not raw.get("ratingChange") and not raw.get("virtualResult"):
                    raw["virtualResult"] = previous_result
        except Exception as exc:
            detail = str(exc)[:300] or exc.__class__.__name__
            contest_error = f"比赛记录同步失败：{detail}"
        stale_hits = http_stale_hits()

        inserted = 0
        for item in submissions:
            remote_id = str(item.get("remote_id") or "")
            submitted_at = int(item.get("submitted_at") or 0)
            if not remote_id or not submitted_at:
                continue
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO submissions(
                    owner_type, owner_id, platform, handle, remote_id, problem_id,
                    problem_name, verdict, language, submitted_at, url, raw_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["owner_type"],
                    row["owner_id"],
                    row["platform"],
                    row["handle"],
                    remote_id,
                    item.get("problem_id") or "",
                    item.get("problem_name") or "",
                    item.get("verdict") or "UNKNOWN",
                    item.get("language") or "",
                    submitted_at,
                    item.get("url") or "",
                    json.dumps(item.get("raw") or {}, ensure_ascii=False),
                    now,
                ),
            )
            inserted += cur.rowcount

        inserted_contests = 0
        for item in contests:
            remote_id = str(item.get("remote_id") or "")
            participated_at = int(item.get("participated_at") or 0)
            if not remote_id or not participated_at:
                continue
            cur = conn.execute(
                """
                INSERT INTO contests(
                    owner_type, owner_id, platform, handle, remote_id, contest_name,
                    category, participated_at, url, raw_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_type, owner_id, platform, handle, remote_id)
                DO UPDATE SET
                    contest_name = excluded.contest_name,
                    category = excluded.category,
                    participated_at = excluded.participated_at,
                    url = excluded.url,
                    raw_json = excluded.raw_json
                """,
                (
                    row["owner_type"],
                    row["owner_id"],
                    row["platform"],
                    row["handle"],
                    remote_id,
                    item.get("contest_name") or remote_id,
                    item.get("category") or classify_contest(row["platform"], str(item.get("contest_name") or ""), remote_id, item.get("raw") or {}),
                    participated_at,
                    item.get("url") or "",
                    json.dumps(item.get("raw") or {}, ensure_ascii=False),
                    now,
                ),
            )
            inserted_contests += cur.rowcount
        warnings = []
        result = {
            "handleId": row["id"],
            "platform": row["platform"],
            "handle": row["handle"],
            "fetched": len(submissions),
            "inserted": inserted,
            "contestsFetched": len(contests),
            "contestsInserted": inserted_contests,
        }
        if stale_hits:
            cache_as_of = min(int(item.get("fetchedAt") or now) for item in stale_hits)
            warnings.append(f"平台接口异常，使用本地缓存；缓存时间 {iso_from_ts(cache_as_of)}")
            result.update({"cached": True, "cacheAsOf": iso_from_ts(cache_as_of)})
        if contest_error:
            warnings.append(contest_error)
            result.update({"partial": True})
        if profile_warning:
            warnings.append(profile_warning)
            result.update({"partial": True, "fallback": profile_is_fallback})
            if use_previous_exact_stats and row["last_sync_at"]:
                result.update({"cached": True, "cacheAsOf": iso_from_ts(int(row["last_sync_at"]))})
        has_luogu_record_list = bool(
            row["platform"] == "luogu"
            and any((item.get("raw") or {}).get("source") == "luogu-record-list" for item in submissions)
        )
        if has_luogu_record_list:
            conn.execute(
                """
                DELETE FROM submissions
                WHERE owner_type = ?
                  AND owner_id = ?
                  AND platform = ?
                  AND handle = ?
                  AND problem_id LIKE 'luogu-activity-%'
                """,
                (row["owner_type"], row["owner_id"], row["platform"], row["handle"]),
            )
        if warnings:
            error = "；".join(warnings)
            update_sync_at = int(row["last_sync_at"] or now) if use_previous_exact_stats else now
            conn.execute(
                "UPDATE handles SET last_sync_at = ?, last_error = ?, stats_json = ? WHERE id = ?",
                (update_sync_at, error, stats_json, row["id"]),
            )
            result.update({"warning": error})
        else:
            conn.execute(
                "UPDATE handles SET last_sync_at = ?, last_error = NULL, stats_json = ? WHERE id = ?",
                (now, stats_json, row["id"]),
            )
        return result
    except Exception as exc:
        error = str(exc)[:500] or exc.__class__.__name__
        conn.execute(
            "UPDATE handles SET last_error = ? WHERE id = ?",
            (error, row["id"]),
        )
        return {
            "handleId": row["id"],
            "platform": row["platform"],
            "handle": row["handle"],
            "error": error,
        }


def sync_targets(
    principal: dict | None = None,
    force: bool = False,
    include_guests: bool = False,
    full: bool = False,
    luogu_auth: dict | None = None,
) -> list[dict]:
    results: list[dict] = []
    if not SYNC_LOCK.acquire(blocking=False):
        return [{"busy": True}]
    try:
        with luogu_request_auth(luogu_auth):
            with connect_db() as conn:
                rows = get_handle_rows(conn, principal=principal, include_guests=include_guests)
                for row in rows:
                    results.append(sync_handle_row(conn, row, force=force, full=full))
                    conn.commit()
        clear_overview_memory_cache()
    finally:
        SYNC_LOCK.release()
    return results


def canonicalize_handle_row(conn: sqlite3.Connection, row: sqlite3.Row, adapter: OJAdapter) -> sqlite3.Row:
    canonicalizer = getattr(adapter, "canonicalize_handle", None)
    if not canonicalizer:
        return row
    old_handle = str(row["handle"] or "")
    try:
        result = canonicalizer(old_handle)
    except Exception:
        return row
    if not result:
        return row
    new_handle, display_name = result
    new_handle = str(new_handle or "").strip()
    if not new_handle or new_handle == old_handle:
        return row

    stats_json = canonicalized_handle_stats_json(row, new_handle, display_name)
    existing = conn.execute(
        """
        SELECT *
        FROM handles
        WHERE owner_type = ? AND owner_id = ? AND platform = ? AND handle = ?
        """,
        (row["owner_type"], row["owner_id"], row["platform"], new_handle),
    ).fetchone()
    if existing and existing["id"] != row["id"]:
        migrate_handle_history(conn, row, new_handle)
        conn.execute(
            """
            UPDATE handles
            SET active = 1,
                last_error = NULL,
                stats_json = COALESCE(stats_json, ?),
                last_sync_at = CASE
                    WHEN COALESCE(last_sync_at, 0) >= COALESCE(?, 0) THEN last_sync_at
                    ELSE ?
                END
            WHERE id = ?
            """,
            (stats_json, row["last_sync_at"], row["last_sync_at"], existing["id"]),
        )
        conn.execute(
            "UPDATE handles SET active = 0, last_error = ? WHERE id = ?",
            (f"已自动合并到 {new_handle}", row["id"]),
        )
        refreshed = conn.execute("SELECT * FROM handles WHERE id = ?", (existing["id"],)).fetchone()
        return refreshed or existing

    migrate_handle_history(conn, row, new_handle)
    conn.execute(
        "UPDATE handles SET handle = ?, stats_json = ? WHERE id = ?",
        (new_handle, stats_json, row["id"]),
    )
    updated = conn.execute("SELECT * FROM handles WHERE id = ?", (row["id"],)).fetchone()
    return updated or row


def canonicalized_handle_stats_json(row: sqlite3.Row, new_handle: str, display_name: str) -> str | None:
    stats = {}
    if row["stats_json"]:
        with contextlib.suppress(Exception):
            parsed = json.loads(row["stats_json"])
            if isinstance(parsed, dict):
                stats = parsed
    if display_name and not stats.get("name"):
        stats["name"] = display_name
    if row["platform"] == "luogu":
        stats["uid"] = new_handle
    return json.dumps(stats, ensure_ascii=False) if stats else row["stats_json"]


def migrate_handle_history(conn: sqlite3.Connection, row: sqlite3.Row, new_handle: str) -> None:
    old_handle = str(row["handle"] or "")
    if not old_handle or old_handle == new_handle:
        return
    params = (row["owner_type"], row["owner_id"], row["platform"], old_handle, new_handle)
    for table in ["submissions", "contests"]:
        conn.execute(
            f"""
            DELETE FROM {table}
            WHERE owner_type = ? AND owner_id = ? AND platform = ? AND handle = ?
              AND EXISTS (
                SELECT 1
                FROM {table} AS target
                WHERE target.owner_type = {table}.owner_type
                  AND target.owner_id = {table}.owner_id
                  AND target.platform = {table}.platform
                  AND target.handle = ?
                  AND target.remote_id = {table}.remote_id
              )
            """,
            params,
        )
        conn.execute(
            f"""
            UPDATE {table}
            SET handle = ?
            WHERE owner_type = ? AND owner_id = ? AND platform = ? AND handle = ?
            """,
            (new_handle, row["owner_type"], row["owner_id"], row["platform"], old_handle),
        )


def get_owned_handle_row(conn: sqlite3.Connection, principal: dict, handle_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM handles
        WHERE id = ? AND owner_type = ? AND owner_id = ? AND active = 1
        """,
        (handle_id, principal["type"], str(principal["id"])),
    ).fetchone()


def sync_one_handle(
    principal: dict,
    handle_id: int,
    force: bool = True,
    full: bool = False,
    luogu_auth: dict | None = None,
) -> dict:
    if not SYNC_LOCK.acquire(blocking=False):
        return {"handleId": handle_id, "busy": True}
    try:
        with luogu_request_auth(luogu_auth):
            with connect_db() as conn:
                row = get_owned_handle_row(conn, principal, handle_id)
                if not row:
                    raise ValueError("没有找到这个账号绑定，可能已经移除")
                result = sync_handle_row(conn, row, force=force, full=full)
                clear_overview_memory_cache()
                return result
    finally:
        SYNC_LOCK.release()


def public_sync_job(job: dict | None) -> dict | None:
    if not job:
        return None
    payload = {
        "id": job.get("id"),
        "scope": job.get("scope"),
        "handleId": job.get("handle_id"),
        "force": bool(job.get("force")),
        "full": bool(job.get("full")),
        "queuedAt": iso_from_ts(job.get("queued_at")),
        "startedAt": iso_from_ts(job.get("started_at")),
        "finishedAt": iso_from_ts(job.get("finished_at")),
    }
    if job.get("error"):
        payload["error"] = str(job.get("error"))[:300]
    if job.get("result_count") is not None:
        payload["resultCount"] = int(job.get("result_count") or 0)
    principal = job.get("principal") if isinstance(job.get("principal"), dict) else None
    if principal:
        payload["principalType"] = principal.get("type")
        payload["principalId"] = str(principal.get("id") or "")
    return payload


def sync_job_key(
    principal: dict | None,
    handle_id: int | None,
    include_guests: bool = False,
) -> tuple:
    if handle_id is not None:
        return ("handle", int(handle_id))
    if principal:
        principal_type = str(principal.get("type") or "")
        principal_id = "" if principal_type == "user" else str(principal.get("id") or "")
        return ("principal", principal_type, principal_id)
    return ("scheduled", bool(include_guests))


def compact_luogu_auth(auth: dict | None) -> dict | None:
    if not auth:
        return None
    cookie = str(auth.get("cookie") or "").strip()
    csrf_token = str(auth.get("csrfToken") or auth.get("csrf_token") or "").strip()
    if not cookie and not csrf_token:
        return None
    return {"cookie": cookie, "csrfToken": csrf_token}


def enqueue_sync_job(
    principal: dict | None = None,
    handle_id: int | None = None,
    force: bool = False,
    include_guests: bool = False,
    full: bool = False,
    luogu_auth: dict | None = None,
) -> dict:
    global SYNC_JOB_COUNTER
    job_key = sync_job_key(principal, handle_id, include_guests)
    auth = compact_luogu_auth(luogu_auth)
    now = utcnow()
    with SYNC_QUEUE_LOCK:
        for job in SYNC_PENDING_JOBS:
            if job.get("key") != job_key:
                continue
            job["force"] = bool(job.get("force") or force)
            job["full"] = bool(job.get("full") or full)
            job["queued_at"] = now
            if auth:
                job["luogu_auth"] = auth
            SYNC_QUEUE_EVENT.set()
            clear_overview_memory_cache()
            return {"queued": True, "alreadyQueued": True, "job": public_sync_job(job)}

        SYNC_JOB_COUNTER += 1
        job = {
            "id": SYNC_JOB_COUNTER,
            "key": job_key,
            "scope": "handle" if handle_id is not None else ("principal" if principal else "scheduled"),
            "principal": dict(principal) if principal else None,
            "handle_id": int(handle_id) if handle_id is not None else None,
            "force": bool(force),
            "full": bool(full),
            "include_guests": bool(include_guests),
            "luogu_auth": auth,
            "queued_at": now,
        }
        SYNC_PENDING_JOBS.append(job)
        SYNC_QUEUE_EVENT.set()
    clear_overview_memory_cache()
    return {"queued": True, "job": public_sync_job(job)}


def pop_next_sync_job(timeout: float | None) -> dict | None:
    with SYNC_QUEUE_LOCK:
        if SYNC_PENDING_JOBS:
            job = SYNC_PENDING_JOBS.pop(0)
            if not SYNC_PENDING_JOBS:
                SYNC_QUEUE_EVENT.clear()
            return job

    if timeout is not None and timeout <= 0:
        return None
    SYNC_QUEUE_EVENT.wait(timeout)

    with SYNC_QUEUE_LOCK:
        if not SYNC_PENDING_JOBS:
            SYNC_QUEUE_EVENT.clear()
            return None
        job = SYNC_PENDING_JOBS.pop(0)
        if not SYNC_PENDING_JOBS:
            SYNC_QUEUE_EVENT.clear()
        return job


def sync_job_matches_handle(job: dict, row: sqlite3.Row) -> bool:
    handle_id = job.get("handle_id")
    if handle_id is not None:
        return int(row["id"]) == int(handle_id)
    principal = job.get("principal") if isinstance(job.get("principal"), dict) else None
    if principal:
        if principal.get("type") == "guest":
            return row["owner_type"] == "user" or (
                row["owner_type"] == "guest" and str(row["owner_id"]) == str(principal.get("id"))
            )
        return row["owner_type"] == "user"
    return row["owner_type"] == "user" or bool(job.get("include_guests"))


def sync_status_snapshot() -> dict:
    with SYNC_QUEUE_LOCK:
        pending = [public_sync_job(job) for job in SYNC_PENDING_JOBS]
        running = public_sync_job(SYNC_RUNNING_JOB)
        last_finished = public_sync_job(SYNC_LAST_FINISHED_JOB)
        pending_internal = [dict(job) for job in SYNC_PENDING_JOBS]
        running_internal = dict(SYNC_RUNNING_JOB) if SYNC_RUNNING_JOB else None
    return {
        "pending": len(pending),
        "running": bool(running),
        "pendingJobs": pending,
        "runningJob": running,
        "lastFinishedJob": last_finished,
        "_pendingInternal": pending_internal,
        "_runningInternal": running_internal,
    }


def sync_status_for_handle(row: sqlite3.Row, snapshot: dict | None) -> str:
    if not snapshot:
        return ""
    running = snapshot.get("_runningInternal")
    if isinstance(running, dict) and sync_job_matches_handle(running, row):
        return "running"
    for job in snapshot.get("_pendingInternal") or []:
        if isinstance(job, dict) and sync_job_matches_handle(job, row):
            return "queued"
    return ""


def execute_sync_job(job: dict) -> None:
    global SYNC_RUNNING_JOB
    global SYNC_LAST_FINISHED_JOB
    job["started_at"] = utcnow()
    with SYNC_QUEUE_LOCK:
        SYNC_RUNNING_JOB = job
    clear_overview_memory_cache()
    try:
        if job.get("handle_id") is not None:
            result = sync_one_handle(
                job["principal"],
                int(job["handle_id"]),
                force=bool(job.get("force")),
                full=bool(job.get("full")),
                luogu_auth=job.get("luogu_auth"),
            )
            job["result_count"] = 1
            if result.get("error"):
                job["error"] = result.get("error")
        else:
            results = sync_targets(
                principal=job.get("principal"),
                force=bool(job.get("force")),
                include_guests=bool(job.get("include_guests")),
                full=bool(job.get("full")),
                luogu_auth=job.get("luogu_auth"),
            )
            job["result_count"] = len(results)
            errors = [str(item.get("error")) for item in results if isinstance(item, dict) and item.get("error")]
            if errors:
                job["error"] = "；".join(errors[:3])[:300]
    except Exception as exc:
        traceback.print_exc()
        job["error"] = str(exc)[:300] or exc.__class__.__name__
    finally:
        job["finished_at"] = utcnow()
        job.pop("luogu_auth", None)
        with SYNC_QUEUE_LOCK:
            SYNC_LAST_FINISHED_JOB = dict(job)
            SYNC_RUNNING_JOB = None
        clear_overview_memory_cache()


def background_sync_loop() -> None:
    next_scheduled_at = time.time()
    while True:
        try:
            if SYNC_INTERVAL_SECONDS > 0:
                timeout = max(0.0, next_scheduled_at - time.time())
            else:
                timeout = None
            job = pop_next_sync_job(timeout)
            if job:
                execute_sync_job(job)
                continue
            if SYNC_INTERVAL_SECONDS <= 0:
                continue
            execute_sync_job(
                {
                    "id": None,
                    "key": sync_job_key(None, None, False),
                    "scope": "scheduled",
                    "principal": None,
                    "handle_id": None,
                    "force": False,
                    "full": False,
                    "include_guests": False,
                    "queued_at": utcnow(),
                }
            )
            next_scheduled_at = time.time() + max(60, SYNC_INTERVAL_SECONDS)
        except Exception:
            traceback.print_exc()


def handle_to_json(row: sqlite3.Row, sync_snapshot: dict | None = None) -> dict:
    adapter = ADAPTERS.get(row["platform"])
    display_handle = str(row["handle"] or "")
    if row["platform"] == "luogu" and row["stats_json"]:
        with contextlib.suppress(Exception):
            stats = json.loads(row["stats_json"])
            if isinstance(stats, dict):
                name = str(stats.get("name") or "").strip()
                uid = str(stats.get("uid") or row["handle"] or "").strip()
                if name and uid and name != uid:
                    display_handle = f"{name} ({uid})"
    return {
        "id": row["id"],
        "platform": row["platform"],
        "platformLabel": adapter.label if adapter else row["platform"],
        "handle": row["handle"],
        "displayHandle": display_handle,
        "lastSyncAt": iso_from_ts(row["last_sync_at"]),
        "lastError": row["last_error"],
        "syncStatus": sync_status_for_handle(row, sync_snapshot),
    }


def solved_problem_key(row: sqlite3.Row) -> str:
    return canonical_problem_key(
        str(row["platform"]),
        str(row["problem_id"] or ""),
        str(row["problem_name"] or ""),
        str(row["remote_id"] or ""),
        raw_json_dict(row),
    )


def build_mirror_meta(conn: sqlite3.Connection, now: int) -> dict:
    rows = conn.execute(
        """
        SELECT platform, COUNT(*) AS handles, MIN(last_sync_at) AS oldest_sync, MAX(last_sync_at) AS newest_sync
        FROM handles
        WHERE active = 1
        GROUP BY platform
        ORDER BY platform
        """
    ).fetchall()
    platforms = {}
    oldest_values = []
    newest_values = []
    for row in rows:
        oldest = int(row["oldest_sync"] or 0)
        newest = int(row["newest_sync"] or 0)
        if oldest:
            oldest_values.append(oldest)
        if newest:
            newest_values.append(newest)
        platforms[row["platform"]] = {
            "handles": int(row["handles"] or 0),
            "oldestSyncAt": iso_from_ts(oldest),
            "newestSyncAt": iso_from_ts(newest),
        }
    return {
        "fallback": False,
        "generatedAt": iso_from_ts(now),
        "asOf": iso_from_ts(min(oldest_values)) if oldest_values else None,
        "newestPlatformSyncAt": iso_from_ts(max(newest_values)) if newest_values else None,
        "platforms": platforms,
    }


def write_overview_cache(overview: dict) -> None:
    payload = json.loads(json.dumps(overview, ensure_ascii=False))
    payload["user"] = None
    for member in payload.get("members", []):
        member["isCurrent"] = False
        member["realName"] = ""
        member["realNameVisible"] = False
    mirror = payload.setdefault("mirror", {})
    mirror.pop("sync", None)
    mirror["cachedAt"] = iso_from_ts(utcnow())
    tmp_path = OVERVIEW_CACHE_PATH.with_name(f"{OVERVIEW_CACHE_PATH.name}.{threading.get_ident()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "utf-8")
    os.replace(tmp_path, OVERVIEW_CACHE_PATH)


def read_overview_cache(principal: dict | None, error: Exception | None = None) -> dict | None:
    if not OVERVIEW_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(OVERVIEW_CACHE_PATH.read_text("utf-8"))
    except Exception:
        return None
    data["user"] = principal
    for member in data.get("members", []):
        member["isCurrent"] = bool(
            principal
            and member.get("ownerType") == principal.get("type")
            and str(member.get("ownerId")) == str(principal.get("id"))
        )
        member["realName"] = ""
        member["realNameVisible"] = False
    mirror = data.setdefault("mirror", {})
    mirror["fallback"] = True
    mirror["servedAt"] = iso_from_ts(utcnow())
    sync_snapshot = sync_status_snapshot()
    mirror["sync"] = {
        "pending": sync_snapshot.get("pending", 0),
        "running": bool(sync_snapshot.get("running")),
        "pendingJobs": sync_snapshot.get("pendingJobs", []),
        "runningJob": sync_snapshot.get("runningJob"),
        "lastFinishedJob": sync_snapshot.get("lastFinishedJob"),
    }
    if error:
        mirror["error"] = str(error)[:300] or error.__class__.__name__
    return data


def overview_memory_cache_key(principal: dict | None, days: int) -> tuple[str, str, str, int]:
    if not principal:
        return ("anon", "", "", int(days))
    return (
        str(principal.get("type") or ""),
        str(principal.get("id") or ""),
        normalize_team_name(principal.get("teamName"), ""),
        int(days),
    )


def clear_overview_memory_cache() -> None:
    with OVERVIEW_CACHE_LOCK:
        OVERVIEW_MEMORY_CACHE.clear()
        BATTLE_MEMORY_CACHE.clear()


def read_overview_memory_cache(principal: dict | None, days: int) -> dict | None:
    if OVERVIEW_CACHE_TTL_SECONDS <= 0:
        return None
    key = overview_memory_cache_key(principal, days)
    now = utcnow()
    with OVERVIEW_CACHE_LOCK:
        item = OVERVIEW_MEMORY_CACHE.get(key)
        if not item:
            return None
        cached_at, overview = item
        if now - cached_at > OVERVIEW_CACHE_TTL_SECONDS:
            OVERVIEW_MEMORY_CACHE.pop(key, None)
            return None
        return overview


def write_overview_memory_cache(principal: dict | None, days: int, overview: dict) -> None:
    if OVERVIEW_CACHE_TTL_SECONDS <= 0:
        return
    key = overview_memory_cache_key(principal, days)
    with OVERVIEW_CACHE_LOCK:
        OVERVIEW_MEMORY_CACHE[key] = (utcnow(), overview)


def empty_activity_stats() -> dict:
    return {
        "accepted": 0,
        "total": 0,
        "activeDays": 0,
        "streak": 0,
        "allTimeAccepted": 0,
        "lastYearAccepted": 0,
        "lastMonthAccepted": 0,
        "maxStreakAllTime": 0,
        "maxStreakYear": 0,
        "maxStreakMonth": 0,
        "contests": 0,
    }


def empty_contest_activity() -> dict:
    return {"items": [], "total": 0, "byCategory": [], "byPlatform": []}


def empty_activity() -> dict:
    return {
        "days": {},
        "stats": empty_activity_stats(),
        "contests": empty_contest_activity(),
        "_all_days": {},
        "_solved_keys": set(),
        "_handle_stats": [],
        "_handle_solved_counts": {},
    }


def handle_activity_key(platform: str, handle: str) -> str:
    return "\x1f".join([str(platform or ""), str(handle or "")])


def add_submission_to_activity(activity: dict, row: sqlite3.Row) -> None:
    date_key = utc_date_from_ts(row["submitted_at"])
    all_day = activity["_all_days"].setdefault(date_key, {"accepted": 0, "total": 0})
    all_day["total"] += 1
    is_accepted = normalize_verdict(row["verdict"]) == "AC"
    is_activity = is_activity_placeholder(row)
    solved_key = solved_problem_key(row)
    is_new_solve = is_accepted and not is_activity and solved_key not in activity["_solved_keys"]
    if is_new_solve:
        all_day["accepted"] += 1
        activity["_solved_keys"].add(solved_key)
        key = handle_activity_key(row["platform"], row["handle"])
        handle_counts = activity["_handle_solved_counts"]
        handle_counts[key] = handle_counts.get(key, 0) + 1
    elif is_accepted and is_activity:
        all_day["accepted"] += 1

    day = activity["days"].setdefault(date_key, {"accepted": 0, "total": 0})
    day["total"] += 1
    activity["stats"]["total"] += 1
    if is_new_solve or (is_accepted and is_activity):
        day["accepted"] += 1
        activity["stats"]["accepted"] += 1


def finalize_submission_activity(activity: dict, start_date: dt.date, month_start_date: dt.date, today_date: dt.date) -> None:
    active_dates = [date_key for date_key, counts in activity["days"].items() if counts.get("accepted", 0) > 0]
    activity["stats"]["activeDays"] = len(active_dates)
    all_days = activity.pop("_all_days")
    activity["stats"]["streak"] = current_streak(all_days)
    activity["stats"]["lastYearAccepted"] = accepted_since(all_days, start_date)
    activity["stats"]["lastMonthAccepted"] = accepted_since(all_days, month_start_date)
    activity["stats"]["maxStreakAllTime"] = max_streak(all_days)
    activity["stats"]["maxStreakYear"] = max_streak(all_days, start_date, today_date)
    activity["stats"]["maxStreakMonth"] = max_streak(all_days, month_start_date, today_date)
    handle_solved_counts = activity.pop("_handle_solved_counts", {})
    for handle_stats in activity.pop("_handle_stats", []):
        with contextlib.suppress(Exception):
            profile_keys = profile_solved_problem_keys(handle_stats)
            if profile_keys:
                activity["_solved_keys"].update(profile_keys)
            else:
                all_time_accepted = int(handle_stats.get("allTimeAccepted") or 0)
                key = handle_activity_key(handle_stats.get("_platform") or "", handle_stats.get("_handle") or "")
                known_accepted = int(handle_solved_counts.get(key, 0) or 0)
                activity["stats"]["allTimeAccepted"] += max(0, all_time_accepted - known_accepted)
    activity["stats"]["allTimeAccepted"] += len(activity["_solved_keys"])
    activity.pop("_solved_keys", None)


def finalize_contest_activity(activity: dict) -> None:
    contest_summary = summarize_contests(activity["contests"]["items"])
    activity["contests"].update(contest_summary)
    activity["stats"]["contests"] = contest_summary["total"]


def build_overview(principal: dict | None, days: int = 365, use_cache: bool = True) -> dict:
    days = max(7, min(days, 3650))
    if use_cache:
        cached = read_overview_memory_cache(principal, days)
        if cached:
            return cached
    overview = build_overview_from_db(principal, days=days)
    write_overview_memory_cache(principal, days, overview)
    with contextlib.suppress(Exception):
        write_overview_cache(overview)
    return overview


def build_overview_from_db(principal: dict | None, days: int = 365) -> dict:
    days = max(7, min(days, 3650))
    now = utcnow()
    sync_snapshot = sync_status_snapshot()
    start_ts = now - (days - 1) * 86400
    today_date = dt.datetime.fromtimestamp(now, DISPLAY_TZ).date()
    start_date = dt.datetime.fromtimestamp(start_ts, DISPLAY_TZ).date()
    month_start_date = today_date - dt.timedelta(days=29)
    with connect_db() as conn:
        owners: dict[tuple[str, str], dict] = {}

        user_rows = conn.execute(
            """
            SELECT id, username, display_name, email, real_name, team_name
            FROM users
            ORDER BY created_at
            """
        ).fetchall()
        for row in user_rows:
            key = ("user", str(row["id"]))
            owners[key] = {
                "ownerType": "user",
                "ownerId": str(row["id"]),
                "username": row["username"],
                "displayName": row["display_name"],
                "teamName": row["team_name"] or DEFAULT_TEAM_NAME,
                "isCurrent": bool(principal and principal["type"] == "user" and principal["id"] == str(row["id"])),
                "realName": "",
                "realNameVisible": False,
                "handles": [],
                **empty_activity(),
                "_handle_activities": {},
                "_real_name": row["real_name"] or "",
            }

        if principal and principal["type"] == "guest":
            key = ("guest", principal["id"])
            owners[key] = {
                "ownerType": "guest",
                "ownerId": principal["id"],
                "displayName": principal["displayName"],
                "teamName": principal.get("teamName") or GUEST_TEAM_NAME,
                "isCurrent": True,
                "realName": "",
                "realNameVisible": False,
                "handles": [],
                **empty_activity(),
                "_handle_activities": {},
                "_real_name": principal.get("realName") or "",
            }

        handle_rows = get_handle_rows(conn, principal=principal, include_guests=False)
        for row in handle_rows:
            key = (row["owner_type"], row["owner_id"])
            if key not in owners:
                continue
            handle_json = handle_to_json(row, sync_snapshot)
            handle_json["activity"] = empty_activity()
            owners[key]["handles"].append(handle_json)
            owners[key]["_handle_activities"][handle_activity_key(row["platform"], row["handle"])] = handle_json["activity"]
            if row["stats_json"]:
                with contextlib.suppress(Exception):
                    stats = json.loads(row["stats_json"])
                    if isinstance(stats, dict):
                        stats["_platform"] = row["platform"]
                        stats["_handle"] = row["handle"]
                        owners[key]["_handle_stats"].append(stats)
                        handle_json["activity"]["_handle_stats"].append(dict(stats))

        sub_rows = conn.execute(
            """
            SELECT owner_type, owner_id, platform, handle, remote_id, problem_id, problem_name, verdict, submitted_at, raw_json
            FROM submissions
            ORDER BY submitted_at
            """
        ).fetchall()
        for row in sub_rows:
            key = (row["owner_type"], row["owner_id"])
            if key not in owners:
                continue
            add_submission_to_activity(owners[key], row)
            handle_activity = owners[key]["_handle_activities"].get(handle_activity_key(row["platform"], row["handle"]))
            if handle_activity:
                add_submission_to_activity(handle_activity, row)

        for owner in owners.values():
            finalize_submission_activity(owner, start_date, month_start_date, today_date)
            for handle_activity in owner["_handle_activities"].values():
                finalize_submission_activity(handle_activity, start_date, month_start_date, today_date)

        contest_rows = conn.execute(
            """
            SELECT *
            FROM contests
            ORDER BY participated_at
            """
        ).fetchall()
        for row in contest_rows:
            key = (row["owner_type"], row["owner_id"])
            if key not in owners:
                continue
            item = contest_to_json(row)
            owners[key]["contests"]["items"].append(item)
            handle_activity = owners[key]["_handle_activities"].get(handle_activity_key(row["platform"], row["handle"]))
            if handle_activity:
                handle_activity["contests"]["items"].append(item)

        for owner in owners.values():
            finalize_contest_activity(owner)
            for handle_activity in owner["_handle_activities"].values():
                finalize_contest_activity(handle_activity)
            owner["realNameVisible"] = can_view_real_name(principal, owner)
            owner["realName"] = owner.get("_real_name", "") if owner["realNameVisible"] else ""
            owner.pop("_handle_activities", None)
            owner.pop("_real_name", None)

        feed_total = sum(
            1
            for row in sub_rows
            if (row["owner_type"], row["owner_id"]) in owners
        )
        feed_limit = max(0, OVERVIEW_FEED_LIMIT)
        feed_sql = """
            SELECT *
            FROM submissions
            ORDER BY submitted_at DESC
        """
        feed_params: tuple[object, ...] = ()
        if feed_limit:
            feed_sql += " LIMIT ?"
            feed_params = (feed_limit,)
        feed_rows = conn.execute(feed_sql, feed_params).fetchall()
        feed = []
        for row in feed_rows:
            key = (row["owner_type"], row["owner_id"])
            if key not in owners:
                continue
            feed.append(submission_to_json(conn, row))

        date_values = [
            date
            for owner in owners.values()
            for date in owner["days"].keys()
        ]
        available_years = sorted({date[:4] for date in date_values}, reverse=True)
        mirror = build_mirror_meta(conn, now)
        mirror["sync"] = {
            "pending": sync_snapshot.get("pending", 0),
            "running": bool(sync_snapshot.get("running")),
            "pendingJobs": sync_snapshot.get("pendingJobs", []),
            "runningJob": sync_snapshot.get("runningJob"),
            "lastFinishedJob": sync_snapshot.get("lastFinishedJob"),
        }
        if feed_limit:
            mirror["feedLimit"] = feed_limit
            if feed_total > len(feed):
                mirror["fullFeedCount"] = feed_total
        return {
            "now": iso_from_ts(now),
            "today": today_date.isoformat(),
            "dateRange": {
                "min": min(date_values) if date_values else today_date.isoformat(),
                "max": max(date_values) if date_values else today_date.isoformat(),
            },
            "availableYears": available_years or [today_date.strftime("%Y")],
            "mirror": mirror,
            "platforms": platform_meta(),
            "user": principal,
            "members": list(owners.values()),
            "feed": feed,
        }


def current_streak(day_counts: dict[str, dict]) -> int:
    streak = 0
    cursor = dt.datetime.now(DISPLAY_TZ).date()
    while True:
        key = cursor.isoformat()
        if day_counts.get(key, {}).get("accepted", 0) <= 0:
            return streak
        streak += 1
        cursor -= dt.timedelta(days=1)


def max_streak(day_counts: dict[str, dict], start_date: dt.date | None = None, end_date: dt.date | None = None) -> int:
    accepted_dates = []
    for date_key, counts in day_counts.items():
        if counts.get("accepted", 0) <= 0:
            continue
        try:
            date = dt.date.fromisoformat(date_key)
        except ValueError:
            continue
        if start_date and date < start_date:
            continue
        if end_date and date > end_date:
            continue
        accepted_dates.append(date)

    longest = 0
    streak = 0
    previous = None
    for date in sorted(accepted_dates):
        if previous and date == previous + dt.timedelta(days=1):
            streak += 1
        else:
            streak = 1
        longest = max(longest, streak)
        previous = date
    return longest


def accepted_since(day_counts: dict[str, dict], start_date: dt.date | None = None) -> int:
    total = 0
    for date_key, counts in day_counts.items():
        try:
            date = dt.date.fromisoformat(date_key)
        except ValueError:
            continue
        if start_date and date < start_date:
            continue
        total += int(counts.get("accepted", 0) or 0)
    return total


def profile_solved_problem_keys(handle_stats: dict) -> set[str]:
    keys: set[str] = set()
    for item in handle_stats.get("solvedProblems") or []:
        if not isinstance(item, dict):
            continue
        canonical_key = str(item.get("canonicalKey") or "")
        if canonical_key:
            keys.add(canonical_key)
            continue
        platform = str(item.get("source") or item.get("platform") or handle_stats.get("_platform") or "")
        problem_id = str(item.get("problemId") or item.get("pid") or "")
        key = canonical_problem_key(platform, problem_id, str(item.get("name") or ""), "", item)
        if key:
            keys.add(key)
    return keys


def summarize_contests(items: list[dict]) -> dict:
    by_category: dict[str, int] = {}
    by_platform: dict[str, dict] = {}
    for item in items:
        category = item.get("category") or "other"
        by_category[category] = by_category.get(category, 0) + 1
        platform = item.get("platform") or ""
        platform_label = item.get("platformLabel") or platform
        entry = by_platform.setdefault(platform, {"platform": platform, "platformLabel": platform_label, "count": 0})
        entry["count"] += 1

    categories = [
        {
            "category": category,
            "label": contest_category_label(category),
            "count": count,
        }
        for category, count in by_category.items()
    ]
    categories.sort(key=lambda item: (CONTEST_CATEGORY_ORDER.get(item["category"], 999), item["label"]))
    platforms = sorted(by_platform.values(), key=lambda item: (-item["count"], item["platformLabel"]))
    return {"total": len(items), "byCategory": categories, "byPlatform": platforms}


def contest_to_json(row: sqlite3.Row) -> dict:
    adapter = ADAPTERS.get(row["platform"])
    category = classify_contest(row["platform"], row["contest_name"], row["remote_id"], raw_json_dict(row))
    return {
        "id": row["id"],
        "platform": row["platform"],
        "platformLabel": adapter.label if adapter else row["platform"],
        "handle": row["handle"],
        "remoteId": row["remote_id"],
        "contestName": row["contest_name"],
        "category": category,
        "categoryLabel": contest_category_label(category),
        "participatedAt": iso_from_ts(row["participated_at"]),
        "participatedDate": utc_date_from_ts(row["participated_at"]),
        "url": row["url"],
    }


def submission_to_json(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    adapter = ADAPTERS.get(row["platform"])
    return {
        "id": row["id"],
        "ownerType": row["owner_type"],
        "ownerId": row["owner_id"],
        "displayName": owner_display_name(conn, row["owner_type"], row["owner_id"]),
        "platform": row["platform"],
        "platformLabel": adapter.label if adapter else row["platform"],
        "handle": row["handle"],
        "remoteId": row["remote_id"],
        "problemId": row["problem_id"],
        "problemName": row["problem_name"],
        "verdict": normalize_verdict(row["verdict"]),
        "language": row["language"],
        "submittedAt": iso_from_ts(row["submitted_at"]),
        "submittedDate": utc_date_from_ts(row["submitted_at"]),
        "url": row["url"],
    }


def battle_range(range_key: str, now: int | None = None) -> dict:
    now = now or utcnow()
    today = dt.datetime.fromtimestamp(now, DISPLAY_TZ).date()
    ranges = {
        "30": (29, "近 30 天"),
        "90": (89, "近 90 天"),
        "365": (364, "近 365 天"),
    }
    if range_key == "all":
        start_date = None
        label = "全部历史"
    elif range_key == "year":
        start_date = dt.date(today.year, 1, 1)
        label = f"{today.year} 年"
    elif range_key in ranges:
        offset, label = ranges[range_key]
        start_date = today - dt.timedelta(days=offset)
    else:
        raise ValueError("不支持的对战时间范围")
    return {
        "key": range_key,
        "label": label,
        "from": start_date.isoformat() if start_date else None,
        "to": today.isoformat(),
    }


def visible_battle_owners(conn: sqlite3.Connection, principal: dict | None) -> dict[str, dict]:
    owners = {}
    rows = conn.execute(
        "SELECT id, username, display_name, real_name, team_name FROM users ORDER BY created_at"
    ).fetchall()
    for row in rows:
        owner = {
            "ownerType": "user",
            "ownerId": str(row["id"]),
            "username": row["username"],
            "displayName": row["display_name"],
            "teamName": row["team_name"] or DEFAULT_TEAM_NAME,
            "isCurrent": bool(principal and principal["type"] == "user" and principal["id"] == str(row["id"])),
            "realName": "",
            "realNameVisible": False,
            "_real_name": row["real_name"] or "",
            "handles": [],
        }
        owners[f"user:{row['id']}"] = owner

    if principal and principal["type"] == "guest":
        owner = {
            "ownerType": "guest",
            "ownerId": str(principal["id"]),
            "displayName": principal["displayName"],
            "teamName": principal.get("teamName") or GUEST_TEAM_NAME,
            "isCurrent": True,
            "realName": "",
            "realNameVisible": False,
            "_real_name": principal.get("realName") or "",
            "handles": [],
        }
        owners[f"guest:{principal['id']}"] = owner

    for owner in owners.values():
        owner["realNameVisible"] = can_view_real_name(principal, owner)
        owner["realName"] = owner["_real_name"] if owner["realNameVisible"] else ""
        owner.pop("_real_name", None)
    return owners


def battle_timestamp_bounds(selected_range: dict) -> tuple[int | None, int]:
    start_date = dt.date.fromisoformat(selected_range["from"]) if selected_range.get("from") else None
    end_date = dt.date.fromisoformat(selected_range["to"]) + dt.timedelta(days=1)
    start_timestamp = (
        int(dt.datetime.combine(start_date, dt.time.min, tzinfo=DISPLAY_TZ).timestamp())
        if start_date
        else None
    )
    end_timestamp = int(dt.datetime.combine(end_date, dt.time.min, tzinfo=DISPLAY_TZ).timestamp())
    return start_timestamp, end_timestamp


def battle_contest_key(row: sqlite3.Row) -> tuple[str, str]:
    remote_id = str(row["remote_id"] or "").strip()
    if remote_id:
        return str(row["platform"] or ""), remote_id
    fallback = f"{normalize_problem_text_key(row['contest_name'])}:{utc_date_from_ts(row['participated_at'])}"
    return str(row["platform"] or ""), fallback


def battle_union_rows(
    conn: sqlite3.Connection,
    table: str,
    columns: str,
    owner_tuples: list[tuple[str, str]],
    extra_where: str = "",
    extra_params: tuple[object, ...] = (),
    order_by: str = "",
) -> list[sqlite3.Row]:
    selects = []
    params: list[object] = []
    for owner_type, owner_id in owner_tuples:
        selects.append(
            f"SELECT {columns} FROM {table} WHERE owner_type = ? AND owner_id = ? {extra_where}"
        )
        params.extend((owner_type, owner_id, *extra_params))
    query = " UNION ALL ".join(selects)
    if order_by:
        query = f"SELECT * FROM ({query}) ORDER BY {order_by}"
    return conn.execute(query, tuple(params)).fetchall()


def battle_optional_number(value) -> int | float | None:
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) == float("inf"):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def battle_optional_int(value, positive: bool = False) -> int | None:
    number = battle_optional_number(value)
    if number is None:
        return None
    result = int(number)
    return None if positive and result <= 0 else result


def battle_epoch_seconds(value) -> int | None:
    timestamp = battle_optional_int(value, positive=True)
    if timestamp is None:
        return None
    return timestamp // 1000 if timestamp > 10_000_000_000 else timestamp


def battle_contest_result(row: sqlite3.Row) -> dict:
    platform = str(row["platform"] or "")
    raw = raw_json_dict(row)
    rank = None
    score = None
    solved = None
    participants = None
    rating_before = None
    rating_after = None
    rating_delta = None
    performance = None
    rated = False
    participant_type = None
    rank_kind = None
    participant_key = None
    start_timestamp = None
    end_timestamp = None
    duration_seconds = None

    if platform == "codeforces":
        contest = raw.get("contest") if isinstance(raw.get("contest"), dict) else {}
        rating_change = raw.get("ratingChange") if isinstance(raw.get("ratingChange"), dict) else {}
        virtual_result = raw.get("virtualResult") if isinstance(raw.get("virtualResult"), dict) else {}
        rank = battle_optional_int(rating_change.get("rank"), positive=True)
        rating_before = battle_optional_int(rating_change.get("oldRating"))
        rating_after = battle_optional_int(rating_change.get("newRating"))
        if rating_before is not None and rating_after is not None:
            rating_delta = rating_after - rating_before
        rated = bool(rating_change)
        if rank is None and virtual_result:
            rank = battle_optional_int(virtual_result.get("rank"), positive=True)
            score = battle_optional_number(virtual_result.get("score"))
            solved = battle_optional_int(virtual_result.get("solved"))
            participants = battle_optional_int(virtual_result.get("participants"), positive=True)
            participant_type = str(virtual_result.get("participantType") or "").upper() or None
            rank_kind = str(virtual_result.get("rankKind") or "") or None
        start_timestamp = battle_epoch_seconds(
            virtual_result.get("startTimeSeconds") if rank_kind == "virtual-equivalent" else None
        ) or battle_epoch_seconds(contest.get("startTimeSeconds"))
        duration_seconds = battle_optional_int(contest.get("durationSeconds"), positive=True)
    elif platform == "atcoder":
        contest = raw.get("contest") if isinstance(raw.get("contest"), dict) else {}
        rank = battle_optional_int(raw.get("Place"), positive=True)
        rating_before = battle_optional_int(raw.get("OldRating"))
        rating_after = battle_optional_int(raw.get("NewRating"))
        if rating_before is not None and rating_after is not None:
            rating_delta = rating_after - rating_before
        performance = battle_optional_int(raw.get("Performance"), positive=True)
        rated = bool(raw.get("IsRated"))
        start_timestamp = battle_epoch_seconds(
            contest.get("start_epoch_second") or contest.get("startTimeSeconds")
        )
        duration_seconds = battle_optional_int(
            contest.get("duration_second") or contest.get("durationSeconds"),
            positive=True,
        )
        end_timestamp = parse_iso_datetime(str(raw.get("EndTime") or ""))
    elif platform == "nowcoder":
        if raw.get("canShowRank") is not False:
            rank = battle_optional_int(raw.get("rank"), positive=True)
        score = battle_optional_number(raw.get("totalScore"))
        solved = battle_optional_int(raw.get("acceptedCount"))
        participants = battle_optional_int(raw.get("userCount"), positive=True)
        rating_after = battle_optional_int(raw.get("rating"))
        rating_delta = battle_optional_int(raw.get("changeValue"))
        if rating_after is not None and rating_delta is not None:
            rating_before = rating_after - rating_delta
        rating_status = str(raw.get("ratingStatus") or "").upper()
        rating_text = str(raw.get("ratingStr") or "")
        rated = rating_status not in {"", "NO", "NONE"} and "不计" not in rating_text
        start_timestamp = battle_epoch_seconds(raw.get("startTime"))
        end_timestamp = battle_epoch_seconds(raw.get("endTime"))
        duration_seconds = battle_optional_int(raw.get("contestDuration"), positive=True)
        if duration_seconds and duration_seconds > 10 * 86400:
            duration_seconds //= 1000
        participant_id = raw.get("teamId") or raw.get("nowcoderSourceId")
        if participant_id:
            participant_key = f"nowcoder:{participant_id}"
    else:
        rank = battle_optional_int(raw.get("rank") or raw.get("ranking") or raw.get("place"), positive=True)
        score = battle_optional_number(raw.get("score") or raw.get("totalScore"))
        solved = battle_optional_int(raw.get("solved") or raw.get("acceptedCount"))
        participants = battle_optional_int(raw.get("participants") or raw.get("userCount"), positive=True)
        rating_before = battle_optional_int(raw.get("oldRating") or raw.get("ratingBefore"))
        rating_after = battle_optional_int(raw.get("newRating") or raw.get("ratingAfter") or raw.get("rating"))
        rating_delta = battle_optional_int(raw.get("ratingDelta") or raw.get("changeValue"))
        performance = battle_optional_int(raw.get("performance"), positive=True)
        rated = rating_before is not None or rating_after is not None
        start_timestamp = battle_epoch_seconds(raw.get("startTime") or raw.get("startTimeSeconds"))
        end_timestamp = battle_epoch_seconds(raw.get("endTime") or raw.get("endTimeSeconds"))
        duration_seconds = battle_optional_int(raw.get("durationSeconds"), positive=True)

    if start_timestamp and duration_seconds and not end_timestamp:
        end_timestamp = start_timestamp + duration_seconds
    if end_timestamp and duration_seconds and not start_timestamp:
        start_timestamp = end_timestamp - duration_seconds

    return {
        "rank": rank,
        "score": score,
        "solved": solved,
        "participants": participants,
        "ratingBefore": rating_before,
        "ratingAfter": rating_after,
        "ratingDelta": rating_delta,
        "performance": performance,
        "rated": rated,
        "participantType": participant_type,
        "rankKind": rank_kind,
        "resultAvailable": rank is not None,
        "_startTimestamp": start_timestamp,
        "_endTimestamp": end_timestamp,
        "_durationSeconds": duration_seconds,
        "_participantKey": participant_key,
    }


def battle_contest_entry(row: sqlite3.Row) -> dict:
    result = battle_contest_result(row)
    return {
        **contest_to_json(row),
        "result": {key: value for key, value in result.items() if not key.startswith("_")},
        "_startTimestamp": result["_startTimestamp"],
        "_endTimestamp": result["_endTimestamp"],
        "_durationSeconds": result["_durationSeconds"],
        "_participantKey": result["_participantKey"],
    }


def battle_contest_preference(entry: dict) -> tuple[int, int, int]:
    result = entry["result"]
    rank = result.get("rank")
    return (
        1 if result.get("resultAvailable") else 0,
        -int(rank) if rank is not None else -1_000_000_000,
        1 if entry.get("_startTimestamp") and entry.get("_endTimestamp") else 0,
    )


def battle_submission_contest_id(row: sqlite3.Row, raw: dict) -> str:
    platform = str(row["platform"] or "")
    if platform == "codeforces":
        problem = raw.get("problem") if isinstance(raw.get("problem"), dict) else {}
        return str(raw.get("contestId") or problem.get("contestId") or "")
    if platform == "atcoder":
        return str(raw.get("contest_id") or "")
    if platform == "vjudge":
        return str(raw.get("contestId") or "")
    return ""


def battle_in_contest_solve(row: sqlite3.Row, entry: dict) -> dict | None:
    raw = raw_json_dict(row)
    if str(row["handle"] or "") != str(entry.get("handle") or ""):
        return None
    if battle_submission_contest_id(row, raw) != str(entry.get("remoteId") or ""):
        return None
    if row["platform"] == "codeforces":
        participant_type = str((raw.get("author") or {}).get("participantType") or "").upper()
        if participant_type == "PRACTICE":
            return None

    submitted_at = int(row["submitted_at"] or 0)
    start_timestamp = entry.get("_startTimestamp")
    end_timestamp = entry.get("_endTimestamp")
    if row["platform"] == "codeforces" and not start_timestamp:
        start_timestamp = battle_epoch_seconds((raw.get("author") or {}).get("startTimeSeconds"))
    if not start_timestamp or submitted_at < start_timestamp:
        return None
    if end_timestamp and submitted_at > end_timestamp:
        return None
    duration_seconds = entry.get("_durationSeconds")
    elapsed_seconds = submitted_at - start_timestamp
    if duration_seconds and elapsed_seconds > duration_seconds:
        return None

    problem_key = solved_problem_key(row)
    if not problem_key:
        return None
    return {
        "key": problem_key,
        "problemId": row["problem_id"],
        "problemName": row["problem_name"],
        "elapsedSeconds": elapsed_seconds,
        "solvedAt": iso_from_ts(submitted_at),
        "url": row["url"],
    }


def battle_absolute_rating_change(result: dict) -> tuple[float, str | None]:
    rating_delta = battle_optional_number(result.get("ratingDelta"))
    if result.get("rated") and rating_delta is not None:
        signal = max(-1.0, min(1.0, float(rating_delta) / 200))
        return BATTLE_ABSOLUTE_K_FACTOR * signal, "official-rating"

    rank = battle_optional_int(result.get("rank"), positive=True)
    participants = battle_optional_int(result.get("participants"), positive=True)
    if rank is not None and participants is not None and rank <= participants:
        rank_percentile = (rank - 0.5) / participants
        signal = 1 - 2 * rank_percentile
        return BATTLE_ABSOLUTE_K_FACTOR * signal, "rank-percentile"

    if rating_delta is not None:
        signal = max(-1.0, min(1.0, float(rating_delta) / 200))
        return BATTLE_ABSOLUTE_K_FACTOR * signal, "official-rating"
    return 0.0, None


def battle_elo_timeline(shared_contests: list[dict]) -> dict:
    current = [float(BATTLE_INITIAL_RATING), float(BATTLE_INITIAL_RATING)]
    points = []
    for contest in sorted(shared_contests, key=lambda item: (item["participatedAt"], item["platform"], item["remoteId"])):
        if contest.get("sameTeam"):
            continue
        left_result = contest["leftResult"]
        right_result = contest["rightResult"]
        if left_result.get("rank") is None or right_result.get("rank") is None:
            continue

        duel_change = 0.0
        if not contest.get("sameTeam") and contest["winner"] in {"left", "right", "tie"}:
            expected_left = 1 / (1 + 10 ** ((current[1] - current[0]) / 400))
            actual_left = 1.0 if contest["winner"] == "left" else 0.0 if contest["winner"] == "right" else 0.5
            duel_change = BATTLE_DUEL_K_FACTOR * (actual_left - expected_left)

        left_absolute, left_absolute_source = battle_absolute_rating_change(left_result)
        right_absolute, right_absolute_source = battle_absolute_rating_change(right_result)
        if left_absolute < 0 and right_absolute < 0:
            if duel_change > 0:
                duel_change = min(duel_change, -left_absolute * BATTLE_DUEL_DIRECTION_LIMIT)
            elif duel_change < 0:
                duel_change = max(duel_change, right_absolute * BATTLE_DUEL_DIRECTION_LIMIT)
        elif left_absolute > 0 and right_absolute > 0:
            if duel_change > 0:
                duel_change = min(duel_change, right_absolute * BATTLE_DUEL_DIRECTION_LIMIT)
            elif duel_change < 0:
                duel_change = max(duel_change, -left_absolute * BATTLE_DUEL_DIRECTION_LIMIT)
        previous = list(current)
        current[0] = max(BATTLE_MIN_RATING, min(BATTLE_MAX_RATING, current[0] + left_absolute + duel_change))
        current[1] = max(BATTLE_MIN_RATING, min(BATTLE_MAX_RATING, current[1] + right_absolute - duel_change))
        points.append(
            {
                "platform": contest["platform"],
                "platformLabel": contest["platformLabel"],
                "remoteId": contest["remoteId"],
                "contestName": contest["contestName"],
                "participatedAt": contest["participatedAt"],
                "participatedDate": contest["participatedDate"],
                "winner": contest["winner"],
                "sameTeam": bool(contest.get("sameTeam")),
                "leftRank": left_result.get("rank"),
                "rightRank": right_result.get("rank"),
                "leftRating": round(current[0]),
                "rightRating": round(current[1]),
                "leftChange": round(current[0] - previous[0], 1),
                "rightChange": round(current[1] - previous[1], 1),
                "leftAbsoluteChange": round(left_absolute, 1),
                "rightAbsoluteChange": round(right_absolute, 1),
                "leftAbsoluteSource": left_absolute_source,
                "rightAbsoluteSource": right_absolute_source,
                "duelChange": round(duel_change, 1),
            }
        )
    return {
        "initialRating": BATTLE_INITIAL_RATING,
        "kFactor": BATTLE_DUEL_K_FACTOR,
        "duelKFactor": BATTLE_DUEL_K_FACTOR,
        "absoluteKFactor": BATTLE_ABSOLUTE_K_FACTOR,
        "leftRating": round(current[0]),
        "rightRating": round(current[1]),
        "points": points,
    }


def build_battle_from_db(principal: dict | None, left_key: str, right_key: str, range_key: str = "365") -> dict:
    selected_range = battle_range(range_key)
    start_timestamp, end_timestamp = battle_timestamp_bounds(selected_range)
    with connect_db() as conn:
        owners = visible_battle_owners(conn, principal)
        if left_key not in owners or right_key not in owners:
            raise ValueError("选择的成员不存在或当前不可见")
        if left_key == right_key:
            raise ValueError("请选择两名不同的成员")

        selected_keys = [left_key, right_key]
        selected_owners = [owners[key] for key in selected_keys]
        owner_tuples = [(owner["ownerType"], owner["ownerId"]) for owner in selected_owners]
        handle_rows = battle_union_rows(
            conn,
            "handles",
            "*",
            owner_tuples,
            extra_where="AND active = 1",
            order_by="created_at",
        )
        for row in handle_rows:
            key = f"{row['owner_type']}:{row['owner_id']}"
            if key in owners:
                item = handle_to_json(row)
                item.pop("lastError", None)
                item.pop("syncStatus", None)
                owners[key]["handles"].append(item)

        contest_range_sql = "participated_at < ?"
        contest_params: tuple[object, ...] = (end_timestamp,)
        if start_timestamp is not None:
            contest_range_sql = "participated_at >= ? AND participated_at < ?"
            contest_params = (start_timestamp, end_timestamp)
        contest_rows = battle_union_rows(
            conn,
            "contests",
            "*",
            owner_tuples,
            extra_where=f"AND {contest_range_sql}",
            extra_params=contest_params,
            order_by="participated_at DESC",
        )
        period_contests: dict[str, dict[tuple[str, str], dict]] = {key: {} for key in selected_keys}
        for row in contest_rows:
            owner_key = f"{row['owner_type']}:{row['owner_id']}"
            if owner_key not in period_contests:
                continue
            contest_key = battle_contest_key(row)
            entry = battle_contest_entry(row)
            existing = period_contests[owner_key].get(contest_key)
            if not existing or battle_contest_preference(entry) > battle_contest_preference(existing):
                period_contests[owner_key][contest_key] = entry

        shared_keys = set(period_contests[left_key]) & set(period_contests[right_key])
        shared_entries = {
            key: (period_contests[left_key][key], period_contests[right_key][key])
            for key in shared_keys
        }
        contest_solves: dict[str, dict[tuple[str, str], dict[str, dict]]] = {
            key: {contest_key: {} for contest_key in shared_keys}
            for key in selected_keys
        }

        if shared_keys:
            known_starts = [
                entry.get("_startTimestamp")
                for pair in shared_entries.values()
                for entry in pair
                if entry.get("_startTimestamp")
            ]
            submission_where = """AND (
                UPPER(TRIM(COALESCE(verdict, ''))) IN ('AC', 'OK', 'ACCEPTED')
                OR TRIM(COALESCE(verdict, '')) IN ('答案正确', '通过', '12')
            ) AND submitted_at < ?"""
            submission_params: tuple[object, ...] = (end_timestamp,)
            lower_bound = min(known_starts) if known_starts else start_timestamp
            if lower_bound is not None:
                submission_where += " AND submitted_at >= ?"
                submission_params = (end_timestamp, lower_bound)
            submission_rows = battle_union_rows(
                conn,
                "submissions",
                "owner_type, owner_id, platform, handle, remote_id, problem_id, problem_name, verdict, submitted_at, url, raw_json",
                owner_tuples,
                extra_where=submission_where,
                extra_params=submission_params,
                order_by="submitted_at",
            )
            for row in submission_rows:
                owner_key = f"{row['owner_type']}:{row['owner_id']}"
                raw = raw_json_dict(row)
                contest_key = (str(row["platform"] or ""), battle_submission_contest_id(row, raw))
                pair = shared_entries.get(contest_key)
                if not pair or owner_key not in contest_solves:
                    continue
                entry = pair[0] if owner_key == left_key else pair[1]
                solve = battle_in_contest_solve(row, entry)
                if not solve:
                    continue
                existing = contest_solves[owner_key][contest_key].get(solve["key"])
                if not existing or solve["elapsedSeconds"] < existing["elapsedSeconds"]:
                    contest_solves[owner_key][contest_key][solve["key"]] = solve

        shared_contests = []
        left_wins = 0
        right_wins = 0
        ties = 0
        ranked_contests = 0
        same_team_contests = 0
        speed_totals = {"left": 0, "right": 0, "tie": 0}
        platform_results: dict[str, dict] = {}
        for contest_key, (left, right) in shared_entries.items():
            left_result = left["result"]
            right_result = right["result"]
            participant_key = left.get("_participantKey")
            same_team = bool(participant_key and participant_key == right.get("_participantKey"))
            winner = None
            if same_team:
                same_team_contests += 1
                winner = "same-team"
            elif left_result.get("rank") is not None and right_result.get("rank") is not None:
                ranked_contests += 1
                if left_result["rank"] < right_result["rank"]:
                    winner = "left"
                    left_wins += 1
                elif right_result["rank"] < left_result["rank"]:
                    winner = "right"
                    right_wins += 1
                else:
                    winner = "tie"
                    ties += 1

            left_solves = contest_solves[left_key][contest_key]
            right_solves = contest_solves[right_key][contest_key]
            problem_duels = []
            contest_speed = {"left": 0, "right": 0, "tie": 0}
            problem_keys = set() if same_team else set(left_solves) | set(right_solves)
            for problem_key in problem_keys:
                left_solve = left_solves.get(problem_key)
                right_solve = right_solves.get(problem_key)
                if left_solve and not right_solve:
                    problem_winner = "left"
                elif right_solve and not left_solve:
                    problem_winner = "right"
                elif left_solve["elapsedSeconds"] < right_solve["elapsedSeconds"]:
                    problem_winner = "left"
                elif right_solve["elapsedSeconds"] < left_solve["elapsedSeconds"]:
                    problem_winner = "right"
                else:
                    problem_winner = "tie"
                contest_speed[problem_winner] += 1
                speed_totals[problem_winner] += 1
                source = left_solve or right_solve
                problem_duels.append(
                    {
                        "key": problem_key,
                        "problemId": source.get("problemId"),
                        "problemName": source.get("problemName"),
                        "winner": problem_winner,
                        "deltaSeconds": (
                            abs(left_solve["elapsedSeconds"] - right_solve["elapsedSeconds"])
                            if left_solve and right_solve
                            else None
                        ),
                        "left": left_solve,
                        "right": right_solve,
                    }
                )
            problem_duels.sort(
                key=lambda item: (
                    max(
                        item["left"]["elapsedSeconds"] if item["left"] else -1,
                        item["right"]["elapsedSeconds"] if item["right"] else -1,
                    ),
                    item["key"],
                )
            )

            platform = left["platform"]
            platform_item = platform_results.setdefault(
                platform,
                {
                    "platform": platform,
                    "platformLabel": left["platformLabel"],
                    "shared": 0,
                    "ranked": 0,
                    "leftWins": 0,
                    "rightWins": 0,
                    "ties": 0,
                    "sameTeamContests": 0,
                },
            )
            platform_item["shared"] += 1
            if same_team:
                platform_item["sameTeamContests"] += 1
            elif winner:
                platform_item["ranked"] += 1
                if winner == "left":
                    platform_item["leftWins"] += 1
                elif winner == "right":
                    platform_item["rightWins"] += 1
                else:
                    platform_item["ties"] += 1

            shared_contests.append(
                {
                    "platform": platform,
                    "platformLabel": left["platformLabel"],
                    "remoteId": left["remoteId"],
                    "contestName": left["contestName"],
                    "category": left["category"],
                    "categoryLabel": left["categoryLabel"],
                    "participatedAt": left["participatedAt"],
                    "participatedDate": left["participatedDate"],
                    "url": left["url"],
                    "leftHandle": left.get("handle") or "",
                    "rightHandle": right.get("handle") or "",
                    "leftResult": left_result,
                    "rightResult": right_result,
                    "winner": winner,
                    "sameTeam": same_team,
                    "speed": {
                        "leftWins": contest_speed["left"],
                        "rightWins": contest_speed["right"],
                        "ties": contest_speed["tie"],
                        "problems": len(problem_duels),
                    },
                    "problemDuels": problem_duels,
                }
            )

        shared_contests.sort(key=lambda item: (item["participatedAt"], item["platform"], item["remoteId"]), reverse=True)
        timeline = battle_elo_timeline(shared_contests)
        platform_rank = {key: index for index, key in enumerate(ADAPTERS)}
        by_platform = sorted(
            platform_results.values(),
            key=lambda item: (platform_rank.get(item["platform"], 999), item["platformLabel"]),
        )
        player_ratings = [timeline["leftRating"], timeline["rightRating"]]
        player_wins = [left_wins, right_wins]
        player_speed_wins = [speed_totals["left"], speed_totals["right"]]
        players = []
        for index, (key, owner) in enumerate(zip(selected_keys, selected_owners)):
            own_contests = period_contests[key].values()
            players.append(
                {
                    **owner,
                    "stats": {
                        "contests": len(period_contests[key]),
                        "ratedContests": sum(1 for item in own_contests if item["result"].get("rated")),
                        "sharedContests": len(shared_keys),
                        "rankedSharedContests": ranked_contests,
                        "contestWins": player_wins[index],
                        "speedWins": player_speed_wins[index],
                        "duelRating": player_ratings[index],
                    },
                }
            )

        return {
            "range": selected_range,
            "players": players,
            "headToHead": {
                "leftWins": left_wins,
                "rightWins": right_wins,
                "ties": ties,
                "rankedContests": ranked_contests,
                "sameTeamContests": same_team_contests,
                "unrankedContests": len(shared_keys) - ranked_contests - same_team_contests,
                "sharedContests": len(shared_keys),
                "leftSpeedWins": speed_totals["left"],
                "rightSpeedWins": speed_totals["right"],
                "speedTies": speed_totals["tie"],
                "speedProblems": sum(speed_totals.values()),
            },
            "timeline": timeline,
            "byPlatform": by_platform,
            "sharedContests": shared_contests[:100],
            "sharedContestLimit": 100,
        }


def battle_memory_cache_key(
    principal: dict | None,
    left_key: str,
    right_key: str,
    range_key: str,
) -> tuple[str, ...]:
    return (
        str(DB_PATH),
        str(principal.get("type") if principal else "anon"),
        str(principal.get("id") if principal else ""),
        normalize_team_name(principal.get("teamName"), "") if principal else "",
        left_key,
        right_key,
        range_key,
    )


def prune_battle_memory_cache(now: int) -> None:
    expired_keys = [
        key
        for key, (cached_at, _) in BATTLE_MEMORY_CACHE.items()
        if now - cached_at > OVERVIEW_CACHE_TTL_SECONDS
    ]
    for key in expired_keys:
        BATTLE_MEMORY_CACHE.pop(key, None)
    while len(BATTLE_MEMORY_CACHE) > BATTLE_MEMORY_CACHE_LIMIT:
        oldest_key = min(BATTLE_MEMORY_CACHE, key=lambda item: BATTLE_MEMORY_CACHE[item][0])
        BATTLE_MEMORY_CACHE.pop(oldest_key, None)


def build_battle(principal: dict | None, left_key: str, right_key: str, range_key: str = "365") -> dict:
    key = battle_memory_cache_key(principal, left_key, right_key, range_key)
    now = utcnow()
    if OVERVIEW_CACHE_TTL_SECONDS > 0:
        with OVERVIEW_CACHE_LOCK:
            prune_battle_memory_cache(now)
            cached = BATTLE_MEMORY_CACHE.get(key)
            if cached and now - cached[0] <= OVERVIEW_CACHE_TTL_SECONDS:
                BATTLE_MEMORY_CACHE[key] = (now, cached[1])
                return cached[1]

    battle = build_battle_from_db(principal, left_key, right_key, range_key)
    if OVERVIEW_CACHE_TTL_SECONDS > 0:
        with OVERVIEW_CACHE_LOCK:
            if key not in BATTLE_MEMORY_CACHE and len(BATTLE_MEMORY_CACHE) >= BATTLE_MEMORY_CACHE_LIMIT:
                oldest_key = min(BATTLE_MEMORY_CACHE, key=lambda item: BATTLE_MEMORY_CACHE[item][0])
                BATTLE_MEMORY_CACHE.pop(oldest_key, None)
            BATTLE_MEMORY_CACHE[key] = (now, battle)
    return battle


def competition_pair_result(battle: dict) -> tuple[int, int, str | None]:
    head_to_head = battle["headToHead"]
    if not head_to_head["rankedContests"]:
        return 0, 0, None
    if head_to_head["leftWins"] > head_to_head["rightWins"]:
        return 3, 0, "left"
    if head_to_head["rightWins"] > head_to_head["leftWins"]:
        return 0, 3, "right"
    return 1, 1, "tie"


def competition_member_record(player: dict) -> dict:
    return {
        **{key: value for key, value in player.items() if key != "stats"},
        "stats": {
            "points": 0,
            "matchWins": 0,
            "matchDraws": 0,
            "matchLosses": 0,
            "validMatches": 0,
            "contestWins": 0,
            "contestLosses": 0,
            "contestTies": 0,
            "sharedContests": 0,
            "rankedSharedContests": 0,
            "speedWins": 0,
            "speedLosses": 0,
            "contests": 0,
            "ratedContests": 0,
            "duelRating": BATTLE_INITIAL_RATING,
        },
        "_ratingDeltaTotal": 0,
        "_ratingCount": 0,
    }


def add_competition_member_result(
    record: dict,
    player: dict,
    own_side: str,
    pair_points: int,
    pair_winner: str | None,
    battle: dict,
) -> None:
    stats = record["stats"]
    player_stats = player["stats"]
    head_to_head = battle["headToHead"]
    other_side = "right" if own_side == "left" else "left"
    stats["contests"] = max(stats["contests"], player_stats["contests"])
    stats["ratedContests"] = max(stats["ratedContests"], player_stats["ratedContests"])
    stats["sharedContests"] += head_to_head["sharedContests"]
    stats["rankedSharedContests"] += head_to_head["rankedContests"]
    stats["contestWins"] += head_to_head[f"{own_side}Wins"]
    stats["contestLosses"] += head_to_head[f"{other_side}Wins"]
    stats["contestTies"] += head_to_head["ties"]
    stats["speedWins"] += head_to_head[f"{own_side}SpeedWins"]
    stats["speedLosses"] += head_to_head[f"{other_side}SpeedWins"]
    record["_ratingDeltaTotal"] += player_stats["duelRating"] - BATTLE_INITIAL_RATING
    record["_ratingCount"] += 1
    if pair_winner is None:
        return
    stats["points"] += pair_points
    stats["validMatches"] += 1
    if pair_winner == own_side:
        stats["matchWins"] += 1
    elif pair_winner == "tie":
        stats["matchDraws"] += 1
    else:
        stats["matchLosses"] += 1


def finalize_competition_members(records: dict[str, dict], include_rank: bool = True) -> list[dict]:
    members = []
    for record in records.values():
        rating_count = record.pop("_ratingCount")
        rating_delta_total = record.pop("_ratingDeltaTotal")
        record["stats"]["duelRating"] = round(
            BATTLE_INITIAL_RATING + (rating_delta_total / rating_count if rating_count else 0)
        )
        members.append(record)

    members.sort(
        key=lambda item: (
            -item["stats"]["points"],
            -item["stats"]["contestWins"],
            -item["stats"]["speedWins"],
            -item["stats"]["duelRating"],
            item["displayName"].casefold(),
        )
    )
    if include_rank:
        previous_score = None
        previous_rank = 0
        for index, member in enumerate(members, start=1):
            score = (
                member["stats"]["points"],
                member["stats"]["contestWins"],
                member["stats"]["speedWins"],
                member["stats"]["duelRating"],
            )
            if score != previous_score:
                previous_rank = index
                previous_score = score
            member["rank"] = previous_rank
    return members


def build_competition(
    principal: dict | None,
    mode: str,
    range_key: str = "365",
    member_keys: list[str] | None = None,
    left_keys: list[str] | None = None,
    right_keys: list[str] | None = None,
) -> dict:
    selected_range = battle_range(range_key)
    requested_member_keys = list(member_keys or [])
    member_keys = list(dict.fromkeys(requested_member_keys))
    left_keys = list(left_keys or [])
    right_keys = list(right_keys or [])

    if mode == "individual":
        if len(member_keys) != len(requested_member_keys) or not 2 <= len(member_keys) <= 5:
            raise ValueError("个人排名请选择 2 至 5 名不同成员")
        pair_keys = [
            (member_keys[left_index], member_keys[right_index])
            for left_index in range(len(member_keys))
            for right_index in range(left_index + 1, len(member_keys))
        ]
    elif mode == "team":
        if len(left_keys) != 3 or len(right_keys) != 3:
            raise ValueError("3v3 对战需要每队选择 3 名成员")
        if len(set(left_keys + right_keys)) != 6:
            raise ValueError("3v3 对战的 6 名成员不能重复")
        pair_keys = [(left_key, right_key) for left_key in left_keys for right_key in right_keys]
    else:
        raise ValueError("不支持的排名模式")

    member_records: dict[str, dict] = {}
    comparisons = []
    team_stats = [
        {
            "points": 0,
            "pairWins": 0,
            "pairDraws": 0,
            "pairLosses": 0,
            "validPairs": 0,
            "contestWins": 0,
            "contestLosses": 0,
            "contestTies": 0,
            "sharedContests": 0,
            "rankedSharedContests": 0,
            "speedWins": 0,
            "speedLosses": 0,
        }
        for _ in range(2)
    ]

    for left_key, right_key in pair_keys:
        battle = build_battle(principal, left_key, right_key, range_key)
        left_player, right_player = battle["players"]
        member_records.setdefault(left_key, competition_member_record(left_player))
        member_records.setdefault(right_key, competition_member_record(right_player))
        left_points, right_points, winner = competition_pair_result(battle)
        add_competition_member_result(
            member_records[left_key], left_player, "left", left_points, winner, battle
        )
        add_competition_member_result(
            member_records[right_key], right_player, "right", right_points, winner, battle
        )

        head_to_head = battle["headToHead"]
        comparisons.append(
            {
                "leftKey": left_key,
                "rightKey": right_key,
                "leftName": left_player["displayName"],
                "rightName": right_player["displayName"],
                "leftWins": head_to_head["leftWins"],
                "rightWins": head_to_head["rightWins"],
                "ties": head_to_head["ties"],
                "rankedContests": head_to_head["rankedContests"],
                "sharedContests": head_to_head["sharedContests"],
                "leftSpeedWins": head_to_head["leftSpeedWins"],
                "rightSpeedWins": head_to_head["rightSpeedWins"],
                "winner": winner,
            }
        )

        if mode == "team":
            for team_index, (own_side, pair_points) in enumerate(
                (("left", left_points), ("right", right_points))
            ):
                other_side = "right" if own_side == "left" else "left"
                stats = team_stats[team_index]
                stats["points"] += pair_points
                stats["contestWins"] += head_to_head[f"{own_side}Wins"]
                stats["contestLosses"] += head_to_head[f"{other_side}Wins"]
                stats["contestTies"] += head_to_head["ties"]
                stats["sharedContests"] += head_to_head["sharedContests"]
                stats["rankedSharedContests"] += head_to_head["rankedContests"]
                stats["speedWins"] += head_to_head[f"{own_side}SpeedWins"]
                stats["speedLosses"] += head_to_head[f"{other_side}SpeedWins"]
                if winner is not None:
                    stats["validPairs"] += 1
                    if winner == own_side:
                        stats["pairWins"] += 1
                    elif winner == "tie":
                        stats["pairDraws"] += 1
                    else:
                        stats["pairLosses"] += 1

    if mode == "individual":
        return {
            "mode": mode,
            "range": selected_range,
            "rankings": finalize_competition_members(member_records),
            "comparisons": comparisons,
        }

    finalized_members = {
        f"{member['ownerType']}:{member['ownerId']}": member
        for member in finalize_competition_members(member_records, include_rank=False)
    }
    return {
        "mode": mode,
        "range": selected_range,
        "teams": [
            {
                "side": "left",
                "members": [finalized_members[key] for key in left_keys],
                "stats": team_stats[0],
            },
            {
                "side": "right",
                "members": [finalized_members[key] for key in right_keys],
                "stats": team_stats[1],
            },
        ],
        "comparisons": comparisons,
    }


class AppHandler(BaseHTTPRequestHandler):
    server_version = "OJWall/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def send_json(self, status: int, data: dict, extra_headers: list[tuple[str, str]] | None = None) -> None:
        payload = json_dumps(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        if extra_headers:
            for name, value in extra_headers:
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def send_html(self, status: int, html_text: str, extra_headers: list[tuple[str, str]] | None = None) -> None:
        payload = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if extra_headers:
            for name, value in extra_headers:
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json(status, {"ok": False, "error": message})

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                return self.send_json(200, {"ok": True, "app": APP_NAME, "time": iso_from_ts(utcnow())})
            if path == "/api/session":
                principal = get_current_principal(self)
                return self.send_json(200, {"ok": True, "user": principal, "platforms": platform_meta()})
            if path == "/api/overview":
                params = urllib.parse.parse_qs(parsed.query)
                days = int(params.get("days", ["365"])[0])
                principal = None
                try:
                    principal = get_current_principal(self)
                    overview = build_overview(principal, days=days)
                except Exception as exc:
                    traceback.print_exc()
                    cached = read_overview_cache(principal, exc)
                    if cached:
                        return self.send_json(200, {"ok": True, **cached})
                    raise
                return self.send_json(200, {"ok": True, **overview})
            if path == "/api/battle":
                params = urllib.parse.parse_qs(parsed.query)
                left_key = str(params.get("left", [""])[0])
                right_key = str(params.get("right", [""])[0])
                range_key = str(params.get("range", ["365"])[0])
                if not left_key or not right_key:
                    return self.send_error_json(400, "请选择两名成员")
                principal = get_current_principal(self)
                try:
                    battle = build_battle(principal, left_key, right_key, range_key)
                except ValueError as exc:
                    return self.send_error_json(400, str(exc))
                return self.send_json(200, {"ok": True, **battle})
            if path == "/api/competition":
                params = urllib.parse.parse_qs(parsed.query)
                mode = str(params.get("mode", [""])[0])
                range_key = str(params.get("range", ["365"])[0])
                principal = get_current_principal(self)
                try:
                    competition = build_competition(
                        principal,
                        mode,
                        range_key=range_key,
                        member_keys=[str(key) for key in params.get("member", [])],
                        left_keys=[str(key) for key in params.get("left", [])],
                        right_keys=[str(key) for key in params.get("right", [])],
                    )
                except ValueError as exc:
                    return self.send_error_json(400, str(exc))
                return self.send_json(200, {"ok": True, **competition})
            if path == "/api/auth/verify":
                return self.handle_verify(parsed)
            if path == "/" or path == "/index.html":
                return self.serve_static("index.html")
            if path in {"/app.js", "/styles.css"}:
                return self.serve_static(path.lstrip("/"))
            return self.send_error_json(404, "没有这个接口")
        except Exception as exc:
            traceback.print_exc()
            return self.send_error_json(500, str(exc) if APP_ENV != "production" else "服务器内部错误")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/auth/register":
                return self.handle_register()
            if parsed.path == "/api/auth/login":
                return self.handle_login()
            if parsed.path == "/api/auth/logout":
                return self.handle_logout()
            if parsed.path == "/api/guest":
                return self.handle_guest()
            if parsed.path == "/api/handles":
                return self.handle_add_handle()
            if re.match(r"^/api/handles/\d+/sync$", parsed.path):
                return self.handle_sync_handle(parsed)
            if parsed.path in {"/api/me/team", "/api/me/profile"}:
                return self.handle_update_profile()
            if parsed.path == "/api/sync":
                return self.handle_sync()
            return self.send_error_json(404, "没有这个接口")
        except ValueError as exc:
            return self.send_error_json(400, str(exc))
        except sqlite3.IntegrityError as exc:
            return self.send_error_json(409, str(exc))
        except Exception as exc:
            traceback.print_exc()
            return self.send_error_json(500, str(exc) if APP_ENV != "production" else "服务器内部错误")

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/handles" or parsed.path.startswith("/api/handles/"):
                return self.handle_delete_handle(parsed)
            return self.send_error_json(404, "没有这个接口")
        except ValueError as exc:
            return self.send_error_json(400, str(exc))
        except Exception as exc:
            traceback.print_exc()
            return self.send_error_json(500, str(exc) if APP_ENV != "production" else "服务器内部错误")

    def serve_static(self, name: str) -> None:
        path = (WEB_ROOT / name).resolve()
        if WEB_ROOT not in path.parents and path != WEB_ROOT:
            return self.send_error_json(403, "禁止访问")
        if not path.exists() or not path.is_file():
            return self.send_error_json(404, "文件不存在")
        suffix = path.suffix.lower()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(suffix, "application/octet-stream")
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def handle_verify(self, parsed) -> None:
        params = urllib.parse.parse_qs(parsed.query)
        token = params.get("token", [""])[0]
        if not token:
            return self.send_html(400, "<h1>验证链接无效</h1><p>缺少 token。</p>")
        now = utcnow()
        with connect_db() as conn:
            row = conn.execute(
                """
                SELECT token_hash, user_id, expires_at, used_at
                FROM verification_tokens
                WHERE token_hash = ?
                """,
                (sha256_hex(token),),
            ).fetchone()
            if not row or row["used_at"]:
                return self.send_html(400, "<h1>验证链接无效</h1><p>这个链接不存在或已经使用。</p>")
            if row["expires_at"] < now:
                return self.send_html(400, "<h1>验证链接已过期</h1><p>请重新注册或联系管理员。</p>")
            conn.execute("UPDATE users SET verified = 1 WHERE id = ?", (row["user_id"],))
            conn.execute("UPDATE verification_tokens SET used_at = ? WHERE token_hash = ?", (now, row["token_hash"]))
        return self.send_html(
            200,
            """
            <!doctype html>
            <meta charset="utf-8">
            <title>邮箱验证完成</title>
            <style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:40px;color:#17202a}</style>
            <h1>邮箱验证完成</h1>
            <p>现在可以返回训练墙登录。</p>
            <p><a href="/">打开 OJ Submission Wall</a></p>
            """,
        )

    def handle_register(self) -> None:
        data = read_json_body(self)
        username = normalize_username(str(data.get("username") or data.get("displayName") or ""))
        email = local_account_email(username)
        display_name = normalize_display_name(data.get("displayName") or data.get("username"), username)
        real_name = normalize_real_name(data.get("realName"))
        team_name = normalize_team_name(data.get("teamName"), DEFAULT_TEAM_NAME)
        password = str(data.get("password") or "")
        if len(password) < 8:
            raise ValueError("密码至少 8 位")

        with connect_db() as conn:
            existing = conn.execute(
                "SELECT username FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if existing:
                raise ValueError("用户名已经被注册")
            cur = conn.execute(
                """
                INSERT INTO users(username, email, display_name, real_name, password_hash, verified, team_name, created_at)
                VALUES(?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (username, email, display_name, real_name, password_hash(password), team_name, utcnow()),
            )
            user_id = str(cur.lastrowid)
            token = create_session(conn, "user", user_id, days=30)
        clear_overview_memory_cache()
        return self.send_json(
            201,
            {
                "ok": True,
                "message": "注册成功，已登录。",
                "user": {
                    "type": "user",
                    "id": user_id,
                    "username": username,
                    "displayName": display_name,
                    "realName": real_name,
                    "teamName": team_name,
                    "verified": True,
                },
            },
            extra_headers=[("Set-Cookie", cookie_header(token, 30 * 86400))],
        )

    def handle_login(self) -> None:
        data = read_json_body(self)
        username = normalize_username(str(data.get("username") or data.get("email") or ""))
        password = str(data.get("password") or "")
        with connect_db() as conn:
            row = conn.execute(
                "SELECT id, username, email, display_name, real_name, password_hash, verified, team_name FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if not row or not verify_password(password, row["password_hash"]):
                return self.send_error_json(401, "用户名或密码不正确")
            token = create_session(conn, "user", str(row["id"]), days=30)
        return self.send_json(
            200,
            {
                "ok": True,
                "user": {
                    "type": "user",
                    "id": str(row["id"]),
                    "username": row["username"],
                    "displayName": row["display_name"],
                    "realName": row["real_name"] or "",
                    "teamName": row["team_name"] or DEFAULT_TEAM_NAME,
                    "verified": True,
                },
            },
            extra_headers=[("Set-Cookie", cookie_header(token, 30 * 86400))],
        )

    def handle_logout(self) -> None:
        cookie_header_text = self.headers.get("Cookie", "")
        jar = cookies.SimpleCookie()
        with contextlib.suppress(cookies.CookieError):
            jar.load(cookie_header_text)
        token = jar.get(SESSION_COOKIE).value if jar.get(SESSION_COOKIE) else None
        with connect_db() as conn:
            delete_session(conn, token)
        return self.send_json(200, {"ok": True}, extra_headers=[("Set-Cookie", expired_cookie_header())])

    def handle_guest(self) -> None:
        data = read_json_body(self)
        display_name = normalize_display_name(data.get("displayName"), "游客-" + secrets.token_hex(2))
        real_name = normalize_real_name(data.get("realName"))
        team_name = normalize_team_name(data.get("teamName"), GUEST_TEAM_NAME)
        guest_id = secrets.token_urlsafe(12)
        with connect_db() as conn:
            conn.execute(
                "INSERT INTO guests(id, display_name, real_name, team_name, created_at) VALUES(?, ?, ?, ?, ?)",
                (guest_id, display_name, real_name, team_name, utcnow()),
            )
            token = create_session(conn, "guest", guest_id, days=7)
        clear_overview_memory_cache()
        return self.send_json(
            201,
            {
                "ok": True,
                "user": {
                    "type": "guest",
                    "id": guest_id,
                    "displayName": display_name,
                    "realName": real_name,
                    "teamName": team_name,
                    "verified": False,
                },
            },
            extra_headers=[("Set-Cookie", cookie_header(token, 7 * 86400))],
        )

    def handle_update_profile(self) -> None:
        principal = get_current_principal(self)
        if not principal:
            return self.send_error_json(401, "请先登录或进入游客模式")
        data = read_json_body(self)
        fallback = GUEST_TEAM_NAME if principal["type"] == "guest" else DEFAULT_TEAM_NAME
        display_name = normalize_display_name(data.get("displayName", principal.get("displayName")), principal["displayName"])
        real_name = normalize_real_name(data.get("realName", principal.get("realName") or ""))
        team_name = normalize_team_name(data.get("teamName"), fallback)
        table = "guests" if principal["type"] == "guest" else "users"
        with connect_db() as conn:
            conn.execute(
                f"UPDATE {table} SET display_name = ?, real_name = ?, team_name = ? WHERE id = ?",
                (display_name, real_name, team_name, str(principal["id"])),
            )
        clear_overview_memory_cache()
        principal["displayName"] = display_name
        principal["realName"] = real_name
        principal["teamName"] = team_name
        return self.send_json(200, {"ok": True, "user": principal})

    def handle_add_handle(self) -> None:
        principal = get_current_principal(self)
        if not principal:
            return self.send_error_json(401, "请先登录或进入游客模式")
        data = read_json_body(self)
        platform = str(data.get("platform") or "").strip().lower()
        handle = str(data.get("handle") or "")
        luogu_auth = luogu_auth_from_payload(self, data)
        with connect_db() as conn:
            row = add_or_restore_handle(conn, principal, platform, handle)
        queue_result = enqueue_sync_job(
            principal=principal,
            handle_id=int(row["id"]),
            force=True,
            full=False,
            luogu_auth=luogu_auth,
        )
        with connect_db() as conn:
            refreshed = get_owned_handle_row(conn, principal, int(row["id"])) or row
        return self.send_json(
            202,
            {
                "ok": True,
                "handle": handle_to_json(refreshed, sync_status_snapshot()),
                "sync": [queue_result],
                **build_overview(principal, use_cache=False),
            },
        )

    def handle_delete_handle(self, parsed) -> None:
        principal = get_current_principal(self)
        if not principal:
            return self.send_error_json(401, "请先登录或进入游客模式")
        params = urllib.parse.parse_qs(parsed.query)
        handle_id = params.get("id", [""])[0]
        path_match = re.match(r"^/api/handles/(\d+)$", parsed.path)
        if not handle_id and path_match:
            handle_id = path_match.group(1)
        if not handle_id.isdigit():
            raise ValueError("缺少账号绑定 ID")
        try:
            with connect_db() as conn:
                cursor = conn.execute(
                    """
                    UPDATE handles SET active = 0
                    WHERE id = ? AND owner_type = ? AND owner_id = ?
                    """,
                    (int(handle_id), principal["type"], str(principal["id"])),
                )
                if cursor.rowcount <= 0:
                    return self.send_error_json(404, "没有找到这个账号绑定，可能已经移除")
        except sqlite3.OperationalError as exc:
            if is_database_locked_error(exc):
                return self.send_error_json(409, "数据库正在写入同步结果，请稍后再移除")
            raise
        clear_overview_memory_cache()
        return self.send_json(200, {"ok": True})

    def handle_sync_handle(self, parsed) -> None:
        principal = get_current_principal(self)
        if not principal:
            return self.send_error_json(401, "请先登录或进入游客模式")
        path_match = re.match(r"^/api/handles/(\d+)/sync$", parsed.path)
        if not path_match:
            raise ValueError("缺少账号绑定 ID")
        data = read_json_body(self)
        result = enqueue_sync_job(
            principal=principal,
            handle_id=int(path_match.group(1)),
            force=True,
            full=bool(data.get("full")),
            luogu_auth=luogu_auth_from_payload(self, data),
        )
        return self.send_json(202, {"ok": True, "result": result, **build_overview(principal, use_cache=False)})

    def handle_sync(self) -> None:
        principal = get_current_principal(self)
        if not principal:
            return self.send_error_json(401, "请先登录或进入游客模式")
        data = read_json_body(self)
        force = bool(data.get("force"))
        result = enqueue_sync_job(
            principal=principal,
            force=force,
            include_guests=False,
            full=bool(data.get("full")),
            luogu_auth=luogu_auth_from_payload(self, data),
        )
        return self.send_json(202, {"ok": True, "results": [result], **build_overview(principal, use_cache=False)})


def cookie_header(token: str, max_age: int) -> str:
    attrs = [
        f"{SESSION_COOKIE}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={max_age}",
    ]
    if os.environ.get("COOKIE_SECURE", "").lower() in {"1", "true", "yes"}:
        attrs.append("Secure")
    return "; ".join(attrs)


def expired_cookie_header() -> str:
    return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"


def luogu_record_sync_state(row: sqlite3.Row | None) -> dict:
    if not row or "stats_json" not in row.keys() or not row["stats_json"]:
        return {}
    with contextlib.suppress(Exception):
        stats = json.loads(row["stats_json"])
        if isinstance(stats, dict) and isinstance(stats.get("recordSync"), dict):
            return stats["recordSync"]
    return {}


def run_luogu_backfill_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Slowly backfill Luogu record/list pages into the local database.")
    parser.add_argument("--pages-per-round", type=int, default=20, help="history pages to fetch per handle round")
    parser.add_argument("--recent-pages", type=int, default=1, help="latest pages to refresh per handle round")
    parser.add_argument("--sleep-min", type=float, default=0.8, help="minimum sleep seconds between Luogu pages")
    parser.add_argument("--sleep-max", type=float, default=2.0, help="maximum sleep seconds between Luogu pages")
    parser.add_argument("--round-sleep", type=float, default=3.0, help="sleep seconds between handle rounds")
    parser.add_argument("--max-rounds", type=int, default=0, help="maximum rounds per handle; 0 means until complete/error")
    parser.add_argument("--handle-id", action="append", type=int, default=[], help="only backfill a specific handle id; repeatable")
    parser.add_argument("--luogu-cookie", default="", help="temporary Luogu Cookie header for this backfill run")
    parser.add_argument("--luogu-csrf-token", default="", help="temporary Luogu CSRF token for this backfill run")
    args = parser.parse_args(argv)

    global LUOGU_RECORD_RECENT_PAGES_PER_SYNC
    global LUOGU_RECORD_BACKFILL_PAGES_PER_SYNC
    global LUOGU_RECORD_SLEEP_MIN_SECONDS
    global LUOGU_RECORD_SLEEP_MAX_SECONDS
    LUOGU_RECORD_RECENT_PAGES_PER_SYNC = max(0, args.recent_pages)
    LUOGU_RECORD_BACKFILL_PAGES_PER_SYNC = max(1, args.pages_per_round)
    LUOGU_RECORD_SLEEP_MIN_SECONDS = max(0.0, args.sleep_min)
    LUOGU_RECORD_SLEEP_MAX_SECONDS = max(LUOGU_RECORD_SLEEP_MIN_SECONDS, args.sleep_max)

    auth = compact_luogu_auth({"cookie": args.luogu_cookie, "csrfToken": args.luogu_csrf_token})

    init_db()
    with luogu_request_auth(auth), connect_db() as conn:
        params: list[object] = []
        where = "active = 1 AND platform = 'luogu'"
        if args.handle_id:
            placeholders = ",".join("?" for _ in args.handle_id)
            where += f" AND id IN ({placeholders})"
            params.extend(args.handle_id)
        rows = conn.execute(
            f"""
            SELECT *
            FROM handles
            WHERE {where}
            ORDER BY last_sync_at, created_at
            """,
            params,
        ).fetchall()
        print(f"luogu handles: {len(rows)}", flush=True)

        for initial_row in rows:
            rounds = 0
            while True:
                row = conn.execute("SELECT * FROM handles WHERE id = ? AND active = 1", (initial_row["id"],)).fetchone()
                if not row:
                    break
                state_before = luogu_record_sync_state(row)
                if state_before.get("historyComplete"):
                    print(f"done handle_id={row['id']} handle={row['handle']} history already complete", flush=True)
                    break

                rounds += 1
                print(
                    f"sync handle_id={row['id']} handle={row['handle']} "
                    f"round={rounds} nextPage={state_before.get('nextBackfillPage') or '-'}",
                    flush=True,
                )
                result = sync_handle_row(conn, row, force=True, full=True)
                conn.commit()
                refreshed = conn.execute("SELECT * FROM handles WHERE id = ?", (row["id"],)).fetchone()
                state_after = luogu_record_sync_state(refreshed)
                print(
                    json.dumps(
                        {
                            "result": result,
                            "recordSync": {
                                "pagesFetched": state_after.get("pagesFetched"),
                                "nextBackfillPage": state_after.get("nextBackfillPage"),
                                "pageCount": state_after.get("pageCount"),
                                "historyComplete": state_after.get("historyComplete"),
                                "queryUser": state_after.get("queryUser"),
                                "lastError": state_after.get("lastError"),
                            },
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                if state_after.get("historyComplete"):
                    print(f"done handle_id={row['id']} handle={row['handle']}", flush=True)
                    break
                if state_after.get("lastError") or result.get("error"):
                    print(f"paused handle_id={row['id']} due to error; rerun later to continue", flush=True)
                    break
                if args.max_rounds and rounds >= args.max_rounds:
                    print(f"paused handle_id={row['id']} after max rounds", flush=True)
                    break
                if args.round_sleep > 0:
                    time.sleep(args.round_sleep)
    clear_overview_memory_cache()
    return 0


def main() -> None:
    init_db()
    thread = threading.Thread(target=background_sync_loop, daemon=True)
    thread.start()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"{APP_NAME} listening on http://{HOST}:{PORT}", flush=True)
    print(f"SQLite database: {DB_PATH}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "luogu-backfill":
        raise SystemExit(run_luogu_backfill_cli(sys.argv[2:]))
    main()
