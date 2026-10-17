"""Independent spatial and weighting boundary fixtures, not research examples."""
import unittest
from types import SimpleNamespace
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import box,Point,LineString
from scipy.sparse import csr_matrix
from src.walking import closure
from src.aggregation import weighted_grid, clusters, bands
from src.timetable import csr_links


class WalkingTests(unittest.TestCase):
    def test_segment_splits_direction_zero_joins_and_parallel_edges(self):
        from src.spatial_network import build_graph
        from scipy.sparse.csgraph import dijkstra
        edge=gpd.GeoDataFrame([
            dict(segment_id='a',u='A',v='B',length_m=10.,direction=1,geometry=LineString([(0,0),(10,0)])),
            dict(segment_id='a',u='A',v='B',length_m=10.,direction=1,geometry=LineString([(0,0),(10,0)])),
            dict(segment_id='b',u='D',v='C',length_m=5.,direction=1,geometry=LineString([(10,0),(15,0)])),
        ],geometry='geometry',crs=5179)
        physical=edge.drop_duplicates('segment_id').set_index('segment_id',drop=False);physical.index.name=None
        net=SimpleNamespace(edges=edge,physical=physical)
        con=pd.DataFrame({'target_segment':['a','a'],'measure_m':[4.,8.]})
        override=gpd.GeoDataFrame([dict(geometry_role='ground_network_join',geometry_id='join',from_ref='osm_node:B',to_ref='osm_node:D',geometry=Point(10,0))],geometry='geometry',crs=5179)
        ptr,idx,cost,connections,ids=build_graph(net,con,override)
        graph=csr_matrix((cost,idx,ptr),shape=(len(ids),len(ids)));dist=dijkstra(graph,directed=True)
        a,b=connections.graph_node.to_numpy()
        self.assertAlmostEqual(dist[a,b],4.)
        self.assertAlmostEqual(dist[ids.index('A'),ids.index('C')],15.)
        self.assertTrue(np.isinf(dist[ids.index('C'),ids.index('A')]))
        self.assertTrue(np.any(cost==0.))

    def test_full_leg_includes_both_connectors_and_no_reset_at_stop(self):
        # A stop at 200m must not reset the limit before the facility at 400m.
        graph=csr_matrix(([200.,200.,.001],([0,1,2],[1,2,3])),shape=(4,4))
        con=pd.DataFrame([
            dict(entity_type='origin',entity_index=0,graph_node=0,length_m=20.,fixed_s=0.),
            dict(entity_type='stop',entity_index=0,graph_node=1,length_m=0.,fixed_s=0.),
            dict(entity_type='facility',entity_index=0,graph_node=2,length_m=60.,fixed_s=0.),
            dict(entity_type='facility',entity_index=1,graph_node=3,length_m=60.,fixed_s=0.),
        ])
        ctx=SimpleNamespace(config={'walk_speeds_mps':[.6,.7,.8],'max_continuous_walk_s':600})
        result=closure(ctx,graph.indptr,graph.indices,graph.data,con)
        pairs=set(zip(result.source_type,result.source_index,result.target_type,result.target_index))
        self.assertIn(('origin',0,'facility',0),pairs)
        self.assertNotIn(('origin',0,'facility',1),pairs)
        self.assertAlmostEqual(result.query("source_type=='origin' and target_type=='facility'").length_m.iloc[0],480.)
        self.assertNotIn(('stop',0,'origin',0),pairs)

    def test_minimum_transfer_elapsed_is_not_added_as_walking(self):
        frame=pd.DataFrame(dict(source_index=[0],target_index=[1],walk_s=[100.],length_m=[70.],min_elapsed_s=[300.]))
        pack=csr_links(frame,2,transfer=True,prep=60)
        self.assertEqual(pack[2][0],100.)
        self.assertEqual(pack[4][0],300.)
        self.assertEqual(pack[4][0]-pack[2][0]-60,140.)


class AggregationTests(unittest.TestCase):
    def test_original_population_denominator_and_missing_child(self):
        small=pd.DataFrame({'gid':['a','b'],'parent_gid':['p','p'],'population':[1.,3.], 'score_status':['valid','valid']})
        large=pd.DataFrame({'gid':['p'],'population':[4.]})
        profiles=np.array([[0.,4.],[4.,0.]])
        result,curves=weighted_grid(small,large,profiles)
        np.testing.assert_equal(curves,[[3.,1.]])
        self.assertEqual(result.score.iloc[0],2.)
        small.loc[1,'score_status']='connector_unresolved'
        result,curves=weighted_grid(small,large,profiles)
        self.assertTrue(np.isnan(result.score.iloc[0]))
        self.assertEqual(result.valid_population_ratio.iloc[0],.25)
        self.assertTrue(np.isnan(curves).all())

    def test_queen_corner_tie_inclusion_singleton_and_rank(self):
        coords=[(0,0),(500,500),(2000,0),(4000,0),(4500,0)]
        frame=gpd.GeoDataFrame({'gid':['a','b','c','d','e'],'population':[2.,2.,4.,9.,9.], 'score':[0.,1.,1.,4.,5.], 'score_status':['valid']*5}, geometry=[box(x,y,x+500,y+500) for x,y in coords],crs=5179)
        low,summary,membership,qa=clusters(frame,.4,'fixture')
        self.assertEqual(qa['order_statistic'],2)
        self.assertEqual(set(low.gid),{'a','b','c'})
        self.assertEqual(len(summary),2)
        self.assertEqual(summary.anchor_gid.tolist(),['a','c'])
        self.assertEqual(summary.grid_count.tolist(),[2,1])
        shuffled=clusters(frame.sample(frac=1,random_state=12),.4,'fixture')[1]
        self.assertEqual(summary.membership_hash.tolist(),shuffled.membership_hash.tolist())

    def test_511_time_samples_keep_final_minute(self):
        times=np.arange(30600,61201,60);labels=bands(times)
        self.assertEqual(len(times),511)
        self.assertEqual(np.sum(labels=='08:30–09:00'),30)
        self.assertEqual(np.sum(labels=='16:00–17:00'),61)


if __name__=='__main__':unittest.main()
