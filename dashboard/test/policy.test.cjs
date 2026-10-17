const {test}=require('node:test'),assert=require('node:assert/strict');
const model=require('../dist/model.js'),data=require('../dist/data.json');
const {createScenarios,validateScenario}=require('../scenario.cjs');
const {createRouter}=require('../routing.cjs');
const {routeFixture}=require('./fixtures.cjs');
const scenario={tier:'t36',destination:'baek',vehicles:2,vehicle:'electric',conversion:.3,occupancy:2.5,waitBaseMin:14.5};
test('nearby clinics keep their original baseline and use each origin medical destination',()=>{
 assert.ok(Math.abs(data.access.baselineShare-.14584373377531057)<1e-12);
 assert.deepEqual(data.clinics.filter(c=>c.id!=='baek').map(c=>c.name),['원내과의원','일산중심재활병원']);
 const tiny={...data,origins:[{key:'o',parent_gid:'g',clinic:'c1',bus:'gA==',busBaek:'AA=='}],grids:[{properties:{gid:'g',population:1}}],totalPopulation:1,
  demand:[{origin:'o',population:1,pickups:{t36:[{stop:'s',walkS:60}]}}],access:{...data.access,departureCount:1,baselineShare:1,baekBaselineShare:0}};
 const route={complete:true,destination:'clinic',baseline:{o:{outKm:1,backKm:1}},boarding:{'s|c1':{outKm:2,backKm:2,driveS:1800}}};
 const local=model.evaluate(tiny,{...scenario,destination:'clinic'},route);
 assert.equal(local.access.withDrt,1);assert.equal(local.access.current,1);assert.equal(local.distances.baselineKm,2);
 const direct=model.evaluate(tiny,scenario,{...route,destination:'baek',baseline:{o:{outKm:7,backKm:7}},boarding:{'s|baek':route.boarding['s|c1']}});
 assert.equal(direct.access.withDrt,0);assert.equal(direct.access.current,0);assert.equal(direct.distances.baselineKm,14);
});
test('both connections use Baek; direct adds final walk and feeder adds onward travel',()=>{
 assert.deepEqual(data.places.map(p=>p.id),['clinic','baek','daehwa']);
 assert.ok(Math.abs(data.access.baekBaselineShare-.01423820506676252)<1e-12);
 for(const destination of ['seogu'])assert.throws(()=>validateScenario({...scenario,destination}));
 const tiny={...data,origins:[{key:'o',parent_gid:'g',bus:Buffer.from([0]).toString('base64'),busBaek:Buffer.from([0]).toString('base64')}],grids:[{properties:{gid:'g',population:1}}],totalPopulation:1,
  demand:[{origin:'o',population:1,pickups:{t36:[{stop:'s',walkS:60}]}}],access:{...data.access,baselineShare:0,baekBaselineShare:0,departureCount:1,onward:{daehwa:{target:'baek',departureStartS:30600,departureIntervalS:60,onwardS:Array(541).fill(600)}}}};
 const routes={complete:true,destination:'baek',baseline:{o:{outKm:5,backKm:5}},boarding:{'s|baek':{outKm:4,backKm:4,driveS:1200}}};
 const direct=model.evaluate(tiny,scenario,routes),feeder=model.evaluate(tiny,{...scenario,destination:'daehwa'},{...routes,destination:'daehwa'});
 assert.equal(direct.access.withDrt,1);assert.equal(feeder.access.withDrt,0);assert.equal(direct.distances.baselineKm,feeder.distances.baselineKm);
});
test('no DRT uses transit baseline without routes, cost or claimed emissions totals',async()=>{
 const evaluate=createScenarios(data,{get:async()=>{assert.fail('No DRT must not request driving routes');}});
 for(const destination of ['clinic','baek','daehwa'])for(const vehicles of [1,2,3]){
  const s={...scenario,tier:'none',destination,vehicles},result=await evaluate(s);
  assert.deepEqual(result,model.evaluate(data,s));assert.equal(result.available,true);assert.equal(result.drtEnabled,false);
  assert.equal(result.access.withDrt,model.baselineShare(data,destination));assert.equal(result.budget.annualWon,0);assert.equal(result.budget.vehicles,0);
  assert.equal(result.result.savingKg,0);assert.equal(result.result.trips,0);assert.equal(result.result.baselineKg,null);assert.equal(result.result.drtKg,null);
  assert.equal(result.access.stationaryWaitMin,null);assert.ok(result.cells.every(c=>c.baseline===c.withDrt));
 }
 assert.deepEqual(Object.keys(model.scenarios),['none','t0','t21','t36']);
 assert.throws(()=>validateScenario({...scenario,tier:'t61'}));
 const adopted=model.evaluate(data,{...scenario,tier:'t0'},routeFixture(data));assert.ok(adopted.access.withDrt>adopted.access.current);assert.ok(adopted.budget.annualWon>0);
});
test('carbon is fixed to tailpipe; electric is zero and generation scope is rejected',()=>{
 assert.equal(Object.keys(model.vehicles)[0],'electric');assert.equal(model.factor('electric'),0);
 assert.throws(()=>model.factor('electric','energy'));
 const p={...scenario,population:100,baselineKm:10,drtKm:10};
 assert.equal(model.calculate(p).drtKg,0);assert.equal(model.calculate(p).percent,100);
 assert.equal(model.calculate({...p,conversion:0}).savingKg,0);
 assert.throws(()=>validateScenario({...scenario,emissionScope:'energy'}));
 assert.throws(()=>validateScenario({...scenario,waitMode:'sequential'}));
});
test('scheduled pickup keeps 1.5 minutes at stop and separates home waiting from travel',()=>{
 const t=model.pickupTiming(240,870);assert.deepEqual(t,{homeWaitS:540,walkS:240,stopWaitS:90,fromHomeS:330,fromCallS:870});
 assert.equal(t.homeWaitS+t.fromHomeS,t.fromCallS);
 assert.equal(model.pickupTiming(600,300).fromCallS,690);assert.equal(model.pickupTiming(600,300).homeWaitS,0);
 const r=routeFixture(data,'baek',600),one=model.evaluate(data,{...scenario,vehicles:1},r),three=model.evaluate(data,{...scenario,vehicles:3},r);
 assert.ok(three.access.waitMin<one.access.waitMin);assert.ok(three.access.homeWaitMin<one.access.homeWaitMin);
 assert.equal(one.access.stationaryWaitMin,1.5);assert.equal(one.access.timeBasis,'home-departure');
 assert.equal(three.access.withDrt,one.access.withDrt);assert.equal(three.result.savingKg,one.result.savingKg);
 assert.ok(three.access.withDrtFromCall>one.access.withDrtFromCall);
 assert.equal(three.budget.annualWon,3*one.budget.annualWon);
});
test('vehicle budget substitutes costs without adding purchase price to annual depreciation again',()=>{
 const l=model.budgetEstimate(2,data.budget,'lpg'),e=model.budgetEstimate(2,data.budget,'electric'),h=model.budgetEstimate(2,data.budget,'hybrid');
 assert.ok(Math.abs(l.annualWon-409112440)<.0001);assert.ok(e.annualWon<h.annualWon&&h.annualWon<l.annualWon);
 assert.equal(e.commonDailyWon,l.commonDailyWon);assert.equal(e.purchaseWon,2*model.vehicles.electric.purchaseWon);
 assert.ok(Math.abs(e.annualWon-2*365*(e.commonDailyWon+e.energy+e.maintenance+e.depreciation))<1e-7);
});
test('layouts change eligible population and carbon; aggregate equals population-weighted cells',()=>{
 const r=routeFixture(data),list=data.tiers.map(t=>model.evaluate(data,{...scenario,tier:t.id},r));
 assert.ok(list[0].eligiblePopulation<list[1].eligiblePopulation&&list[1].eligiblePopulation<list[2].eligiblePopulation);
 assert.notEqual(list[1].result.trips,list[2].result.trips);assert.notEqual(list[1].result.savingKg,list[2].result.savingKg);
 for(const result of list){
  assert.ok(Math.abs(result.cells.reduce((n,c)=>n+c.population*c.withDrt,0)/data.totalPopulation-result.access.withDrt)<1e-10);
  assert.ok(result.access.withDrt>=result.access.current-1e-4);
 }
 const b=structuredClone(r);for(const route of Object.values(b.boarding))route.outKm+=10;
 const delta=data.tiers.map(t=>model.evaluate(data,{...scenario,tier:t.id,vehicle:'lpg'},b).result.drtKg-model.evaluate(data,{...scenario,tier:t.id,vehicle:'lpg'},r).result.drtKg);
 assert.ok(delta.some(d=>d>0));
});
test('missing boarding route fails closed and server and browser evaluate the same scenario',async()=>{
 const r=routeFixture(data);const evaluate=createScenarios(data,{get:async()=>r});
 const result=await evaluate(scenario);assert.deepEqual(result,model.evaluate(data,validateScenario(scenario),r));
 const broken={...r,boarding:{}};const fail=await createScenarios(data,{get:async()=>broken})(scenario);
 assert.equal(fail.available,false);assert.equal(fail.result,null);
});
test('17:00 departure may transfer after 17:00 and still reach within 30 minutes',()=>{
 const tiny={...data,origins:[{key:'o',parent_gid:'g',bus:Buffer.from([0]).toString('base64'),busBaek:Buffer.from([0]).toString('base64'),clinic:'c'}],
  grids:[{properties:{gid:'g',population:1}}],totalPopulation:1,demand:[{origin:'o',population:1,pickups:{t36:[{stop:'s',walkS:60}]}}],
  access:{...data.access,baselineShare:0,baekBaselineShare:0,departureStartS:61200,departureCount:1,onward:{daehwa:{target:'baek',departureStartS:30600,departureIntervalS:60,onwardS:Array(541).fill(300)}}}};
 const r={complete:true,destination:'daehwa',baseline:{o:{outKm:5,backKm:5}},boarding:{'s|baek':{outKm:2,backKm:2,driveS:240}}};
 assert.equal(model.evaluate(tiny,{...scenario,destination:'daehwa'},r).access.withDrt,1);
});
test('snapshot assignments conserve population, obey walking cap, and reference selected stops',()=>{
 assert.equal(data.access.speedMps,.8);assert.equal(data.schemaVersion,6);
 assert.ok(Math.abs(data.demand.reduce((n,d)=>n+d.population,0)-784)<1e-6);
 const stops=Object.fromEntries(data.stops.map(s=>[s.id,s]));
 for(const t of data.tiers){
  assert.equal(data.stops.filter(s=>!s.existing&&s.tiers.includes(t.id)).length,t.stops);
  let eligible=0;for(const d of data.demand){const b=d.boarding[t.id];if(b){assert.ok(stops[b.stop].tiers.includes(t.id));assert.ok(b.walkS>=0&&b.walkS<=600);eligible+=d.population;}}
  assert.ok(Math.abs(eligible/784-t.walk10)<.00006);
 }
 for(let i=1;i<data.tiers.length;i++){const prev=data.tiers[i-1].id,next=data.tiers[i].id;for(const d of data.demand){const ids=new Set(d.pickups[next].map(p=>p.stop));for(const p of d.pickups[prev])assert.ok(ids.has(p.stop));}}
 for(const a of data.locationAudit){assert.ok(a.selectedAddedPopulation>=a.greedyAddedPopulation-1e-7);assert.equal(a.gap,0);}
 for(const h of Object.values(data.access.onward))assert.equal(h.onwardS.length,541);
});
test('Kakao requests use boarding coordinates and same-hospital baseline; reuse on condition changes',async()=>{
 const small={origins:[{key:'o',x:126,y:37,clinic:'c1'}],clinics:[{id:'baek',lng:128,lat:39},{id:'c1',lng:126.5,lat:37.5}],stops:[{id:'s',lng:126.1,lat:37.1}],places:[{id:'clinic'},{id:'baek',lng:128,lat:39,target:'baek'},{id:'daehwa',lng:127.1,lat:38.1,target:'baek'}],demand:[{origin:'o',pickups:{t0:[{stop:'s',walkS:20}],t36:[{stop:'s',walkS:20}]}}]};
 const calls=[];
 const router=createRouter('test-key',small,{fetchImpl:async(url,{body})=>{const q=JSON.parse(body);calls.push({url,q});const points=q.origins||q.destinations;return new Response(JSON.stringify({routes:points.map(p=>({key:p.key,result_code:0,summary:{distance:1000,duration:120}}))}));}});
 const r=await router.get('daehwa');assert.equal(r.boarding['s|baek'].outKm,1);
 assert.ok(calls.some(c=>c.q.origins?.[0].x===126.1&&c.q.destination.x===127.1));
 assert.ok(calls.some(c=>c.q.origins?.[0].x===126&&c.q.destination.x===128));
 const count=calls.length;await router.get('daehwa');assert.equal(calls.length,count);
 const direct=await router.get('baek');assert.equal(direct.boarding['s|baek'].outKm,1);
 assert.ok(calls.some(c=>c.q.origins?.[0].x===126.1&&c.q.destination.x===128));
 assert.ok(!calls.slice(count).some(c=>c.q.origins?.[0].x===126));
 const beforeClinic=calls.length,local=await router.get('clinic');assert.equal(local.boarding['s|c1'].outKm,1);assert.equal(local.boarding['s|baek'],undefined);
 const clinicCalls=calls.slice(beforeClinic);
 assert.ok(clinicCalls.some(c=>c.q.origins?.[0].x===126&&c.q.destination.x===126.5));
 assert.ok(clinicCalls.some(c=>c.q.origins?.[0].x===126.1&&c.q.destination.x===126.5));
 assert.ok(clinicCalls.every(c=>(c.q.destination||c.q.origin).x===126.5));
});

test('a nearer new stop with slower vehicle travel cannot remove an existing reachable trip',()=>{
 const tiny={...data,origins:[{key:'o',parent_gid:'g',bus:Buffer.from([0]).toString('base64'),busBaek:Buffer.from([0]).toString('base64'),clinic:'c'}],grids:[{properties:{gid:'g',population:1}}],totalPopulation:1,
  demand:[{origin:'o',population:1,pickups:{t0:[{stop:'old',walkS:300}],t21:[{stop:'old',walkS:300},{stop:'new',walkS:10}]}}],access:{...data.access,baselineShare:0,baekBaselineShare:0,departureCount:1}};
 const r={complete:true,destination:'baek',baseline:{o:{outKm:5,backKm:5}},boarding:{'old|baek':{outKm:2,backKm:2,driveS:600},'new|baek':{outKm:4,backKm:4,driveS:1500}}};
 const before=model.evaluate(tiny,{...scenario,tier:'t0'},r),after=model.evaluate(tiny,{...scenario,tier:'t21'},r);
 assert.equal(before.access.withDrt,1);assert.equal(after.access.withDrt,1);assert.equal(after.distances.drtKm,4);
});
test('all layouts preserve or improve every grid for every connection under fixed supply assumptions',()=>{
 for(const destination of ['clinic','baek','daehwa']){
  const r=routeFixture(data,destination,900);let prev=null;
  for(const t of data.tiers){const now=model.evaluate(data,{...scenario,tier:t.id,destination},r);
   if(prev){assert.ok(now.access.withDrt>=prev.access.withDrt-1e-10);for(let i=0;i<now.cells.length;i++)assert.ok(now.cells[i].withDrt>=prev.cells[i].withDrt-1e-10);}
   prev=now;
  }
 }
});
