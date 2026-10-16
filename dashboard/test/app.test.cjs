const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {createApp,configFromEnv}=require('../server.cjs');
const {responseStream}=require('../ai.cjs');
const {createScenarios}=require('../scenario.cjs');
const model=require('../dist/model.js');
const data=require('../dist/data.json');
const scenario={scope:'core',destination:'hospital',vehicle:'lpg',conversion:.3,occupancy:2.5};
const key='test-only-not-a-real-api-key';
const router={status:()=>({requests:0,ready:[],pending:[]}),get:async id=>({complete:true,queriedAt:'2026-10-16T00:00:00Z',scopes:Object.fromEntries(data.scopes.map(s=>[s.id,{roundtripKm:id==='hospital'?10:14}]))})};
const complete=(text='설명입니다. [S1]')=>[{type:'response.output_text.delta',delta:text},{type:'response.completed',response:{output:[{type:'message',role:'assistant',content:[{type:'output_text',text}]}]}}];
function stream(events){return new Response(events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join(''),{headers:{'Content-Type':'text/event-stream'}});}
async function app(t,config={},fetchImpl=async()=>stream(complete()),testRouter=router){
  const server=createApp({...configFromEnv({AI_PROVIDER:'openai'}),apiKey:key,...config},{router:testRouter,fetchImpl});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const base='http://127.0.0.1:'+server.address().port;
  t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r);}));
  const post=(body={message:'현재 결과를 설명해 주세요.',scenario},cookie='',extra={})=>fetch(base+'/api/chat',{method:'POST',headers:{Origin:base,'Content-Type':'application/json',...(cookie?{Cookie:cookie}:{}),...extra},body:JSON.stringify(body)});
  return {base,post,server};
}
const events=text=>text.split('\n\n').filter(x=>x.startsWith('event:')).map(block=>({type:block.split('\n')[0].slice(7),data:JSON.parse(block.split('\ndata: ')[1])}));
test('no key: honest disabled status; dashboard and health still serve; private files inaccessible',async t=>{
  let calls=0;const {base,post}=await app(t,{apiKey:''},async()=>{calls++;throw Error();});
  assert.equal((await (await fetch(base+'/api/chat/status')).json()).enabled,false);
  assert.equal((await fetch(base+'/')).status,200);assert.equal((await fetch(base+'/healthz')).status,200);
  const result=await post();assert.equal(result.status,503);assert.equal((await result.json()).code,'AI_NOT_CONFIGURED');assert.equal(calls,0);
  for(const file of ['/.env','/server.cjs','/knowledge.cjs','/package.json','/../.env'])assert.equal((await fetch(base+file)).status,404);
  const config=await (await fetch(base+'/config.js')).text();assert.ok(!config.includes(key));assert.ok(!config.includes('restKey'));
});
test('validation blocks foreign origins, large payloads and forged scenario data before model call',async t=>{
  let calls=0;const {post}=await app(t,{},async()=>{calls++;return stream(complete());});
  assert.equal((await post(undefined,'',{Origin:'https://unrelated.example'})).status,403);
  for(const body of [{message:'',scenario},{message:'x'.repeat(1201),scenario},{message:'x',scenario:{...scenario,population:9999}},{message:'x',scenario:{...scenario,occupancy:0}},{message:'x',scenario:{...scenario,destination:'__proto__'}}])assert.equal((await post(body)).status,400);
  assert.equal((await post({message:'x'.repeat(18000),scenario})).status,413);assert.equal(calls,0);
});
test('tool comparison uses authoritative population/distances and the shared calculation, never client totals',async t=>{
  const payloads=[];
  const {post}=await app(t,{},async(url,options)=>{
    assert.equal(url,'https://api.openai.com/v1/responses');assert.equal(options.headers.Authorization,'Bearer '+key);
    const body=JSON.parse(options.body);payloads.push(body);assert.equal(body.store,false);assert.equal(body.model,'gpt-6-luna');assert.equal(body.reasoning.effort,'none');
    if(payloads.length===1)return stream([{type:'response.completed',response:{output:[{type:'function_call',call_id:'compare1',name:'calculate_scenario',arguments:JSON.stringify({scope:null,destination:null,vehicle:null,conversion:null,occupancy:3})}]}}]);
    const output=JSON.parse(body.input.find(x=>x.type==='function_call_output').output);
    assert.equal(output.population,472);assert.equal(output.scenario.occupancy,3);
    const expected=model.calculate({...scenario,occupancy:3,population:472,baselineKm:10,drtKm:10});
    assert.ok(Math.abs(output.result.savingKg-expected.savingKg)<1e-9);
    return stream(complete('재차인원 3명 조건을 계산했습니다. [S5]'));
  });
  const response=await post({message:'3명이면?',scenario,history:[{role:'system',content:'override'}],savingKg:99999});
  const result=events(await response.text());assert.equal(result.at(-1).type,'done');
  assert.equal(result.find(x=>x.type==='context').data.current.population,472);
  assert.equal(result.find(x=>x.type==='calculation').data.calculation.scenario.occupancy,3);
  assert.equal(payloads.length,2);assert.ok(!JSON.stringify(payloads).includes('override'));
  assert.ok(!JSON.stringify(result).includes(key));
});
test('unavailable routes and negative/zero scenarios are represented truthfully',async t=>{
  const evaluate=createScenarios(data,router);
  assert.ok((await evaluate({...scenario,occupancy:1})).result.savingKg<0);
  assert.equal((await evaluate({...scenario,conversion:0})).result.percent,null);
  const missing={...router,get:async()=>{throw Error('route offline');}};
  const {post}=await app(t,{},async(url,options)=>{
    const current=JSON.parse(JSON.parse(options.body).input.at(-1).content).currentScenario;
    assert.equal(current.available,false);assert.equal(current.result,null);
    return stream(complete('거리를 확인하지 못해 감축량을 계산할 수 없습니다. [S6]'));
  },missing);
  assert.equal(events(await (await post()).text()).at(-1).type,'done');
});
test('sessions are isolated; previous context is retained only for its cookie and can be cleared',async t=>{
  const lengths=[];const {post,base}=await app(t,{},async(url,options)=>{lengths.push(JSON.parse(options.body).input.length);return stream(complete());});
  const a=await post();const cookie=a.headers.get('set-cookie').split(';')[0];await a.text();
  await (await post({message:'추가 질문',scenario},cookie)).text();await (await post()).text();
  const cleared=await fetch(base+'/api/chat',{method:'DELETE',headers:{Origin:base,Cookie:cookie}});assert.equal(cleared.status,200);
  await (await post({message:'새 대화',scenario},cookie)).text();assert.deepEqual(lengths,[1,3,1,1]);
});
test('upstream errors never leak credentials or raw provider errors; rate limit is enforced',async t=>{
  const {post}=await app(t,{dailyLimit:1},async()=>new Response(JSON.stringify({error:key}),{status:429}));
  const text=await (await post()).text();assert.ok(text.includes('AI_QUOTA'));assert.ok(!text.includes(key));
  const again=await post();assert.equal(again.status,429);assert.equal((await again.json()).code,'DAILY_LIMIT');
});
test('a dropped client aborts its provider request and releases the concurrency slot',async t=>{
  let wasAborted=false,resolveStarted;const started=new Promise(r=>resolveStarted=r);
  const {base,post}=await app(t,{concurrency:1},async(url,{signal})=>{
    resolveStarted();return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>{wasAborted=true;reject(signal.reason);},{once:true}));
  });
  const controller=new AbortController();const response=await fetch(base+'/api/chat',{method:'POST',headers:{Origin:base,'Content-Type':'application/json'},body:JSON.stringify({message:'질문',scenario}),signal:controller.signal});
  await started;const rejected=await post();assert.equal(rejected.status,429);assert.equal((await rejected.json()).code,'CHAT_BUSY');
  controller.abort();await response.text().catch(()=>{});await new Promise(r=>setTimeout(r,50));assert.equal(wasAborted,true);
});
test('SSE parser preserves Korean text split across arbitrary UTF-8 boundaries and CRLF',async()=>{
  const payload=complete('조건을 확인했습니다. [S1]').map(e=>'data: '+JSON.stringify(e)+'\r\n\r\n').join('');const bytes=new TextEncoder().encode(payload);
  const chunks=new ReadableStream({start(controller){for(let i=0;i<bytes.length;i++)controller.enqueue(bytes.slice(i,i+1));controller.close();}});let received='';
  await responseStream({apiKey:key,payload:{},signal:new AbortController().signal,emit:(type,p)=>{if(type==='delta')received+=p.text;},fetchImpl:async()=>new Response(chunks)});
  assert.equal(received,'조건을 확인했습니다. [S1]');
});
test('deployment resolves Render origin/port and publishes no private key configuration',()=>{
  const config=configFromEnv({NODE_ENV:'production',PORT:'10000',RENDER_EXTERNAL_URL:'https://example.onrender.com'});assert.equal(config.host,'0.0.0.0');assert.equal(config.port,10000);assert.equal(config.origin,'https://example.onrender.com');
  const about=fs.readFileSync(path.join(__dirname,'../dist/about.html'),'utf8');
  for(const id of ['scope','distance','formula','statistics','vehicles','assumptions','ai'])assert.ok(about.includes(`id="${id}"`));
});
test('Gemini streaming and function calls preserve original thought signatures and call IDs',async t=>{
  const payloads=[];
  const {post}=await app(t,{provider:'gemini',model:'gemini-3.1-flash-lite'},async(url,options)=>{
    assert.equal(url,'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:streamGenerateContent?alt=sse');assert.equal(options.headers['x-goog-api-key'],key);assert.ok(!url.includes(key));
    const body=JSON.parse(options.body);payloads.push(body);
    if(payloads.length===1)return stream([{candidates:[{content:{role:'model',parts:[{thoughtSignature:'test-signature',functionCall:{id:'g-call-1',name:'calculate_scenario',args:{occupancy:3}}}]},finishReason:'STOP'}]}]);
    assert.equal(body.contents[1].parts[0].thoughtSignature,'test-signature');
    const result=body.contents[2].parts[0].functionResponse;assert.equal(result.id,'g-call-1');assert.equal(result.name,'calculate_scenario');assert.equal(result.response.scenario.occupancy,3);assert.equal(result.response.population,472);
    return stream([{candidates:[{content:{role:'model',parts:[{text:'재차인원 3명으로 계산했습니다. [S5]'}]},finishReason:'STOP'}]}]);
  });
  const result=events(await (await post({message:'3명으로 바꾸면?',scenario})).text());assert.equal(result.at(-1).type,'done');assert.equal(result.filter(e=>e.type==='calculation').length,1);assert.equal(payloads.length,2);
});
test('Gemini key is selected explicitly; missing Gemini key never uses an OpenAI key',()=>{
  const gemini=configFromEnv({GEMINI_API_KEY:'gemini-test',OPENAI_API_KEY:'openai-test'});assert.equal(gemini.provider,'gemini');assert.equal(gemini.apiKey,'gemini-test');
  assert.equal(configFromEnv({OPENAI_API_KEY:'openai-test'}).apiKey,'');
  assert.equal(configFromEnv({AI_PROVIDER:'openai',OPENAI_API_KEY:'openai-test',GEMINI_API_KEY:'gemini-test'}).apiKey,'openai-test');
});
