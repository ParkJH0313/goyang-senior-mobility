// Route only actual boarding locations; baseline and alternative end at the same medical facility.
function createRouter(restKey,data,{fetchImpl=fetch}={}){
 const cache=new Map(),pending=new Map(),failedUntil=new Map(),odCache=new Map();let requests=0;
 const clinics=Object.fromEntries(data.clinics.map(c=>[c.id,c])),stops=Object.fromEntries(data.stops.map(s=>[s.id,s]));
 const origins=Object.fromEntries(data.origins.map(o=>[o.key,o]));
 const places=Object.fromEntries(data.places.map(p=>[p.id,p])),ids=Object.keys(places);
 const point=p=>({x:p.x??p.lng,y:p.y??p.lat});
 const routeKey=(p,q)=>JSON.stringify([point(p),point(q)]);
 async function call(endpoint,body){
  if(!restKey)throw Error('자동차 경로 연결 준비 중입니다.');
  requests++;
  const response=await fetchImpl('https://apis-navi.kakaomobility.com/v1/'+endpoint+'/directions',{method:'POST',headers:{Authorization:'KakaoAK '+restKey,'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
  if(!response.ok)throw Error('Route lookup failed');const json=await response.json();
  if(!Array.isArray(json.routes))throw Error('Invalid routes');return json.routes;
 }
 async function batch(points,destination){
  const missing=points.filter(p=>!odCache.has(routeKey(p,destination)));
  for(let i=0;i<missing.length;i+=30){
   const group=missing.slice(i,i+30),query=group.map((p,j)=>({key:String(j),...point(p)}));
   const results=await Promise.allSettled([call('origins',{radius:10000,priority:'DISTANCE',origins:query,destination:point(destination)}),call('destinations',{radius:10000,priority:'DISTANCE',origin:point(destination),destinations:query})]);
   for(const r of results)if(r.status==='rejected')throw r.reason;
   const out=new Map(results[0].value.map(r=>[String(r.key),r])),back=new Map(results[1].value.map(r=>[String(r.key),r]));
   for(let j=0;j<group.length;j++){
    const a=out.get(String(j)),b=back.get(String(j));
    if(a?.result_code!==0||b?.result_code!==0||[a?.summary?.distance,a?.summary?.duration,b?.summary?.distance].some(x=>!Number.isFinite(x)||x<0))throw Error('Incomplete routes');
    odCache.set(routeKey(group[j],destination),{outKm:a.summary.distance/1000,backKm:b.summary.distance/1000,driveS:a.summary.duration});
   }
  }
  return Object.fromEntries(points.map(p=>[p.key,odCache.get(routeKey(p,destination))]));
 }
 async function calculate(id){
  const baseline={},boarding={},groups=new Map();
  for(const o of data.origins){const target=id==='clinic'?o.clinic:places[id].target;
   if(!groups.has(target))groups.set(target,{origin:[],stops:new Set()});groups.get(target).origin.push(o);}
  for(const sample of data.demand){const o=origins[sample.origin],target=id==='clinic'?o.clinic:places[id].target;
   for(const options of Object.values(sample.pickups))for(const assignment of options)groups.get(target).stops.add(assignment.stop);}
  for(const [target,g]of groups){
   Object.assign(baseline,await batch(g.origin,clinics[target]));
   const start=[...g.stops].map(sid=>({...stops[sid],key:sid+'|'+target}));
   Object.assign(boarding,await batch(start,id==='clinic'?clinics[target]:places[id]));
  }
  const result={destination:id,complete:true,queriedAt:new Date().toISOString(),runId:data.runId,priority:'DISTANCE',baseline,boarding};
  cache.set(id,result);return result;
 }
 return {ids,status:()=>({requests,ready:[...cache.keys()],pending:[...pending.keys()]}),async get(id){
  if(!ids.includes(id))throw Error('Unsupported destination');if(cache.has(id))return cache.get(id);
  if((failedUntil.get(id)||0)>Date.now())throw Error('Retry later');
  if(!pending.has(id))pending.set(id,calculate(id).catch(error=>{failedUntil.set(id,Date.now()+60000);throw error;}).finally(()=>pending.delete(id)));
  return pending.get(id);
 }};
}
module.exports={createRouter};
