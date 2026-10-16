"""Read-only package validation, intended for later run.py preflight integration.

No legacy folders, raw data, network calls, or analysis results are accessed.
Requires shapely >= 2 and pyproj. Raises ValueError for invalid input.
"""
from pathlib import Path
import csv
import hashlib
import json
import math
import re
from collections import Counter
from shapely import from_wkt, to_wkb
from shapely.geometry import Point
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent
TABLES = ['building', 'walk_access', 'origin', 'facility', 'network', 'transit']
COMMON = {'override_id', 'dataset_id', 'target_id', 'action', 'field', 'new_value',
          'expected_before', 'target_fingerprint', 'reason', 'evidence_type',
          'evidence_path', 'source_url', 'decision_date', 'decision_source',
          'status', 'source_version', 'supersedes'}

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)

def digest(value):
    if not isinstance(value, bytes):
        value = canonical(value).encode('utf-8')
    return hashlib.sha256(value).hexdigest()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def local(path):
    require(path and not Path(path).is_absolute(), 'Relative path required: '+path)
    target = (ROOT/path).resolve()
    require(target.is_relative_to(ROOT), 'Path escapes package: '+path)
    return target

def read(path):
    with local(path).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))

def geometry(row):
    require(row['crs'] == 'EPSG:5179', 'Unsupported override CRS')
    if row['geometry_type'] == 'Point':
        require(not row['wkt'], 'Point must use X/Y, not WKT')
        g = Point(float(row['x']), float(row['y']))
    else:
        require(row['geometry_type'] == 'LineString', 'Unexpected geometry type')
        require(not row['x'] and not row['y'], 'Line must use WKT only')
        g = from_wkt(row['wkt'])
        require(g.geom_type == 'LineString' and g.length > 0, 'Empty or zero line')
    require(g.is_valid and not g.is_empty, 'Invalid geometry: '+row['geometry_id'])
    require(all(math.isfinite(v) for xy in g.coords for v in xy), 'Nonfinite ordinate')
    require(digest(to_wkb(g, byte_order=1, include_srid=False)) == row['geometry_sha256'],
            'Geometry round-trip fingerprint mismatch: '+row['geometry_id'])
    return g

def referenced_geometries(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if k.endswith('geometry_id'):
                yield v
            else:
                yield from referenced_geometries(v)
    elif isinstance(value, list):
        for v in value:
            yield from referenced_geometries(v)

def validate():
    decisions = {name:read(name+'_decisions.csv') for name in TABLES}
    gr = read('geometry_overrides.csv')
    require(len({r['geometry_id'] for r in gr}) == len(gr), 'Duplicate geometry IDs')
    geoms = {r['geometry_id']:geometry(r) for r in gr}
    decision_rows = [r for rr in decisions.values() for r in rr]
    all_rows = decision_rows + gr
    decision_ids = [r['override_id'] for r in decision_rows]
    require(len(decision_ids)==len(set(decision_ids)), 'Duplicate decision override ID')
    allowed = {'set_residential_decision','exclude_group','allow_both_walk_directions',
      'exclude_walk_way','use_separate_sidewalk','exclude_analysis_origin',
      'forbid_automatic_component_join','retain_provisional_connector','connect_ground_segments',
      'allow_provisional_join_passage','use_address_arrival_proxy','retain_stored_geocode',
      'use_user_entrance','use_assumed_median_crossing','retain_ordinary_wall_access_assumption',
      'ignore_service_poi_as_walk_barrier','provide_geometry'}
    for row in all_rows:
        require(COMMON <= row.keys(), 'Missing common fields')
        require(row['action'] in allowed, 'Unknown action: '+row['action'])
        if row['action']=='provide_geometry':
            require(row['override_id'] in decision_ids, 'Geometry parent decision missing')
        require(row['status'] in {'approved','superseded','pending','conflict'}, 'Invalid status')
        old = json.loads(row['expected_before'])
        require(digest(old) == row['target_fingerprint'], 'Guard fingerprint mismatch')
        value = json.loads(row['new_value'])
        require(local(row['evidence_path']).is_file(), 'Missing evidence file')
        for gid in referenced_geometries(value):
            require(gid in geoms, 'Missing geometry reference: '+str(gid))
        require(not re.search(r'^[OM]\d+$', row['target_id']), 'Legacy display ID target')
    for name,rr in decisions.items():
        keys=[(r['target_id'],r['field'],r['action']) for r in rr]
        require(len(keys)==len(set(keys)), 'Duplicate active operation: '+name)

    anchors = {}
    for r in read('evidence/target_segments.csv'):
        a=json.loads(r['expected_attributes'])
        require(digest(a)==r['target_fingerprint'], 'Segment guard mismatch')
        anchors[r['ref']]=from_wkt(a['wkt'])
    for r in read('evidence/target_nodes.csv'):
        a=json.loads(r['expected_attributes'])
        require(digest(a)==r['target_fingerprint'], 'Node guard mismatch')
        anchors[r['ref']]=Point(a['x'],a['y'])
    for r in read('evidence/target_stops.csv'):
        a={k:r[k] for k in ['stop_id','stop_name']}
        a.update({k:float(r[k]) for k in ['stop_lon','stop_lat','x_5179','y_5179']})
        require(digest(a)==r['target_fingerprint'], 'Stop guard mismatch')
        anchors[r['ref']]=Point(a['x_5179'],a['y_5179'])
    for r in decisions['transit']:
        v=json.loads(r['new_value'])
        if r['action']=='use_user_entrance':
            anchors[v['entrance_ref']]=geoms[v['entrance_geometry_id']]
    for r in decisions['facility']:
        v=json.loads(r['new_value'])
        if 'point_geometry_id' in v:
            anchors[r['target_id']]=geoms[v['point_geometry_id']]
    for r in decisions['origin']:
        v=json.loads(r['new_value']);a=json.loads(r['expected_before'])
        if r['action']=='retain_provisional_connector':
            anchors[r['target_id']]=Point(a['origin_x'],a['origin_y'])

    endpoints=0; tr=Transformer.from_crs(4326,5179,always_xy=True)
    for r in gr:
        g=geoms[r['geometry_id']];md=json.loads(r['metadata'])
        require(r['cost_kind'] in {'none','length_over_scenario_speed','shared_node_no_distance','fixed_internal_walk_seconds'},'Unknown cost basis')
        require(all(x in decision_ids for x in json.loads(r['related_override_ids'])), 'Missing related decision')
        if g.geom_type=='Point' and 'longitude' in md:
            p=Point(*tr.transform(md['longitude'],md['latitude']))
            require(p.distance(g)<0.001, 'Coordinate conversion differs by over 1 mm')
        if r['from_ref'] and r['to_ref']:
            coords=[Point(g.coords[0]),Point(g.coords[-1])]
            for key,p in zip(['from_ref','to_ref'],coords):
                require(r[key] in anchors, 'Unresolved endpoint: '+r[key])
                require(anchors[r[key]].distance(p)<0.001, 'Endpoint mismatch: '+r['geometry_id']+' '+key)
                if r[key].startswith('osm_segment:'):
                    stored=float(r[key.replace('_ref','_position_m')])
                    require(abs(anchors[r[key]].project(p)-stored)<0.001, 'Along-segment position mismatch')
                endpoints+=1

    dep=read('transit_056/weekday_departures.csv')
    require(Counter(r['branch'] for r in dep)=={'도촌':32,'서촌':24,'멱절':24}, '056 departure counts')
    require(len({(r['branch'],r['departure_time']) for r in dep})==80,'Duplicate departure')
    require(any(r['branch']=='멱절' and r['departure_time']=='19:41' for r in dep),'Missing Myeokjeol 19:41')
    require(len(read('transit_056/stops.csv'))==32,'056 stop count')
    require(len(read('transit_056/common_section.csv'))==63,'056 common sequence')
    require(len(read('transit_056/route_sources.csv'))==3,'056 route count')
    sources={r['source_label']:r for r in read('evidence/source_manifest.csv')}
    for name in ['stops.csv','route_sources.csv','common_section.csv','weekday_departures.csv']:
        expected=sources['legacy_submission/data/metadata/056/'+name]['sha256']
        require(digest(local('transit_056/'+name).read_bytes())==expected,'056 input differs from approved source')
    require(not list(ROOT.rglob('*study_grids*')),'Legacy selected grid input')
    require(not list(ROOT.rglob('*.gpkg')),'GPKG must be a derived output')
    for r in read('evidence/attachment_inventory.csv'):
        if r['evidence_path']:
            require(digest(local(r['evidence_path']).read_bytes())==r['sha256'],'Attachment hash mismatch')
    files=ROOT/'evidence/package_files.csv'
    if files.exists():
        for r in read('evidence/package_files.csv'):
            require(digest(local(r['path']).read_bytes())==r['sha256'],'Package content changed: '+r['path'])
    return {'decision_rows':{k:len(v) for k,v in decisions.items()},
            'geometry_rows':len(gr),'validated_endpoint_bindings':endpoints,
            'decision_categories':len(read('decision_register.csv')),
            'field_verification_performed':False,'v7_analysis_executed':False}

if __name__ == '__main__':
    print(json.dumps(validate(),ensure_ascii=False,indent=2))
