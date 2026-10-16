const {ChatError}=require('./errors.cjs');
const {randomUUID}=require('node:crypto');
// Preserve model parts, thought signatures and call IDs during tool continuation.
function toContents(input){
  const contents=[],calls=new Map(input.filter(x=>x.type==='function_call').map(x=>[x.call_id,x]));
  for(const item of input){
    if(item.type==='gemini_content'){contents.push(item.content);continue;}
    if(item.type==='function_call')continue;
    if(item.type==='function_call_output'){
      const call=calls.get(item.call_id);if(!call)throw new ChatError('AI_FORMAT','비교 결과를 AI에 전달하지 못했습니다.');
      const part={functionResponse:{name:call.name,response:JSON.parse(item.output),...(call.geminiId?{id:call.geminiId}:{})}};
      if(contents.at(-1)?.parts?.some(p=>p.functionResponse))contents.at(-1).parts.push(part);
      else contents.push({role:'user',parts:[part]});continue;
    }
    if(item.role==='user'||item.role==='assistant')contents.push({role:item.role==='assistant'?'model':'user',parts:[{text:item.content}]});
  }
  return contents;
}
function declaration(tool){
  const properties={};
  for(const [name,value]of Object.entries(tool.parameters.properties)){
    const type=(Array.isArray(value.type)?value.type.find(t=>t!=='null'):value.type).toUpperCase();
    properties[name]={type,nullable:true,...(value.enum?{enum:value.enum.filter(x=>x!==null)}:{}),...(value.description?{description:value.description}:{}),...(value.minimum!==undefined?{minimum:value.minimum}:{}),...(value.maximum!==undefined?{maximum:value.maximum}:{})};
  }
  return {name:tool.name,description:tool.description,parameters:{type:'OBJECT',properties}};
}
async function geminiStream({apiKey,payload,signal,emit,fetchImpl=fetch}){
  if(!/^gemini-[a-z0-9.-]+$/.test(payload.model))throw new ChatError('AI_MODEL','AI 모델 설정을 확인해야 합니다.',503);
  const response=await fetchImpl(`https://generativelanguage.googleapis.com/v1beta/models/${payload.model}:streamGenerateContent?alt=sse`,{
    method:'POST',headers:{'x-goog-api-key':apiKey,'Content-Type':'application/json'},signal,
    body:JSON.stringify({systemInstruction:{parts:[{text:payload.instructions}]},contents:toContents(payload.input),
      tools:[{functionDeclarations:payload.tools.map(declaration)}],toolConfig:{functionCallingConfig:{mode:payload.tool_choice==='none'?'NONE':'AUTO'}},
      generationConfig:{maxOutputTokens:2048}})
  });
  if(!response.ok){
    if([400,401,403,404].includes(response.status))throw new ChatError('AI_AUTH','Gemini 키 또는 모델 연결 설정을 확인해야 합니다. 관리자에게 알려 주세요.',503);
    if(response.status===429)throw new ChatError('AI_QUOTA','Gemini 사용 한도 또는 요청 제한에 도달했습니다. 잠시 후 다시 시도해 주세요.',429);
    throw new ChatError('AI_UPSTREAM','Gemini에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.');
  }
  if(!response.body)throw new ChatError('AI_EMPTY','Gemini 응답을 받지 못했습니다.');
  const decoder=new TextDecoder(),parts=[];let buffer='',finish=null;
  const consume=block=>{
    const raw=block.split('\n').filter(x=>x.startsWith('data:')).map(x=>x.slice(5).trimStart()).join('\n');if(!raw||raw==='[DONE]')return;
    let event;try{event=JSON.parse(raw);}catch{throw new ChatError('AI_FORMAT','Gemini 응답 형식을 확인하지 못했습니다.');}
    if(event.error)throw new ChatError('AI_UPSTREAM','Gemini 응답 생성이 중단되었습니다.');
    if(event.promptFeedback?.blockReason)throw new ChatError('AI_BLOCKED','이 질문에는 답변을 생성하지 못했습니다. 정책 시나리오에 관한 질문으로 다시 입력해 주세요.');
    const candidate=event.candidates?.[0];
    for(const part of candidate?.content?.parts||[]){parts.push(part);if(part.text&&!part.thought)emit('delta',{text:part.text});}
    if(candidate?.finishReason)finish=candidate.finishReason;
  };
  for await(const chunk of response.body){
    buffer=(buffer+decoder.decode(chunk,{stream:true})).replace(/\r\n/g,'\n');
    if(buffer.length>2000000)throw new ChatError('AI_FORMAT','AI 응답이 처리 범위를 넘었습니다.');
    let index;while((index=buffer.indexOf('\n\n'))>=0){consume(buffer.slice(0,index));buffer=buffer.slice(index+2);}
  }
  buffer+=decoder.decode();if(buffer.trim())consume(buffer);
  if(finish==='MAX_TOKENS')throw new ChatError('AI_INCOMPLETE','답변이 길어 완료되지 않았습니다. 질문을 나누어 다시 시도해 주세요.');
  if(finish!=='STOP')throw new ChatError('AI_INTERRUPTED','Gemini 답변이 완료되지 않았습니다. 다시 시도해 주세요.');
  const calls=parts.filter(p=>p.functionCall).map(part=>({type:'function_call',name:part.functionCall.name,arguments:JSON.stringify(part.functionCall.args||{}),call_id:part.functionCall.id||randomUUID(),geminiId:part.functionCall.id}));
  return {output:[{type:'gemini_content',content:{role:'model',parts}},...calls]};
}
module.exports={geminiStream,toContents};
