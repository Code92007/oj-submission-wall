"""Public scoreboard adapters using DLUT curated contest links and confirmed rosters."""
from __future__ import annotations
import ast
import datetime as dt
import hashlib
import json
import math
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, build_opener
from cpc_common import NoRedirect
from cpc_scoreboard import prepare_xcpc

SITES = dict(zip(
    ['哈尔滨','济南','郑州','重庆','上海','南京','成都','武汉','沈阳','西安','香港','桂林','深圳','秦皇岛','合肥','杭州','澳门','昆明','长春','绵阳','威海'],
    ['harbin','jinan','zhengzhou','chongqing','shanghai','nanjing','chengdu','wuhan','shenyang','xian','hongkong','guilin','shenzhen','qinhuangdao','hefei','hangzhou','macau','kunming','changchun','mianyang','weihai']))


def public_bytes(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in {'cpcfinder.com','rl.algoux.cn','raw.githubusercontent.com','api.github.com'}
            or parsed.username or parsed.password or parsed.port not in {None,443}):
        raise ValueError('榜单来源地址不受支持')
    with build_opener(NoRedirect()).open(Request(url, headers={'User-Agent':'OJ-Wall-onsite/1.0'}), timeout=20) as response:
        raw = response.read(15_000_001)
    if len(raw) > 15_000_000:
        raise ValueError('榜单响应过大')
    return raw


def public_json(url):
    return json.loads(public_bytes(url))


def profile_awards(member):
    identifier = str(member.get('cpcfinder_id') or '')
    uuid.UUID(identifier)
    rows = public_json('https://cpcfinder.com/api/student/'+identifier+'/awards').get('data')
    if not isinstance(rows, list):
        raise ValueError('CPC Finder 选手比赛列表无效')
    return rows


def edition_path(award):
    title = award['contestName']
    series = 'ccpc' if 'CCPC' in title else 'icpc' if 'ICPC' in title else None
    match = re.search(r'第\s*(\d+)\s*届', title)
    site = SITES.get(award.get('place'))
    if not series or not match or not site:
        raise ValueError('比赛暂未建立原榜单映射')
    edition = int(match[1])
    season = edition + (2014 if series == 'ccpc' else 1975)
    return series, season, f'{series}/{season if season <= 2022 else str(edition)+"th"}/{site}'


def localized(value):
    if isinstance(value, str): return value
    if isinstance(value, dict):
        texts = value.get('texts', value)
        return texts.get('zh-CN') or texts.get('fallback') or texts.get('en') or ''
    return ''


def check_members(source, names):
    if source:
        actual = {localized(m.get('name')) if isinstance(m, dict) else str(m) for m in source
                  if not isinstance(m, dict) or m.get('role','contestant') not in {'coach','reserve'}}
        if actual != set(names): raise ValueError('原榜单队员与 DLUT 确认名单不一致')


def school_matches(value, participation):
    return localized(value) in participation.get('school_names', [participation['school']])


def seconds(value):
    number, unit = value
    scale = {'ms': .001, 's': 1, 'min': 60, 'h': 3600}.get(unit)
    if scale is None or not isinstance(number, (int, float)) or not math.isfinite(number):
        raise ValueError('RankLand 时间格式无效')
    return number * scale


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False); self.active=False; self.parts=[]; self.scripts=[]
    def handle_starttag(self, tag, attrs):
        if tag=='script': self.active=True; self.parts=[]
    def handle_data(self, data):
        if self.active:self.parts.append(data)
    def handle_endtag(self, tag):
        if tag=='script' and self.active:self.scripts.append(''.join(self.parts));self.active=False


def rankland_body(raw, award, participation, names, url):
    parser=Scripts();parser.feed(raw.decode())
    for script in parser.scripts:
        match=re.fullmatch(r'\s*window\.__INITIAL_STATE__\s*=\s*(.*?)\s*;?\s*',script,re.S)
        if match:
            state=json.loads(ast.literal_eval(match[1]));break
    else:raise ValueError('RankLand 缺少结构化榜单')
    srk=state['ranklistData']['srk']
    if srk.get('type') not in {'general','static'}:raise ValueError('RankLand 榜单格式暂不支持')
    date=dt.datetime.fromisoformat(srk['contest']['startAt'].replace('Z','+00:00')).astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    if date!=participation['date']:raise ValueError('原榜单与参赛日期不一致')
    rows=[r for r in srk['rows'] if localized(r['user'].get('name'))==participation['team']
          and school_matches(r['user'].get('organization'),participation)]
    if len(rows)!=1:raise ValueError('RankLand 队伍行不存在或有歧义')
    row=rows[0];check_members(row['user'].get('teamMembers'),names)
    source_key = state['ranklistData'].get('info', {}).get('uniqueKey')
    if (participation.get('source_provider') == 'rankland' and participation.get('source_contest_id') == source_key
            and participation.get('source_team_id') and str(row['user']['id']) != str(participation['source_team_id'])):
        raise ValueError('原榜单行 ID 与 DLUT 归档记录不一致')
    labels=[p['alias'] for p in srk['problems']]
    if len(set(labels))!=len(labels) or len(row['statuses'])!=len(labels):raise ValueError('RankLand 逐题列不完整')
    accepted=[]
    duration = seconds(srk['contest']['duration'])
    if not 0 < duration <= 86400:raise ValueError('RankLand 比赛时长无效')
    for label,status in zip(labels,row['statuses']):
        result=status.get('result')
        if result in {'PD','PENDING','FZ','?'}:raise ValueError('榜单仍有未决或封榜提交')
        if result not in {None,'AC','FB','RJ'}:raise ValueError('RankLand 逐题结果无效')
        if result in {'AC','FB'}:
            if not 0 <= seconds(status['time']) <= duration:raise ValueError('榜单 AC 时间不在比赛内')
            accepted.append(label)
    return {'accepted':accepted,'source_url':url,'source_row':str(row['user']['id']),
            'source_team':row['user'],'source_statuses':row['statuses'],'source_contest':srk['contest'],
            'source_sha256':{'rankland':hashlib.sha256(raw).hexdigest()},
            'source_type':'rankland','problem_labels':labels,
            'reference_urls':[r['link'] for r in srk['contest'].get('refLinks',[]) if 'link' in r]}


class Scoreboards:
    def __init__(self, root):
        self.root = Path(root)
        self.revision = None

    def save_raw(self, target, raw):
        temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_bytes(raw)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def rankland(self, url, award, participation, names):
        parsed = urlsplit(url)
        key = (parsed.path.removeprefix('/ranklist/') if parsed.path.startswith('/ranklist/')
               else parse_qs(parsed.query).get('rankId', [''])[0])
        if not re.fullmatch('[a-zA-Z0-9_-]+', key):
            raise ValueError('RankLand 比赛标识无效')
        url = 'https://rl.algoux.cn/ranklist/' + key
        raw = public_bytes(url)
        directory = self.root / 'rankland'
        directory.mkdir(parents=True, exist_ok=True)
        self.save_raw(directory / (hashlib.sha256(raw).hexdigest() + '.html'), raw)
        return rankland_body(raw, award, participation, names, url), 'rankland-' + key

    def prepare(self, award, participation, names, contests):
        award = award or {}
        selected = participation.get('ranklist_url', '')
        links = ([selected] if selected else []) + [s.get('url', '') for s in participation.get('sources', [])]
        cid = award.get('contestId') or participation.get('cpcfinder_contest_id')
        if not cid:
            cid = next((urlsplit(u).path.split('/')[2] for u in links
                        if urlsplit(u).hostname == 'cpcfinder.com' and re.fullmatch(r'/contest/\d+/?', urlsplit(u).path)), None)
        xcpc = next((u for u in links if urlsplit(u).hostname in {'xcpcio.com', 'board.xcpcio.com'}), None)
        rankland = next((u for u in links if urlsplit(u).hostname == 'rl.algoux.cn'
                         and ('/ranklist/' in u or 'rankId=' in u)), None)
        # Direct DLUT links work even when CPC Finder is unavailable or has no profile.
        if cid and not (xcpc or rankland):
            cid = int(cid)
            detail = public_json(f'https://cpcfinder.com/api/contest/{cid}').get('data', {})
            if detail.get('contestId') != cid or detail.get('date', '')[:10] != participation['date']:
                raise ValueError('CPC Finder 比赛信息不一致')
            links += [v.get('url', '') for v in detail.get('links', [])]
            xcpc = next((u for u in links if urlsplit(u).hostname in {'xcpcio.com', 'board.xcpcio.com'}), None)
            rankland = next((u for u in links if urlsplit(u).hostname == 'rl.algoux.cn'
                             and ('/ranklist/' in u or 'rankId=' in u)), None)
        series, season, path = None, None, None
        try:
            series, season, path = edition_path(award)
        except (ValueError, KeyError):
            pass
        if xcpc:
            path = urlsplit(xcpc).path.removeprefix('/board/').strip('/')
            if not re.fullmatch(r'(?:icpc|ccpc)/(?:\d{4}|\d+th)/[a-z0-9-]+', path):
                raise ValueError('XCPCIO 比赛路径无效')
            series, edition, site = path.split('/')
            season = int(edition[:-2]) + (2014 if series == 'ccpc' else 1975) if edition.endswith('th') else int(edition)
        site_name = award.get('place') or participation.get('location')
        if xcpc:
            site_name = next((cn for cn, en in SITES.items() if en == site), site_name)
        elif rankland:
            parsed = urlsplit(rankland)
            key = parsed.path.removeprefix('/ranklist/') if '/ranklist/' in parsed.path else parse_qs(parsed.query).get('rankId',[''])[0]
            match = re.fullmatch(r'(icpc|ccpc)(\d{4})([a-z_]+)', key)
            if match:
                series, year, site = match.groups()
                season = int(year)
                site_name = next((cn for cn, en in SITES.items() if en == site.replace('_','')), site_name)
        contest = next((c for c in contests.values() if c['series'].lower() == series
                        and c['year'] == season and c['site'] == site_name), None)
        # Prefer the original board chosen by DLUT, including archived RankLand events.
        if rankland and (not xcpc or selected == rankland):
            body, source_id = self.rankland(rankland, award, participation, names)
        else:
            try:
                if not path:
                    raise ValueError('暂缺可读取逐题结果的原榜单链接')
                if self.revision is None:
                    self.revision = public_json('https://api.github.com/repos/xcpcio/board-data/commits/main')['sha']
                    if not re.fullmatch('[0-9a-f]{40}', self.revision):
                        raise ValueError('榜单版本无效')
                directory = self.root / self.revision / path
                directory.mkdir(parents=True, exist_ok=True)
                base = f'https://raw.githubusercontent.com/xcpcio/board-data/{self.revision}/data/{path}'
                for name in ('config', 'team', 'run'):
                    target = directory / (name + '.json')
                    if not target.exists():
                        raw = public_bytes(base + '/' + name + '.json')
                        json.loads(raw)
                        self.save_raw(target, raw)
                config = json.loads((directory / 'config.json').read_text())
                labels = [p['label'] for p in config['problems']]
                source_id = 'xcpcio-' + path.replace('/', '-')
                target_contest = contest or {'id': source_id, 'problems': [{'index': p} for p in labels]}
                teams = json.loads((directory / 'team.json').read_text())
                matching = [t for t in teams if t.get('name') == participation['team']
                            and school_matches(t.get('organization'), participation)]
                if len(matching) != 1:
                    raise ValueError('XCPCIO 队伍行不存在或有歧义')
                team = matching[0]
                check_members(team.get('members'), names)
                body = prepare_xcpc(directory, target_contest, {**participation,'school':team['organization']}, team.get('id', team.get('team_id')),
                                    'https://board.xcpcio.com/' + path,
                                    f'https://github.com/xcpcio/board-data/tree/{self.revision}/data/{path}')
                body.update(source_type='xcpcio', problem_labels=labels)
            except (OSError, ValueError, KeyError, TypeError):
                if not rankland:
                    raise
                body, source_id = self.rankland(rankland, award, participation, names)
        body.update(contest_id=contest['id'] if contest else source_id,
                    participation_id=participation['id'], team=participation['team'], confirmed=True,
                    cpcfinder_contest_id=cid, contest_name=participation['event'],
                    contest_date=participation['date'], dlut_ranklist_url=selected)
        if cid:
            body['cpcfinder_url'] = f'https://cpcfinder.com/contest/{cid}'
        return body
