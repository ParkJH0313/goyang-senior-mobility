const model = require('./dist/model.js');
const destinations = {hospital:'일산백병원 직결',tanhyeon:'탄현역까지 이동 후 환승',kintex:'킨텍스역까지 이동 후 환승'};
const keys = ['scope','destination','vehicle','conversion','occupancy'];
function validateScenario(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(k => !keys.includes(k))) throw new Error('지원 범위와 운영 조건을 확인해 주세요.');
  const {scope,destination,vehicle,conversion,occupancy} = value;
  if (!['core','extended','all'].includes(scope) || !Object.hasOwn(destinations,destination) || !['lpg','hybrid'].includes(vehicle) || !Number.isFinite(conversion) || conversion < 0 || conversion > 1 || !Number.isFinite(occupancy) || occupancy < 1 || occupancy > 3.2) throw new Error('지원 범위와 운영 조건을 확인해 주세요.');
  return {scope,destination,vehicle,conversion,occupancy};
}
function createScenarios(data,router) {
  return async function evaluate(value) {
    const scenario = validateScenario(value);
    const scope = data.scopes.find(s => s.id === scenario.scope);
    const summary = {scenario,scopeTitle:scope.title,population:scope.population,gridCount:scope.count,destinationTitle:destinations[scenario.destination],vehicleTitle:model.vehicles[scenario.vehicle].name};
    try {
      const [baseline,alternative] = await Promise.all([router.get('hospital'),router.get(scenario.destination)]);
      if (!baseline.complete || !alternative.complete) throw new Error('Incomplete routes');
      const distances = {baselineKm:baseline.scopes[scenario.scope].roundtripKm,drtKm:alternative.scopes[scenario.scope].roundtripKm};
      return {...summary,distances,queriedAt:alternative.queriedAt,result:model.calculate({...scenario,...distances,population:scope.population}),available:true};
    } catch {
      return {...summary,available:false,result:null,reason:'자동차 왕복거리가 준비되지 않아 감축량을 계산할 수 없습니다.'};
    }
  };
}
module.exports = {validateScenario,createScenarios,keys};
