#!/usr/bin/env python3
"""Join a DLUT CPC public snapshot to pinned regional final boards, offline.

Does not import results into any platform. All joins require a unique contest,
school and team, with the final board's actual contest date checked as well.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
MEDALS = ('gold', 'silver', 'bronze')
CN = {'gold': '金牌', 'silver': '银牌', 'bronze': '铜牌'}
SCHOOL_ALIASES = {'Dalian University of Technology': '大连理工大学'}
REFERENCE_UNOFFICIAL_TEAMS = {'Attention is all you need'}
# This pinned RankLand board has a year typo. The host university dates the
# 47th EC Final to 2023-03-25, as does the independently curated DLUT record.
DATE_CORRECTIONS = {'icpc-2022-ECFinal': ('2023-03-25', 'https://www.shu.edu.cn/info/1053/301004.htm')}
SITES = dict(zip(
    ['哈尔滨','济南','郑州','重庆','上海','南京','成都','武汉','沈阳','西安','香港','桂林','深圳','秦皇岛','合肥','杭州','澳门','昆明','长春','绵阳','威海','银川','南昌','徐州','广州','厦门'],
    ['harbin','jinan','zhengzhou','chongqing','shanghai','nanjing','chengdu','wuhan','shenyang','xian','hongkong','guilin','shenzhen','qinhuangdao','hefei','hangzhou','macau','kunming','changchun','mianyang','weihai','yinchuan','nanchang','xuzhou','guangzhou','xiamen']))


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold()
                   if not c.isspace() and not unicodedata.category(c).startswith(('P', 'Z')))


def localized(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        texts = value.get('texts', value)
        return texts.get('zh-CN') or texts.get('fallback') or texts.get('en') or ''
    return ''


def board_path(contest):
    evidence = contest.get('rating_evidence', {})
    if evidence.get('standings_path'):
        return evidence['standings_path']
    if contest['year'] < 2023:
        return None
    series = contest['series'].lower()
    edition = contest['year'] - (1975 if series == 'icpc' else 2014)
    return f'data/{series}/{edition}th/{SITES[contest["site"]]}'


def load_board(contest, stats, snapshot):
    path = snapshot / board_path(contest)
    provider = contest.get('rating_evidence', {}).get('provider', 'xcpcio')
    if provider == 'rankland':
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == stats['sha256']['rankland']
        if raw.lstrip().startswith(b'{'):
            data = json.loads(raw)
        else:
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(.*?)\s*</script>', raw.decode(), re.S)
            data = json.loads(ast.literal_eval(match[1].strip().removesuffix(';')))['ranklistData']
        srk = data['srk']
        labels = [p['alias'] for p in srk['problems']]
        date = dt.datetime.fromisoformat(srk['contest']['startAt'].replace('Z', '+00:00')).astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        rows = []
        for row in srk['rows']:
            user = row['user']
            accepted = [p for p, s in zip(labels, row['statuses']) if s.get('result') in ('AC', 'FB')]
            assert len(accepted) == row['score']['value']
            rows.append({'id': str(user['id']), 'team': localized(user['name']),
                         'school': localized(user.get('organization')), 'accepted': accepted,
                         'official': user.get('official'), 'markers': user.get('markers', [user['marker']] if user.get('marker') else []),
                         'members': [localized(m.get('name')) for m in user.get('teamMembers', []) if m.get('role', 'contestant') == 'contestant']})
        return date, rows
    if provider == 'final-scoreboard':
        raise ValueError('Anonymous archival rows cannot identify individual DLUT teams')
    data = {}
    for name in ('config', 'team', 'run'):
        raw = (path / f'{name}.json').read_bytes()
        assert hashlib.sha256(raw).hexdigest() == stats['sha256'][name]
        data[name] = json.loads(raw)
    config = data['config']
    scale = 1000 if config['start_time'] > 100_000_000_000 else 1
    duration = (config['end_time'] - config['start_time']) / scale
    date = dt.datetime.fromtimestamp(config['start_time'] / scale, dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    labels = {str(p['id']): p['label'] for p in config['problems']}
    run_scale = 1000 if config.get('options', {}).get('submission_timestamp_unit') == 'millisecond' else 1
    final = {}
    for i, run in enumerate(data['run']):
        rid = run.get('id', run.get('submission_id'))
        final[('id', str(rid)) if rid is not None else ('row', i)] = run
    accepted = {}
    for run in final.values():
        elapsed = run['timestamp'] / run_scale
        if 0 <= elapsed < duration and not run.get('is_ignore', run.get('ignore', False)) and run['status'].upper() in {'ACCEPTED','CORRECT','AC','OK'}:
            accepted.setdefault(str(run['team_id']), set()).add(labels[str(run['problem_id'])])
    organizations = {}
    if config.get('organizations', {}).get('url') == 'organizations.json':
        organizations = {str(o['id']): localized(o['name']) for o in json.loads((path/'organizations.json').read_text())}
    rows = []
    for team in data['team']:
        tid = str(team.get('id', team.get('team_id')))
        official = ('official' in team['group'] if 'group' in team else bool(team.get('official'))) and not ('unofficial' in team.get('group', []) or team.get('unofficial'))
        school = localized(team.get('organization')) or organizations.get(str(team.get('organization_id')), '')
        rows.append({'id': tid, 'team': localized(team['name']), 'school': SCHOOL_ALIASES.get(school, school),
                     'accepted': sorted(accepted.get(tid, [])), 'official': official, 'markers': [], 'members': []})
    return date, rows


def contest_for(honor, contests):
    edition = re.search(r'第\s*(\d+)\s*届', honor['event'])
    if not edition:
        return None
    season = int(edition[1]) + (1975 if honor['series'] == 'ICPC' else 2014)
    final = '总决赛' in honor['event'] or '东亚区决赛' in honor['event']
    cid = f'{honor["series"].lower()}-{season}-' + (('ECFinal' if honor['series'] == 'ICPC' else 'Final') if final else honor['location'])
    return contests.get(cid)


def superseding_safe_medal(stats, target):
    """The highest guarantee reached at this count, if no distinct stage exists."""
    count = stats['medal_safety'][target]['safe_solved']
    return next((medal for medal in MEDALS[:MEDALS.index(target)]
                 if count >= stats['medal_safety'][medal]['safe_solved']), None)


def plan_for(row, contest, stats, ratings, target, mode):
    count = stats['medal_boundaries'][target]['last_solved'] if mode == 'speed' else stats['medal_safety'][target]['safe_solved']
    solved = set(row['accepted'])
    missing = count - len(solved)
    problems = sorted(contest['problems'], key=lambda p: (ratings[p['id']]['rating'], p['index']))
    additions = [p for p in problems if p['index'] not in solved][:max(0, missing)]
    solved_ratings = [ratings[p['id']]['rating'] for p in problems if p['index'] in solved]
    available = missing <= len(additions)
    # Current solves are retained. Pick the easiest unaccepted problems to
    # minimize the maximum difficulty in the resulting solve set.
    max_new = max((ratings[p['id']]['rating'] for p in additions), default=None)
    max_total = max(solved_ratings + [ratings[p['id']]['rating'] for p in additions], default=None)
    superseded = superseding_safe_medal(stats, target) if mode == 'safe' else None
    return {'count': count, 'additional': max(0, missing), 'new_rating': max_new if available else None,
            'total_rating': max_total if available else None,
            'stage_available': superseded is None, 'superseded_by': CN.get(superseded),
            'problems': ', '.join(f'{p["index"]}({ratings[p["id"]]["rating"]})' for p in additions) if available else '题数不可达',
            'condition': '按本场终榜题数保证' if mode == 'safe' else ('已达题数，仍需降低罚时' if missing <= 0 else '同题数仍需比较罚时')}


def add_unofficial_reference(record, team, contest, stats, ratings):
    """Add requested training references without changing award eligibility."""
    if record['official'] or record['team'] not in REFERENCE_UNOFFICIAL_TEAMS:
        return
    medal = next((m for m in MEDALS if record['solved'] >= stats['medal_safety'][m]['safe_solved']), None)
    if medal is None:
        return  # A count alone cannot resolve a speed/penalty tie.
    record['reference_medal'] = CN[medal]
    record['reference_note'] = '打星队按正式队题数门槛作训练参考，不代表实际获牌'
    target = {'silver':'gold','bronze':'silver'}.get(medal)
    record['target'] = CN[target] + '（参考）' if target else '已达金牌题数（参考）'
    record['all_targets'] = {m: {mode: plan_for(team, contest, stats, ratings, m, mode)
                               for mode in ('speed','safe')} for m in MEDALS}
    record['plans'] = record['all_targets'][target] if target else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dlut', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--extra-boards', type=Path, help='Optional RankLand HTML for contests lacking current ratings')
    args = parser.parse_args()
    source = json.loads(args.dlut.read_text())
    release = json.loads((ROOT/'catalog/regional_ratings.json').read_text())
    catalog = json.loads((ROOT/'catalog/regionals.json').read_text())
    contests = {c['id']: c for c in catalog['contests']}
    honors = [h for h in source['honors'] if '2020-01-01' <= h['date'] <= '2026-10-16' and h['series'] in ('ICPC', 'CCPC')]
    cache, results, issues = {}, [], []
    for honor in sorted(honors, key=lambda h: (h['date'], h['event'], h['school'], h['team']), reverse=True):
        contest = contest_for(honor, contests)
        row = {key: honor.get(key) for key in ('id','date','event','team','school','medal','rank','overallRank','official','members','rosterConfirmed')}
        row['honor_source'] = honor.get('source', {}).get('url')
        row['board_url'] = source.get('contestRanklists', {}).get(honor['event'], '')
        if isinstance(row['board_url'], dict):
            row['board_url'] = row['board_url'].get('url', '')
        edition = re.search(r'第\s*(\d+)\s*届', honor['event'])
        row['season'] = contest['year'] if contest else (int(edition[1]) + (1975 if honor['series'] == 'ICPC' else 2014) if edition else None)
        row['contest_id'] = contest['id'] if contest else None
        try:
            if not contest:
                raise ValueError('区域赛目录尚未收录该场比赛')
            stats = release['contests'].get(contest['id'])
            if not stats:
                raise ValueError(release['unrated_contests'].get(contest['id'], '无可核验奖牌评级'))
            row['board_url'] = next((release['problems'][p['id']]['standings_url'] for p in contest['problems'] if p['id'] in release['problems']), stats['source_url'])
            if contest['id'] not in cache:
                cache[contest['id']] = load_board(contest, stats, args.snapshot)
            date, teams = cache[contest['id']]
            if date != honor['date'] and contest['id'] in DATE_CORRECTIONS:
                date, reference = DATE_CORRECTIONS[contest['id']]
                row['source_note'] = 'RankLand 元数据年份误写为 2022，按承办方报道核验为 2023-03-25'
                row['date_reference'] = reference
            if date != honor['date']:
                raise ValueError(f'DLUT 日期 {honor["date"]} 与终榜 {date} 不一致')
            exact = [t for t in teams if t['team'] == honor['team'] and t['school'] == honor['school']]
            matching = exact or [t for t in teams if normalized(t['team']) == normalized(honor['team']) and normalized(t['school']) == normalized(honor['school'])]
            if len(matching) != 1:
                raise ValueError(f'终榜学校及队名匹配到 {len(matching)} 行')
            team = matching[0]
            if team['official'] != honor['official']:
                raise ValueError('DLUT 与终榜的正式/打星资格不一致')
            row['board_team_id'] = team['id']
            row['board_team_name'] = team['team']
            row['solved'] = len(team['accepted'])
            ratings = release['problems']
            problems = sorted(contest['problems'], key=lambda p: (ratings[p['id']]['rating'], p['index']))
            solved = [p for p in problems if p['index'] in team['accepted']]
            todo = [p for p in problems if p['index'] not in team['accepted']]
            row['accepted'] = ', '.join(f'{p["index"]}({ratings[p["id"]]["rating"]})' for p in solved)
            row['max_rating'] = max((ratings[p['id']]['rating'] for p in solved), default=None)
            row['hardest'] = ', '.join(p['index'] for p in solved if ratings[p['id']]['rating'] == row['max_rating'])
            row['next_rating'] = ratings[todo[0]['id']]['rating'] if todo else None
            row['next_problems'] = ', '.join(p['index'] for p in todo if ratings[p['id']]['rating'] == row['next_rating'])
            groups = stats.get('medal_reference_groups', [])
            if len(groups) > 1:
                group = [g for g in groups if g['marker'] in team['markers']]
                if len(group) != 1:
                    raise ValueError('未能唯一确认队伍奖牌分组')
                stats = group[0]
                row['medal_group'] = group[0]['label']
            else:
                row['medal_group'] = '正式队'
            target = {'银牌':'gold','铜牌':'silver','铁牌':'bronze'}.get(honor['medal'])
            row['target'] = CN.get(target, '已获金牌') if honor['official'] else '打星无获奖资格'
            row['plans'] = {}
            if target and honor['official']:
                row['plans'] = {mode: plan_for(team, contest, stats, ratings, target, mode) for mode in ('speed', 'safe')}
            row['all_targets'] = {m: {mode: plan_for(team, contest, stats, ratings, m, mode) for mode in ('speed', 'safe')} for m in MEDALS} if honor['official'] else {}
            add_unofficial_reference(row, team, contest, stats, ratings)
            row['status'] = '已核验逐题终榜'
        except (ValueError, KeyError, OSError) as exc:
            row['status'] = str(exc)
            key = honor.get('externalContestId', '')
            if args.extra_boards and re.fullmatch(r'[a-z0-9_-]+', str(key)):
                path = args.extra_boards / (key + '.html')
                if path.exists():
                    raw = path.read_bytes()
                    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(.*?)\s*</script>', raw.decode(), re.S)
                    state = json.loads(ast.literal_eval(match[1].strip().removesuffix(';')))['ranklistData']
                    assert state['info']['uniqueKey'] == key
                    srk = state['srk']
                    date = dt.datetime.fromisoformat(srk['contest']['startAt']).date().isoformat()
                    teams = [t for t in srk['rows'] if localized(t['user']['name']) == honor['team']
                             and localized(t['user']['organization']) == honor['school']]
                    assert date == honor['date'] and len(teams) == 1
                    team = teams[0]
                    assert team['user']['official'] == honor['official']
                    accepted = [p['alias'] for p, s in zip(srk['problems'], team['statuses']) if s.get('result') in ('AC', 'FB')]
                    assert len(accepted) == team['score']['value']
                    assert all(s.get('result') in (None, 'AC', 'FB', 'RJ') for s in team['statuses'])
                    row.update(solved=len(accepted), accepted=', '.join(accepted), board_team_id=str(team['user']['id']),
                               board_team_name=localized(team['user']['name']), board_url='https://rl.algoux.cn/ranklist/'+key,
                               supplement_sha256=hashlib.sha256(raw).hexdigest(),
                               target={'银牌':'金牌','铜牌':'银牌','铁牌':'铜牌'}.get(honor['medal'], '已获金牌'))
                    row['status'] = '已核验赛时 AC；' + str(exc)
            issues.append({'id': honor['id'], 'date': honor['date'], 'event': honor['event'], 'team': honor['team'], 'reason': str(exc)})
        results.append(row)
    # No source participation may vanish because ratings or mapping are absent.
    assert len(results) == len(honors) and len({r['id'] for r in results}) == len(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'as_of':'2026-10-16','source_url':'https://dlut-cpc.wannafly.cn/api/site',
        'source_sha256':hashlib.sha256(args.dlut.read_bytes()).hexdigest(), 'rating_revision':release['source_revision'],
        'records':results,'issues':issues}, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'records':len(results),'verified':len(results)-len(issues),'issues':issues},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
