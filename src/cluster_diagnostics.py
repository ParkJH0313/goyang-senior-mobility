"""Population-weighted arrival diagnosis and uncapped directed walks to bus stops."""
import heapq
import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio
from scipy.sparse import csr_matrix
from src.analysis_io import csv, ro

STATUS_ORDER = ['within_budget', 'first_walk_blocked', 'over_budget', 'no_route', 'unresolved']
WALK_BANDS = ['10분 이하', '10분 초과~15분 이하', '15분 초과~20분 이하', '20분 초과', '보행망 경로 없음']
COMPONENTS = ['total_s', 'walk_s', 'wait_s', 'in_vehicle_s', 'preparation_s',
              'initial_walk_s', 'transfer_walk_s', 'final_walk_s', 'initial_wait_s', 'transfer_wait_s']


def arrival_tables(comp, access, budget_min):
    """Disjoint states; all departures and all positive origin weights stay in the denominator."""
    rows = comp.merge(access[['gid', 'first_walk_blocked']], on='gid', validate='many_to_one')
    assert rows.first_walk_blocked.notna().all()
    known = rows.status.ne('unresolved')
    reachable = rows.status.eq('reachable') & rows.total_s.notna()
    assert not (known & reachable & rows.first_walk_blocked).any()
    rows['arrival_status'] = np.select(
        [~known, rows.first_walk_blocked, reachable & rows.total_s.le(budget_min * 60 + 1e-8), reachable],
        ['unresolved', 'first_walk_blocked', 'within_budget', 'over_budget'], default='no_route')
    states, means = [], []
    for cid, group in rows.groupby('cluster_id'):
        # Every origin has the same complete departure sequence.
        times = group.groupby('gid').departure_s.nunique()
        assert times.nunique() == 1
        departures = int(times.iloc[0]); total = group.population.sum()
        for status in STATUS_ORDER:
            part = group[group.arrival_status.eq(status)]; weight = part.population.sum()
            states.append(dict(cluster_id=cid, arrival_status=status, sample_count=len(part),
                population_time_weight=float(weight), population_equivalent=float(weight/departures),
                fraction=float(weight/total), departure_count=departures))
        for status in ['within_budget', 'over_budget']:
            part = group[group.arrival_status.eq(status)]; weight = part.population.sum()
            record = dict(cluster_id=cid, arrival_status=status, sample_count=len(part), fraction=float(weight/total))
            for col in COMPONENTS:
                record[col] = float(np.sum(part[col]*part.population)/weight) if weight else np.nan
            if weight:
                assert np.isclose(sum(record[x] for x in ['walk_s','wait_s','in_vehicle_s','preparation_s']), record['total_s'])
            means.append(record)
    states = pd.DataFrame(states)
    assert np.allclose(states.groupby('cluster_id').fraction.sum(), 1)
    return states, pd.DataFrame(means)


def reverse_nearest(indptr, indices, lengths, seed_nodes, seed_costs, speed):
    """Reverse multi-source Dijkstra: directed source→stop cost, including stop connectors."""
    n = len(indptr)-1
    reverse = csr_matrix((lengths/speed, indices, indptr), shape=(n,n)).transpose().tocsr()
    distances = np.full(n, np.inf); labels = np.full(n, -1, dtype=np.int64); queue = []
    for label, (node, cost) in enumerate(zip(seed_nodes, seed_costs)):
        if cost < distances[node]:
            distances[node] = cost; labels[node] = label; heapq.heappush(queue, (float(cost), int(node)))
    while queue:
        cost, node = heapq.heappop(queue)
        if cost > distances[node]: continue
        for edge in range(reverse.indptr[node], reverse.indptr[node+1]):
            source = reverse.indices[edge]; candidate = cost+reverse.data[edge]
            if candidate < distances[source]-1e-10:
                distances[source] = candidate; labels[source] = labels[node]
                heapq.heappush(queue, (float(candidate), int(source)))
    return distances, labels


def bus_walk(ctx, small, membership):
    """Descriptive uncapped walking distances. This does not change routing's 10-minute limit."""
    speed = ctx.config['baseline_speed_mps']
    stops = pd.read_parquet(ctx.step(4)/'stops.parquet')
    connections = pd.read_parquet(ctx.step(4)/'connections.parquet')
    with ro('data/processed/gtfs.sqlite') as con:
        keys = pd.read_sql_query('''SELECT DISTINCT st.stop_key FROM stop_times st
            JOIN trips t USING(trip_key) JOIN calendar c USING(service_id) JOIN routes r USING(route_id)
            WHERE c.monday=1 AND c.tuesday=1 AND c.wednesday=1 AND c.thursday=1 AND c.friday=1
            AND r.mode='local_bus' AND COALESCE(st.pickup_type,0)=0''', con).stop_key
    eligible = stops[stops.stop_key.isin(keys)]
    targets = connections[connections.entity_type.eq('stop') & connections.entity_index.isin(eligible.entity_index)].sort_values(['entity_index','graph_node']).reset_index(drop=True)
    assert len(targets)
    with np.load(ctx.step(4)/'walk_graph.npz') as graph:
        distances, labels = reverse_nearest(graph['indptr'], graph['indices'], graph['length_m'],
            targets.graph_node.to_numpy(int), (targets.length_m/speed+targets.fixed_s).to_numpy(), speed)
    selected = small[small.parent_gid.isin(membership.gid) & small.population.gt(0)].copy()
    selected = selected[['gid','parent_gid','population','geometry']].merge(
        membership[['gid','cluster_id']].rename(columns={'gid':'parent_gid'}), on='parent_gid', validate='many_to_one')
    origins = connections[connections.entity_type.eq('origin') & connections.entity_id.isin(selected.gid)].copy()
    nodes = origins.graph_node.to_numpy(int); origins['nearest_seed'] = labels[nodes]
    origins['walk_s'] = distances[nodes]+origins.length_m/speed+origins.fixed_s
    origins = origins.sort_values(['walk_s','entity_id']).drop_duplicates('entity_id')
    selected = selected.merge(origins[['entity_id','entity_index','walk_s','nearest_seed']].rename(
        columns={'entity_id':'gid','entity_index':'origin_index'}), on='gid', validate='one_to_one')
    assert len(selected) == len(origins)
    # No seed is a missing path, never a zero-length walk.
    selected['nearest_stop_index'] = [int(targets.entity_index.iloc[int(i)]) if i >= 0 else -1 for i in selected.nearest_seed]
    lookup = stops.set_index('entity_index')
    selected['nearest_stop_id'] = selected.nearest_stop_index.map(lookup.stop_id).fillna('')
    selected['nearest_stop_name'] = selected.nearest_stop_index.map(lookup.stop_name).fillna('')
    selected['walk_min'] = selected.walk_s/60
    selected['band'] = np.select([~np.isfinite(selected.walk_s),selected.walk_s.le(600+1e-8),
        selected.walk_s.le(900+1e-8),selected.walk_s.le(1200+1e-8)],
        [WALK_BANDS[4],WALK_BANDS[0],WALK_BANDS[1],WALK_BANDS[2]], default=WALK_BANDS[3])
    selected['walk_s'] = selected.walk_s.replace(np.inf,np.nan)
    selected['walk_min'] = selected.walk_min.replace(np.inf,np.nan)
    selected = selected.drop(columns='nearest_seed')
    totals=[]; point_groups=[]
    for cid, group in selected.groupby('cluster_id'):
        for band in WALK_BANDS:
            part=group[group.band.eq(band)]
            totals.append(dict(cluster_id=cid,band=band,origin_count=len(part),population=float(part.population.sum()),
                fraction=float(part.population.sum()/group.population.sum()),min_minutes=part.walk_min.min(),max_minutes=part.walk_min.max()))
        points=stops[stops.entity_index.isin(group.nearest_stop_index)].copy();points['cluster_id']=cid
        point_groups.append(points[['cluster_id','entity_index','stop_id','stop_name','x_5179','y_5179']])
    points=pd.concat(point_groups,ignore_index=True)
    points=gpd.GeoDataFrame(points,geometry=gpd.points_from_xy(points.x_5179,points.y_5179),crs=5179)
    return selected,pd.DataFrame(totals),points


def build(ctx, small, membership, comp, access, summary):
    out=ctx.step(9)
    states, means = arrival_tables(comp, access, ctx.config['baseline_budget_min'])
    walks, bands, stops = bus_walk(ctx, small.reset_index(drop=True), membership)
    parents=pyogrio.read_dataframe(ctx.step(6)/'accessibility.gpkg',layer='accessibility_500m')
    parents=parents[['gid','population','geometry']].merge(membership[['gid','cluster_id']],on='gid',validate='one_to_one')
    for cid, part in walks.groupby('cluster_id'):
        expected=float(summary.set_index('cluster_id').loc[cid,'population'])
        assert np.isclose(part.population.sum(),expected)
        assert np.isclose(parents.loc[parents.cluster_id.eq(cid),'population'].sum(),expected)
    for name, table in [('arrival_status',states),('arrival_time_components',means),
                        ('nearest_bus_walk',walks.drop(columns='geometry')),('bus_walk_population',bands)]:
        csv(table,out/'tables'/f'{name}.csv')
    return {'stop_walk_250m':walks,'diagnostic_population_500m':parents,'nearest_boarding_stops':stops}
