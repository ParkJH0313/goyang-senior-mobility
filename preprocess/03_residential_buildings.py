# -*- coding: utf-8 -*-
"""도로명주소 전자지도(2025-03)로 고양시 주거 건물과 보조 위치를 전처리한다.

실행: python "preprocess/03_residential_buildings.py"
선택: --output 별도결과.gpkg
입력: data/raw의 도로명주소 전자지도 및 센서스용 고양시 3개 구 경계.
출력: data/processed/residential_buildings.gpkg. MD·이미지·격자 출발점은 생성하지 않는다.
네트워크, API, 다른 processed, 검증용 보관 파일에 의존하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.preprocessing_common import (ROOT, initialize, internal, data_path, save_report, approved,
    building_constants, validate_buildings, building_application_log, walk_constants, validate_walk)
initialize()
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from uuid import uuid4
import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from pyproj import CRS as PyCRS
import shapely
from shapely.geometry import MultiPolygon

CRS = 'EPSG:5179'
SOURCE = 'address_map'
REFERENCE = '2025-03'
RAW_FOLDER = '도로명주소_전자지도_고양시_202503'
RESIDENTIAL = {'01000': '단독주택', '01001': '단독주택', '01002': '다중주택',
               '01003': '다가구주택', '02000': '공동주택', '02001': '아파트',
               '02002': '연립주택', '02003': '다세대주택', '10202': '오피스텔(주거가능)'}
USE_NAMES = {**RESIDENTIAL, '10202': '오피스텔', '01004': '공관', '02007': '기숙사',
             '10299': '기타일반업무시설', '10204': '사무소', '04402': '사무소',
             '04999': '기타제2종근린생활시설', '03999': '기타제1종근린생활시설'}
# 상세 동명이 지목하는 비주거 시설. 단지 이름에는 이 규칙을 적용하지 않는다.
NONRES_DETAIL = re.compile(r'상가|근린생활|관리동|관리사무소|경비|주차|기계실|전기실|'
                          r'변전|펌프|화장실|창고|차고|부속사|부대시설|복리시설|'
                          r'보육시설|판매시설|사무동|사무소|업무편의시설|미디어센터')
NONRES_OWN = re.compile(r'상가동|관리사무소|화장실|경로당|노인정|모델하우스|견본주택|'
                       r'실습실|식품가공실|^부속사$|^차고$|^관리동$|^근린생활시설$')
CONTEXT_CONFLICT = re.compile(r'교회|성당|사찰|유치원|어린이집|학교|공장|주유소|'
                              r'골프|컨트리클럽|차고지|물류|창고|복지타운|요양|병원|공원')
PUBLIC_OFFICE = re.compile(r'영업소|세무서|은행|보험|법조|사업본부|공원|관리사무소|판매시설')
RESIDENCE_WORD = re.compile(r'아파트|연립|다세대|다가구|주택|빌라|오피스텔')
# 2026-10-14 사용자 확정: 확인한 오피스텔 9개의 포함 판정을 유지한다.
# 새 원자료의 SIG_CD_BUL_MAN_NO에 고정하며 이전 결과·별도 판정 파일은 읽지 않는다.
# 2026-10-14 사용자 확인: 제2자유로 33은 군부대 부지로 분석에서 제외한다.
# 다른 건물군에는 이 개별 판정을 확대 적용하지 않는다.
# 2026-10-14 면적 검토 37개에 대한 사용자 확정. 식별번호를 원자료 ID에 고정한다.
# 작은 도형 24개는 원자료 단독주택 용도를 근거로 포함한다. 다른 후보에는 확대 적용하지 않는다.
# 검토 HTML은 읽지 않고, 확정 판정은 overrides의 CSV에서 원본 ID로 읽는다.
# 2026-10-14 사용자 확정: 고령인구가 있으나 선정 주거가 없던 4개 격자의
# 아래 6개 후보만 포함한다. 인구가 있는 격자의 모든 건물을 포함하는 규칙이 아니다.
# 인구 대조는 별도 검증으로 수행했으며 재실행에서는 이 원자료 ID 판정만 사용한다.
# 2026-10-14 남은 후보 개별 대조 결과. 원자료 ID에 판정을 고정한다.
# 카카오 장소·주소·대상/주건물 도형 및 원자료 명칭을 대조한 근거는 통합 MD에 보관.
# API 검색이나 인구 자료를 재실행 입력으로 요구하지 않는다. 원자료 용도는 보존한다.
# 2026-10-14 사용자 최종 지시: 검색 후 남은 미확정 후보 233개를 모두 분석 제외.
# 실제 비주거 확인으로 바꾸어 기록하지 않는다. 당시 후보 ID에만 적용한다.
# 기존 주거 포함 판정은 유지하며 재실행 시 검토표·다른 processed를 읽지 않는다.
# 남은 종속건물 후보에 적용하는 사용자 확정 제외 기준(2026-10-14).
# 동일 SIG_CD_EQB_MAN_SN의 주건물(M)을 대조한다. 이미 개별 확정한 37건은 우선한다.
EXCLUDED_MAIN_USE_CODES = {
    'nonresidential_main_factory': {'13000', '13100', '13200', '04005'},
    'nonresidential_main_warehouse': {'14000', '14001', '14002', '14999'},
    'nonresidential_main_vehicle': {'15001', '16000', '16001', '16002', '16003',
                                  '16004', '16005', '16006', '16007', '16008',
                                  '16009', '16999'},
}
_confirmed = building_constants()
CONFIRMED_LARGE_RESIDENCES = _confirmed.get('CONFIRMED_LARGE_RESIDENCES', {})
CONFIRMED_OFFICETELS = _confirmed.get('CONFIRMED_OFFICETELS', {})
CONFIRMED_POPULATION_REVIEW_RESIDENCES = _confirmed.get('CONFIRMED_POPULATION_REVIEW_RESIDENCES', {})
CONFIRMED_SMALL_RESIDENCES = _confirmed.get('CONFIRMED_SMALL_RESIDENCES', {})
EXCLUDED_BUILDING_GROUPS = _confirmed.get('EXCLUDED_BUILDING_GROUPS', {})
EXCLUDED_LARGE_BUILDINGS = _confirmed.get('EXCLUDED_LARGE_BUILDINGS', {})
REVIEWED_CANDIDATE_DECISIONS = _confirmed.get('REVIEWED_CANDIDATE_DECISIONS', {})
USER_EXCLUDED_REMAINING_CANDIDATES = _confirmed.get('USER_EXCLUDED_REMAINING_CANDIDATES', {})

FIELDS = ['building_id', 'building_source', 'source_id', 'link_id', 'name',
          'residential_type', 'use_code', 'use_name', 'legal_dong_code',
          'reference_date', 'decision_reason', 'quality_note', 'geometry_status',
          'source_parts', 'full_area_m2', 'analysis_area_m2',
          'building_group_id', 'building_role', 'road_address',
          'representative_x', 'representative_y', 'entrance_id', 'entrance_scope',
          'entrance_x', 'entrance_y', 'geometry']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return '' if pd.isna(value) else str(value).strip()


def names(row):
    return ' / '.join(dict.fromkeys(v for v in
        [text(row.BULD_NM), text(row.BULD_NM_DC), text(row.POS_BUL_NM)] if v))


def key(sig, number):
    return f'{sig}_{int(number)}' if pd.notna(number) and int(number) > 0 else ''


def polygons(geom):
    if geom is None or geom.is_empty:
        return MultiPolygon()
    if geom.geom_type == 'Polygon':
        return MultiPolygon([geom])
    if geom.geom_type == 'MultiPolygon':
        return geom
    pieces = []
    for part in getattr(geom, 'geoms', []):
        pieces.extend(polygons(part).geoms)
    return MultiPolygon(pieces)


def repair(frame, label, audit):
    frame = frame.copy()
    frame['geometry_status'] = 'valid'
    for i in frame.index[~frame.geometry.is_valid]:
        before = frame.at[i, 'geometry']
        after = shapely.normalize(polygons(shapely.make_valid(before)))
        frame.at[i, 'geometry'] = after
        frame.at[i, 'geometry_status'] = 'repaired'
        audit.append({'stage': label, 'source_id': frame.at[i, '_id'],
                      'action': 'repaired', 'reason': shapely.is_valid_reason(before),
                      'area_before_m2': before.area, 'area_after_m2': after.area})
    require(frame.geometry.notna().all() and (~frame.geometry.is_empty).all(), label+': 빈 도형')
    require(frame.geometry.is_valid.all(), label+': 복구 후 도형 오류')
    frame.geometry = frame.geometry.map(lambda g: shapely.normalize(polygons(g)))
    return frame


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def layer_hash(frame, order):
    result = hashlib.sha256()
    for _, row in frame.sort_values(order).iterrows():
        attrs = {k: (None if pd.isna(v) else v.item() if isinstance(v, np.generic) else v)
                 for k, v in row.items() if k != 'geometry'}
        result.update(json.dumps(attrs, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8'))
        result.update(shapely.to_wkb(shapely.normalize(row.geometry)))
    return result.hexdigest()


def read_inputs(data, audit):
    base = data/'raw'/RAW_FOLDER
    require(base.is_dir(), f'원자료 폴더 없음: {base}')
    source_crs = PyCRS.from_wkt((base/'GRS80_UTMK.prj').read_text())
    frames, files = {}, [base/'GRS80_UTMK.prj']
    for label in ['BULD', 'ENTRC', 'EQB']:
        path = base/'41280'/f'TL_SPBD_{label}.shp'
        frame = pyogrio.read_dataframe(path, encoding='CP949')
        require(frame.crs is None or PyCRS(frame.crs).equals(source_crs), '예상하지 못한 좌표계')
        frame = frame.set_crs(source_crs, allow_override=True).to_crs(CRS)
        idcol = {'BULD': 'BUL_MAN_NO', 'ENTRC': 'ENT_MAN_NO', 'EQB': 'EQB_MAN_SN'}[label]
        frame['_id'] = [key(s, n) for s, n in zip(frame.SIG_CD, frame[idcol])]
        require(frame._id.ne('').all() and frame._id.is_unique, label+': ID 누락 또는 중복')
        frames[label] = frame if label == 'ENTRC' else repair(frame, label, audit)
        if label == 'ENTRC':
            require(frame.geometry.notna().all() and frame.is_valid.all() and (~frame.is_empty).all(), '출입구 도형 오류')
        files.extend(path.with_suffix(ext) for ext in ['.shp', '.shx', '.dbf'])
    for label in ['TL_SPRD_MANAGE', 'TL_SCCO_SIG']:
        path = base/'41280'/(label+'.shp')
        frames[label] = pyogrio.read_dataframe(path, encoding='CP949', read_geometry=False)
        files.append(path.with_suffix('.dbf'))
    borders = []
    for code in ['31101', '31103', '31104']:
        found = list((data/'raw'/'경계').rglob(f'bnd_sigungu_{code}_2025_2Q.shp'))
        require(len(found) == 1, f'고양시 구 경계 {code} 파일 수 오류')
        f = pyogrio.read_dataframe(found[0]).to_crs(CRS)
        require(len(f) == 1 and f.is_valid.all(), '구 경계 오류')
        borders.append(f.geometry.iloc[0])
        files.extend(found[0].with_suffix(ext) for ext in ['.shp', '.shx', '.dbf', '.prj'])
    return frames, shapely.union_all(borders), files


def main_building_exclusions(buildings):
    """주건물의 코드·학교 명칭으로 제외 대상 건물군을 식별한다."""
    result = {}
    mains = buildings.loc[buildings.BUL_DPN_SE.eq('M') & buildings['_group'].ne('')]
    for group, rows in mains.groupby('_group'):
        uses = set(rows.BDTYP_CD.map(text))
        for reason, codes in EXCLUDED_MAIN_USE_CODES.items():
            if uses & codes:
                result[group] = reason
                break
        else:
            # 081xx 학교 코드 외에도 '한국경진학교'(08999)처럼 명칭이 명확한 학교 포함.
            if any(code.startswith('081') for code in uses) or any('학교' in names(r) for _, r in rows.iterrows()):
                result[group] = 'school_main_building'
    return result


def classify(row, group_has_residential_main, excluded_main_groups):
    use = text(row.BDTYP_CD)
    own, detail, group_name = text(row.BULD_NM), text(row.BULD_NM_DC), text(row.POS_BUL_NM)
    all_name = names(row)
    candidate = use in RESIDENTIAL or '오피스텔' in all_name or use in {'10299', '01004', '02007'}
    if not candidate:
        return 'excluded', 'nonresidential_use', ''
    if row['_group'] in EXCLUDED_BUILDING_GROUPS:
        return 'excluded', 'user_excluded_military_site', ''
    if row['_id'] in USER_EXCLUDED_REMAINING_CANDIDATES:
        return 'excluded', 'user_excluded_remaining_uncertain', ''
    if row['_id'] in REVIEWED_CANDIDATE_DECISIONS:
        action, reason = REVIEWED_CANDIDATE_DECISIONS[row['_id']]
        typ = '아파트' if reason == 'reviewed_mixed_residential_building' else RESIDENTIAL.get(use, '')
        return action, reason, typ if action == 'accepted' else ''
    if text(row.BULD_SE_CD) != '0':
        return 'review', 'not_above_ground', ''
    if NONRES_DETAIL.search(detail) or NONRES_OWN.search(own):
        return 'excluded', 'explicit_nonresidential_building_name', ''
    # 사용자 확정(2026-10-14): 공관·기숙사는 일반 주거 건물 분석에서 제외한다.
    # 오피스텔 코드라도 상세 동명이 기숙사이면 이 제외 조건을 우선한다.
    if use in {'01004', '02007'} or '기숙사' in detail:
        return 'excluded', 'collective_or_official_residence', ''
    if row['_id'] in CONFIRMED_OFFICETELS:
        return 'accepted', 'user_confirmed_officetel', '오피스텔(주거가능)'
    if '오피스텔' in all_name:
        return 'accepted', 'officetel_name', '오피스텔(주거가능)'
    if use == '10299':
        if PUBLIC_OFFICE.search(all_name):
            return 'excluded', 'explicit_nonresidential_office', ''
        return 'review', 'unspecified_business_use', ''
    if use in RESIDENTIAL:
        if CONTEXT_CONFLICT.search(own) and not RESIDENCE_WORD.search(own):
            return 'excluded', 'nonresidential_building_name_priority', ''
        if CONTEXT_CONFLICT.search(group_name) and not RESIDENCE_WORD.search(group_name) and not detail:
            return 'excluded', 'nonresidential_facility_name_priority', ''
        if text(row.BUL_DPN_SE) == 'S' and row['_group'] and not group_has_residential_main.get(row['_group'], False):
            if row['_id'] in EXCLUDED_LARGE_BUILDINGS:
                return 'excluded', 'user_excluded_large_building', ''
            if row['_id'] in CONFIRMED_SMALL_RESIDENCES:
                return 'accepted', 'user_confirmed_small_residential_use', RESIDENTIAL[use]
            if row['_id'] in CONFIRMED_LARGE_RESIDENCES:
                return 'accepted', 'user_confirmed_large_residence', RESIDENTIAL[use]
            if row['_id'] in CONFIRMED_POPULATION_REVIEW_RESIDENCES:
                return 'accepted', 'user_confirmed_population_review_residence', RESIDENTIAL[use]
            if row['_group'] in excluded_main_groups:
                return 'excluded', excluded_main_groups[row['_group']], ''
            return 'review', 'residential_subordinate_in_nonresidential_group', ''
        return 'accepted', 'residential_use_code', RESIDENTIAL[use]
    return 'review', 'name_code_conflict', ''


def make_output(frames, city, audit):
    b, e, groups = frames['BULD'].copy(), frames['ENTRC'].copy(), frames['EQB']
    b['_group'] = [key(s, n) for s, n in zip(b.SIG_CD, b.EQB_MAN_SN)]
    approved_rows = validate_buildings(b, names)
    require(set(EXCLUDED_BUILDING_GROUPS) <= set(b['_group']), '사용자 제외 건물군이 원자료에 없음')
    e['_group'] = [key(s, n) for s, n in zip(e.SIG_CD, e.EQB_MAN_SN)]
    e['_building'] = [key(s, n) for s, n in zip(e.SIG_CD, e.BUL_MAN_NO)]
    orphan_groups = set(b._group)-{''}-set(groups._id)
    for _, orphan in b.loc[b._group.isin(orphan_groups)].iterrows():
        audit.append({'stage': 'BULD', 'source_id': orphan['_id'], 'action': 'noted',
                      'reason': 'missing_group_polygon:'+orphan['_group'],
                      'area_before_m2': None, 'area_after_m2': None})
    require(set(e._group)-{''} <= set(groups._id), '출입구의 건물군 참조 오류')
    require(set(e._building)-{''} <= set(b._id), '출입구의 건물 참조 오류')
    entrances = e.loc[e.ENTRC_SE.eq('RM')].copy()
    direct = {k: list(v.index) for k, v in entrances.loc[entrances._building.ne('')].groupby('_building')}
    shared = {k: list(v.index) for k, v in entrances.loc[entrances._group.ne('')].groupby('_group')}
    group_geometry = groups.set_index('_id').geometry.to_dict()
    main = b.loc[b.BUL_DPN_SE.eq('M') & b.BDTYP_CD.isin(RESIDENTIAL)]
    has_res_main = {v: True for v in main._group if v}
    excluded_main_groups = main_building_exclusions(b)
    road_names = {}
    for (sig, rn), sub in frames['TL_SPRD_MANAGE'].groupby(['SIG_CD', 'RN_CD']):
        vals = sorted(set(sub.RN.dropna()))
        require(len(vals) == 1, '도로명 코드에 여러 도로명')
        road_names[(sig, rn)] = vals[0]
    sig_names = frames['TL_SCCO_SIG'].set_index('SIG_CD').SIG_KOR_NM.to_dict()
    counts, entrance_counts = Counter(), Counter()
    full_rows, part_rows, review_rows, decision_rows = [], [], [], []
    accepted_entrances = set()
    duplicates = pd.Series(shapely.to_wkb(shapely.normalize(b.geometry))).duplicated(keep=False)
    for i in b.index[duplicates]:
        audit.append({'stage': 'BULD', 'source_id': b.at[i, '_id'], 'action': 'noted',
                      'reason': 'same_geometry_different_id', 'area_before_m2': None, 'area_after_m2': None})
    for _, row in b.sort_values('_id').iterrows():
        action, reason, typ = classify(row, has_res_main, excluded_main_groups)
        geom = shapely.normalize(polygons(row.geometry))
        effective = shapely.normalize(polygons(geom.intersection(city)))
        if effective.is_empty or effective.area <= 0:
            action, reason, typ = 'excluded', 'outside_goyang', ''
        counts[action+':'+reason] += 1
        display_name = names(row)
        address = road_names.get((text(row.RDS_SIG_CD), text(row.RN_CD)), '')
        if address:
            address = f"{sig_names.get(row.SIG_CD, row.SIG_CD)} {address} {int(row.BULD_MNNM)}"
            if row.BULD_SLNO:
                address += f'-{int(row.BULD_SLNO)}'
        decision_rows.append({'source_id': row['_id'], 'use_code': row.BDTYP_CD,
                              'name': display_name, 'action': action, 'reason': reason})
        if action == 'excluded':
            continue
        # 시내 건물 도형 내부점이다. 격자 대표점이나 출입구를 뜻하지 않는다.
        rep = effective.representative_point()
        options, scope = direct.get(row['_id'], []), 'building'
        if not options:
            options, scope = shared.get(row['_group'], []), 'building_group'
        require(len(options) <= 1, f"주출입구 복수: {row['_id']}; 임의 선택하지 않음")
        entry = entrances.loc[options[0]] if options else None
        scope = scope if entry is not None else 'missing'
        note = []
        if typ == '오피스텔(주거가능)':
            note.append('주거 가능성 기준; 실제 거주 여부·층별 주거비율 미확인')
        if reason == 'user_confirmed_officetel':
            note.append('사용자 포함 판정 확정(2026-10-14): '+CONFIRMED_OFFICETELS[row['_id']])
        if reason == 'user_confirmed_small_residential_use':
            note.append('사용자 포함 확정(2026-10-14): '+CONFIRMED_SMALL_RESIDENCES[row['_id']]+
                        '; 원자료 단독주택 용도 우선; 작은 면적만으로 제외하지 않음')
        if reason == 'user_confirmed_large_residence':
            note.append('사용자 개별 포함 확정(2026-10-14): '+CONFIRMED_LARGE_RESIDENCES[row['_id']])
        if reason == 'user_confirmed_population_review_residence':
            note.append('사용자 포함 확정(2026-10-14): '+CONFIRMED_POPULATION_REVIEW_RESIDENCES[row['_id']]+
                        '; 고령인구가 있으나 선정 주거가 없던 격자의 후보; 해당 6개만 적용; '
                        '특정 건물의 고령자 거주 확인이나 인구 배정은 아님')
        if reason == 'reviewed_mixed_residential_building':
            note.append('CIC 창조혁신캠퍼스 성사; 사업주체 공고 25층·임대주택 118세대 및 주소 대조; '
                        '주거·업무 복합건물의 원도형 평면 면적 사용; 주거층 비율·실제 입주 인구 미산정')
        if reason == 'reviewed_residential_own_name':
            note.append('명칭 대조 포함(2026-10-14): 주택동 명칭과 원자료 다가구주택 용도 일치')
        if row.BUL_DPN_SE == 'S':
            note.append('종속건물; 종속 여부만으로 제외하지 않고 용도·명칭·소속 대조')
        if scope == 'building_group':
            note.append('건물군 공용 주출입구; 개별 동 현관 또는 필수 보행 경유지로 확정하지 않음')
        if scope == 'missing':
            note.append('원자료 연결 주출입구 없음; 임의 좌표 생성 없음')
        if row['_group'] in orphan_groups:
            note.append('건물군 번호는 있으나 해당 EQB 도형 없음')
        if entry is not None:
            target_geom = geom if scope == 'building' else group_geometry[row['_group']]
            if entry.geometry.distance(target_geom) > 2:
                note.append('출입구가 연결 대상 도형에서 2m 초과 이격; 원좌표 유지')
            if not city.covers(entry.geometry):
                note.append('출입구가 센서스 고양시 경계 밖; 원좌표 유지')
        record = {'building_id': 'A_'+row['_id'], 'building_source': SOURCE,
                  'source_id': row['_id'], 'link_id': text(row.BD_MGT_SN), 'name': display_name,
                  'residential_type': typ, 'use_code': text(row.BDTYP_CD),
                  'use_name': USE_NAMES.get(text(row.BDTYP_CD), ''),
                  'legal_dong_code': text(row.SIG_CD)+text(row.EMD_CD).zfill(3)+text(row.LI_CD).zfill(2),
                  'reference_date': REFERENCE, 'decision_reason': reason, 'quality_note': '; '.join(note),
                  'geometry_status': row.geometry_status, 'source_parts': 1,
                  'full_area_m2': geom.area, 'analysis_area_m2': effective.area,
                  'building_group_id': row['_group'], 'building_role': text(row.BUL_DPN_SE),
                  'road_address': address, 'representative_x': rep.x, 'representative_y': rep.y,
                  'entrance_id': entry['_id'] if entry is not None else '', 'entrance_scope': scope,
                  'entrance_x': entry.geometry.x if entry is not None else None,
                  'entrance_y': entry.geometry.y if entry is not None else None, 'geometry': geom}
        if action == 'review':
            record.update({'review_reason': reason, 'raw_building_name': text(row.BULD_NM),
                           'raw_detail_name': text(row.BULD_NM_DC), 'raw_group_name': text(row.POS_BUL_NM)})
            review_rows.append(record)
            continue
        full_rows.append(record)
        part_rows.append({**record, 'geometry': effective})
        entrance_counts[scope] += 1
        if entry is not None:
            accepted_entrances.add(entry['_id'])
    full = gpd.GeoDataFrame(full_rows, columns=FIELDS, crs=CRS)
    parts = gpd.GeoDataFrame(part_rows, columns=FIELDS, crs=CRS)
    union = shapely.normalize(polygons(shapely.union_all(parts.geometry)))
    coverage = gpd.GeoDataFrame([{'building_source': SOURCE, 'area_m2': union.area,
        'overlap_removed_m2': parts.area.sum()-union.area, 'geometry': union}], crs=CRS)
    points = full[['building_id', 'name', 'building_group_id', 'entrance_id', 'entrance_scope']].copy()
    points['geometry'] = gpd.points_from_xy(full.representative_x, full.representative_y, crs=CRS)
    points = gpd.GeoDataFrame(points, crs=CRS)
    entrances_out = entrances.loc[entrances._id.isin(accepted_entrances)].copy()
    entrances_out = entrances_out.rename(columns={'_id': 'entrance_id', '_group': 'building_group_id',
        '_building': 'source_building_id', 'ENTRC_SE': 'entrance_type'})
    entrances_out['linked_buildings'] = entrances_out.entrance_id.map(full.entrance_id.value_counts()).astype(int)
    entrances_out = entrances_out[['entrance_id', 'entrance_type', 'source_building_id',
        'building_group_id', 'linked_buildings', 'geometry']].sort_values('entrance_id')
    layers = {'residential_buildings': full, 'residential_parts': parts, 'residential_coverage': coverage,
              'building_representative_points': points, 'building_entrances': entrances_out}
    if review_rows:
        layers['review_buildings'] = gpd.GeoDataFrame(review_rows, crs=CRS)
    else:
        empty_review = full.iloc[:0].copy()
        for column in ['review_reason', 'raw_building_name', 'raw_detail_name', 'raw_group_name']:
            empty_review[column] = pd.Series(dtype='object')
        layers['review_buildings'] = empty_review
    summary = {'input_buildings': len(b), 'input_entrances': len(e), 'input_groups': len(groups),
        'decisions': dict(sorted(counts.items())), 'selected': len(full), 'pending': len(review_rows),
        'selected_types': full.residential_type.value_counts().to_dict(),
        'selected_roles': full.building_role.value_counts().to_dict(),
        'entrance_assignment': dict(entrance_counts), 'unique_selected_entrances': len(entrances_out),
        'full_sum_m2': float(full.area.sum()), 'analysis_sum_m2': float(parts.area.sum()),
        'coverage_m2': union.area, 'overlap_removed_m2': float(parts.area.sum()-union.area),
        'geometry_repairs': dict(Counter(r['stage'] for r in audit if r['action'] == 'repaired')),
        'same_geometry_records': int(duplicates.sum()),
        'missing_entrance_buildings': full.loc[full.entrance_scope.eq('missing'), 'building_id'].tolist()}
    summary['user_excluded_building_groups'] = EXCLUDED_BUILDING_GROUPS
    summary['user_reviewed_area_candidates'] = {
        'accepted_small': CONFIRMED_SMALL_RESIDENCES,
        'accepted_large': CONFIRMED_LARGE_RESIDENCES,
        'excluded_large': EXCLUDED_LARGE_BUILDINGS}
    summary['user_confirmed_population_review_residences'] = CONFIRMED_POPULATION_REVIEW_RESIDENCES
    summary['reviewed_candidate_decisions'] = REVIEWED_CANDIDATE_DECISIONS
    summary['user_excluded_remaining_candidates'] = USER_EXCLUDED_REMAINING_CANDIDATES
    if 'review_buildings' in layers:
        require(not layers['review_buildings'].building_group_id.isin(excluded_main_groups).any(),
                '확정한 비주거·학교 주건물의 종속건물이 검토에 남음')
    return layers, pd.DataFrame(decision_rows), summary


def validate(layers, decisions, city):
    f, p, c = (layers[k] for k in ['residential_buildings', 'residential_parts', 'residential_coverage'])
    require(f.building_id.is_unique and f.source_id.is_unique, '건물 ID 중복')
    require(f.building_id.tolist() == p.building_id.tolist(), '전체·분석 도형 ID 불일치')
    require(len(decisions) == decisions.source_id.nunique(), '전수 판정 누락 또는 중복')
    require(set(f.source_id) == set(decisions.loc[decisions.action.eq('accepted'), 'source_id']), '선정 판정 불일치')
    require(not f.building_group_id.isin(EXCLUDED_BUILDING_GROUPS).any(), '사용자 제외 건물군이 선정됨')
    require(set(CONFIRMED_OFFICETELS) <= set(f.source_id), '사용자 확정 오피스텔 누락')
    confirmed_sets = [set(CONFIRMED_SMALL_RESIDENCES), set(CONFIRMED_LARGE_RESIDENCES),
                      set(EXCLUDED_LARGE_BUILDINGS), set(CONFIRMED_POPULATION_REVIEW_RESIDENCES)]
    require(sum(map(len, confirmed_sets)) == len(set.union(*confirmed_sets)), '사용자 검토 확정 ID 중복')
    for ids, action, reason in [
        (CONFIRMED_SMALL_RESIDENCES, 'accepted', 'user_confirmed_small_residential_use'),
        (CONFIRMED_LARGE_RESIDENCES, 'accepted', 'user_confirmed_large_residence'),
        (EXCLUDED_LARGE_BUILDINGS, 'excluded', 'user_excluded_large_building'),
        (CONFIRMED_POPULATION_REVIEW_RESIDENCES, 'accepted', 'user_confirmed_population_review_residence')]:
        actual = decisions.loc[decisions.action.eq(action) & decisions.reason.eq(reason)]
        require(set(actual.source_id) == set(ids), '사용자 검토 확정 판정 불일치: '+reason)
        require(actual.use_code.eq('01001').all(), '사용자 확정 주택의 원자료 단독주택 코드 변경')
    require(not (set(REVIEWED_CANDIDATE_DECISIONS) &
                 (set.union(*confirmed_sets) | set(CONFIRMED_OFFICETELS))), '기존 개별 확정과 새 판정 충돌')
    require(set(REVIEWED_CANDIDATE_DECISIONS) <= set(decisions.source_id), '개별 대조 ID가 원자료에 없음')
    indexed = decisions.set_index('source_id')
    for source_id, (action, reason) in REVIEWED_CANDIDATE_DECISIONS.items():
        actual = indexed.loc[source_id]
        require((actual.action, actual.reason) == (action, reason), '개별 대조 판정 불일치: '+source_id)
        if reason == 'reviewed_mixed_residential_building':
            require(source_id == '41281_131976' and actual.use_code == '10299', '복합건물 원자료 식별·용도 변경')
        elif action == 'accepted':
            require(actual.use_code in RESIDENTIAL, '명칭 대조 포함 건물의 주거 코드 변경')
    require(not (set(USER_EXCLUDED_REMAINING_CANDIDATES) &
                 (set.union(*confirmed_sets) | set(CONFIRMED_OFFICETELS) |
                  set(REVIEWED_CANDIDATE_DECISIONS))), '최종 제외 ID가 기존 확정과 충돌')
    final_excluded = decisions.loc[decisions.reason.eq('user_excluded_remaining_uncertain')]
    require(set(final_excluded.source_id) == set(USER_EXCLUDED_REMAINING_CANDIDATES),
            '사용자 최종 제외 ID 누락 또는 추가')
    require(final_excluded.action.eq('excluded').all(), '최종 제외 판정 오류')
    require(not f.use_code.isin(['01004', '02007']).any(), '공관·기숙사가 선정됨')
    require(not decisions.loc[decisions.reason.eq('collective_or_official_residence'), 'action'].ne('excluded').any(), '공관·기숙사 제외 판정 오류')
    require(set(f.loc[f.decision_reason.eq('user_confirmed_officetel'), 'source_id']) == set(CONFIRMED_OFFICETELS), '사용자 확정 오피스텔 ID 불일치')
    require(set(f.building_source) == {SOURCE}, '출처 불일치')
    require(np.allclose(f.full_area_m2, f.area, rtol=0, atol=1e-6), '전체 면적 불일치')
    require(np.allclose(p.analysis_area_m2, p.area, rtol=0, atol=1e-6), '분석 면적 불일치')
    require(shapely.area(shapely.difference(p.geometry, city)).max() < 1e-6, '고양시 밖 분석 면적')
    require(shapely.area(shapely.difference(p.geometry, f.geometry)).max() < 1e-6, '원 건물 밖 분석 면적')
    require(shapely.covers(p.geometry, gpd.points_from_xy(f.representative_x, f.representative_y)).all(), '대표점이 건물 분석 도형 밖에 있음')
    require(set(layers['building_representative_points'].building_id) == set(f.building_id), '대표점 누락')
    known = f.entrance_scope.ne('missing')
    require(f.loc[known, ['entrance_x', 'entrance_y']].notna().all().all(), '출입구 좌표 누락')
    require(f.loc[~known, ['entrance_x', 'entrance_y']].isna().all().all(), '미확인 출입구 임의 좌표')
    e = layers['building_entrances'].set_index('entrance_id')
    require(set(f.loc[known, 'entrance_id']) == set(e.index), '출입구 레이어 연결 오류')
    require(np.allclose(f.loc[known, 'entrance_x'], f.loc[known, 'entrance_id'].map(e.geometry.x), rtol=0, atol=1e-8), '출입구 X 변경')
    require(np.allclose(f.loc[known, 'entrance_y'], f.loc[known, 'entrance_id'].map(e.geometry.y), rtol=0, atol=1e-8), '출입구 Y 변경')
    if 'review_buildings' in layers:
        require(not (set(layers['review_buildings'].building_id) & set(f.building_id)), '검토 대상이 분석에 포함됨')
        require(not layers['review_buildings'].building_group_id.isin(EXCLUDED_BUILDING_GROUPS).any(), '사용자 제외 건물군이 검토에 남음')
    require(shapely.union_all(p.geometry).symmetric_difference(c.geometry.iloc[0]).area < 1e-6, '합집합 면적 불일치')
    for name, layer in layers.items():
        require(layer.crs.to_epsg() == 5179 and layer.is_valid.all() and (~layer.is_empty).all(), name+': 공간 검증 오류')


def save(path, layers, tables):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.stem+'.'+uuid4().hex+'.tmp.gpkg')
    hashes = {}
    for name, frame in layers.items():
        options = {'geometry_type': 'MultiPolygon'} if name == 'review_buildings' and frame.empty else {}
        pyogrio.write_dataframe(frame, temp, layer=name, driver='GPKG', **options)
        check = pyogrio.read_dataframe(temp, layer=name)
        order = 'building_id' if 'building_id' in frame else 'entrance_id' if 'entrance_id' in frame else 'building_source'
        expected = layer_hash(frame, order)
        require(len(frame) == len(check) and expected == layer_hash(check, order), name+': 저장 대조 오류')
        hashes[name] = expected
    with closing(sqlite3.connect(temp)) as con:
        for name, frame in tables.items():
            frame.to_sql(name, con, index=False, if_exists='fail')
            con.execute('INSERT INTO gpkg_contents(table_name,data_type,identifier,description,srs_id) VALUES (?,?,?,?,NULL)',
                        (name, 'attributes', name, 'address map preprocessing'))
        con.commit()
        require(con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite 무결성 오류')
    try:
        temp.replace(path)
    except PermissionError:
        pending = path.with_name(path.stem+'_pending.gpkg')
        require(not pending.exists(), f'검증 결과는 {temp}에 보존됨; 기존 pending을 먼저 확인')
        temp.replace(pending)
        raise PermissionError(f'출력 파일 사용 중. 검증된 결과 보존: {pending}')
    return hashes


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    data = data_path()
    output = internal(args.output or data/'processed'/'residential_buildings.gpkg')
    audit = []
    print('Reading address map and boundaries...', flush=True)
    frames, city, files = read_inputs(data, audit)
    inputs = [{'path': p.relative_to(data).as_posix(), 'sha256': sha(p)} for p in files]
    print('Selecting buildings and linking supplied entrances...', flush=True)
    layers, decisions, summary = make_output(frames, city, audit)
    validate(layers, decisions, city)
    override_log = building_application_log(approved('building_decisions.csv'), decisions)
    require(all(sha(data/i['path']) == i['sha256'] for i in inputs), '입력 파일 실행 중 변경')
    metadata = {'source': SOURCE, 'reference_month': REFERENCE, 'crs': CRS, 'inputs': inputs,
        'summary': summary, 'code_sha256': sha(Path(__file__)),
        'position_semantics': 'representative = point_on_surface of building inside Goyang; entrance = supplied main entrance, building then group; not grid origin',
        'scope': 'Residential footprints and auxiliary positions only. No population, routing or internal travel times.',
        'limitations': 'Use code/name do not establish occupancy, completion date, residential floor share, pedestrian entrance availability or mandatory travel via a shared entrance.'}
    tables = {'building_decisions': decisions, 'geometry_audit': pd.DataFrame(audit),
        'processing_metadata': pd.DataFrame([{'key': k, 'value_json': json.dumps(v, ensure_ascii=False)} for k, v in metadata.items()])}
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    hashes = save(output, layers, tables)
    save_report('residential_buildings', dict(metadata, layer_hashes=hashes, override_application_log=override_log))
    print(json.dumps({'output': output.relative_to(ROOT).as_posix(), 'layer_hashes': hashes, 'validation': 'passed'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
