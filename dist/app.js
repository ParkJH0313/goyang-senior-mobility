(async()=>{
const $=id=>document.getElementById(id), nf=new Intl.NumberFormat('ko-KR');
const data=await fetch('/data.json').then(r=>r.json());
const initial={scope:'core',destination:'hospital',vehicle:'lpg',conversion:.3,occupancy:2.5};
let state={...initial}, map, cells=[], places={}, bounds;
const distances={},pending={};
let currentResult=null;
try{const saved=JSON.parse(sessionStorage.getItem('goyang-scenario'));if(saved&&data.scopes.some(s=>s.id===saved.scope)&&['hospital','tanhyeon','kintex'].includes(saved.destination)&&['lpg','hybrid'].includes(saved.vehicle)&&saved.conversion>=0&&saved.conversion<=1&&saved.occupancy>=1&&saved.occupancy<=3.2)state=saved;}catch{}
const active=(g,s)=>s==='all'||g.properties[s==='core'?'low80':'low45'];
const style=on=>({strokeWeight:1,strokeColor:on?'#416c4e':'#a6b5a1',strokeOpacity:on?.9:.65,fillColor:on?'#4b7f55':'#e5ecdf',fillOpacity:on?.46:.18});
function chart(result,params){
 const values=Array.from({length:60},(_,i)=>{const n=1+2.2*i/59;return {n,y:CarbonModel.calculate({...params,occupancy:n}).savingKg};});
 const low=Math.min(0,...values.map(v=>v.y)),high=Math.max(0,...values.map(v=>v.y));
 const spread=high-low||1, y=v=>88-(v-low)/spread*66, x=n=>35+(n-1)/2.2*285;
 const zero=y(0), path=values.map((v,i)=>(i?'L':'M')+x(v.n).toFixed(2)+','+y(v.y).toFixed(2)).join(' ');
 const pointY=y(result.savingKg), pointX=x(state.occupancy);
 const threshold=result.breakEven>=1&&result.breakEven<=3.2?'<line x1="'+x(result.breakEven)+'" x2="'+x(result.breakEven)+'" y1="16" y2="92" stroke="#c0c9b7" stroke-dasharray="3 3"/>':'';
 $('occupancy-chart').innerHTML='<line x1="35" x2="320" y1="'+zero+'" y2="'+zero+'" stroke="#b9c4b1" stroke-dasharray="3 3"/><text x="25" y="'+(zero+3)+'" text-anchor="end" fill="#8d9d82" font-size="9">0</text>'+threshold+'<path d="'+path+'" fill="none" stroke="#688761" stroke-width="2.4"/><circle cx="'+pointX+'" cy="'+pointY+'" r="4.5" fill="'+(result.savingKg<0?'#a14d3c':'#224e37')+'" stroke="white" stroke-width="2"/><text x="35" y="112" fill="#8d9d82" font-size="9">1명</text><text x="320" y="112" text-anchor="end" fill="#8d9d82" font-size="9">3.2명</text><text x="320" y="10" text-anchor="end" fill="#8d9d82" font-size="9">'+(high/1000).toFixed(2)+' tCO₂</text>';
 $('occupancy-chart').setAttribute('aria-label','평균 재차인원에 따른 연간 탄소 감축량. 탄소 상쇄 기준 '+result.breakEven.toFixed(2)+'명');
}
function clearResults(){
 currentResult=null;
 for(const id of ['saving','break-even','baseline-total','drt-total'])$(id).textContent='—';
 $('saving-title').textContent='예상 연간 탄소 감축량';$('saving-percent').textContent='거리 조회 중';
 $('saving-card').classList.remove('negative','zero');
 $('baseline-bar').style.width='0';$('drt-bar').style.width='0';
 $('occupancy-chart').innerHTML='<text x="170" y="60" text-anchor="middle" fill="#78877e" font-size="12">거리 조회 후 표시됩니다.</text>';
 $('per-trip-note').textContent='왕복 1회당 배출량을 계산하고 있습니다.';
 $('break-even-note').textContent='기존 이동과 똑버스 배출량을 비교합니다.';
 $('sensitivity-note').textContent='재차인원 조건별 감축과 증가를 함께 확인합니다.';
}
function render(){
 const scope=data.scopes.find(s=>s.id===state.scope);
 window.dispatchEvent(new Event('scenariochange'));
 $('conversion').value=state.conversion*100;$('occupancy').value=state.occupancy;$('destination').value=state.destination;
 $('conversion-value').innerHTML=Math.round(state.conversion*100)+'<small>%</small>';
 $('occupancy-value').innerHTML=state.occupancy.toFixed(1)+'<small>명</small>';
 $('conversion-summary').textContent=Math.round(state.conversion*100);$('selected-pop').textContent=nf.format(scope.population);
 $('trips').textContent=nf.format(Math.round(scope.population*CarbonModel.defaults.visits*(CarbonModel.defaults.taxiShare+CarbonModel.defaults.carShare)*state.conversion));
 $('share').textContent=(scope.population/902*100).toFixed(1)+'%';$('share-bar').style.width=scope.population/902*100+'%';$('count').textContent=scope.count;
 $('map-title').textContent=scope.title;$('map-subtitle').textContent=scope.count+'개 격자 · 고령인구 '+scope.population+'명';
 $('destination-note').textContent=state.destination==='hospital'?'기존 이동과 똑버스 모두 병원까지 비교':'기존 이동은 병원까지 · 똑버스는 역까지 / 이후 환승의 증분 배출 0 적용';
 document.querySelectorAll('[data-scope]').forEach(b=>{const on=b.dataset.scope===state.scope;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});
 document.querySelectorAll('[data-vehicle]').forEach(b=>{const on=b.dataset.vehicle===state.vehicle;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});
 for(const c of cells){const on=active(c.grid,state.scope);if(on!==c.active){c.polygon.setOptions(style(on));c.active=on;}}
 for(const [id,p] of Object.entries(places))p.content.classList.toggle('chosen',id===state.destination);
 try{sessionStorage.setItem('goyang-scenario',JSON.stringify(state));}catch{}
 const baseline=distances.hospital, alternative=distances[state.destination];
 if(!baseline||!alternative){clearResults();return;}
 const params={population:scope.population,baselineKm:baseline.scopes[state.scope].roundtripKm,drtKm:alternative.scopes[state.scope].roundtripKm,conversion:state.conversion,occupancy:state.occupancy,vehicle:state.vehicle};
 const result=CarbonModel.calculate(params);currentResult=result;
 const negative=result.savingKg<-.000001, zero=Math.abs(result.savingKg)<.000001;
 $('saving-title').textContent=negative?'예상 연간 탄소 증가량':'예상 연간 탄소 감축량';
 $('saving').textContent=(Math.abs(result.savingKg)/1000).toFixed(2);
 $('saving-card').classList.toggle('negative',negative);$('saving-card').classList.toggle('zero',zero);
 $('saving-percent').textContent=result.percent===null?'전환 통행 없음':Math.abs(result.percent).toFixed(1)+'% '+(negative?'증가':'감축');
 $('break-even').textContent=result.breakEven.toFixed(2);
 $('break-even-note').textContent='계산상 '+result.breakEven.toFixed(2)+'명보다 높으면 감축 · 현재 '+state.occupancy.toFixed(1)+'명';
 $('baseline-total').textContent=(result.baselineKg/1000).toFixed(2);$('drt-total').textContent=(result.drtKg/1000).toFixed(2);
 const max=Math.max(result.baselineKg,result.drtKg)||1;
 $('baseline-bar').style.width=result.baselineKg/max*100+'%';$('drt-bar').style.width=result.drtKg/max*100+'%';
 $('drt-bar').style.background=negative?'#b27158':'#4d7a59';
 $('per-trip-note').textContent='왕복 1회당 '+result.baselinePerTrip.toFixed(2)+' → '+result.drtPerTrip.toFixed(2)+' kgCO₂';
 $('sensitivity-note').textContent=state.conversion===0?'전환율이 0%이므로 총 감축량도 0입니다.':(result.breakEven>3.2?'현재 거리·차종에서는 3.2명을 넘어야 감축됩니다.':'재차인원 '+result.breakEven.toFixed(2)+'명을 기준으로 증가와 감축이 나뉩니다.');
 chart(result,params);
 const time=new Date(alternative.queriedAt).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false});
 $('status').textContent='인구가중 왕복거리 · 기존 '+params.baselineKm.toFixed(2)+' km / 똑버스 연결 '+params.drtKm.toFixed(2)+' km · '+time+' 조회';
}
async function getDistance(id){
 if(distances[id])return distances[id];
 if(!pending[id])pending[id]=fetch('/api/distances?destination='+id).then(async r=>{const value=await r.json();if(!r.ok)throw new Error(value.error||'거리 조회에 실패했습니다.');distances[id]=value;return value;}).finally(()=>delete pending[id]);
 return pending[id];
}
async function loadDistances(){
 const destination=state.destination;$('retry').hidden=true;
 if(!distances.hospital||!distances[destination])$('status').textContent='121개 출발점의 자동차 왕복거리를 조회하고 있습니다…';
 try{await Promise.all([getDistance('hospital'),getDistance(destination)]);render();}
 catch(e){if(destination===state.destination){clearResults();$('saving-percent').textContent='거리 확인 필요';$('status').textContent=e.message;$('retry').hidden=false;}}
}
document.querySelectorAll('[data-scope]').forEach(b=>b.addEventListener('click',()=>{state.scope=b.dataset.scope;render();}));
document.querySelectorAll('[data-vehicle]').forEach(b=>b.addEventListener('click',()=>{state.vehicle=b.dataset.vehicle;render();}));
$('conversion').addEventListener('input',e=>{state.conversion=+e.target.value/100;render();});
$('occupancy').addEventListener('input',e=>{state.occupancy=+e.target.value;render();});
$('destination').addEventListener('change',e=>{state.destination=e.target.value;render();loadDistances();});
$('reset').addEventListener('click',()=>{state={...initial};render();loadDistances();if(map)map.setBounds(bounds,40,40,40,40);});
$('retry').addEventListener('click',loadDistances);
$('fit').addEventListener('click',()=>{if(map)map.setBounds(bounds,40,40,40,40);});
window.dashboard={data,state:()=>({...state}),result:()=>currentResult,distances,render,map:()=>map,cells:()=>cells};
render();loadDistances();
try{
 if(!window.KAKAO_TEST_CONFIG?.javascriptKey)throw new Error('지도 연결 준비 중입니다.');
 await new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='https://dapi.kakao.com/v2/maps/sdk.js?autoload=false&appkey='+encodeURIComponent(window.KAKAO_TEST_CONFIG.javascriptKey);s.onload=()=>window.kakao?.maps?kakao.maps.load(resolve):reject(new Error('지도 SDK를 확인해 주세요.'));s.onerror=()=>reject(new Error('카카오 지도 연결에 실패했습니다.'));document.head.append(s);});
 $('loading').remove();map=new kakao.maps.Map($('map'),{center:new kakao.maps.LatLng(37.681,126.718),level:7});bounds=new kakao.maps.LatLngBounds();
 cells=data.grids.map(grid=>{
  const path=grid.geometry.coordinates.map(r=>r.map(([lng,lat])=>{const p=new kakao.maps.LatLng(lat,lng);bounds.extend(p);return p;}));
  const on=active(grid,state.scope),polygon=new kakao.maps.Polygon({map,path,...style(on)}),cell={grid,polygon,active:on};
  kakao.maps.event.addListener(polygon,'click',()=>{$('cell-info').textContent=grid.properties.gid+' · 고령인구 '+nf.format(grid.properties.population)+'명';});return cell;
 });
 data.places.forEach(p=>{const [lng,lat]=p.geometry.coordinates,position=new kakao.maps.LatLng(lat,lng);bounds.extend(position);const content=document.createElement('div');content.className='place-label';content.textContent=p.properties.name;const label=new kakao.maps.CustomOverlay({map,position,content,yAnchor:1.2,zIndex:4});places[p.properties.id]={content,label,position};});
 map.addControl(new kakao.maps.ZoomControl(),kakao.maps.ControlPosition.RIGHT);map.setBounds(bounds,40,40,40,40);
 new ResizeObserver(()=>map.relayout()).observe($('map'));render();window.dashboard.mapReady=true;
}catch(e){if($('loading'))$('loading').textContent=e.message;document.querySelector('.live').textContent='지도 연결 확인 필요';window.dashboard.mapError=e.message;}
})().catch(error=>{document.getElementById('status').textContent='화면 준비 중 오류가 발생했습니다.';window.dashboardError=error.message;});

