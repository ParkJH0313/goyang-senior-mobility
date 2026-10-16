(function(root){
 const defaults={visits:23.7,taxiShare:.046,carShare:.233,taxiEmpty:0,drtEmpty:.20,detour:1.25,taxiFactor:.139,carFactor:.132};
 const vehicles={lpg:{name:'LPG',factor:.199},hybrid:{name:'하이브리드',factor:.130}};
 function calculate({population,baselineKm,drtKm,conversion,occupancy,vehicle},p=defaults){
  const values=[population,baselineKm,drtKm,conversion,occupancy,...Object.values(p)];
  if(values.some(x=>!Number.isFinite(x))||population<0||baselineKm<=0||drtKm<=0||conversion<0||conversion>1||occupancy<=0||!vehicles[vehicle])throw new Error('Invalid model inputs');
  const modeShare=p.taxiShare+p.carShare;
  if(modeShare<=0||modeShare>1)throw new Error('Invalid mode share');
  const trips=population*p.visits*modeShare*conversion;
  const baselinePerTrip=baselineKm*(p.taxiShare*p.taxiFactor*(1+p.taxiEmpty)+p.carShare*p.carFactor)/modeShare;
  const drtNumerator=drtKm*p.detour*(1+p.drtEmpty)*vehicles[vehicle].factor;
  const drtPerTrip=drtNumerator/occupancy;
  const baselineKg=trips*baselinePerTrip,drtKg=trips*drtPerTrip;
  return {trips,baselinePerTrip,drtPerTrip,baselineKg,drtKg,savingKg:baselineKg-drtKg,savingPerTrip:baselinePerTrip-drtPerTrip,percent:baselineKg?100*(baselineKg-drtKg)/baselineKg:null,breakEven:drtNumerator/baselinePerTrip,drtOccupiedVehicleKmPerTrip:drtKm*p.detour/occupancy};
 }
 const model={defaults,vehicles,calculate};if(typeof module!=='undefined'&&module.exports)module.exports=model;else root.CarbonModel=model;
})(typeof window==='undefined'?globalThis:window);
