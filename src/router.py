"""Exact boarding-round timetable search with closed, bounded walking legs.

Every boardable trip is scanned: overtaking and different route choices are retained.
Dominance is only among alighted states with equal boarding count and stop; the
walking leg has ended on the vehicle and next walking allowance is identical.
No total-walk cap. GTFS pair minimum elapsed time is distinct from physical walk.
"""
import numpy as np
from numba import njit,prange

@njit(cache=True)
def query(origin,start,budget,nfac,maxboards,prep,tt,walks):
    trip_ptr,stops,arr,dep,drop,event_ptr,event_pos,event_dep,event_trip=tt
    os,of,ss,sf=walks;ns=len(event_ptr)-1;nt=len(trip_ptr)-1;deadline=start+budget
    # Components: walking seconds, metres, waiting, in-vehicle, preparation, max leg.
    # Trace/component rows are read only after their finite-time label is set.
    # Avoid zero-filling tens of MB for every departure in a sparse local search.
    alight=np.full((maxboards+1,ns),np.inf);ac=np.empty((maxboards+1,ns,6))
    prev=np.empty((maxboards+1,ns),np.int32);bt=np.empty_like(prev);bp=np.empty_like(prev);ap=np.empty_like(prev)
    ready=np.full(ns,np.inf);rc=np.empty((ns,6));prior=np.empty(ns,np.int32)
    ru=np.empty(ns,np.int32);au=np.empty((maxboards+1,ns),np.int32);causes=np.full(nfac,-1,np.int32)
    result=np.full(nfac,np.inf);best=np.inf;best_round=0;best_stop=-1;best_fac=-1;best_comp=np.zeros(8)
    for j in range(of[0][origin],of[0][origin+1]):
        fid=of[1][j];w=of[2][j]
        if w<=budget+1e-8:
            result[fid]=w
            if w<best:
                best=w;best_fac=fid;best_comp[0]=w;best_comp[1]=of[3][j];best_comp[5]=w
    for j in range(os[0][origin],os[0][origin+1]):
        s=os[1][j];w=os[2][j]
        if start+w<ready[s]:
            ready[s]=start+w;rc[s,:]=0.;rc[s,0]=w;rc[s,1]=os[3][j];rc[s,5]=w;ru[s]=os[5][j];prior[s]=-1
    board=np.full(nt,-1,np.int32)
    for round in range(1,maxboards+1):
        touched=[]
        for s in range(ns):
            if ready[s]>deadline:continue
            lo=event_ptr[s];hi=event_ptr[s+1]
            left=lo;right=hi
            while left<right:
                mid=(left+right)//2
                if event_dep[mid]+1e-8<ready[s]:left=mid+1
                else:right=mid
            for ev in range(left,hi):
                if event_dep[ev]>deadline+1e-8:break
                tr=event_trip[ev];pos=event_pos[ev]
                if board[tr]<0:touched.append(tr);board[tr]=pos
                elif pos<board[tr]:board[tr]=pos
        for tr in touched:
            pos=board[tr];s=stops[pos];board[tr]=-1
            # Alighting at the boarding event would falsely reset a walking allowance.
            for k in range(pos+1,trip_ptr[tr+1]):
                if arr[k]>deadline+1e-8:break
                v=stops[k]
                if drop[k]!=0 or arr[k]>=alight[round,v]-1e-9:continue
                alight[round,v]=arr[k];prev[round,v]=prior[s];bt[round,v]=tr;bp[round,v]=pos;ap[round,v]=k
                au[round,v]=ru[s]
                ac[round,v,:]=rc[s,:];ac[round,v,2]+=dep[pos]-ready[s];ac[round,v,3]+=arr[k]-dep[pos]
        for s in range(ns):
            a=alight[round,s]
            if a>deadline:continue
            for j in range(sf[0][s],sf[0][s+1]):
                fid=sf[1][j];w=sf[2][j];duration=a+w-start
                if duration>budget+1e-8:continue
                if duration<result[fid]:
                    result[fid]=duration;causes[fid]=au[round,s] if au[round,s]>=0 else sf[5][j]
                if duration<best-1e-9:
                    best=duration;best_fac=fid;best_stop=s;best_round=round
                    best_comp[:6]=ac[round,s,:];best_comp[0]+=w;best_comp[1]+=sf[3][j];best_comp[5]=max(best_comp[5],w);best_comp[6]=round;best_comp[7]=duration
        if round==maxboards:break
        ready[:]=np.inf;prior[:]=-1
        for s in range(ns):
            a=alight[round,s]
            if a>deadline:continue
            for j in range(ss[0][s],ss[0][s+1]):
                v=ss[1][j];elapsed=ss[4][j];at=a+elapsed
                if at>=ready[v]-1e-9 or at>deadline+1e-8:continue
                ready[v]=at;prior[v]=s;rc[v,:]=ac[round,s,:]
                ru[v]=au[round,s] if au[round,s]>=0 else ss[5][j]
                rc[v,0]+=ss[2][j];rc[v,1]+=ss[3][j];rc[v,4]+=prep;rc[v,2]+=elapsed-ss[2][j]-prep;rc[v,5]=max(rc[v,5],ss[2][j])
    legs=np.full((maxboards,5),-1,np.int32)
    current=best_stop
    for round in range(best_round,0,-1):
        p=bp[round,current];q=ap[round,current]
        legs[round-1,0]=bt[round,current];legs[round-1,1]=stops[p];legs[round-1,2]=stops[q];legs[round-1,3]=dep[p];legs[round-1,4]=arr[q]
        current=prev[round,current]
    if best_fac>=0:best_comp[7]=best
    else:best_comp[:]=np.nan
    return result,best_fac,best_comp,legs,causes

@njit(cache=True,nogil=True)
def profile_batch(origin,times,budget,nfac,maxboards,prep,tt,walks):
    od=np.full((len(times),nfac),np.inf);nearest=np.full(len(times),-1,np.int32);comp=np.empty((len(times),8));legs=np.empty((len(times),maxboards,5),np.int32);causes=np.full((len(times),nfac),-1,np.int32)
    for i in range(len(times)):
        a,b,c,d,e=query(origin,times[i],budget,nfac,maxboards,prep,tt,walks)
        od[i,:]=a;nearest[i]=b;comp[i,:]=c;legs[i,:,:]=d;causes[i,:]=e
    return od,nearest,comp,legs,causes

_pool=None
def profile(origin,times,budget,nfac,maxboards,prep,tt,walks):
    # Numba's Windows gufunc lowering does not support these nested CSR tuples.
    # Independent time batches release the GIL and share read-only timetable arrays.
    global _pool
    if _pool is None:
        import os
        from concurrent.futures import ThreadPoolExecutor
        _pool=ThreadPoolExecutor(max_workers=max(1,min(8,os.cpu_count() or 2)))
    batches=[x for x in np.array_split(times,min(8,len(times))) if len(x)]
    futures=[_pool.submit(profile_batch,origin,x,budget,nfac,maxboards,prep,tt,walks) for x in batches]
    result=[f.result() for f in futures]
    return tuple(np.concatenate([x[i] for x in result]) for i in range(5))

def timetable_tuple(data):
    return tuple(data[k] for k in ['trip_ptr','stop','arrival','departure','dropoff','event_ptr','event_position','event_departure','event_trip'])
