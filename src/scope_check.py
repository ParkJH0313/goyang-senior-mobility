"""Optimistic missing-access envelope, used only to detect affected scores.

These straight-line links are never accepted as real walking connections. Missing
rail entrance locations get the same configured entrance search envelope as access construction.
Only a change in reachable institutions flags a score as unresolved.
"""
import numpy as np,pandas as pd
from scipy.spatial import cKDTree
from src.analysis_io import digest,sha,parquet,ro,log

def potential_links(ctx):
    key=digest({'stops':sha(ctx.step(4)/'stops.parquet'),'code':sha('src/scope_check.py'),'radius':ctx.config['rail_entrance_search_m'],'speeds':ctx.config['walk_speeds_mps'],'cap':ctx.config['max_continuous_walk_s']})[:16]
    target=ctx.cache/('scope_'+key+'.parquet')
    if target.exists():return pd.read_parquet(target)
    s=pd.read_parquet(ctx.step(4)/'stops.parquet');o=pd.read_parquet(ctx.step(4)/'origin_index.parquet');f=pd.read_parquet(ctx.step(4)/'facility_index.parquet')
    # Exact origin points are stored as geometry in Step 2.
    import pyogrio
    points=pyogrio.read_dataframe(ctx.step(2)/'origins.gpkg',layer='origins_250m').set_index('gid').loc[o.gid].geometry
    oxy=np.column_stack([points.x,points.y]);fxy=f[['x_5179','y_5179']].to_numpy();sxy=s[['x_5179','y_5179']].to_numpy()
    st=cKDTree(sxy);ot=cKDTree(oxy);ft=cKDTree(fxy);radius=ctx.config['rail_entrance_search_m'];maximum=max(ctx.config['walk_speeds_mps'])*ctx.config['max_continuous_walk_s'];rows=[]
    unknown=s.connection_status.ne('connected').to_numpy();rail=s.is_rail.to_numpy()
    with ro('data/processed/gtfs.sqlite') as c:trans=pd.read_sql_query('SELECT * FROM transfers',c)
    keys=dict(zip(s.stop_key,s.entity_index));policies={(keys.get(r.from_stop_key),keys.get(r.to_stop_key)):(r.transfer_type,float(r.min_transfer_time) if pd.notna(r.min_transfer_time) else 0.) for r in trans.itertuples()}
    def add(kind,source,targetkind,dest,d,u):
        typ,minimum=policies.get((source,dest),(0,0)) if kind==targetkind=='stop' else (0,0)
        if typ!=3:rows.append((kind,source,targetkind,dest,d,0.,minimum,typ,u))
    for u in np.flatnonzero(unknown):
        point=sxy[u];slack=radius if rail[u] else 0
        for v in st.query_ball_point(point,maximum+slack+radius):
            if v==u:continue
            d=max(0.,np.linalg.norm(point-sxy[v])-slack-(radius if rail[v] else 0))
            if d<=maximum:add('stop',u,'stop',v,d,u);add('stop',v,'stop',u,d,u)
        for v in ot.query_ball_point(point,maximum+slack):add('origin',v,'stop',u,max(0.,np.linalg.norm(point-oxy[v])-slack),u)
        for v in ft.query_ball_point(point,maximum+slack):add('stop',u,'facility',v,max(0.,np.linalg.norm(point-fxy[v])-slack),u)
    frame=pd.DataFrame(rows,columns=['source_type','source_index','target_type','target_index','length_m','fixed_s','min_elapsed_s','transfer_type','unknown_stop']).drop_duplicates()
    parquet(frame,target);log(f'Missing-access influence envelope: {len(frame)} potential links (not used as actual routes)');return frame
