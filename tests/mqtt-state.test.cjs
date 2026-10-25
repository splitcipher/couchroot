const test = require('node:test');
const assert = require('node:assert/strict');
const {createMqttState, appInventory, sourceId} = require('../agent/service/mqtt-state');
const {createMqttLifecycle} = require('../agent/service/mqtt-lifecycle');
const row = (id, name) => ({id, name, show:true});
function platform() {
  return {
    tvaudiocontrol:{getVolume:()=>0,isMute:()=>false},
    tvwindow:{getSource:()=>({type:'HDMI',number:2,signal:true}),getVideoResolution:()=>({width:3840,height:2160,frequency:60})},
    application:{getAppInfo:id=>({id,name:'Example foreground'}),getAppsInfo:ok=>ok([row('Abcdef1234.App','Example')])},
    systeminfo:{getPropertyValue:(_,ok)=>ok({connected:[{type:'HDMI',number:2}],disconnected:[{type:'TV',number:1}]})},
  };
}
test('read-only projection uses documented units and never turns codecs into speaker routes', async()=>{
  const p=platform(), observer=createMqttState(p); const result=await observer.sample('example.App');
  assert.deepEqual(result.state,{app_id:'example.App',app_name:'Example foreground',volume:0,muted:false,});
  assert.deepEqual(result.sources,['hdmi2','tv']);
  for(const key of ['input','resolution','refresh_hz','power','screen','audio_output','picture_mode','game_mode','hdr','temp_c','wifi_rssi_dbm']) assert.equal(result.state[key],undefined);
  p.tvwindow.getSource=()=>{throw Error('must not read unqualified visible source');};
  await observer.sample('example.App');
  observer.stop();
});
test('temporary failures clear values; permanent capability errors park support', async()=>{
  const p=platform(), observer=createMqttState(p); await observer.sample('example.App');
  p.tvaudiocontrol.getVolume=()=>{throw Error('temporary');};
  p.tvaudiocontrol.isMute=()=>{throw Object.assign(Error(),{name:'NotSupportedError'});};
  p.tvwindow.getSource=()=>({type:'HDMI',number:2,signal:false});
  const result=await observer.sample('example.App');
  assert.equal(result.state.volume,null);assert.equal(result.supported.volume,true);
  assert.equal(result.state.muted,null);assert.equal(result.supported.muted,undefined);
  assert.equal(result.state.input,undefined);assert.equal(result.state.resolution,undefined);assert.equal(result.state.refresh_hz,undefined);
  observer.stop();
});
test('invalid and absent APIs never establish support or invent signal from unknown status', async()=>{
  const p=platform();p.tvaudiocontrol.getVolume=()=>101;p.tvaudiocontrol.isMute=()=>1;
  p.tvwindow.getSource=()=>({type:'HDMI',number:2,signal:null});
  const result=await createMqttState(p).sample(); assert.deepEqual(result.supported,{});
  const missing=await createMqttState({}).sample();assert.deepEqual(missing.supported,{});
  assert.equal(sourceId({type:'HDMI',number:0}),null);assert.equal(sourceId({type:'MEDIA',number:1}),null);
});
test('inventory refresh is canonical, complete, bounded and does not run each tick', async()=>{
  let now=0,calls=0;const p=platform();let rows=[row('Zbcdef1234.App','Z'),row('Abcdef1234.App','A')];
  p.application.getAppsInfo=ok=>{calls++;ok(rows);};
  const observer=createMqttState(p,()=>now);assert.deepEqual((await observer.sample()).apps.map(x=>x.name),['A','Z']);
  now=29000;await observer.sample();assert.equal(calls,1);
  rows=[];now=30000;assert.deepEqual((await observer.sample()).apps,[]);
  rows=[row('Abcdef1234.App','A')];now=60000;assert.equal((await observer.sample()).apps.length,1);
  p.application.getAppsInfo=(_,fail)=>fail();now=90000;assert.equal((await observer.sample()).apps.length,1);
  assert.throws(()=>appInventory(Array.from({length:65},(_,i)=>row('Abcdef1234.App'+i,'Example'))));
  assert.throws(()=>appInventory([row('Abcdef1234.App','bad\u0000name')]));
  assert.deepEqual(appInventory([row('MiniHub001.Hub','Hub'),row('com.samsung.tv.csfs','Home'),row('internal.service','')]),[]);
  observer.stop();
});
test('hung inventory is bounded, late callbacks cannot mutate snapshots, and stop cancels waits', async()=>{
  let now=0,callback,calls=0;const p=platform();p.application.getAppsInfo=ok=>{calls++;callback=ok;};
  const observer=createMqttState(p,()=>now);const result=await observer.sample();assert.equal(result.apps,null);
  now=30000;await observer.sample();assert.equal(calls,1);
  callback([row('Abcdef1234.App','Late')]);assert.equal(result.apps,null);
  now=60000;const pending=observer.sample();observer.stop();assert.equal(await pending,null);
  assert.equal(await observer.sample(),null);
});
test('state collection requires native admission and rechecks maintenance after async reads', async()=>{
  const p=platform();let status={worker_ready:true,capabilities:['mqtt-bridge-v1']},calls=[],release;
  const agent={status:()=>status,operation:async request=>{calls.push(request);return {state:'started',observe_state:true,foreground_app:'example.App'};}};
  const bridge=createMqttLifecycle(agent,{device:'s90d',firmware:'fixture'},'test',p);
  await bridge.tick();assert.equal(calls[0].observations,undefined);
  p.application.getAppsInfo=ok=>{release=ok;};const next=bridge.tick();status={...status,admission_held:true};release([]);await next;
  assert.equal(calls.length,1);status={...status,admission_held:false};await bridge.tick();
  assert.equal(JSON.parse(calls[1].observations).state.app_name,'Example foreground');
  bridge.stop();await bridge.tick();assert.equal(calls.length,2);
});
test('offline MAIN-window prototype bounds timing values but makes no visibility claim',()=>{
  const {mainWindow}=require('../research/mqtt-state/tvwindow.cjs');const p=platform();
  assert.deepEqual(mainWindow(p.tvwindow),{input:'hdmi2',resolution:'3840x2160',refresh_hz:60});
  p.tvwindow.getSource=()=>({type:'HDMI',number:2,signal:null});assert.equal(mainWindow(p.tvwindow),null);
  p.tvwindow.getSource=()=>({type:'HDMI',number:2,signal:true});
  for(const r of [{width:0,height:2160,frequency:60},{width:3840,height:2160,frequency:60000},{width:3840,height:2160,frequency:'60'}]) {
    p.tvwindow.getVideoResolution=()=>r;assert.equal(mainWindow(p.tvwindow),null);
  }
});
test('maximum app labels and IDs cannot overflow the existing worker OP frame',async()=>{
  const p=platform();p.application.getAppsInfo=ok=>ok(Array.from({length:64},(_,i)=>row('Abcdef1234.'+('a'.repeat(240))+i,'"'.repeat(96))));
  const observer=createMqttState(p);const snapshot=await observer.sample('example.App');
  assert.equal(snapshot.apps,null);
  assert.ok(Buffer.byteLength(JSON.stringify({op:'mqtt.start',observations:JSON.stringify(snapshot),device:'s90d',firmware:'f'.repeat(95),version:'v'.repeat(31)})) < 20000);
  assert.equal(snapshot.state.volume,0);observer.stop();
});

test('replacement worker must admit observation again before any TV API read',async()=>{
  let worker='one', reads=0;
  const p=platform();p.tvaudiocontrol.getVolume=()=>{reads++;return 15;};
  const agent={status:()=>({worker_ready:true,worker_id:worker,capabilities:['mqtt-bridge-v1']}),operation:async()=>({state:'started',observe_state:worker==='one'})};
  const bridge=createMqttLifecycle(agent,{device:'s90d',firmware:'fixture'},'test',p);
  await bridge.tick();await bridge.tick();assert.equal(reads,1);
  worker='two';await bridge.tick();await bridge.tick();assert.equal(reads,1);bridge.stop();
});
