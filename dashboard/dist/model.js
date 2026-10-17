(function(root){
 'use strict';
 const defaults={visits:23.7,taxiShare:.046,carShare:.233,taxiEmpty:0,drtEmpty:.20,detour:1.25,taxiFactor:.139,carFactor:.132};
 // Operational approximation: combustion CO2 + electricity generation CO2e; not lifecycle.
 const electricity={kmPerKwh:3.9,kgPerKwh:.4173,inventoryYear:2023};
 const vehicles={electric:{name:'전기',model:'스타리아 투어러 일렉트릭 11인승',factor:0,seats:10},lpg:{name:'LPG',model:'스타리아 투어러 LPG 11인승',factor:.199,seats:10},hybrid:{name:'하이브리드',model:'스타리아 투어러 하이브리드 11인승',factor:.130,seats:10}};
 function factor(vehicle,scope='energy'){
  if(!Object.hasOwn(vehicles,vehicle)||!['energy','tailpipe'].includes(scope))throw Error('Invalid emission basis');
  return vehicle==='electric'&&scope==='energy'?electricity.kgPerKwh/electricity.kmPerKwh:vehicles[vehicle].factor;
 }
 function calculate({population,baselineKm,drtKm,conversion,occupancy,vehicle,emissionScope='energy'},p=defaults){
  if([population,baselineKm,drtKm,conversion,occupancy,...Object.values(p)].some(x=>!Number.isFinite(x))||population<0||baselineKm<0||drtKm<0||conversion<0||conversion>1||occupancy<=0)throw Error('Invalid model inputs');
  const modeShare=p.taxiShare+p.carShare;if(modeShare<=0||modeShare>1)throw Error('Invalid mode share');
  const trips=population*p.visits*modeShare*conversion;
  const baselinePerTrip=baselineKm*(p.taxiShare*p.taxiFactor*(1+p.taxiEmpty)+p.carShare*p.carFactor)/modeShare;
  const drtNumerator=drtKm*p.detour*(1+p.drtEmpty)*factor(vehicle,emissionScope),drtPerTrip=drtNumerator/occupancy;
  const baselineKg=trips*baselinePerTrip,drtKg=trips*drtPerTrip;
  return {trips,baselinePerTrip,drtPerTrip,baselineKg,drtKg,savingKg:baselineKg-drtKg,savingPerTrip:baselinePerTrip-drtPerTrip,percent:baselineKg?100*(baselineKg-drtKg)/baselineKg:null,breakEven:baselinePerTrip?drtNumerator/baselinePerTrip:null,drtOccupiedVehicleKmPerTrip:drtKm*p.detour/occupancy,vehicleFactor:factor(vehicle,emissionScope),emissionScope};
 }
 function annualCost(count,{dailyCostPerVehicle,days}){
  if(!Number.isInteger(count)||count<1||!Number.isFinite(dailyCostPerVehicle)||dailyCostPerVehicle<0||!Number.isFinite(days)||days<=0)throw Error('Invalid budget inputs');
  return count*dailyCostPerVehicle*days;
 }
 function waitMinutes(count,base=14.5,elasticity=.5){
  if(!Number.isInteger(count)||count<1||!Number.isFinite(base)||base<=0||!Number.isFinite(elasticity)||elasticity<0)throw Error('Invalid wait inputs');
  return base*Math.pow(2/count,elasticity);
 }
 function boardingTime(walkS,dispatchS,mode){
  if(mode==='overlap')return Math.max(walkS,dispatchS);
  if(mode==='sequential')return walkS+dispatchS;
  throw Error('Invalid calling mode');
 }
 const decoded=new WeakMap();
 function busProfiles(data){
  if(!decoded.has(data)){
   const result={};for(const o of data.origins){const bytes=typeof Buffer!=='undefined'?Buffer.from(o.bus,'base64'):Uint8Array.from(atob(o.bus),c=>c.charCodeAt(0));result[o.key]=Array.from({length:data.access.departureCount},(_,i)=>(bytes[i>>3]>>(7-(i&7)))&1);}
   decoded.set(data,result);
  }return decoded.get(data);
 }
 function evaluate(data,s,routes){
  if(!routes?.complete||routes.destination!==s.destination)throw Error('Route data missing or mismatched');
  const tier=data.tiers.find(t=>t.id===s.tier);if(!tier)throw Error('Unknown layout');
  const origins=Object.fromEntries(data.origins.map(o=>[o.key,o])),bus=busProfiles(data),a=data.access,n=a.departureCount;
  const waitMin=waitMinutes(s.vehicles,s.waitBaseMin??14.5,a.waitElasticity),dispatchS=waitMin*60;
  let eligible=0,baseKm=0,drtKm=0,walk=0,drive=0,stationaryWait=0,reachTotal=0;
  const cells=Object.fromEntries(data.grids.map(g=>[g.properties.gid,{gid:g.properties.gid,population:0,eligible:0,baseline:0,withDrt:0,walkS:0}]));
  for(const sample of data.demand){
   const o=origins[sample.origin],b=sample.boarding[s.tier],w=sample.population,cell=cells[o.parent_gid];
   const bs=bus[o.key].reduce((x,y)=>x+y,0)/n;let share=bs;
   cell.population+=w;cell.baseline+=w*bs;
   if(b){
    const target=s.destination==='clinic'?o.clinic:a.onward[s.destination].target;
    const route=routes.boarding[b.stop+'|'+target],baseline=routes.baseline[o.key];
    if(!route||!baseline||[route.outKm,route.backKm,route.driveS,baseline.outKm,baseline.backKm].some(x=>!Number.isFinite(x)||x<0))throw Error('Incomplete pickup routes');
    const board=boardingTime(b.walkS,dispatchS,s.waitMode??'overlap'),first=board+route.driveS*a.detour;
    let sum=0;
    for(let i=0;i<n;i++){
     let ok=false;
     if(s.destination==='clinic')ok=first+a.finalWalkS<=a.budgetS;
     else{
      const h=a.onward[s.destination],start=a.departureStartS+i*a.departureIntervalS,arrive=start+first+a.hubAlightS;
      const j=Math.ceil((arrive-h.departureStartS)/h.departureIntervalS),onward=h.onwardS[j];
      ok=j>=0&&j<h.onwardS.length&&onward!=null&&(h.departureStartS+j*h.departureIntervalS-start+onward<=a.budgetS);
     }
     sum+=(bus[o.key][i]||ok)?1:0;
    }
    share=sum/n;eligible+=w;baseKm+=w*(baseline.outKm+baseline.backKm);drtKm+=w*(route.outKm+route.backKm);
    walk+=w*b.walkS;drive+=w*route.driveS;stationaryWait+=w*(board-b.walkS);cell.eligible+=w;cell.walkS+=w*b.walkS;
   }
   cell.withDrt+=w*share;reachTotal+=w*share;
  }
  const mean=x=>eligible?x/eligible:0,distances={baselineKm:mean(baseKm),drtKm:mean(drtKm)};
  const result=calculate({...s,...distances,population:eligible});
  return {available:true,scenario:s,areaName:data.areaName,population:data.totalPopulation,gridCount:data.totalGrids,eligiblePopulation:eligible,
   stops:{added:tier.stops,walk5:tier.walk5,walk10:tier.walk10,existingWalk5:data.existing.walk5,existingWalk10:data.existing.walk10},destinationTitle:data.places.find(p=>p.id===s.destination).name,vehicleTitle:vehicles[s.vehicle].name,
   budget:{vehicles:s.vehicles,annualWon:annualCost(s.vehicles,data.budget),dailyCostPerVehicle:data.budget.dailyCostPerVehicle},distances,
   access:{current:data.access.baselineShare,withDrt:reachTotal/data.totalPopulation,waitMin,walkMin:mean(walk)/60,stationaryWaitMin:mean(stationaryWait)/60,driveMin:mean(drive)/60,waitModel:'sensitivity-not-forecast'},
   cells:Object.values(cells).map(c=>({...c,baseline:c.baseline/c.population,withDrt:c.withDrt/c.population,walkMin:c.eligible?c.walkS/c.eligible/60:null})),queriedAt:routes.queriedAt,result};
 }
 const model={defaults,electricity,vehicles,factor,calculate,annualCost,waitMinutes,boardingTime,evaluate};
 if(typeof module!=='undefined'&&module.exports)module.exports=model;else root.CarbonModel=model;
})(typeof window==='undefined'?globalThis:window);
