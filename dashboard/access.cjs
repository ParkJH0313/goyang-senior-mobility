// 30분 의료시설 도달 비율: 기존 버스(본 분석 출발시각별 결과) 또는 똑버스 중 하나로 도달하면 도달로 센다.
// 똑버스 = 호출~탑승 W + 카카오 자동차 소요시간 × 우회계수 + (직결) 하차 후 도보 / (역) 역 격자에서 대중교통으로 이어서 도달
function decodeBits(text,count){const bytes=Buffer.from(text,'base64');return Array.from({length:count},(_,i)=>(bytes[i>>3]>>(7-(i&7)))&1);}
function createAccess(data){
  const a=data.access,n=a.departureCount;
  const bus=new Map(data.origins.map(o=>[o.key,decodeBits(o.bus,n)]));
  const tierIds=data.tiers.map(t=>t.id);
  function drtReach(destination,driveS){
    const ride=a.waitS+driveS*a.detour;
    if(destination==='clinic'){const ok=ride+a.finalWalkS<=a.budgetS;return Array(n).fill(ok?1:0);}
    const onward=a.onward[destination].onwardS;
    return Array.from({length:n},(_,i)=>{
      const arrive=a.departureStartS+i*a.departureIntervalS+ride;
      const j=Math.ceil((arrive-a.departureStartS)/a.departureIntervalS);
      if(j>=n||onward[j]==null)return 0;
      const total=(a.departureStartS+j*a.departureIntervalS-(a.departureStartS+i*a.departureIntervalS))+onward[j];
      return total<=a.budgetS?1:0;
    });
  }
  // durations: Map(originKey -> 출발점→목적지 자동차 소요시간 초)
  return function shares(destination,durations){
    const totals=Object.fromEntries(tierIds.map(id=>[id,0]));let population=0,baseline=0,drtOnly=0;
    for(const o of data.origins){
      const b=bus.get(o.key),d=drtReach(destination,durations.get(o.key));
      const busShare=b.reduce((s,x)=>s+x,0)/n,either=b.reduce((s,x,i)=>s+(x||d[i]),0)/n;
      population+=o.population;baseline+=o.population*busShare;drtOnly+=o.population*d.reduce((s,x)=>s+x,0)/n;
      for(const id of tierIds){const u=o.usable[id];totals[id]+=o.population*(u*either+(1-u)*busShare);}
    }
    return {baseline:baseline/population,drtOnly:drtOnly/population,tiers:Object.fromEntries(tierIds.map(id=>[id,totals[id]/population]))};
  };
}
module.exports={createAccess,decodeBits};
