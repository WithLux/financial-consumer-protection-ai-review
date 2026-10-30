// Actual HTTP browser smoke test. Never replaces a missing browser/server with Mock.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir} from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.E2E_BASE_URL||'http://127.0.0.1:8765';
if(!['http:','https:'].includes(new URL(base).protocol))throw new Error('HTTP(S) server required');
const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
try{
 const context=await browser.newContext({acceptDownloads:true,viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 await page.goto(base+'/?mode=real');
 await page.locator('#source').waitFor();
 assert.match(await page.title(),/消保/);
 if(!process.env.E2E_ACCESS_TOKEN)throw new Error('E2E_ACCESS_TOKEN required; do not commit it');
 await page.locator('#login').click();
 await page.locator('#modal-body input').fill(process.env.E2E_ACCESS_TOKEN);
 await page.locator('#save-modal').click();await page.locator('#modal').waitFor({state:'hidden'});
 await page.locator('#file').setInputFiles(path.resolve('data/demo_samples/qa/A-high-risk.txt'));
 await page.locator('#start:not([disabled])').waitFor();
 if(process.env.E2E_USE_AI==='true'){await page.locator('#ai').check();await page.locator('#consent').check();}
 await page.locator('#start').click();
 await page.waitForFunction(()=>document.querySelector('#task-status').textContent==='待复核',null,{timeout:120000});
 if(process.env.E2E_USE_AI==='true'){
  const status=await page.locator('#execution').textContent();
  assert.match(status,/AI：succeeded/,'Live AI must succeed; rule-only is not AI verification');
 }
 await page.locator('.quote').first().click();
 assert.ok(await page.locator('#source mark').count(),'quote highlight missing');
 await page.locator('.expand').first().click();
 assert.ok(await page.locator('.issue-body').count());
 for(const link of await page.locator('.issue-body a').all())assert.ok((await link.getAttribute('href')).startsWith('https:'));
 await page.locator('.issue-actions button').filter({hasText:'驳回'}).first().click();
 await page.locator('#modal-body textarea').fill('虚构材料测试：人工决定不采纳本候选意见');
 await page.locator('#save-modal').click();await page.locator('#modal').waitFor({state:'hidden'});
 assert.match(await page.locator('#decision-counts').textContent(),/驳回 1/);
 await page.locator('#preview').click();assert.ok(await page.locator('.report-preview').count());await page.locator('#cancel-modal').click();
 const downloadEvent=page.waitForEvent('download');await page.locator('#download').click();
 const download=await downloadEvent;await mkdir('runtime/browser-qa',{recursive:true});await download.saveAs('runtime/browser-qa/draft.docx');
 for(const width of [1440,1280]){await page.setViewportSize({width,height:900});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow');await page.screenshot({path:`runtime/browser-qa/width-${width}.png`,fullPage:true});}
 assert.deepEqual(errors,[],'browser console/page errors');
 // A deliberate transport failure must show feedback, never silently return Mock.
 await context.setOffline(true);await page.locator('#refresh').click();await page.locator('#feedback').waitFor();assert.match(await page.locator('#feedback').textContent(),/网络|请求|失败|连接/);
 console.log('HTTP browser smoke passed (TXT, review, quote, reject, preview, draft download, 1440/1280, offline feedback). Remaining final-review cases are covered separately in API tests.');
}finally{await browser.close();}
