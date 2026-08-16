#!/usr/bin/env python3
from __future__ import annotations
import contextlib
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import socket
import smtplib
import sqlite3
import ssl
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
OVERVIEW_CACHE_PATH = CACHE_DIR / "overview.json"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
APP_ENV = os.environ.get("APP_ENV", "development").lower()
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")
SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", "900"))
SYNC_MIN_AGE_SECONDS = int(os.environ.get("SYNC_MIN_AGE_SECONDS", "120"))
FETCH_LOOKBACK_DAYS = int(os.environ.get("FETCH_LOOKBACK_DAYS", "3650"))
FETCH_LIMIT = int(os.environ.get("FETCH_LIMIT", "1000"))
HTTP_TIMEOUT_SECONDS = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "15"))
HTTP_RETRY_COUNT = int(os.environ.get("HTTP_RETRY_COUNT", "2"))
HTTP_RETRY_BACKOFF_SECONDS = float(os.environ.get("HTTP_RETRY_BACKOFF_SECONDS", "0.8"))
HISTORICAL_CACHE_AFTER_DAYS = int(os.environ.get("HISTORICAL_CACHE_AFTER_DAYS", "30"))
HISTORICAL_CACHE_TTL_SECONDS = int(os.environ.get("HISTORICAL_CACHE_TTL_SECONDS", str(3650 * 86400)))
SESSION_COOKIE = "ojwall_session"
DEFAULT_TEAM_NAME = "未分组"
GUEST_TEAM_NAME = "游客"
USER_AGENT = os.environ.get(
    "OJ_USER_AGENT",
    "OJSubmissionWall/1.0 (+https://github.com/your-name/oj-submission-wall)",
)
SMTP_PLACEHOLDERS = {
    "smtp.example.com",
    "noreply@example.com",
    "change-me",
    "your@qq.com",
}


DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
HTTP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
SYNC_LOCK = threading.Lock()
HTTP_STALE_HITS = threading.local()
TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def utcnow() -> int:
    return int(time.time())


def utc_date_from_ts(ts: int) -> str:
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date().isoformat()


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
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
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


def http_get(
    url: str,
    headers: dict[str, str] | None = None,
    cache_ttl_seconds: int | None = None,
    allow_stale_cache: bool = True,
) -> tuple[bytes, str]:
    cached = read_http_cache(url, cache_ttl_seconds) if cache_ttl_seconds is not None else None
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
                    write_http_cache(url, body, content_type)
                return body, content_type
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1 and is_transient_http_error(exc):
                time.sleep(retry_delay(attempt))
                continue
            break
    if allow_stale_cache:
        stale = read_http_cache(url)
        if stale:
            body, content_type, fetched_at = stale
            record_http_stale_hit(url, fetched_at)
            return body, content_type
    if last_exc:
        raise last_exc
    raise RuntimeError("HTTP request failed")


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


def parse_datetime_text(value: str) -> int | None:
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
            return int(parsed.replace(tzinfo=dt.timezone.utc).timestamp())
        except ValueError:
            pass
    return None


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
        contests = {}
        for item in submissions:
            raw = item.get("raw") or {}
            problem = raw.get("problem") or {}
            contest_id = raw.get("contestId") or problem.get("contestId")
            submitted_at = int(item.get("submitted_at") or 0)
            if not contest_id or submitted_at < since_ts:
                continue
            participant_type = str((raw.get("author") or {}).get("participantType") or "")
            if participant_type.upper() == "PRACTICE":
                continue
            contest_id = int(contest_id)
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
                "raw": {"contest": contest, "source": "user.status"},
            }
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
        contests = []
        for item in data:
            contest_screen = str(item.get("ContestScreenName") or "")
            contest_id = contest_screen.split(".", 1)[0]
            name = str(item.get("ContestName") or item.get("ContestNameEn") or contest_id.upper())
            participated_at = parse_iso_datetime(str(item.get("EndTime") or "")) or 0
            if not contest_id or not participated_at or participated_at < since_ts:
                continue
            raw = {**item, "id": contest_id}
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
    handle_hint = "洛谷用户名或数字 UID，例如 Yzm007；也可粘贴用户主页链接"

    def normalize_handle(self, handle: str) -> str:
        handle = handle.strip()
        if not handle:
            raise ValueError("洛谷账号不能为空")
        user_path = re.search(r"luogu\.com\.cn/user/([0-9A-Za-z_\-]+)", handle)
        if user_path:
            handle = user_path.group(1)
        if not re.match(r"^[0-9A-Za-z_\-]{2,32}$", handle):
            raise ValueError("洛谷请填写用户名、数字 UID 或用户主页链接")
        return handle

    def fetch_submissions(self, handle: str, since_ts: int) -> list[dict]:
        uid, profile_name = self._resolve_user(handle)
        profile_url = f"https://www.luogu.com.cn/user/{uid}"
        context = self._fetch_profile_context(uid)
        data = context.get("data") or {}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        profile_name = str(user.get("name") or profile_name)
        daily_counts = data.get("dailyCounts") or {}
        if not isinstance(daily_counts, dict):
            daily_counts = {}

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

    def _resolve_user(self, handle: str) -> tuple[str, str]:
        if handle.isdigit():
            context = self._fetch_profile_context(handle)
            data = context.get("data") or {}
            user = data.get("user") if isinstance(data.get("user"), dict) else {}
            return str(user.get("uid") or handle), str(user.get("name") or handle)

        params = urllib.parse.urlencode({"keyword": handle})
        data = http_get_json(f"https://www.luogu.com.cn/api/user/search?{params}")
        users = data.get("users") if isinstance(data, dict) else []
        if not isinstance(users, list):
            users = []
        exact = None
        for user in users:
            if str(user.get("name") or "").lower() == handle.lower():
                exact = user
                break
        selected = exact or (users[0] if users else None)
        if not selected or not selected.get("uid"):
            raise ValueError(f"没有找到洛谷用户：{handle}")
        return str(selected["uid"]), str(selected.get("name") or handle)

    def _fetch_profile_context(self, uid: str) -> dict:
        body, _ = http_get(
            f"https://www.luogu.com.cn/user/{uid}",
            headers={
                "Referer": "https://www.luogu.com.cn/",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        return self._parse_lentille_context(body.decode("utf-8", errors="ignore"))

    @staticmethod
    def _parse_lentille_context(page: str) -> dict:
        match = re.search(
            r'<script id="lentille-context" type="application/json">(.*?)</script>',
            page,
            flags=re.S,
        )
        if not match:
            raise RuntimeError("洛谷公开个人页没有返回 activity 数据")
        return json.loads(html.unescape(match.group(1)))

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
    handle_hint = "牛客竞赛个人页数字 ID，例如 profile/123456 的 123456"

    def normalize_handle(self, handle: str) -> str:
        match = re.search(r"(\d+)", handle.strip())
        if not match:
            raise ValueError("牛客请填写竞赛个人页数字 ID 或 profile 链接")
        return match.group(1)

    def fetch_submissions(self, handle: str, since_ts: int) -> list[dict]:
        submissions = []
        page_no = 1
        last_page = None
        page_size = 100
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
            url = f"https://ac.nowcoder.com/acm/contest/profile/{handle}/practice-coding?{params}"
            body, _ = http_get(
                url,
                headers={
                    "Referer": f"https://ac.nowcoder.com/acm/contest/profile/{handle}",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            page = body.decode("utf-8", errors="ignore")
            page_submissions, reached_older = self._parse_practice_page(page, since_ts)
            submissions.extend(page_submissions)
            last_page = last_page or self._last_page(page)
            if reached_older or page_no >= last_page:
                break
            page_no += 1
        return submissions

    def fetch_contests(self, handle: str, since_ts: int, submissions: list[dict]) -> list[dict]:
        contests = {}
        for finished in ["true", "false"]:
            page_no = 1
            while True:
                params = urllib.parse.urlencode(
                    {
                        "uid": handle,
                        "page": page_no,
                        "pageSize": 100,
                        "onlyJoinedFilter": "true",
                        "searchContestName": "",
                        "onlyRatingFilter": "false",
                        "contestEndFilter": finished,
                    }
                )
                data = http_get_json(f"https://ac.nowcoder.com/acm-heavy/acm/contest/profile/contest-joined-history?{params}")
                if int(data.get("code") or 0) != 0:
                    raise RuntimeError(data.get("msg") or "牛客参赛记录返回失败")
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
                    contests[contest_id] = {
                        "remote_id": contest_id,
                        "contest_name": name,
                        "category": classify_contest(self.key, name, contest_id, item),
                        "participated_at": participated_at,
                        "url": f"https://ac.nowcoder.com/acm/contest/{contest_id}",
                        "raw": item,
                    }

                page_info = payload.get("pageInfo") or {}
                page_count = int(page_info.get("pageCount") or page_no)
                if reached_older or page_no >= page_count:
                    break
                page_no += 1
        return list(contests.values())

    def _parse_practice_page(self, page: str, since_ts: int) -> tuple[list[dict], bool]:
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, flags=re.I | re.S)
        submissions = []
        reached_older = False
        for row in rows:
            text = strip_tags(row)
            if not re.search(r"20\d\d[-/]\d\d[-/]\d\d", text):
                continue
            submitted_at = parse_datetime_text(text)
            if not submitted_at:
                continue
            if submitted_at < since_ts:
                reached_older = True
                continue
            id_match = re.search(r"(?:submissionId|submitId|id)=([0-9]+)", row)
            if not id_match:
                id_match = re.search(r"/(?:submission|view-submission)[^\"']*?([0-9]{5,})", row)
            problem_match = re.search(r"/acm/problem/([0-9A-Za-z_\\-]+)[^>]*>(.*?)</a>", row, flags=re.I | re.S)
            remote_id = id_match.group(1) if id_match else hashlib.sha1(text.encode("utf-8")).hexdigest()
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
                    "url": f"https://ac.nowcoder.com/acm/contest/view-submission?submissionId={remote_id}" if remote_id.isdigit() else None,
                    "raw": {"text": text},
                }
            )
        return submissions, reached_older

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
    handle_hint = "LOJ 用户名，例如 Yzm007"

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
    handle_hint = "QOJ 用户名；服务端需配置 QOJ_COOKIE"

    def normalize_handle(self, handle: str) -> str:
        handle = handle.strip()
        if not re.match(r"^[0-9A-Za-z_\-.]{2,64}$", handle):
            raise ValueError("QOJ 请填写用户名")
        return handle

    def fetch_submissions(self, handle: str, since_ts: int) -> list[dict]:
        cookie = os.environ.get("QOJ_COOKIE", "").strip()
        if not cookie:
            raise RuntimeError("QOJ 需要配置 QOJ_COOKIE 后才能精确同步；qoj.ac 当前有 Cloudflare 校验")

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


def sync_handle_row(conn: sqlite3.Connection, row: sqlite3.Row, force: bool = False) -> dict:
    now = utcnow()
    if not force and row["last_sync_at"] and now - int(row["last_sync_at"]) < SYNC_MIN_AGE_SECONDS:
        return {"handleId": row["id"], "platform": row["platform"], "handle": row["handle"], "skipped": True}

    adapter = ADAPTERS[row["platform"]]
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
    since_ts = default_since if force or needs_full_retry else max(default_since, int(max_row["max_submitted_at"] or 0) - 3 * 86400)

    try:
        reset_http_stale_hits()
        submissions = adapter.fetch_submissions(row["handle"], since_ts)
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

        contests = []
        contest_error = ""
        try:
            contests = adapter.fetch_contests(row["handle"], since_ts, submissions)
        except Exception as exc:
            detail = str(exc)[:300] or exc.__class__.__name__
            contest_error = f"比赛记录同步失败：{detail}"
        stale_hits = http_stale_hits()
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
        if warnings:
            error = "；".join(warnings)
            conn.execute(
                "UPDATE handles SET last_sync_at = ?, last_error = ? WHERE id = ?",
                (now, error, row["id"]),
            )
            result.update({"warning": error})
        else:
            conn.execute(
                "UPDATE handles SET last_sync_at = ?, last_error = NULL WHERE id = ?",
                (now, row["id"]),
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


def sync_targets(principal: dict | None = None, force: bool = False, include_guests: bool = False) -> list[dict]:
    results: list[dict] = []
    if not SYNC_LOCK.acquire(blocking=False):
        return [{"busy": True}]
    try:
        with connect_db() as conn:
            rows = get_handle_rows(conn, principal=principal, include_guests=include_guests)
            for row in rows:
                results.append(sync_handle_row(conn, row, force=force))
    finally:
        SYNC_LOCK.release()
    return results


def background_sync_loop() -> None:
    while True:
        try:
            sync_targets(principal=None, force=False, include_guests=False)
        except Exception:
            traceback.print_exc()
        time.sleep(max(60, SYNC_INTERVAL_SECONDS))


def handle_to_json(row: sqlite3.Row) -> dict:
    adapter = ADAPTERS.get(row["platform"])
    return {
        "id": row["id"],
        "platform": row["platform"],
        "platformLabel": adapter.label if adapter else row["platform"],
        "handle": row["handle"],
        "lastSyncAt": iso_from_ts(row["last_sync_at"]),
        "lastError": row["last_error"],
    }


def solved_problem_key(row: sqlite3.Row) -> str:
    problem_id = str(row["problem_id"] or row["problem_name"] or row["remote_id"] or "")
    if row["platform"] == "luogu" and problem_id.startswith("luogu-activity-"):
        problem_id = str(row["remote_id"] or problem_id)
    return "\x1f".join([str(row["platform"]), str(row["handle"]), problem_id])


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
    payload.setdefault("mirror", {})["cachedAt"] = iso_from_ts(utcnow())
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
    if error:
        mirror["error"] = str(error)[:300] or error.__class__.__name__
    return data


def build_overview(principal: dict | None, days: int = 365) -> dict:
    overview = build_overview_from_db(principal, days=days)
    with contextlib.suppress(Exception):
        write_overview_cache(overview)
    return overview


def build_overview_from_db(principal: dict | None, days: int = 365) -> dict:
    days = max(7, min(days, 370))
    now = utcnow()
    start_ts = now - (days - 1) * 86400
    today_date = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
    start_date = dt.datetime.fromtimestamp(start_ts, dt.timezone.utc).date()
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
                "days": {},
                "stats": {
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
                },
                "contests": {"items": [], "total": 0, "byCategory": [], "byPlatform": []},
                "_all_days": {},
                "_solved_keys": set(),
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
                "days": {},
                "stats": {
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
                },
                "contests": {"items": [], "total": 0, "byCategory": [], "byPlatform": []},
                "_all_days": {},
                "_solved_keys": set(),
                "_real_name": principal.get("realName") or "",
            }

        handle_rows = get_handle_rows(conn, principal=principal, include_guests=False)
        for row in handle_rows:
            key = (row["owner_type"], row["owner_id"])
            if key not in owners:
                continue
            owners[key]["handles"].append(handle_to_json(row))

        sub_rows = conn.execute(
            """
            SELECT owner_type, owner_id, platform, handle, remote_id, problem_id, problem_name, verdict, submitted_at
            FROM submissions
            ORDER BY submitted_at
            """
        ).fetchall()
        for row in sub_rows:
            key = (row["owner_type"], row["owner_id"])
            if key not in owners:
                continue
            date_key = utc_date_from_ts(row["submitted_at"])
            all_day = owners[key]["_all_days"].setdefault(date_key, {"accepted": 0, "total": 0})
            all_day["total"] += 1
            is_accepted = normalize_verdict(row["verdict"]) == "AC"
            solved_key = solved_problem_key(row)
            is_new_solve = is_accepted and solved_key not in owners[key]["_solved_keys"]
            if is_new_solve:
                all_day["accepted"] += 1
                owners[key]["_solved_keys"].add(solved_key)

            day = owners[key]["days"].setdefault(date_key, {"accepted": 0, "total": 0})
            day["total"] += 1
            owners[key]["stats"]["total"] += 1
            if is_new_solve:
                day["accepted"] += 1
                owners[key]["stats"]["accepted"] += 1

        for owner in owners.values():
            active_dates = [date_key for date_key, counts in owner["days"].items() if counts.get("accepted", 0) > 0]
            owner["stats"]["activeDays"] = len(active_dates)
            all_days = owner.pop("_all_days")
            owner.pop("_solved_keys", None)
            owner["stats"]["streak"] = current_streak(all_days)
            owner["stats"]["allTimeAccepted"] = accepted_since(all_days)
            owner["stats"]["lastYearAccepted"] = accepted_since(all_days, start_date)
            owner["stats"]["lastMonthAccepted"] = accepted_since(all_days, month_start_date)
            owner["stats"]["maxStreakAllTime"] = max_streak(all_days)
            owner["stats"]["maxStreakYear"] = max_streak(all_days, start_date, today_date)
            owner["stats"]["maxStreakMonth"] = max_streak(all_days, month_start_date, today_date)

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
            owners[key]["contests"]["items"].append(contest_to_json(row))

        for owner in owners.values():
            contest_summary = summarize_contests(owner["contests"]["items"])
            owner["contests"].update(contest_summary)
            owner["stats"]["contests"] = contest_summary["total"]
            owner["realNameVisible"] = can_view_real_name(principal, owner)
            owner["realName"] = owner.get("_real_name", "") if owner["realNameVisible"] else ""
            owner.pop("_real_name", None)

        feed_rows = conn.execute(
            """
            SELECT *
            FROM submissions
            ORDER BY submitted_at DESC
            """
        ).fetchall()
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
        return {
            "now": iso_from_ts(now),
            "today": today_date.isoformat(),
            "dateRange": {
                "min": min(date_values) if date_values else today_date.isoformat(),
                "max": max(date_values) if date_values else today_date.isoformat(),
            },
            "availableYears": available_years or [today_date.strftime("%Y")],
            "mirror": build_mirror_meta(conn, now),
            "platforms": platform_meta(),
            "user": principal,
            "members": list(owners.values()),
            "feed": feed,
        }


def current_streak(day_counts: dict[str, dict]) -> int:
    streak = 0
    cursor = dt.datetime.now(dt.timezone.utc).date()
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
    category = row["category"] or "other"
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
        with connect_db() as conn:
            row = add_or_restore_handle(conn, principal, platform, handle)
        sync_result = sync_targets(principal=principal, force=True, include_guests=False)
        return self.send_json(201, {"ok": True, "handle": handle_to_json(row), "sync": sync_result})

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
        return self.send_json(200, {"ok": True})

    def handle_sync(self) -> None:
        principal = get_current_principal(self)
        if not principal:
            return self.send_error_json(401, "请先登录或进入游客模式")
        data = read_json_body(self)
        force = bool(data.get("force"))
        results = sync_targets(principal=principal, force=force, include_guests=False)
        return self.send_json(200, {"ok": True, "results": results, **build_overview(principal)})


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


def main() -> None:
    init_db()
    if SYNC_INTERVAL_SECONDS > 0:
        thread = threading.Thread(target=background_sync_loop, daemon=True)
        thread.start()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"{APP_NAME} listening on http://{HOST}:{PORT}", flush=True)
    print(f"SQLite database: {DB_PATH}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
