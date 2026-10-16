# -*- coding: utf-8 -*-
"""raw OSM PBF와 raw SGIS 경계만으로 보행망 GeoPackage를 만든다.

실행: python "preprocess/05_osm_walk_network.py"
기본: 고양시+주변 12개 지역의 2km 완충영역을 감싸는 추출 사각형,
      도로 전체 참조 보존, 거리 기반 비용, 계단 포함, 작은 연결성분 유지.
산출물: processed/osm_walk_network.gpkg. 처리·검증 결과는 JSON 표준출력.
MD·이미지를 작성하지 않으며 외부 GeoJSON/기존 processed를 읽지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.preprocessing_common import (ROOT, initialize, internal, data_path, save_report,
    building_constants, validate_buildings, building_application_log, walk_constants, validate_walk)
initialize()
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile

import geopandas as gpd
import networkx as nx
import numpy as np
import osmium
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point, box

REGIONS = {
    '31101': '고양시 덕양구', '31103': '고양시 일산동구', '31104': '고양시 일산서구',
    '31030': '의정부시', '31200': '파주시', '31230': '김포시', '31260': '양주시',
    '11010': '종로구', '11080': '성북구', '11090': '강북구', '11100': '도봉구',
    '11120': '은평구', '11130': '서대문구', '11140': '마포구', '11160': '강서구',
}
ALLOWED = {'yes', 'designated', 'official', 'permissive'}
DENIED = {'no', 'private', 'closed', 'military'}
LIMITED = {'destination', 'customers', 'delivery', 'permit', 'agricultural', 'forestry'}
WALK_TYPES = {'footway', 'pedestrian', 'path', 'steps', 'corridor', 'platform',
              'residential', 'living_street', 'service', 'unclassified', 'track',
              'primary', 'primary_link', 'secondary', 'secondary_link',
              'tertiary', 'tertiary_link', 'residential_link'}
MOTOR_TYPES = {'motorway', 'motorway_link', 'trunk', 'trunk_link'}
INACTIVE_TYPES = {'construction', 'proposed', 'disused', 'abandoned', 'razed'}
ROAD_TYPES = WALK_TYPES - {'footway', 'pedestrian', 'path', 'steps', 'corridor', 'platform', 'track'}
PASS_BARRIERS = {'', 'no', 'bollard', 'cycle_barrier', 'motorcycle_barrier',
                 'height_restrictor', 'bus_trap', 'entrance', 'kerb'}
# 사용자가 확인한 기존 W번호를 유지한다. 각 묶음의 최소 원본 way ID가 기준이며,
# 검토 대상 삭제 후에도 재번호를 매기지 않는다. 새 묶음은 W_OSM_<최소 ID> 사용.
# 위치 안내용 번호 대응표이며 기존 processed 파일을 입력으로 읽지 않는다.
REVIEW_ID_ANCHORS = [
    31274999, 124955261, 124955308, 125062189, 125104622,
    128945530, 134834196, 134834197, 134834204, 301277512,
    380883723, 381956914, 381956925, 394306817, 464233652,
    465315856, 469693938, 469693951, 470627702, 470653858,
    470658558, 471478113, 588189241, 588536002, 614034666,
    952092576, 976031834, 1243460859, 1275296578, 1301826250,
    37928434, 59097428, 59097498, 70998377, 129015727,
    203390542, 218855790, 224673555, 226311676, 241752056,
    276659755, 314992673, 471845977, 484830938, 516723474,
    516723476, 668184492, 896413225, 908313115, 908654523,
    976031826, 1193136544, 1221350594, 1273992540, 1337988547,
]
REVIEW_IDS = {anchor: f'W{n:03d}' for n, anchor in enumerate(REVIEW_ID_ANCHORS, 1)}
# 2026-10-12 사용자 지도 확인. 이번에 확인한 원본 길에만 적용하며,
# 다른 길의 보행 금지·조건부 출입·보행 전용 방향 태그를 일괄 해제하지 않는다.
# W054: 사용자가 보행자 출입 불가로 확인. 원본 access=unknown은 보존한다.
_confirmed = walk_constants()
CONFIRMED_BIDIRECTIONAL_WAYS = _confirmed['CONFIRMED_BIDIRECTIONAL_WAYS']
CONFIRMED_NO_PEDESTRIAN_ACCESS = _confirmed['CONFIRMED_NO_PEDESTRIAN_ACCESS']
CONFIRMED_SEPARATE_SIDEWALKS = _confirmed['CONFIRMED_SEPARATE_SIDEWALKS']

TAG_KEYS = ['name', 'highway', 'foot', 'access', 'motorroad', 'service', 'footway',
            'sidewalk', 'sidewalk:both', 'sidewalk:left', 'sidewalk:right',
            'oneway', 'oneway:foot', 'foot:forward', 'foot:backward',
            'foot:conditional', 'access:conditional', 'oneway:foot:conditional',
            'bridge', 'tunnel', 'layer', 'level', 'indoor', 'incline', 'surface',
            'smoothness', 'sac_scale', 'conveying', 'conveying:forward', 'conveying:backward',
            'barrier', 'entrance', 'door', 'locked', 'crossing', 'crossing:signals',
            'railway', 'public_transport', 'wheelchair', 'step_count', 'area']


def require(ok, message):
    if not ok:
        raise ValueError(message)


def log(message):
    print(message, file=sys.stderr, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def find_one(root, pattern):
    paths = list(root.rglob(pattern))
    require(len(paths) == 1, f'{pattern}: 원본 1개 필요, 현재 {len(paths)}개')
    return paths[0]


def tags_json(tags):
    # 겸용 통행 등 추가 속성을 누락하지 않도록 원본 속성을 보존한다.
    return json.dumps(dict(tags), ensure_ascii=False, sort_keys=True)



def boundary_areas(path, buffer_m):
    raw = gpd.read_file(path, engine='pyogrio')
    require(raw.crs is not None, '경계 좌표계 없음')
    selected = raw.loc[raw.SIGUNGU_CD.astype(str).isin(REGIONS)].copy()
    require(len(selected) == 15 and selected.SIGUNGU_CD.is_unique, '경계 15개 누락/중복')
    require(set(selected.BASE_DATE.astype(str)) == {'20250630'}, '경계 기준일 불일치')
    for row in selected.itertuples():
        require(row.SIGUNGU_NM == REGIONS[str(row.SIGUNGU_CD)], '경계 코드·명칭 불일치')
    selected = selected.to_crs(5179)
    require(selected.geometry.notna().all() and (~selected.geometry.is_empty).all(), '빈 경계')
    selected.geometry = selected.geometry.map(lambda g: shapely.make_valid(g) if not g.is_valid else g)
    core = shapely.union_all(selected.geometry.values)
    # 코드를 이동해도 같은 raw 경계로 같은 범위를 재생성한다.
    bounds = gpd.GeoSeries([core.buffer(buffer_m).envelope], crs=5179).to_crs(4326).total_bounds
    extraction = box(*bounds)
    actual_m = gpd.GeoSeries([extraction], crs=4326).to_crs(5179).iloc[0]
    areas = gpd.GeoDataFrame([
        {'area_id': 'institution_region', 'buffer_m': 0.0, 'geometry': core},
        {'area_id': 'extraction_bbox', 'buffer_m': float(buffer_m), 'geometry': actual_m},
    ], crs=5179)
    areas.geometry = areas.geometry.map(lambda g: shapely.MultiPolygon([g]) if g.geom_type == 'Polygon' else g)
    areas['area_km2'] = areas.area / 1e6
    return bounds, extraction, core, areas


def access_rule(tags):
    """보행 지정 값이 일반 access보다 우선한다. 값 부재와 금지를 구분한다."""
    foot = tags.get('foot', '')
    access = tags.get('access', '')
    if foot in DENIED or foot == 'use_sidepath':
        return 'exclude', 'foot_' + foot
    if foot in LIMITED:
        return ('conditional' if foot in {'destination', 'customers'} else 'exclude'), 'restricted_foot_' + foot
    if foot and foot not in ALLOWED:
        return 'review', 'unknown_foot_value'
    if 'foot:conditional' in tags or 'oneway:foot:conditional' in tags:
        return 'review', 'conditional_pedestrian_access'
    if not foot:
        if 'access:conditional' in tags and not expired_closure(tags['access:conditional']):
            return 'review', 'conditional_access'
        if access in DENIED:
            return 'exclude', 'access_' + access
        if access in LIMITED:
            return ('conditional' if access in {'destination', 'customers'} else 'exclude'), 'restricted_access_' + access
        if access and access not in ALLOWED:
            return 'review', 'unknown_access_value'
    return 'include', 'explicit_foot' if foot in ALLOWED else 'type_default'


def expired_closure(value):
    """명확히 종료된 단일 폐쇄 기간만 해석. 그 외 조건식은 임의로 해제하지 않는다."""
    match = re.fullmatch(r'no\s*@\s*\((\d{4} [A-Za-z]{3} \d{1,2})\s*-\s*(\d{4} [A-Za-z]{3} \d{1,2})\)', value)
    if not match:
        return False
    months = {m: i+1 for i, m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())}
    def parts(s):
        y, m, d = s.split()
        return int(y), months[m], int(d)
    try:
        begin, end = parts(match[1]), parts(match[2])
        return begin <= end < (2025, 1, 1)
    except (ValueError, KeyError):
        return False


def has_sidewalk(tags):
    return (tags.get('sidewalk') in {'yes', 'both', 'left', 'right', 'lane'} or
            any(tags.get(k) == 'yes' for k in ['sidewalk:left', 'sidewalk:right', 'sidewalk:both']))


def way_rule(tags, osm_way_id=None):
    if osm_way_id in CONFIRMED_NO_PEDESTRIAN_ACCESS:
        return 'exclude', 'user_confirmed_no_pedestrian_access', []
    highway = tags.get('highway', '')
    if not highway:
        return 'exclude', 'not_highway', []
    if highway in INACTIVE_TYPES:
        return 'exclude', 'inactive_highway', []
    state, reason = access_rule(tags)
    if state != 'include':
        return state, reason, []
    if highway in {'motorway', 'motorway_link'} or tags.get('motorroad') == 'yes':
        return ('review', 'motorroad_foot_conflict', []) if tags.get('foot') in ALLOWED else ('exclude', 'motorroad', [])
    if highway in {'trunk', 'trunk_link'} and tags.get('foot') not in ALLOWED:
        return 'exclude', 'motorroad', []
    if tags.get('area') == 'yes':
        return 'deferred', 'area_requires_internal_paths', []
    if highway == 'elevator':
        return 'deferred', 'elevator_requires_vertical_model', []
    if tags.get('indoor') == 'room':
        return 'review', 'indoor_room_not_path', []
    if highway not in WALK_TYPES:
        if highway in {'cycleway', 'bridleway', 'busway', 'road', 'trunk', 'trunk_link'} and tags.get('foot') in ALLOWED:
            reason = 'explicit_foot_over_road_class'
        elif highway == 'cycleway' and tags.get('segregated') in {'yes', 'no'}:
            reason = 'shared_cycle_foot_attribute'
        elif highway in {'cycleway', 'busway'} and has_sidewalk(tags):
            reason = 'sidewalk_attribute'
        elif highway == 'cycleway' and any(tags.get(k) == 'separate' for k in ['sidewalk', 'sidewalk:both', 'sidewalk:left', 'sidewalk:right']):
            return 'separate', 'use_separately_mapped_sidewalk', []
        elif highway == 'cycleway':
            # 사용자 확정: 보행 허용·겸용·보도 근거가 없는 자전거길은 분석에서 제외.
            # 속성 부재를 실제 법적 보행 금지로 해석한 것은 아니다.
            return 'exclude', 'cycleway_without_pedestrian_evidence', []
        elif highway in {'road', 'bridleway'}:
            # 사용자 검토 확정: 현재 '보행 허용 정보 부족' 범주의 51개 길 제외.
            # 명시적인 foot 허용은 위 분기에서 유지하며 일반 path/track에 확대하지 않는다.
            return 'exclude', 'way_without_pedestrian_evidence', []
        elif highway == 'crossing' and tags.get('crossing') in {'zebra', 'marked', 'traffic_signals', 'uncontrolled'}:
            reason = 'pedestrian_crossing_attribute'
        elif highway == 'busway':
            return 'exclude', 'busway_without_pedestrian_evidence', []
        elif highway == 'raceway' and tags.get('sport') in {'motor', 'karting'}:
            return 'exclude', 'motor_sport_track', []
        elif highway in {'services', 'rest_area', 'bus_stop'}:
            return 'deferred', 'facility_outline_not_walk_path', []
        else:
            return 'review', 'highway_requires_foot_evidence', []
    separate = tags.get('sidewalk') == 'separate' or tags.get('sidewalk:both') == 'separate'
    separate |= tags.get('sidewalk:left') == tags.get('sidewalk:right') == 'separate'
    if highway in ROAD_TYPES and separate:
        return 'separate', 'use_separately_mapped_sidewalk', []
    conveying = tags.get('conveying', '')
    if highway == 'steps' and conveying in {'', 'no'}:
        # 사용자 확정: 일반 계단은 보행 방향 속성과 관계없이 양방향으로 모델링한다.
        return 'include', 'ordinary_steps_bidirectional', [1, -1]
    directions = [1, -1]
    direction = tags.get('oneway:foot', '')
    if direction in {'yes', '1', 'true'}:
        directions = [1]
    elif direction == '-1':
        directions = [-1]
    elif direction not in {'', 'no', '0', 'false'}:
        return 'review', 'unknown_pedestrian_direction', []
    if not direction and conveying not in {'', 'no'} and tags.get('oneway') in {'yes', '-1'}:
        directions = [1 if tags['oneway'] == 'yes' else -1]
    elif not direction and highway in {'footway', 'path', 'corridor'} and tags.get('oneway') in {'yes', '-1'}:
        if 'oneway:bicycle' not in tags:
            if osm_way_id in CONFIRMED_BIDIRECTIONAL_WAYS:
                reason = 'user_confirmed_bidirectional'
            else:
                return 'review', 'ambiguous_oneway_on_walkway', []
    if conveying in {'forward', 'backward'}:
        directions = [d for d in directions if d == (1 if conveying == 'forward' else -1)]
    elif conveying not in {'', 'no'}:
        if tags.get('conveying:forward') == tags.get('conveying:backward') == 'yes':
            pass  # 같은 통로의 양방향 설비가 명시된 경우, 보행속도만 적용.
        elif conveying == 'yes' and len(directions) == 1:
            pass
        else:
            return 'deferred', 'conveying_direction_unresolved', []
    for tag, d in [('foot:forward', 1), ('foot:backward', -1)]:
        value = tags.get(tag, '')
        if value in DENIED:
            directions = [x for x in directions if x != d]
        elif value and value not in ALLOWED:
            return 'review', 'directional_access_unresolved', []
    return ('include', reason, directions) if directions else ('exclude', 'no_permitted_direction', [])


def node_rule(tags):
    state, reason = access_rule(tags)
    if state != 'include':
        return state, reason
    if tags.get('locked') == 'yes':
        return 'exclude', 'locked'
    if tags.get('entrance') in {'emergency', 'exit'}:
        return 'review', 'restricted_entrance'
    if tags.get('highway') == 'elevator' or tags.get('level', '').count(';') > 0:
        return 'review', 'vertical_node_requires_model'
    barrier = tags.get('barrier', '')
    if tags.get('foot') in ALLOWED or tags.get('access') in ALLOWED:
        return 'include', 'explicit_access'
    if barrier in PASS_BARRIERS:
        return 'include', 'pedestrian_passable_default'
    if barrier in {'wall', 'fence', 'hedge', 'block', 'barricade', 'jersey_barrier', 'tank_trap'}:
        return 'exclude', 'physical_barrier'
    return 'review', 'barrier_passage_unconfirmed'


def important_node(tags):
    return (any(k in tags for k in ['barrier', 'entrance', 'door', 'public_transport'])
            or tags.get('highway') in {'crossing', 'traffic_signals', 'traffic_signals;crossing', 'elevator', 'bus_stop', 'platform', 'steps'}
            or tags.get('railway') in {'subway_entrance', 'station', 'halt', 'platform'}
            or any(k in tags for k in ['foot', 'access', 'foot:conditional', 'access:conditional']))


class Extractor(osmium.SimpleHandler):
    def __init__(self, bounds, polygon):
        super().__init__()
        self.bounds, self.polygon = bounds, polygon
        self.ways, self.tagged_nodes, self.barriers, self.relations = [], {}, [], []
        self.counts, self.tag_counts = Counter(), Counter()
        self.selected_way_ids = set()

    def node(self, n):
        self.counts['national_nodes'] += 1
        if self.counts['national_nodes'] % 5000000 == 0:
            log(f"OSM 지점 {self.counts['national_nodes']:,}개 읽음")
        if not len(n.tags):
            return
        tags = dict(n.tags)
        if not important_node(tags):
            return
        # 경계 밖으로 이어지는 완전한 way의 제한 노드도 빠뜨리지 않도록 전국의 관련 태그 보관.
        self.tagged_nodes[n.id] = {'coords': (n.location.lon, n.location.lat), 'tags': tags}

    def way(self, w):
        self.counts['national_ways'] += 1
        if self.counts['national_ways'] % 500000 == 0:
            log(f"OSM 선 {self.counts['national_ways']:,}개 읽음")
        tags = dict(w.tags)
        if not ('highway' in tags or 'barrier' in tags):
            return
        refs, coords = [], []
        for n in w.nodes:
            require(n.location.valid(), f'원본 way {w.id}의 참조 지점 좌표 누락')
            refs.append(n.ref)
            coords.append((n.lon, n.lat))
        if len(coords) < 2:
            self.counts['short_source_ways'] += 1
            return
        xs, ys = zip(*coords)
        x0, y0, x1, y1 = self.bounds
        if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
            return
        geometry = LineString(coords)
        if not geometry.intersects(self.polygon):
            return
        if 'barrier' in tags:
            self.barriers.append({'osm_way_id': w.id, 'barrier': tags['barrier'], 'tags_json': tags_json(tags), 'geometry': geometry})
        if 'highway' not in tags:
            return
        self.selected_way_ids.add(w.id)
        self.tag_counts[tags['highway']] += 1
        self.ways.append({'id': w.id, 'refs': refs, 'coords': coords, 'tags': tags, 'geometry': geometry})

    def relation(self, r):
        tags = dict(r.tags)
        members = [(m.type, m.ref, m.role) for m in r.members]
        if not any(t == 'w' and ref in self.selected_way_ids for t, ref, _ in members):
            return
        if tags.get('type') == 'restriction' or (tags.get('type') == 'multipolygon' and 'highway' in tags):
            self.relations.append({'osm_relation_id': r.id, 'tags': tags, 'members': members})


def frame(records, columns):
    return gpd.GeoDataFrame(records, columns=columns, geometry='geometry', crs=5179)


def content_hash(frame_, id_column):
    digest = hashlib.sha256()
    geometry_index = frame_.columns.get_loc('geometry')
    for row in frame_.sort_values(id_column).itertuples(index=False, name=None):
        values = list(row)
        geometry = values.pop(geometry_index)
        digest.update(json.dumps(values, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8'))
        digest.update(geometry.wkb)
    return digest.hexdigest()


def build_network(handler, core):
    projection = Transformer.from_crs(4326, 5179, always_xy=True)
    foot_relations = [r for r in handler.relations if any('foot' in k for k in r['tags'])
                      and r['tags'].get('type') == 'restriction']
    affected = {ref for r in foot_relations for typ, ref, _ in r['members'] if typ == 'w'}
    ways = sorted(handler.ways, key=lambda w: w['id'])
    require(len({w['id'] for w in ways}) == len(ways), 'OSM way ID 중복')
    projected = gpd.GeoSeries([w['geometry'] for w in ways], crs=4326).to_crs(5179)
    decisions, review, deferred, valid = [], [], [], []
    for w, geometry in zip(ways, projected):
        state, reason, directions = way_rule(w['tags'], w['id'])
        if w['id'] in affected:
            state, reason, directions = 'review', 'pedestrian_relation_requires_model', []
        if not geometry.is_valid or geometry.length <= 1e-8:
            state, reason, directions = 'exclude', 'invalid_or_zero_length_geometry', []
        w.update(state=state, reason=reason, directions=directions, geometry_m=geometry)
        decisions.append({'osm_way_id': w['id'], 'highway': w['tags'].get('highway', ''),
                          'decision': state, 'reason': reason, 'source_node_count': len(w['refs']),
                          'tags_json': tags_json(w['tags'])})
        if state in {'review', 'separate'}:
            review.append({'osm_way_id': w['id'], 'highway': w['tags'].get('highway', ''),
                           'name': w['tags'].get('name', ''), 'reason': reason, 'geometry': geometry})
        elif state in {'deferred', 'conditional'}:
            deferred.append({'osm_way_id': w['id'], 'highway': w['tags'].get('highway', ''),
                'name': w['tags'].get('name', ''), 'decision': state, 'reason': reason,
                'tags_json': tags_json(w['tags']), 'geometry': geometry})
        elif state == 'include':
            valid.append(w)
    usage = Counter(n for w in valid for n in w['refs'])
    junctions = {n for n, count in usage.items() if count > 1}
    junctions.update(handler.tagged_nodes)
    nodes, edges, issues = {}, [], []
    way_length, segmented_length = 0.0, 0.0
    for w in valid:
        refs, tags = w['refs'], w['tags']
        coords = list(w['geometry_m'].coords)
        way_length += w['geometry_m'].length
        cuts = sorted({0, len(refs) - 1} | {i for i, ref in enumerate(refs) if ref in junctions})
        for part_index, (a, b) in enumerate(zip(cuts, cuts[1:])):
            geometry = LineString(coords[a:b+1])
            length = geometry.length
            if length <= 1e-8:
                issues.append({'osm_way_id': w['id'], 'part_index': part_index,
                               'reason': 'zero_length_segment', 'u_osm': refs[a], 'v_osm': refs[b]})
                continue
            segment_id = f"w{w['id']}_p{part_index}"
            endpoint_ids = []
            for position, side in [(a, 'a'), (b, 'b')]:
                original = refs[position]
                ntags = handler.tagged_nodes.get(original, {}).get('tags', {})
                state, reason = node_rule(ntags)
                # 같은 원본 좌표라도 통행이 미확인/금지된 지점은 가지별 끝점으로 분리한다.
                # 좌표 스냅이나 osm_node_id로 재병합하면 이 제한을 우회하게 되므로 node_id로 연결한다.
                node_id = str(original) if state == 'include' else f'b{original}_{segment_id}_{side}'
                x, y = coords[position]
                record = {'node_id': node_id, 'osm_node_id': original, 'x': x, 'y': y,
                          'is_virtual': int(state != 'include'), 'passage_status': state,
                          'passage_reason': reason, 'geometry': Point(x, y)}
                if node_id in nodes:
                    require(nodes[node_id]['geometry'].distance(record['geometry']) < 1e-6,
                            f'같은 노드 ID의 좌표 불일치: {node_id}')
                else:
                    nodes[node_id] = record
                endpoint_ids.append(node_id)
            segmented_length += length
            for direction in w['directions']:
                u, v = endpoint_ids if direction == 1 else endpoint_ids[::-1]
                edges.append({
                    'edge_id': segment_id + ('_f' if direction == 1 else '_r'), 'segment_id': segment_id,
                    'osm_way_id': w['id'], 'u': u, 'v': v, 'direction': direction,
                    'name': tags.get('name', ''), 'highway': tags['highway'],
                    'length_m': length, 'cost_kind': 'distance', 'is_steps': int(tags['highway'] == 'steps'),
                    'foot': tags.get('foot', ''), 'access': tags.get('access', ''),
                    'bridge': tags.get('bridge', ''), 'tunnel': tags.get('tunnel', ''),
                    'layer': tags.get('layer', ''), 'level': tags.get('level', ''),
                    'geometry': geometry if direction == 1 else shapely.reverse(geometry),
                })
    require(abs(way_length - segmented_length) < 1e-4, '분할 전후 실제 선형 길이 불일치')
    edge_frame = gpd.GeoDataFrame(edges, crs=5179).sort_values('edge_id').reset_index(drop=True)
    node_frame = gpd.GeoDataFrame(list(nodes.values()), crs=5179).sort_values('node_id').reset_index(drop=True)
    graph = nx.Graph()
    graph.add_edges_from(zip(edge_frame.u, edge_frame.v))
    components = sorted(nx.connected_components(graph), key=lambda x: (-len(x), min(x)))
    component_ids = {node: index + 1 for index, component in enumerate(components) for node in component}
    node_frame['component_id'] = node_frame.node_id.map(component_ids).astype('int64')
    edge_frame['component_id'] = edge_frame.u.map(component_ids).astype('int64')
    node_frame['in_institution_region'] = shapely.covers(core, node_frame.geometry.values).astype('int8')
    del graph

    retained = set(usage)
    access_records = []
    for original, record in sorted(handler.tagged_nodes.items()):
        x, y = record['coords']
        x0, y0, x1, y1 = handler.bounds
        if not (original in retained or (x0 <= x <= x1 and y0 <= y <= y1)):
            continue
        tags = record['tags']
        state, reason = node_rule(tags)
        access_records.append({'osm_node_id': original, 'name': tags.get('name', ''),
                               'barrier': tags.get('barrier', ''), 'entrance': tags.get('entrance', ''),
                               'highway': tags.get('highway', ''), 'railway': tags.get('railway', ''),
                               'passage_status': state, 'passage_reason': reason,
                               'in_network': int(original in retained), 'tags_json': tags_json(tags),
                               'geometry': Point(*projection.transform(x, y))})
    access_frame = frame(access_records, ['osm_node_id', 'name', 'barrier', 'entrance', 'highway', 'railway',
                                        'passage_status', 'passage_reason', 'in_network', 'tags_json', 'geometry'])
    barrier_frame = gpd.GeoDataFrame(handler.barriers, crs=4326).to_crs(5179)
    review_frame = frame(review, ['osm_way_id', 'highway', 'name', 'reason', 'geometry'])
    deferred_frame = frame(deferred, ['osm_way_id', 'highway', 'name', 'decision', 'reason', 'tags_json', 'geometry'])
    # 별도 보도 표시가 있는 차도를 사람에게 전부 재확인시키지 않는다.
    # 같은 층의 주변 보행로가 길의 대부분을 덮고 실제 원본 노드 연결을 갖는지 검사한다.
    physical = edge_frame.drop_duplicates('segment_id').reset_index(drop=True)
    footpaths = physical[physical.highway.isin(['footway', 'path', 'pedestrian', 'steps', 'corridor'])].copy().reset_index(drop=True)
    tree = shapely.STRtree(footpaths.geometry.values)
    decision_lookup = {d['osm_way_id']: d for d in decisions}
    ways_lookup = {w['id']: w for w in ways}
    resolved, user_confirmed_sidewalks = set(), set()
    for row in review_frame[review_frame.reason == 'use_separately_mapped_sidewalk'].itertuples():
        tags = ways_lookup[row.osm_way_id]['tags']
        local = footpaths.iloc[tree.query(row.geometry.buffer(40), predicate='intersects')]
        local = local[(local.layer.replace('', '0') == tags.get('layer', '0')) &
                      (local.level.replace('', '0') == tags.get('level', '0'))]
        verified = False
        if len(local):
            coverage = row.geometry.intersection(shapely.union_all(local.geometry.values).buffer(30)).length / row.geometry.length
            local_graph = nx.Graph()
            local_graph.add_edges_from(zip(local.u, local.v))
            starts, ends = set(), set()
            first, last = Point(row.geometry.coords[0]), Point(row.geometry.coords[-1])
            for e in local.itertuples():
                for node, coordinate in [(e.u, e.geometry.coords[0]), (e.v, e.geometry.coords[-1])]:
                    p = Point(coordinate)
                    if p.distance(first) <= 50:
                        starts.add(node)
                    if p.distance(last) <= 50:
                        ends.add(node)
            verified = coverage >= .90 and any(starts & c and ends & c for c in nx.connected_components(local_graph))
        d = decision_lookup[row.osm_way_id]
        if row.osm_way_id in CONFIRMED_SEPARATE_SIDEWALKS:
            # 사용자 확인에 따른 별도 보도 이용 판정. 차도/자전거길 중심선은
            # 중복 보행선으로 넣지 않으며 원본 보도선을 사용한다.
            # 실제로 계산한 자동 검증 결과와 사용자 확인 근거를 구분한다.
            d.update(decision='exclude', reason='separate_sidewalk_user_confirmed')
            resolved.add(row.osm_way_id)
            user_confirmed_sidewalks.add(row.osm_way_id)
        elif verified:
            d.update(decision='exclude', reason='separate_sidewalk_verified')
            resolved.add(row.osm_way_id)
        else:
            d.update(decision='review', reason='separate_sidewalk_connection_unverified')
            review_frame.loc[review_frame.osm_way_id == row.osm_way_id, 'reason'] = d['reason']
    review_frame = review_frame[~review_frame.osm_way_id.isin(resolved)].reset_index(drop=True)
    sizes = Counter(edge_frame.component_id)
    component_table = [{'component_id': i+1, 'nodes': len(c), 'directed_edges': sizes[i+1]}
                       for i, c in enumerate(components)]
    return ({'nodes': node_frame, 'edges': edge_frame, 'access_points': access_frame,
             'barriers': barrier_frame, 'review_ways': review_frame, 'deferred_ways': deferred_frame},
            {'way_decisions': pd.DataFrame(decisions), 'segment_issues': pd.DataFrame(issues,
                columns=['osm_way_id', 'part_index', 'reason', 'u_osm', 'v_osm']),
             'components': pd.DataFrame(component_table)},
            {'selected_highway_ways': len(ways), 'included_ways': len(valid),
             'physical_segments': int(edge_frame.segment_id.nunique()),
             'physical_length_m': float(segmented_length), 'components': len(components),
             'largest_component_nodes': len(components[0]), 'unsupported_foot_relations': len(foot_relations),
             'separate_sidewalk_verified': len(resolved - user_confirmed_sidewalks),
             'separate_sidewalk_user_confirmed': len(user_confirmed_sidewalks)})


def organize_reviews(layers, boundary):
    """미확정 길을 위치별 확인 단위로 묶는다. 이 묶음은 보행망 연결이나 허용 판정이 아니다."""
    reviews = layers['review_ways'].copy().sort_values('osm_way_id').reset_index(drop=True)
    if reviews.empty:
        # 확인 완료 후에도 같은 필드와 공간 레이어 구조를 가진 0행 결과를 저장한다.
        reviews['priority'] = pd.Series(dtype='int64')
        for column in ['reason_ko', 'question', 'region', 'review_task', 'review_id']:
            reviews[column] = pd.Series(dtype='object')
        layers['review_ways'] = reviews
        layers['review_groups'] = frame([], ['review_id', 'priority', 'region', 'review_task',
            'name', 'reason_ko', 'question', 'way_count', 'length_m', 'osm_way_ids',
            'longitude', 'latitude', 'geometry']).astype({'priority': 'int64',
                'way_count': 'int64', 'length_m': 'float64', 'longitude': 'float64', 'latitude': 'float64'})
        return {'ways': 0, 'groups': 0, 'by_task': [], 'by_priority': []}
    regions = gpd.read_file(boundary, engine='pyogrio').to_crs(5179)
    regions = regions[regions.SIGUNGU_CD.astype(str).isin(REGIONS)]
    goyang = shapely.union_all(regions[regions.SIGUNGU_CD.astype(str).str.startswith('3110')].geometry.values)
    core = shapely.union_all(regions.geometry.values)
    reviews['priority'] = [1 if g.intersects(goyang) else 2 if g.intersects(core) else 3 for g in reviews.geometry]
    questions = {
        'highway_requires_foot_evidence': ('보행 허용 정보 부족', '자전거 전용인가요, 보행자도 이용하는 길인가요?'),
        'ambiguous_oneway_on_walkway': ('보행로 방향 불명확', '이 통로는 보행자가 양방향으로 이용할 수 있나요?'),
        'separate_sidewalk_connection_unverified': ('별도 보도 연결 검증', '코드로 보도 선과 교차점·출입 지점의 연결을 재검증할 항목입니다. 보도 존재 여부를 사용자에게 다시 묻는 항목이 아닙니다.'),
        'unknown_access_value': ('출입 조건 미상', '일반 보행자가 별도 허가 없이 통과할 수 있나요?'),
        'conditional_access': ('조건부 통행 해석 필요', '기록된 제한이 분석 기준 시점에도 적용되는지 확인해 주세요.'),
    }
    reviews['reason_ko'] = [questions.get(r, ('추가 확인 필요', '보행 허용과 연결 조건을 확인해 주세요.'))[0] for r in reviews.reason]
    reviews['question'] = [questions.get(r, ('추가 확인 필요', '보행 허용과 연결 조건을 확인해 주세요.'))[1] for r in reviews.reason]
    reviews.loc[(reviews.reason == 'highway_requires_foot_evidence') & (reviews.highway != 'cycleway'), 'question'] = '이 선이 일반 보행자가 이용하는 통행로인가요?'
    reviews['region'] = ['고양시' if p == 1 else '주변 12개 지역' if p == 2 else '추출 외곽' for p in reviews.priority]
    reviews['review_task'] = np.where(reviews.reason == 'separate_sidewalk_connection_unverified',
                                      'network_connection', 'user_check')
    tree = shapely.STRtree(reviews.geometry.values)
    graph = nx.Graph()
    graph.add_nodes_from(range(len(reviews)))
    # 60m 이내의 같은 확인 질문을 가진 길을 지도 확인 묶음으로 구성한다.
    # 층이나 방향 등의 판정은 원본 길별로 보존하며 가까움을 이유로 연결하지 않는다.
    for i, row in reviews.iterrows():
        for j in tree.query(row.geometry, predicate='dwithin', distance=60):
            if j > i and row.priority == reviews.at[j, 'priority'] and row.reason == reviews.at[j, 'reason'] and row.highway == reviews.at[j, 'highway']:
                graph.add_edge(i, int(j))
    groups = []
    for component in nx.connected_components(graph):
        indices = sorted(component)
        bounds = reviews.iloc[indices].total_bounds
        # 도시 전체가 한 묶음이 되지 않게 큰 군집은 2km 격자의 중심점 위치로 나눈다.
        buckets = {}
        for i in indices:
            c = reviews.at[i, 'geometry'].centroid
            key = (int(c.x//2000), int(c.y//2000)) if max(bounds[2]-bounds[0], bounds[3]-bounds[1]) > 3000 else (0, 0)
            buckets.setdefault(key, []).append(i)
        groups.extend(buckets.values())
    groups.sort(key=lambda idx: (int(reviews.iloc[idx].priority.min()), int(reviews.iloc[idx].osm_way_id.min())))
    group_records = []
    reviews['review_id'] = ''
    for idx in groups:
        anchor = int(reviews.iloc[idx].osm_way_id.min())
        review_id = REVIEW_IDS.get(anchor, f'W_OSM_{anchor}')
        reviews.loc[idx, 'review_id'] = review_id
        subset = reviews.iloc[idx]
        names = sorted(set(subset['name']) - {''})
        center = subset.geometry.iloc[0].interpolate(.5, normalized=True)
        lon, lat = Transformer.from_crs(5179, 4326, always_xy=True).transform(center.x, center.y)
        group_records.append({'review_id': review_id, 'priority': int(subset.priority.iloc[0]),
            'region': subset.region.iloc[0], 'review_task': subset.review_task.iloc[0],
            'name': ' / '.join(names) if names else '이름 없음',
            'reason_ko': subset.reason_ko.iloc[0], 'question': subset.question.iloc[0],
            'way_count': len(subset), 'length_m': float(subset.length.sum()),
            'osm_way_ids': ','.join(map(str, sorted(subset.osm_way_id))),
            'longitude': lon, 'latitude': lat,
            'geometry': shapely.MultiLineString([list(g.coords) for g in subset.geometry])})
    layers['review_ways'] = reviews
    layers['review_groups'] = frame(group_records, ['review_id', 'priority', 'region', 'review_task', 'name', 'reason_ko', 'question',
        'way_count', 'length_m', 'osm_way_ids', 'longitude', 'latitude', 'geometry'])
    require(layers['review_groups'].review_id.is_unique, '검토 묶음 ID 중복')
    return {'ways': len(reviews), 'groups': len(groups),
            'by_task': layers['review_groups'].groupby('review_task').agg(groups=('review_id', 'size'), ways=('way_count', 'sum')).reset_index().to_dict('records'),
            'by_priority': layers['review_groups'].groupby('priority').agg(groups=('review_id', 'size'), ways=('way_count', 'sum')).reset_index().to_dict('records')}


def validate(layers):
    nodes, edges = layers['nodes'], layers['edges']
    require(nodes.node_id.is_unique and edges.edge_id.is_unique, '노드/엣지 ID 중복')
    require(set(edges.u) | set(edges.v) == set(nodes.node_id), '엣지 끝점 누락/미사용 노드')
    for name in ['nodes', 'edges', 'access_points', 'barriers', 'review_ways', 'deferred_ways', 'review_groups']:
        current = layers[name]
        require(current.crs.to_epsg() == 5179 and current.geometry.notna().all(), f'{name}: 좌표계/빈 도형')
        require(current.is_valid.all() and (~current.is_empty).all(), f'{name}: 무효/빈 도형')
    require((edges.length_m > 0).all(), '길이 0/음수 엣지')
    require(np.allclose(edges.length_m, edges.length, atol=1e-7, rtol=0), '길이 불일치')
    require(edges.cost_kind.eq('distance').all() and 'walk_time_s' not in edges, '거리 비용 계약 불일치')
    lookup = nodes.set_index('node_id')
    start = shapely.get_point(edges.geometry.values, 0)
    end = shapely.get_point(edges.geometry.values, -1)
    require(np.max(shapely.distance(start, lookup.loc[edges.u].geometry.values)) < 1e-6, '시작 노드 좌표 불일치')
    require(np.max(shapely.distance(end, lookup.loc[edges.v].geometry.values)) < 1e-6, '끝 노드 좌표 불일치')
    # 제한된 원본 지점은 별개의 가지 끝점 ID만 가져야 한다.
    split = nodes.loc[nodes.is_virtual == 1]
    require(split.node_id.str.startswith('b').all(), '제한 노드 분리 실패')
    direction_counts = edges.groupby('segment_id', sort=False).size()
    require(direction_counts.isin([1, 2]).all(), '분할 구간 방향 중복')
    pairs = edges.loc[edges.segment_id.isin(direction_counts[direction_counts == 2].index)].sort_values(
        ['segment_id', 'direction'])
    a, b = pairs.iloc[::2], pairs.iloc[1::2]
    require(np.array_equal(a.u.to_numpy(), b.v.to_numpy()) and
            np.array_equal(a.v.to_numpy(), b.u.to_numpy()) and
            np.array_equal(a.direction.to_numpy(), -b.direction.to_numpy()), '양방향 끝점 불일치')
    log('끝점·방향 검증 완료. 저장 비용으로 그래프를 재구성하여 표본 경로를 확인합니다.')
    # 저장한 비용만으로 경로를 만들 수 있는지 독립적인 그래프 재구성으로 점검한다.
    graph = nx.DiGraph()
    for row in edges.itertuples():
        old = graph.get_edge_data(row.u, row.v)
        if old is None or row.length_m < old['weight']:
            graph.add_edge(row.u, row.v, weight=row.length_m)
    sample_results = []
    for source in sorted(graph)[::max(1, len(graph)//100)]:
        path, cost = [source], 0.0
        for _ in range(6):
            next_nodes = sorted(n for n in graph.successors(path[-1]) if n not in path)
            if not next_nodes:
                break
            nxt = next_nodes[0]
            cost += graph[path[-1]][nxt]['weight']
            path.append(nxt)
        if len(path) < 3:
            continue
        shortest = nx.shortest_path_length(graph, path[0], path[-1], weight='weight')
        lower_bound = lookup.loc[path[0]].geometry.distance(lookup.loc[path[-1]].geometry)
        require(lower_bound - 1e-6 <= shortest <= cost + 1e-6, '경로 비용 검산 실패')
        sample_results.append({'u': path[0], 'v': path[-1], 'distance_m': shortest})
        if len(sample_results) == 20:
            break
    require(len(sample_results) == 20, '경로 검증 표본 부족')
    return {'endpoint_integrity': True, 'length_and_cost_kind': True, 'unique_ids': True,
            'direction_pairs': True, 'barrier_node_separation': True, 'valid_geometries': True,
            'route_samples': sample_results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT/'data')
    parser.add_argument('--buffer-m', type=float, default=2000)
    args = parser.parse_args()
    require(args.buffer_m >= 480, 'v7 민감도 후보에 필요한 최소 480m 완충거리 미달')
    data = data_path(args.data_dir)
    source = find_one(data/'raw/OSM', '*.osm.pbf')
    boundary = find_one(data/'raw/경계', 'bnd_sigungu_00_2025_2Q.shp')
    inputs = [source] + [boundary.with_suffix(s) for s in ['.shp', '.shx', '.dbf', '.prj', '.cpg']]
    hashes = {p.relative_to(data).as_posix(): sha256(p) for p in inputs}
    bounds, extraction, core, areas = boundary_areas(boundary, args.buffer_m)
    handler = Extractor(bounds, extraction)
    log('OSM 원본 읽기 시작: 도로 선형과 원본 노드 참조를 함께 보존합니다.')
    # FileBuffer avoids libosmium's Windows narrow-path API; no external ASCII copy.
    buffer = source.read_bytes()
    reader = osmium.io.Reader(osmium.io.FileBuffer(buffer, 'pbf'))
    header = {key: reader.header().get(key) for key in ['generator', 'osmosis_replication_timestamp',
               'osmosis_replication_sequence_number', 'osmosis_replication_base_url']}
    reader.close()
    handler.apply_buffer(buffer, 'pbf', locations=True, idx='flex_mem')
    del buffer
    override_log = validate_walk(handler.ways)
    log(f'지역 highway way {len(handler.ways):,}개 읽음. 보행 조건과 연결 구조 구성 중.')
    layers, tables, summary = build_network(handler, core)
    review_summary = organize_reviews(layers, boundary)
    layers['extraction_area'] = areas
    log('도형·끝점·방향·분할 길이·표본 경로 검증 중.')
    checks = validate(layers)
    ids = {'nodes': 'node_id', 'edges': 'edge_id', 'access_points': 'osm_node_id',
           'barriers': 'osm_way_id', 'review_ways': 'osm_way_id', 'extraction_area': 'area_id',
           'deferred_ways': 'osm_way_id', 'review_groups': 'review_id'}
    layer_hashes = {}
    for name, frame_ in layers.items():
        log(f'{name} {len(frame_):,}건 내용 해시 계산')
        layer_hashes[name] = content_hash(frame_, ids[name])
    counts = {name: len(frame_) for name, frame_ in layers.items()}
    decisions = tables['way_decisions']
    report = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'header': header,
              'parameters': {'buffer_m': args.buffer_m, 'cost_kind': 'distance', 'scenario_walk_speeds_mps': [0.6, 0.7, 0.8], 'continuous_walk_limit_s': 600, 'total_walk_limit_s': None, 'bbox_4326': list(bounds)},
              'area_km2': dict(zip(areas.area_id, areas.area_km2)),
              'source_counts': dict(handler.counts), 'counts': counts, 'summary': summary,
              'review_summary': review_summary,
              'way_decisions': decisions.groupby(['decision', 'reason']).size().reset_index(name='count').to_dict('records'),
              'highway_counts': dict(handler.tag_counts),
              'included_highway_counts': decisions.loc[decisions.decision == 'include'].highway.value_counts().to_dict(),
              'access_point_decisions': layers['access_points'].groupby(['passage_status', 'passage_reason']).size().reset_index(name='count').to_dict('records'),
              'node_statistics': {'virtual_nodes': int(layers['nodes'].is_virtual.sum()),
                 'split_osm_nodes': int(layers['nodes'].loc[layers['nodes'].is_virtual == 1].osm_node_id.nunique()),
                 'outside_institution_region': int((layers['nodes'].in_institution_region == 0).sum())},
              'input_sha256': hashes, 'code_sha256': sha256(Path(__file__)), 'content_sha256': layer_hashes,
              'checks': checks, 'environment': {m: importlib.metadata.version(m) for m in
                  ['osmium', 'geopandas', 'shapely', 'pyogrio', 'pandas', 'networkx', 'pyproj']}}
    output = data/'processed/osm_walk_network.gpkg'
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name('osm_walk_network.writing.gpkg')
    require(not temporary.exists(), '이전 임시 출력이 존재함: 내용 확인 후 정리 필요')
    for name, frame_ in layers.items():
        log(f'{name} 저장 중')
        pyogrio.write_dataframe(frame_, temporary, layer=name, driver='GPKG',
                                geometry_type={'review_ways': 'LineString', 'review_groups': 'MultiLineString'}.get(name),
                                layer_options={'SPATIAL_INDEX': 'YES'})
    with sqlite3.connect(temporary) as connection:
        for name, table in tables.items():
            table.to_sql(name, connection, index=False, if_exists='fail')
        relations = [{'osm_relation_id': r['osm_relation_id'],
                      'tags_json': json.dumps(r['tags'], ensure_ascii=False, sort_keys=True),
                      'members_json': json.dumps(r['members'])} for r in handler.relations]
        pd.DataFrame(relations, columns=['osm_relation_id', 'tags_json', 'members_json']).to_sql(
            'source_relations', connection, index=False, if_exists='fail')
        pd.DataFrame([{'key': k, 'value_json': json.dumps(v, ensure_ascii=False)} for k, v in report.items()]).to_sql(
            'processing_metadata', connection, index=False, if_exists='fail')
        require(connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'GeoPackage DB 오류')
    connection.close()  # sqlite3의 with는 트랜잭션만 종료하므로 Windows 파일 잠금을 별도로 해제한다.
    log('GeoPackage 저장 재읽기 및 내용 해시 검증 중.')
    for name, expected in layer_hashes.items():
        log(f'{name} 재읽기 검증 중')
        saved = gpd.read_file(temporary, layer=name, engine='pyogrio')
        require(len(saved) == counts[name] and saved.crs.to_epsg() == 5179, f'{name}: 저장 구조 불일치')
        require(content_hash(saved, ids[name]) == expected, f'{name}: 저장 내용 불일치')
    require(all(sha256(p) == hashes[p.relative_to(data).as_posix()] for p in inputs), '원본 파일 변경')
    report['checks']['saved_layer_hashes'] = True
    report['checks']['input_unchanged'] = True
    for item in override_log: item['status'] = 'applied'
    report['override_application_log'] = override_log
    with sqlite3.connect(temporary) as connection:
        connection.execute('UPDATE processing_metadata SET value_json=? WHERE key=?',
                           (json.dumps(report['checks'], ensure_ascii=False), 'checks'))
    connection.close()
    temporary.replace(output)
    save_report('osm_walk_network', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
