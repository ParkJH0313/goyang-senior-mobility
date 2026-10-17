// Optional browser QA: requires Playwright and an installed Chrome. No AI calls.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.env.TEST_BASE_URL||'http://localhost:8080';
const artifact=path.join(__dirname,'../artifacts');fs.mkdirSync(artifact,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  const report={checks:[],errors:[],liveAI:false};
  try{
    const context=await browser.newContext({viewport:{width:1440,height:1050}}),page=await context.newPage();
    page.on('pageerror',error=>report.errors.push(error.message));
    await page.goto(base);await page.waitForFunction(()=>window.dashboard?.mapReady&&window.dashboard.result(),{},{timeout:90000});
    const before=await page.evaluate(()=>fetch('/api/status').then(r=>r.json()));
    await page.locator('#chat-open').click();await page.waitForFunction(()=>document.getElementById('chat-connection').textContent.includes('키 등록'));
    assert.equal(await page.locator('#chat-input').isDisabled(),true);assert.equal(await page.locator('#chat-send').isDisabled(),true);
    await page.locator('#occupancy').fill('3');await page.locator('#occupancy').dispatchEvent('input');
    assert.match(await page.locator('#chat-context').textContent(),/3.0명/);
    await page.locator('[data-tier="t61"]').click();assert.match(await page.locator('#chat-context').textContent(),/61곳/);
    const after=await page.evaluate(()=>fetch('/api/status').then(r=>r.json()));assert.equal(before.requests,after.requests);
    report.checks.push('keyless state is honest; sliders update chat context without any AI/routing calls');
    await page.locator('#reset').click();await page.locator('#fit').click();await page.waitForTimeout(1500);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:path.join(artifact,'ai-panel-desktop.png')});
    const mobile=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true}),mp=await mobile.newPage();
    mp.on('pageerror',error=>report.errors.push(error.message));await mp.goto(base);await mp.waitForFunction(()=>window.dashboard?.mapReady&&window.dashboard.result());
    await mp.locator('#chat-open').click();assert.equal(await mp.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.equal(await mp.locator('.workspace').evaluate(el=>el.inert),true);
    await mp.screenshot({path:path.join(artifact,'ai-panel-mobile.png')});
    await mp.locator('#chat-close').click();assert.equal(await mp.locator('.workspace').evaluate(el=>el.inert),false);assert.equal(await mp.evaluate(()=>document.activeElement.id),'chat-open');
    report.checks.push('desktop/mobile no overflow; mobile focus and background controls restored after close');
    // UI-only response fixture; never enabled by a production environment variable.
    const mock=await browser.newContext({viewport:{width:1440,height:1050}}),qp=await mock.newPage();
    qp.on('pageerror',error=>report.errors.push(error.message));
    await qp.route('**/api/chat/status',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({enabled:true,provider:'gemini',model:'gemini-3.1-flash-lite'})}));
    let sent=null;
    await qp.route('**/api/chat',async route=>{
      if(route.request().method()==='DELETE')return route.fulfill({contentType:'application/json',body:'{"ok":true}'});
      sent=route.request().postDataJSON();
      const calculation=await qp.evaluate(()=>{
        const scenario={...dashboard.state(),occupancy:3},d=dashboard.distances.clinic;
        return {available:true,scenario,stops:{added:36},budget:{vehicles:scenario.vehicles,annualWon:CarbonModel.annualCost(scenario.vehicles,dashboard.data.budget)},access:{withDrt:d.access.tiers[scenario.tier]},destinationTitle:'가까운 내과·정형외과 직결',vehicleTitle:'LPG',result:CarbonModel.calculate({...scenario,population:dashboard.data.totalPopulation,baselineKm:d.roundtripKm,drtKm:d.roundtripKm})};
      });
      const events=[['context',{sources:[{id:'S5',title:'탄소 계산식과 평가 범위',url:'/about.html#formula'}]}],['calculation',{calculation}],['delta',{text:'[테스트용 응답] 3명 조건을 비교했습니다. [S5]\n<img src=x onerror=alert(1)>'}],['done',{ok:true}]];
      return route.fulfill({contentType:'text/event-stream',body:events.map(([event,data])=>`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('')});
    });
    await qp.goto(base);await qp.waitForFunction(()=>window.dashboard?.result());await qp.locator('#chat-open').click();
    await qp.locator('[data-question]').nth(1).click();await qp.locator('.chat-sources a').waitFor();
    assert.equal(sent.scenario.tier,'t36');assert.equal(sent.scenario.occupancy,2.5);
    assert.equal(await qp.locator('.chat-text img').count(),0);assert.equal(await qp.locator('.chat-text a').getAttribute('href'),'/about.html#formula');
    assert.equal(await qp.locator('.chat-result-card').count(),1);
    await qp.locator('[data-tier="t61"]').click();assert.match(await qp.locator('.chat-snapshot').textContent(),/36곳/);assert.match(await qp.locator('#chat-context').textContent(),/61곳/);
    await qp.locator('#chat-clear').click();await qp.waitForFunction(()=>!document.querySelector('#chat-messages').children.length);
    report.checks.push('mock stream, deterministic comparison card, citation link, escaped HTML, frozen question context, clear conversation');
    await qp.unroute('**/api/chat');await qp.route('**/api/chat',route=>route.fulfill({status:429,contentType:'application/json',body:JSON.stringify({code:'RATE_LIMIT',error:'테스트: 잠시 후 다시 시도해 주세요.'})}));
    await qp.locator('[data-question]').first().click();await qp.locator('.chat-error').waitFor();assert.match(await qp.locator('.chat-error').textContent(),/잠시 후/);
    await qp.locator('#chat-input').fill('다시 질문');assert.equal(await qp.locator('#chat-send').isEnabled(),true);
    report.checks.push('rate-limit error remains readable and composer recovers');
    assert.equal(report.errors.length,0);
    fs.writeFileSync(path.join(artifact,'ui-validation.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
