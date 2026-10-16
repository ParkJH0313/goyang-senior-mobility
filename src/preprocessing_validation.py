"""기초 전처리 결과와 후속 분석에 넘기는 보정 입력을 검증한다.

접속선을 새 망에 적용하거나 출발점/접근성/군집을 계산하지 않는다.
"""
from __future__ import annotations
from .preprocessing_common import ROOT, initialize, internal, approved, fingerprint, sha256, save_report
initialize()
import csv
import hashlib
import json
from contextlib import closing
from collections import Counter, defaultdict
from pathlib import Path
import sqlite3
import importlib.metadata
import sys
import geopandas as gpd
import pandas as pd
import pyogrio
import shapely
from shapely.geometry import Point


def read_csv(path):
    with internal(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_handoff():
    decisions = [r for file in sorted((ROOT/'overrides').glob('*_decisions.csv')) for r in approved(file.name)]
    by_id = {r['override_id']: r for r in decisions}
    require(len(by_id) == len(decisions), '자료 간 override_id 중복')
    geometries = read_csv('overrides/geometry_overrides.csv')
    restored, references, endpoint_checks = {}, {}, 0
    target_fingerprints = {}
    for row in geometries:
        gid = row['geometry_id']
        require(gid not in restored and row['crs'] == 'EPSG:5179', '도형 ID 중복/좌표계 오류')
        require(row['geometry_type'] in {'Point','LineString'}, '지원하지 않는 보정 도형 종류')
        geom = Point(float(row['x']), float(row['y'])) if row['geometry_type'] == 'Point' else shapely.from_wkt(row['wkt'])
        require(geom.geom_type == row['geometry_type'] and not geom.is_empty and geom.is_valid, '보정 도형 오류: '+gid)
        require(geom.geom_type == 'Point' or geom.length > 0, '보정 선 길이 0: '+gid)
        digest = hashlib.sha256(shapely.to_wkb(geom, byte_order=1, include_srid=False)).hexdigest()
        require(digest == row['geometry_sha256'], '도형 꼭짓점/정밀도 지문 변경: '+gid)
        expected = json.loads(row['expected_before'])
        require(fingerprint(expected) == row['target_fingerprint'], '도형 사전조건 지문 오류')
        for oid in json.loads(row['related_override_ids']):
            require(oid in by_id, '도형의 판정 참조 누락: '+oid)
        restored[gid] = geom
        if row['geometry_role'] == 'user_station_entrance':
            references[row['target_id']] = geom
    # 모든 판정의 geometry_id 참조를 재귀적으로 검사한다.
    def check_refs(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith('geometry_id'):
                    require(item in restored, '판정의 도형 참조 누락: '+str(item))
                else:
                    check_refs(item)
        elif isinstance(value, list):
            for item in value: check_refs(item)
    for row in decisions:
        check_refs(row['value'])

    network = internal('data/processed/osm_walk_network.gpkg')
    segment_sources = read_csv('overrides/evidence/target_segments.csv')
    wanted = [r['segment_id'] for r in segment_sources]
    where = 'segment_id IN (' + ','.join("'"+v.replace("'","''")+"'" for v in wanted) + ')'
    segments = pyogrio.read_dataframe(network, layer='edges', where=where)
    grouped = {k:v for k,v in segments.groupby('segment_id')}
    for row in segment_sources:
        expected = json.loads(row['expected_attributes'])
        require(fingerprint(expected) == row['target_fingerprint'], '구간 근거 지문 오류')
        require(row['segment_id'] in grouped, '보정 대상 구간 소실: '+row['ref'])
        original = shapely.from_wkt(expected['wkt'])
        candidates = grouped[row['segment_id']]
        keys = [k for k in expected if k not in {'wkt','crs'}]
        matched = [r for _,r in candidates.iterrows() if all(r[k] == expected[k] for k in keys)
                   and shapely.equals_exact(r.geometry, original, tolerance=1e-7)]
        require(bool(matched), '구간 속성/도형 변경: '+row['ref'])
        references[row['ref']] = original
        target_fingerprints[row['ref']] = row['target_fingerprint']
    node_sources = read_csv('overrides/evidence/target_nodes.csv')
    node_ids = [str(json.loads(r['expected_attributes'])['osm_node_id']) for r in node_sources]
    nodes = pyogrio.read_dataframe(network, layer='access_points', where='osm_node_id IN ('+','.join(node_ids)+')')
    nodes = nodes.set_index('osm_node_id', drop=False)
    graph_nodes = pyogrio.read_dataframe(network, layer='nodes', where='osm_node_id IN ('+','.join(node_ids)+')').set_index('node_id',drop=False)
    for row in node_sources:
        expected = json.loads(row['expected_attributes'])
        require(fingerprint(expected) == row['target_fingerprint'], '지점 근거 지문 오류')
        item = graph_nodes.loc[expected['node_id']] if 'node_id' in expected else nodes.loc[expected['osm_node_id']]
        for key, value in expected.items():
            actual = item.geometry.x if key=='x' else item.geometry.y if key=='y' else 'EPSG:5179' if key=='crs' else item[key]
            require(abs(actual-value)<1e-7 if isinstance(value,float) else actual==value, '지점 속성 변경: '+row['ref']+'/'+key)
        references[row['ref']] = item.geometry
        target_fingerprints[row['ref']] = row['target_fingerprint']

    stop_sources = read_csv('overrides/evidence/target_stops.csv')
    with closing(sqlite3.connect(internal('data/processed/gtfs.sqlite'))) as con:
        stops = pd.read_sql_query('SELECT * FROM stops',con).set_index('stop_id',drop=False)
        require(con.execute('PRAGMA integrity_check').fetchone()[0]=='ok', 'GTFS 무결성')
        require(not con.execute('PRAGMA foreign_key_check').fetchall(), 'GTFS 외래키')
        require(con.execute('SELECT count(*) FROM routes WHERE route_type_raw NOT IN(0,1,4)').fetchone()[0]==0, '금지 수단 잔존')
        require(con.execute('SELECT count(*) FROM routes r JOIN route_decisions d USING(route_id) WHERE d.is_gtx=1').fetchone()[0]==0,'GTX 잔존')
        current_counts = {t:con.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['routes','trips','stops','stop_times','patterns','pattern_stops','transfers']}
        modes = dict(con.execute('SELECT mode,count(*) FROM routes GROUP BY mode'))
        require(con.execute("SELECT count(*) FROM trips WHERE route_id='BR_3100_241299005'").fetchone()[0]==80,'056 중복/누락')
    for row in stop_sources:
        canonical = {k:float(v) if k in ['stop_lon','stop_lat','x_5179','y_5179'] else v
                     for k,v in row.items() if k not in {'ref','target_fingerprint'}}
        require(fingerprint(canonical)==row['target_fingerprint'],'정류장 근거 지문 오류')
        require(row['stop_id'] in stops.index, '확정 정류장이 후보 추출에서 누락: '+row['ref'])
        item = stops.loc[row['stop_id']]
        require(item.stop_name == row['stop_name'], '정류장 이름 변경')
        for key in ['stop_lon','stop_lat','x_5179','y_5179']:
            require(abs(float(item[key])-float(row[key]))<1e-7, '정류장 위치 변경')
        references[row['ref']] = Point(item.x_5179, item.y_5179)
        target_fingerprints[row['ref']] = row['target_fingerprint']

    def verify_nested_targets(value):
        if isinstance(value,dict):
            ref=value.get('ref')
            expected=value.get('segment_fingerprint',value.get('target_fingerprint'))
            if ref and expected:
                require(target_fingerprints.get(ref)==expected,'판정과 대상 스냅샷 지문 불일치: '+ref)
            for child in value.values(): verify_nested_targets(child)
        elif isinstance(value,list):
            for child in value: verify_nested_targets(child)
    for row in decisions: verify_nested_targets(row['expected'])

    medical = pd.read_csv(internal('data/processed/medical_institutions.csv'),dtype={'hospital_id':str}).set_index('hospital_id',drop=False)
    population = pyogrio.read_dataframe(internal('data/processed/elderly_population.gpkg'),layer='elderly_250m').set_index('gid',drop=False)
    for row in decisions:
        expected, value = row['expected'], row['value']
        if row['action']=='use_address_arrival_proxy':
            item=medical.loc[expected['hospital_id']]
            require(item['name']==expected['name'] and item.address==expected['address'], '도착점 기관 속성 변경')
            point=Point(expected['address_x'],expected['address_y'])
            require(point.distance(Point(item.x_5179,item.y_5179))<1e-7,'기관 주소 좌표 변경')
            references[row['target_id']]=point
        elif row['action'] in {'exclude_analysis_origin','retain_provisional_connector'}:
            item=population.loc[expected['gid']]
            x=expected.get('origin_x',expected.get('original_origin_x'))
            y=expected.get('origin_y',expected.get('original_origin_y'))
            point=Point(x,y)
            require(item.geometry.covers(point),'확정 출발 위치의 격자 소속 변경')
            if 'parent_gid' in expected: require(item.parent_gid==expected['parent_gid'],'부모 격자 변경')
            references[row['target_id']]=point
        elif row['action']=='use_user_entrance':
            references[value['entrance_ref']]=restored[value['entrance_geometry_id']]
            if 'internal_walk_seconds' in value:
                require(value['internal_walk_seconds']==180,'승인된 운정 내부 고정시간 변경')
    for row in geometries:
        geom=restored[row['geometry_id']]
        for key, coordinate in [('from_ref',0),('to_ref',-1)]:
            ref=row[key]
            if not ref: continue
            require(ref in references,'보정 도형 끝점 참조 미해결: '+ref)
            point=geom if geom.geom_type=='Point' else Point(geom.coords[coordinate])
            target=references[ref]
            require(point.distance(target)<1e-5, '보정 도형 끝점 불일치: '+row['geometry_id']+'/'+key)
            position=row['from_position_m' if coordinate==0 else 'to_position_m']
            if position and target.geom_type=='LineString':
                require(abs(target.project(point)-float(position))<1e-5,'보정 선상 위치 불일치')
            endpoint_checks += 1
    direct_ids=set()
    for name in ['residential_buildings','medical_institutions','osm_walk_network']:
        report=json.loads(internal('data/processed/preprocessing_reports/'+name+'.json').read_text(encoding='utf-8'))
        direct_ids.update(r['override_id'] for r in report.get('override_application_log',[]))
    log=[dict(override_id=r['override_id'],target_id=r['target_id'],action=r['action'],
              status='applied_in_preprocessing' if r['override_id'] in direct_ids else 'validated_for_downstream',
              reason='원본 대상·속성 및 제공 도형 검증. 연결선 적용·격자 출발점 산정은 후속 분석.') for r in decisions]
    result={'approved_decisions':len(decisions),'by_file':{f.name:len(approved(f.name)) for f in sorted((ROOT/'overrides').glob('*_decisions.csv'))},
            'applied_in_preprocessing':len(direct_ids),'downstream_decisions':len(decisions)-len(direct_ids),
            'geometry_count':len(restored),'geometry_types':dict(Counter(g.geom_type for g in restored.values())),
            'geometry_wkb_exact':True,'endpoint_checks':endpoint_checks,
            'target_segments':len(segment_sources),'target_nodes':len(node_sources),'target_stops':len(stop_sources),
            'gtfs_counts':current_counts,'gtfs_modes':modes,'unresolved_conflicts':0,
            'override_application_log':log,'scope':'preprocessing validation only; downstream network corrections not applied'}
    save_report('override_handoff',result)
    return result


def file_description(path):
    path=internal(path)
    result={'path':path.relative_to(ROOT).as_posix(),'sha256':sha256(path),'bytes':path.stat().st_size}
    if path.suffix in {'.gpkg','.sqlite'}:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as con:
            if path.suffix=='.gpkg':
                result['crs']='EPSG:5179'
                tables=[r[0] for r in con.execute('SELECT table_name FROM gpkg_contents')]
            else:
                result['crs']='stop_lon/stop_lat: EPSG:4326; x_5179/y_5179: EPSG:5179'
                tables=['routes','stops','trips','stop_times','transfers','patterns','pattern_stops']
            result['tables']={t:{'rows':con.execute('SELECT count(*) FROM "'+t+'"').fetchone()[0],
                                  'fields':[r[1] for r in con.execute('PRAGMA table_info("'+t+'")')]} for t in tables}
    elif path.suffix=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as stream:
            reader=csv.reader(stream);result['fields']=next(reader)
    elif path.suffix=='.shp':
        info=pyogrio.read_info(path)
        result['crs']=str(info['crs']) if info['crs'] else '원본 배포본 공통 GRS80_UTMK.prj 적용'
        result['fields']=list(info['fields']);result['features']=info['features']
    return result


def write_manifest():
    reports={p.stem:json.loads(p.read_text(encoding='utf-8')) for p in internal('data/processed/preprocessing_reports').glob('*.json')}
    configs=[
      ('boundaries','경계','boundaries.gpkg','통계지리정보서비스(SGIS)','https://sgis.mods.go.kr/view/pss/openDataIntrcn','2025-06-30','SGIS 제공 조건 확인 필요'),
      ('elderly_population','고령인구','elderly_population.gpkg','국토교통부 국토지리정보원','https://map.ngii.go.kr/ms/map/NlipMap.do','2025-04','국토정보플랫폼 원자료별 이용 조건 확인 필요'),
      ('address_buildings','도로명주소_전자지도_고양시_202503','residential_buildings.gpkg','행정안전부 / 주소기반산업지원서비스','https://business.juso.go.kr/','2025-03','신청 제공자료; 원본 재배포 허용 여부 별도 확인 필요'),
      ('medical_institutions','병원','medical_institutions.csv','건강보험심사평가원','https://opendata.hira.or.kr/op/opc/selectOpenData.do?sno=11925','2025-03','HIRA 및 좌표보완 Kakao 응답의 각각의 이용·재배포 조건 확인 필요'),
      ('osm_walk_network','OSM','osm_walk_network.gpkg','OpenStreetMap contributors / Geofabrik','https://download.geofabrik.de/asia/south-korea.html','2025-01','OpenStreetMap ODbL 1.0; 제공 출처 표시 및 파생 DB 배포 조건 적용'),
      ('gtfs','GTFS','gtfs.sqlite','한국교통연구원 국가교통DB(KTDB)','https://www.ktdb.go.kr/','2025-03 weekday sample','KTDB 원자료 제공·재배포 조건 확인 필요'),
    ]
    datasets=[]
    for did,folder,out,provider,url,date,license_text in configs:
        meta=dict(provider=provider,source_url=url,reference_date=date,license_and_redistribution=license_text)
        # 기록된 실제 사용 파일만 명세에 포함. 다른 폴더의 구버전 자료는 런타임 입력이 아니다.
        report=reports[{'address_buildings':'residential_buildings'}.get(did,did)]
        if did=='boundaries':
            raw_files=[internal('data/'+r['file']).with_suffix(s) for r in report['sources'] for s in ['.shp','.shx','.dbf','.prj','.cpg']]
        elif did=='elderly_population':raw_files=[internal('data/'+p) for p in report['source_sha256']]
        elif did=='address_buildings':raw_files=[internal('data/'+r['path']) for r in report['inputs'] if r['path'].startswith('raw/'+folder+'/')]
        else:
            raw_files=[internal('data/'+p) for p in report['input_sha256'] if p.startswith('raw/'+folder+'/')]
        if did=='medical_institutions': raw_files+=list(internal('data/raw/병원').glob('kakao_address_responses.json'))
        raw_files=sorted(set(raw_files))
        datasets.append(dict(dataset_id=did+'_raw',kind='raw',**meta,files=[file_description(p) for p in raw_files]))
        output_files=[file_description('data/processed/'+out)]
        if did=='gtfs': output_files.append(file_description('data/processed/gtfs_056_branch_parameters.csv'))
        datasets.append(dict(dataset_id=did,kind='processed',schema_version='1.0',**meta,files=output_files))
    datasets.append(dict(dataset_id='transit_056',kind='override_input',provider='기존 확정 사용자 입력 / BusMaps 및 게시 시간표',
        source_url='overrides/transit_056/route_sources.csv와 weekday_departures.csv의 행별 URL',
        reference_date='도촌 2025-02, 서촌·멱절 2025-04-15; 위치 자료 기준연도 미상',
        license_and_redistribution='원문별 조건 확인 필요; 추정 시간표로 표시',
        files=[file_description('overrides/transit_056/'+n) for n in ['stops.csv','route_sources.csv','common_section.csv','weekday_departures.csv']]))
    overrides=[file_description(p) for p in sorted(internal('overrides').rglob('*')) if p.is_file()]
    metadata=dict(schema_version='1.0',methodology_version='v7',scope='preprocessing',datasets=datasets,
                  overrides=overrides,code=[file_description(p) for folder in ['preprocess','src'] for p in sorted(internal(folder).glob('*.py'))],
                  requirements=file_description('requirements.txt'),
                  preprocessing_reports=[file_description(p) for p in sorted(internal('data/processed/preprocessing_reports').glob('*.json'))],
                  environment={'python':sys.version.split()[0],'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}},
                  root_policy='all paths relative to project root; no external research file dependency',
                  unused_raw_folders=sorted({p.name for p in internal('data/raw').iterdir() if p.is_dir()}-{c[1] for c in configs}))
    target=internal('data/manifest.json');temporary=target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(target)
    return metadata


def finalize():
    result=validate_handoff()
    manifest=write_manifest()
    print(json.dumps({'validation':'passed','approved_decisions':result['approved_decisions'],
                      'unresolved_conflicts':result['unresolved_conflicts'],'datasets':len(manifest['datasets']),
                      'gtfs_counts':result['gtfs_counts']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    finalize()
