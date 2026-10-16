"""프로젝트 내부 경로, 확정 보정의 사전조건과 기계 판독용 실행 기록."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def internal(path):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"프로젝트 외부 경로는 사용할 수 없습니다: {path}")
    return path


def initialize():
    # 운영체제의 기본 TEMP를 연구 파일의 임시 경로로 사용하지 않는다.
    for name, relative in {
        'TMP': '.tmp', 'TEMP': '.tmp', 'TMPDIR': '.tmp',
        'NUMBA_CACHE_DIR': '.cache/numba', 'MPLCONFIGDIR': '.cache/matplotlib',
        'XDG_CACHE_HOME': '.cache', 'PIP_CACHE_DIR': '.cache/pip',
    }.items():
        path = internal(relative)
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    os.environ['PYTHONNOUSERSITE'] = '1'
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    for name in ['data/raw', 'data/processed', 'overrides']:
        base = internal(name)
        if base.exists():
            # 파일별 경로까지 확인하여 외부 정션/심볼릭 링크를 허용하지 않는다.
            for item in base.rglob('*'):
                internal(item)


def data_path(path=None):
    result = internal(path or ROOT / 'data')
    if result != internal(ROOT / 'data'):
        raise ValueError('자료는 현재 프로젝트의 data 폴더에 배치해야 합니다.')
    for branch in ('raw', 'processed'):
        internal(result / branch)
    return result


def sha256(path):
    with internal(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def approved(filename):
    path = internal(ROOT / 'overrides' / filename)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    ids = set()
    targets = {}
    result = []
    for row in rows:
        oid = row['override_id']
        if not oid or oid in ids:
            raise ValueError(f'보정 ID 누락/중복: {oid}')
        ids.add(oid)
        if row['status'] != 'approved':
            continue
        row = dict(row)
        row['expected'] = json.loads(row['expected_before'] or '{}')
        row['value'] = json.loads(row['new_value'])
        if row['target_fingerprint'] and fingerprint(row['expected']) != row['target_fingerprint']:
            raise ValueError(f'사전조건 지문 불일치: {oid}')
        if not row['expected']:
            raise ValueError(f'사전조건 없음: {oid}')
        key = (row['dataset_id'], row['target_id'], row['field'])
        if key in targets and targets[key]['new_value'] != row['new_value']:
            previous = targets[key]
            if row['supersedes'] != previous['override_id']:
                raise ValueError(f'충돌하는 승인 보정: {previous["override_id"]}, {oid}')
            result.remove(previous)
        targets[key] = row
        result.append(row)
    return result


def check_expected(row, actual):
    expected = row['expected']
    mismatches = {k: {'expected': v, 'actual': actual.get(k)} for k, v in expected.items()
                  if actual.get(k) != v}
    if mismatches:
        raise ValueError(f"보정 대상 불일치 {row['override_id']}: {mismatches}")


def record(row, status, before=None, after=None):
    return dict(override_id=row['override_id'], target_id=row['target_id'],
                action=row['action'], status=status, before=before, after=after,
                target_fingerprint=row['target_fingerprint'])


def save_report(name, report):
    target = internal(ROOT / 'data/processed/preprocessing_reports' / (name + '.json'))
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(schema_version='1.0', completed_at_utc=datetime.now(timezone.utc).isoformat(),
                   status='complete', **report)
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(target)
    return payload


def building_constants():
    groups = {}
    for row in approved('building_decisions.csv'):
        if row['action'] not in {'set_residential_decision', 'exclude_group'}:
            raise ValueError('미지원 건물 보정: ' + row['action'])
        sid = row['target_id'].split(':', 1)[1]
        for group, value in row['value']['classification_constants'].items():
            groups.setdefault(group, {})[sid] = tuple(value) if isinstance(value, list) else value
    return groups


def validate_buildings(frame, names):
    lookup = frame.set_index('_id', drop=False)
    rows = approved('building_decisions.csv')
    for row in rows:
        sid = row['target_id'].split(':', 1)[1]
        if row['action'] == 'exclude_group':
            members = row['expected']['member_source_ids']
            actual = set(frame.loc[frame['_group'].eq(sid), '_id'])
            if not set(members) <= actual:
                raise ValueError('건물군 소속 변경: ' + sid)
            check_expected(row, {'building_group_id': sid, 'member_source_ids': members})
        else:
            item = lookup.loc[sid]
            check_expected(row, {'source_id': sid, 'use_code': item.BDTYP_CD, 'name': names(item)})
    return rows


def building_application_log(rows, decisions):
    lookup = decisions.set_index('source_id')
    log = []
    for row in rows:
        if row['action'] == 'exclude_group':
            ids = row['expected']['member_source_ids']
            if not lookup.loc[ids, 'action'].eq('excluded').all():
                raise ValueError('군부대 제외 미반영')
            after = {'excluded_members': len(ids)}
        else:
            item = lookup.loc[row['target_id'].split(':', 1)[1]]
            after = {'classification': item.action, 'classification_reason': item.reason}
            for field, value in after.items():
                if row['value'][field] != value:
                    raise ValueError('건물 확정 판정 미반영: ' + row['override_id'])
        log.append(record(row, 'applied', row['expected'], after))
    return log


def walk_constants():
    mapping = {'allow_both_walk_directions': 'CONFIRMED_BIDIRECTIONAL_WAYS',
               'exclude_walk_way': 'CONFIRMED_NO_PEDESTRIAN_ACCESS',
               'use_separate_sidewalk': 'CONFIRMED_SEPARATE_SIDEWALKS'}
    result = {name: set() for name in mapping.values()}
    for row in approved('walk_access_decisions.csv'):
        if row['action'] in mapping:
            result[mapping[row['action']]].add(int(row['target_id'].split(':')[1]))
    return result


def validate_walk(ways):
    lookup = {w['id']: w for w in ways}
    log = []
    for row in approved('walk_access_decisions.csv'):
        if not row['target_id'].startswith('osm_way:'):
            continue  # 출입구·특정 접속선의 예외는 후속 연결 단계에서 적용한다.
        sid = int(row['target_id'].split(':')[1])
        item = lookup[sid]
        actual = {'osm_way_id': sid, 'highway': item['tags'].get('highway', ''),
                  'source_node_count': len(item['refs']),
                  'tags_json': json.dumps(item['tags'], ensure_ascii=False, sort_keys=True)}
        check_expected(row, actual)
        log.append(record(row, 'validated', actual, row['value']))
    return log


def validate_geocodes(frame):
    lookup = frame.set_index('hospital_id', drop=False)
    log = []
    for row in approved('facility_decisions.csv'):
        if row['action'] != 'retain_stored_geocode':
            continue
        sid = row['target_id'].split(':', 1)[1]
        item = lookup.loc[sid]
        check_expected(row, {key: item[key] for key in row['expected']})
        for key in ['longitude', 'latitude']:
            if abs(float(item[key]) - row['value'][key]) > 1e-10:
                raise ValueError('저장 지오코딩 좌표 변경: ' + row['override_id'])
        log.append(record(row, 'retained_stored_geocode', row['expected'], row['value']))
    return log
