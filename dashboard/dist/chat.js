(()=>{
  const $=id=>document.getElementById(id);let enabled=false,busy=false,controller=null,settingsReady=false,provider='Gemini';
  const names={clinic:'병원까지 직행',daehwa:'주거지→대화역 거점',seogu:'주거지→일산서구청 거점'},vehicles={electric:'전기',lpg:'LPG',hybrid:'하이브리드'};
  const summary=s=>s.tier==='none'?'똑버스 미도입 · 기존 대중교통·보행 · 집 출발 후 30분 기준\n추가 운영비·도입에 따른 탄소 감축 없음':`${CarbonModel.scenarios[s.tier]} · ${names[s.destination]} · ${s.vehicles}대\n스타리아 11인승 ${vehicles[s.vehicle]} · 전환 ${Math.round(s.conversion*100)}% · 재차 ${s.occupancy.toFixed(1)}명 · 집 출발 기준 · 정류장 대기 1.5분 · 배기관 CO₂`;

  const scroll=()=>{$('chat-scroll').scrollTop=$('chat-scroll').scrollHeight;};
  function controls(){
    $('chat-input').disabled=!enabled;
    $('chat-send').disabled=!enabled||busy||!settingsReady||!$('chat-input').value.trim();
    $('chat-stop').hidden=!busy;$('chat-send').hidden=busy;
    $('chat-clear').disabled=busy||!$('chat-messages').children.length;
    document.querySelectorAll('[data-question]').forEach(b=>b.disabled=!enabled||busy||!settingsReady);
  }
  function refresh(){
    if(window.dashboard){settingsReady=true;$('chat-context').textContent=summary(dashboard.state());controls();}
  }
  function close(){
    document.querySelector('.workspace').inert=false;document.querySelector('.topbar').inert=false;
    $('chat-panel').hidden=true;document.body.classList.remove('ai-open');$('chat-open').setAttribute('aria-expanded','false');$('chat-open').focus();
  }
  function mobileInert(){const modal=!$('chat-panel').hidden&&matchMedia('(max-width:600px)').matches;document.querySelector('.workspace').inert=modal;document.querySelector('.topbar').inert=modal;}
  $('chat-open').addEventListener('click',()=>{
    $('chat-panel').hidden=false;document.body.classList.add('ai-open');$('chat-open').setAttribute('aria-expanded','true');refresh();mobileInert();$('chat-close').focus();
  });
  $('chat-close').addEventListener('click',close);addEventListener('resize',mobileInert);
  document.addEventListener('keydown',e=>{
    if($('chat-panel').hidden)return;
    if(e.key==='Escape'){e.preventDefault();close();}
    if(e.key==='Tab'&&matchMedia('(max-width:600px)').matches){
      const nodes=[...$('chat-panel').querySelectorAll('button:not(:disabled),a,textarea:not(:disabled)')].filter(el=>el.getClientRects().length);
      if(!nodes.length)return;const first=nodes[0],last=nodes.at(-1);
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
    }
  });
  $('chat-input').addEventListener('input',()=>{$('chat-count').textContent=`${$('chat-input').value.length} / 1,200`;controls();});
  $('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('chat-form').requestSubmit();}});
  $('chat-stop').addEventListener('click',()=>controller?.abort());
  const create=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(text!==undefined)el.textContent=text;return el;};
  function renderCitations(el,text,sources){
    const known=new Map(sources.map(s=>[s.id,s]));el.replaceChildren();let last=0;
    for(const match of text.matchAll(/\[(S[1-8])\]/g)){
      el.append(document.createTextNode(text.slice(last,match.index)));
      const source=known.get(match[1]);
      if(source){const a=create('a','',match[0]);a.href=source.url;a.target='_blank';a.rel='noopener';a.title=source.title;el.append(a);}else el.append(document.createTextNode(match[0]));
      last=match.index+match[0].length;
    }
    el.append(document.createTextNode(text.slice(last)));
  }
  function resultCard(value){
    const card=create('div','chat-result-card');
    if(value.scenario.tier==='none'){card.append(create('p','','똑버스 미도입 · 기존 대중교통·보행'),create('strong','',`집 출발 후 30분 ${(value.access.withDrt*100).toFixed(1)}% · 추가 운영비 0원 · 탄소 감축 0`),create('small','','도입 효과가 없다는 의미이며 지역 전체 배출량은 별도입니다.'));return card;}
    card.append(create('p','',`${CarbonModel.scenarios[value.scenario.tier]} · ${value.destinationTitle} · ${value.budget.vehicles}대 · 운영비 ${(value.budget.annualWon/1e8).toFixed(2)}억 원`),create('p','',`${value.vehicleTitle} · 전환 ${Math.round(value.scenario.conversion*100)}% · 재차 ${value.scenario.occupancy.toFixed(1)}명`));
    if(!value.available){card.append(create('p','',value.reason||'경로 확인 후 계산할 수 있습니다.'));return card;}
    card.append(create('p','',`집 안 대기 ${value.access.homeWaitMin.toFixed(1)}분 별도 · 정류장 대기 1.5분 · 배기관 CO₂`));
    const negative=value.result.savingKg<-.000001;card.classList.toggle('negative',negative);
    card.append(create('strong','',`집 출발 후 30분 ${(value.access.withDrt*100).toFixed(1)}% · ${(Math.abs(value.result.savingKg)/1000).toFixed(2)} tCO₂ / 년 ${negative?'증가':'감축'}`),create('small','','같은 계산식으로 산출 · 비교 조건은 화면에 자동 적용되지 않습니다.'));
    return card;
  }
  async function send(message){
    if(!enabled||busy||!settingsReady||!message.trim())return;
    busy=true;controller=new AbortController();const scenario=dashboard.state();
    const turn=create('article','chat-turn'),question=create('p','chat-user',message),label=create('div','chat-answer-label'),snapshot=create('div','chat-snapshot','질문 당시 · '+summary(scenario).replace('\n',' · ')),text=create('div','chat-text'),cards=create('div','chat-calculations'),sourceList=create('div','chat-sources');
    label.append(create('span','gemini-spark','✦'),create('span','',provider+' 정책 도우미'));turn.append(question,label,snapshot,text,cards,sourceList);$('chat-messages').append(turn);$('chat-welcome').hidden=true;
    $('chat-input').value='';$('chat-count').textContent='0 / 1,200';controls();scroll();
    let answer='',sources=[],done=false;
    const progress=create('div','chat-thinking'),spinner=create('span','thinking-spinner','✦'),stage=create('span','thinking-stage',provider+' 생각 중…'),elapsed=create('span','thinking-elapsed','0초');
    progress.setAttribute('role','status');spinner.setAttribute('aria-hidden','true');elapsed.setAttribute('aria-hidden','true');progress.append(spinner,stage,elapsed);turn.append(progress);turn.setAttribute('aria-busy','true');
    const started=Date.now(),ticker=setInterval(()=>{elapsed.textContent=Math.floor((Date.now()-started)/1000)+'초';},1000);scroll();
    const errorMessage=message=>{turn.append(create('div','chat-error',message));scroll();};
    try{
      const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,scenario}),signal:controller.signal});
      if(!response.ok){const body=await response.json();if(body.code==='AI_NOT_CONFIGURED')enabled=false;throw new Error(body.error||'문답 연결에 실패했습니다.');}
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
      const event=block=>{
        const type=block.split('\n').find(x=>x.startsWith('event:'))?.slice(6).trim();
        const raw=block.split('\n').filter(x=>x.startsWith('data:')).map(x=>x.slice(5).trim()).join('\n');if(!raw)return;
        const data=JSON.parse(raw);
        if(type==='status'){stage.textContent=provider+' 생각 중… '+data.text;$('chat-connection').textContent=provider+' 응답 준비 중…';}
        if(type==='context')sources=data.sources;
        if(type==='delta'){stage.textContent=provider+' 답변 작성 중…';answer+=data.text;text.textContent=answer;scroll();}
        if(type==='calculation'){stage.textContent='계산 결과를 설명하고 있습니다…';cards.append(resultCard(data.calculation));scroll();}
        if(type==='done'){done=true;}
        if(type==='error')throw new Error(data.message);
      };
      while(true){const {done:finished,value}=await reader.read();if(finished)break;buffer+=decoder.decode(value,{stream:true});let index;while((index=buffer.indexOf('\n\n'))>=0){event(buffer.slice(0,index));buffer=buffer.slice(index+2);}}
      buffer+=decoder.decode();if(buffer.trim())event(buffer);
      if(!done)throw new Error('답변 연결이 중단되었습니다. 다시 질문해 주세요.');
      renderCitations(text,answer,sources);
      for(const source of sources.filter(s=>answer.includes(`[${s.id}]`))){const a=create('a','',source.title+' ↗');a.href=source.url;a.target='_blank';a.rel='noopener';sourceList.append(a);}
    }catch(error){controller?.abort();errorMessage(error.name==='AbortError'?'답변 생성을 중지했습니다.':error.message);}
    finally{clearInterval(ticker);progress.remove();turn.setAttribute('aria-busy','false');busy=false;controller=null;$('chat-connection').textContent=enabled?'현재 조건과 연구 자료를 바탕으로 답합니다.':'AI 연결 준비 중 · 키 등록 후 이용할 수 있습니다.';controls();scroll();}
  }
  $('chat-form').addEventListener('submit',e=>{e.preventDefault();send($('chat-input').value.trim());});
  document.querySelectorAll('[data-question]').forEach(button=>button.addEventListener('click',()=>send(button.dataset.question)));
  $('chat-clear').addEventListener('click',async()=>{
    if(busy)return;try{const response=await fetch('/api/chat',{method:'DELETE'});if(!response.ok)throw new Error();$('chat-messages').replaceChildren();$('chat-welcome').hidden=false;controls();}catch{$('chat-connection').textContent='대화를 지우지 못했습니다. 잠시 후 다시 시도해 주세요.';}
  });
  addEventListener('scenariochange',refresh);refresh();
  fetch('/api/chat/status').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(value=>{
    provider=value.provider==='openai'?'OpenAI':'Gemini';document.body.dataset.aiProvider=value.provider||'gemini';document.querySelectorAll('[data-provider-name]').forEach(el=>el.textContent=provider);enabled=value.enabled;$('chat-connection').classList.toggle('waiting',!enabled);$('chat-connection').textContent=enabled?'현재 조건과 연구 자료를 바탕으로 답합니다.':'AI 연결 준비 중 · 키 등록 후 이용할 수 있습니다.';if(!enabled)$('chat-input').placeholder='AI 연결 후 질문을 입력할 수 있습니다';controls();
  }).catch(()=>{$('chat-connection').textContent='AI 연결 상태를 확인하지 못했습니다. 페이지를 새로고침해 주세요.';controls();});
})();
