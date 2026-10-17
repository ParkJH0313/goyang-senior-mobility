"""Time means, original-population aggregation and Queen cluster membership."""
import math
import numpy as np,pandas as pd,geopandas as gpd,shapely
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from src.analysis_io import inside,digest

def load_profiles(checkpoints,budget_min):
    profiles=[];nearest=[];components=[]
    for r in checkpoints.itertuples():
        with np.load(inside(r.path)) as z:
            assert len(z['times'])==511
            profiles.append(np.sum(z['od']<=budget_min*60+1e-8,axis=1));nearest.append(z['nearest']);components.append(z['components'])
    return np.asarray(profiles,float),np.asarray(nearest),np.asarray(components)

def weighted_grid(small,large,profiles):
    results=large.copy();curves=np.full((len(large),profiles.shape[1]),np.nan)
    results['score']=np.nan;results['valid_population']=0.;results['score_status']='not_applicable'
    positions={gid:i for i,gid in enumerate(small.gid)}
    for i,r in enumerate(results.itertuples()):
        children=small[small.parent_gid.eq(r.gid)&small.population.gt(0)]
        valid=children[children.score_status.eq('valid')]
        results.loc[results.index[i],'valid_population']=valid.population.sum()
        if r.population<=0:continue
        if abs(valid.population.sum()-r.population)>1e-7:
            results.loc[results.index[i],'score_status']='unresolved_or_excluded_child';continue
        ids=[positions[x] for x in valid.gid];w=valid.population.to_numpy()
        curves[i]=np.sum(profiles[ids]*w[:,None],axis=0)/r.population
        results.loc[results.index[i],'score']=curves[i].mean();results.loc[results.index[i],'score_status']='valid'
    results['valid_population_ratio']=np.where(results.population>0,results.valid_population/results.population,np.nan)
    return results,curves

def clusters(large,cutoff,run_id,topn=3):
    valid=large[large.score_status.eq('valid')&large.population.gt(0)].copy()
    if len(valid)==0:return valid,pd.DataFrame(),pd.DataFrame(),{'valid_grids':0,'reason':'no_complete_population_scores'}
    k=math.ceil(cutoff*len(valid));threshold=float(np.sort(valid.score.to_numpy())[k-1]);low=valid[valid.score<=threshold].copy().reset_index(drop=True)
    # Original square grid centroids preserve adjacency independently of map clipping.
    centers=np.column_stack([low.geometry.centroid.x,low.geometry.centroid.y]);origin=np.min(centers,axis=0)
    indices=np.rint((centers-origin)/500).astype(int);lookup={tuple(x):i for i,x in enumerate(indices)}
    assert len(lookup)==len(low)
    aa=[];bb=[]
    for i,(x,y) in enumerate(indices):
        for dx in [-1,0,1]:
            for dy in [-1,0,1]:
                j=lookup.get((x+dx,y+dy))
                if j is not None and j!=i:aa.append(i);bb.append(j)
    graph=csr_matrix((np.ones(len(aa)),(aa,bb)),shape=(len(low),len(low)))
    _,labels=connected_components(graph,directed=False);low['component']=labels
    rows=[]
    for c,g in low.groupby('component'):
        members=sorted(g.gid);pop=float(g.population.sum());score=float(np.sum(g.population*g.score)/pop)
        rows.append(dict(component=c,population=pop,score=score,anchor_gid=members[0],membership_hash=digest(members),grid_count=len(g),area_km2=float(g.geometry.area.sum()/1e6),run_id=run_id,geometry=shapely.union_all(g.geometry.values)))
    summary=gpd.GeoDataFrame(rows,geometry='geometry',crs=large.crs).sort_values(['population','score','anchor_gid'],ascending=[False,True,True]).reset_index(drop=True)
    summary['rank']=np.arange(1,len(summary)+1);summary['cluster_id']=['C'+str(i).zfill(3) for i in summary['rank']];summary['is_top3']=summary['rank']<=topn
    low=low.merge(summary[['component','cluster_id','rank','membership_hash','is_top3']],on='component',validate='many_to_one')
    membership=low[['gid','cluster_id','rank','population','score','membership_hash','is_top3']].copy();membership['run_id']=run_id
    qa=dict(valid_grids=len(valid),cutoff=cutoff,order_statistic=k,threshold=threshold,tied_at_boundary=int(valid.score.eq(threshold).sum()),selected_grids=len(low),selected_fraction=len(low)/len(valid),queen_tolerance_m=1e-5)
    return low,summary,membership,qa

def bands(times):
    return np.where(times<32400,'08:30–09:00',np.where(times>=57600,'16:00–17:00',[f'{t//3600:02d}:00–{t//3600+1:02d}:00' for t in times]))

def cluster_metrics(small,profiles,membership,times,scenario):
    rows=[];curves=[]
    for cid,m in membership[membership.is_top3].groupby('cluster_id'):
        ids=np.flatnonzero(small.parent_gid.isin(m.gid));weights=small.population.to_numpy()[ids]
        valid=small.iloc[ids].score_status.eq('valid').all() and abs(weights.sum()-m.population.sum())<1e-6
        curve=np.sum(profiles[ids]*weights[:,None],axis=0)/weights.sum() if valid else np.full(len(times),np.nan)
        zero=float(np.sum((profiles[ids]==0).mean(axis=1)*weights)/weights.sum()) if valid else np.nan
        rows.append({'scenario':scenario,'cluster_id':cid,'population':float(m.population.sum()),'score':float(curve.mean()),'zero_origin_time_fraction':zero,'valid':valid,'origin_count':len(ids)})
        curves.extend({'scenario':scenario,'cluster_id':cid,'departure_s':int(t),'count':float(v)} for t,v in zip(times,curve))
    return pd.DataFrame(rows),pd.DataFrame(curves)
