import numpy as np,pandas as pd,pyogrio
from src.analysis_io import inside,csv,parquet,gpkg,atomic_json,describe
from src.routing_runner import calculate
from src.aggregation import load_profiles,clusters,cluster_metrics
from steps.step07_clusters import label_clusters
DEPENDENCIES=['steps/step08_sensitivity.py','src/aggregation.py','src/router.py','src/routing_runner.py','src/timetable.py','src/scope_check.py','src/analysis_io.py']
SETTINGS=['sensitivity_budgets_min','cutoffs','top_clusters','diagnostic_budgets_min','baseline_speed_mps','baseline_budget_min']

def run(ctx):
    small=pyogrio.read_dataframe(ctx.step(6)/'accessibility.gpkg',layer='accessibility_250m');large=pyogrio.read_dataframe(ctx.step(6)/'accessibility.gpkg',layer='accessibility_500m')
    membership=pd.read_csv(ctx.step(7)/'tables/cluster_membership.csv');summary=pyogrio.read_dataframe(ctx.step(7)/'clusters.gpkg',layer='cluster_summary')
    top=membership[membership.is_top3];orig=pd.read_parquet(ctx.step(4)/'origin_index.parquet');indices=list(orig.index[orig.parent_gid.isin(top.gid)])
    small=small[small.gid.isin(orig.loc[indices,'gid'])].sort_values('gid').reset_index(drop=True)
    times=np.arange(ctx.config['departure_start_s'],ctx.config['departure_end_s']+1,ctx.config['departure_interval_s']);out=ctx.step(8)
    metrics=[];profiles=[];manifests=[];counts_by_budget={}
    baseline_budget=ctx.config['baseline_budget_min'];baseline_speed=ctx.config['baseline_speed_mps']
    def scoped_population(checkpoints,budget):
        f=small.copy();bad=[]
        for r in checkpoints.itertuples():
            with np.load(inside(r.path)) as z:
                j=int(np.flatnonzero(z['budgets']==budget)[0]);known=np.sum(z['od']<=budget*60+1e-8,axis=1)
                if np.any(z['upper_counts'][:,j]>known):bad.append(r.gid)
        f.loc[f.gid.isin(bad),'score_status']='connector_unresolved'
        return f
    # The exact 80-minute search is shared with Step 9; S1 only reports 30/40/50.
    cp=calculate(ctx,indices,ctx.config['baseline_speed_mps'],max(ctx.config['diagnostic_budgets_min']))
    assert list(cp.gid)==list(small.gid), 'Origin/profile alignment'
    parquet(cp,out/'extended_checkpoint.parquet')
    baseline_cp=pd.read_parquet(ctx.step(5)/'routing_checkpoint.parquet');basecounts,_,_=load_profiles(baseline_cp[baseline_cp.origin_index.isin(indices)],baseline_budget)
    for b in ctx.config['sensitivity_budgets_min']:
        curves,_,_=load_profiles(cp,b)
        counts_by_budget[b]=curves
        if b==baseline_budget:np.testing.assert_array_equal(curves,basecounts)
        m,p=cluster_metrics(scoped_population(cp,b),curves,top,times,'budget_'+str(b));m['kind']='budget';m['value']=b;metrics.append(m);profiles.append(p)
        manifests.append(dict(scenario='budget_'+str(b),speed=baseline_speed,budget_min=b,origins=len(indices),membership='baseline_top3_membership'))
    budget_order=sorted(counts_by_budget)
    for a,b in zip(budget_order,budget_order[1:]):assert np.all(counts_by_budget[a]<=counts_by_budget[b])
    metrics=pd.concat(metrics,ignore_index=True);profiles=pd.concat(profiles,ignore_index=True);base=metrics[metrics.scenario.eq('budget_'+str(baseline_budget))].set_index('cluster_id').score;metrics['delta']=metrics.score-metrics.cluster_id.map(base)
    sets=set(top.gid);pop=large.set_index('gid').population.to_dict();overlaps=[];cross=[];layers={};spatial={}
    for q in ctx.config['cutoffs']:
        low,cs,cm,qa=clusters(large,q,ctx.run_id,ctx.config['top_clusters']);cs=label_clusters(cs);low['area_name']=low.cluster_id.map(cs.set_index('cluster_id').area_name);layers[q]=low
        other=set(cm.loc[cm.is_top3,'gid']);union=sets|other;intersection=sets&other
        overlaps.append(dict(cutoff=q,grid_jaccard=len(intersection)/len(union) if union else np.nan,population_jaccard=sum(pop[x] for x in intersection)/sum(pop[x] for x in union) if union else np.nan,top3_population=sum(pop[x] for x in other),top3_grids=len(other),**{k:v for k,v in qa.items() if k!='cutoff'}))
        for cid,group in top.groupby('cluster_id'):
            for target,m in cm.groupby('cluster_id'):
                shared=set(group.gid)&set(m.gid)
                if shared:
                    destination=cs[cs.cluster_id.eq(target)].iloc[0]
                    cross.append(dict(cutoff=q,baseline_cluster=cid,scenario_cluster=target,scenario_name=destination.area_name,scenario_rank=int(m['rank'].iloc[0]),scenario_population=destination.population,shared_grids=len(shared),shared_population=sum(pop[x] for x in shared)))
        spatial[f'cutoff_{int(q*100)}_grids']=low;spatial[f'cutoff_{int(q*100)}_clusters']=cs
        csv(cm,out/f'tables/cutoff_{int(q*100)}_membership.csv');csv(cs.drop(columns='geometry'),out/f'tables/cutoff_{int(q*100)}_summary.csv')
    ov=pd.DataFrame(overlaps);cw=pd.DataFrame(cross)
    csv(metrics,out/'tables/sensitivity_cluster_metrics.csv');parquet(profiles,out/'sensitivity_minute_profiles.parquet');csv(ov,out/'tables/top3_overlap.csv');csv(cw,out/'tables/cluster_crosswalk.csv');csv(pd.DataFrame(manifests),out/'tables/scenario_manifest.csv');gpkg(out/'sensitivity.gpkg',spatial)
    for checkpoint in out.glob('speed_*_checkpoint.parquet'):
        assert checkpoint.resolve().is_relative_to(out.resolve());checkpoint.unlink()
    describe(ctx,8,f'# Step 8 민감도\n\n`steps/step08_sensitivity.py`는 기준 상위 3개 군집의 모든 양의 인구 출발점을 고정해 기본 보행속도를 유지한 채 시간예산 30/40/50분을 비교한다. 기본 {baseline_speed:g}m/s의 정확한 80분 탐색은 Step 9와 공유하며 이 Step의 시간예산 표·그림에는 30/40/50분만 사용한다. 하위 25/30/35%는 전체 유효 격자에서 Queen 군집과 인구 순위를 다시 구한다. sensitivity.gpkg는 각 비율의 격자·군집, tables는 군집별 점수·0기관 비율·변화량·Jaccard·분리/병합 중첩이다. PNG는 별도 표현 모듈에서 저장된 계산값으로 생성한다. 시간예산 증가에 따른 도달 기관 수 비감소와 넓은 탐색에서 꺼낸 기준 점수의 일치를 검사했다.\n')
    return {'top3_origins':len(indices),'scenarios':len(manifests)+3,'time_budget_monotonic':True}
