"""Reconstruct physical and waiting components of selected timetable itineraries."""
import numpy as np


def lookup(pack,source,target):
    a,b=pack[0][source:source+2]
    ids=pack[1][a:b];j=int(np.searchsorted(ids,target))
    if j==len(ids) or ids[j]!=target:raise ValueError('Selected path has no eligible walking leg')
    j+=a
    return float(pack[2][j]),float(pack[3][j]),float(pack[4][j])


def decompose(origin,start,facility,legs,walks):
    os,of,ss,sf=walks;used=[list(map(int,x)) for x in legs if x[0]>=0]
    out={k:0. for k in ['initial_walk_s','initial_walk_m','transfer_walk_s','transfer_walk_m','final_walk_s','final_walk_m','initial_wait_s','transfer_wait_s']}
    if not used:
        w,m,e=lookup(of,origin,facility);out['initial_walk_s']=w;out['initial_walk_m']=m
        return out
    w,m,e=lookup(os,origin,used[0][1]);out['initial_walk_s']=w;out['initial_walk_m']=m
    out['initial_wait_s']=used[0][3]-start-w
    for previous,current in zip(used,used[1:]):
        w,m,e=lookup(ss,previous[2],current[1]);out['transfer_walk_s']+=w;out['transfer_walk_m']+=m
        # Vehicle waiting plus the GTFS minimum's non-walking remainder.
        out['transfer_wait_s']+=current[3]-previous[4]-w
    w,m,e=lookup(sf,used[-1][2],facility);out['final_walk_s']=w;out['final_walk_m']=m
    return out
