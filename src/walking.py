"""Bounded directed walking closure; no stop visit resets continuous walking."""
import heapq
import numpy as np,pandas as pd
from numba import njit
from src.analysis_io import log,parquet

@njit(cache=True)
def bounded(indptr,indices,cost,start,limit,dist,stamp,epoch):
    heap=[(0.0,start)];dist[start]=0.;stamp[start]=epoch;nodes=[];values=[]
    while heap:
        value,u=heapq.heappop(heap)
        if value>dist[u]+1e-10:continue
        nodes.append(u);values.append(value)
        for j in range(indptr[u],indptr[u+1]):
            v=np.int64(indices[j]);new=value+cost[j]
            if new<=limit+1e-9 and (stamp[v]!=epoch or new<dist[v]-1e-9):
                dist[v]=new;stamp[v]=epoch;heapq.heappush(heap,(new,v))
    return nodes,values

def closure(ctx,indptr,indices,length,conns):
    from collections import defaultdict
    targets=defaultdict(list)
    for r in conns[conns.entity_type.isin(['stop','facility'])].itertuples():targets[r.graph_node].append(r)
    dist=np.empty(len(indptr)-1);stamp=np.zeros(len(dist),np.int64);epoch=0;rows=[]
    speed=max(ctx.config['walk_speeds_mps']);cap=ctx.config['max_continuous_walk_s']
    sources=conns[conns.entity_type.isin(['origin','stop'])]
    for i,r in enumerate(sources.itertuples()):
        budget=(cap-r.fixed_s)*speed-r.length_m
        if budget<0:continue
        epoch+=1;nodes,values=bounded(indptr,indices,length,int(r.graph_node),budget,dist,stamp,epoch)
        for node,d in zip(nodes,values):
            for t in targets.get(node,[]):
                if r.entity_type=='stop' and t.entity_type=='stop' and r.entity_index==t.entity_index:continue
                total=r.length_m+d+t.length_m;fixed=r.fixed_s+t.fixed_s
                if total/speed+fixed<=cap+1e-8:rows.append((r.entity_type,int(r.entity_index),t.entity_type,int(t.entity_index),total,fixed))
        if i%1000==0:log(f'Walking closure {i}/{len(sources)}, links {len(rows)}')
    f=pd.DataFrame(rows,columns=['source_type','source_index','target_type','target_index','length_m','fixed_s'])
    # Each entity has a fixed entry/exit process; retain each non-dominated cost kind.
    f=f.sort_values('length_m').drop_duplicates(['source_type','source_index','target_type','target_index','fixed_s'])
    return f.reset_index(drop=True)
