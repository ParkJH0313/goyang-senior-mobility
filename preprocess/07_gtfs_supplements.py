"""BIS에 없는 056 지선을 BusMaps 위치·경로와 2025년 평일 출발표로 보완.

확인한 입력: overrides/transit_056/*.csv. 기존 processed/gtfs.sqlite를 원자적으로 교체.
원본 5편은 대체하며 중복 운행으로 남기지 않는다. 중간 시각은 추정값이다.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.preprocessing_common import (ROOT, initialize, internal, data_path, save_report,
    building_constants, validate_buildings, building_application_log, walk_constants, validate_walk)
initialize()
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone
import argparse,hashlib,json,sqlite3,shutil
import numpy as np,pandas as pd,geopandas as gpd,pyogrio
from pyproj import Transformer
from shapely.geometry import Point,LineString
from shapely.ops import substring

DATA=data_path();BASE=ROOT
INPUT=internal(ROOT/'overrides/transit_056');DB=DATA/'processed/gtfs.sqlite'
ROUTE='BR_3100_241299005';T=Transformer.from_crs(4326,5179,always_xy=True)
NOTE='일부 지선 구간은 BIS에 등록되어 있지 않아 BusMaps의 정류장 좌표와 경로로 보완하였다. 사용자가 위치 후보를 분석에 채택하였다. BusMaps 원자료 기준연도는 불명이다.'

def sha(p):
 with open(p,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def log(s):print(s,flush=True)
def ro(p):return sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True)
def decode(s):
 out=[];lat=lon=i=0
 while i<len(s):
  delta=[]
  for _ in range(2):
   value=shift=0
   while True:
    b=ord(s[i])-63;i+=1;value|=(b&31)<<shift;shift+=5
    if b<32:break
   delta.append(~(value>>1) if value&1 else value>>1)
  lat+=delta[0];lon+=delta[1];out.append(T.transform(lon/1e5,lat/1e5))
 return LineString(out)


def compile_inputs():
 stops=pd.read_csv(INPUT/'stops.csv',keep_default_na=False)
 sources=pd.read_csv(INPUT/'route_sources.csv',keep_default_na=False)
 common=pd.read_csv(INPUT/'common_section.csv',keep_default_na=False)
 departures=pd.read_csv(INPUT/'weekday_departures.csv',keep_default_na=False)
 assert len(stops)==32 and stops.review_id.is_unique and len(departures)==80
 geometries={};common_lengths=[]
 for r in sources.itertuples():
  full=decode(r.full_shape_polyline);parts={}
  for direction in ['out','in']:
   anchor=Point(T.transform(getattr(r,direction+'_anchor_lon'),getattr(r,direction+'_anchor_lat')))
   part=substring(full,0,full.length*.25) if direction=='out' else substring(full,full.length*.75,full.length)
   cut=part.project(anchor);parts[direction]=substring(part,0,cut) if direction=='out' else substring(part,cut,part.length)
   geometries[(r.branch,direction)]=parts[direction]
  common_lengths.append(full.length-sum(x.length for x in parts.values()))
 seconds=float(common.departure_offset_s.iloc[-1]);speed=float(np.median(common_lengths)/seconds)
 assert 1.5<speed<15,speed
 return stops,sources,common,departures,geometries,speed

def complete():
 stops,sources,common,departures,geometry,speed=compile_inputs()
 manifest={name:sha(INPUT/name) for name in ['stops.csv','route_sources.csv','common_section.csv','weekday_departures.csv']}
 fingerprint=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
 with closing(ro(DB)) as c:
  saved=c.execute("select value_json from processing_metadata where key='supplement_056'").fetchone()
  if saved and json.loads(saved[0]).get('input_fingerprint')==fingerprint and json.loads(saved[0]).get('code_sha256')==sha(Path(__file__)):
   log('동일한 056 보완 입력: processed 재사용');return
 work=DB.with_name('gtfs.completing.sqlite')
 with closing(ro(DB)) as src,closing(sqlite3.connect(work)) as dest:src.backup(dest)
 branchfacts=[];shape_rows=[];timing_rows=[];trip_rows=[]
 with closing(sqlite3.connect(work)) as c:
  c.execute('pragma foreign_keys=on');c.execute('pragma busy_timeout=60000')
  with c:
   schema=c.execute("select sql from sqlite_master where name='stop_times'").fetchone()[0]
   if 'timepoint=1' in schema:
    # GTFS timepoint=0은 추정시각이다. 원자료 전용 제약을 표준의 0/1로 확장한다.
    view=c.execute("select sql from sqlite_master where name='stop_times_named'").fetchone()[0]
    c.execute('drop view stop_times_named')
    c.execute(schema.replace('CREATE TABLE stop_times(', 'CREATE TABLE stop_times_completed(').replace('CHECK(timepoint=1)','CHECK(timepoint IN(0,1))'))
    c.execute('insert into stop_times_completed select * from stop_times')
    c.execute('drop table stop_times')
    c.execute('alter table stop_times_completed rename to stop_times')
    c.execute('create index stop_times_stop_departure on stop_times(stop_key,departure_s,trip_key)')
    c.execute(view)
   oldkeys=c.execute('select trip_key from trips where route_id=?',(ROUTE,)).fetchall()
   oldpatterns=c.execute('select pattern_id from patterns where route_id=?',(ROUTE,)).fetchall()
   c.executemany('delete from stop_times where trip_key=?',oldkeys)
   c.execute('delete from trips where route_id=?',(ROUTE,))
   c.executemany('delete from pattern_stops where pattern_id=?',oldpatterns)
   c.execute('delete from patterns where route_id=?',(ROUTE,))
   nextstop=c.execute('select max(stop_key)+1 from stops').fetchone()[0]
   nexttrip=c.execute('select max(trip_key)+1 from trips').fetchone()[0]
   keymap={}
   for r in stops.itertuples():
    sid='BS_SUPP056_'+r.review_id
    found=c.execute('select stop_key from stops where stop_id=?',(sid,)).fetchone()
    key=found[0] if found else nextstop
    if not found:nextstop+=1
    x,y=T.transform(r.longitude,r.latitude)
    if found:c.execute('update stops set stop_name=?,stop_lat=?,stop_lon=?,x_5179=?,y_5179=? where stop_key=?',(r.stop_name,r.latitude,r.longitude,x,y,key))
    else:c.execute('insert into stops values(?,?,?,?,?,?,?,?,?,?)',(key,sid,r.stop_name,r.latitude,r.longitude,x,y,1,1,1))
    keymap[r.review_id]=key
   for source in sources.itertuples():
    branch=source.branch;code=source.branch_code;out=geometry[(branch,'out')];back=geometry[(branch,'in')]
    outbound=stops[(stops.branch==branch)&(stops.direction=='out')].sort_values('branch_sequence')
    inbound=stops[(stops.branch==branch)&(stops.direction=='in')].sort_values('branch_sequence')
    out_end=int(np.ceil(out.length/speed));back_start=out_end+int(common.departure_offset_s.iloc[-1])
    pattern=[]
    for r in outbound.itertuples():
     offset=int(round(out.project(Point(T.transform(r.longitude,r.latitude)))/speed))
     if r.branch_sequence==1:offset=0
     pattern.append((keymap[r.review_id],offset,offset,0,0,1 if r.branch_sequence==1 else 0,'branch_distance_speed'))
    for r in common.itertuples():pattern.append((int(r.stop_key),out_end+int(r.arrival_offset_s),out_end+int(r.departure_offset_s),int(r.pickup_type),int(r.drop_off_type),0,'common_5trip_median'))
    for r in inbound.itertuples():
     offset=back_start+int(round(back.project(Point(T.transform(r.longitude,r.latitude)))/speed))
     if r.branch_sequence==len(inbound):offset=back_start+int(np.ceil(back.length/speed))
     pattern.append((keymap[r.review_id],offset,offset,0,0,0,'branch_distance_speed'))
    offsets=np.array([(r[1],r[2]) for r in pattern]);assert np.all(offsets[1:,0]>=offsets[:-1,1]),branch
    pid=hashlib.sha256((ROUTE+':'+code+':'+','.join(str(r[0]) for r in pattern)).encode()).hexdigest()
    c.execute('insert into patterns values(?,?,?,?,?)',(pid,ROUTE,len(pattern),pattern[0][0],pattern[-1][0]))
    c.executemany('insert into pattern_stops values(?,?,?,?,?)',[(pid,i,key,pick,drop) for i,(key,a,d,pick,drop,tp,basis) in enumerate(pattern,1)])
    for r in departures[departures.branch==branch].itertuples():
     tid=f'{ROUTE}_{code}_WD_{r.departure_number:03d}';key=nexttrip;nexttrip+=1
     c.execute('insert into trips values(?,?,?,?,?,?,?,?)',(key,tid,ROUTE,'B1',pid,len(pattern),int(r.departure_s),int(r.departure_s)+pattern[-1][1]))
     c.executemany('insert into stop_times values(?,?,?,?,?,?,?,?)',[(key,i,s,int(r.departure_s)+a,int(r.departure_s)+d,pick,drop,tp) for i,(s,a,d,pick,drop,tp,basis) in enumerate(pattern,1)])
     trip_rows.append(dict(trip_key=key,trip_id=tid,branch=branch,departure_s=int(r.departure_s),departure_source_date=r.source_date,departure_source_url=r.source_url,reference_point=branch+' 기점'))
    for i,(key,a,d,pick,drop,tp,basis) in enumerate(pattern,1):timing_rows.append(dict(pattern_id=pid,branch=branch,stop_sequence=i,stop_key=key,arrival_offset_s=a,departure_offset_s=d,timing_basis=basis,timepoint=tp))
    for direction,line in [('out',out),('in',back)]:shape_rows.append(dict(branch=branch,direction=direction,source_url=source.source_url,length_m=line.length,crs='EPSG:5179',geometry_wkt=line.wkt))
    branchfacts.append(dict(branch=branch,pattern_id=pid,weekday_departures=int((departures.branch==branch).sum()),stops_per_trip=len(pattern),outbound_length_m=out.length,inbound_length_m=back.length,outbound_estimated_s=out_end,inbound_estimated_s=int(np.ceil(back.length/speed)),effective_speed_kmh=speed*3.6))
   c.execute('update route_decisions set selection_reason=? where route_id=?',('selected; BIS-unregistered branches completed with BusMaps and 2025 weekday origin departure tables',ROUTE))
  stop_source=stops.assign(stop_key=stops.review_id.map(keymap),location_status='user_accepted_approximation_2025_source_year_unverified')
  for name,rows in [('supplement_056_stops',stop_source),('supplement_056_branches',pd.DataFrame(branchfacts)),('supplement_056_shapes',pd.DataFrame(shape_rows)),('supplement_056_trip_sources',pd.DataFrame(trip_rows)),('supplement_056_timing',pd.DataFrame(timing_rows))]:rows.to_sql(name,c,index=False,if_exists='replace')
  metadata=dict(note=NOTE,source_geometry='https://busmaps.com/ko/south-korea/KTDB/ktdb-korea',
   location_acceptance='사용자 2026-10-16 채택. 현장측량 또는 2025년 좌표 확정으로 해석하지 않음.',
   temporal_basis='도촌 2025-02, 서촌/멱절 2025-04-15 평일표를 결합한 2025년 보완 모형. 정확한 2025-03 날짜의 실측 시간표가 아님.',
   running_time_basis='공통구간: 원자료5편의 정류장별 상대 도착/출발 중앙값. 지선: BusMaps 거리/공통구간 유효속도; 유효속도=3개 원문 공통구간 거리 중앙값/공통 왕복시간. 정차대기는 이 유효속도에 포함하는 근사.',
   branch_return_assumption='동일 지선 기점 출발→기존 공통 왕복구간→동일 지선 복귀를 한 운행편으로 구성. 운행편 사이 차량 계속탑승은 추가하지 않음.',
   effective_speed_kmh=speed*3.6,input_fingerprint=fingerprint,input_sha256=manifest,code_sha256=sha(Path(__file__)),weekday_trip_count=80,new_directional_stops=32,
   calendar_interpretation='기존B1은 분석용 평일 표본 식별자. 원본 달력의 전요일 범위를 실제 전요일 운행 근거로 사용하지 않음.')
  c.execute('insert or replace into processing_metadata values(?,?)',('supplement_056',json.dumps(metadata,ensure_ascii=False)))
  counts={t:c.execute('select count(*) from '+t).fetchone()[0] for t in ['routes','trips','stops','stop_times','patterns','pattern_stops','transfers']}
  c.execute('insert or replace into processing_metadata values(?,?)',('current_counts',json.dumps(counts)))
  c.execute('insert or replace into qa_checks values(?,?,?)',('supplement_056_integrity',1,json.dumps({'trips':80,'stops':32,'original_5_trips_replaced':True})))
  c.commit()
  assert c.execute('pragma integrity_check').fetchone()[0]=='ok'
  assert not c.execute('pragma foreign_key_check').fetchall()
  assert c.execute('select count(*) from trips where route_id=?',(ROUTE,)).fetchone()[0]==80
  assert c.execute('select count(*) from (select arrival_s,lag(departure_s) over(partition by trip_key order by stop_sequence) prev from stop_times) where arrival_s<prev').fetchone()[0]==0
  assert c.execute("select count(*) from stops where stop_id like 'BS_SUPP056_%'").fetchone()[0]==32
  c.execute('analyze');c.commit()
  c.execute('vacuum')
 work.replace(DB)
 pd.DataFrame(branchfacts).to_csv(DATA/'processed/gtfs_056_branch_parameters.csv',index=False,encoding='utf-8-sig')
 save_report('gtfs_056',dict(metadata,counts=counts,branches=branchfacts))
 # 파생 결과를 다음 실행의 입력 지문에 포함하지 않는다.
 log(pd.DataFrame(branchfacts).to_string(index=False));log('processed/gtfs.sqlite 교체 완료')

if __name__=='__main__':
 complete()
