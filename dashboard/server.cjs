const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {createRouter}=require('./routing.cjs');
const {validateScenario,createScenarios}=require('./scenario.cjs');
const {createAI,ChatError}=require('./ai.cjs');
const root=path.join(__dirname,'dist');
const positive=(value,fallback)=>{const n=Number(value);return Number.isInteger(n)&&n>0?n:fallback;};
function configFromEnv(env=process.env){
  const provider=env.AI_PROVIDER||'gemini';
  if(!['gemini','openai'].includes(provider))throw new Error('Unsupported AI_PROVIDER');
  return {provider,javascriptKey:env.KAKAO_JAVASCRIPT_KEY||'',restKey:env.KAKAO_REST_API_KEY||'',apiKey:(provider==='gemini'?env.GEMINI_API_KEY:env.OPENAI_API_KEY)||'',model:provider==='gemini'?(env.GEMINI_MODEL||'gemini-3.1-flash-lite'):(env.OPENAI_MODEL||'gpt-6-luna'),
    port:positive(env.PORT,8080),host:env.HOST||(env.NODE_ENV==='production'?'0.0.0.0':'127.0.0.1'),production:env.NODE_ENV==='production',
    origin:env.APP_ORIGIN||env.RENDER_EXTERNAL_URL||'',dailyLimit:positive(env.CHAT_DAILY_LIMIT,100),sessionLimit:positive(env.CHAT_SESSION_LIMIT,8),concurrency:positive(env.CHAT_CONCURRENCY,2)};
}
function createApp(config,overrides={}){
  const data=JSON.parse(fs.readFileSync(path.join(root,'data.json'),'utf8'));
  if(data.schemaVersion!==5)throw new Error('Rebuild dashboard data with analysis/build_data.py (schema 5 required).');
  const router=overrides.router||createRouter(config.restKey,data);
  const evaluate=createScenarios(data,router);
  const answer=createAI({apiKey:config.apiKey,model:config.model,provider:config.provider,evaluate,fetchImpl:overrides.fetchImpl});
  const sessions=new Map();let active=0,daily=0,day='';
  const types={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.json':'application/json; charset=utf-8'};
  const files={'/':'index.html','/index.html':'index.html','/about.html':'about.html','/app.js':'app.js','/chat.js':'chat.js','/model.js':'model.js','/style.css':'style.css','/chat.css':'chat.css','/data.json':'data.json'};
  const json=(res,status,value)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(value));};
  const session=(req,res,create=true)=>{
    const now=Date.now();
    for(const [key,value]of sessions)if(now-value.touched>3600000&&!value.busy)sessions.delete(key);
    const match=(req.headers.cookie||'').match(/(?:^|;\s*)goyang_chat=([a-f0-9]{48})(?:;|$)/);
    let current=match&&sessions.get(match[1]);
    if(!current&&create){
      if(sessions.size>=200)throw new ChatError('CHAT_BUSY','현재 이용자가 많습니다. 잠시 후 다시 시도해 주세요.',429);
      const id=crypto.randomBytes(24).toString('hex');current={history:[],busy:false,touched:now};sessions.set(id,current);
      res.setHeader('Set-Cookie',`goyang_chat=${id}; Path=/api/chat; HttpOnly; SameSite=Strict; Max-Age=3600${config.production?'; Secure':''}`);
    }
    if(current)current.touched=now;return current;
  };
  async function readBody(req){
    if(!/^application\/json(?:;|$)/i.test(req.headers['content-type']||''))throw new ChatError('BAD_TYPE','요청 형식을 확인해 주세요.',415);
    if(Number(req.headers['content-length'])>16000)throw new ChatError('BODY_LIMIT','질문이 너무 깁니다.',413);
    let size=0,parts=[];
    for await(const chunk of req){size+=chunk.length;if(size>16000)throw new ChatError('BODY_LIMIT','질문이 너무 깁니다.',413);parts.push(chunk);}
    try{return JSON.parse(Buffer.concat(parts).toString('utf8'));}catch{throw new ChatError('BAD_JSON','요청 형식을 확인해 주세요.',400);}
  }
  function checkOrigin(req){
    const supplied=req.headers.origin;
    let allowed=config.origin;
    if(!allowed&&!config.production&&/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(req.headers.host||''))allowed='http://'+req.headers.host;
    if(!allowed||!supplied||supplied!==allowed.replace(/\/$/,''))throw new ChatError('BAD_ORIGIN','이 대시보드에서 질문을 보내 주세요.',403);
  }
  function checkLimits(current){
    const now=Date.now(),today=new Date().toISOString().slice(0,10);
    if(day!==today){day=today;daily=0;}
    const rate=current.rate?.until>now?current.rate:{count:0,until:now+600000};
    if(daily>=positive(config.dailyLimit,100))throw new ChatError('DAILY_LIMIT','오늘의 AI 문답 이용 한도에 도달했습니다. 지도와 탄소 계산은 계속 사용할 수 있습니다.',429);
    if(rate.count>=positive(config.sessionLimit,8))throw new ChatError('RATE_LIMIT','질문이 잠시 집중되었습니다. 몇 분 후 다시 시도해 주세요.',429);
    if(active>=positive(config.concurrency,2))throw new ChatError('CHAT_BUSY','다른 질문을 처리 중입니다. 잠시 후 다시 시도해 주세요.',429);
    rate.count++;current.rate=rate;daily++;
  }
  const server=http.createServer(async(req,res)=>{
    res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','strict-origin-when-cross-origin');res.setHeader('X-Frame-Options','SAMEORIGIN');
    try{
      const url=new URL(req.url,'http://localhost'),pathname=url.pathname;
      if(pathname==='/healthz'&&req.method==='GET')return json(res,200,{status:'ok'});
      if(pathname==='/api/chat/status'&&req.method==='GET')return json(res,200,{enabled:!!config.apiKey,model:config.model,provider:config.provider});
      if(pathname==='/api/chat'&&req.method==='DELETE'){
        checkOrigin(req);const current=session(req,res,false);if(current?.busy)throw new ChatError('CHAT_BUSY','답변을 중지한 뒤 대화를 지워 주세요.',409);
        if(current)current.history=[];return json(res,200,{ok:true});
      }
      if(pathname==='/api/chat'&&req.method==='POST'){
        checkOrigin(req);
        if(!config.apiKey)throw new ChatError('AI_NOT_CONFIGURED','AI 문답은 연결 준비 중입니다. 키가 등록되면 이용할 수 있습니다.',503);
        const body=await readBody(req);
        if(!body||typeof body.message!=='string'||body.message.trim().length<1||body.message.length>1200)throw new ChatError('INVALID_MESSAGE','질문을 1~1,200자 이내로 입력해 주세요.',400);
        let scenario;try{scenario=validateScenario(body.scenario);}catch(error){throw new ChatError('INVALID_SCENARIO',error.message,400);}
        const current=session(req,res);
        if(current.busy)throw new ChatError('CHAT_BUSY','이전 답변을 기다리거나 중지한 뒤 질문해 주세요.',409);
        checkLimits(current);current.busy=true;active++;
        const controller=new AbortController(),timer=setTimeout(()=>controller.abort(new Error('timeout')),120000);
        const disconnected=()=>{if(!res.writableEnded)controller.abort(new Error('disconnected'));};res.on('close',disconnected);
        res.writeHead(200,{'Content-Type':'text/event-stream; charset=utf-8','Cache-Control':'no-cache, no-transform','X-Accel-Buffering':'no'});res.flushHeaders();
        const emit=(event,payload)=>{if(!res.destroyed&&!res.writableEnded)res.write(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`);};
        const heartbeat=setInterval(()=>{if(!res.destroyed)res.write(': keepalive\n\n');},15000);
        try{
          emit('status',{text:'현재 조건과 자료 근거를 확인하고 있습니다…'});
          const result=await answer({message:body.message.trim(),scenario,history:current.history,signal:controller.signal,emit});
          current.history=result.history;current.touched=Date.now();emit('done',{ok:true});
        }catch(error){
          emit('error',{code:error instanceof ChatError?error.code:controller.signal.aborted?'TIMEOUT':'CHAT_FAILED',message:error instanceof ChatError?error.message:controller.signal.aborted?'응답 시간이 길어 연결을 종료했습니다. 다시 시도해 주세요.':'답변을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.'});
        }finally{clearTimeout(timer);clearInterval(heartbeat);res.off('close',disconnected);current.busy=false;active--;res.end();}
        return;
      }
      if(req.method!=='GET'&&req.method!=='HEAD')return json(res,405,{error:'지원하지 않는 요청입니다.'});
      if(pathname==='/api/distances'){
        const id=url.searchParams.get('destination')||'baek';
        if(!data.places.some(p=>p.id===id))return json(res,400,{error:'지원하지 않는 목적지입니다.'});
        if(!config.restKey&&!overrides.router)return json(res,503,{error:'자동차 경로 연결 준비 중입니다.'});
        try{return json(res,200,await router.get(id));}catch{return json(res,502,{error:'자동차 경로 조회를 완료하지 못했습니다. 잠시 후 다시 조회해 주세요.'});}
      }
      if(pathname==='/api/status')return json(res,200,router.status());
      if(pathname==='/config.js'){
        res.writeHead(200,{'Content-Type':types['.js']});return res.end('window.KAKAO_TEST_CONFIG='+JSON.stringify({javascriptKey:config.javascriptKey})+';');
      }
      const file=files[pathname];if(!file){res.writeHead(404);return res.end('Not found');}
      const content=await fs.promises.readFile(path.join(root,file));res.writeHead(200,{'Content-Type':types[path.extname(file)]});res.end(req.method==='HEAD'?undefined:content);
    }catch(error){if(!res.headersSent)json(res,error instanceof ChatError?error.status:500,{code:error instanceof ChatError?error.code:'SERVER_ERROR',error:error instanceof ChatError?error.message:'요청을 처리하지 못했습니다.'});else res.end();}
  });
  server.requestTimeout=15000;server.headersTimeout=10000;
  return server;
}
async function start(){
  let config=configFromEnv();
  if(process.argv.includes('--stdin-config')){
    console.log('Waiting for configuration on stdin. Keys are not logged.');
    let raw='';for await(const chunk of process.stdin){raw+=chunk;if(raw.includes('\n'))break;}
    try{const local=JSON.parse(raw.trim());config={...config,...local};raw='';}catch{throw new Error('Invalid stdin configuration');}
  }
  for(const [name,key]of [['KAKAO_JAVASCRIPT_KEY',config.javascriptKey],['KAKAO_REST_API_KEY',config.restKey]])if(key&&!/^[a-f0-9]{32}$/i.test(key))throw new Error(name+' format is invalid');
  const server=createApp(config);
  server.on('error',error=>{console.error('Server error:',error.code);process.exitCode=1;});
  server.listen(config.port,config.host,()=>console.log(`Local: http://localhost:${config.port} | AI ${config.apiKey?'enabled':'awaiting key'}`));
  for(const name of ['SIGTERM','SIGINT'])process.on(name,()=>{server.close(()=>process.exit(0));setTimeout(()=>process.exit(0),5000).unref();});
}
if(require.main===module)start().catch(()=>{console.error('Could not start. Check environment variable formats and PORT.');process.exitCode=1;});
module.exports={createApp,configFromEnv};
