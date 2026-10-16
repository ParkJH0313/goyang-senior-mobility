// External route responses stay in process memory. Only aggregate distances are returned.
const places={hospital:{x:126.750433,y:37.674314},tanhyeon:{x:126.761175,y:37.693887},kintex:{x:126.747533,y:37.665417}};
function createRouter(restKey,data){
 const cache=new Map(),pending=new Map(),failedUntil=new Map();let requests=0;
 const safeError=status=>new Error(`자동차 거리 조회가 완료되지 않았습니다 (HTTP ${status}).`);
 async function call(endpoint,body){
  if(!restKey)throw new Error('자동차 거리 연결 준비 중입니다.');
  requests++;
  const response=await fetch('https://apis-navi.kakaomobility.com/v1/'+endpoint+'/directions',{method:'POST',headers:{Authorization:'KakaoAK '+restKey,'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
  if(!response.ok)throw safeError(response.status);
  const result=await response.json();if(!Array.isArray(result.routes))throw new Error('길찾기 응답 형식을 확인할 수 없습니다.');
  return result.routes;
 }
 async function calculate(id){
  const place=places[id];if(!place)throw new Error('지원하지 않는 목적지입니다.');
  const routes=new Map();const missing=[];
  for(let start=0;start<data.origins.length;start+=30){
   const group=data.origins.slice(start,start+30).map(o=>({key:o.key,x:o.x,y:o.y}));
   const shared={radius:10000,priority:'DISTANCE'};
   const results=await Promise.allSettled([
    call('origins',{...shared,origins:group,destination:place}),
    call('destinations',{...shared,origin:place,destinations:group})
   ]);
   const forward=results[0],backward=results[1];
   if(forward.status==='rejected')throw forward.reason;
   if(backward.status==='rejected')throw backward.reason;
   const out=new Map(forward.value.map(r=>[r.key,r]));const back=new Map(backward.value.map(r=>[r.key,r]));
   for(const origin of group){
    const a=out.get(origin.key),b=back.get(origin.key);
    if(a?.result_code!==0 || b?.result_code!==0 || !Number.isFinite(a?.summary?.distance)||!Number.isFinite(b?.summary?.distance))missing.push(origin.key);
    else routes.set(origin.key,{out:a.summary.distance,back:b.summary.distance});
   }
  }
  if(missing.length)throw new Error(`${missing.length}개 출발점의 왕복 거리를 확인하지 못했습니다. 전체 인구의 탄소 결과는 표시하지 않습니다.`);
  const cells=new Map(data.grids.map(g=>[g.properties.gid,g.properties]));
  const summaries={};
  for(const scope of data.scopes){
   const selected=data.origins.filter(o=>scope.id==='all'||cells.get(o.parent_gid)[scope.id==='core'?'low80':'low45']);
   const population=selected.reduce((n,o)=>n+o.population,0);
   const out=selected.reduce((n,o)=>n+routes.get(o.key).out*o.population,0)/population/1000;
   const back=selected.reduce((n,o)=>n+routes.get(o.key).back*o.population,0)/population/1000;
   summaries[scope.id]={population,origins:selected.length,outKm:out,backKm:back,roundtripKm:out+back};
  }
  const result={destination:id,queriedAt:new Date().toISOString(),priority:'DISTANCE',complete:true,originCount:data.origins.length,scopes:summaries};
  cache.set(id,result);console.log('Distance lookup complete:',id,data.origins.length,'origins, both directions');return result;
 }
 return {
  async get(id){if(!places[id])throw new Error('지원하지 않는 목적지입니다.');if(cache.has(id))return cache.get(id);if((failedUntil.get(id)||0)>Date.now())throw new Error('잠시 후 다시 조회해 주세요.');if(!pending.has(id)){pending.set(id,calculate(id).catch(error=>{failedUntil.set(id,Date.now()+60000);throw error;}).finally(()=>pending.delete(id)));}return pending.get(id);},
  status:()=>({requests,ready:[...cache.keys()],pending:[...pending.keys()]})
 };
}
module.exports={createRouter};
