"""Optional account-scoped authentication for Codeforces private submissions."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlencode


@dataclass(frozen=True)
class CodeforcesAuth:
    owner_id: str
    handle: str
    key: str = field(repr=False)
    secret: str = field(repr=False)

    @property
    def history_token(self) -> str:
        value = '\0'.join((self.owner_id, self.handle.casefold(), self.key))
        return hashlib.sha256(value.encode()).hexdigest()


def load_auth(path: Path, owner_type: str, owner_id: str, handle: str) -> CodeforcesAuth | None:
    if owner_type != 'user' or not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        accounts = data['accounts']
        if not isinstance(accounts, list):
            raise ValueError()
        matches = []
        for account in accounts:
            if not isinstance(account, dict):
                raise ValueError()
            if str(account.get('ownerId')) == owner_id and str(account.get('handle', '')).casefold() == handle.casefold():
                if not all(isinstance(account.get(k), str) and account[k].strip() for k in ('key', 'secret')):
                    raise ValueError()
                matches.append(CodeforcesAuth(owner_id, handle, account['key'].strip(), account['secret'].strip()))
        if len(matches) > 1:
            raise ValueError()
        return matches[0] if matches else None
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError('Codeforces 授权文件无效，请管理员检查 accounts、ownerId、handle、key、secret') from None


def signed_url(method: str, params: dict, auth: CodeforcesAuth, *, timestamp: int, nonce: str) -> str:
    # Keep the signing primitive limited to this integration's own submissions.
    if method != 'user.status' or str(params.get('handle', '')).casefold() != auth.handle.casefold():
        raise ValueError('Codeforces 授权只能读取配置账号的提交')
    if not re.fullmatch(r'[a-zA-Z0-9]{6}', nonce):
        raise ValueError('Codeforces 签名随机前缀应为六位')
    query = {str(k): str(v) for k, v in params.items()}
    if {'apiKey', 'apiSig', 'time', 'includeSources'} & query.keys():
        raise ValueError('Codeforces 授权请求包含不允许的参数')
    query.update(apiKey=auth.key, time=str(timestamp))
    ordered = sorted(query.items())
    canonical = '&'.join(f'{key}={value}' for key, value in ordered)
    digest = hashlib.sha512(f'{nonce}/{method}?{canonical}#{auth.secret}'.encode()).hexdigest()
    return f'https://codeforces.com/api/{method}?{urlencode(ordered)}&apiSig={nonce}{digest}'


_request_lock = threading.Lock()
_last_request_at = 0.0


def signed_api_get(method: str, params: dict, auth: CodeforcesAuth, http_get) -> dict:
    global _last_request_at
    with _request_lock:
        delay = 2.1 - (time.monotonic() - _last_request_at)
        if delay > 0:
            time.sleep(delay)
        try:
            url = signed_url(method, params, auth, timestamp=int(time.time()), nonce=secrets.token_hex(3))
            # Signed URLs contain apiKey. Never persist them or reuse stale private data.
            body, _ = http_get(url, allow_stale_cache=False, cache_write=False)
            data = json.loads(body.decode('utf-8'))
            if not isinstance(data, dict) or data.get('status') != 'OK' or not isinstance(data.get('result'), list):
                raise ValueError()
            return data
        except Exception:
            # HTTP/API exceptions may contain the signed URL; keep credentials out of logs/UI.
            raise RuntimeError('Codeforces 授权读取失败，请检查 API Key、secret、账号归属和服务器时间后重试') from None
        finally:
            _last_request_at = time.monotonic()
