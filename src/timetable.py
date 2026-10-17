"""Immutable timetable arrays and scenario-specific walking closures."""
import gc
import numpy as np,pandas as pd
from src.analysis_io import ro,sha,inside,atomic_npz,log,parquet,digest

def prepare(ctx):
    folder=ctx.cache/('timetable_'+digest({'db':sha('data/processed/gtfs.sqlite'),'code':sha('src/timetable.py')})[:16]);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'timetable.npz'
    if path.exists():return np.load(path,allow_pickle=False)
    stops=pd.read_parquet(ctx.step(4)/'stops.parquet')
    with ro('data/processed/gtfs.sqlite') as c:
        trips=pd.read_sql_query('SELECT t.* FROM trips t JOIN calendar c USING(service_id) WHERE c.monday=1 AND c.tuesday=1 AND c.wednesday=1 AND c.thursday=1 AND c.friday=1 ORDER BY trip_key',c)
        trips['trip_index']=np.arange(len(trips));parquet(trips,folder/'trips.parquet')
        count=c.execute('SELECT count(*) FROM stop_times').fetchone()[0]
        oldkeys=stops.stop_key.to_numpy();sm=np.full(int(oldkeys.max())+1,-1,np.int32);sm[oldkeys]=stops.entity_index
        tm=np.full(int(trips.trip_key.max())+1,-1,np.int32);tm[trips.trip_key]=trips.trip_index
        arrays={k:np.empty(count,np.int32) for k in ['trip','stop','arrival','departure','pickup','dropoff']};at=0
        query='SELECT s.trip_key,s.stop_key,s.arrival_s,s.departure_s,s.pickup_type,s.drop_off_type FROM stop_times s ORDER BY s.trip_key,s.stop_sequence'
        for chunk in pd.read_sql_query(query,c,chunksize=250000):
            chunk=chunk[chunk.trip_key.isin(trips.trip_key)];n=len(chunk)
            for key,col in [('arrival','arrival_s'),('departure','departure_s'),('pickup','pickup_type'),('dropoff','drop_off_type')]:arrays[key][at:at+n]=chunk[col]
            arrays['trip'][at:at+n]=tm[chunk.trip_key];arrays['stop'][at:at+n]=sm[chunk.stop_key];at+=n
            if at%1000000<250000:log(f'Timetable packed {at}/{count} stop times')
    arrays={k:v[:at] for k,v in arrays.items()};assert (arrays['stop']>=0).all()
    trip_ptr=np.zeros(len(trips)+1,np.int64);trip_ptr[1:]=np.cumsum(np.bincount(arrays['trip'],minlength=len(trips)))
    allowed=np.flatnonzero(arrays['pickup']==0);order=allowed[np.lexsort((arrays['trip'][allowed],arrays['departure'][allowed],arrays['stop'][allowed]))]
    event_ptr=np.zeros(len(stops)+1,np.int64);event_ptr[1:]=np.cumsum(np.bincount(arrays['stop'][order],minlength=len(stops)))
    atomic_npz(path,trip_ptr=trip_ptr,stop=arrays['stop'],arrival=arrays['arrival'],departure=arrays['departure'],dropoff=arrays['dropoff'],event_ptr=event_ptr,event_position=order.astype(np.int32),event_departure=arrays['departure'][order],event_trip=arrays['trip'][order])
    del arrays;gc.collect();return np.load(path,allow_pickle=False)

def csr_links(frame,n,transfer=False,prep=60):
    frame=frame.copy();frame['elapsed_s']=np.maximum(frame.walk_s+prep,frame.min_elapsed_s) if transfer else frame.walk_s
    assert np.isfinite(frame[['walk_s','length_m','elapsed_s']].to_numpy()).all(), 'Non-finite walking or transfer costs'
    assert (frame[['walk_s','length_m','elapsed_s']].to_numpy()>=0).all(), 'Negative physical costs'
    frame=frame.sort_values(['source_index','elapsed_s','target_index','walk_s','length_m']).drop_duplicates(['source_index','target_index']).sort_values(['source_index','target_index'])
    ptr=np.zeros(n+1,np.int64);ptr[1:]=np.cumsum(np.bincount(frame.source_index.to_numpy(np.int64),minlength=n))
    causes=frame.unknown_stop.to_numpy(np.int32) if 'unknown_stop' in frame else np.full(len(frame),-1,np.int32)
    return ptr,frame.target_index.to_numpy(np.int32),frame.walk_s.to_numpy(float),frame.length_m.to_numpy(float),frame.elapsed_s.to_numpy(float),causes

def walk_arrays(ctx,speed,optimistic=False):
    links=pd.read_parquet(ctx.step(4)/'walk_links.parquet');links['walk_s']=links.length_m/speed+links.fixed_s
    links['unknown_stop']=-1
    if optimistic:
        from src.scope_check import potential_links
        extra=potential_links(ctx);extra['walk_s']=extra.length_m/speed+extra.fixed_s
        links=pd.concat([links,extra],ignore_index=True)
    links=links[links.walk_s<=ctx.config['max_continuous_walk_s']+1e-8]
    no=len(pd.read_parquet(ctx.step(4)/'origin_index.parquet'));ns=len(pd.read_parquet(ctx.step(4)/'stops.parquet'))
    packs=[]
    for a,b,n in [('origin','stop',no),('origin','facility',no),('stop','stop',ns),('stop','facility',ns)]:
        f=links[links.source_type.eq(a)&links.target_type.eq(b)]
        packs.append(csr_links(f,n,a==b=='stop',ctx.config['transfer_preparation_s']))
    return tuple(packs)
