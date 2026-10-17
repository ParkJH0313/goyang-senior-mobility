const {test}=require('node:test'),assert=require('node:assert/strict');
const model=require('../dist/model.js'),data=require('../dist/data.json');
const {createScenarios,validateScenario}=require('../scenario.cjs');
const {createRouter}=require('../routing.cjs');
const {routeFixture}=require('./fixtures.cjs');
const scenario={tier:'t36',destination:'clinic',vehicles:2,vehicle:'electric',conversion:.3,occupancy:2.5,emissionScope:'energy',waitBaseMin:14.5,waitMode:'overlap'};
test('electric defaults use actual efficiency and positive generation emissions; tailpipe basis is separate',()=>{
 assert.equal(Object.keys(model.vehicles)[0],'electric');
 assert.equal(model.factor('electric','tailpipe'),0);
 assert.ok(Math.abs(model.factor('electric','energy')-.4173/3.9)<1e-12);
 const p={...scenario,population:100,baselineKm:10,drtKm:10};
 assert.ok(model.calculate(p).drtKg>0);assert.equal(model.calculate({...p,emissionScope:'tailpipe'}).drtKg,0);
 assert.equal(model.calculate({...p,conversion:0}).savingKg,0);
});
test('waiting responds to fleet size; walking cannot disappear or be double counted',()=>{
 assert.ok(model.waitMinutes(1)>model.waitMinutes(2)&&model.waitMinutes(2)>model.waitMinutes(3));
 assert.equal(model.boardingTime(600,300,'overlap'),600);
 assert.equal(model.boardingTime(300,600,'overlap'),600);
 assert.equal(model.boardingTime(300,600,'sequential'),900);
 const r=routeFixture(data,'clinic',600);
 const one=model.evaluate(data,{...scenario,vehicles:1},r),three=model.evaluate(data,{...scenario,vehicles:3},r);
 assert.ok(three.access.withDrt>one.access.withDrt);
 assert.equal(three.budget.annualWon,3*one.budget.annualWon);
 // Allocated emissions do not count a fleet factor twice; whole-fleet VKT is unknown.
 assert.equal(three.result.savingKg,one.result.savingKg);
});
test('layouts change eligible population and carbon; aggregate equals population-weighted cells',()=>{
 const r=routeFixture(data),list=data.tiers.map(t=>model.evaluate(data,{...scenario,tier:t.id},r));
 assert.ok(list[0].eligiblePopulation<list[1].eligiblePopulation&&list[1].eligiblePopulation<list[2].eligiblePopulation);
 assert.notEqual(list[1].result.trips,list[2].result.trips);assert.notEqual(list[1].result.savingKg,list[2].result.savingKg);
 for(const result of list){
  assert.ok(Math.abs(result.cells.reduce((n,c)=>n+c.population*c.withDrt,0)/data.totalPopulation-result.access.withDrt)<1e-10);
  assert.ok(result.access.withDrt>=data.access.baselineShare-1e-4);
 }
 const b=structuredClone(r),key=Object.keys(b.boarding)[0];b.boarding[key].outKm+=10;
 const delta=data.tiers.map(t=>model.evaluate(data,{...scenario,tier:t.id},b).result.drtKg-model.evaluate(data,{...scenario,tier:t.id},r).result.drtKg);
 assert.ok(delta.some(d=>d>0));
});
test('missing boarding route fails closed and server and browser evaluate the same scenario',async()=>{
 const r=routeFixture(data);const evaluate=createScenarios(data,{get:async()=>r});
 const result=await evaluate(scenario);assert.deepEqual(result,model.evaluate(data,validateScenario(scenario),r));
 const broken={...r,boarding:{}};const fail=await createScenarios(data,{get:async()=>broken})(scenario);
 assert.equal(fail.available,false);assert.equal(fail.result,null);
});
test('17:00 departure may transfer after 17:00 and still reach within 30 minutes',()=>{
 const tiny={...data,origins:[{key:'o',parent_gid:'g',bus:Buffer.from([0]).toString('base64'),clinic:'c'}],
  grids:[{properties:{gid:'g',population:1}}],totalPopulation:1,demand:[{origin:'o',population:1,boarding:{t36:{stop:'s',walkS:60}}}],
  access:{...data.access,baselineShare:0,departureStartS:61200,departureCount:1,onward:{daehwa:{target:'baek',departureStartS:30600,departureIntervalS:60,onwardS:Array(541).fill(300)}}}};
 const r={complete:true,destination:'daehwa',baseline:{o:{outKm:5,backKm:5}},boarding:{'s|baek':{outKm:2,backKm:2,driveS:240}}};
 assert.equal(model.evaluate(tiny,{...scenario,destination:'daehwa'},r).access.withDrt,1);
});
test('snapshot assignments conserve population, obey walking cap, and reference selected stops',()=>{
 assert.equal(data.access.speedMps,.8);assert.equal(data.schemaVersion,3);
 assert.ok(Math.abs(data.demand.reduce((n,d)=>n+d.population,0)-784)<1e-6);
 const stops=Object.fromEntries(data.stops.map(s=>[s.id,s]));
 for(const t of data.tiers){
  assert.equal(data.stops.filter(s=>!s.existing&&s.tiers.includes(t.id)).length,t.stops);
  let eligible=0;for(const d of data.demand){const b=d.boarding[t.id];if(b){assert.ok(stops[b.stop].tiers.includes(t.id));assert.ok(b.walkS>=0&&b.walkS<=600);eligible+=d.population;}}
  assert.ok(Math.abs(eligible/784-t.walk10)<.00006);
 }
 for(const a of data.locationAudit){assert.ok(a.selectedAddedPopulation>=a.greedyAddedPopulation-1e-7);assert.equal(a.gap,0);}
 for(const h of Object.values(data.access.onward))assert.equal(h.onwardS.length,541);
});
test('Kakao requests use boarding coordinates and same-hospital baseline; reuse on condition changes',async()=>{
 const small={origins:[{key:'o',x:126,y:37,clinic:'c'}],clinics:[{id:'c',lng:127,lat:38},{id:'baek',lng:128,lat:39}],stops:[{id:'s',lng:126.1,lat:37.1}],places:[{id:'clinic'},{id:'daehwa',lng:127.1,lat:38.1,target:'baek'}],demand:[{origin:'o',boarding:{t0:{stop:'s',walkS:20},t36:{stop:'s',walkS:20}}}]};
 const calls=[];
 const router=createRouter('test-key',small,{fetchImpl:async(url,{body})=>{const q=JSON.parse(body);calls.push({url,q});const points=q.origins||q.destinations;return new Response(JSON.stringify({routes:points.map(p=>({key:p.key,result_code:0,summary:{distance:1000,duration:120}}))}));}});
 const r=await router.get('daehwa');assert.equal(r.boarding['s|baek'].outKm,1);
 assert.ok(calls.some(c=>c.q.origins?.[0].x===126.1&&c.q.destination.x===127.1));
 assert.ok(calls.some(c=>c.q.origins?.[0].x===126&&c.q.destination.x===128));
 const count=calls.length;await router.get('daehwa');assert.equal(calls.length,count);
});
