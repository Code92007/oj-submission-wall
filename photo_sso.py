"""Narrow authorization-code bridge to the configured DLUT photo gallery."""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import os
import re
import secrets
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlencode, urlsplit


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')


def db_for(service):
    db = service.db()
    db.execute('''create table if not exists cpc_photo_codes(
        hash text primary key, owner text not null, session_hash text not null,
        challenge text not null, expires integer not null)''')
    return db


def handle(handler, service, post=False):
    parsed = urlsplit(handler.path)
    if parsed.path not in {'/api/cpc/photos/authorize', '/api/integration/v1/photos/exchange'}:
        return False
    query = parse_qs(parsed.query)
    # Authorization material must not reach the HTTP access log.
    handler.requestline = f'{handler.command} {parsed.path} {handler.request_version}'
    try:
        base = os.environ.get('CPC_PHOTO_PUBLIC_URL', '').rstrip('/')
        if not service.configured or urlsplit(base).scheme != 'https' or urlsplit(base).path not in {'', '/'}:
            handler.send_error_json(503, '比赛照片登录暂未配置')
            return True
        if not post and parsed.path == '/api/cpc/photos/authorize':
            state = query.get('state', [''])[0]
            proof = query.get('code_challenge', [''])[0]
            if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', state) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', proof):
                raise ValueError('登录参数无效，请从比赛照片页重新进入')
            principal = service.app.get_current_principal(handler)
            if not principal or principal['type'] != 'user':
                retry = html.escape(handler.path, quote=True)
                handler.send_html(200, f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
                  <meta name="viewport" content="width=device-width,initial-scale=1"><title>登录 OJ Wall</title>
                  <link rel="stylesheet" href="/styles.css"><main style="max-width:640px;margin:12vh auto;padding:28px">
                  <h1>登录后查看比赛照片</h1><p>请使用完成成员认证的 OJ Wall 正式账号登录。</p>
                  <p><a href="/#login" target="_blank" rel="noopener noreferrer">打开 OJ Wall 登录</a></p>
                  <p>登录完成后回到本页继续。</p><p><a href="{retry}">已登录，继续查看照片 →</a></p>
                  <p><a href="{html.escape(base)}/photos">返回比赛照片</a></p></main></html>''',
                  [('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer')])
                return True
            jar = SimpleCookie()
            jar.load(handler.headers.get('Cookie', ''))
            session = jar.get(service.app.SESSION_COOKIE)
            if not session:
                raise ValueError('登录已失效')
            code = secrets.token_urlsafe(32)
            with db_for(service) as db:
                db.execute('delete from cpc_photo_codes where expires<=?', (int(time.time()),))
                db.execute('insert into cpc_photo_codes values (?,?,?,?,?)',
                           (service.app.sha256_hex(code), str(principal['id']),
                            service.app.sha256_hex(session.value), proof, int(time.time()) + 60))
            handler.send_response(302)
            handler.send_header('Location', base + '/api/photos/callback?' + urlencode({'code': code, 'state': state}))
            for name, value in [('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer'), ('Content-Length', '0')]:
                handler.send_header(name, value)
            handler.end_headers()
        elif post and parsed.path == '/api/integration/v1/photos/exchange':
            token = os.environ.get('CPC_SYNC_TOKEN', '')
            if not token or not hmac.compare_digest(handler.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode()):
                handler.send_error_json(403, '凭据无效')
                return True
            body = service.app.read_json_body(handler)
            code, verifier = body.get('code', ''), body.get('verifier', '')
            if not isinstance(code, str) or not isinstance(verifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', verifier):
                raise ValueError('授权码无效')
            with db_for(service) as db:
                db.execute('begin immediate')
                row = db.execute('select * from cpc_photo_codes where hash=? and expires>?',
                                 (service.app.sha256_hex(code), int(time.time()))).fetchone()
                if not row or not hmac.compare_digest(row['challenge'], challenge(verifier)):
                    raise ValueError('授权码已失效，请重新登录')
                active = db.execute("select 1 from sessions s join users u on cast(u.id as text)=s.owner_id where s.token_hash=? and s.owner_type='user' and s.owner_id=? and s.expires_at>?",
                                    (row['session_hash'], row['owner'], service.app.utcnow())).fetchone()
                if not active:
                    raise ValueError('OJ Wall 登录已失效')
                db.execute('delete from cpc_photo_codes where hash=?', (row['hash'],))
                subject = service.subject(db, row['owner'])
            handler.send_json(200, {'authority_id': service.authority, 'subject': subject})
        else:
            handler.send_error_json(405, '请求方法无效')
    except (ValueError, TypeError, KeyError):
        handler.send_error_json(400, '照片授权已失效，请回到比赛照片页重新登录')
    return True
