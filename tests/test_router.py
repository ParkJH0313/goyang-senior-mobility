"""Independent exhaustive itineraries for small boundary/overtaking fixtures."""
import unittest
import numpy as np
from src.router import query,profile

def links(n,rows):
    rows=sorted(rows);ptr=np.zeros(n+1,np.int64)
    for s,t,w,m,e in rows:ptr[s+1]+=1
    ptr=np.cumsum(ptr)
    return ptr,np.array([r[1] for r in rows],np.int32),np.array([r[2] for r in rows],float),np.array([r[3] for r in rows],float),np.array([r[4] for r in rows],float),np.full(len(rows),-1,np.int32)

def pack(trips,ns):
    ptr=[0];st=[];ar=[];de=[];drop=[];events=[]
    for tid,trip in enumerate(trips):
        for s,a,d,pick,off in trip:
            pos=len(st);st.append(s);ar.append(a);de.append(d);drop.append(off)
            if pick==0:events.append((s,d,tid,pos))
        ptr.append(len(st))
    events.sort();ep=np.zeros(ns+1,np.int64)
    for s,d,t,p in events:ep[s+1]+=1
    return (np.array(ptr,np.int64),np.array(st,np.int32),np.array(ar,np.int32),np.array(de,np.int32),np.array(drop,np.int32),np.cumsum(ep),np.array([x[3] for x in events],np.int32),np.array([x[1] for x in events],np.int32),np.array([x[2] for x in events],np.int32))

def reference(start,budget,trips,os,of,ss,sf,maxboards):
    # Enumerate all boarding positions and all downstream alighting events.
    best=np.full(2,np.inf)
    for s,f,w,m,e in of:
        if w<=budget:best[f]=min(best[f],w)
    stack=[(t,start+w,0) for s,t,w,m,e in os]
    while stack:
        stop,ready,used=stack.pop()
        if used==maxboards:continue
        for trip in trips:
            for p,(s,a,d,pick,off) in enumerate(trip):
                if s!=stop or pick or d<ready or d>start+budget:continue
                for t,arr,dep,pick,off in trip[p+1:]:
                    if off or arr>start+budget:continue
                    for s,f,w,m,e in sf:
                        if s==t and arr+w<=start+budget:best[f]=min(best[f],arr+w-start)
                    for s,v,w,m,e in ss:
                        if s==t and arr+e<=start+budget:stack.append((v,arr+e,used+1))
    return best

class RoutingTests(unittest.TestCase):
    def test_random_timetables_against_exhaustive_reference(self):
        rng=np.random.default_rng(20261017)
        os=[(0,0,5.,3.5,5.),(0,1,12.,8.4,12.)];of=[(0,1,60.,42.,60.)]
        ss=[(i,j,float(abs(i-j)*4),float(abs(i-j)*2.8),float(abs(i-j)*4+5)) for i in range(4) for j in range(4)]
        sf=[(2,0,10.,7.,10.),(3,1,20.,14.,20.)]
        walks=(links(1,os),links(1,of),links(4,ss),links(4,sf))
        for case in range(12):
            trips=[]
            for k in range(5):
                order=rng.choice(4,3,replace=False);clock=int(rng.integers(0,100));trip=[]
                for stop in order:
                    clock+=int(rng.integers(1,50));trip.append((int(stop),clock,clock,int(rng.random()<.1),int(rng.random()<.1)))
                trips.append(trip)
            tt=pack(trips,4)
            for start in [0,30,90]:
                for budget in [50,120,250]:
                    actual=query(0,start,budget,2,2,5,tt,walks)[0]
                    expected=reference(start,budget,trips,os,of,ss,sf,2)
                    np.testing.assert_allclose(actual,expected)

    def test_unknown_access_is_traced_only_in_optimistic_search(self):
        trips=[[(0,10,10,0,0),(1,100,100,0,0)]]
        actual=(links(1,[]),links(1,[]),links(2,[]),links(2,[(1,0,0.,0.,0.)]))
        assumed=list(links(1,[(0,0,0.,0.,0.)]));assumed[5][:]=0
        optimistic=(tuple(assumed),actual[1],actual[2],actual[3]);tt=pack(trips,2)
        self.assertTrue(np.isinf(query(0,0,120,2,3,60,tt,actual)[0][0]))
        got=query(0,0,120,2,3,60,tt,optimistic)
        self.assertEqual(got[0][0],100.)
        self.assertEqual(got[4][0],0)

    def test_total_walking_above_old_cap_is_allowed(self):
        trips=[[(0,600,600,0,0),(1,700,700,0,0)],[(2,1360,1360,0,0),(3,1460,1460,0,0)],[(4,2120,2120,0,0),(5,2220,2220,0,0)]]
        walks=(links(1,[(0,0,600.,420.,600.)]),links(1,[]),links(6,[(1,2,600.,420.,660.),(3,4,600.,420.,660.)]),links(6,[(5,0,600.,420.,600.)]))
        result,facility,components,legs,_=query(0,0,3000,2,3,60,pack(trips,6),walks)
        self.assertEqual(result[0],2820.)
        self.assertEqual(components[0],2400.)
        self.assertEqual(components[5],600.)

    def test_separate_walk_wait_and_preparation_reconstruction(self):
        from src.path_diagnosis import decompose
        trips=[[(0,0,0,0,0),(1,100,100,0,0)],[(2,400,400,0,0),(3,500,500,0,0)]]
        walks=(links(1,[(0,0,0.,0.,0.)]),links(1,[]),links(4,[(1,2,100.,70.,300.)]),links(4,[(3,0,0.,0.,0.)]))
        result,facility,c,legs,_=query(0,0,600,2,3,60,pack(trips,4),walks)
        d=decompose(0,0,facility,legs,walks);d['transfer_wait_s']-=c[4]
        self.assertEqual(result[0],500.)
        self.assertEqual(d['transfer_walk_s'],100.)
        self.assertEqual(d['transfer_wait_s'],140.)
        self.assertEqual(c[4],60.)
        self.assertEqual(c[3],200.)

    def test_parallel_profile_and_resumed_batches_equal_scalar(self):
        trips=[[(0,10,10,0,0),(1,100,100,0,0)],[(0,30,30,0,0),(1,80,80,0,0)]]
        walks=(links(1,[(0,0,0.,0.,0.)]),links(1,[]),links(2,[]),links(2,[(1,0,0.,0.,0.)]))
        tt=pack(trips,2);times=np.array([0,10,11,29,30,31],np.int32)
        full=profile(0,times,100,2,3,60,tt,walks)
        parts=[profile(0,t,100,2,3,60,tt,walks) for t in [times[:2],times[2:]]]
        for k in range(5):np.testing.assert_equal(full[k],np.concatenate([p[k] for p in parts]))
        for i,t in enumerate(times):
            scalar=query(0,int(t),100,2,3,60,tt,walks)
            for k in range(5):np.testing.assert_equal(full[k][i],scalar[k])

    def test_overtaking_transfer_and_boundaries(self):
        trips=[[(0,600,600,0,0),(1,1100,1100,0,0)],[(0,660,660,0,0),(1,900,900,0,0)],[(2,1200,1200,0,0),(3,1400,1400,0,0)],[(1,901,901,0,0),(3,1000,1000,0,0)]]
        os=[(0,0,600.,420.,600.)];of=[(0,1,600.,420.,600.)]
        ss=[(1,2,100.,70.,300.)];sf=[(1,0,100.,70.,100.),(3,0,100.,70.,100.)]
        walk=(links(1,os),links(1,of),links(4,ss),links(4,sf));tt=pack(trips,4)
        for start in [0,1,60,61,300]:
            for budget in [599,600,999,1000,1500,1800]:
                got,f,c,legs,causes=query(0,start,budget,2,3,60,tt,walk)
                np.testing.assert_allclose(got,reference(start,budget,trips,os,of,ss,sf,3))
                if f>=0:
                    self.assertAlmostEqual(c[0]+c[2]+c[3]+c[4],c[7]);self.assertLessEqual(c[5],600)
        self.assertEqual(query(0,0,1000,2,3,60,tt,walk)[0][0],1000)
    def test_pickup_dropoff(self):
        trips=[[(0,0,0,1,0),(1,100,100,0,0)],[(0,10,10,0,0),(1,90,90,0,1)]]
        walks=(links(1,[(0,0,0.,0.,0.)]),links(1,[]),links(2,[]),links(2,[(1,0,0.,0.,0.)]))
        self.assertTrue(np.isinf(query(0,0,1000,2,3,60,pack(trips,2),walks)[0]).all())
    def test_boarding_limit(self):
        trips=[[(i,100+i*200,100+i*200,0,0),(i+1,200+i*200,200+i*200,0,0)] for i in range(4)]
        walks=(links(1,[(0,0,0.,0.,0.)]),links(1,[]),links(5,[(i,i,0.,0.,60.) for i in range(5)]),links(5,[(4,0,0.,0.,0.)]))
        self.assertTrue(np.isinf(query(0,0,2000,2,3,60,pack(trips,5),walks)[0][0]))
        self.assertEqual(query(0,0,2000,2,4,60,pack(trips,5),walks)[0][0],800)

if __name__=='__main__':unittest.main()
