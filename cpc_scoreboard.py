"""Prepare audited onsite evidence from a local XCPCIO final snapshot."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

ACCEPTED = {'ACCEPTED', 'CORRECT', 'OK', 'AC'}
FINAL_OTHER = {'WRONG_ANSWER', 'TIME_LIMIT_EXCEEDED', 'RUNTIME_ERROR', 'MEMORY_LIMIT_EXCEEDED',
               'OUTPUT_LIMIT_EXCEEDED', 'IDLENESS_LIMIT_EXCEEDED', 'NO_OUTPUT', 'REJECTED',
               'COMPILATION_ERROR', 'PRESENTATION_ERROR', 'CONFIGURATION_ERROR', 'SYSTEM_ERROR',
               'CANCELED', 'SKIPPED'}


def prepare_xcpc(directory, contest, participation, team_id, source_url, snapshot_url=''):
    if urlsplit(source_url).scheme not in {'http', 'https'}:
        raise ValueError('请提供榜单来源链接')
    data, hashes = {}, {}
    for name in ('config', 'team', 'run'):
        raw = (Path(directory) / (name + '.json')).read_bytes()
        data[name] = json.loads(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    config, teams, runs = data['config'], data['team'], data['run']
    if not isinstance(config, dict) or not isinstance(teams, list) or not isinstance(runs, list):
        raise ValueError('榜单快照结构无效')
    matching = [t for t in teams if str(t.get('id', t.get('team_id'))) == str(team_id)]
    if len(matching) != 1:
        raise ValueError('榜单队伍 ID 不存在或不唯一')
    team = matching[0]
    if team.get('name') != participation['team'] or team.get('organization') != participation['school']:
        raise ValueError('榜单队名或学校与已确认参赛记录不一致，请人工核验')
    problem_map = {str(p['id']): p['label'] for p in config['problems']}
    expected = {p['index'] for p in contest['problems']}
    if (len(problem_map) != len(config['problems']) or len(set(problem_map.values())) != len(problem_map)
            or set(problem_map.values()) != expected):
        raise ValueError('榜单题序与比赛目录不一致')
    clock_scale = 1000 if config['start_time'] > 100_000_000_000 else 1
    start = config['start_time'] / clock_scale
    duration = (config['end_time'] - config['start_time']) / clock_scale
    if not math.isfinite(duration) or not 0 < duration <= 86400:
        raise ValueError('比赛时长无效')
    date = dt.datetime.fromtimestamp(start, dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    if date != participation['date']:
        raise ValueError('榜单日期与参赛记录或比赛目录不一致')
    unit = config.get('options', {}).get('submission_timestamp_unit', 'second')
    if unit not in {'second', 'millisecond'}:
        raise ValueError('未知榜单时间单位')
    # A later verdict for the same submission replaces its earlier verdict.
    final_runs = {}
    for index, run in enumerate(runs):
        rid = run.get('id', run.get('submission_id'))
        final_runs[('id', str(rid)) if rid is not None else ('row', index)] = run
    accepted, evidence = set(), []
    for run in final_runs.values():
        if str(run['team_id']) != str(team_id):
            continue
        elapsed = run['timestamp'] / (1000 if unit == 'millisecond' else 1)
        if not math.isfinite(elapsed):
            raise ValueError('提交时间无效')
        if elapsed < 0 or elapsed >= duration or run.get('is_ignore', run.get('ignore', False)):
            continue
        label = problem_map.get(str(run['problem_id']))
        if label is None:
            raise ValueError('提交题目未映射到榜单题序')
        status = run['status'].upper()
        if status not in ACCEPTED | FINAL_OTHER:
            raise ValueError('榜单仍有未决提交，不能导入为最终结果')
        # Official/medal eligibility has no bearing on real in-contest solves.
        if status in ACCEPTED:
            accepted.add(label)
            evidence.append({'submission_id': run.get('id', run.get('submission_id')),
                             'problem': label, 'elapsed_seconds': elapsed, 'status': status})
    return {'contest_id': contest['id'], 'participation_id': participation['id'],
            'team': participation['team'], 'source_url': source_url, 'source_row': str(team_id),
            'accepted': sorted(accepted), 'confirmed': False, 'source_team': team,
            'source_config': config, 'source_sha256': hashes, 'snapshot_url': snapshot_url,
            'accepted_runs': evidence}
