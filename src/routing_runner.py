"""Origin and departure-batch checkpoints shared by baseline and diagnostics."""
import os,time,shutil,json
import numpy as np,pandas as pd
from numba import set_num_threads
from src.analysis_io import ROOT,sha,digest,atomic_npz,atomic_json,read_json,log,parquet
from src.timetable import prepare,walk_arrays
from src.router import profile,timetable_tuple

def calculate(ctx,origin_indices,speed,budget_min):
    set_num_threads(max(1,min(8,os.cpu_count() or 2)))
    timetable=prepare(ctx);tt=timetable_tuple(timetable);walks=walk_arrays(ctx,speed);upper_walks=walk_arrays(ctx,speed,optimistic=True)
    origins=pd.read_parquet(ctx.step(4)/'origin_index.parquet');fac=pd.read_parquet(ctx.step(4)/'facility_index.parquet')
    sig=digest({'network':ctx.state['stages']['4']['signature'],'links':sha(ctx.step(4)/'walk_links.parquet'),'timetable':sha('data/processed/gtfs.sqlite'),'code':{p:sha(p) for p in ['src/router.py','src/routing_runner.py','src/timetable.py','src/scope_check.py']},'speed':speed,'budget':budget_min,'max_boardings':ctx.config['max_boardings'],'prep':ctx.config['transfer_preparation_s'],'times':[ctx.config['departure_start_s'],ctx.config['departure_end_s'],ctx.config['departure_interval_s']]})
    folder=ctx.cache/('routing_'+sig[:20]);folder.mkdir(parents=True,exist_ok=True)
    times=np.arange(ctx.config['departure_start_s'],ctx.config['departure_end_s']+1,ctx.config['departure_interval_s'],dtype=np.int32)
    budgets=np.array(sorted(set(ctx.config['sensitivity_budgets_min']+ctx.config['diagnostic_budgets_min']+[budget_min])),np.int32)
    def record(i,target):
        with np.load(target) as z:
            k=int(np.flatnonzero(budgets==budget_min)[0]);actual=np.sum(z['od']<=budget_min*60+1e-8,axis=1)
            uncertain=int(np.sum(z['upper_counts'][:,k]>actual));events=z['cause_events'];causes=np.unique(events[events[:,1]==k,2]).tolist() if len(events) else []
        return {'origin_index':int(i),'gid':origins.gid.iloc[i],'path':target.relative_to(ROOT).as_posix(),'status':'complete','uncertain_departures':uncertain,'review_stop_indices':json.dumps(causes)}
    atomic_json(folder/'manifest.json',{'signature':sig,'speed_mps':speed,'budget_min':budget_min,'departure_count':len(times),'origin_count':len(origins),'status':'checkpoint_store'})
    checkpoints=[]
    for count,i in enumerate(origin_indices):
        target=folder/f'origin_{int(i):05d}.npz'
        if target.exists():
            with np.load(target) as z:assert z['od'].shape==(len(times),len(fac)) and np.array_equal(z['times'],times)
            checkpoints.append(record(i,target));continue
        started=time.monotonic();parts=[]
        for begin in range(0,len(times),64):
            end=min(len(times),begin+64);part=folder/f'origin_{int(i):05d}_part_{begin:03d}.npz'
            if not part.exists():
                od,nearest,components,legs,_=profile(int(i),times[begin:end],budget_min*60,len(fac),ctx.config['max_boardings'],ctx.config['transfer_preparation_s'],tt,walks)
                upper,_,uc,_,causes=profile(int(i),times[begin:end],budget_min*60,len(fac),ctx.config['max_boardings'],ctx.config['transfer_preparation_s'],tt,upper_walks)
                finite=np.isfinite(od);assert np.all(upper[finite]<=od[finite]+1e-7)
                counts=np.column_stack([np.sum(upper<=min(b,budget_min)*60+1e-8,axis=1) for b in budgets]);events=[]
                for k,b in enumerate(budgets):
                    if b>budget_min:continue
                    ii,jj=np.where((upper<=b*60+1e-8)&(od>b*60+1e-8))
                    if len(ii):
                        cause=causes[ii,jj];assert (cause>=0).all();events.extend(zip(begin+ii,np.full(len(ii),k),cause))
                events=np.unique(np.array(events,dtype=np.int32).reshape(-1,3),axis=0)
                nearest_causes=causes[np.arange(len(upper)),np.argmin(upper,axis=1)]
                atomic_npz(part,od=od,nearest=nearest,components=components,legs=legs,times=times[begin:end],upper_counts=counts,upper_nearest_s=uc[:,7],nearest_causes=nearest_causes,cause_events=events)
            parts.append(part)
        arrays={k:[] for k in ['od','nearest','components','legs','times','upper_counts','upper_nearest_s','nearest_causes','cause_events']}
        for part in parts:
            with np.load(part) as z:
                for key in arrays:arrays[key].append(z[key])
        atomic_npz(target,**{k:np.concatenate(v) for k,v in arrays.items()},budgets=budgets)
        for part in parts:part.unlink()
        checkpoints.append(record(i,target))
        log(f'Routing {speed}m/s {budget_min}min {count+1}/{len(origin_indices)} {origins.gid.iloc[i]} ({time.monotonic()-started:.1f}s)')
        atomic_json(folder/'progress.json',{'completed':len(list(folder.glob('origin_?????.npz'))),'requested':len(origin_indices),'last_gid':origins.gid.iloc[i]})
    return pd.DataFrame(checkpoints)
