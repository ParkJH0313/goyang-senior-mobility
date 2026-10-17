const {instructions,sources} = require('./knowledge.cjs');
const {validateScenario,keys} = require('./scenario.cjs');
const {ChatError}=require('./errors.cjs');
const {geminiStream}=require('./gemini.cjs');
const tool = {
  type:'function',name:'calculate_scenario',strict:true,
  description:'가상정류장/연결 방식/차량 대수/차종/전환율/재차인원/대기시간를 바꾸어 같은 계산식으로 30분 도달 비율·연간 운영비·탄소 감축량을 계산한다. 바꾸지 않을 필드는 null. 화면은 변경하지 않는다. 수치 비교 질문에는 이 함수를 사용한다.',
  parameters:{type:'object',additionalProperties:false,required:keys,properties:{
    tier:{type:['string','null'],enum:['none','t0','t21','t36',null],description:'none=똑버스 미도입, t0=기존 정류장에 똑버스 도입, t21/t36=똑버스 도입과 가상 정류장 21/36곳 추가'},
    destination:{type:['string','null'],enum:['clinic','baek','daehwa',null],description:'clinic=출발지별 주변 내과·정형외과 직행, baek=일산백병원 직행, daehwa=대화역 하차 후 일산백병원 연계. 주변 의료기관과 백병원은 목적지 범위와 미도입 기준선이 다름'},
    vehicles:{type:['integer','null'],description:'똑버스 차량 대수 1~3대',minimum:1,maximum:3},
    vehicle:{type:['string','null'],enum:['electric','lpg','hybrid',null]},
    conversion:{type:['number','null'],description:'택시/자가용 통행 전환율 0~1',minimum:0,maximum:1},
    occupancy:{type:['number','null'],description:'평균 재차인원 1~3.2명',minimum:1,maximum:3.2},
    waitBaseMin:{type:['number','null'],minimum:5,maximum:30,description:'2대 기준 가정 대기시간. 지역 실측값이 아님'},
  }}
};
// Production always uses the official endpoint. Tests inject fetch, never a runtime URL.
async function responseStream({apiKey,payload,signal,emit,fetchImpl=fetch}) {
  const response = await fetchImpl('https://api.openai.com/v1/responses',{
    method:'POST',headers:{Authorization:`Bearer ${apiKey}`,'Content-Type':'application/json'},
    body:JSON.stringify({...payload,stream:true}),signal
  });
  if(!response.ok){
    if(response.status===401||response.status===403)throw new ChatError('AI_AUTH','AI 연결 설정을 확인해야 합니다. 관리자에게 알려 주세요.',503);
    if(response.status===429)throw new ChatError('AI_QUOTA','AI 사용 한도 또는 요청 제한에 도달했습니다. 잠시 후 다시 시도해 주세요.',429);
    throw new ChatError('AI_UPSTREAM','AI 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.');
  }
  if(!response.body)throw new ChatError('AI_EMPTY','AI 응답을 받지 못했습니다. 다시 시도해 주세요.');
  const decoder = new TextDecoder(); let buffer='',completed=null;
  const consume = block => {
    const raw = block.split('\n').filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n');
    if(!raw || raw==='[DONE]')return;
    let event;try{event=JSON.parse(raw);}catch{throw new ChatError('AI_FORMAT','AI 응답 형식을 확인하지 못했습니다. 다시 시도해 주세요.');}
    if(event.type==='response.output_text.delta')emit('delta',{text:event.delta});
    if(event.type==='response.refusal.delta')emit('delta',{text:event.delta});
    if(event.type==='response.completed')completed=event.response;
    if(event.type==='response.incomplete')throw new ChatError('AI_INCOMPLETE','답변이 길어 끝까지 생성되지 않았습니다. 질문을 나누어 다시 시도해 주세요.');
    if(event.type==='error'||event.type==='response.failed')throw new ChatError('AI_UPSTREAM','AI 응답 생성이 중단되었습니다. 다시 시도해 주세요.');
  };
  for await(const chunk of response.body){
    buffer=(buffer+decoder.decode(chunk,{stream:true})).replace(/\r\n/g,'\n');
    if(buffer.length>2000000)throw new ChatError('AI_FORMAT','AI 응답이 처리 범위를 넘었습니다.');
    let index;while((index=buffer.indexOf('\n\n'))>=0){consume(buffer.slice(0,index));buffer=buffer.slice(index+2);}
  }
  buffer+=decoder.decode();if(buffer.trim())consume(buffer);
  if(!completed)throw new ChatError('AI_INTERRUPTED','AI 연결이 끊겼습니다. 다시 시도해 주세요.');
  return completed;
}
function createAI({apiKey,model='gpt-6-luna',provider='openai',evaluate,fetchImpl}) {
  return async function answer({message,scenario,history,signal,emit}) {
    const current = await evaluate(scenario);
    signal.throwIfAborted();
    emit('context',{current,sources,askedAt:new Date().toISOString()});
    const user = {role:'user',content:JSON.stringify({question:message,currentScenario:current})};
    const input = [...history,user];let text='',toolCount=0;
    const relay=(type,payload)=>{if(type==='delta')text+=payload.text;emit(type,payload);};
    for(let round=0;round<3;round++) {
      signal.throwIfAborted();
      const result = await (provider==='gemini'?geminiStream:responseStream)({apiKey,signal,fetchImpl,emit:relay,payload:{
        model,instructions,input,store:false,reasoning:{effort:'none'},
        max_output_tokens:1200,tools:[tool],parallel_tool_calls:false,tool_choice:round===2?'none':'auto'
      }});
      const calls=(result.output||[]).filter(x=>x.type==='function_call');
      if(!calls.length){
        if(!text.trim())throw new ChatError('AI_EMPTY','AI가 설명을 반환하지 않았습니다. 질문을 바꾸어 다시 시도해 주세요.');
        return {history:[...history,user,{role:'assistant',content:text.slice(0,6000)}].slice(-8),text};
      }
      if(round===2||toolCount+calls.length>4)throw new ChatError('TOOL_LIMIT','조건 비교가 많습니다. 한두 가지 조건으로 나누어 질문해 주세요.');
      input.push(...result.output);
      for(const call of calls){
        toolCount++;
        let result;
        try{
          if(call.name!==tool.name)throw new Error('Unsupported tool');
          const args=JSON.parse(call.arguments);
          if(!args||typeof args!=='object'||Array.isArray(args)||Object.keys(args).some(k=>!keys.includes(k)))throw new Error('Invalid tool inputs');
          const next=validateScenario({...scenario,...Object.fromEntries(Object.entries(args).filter(([,v])=>v!==null))});
          emit('status',{text:'비교 조건으로 다시 계산하고 있습니다…'});
          result=await evaluate(next);
          signal.throwIfAborted();emit('calculation',{calculation:result});
        }catch(error){
          if(signal.aborted)throw error;
          result={available:false,error:'시나리오 none(미도입)/t0(기존 정류장에 도입)/t21/t36, 연결 방식 clinic(주변 내과·정형외과 직행)/baek(백병원 직행)/daehwa(대화역 경유), 차종 electric/lpg/hybrid, 전환율0~1, 재차인원1~3.2 안에서만 계산할 수 있습니다.'};
        }
        input.push({type:'function_call_output',call_id:call.call_id,output:JSON.stringify(result)});
      }
      if(text)relay('delta',{text:'\n\n'});
      emit('status',{text:'계산 결과를 바탕으로 설명하고 있습니다…'});
    }
    throw new ChatError('AI_INCOMPLETE','답변이 완료되지 않았습니다. 다시 시도해 주세요.');
  };
}
module.exports = {createAI,ChatError,responseStream};
