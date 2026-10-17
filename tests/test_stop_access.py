"""Regression fixtures for inherited access rules, not desired research outcomes."""
import unittest
from types import SimpleNamespace
import geopandas as gpd,shapely
from shapely.geometry import Point,LineString
from src.stop_access import StopAccess,central_stop,StationEntrances,Crossings,named_stations

def fake_net(highway='footway',ground_y=4):
    rows=[dict(segment_id='elevated',osm_way_id=1,u='1',v='2',layer='1',level='',bridge='yes',tunnel='',highway=highway,name='',geometry=LineString([(-100,0),(100,0)])),dict(segment_id='ground',osm_way_id=2,u='3',v='4',layer='',level='',bridge='',tunnel='',highway='residential',name='',geometry=LineString([(-100,ground_y),(100,ground_y)]))]
    f=gpd.GeoDataFrame(rows,geometry='geometry',crs=5179);g=f.iloc[[1]]
    access=gpd.GeoDataFrame({'highway':[],'name':[],'geometry':[]},geometry='geometry',crs=5179)
    return SimpleNamespace(physical=f,ground=g,all_tree=shapely.STRtree(f.geometry.values),ground_tree=shapely.STRtree(g.geometry.values),access=access,snap=lambda p,r:({'length_m':ground_y,'connection_status':'proxy'},''),blocked=lambda x:False)

class AccessTests(unittest.TestCase):
    def test_explicit_bidirectional_same_station_transfer_shares_entrance(self):
        import pandas as pd
        matcher=StationEntrances.__new__(StationEntrances)
        matcher.groups=[{},{}];matcher.stop_group={'a':0,'b':1}
        con={'entrance_osm_id':'entry','target_segment':'edge','measure_m':0.,'fixed_s':180.}
        matcher.connections={1:[con]}
        stops=pd.DataFrame([dict(stop_key=1,stop_id='a',station_name='도봉산',is_rail=True),dict(stop_key=2,stop_id='b',station_name='도봉산',is_rail=True)])
        one_way=pd.DataFrame([dict(from_stop_key=1,to_stop_key=2,transfer_type=2)])
        matcher.share_explicit_station_entrances(stops,one_way);self.assertEqual(matcher.for_stop('a'),[])
        both=pd.concat([one_way,pd.DataFrame([dict(from_stop_key=2,to_stop_key=1,transfer_type=2)])],ignore_index=True)
        matcher.share_explicit_station_entrances(stops,both)
        self.assertEqual(matcher.for_stop('a')[0]['fixed_s'],180.)
        self.assertEqual(matcher.for_stop('a')[0]['entrance_association'],'explicit_bidirectional_gtfs_same_station_entrance')
        matcher.connections={1:[con]};stops.loc[0,'station_name']='도봉'
        matcher.share_explicit_station_entrances(stops,both);self.assertEqual(matcher.for_stop('a'),[])
    def test_short_station_name_inside_another_name_is_not_a_second_match(self):
        self.assertEqual(named_stations('신용산역4번출구',{'신용산','용산'}),{'신용산'})
        self.assertEqual(named_stations('신용산역에서용산역방향',{'신용산','용산'}),{'신용산','용산'})
    def test_explicit_entrance_assigns_full_station_name(self):
        import pandas as pd
        net=fake_net()
        net.access=gpd.GeoDataFrame([dict(railway='subway_entrance',passage_status='include',tags_json='{"name":"신용산역 4번출구"}',in_network=0,osm_node_id=5,geometry=Point(5,0))],geometry='geometry',crs=5179)
        stops=pd.DataFrame([dict(stop_id='a',station_name='신용산',is_rail=True,x_5179=0,y_5179=0),dict(stop_id='b',station_name='용산',is_rail=True,x_5179=20,y_5179=0)])
        cfg={'station_group_radius_m':800,'rail_entrance_search_m':500,'station_second_gap_m':50,'station_second_ratio':1.5,'connector_search_m':720,'rail_entrance_s':180}
        matcher=StationEntrances(net,stops,cfg)
        self.assertEqual(len(matcher.for_stop('a')),1);self.assertEqual(matcher.for_stop('b'),[])
        # An explicit name outside the search radius cannot be reassigned by proximity.
        stops.loc[stops.stop_id.eq('a'),'x_5179']=900
        matcher=StationEntrances(net,stops,cfg)
        self.assertEqual(matcher.for_stop('a'),[]);self.assertEqual(matcher.for_stop('b'),[])
    def test_repeated_entrance_fields_do_not_invent_another_station_name(self):
        import pandas as pd
        net=fake_net()
        net.access=gpd.GeoDataFrame([dict(railway='subway_entrance',passage_status='include',tags_json='{"name":"반포역 1번출구","name:ko":"반포역 1번출구"}',in_network=0,osm_node_id=5,geometry=Point(5,0))],geometry='geometry',crs=5179)
        stops=pd.DataFrame([dict(stop_id='a',station_name='반포',is_rail=True,x_5179=0,y_5179=0),dict(stop_id='b',station_name='구반포',is_rail=True,x_5179=900,y_5179=0)])
        cfg={'station_group_radius_m':800,'rail_entrance_search_m':500,'station_second_gap_m':50,'station_second_ratio':1.5,'connector_search_m':720,'rail_entrance_s':180}
        matcher=StationEntrances(net,stops,cfg)
        self.assertEqual(len(matcher.for_stop('a')),1);self.assertEqual(matcher.for_stop('b'),[])
    def test_same_road_median_crossing_beyond_100m_is_reachable(self):
        # A crossing 250m along the same road must not become a missing-data case.
        net=fake_net('footway',0)
        roads=net.ground.copy();roads['name']='중앙로'
        roads.geometry=[LineString([(-400,0),(400,0)])]
        crossings=roads.copy();crossings['segment_id']='crossing';crossings['highway']='footway'
        crossings.geometry=[LineString([(250,-10),(250,10)])]
        finder=Crossings.__new__(Crossings);finder.net=net
        finder.roads=roads;finder.rt=shapely.STRtree(roads.geometry.values)
        finder.cross=crossings;finder.ct=shapely.STRtree(crossings.geometry.values)
        finder.points=net.access;finder.pt=shapely.STRtree([])
        net.record=lambda p,line,sid,end,status,oid:dict(length_m=line.length,target_segment=sid,geometry=line)
        con,reason=finder.connect(Point(0,2),720)
        self.assertEqual(reason,'');self.assertAlmostEqual(con['length_m'],250.)
        self.assertEqual(con['geometry'].coords[-1],(250.,2.))
        con,reason=finder.connect(Point(0,2),100)
        self.assertIsNone(con)
    def test_crossing_name_must_match_road_or_way(self):
        import pandas as pd
        a=pd.Series({'osm_way_id':1,'name':'중앙로'})
        b=pd.Series({'osm_way_id':2,'name':'다른로'})
        self.assertFalse(Crossings.same_road(a,b))
        b['name']='중앙로';self.assertTrue(Crossings.same_road(a,b))
    def test_footbridge_proximity_does_not_make_surface_stop_elevated(self):
        net=fake_net();config={'connector_search_m':720,'stop_poi_search_m':40,'stop_road_evidence_m':20,'stop_ground_fallback_m':50}
        con,why=StopAccess(net,config).connect(Point(0,1),'학교');self.assertIsNotNone(con);self.assertEqual(why,'')
    def test_elevated_motorroad_without_near_ground_stays_unresolved(self):
        net=fake_net('primary',100);config={'connector_search_m':720,'stop_poi_search_m':40,'stop_road_evidence_m':20,'stop_ground_fallback_m':50}
        con,why=StopAccess(net,config).connect(Point(0,1),'불명정류장');self.assertIsNone(con);self.assertEqual(why,'stop_level_requires_evidence')
    def test_median_name_variants(self):
        for name in ['가(중)','가(중앙)','가중앙차로','가중앙정류장']:self.assertTrue(central_stop(name))
        self.assertFalse(central_stop('중앙역'))
    def test_rail_unnamed_entrance_between_stations_is_not_assigned(self):
        import pandas as pd
        net=fake_net();net.access=gpd.GeoDataFrame([dict(railway='subway_entrance',passage_status='include',tags_json='{}',in_network=0,osm_node_id=5,geometry=Point(5,0))],geometry='geometry',crs=5179)
        stops=pd.DataFrame([dict(stop_id='a',station_name='가',is_rail=True,x_5179=0,y_5179=0),dict(stop_id='b',station_name='나',is_rail=True,x_5179=10,y_5179=0)])
        cfg={'station_group_radius_m':800,'rail_entrance_search_m':500,'station_second_gap_m':50,'station_second_ratio':1.5,'connector_search_m':720,'rail_entrance_s':180}
        matcher=StationEntrances(net,stops,cfg);self.assertEqual(matcher.for_stop('a'),[]);self.assertEqual(matcher.for_stop('b'),[])
if __name__=='__main__':unittest.main()
