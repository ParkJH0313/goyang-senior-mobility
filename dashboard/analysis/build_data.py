"""대시보드 고정 자료(dist/data.json) 생성.

본 분석 결과(outputs/step01·02·03·04·05·06·07·09, data/processed, .cache 경로 캐시)를 읽기만 한다.
실행: 저장소 루트에서  .venv\\Scripts\\python.exe dashboard\\analysis\\build_data.py

- 대상: Step7 저접근 2위 군집(C002, 보행 0.8m/s·연속보행 10분·30분·하위 30%·Queen)
- 가상정류장: 기존 정류장을 유지하고 고정 예산별 도보 5분(240m) 피복 고령인구 최대화 MCLP
- 30분 도달: 기존 버스 또는 집→배정 승하차 지점 보행·대기→직결/거점→의료기관 연결
"""
from pathlib import Path
import base64, json, sqlite3, sys, hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
import numpy as np, pandas as pd, geopandas as gpd
from scipy.sparse import load_npz, csr_matrix
from scipy.sparse.csgraph import dijkstra, connected_components
from scipy.spatial import cKDTree
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from location import solve_locations
DIST = HERE.parent / 'dist'
CLUSTER = 'C002'
SPEED = 0.8
R5, R10 = 5 * 60 * SPEED, 10 * 60 * SPEED          # 240m, 480m (연속보행 상한)
SNAP_MAX = 150.0
TIERS = [21, 36, 61]                               # 기존 탐욕식 70%·80%·90% 단계의 예산을 고정해 재최적화
WAIT_S = 870                                       # 광교 관측 14.5분을 2대 기준으로 전용한 민감도 가정
DETOUR = 1.25
FINAL_WALK_S = 60
DAILY_COST = 560428                                # 수원 똑버스 대당 1일 운송원가(2024)
DRIVE = {'primary', 'primary_link', 'secondary', 'secondary_link', 'tertiary', 'tertiary_link',
         'residential', 'unclassified', 'living_street'}
CAR = DRIVE | {'trunk', 'trunk_link'}
HUBS = {'daehwa': 'BS_TAGO_GGB219000193', 'seogu': 'BS_TAGO_GGB219000451'}
TO4326 = Transformer.from_crs(5179, 4326, always_xy=True)
TO5179 = Transformer.from_crs(4326, 5179, always_xy=True)


def lonlat(x, y):
    lon, lat = TO4326.transform(x, y)
    return round(float(lon), 6), round(float(lat), 6)


def cluster():
    m = pd.read_csv(ROOT / 'outputs/step07/tables/baseline_top3_membership.csv')
    m = m[m.cluster_id == CLUSTER]
    g500 = gpd.read_file(ROOT / 'outputs/step01/population.gpkg', layer='population_500m')
    g500 = g500[g500.gid.isin(m.gid)][['gid', 'geometry']].merge(m[['gid', 'population']], on='gid')
    acc = pd.read_csv(ROOT / 'outputs/step06/tables/accessibility_250m.csv', usecols=['gid', 'parent_gid', 'population'])
    acc = acc[acc.parent_gid.isin(m.gid) & (acc.population > 0)]
    g250 = gpd.read_file(ROOT / 'outputs/step01/population.gpkg', layer='population_250m')
    g250 = g250[g250.gid.isin(acc.gid)][['gid', 'geometry']].merge(acc, on='gid')
    o = gpd.read_file(ROOT / 'outputs/step02/origins.gpkg', layer='origins_250m')[['gid', 'geometry']]
    o = o[o.gid.isin(acc.gid)].merge(acc, on='gid').sort_values('gid').reset_index(drop=True)
    return g500, g250, o


def demand(g250):
    xmin, ymin, xmax, ymax = g250.total_bounds
    b = gpd.read_file(ROOT / 'data/processed/residential_buildings.gpkg', layer='residential_buildings',
                      bbox=(xmin, ymin, xmax, ymax), columns=['analysis_area_m2', 'representative_x', 'representative_y'])
    pts = gpd.GeoDataFrame(b.drop(columns='geometry'), geometry=gpd.points_from_xy(b.representative_x, b.representative_y), crs=g250.crs)
    j = gpd.sjoin(pts, g250[['gid', 'population', 'geometry']], predicate='within')
    j['w'] = j.analysis_area_m2.clip(lower=1.0)
    j['pop'] = j.population * j.w / j.groupby('gid').w.transform('sum')
    rows = j[['gid', 'pop', 'geometry']]
    missing = g250[~g250.gid.isin(j.gid)]
    if len(missing):
        o = gpd.read_file(ROOT / 'outputs/step02/origins.gpkg', layer='origins_250m')[['gid', 'geometry']]
        o = o[o.gid.isin(missing.gid)].merge(missing[['gid', 'population']], on='gid').rename(columns={'population': 'pop'})
        rows = pd.concat([rows, o[['gid', 'pop', 'geometry']]], ignore_index=True)
    rows = gpd.GeoDataFrame(rows, geometry='geometry', crs=g250.crs).reset_index(drop=True)
    assert abs(rows['pop'].sum() - g250.population.sum()) < 1e-6
    return rows


def walk_network(bounds, buffer=1200):
    xmin, ymin, xmax, ymax = bounds
    box = (xmin - buffer, ymin - buffer, xmax + buffer, ymax + buffer)
    z = np.load(ROOT / 'outputs/step04/walk_graph.npz')
    n = len(z['indptr']) - 1
    G = csr_matrix((z['length_m'], z['indices'], z['indptr']), shape=(n, n))
    gn = pd.read_parquet(ROOT / 'outputs/step04/graph_nodes.parquet')
    nodes = gpd.read_file(ROOT / 'data/processed/osm_walk_network.gpkg', layer='nodes', bbox=box, columns=['node_id', 'x', 'y'])
    nodes = pd.DataFrame(nodes.drop(columns='geometry')).merge(gn, on='node_id')
    # 정류장·출발점 접속용 access 노드는 좌표가 없어 이웃 확장으로 포함한다
    mask = np.zeros(n, bool); mask[nodes.node_index.to_numpy()] = True
    U = (G + G.T).tocsr()
    for _ in range(3):
        mask = mask | (U @ mask.astype(np.int32) > 0)
    keep = np.flatnonzero(mask)
    sub = G[keep][:, keep].T.tocsr()                       # 역방향: 정류장 기준 거리 = 건물→정류장 보행거리
    pos = pd.Series(np.arange(len(keep)), index=keep)
    nodes['local'] = pos.loc[nodes.node_index].to_numpy()
    edges = gpd.read_file(ROOT / 'data/processed/osm_walk_network.gpkg', layer='edges', bbox=box, columns=['u', 'v', 'highway'])
    drive = edges.highway.isin(DRIVE)
    nodes['drivable'] = nodes.node_id.isin(set(edges.u[drive]) | set(edges.v[drive]))
    return nodes.reset_index(drop=True), sub, pos


def existing_stops(pos):
    con = sqlite3.connect(f"file:{ROOT / 'data/processed/gtfs.sqlite'}?mode=ro", uri=True)
    dep = pd.read_sql_query("""SELECT s.stop_key, count(*) AS deps FROM stop_times s JOIN trips t USING(trip_key) JOIN calendar c USING(service_id)
        WHERE c.monday=1 AND c.tuesday=1 AND c.wednesday=1 AND c.thursday=1 AND c.friday=1
        AND coalesce(s.pickup_type,0)<>1 AND s.departure_s BETWEEN 30600 AND 61200 GROUP BY s.stop_key""", con)
    st = pd.read_parquet(ROOT / 'outputs/step04/stops.parquet')
    st = st[(~st.is_rail) & (st.connection_status == 'connected')].merge(dep, on='stop_key')
    c = pd.read_parquet(ROOT / 'outputs/step04/connections.parquet', columns=['entity_type', 'entity_index', 'graph_node', 'length_m'])
    st = st.merge(c[c.entity_type == 'stop'][['entity_index', 'graph_node', 'length_m']], on='entity_index')
    st = st[st.graph_node.isin(pos.index)].copy()
    st['local'] = pos.loc[st.graph_node].to_numpy()
    return st


def virtual_stops(g500, dem):
    nodes, sub, pos = walk_network(g500.total_bounds)
    tree = cKDTree(nodes[['x', 'y']].to_numpy())
    snap_d, k = tree.query(np.column_stack([dem.geometry.x, dem.geometry.y]))
    snap = nodes.local.to_numpy()[k]
    far = snap_d > SNAP_MAX
    w = dem['pop'].to_numpy()
    zone = g500.union_all().buffer(300)
    cand = nodes[nodes.drivable & gpd.points_from_xy(nodes.x, nodes.y).within(zone)].index.to_numpy()
    dist = np.concatenate([dijkstra(sub, indices=nodes.local.to_numpy()[chunk], limit=R10 + 1)[:, snap]
                           for chunk in np.array_split(cand, max(1, int(np.ceil(len(cand) / 64))))]) + snap_d[None, :]
    dist[:, far] = np.inf
    st = existing_stops(pos)
    st = st.drop_duplicates('stop_key').reset_index(drop=True)
    sd_all = dijkstra(sub, indices=st.local.to_numpy(), limit=R10 + 400)[:, snap] + snap_d[None, :] + st.length_m.to_numpy()[:, None]
    sd_all[:, far] = np.inf
    sd = sd_all.min(axis=0)
    selected, audit = solve_locations(dist, sd, w, TIERS, R5)
    stops = [dict(id='s'+str(r.stop_key), name=r.stop_name, existing=True,
                  lng=float(r.stop_lon), lat=float(r.stop_lat), tiers=['t0']+['t'+str(t) for t in TIERS])
             for r in st.itertuples()]
    selected_union = sorted(set(np.concatenate(list(selected.values()))))
    virtual_ids = {}
    for j in selected_union:
        x, y = nodes.loc[cand[j], ['x', 'y']]
        lng, lat = lonlat(x, y); sid = 'v'+str(int(nodes.loc[cand[j], 'node_id']))
        virtual_ids[j] = sid
        stops.append(dict(id=sid, name='가상 승하차 지점', existing=False, lng=lng, lat=lat,
                          tiers=['t'+str(t) for t in TIERS if j in selected[t]]))
    near, assignments = {}, {}
    for t in [0] + TIERS:
        indices = selected[t] if t else []
        matrix = np.vstack([sd_all, dist[indices]]) if t else sd_all
        ids = ['s'+str(k) for k in st.stop_key] + [virtual_ids[j] for j in indices]
        idx = matrix.argmin(axis=0); lengths = matrix[idx, np.arange(len(w))]
        near[t] = lengths
        assignments[t] = [dict(stop=ids[j], walkS=float(np.ceil(d/SPEED))) if d <= R10 else None for j, d in zip(idx, lengths)]
    used = {a['stop'] for rows in assignments.values() for a in rows if a}
    # Keep every selected virtual location on the map; unused existing stops are omitted.
    stops = [s for s in stops if not s['existing'] or s['id'] in used]
    return near, stops, w, assignments, audit


def car_graph(bounds, buffer=6000):
    xmin, ymin, xmax, ymax = bounds
    box = (xmin - buffer, ymin - buffer, xmax + buffer, ymax + buffer)
    e = gpd.read_file(ROOT / 'data/processed/osm_walk_network.gpkg', layer='edges', bbox=box, columns=['u', 'v', 'highway', 'length_m'])
    e = e[e.highway.isin(CAR)]
    n = gpd.read_file(ROOT / 'data/processed/osm_walk_network.gpkg', layer='nodes', bbox=box, columns=['node_id', 'x', 'y']).set_index('node_id')
    e = e[e.u.isin(n.index) & e.v.isin(n.index)]
    ids = pd.Index(pd.unique(pd.concat([e.u, e.v]))); n = n.loc[ids]
    u, v = ids.get_indexer(e.u), ids.get_indexer(e.v)
    G = csr_matrix((np.r_[e.length_m, e.length_m], (np.r_[u, v], np.r_[v, u])), shape=(len(ids), len(ids)))
    _, lab = connected_components(G, directed=False)
    ok = np.flatnonzero(lab == np.bincount(lab).argmax())
    return G, ok, cKDTree(n[['x', 'y']].to_numpy()[ok])


def nearest_clinics(o, g500):
    """OSM 무방향 도로망 근사 최근접 기관. 최종 자동차 거리는 카카오에서 별도 조회."""
    G, ok, tree = car_graph(g500.total_bounds)
    f = gpd.read_file(ROOT / 'outputs/step03/facilities.gpkg', layer='facilities')
    f = f[f.is_goyang.astype(bool)].reset_index(drop=True)
    _, oi = tree.query(np.c_[o.geometry.x, o.geometry.y])
    _, fi = tree.query(np.c_[f.x_5179, f.y_5179])
    D = dijkstra(G, indices=ok[oi], limit=15000)[:, ok[fi]]
    j = D.argmin(axis=1)
    used = sorted(set(j))
    clinics = [dict(id=f'c{i + 1}', name=f.name.iloc[k], lng=round(float(f.longitude.iloc[k]), 6), lat=round(float(f.latitude.iloc[k]), 6),
                    address=f.address.iloc[k]) for i, k in enumerate(used)]
    index = {k: f'c{i + 1}' for i, k in enumerate(used)}
    return [index[k] for k in j], clinics, D.min(axis=1)


def bus_bits(o):
    t = pd.read_parquet(ROOT / 'outputs/step09/travel_components.parquet', columns=['gid', 'cluster_id', 'departure_s', 'count_30'])
    t = t[t.cluster_id == CLUSTER]
    times = np.arange(30600, 61201, 60)
    piv = t.pivot_table(index='gid', columns='departure_s', values='count_30', aggfunc='first').reindex(index=o.gid, columns=times)
    assert not piv.isna().any().any(), '군집 출발점의 출발시각별 결과가 비어 있습니다'
    reach = piv.to_numpy() > 0
    return [base64.b64encode(np.packbits(r).tobytes()).decode() for r in reach], reach


def hub_onward():
    """Exact existing stop -> named hospital profiles; DRT consumes one boarding.

    Extends onward departures through 17:30, so 17:00 home departures are not censored.
    Every alternative's carbon baseline has the same named hospital destination.
    """
    from run import CONFIG
    from src.timetable import prepare, walk_arrays, csr_links
    from src.router import profile, timetable_tuple
    ctx = SimpleNamespace(cache=ROOT/'.cache/analysis', config=CONFIG, step=lambda n: ROOT/f'outputs/step{n:02d}')
    tt = timetable_tuple(prepare(ctx)); walks = walk_arrays(ctx, SPEED)
    links = pd.read_parquet(ctx.step(4)/'walk_links.parquet')
    links['walk_s'] = links.length_m/SPEED + links.fixed_s
    links = links[links.walk_s <= 600+1e-8]
    st = pd.read_parquet(ctx.step(4)/'stops.parquet')
    fac = pd.read_parquet(ctx.step(4)/'facility_index.parquet')
    fid = int(np.flatnonzero(fac.name.eq('인제대학교일산백병원'))[0]); f = fac.iloc[fid]
    times = np.arange(30600, 63001, 60, dtype=np.int32)
    out = {}
    for key, stop_id in HUBS.items():
        s = st[st.stop_id.eq(stop_id)].iloc[0]
        start = links[links.source_type.eq('stop') & links.source_index.eq(s.entity_index)].copy()
        start['source_index'] = 0
        os = csr_links(start[start.target_type.eq('stop')], 1)
        of = csr_links(start[start.target_type.eq('facility')], 1)
        od, _, _, _, _ = profile(0, times, 1800, len(fac), 2, 60, tt, (os, of, walks[2], walks[3]))
        best = od[:, fid]
        if not np.isfinite(best).any():
            raise ValueError('Hub cannot reach target hospital: '+key)
        out[key] = dict(id=key, name=str(s.stop_name), stopId=stop_id, stopKey=int(s.stop_key),
                        lng=float(s.stop_lon), lat=float(s.stop_lat), kind='실제 정류장 연계',
                        target='baek', targetName=f['name'],
                        onwardS=[None if not np.isfinite(v) else float(v) for v in best])
        print('HUB', key, s.stop_name, 'reachable', int(np.isfinite(best).sum()), flush=True)
    hospital = dict(id='baek', name=f['name'], lng=float(f.longitude), lat=float(f.latitude), address=f.address)
    return out, hospital


def main():
    g500, g250, o = cluster()
    dem = demand(g250)
    near, stops, w, assignments, audit = virtual_stops(g500, dem)
    usable = {}
    for t, d in near.items():
        ok = pd.Series(w * (d <= R10)).groupby(dem.gid.values).sum() / pd.Series(w).groupby(dem.gid.values).sum()
        usable[t] = ok.reindex(o.gid).fillna(0).to_numpy()
    cover = {t: dict(walk5=float(w[d <= R5].sum() / w.sum()), walk10=float(w[d <= R10].sum() / w.sum())) for t, d in near.items()}
    clinic_of, clinics, clinic_m = nearest_clinics(o, g500)
    bits, reach = bus_bits(o)
    wpop = o.population.to_numpy()
    baseline = float((reach.mean(axis=1) * wpop).sum() / wpop.sum())
    onward, hospital = hub_onward()

    origins = []
    for i, r in o.iterrows():
        lng, lat = lonlat(r.geometry.x, r.geometry.y)
        origins.append(dict(key=str(i), gid=r.gid, parent_gid=r.parent_gid, population=float(r.population), x=lng, y=lat,
                            clinic=clinic_of[i], usable={f't{t}': round(float(usable[t][i]), 4) for t in [0] + TIERS}, bus=bits[i]))
    grids = []
    for r in g500.to_crs(4326).itertuples():
        ring = [[round(x, 6), round(y, 6)] for x, y in r.geometry.exterior.coords]
        grids.append(dict(type='Feature', geometry=dict(type='Polygon', coordinates=[ring]), properties=dict(gid=r.gid, population=float(r.population))))
    tiers = [dict(id=f't{t}', stops=t, walk5=round(cover[t]['walk5'], 4), walk10=round(cover[t]['walk10'], 4)) for t in [0]+TIERS]
    places = [dict(id='clinic', name='가까운 내과·정형외과', kind='출발지별 최근접 의원 직결')] + \
             [{k:v for k,v in item.items() if k!='onwardS'} for item in onward.values()]
    origin_keys = {r.gid: str(i) for i, r in o.iterrows()}
    samples = [dict(origin=origin_keys[r.gid], population=float(r['pop']),
                    boarding={f't{t}': assignments[t][i] for t in [0]+TIERS}) for i, r in dem.iterrows()]
    manifest = json.loads((ROOT/'outputs/run_manifest.json').read_text(encoding='utf-8'))
    assert manifest['settings']['baseline_speed_mps'] == SPEED
    data = dict(
        schemaVersion=3, generatedAt=datetime.now(timezone.utc).isoformat(), runId=manifest['run_id'],
        source='Step7 C002 (0.8m/s·연속보행 10분·30분·하위 30%·Queen) / Step9 / fixed-budget MCLP',
        sourceHashes={str(p):hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in [Path('outputs/run_manifest.json'),Path('outputs/step07/tables/baseline_top3_membership.csv'),Path('dashboard/analysis/build_data.py'),Path('dashboard/analysis/location.py')]},
        areaName='구산·법곳·가좌 일대', clusterId=CLUSTER,
        totalPopulation=round(float(wpop.sum()), 1), totalGrids=len(grids), originCount=len(origins),
        existing=dict(walk5=round(cover[0]['walk5'], 4), walk10=round(cover[0]['walk10'], 4)),
        tiers=tiers, stops=stops, clinics=clinics+[hospital], places=places, demand=samples, locationAudit=audit,
        access=dict(baselineShare=round(baseline, 4), waitS=WAIT_S, detour=DETOUR, budgetS=1800, finalWalkS=FINAL_WALK_S,
                    departureStartS=30600, departureIntervalS=60, departureCount=511,
                    speedMps=SPEED, maxWalkS=600, hubAlightS=60,
                    referenceVehicles=2, waitElasticity=.5,
                    onward={k:dict(onwardS=v['onwardS'], target=v['target'], departureStartS=30600, departureIntervalS=60) for k,v in onward.items()}),
        budget=dict(dailyCostPerVehicle=DAILY_COST, days=365, defaultVehicles=2, maxVehicles=3),
        grids=grids, origins=origins)
    assert abs(sum(x['population'] for x in samples)-data['totalPopulation']) < 1e-6
    target=DIST/'data.json'; temp=target.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8');temp.replace(target)
    print(json.dumps(dict(population=data['totalPopulation'], grids=len(grids), origins=len(origins), baseline=baseline,
                          existing=data['existing'], tiers=tiers, clinics=[c['name'] for c in clinics],
                          clinic_km=float((clinic_m * wpop).sum() / wpop.sum() / 1000),
                          onward={k: (v['stopId'], sum(x is not None for x in v['onwardS'])) for k, v in onward.items()}),
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
