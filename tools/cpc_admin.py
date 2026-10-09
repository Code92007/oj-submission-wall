#!/usr/bin/env python3
"""Import administrator-verified scoreboard rows without modifying submissions."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from cpc_integration import Integration

parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest='command', required=True)
for name in ('meta', 'sync', 'rosters'):
    sub.add_parser(name)
imp = sub.add_parser('import')
imp.add_argument('file', type=Path)
imp.add_argument('--confirm', action='store_true', help='已核验来源、队伍行和题序')
rev = sub.add_parser('revoke')
rev.add_argument('id')
args = parser.parse_args()
if not app.DB_PATH.is_file():
    parser.error('运行数据库不存在，不会初始化新的用户库')
service = Integration(app)
if args.command == 'meta':
    print(service.authority)
elif args.command == 'sync':
    service.sync()
    service.sync_onsite(force=True)
    print('已同步名单、认证及现场成绩；各账号页面显示逐场同步状态')
elif args.command == 'rosters':
    with service.db() as db:
        remote, checked = service.remote(db)
    print(json.dumps({'checked': checked, 'participations': remote['roster']['participations']}, ensure_ascii=False, indent=2))
elif args.command == 'import':
    body = json.loads(args.file.read_text())
    if not args.confirm:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        print('仅预览；核验后加 --confirm 导入')
    else:
        body['confirmed'] = True
        print(service.import_onsite(body))
else:
    service.revoke_onsite(args.id)
    print('已撤销榜单证据')
