import pandas as pd,pyogrio,shapely
from src.analysis_io import inside,csv,gpkg,atomic_json,describe
from src.aggregation import clusters
from src.cluster_labels import area_label
DEPENDENCIES=['steps/step07_clusters.py','src/aggregation.py','src/analysis_io.py','src/cluster_labels.py']
SETTINGS=['baseline_cutoff','top_clusters']

def label_clusters(summary):
    if not len(summary):return summary
    dong=pyogrio.read_dataframe(inside('data/processed/boundaries.gpkg'),layer='goyang_dong')
    names=[x for x in dong.columns if 'nm' in x.lower() or 'name' in x.lower()];name=names[0]
    labels=[]
    for r in summary.itertuples():
        area=dong.geometry.intersection(r.geometry).area;order=area.sort_values(ascending=False);chosen=order[order>0].index[:3]
        labels.append(area_label('·'.join(dong.loc[chosen,name].astype(str))))
    summary['area_name']=labels;return summary

def run(ctx):
    f=pyogrio.read_dataframe(ctx.step(6)/'accessibility.gpkg',layer='accessibility_500m')
    low,summary,membership,qa=clusters(f,ctx.config['baseline_cutoff'],ctx.run_id,ctx.config['top_clusters']);summary=label_clusters(summary)
    out=ctx.step(7);gpkg(out/'clusters.gpkg',{'low_access_500m':low,'cluster_summary':summary})
    csv(membership,out/'tables/cluster_membership.csv');csv(membership[membership.is_top3] if len(membership) else membership,out/'tables/baseline_top3_membership.csv')
    csv(summary.drop(columns='geometry') if len(summary) else summary,out/'tables/cluster_summary.csv');atomic_json(out/'cluster_qa.json',qa)
    describe(ctx,7,'# Step 7 Queen 저접근 군집\n\n`steps/step07_clusters.py`와 `src/aggregation.py`는 유효 500m 점수의 ceil(0.30N) 순서통계량을 경계로 동점을 모두 포함한다. 원래 격자의 변/꼭짓점 8방향 연결요소를 사용하며 단독 격자를 유지한다. 인구 내림차순, 점수 오름차순, 최소 격자 ID 순으로 순위를 정한다. clusters.gpkg의 low_access_500m은 선정 격자, cluster_summary는 군집 도형과 인구·점수다. baseline_top3_membership은 이번 실행에서 새로 선정한 상위 군집의 고정 구성 목록이다. 과거 가좌동·송포동 선정 목록을 입력하지 않는다.\n')
    return {'clusters':len(summary),'top_clusters':int(summary.is_top3.sum()) if len(summary) else 0,**qa}
