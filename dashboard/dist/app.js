(async()=>{
const $=id=>document.getElementById(id),nf=new Intl.NumberFormat('ko-KR'),pct=v=>(v*100).toFixed(1);
const data=await fetch('/data.json').then(r=>r.json());
if(data.schemaVersion!==5)throw Error('자료 버전이 다릅니다. 새로고침해 주세요.');
const destinations=data.places.map(p=>p.id);
const initial={tier:'t36',destination:'baek',vehicles:2,vehicle:'electric',conversion:.3,occupancy:2.5,waitBaseMin:14.5};
let state={...initial},map,cells=[],stops=[],labels=[],bounds,current=null,currentResult=null;
const distances={},pending={};
try{const s=JSON.parse(sessionStorage.getItem('goyang-scenario-v7'));if(s&&Object.hasOwn(CarbonModel.scenarios,s.tier)&&destinations.includes(s.destination)&&[1,2,3].includes(s.vehicles)&&Object.hasOwn(CarbonModel.vehicles,s.vehicle)&&Number.isFinite(s.conversion)&&s.conversion>=0&&s.conversion<=1&&Number.isFinite(s.occupancy)&&s.occupancy>=1&&s.occupancy<=3.2&&Number.isFinite(s.waitBaseMin)&&s.waitBaseMin>=5&&s.waitBaseMin<=30)state={...s,waitBaseMin:initial.waitBaseMin};}catch{}
const style={strokeWeight:1,strokeColor:'#416c4e',strokeOpacity:.85,fillColor:'#cbd5c8',fillOpacity:.55};
function chart(result,params){
 const values=Array.from({length:60},(_,i)=>{const n=1+2.2*i/59;return {n,y:CarbonModel.calculate({...params,occupancy:n}).savingKg};});
 const low=Math.min(0,...values.map(v=>v.y)),high=Math.max(0,...values.map(v=>v.y)),spread=high-low||1;
 const y=v=>88-(v-low)/spread*66,x=n=>35+(n-1)/2.2*285,zero=y(0),path=values.map((v,i)=>(i?'L':'M')+x(v.n).toFixed(2)+','+y(v.y).toFixed(2)).join(' ');
 $('occupancy-chart').innerHTML='<line x1="35" x2="320" y1="'+zero+'" y2="'+zero+'" stroke="#b9c4b1" stroke-dasharray="3 3"/><text x="25" y="'+(zero+3)+'" text-anchor="end" fill="#70816b" font-size="9">0</text><path d="'+path+'" fill="none" stroke="#688761" stroke-width="2.4"/><circle cx="'+x(state.occupancy)+'" cy="'+y(result.savingKg)+'" r="4.5" fill="#224e37"/><text x="35" y="112" fill="#70816b" font-size="9">1명</text><text x="320" y="112" text-anchor="end" fill="#70816b" font-size="9">3.2명</text><text x="320" y="10" text-anchor="end" fill="#70816b" font-size="9">'+(high/1000).toFixed(2)+' t</text>';
}
function clearResults(text='경로 조회 중'){
 current=null;currentResult=null;for(const id of ['saving','access','baseline-total','drt-total','walk-time','drive-time','stationary-wait','home-wait'])$(id).textContent='—';
 $('saving-percent').textContent=text;$('access-gain').textContent=text;$('saving-card').classList.remove('negative','zero');
 $('baseline-bar').style.width='0';$('drt-bar').style.width='0';$('occupancy-chart').innerHTML='';$('per-trip-note').textContent=text;$('sensitivity-note').textContent='경로 확인 후 표시됩니다.';
 for(const c of cells)c.polygon.setOptions(style);
}
function render(){
 const enabled=state.tier!=='none',tier=data.tiers.find(t=>t.id===(enabled?state.tier:'t0'));
 document.querySelectorAll('[data-drt-control]').forEach(el=>el.disabled=!enabled);
 $('budget-detail').hidden=!enabled;$('budget-none').hidden=enabled;$('journey-summary').hidden=!enabled;
 $('access-mode').textContent=enabled?'→ 도입 후 · 버스나 똑버스 중 하나로 도달':'· 미도입 기준선';
 $('scenario-caption').hidden=!enabled;$('baseline-caption').hidden=enabled;
 for(const id of ['conversion','occupancy','destination'])$(id).value=id==='conversion'?state[id]*100:state[id];
 $('conversion-value').textContent=Math.round(state.conversion*100)+'%';$('occupancy-value').textContent=state.occupancy.toFixed(1)+'명';
 $('wait-vehicles').textContent=enabled?state.vehicles:'—';
 $('wait-time').textContent=enabled?CarbonModel.waitMinutes(state.vehicles,state.waitBaseMin,data.access.waitElasticity).toFixed(1):'—';
 const eligible=enabled?data.demand.reduce((s,d)=>s+(d.boarding[state.tier]?d.population:0),0):0;
 $('eligible').textContent=nf.format(Math.round(eligible));
 $('trips').textContent=nf.format(Math.round(eligible*CarbonModel.defaults.visits*(CarbonModel.defaults.taxiShare+CarbonModel.defaults.carShare)*state.conversion));
 $('walk5').textContent=pct(tier.walk5)+'%';$('walk5-now').textContent=pct(data.existing.walk5)+'%';$('walk5-bar').style.width=tier.walk5*100+'%';
 document.querySelectorAll('[data-walk5]').forEach(el=>el.textContent=pct(data.tiers.find(t=>t.id===el.dataset.walk5).walk5)+'%');
 const budget=enabled?CarbonModel.budgetEstimate(state.vehicles,data.budget,state.vehicle):{annualWon:0,vehicles:0,dailyCostPerVehicle:0,purchaseWon:0};$('budget').textContent=(budget.annualWon/1e8).toFixed(2);$('budget-vehicles').textContent=budget.vehicles;$('budget-daily').textContent=nf.format(Math.round(budget.dailyCostPerVehicle));$('purchase-cost').textContent=nf.format(Math.round(budget.purchaseWon/10000));$('budget-vehicle').textContent=CarbonModel.vehicles[state.vehicle].name;
 $('access-now').textContent=pct(data.access.baselineShare);
 $('map-subtitle').textContent=data.totalGrids+'개 격자 · '+CarbonModel.scenarios[state.tier];
 const descriptions={baek:{description:'주거지 승하차 지점에서 똑버스를 타고 일산백병원 앞까지 갑니다. 중간에 갈아타지 않습니다.',assumption:'하차 후 병원까지 보행 1분을 가정합니다. 미도입과 대화역 경유도 같은 백병원을 기준으로 비교합니다.'},daehwa:{description:'주거지 승하차 지점에서 똑버스로 대화역 버스정류장까지 이동합니다. 그곳에서 내려 도보 또는 기존 버스로 일산백병원에 갑니다.',assumption:'실제 보행망·버스 시간표 중 빠른 후속 경로를 적용합니다. 지하철·GTX는 이용하지 않습니다. 대화역은 서구청과 비교한 현재 조건에서 총 이동시간이 더 짧았습니다.'}};
 $('destination-note').textContent=descriptions[state.destination].description;$('destination-assumption').textContent='계산 가정 · '+descriptions[state.destination].assumption;
 document.querySelectorAll('[data-carbon-unit]').forEach(el=>el.textContent='tCO₂ / 년');
 for(const attr of ['tier','vehicle','vehicles'])document.querySelectorAll('[data-'+attr+']').forEach(b=>{const on=String(state[attr])===b.dataset[attr];b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});
 for(const s of stops)s.overlay.setMap((enabled?s.tiers.includes(state.tier):s.existing)?map:null);
 for(const l of labels){
  const dropoff=enabled&&l.id===state.destination,final=enabled&&state.destination!=='baek'&&l.id==='baek';
  l.content.classList.toggle('chosen',dropoff);l.content.classList.toggle('final-destination',final);
  l.role.hidden=!dropoff&&!final;l.role.textContent=final?'최종 병원':state.destination==='baek'?'똑버스 하차 · 진료 목적지':'똑버스 하차';
 }
 try{sessionStorage.setItem('goyang-scenario-v7',JSON.stringify(state));}catch{}
 window.dispatchEvent(new Event('scenariochange'));
 if(!enabled){
  clearResults();current=CarbonModel.evaluate(data,state);currentResult=current.result;
  $('access').textContent=pct(current.access.withDrt);$('access-gain').textContent='미도입 기준';
  $('saving').textContent='0.00';$('saving-title').textContent='똑버스 도입에 따른 탄소 감축';$('saving-percent').textContent='미도입 · 감축 없음';
  $('per-trip-note').textContent='똑버스 전환 통행이 없어 배출량 비교를 적용하지 않습니다. 지역 전체 배출량이 0이라는 뜻은 아닙니다.';
  $('sensitivity-note').textContent='똑버스 도입안을 선택하면 재차인원에 따른 탄소 효과를 비교할 수 있습니다.';
  $('status').textContent='기존 대중교통·보행으로 일산백병원 도달 기준 · 똑버스 추가 운영비와 도입 효과 없음';$('retry').hidden=true;return;
 }
 if(!distances[state.destination]){clearResults();return;}
 try{current=CarbonModel.evaluate(data,state,distances[state.destination]);}catch{clearResults('경로 자료 확인 필요');return;}
 const r=current.result;currentResult=r;const a=current.access,gain=(a.withDrt-data.access.baselineShare)*100;
 $('access').textContent=pct(a.withDrt);$('access-gain').textContent=(gain>=0?'+':'')+gain.toFixed(1)+'%p';
 $('home-wait').textContent=a.homeWaitMin.toFixed(1);$('walk-time').textContent=a.walkMin.toFixed(1);$('drive-time').textContent=(a.driveMin*data.access.detour).toFixed(1);$('stationary-wait').textContent=a.stationaryWaitMin.toFixed(1);
 const negative=r.savingKg<-.000001,zero=Math.abs(r.savingKg)<.000001;
 $('saving-title').textContent=negative?'전환 통행 탄소 증가':'전환 통행 탄소 감축';$('saving').textContent=(Math.abs(r.savingKg)/1000).toFixed(2);
 $('saving-card').classList.toggle('negative',negative);$('saving-card').classList.toggle('zero',zero);
 $('saving-percent').textContent=r.percent===null?'전환 통행 없음':Math.abs(r.percent).toFixed(1)+'% '+(negative?'증가':'감축');
 $('baseline-total').textContent=(r.baselineKg/1000).toFixed(2);$('drt-total').textContent=(r.drtKg/1000).toFixed(2);
 const max=Math.max(r.baselineKg,r.drtKg)||1;$('baseline-bar').style.width=r.baselineKg/max*100+'%';$('drt-bar').style.width=r.drtKg/max*100+'%';
 $('per-trip-note').textContent='왕복 1회당 '+r.baselinePerTrip.toFixed(2)+' → '+r.drtPerTrip.toFixed(2)+' kg · 동일 인구·의료 목적지 비교';
 $('sensitivity-note').textContent=state.conversion===0?'전환율 0%: 총 감축량 0. 접근성은 이용 여부와 별개인 잠재적 기회입니다.':r.vehicleFactor===0?'전기차는 배기관 CO₂가 0이므로 재차인원을 바꿔도 이 범위의 감축량은 같습니다.':r.breakEven==null?'상쇄 기준 계산 불가':'탄소 상쇄 재차인원 '+r.breakEven.toFixed(2)+'명 · 전체 사업 순감축량은 아닙니다.';
 chart(r,{...state,...current.distances,population:current.eligiblePopulation});
 const byCell=Object.fromEntries(current.cells.map(c=>[c.gid,c]));
 for(const c of cells){const v=byCell[c.grid.properties.gid],g=Math.max(0,v.withDrt-v.baseline);c.polygon.setOptions({fillColor:g>.5?'#1b654b':g>.2?'#559875':g>.01?'#9dc3a6':'#d8dfd3',fillOpacity:.65});}
 const time=new Date(current.queriedAt).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false});
 $('status').textContent='이용 가능 인구 가중 왕복거리 · 기존 '+current.distances.baselineKm.toFixed(2)+' km / 승하차 지점 연결 '+current.distances.drtKm.toFixed(2)+' km · '+time+' 조회';
}
async function getDistance(id){if(distances[id])return distances[id];if(!pending[id])pending[id]=fetch('/api/distances?destination='+id).then(async r=>{const v=await r.json();if(!r.ok)throw Error(v.error||'경로 조회 실패');distances[id]=v;return v;}).finally(()=>delete pending[id]);return pending[id];}
async function loadDistances(){if(state.tier==='none')return;const id=state.destination;$('retry').hidden=true;if(!distances[id])$('status').textContent='주거 대표점과 실제 승하차 지점의 왕복 경로를 조회합니다…';try{await getDistance(id);render();}catch(e){if(id===state.destination&&state.tier!=='none'){clearResults('경로 확인 필요');$('status').textContent=e.message;$('retry').hidden=false;}}}
for(const attr of ['tier','vehicle','vehicles'])document.querySelectorAll('[data-'+attr+']').forEach(b=>b.addEventListener('click',()=>{state[attr]=attr==='vehicles'?+b.dataset[attr]:b.dataset[attr];render();if(attr==='tier')loadDistances();}));
for(const id of ['conversion','occupancy'])$(id).addEventListener('input',e=>{state[id]=+e.target.value/(id==='conversion'?100:1);render();});
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
 const label=(id,name,lng,lat)=>{const position=new kakao.maps.LatLng(lat,lng);bounds.extend(position);const content=document.createElement('div');content.className='place-label';content.dataset.place=id;const role=document.createElement('small'),title=document.createElement('span');role.className='place-role';role.hidden=true;title.textContent=name;content.append(role,title);new kakao.maps.CustomOverlay({map,position,content,yAnchor:1.2,zIndex:4});labels.push({id,content,role});};
 data.clinics.forEach(c=>label(c.id,c.name,c.lng,c.lat));data.places.filter(p=>p.id!=='baek').forEach(p=>label(p.id,p.name,p.lng,p.lat));
 map.addControl(new kakao.maps.ZoomControl(),kakao.maps.ControlPosition.RIGHT);map.setBounds(bounds,40,40,40,40);new ResizeObserver(()=>map.relayout()).observe($('map'));render();window.dashboard.mapReady=true;
}catch(e){if($('loading'))$('loading').textContent=e.message;document.querySelector('.live').textContent='지도 연결 확인 필요';window.dashboard.mapError=e.message;}
})().catch(error=>{document.getElementById('status').textContent='화면 준비 중 오류: '+error.message;window.dashboardError=error.message;});
