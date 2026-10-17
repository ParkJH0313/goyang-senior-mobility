const model=require('./dist/model.js');
const destinations={clinic:'가까운 내과·정형외과 직결',daehwa:'대화역 정류장 → 일산백병원',seogu:'일산서구청 정류장 → 일산백병원'};
const keys=['tier','destination','vehicles','vehicle','conversion','occupancy','waitBaseMin'];
function validateScenario(value){
 if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!keys.includes(k)))throw Error('가상정류장과 운영 조건을 확인해 주세요.');
 const s={waitBaseMin:14.5,...value};
 if(!['t0','t21','t36','t61'].includes(s.tier)||!Object.hasOwn(destinations,s.destination)||!Number.isInteger(s.vehicles)||s.vehicles<1||s.vehicles>3||!Object.hasOwn(model.vehicles,s.vehicle)||!Number.isFinite(s.conversion)||s.conversion<0||s.conversion>1||!Number.isFinite(s.occupancy)||s.occupancy<1||s.occupancy>3.2||!Number.isFinite(s.waitBaseMin)||s.waitBaseMin<5||s.waitBaseMin>30)throw Error('가상정류장과 운영 조건을 확인해 주세요.');
 return s;
}
function createScenarios(data,router){return async value=>{
 const s=validateScenario(value),tier=data.tiers.find(t=>t.id===s.tier);
 try{return model.evaluate(data,s,await router.get(s.destination));}
 catch{return {available:false,scenario:s,population:data.totalPopulation,stops:{added:tier.stops},destinationTitle:destinations[s.destination],vehicleTitle:model.vehicles[s.vehicle].name,budget:model.budgetEstimate(s.vehicles,data.budget,s.vehicle),access:{current:data.access.baselineShare,withDrt:null},result:null,reason:'승하차 지점과 목적지의 왕복 경로를 모두 확인하지 못했습니다. 탄소·도달 효과는 표시하지 않습니다.'};}
};}
module.exports={validateScenario,createScenarios,keys,destinations};
