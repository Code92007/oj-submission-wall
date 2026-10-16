"""Read-only AC history for CF Bot's knowledge wall (same owner-scoped token)."""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHANGHAI = timezone(timedelta(hours=8))


def luogu_metadata(app):
    """Read the same reviewed algorithm dictionary and public cache as OJ Wall."""
    if not hasattr(app, 'ROOT'):
        return {}, {}
    def read(path):
        try:
            return json.loads(Path(path).read_text())
        except (OSError, ValueError):
            return {}
    root = Path(app.ROOT)
    algorithms = read(root / 'catalog/luogu_algorithm_tags.json').get('tags', {})
    problems = read(root / 'catalog/luogu_problems.json').get('problems', {})
    if hasattr(app, 'CACHE_DIR'):
        problems.update(read(Path(app.CACHE_DIR) / 'luogu-analysis.json').get('problems', {}))
    return algorithms, problems


def knowledge_snapshot(service, owner):
    records = {}
    excluded = 0
    algorithms, luogu = luogu_metadata(service.app)
    def add_luogu_tags(record, values):
        for value in values if isinstance(values, list) else []:
            tag = algorithms.get(str(value)) if type(value) is int else None
            if tag:
                record['tags'].add(tag['label'])
                if not tag['key'].startswith('luogu:'):
                    record['tags'].add(tag['key'])
    with service.db() as db:
        accounts = {}
        handles = list(db.execute("select h.platform,h.handle,h.stats_json,k.kind from handles h left join cpc_handle_kinds k on k.handle_id=h.id where h.owner_type='user' and h.owner_id=? and h.active=1", (str(owner),)))
        for row in handles:
            accounts[row['platform'], row['handle']] = row['kind'] or ('team' if row['handle'].lower().startswith('ucup-team') else 'personal')
        for row in db.execute("select platform,handle,problem_id,problem_name,submitted_at,url,raw_json from submissions where owner_type='user' and owner_id=? and upper(verdict) in ('AC','OK','ACCEPTED')", (str(owner),)):
            kind = accounts.get((row['platform'], row['handle']))
            pid = str(row['problem_id'] or '')
            if not kind or not pid:
                continue
            raw = service.app.raw_json_dict(row)
            if service.app.is_activity_placeholder(row, raw):
                excluded += 1
                continue
            key = service.app.canonical_problem_key(row['platform'], pid, row['problem_name'] or '', raw=raw)
            record = records.setdefault((key, kind), {'key': key, 'kind': kind, 'title': row['problem_name'] or pid, 'tags': set(), 'firstAt': None, 'lastAt': None, 'days': set()})
            problem = raw.get('problem') if isinstance(raw.get('problem'), dict) else {}
            for tags in (raw.get('tags'), problem.get('tags')):
                if row['platform'] == 'luogu':
                    add_luogu_tags(record, tags)
                if isinstance(tags, list):
                    for tag in tags:
                        if isinstance(tag, dict):
                            tag = tag.get('name')
                        if isinstance(tag, str) and tag.strip() and not tag.isdigit():
                            record['tags'].add(tag.strip()[:100])
            stamp = row['submitted_at']
            # Profile-only solves have no original acceptance time; never use sync time.
            if isinstance(stamp, (int, float)) and 0 < stamp <= time.time() + 86400 and not raw.get('syntheticFromProfile') and raw.get('source') not in {'luogu-profile', 'luogu-third-party-fallback', 'solved-list'}:
                record['firstAt'] = min(record['firstAt'] or stamp, stamp)
                record['lastAt'] = max(record['lastAt'] or stamp, stamp)
                record['days'].add(datetime.fromtimestamp(stamp, SHANGHAI).date().isoformat())
        # Luogu's passed-problem list can complement incomplete record backfills.
        for handle in handles:
            try:
                stats = json.loads(handle['stats_json'] or '{}')
            except (TypeError, ValueError):
                continue
            kind = accounts[handle['platform'], handle['handle']]
            for solved in stats.get('solvedProblems', []):
                if not isinstance(solved, dict) or not solved.get('problemId'):
                    continue
                pid = str(solved['problemId'])
                key = service.app.canonical_problem_key(handle['platform'], pid, solved.get('name', ''), raw={'pid':pid, 'type':solved.get('source', '')})
                records.setdefault((key, kind), {'key': key, 'kind': kind, 'title': solved.get('name') or pid, 'tags': set(), 'firstAt': None, 'lastAt': None, 'days': set()})
    for record in records.values():
        if record['key'].startswith('luogu:'):
            add_luogu_tags(record, luogu.get(record['key'].split(':', 1)[1], {}).get('tags'))
        record['tags'] = sorted(record['tags'])
        record['days'] = sorted(record['days'])
    return {'version': 1, 'complete': True, 'records': sorted(records.values(), key=lambda r: (r['key'], r['kind'])), 'excludedActivity': excluded}
