(async()=>{
const $=id=>document.getElementById(id),nf=new Intl.NumberFormat('ko-KR'),pct=v=>(v*100).toFixed(1);
const data=await fetch('/data.json').then(r=>r.json());
if(data.schemaVersion!==3)throw Error('자료 버전이 다릅니다. 새로고침해 주세요.');
const destinations=data.places.map(p=>p.id);
const initial={tier:'t36',destination:'clinic',vehicles:2,vehicle:'electric',conversion:.3,occupancy:2.5,emissionScope:'energy',waitBaseMin:14.5,waitMode:'overlap'};
let state={...initial},map,cells=[],stops=[],labels=[],bounds,current=null,currentResult=null;
const distances={},pending={};
try{const s=JSON.parse(sessionStorage.getItem('goyang-scenario-v3'));if(s&&data.tiers.some(t=>t.id===s.tier)&&destinations.includes(s.destination)&&[1,2,3].includes(s.vehicles)&&Object.hasOwn(CarbonModel.vehicles,s.vehicle)&&Number.isFinite(s.conversion)&&s.conversion>=0&&s.conversion<=1&&Number.isFinite(s.occupancy)&&s.occupancy>=1&&s.occupancy<=3.2&&['energy','tailpipe'].includes(s.emissionScope)&&Number.isFinite(s.waitBaseMin)&&s.waitBaseMin>=5&&s.waitBaseMin<=30&&['overlap','sequential'].includes(s.waitMode))state=s;}catch{}
const style={strokeWeight:1,strokeColor:'#416c4e',strokeOpacity:.85,fillColor:'#cbd5c8',fillOpacity:.55};
function chart(result,params){
 const values=Array.from({length:60},(_,i)=>{const n=1+2.2*i/59;return {n,y:CarbonModel.calculate({...params,occupancy:n}).savingKg};});
 const low=Math.min(0,...values.map(v=>v.y)),high=Math.max(0,...values.map(v=>v.y)),spread=high-low||1;
 const y=v=>88-(v-low)/spread*66,x=n=>35+(n-1)/2.2*285,zero=y(0),path=values.map((v,i)=>(i?'L':'M')+x(v.n).toFixed(2)+','+y(v.y).toFixed(2)).join(' ');
 $('occupancy-chart').innerHTML='<line x1="35" x2="320" y1="'+zero+'" y2="'+zero+'" stroke="#b9c4b1" stroke-dasharray="3 3"/><text x="25" y="'+(zero+3)+'" text-anchor="end" fill="#70816b" font-size="9">0</text><path d="'+path+'" fill="none" stroke="#688761" stroke-width="2.4"/><circle cx="'+x(state.occupancy)+'" cy="'+y(result.savingKg)+'" r="4.5" fill="#224e37"/><text x="35" y="112" fill="#70816b" font-size="9">1명</text><text x="320" y="112" text-anchor="end" fill="#70816b" font-size="9">3.2명</text><text x="320" y="10" text-anchor="end" fill="#70816b" font-size="9">'+(high/1000).toFixed(2)+' t</text>';
}
function clearResults(text='경로 조회 중'){
 current=null;currentResult=null;for(const id of ['saving','access','baseline-total','drt-total','walk-time','drive-time','stationary-wait'])$(id).textContent='—';
 $('saving-percent').textContent=text;$('access-gain').textContent=text;$('saving-card').classList.remove('negative','zero');
 $('baseline-bar').style.width='0';$('drt-bar').style.width='0';$('occupancy-chart').innerHTML='';$('per-trip-note').textContent=text;$('sensitivity-note').textContent='경로 확인 후 표시됩니다.';
 for(const c of cells)c.polygon.setOptions(style);
}
function render(){
 const tier=data.tiers.find(t=>t.id===state.tier);
 for(const id of ['conversion','occupancy','destination','emissionScope','waitBaseMin','waitMode'])$(id).value=id==='conversion'?state[id]*100:state[id];
 $('conversion-value').textContent=Math.round(state.conversion*100)+'%';$('occupancy-value').textContent=state.occupancy.toFixed(1)+'명';
 $('wait-base-value').textContent=state.waitBaseMin.toFixed(1)+'분';
 $('wait-time').textContent=CarbonModel.waitMinutes(state.vehicles,state.waitBaseMin,data.access.waitElasticity).toFixed(1);
 const eligible=data.demand.reduce((s,d)=>s+(d.boarding[state.tier]?d.population:0),0);
 $('eligible').textContent=nf.format(Math.round(eligible));
 $('trips').textContent=nf.format(Math.round(eligible*CarbonModel.defaults.visits*(CarbonModel.defaults.taxiShare+CarbonModel.defaults.carShare)*state.conversion));
 $('walk5').textContent=pct(tier.walk5)+'%';$('walk5-now').textContent=pct(data.existing.walk5)+'%';$('walk5-bar').style.width=tier.walk5*100+'%';
 document.querySelectorAll('[data-walk5]').forEach(el=>el.textContent=pct(data.tiers.find(t=>t.id===el.dataset.walk5).walk5)+'%');
 $('budget').textContent=(CarbonModel.annualCost(state.vehicles,data.budget)/1e8).toFixed(2);$('budget-vehicles').textContent=state.vehicles;$('budget-daily').textContent=nf.format(data.budget.dailyCostPerVehicle);
 $('access-now').textContent=pct(data.access.baselineShare);
 $('map-subtitle').textContent=data.totalGrids+'개 격자 · 추가 지점 '+tier.stops+'곳';
 $('destination-note').textContent=state.destination==='clinic'?'집 → 승하차 지점 → 출발지별 가까운 의료기관. 기존 자동차도 같은 기관 기준.':'집 → 승하차 지점 → 실제 거점 정류장 → 일산백병원. 도보·시간표 경로 연결, GTX 제외.';
 $('scope-note').textContent=state.emissionScope==='energy'?'연료연소 CO₂ + 사용전력 발전 CO₂e 근사 · 전 과정 평가 아님':'배기관 CO₂만 비교 · 전기차 발전 배출 제외';
 document.querySelectorAll('[data-carbon-unit]').forEach(el=>el.textContent=state.emissionScope==='energy'?'tCO₂e / 년 (근사)':'tCO₂ / 년');
 for(const attr of ['tier','vehicle','vehicles'])document.querySelectorAll('[data-'+attr+']').forEach(b=>{const on=String(state[attr])===b.dataset[attr];b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});
 for(const s of stops)s.overlay.setMap(s.tiers.includes(state.tier)?map:null);
 for(const l of labels)l.content.classList.toggle('chosen',l.id===state.destination||(state.destination!=='clinic'&&l.id==='baek'));
 try{sessionStorage.setItem('goyang-scenario-v3',JSON.stringify(state));}catch{}
 window.dispatchEvent(new Event('scenariochange'));
 if(!distances[state.destination]){clearResults();return;}
 try{current=CarbonModel.evaluate(data,state,distances[state.destination]);}catch{clearResults('경로 자료 확인 필요');return;}
 const r=current.result;currentResult=r;const a=current.access,gain=(a.withDrt-data.access.baselineShare)*100;
 $('access').textContent=pct(a.withDrt);$('access-gain').textContent=(gain>=0?'+':'')+gain.toFixed(1)+'%p';
 $('walk-time').textContent=a.walkMin.toFixed(1);$('drive-time').textContent=(a.driveMin*data.access.detour).toFixed(1);$('stationary-wait').textContent=a.stationaryWaitMin.toFixed(1);
 const negative=r.savingKg<-.000001,zero=Math.abs(r.savingKg)<.000001;
 $('saving-title').textContent=negative?'전환 통행 탄소 증가':'전환 통행 탄소 감축';$('saving').textContent=(Math.abs(r.savingKg)/1000).toFixed(2);
 $('saving-card').classList.toggle('negative',negative);$('saving-card').classList.toggle('zero',zero);
 $('saving-percent').textContent=r.percent===null?'전환 통행 없음':Math.abs(r.percent).toFixed(1)+'% '+(negative?'증가':'감축');
 $('baseline-total').textContent=(r.baselineKg/1000).toFixed(2);$('drt-total').textContent=(r.drtKg/1000).toFixed(2);
 const max=Math.max(r.baselineKg,r.drtKg)||1;$('baseline-bar').style.width=r.baselineKg/max*100+'%';$('drt-bar').style.width=r.drtKg/max*100+'%';
 $('per-trip-note').textContent='왕복 1회당 '+r.baselinePerTrip.toFixed(2)+' → '+r.drtPerTrip.toFixed(2)+' kg · 동일 인구·의료 목적지 비교';
 $('sensitivity-note').textContent=state.conversion===0?'전환율 0%: 총 감축량 0. 접근성은 이용 여부와 별개인 잠재적 기회입니다.':r.vehicleFactor===0?'배기관 기준에서 전기차 배출은 0. 전력 발전 포함 기준도 확인하세요.':r.breakEven==null?'상쇄 기준 계산 불가':'탄소 상쇄 재차인원 '+r.breakEven.toFixed(2)+'명 · 전체 사업 순감축량은 아닙니다.';
 chart(r,{...state,...current.distances,population:current.eligiblePopulation});
 const byCell=Object.fromEntries(current.cells.map(c=>[c.gid,c]));
 for(const c of cells){const v=byCell[c.grid.properties.gid],g=Math.max(0,v.withDrt-v.baseline);c.polygon.setOptions({fillColor:g>.5?'#1b654b':g>.2?'#559875':g>.01?'#9dc3a6':'#d8dfd3',fillOpacity:.65});}
 const time=new Date(current.queriedAt).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false});
 $('status').textContent='이용 가능 인구 가중 왕복거리 · 기존 '+current.distances.baselineKm.toFixed(2)+' km / 승하차 지점 연결 '+current.distances.drtKm.toFixed(2)+' km · '+time+' 조회';
}
async function getDistance(id){if(distances[id])return distances[id];if(!pending[id])pending[id]=fetch('/api/distances?destination='+id).then(async r=>{const v=await r.json();if(!r.ok)throw Error(v.error||'경로 조회 실패');distances[id]=v;return v;}).finally(()=>delete pending[id]);return pending[id];}
async function loadDistances(){const id=state.destination;$('retry').hidden=true;if(!distances[id])$('status').textContent='주거 대표점과 실제 승하차 지점의 왕복 경로를 조회합니다…';try{await getDistance(id);render();}catch(e){if(id===state.destination){clearResults('경로 확인 필요');$('status').textContent=e.message;$('retry').hidden=false;}}}
for(const attr of ['tier','vehicle','vehicles'])document.querySelectorAll('[data-'+attr+']').forEach(b=>b.addEventListener('click',()=>{state[attr]=attr==='vehicles'?+b.dataset[attr]:b.dataset[attr];render();}));
for(const id of ['conversion','occupancy','waitBaseMin'])$(id).addEventListener('input',e=>{state[id]=+e.target.value/(id==='conversion'?100:1);render();});
for(const id of ['emissionScope','waitMode'])$(id).addEventListener('change',e=>{state[id]=e.target.value;render();});
$('destination').addEventListener('change',e=>{state.destination=e.target.value;render();loadDistances();});
$('reset').addEventListener('click',()=>{state={...initial};render();loadDistances();if(map)map.setBounds(bounds,40,40,40,40);});$('retry').addEventListener('click',loadDistances);$('fit').addEventListener('click',()=>{if(map)map.setBounds(bounds,40,40,40,40);});
window.dashboard={data,state:()=>({...state}),result:()=>currentResult,evaluation:()=>current,distances,render,map:()=>map,cells:()=>cells};
render();loadDistances();
try{
 if(!window.KAKAO_TEST_CONFIG?.javascriptKey)throw Error('지도 키가 등록되지 않았습니다.');
 await new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='https://dapi.kakao.com/v2/maps/sdk.js?autoload=false&appkey='+encodeURIComponent(window.KAKAO_TEST_CONFIG.javascriptKey);s.onload=()=>window.kakao?.maps?kakao.maps.load(resolve):reject(Error('지도 SDK 확인 필요'));s.onerror=()=>reject(Error('카카오 지도 연결 실패'));document.head.append(s);});
 $('loading').remove();map=new kakao.maps.Map($('map'),{center:new kakao.maps.LatLng(37.681,126.718),level:7});bounds=new kakao.maps.LatLngBounds();
 cells=data.grids.map(grid=>{
  const path=grid.geometry.coordinates.map(r=>r.map(([lng,lat])=>{const p=new kakao.maps.LatLng(lat,lng);bounds.extend(p);return p;}));
  const polygon=new kakao.maps.Polygon({map,path,...style}),cell={grid,polygon};
  kakao.maps.event.addListener(polygon,'click',()=>{const c=current?.cells.find(c=>c.gid===grid.properties.gid);$('cell-info').textContent=grid.properties.gid+' · '+nf.format(grid.properties.population)+'명'+(c?' · 30분 '+pct(c.baseline)+' → '+pct(c.withDrt)+'% · 탑승권 '+Math.round(c.eligible)+'명':' · 효과 계산 대기');});return cell;
 });
 stops=data.stops.map(s=>{const content=document.createElement('div');content.className='vstop'+(s.existing?' existing-stop':'');content.title=s.existing?'기존 '+s.name:'가상정류장 '+s.id;return {...s,overlay:new kakao.maps.CustomOverlay({position:new kakao.maps.LatLng(s.lat,s.lng),content,zIndex:3})};});
 const label=(id,name,lng,lat)=>{const position=new kakao.maps.LatLng(lat,lng);bounds.extend(position);const content=document.createElement('div');content.className='place-label';content.textContent=name;new kakao.maps.CustomOverlay({map,position,content,yAnchor:1.2,zIndex:4});labels.push({id,content});};
 data.clinics.forEach(c=>label(c.id==='baek'?'baek':'clinic',c.name,c.lng,c.lat));data.places.filter(p=>p.id!=='clinic').forEach(p=>label(p.id,p.name,p.lng,p.lat));
 map.addControl(new kakao.maps.ZoomControl(),kakao.maps.ControlPosition.RIGHT);map.setBounds(bounds,40,40,40,40);new ResizeObserver(()=>map.relayout()).observe($('map'));render();window.dashboard.mapReady=true;
}catch(e){if($('loading'))$('loading').textContent=e.message;document.querySelector('.live').textContent='지도 연결 확인 필요';window.dashboard.mapError=e.message;}
})().catch(error=>{document.getElementById('status').textContent='화면 준비 중 오류: '+error.message;window.dashboardError=error.message;});
