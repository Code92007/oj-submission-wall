"""Verified email binding and single-use password recovery."""
from __future__ import annotations

import re
import secrets
import urllib.parse


RESET_MESSAGE = "如果用户名和已验证邮箱匹配，重置链接将发送到邮箱，请查收（含垃圾邮件）。"
ROUTES = {
    "/api/me/email", "/api/auth/bind-email", "/api/auth/verify-email",
    "/api/auth/forgot-password", "/api/auth/reset-password",
}


def init_schema(conn):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "email_verified_at" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN email_verified_at INTEGER")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS account_recovery_tokens (
            token_hash TEXT PRIMARY KEY,
            purpose TEXT NOT NULL CHECK(purpose IN ('bind_email', 'reset_password')),
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            email TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recovery_user
            ON account_recovery_tokens(user_id, purpose);
        CREATE TABLE IF NOT EXISTS account_mail_limits (
            scope_hash TEXT PRIMARY KEY,
            started_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL
        );
    """)


def normalize_email(value):
    email = str(value or "").strip().lower()
    if (len(email) > 254 or not re.fullmatch(r"[^\s@<>\x00-\x1f\x7f]+@[^\s@<>\x00-\x1f\x7f]+\.[^\s@<>\x00-\x1f\x7f]+", email)
            or email.endswith(".invalid")):
        raise ValueError("请输入有效的邮箱地址")
    return email


def consume_limit(app, scope, maximum, window):
    """Commit limits separately, including failed authentication attempts."""
    now = app.utcnow()
    with app.connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM account_mail_limits WHERE started_at <= ?", (now - 86400,))
        cursor = conn.execute("""
            INSERT INTO account_mail_limits VALUES (?, ?, 1)
            ON CONFLICT(scope_hash) DO UPDATE SET
                started_at = CASE WHEN started_at <= ? THEN excluded.started_at ELSE started_at END,
                attempts = CASE WHEN started_at <= ? THEN 1 ELSE attempts + 1 END
            WHERE started_at <= ? OR attempts < ?
        """, (app.sha256_hex(scope), now, now-window, now-window, now-window, maximum))
        return cursor.rowcount == 1


def recovery_url(app, purpose, token):
    # Use configured origin, never the untrusted incoming Host header.
    base = app.PUBLIC_BASE_URL.rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (app.APP_ENV == "production" and parsed.scheme != "https")):
        raise ValueError("请管理员配置正确的 PUBLIC_BASE_URL（生产环境需要 HTTPS）")
    return base + "/account-recovery#" + urllib.parse.urlencode({"action": purpose, "token": token})


def create_token(app, conn, user_id, email, purpose):
    now = app.utcnow()
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM account_recovery_tokens WHERE expires_at <= ?", (now,))
    conn.execute("DELETE FROM account_recovery_tokens WHERE user_id = ? AND purpose = ?", (user_id, purpose))
    conn.execute("INSERT INTO account_recovery_tokens VALUES (?, ?, ?, ?, ?, ?)",
                 (app.sha256_hex(token), purpose, user_id, email, now,
                  now + (1800 if purpose == "reset_password" else 86400)))
    return token


def send_token(app, token, email, display_name, purpose):
    binding = purpose == "bind_email"
    url = recovery_url(app, "verify-email" if binding else "reset-password", token)
    sent = app.send_email(email,
        "验证你的 OJ 训练墙邮箱" if binding else "重置你的 OJ 训练墙密码",
        f"{display_name}，你好：\n\n"
        + ("请打开以下链接，确认将此邮箱绑定为账号的密码找回邮箱。链接 24 小时内有效：\n"
           if binding else "请打开以下链接设置新密码。链接 30 分钟内有效，只能使用一次：\n")
        + url + "\n\n如果不是你本人操作，请忽略此邮件。\n")
    if not sent:
        with app.connect_db() as conn:
            conn.execute("DELETE FROM account_recovery_tokens WHERE token_hash = ?", (app.sha256_hex(token),))
    return sent


class RecoveryHandler:
    def __init__(self, handler, app):
        self.handler, self.app = handler, app

    def error(self, status, message):
        return self.handler.send_error_json(status, message)

    def mail_ready(self):
        if not self.app.smtp_configured():
            self.error(503, "邮箱服务尚未配置，请联系管理员")
            return False
        try:
            recovery_url(self.app, "reset-password", "")
        except ValueError as exc:
            self.error(503, str(exc))
            return False
        return True

    def user(self):
        principal = self.app.get_current_principal(self.handler)
        if not principal or principal["type"] != "user":
            self.error(401, "请先登录正式账号")
            return None
        return principal

    def email_status(self):
        principal = self.user()
        if not principal:
            return
        with self.app.connect_db() as conn:
            user = conn.execute("SELECT email, email_verified_at FROM users WHERE id = ?", (principal["id"],)).fetchone()
            pending = conn.execute("""SELECT email FROM account_recovery_tokens
                WHERE user_id = ? AND purpose = 'bind_email' AND expires_at > ?""",
                (principal["id"], self.app.utcnow())).fetchone()
        return self.handler.send_json(200, {"ok": True,
            "email": "" if user["email"].endswith(".invalid") else user["email"],
            "verified": user["email_verified_at"] is not None,
            "pendingEmail": pending["email"] if pending else ""})

    def bind_email(self):
        principal = self.user()
        if not principal:
            return
        data = self.app.read_json_body(self.handler)
        email = normalize_email(data.get("email"))
        if not consume_limit(self.app, "bind:" + principal["id"], 5, 900):
            return self.error(429, "操作过于频繁，请 15 分钟后再试")
        with self.app.connect_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT * FROM users WHERE id = ?", (principal["id"],)).fetchone()
            if not self.app.verify_password(str(data.get("password") or ""), user["password_hash"]):
                return self.error(400, "当前密码不正确")
            if conn.execute("SELECT id FROM users WHERE lower(email) = ? AND id != ?", (email, user["id"])).fetchone():
                return self.error(409, "该邮箱已绑定其他账号")
            if user["email"] == email and user["email_verified_at"] is not None:
                return self.handler.send_json(200, {"ok": True, "message": "此邮箱已验证，可以用于找回密码。"})
            if user["email"] != email:
                conn.execute("UPDATE users SET email = ?, email_verified_at = NULL WHERE id = ?", (email, user["id"]))
                conn.execute("DELETE FROM account_recovery_tokens WHERE user_id = ?", (user["id"],))
            try:
                recovery_url(self.app, "verify-email", "")
                ready = self.app.smtp_configured()
            except ValueError:
                ready = False
            token = create_token(self.app, conn, user["id"], email, "bind_email") if ready else None
        if not ready:
            return self.handler.send_json(200, {"ok": True,
                "message": "邮箱已保存，尚未验证。邮件服务启用后，请再次点击发送验证邮件。"})
        if not send_token(self.app, token, email, user["display_name"], "bind_email"):
            return self.error(503, "邮件发送失败，请稍后重试或联系管理员")
        return self.handler.send_json(200, {"ok": True, "message": "验证邮件已发送，请打开邮件中的链接完成绑定。"})

    def verify_email(self):
        token = str(self.app.read_json_body(self.handler).get("token") or "")
        with self.app.connect_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.valid_token(conn, token, "bind_email")
            if not row:
                return self.error(400, "验证链接无效或已过期，请登录后重新发送")
            if conn.execute("SELECT id FROM users WHERE lower(email) = ? AND id != ?", (row["email"], row["user_id"])).fetchone():
                return self.error(409, "该邮箱已绑定其他账号，请重新选择邮箱")
            conn.execute("UPDATE users SET email = ?, email_verified_at = ? WHERE id = ?",
                         (row["email"], self.app.utcnow(), row["user_id"]))
            conn.execute("DELETE FROM account_recovery_tokens WHERE user_id = ?", (row["user_id"],))
        self.app.clear_overview_memory_cache()
        return self.handler.send_json(200, {"ok": True, "message": "邮箱验证成功，现在可以通过此邮箱找回密码。"})

    def forgot_password(self):
        data = self.app.read_json_body(self.handler)
        username = self.app.normalize_username(str(data.get("username") or ""))
        email = normalize_email(data.get("email"))
        if not self.mail_ready():
            return
        # Use the actual socket peer; do not trust arbitrary X-Forwarded-For headers.
        if not consume_limit(self.app, "reset-ip:" + self.handler.client_address[0], 20, 3600):
            return self.error(429, "操作过于频繁，请稍后再试")
        if consume_limit(self.app, "reset-user:" + username, 1, 60):
            with self.app.connect_db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                user = conn.execute("""SELECT id, display_name, email FROM users
                    WHERE username = ? AND lower(email) = ? AND email_verified_at IS NOT NULL""",
                    (username, email)).fetchone()
                token = create_token(self.app, conn, user["id"], user["email"], "reset_password") if user else None
            if token and not send_token(self.app, token, user["email"], user["display_name"], "reset_password"):
                # Identical response for an existing account and an unknown one.
                print("[mail] 密码重置邮件未能送达", flush=True)
        return self.handler.send_json(200, {"ok": True, "message": RESET_MESSAGE})

    def valid_token(self, conn, token, purpose):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return None
        return conn.execute("""SELECT * FROM account_recovery_tokens
            WHERE token_hash = ? AND purpose = ? AND expires_at > ?""",
            (self.app.sha256_hex(token), purpose, self.app.utcnow())).fetchone()

    def reset_password(self):
        data = self.app.read_json_body(self.handler)
        token = str(data.get("token") or "")
        password = str(data.get("password") or "")
        if not 8 <= len(password) <= 1024:
            raise ValueError("密码长度须为 8–1024 位")
        # Check before the expensive password hash, then recheck under the write lock.
        with self.app.connect_db() as conn:
            if not self.valid_token(conn, token, "reset_password"):
                return self.error(400, "重置链接无效或已过期，请重新申请")
        encoded = self.app.password_hash(password)
        with self.app.connect_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.valid_token(conn, token, "reset_password")
            if not row:
                return self.error(400, "重置链接无效或已过期，请重新申请")
            cursor = conn.execute("""UPDATE users SET password_hash = ?
                WHERE id = ? AND email = ? AND email_verified_at IS NOT NULL""",
                (encoded, row["user_id"], row["email"]))
            if cursor.rowcount != 1:
                return self.error(400, "找回邮箱已变更，请重新申请重置链接")
            conn.execute("DELETE FROM account_recovery_tokens WHERE user_id = ?", (row["user_id"],))
            conn.execute("DELETE FROM sessions WHERE owner_type = 'user' AND owner_id = ?", (str(row["user_id"]),))
        self.app.clear_overview_memory_cache()
        return self.handler.send_json(200, {"ok": True, "message": "密码已重置，请使用新密码登录。"})


def handle(handler, app, path):
    method = {
        "/api/me/email": "email_status", "/api/auth/bind-email": "bind_email",
        "/api/auth/verify-email": "verify_email", "/api/auth/forgot-password": "forgot_password",
        "/api/auth/reset-password": "reset_password",
    }[path]
    return getattr(RecoveryHandler(handler, app), method)()
