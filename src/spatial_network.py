"""Stable segment references, ground access and directed distance graph splitting."""
from __future__ import annotations
import json,heapq
from collections import defaultdict
import numpy as np,pandas as pd,geopandas as gpd,pyogrio,shapely
from shapely.geometry import Point,LineString
from shapely.ops import substring
from scipy.sparse import csr_matrix
from src.analysis_io import inside,ro,atomic_npz,parquet,log
from src.preprocessing_common import approved

def geometry_overrides():
    f=pd.read_csv(inside('overrides/geometry_overrides.csv'),keep_default_na=False,dtype=str)
    f['geometry']=[Point(float(r.x),float(r.y)) if r.geometry_type=='Point' else shapely.from_wkt(r.wkt) for r in f.itertuples()]
    return gpd.GeoDataFrame(f.drop(columns=['wkt']),geometry='geometry',crs=5179)

class GroundNetwork:
    def __init__(self):
        p=inside('data/processed/osm_walk_network.gpkg')
        self.edges=pyogrio.read_dataframe(p,layer='edges')
        self.physical=self.edges.sort_values('direction',ascending=False).drop_duplicates('segment_id').set_index('segment_id',drop=False)
        self.physical.index.name=None
        self.nodes=pyogrio.read_dataframe(p,layer='nodes').set_index('node_id',drop=False)
        self.access=pyogrio.read_dataframe(p,layer='access_points')
        self.barriers=pyogrio.read_dataframe(p,layer='barriers')
        self.barrier_tree=shapely.STRtree(self.barriers.geometry.values)
        restricted=self.access[self.access.passage_status.ne('include') & (self.access.barrier.fillna('').ne('') | self.access.entrance.fillna('').ne(''))]
        self.restricted_tree=shapely.STRtree(restricted.geometry.values)
        with ro(p) as con:
            hard_ids=set(pd.read_sql_query("SELECT osm_way_id FROM way_decisions WHERE json_extract(tags_json,'$.motorroad')='yes' OR json_extract(tags_json,'$.access') IN ('no','private','military','permit')",con).osm_way_id)
        self.hard_tree=shapely.STRtree(self.physical[self.physical.osm_way_id.isin(hard_ids)].geometry.values)
        excluded=set()
        for r in approved('network_decisions.csv'):
            if r['action']=='forbid_automatic_component_join':excluded.update(r['value']['known_way_ids'])
        e=self.physical
        self.ground=e[e.bridge.fillna('').isin(['','no']) & e.tunnel.fillna('').isin(['','no']) & e.layer.fillna('').isin(['','0']) & e.level.fillna('').isin(['','0']) & ~e.osm_way_id.isin(excluded)].copy()
        self.ground_tree=shapely.STRtree(self.ground.geometry.values)
        self.all_tree=shapely.STRtree(self.physical.geometry.values)
        opening=self.access[self.access.passage_status.eq('include') & (self.access.barrier.isin(['gate','lift_gate','swing_gate','bollard','entrance','cycle_barrier']) | self.access.entrance.fillna('').isin(['yes','main']))]
        self.openings=opening.geometry.values;self.opening_tree=shapely.STRtree(self.openings)
    def blocked(self,line):
        if len(self.restricted_tree.query(line,predicate='dwithin',distance=1.)):return True
        if line.geom_type!='Point' and len(self.hard_tree.query(line,predicate='crosses')):return True
        if line.geom_type=='Point':return False
        for i in self.barrier_tree.query(line,predicate='intersects'):
            hit=line.intersection(self.barriers.geometry.iloc[i])
            if hit.is_empty:continue
            # A passage is only accepted at an explicitly permitted mapped opening.
            cand=self.opening_tree.query(hit.buffer(2),predicate='intersects')
            if len(cand) and hit.difference(shapely.union_all(self.openings[cand]).buffer(2)).is_empty:continue
            return True
        return False
    def snap(self,point,max_distance):
        nearest=self.ground_tree.nearest(point)
        min_d=point.distance(self.ground.geometry.iloc[nearest])
        if min_d>max_distance:return None,'outside_walk_coverage'
        ids=self.ground_tree.query(point.buffer(max_distance),predicate='intersects')
        cand=self.ground.iloc[ids].copy();cand['distance']=cand.geometry.distance(point)
        cand=cand.sort_values(['distance','segment_id'])
        for r in cand.itertuples():
            end=r.geometry.interpolate(r.geometry.project(point));line=LineString([point,end]) if point.distance(end)>1e-8 else point
            if not self.blocked(line):return self.record(point,line,r.segment_id,end,'provisional_connector',''),''
        return None,'no_barrier_safe_ground_connection'
    def record(self,point,line,segment,end,status,override_id,fixed_s=0):
        return dict(target_segment=str(segment),measure_m=float(self.physical.loc[segment].geometry.project(end)),length_m=float(line.length),fixed_s=float(fixed_s),connection_status=status,override_id=override_id,geometry=line)
    def manual(self,row,point,fixed_s=0):
        geom=row.geometry
        endpoints=[(row.from_ref,Point(geom.coords[0])),(row.to_ref,Point(geom.coords[-1]))]
        target=[(ref,p) for ref,p in endpoints if ref.startswith('osm_segment:')]
        if target:
            ref,end=target[-1];sid=ref.split(':',1)[1]
            if sid not in self.physical.index or self.physical.loc[sid].geometry.distance(end)>1e-5:raise ValueError('Override segment changed: '+row.geometry_id)
        else:
            ref,end=next((ref,p) for ref,p in endpoints if ref.startswith('osm_node:'))
            raw=ref.split(':',1)[1]
            matching=self.physical[self.physical.u.eq(raw)|self.physical.v.eq(raw)]
            if matching.empty:
                ids=self.all_tree.query(end.buffer(1e-5));matching=self.physical.iloc[ids]
            matching=matching[matching.geometry.distance(end)<1e-5]
            if matching.empty:raise ValueError('Override node changed: '+row.geometry_id)
            sid=sorted(matching.index)[0]
        return self.record(point,geom,sid,end,'approved_provisional',row.override_id,fixed_s)

def frame(records):
    return gpd.GeoDataFrame(records,geometry='geometry',crs=5179)

def build_graph(net,connections,overrides):
    """Split all referenced segments, preserving direction and endpoint topology."""
    cuts=defaultdict(list);refs={};extra=[]
    for i,r in connections.iterrows():cuts[r.target_segment].append((float(r.measure_m),'access:'+str(i)))
    for r in overrides[overrides.geometry_role.eq('ground_network_join')].itertuples():
        geo=r.geometry
        for side,pos in [('from_ref',0),('to_ref',-1)]:
            ref=getattr(r,side);pt=Point(geo.coords[pos]);key=r.geometry_id+':'+side
            if ref.startswith('osm_segment:'):
                sid=ref.split(':',1)[1]
                if sid not in net.physical.index or net.physical.loc[sid].geometry.distance(pt)>1e-5:raise ValueError('Join no longer matches '+sid)
                cuts[sid].append((net.physical.loc[sid].geometry.project(pt),key))
            elif ref.startswith('osm_node:'):refs[key]=ref.split(':',1)[1]
            else:raise ValueError('Unsupported ground join endpoint '+ref)
        extra.append((r.geometry_id+':from_ref',r.geometry_id+':to_ref',float(geo.length)))
    split={}
    for sid,items in cuts.items():
        row=net.physical.loc[sid];items=sorted([(0.0,'base:'+str(row.u)),(float(row.geometry.length),'base:'+str(row.v))]+items)
        positions=[]
        for m,ref in items:
            if m<1e-6:node=str(row.u);m=0.0
            elif row.geometry.length-m<1e-6:node=str(row.v);m=float(row.geometry.length)
            elif positions and abs(m-positions[-1][0])<1e-6:node=positions[-1][1]
            else:node='split:'+sid+':'+format(m,'.9f')
            refs[ref]=node
            if not positions or abs(m-positions[-1][0])>=1e-6:positions.append((m,node))
        split[sid]=positions
    arcs=[]
    for r in net.edges.itertuples():
        if r.segment_id not in split:arcs.append((str(r.u),str(r.v),float(r.length_m)));continue
        physical=net.physical.loc[r.segment_id];pos=split[r.segment_id]
        reverse=str(r.u)!=str(physical.u)
        for (a,u),(b,v) in zip(pos,pos[1:]):
            if reverse:u,v=v,u
            arcs.append((u,v,(b-a)*r.length_m/physical.geometry.length))
    for a,b,d in extra:
        u,v=refs[a],refs[b];arcs.extend([(u,v,d),(v,u,d)])
    ids=sorted({x for a,b,d in arcs for x in [a,b]});index={v:i for i,v in enumerate(ids)}
    # Min, not sum, for parallel arcs. Explicit zero-cost node joins remain edges.
    compact={}
    for u,v,d in arcs:
        key=(index[u],index[v]);compact[key]=min(d,compact.get(key,float('inf')))
    order=sorted(compact);indptr=np.zeros(len(ids)+1,dtype=np.int64)
    for u,v in order:indptr[u+1]+=1
    np.cumsum(indptr,out=indptr)
    indices=np.array([v for u,v in order],dtype=np.int32);length=np.array([compact[k] for k in order],dtype=np.float64)
    connections=connections.copy();connections['graph_node']=[index[refs['access:'+str(i)]] for i in connections.index]
    return indptr,indices,length,connections,ids
