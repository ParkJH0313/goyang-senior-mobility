const model = require('./dist/model.js');
const destinations = {clinic:'가까운 내과·정형외과 직결',tanhyeon:'탄현역까지 이동 후 환승',kintex:'킨텍스역까지 이동 후 환승'};
const keys = ['tier','destination','vehicles','vehicle','conversion','occupancy'];
const tiers = ['t21','t36','t61'];
function validateScenario(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(k => !keys.includes(k))) throw new Error('가상정류장과 운영 조건을 확인해 주세요.');
  const {tier,destination,vehicles,vehicle,conversion,occupancy} = value;
  if (!tiers.includes(tier) || !Object.hasOwn(destinations,destination) || !Number.isInteger(vehicles) || vehicles < 1 || vehicles > 3 || !['lpg','hybrid'].includes(vehicle) || !Number.isFinite(conversion) || conversion < 0 || conversion > 1 || !Number.isFinite(occupancy) || occupancy < 1 || occupancy > 3.2) throw new Error('가상정류장과 운영 조건을 확인해 주세요.');
  return {tier,destination,vehicles,vehicle,conversion,occupancy};
}
function createScenarios(data,router) {
  return async function evaluate(value) {
    const scenario = validateScenario(value);
    const tier = data.tiers.find(t => t.id === scenario.tier);
    const budget = {vehicles:scenario.vehicles,annualWon:model.annualCost(scenario.vehicles,data.budget),dailyCostPerVehicle:data.budget.dailyCostPerVehicle};
    const summary = {scenario,areaName:data.areaName,population:data.totalPopulation,gridCount:data.totalGrids,
      stops:{added:tier.stops,walk5:tier.walk5,walk10:tier.walk10,existingWalk5:data.existing.walk5,existingWalk10:data.existing.walk10},
      destinationTitle:destinations[scenario.destination],vehicleTitle:model.vehicles[scenario.vehicle].name,budget};
    try {
      const [baseline,alternative] = await Promise.all([router.get('clinic'),router.get(scenario.destination)]);
      if (!baseline.complete || !alternative.complete) throw new Error('Incomplete routes');
      const distances = {baselineKm:baseline.roundtripKm,drtKm:alternative.roundtripKm};
      const access = {current:data.access.baselineShare,withDrt:alternative.access.tiers[scenario.tier],waitMin:data.access.waitS/60,driveMin:alternative.driveMin};
      return {...summary,distances,access,queriedAt:alternative.queriedAt,result:model.calculate({...scenario,...distances,population:data.totalPopulation}),available:true};
    } catch {
      return {...summary,access:{current:data.access.baselineShare,withDrt:null},available:false,result:null,reason:'자동차 경로가 준비되지 않아 30분 도달 효과와 탄소 감축량을 계산할 수 없습니다.'};
    }
  };
}
module.exports = {validateScenario,createScenarios,keys,destinations};
