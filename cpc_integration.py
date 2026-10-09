"""Internal regional progress. Existing submissions remain untouched."""
from __future__ import annotations
import json
import os
import secrets
import threading
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from cpc_common import connect, uid, digest, fetch, validate_snapshot, catalog
from cpc_sources import Scoreboards, profile_awards


def problem_key(platform, value):
    value = str(value or '').strip()
    if platform == 'vjudge' and '-' in value:
        oj, value = value.split('-', 1)
        platform = {'codeforces':'codeforces', 'gym':'codeforces', 'luogu':'luogu', 'qoj':'qoj', 'nowcoder':'nowcoder'}.get(oj.lower(), oj.lower())
    if platform == 'luogu' and value.upper().startswith('CF'):
        platform, value = 'codeforces', value[2:]
    return platform.lower() + ':' + value.upper()


class Integration:
    def __init__(self, app):
        self.app = app
        self.path = app.DB_PATH
        self.catalog, self.aliases = catalog(os.environ.get('CPC_CATALOG_PATH', app.ROOT / 'catalog/regionals.json'))
        self.contests = {c['id']: c for c in self.catalog['contests']}
        self.problem_ids = {p['id'] for c in self.contests.values() for p in c['problems']}
        with self.db() as db:
            self.authority = uid(db, 'authority', 'self')
        self.wake = threading.Event()
        self.sync_lock = threading.Lock()
        self.onsite_lock = threading.Lock()
        self.force_onsite = threading.Event()

    @property
    def configured(self):
        return all(os.environ.get(k) for k in ('CPC_DLUT_URL', 'CPC_SYNC_TOKEN', 'CPC_DLUT_AUTHORITY_ID'))

    def db(self):
        db = connect(self.path)
        db.executescript('''
          create table if not exists cpc_remote(id integer primary key check(id=1),body text,checked integer);
          create table if not exists cpc_read_tokens(owner text primary key,hash text unique,expires integer);
          create table if not exists cpc_handle_kinds(handle_id integer primary key,kind text);
          create table if not exists cpc_onsite(id text primary key,participation text,contest text,body text,active integer);
          create table if not exists cpc_onsite_history(id integer primary key,evidence_id text,body text,created integer);
          create table if not exists cpc_onsite_sync(person text primary key,body text,checked integer);
        ''')
        return db

    def sync(self):
        with self.sync_lock:
            return self._sync()

    def _sync(self):
        base = os.environ.get('CPC_DLUT_URL', '')
        token = os.environ.get('CPC_SYNC_TOKEN', '')
        authority = os.environ.get('CPC_DLUT_AUTHORITY_ID', '')
        if not base or not token or not authority:
            raise ValueError('请先配置 DLUT 地址、信源 ID 和同步凭据')
        roster = validate_snapshot(fetch(base, '/api/integration/v1/roster/snapshot', token), authority)
        claims = validate_snapshot(fetch(base, '/api/integration/v1/claims/snapshot?client=' + self.authority, token), authority)
        if not isinstance(roster.get('members'), list) or not isinstance(roster.get('participations'), list) or not isinstance(roster.get('redirects'), dict) or not isinstance(claims.get('claims'), list):
            raise ValueError('名单快照不完整')
        if (roster.get('record_count') != len(roster['members']) + len(roster['participations']) + len(roster['redirects'])
                or claims.get('record_count') != len(claims['claims']) or claims.get('client_id') != self.authority):
            raise ValueError('名单快照数量或客户端不匹配')
        # Validate before replacing either snapshot; a partial pair never clears data.
        for row in roster['members']:
            uuid.UUID(row['id'])
            if not isinstance(row['name'], str) or not isinstance(row['school'], str):
                raise ValueError('成员格式错误')
        for row in roster['participations']:
            uuid.UUID(row['id'])
            if not isinstance(row['members'], list) or not isinstance(row['team'], str):
                raise ValueError('名单格式错误')
            for member in row['members']:
                uuid.UUID(member)
        for old, current in roster['redirects'].items():
            uuid.UUID(old); uuid.UUID(current)
        for row in claims['claims']:
            if row['status'] not in {'pending','approved','rejected','revoked','superseded'}:
                raise ValueError('认领状态错误')
            uuid.UUID(row['id']); uuid.UUID(row['subject']); uuid.UUID(row['person'])
            if type(row['updated']) is not int:
                raise ValueError('认领时间格式错误')
        with self.db() as db:
            db.execute('insert or replace into cpc_remote values (1,?,?)',
                       (json.dumps({'roster': roster, 'claims': claims['claims']}), int(time.time())))

    def start(self):
        if not self.configured:
            return
        def worker():
            while True:
                try:
                    self.sync()
                    force = self.force_onsite.is_set()
                    self.force_onsite.clear()
                    self.sync_onsite(force=force)
                except Exception:
                    # Do not log request bodies, credentials or verification notes.
                    print('CPC sync failed; previous snapshot retained', flush=True)
                self.wake.wait(300)
                self.wake.clear()
        threading.Thread(target=worker, daemon=True, name='cpc-roster').start()

    def sync_onsite(self, force=False):
        """Detection of an approved claim triggers profile-scoped scoreboard import."""
        with self.onsite_lock:
            with self.db() as db:
                remote, checked = self.remote(db)
            if checked + 86400 < time.time():
                return
            people = {m['id']: m for m in remote['roster']['members']}
            redirects = remote['roster']['redirects']
            boards = Scoreboards(self.app.DATA_DIR / 'cpc_sources')
            for claim in remote['claims']:
                if claim['status'] != 'approved': continue
                person = claim['person']; visited = set()
                while person in redirects and person not in visited:
                    visited.add(person); person = redirects[person]
                member = people.get(person)
                if not member: continue
                with self.db() as db:
                    old = db.execute('select body,checked from cpc_onsite_sync where person=?',(person,)).fetchone()
                if old and not force:
                    previous = json.loads(old['body'])
                    interval = 86400 if previous['status'] == 'complete' else 300
                    if old['checked'] + interval > time.time() and old['checked'] >= claim['updated']: continue
                report = {'status':'running','imported':0,'listed':0,'issues':[]}
                def save_report():
                    with self.db() as db:
                        db.execute('insert or replace into cpc_onsite_sync values (?,?,?)',
                                   (person,json.dumps(report,ensure_ascii=False),int(time.time())))
                save_report()
                try:
                    participations = [p for p in remote['roster']['participations'] if person in p['members']]
                    awards = []
                    if member.get('cpcfinder_id'):
                        try:
                            awards = profile_awards(member)
                        except (OSError,ValueError,KeyError,TypeError):
                            report['issues'].append({'contest':'CPC Finder','reason':'选手比赛列表暂不可用，继续使用 DLUT 原榜单链接'})
                    report['listed'] = len(participations)
                    for participation in participations:
                        matches = [a for a in awards if a.get('date','')[:10] == participation['date']
                                   and a.get('teamName') == participation['team']]
                        award = matches[0] if len(matches) == 1 else None
                        try:
                            body = boards.prepare(award,participation,[people[m]['name'] for m in participation['members']],self.contests)
                            self.import_auto_onsite(body)
                            report['imported'] += 1
                        except (OSError,ValueError,KeyError,TypeError) as exc:
                            reason = str(exc) if isinstance(exc,ValueError) else '原榜单暂时无法读取，稍后重试'
                            report['issues'].append({'contest':participation['event'],'reason':reason[:200]})
                    report['status'] = 'partial' if report['issues'] else 'complete'
                except (OSError,ValueError,KeyError,TypeError) as exc:
                    report['status'] = 'error'
                    report['issues'].append({'contest':'选手比赛列表','reason':str(exc)[:200] if isinstance(exc,ValueError) else 'CPC Finder 暂时无法读取，稍后重试'})
                save_report()

    def remote(self, db):
        row = db.execute('select * from cpc_remote where id=1').fetchone()
        return (json.loads(row['body']), row['checked']) if row else ({'roster': {'members': [], 'participations': [], 'redirects': {}}, 'claims': []}, 0)

    def subject(self, db, owner):
        return uid(db, 'subject', owner)

    def request_claim(self, owner, name, body):
        with self.db() as db:
            remote, checked = self.remote(db)
            subject = self.subject(db, owner)
        if checked < time.time() - 86400 or body.get('person') not in {m['id'] for m in remote['roster']['members']}:
            raise ValueError('成员列表未就绪，请稍后刷新')
        payload = {'id': str(uuid.uuid4()), 'client': self.authority, 'subject': subject,
                   'person': body['person'], 'account_name': name, 'note': body.get('note', '')}
        try:
            result = fetch(os.environ['CPC_DLUT_URL'], '/api/integration/v1/claims', os.environ['CPC_SYNC_TOKEN'], payload)
        except HTTPError:
            raise ValueError('申请未被接受，可能已有待审核或已认证申请，请联系管理员') from None
        self.wake.set()
        return result

    def issue_token(self, owner):
        token = self.authority + '.' + secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('insert or replace into cpc_read_tokens values (?,?,?)', (str(owner), digest(token), int(time.time()) + 180*86400))
        return {'ok': True, 'token': token}

    def token_owner(self, token):
        with self.db() as db:
            row = db.execute('select owner from cpc_read_tokens where hash=? and expires>?', (digest(token), int(time.time()))).fetchone()
        return row['owner'] if row else None

    def progress(self, owner):
        with self.db() as db:
            remote, checked = self.remote(db)
            subject = self.subject(db, owner)
            claims = [c for c in remote['claims'] if c['subject'] == subject]
            claim = max(claims, key=lambda c: (c['status']=='approved', c['status']=='pending', c['updated'], c['id']), default=None)
            identity = dict(claim or {'status': 'unverified'})
            identity['authority_id'] = remote['roster'].get('authority_id')
            identity['verified_until'] = checked + 86400
            person = claim['person'] if claim and claim['status'] == 'approved' and checked + 86400 > time.time() else None
            redirects = remote['roster']['redirects']
            visited = set()
            while person in redirects and person not in visited:
                visited.add(person)
                person = redirects[person]
            identity['person'] = person
            result = {}
            unmatched = set()
            participations = {p['id']: p for p in remote['roster']['participations'] if person and person in p['members']}
            onsite_rows = [(row, json.loads(row['body'])) for row in db.execute('select * from cpc_onsite where active=1')
                           if row['participation'] in participations]
            aliases = dict(self.aliases)
            extra_aliases = {}
            for _, evidence in onsite_rows:
                for pid, alias in evidence.get('problem_aliases', {}).items():
                    extra_aliases.setdefault(alias, set()).add(self.aliases.get(alias, pid))
            for alias, targets in extra_aliases.items():
                if len(targets) == 1:
                    aliases.setdefault(alias, next(iter(targets)))
            handles = [dict(r) for r in db.execute('select h.id,h.platform,h.handle,k.kind from handles h left join cpc_handle_kinds k on k.handle_id=h.id where h.owner_type=? and h.owner_id=? and h.active=1', ('user',str(owner)))]
            by_account = {}
            for h in handles:
                # Explicit selection handles non-obvious team accounts; QOJ team names are recognizable.
                h['kind'] = h['kind'] or ('team' if h['handle'].lower().startswith('ucup-team') else 'personal')
                by_account[h['platform'], h['handle']] = h['kind']
            rows = db.execute("select platform,handle,problem_id,verdict from submissions where owner_type='user' and owner_id=?", (str(owner),))
            for r in rows:
                kind = by_account.get((r['platform'],r['handle']))
                if not kind:
                    continue
                key = problem_key(r['platform'], r['problem_id'])
                pid = aliases.get(key)
                if not pid:
                    if r['verdict'] in {'AC','OK','Accepted'}:
                        unmatched.add(key)
                    continue
                if pid not in self.problem_ids and str(r['verdict']).upper() in {'AC','OK','ACCEPTED'}:
                    unmatched.add(pid)
                p = result.setdefault(pid, {'personal': False, 'team': False, 'onsite': False, 'attempted': False, 'evidence': []})
                p['attempted'] = True
                if str(r['verdict']).upper() in {'AC','OK','ACCEPTED'}:
                    p[kind] = True
            onsite_contests = []
            for row, evidence in onsite_rows:
                participation = participations[row['participation']]
                onsite_contests.append({'name':evidence.get('contest_name',row['contest']),
                    'date':participation['date'],'team':participation['team'],'official':participation.get('official'),
                    'accepted':evidence.get('accepted_labels',[p.rsplit(':',1)[-1] for p in evidence['accepted']]),
                    'source_url':evidence['source_url'],'mapped':row['contest'] in self.contests})
                for pid in evidence['accepted']:
                    alias = evidence.get('problem_aliases',{}).get(pid)
                    pid = self.aliases.get(alias,pid) if alias else pid
                    if pid not in self.problem_ids:
                        unmatched.add(pid)
                    p = result.setdefault(pid, {'personal': False, 'team': False, 'onsite': False, 'attempted': False, 'evidence': []})
                    p['onsite'] = True
                    p['evidence'].append({'id': row['id'], 'source': evidence['source_url'], 'team': participation['team']})
            job = db.execute('select body,checked from cpc_onsite_sync where person=?',(person,)).fetchone() if person else None
            onsite_sync = {**json.loads(job['body']),'checked':job['checked']} if job else {'status':'waiting' if person else 'unverified','issues':[]}
            if person and not job: self.wake.set()
            return {'schema_version': 1, 'authority_id': self.authority, 'subject_id': subject,
                    'snapshot_complete': True, 'identity': identity, 'problems': result,
                    'record_count': len(result), 'unmapped_count': len(unmatched),
                    'coverage': 'partial', 'handles': handles, 'roster_checked': checked,
                    'onsite_contests':sorted(onsite_contests,key=lambda c:c['date'],reverse=True),'onsite_sync':onsite_sync}

    def import_auto_onsite(self, body):
        """Provider adapters validated the row; retain unmapped contests for later catalogs."""
        contest = self.contests.get(body['contest_id'])
        labels = body['problem_labels']
        if len(labels) != len(set(labels)) or any(p not in labels for p in body['accepted']):
            raise ValueError('原榜单题序无效')
        if contest and set(labels) != {p['index'] for p in contest['problems']}:
            raise ValueError('原榜单题序与区域赛目录不一致')
        indices = {p['index']:p['id'] for p in contest['problems']} if contest else {p:body['contest_id']+':'+p for p in labels}
        gyms = set()
        for url in body.get('reference_urls',[]):
            parsed = urlsplit(url)
            if parsed.hostname in {'codeforces.com','www.codeforces.com'} and parsed.path.startswith('/gym/'):
                identifier = parsed.path.split('/')[2]
                if identifier.isdigit(): gyms.add(identifier)
        aliases = {indices[p]:'codeforces:'+next(iter(gyms))+p for p in labels} if len(gyms) == 1 else {}
        stored = {**body,'accepted_labels':sorted(set(body['accepted'])),
                  'accepted':sorted({indices[p] for p in body['accepted']}),'problem_aliases':aliases}
        raw = json.dumps(stored,ensure_ascii=False)
        key = digest('auto|'+body['participation_id'])
        with self.db() as db:
            remote,_ = self.remote(db)
            participation = next((p for p in remote['roster']['participations'] if p['id'] == body['participation_id']),None)
            if not participation or participation['team'] != body['team'] or participation['date'] != body['contest_date']:
                raise ValueError('参赛记录已改变，请重新同步')
            old = db.execute('select body,active from cpc_onsite where id=?',(key,)).fetchone()
            if old and old['body'] == raw and old['active']:return key
            db.execute('insert into cpc_onsite_history(evidence_id,body,created) values (?,?,?)',(key,raw,int(time.time())))
            db.execute('insert or replace into cpc_onsite values (?,?,?,?,1)',(key,body['participation_id'],body['contest_id'],raw))
        return key

    def import_onsite(self, body):
        contest = self.contests.get(body.get('contest_id'))
        if not contest or not isinstance(body.get('accepted'), list) or body.get('confirmed') is not True:
            raise ValueError('需提供已确认比赛和通过题列表')
        if urlsplit(str(body.get('source_url', ''))).scheme not in {'http','https'} or not body.get('source_row'):
            raise ValueError('需保留榜单来源链接和行标识')
        indices = {p['index']: p['id'] for p in contest['problems']}
        if any(p not in indices for p in body['accepted']):
            raise ValueError('榜单题号未映射到目录；不会部分导入')
        with self.db() as db:
            remote, _ = self.remote(db)
            participation = next((p for p in remote['roster']['participations'] if p['id'] == body.get('participation_id')), None)
            if not participation or body.get('team') != participation['team']:
                raise ValueError('参赛记录或队名不匹配')
            key = digest(body['participation_id'] + '|' + body['source_url'] + '|' + str(body['source_row']))
            stored = {**body, 'accepted': sorted({indices[p] for p in body['accepted']})}
            raw = json.dumps(stored, ensure_ascii=False)
            db.execute('insert into cpc_onsite_history(evidence_id,body,created) values (?,?,?)', (key,raw,int(time.time())))
            db.execute('insert or replace into cpc_onsite values (?,?,?,?,1)', (key, body['participation_id'], contest['id'],raw))
        return key

    def revoke_onsite(self, key):
        with self.db() as db:
            if not db.execute('select 1 from cpc_onsite where id=?', (key,)).fetchone():
                raise ValueError('证据不存在')
            db.execute('update cpc_onsite set active=0 where id=?', (key,))
            db.execute('insert into cpc_onsite_history(evidence_id,body,created) values (?,?,?)', (key,'{"revoked":true}',int(time.time())))


def handle(handler, service, post=False):
    path = urlsplit(handler.path).path
    if path not in {'/api/cpc/me','/api/cpc/claim','/api/cpc/token','/api/cpc/token/revoke','/api/cpc/refresh','/api/cpc/handle-kind','/api/integration/v1/me/progress/snapshot'}:
        return False
    try:
        if path == '/api/integration/v1/me/progress/snapshot' and not post:
            authorization = handler.headers.get('Authorization', '')
            owner = service.token_owner(authorization.removeprefix('Bearer ')) if authorization.startswith('Bearer ') else None
            if not owner:
                handler.send_error_json(401, '连接码无效、已撤销或已到期')
                return True
            handler.send_json(200, service.progress(owner))
            return True
        principal = service.app.get_current_principal(handler)
        if not principal or principal['type'] != 'user':
            handler.send_error_json(401, '请先登录正式账号')
            return True
        owner = str(principal['id'])
        if not post and path == '/api/cpc/me':
            result = service.progress(owner)
            with service.db() as db:
                remote, _ = service.remote(db)
            result.update({'members': remote['roster']['members'], 'contests': service.catalog['contests']})
        elif post:
            origin = handler.headers.get('Origin', '')
            expected = service.app.PUBLIC_BASE_URL.rstrip('/') or 'http://' + handler.headers.get('Host', '')
            if origin != expected:
                handler.send_error_json(403, '请求来源无效')
                return True
            body = service.app.read_json_body(handler)
            if path == '/api/cpc/claim':
                result = service.request_claim(owner, principal['username'], body)
            elif path == '/api/cpc/token':
                result = service.issue_token(owner)
            elif path == '/api/cpc/token/revoke':
                with service.db() as db:
                    db.execute('delete from cpc_read_tokens where owner=?', (owner,))
                result = {'ok': True}
            elif path == '/api/cpc/refresh':
                service.force_onsite.set()
                service.wake.set()
                result = {'ok': True}
            elif path == '/api/cpc/handle-kind':
                if body.get('kind') not in {'personal','team'}:
                    raise ValueError('账号类型无效')
                with service.db() as db:
                    row = db.execute("select id from handles where id=? and owner_type='user' and owner_id=?", (body.get('id'),owner)).fetchone()
                    if not row:
                        raise ValueError('账号不属于当前用户')
                    db.execute('insert or replace into cpc_handle_kinds values (?,?)', (row['id'],body['kind']))
                result = {'ok': True}
            else:
                handler.send_error_json(404, 'not found')
                return True
        else:
            handler.send_error_json(404, 'not found')
            return True
        handler.send_json(200, result)
    except (ValueError, KeyError, TypeError) as exc:
        handler.send_error_json(400, str(exc))
    return True
