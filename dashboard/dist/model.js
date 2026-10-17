(function(root){
 'use strict';
 const defaults={visits:23.7,taxiShare:.046,carShare:.233,taxiEmpty:0,drtEmpty:.20,detour:1.25,taxiFactor:.139,carFactor:.132};
 // Certified representative tailpipe CO2; operating costs below are explicit planning assumptions.
 const vehicles={
  electric:{name:'전기',model:'스타리아 일렉트릭 11인승',factor:0,seats:10,purchaseWon:60290000,efficiency:3.9,energyWon:300,maintenanceWonKm:50},
  lpg:{name:'LPG',model:'스타리아 LPG 11인승',factor:.200,seats:10,purchaseWon:36590000,efficiency:6.7,energyWon:1200,maintenanceWonKm:80},
  hybrid:{name:'하이브리드',model:'스타리아 하이브리드 11인승',factor:.128,seats:10,purchaseWon:39990000,efficiency:12.7,energyWon:1750,maintenanceWonKm:70}
 };
 const costAssumptions={dailyKm:200,lifeYears:8,residualRate:0};
 const destinations={clinic:'주변 내과·정형외과 직행',baek:'백병원까지 직행',daehwa:'대화역 하차 후 백병원 이동'};
 const medicalTarget=destination=>destination==='clinic'?'주변 내과·정형외과':'일산백병원';
 const baselineShare=(data,destination)=>destination==='clinic'?data.access.baselineShare:data.access.baekBaselineShare;
 const scenarios={none:'똑버스 미도입',t0:'기존 정류장에 도입',t21:'가상 정류장 21곳 추가',t36:'가상 정류장 36곳 추가'};
 function factor(vehicle,scope='tailpipe'){
  if(!Object.hasOwn(vehicles,vehicle)||scope!=='tailpipe')throw Error('Tailpipe CO2 only');return vehicles[vehicle].factor;
 }
 function calculate({population,baselineKm,drtKm,conversion,occupancy,vehicle,emissionScope='tailpipe'},p=defaults){
  if([population,baselineKm,drtKm,conversion,occupancy,...Object.values(p)].some(x=>!Number.isFinite(x))||population<0||baselineKm<0||drtKm<0||conversion<0||conversion>1||occupancy<=0)throw Error('Invalid model inputs');
  const modeShare=p.taxiShare+p.carShare;if(modeShare<=0||modeShare>1)throw Error('Invalid mode share');
  const trips=population*p.visits*modeShare*conversion;
  const baselinePerTrip=baselineKm*(p.taxiShare*p.taxiFactor*(1+p.taxiEmpty)+p.carShare*p.carFactor)/modeShare;
  const drtNumerator=drtKm*p.detour*(1+p.drtEmpty)*factor(vehicle,emissionScope),drtPerTrip=drtNumerator/occupancy;
  const baselineKg=trips*baselinePerTrip,drtKg=trips*drtPerTrip;
  return {trips,baselinePerTrip,drtPerTrip,baselineKg,drtKg,savingKg:baselineKg-drtKg,savingPerTrip:baselinePerTrip-drtPerTrip,percent:baselineKg?100*(baselineKg-drtKg)/baselineKg:null,breakEven:baselinePerTrip?drtNumerator/baselinePerTrip:null,drtOccupiedVehicleKmPerTrip:drtKm*p.detour/occupancy,vehicleFactor:factor(vehicle),emissionScope:'tailpipe'};
 }
 function budgetEstimate(count,budget,vehicle='lpg'){
  const {dailyCostPerVehicle,days}=budget,a=costAssumptions,v=vehicles[vehicle];
  if(!v||!Number.isInteger(count)||count<1||!Number.isFinite(dailyCostPerVehicle)||dailyCostPerVehicle<0||!Number.isFinite(days)||days<=0)throw Error('Invalid budget inputs');
  const variable=x=>({energy:a.dailyKm/x.efficiency*x.energyWon,maintenance:a.dailyKm*x.maintenanceWonKm,depreciation:x.purchaseWon*(1-a.residualRate)/(a.lifeYears*days)});
  const reference=variable(vehicles.lpg),parts=variable(v),common=dailyCostPerVehicle-reference.energy-reference.maintenance-reference.depreciation;
  const dailyWon=common+parts.energy+parts.maintenance+parts.depreciation;
  return {vehicles:count,annualWon:count*days*dailyWon,dailyCostPerVehicle:dailyWon,purchaseWon:count*v.purchaseWon,commonDailyWon:common,...parts,assumptions:a};
 }
 function annualCost(count,budget,vehicle='lpg'){return budgetEstimate(count,budget,vehicle).annualWon;}
 function waitMinutes(count,base=14.5,elasticity=.5){
  if(!Number.isInteger(count)||count<1||!Number.isFinite(base)||base<=0||!Number.isFinite(elasticity)||elasticity<0)throw Error('Invalid wait inputs');
  return base*Math.pow(2/count,elasticity);
 }
 function pickupTiming(walkS,dispatchS,bufferS=90){
  if([walkS,dispatchS,bufferS].some(x=>!Number.isFinite(x)||x<0))throw Error('Invalid pickup timing');
  const pickupS=Math.max(dispatchS,walkS+bufferS);
  return {homeWaitS:pickupS-walkS-bufferS,walkS,stopWaitS:bufferS,fromHomeS:walkS+bufferS,fromCallS:pickupS};
 }
 const decoded=new WeakMap();
 function busProfiles(data,destination){
  if(!decoded.has(data))decoded.set(data,{});
  const fields=decoded.get(data),field=destination==='clinic'?'bus':'busBaek';
  if(!fields[field]){
   const result={};for(const o of data.origins){const bytes=typeof Buffer!=='undefined'?Buffer.from(o[field],'base64'):Uint8Array.from(atob(o[field]),c=>c.charCodeAt(0));result[o.key]=Array.from({length:data.access.departureCount},(_,i)=>(bytes[i>>3]>>(7-(i&7)))&1);}
   fields[field]=result;
  }return fields[field];
 }
 function evaluate(data,s,routes){
  if(!Object.hasOwn(destinations,s.destination))throw Error('Unknown medical connection');
  const baseline=baselineShare(data,s.destination);
  if(s.tier==='none'){
   const profiles=busProfiles(data,s.destination),cells=Object.fromEntries(data.grids.map(g=>[g.properties.gid,{gid:g.properties.gid,population:0,baseline:0}]));
   const origins=Object.fromEntries(data.origins.map(o=>[o.key,o]));
   for(const sample of data.demand){const c=cells[origins[sample.origin].parent_gid];c.population+=sample.population;c.baseline+=sample.population*profiles[sample.origin].reduce((x,y)=>x+y,0)/data.access.departureCount;}
   return {available:true,drtEnabled:false,scenario:s,scenarioTitle:scenarios.none,areaName:data.areaName,population:data.totalPopulation,gridCount:data.totalGrids,eligiblePopulation:0,
    stops:{added:0,walk5:data.existing.walk5,walk10:data.existing.walk10,existingWalk5:data.existing.walk5,existingWalk10:data.existing.walk10},destinationTitle:'기존 대중교통·보행으로 '+medicalTarget(s.destination)+' 이동',vehicleTitle:'운행 없음',
    budget:{vehicles:0,annualWon:0,purchaseWon:0,dailyCostPerVehicle:0},distances:null,
    access:{current:baseline,withDrt:baseline,withDrtFromCall:null,timeBasis:'home-departure',waitMin:null,homeWaitMin:null,walkMin:null,stationaryWaitMin:null,driveMin:null,waitModel:'not-applicable'},
    cells:Object.values(cells).map(c=>({...c,eligible:0,baseline:c.baseline/c.population,withDrt:c.baseline/c.population,walkMin:null})),queriedAt:null,
    result:{trips:0,savingKg:0,percent:null,baselineKg:null,drtKg:null,baselinePerTrip:null,drtPerTrip:null,breakEven:null,emissionScope:'tailpipe'}};
  }
  if(!routes?.complete||routes.destination!==s.destination)throw Error('Route data missing or mismatched');
  const tier=data.tiers.find(t=>t.id===s.tier);if(!tier)throw Error('Unknown layout');
  const origins=Object.fromEntries(data.origins.map(o=>[o.key,o])),bus=busProfiles(data,s.destination),a=data.access,n=a.departureCount;
  const waitMin=waitMinutes(s.vehicles,s.waitBaseMin??14.5,a.waitElasticity),dispatchS=waitMin*60;
  let eligible=0,baseKm=0,drtKm=0,walk=0,drive=0,homeWait=0,reachTotal=0,callReachTotal=0;
  const cells=Object.fromEntries(data.grids.map(g=>[g.properties.gid,{gid:g.properties.gid,population:0,eligible:0,baseline:0,withDrt:0,walkS:0}]));
  const onward=(first,i)=>{
   if(s.destination==='clinic'||s.destination==='baek')return first+a.finalWalkS;
   const h=a.onward[s.destination],start=a.departureStartS+i*a.departureIntervalS,arrive=start+first+a.hubAlightS;
   const j=Math.ceil((arrive-h.departureStartS)/h.departureIntervalS),next=h.onwardS[j];
   return j>=0&&j<h.onwardS.length&&next!=null?h.departureStartS+j*h.departureIntervalS-start+next:Infinity;
  };
  for(const sample of data.demand){
   const o=origins[sample.origin],w=sample.population,cell=cells[o.parent_gid],bs=bus[o.key].reduce((x,y)=>x+y,0)/n;
   const options=sample.pickups[s.tier];let share=bs,callShare=bs;
   cell.population+=w;cell.baseline+=w*bs;
   if(options.length){
    const target=s.destination==='clinic'?o.clinic:'baek',baseline=routes.baseline[o.key];
    if(!baseline||[baseline.outKm,baseline.backKm].some(x=>!Number.isFinite(x)||x<0))throw Error('Incomplete baseline routes');
    const candidates=options.map(b=>{
     const route=routes.boarding[b.stop+'|'+target];
     if(!route||[route.outKm,route.backKm,route.driveS].some(x=>!Number.isFinite(x)||x<0))throw Error('Incomplete pickup routes');
     const timing=pickupTiming(b.walkS,dispatchS,a.pickupBufferS??90);
     return {b,route,timing,first:timing.fromHomeS+route.driveS*a.detour,callFirst:timing.fromCallS+route.driveS*a.detour};
    }).sort((x,y)=>x.first-y.first||x.b.walkS-y.b.walkS||x.b.stop.localeCompare(y.b.stop));
    let sum=0,callSum=0,km=0,l=0,d=0,h=0;
    for(let i=0;i<n;i++){
     let chosen=candidates[0],best=Infinity,callBest=Infinity;
     for(const c of candidates){const duration=onward(c.first,i);if(duration<best){best=duration;chosen=c;}callBest=Math.min(callBest,onward(c.callFirst,i));}
     sum+=(bus[o.key][i]||best<=a.budgetS)?1:0;callSum+=(bus[o.key][i]||callBest<=a.budgetS)?1:0;
     km+=chosen.route.outKm+chosen.route.backKm;l+=chosen.b.walkS;d+=chosen.route.driveS;h+=chosen.timing.homeWaitS;
    }
    share=sum/n;callShare=callSum/n;eligible+=w;baseKm+=w*(baseline.outKm+baseline.backKm);drtKm+=w*km/n;
    walk+=w*l/n;drive+=w*d/n;homeWait+=w*h/n;cell.eligible+=w;cell.walkS+=w*l/n;
   }
   cell.withDrt+=w*share;reachTotal+=w*share;callReachTotal+=w*callShare;
  }
  const mean=x=>eligible?x/eligible:0,distances={baselineKm:mean(baseKm),drtKm:mean(drtKm)};
  const result=calculate({...s,...distances,population:eligible});
  return {available:true,drtEnabled:true,scenario:s,scenarioTitle:scenarios[s.tier]||('가상 정류장 '+tier.stops+'곳 추가'),areaName:data.areaName,population:data.totalPopulation,gridCount:data.totalGrids,eligiblePopulation:eligible,
   stops:{added:tier.stops,walk5:tier.walk5,walk10:tier.walk10,existingWalk5:data.existing.walk5,existingWalk10:data.existing.walk10},destinationTitle:destinations[s.destination],vehicleTitle:vehicles[s.vehicle].model,
   budget:budgetEstimate(s.vehicles,data.budget,s.vehicle),distances,
   access:{current:baseline,withDrt:reachTotal/data.totalPopulation,withDrtFromCall:callReachTotal/data.totalPopulation,timeBasis:'home-departure',waitMin,homeWaitMin:mean(homeWait)/60,walkMin:mean(walk)/60,stationaryWaitMin:eligible?(a.pickupBufferS??90)/60:0,driveMin:mean(drive)/60,waitModel:'scheduled-pickup-sensitivity'},
   cells:Object.values(cells).map(c=>({...c,baseline:c.baseline/c.population,withDrt:c.withDrt/c.population,walkMin:c.eligible?c.walkS/c.eligible/60:null})),queriedAt:routes.queriedAt,result};
 }
 const model={defaults,vehicles,costAssumptions,scenarios,destinations,medicalTarget,baselineShare,factor,calculate,annualCost,budgetEstimate,waitMinutes,pickupTiming,evaluate};
 if(typeof module!=='undefined'&&module.exports)module.exports=model;else root.CarbonModel=model;
})(typeof window==='undefined'?globalThis:window);
