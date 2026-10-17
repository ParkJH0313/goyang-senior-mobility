// Read-only comparison of two saved live route responses; no API calls or assumed driving times.
// node dashboard/analysis/compare_hubs.cjs <data-snapshot.json> <daehwa.json> <seogu.json> > <report.json>
const fs=require('node:fs'),crypto=require('node:crypto');
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const ids=['daehwa','seogu'],[sourcePath,...paths]=process.argv.slice(2);
if(!sourcePath||paths.length!==2)throw Error('Provide source data snapshot and Daehwa/Seogu route response files');
const data=JSON.parse(fs.readFileSync(sourcePath,'utf8'));
const routes=paths.map((p,i)=>{const r=JSON.parse(fs.readFileSync(p,'utf8'));if(!r.complete||r.destination!==ids[i]||r.runId!==data.runId)throw Error('Mismatched route snapshot');return r;});
const a=data.access,rows=[];
for(const tier of ['t0','t21','t36']){
 let eligible=0,commonWeight=0;const elapsed=[0,0],onward=[0,0],drive=[0,0],within30=[0,0];
 for(const sample of data.demand){
  const options=sample.pickups[tier];if(!options.length)continue;eligible+=sample.population;
  const candidates=routes.map(r=>options.map(p=>{const v=r.boarding[p.stop+'|baek'];if(!v||!Number.isFinite(v.driveS))throw Error('Missing boarding route');return {first:p.walkS+a.pickupBufferS+v.driveS*a.detour,drive:v.driveS*a.detour};}));
  for(let i=0;i<a.departureCount;i++){
   const start=a.departureStartS+i*a.departureIntervalS,w=sample.population/a.departureCount;
   const best=candidates.map((options,k)=>{const h=a.onward[ids[k]];let result={total:Infinity};for(const c of options){const j=Math.ceil((start+c.first+a.hubAlightS-h.departureStartS)/h.departureIntervalS),next=h.onwardS[j];if(j<0||j>=h.onwardS.length||next==null)continue;const total=h.departureStartS+j*h.departureIntervalS-start+next;if(total<result.total)result={total,drive:c.drive,onward:total-c.first};}return result;});
   for(let k=0;k<2;k++)if(best[k].total<=a.budgetS)within30[k]+=w;
   // Both means use exactly the same population/departure cases; missing late profiles are excluded from both.
   if(best.every(v=>Number.isFinite(v.total))){commonWeight+=w;for(let k=0;k<2;k++){elapsed[k]+=best[k].total*w;onward[k]+=best[k].onward*w;drive[k]+=best[k].drive*w;}}
  }
 }
 rows.push({tier,eligiblePopulation:eligible,commonFinitePopulationEquivalent:commonWeight,commonFiniteShare:commonWeight/eligible,
  alternatives:ids.map((id,k)=>({id,meanHomeToHospitalMin:elapsed[k]/commonWeight/60,meanDrivingMin:drive[k]/commonWeight/60,meanAfterAlightingMin:onward[k]/commonWeight/60,drtWithin30ShareOfPopulation:within30[k]/data.totalPopulation}))});
}
const winner=ids.find((_,k)=>rows.every(row=>row.alternatives[k].meanHomeToHospitalMin<row.alternatives[1-k].meanHomeToHospitalMin))||null;
console.log(JSON.stringify({runId:data.runId,dataGeneratedAt:data.generatedAt,dataSha256:hash(sourcePath),routeQueries:routes.map((r,i)=>({id:ids[i],queriedAt:r.queriedAt,sha256:hash(paths[i])})),
 basis:'Home departure; population and minute weighted; matched finite cases for travel means; same Baek hospital; fixed detour and scheduled 1.5-minute pickup buffer. DRT-only reach is separate from transit union.',selectedHub:winner,selection:winner?'Lower mean total travel time in all three active layouts among these two candidates only; not a citywide optimum.':'No single faster hub across all layouts.',rows},null,2));
