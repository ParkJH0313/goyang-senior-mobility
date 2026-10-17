import pandas as pd,geopandas as gpd
from src.analysis_io import inside,csv,gpkg,describe
from src.spatial_network import GroundNetwork,geometry_overrides,frame
DEPENDENCIES=['steps/step03_facilities.py','src/spatial_network.py','src/analysis_io.py']
SETTINGS=['connector_search_m','crs']

def run(ctx):
    f=pd.read_csv(inside('data/processed/medical_institutions.csv'),dtype={'hospital_id':str})
    assert f.hospital_id.is_unique
    f=gpd.GeoDataFrame(f,geometry=gpd.points_from_xy(f.x_5179,f.y_5179),crs=5179)
    net=GroundNetwork();geos=geometry_overrides();manual=geos[geos.geometry_role.eq('facility_access_proxy')].set_index('target_id')
    rows=[];states=[];reviews=[]
    for r in f.itertuples():
        ref='hospital:'+r.hospital_id
        if ref in manual.index:connection=net.manual(manual.loc[ref],r.geometry);reason=''
        else:connection,reason=net.snap(r.geometry,ctx.config['connector_search_m'])
        states.append('connected' if connection else 'connector_unresolved')
        if connection:rows.append(dict(entity_id=r.hospital_id,entity_type='facility',**connection))
        else:reviews.append(dict(target_id=r.hospital_id,name=r.name,reason=reason,step=3))
    f['connection_status']=states;f['entrance_quality']='address_proxy_not_verified_outpatient_entrance'
    out=ctx.step(3);gpkg(out/'facilities.gpkg',{'facilities':f,'destination_connectors':frame(rows)})
    csv(f.drop(columns='geometry'),out/'tables/facility_status.csv')
    describe(ctx,3,'# Step 3 의료기관과 도착 접속\n\n`steps/step03_facilities.py`는 processed에서 선정된 기관 ID·전문의 자격·좌표를 유지한다. facilities는 기관 위치와 출처, destination_connectors는 도착 전용 접속선이다. 31개 승인 주소 대리점과 접속선을 우선 적용하며, 같은 좌표의 다른 기관 ID는 별개 공급이다. 주소를 실제 외래 출입구로 표현하지 않는다. facility_status에 전체 기관 상태를 기록한다.\n')
    return {'facilities':len(f),'connected':len(rows),'unresolved':len(reviews)}
