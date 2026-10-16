(()=>{
  const $=id=>document.getElementById(id);let enabled=false,busy=false,controller=null,settingsReady=false;
  const names={hospital:'일산백병원 직결',tanhyeon:'탄현역 환승',kintex:'킨텍스역 환승'},vehicles={lpg:'LPG',hybrid:'하이브리드'};
  const summary=s=>`${{core:'핵심 집중 472명',extended:'추가 포함 496명',all:'전체 포함 902명'}[s.scope]} · ${names[s.destination]}\n${vehicles[s.vehicle]} · 전환 ${Math.round(s.conversion*100)}% · 재차 ${s.occupancy.toFixed(1)}명`;
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
    for(const match of text.matchAll(/\[(S[1-6])\]/g)){
      el.append(document.createTextNode(text.slice(last,match.index)));
      const source=known.get(match[1]);
      if(source){const a=create('a','',match[0]);a.href=source.url;a.target='_blank';a.rel='noopener';a.title=source.title;el.append(a);}else el.append(document.createTextNode(match[0]));
      last=match.index+match[0].length;
    }
    el.append(document.createTextNode(text.slice(last)));
  }
  function resultCard(value){
    const card=create('div','chat-result-card');
    card.append(create('p','',`${value.scopeTitle} · ${value.destinationTitle}`),create('p','',`${value.vehicleTitle} · 전환 ${Math.round(value.scenario.conversion*100)}% · 재차 ${value.scenario.occupancy.toFixed(1)}명`));
    if(!value.available){card.append(create('p','',value.reason||'거리 확인 후 계산할 수 있습니다.'));return card;}
    const negative=value.result.savingKg<-.000001;card.classList.toggle('negative',negative);
    card.append(create('strong','',`${(Math.abs(value.result.savingKg)/1000).toFixed(2)} tCO₂ / 년 ${negative?'증가':'감축'}`),create('small','','같은 계산식으로 산출 · 비교 조건은 화면에 자동 적용되지 않습니다.'));
    return card;
  }
  async function send(message){
    if(!enabled||busy||!settingsReady||!message.trim())return;
    busy=true;controller=new AbortController();const scenario=dashboard.state();
    const turn=create('article','chat-turn'),question=create('p','chat-user',message),label=create('div','chat-answer-label'),snapshot=create('div','chat-snapshot','질문 당시 · '+summary(scenario).replace('\n',' · ')),text=create('div','chat-text'),cards=create('div','chat-calculations'),sourceList=create('div','chat-sources');
    label.append(create('span','','✦'),create('span','','정책 도우미'));turn.append(question,label,snapshot,text,cards,sourceList);$('chat-messages').append(turn);$('chat-welcome').hidden=true;
    $('chat-input').value='';$('chat-count').textContent='0 / 1,200';controls();scroll();
    let answer='',sources=[],done=false;
    const errorMessage=message=>{turn.append(create('div','chat-error',message));scroll();};
    try{
      const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,scenario}),signal:controller.signal});
      if(!response.ok){const body=await response.json();if(body.code==='AI_NOT_CONFIGURED')enabled=false;throw new Error(body.error||'문답 연결에 실패했습니다.');}
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
      const event=block=>{
        const type=block.split('\n').find(x=>x.startsWith('event:'))?.slice(6).trim();
        const raw=block.split('\n').filter(x=>x.startsWith('data:')).map(x=>x.slice(5).trim()).join('\n');if(!raw)return;
        const data=JSON.parse(raw);
        if(type==='status')$('chat-connection').textContent=data.text;
        if(type==='context')sources=data.sources;
        if(type==='delta'){answer+=data.text;text.textContent=answer;scroll();}
        if(type==='calculation'){cards.append(resultCard(data.calculation));scroll();}
        if(type==='done'){done=true;}
        if(type==='error')throw new Error(data.message);
      };
      while(true){const {done:finished,value}=await reader.read();if(finished)break;buffer+=decoder.decode(value,{stream:true});let index;while((index=buffer.indexOf('\n\n'))>=0){event(buffer.slice(0,index));buffer=buffer.slice(index+2);}}
      buffer+=decoder.decode();if(buffer.trim())event(buffer);
      if(!done)throw new Error('답변 연결이 중단되었습니다. 다시 질문해 주세요.');
      renderCitations(text,answer,sources);
      for(const source of sources.filter(s=>answer.includes(`[${s.id}]`))){const a=create('a','',source.title+' ↗');a.href=source.url;a.target='_blank';a.rel='noopener';sourceList.append(a);}
    }catch(error){controller?.abort();errorMessage(error.name==='AbortError'?'답변 생성을 중지했습니다.':error.message);}
    finally{busy=false;controller=null;$('chat-connection').textContent=enabled?'현재 조건과 연구 자료를 바탕으로 답합니다.':'AI 연결 준비 중 · 키 등록 후 이용할 수 있습니다.';controls();scroll();}
  }
  $('chat-form').addEventListener('submit',e=>{e.preventDefault();send($('chat-input').value.trim());});
  document.querySelectorAll('[data-question]').forEach(button=>button.addEventListener('click',()=>send(button.dataset.question)));
  $('chat-clear').addEventListener('click',async()=>{
    if(busy)return;try{const response=await fetch('/api/chat',{method:'DELETE'});if(!response.ok)throw new Error();$('chat-messages').replaceChildren();$('chat-welcome').hidden=false;controls();}catch{$('chat-connection').textContent='대화를 지우지 못했습니다. 잠시 후 다시 시도해 주세요.';}
  });
  addEventListener('scenariochange',refresh);refresh();
  fetch('/api/chat/status').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(value=>{
    enabled=value.enabled;$('chat-connection').classList.toggle('waiting',!enabled);$('chat-connection').textContent=enabled?'현재 조건과 연구 자료를 바탕으로 답합니다.':'AI 연결 준비 중 · 키 등록 후 이용할 수 있습니다.';if(!enabled)$('chat-input').placeholder='AI 연결 후 질문을 입력할 수 있습니다';controls();
  }).catch(()=>{$('chat-connection').textContent='AI 연결 상태를 확인하지 못했습니다. 페이지를 새로고침해 주세요.';controls();});
})();
