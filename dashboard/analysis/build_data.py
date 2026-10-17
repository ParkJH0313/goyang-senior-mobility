"""대시보드 고정 자료(dist/data.json) 생성.

본 분석 결과(outputs/step01·02·03·04·05·06·07·09, data/processed, .cache 경로 캐시)를 읽기만 한다.
실행: 저장소 루트에서  .venv\\Scripts\\python.exe dashboard\\analysis\\build_data.py

- 대상: Step7 저접근 2위 군집(C002, 보행 0.8m/s·연속보행 10분·30분·하위 30%·Queen)
- 가상정류장: 기존 버스정류장을 승하차 지점으로 두고 도보 5분(240m) 밖 고령인구를 가장 많이 덮는 지점부터 추가
- 30분 도달: 버스(본 분석 출발시각별 결과) 또는 똑버스(호출~탑승 W + 카카오 자동차 소요시간 × 우회) 중 하나로 도달
"""
from pathlib import Path
import base64, json, sqlite3
import numpy as np, pandas as pd, geopandas as gpd
from scipy.sparse import load_npz, csr_matrix
from scipy.sparse.csgraph import dijkstra, connected_components
from scipy.spatial import cKDTree
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIST = HERE.parent / 'dist'
CLUSTER = 'C002'
SPEED = 0.8
R5, R10 = 5 * 60 * SPEED, 10 * 60 * SPEED          # 240m, 480m (연속보행 상한)
SNAP_MAX = 150.0
TIERS = [21, 36, 61]                               # 도보 5분 70%·80%·90%를 처음 넘는 추가 정류장 수
WAIT_S = 870                                       # 호출~탑승 14.5분 (수원 광교 똑버스 평균 대기 14분 30초)
DETOUR = 1.25
FINAL_WALK_S = 60
DAILY_COST = 560428                                # 수원 똑버스 대당 1일 운송원가(2024)
DRIVE = {'primary', 'primary_link', 'secondary', 'secondary_link', 'tertiary', 'tertiary_link',
         'residential', 'unclassified', 'living_street'}
CAR = DRIVE | {'trunk', 'trunk_link'}
STATIONS = {'tanhyeon': ('탄현역', 126.761175, 37.693887), 'kintex': ('킨텍스역', 126.747533, 37.665417)}
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
        mask = mask | (U @ mask.astype(np.int8) > 0)
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
    dist = dijkstra(sub, indices=nodes.local.to_numpy()[cand], limit=R10 + 1)[:, snap] + snap_d[None, :]
    dist[:, far] = np.inf
    st = existing_stops(pos)
    sd = (dijkstra(sub, indices=st.local.to_numpy(), limit=R10 + 400)[:, snap] + snap_d[None, :] + st.length_m.to_numpy()[:, None]).min(axis=0)
    sd[far] = np.inf
    cov5 = dist <= R5
    covered = sd <= R5; order = []; curve = [w[covered].sum() / w.sum()]
    for _ in range(max(TIERS)):
        gain = (cov5[:, ~covered] * w[~covered]).sum(axis=1)
        j = int(np.argmax(gain))
        if gain[j] <= 1e-9: break
        order.append(j); covered |= cov5[j]; curve.append(w[covered].sum() / w.sum())
    near = {0: sd}
    for t in TIERS:
        near[t] = np.minimum(sd, dist[order[:t]].min(axis=0))
    stops = [dict(order=i + 1, lng=lonlat(*nodes.loc[cand[j], ['x', 'y']])[0], lat=lonlat(*nodes.loc[cand[j], ['x', 'y']])[1])
             for i, j in enumerate(order[:max(TIERS)])]
    return near, stops, w


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
    """출발점별 도로거리 기준 가장 가까운 고양시 내과·정형외과 (카카오 조회 목적지 선정용)."""
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


def station_onward():
    """역이 속한 250m 분석 출발점의 출발시각별 '가장 빠른 의료기관 도달 시간'(30분 이내, 초)."""
    oi = pd.read_parquet(ROOT / 'outputs/step04/origin_index.parquet')
    og = gpd.read_file(ROOT / 'outputs/step02/origins.gpkg', layer='origins_250m')[['gid', 'geometry']]
    cp = pd.read_parquet(ROOT / 'outputs/step05/routing_checkpoint.parquet')
    tree = cKDTree(np.c_[og.geometry.x, og.geometry.y])
    out = {}
    for key, (name, lng, lat) in STATIONS.items():
        x, y = TO5179.transform(lng, lat)
        d, k = tree.query([x, y])
        gid = og.gid.iloc[k]
        path = cp.loc[cp.gid == gid, 'path'].iloc[0]
        with np.load(ROOT / path) as z:
            od = z['od']
        best = np.where(np.isfinite(od).any(axis=1), np.nanmin(np.where(np.isfinite(od), od, np.nan), axis=1), np.nan)
        out[key] = dict(name=name, lng=lng, lat=lat, proxyGid=gid, proxyDistanceM=round(float(d), 1),
                        onwardS=[None if not np.isfinite(v) else int(round(v)) for v in best])
    return out


def main():
    g500, g250, o = cluster()
    dem = demand(g250)
    near, stops, w = virtual_stops(g500, dem)
    usable = {}
    for t, d in near.items():
        ok = pd.Series(w * (d <= R10)).groupby(dem.gid.values).sum() / pd.Series(w).groupby(dem.gid.values).sum()
        usable[t] = ok.reindex(o.gid).fillna(0).to_numpy()
    cover = {t: dict(walk5=float(w[d <= R5].sum() / w.sum()), walk10=float(w[d <= R10].sum() / w.sum())) for t, d in near.items()}
    clinic_of, clinics, clinic_m = nearest_clinics(o, g500)
    bits, reach = bus_bits(o)
    wpop = o.population.to_numpy()
    baseline = float((reach.mean(axis=1) * wpop).sum() / wpop.sum())
    onward = station_onward()

    origins = []
    for i, r in o.iterrows():
        lng, lat = lonlat(r.geometry.x, r.geometry.y)
        origins.append(dict(key=str(i), gid=r.gid, parent_gid=r.parent_gid, population=float(r.population), x=lng, y=lat,
                            clinic=clinic_of[i], usable={f't{t}': round(float(usable[t][i]), 4) for t in [0] + TIERS}, bus=bits[i]))
    grids = []
    for r in g500.to_crs(4326).itertuples():
        ring = [[round(x, 6), round(y, 6)] for x, y in r.geometry.exterior.coords]
        grids.append(dict(type='Feature', geometry=dict(type='Polygon', coordinates=[ring]), properties=dict(gid=r.gid, population=float(r.population))))
    tiers = [dict(id=f't{t}', stops=t, walk5=round(cover[t]['walk5'], 4), walk10=round(cover[t]['walk10'], 4)) for t in TIERS]
    places = [dict(id='clinic', name='가까운 내과·정형외과', kind='출발지별 최근접 의원 직결')] + \
             [dict(id=k, name=v['name'], kind='역 환승', lng=v['lng'], lat=v['lat']) for k, v in onward.items()]
    data = dict(
        source='Step7 C002 (0.8m/s·연속보행 10분·30분·하위 30%·Queen) / Step9 출발시각별 30분 도달 / 가상정류장 최대피복',
        areaName='구산·법곳·가좌 일대', clusterId=CLUSTER,
        totalPopulation=round(float(wpop.sum()), 1), totalGrids=len(grids), originCount=len(origins),
        existing=dict(walk5=round(cover[0]['walk5'], 4), walk10=round(cover[0]['walk10'], 4)),
        tiers=tiers, stops=stops, clinics=clinics, places=places,
        access=dict(baselineShare=round(baseline, 4), waitS=WAIT_S, detour=DETOUR, budgetS=1800, finalWalkS=FINAL_WALK_S,
                    departureStartS=30600, departureIntervalS=60, departureCount=511,
                    onward={k: dict(proxyGid=v['proxyGid'], proxyDistanceM=v['proxyDistanceM'], onwardS=v['onwardS']) for k, v in onward.items()}),
        budget=dict(dailyCostPerVehicle=DAILY_COST, days=365, defaultVehicles=2, maxVehicles=3),
        grids=grids, origins=origins)
    (DIST / 'data.json').write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps(dict(population=data['totalPopulation'], grids=len(grids), origins=len(origins), baseline=baseline,
                          existing=data['existing'], tiers=tiers, clinics=[c['name'] for c in clinics],
                          clinic_km=float((clinic_m * wpop).sum() / wpop.sum() / 1000),
                          onward={k: (v['proxyGid'], v['proxyDistanceM'], sum(x is not None for x in v['onwardS'])) for k, v in onward.items()}),
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
