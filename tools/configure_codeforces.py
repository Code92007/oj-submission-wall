#!/usr/bin/env python3
"""Configure one verified local user's own Codeforces API key without echoing secrets."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-id', required=True, help='OJ Wall 正式用户 ID')
    parser.add_argument('--handle', required=True, help='该用户已绑定的本人 CF handle')
    args = parser.parse_args()
    with app.connect_db() as db:
        found = db.execute("SELECT 1 FROM handles WHERE owner_type='user' AND owner_id=? AND platform='codeforces' AND lower(handle)=lower(?) AND active=1",
                           (args.owner_id, args.handle)).fetchone()
    if not found:
        parser.error('找不到该正式用户的有效 CF 绑定')
    key = getpass.getpass('Codeforces API Key（不回显）: ').strip()
    secret = getpass.getpass('Codeforces API secret（不回显）: ').strip()
    if not key or not secret:
        parser.error('Key 和 secret 均不能为空')
    path = app.CODEFORCES_AUTH_FILE
    data = json.loads(path.read_text()) if path.exists() else {'accounts': []}
    if not isinstance(data, dict) or not isinstance(data.get('accounts'), list):
        parser.error('已有授权文件格式错误，请先修复')
    accounts = data['accounts']
    if any(not isinstance(account, dict) for account in accounts):
        parser.error('已有授权文件格式错误，请先修复')
    data['accounts'] = [a for a in accounts if not (str(a.get('ownerId')) == args.owner_id and str(a.get('handle', '')).casefold() == args.handle.casefold())]
    data['accounts'].append({'ownerId': args.owner_id, 'handle': args.handle, 'key': key, 'secret': secret})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.cf-auth-', delete=False) as file:
            temporary = Path(file.name)
            os.fchmod(file.fileno(), 0o600)
            json.dump(data, file, indent=2)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    print('授权配置已保存。下次同步该账号时自动回补历史；也可在训练墙立即刷新。')


if __name__ == '__main__':
    main()
