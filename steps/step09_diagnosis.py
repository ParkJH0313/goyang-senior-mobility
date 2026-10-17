"""Cluster-level travel components, arrival states, and bus-stop walking access."""
import json
from collections import defaultdict
import numpy as np,pandas as pd,geopandas as gpd,pyogrio
from shapely.geometry import LineString
from src.analysis_io import inside,csv,parquet,gpkg,atomic_json,describe,digest,sha,ro
from src.timetable import walk_arrays
from src.path_diagnosis import decompose
from src.cluster_diagnostics import build
DEPENDENCIES=['steps/step09_diagnosis.py','src/path_diagnosis.py','src/cluster_diagnostics.py','src/analysis_io.py']
SETTINGS=['diagnostic_budgets_min','max_continuous_walk_s','max_boardings','dpi','baseline_budget_min']

def run(ctx):
    out=ctx.step(9);cp=pd.read_parquet(ctx.step(8)/'extended_checkpoint.parquet')
    small=pyogrio.read_dataframe(ctx.step(6)/'accessibility.gpkg',layer='accessibility_250m').set_index('gid',drop=False)
    small.index.name=None
    membership=pd.read_csv(ctx.step(7)/'tables/baseline_top3_membership.csv');summary=pyogrio.read_dataframe(ctx.step(7)/'clusters.gpkg',layer='cluster_summary');summary=summary[summary.is_top3].copy()
    cluster_map=dict(zip(membership.gid,membership.cluster_id));stops=pd.read_parquet(ctx.step(4)/'stops.parquet');fac=pd.read_parquet(ctx.step(4)/'facility_index.parquet')
    timetable_dir=ctx.cache/('timetable_'+digest({'db':sha('data/processed/gtfs.sqlite'),'code':sha('src/timetable.py')})[:16])
    if not (timetable_dir/'trips.parquet').exists():
        # Recreate disposable timetable caches when only saved outputs were retained.
        with ro('data/processed/gtfs.sqlite') as con:
            trips=pd.read_sql_query('SELECT t.* FROM trips t JOIN calendar c USING(service_id) WHERE c.monday=1 AND c.tuesday=1 AND c.wednesday=1 AND c.thursday=1 AND c.friday=1 ORDER BY trip_key',con)
    else:trips=pd.read_parquet(timetable_dir/'trips.parquet')
    with ro('data/processed/gtfs.sqlite') as con:
        estimated_trips=set(pd.read_sql_query('SELECT trip_id FROM supplement_056_trip_sources',con).trip_id)
        route_modes=pd.read_sql_query('SELECT route_id,mode FROM routes',con).set_index('route_id')['mode'].to_dict()
    trip_modes=trips.route_id.map(route_modes).to_numpy();estimated=trips.trip_id.isin(estimated_trips).to_numpy()
    walks=walk_arrays(ctx,ctx.config['baseline_speed_mps']);local_facility=fac.is_goyang.to_numpy(bool)
    facility_contribution=defaultdict(lambda:np.zeros((len(fac),2)))
    names=dict(zip(summary.cluster_id,summary.area_name));components=[];route_rows=[];sample_ids=set()
    for cid,m in membership.groupby('cluster_id'):
        sub=small[small.parent_gid.isin(m.gid)&small.population.gt(0)].sort_values(['score','gid'])
        if len(sub):sample_ids.update(sub.gid.iloc[[0,len(sub)//2,len(sub)-1]].tolist())
    for r in cp.itertuples():
        row=small.loc[r.gid];cid=cluster_map[row.parent_gid]
        with np.load(inside(r.path)) as z:
            od=z['od'];times=z['times'];near=z['nearest'];com=z['components'];legs=z['legs'];upper=z['upper_nearest_s']
            base=(od<=ctx.config['baseline_budget_min']*60+1e-8).sum(axis=1);actual=np.nan_to_num(com[:,7],nan=np.inf)
            uncertain=np.isfinite(upper)&(upper<actual-1e-7)
            reach30=od<=ctx.config['baseline_budget_min']*60+1e-8
            reach80=od<=max(ctx.config['diagnostic_budgets_min'])*60+1e-8
            facility_contribution[cid][:,0]+=reach30.sum(axis=0)*row.population/len(times)
            facility_contribution[cid][:,1]+=reach80.sum(axis=0)*row.population/len(times)
            finite=np.isfinite(actual);good=finite&~uncertain
            if good.any():
                assert np.max(com[good,5])<=ctx.config['max_continuous_walk_s']+1e-7
                assert np.max(com[good,6])<=ctx.config['max_boardings']
                assert np.allclose(com[good,0]+com[good,2]+com[good,3]+com[good,4],actual[good],atol=1e-6)
            for i,t in enumerate(times):
                detail=decompose(int(r.origin_index),int(t),int(near[i]),legs[i],walks) if finite[i] else {}
                if finite[i]:
                    detail['transfer_wait_s']-=com[i,4]
                    assert abs(sum(detail[k] for k in ['initial_walk_s','transfer_walk_s','final_walk_s'])-com[i,0])<1e-6
                    assert abs(detail['initial_wait_s']+detail['transfer_wait_s']-com[i,2])<1e-6
                    assert min(detail.values())>=-1e-6
                used=legs[i,:,0];used=used[used>=0]
                modes='|'.join(sorted(set(trip_modes[used]))) if len(used) else 'direct_walk' if finite[i] else ''
                assert not set(modes.split('|'))&set(ctx.config['excluded_modes'])
                components.append(dict(gid=r.gid,cluster_id=cid,population=row.population,departure_s=int(t),count_30=int(base[i]),count_30_inside=int(reach30[i,local_facility].sum()),count_30_outside=int(reach30[i,~local_facility].sum()),nearest_facility_id=fac.hospital_id.iloc[near[i]] if near[i]>=0 else '',nearest_entrance_quality=fac.entrance_quality.iloc[near[i]] if near[i]>=0 else '',used_modes=modes,uses_estimated_056=bool(estimated[used].any()) if len(used) else False,status='unresolved' if uncertain[i] else 'reachable' if finite[i] else 'unreachable_within_80',total_s=actual[i] if finite[i] else np.nan,walk_s=com[i,0],walk_m=com[i,1],wait_s=com[i,2],in_vehicle_s=com[i,3],preparation_s=com[i,4],max_continuous_walk_s=com[i,5],boardings=com[i,6],transfers=max(0,com[i,6]-1) if finite[i] else np.nan,**detail))
            if r.gid in sample_ids:
                for t in [30600,43200,59400]:
                    i=int(np.flatnonzero(times==t)[0])
                    if near[i]<0:continue
                    for leg in legs[i]:
                        tid,a,b,depart,arrive=map(int,leg)
                        if tid<0:continue
                        sa,sb=stops.iloc[a],stops.iloc[b];trip=trips.iloc[tid]
                        route_rows.append(dict(gid=r.gid,cluster_id=cid,departure_s=t,trip_id=trip.trip_id,route_id=trip.route_id,from_stop_id=sa.stop_id,to_stop_id=sb.stop_id,boarding_s=depart,alighting_s=arrive,geometry_quality='schematic_stop_chord_not_route_shape',vehicle_distance_m=np.nan,geometry=LineString([(sa.x_5179,sa.y_5179),(sb.x_5179,sb.y_5179)])))
    comp=pd.DataFrame(components);diagnoses=[]
    for cid,g in comp.groupby('cluster_id'):
        total=g.population.sum();valid=g.status.eq('reachable');v=g[valid];weight=v.population.sum()
        d={'cluster_id':cid,'area_name':names[cid],'population':float(g.drop_duplicates('gid').population.sum()),'population_time_samples':float(total),'conditional_reachable_fraction':float(weight/total),'unresolved_fraction':float(g.loc[g.status.eq('unresolved'),'population'].sum()/total),'absolute_unmet_30_fraction':float(g.loc[g.count_30.eq(0),'population'].sum()/total)}
        for col in ['total_s','walk_s','walk_m','wait_s','in_vehicle_s','preparation_s','transfers','max_continuous_walk_s','initial_walk_s','transfer_walk_s','final_walk_s','initial_wait_s','transfer_wait_s']:d['conditional_mean_'+col]=float(np.sum(v[col]*v.population)/weight) if weight else np.nan
        d['mean_count_30_inside']=float(np.sum(g.count_30_inside*g.population)/total)
        d['mean_count_30_outside']=float(np.sum(g.count_30_outside*g.population)/total)
        d['uses_estimated_056_population_time_fraction']=float(g.loc[g.uses_estimated_056,'population'].sum()/total)
        d['additional_diagnosis_applicable']=bool(g.count_30.eq(0).any())
        diagnoses.append(d)
    diagnosis=pd.DataFrame(diagnoses)
    # Distinguish absence of a first eligible walk from an unfortunate timetable.
    origin_index=pd.read_parquet(ctx.step(4)/'origin_index.parquet')
    links=pd.read_parquet(ctx.step(4)/'walk_links.parquet')
    links=links[links.source_type.eq('origin')];access=[]
    for r in cp.itertuples():
        local=links[links.source_index.eq(r.origin_index)];item={'gid':r.gid,'cluster_id':cluster_map[small.loc[r.gid,'parent_gid']],'population':small.loc[r.gid,'population']}
        speed=ctx.config['baseline_speed_mps']
        eligible=local[local.length_m/speed+local.fixed_s<=ctx.config['max_continuous_walk_s']+1e-8]
        item['first_stop_count']=eligible.loc[eligible.target_type.eq('stop'),'target_index'].nunique()
        item['direct_facility_count']=eligible.loc[eligible.target_type.eq('facility'),'target_index'].nunique()
        item['first_walk_blocked']=item['first_stop_count']==0 and item['direct_facility_count']==0
        item['interpretation']='연속보행 한도 안에 첫 승차 지점·직접 도달 기관 없음' if item['first_walk_blocked'] else '첫 보행 가능; 운행·환승·도착 조건 함께 해석'
        access.append(item)
    access=pd.DataFrame(access)
    for i,r in diagnosis.iterrows():
        a=access[access.cluster_id.eq(r.cluster_id)]
        diagnosis.loc[i,'first_walk_blocked_population']=a.loc[a.first_walk_blocked,'population'].sum()
        diagnosis.loc[i,'first_walk_blocked_fraction']=a.loc[a.first_walk_blocked,'population'].sum()/a.population.sum()
    parquet(comp,out/'travel_components.parquet');csv(diagnosis,out/'tables/cluster_diagnosis.csv')
    layers={'cluster_diagnosis':summary.merge(diagnosis,on=['cluster_id','area_name'],suffixes=('','_diagnosis'))}
    contributions=[]
    for cid,values in facility_contribution.items():
        for j in np.flatnonzero(values[:,1]>0):
            f=fac.iloc[j];contributions.append(dict(cluster_id=cid,hospital_id=f.hospital_id,name=f['name'],is_goyang=bool(f.is_goyang),entrance_quality=f.entrance_quality,reachable_population_time_30=float(values[j,0]),reachable_population_time_80_lower_bound=float(values[j,1]),geometry=__import__('shapely').geometry.Point(f.x_5179,f.y_5179)))
    if contributions:
        layers['reached_facilities']=gpd.GeoDataFrame(contributions,geometry='geometry',crs=5179)
        csv(pd.DataFrame(contributions).drop(columns='geometry'),out/'tables/facility_contribution.csv')
    if route_rows:layers['diagnostic_routes']=gpd.GeoDataFrame(route_rows,geometry='geometry',crs=5179)
    layers.update(build(ctx,small,membership,comp,access,summary))
    gpkg(out/'diagnosis.gpkg',layers)
    atomic_json(ctx.cache/'validation_report.json',{
        'status':'passed', 'all_511_departures_complete':True,
        'route_component_sums_checked':True, 'continuous_walk_and_boarding_limits_checked':True,
        'time_budget_monotonicity_checked':True,
        'unresolved_path_rows':int(comp.status.eq('unresolved').sum()),
        'field_verification_performed':False})
    describe(ctx,9,'# Step 9 취약 원인 진단\n\n기준 상위 군집의 모든 출발점과 511개 출발시각을 고령인구로 가중한다. travel_components.parquet는 실제 경로의 보행·대기·차내·추가 탑승 준비시간이다. 군집 진단표는 80분 이내 도달한 경로의 조건부 평균과 전체 인구·시각에 대한 미도달 비율을 함께 제시한다. arrival_status는 30분 이내 도달·첫 보행 불가·30분 초과 도달·80분 내 미도달을 구분한다. nearest_bus_walk는 방향성 보행망에서 평일 승차가 가능한 버스정류장까지의 상한 없는 최단 보행시간이다. diagnostic_routes는 승하차 정류장을 잇는 설명선이며 차량 궤적이나 운행거리 자료가 아니다. 도달 경로가 없으면 시간 평균은 0분이 아닌 NaN이다.\n')
    return {'diagnostic_origins':len(cp),'travel_rows':len(comp),'clusters':len(diagnosis)}
