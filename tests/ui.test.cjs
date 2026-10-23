const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const fixtures = require('../preview/fixtures.js');
let server, browser, base;
before(async()=>{
 server=http.createServer((req,res)=>{
  const name=req.url==='/'?'index.html':req.url.slice(1);
  if(!/^[a-z.]+$/.test(name)){res.writeHead(404).end();return;}
  res.setHeader('Content-Type', name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html');
  res.end(fs.readFileSync(path.join(__dirname,'../web',name)));
 }).listen(0,'127.0.0.1');
 await new Promise(r=>server.once('listening',r));base=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launch({headless:true});
});
after(async()=>{await browser?.close();server?.close();});
async function setup(options={}) {
 const page=await browser.newPage({viewport:{width:1920,height:1080}});
 if(options.legacyCss)await page.route('**/style.css',route=>route.fulfill({
  contentType:'text/css',body:fs.readFileSync(path.join(__dirname,'../web/style.css'),'utf8').replace(/font-size:\s*clamp\([^;]+;/g,'')
 }));
 await page.addInitScript(fixtures.install, { ...options, apps: fixtures.catalog('test') });
 if(options.startupUnfocused)await page.addInitScript(()=>{
  window.bootFocused=false;window.bootDiscoveries=0;document.hasFocus=()=>window.bootFocused;
  const discover=tizen.application.getAppsInfo;
  tizen.application.getAppsInfo=(...args)=>{window.bootDiscoveries++;return discover(...args);};
 });
 await page.goto(base);await page.waitForTimeout(80);return page;
}
async function key(page,...keys){for(const k of keys)await page.keyboard.press(k);}
async function focusText(page){return page.locator(':focus').textContent();}
const ids=page=>page.locator('#favorites > button').evaluateAll(bs=>bs.map(b=>b.dataset.id));
test('saved shortcuts and remote focus work before initial catalog discovery; foreground starts it once',async()=>{
 const p=await setup({startupUnfocused:true});
 assert.equal((await ids(p)).length,2);assert.equal(await p.evaluate(()=>bootDiscoveries),0);
 await key(p,'ArrowDown','ArrowRight');assert.equal(await focusText(p),'Samsung Home');
 await p.evaluate(()=>{window.bootFocused=true;window.dispatchEvent(new Event('focus'));});
 await p.waitForFunction(()=>bootDiscoveries===1);await p.waitForTimeout(80);
 assert.equal(await focusText(p),'Samsung Home');
 await p.evaluate(()=>window.dispatchEvent(new Event('focus')));await p.waitForTimeout(30);
 assert.equal(await p.evaluate(()=>bootDiscoveries),1);await p.close();
 const edit=await setup({startupUnfocused:true});
 await edit.locator('#edit-apps').click();await edit.waitForFunction(()=>bootDiscoveries===1);
 await edit.evaluate(()=>{window.bootFocused=true;window.dispatchEvent(new Event('focus'));});await edit.waitForTimeout(80);
 assert.equal(await edit.evaluate(()=>bootDiscoveries),1);await edit.close();
});
test('Home backdrop stays cached while arrows repaint the focused controls',async()=>{
 const p=await setup(),cdp=await p.context().newCDPSession(p);let layers=[];
 cdp.on('LayerTree.layerTreeDidChange',event=>{layers=event.layers||[];});
 await cdp.send('LayerTree.enable');await p.screenshot();
 const {root}=await cdp.send('DOM.getDocument');
 async function layerFor(selector){
  const {nodeId}=await cdp.send('DOM.querySelector',{nodeId:root.nodeId,selector});
  const {node}=await cdp.send('DOM.describeNode',{nodeId});
  return layers.find(layer=>layer.backendNodeId===node.backendNodeId&&layer.drawsContent);
 }
 const backdrop=await layerFor('.ambient'),controls=await layerFor('main');
 assert.ok(backdrop,'Backdrop must have a separate cached surface');
 assert.ok(controls,'Interactive controls must paint separately from the backdrop');
 assert.ok(backdrop.width<=1920&&backdrop.height<=1080,'Decorations must not allocate an oversized surface');
 for(const arrow of ['ArrowRight','ArrowLeft','ArrowDown']){
  await key(p,arrow);await p.screenshot(); // Complete a rendered frame, not just event dispatch.
 }
 const tilesBeforeFooter=await layerFor('main'),footer=await layerFor('.bottom-menu');
 assert.ok(footer,'Footer focus and fading must have a small separate surface');
 assert.ok(footer.height<270,'The footer surface must not cover the app tiles');
 for(const arrow of ['ArrowRight','ArrowLeft']){await key(p,arrow);await p.screenshot();}
 assert.equal((await layerFor('main')).paintCount,tilesBeforeFooter.paintCount,'Footer arrows must not repaint app tiles');
 assert.ok((await layerFor('.bottom-menu')).paintCount>footer.paintCount);
 await key(p,'ArrowUp');await p.screenshot();
 const after=await layerFor('.ambient');
 assert.equal(after.layerId,backdrop.layerId);
 assert.equal(after.paintCount,backdrop.paintCount,'Arrow navigation must reuse the painted backdrop');
 assert.ok((await layerFor('main')).paintCount>controls.paintCount,'The test must exercise actual control painting');
 await p.close();
});
test('older TV CSS keeps readable logos, separated controls and full-screen utility pages',async()=>{
 const p=await setup({legacyCss:true});
 await p.evaluate(()=>document.documentElement.classList.add('no-flex-gap'));
 assert.ok(await p.locator('.plex-word').evaluate(e=>parseFloat(getComputedStyle(e).fontSize))>100);
 const controls=await p.locator('footer > button').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right};}));
 assert.ok(controls[1].left-controls[0].right>30);
 assert.ok(controls[2].left-controls[1].right>30);
 await p.locator('#edit-apps').click();
 assert.deepEqual(await p.locator('#editor').boundingBox(),{x:0,y:0,width:1920,height:1080});
 await key(p,'Escape');await p.locator('#settings').click();
 assert.deepEqual(await p.locator('#settings-dialog').boundingBox(),{x:0,y:0,width:1920,height:1080});
 await key(p,'Escape');assert.equal(await p.locator('#favorites').isVisible(),true);await p.close();
});
test('remote add, order save/cancel, restart persistence, remove, empty Home and fallback',async()=>{
 const p=await setup();const errors=[];p.on('pageerror',e=>errors.push(e.message));
 assert.equal((await ids(p)).length,2);
 await key(p,'ArrowDown','Enter');assert.equal(await focusText(p),'Add apps');
 await key(p,'Enter');await p.waitForTimeout(80);assert.match(await focusText(p),/App 00/);
 await key(p,'Enter');assert.match(await p.locator('#editor-status').textContent(),/added/);
 await key(p,'Escape','Escape');assert.equal((await ids(p)).length,3);
 await key(p,'ArrowUp','ArrowRight','ArrowRight','Enter');assert.deepEqual(await p.evaluate(()=>launches),['Store00001.app0']);
 await key(p,'ArrowDown','ArrowLeft','ArrowLeft','Enter','ArrowDown','ArrowDown','ArrowDown','Enter','Enter','ArrowUp','Escape');
 assert.deepEqual((await p.evaluate(()=>JSON.parse(localStorage.getItem('minimal-hub.shortcuts.v1')).apps)).map(a=>a.id),['kIciSQlYEM.plex','9Ur5IzDKqV.TizenYouTube','Store00001.app0']);
 await key(p,'Enter','Enter','ArrowLeft','ArrowLeft','Enter','Escape');
 assert.equal((await ids(p))[0],'Store00001.app0');await p.reload();await p.waitForTimeout(80);assert.equal((await ids(p))[0],'Store00001.app0');
 await key(p,'ArrowDown','Enter','ArrowDown','Enter','ArrowRight','Enter');assert.match(await p.locator('#editor-status').textContent(),/Undo remove/);
 await key(p,'Escape');assert.equal((await ids(p)).length,2);
 // Remove each remaining shortcut through the actual editor.
 for(let i=0;i<2;i++){await p.locator('#edit-apps').click();await key(p,'ArrowDown','Enter','ArrowRight','Enter','Escape');}
 assert.equal((await ids(p)).length,0);assert.equal(await p.locator('#empty-home').isVisible(),true);
 await p.reload();await p.waitForTimeout(80);assert.equal((await ids(p)).length,0);
 // Empty Home offers Add apps first; Back returns to the hub and Samsung Home stays reachable.
 assert.equal(await p.locator(':focus').getAttribute('id'),'empty-add');
 await key(p,'Enter');await p.waitForTimeout(80);assert.equal(await p.locator('#editor-title').textContent(),'Add apps');
 await key(p,'Escape','Escape');assert.equal(await p.locator(':focus').getAttribute('id'),'edit-apps');
 await key(p,'ArrowRight','Enter');assert.equal((await p.evaluate(()=>launches)).at(-1),'com.samsung.tv.csfs');
 assert.deepEqual(errors,[]);await p.close();
});
test('picker scroll, unavailable app, icon fallback, launch/storage/discovery failure and focus trap',async()=>{
 const p=await setup();
 await p.locator('#edit-apps').click();await key(p,'Enter');await p.waitForTimeout(80);
 for(let i=0;i<12;i++)await key(p,'ArrowDown');
 assert.ok(await p.locator('#editor-list').evaluate(e=>e.scrollTop)>0);
 const rect=await p.locator(':focus').boundingBox();assert.ok(rect.y>=0&&rect.y+rect.height<=1080);
 await key(p,'Escape','Escape');
 await p.evaluate(()=>{window.testApps=[];window.launchFail=true;});
 await p.locator('#edit-apps').click();await p.waitForTimeout(80);await key(p,'Escape','ArrowUp','Enter');
 assert.match(await p.locator('#launch-error-title').textContent(),/Could not open/);assert.equal(await p.locator('.unavailable').count(),2);await key(p,'Escape');
 await p.locator('#edit-apps').click();await key(p,'ArrowDown','Enter','ArrowRight');
 await p.evaluate(()=>Storage.prototype.setItem=function(){throw Error('QuotaExceeded');});await key(p,'Enter');
 assert.match(await p.locator('#editor-status').textContent(),/Could not save/);await key(p,'Escape','Escape');assert.equal((await ids(p)).length,2);
 await key(p,'Escape','Escape');assert.equal(await p.locator('#favorites').isVisible(),true);assert.deepEqual(await p.evaluate(()=>launches),['kIciSQlYEM.plex']);
 await p.close();
 const denied=await setup({discoveryFail:true});await denied.locator('#edit-apps').click();await key(denied,'Enter');await denied.waitForTimeout(80);assert.match(await denied.locator('#editor-status').textContent(),/Could not list/);assert.equal(await denied.locator('#editor-list button').count(),0);await denied.close();
});
test('large saved grid scrolls with arrows; broken icon keeps initials; fallback stays reachable',async()=>{
 const p=await setup();
 await p.evaluate(()=>localStorage.setItem('minimal-hub.shortcuts.v1',JSON.stringify({version:1,apps:window.testApps.slice(2)})));
 await p.reload();await p.waitForTimeout(80);
 await p.evaluate(()=>{window.testApps[2].iconPath='/missing-app-icon.png';});
 await p.locator('#edit-apps').click();await p.waitForTimeout(80);await key(p,'Escape');
 const first=p.locator('#favorites > button').first();await first.locator('img').waitFor({state:'detached'});assert.equal(await first.locator('img').count(),0);assert.match(await first.textContent(),/App 00/);
 await key(p,'ArrowUp','ArrowUp','ArrowUp','ArrowUp','ArrowDown','ArrowDown','ArrowDown');
 assert.ok(await p.locator('#favorites').evaluate(e=>e.scrollTop)>0);
 const r=await p.locator(':focus').boundingBox();assert.ok(r.y>=0&&r.y+r.height<1080);
 await key(p,'ArrowDown','ArrowRight');assert.match(await focusText(p),/Samsung Home/);
 const home=await p.locator(':focus').boundingBox();assert.ok(home.y+home.height<1080);
 await p.close();
});
test('late discovery preserves toolbar focus',async()=>{
 const p=await setup();
 await p.evaluate(()=>{const get=tizen.application.getAppsInfo;tizen.application.getAppsInfo=(ok,fail)=>setTimeout(()=>get(ok,fail),250);});
 await key(p,'ArrowDown','Enter','ArrowRight');
 assert.equal(await focusText(p),'Done');await p.waitForTimeout(350);assert.equal(await focusText(p),'Done');await p.close();
});
test('gear settings persist sound/layout, navigate four columns, confirm reset, and trap focus',async()=>{
 const p=await setup();
 await p.evaluate(()=>localStorage.setItem('minimal-hub.shortcuts.v1',JSON.stringify({version:1,apps:window.testApps.slice(2)})));
 await p.reload();await p.waitForTimeout(80);await p.locator('#settings').click();
 assert.equal(await p.locator(':focus').getAttribute('id'),'setting-sound');
 await key(p,'Enter','ArrowDown','Enter');assert.equal(await p.locator('#sound-value').textContent(),'Off');assert.equal(await p.locator('#layout-value').textContent(),'Compact');
 await key(p,'ArrowDown','ArrowDown','ArrowDown','ArrowDown','ArrowDown','Enter');assert.equal(await p.locator(':focus').getAttribute('id'),'reset-cancel');
 await key(p,'Tab');assert.equal(await p.locator(':focus').getAttribute('id'),'reset-confirm');await key(p,'Tab');assert.equal(await p.locator(':focus').getAttribute('id'),'reset-cancel');
 await key(p,'Escape','Escape');assert.equal((await ids(p)).length,12);assert.equal(await p.locator('.apps.compact').count(),1);
 await p.reload();await p.waitForTimeout(80);await key(p,'ArrowDown');assert.equal(await p.locator(':focus').getAttribute('data-id'),'Store00001.app4');
 await p.locator('#settings').click();assert.equal(await p.locator('#sound-value').textContent(),'Off');assert.equal(await p.locator('#layout-value').textContent(),'Compact');
 await key(p,'ArrowDown','ArrowDown','ArrowDown','ArrowDown','ArrowDown','ArrowDown','Enter','ArrowRight','Enter');assert.match(await p.locator('#settings-status').textContent(),/restored/);
 await key(p,'Escape');assert.deepEqual(await ids(p),['kIciSQlYEM.plex','9Ur5IzDKqV.TizenYouTube']);
 assert.equal(await p.evaluate(()=>localStorage.getItem('minimal-hub.sound.v1')),'off');assert.equal(await p.evaluate(()=>localStorage.getItem('minimal-hub.layout.v1')),'compact');await p.close();
});
test('settings failed saves preserve preferences and shortcuts; repeated Back stays in hub',async()=>{
 const p=await setup();await p.locator('#settings').click();
 await p.evaluate(()=>Storage.prototype.setItem=function(){throw Error('QuotaExceeded');});
 await key(p,'Enter');assert.match(await p.locator('#settings-status').textContent(),/Could not save/);assert.equal(await p.locator('#sound-value').textContent(),'On');
 await key(p,'ArrowDown','Enter');assert.match(await p.locator('#settings-status').textContent(),/Could not save/);assert.equal(await p.locator('#layout-value').textContent(),'Comfortable');
 await key(p,'ArrowDown','Enter');assert.equal(await p.locator('#fade-value').textContent(),'Auto-dim');assert.match(await p.locator('#settings-status').textContent(),/Could not save/);
 await key(p,'ArrowDown','Enter');assert.equal(await p.locator('#clock-value').textContent(),'Off');assert.match(await p.locator('#settings-status').textContent(),/Could not save/);
 await key(p,'ArrowDown','Enter');assert.equal(await p.locator('#start-value').textContent(),'Last selected');assert.match(await p.locator('#settings-status').textContent(),/Could not save/);
 await key(p,'ArrowDown','ArrowDown','Enter','ArrowRight','Enter');assert.match(await p.locator('#settings-status').textContent(),/previous list is unchanged/);
 await key(p,'Escape','Escape','Escape');assert.equal(await p.locator('#settings-dialog').isVisible(),false);assert.deepEqual(await p.evaluate(()=>launches),[]);
 const consumed=await p.evaluate(()=>[false,true,false].map(repeat=>{const e=new KeyboardEvent('keydown',{key:'Back',keyCode:10009,repeat,bubbles:true,cancelable:true});document.dispatchEvent(e);return e.defaultPrevented;}));assert.deepEqual(consumed,[true,true,true]);
 assert.deepEqual(await p.evaluate(()=>launches),[]);await p.locator('[data-app="home"]').click();assert.deepEqual(await p.evaluate(()=>launches),['com.samsung.tv.csfs']);await p.close();
});
test('editor artwork follows focus and moving retains tile artwork; settings preview follows values',async()=>{
 const p=await setup();await p.locator('#edit-apps').click();await key(p,'ArrowDown','ArrowDown');
 assert.equal(await p.locator('#preview-name').textContent(),'YouTube');assert.equal(await p.locator('#preview-art .youtube-logo').count(),1);
 await key(p,'Enter','Enter','ArrowLeft');
 assert.equal(await p.locator(':focus').getAttribute('data-id'),'9Ur5IzDKqV.TizenYouTube');assert.equal(await p.locator('#move-position').textContent(),'Position 1 of 2');assert.equal(await p.locator(':focus .youtube-logo').count(),1);
 await key(p,'Escape','Escape');await p.locator('#settings').click();await key(p,'ArrowDown');assert.equal(await p.locator('#setting-visual > span').count(),6);
 await key(p,'Enter');assert.equal(await p.locator('#setting-visual > span').count(),8);await key(p,'ArrowUp','Enter');assert.equal(await p.locator('#setting-visual.quiet').count(),1);await p.close();
});

test('idle menu dims without moving focus, restores on first key, and stays visible for controls and errors',async()=>{
 const p=await setup();await p.clock.install();
 await key(p,'ArrowRight');await p.clock.fastForward(8500);assert.equal(await p.locator('.bottom-menu.idle').count(),1);
 await key(p,'ArrowLeft');assert.equal(await p.locator('.bottom-menu.idle').count(),0);assert.equal(await p.locator(':focus').getAttribute('data-id'),'kIciSQlYEM.plex');
 await key(p,'ArrowDown');await p.clock.fastForward(10000);assert.equal(await p.locator('.bottom-menu.idle').count(),0);
 await key(p,'ArrowUp');await p.evaluate(()=>window.launchFail=true);await key(p,'Enter');await p.clock.fastForward(10000);assert.equal(await p.locator('.bottom-menu.idle').count(),0);await p.close();
});
test('clock cycles off/12/24, idle preference persists, and minute display refreshes',async()=>{
 const p=await setup();await p.clock.install({time:new Date(2026,8,20,13,8,0)});
 await p.locator('#settings').click();await key(p,'ArrowDown','ArrowDown','Enter');assert.equal(await p.locator('#fade-value').textContent(),'Always visible');
 await key(p,'ArrowDown','Enter');assert.equal(await p.locator('#clock-value').textContent(),'12-hour');await key(p,'Escape');assert.equal(await p.locator('#home-clock').textContent(),'1:08 PM');
 await p.clock.fastForward(61000);assert.equal(await p.locator('#home-clock').textContent(),'1:09 PM');
 await p.locator('#settings').click();await key(p,'ArrowDown','ArrowDown','ArrowDown','Enter');assert.equal(await p.locator('#clock-value').textContent(),'24-hour');await key(p,'Escape');assert.equal(await p.locator('#home-clock').textContent(),'13:09');
 await p.reload();await p.waitForTimeout(80);assert.equal(await p.locator('#home-clock').isVisible(),true);await p.clock.fastForward(10000);assert.equal(await p.locator('.bottom-menu.idle').count(),0);
 await p.locator('#settings').click();await key(p,'ArrowDown','ArrowDown','ArrowDown','Enter','Escape');assert.equal(await p.locator('#home-clock').isVisible(),false);await p.close();
});

test('launch expands selected tile and moves neighbors without delaying launch; failure/reduced motion recover',async()=>{
 const p=await setup();await p.clock.install();await key(p,'Enter');assert.deepEqual(await p.evaluate(()=>launches),['kIciSQlYEM.plex']);
 assert.equal(await p.locator('.launch-selected').count(),1);assert.match(await p.locator('#favorites > button').first().getAttribute('style'),/scale\(1\.12\)/);
 assert.match(await p.locator('#favorites > button').nth(1).getAttribute('style'),/translateX/);
 await p.clock.runFor(1200);assert.equal(await p.locator('.launch-motion').count(),0);await key(p,'Escape');
 await p.evaluate(()=>window.launchFail=true);await key(p,'Enter');assert.equal(await p.locator('.launch-motion').count(),0);assert.match(await p.locator('#launch-error-title').textContent(),/Could not open/);
 await p.evaluate(()=>window.launchFail=false);await p.emulateMedia({reducedMotion:'reduce'});await key(p,'Escape','ArrowRight','Enter');assert.equal(await p.locator('.launch-motion').count(),0);assert.equal((await p.evaluate(()=>launches)).at(-1),'9Ur5IzDKqV.TizenYouTube');await p.close();
});

test('monitoring config edits endpoint, persists, cancels, and preserves text input keys',async()=>{
 const p=await setup();
 await p.locator('#settings').click();await p.locator('#setting-telemetry').click();
 await p.locator('#telemetry-enabled').click();await p.locator('#telemetry-endpoint').fill('https://nas.local:20490/v1/s90d');
 const consumed=await p.locator('#telemetry-endpoint').evaluate(e=>{const event=new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true,cancelable:true});e.dispatchEvent(event);return event.defaultPrevented;});assert.equal(consumed,false);
 await p.locator('#telemetry-save').click();assert.match(await p.locator('#settings-status').textContent(),/saved/);
 assert.deepEqual(await p.evaluate(()=>JSON.parse(localStorage.getItem('hub-preview.telemetry'))),{schema:1,enabled:true,endpoint:'https://nas.local:20490/v1/s90d'});
 await p.locator('#setting-telemetry').click();await p.locator('#telemetry-endpoint').fill('http://unsafe/v1/s90d');await p.locator('#telemetry-save').click();assert.match(await p.locator('#telemetry-status').textContent(),/HTTPS/);
 await key(p,'Escape');assert.equal(await p.locator('#telemetry-dialog').isVisible(),false);
 assert.equal(await p.evaluate(()=>JSON.parse(localStorage.getItem('hub-preview.telemetry')).endpoint),'https://nas.local:20490/v1/s90d');await p.close();
});
test('scrolled tiles keep the focus-ring gutter and normal opacity; late discovery keeps the added confirmation; options list uses up/down',async()=>{
 const p=await setup({discoveryDelay:200});
 await p.evaluate(()=>localStorage.setItem('minimal-hub.shortcuts.v1',JSON.stringify({version:1,apps:window.testApps.slice(2,13)})));
 await p.reload();await p.waitForTimeout(300);await key(p,'ArrowDown','ArrowDown','ArrowDown');
 // Edge markers update in the browser's asynchronous scroll event.
 await p.waitForFunction(()=>document.getElementById('home-scroll').classList.contains('can-scroll-up'));
 const room=await p.evaluate(()=>document.getElementById('favorites').getBoundingClientRect().bottom-document.activeElement.getBoundingClientRect().bottom);
 assert.ok(room>=10,`focus ring gutter was ${room}px`);assert.equal(await p.locator('#home-scroll.can-scroll-up').count(),1);
 assert.ok(await p.locator('#favorites > button').evaluateAll(bs=>bs.every(b=>getComputedStyle(b).opacity==='1')));
 await p.locator('#edit-apps').click();await key(p,'Enter');for(let i=0;i<11;i++)await key(p,'ArrowDown');assert.match(await focusText(p),/App 11/);
 await key(p,'Enter');await p.waitForTimeout(300);assert.match(await p.locator('#editor-status').textContent(),/App 11 added/);assert.match(await focusText(p),/App 11/);
 await key(p,'Escape','ArrowDown','Enter','ArrowDown');assert.match(await focusText(p),/Remove from Home/);
 await key(p,'ArrowDown','Enter');assert.equal(await p.locator('#editor').getAttribute('data-mode'),'edit');await p.close();
});

test('selection survives immediate reload; first-favorite preference, removed selection and empty Home have predictable focus',async()=>{
 const p=await setup();
 await key(p,'ArrowRight');await p.reload();await p.waitForTimeout(80);
 assert.equal(await p.locator(':focus').getAttribute('data-id'),'9Ur5IzDKqV.TizenYouTube');
 assert.deepEqual(await ids(p),['kIciSQlYEM.plex','9Ur5IzDKqV.TizenYouTube']);
 await p.locator('#settings').click();await p.locator('#setting-start').click();
 assert.equal(await p.locator('#start-value').textContent(),'First favorite');
 await key(p,'Escape');await p.reload();await p.waitForTimeout(80);
 assert.equal(await p.locator(':focus').getAttribute('data-id'),'kIciSQlYEM.plex');
 // Starting on the first favorite does not change focus restoration on app return.
 await key(p,'ArrowRight');await p.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));await p.waitForTimeout(80);
 assert.equal(await p.locator(':focus').getAttribute('data-id'),'9Ur5IzDKqV.TizenYouTube');
 await p.locator('#settings').click();await p.locator('#setting-start').click();await key(p,'Escape');
 await p.evaluate(()=>localStorage.setItem('minimal-hub.shortcuts.v1',JSON.stringify({version:1,apps:window.testApps.slice(0,1)})));
 await p.reload();await p.waitForTimeout(80);assert.equal(await p.locator(':focus').getAttribute('data-id'),'kIciSQlYEM.plex');
 await p.evaluate(()=>localStorage.setItem('minimal-hub.shortcuts.v1',JSON.stringify({version:1,apps:[]})));
 await p.reload();await p.waitForTimeout(80);assert.equal(await p.locator(':focus').getAttribute('id'),'empty-add');
 assert.equal(await p.locator('#home-scroll').isVisible(),false);await p.close();
});

test('selection save failures keep remote navigation usable and late Home discovery preserves footer focus',async()=>{
 const p=await setup({discoveryDelay:500});
 await key(p,'ArrowDown','ArrowRight');await p.waitForTimeout(600);
 assert.equal(await focusText(p),'Samsung Home');
 await p.evaluate(()=>{Storage.prototype.setItem=function(){throw Error('QuotaExceeded');};});
 await key(p,'ArrowUp');await p.waitForTimeout(300);
 assert.equal(await p.locator(':focus').getAttribute('data-id'),'9Ur5IzDKqV.TizenYouTube');
 assert.match(await p.locator('#status').textContent(),/Could not remember/);
 await key(p,'Enter');assert.equal((await p.evaluate(()=>launches)).at(-1),'9Ur5IzDKqV.TizenYouTube');await p.close();
});

test('launch errors offer remote retry and Samsung Home, trap focus and restore the failed tile on Back',async()=>{
 const p=await setup({launchFail:true,discoveryDelay:300});
 await key(p,'ArrowRight','Enter');await p.waitForTimeout(350);
 assert.equal(await p.locator('#launch-error-title').textContent(),'Could not open YouTube');
 assert.equal(await p.locator(':focus').getAttribute('id'),'launch-cancel');
 assert.equal(await p.locator('#status').textContent(),'');
 await key(p,'Tab','Tab','Tab');assert.equal(await p.locator(':focus').getAttribute('id'),'launch-cancel');
 await key(p,'Escape');assert.equal(await p.locator(':focus').getAttribute('data-id'),'9Ur5IzDKqV.TizenYouTube');
 await key(p,'Enter','ArrowRight');await p.evaluate(()=>window.launchFail=false);await key(p,'Enter');
 assert.equal(await p.locator('#launch-error-dialog').isVisible(),false);
 assert.deepEqual(await p.evaluate(()=>launches),['9Ur5IzDKqV.TizenYouTube','9Ur5IzDKqV.TizenYouTube','9Ur5IzDKqV.TizenYouTube']);
 await key(p,'Escape');await p.evaluate(()=>window.launchFail=true);await key(p,'Enter','ArrowRight','ArrowRight','Enter');
 assert.equal(await p.locator('#launch-error-title').textContent(),'Could not open Samsung Home');
 assert.equal(await p.locator('#launch-home').isVisible(),false);
 await key(p,'Tab','Tab');assert.equal(await p.locator(':focus').getAttribute('id'),'launch-cancel');
 await key(p,'Escape');assert.equal(await focusText(p),'Samsung Home');await p.close();
});

test('launch timeout can retry; late callbacks and abandoned launches cannot interrupt another screen',async()=>{
 const p=await setup();await p.clock.install();
 await p.evaluate(()=>{window.pending=[];tizen.application.launch=(id,ok,fail)=>{launches.push(id);pending.push({ok,fail});};});
 await key(p,'Enter','Enter');assert.equal((await p.evaluate(()=>launches)).length,1);
 await p.clock.fastForward(10001);assert.match(await p.locator('#launch-error-detail').textContent(),/did not respond/);
 await key(p,'ArrowRight','Enter');assert.equal((await p.evaluate(()=>launches)).length,2);
 await p.evaluate(()=>pending[0].fail({name:'LateError'}));assert.equal(await p.locator('#launch-error-dialog').isVisible(),false);
 await p.evaluate(()=>pending[1].ok());assert.match(await p.locator('#status').textContent(),/Opening/);
 await key(p,'Escape','Enter');await p.locator('#settings').click();
 await p.evaluate(()=>pending[2].fail({name:'LateError'}));await p.clock.fastForward(11000);
 assert.equal(await p.locator('#settings-dialog').isVisible(),true);assert.equal(await p.locator('#launch-error-dialog').isVisible(),false);
 await key(p,'Escape');assert.equal(await p.locator('#status').textContent(),'');await p.close();
});

test('scroll cues follow Home and list boundaries at both viewport sizes without dimming apps',async()=>{
 for(const viewport of [{width:1920,height:1080},{width:960,height:540}]){
  const p=await setup();await p.setViewportSize(viewport);
  await p.evaluate(()=>localStorage.setItem('minimal-hub.shortcuts.v1',JSON.stringify({version:1,apps:window.testApps})));
  await p.reload();await p.locator('#home-scroll.can-scroll-down:not(.can-scroll-up)').waitFor({state:'attached',timeout:3000});
  assert.equal(await p.locator('#home-scroll.can-scroll-down').count(),1);assert.equal(await p.locator('#home-scroll.can-scroll-up').count(),0);
  for(let i=0;i<4;i++)await key(p,'ArrowDown');await p.locator('#home-scroll.can-scroll-up:not(.can-scroll-down)').waitFor({state:'attached',timeout:3000});
  assert.equal(await p.locator('#home-scroll.can-scroll-up').count(),1);assert.equal(await p.locator('#home-scroll.can-scroll-down').count(),0);
  assert.ok(await p.locator('#favorites > button').evaluateAll(bs=>bs.every(b=>getComputedStyle(b).opacity==='1')));
  await p.locator('#edit-apps').click();await p.locator('#editor-scroll.can-scroll-down').waitFor({state:'attached',timeout:3000});assert.equal(await p.locator('#editor-scroll.can-scroll-down').count(),1);
  for(let i=0;i<14;i++)await key(p,'ArrowDown');await p.locator('#editor-scroll.can-scroll-up:not(.can-scroll-down)').waitFor({state:'attached',timeout:3000});
  assert.equal(await p.locator('#editor-scroll.can-scroll-up').count(),1);assert.equal(await p.locator('#editor-scroll.can-scroll-down').count(),0);
  await key(p,'Escape');await p.locator('#settings').click();
  for(let i=0;i<6;i++)await key(p,'ArrowDown');
  const box=await p.locator(':focus').boundingBox();assert.ok(box.y>=0&&box.y+box.height<viewport.height);
  await p.close();
 }
});

test('return reuses unchanged tiles, defers discovery, and refreshes changed app data without stealing focus',async()=>{
 const p=await setup();await p.clock.install();
 await p.evaluate(()=>{
  window.originalTiles=Array.from(document.querySelector('#favorites').children);window.discoveries=0;
  const discover=tizen.application.getAppsInfo;tizen.application.getAppsInfo=(...args)=>{discoveries++;discover(...args);};
  document.dispatchEvent(new Event('visibilitychange'));
 });
 assert.equal(await p.evaluate(()=>discoveries),0);
 assert.equal(await p.evaluate(()=>originalTiles.every((tile,i)=>tile===document.querySelector('#favorites').children[i])),true);
 await key(p,'ArrowDown','ArrowRight');await p.clock.fastForward(200);await p.clock.fastForward(30);
 assert.equal(await p.evaluate(()=>discoveries),1);
 assert.equal(await p.evaluate(()=>originalTiles.every((tile,i)=>tile===document.querySelector('#favorites').children[i])),true);
 assert.equal(await focusText(p),'Samsung Home');
 await p.evaluate(()=>{testApps[1].name='Renamed YouTube';document.dispatchEvent(new Event('visibilitychange'));});
 await key(p,'ArrowDown','ArrowRight');await p.clock.fastForward(200);await p.clock.fastForward(30);
 assert.equal(await p.locator('#favorites button').nth(1).getAttribute('aria-label'),'Open Renamed YouTube');
 assert.equal(await focusText(p),'Samsung Home');await p.close();
});

test('grid move follows rows in both layouts, reuses its tile, cancels, and preserves the draft after a failed save',async()=>{
 for(const columns of [3,4]){
  const p=await setup();
  await p.evaluate(columns=>{localStorage.setItem('minimal-hub.shortcuts.v1',JSON.stringify({version:1,apps:testApps.slice(0,7)}));localStorage.setItem('minimal-hub.layout.v1',columns===4?'compact':'comfortable');},columns);
  await p.reload();await p.waitForTimeout(80);
  const before=await ids(p);
  await p.locator('#edit-apps').click();await key(p,'ArrowDown','Enter','Enter');
  await p.evaluate(()=>window.movedTile=document.activeElement);
  await key(p,'ArrowDown');assert.equal((await ids(p))[columns],before[0]);
  assert.equal(await p.evaluate(()=>movedTile===document.activeElement),true);
  assert.deepEqual(await p.evaluate(()=>JSON.parse(localStorage.getItem('minimal-hub.shortcuts.v1')).apps.map(a=>a.id)),before);
  await key(p,'ArrowRight',columns===3?'ArrowDown':'ArrowRight');assert.equal((await ids(p))[6],before[0]);
  // Bottom-row Down reaches safe Cancel; Up restores the selected tile.
  await key(p,'ArrowDown');assert.equal(await p.locator(':focus').getAttribute('id'),'move-cancel');
  await key(p,'ArrowUp');assert.equal(await p.evaluate(()=>movedTile===document.activeElement),true);
  await key(p,'Escape','Escape');assert.deepEqual(await ids(p),before);
  await p.locator('#edit-apps').click();await key(p,'ArrowDown','Enter','Enter','ArrowRight');
  await p.evaluate(()=>{window.realSet=Storage.prototype.setItem;Storage.prototype.setItem=function(){throw Error('Quota');};});
  await key(p,'Enter');assert.match(await p.locator('#move-status').textContent(),/Could not save/);
  assert.equal(await p.locator('#move-banner').isVisible(),true);
  await p.evaluate(()=>Storage.prototype.setItem=realSet);await key(p,'Enter','Escape');
  assert.equal((await ids(p))[1],before[0]);await p.reload();await p.waitForTimeout(80);assert.equal((await ids(p))[1],before[0]);await p.close();
 }
});

test('undo restores original position, preserves later additions, and survives a failed write',async()=>{
 const p=await setup();const before=await ids(p);
 await p.locator('#edit-apps').click();await key(p,'ArrowDown','ArrowDown','Enter','ArrowDown','Enter');
 await p.locator('#editor-actions button').first().click();await p.waitForTimeout(80);await key(p,'Enter','Escape','Escape');
 await p.evaluate(()=>{window.realSet=Storage.prototype.setItem;Storage.prototype.setItem=function(){throw Error('Quota');};});
 await p.locator('#undo-remove').click();assert.match(await p.locator('#status').textContent(),/Could not save/);assert.equal(await p.locator('#undo-remove').isVisible(),true);
 await p.evaluate(()=>Storage.prototype.setItem=realSet);await key(p,'Enter');
 assert.deepEqual(await ids(p),[...before,'Store00001.app0']);assert.equal(await p.locator('#undo-remove').isVisible(),false);
 assert.equal(await p.locator(':focus').getAttribute('data-id'),before[1]);
 await p.locator('#edit-apps').click();await key(p,'ArrowDown','Enter','ArrowDown','Enter','Escape');
 await p.locator('#settings').click();await p.locator('#setting-reset').click();await key(p,'ArrowRight','Enter','Escape');
 assert.equal(await p.locator('#undo-remove').isVisible(),false);assert.deepEqual(await ids(p),before);await p.close();
});

test('optional hold OK opens actions only after holding, taps launch on release, and interrupted holds cancel',async()=>{
 const p=await setup();await p.clock.install();
 await p.keyboard.down('Enter');assert.equal(await p.evaluate(()=>launches.length),1);await p.keyboard.up('Enter');await key(p,'Escape');
 await p.locator('#settings').click();await p.locator('#setting-hold').click();await key(p,'Escape','ArrowUp');
 await p.keyboard.down('Enter');assert.equal(await p.evaluate(()=>launches.length),1);
 await p.clock.fastForward(100);await p.keyboard.up('Enter');assert.equal(await p.evaluate(()=>launches.length),2);await key(p,'Escape');
 await p.keyboard.down('Enter');await p.clock.fastForward(700);await p.keyboard.down('Enter');await p.keyboard.up('Enter');
 assert.equal(await p.locator('#editor').getAttribute('data-mode'),'options');assert.equal(await p.evaluate(()=>launches.length),2);
 await key(p,'Enter','ArrowLeft','Enter');assert.equal(await p.locator('#editor').isVisible(),false);assert.match(await p.locator('#status').textContent(),/saved/);
 for(const interrupt of ['back','arrow','blur','visibility']){
  await p.keyboard.down('Enter');
  if(interrupt==='back')await key(p,'Escape');
  else if(interrupt==='arrow')await key(p,'ArrowRight');
  else await p.evaluate(type=>type==='blur'?window.dispatchEvent(new Event('blur')):document.dispatchEvent(new Event('visibilitychange')),interrupt);
  await p.clock.fastForward(700);await p.keyboard.up('Enter');assert.equal(await p.locator('#editor').isVisible(),false);assert.equal(await p.evaluate(()=>launches.length),2);
 }
 await p.reload();await p.waitForTimeout(80);await p.locator('#settings').click();assert.equal(await p.locator('#hold-value').textContent(),'On');await p.close();
});

test('accepted launch keeps progress until hidden; duplicate requests and stale callbacks are suppressed',async()=>{
 const p=await setup();await p.clock.install();await p.emulateMedia({reducedMotion:'reduce'});
 await key(p,'Enter','Enter');assert.equal(await p.evaluate(()=>launches.length),1);assert.equal(await p.locator('.launch-label').count(),1);
 assert.equal(await p.locator('#favorites button').first().getAttribute('aria-busy'),'true');
 await p.clock.fastForward(10001);assert.match(await p.locator('#launch-error-detail').textContent(),/accepted the request/);
 await key(p,'Escape','Enter');
 await p.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
 assert.equal(await p.locator('.launch-label').count(),0);
 await p.clock.fastForward(11000);assert.equal(await p.locator('#launch-error-dialog').isVisible(),false);
 await p.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});
 await key(p,'Enter');assert.equal(await p.evaluate(()=>launches.length),3);await key(p,'Escape');assert.equal(await p.locator('.launch-label').count(),0);await p.close();
});

test('Samsung Home overlay can be accepted while Hub stays visible; missing callbacks still time out',async()=>{
 const p=await setup();await p.clock.install();
 await p.locator('[data-app="home"]').click();
 assert.deepEqual(await p.evaluate(()=>launches),['com.samsung.tv.csfs']);
 assert.equal(await p.evaluate(()=>document.hidden),false);
 await p.clock.fastForward(11000);
 assert.equal(await p.locator('#launch-error-dialog').isVisible(),false);
 assert.equal(await p.locator('#status').textContent(),'');
 await p.evaluate(()=>{tizen.application.launch=(id)=>launches.push(id);});
 await key(p,'Enter');assert.equal(await p.evaluate(()=>launches.length),2);
 await p.clock.fastForward(11000);
 assert.equal(await p.locator('#launch-error-title').textContent(),'Could not open Samsung Home');
 await key(p,'Escape');assert.equal(await focusText(p),'Samsung Home');await p.close();
});


test('a second move without arrows has only its own moving tile and badge',async()=>{
 const p=await setup();
 try {
  await p.locator('#edit-apps').click();await key(p,'ArrowDown','Enter','Enter');
  const first=await p.locator('#favorites .moving').getAttribute('data-id');
  await key(p,'Escape','ArrowDown','Enter','Enter');
  assert.equal(await p.locator('#favorites .moving').count(),1);
  assert.equal(await p.locator('#favorites .move-label').count(),1);
  assert.notEqual(await p.locator('#favorites .moving').getAttribute('data-id'),first);
  assert.equal(await p.locator('#favorites .moving').getAttribute('aria-disabled'),null);
  await key(p,'Enter');assert.equal(await p.locator('#move-banner').isVisible(),false);
 } finally {await p.close();}
});

test('a late telemetry save cannot reopen settings after Back',async()=>{
 for(const success of [true,false]) {
  const p=await setup();
  try {
   await p.locator('#settings').click();await p.locator('#setting-telemetry').click();
   await p.waitForFunction(()=>!document.getElementById('telemetry-save').disabled);
   // Hold the real filesystem callback after editing, then navigate away.
   await p.evaluate(()=>{
    const resolve=tizen.filesystem.resolve;
    tizen.filesystem.resolve=function(...args){window.finishTelemetry=()=>resolve.apply(this,args);};
   });
   await p.locator('#telemetry-save').click();await key(p,'Escape','Escape');
   assert.equal(await p.locator('#settings-dialog').isVisible(),false);
   await p.evaluate(success=>{if(!success)Storage.prototype.setItem=function(){throw Error('save failed');};window.finishTelemetry();},success);
   assert.equal(await p.locator('#settings-dialog').isVisible(),false);
   assert.equal(await p.locator('#telemetry-dialog').isVisible(),false);
   assert.equal(await p.locator('#favorites').isVisible(),true);
  } finally {await p.close();}
 }
});

test('a telemetry save from an earlier visit cannot affect a new pending save',async()=>{
 for(const success of [true,false]) {
  const p=await setup();
  try {
   await p.locator('#settings').click();await p.locator('#setting-telemetry').click();
   await p.waitForFunction(()=>!document.getElementById('telemetry-save').disabled);
   await p.evaluate(()=>{
    window.telemetryCallbacks=[];
    window.holdNextTelemetry=()=>{
     const resolve=tizen.filesystem.resolve;
     tizen.filesystem.resolve=function(...args){
      tizen.filesystem.resolve=resolve;
      window.telemetryCallbacks.push(()=>resolve.apply(this,args));
     };
    };
    window.holdNextTelemetry();
   });
   await p.locator('#telemetry-save').click();await key(p,'Escape');
   await p.locator('#setting-telemetry').click();
   await p.waitForFunction(()=>!document.getElementById('telemetry-save').disabled);
   await p.locator('#telemetry-endpoint').fill('https://new.example.invalid/v1/devices/s90d');
   await p.evaluate(()=>window.holdNextTelemetry());await p.locator('#telemetry-save').click();
   const status=await p.locator('#telemetry-status').textContent();
   await p.evaluate(success=>{
    const setItem=Storage.prototype.setItem;
    try {
     if(!success)Storage.prototype.setItem=function(){throw Error('old save failed');};
     window.telemetryCallbacks[0]();
    } finally {Storage.prototype.setItem=setItem;}
   },success);
   assert.equal(await p.locator('#telemetry-dialog').isVisible(),true);
   assert.equal(await p.locator('#telemetry-save').isDisabled(),true);
   assert.equal(await p.locator('#telemetry-status').textContent(),status);
   assert.equal(await p.locator('#telemetry-endpoint').inputValue(),'https://new.example.invalid/v1/devices/s90d');
   await p.evaluate(()=>window.telemetryCallbacks[1]());
   assert.equal(await p.locator('#telemetry-dialog').isVisible(),false);
   assert.equal(await p.locator('#settings-dialog').isVisible(),true);
  } finally {await p.close();}
 }
});
