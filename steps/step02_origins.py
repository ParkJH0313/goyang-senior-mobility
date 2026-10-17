import numpy as np,pandas as pd,pyogrio,shapely
from src.analysis_io import inside,csv,gpkg,describe,log
from src.spatial_network import GroundNetwork,geometry_overrides,frame
DEPENDENCIES=['steps/step02_origins.py','src/spatial_network.py','src/analysis_io.py']
SETTINGS=['connector_search_m','crs']

def run(ctx):
    origins=pyogrio.read_dataframe(ctx.step(1)/'population.gpkg',layer='population_250m')
    origins=origins[origins.analysis_status.eq('included')].copy()
    coverage=pyogrio.read_dataframe(inside('data/processed/residential_buildings.gpkg'),layer='residential_coverage').geometry.iloc[0]
    geos=geometry_overrides();manual=geos[geos.geometry_role.eq('origin_access_proxy')].set_index('target_id')
    net=GroundNetwork();rows=[];reviews=[];areas=[];methods=[];points=[];states=[]
    for k,r in enumerate(origins.itertuples()):
        cut=coverage.intersection(r.geometry);areas.append(cut.area)
        point=cut.centroid if cut.area>0 else r.geometry.centroid;points.append(point)
        method='residential_area_centroid' if cut.area>0 else 'provisional_grid_centroid';methods.append(method)
        ref='grid:'+r.gid
        if ref in manual.index:connection=net.manual(manual.loc[ref],point);reason=''
        else:connection,reason=net.snap(point,ctx.config['connector_search_m'])
        state='connected' if connection else 'connector_unresolved';states.append(state)
        if connection:rows.append(dict(entity_id=r.gid,entity_type='origin',**connection))
        else:reviews.append(dict(target_id=r.gid,reason=reason,population=r.population,step=2))
        if k%250==0:log(f'Origin connections {k}/{len(origins)}')
    origins['residential_area_m2']=areas;origins['origin_method']=methods;origins['connection_status']=states;origins.geometry=points
    connections=frame(rows);out=ctx.step(2)
    corrections=geos[geos.geometry_role.eq('ground_network_join')].copy()
    gpkg(out/'origins.gpkg',{'origins_250m':origins,'origin_connectors':connections,'network_corrections':corrections})
    csv(origins.drop(columns='geometry'),out/'tables/origin_status.csv')
    describe(ctx,2,'# Step 2 주거 대표점과 보행 접속\n\n`steps/step02_origins.py`는 주거 합집합을 격자로 자른 면적 중심을 계산한다. 주거 없는 유인구 격자는 잠정 중심으로 표시한다. `src/spatial_network.py`는 지상·통행권한·기록된 장벽을 검사하고 승인된 접속선을 우선한다. origin_connectors는 출발 전용이며 망 전체의 지름길로 쓰지 않는다. network_corrections는 Step 4에서 공용 망에 적용하는 승인 도형이다. tables/origin_status는 산정 방식·접속 상태·면적·인구를 담는다.\n')
    return {'origins':len(origins),'connected':len(rows),'unresolved':len(reviews),'provisional_centroids':methods.count('provisional_grid_centroid')}
