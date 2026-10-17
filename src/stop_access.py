"""Adopted stop-access rules, reproduced from processed geometry without legacy inputs."""
import json,re
from functools import lru_cache
import numpy as np,pandas as pd,shapely
from shapely.geometry import Point,LineString
from src.analysis_io import ro
ROAD_TYPES={'primary','primary_link','secondary','secondary_link','tertiary','tertiary_link','trunk','trunk_link','residential','unclassified','service','living_street'}
def norm(value):return re.sub(r'[\s.·()\[\]_-]','',re.sub(r'\(중\)|\(중앙\)','',str(value or '')))
def level_key(row):
    def clean(x):return '' if pd.isna(x) else str(x)
    return (clean(row.layer) or '0',clean(row.level) or '0',clean(row.bridge) not in {'','no'},clean(row.tunnel) not in {'','no'})
def is_ground(row):return level_key(row)==('0','0',False,False)
def central_stop(name):return any(mark in str(name) for mark in ['(중)','(중앙)','중앙차로','중앙정류장'])
def join_line(point,end):return point if point.distance(end)<1e-8 else LineString([point,end])

@lru_cache(maxsize=8)
def station_name_pattern(names):
    return re.compile('|'.join(re.escape(name+'역') for name in sorted(names,key=lambda x:(-len(x),x))) or r'(?!)')

def named_stations(label,names):
    """A shorter station name inside another name is not a second station.

    Keep independent mentions ambiguous (e.g. a corridor connecting two stations).
    Use all available station names, not only the nearest spatial candidates.
    """
    pattern=station_name_pattern(tuple(sorted(set(names))))
    return {m.group(0)[:-1] for m in pattern.finditer(label)}

class StopAccess:
    def __init__(self,net,config):
        self.net,self.config=net,config
        self.poi=net.access[net.access.highway.eq('bus_stop')].copy()
        self.poi_tree=shapely.STRtree(self.poi.geometry.values)
    def connect(self,point,name):
        net=self.net;edge=net.physical.iloc[net.all_tree.nearest(point)]
        con,reason=net.snap(point,self.config['connector_search_m'])
        if not is_ground(edge) and edge.highway in ROAD_TYPES:
            ids=self.poi_tree.query(point.buffer(self.config['stop_poi_search_m']),predicate='intersects')
            evidence=any(norm(name)==norm(self.poi.iloc[j]['name']) for j in ids)
            if evidence and edge.geometry.distance(point)<=self.config['stop_road_evidence_m']:
                end=edge.geometry.interpolate(edge.geometry.project(point));line=join_line(point,end)
                if not net.blocked(line):
                    return net.record(point,line,edge.segment_id,end,'same_named_osm_stop_near_elevated_road_proxy',''),''
            distance=net.ground.geometry.iloc[net.ground_tree.nearest(point)].distance(point)
            if distance>self.config['stop_ground_fallback_m']:return None,'stop_level_requires_evidence'
        # Nearby footbridges/underpasses do not establish a bus stop's elevation.
        if con:con['connection_status']='nearest_ground_coordinate_proxy'
        return con,reason

class Crossings:
    def __init__(self,net):
        self.net=net
        with ro('data/processed/osm_walk_network.gpkg') as c:
            ways=pd.read_sql_query("SELECT osm_way_id,tags_json FROM way_decisions WHERE decision='include'",c)
        ids=set(ways.loc[ways.tags_json.map(lambda s:'crossing' in json.loads(s).get('footway','')),'osm_way_id'])
        self.cross=net.ground[net.ground.osm_way_id.isin(ids)];self.ct=shapely.STRtree(self.cross.geometry.values)
        self.roads=net.ground[net.ground.highway.isin(ROAD_TYPES)];self.rt=shapely.STRtree(self.roads.geometry.values)
        self.allroads=net.physical[net.physical.highway.isin(ROAD_TYPES)];self.art=shapely.STRtree(self.allroads.geometry.values)
        self.points=net.access[net.access.highway.fillna('').str.contains('crossing')&net.access.passage_status.eq('include')&net.access.in_network.eq(1)]
        self.pt=shapely.STRtree(self.points.geometry.values);self.incident={}
        for edge in net.physical.itertuples():
            self.incident.setdefault(str(edge.u),[]).append(edge.segment_id)
            self.incident.setdefault(str(edge.v),[]).append(edge.segment_id)
    @staticmethod
    def same_road(a,b):return a.osm_way_id==b.osm_way_id or bool(norm(a['name'])) and norm(a['name'])==norm(b['name'])
    def connect(self,point,radius):
        if not len(self.roads):return None,'median_crossing_not_resolved'
        road=self.roads.iloc[self.rt.nearest(point)];accepted=[]
        if point.distance(road.geometry)>50:return None,'median_crossing_not_resolved'
        for j in self.ct.query(point.buffer(radius),predicate='intersects'):
            edge=self.cross.iloc[j];end=edge.geometry.interpolate(edge.geometry.project(point));crossroad=self.roads.iloc[self.rt.nearest(end)]
            if level_key(road)!=level_key(edge) or not self.same_road(road,crossroad) or end.distance(crossroad.geometry)>40:continue
            line=join_line(point,end)
            if not self.net.blocked(line):accepted.append((line.length,str(edge.segment_id),edge,end,line,'mapped_same_road_crossing_projection'))
        for j in self.pt.query(point.buffer(radius),predicate='intersects'):
            node=self.points.iloc[j];end=node.geometry;crossroad=self.allroads.iloc[self.art.nearest(end)]
            if not self.same_road(road,crossroad) or level_key(road)!=level_key(crossroad) or end.distance(crossroad.geometry)>40:continue
            matches=self.net.physical.loc[self.incident.get(str(node.osm_node_id),[])]
            matches=matches[[level_key(x)==level_key(road) for x in matches.itertuples()]]
            if matches.empty:continue
            edge=matches.sort_values('segment_id').iloc[0];line=join_line(point,end)
            if not self.net.blocked(line):accepted.append((line.length,'node::'+str(node.osm_node_id),edge,end,line,'mapped_same_road_crossing_node'))
        if not accepted:return None,'median_crossing_not_resolved'
        _,ref,edge,end,line,rule=min(accepted,key=lambda x:x[:2]);con=self.net.record(point,line,edge.segment_id,end,rule,'');con['crossing_ref']=ref
        return con,''

class StationEntrances:
    """Named entrance priority; unnamed nearest group needs distance separation."""
    def __init__(self,net,stops,config,transfers=None):
        self.net,self.config=net,config;groups=[];self.stop_group={}
        for name,f in stops[stops.is_rail].groupby('station_name',sort=True):
            remaining=list(f.sort_values('stop_id').itertuples())
            while remaining:
                seed=remaining.pop(0);anchor=Point(seed.x_5179,seed.y_5179);members=[seed]
                near=[x for x in remaining if anchor.distance(Point(x.x_5179,x.y_5179))<=config['station_group_radius_m']]
                members+=near;remove={x.stop_id for x in near};remaining=[x for x in remaining if x.stop_id not in remove]
                idx=len(groups);center=Point(np.mean([x.x_5179 for x in members]),np.mean([x.y_5179 for x in members]))
                groups.append({'name':name,'geometry':center})
                for x in members:self.stop_group[x.stop_id]=idx
        self.groups=groups;tree=shapely.STRtree([x['geometry'] for x in groups]);self.connections={};incident={}
        names={x['name'] for x in groups};name_pattern=station_name_pattern(tuple(sorted(names)))
        for edge in net.physical.itertuples():
            incident.setdefault(str(edge.u),[]).append(edge.segment_id);incident.setdefault(str(edge.v),[]).append(edge.segment_id)
        entries=net.access[net.access.railway.eq('subway_entrance')&net.access.passage_status.eq('include')]
        for r in entries.itertuples():
            tags=json.loads(r.tags_json)
            # Keep field boundaries: "출구" + "반포역" must not invent "구반포역".
            label=' | '.join(str(tags.get(k,'')).replace(' ','') for k in ['name','name:ko','description'])
            nearby=tree.query(r.geometry.buffer(config['rail_entrance_search_m']),predicate='intersects');choices=sorted([(r.geometry.distance(groups[j]['geometry']),int(j)) for j in nearby])
            mentioned={m.group(0)[:-1] for m in name_pattern.finditer(label)}
            named=[x for x in choices if groups[x[1]]['name'] in mentioned]
            selected=named[0] if len(named)==1 and len(mentioned)==1 else choices[0] if not mentioned and choices and (len(choices)==1 or (choices[1][0]-choices[0][0]>=config['station_second_gap_m'] and choices[1][0]>=config['station_second_ratio']*max(choices[0][0],1))) else None
            if selected is None:continue
            segments=incident.get(str(r.osm_node_id),[]) if r.in_network else []
            if segments:
                sid=sorted(segments)[0];con=net.record(r.geometry,r.geometry,sid,r.geometry,'mapped_entrance_existing_node','')
            else:con,_=net.snap(r.geometry,config['connector_search_m'])
            if con:
                con.update(fixed_s=config['rail_entrance_s'],entrance_osm_id=str(r.osm_node_id),entrance_association='explicit_station_name' if named else 'unambiguous_nearest_station_proxy')
                self.connections.setdefault(selected[1],[]).append(con)
        if transfers is not None:
            self.share_explicit_station_entrances(stops,transfers)
    def share_explicit_station_entrances(self,stops,transfers):
        """Use bidirectional same-station GTFS identity despite a misplaced platform centroid.

        No new walking edge is added. Each platform still pays the standard
        entrance-to-platform cost; the raw GTFS coordinates remain untouched.
        """
        rail=stops[stops.is_rail].set_index('stop_key');parent=list(range(len(self.groups)))
        def root(x):
            while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
            return x
        pairs={(r.from_stop_key,r.to_stop_key) for r in transfers.itertuples() if r.transfer_type!=3}
        for a,b in sorted(pairs):
            if (b,a) not in pairs or a not in rail.index or b not in rail.index:continue
            aa,bb=rail.loc[a],rail.loc[b]
            if aa.station_name!=bb.station_name:continue
            ga,gb=self.stop_group[aa.stop_id],self.stop_group[bb.stop_id]
            parent[root(gb)]=root(ga)
        members={}
        for group in range(len(parent)):members.setdefault(root(group),[]).append(group)
        for groups in members.values():
            if len(groups)<2:continue
            for target in groups:
                own=self.connections.setdefault(target,[])
                keys={(x.get('entrance_osm_id'),x['target_segment'],x['measure_m']) for x in own}
                for source in groups:
                    if source==target:continue
                    for con in self.connections.get(source,[]):
                        key=(con.get('entrance_osm_id'),con['target_segment'],con['measure_m'])
                        if key in keys:continue
                        shared=dict(con,entrance_association='explicit_bidirectional_gtfs_same_station_entrance',entrance_donor_group=source)
                        own.append(shared);keys.add(key)
    def for_stop(self,stop_id):return [dict(x) for x in self.connections.get(self.stop_group.get(stop_id),[])]
