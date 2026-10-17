import numpy as np,pandas as pd,pyogrio
from src.analysis_io import csv,parquet,gpkg,atomic_npz,describe
from src.aggregation import load_profiles,weighted_grid,bands
DEPENDENCIES=['steps/step06_accessibility.py','src/aggregation.py','src/analysis_io.py']
SETTINGS=['baseline_budget_min','departure_start_s','departure_end_s','departure_interval_s']

def run(ctx):
    cp=pd.read_parquet(ctx.step(5)/'routing_checkpoint.parquet');curves,_,_=load_profiles(cp,ctx.config['baseline_budget_min'])
    small=pyogrio.read_dataframe(ctx.step(1)/'population.gpkg',layer='population_250m').sort_values('gid').reset_index(drop=True)
    large=pyogrio.read_dataframe(ctx.step(1)/'population.gpkg',layer='population_500m').sort_values('gid').reset_index(drop=True)
    times=np.arange(ctx.config['departure_start_s'],ctx.config['departure_end_s']+1,ctx.config['departure_interval_s']);allcurves=np.full((len(small),len(times)),np.nan)
    lookup=dict(zip(small.gid,small.index));positions=[lookup[x] for x in cp.gid];allcurves[positions]=curves
    small['score']=allcurves.mean(axis=1);small['completed_departures']=np.sum(np.isfinite(allcurves),axis=1)
    small['score_status']=np.where(small.completed_departures.eq(len(times)),'valid',small.analysis_status)
    small['score_lower_bound']=small['score']
    uncertain=set(cp.loc[cp.uncertain_departures.gt(0),'gid'])
    mask=small.gid.isin(uncertain);small.loc[mask,'score_status']='connector_unresolved';small.loc[mask,'score']=np.nan;allcurves[mask.to_numpy()]=np.nan
    origin_status=pyogrio.read_dataframe(ctx.step(2)/'origins.gpkg',layer='origins_250m')
    missing_origin=set(origin_status.loc[origin_status.connection_status.ne('connected'),'gid'])
    mask=small.gid.isin(missing_origin);small.loc[mask,'score_status']='origin_connector_unresolved';small.loc[mask,'score']=np.nan;allcurves[mask.to_numpy()]=np.nan
    destination_status=pyogrio.read_dataframe(ctx.step(3)/'facilities.gpkg',layer='facilities')
    if destination_status.connection_status.ne('connected').any():
        # Never turn a missing destination into a confirmed zero opportunity.
        mask=small.gid.isin(cp.gid);small.loc[mask,'score_status']='destination_scope_unresolved';small.loc[mask,'score']=np.nan;allcurves[mask.to_numpy()]=np.nan
    small['zero_time_fraction']=np.mean(allcurves==0,axis=1);small.loc[small.score_status.ne('valid'),'zero_time_fraction']=np.nan
    large,hcurves=weighted_grid(small,large,allcurves)
    for r in large[large.score_status.eq('valid')].itertuples():
        c=small[small.parent_gid.eq(r.gid)];assert abs(np.sum(c.population*c.score.fillna(0))/r.population-r.score)<1e-7
    out=ctx.step(6);gpkg(out/'accessibility.gpkg',{'accessibility_250m':small,'accessibility_500m':large})
    csv(small.drop(columns='geometry'),out/'tables/accessibility_250m.csv');csv(large.drop(columns='geometry'),out/'tables/accessibility_500m.csv')
    atomic_npz(out/'minute_profiles.npz',times=times,gid_250m=small.gid.to_numpy(str),gid_500m=large.gid.to_numpy(str),profiles_250m=allcurves,profiles_500m=hcurves)
    labels=bands(times);rows=[]
    for level,frame,profiles in [(250,small,allcurves),(500,large,hcurves)]:
        for label in pd.unique(labels):
            mask=labels==label
            for i,r in enumerate(frame.itertuples()):
                a=profiles[i,mask];ok=np.isfinite(a).all()
                rows.append(dict(grid_m=level,gid=r.gid,time_band=label,samples=int(mask.sum()),mean=float(a.mean()) if ok else np.nan,zero_fraction=float(np.mean(a==0)) if ok else np.nan,minimum=float(a.min()) if ok else np.nan,maximum=float(a.max()) if ok else np.nan))
    csv(pd.DataFrame(rows),out/'tables/time_band_summary.csv')
    cov=large.groupby('score_status').agg(grids=('gid','size'),population=('population','sum')).reset_index();csv(cov,out/'tables/coverage_summary.csv')
    describe(ctx,6,'# Step 6 접근성 집계\n\n`steps/step06_accessibility.py`는 511개 시각을 같은 비중으로 평균하고, `src/aggregation.py`는 원래 부모 인구를 분모로 500m 점수·곡선을 계산한다. 일부 자식 제외/미해결이면 부모 정식 점수는 비워 두며 유효 인구와 비율을 별도로 표시한다. accessibility.gpkg의 두 레이어는 250m·500m 점수와 상태다. minute_profiles.npz는 원래 매분 곡선, time_band_summary는 표본 수를 포함한 설명용 시간대 표다. 점수 단위는 도달 의료기관 수(곳), 기관별 전문의 수는 공급 가중치가 아니다.\n')
    return {'valid_250m':int(small.score_status.eq('valid').sum()),'valid_500m':int(large.score_status.eq('valid').sum()),'excluded_or_unresolved_500m':int(large.score_status.eq('unresolved_or_excluded_child').sum())}
