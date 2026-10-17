// Synthetic route fixture for tests only. Never enabled by production configuration.
function routeFixture(data,destination='clinic',driveS=480){
 const baseline=Object.fromEntries(data.origins.map(o=>[o.key,{outKm:5,backKm:5,driveS}]));
 const boarding={},origins=Object.fromEntries(data.origins.map(o=>[o.key,o]));
 for(const d of data.demand){const target=destination==='clinic'?origins[d.origin].clinic:data.access.onward[destination].target;
  for(const b of Object.values(d.boarding))if(b)boarding[b.stop+'|'+target]={outKm:4.8,backKm:5.2,driveS};}
 return {complete:true,destination,queriedAt:'2026-10-17T00:00:00Z',baseline,boarding};
}
module.exports={routeFixture};
