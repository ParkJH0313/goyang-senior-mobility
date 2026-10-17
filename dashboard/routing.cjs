// External route responses stay in process memory. Only aggregate distances and reach shares are returned.
const {createAccess}=require('./access.cjs');
function createRouter(restKey,data){
 const cache=new Map(),pending=new Map(),failedUntil=new Map();let requests=0;
 const places=Object.fromEntries(data.places.filter(p=>p.id!=='clinic').map(p=>[p.id,{x:p.lng,y:p.lat}]));
 const clinics=Object.fromEntries(data.clinics.map(c=>[c.id,{x:c.lng,y:c.lat}]));
 const ids=['clinic',...Object.keys(places)];
 const shares=createAccess(data);
 const safeError=status=>new Error(`자동차 경로 조회가 완료되지 않았습니다 (HTTP ${status}).`);
 async function call(endpoint,body){
  if(!restKey)throw new Error('자동차 경로 연결 준비 중입니다.');
  requests++;
  const response=await fetch('https://apis-navi.kakaomobility.com/v1/'+endpoint+'/directions',{method:'POST',headers:{Authorization:'KakaoAK '+restKey,'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
  if(!response.ok)throw safeError(response.status);
  const result=await response.json();if(!Array.isArray(result.routes))throw new Error('길찾기 응답 형식을 확인할 수 없습니다.');
  return result.routes;
 }
 // 출발점 묶음과 목적지 한 곳 사이의 왕복 경로(가는 길 거리·시간, 돌아오는 길 거리)
 async function roundtrips(origins,place,routes,missing){
  for(let start=0;start<origins.length;start+=30){
   const group=origins.slice(start,start+30).map(o=>({key:o.key,x:o.x,y:o.y}));
   const shared={radius:10000,priority:'DISTANCE'};
   const results=await Promise.allSettled([
    call('origins',{...shared,origins:group,destination:place}),
    call('destinations',{...shared,origin:place,destinations:group})
   ]);
   for(const r of results)if(r.status==='rejected')throw r.reason;
   const out=new Map(results[0].value.map(r=>[r.key,r]));const back=new Map(results[1].value.map(r=>[r.key,r]));
   for(const origin of group){
    const a=out.get(origin.key),b=back.get(origin.key);
    if(a?.result_code!==0||b?.result_code!==0||!Number.isFinite(a?.summary?.distance)||!Number.isFinite(a?.summary?.duration)||!Number.isFinite(b?.summary?.distance))missing.push(origin.key);
    else routes.set(origin.key,{out:a.summary.distance,back:b.summary.distance,duration:a.summary.duration});
   }
  }
 }
 async function calculate(id){
  const routes=new Map(),missing=[];
  if(id==='clinic'){
   const groups=new Map();for(const o of data.origins){if(!groups.has(o.clinic))groups.set(o.clinic,[]);groups.get(o.clinic).push(o);}
   for(const [clinic,origins] of groups)await roundtrips(origins,clinics[clinic],routes,missing);
  }else await roundtrips(data.origins,places[id],routes,missing);
  if(missing.length)throw new Error(`${missing.length}개 출발점의 왕복 경로를 확인하지 못했습니다. 전체 인구의 결과는 표시하지 않습니다.`);
  const population=data.origins.reduce((n,o)=>n+o.population,0);
  const avg=key=>data.origins.reduce((n,o)=>n+routes.get(o.key)[key]*o.population,0)/population;
  const outKm=avg('out')/1000,backKm=avg('back')/1000;
  const access=shares(id,new Map(data.origins.map(o=>[o.key,routes.get(o.key).duration])));
  const result={destination:id,queriedAt:new Date().toISOString(),priority:'DISTANCE',complete:true,originCount:data.origins.length,population,outKm,backKm,roundtripKm:outKm+backKm,driveMin:avg('duration')/60,access};
  cache.set(id,result);console.log('Route lookup complete:',id,data.origins.length,'origins, both directions');return result;
 }
 return {
  ids,
  async get(id){if(!ids.includes(id))throw new Error('지원하지 않는 목적지입니다.');if(cache.has(id))return cache.get(id);if((failedUntil.get(id)||0)>Date.now())throw new Error('잠시 후 다시 조회해 주세요.');if(!pending.has(id)){pending.set(id,calculate(id).catch(error=>{failedUntil.set(id,Date.now()+60000);throw error;}).finally(()=>pending.delete(id)));}return pending.get(id);},
  status:()=>({requests,ready:[...cache.keys()],pending:[...pending.keys()]})
 };
}
module.exports={createRouter};
