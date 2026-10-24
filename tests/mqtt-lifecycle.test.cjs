const test = require('node:test');
const assert = require('node:assert/strict');
const { createMqttLifecycle } = require('../agent/service/mqtt-lifecycle');
test('MQTT lease follows readiness and maintenance fences without exposing credentials', async () => {
  let status = {worker_ready:true,admission_held:false,native_upgrade:null,capabilities:['mqtt-bridge-v1']};
  const calls = [];
  const agent = { status:()=>status, operation:async value=>{calls.push(value);return {state:'started'};} };
  const bridge = createMqttLifecycle(agent,{device:'qn90a',firmware:'fixture'},'test');
  await bridge.tick();
  assert.deepEqual(bridge.status(),{lease_state:'started'});
  assert.deepEqual(calls,[{op:'mqtt.start',device:'qn90a',firmware:'fixture',version:'test'}]);
  for(const patch of [{worker_ready:false},{admission_held:true},{native_upgrade:'pending'},{capabilities:[]}]) {
    const before=status;status={...before,...patch};await bridge.tick();status=before;
  }
  assert.equal(calls.length,1);bridge.stop();await bridge.tick();assert.equal(calls.length,1);
});
test('overlapping ticks serialize and unavailable worker is retried only through readiness', async () => {
  let release, count=0;
  const agent={status:()=>({worker_ready:true,capabilities:['mqtt-bridge-v1']}),
    operation:()=>{count++;return new Promise((_,reject)=>{release=reject;});}};
  const bridge=createMqttLifecycle(agent,{device:'s90d',firmware:'fixture'},'test');
  const first=bridge.tick();await bridge.tick();assert.equal(count,1);
  release(Error('private error'));await first;
  const second=bridge.tick();assert.equal(count,2);release(Error('unavailable'));await second;
});

test('status failures cannot escape the optional timer', async () => {
  const bridge=createMqttLifecycle({status:()=>{throw Error('pending recovery');}}, {}, 'test');
  await assert.doesNotReject(bridge.tick());
});

test('failed API startup clears the optional MQTT timer and stops acquisition', () => {
  const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
  let cleared=0,stopped=0;
  const agent={status:()=>({}),stop:()=>stopped++};
  const modules={
    './policy':{read:()=>Buffer.from('{}'),config:x=>x,Journal:class{},createBootLaunch:()=>({status:()=> 'disabled'})},
    './worker-state':{prepareWorkerState:()=>({})},
    './agent':{createAgent:()=>agent},
    './mqtt-lifecycle':{createMqttLifecycle},
    './api':{createApi:()=>{throw Error('certificate unavailable');}}
  };
  const proc={on:()=>{}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../agent/service/main.js'),'utf8'),{
    require:n=>modules[n],process:proc,console:{error:()=>{}},setInterval:()=>1,clearInterval:()=>cleared++
  });
  assert.equal(cleared,1);assert.equal(stopped,1);assert.equal(proc.exitCode,1);
});
