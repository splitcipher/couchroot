'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('fs'),os=require('os'),path=require('path');
const {hash}=require('../agent/service/policy');
const {loadCandidate,candidateStatus}=require('../agent/service/native-candidate');
const {createAgent}=require('../agent/service/agent');
const names=['native-worker','native-app-launcher'];
function artifact(){const b=Buffer.alloc(64);Buffer.from([127,69,76,70,1,1,1]).copy(b);b.writeUInt16LE(3,16);b.writeUInt16LE(40,18);b.writeUInt32LE(0x05000200,36);return b;}
function fixture(schema=1){
 const names=schema===2?['native-worker','native-app-launcher','native-process-observer']:['native-worker','native-app-launcher'];
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'native-candidate-test-'));
 const source=Object.fromEntries(['native-worker/worker.c','native-worker/build.sh','native-launcher/app-launcher.c','native-launcher/build.sh'].map(n=>[n,'a'.repeat(64)]));
 const m={schema:1,kind:'native-worker-candidate',implementation:'native-prototype',selection:'managed',device_qualified:false,candidate_profiles:['qn90a','s90d'],source,toolchain:{image:'sha256:'+'b'.repeat(64),compiler:'10.2.1'},reproducible_builds:2,artifacts:{},runtime_loads:{json_c:['libjson-c.so.5','libjson-c.so.4'],crypto:['libcrypto.so.1.1','libcrypto.so.3']}};
 m.schema=schema;
 if(schema===2)for(const n of ['native-observer/process-observer.c','native-observer/build.sh'])source[n]='a'.repeat(64);
 for(const name of names){const bytes=artifact();fs.writeFileSync(path.join(dir,name),bytes);m.artifacts[name]={sha256:hash(bytes),size:bytes.length,abi:'armv7-eabi5-softfp',interpreter:'/lib/ld-linux.so.3',needed:['libc.so.6'],glibc_max:'2.17.0'};}
 const seal=()=>{const raw=JSON.stringify(m);fs.writeFileSync(path.join(dir,'native-manifest.json'),raw);fs.writeFileSync(path.join(dir,'manifest.json'),JSON.stringify({'native-manifest.json':hash(raw),...Object.fromEntries(names.map(n=>[n,m.artifacts[n].sha256]))}));};
 seal();return {dir,m,seal,close:()=>fs.rmSync(dir,{recursive:true,force:true})};
}
test('legacy packages have no candidate and require enrollment',()=>{
 const f=fixture();try{
  for(const name of [...names,'native-manifest.json'])fs.unlinkSync(path.join(f.dir,name));
  fs.writeFileSync(path.join(f.dir,'manifest.json'),'{}');
  assert.equal(loadCandidate(f.dir,'qn90a'),null);
  const status=createAgent({device:'qn90a'},{payload:f.dir}).status();
  assert.equal(status.selected_implementation,null);assert.equal(status.native_candidate.state,'absent');assert.equal(status.worker_ready,false);
 }finally{f.close();}
});
test('both profiles validate candidate bytes without promoting readiness or selecting native',()=>{
 const f=fixture();try{
  for(const device of ['qn90a','s90d']){
   const c=loadCandidate(f.dir,device);assert.equal(c.manifest_sha256,hash(fs.readFileSync(path.join(f.dir,'native-manifest.json'))));
   assert.equal(c.artifacts['native-worker'].sha256,f.m.artifacts['native-worker'].sha256);
   const status=createAgent({device},{payload:f.dir}).status();
   assert.equal(status.selected_implementation,null);assert.equal(status.native_candidate.state,'verified');
   assert.equal(status.native_candidate.device_qualified,false);assert.equal(status.worker_ready,false);assert.equal(status.connected,false);
  }
 }finally{f.close();}
});
test('MQTT header provenance is admitted without promoting candidate readiness',()=>{
 for(const schema of [1,2]){
  const f=fixture(schema);try{
   for(const name of ['bridge','commands','config','discovery','fd','foreground','metrics','state','wire'])
    f.m.source['native-worker/mqtt/'+name+'.h']='a'.repeat(64);
   f.seal();
   for(const device of ['qn90a','s90d']){
    assert.ok(loadCandidate(f.dir,device));
    const status=createAgent({device},{payload:f.dir}).status();
    assert.equal(status.native_candidate.state,'verified');
    assert.equal(status.native_candidate.device_qualified,false);
    assert.equal(status.selected_implementation,null);
    assert.equal(status.worker_ready,false);
   }
  }finally{f.close();}
 }
});
test('MQTT provenance rejects unknown paths and malformed digests',()=>{
 const cases=[
  ['native-worker/mqtt/other.h','a'.repeat(64)],
  ['native-worker/mqtt/../worker.c','a'.repeat(64)],
  ['native-worker/mqtt/sub/config.h','a'.repeat(64)],
  ['native-worker/mqtt/config.c','a'.repeat(64)],
  ['native-worker/mqtt/.h','a'.repeat(64)],
  ['native-worker/mqtt/config.h/extra','a'.repeat(64)],
  ['native-worker/mqtt/config.h','not-a-digest'],
 ];
 for(const schema of [1,2])for(const [name,digest] of cases){
  const f=fixture(schema);try{
   f.m.source[name]=digest;f.seal();
   assert.throws(()=>loadCandidate(f.dir,'s90d'),/candidate-source-manifest/);
  }finally{f.close();}
 }
});
test('invalid schema profile build provenance and dependency declarations are rejected',()=>{
 const cases=[m=>m.schema=2,m=>m.selection='native',m=>m.device_qualified=true,m=>m.reproducible_builds=1,
  m=>m.candidate_profiles=['s90d'],m=>m.candidate_profiles=['qn90a','qn90a'],m=>m.toolchain.image='mutable:tag',
  m=>m.toolchain.compiler=['10.2.1'],m=>m.source['../outside']='a'.repeat(64),m=>delete m.source['native-worker/worker.c'],
  m=>m.artifacts['native-worker'].needed=['libc.so.6','libunexpected.so'],m=>m.artifacts['native-worker'].glibc_max='2.29.0',
  m=>m.artifacts['native-app-launcher'].glibc_max='2.28.0',m=>m.artifacts['native-worker'].size=0,
  m=>m.artifacts['native-worker'].interpreter='/lib/other',m=>m.runtime_loads.crypto=['libcrypto.so'],m=>m.unexpected=true];
 for(const change of cases){const f=fixture();try{change(f.m);f.seal();assert.throws(()=>loadCandidate(f.dir,'qn90a'));assert.equal(candidateStatus(f.dir,'qn90a').state,'invalid');}finally{f.close();}}
});
test('digest mismatches missing files symlinks and oversized metadata are not valid candidates',()=>{
 for(const kind of ['binary','manifest','missing','missing-all','symlink','oversized']){
  const f=fixture();try{
   if(kind==='binary')fs.appendFileSync(path.join(f.dir,'native-worker'),'changed');
   if(kind==='manifest')fs.appendFileSync(path.join(f.dir,'native-manifest.json'),' ');
   if(kind==='missing')fs.unlinkSync(path.join(f.dir,'native-app-launcher'));
   if(kind==='missing-all')for(const name of [...names,'native-manifest.json'])fs.unlinkSync(path.join(f.dir,name));
   if(kind==='symlink'){fs.renameSync(path.join(f.dir,'native-worker'),path.join(f.dir,'other'));fs.symlinkSync('other',path.join(f.dir,'native-worker'));}
   if(kind==='oversized')fs.writeFileSync(path.join(f.dir,'native-manifest.json'),' '.repeat(65537));
   assert.throws(()=>loadCandidate(f.dir,'qn90a'));
   const status=createAgent({device:'qn90a'},{payload:f.dir}).status();assert.equal(status.selected_implementation,null);assert.equal(status.native_candidate.state,'invalid');
   assert.ok(!JSON.stringify(status.native_candidate).includes(f.dir));
  }finally{f.close();}
 }
});
test('rehashed wrong-ABI and test-controlled binaries are still rejected',()=>{
 for(const kind of ['machine','hard-float','test']){
  const f=fixture();try{
   let bytes=artifact();if(kind==='machine')bytes.writeUInt16LE(62,18);if(kind==='hard-float')bytes.writeUInt32LE(0x05000400,36);if(kind==='test')bytes=Buffer.concat([bytes,Buffer.from('--test-child-fault')]);
   fs.writeFileSync(path.join(f.dir,'native-worker'),bytes);Object.assign(f.m.artifacts['native-worker'],{sha256:hash(bytes),size:bytes.length});f.seal();
   assert.throws(()=>loadCandidate(f.dir,'qn90a'),/candidate-(artifact-header|test-controls)/);
  }finally{f.close();}
 }
});

test('ordinary source-built candidate is accepted for both profile declarations',{skip:!process.env.NATIVE_CANDIDATE_BUILD},()=>{
 const f=fixture();try{
  const manifest=JSON.parse(fs.readFileSync(path.join(process.env.NATIVE_CANDIDATE_BUILD,'native-manifest.json')));
  const names=Object.keys(manifest.artifacts);
  for(const name of [...names,'native-manifest.json'])fs.copyFileSync(path.join(process.env.NATIVE_CANDIDATE_BUILD,name),path.join(f.dir,name));
  const index=Object.fromEntries([...names,'native-manifest.json'].map(name=>[name,hash(fs.readFileSync(path.join(f.dir,name)))]));fs.writeFileSync(path.join(f.dir,'manifest.json'),JSON.stringify(index));
  for(const device of ['qn90a','s90d'])assert.ok(loadCandidate(f.dir,device));
 }finally{f.close();}
});
test('schema two binds observer bytes and provenance while preserving managed default',()=>{
 const f=fixture(2);try{
  for(const device of ['qn90a','s90d']){
   const c=loadCandidate(f.dir,device);
   assert.equal(c.artifacts['native-process-observer'].sha256,f.m.artifacts['native-process-observer'].sha256);
   assert.equal(createAgent({device},{payload:f.dir}).status().selected_implementation,null);
  }
 }finally{f.close();}
});
test('schema two refuses missing changed incompatible or unbound observers',()=>{
 for(const kind of ['missing','changed','source','glibc','large','downgrade','schema','profile-test']){
  const f=fixture(2);try{
   if(kind==='missing')fs.unlinkSync(path.join(f.dir,'native-process-observer'));
   if(kind==='changed')fs.appendFileSync(path.join(f.dir,'native-process-observer'),'changed');
   if(kind==='source')delete f.m.source['native-observer/process-observer.c'];
   if(kind==='glibc')f.m.artifacts['native-process-observer'].glibc_max='2.28.0';
   if(kind==='large')f.m.artifacts['native-process-observer'].size=128*1024+1;
   if(kind==='downgrade')f.m.schema=1;
   if(kind==='schema')f.m.schema=3;
   if(kind==='profile-test'){const bytes=Buffer.concat([artifact(),Buffer.from('host-test-without-Smack')]);fs.writeFileSync(path.join(f.dir,'native-process-observer'),bytes);Object.assign(f.m.artifacts['native-process-observer'],{sha256:hash(bytes),size:bytes.length});}
   f.seal();assert.throws(()=>loadCandidate(f.dir,'s90d'));
  }finally{f.close();}
 }
 const f=fixture();try{
  fs.writeFileSync(path.join(f.dir,'native-process-observer'),artifact());
  assert.throws(()=>loadCandidate(f.dir,'s90d'),/package-incomplete/);
 }finally{f.close();}
});

test('service-profile source is allowed and required by observers exposing the fixed profile mode',()=>{
 const f=fixture(2);try{
  const name='native-process-observer',bytes=Buffer.concat([artifact(),Buffer.from('--service-supervise')]);
  fs.writeFileSync(path.join(f.dir,name),bytes);Object.assign(f.m.artifacts[name],{sha256:hash(bytes),size:bytes.length});f.seal();
  assert.throws(()=>loadCandidate(f.dir,'s90d'),/candidate-source-missing/);
  f.m.source['native-observer/service-profile.h']='c'.repeat(64);f.seal();assert.ok(loadCandidate(f.dir,'s90d'));
  f.m.source['native-observer/other-profile.h']='c'.repeat(64);f.seal();assert.throws(()=>loadCandidate(f.dir,'s90d'),/candidate-source-manifest/);
 }finally{f.close();}
});
