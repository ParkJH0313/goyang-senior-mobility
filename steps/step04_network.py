"""Integrate approved spatial corrections and stop-specific access/transfer processes."""
import re,json
import numpy as np,pandas as pd,geopandas as gpd,pyogrio,shapely
from shapely.geometry import Point,LineString
from src.analysis_io import inside,ro,csv,gpkg,parquet,atomic_npz,atomic_json,describe,log,digest,sha,read_json
from src.spatial_network import GroundNetwork,geometry_overrides,frame,build_graph
from src.walking import closure
from src.stop_access import Crossings,StopAccess,StationEntrances,central_stop
DEPENDENCIES=['steps/step04_network.py','src/spatial_network.py','src/stop_access.py','src/walking.py','src/analysis_io.py']
SETTINGS=['connector_search_m','rail_entrance_search_m','median_crossing_search_m','station_group_radius_m','station_second_gap_m','station_second_ratio','stop_ground_fallback_m','stop_poi_search_m','stop_road_evidence_m','rail_entrance_s','rail_transfer_s','same_platform_s','transfer_preparation_s','max_continuous_walk_s','baseline_speed_mps','excluded_modes','service_profile_id']

def station_name(s):return re.sub(r'\([^)]*\)|\[[^]]*\]|\s','',str(s)).removesuffix('역')

def run(ctx):
    out=ctx.step(4);net=GroundNetwork();geos=geometry_overrides();crossings=Crossings(net)
    with ro('data/processed/gtfs.sqlite') as c:
        stops=pd.read_sql_query('SELECT * FROM stops ORDER BY stop_id',c)
        routes=pd.read_sql_query('SELECT * FROM routes',c)
        rail=set(pd.read_sql_query("SELECT DISTINCT ps.stop_key FROM pattern_stops ps JOIN patterns p USING(pattern_id) JOIN routes r USING(route_id) WHERE r.mode<>'local_bus'",c).stop_key)
        transfers=pd.read_sql_query('SELECT * FROM transfers',c)
        cal=pd.read_sql_query('SELECT * FROM calendar',c)
    assert not routes['mode'].isin(ctx.config['excluded_modes']).any()
    stops['entity_index']=np.arange(len(stops));stops['is_rail']=stops.stop_key.isin(rail)
    stops['station_name']=stops.stop_name.map(station_name)
    stopkey=dict(zip(stops.stop_key,stops.entity_index));stopids=dict(zip(stops.stop_id,stops.entity_index))
    surfaces=geos[geos.geometry_role.eq('station_surface_access')].set_index('target_id')
    selected=geos[geos.geometry_role.isin(['assumed_median_crossing','ordinary_wall_access_assumption'])].drop_duplicates('target_id').set_index('target_id')
    stop_lookup=stops.set_index('stop_id');aliases={}
    for ref,r in selected.iterrows():
        original=stop_lookup.loc[ref.split(':',1)[1]]
        aliases[(original.stop_name,float(original.x_5179),float(original.y_5179))]=r
    bus_access=StopAccess(net,ctx.config);entrances=StationEntrances(net,stops,ctx.config,transfers)
    rows=[];status=[];reviews=[]
    cache=ctx.cache/('stop_access_'+digest({'input':ctx.input_id,'code':sha('steps/step04_network.py'),'spatial':sha('src/spatial_network.py'),'settings':{k:ctx.config[k] for k in SETTINGS}})[:16]);cache.mkdir(parents=True,exist_ok=True)
    cached=(cache/'complete.json').exists()
    if cached:
        rows=gpd.read_parquet(cache/'access.parquet').to_dict('records');saved=read_json(cache/'complete.json');status=saved['status'];reviews=saved['reviews'];log('Reusing completed stop-access checkpoint')
    for i,r in enumerate([] if cached else stops.itertuples()):
        point=Point(r.x_5179,r.y_5179);ref='gtfs_stop:'+r.stop_id;connections=[];reason=''
        if ref in surfaces.index:
            con=net.manual(surfaces.loc[ref],point,ctx.config['rail_entrance_s']);connections=[con]
        elif ref in selected.index:connections=[net.manual(selected.loc[ref],point)]
        elif (r.stop_name,float(r.x_5179),float(r.y_5179)) in aliases:
            con=net.manual(aliases[(r.stop_name,float(r.x_5179),float(r.y_5179))],point);con['connection_status']='same_physical_stop_override_alias';connections=[con]
        elif r.is_rail:
            connections=entrances.for_stop(r.stop_id)
            if not connections:reason='rail_entrance_not_resolved'
        elif central_stop(r.stop_name):
            con,reason=crossings.connect(point,ctx.config['median_crossing_search_m'])
            if con:connections=[con]
        else:
            con,reason=bus_access.connect(point,r.stop_name)
            if con:connections=[con]
        state='connected' if connections else 'connector_unresolved'
        if not connections and point.distance(net.ground.geometry.iloc[net.ground_tree.nearest(point)])>ctx.config['connector_search_m']:state='outside_walk_coverage';reason=state
        status.append(state)
        for con in connections:rows.append(dict(entity_id=r.stop_id,entity_type='stop',entity_index=r.entity_index,**con))
        if state=='connector_unresolved':reviews.append(dict(target_id=r.stop_id,name=r.stop_name,reason=reason,step=4,review_scope='route_influence_to_be_checked'))
        if i%2000==0:log(f'Stop access {i}/{len(stops)}')
    stops['connection_status']=status
    if not cached:
        parquet(frame(rows),cache/'access.parquet');atomic_json(cache/'complete.json',{'status':status,'reviews':reviews})
    orig=pyogrio.read_dataframe(ctx.step(2)/'origins.gpkg',layer='origins_250m').sort_values('gid').reset_index(drop=True)
    fac=pyogrio.read_dataframe(ctx.step(3)/'facilities.gpkg',layer='facilities').sort_values('hospital_id').reset_index(drop=True)
    oc=pyogrio.read_dataframe(ctx.step(2)/'origins.gpkg',layer='origin_connectors');fc=pyogrio.read_dataframe(ctx.step(3)/'facilities.gpkg',layer='destination_connectors')
    oc['entity_index']=oc.entity_id.map(dict(zip(orig.gid,orig.index)));fc['entity_index']=fc.entity_id.map(dict(zip(fac.hospital_id,fac.index)))
    conns=gpd.GeoDataFrame(pd.concat([oc,fc,frame(rows)],ignore_index=True),geometry='geometry',crs=5179)
    ptr,idx,length,conns,node_ids=build_graph(net,conns,geos)
    atomic_npz(out/'walk_graph.npz',indptr=ptr,indices=idx,length_m=length)
    parquet(pd.DataFrame({'node_id':node_ids,'node_index':np.arange(len(node_ids))}),out/'graph_nodes.parquet')
    parquet(conns,out/'connections.parquet')
    walks=closure(ctx,ptr,idx,length,conns)
    extra=[]
    for r in stops.itertuples():extra.append(('stop',r.entity_index,'stop',r.entity_index,0.,ctx.config['rail_transfer_s'] if r.is_rail else 0.))
    # Explicit original rail transfers define actual transfer pairs, not proximity alone.
    for r in transfers.itertuples():
        a,b=stopkey.get(r.from_stop_key),stopkey.get(r.to_stop_key)
        if a is None or b is None or r.transfer_type==3:continue
        aa,bb=stops.iloc[a],stops.iloc[b]
        if aa.is_rail and bb.is_rail and aa.station_name==bb.station_name:
            extra.append(('stop',a,'stop',b,0.,ctx.config['rail_transfer_s']))
    walks=pd.concat([walks,pd.DataFrame(extra,columns=walks.columns)],ignore_index=True)
    walks['min_elapsed_s']=0.;walks['transfer_type']=0
    lookup={(stopkey.get(r.from_stop_key),stopkey.get(r.to_stop_key)):(r.transfer_type,float(r.min_transfer_time) if pd.notna(r.min_transfer_time) else 0.) for r in transfers.itertuples()}
    mask=walks.source_type.eq('stop')&walks.target_type.eq('stop')
    policy=[lookup.get((int(a),int(b)),(0,0.)) for a,b in zip(walks.loc[mask,'source_index'],walks.loc[mask,'target_index'])]
    walks.loc[mask,'transfer_type']=[p[0] for p in policy];walks.loc[mask,'min_elapsed_s']=[p[1] for p in policy]
    walks=walks[walks.transfer_type.ne(3)].sort_values(['length_m','fixed_s']).drop_duplicates(['source_type','source_index','target_type','target_index','fixed_s'])
    parquet(walks,out/'walk_links.parquet');parquet(stops,out/'stops.parquet')
    parquet(orig.drop(columns='geometry'),out/'origin_index.parquet');parquet(fac.drop(columns='geometry'),out/'facility_index.parquet')
    gpkg(out/'network.gpkg',{'stop_access':conns[conns.entity_type.eq('stop')],'stops':gpd.GeoDataFrame(stops,geometry=gpd.points_from_xy(stops.x_5179,stops.y_5179),crs=5179),'network_corrections':geos[geos.geometry_role.eq('ground_network_join')]})
    parquet(conns,out/'connections.parquet');csv(routes,out/'tables/eligible_routes.csv');csv(cal,out/'tables/service_profile.csv')
    atomic_json(out/'network_qa.json',{'status_counts':stops.connection_status.value_counts().to_dict(),'graph_nodes':len(node_ids),'directed_arcs':len(idx),'walking_links':len(walks),'continuous_walk_basis':'source access + bounded directed ground path + target access + fixed internal walking; no reset at intermediate stop','service_profile_id':ctx.config['service_profile_id'],'missing_access_not_zero':True})
    describe(ctx,4,'# Step 4 交通網 통합\n\n`steps/step04_network.py`는 지정 수단만 유지하고 승인된 망 연결·출입구·중앙정류장 보정을 적용한다. `src/spatial_network.py`는 방향을 유지해 엣지 중간을 분할하며 `src/walking.py`는 연속보행 범위의 방향성 최단거리를 계산한다. walk_graph.npz와 graph_nodes.parquet가 계산용 거리망, walk_links.parquet는 출발/환승/도착의 거리·고정시간·원래 최소 환승시간이다. 정류장을 경유해 보행시간을 초기화하지 않는다. network.gpkg의 stops는 접속 상태, stop_access는 실제 사용한 접속선, network_corrections는 승인 연결이다. 역 내부 통로는 일반 지상망의 지름길로 추가하지 않는다. 원릉 B·송추·운정 출입구를 지정선으로 적용하고 운정 A↔B는 지상 경유한다.\n')
    return {'stops':len(stops),'access_points':len(rows),'graph_arcs':len(idx),'walk_links':len(walks),'unresolved_stop_candidates':len(reviews)}

def approved_table(table):
    from src.preprocessing_common import approved
    return approved(table+'_decisions.csv')
