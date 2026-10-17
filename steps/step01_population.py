"""Preserve joint population estimates, exclusions and original denominators."""
import numpy as np,pandas as pd,pyogrio
from src.analysis_io import inside,csv,gpkg,describe
from src.preprocessing_common import approved
DEPENDENCIES=['steps/step01_population.py','src/analysis_io.py']
SETTINGS=['methodology','crs']

def run(ctx):
    p=inside('data/processed/elderly_population.gpkg');small=pyogrio.read_dataframe(p,layer='elderly_250m');large=pyogrio.read_dataframe(p,layer='elderly_500m')
    assert small.gid.is_unique and large.gid.is_unique
    for f in [small,large]:
        f['population_raw']=f.lbl.fillna('').astype(str);f['population']=f.population_estimated
        f['analysis_status']=np.where(f.population>0,'included','zero_population')
        assert f.population.notna().all() and (f.population>=0).all()
        assert f.loc[f.population_status.eq('blank_as_zero'),'population'].eq(0).all()
        mask=f.population_status.isin(['masked_zero','masked_explicit']);assert f.loc[mask,'population'].between(1,5).all()
    small['exclusion_reason']=''
    for r in approved('origin_decisions.csv'):
        if r['action']=='exclude_analysis_origin':
            sel=small.gid.eq(r['expected']['gid']);assert sel.sum()==1
            small.loc[sel,'analysis_status']='excluded';small.loc[sel,'exclusion_reason']=r['reason']
    totals=small.groupby('parent_gid').population.sum();expected=large.set_index('gid').population
    assert set(totals.index)<=set(expected.index)
    assert np.allclose(totals,expected.loc[totals.index],rtol=0,atol=1e-7)
    small['parent_population']=small.parent_gid.map(expected)
    small['population_weight']=np.where(small.parent_population>0,small.population/small.parent_population,0)
    valid=small[small.analysis_status.eq('included')].groupby('parent_gid').population.sum()
    large['included_population']=large.gid.map(valid).fillna(0)
    large['coverage_ratio']=np.where(large.population>0,large.included_population/large.population,np.nan)
    large.loc[(large.population>0)&(large.coverage_ratio<1-1e-9),'analysis_status']='partial_exclusion'
    out=ctx.step(1);gpkg(out/'population.gpkg',{'population_250m':small,'population_500m':large})
    weights=small[['gid','parent_gid','population_raw','population_status','population','population_min','population_max','joint_solution_count','parent_population','population_weight','analysis_status','exclusion_reason']]
    csv(weights,out/'tables/parent_child_weights.csv')
    qa=pd.DataFrame([{'check':'joint_parent_sum','passed':True},{'check':'raw_blank_zero_and_masked_bounds','passed':True},{'check':'excluded_population_preserved','passed':True}]);csv(qa,out/'tables/population_qa.csv')
    describe(ctx,1,'# Step 1 고령인구와 집계 가중치\n\n`steps/step01_population.py`는 processed의 공동 추정 인구를 검사하고 원래 인구 분모와 분석 제외를 분리한다. `population.gpkg`의 population_250m은 출발 격자, population_500m은 부모 격자다. tables의 parent_child_weights는 원자료 상태·범위·조합 수·가중치, population_qa는 검사 결과다. 군부대 인구는 삭제하거나 0으로 바꾸지 않는다.\n')
    return {'population':float(small.population.sum()),'positive_origins':int((small.population>0).sum()),'included_origins':int(small.analysis_status.eq('included').sum()),'excluded_population':float(small.loc[small.analysis_status.eq('excluded'),'population'].sum())}
