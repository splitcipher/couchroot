const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {prepareWorkerState}=require('../agent/service/worker-state');
const {SelectionJournal,selectionStatus}=require('../agent/service/worker-selection');
function fixture(fn){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'worker-state-')));
 const data=path.join(root,'data');fs.mkdirSync(data,{mode:0o755});fs.chmodSync(data,0o2755);
 try{return fn({root,data});}finally{fs.rmSync(root,{recursive:true,force:true});}
}
test('creates a durable private child without altering app data permissions or enrollment',()=>fixture(({data})=>{
 const enrollment=path.join(data,'config.json');fs.writeFileSync(enrollment,'fixture');
 const before=fs.statSync(data),state=prepareWorkerState(data);
 assert.equal(fs.statSync(data).mode,before.mode);assert.equal(fs.readFileSync(enrollment,'utf8'),'fixture');
 assert.equal(fs.statSync(state.directory).mode&0o7777,0o700);
 assert.equal(selectionStatus(state.selectionFile).phase,'legacy-managed');
 const journal=new SelectionJournal(state.selectionFile);journal.initialize({implementation:'managed',manifest_sha256:'a'.repeat(64)});
 const bytes=fs.readFileSync(state.selectionFile);assert.deepEqual(prepareWorkerState(data),state);
 assert.deepEqual(fs.readFileSync(state.selectionFile),bytes);assert.equal(journal.read().revision,1);
}));
test('private pending selection and writer markers remain authoritative on restart',()=>fixture(({data})=>{
 const state=prepareWorkerState(data),journal=new SelectionJournal(state.selectionFile);
 journal.initialize({implementation:'managed',manifest_sha256:'a'.repeat(64)});
 journal.begin(1,{implementation:'native-prototype',manifest_sha256:'b'.repeat(64)},'c'.repeat(64));
 const bytes=fs.readFileSync(state.selectionFile);prepareWorkerState(data);
 assert.equal(selectionStatus(state.selectionFile).launch_allowed,false);assert.deepEqual(fs.readFileSync(state.selectionFile),bytes);
 fs.writeFileSync(state.selectionFile+'.writer','unfinished',{mode:0o600});prepareWorkerState(data);
 assert.equal(selectionStatus(state.selectionFile).reason,'selection-writer-incomplete');
 assert.equal(fs.readFileSync(state.selectionFile+'.writer','utf8'),'unfinished');
}));
test('legacy journal writer and dangling links are never bypassed or removed',()=>{
 for(const suffix of ['','.writer'])for(const kind of ['file','link'])fixture(({data})=>{
  const legacy=path.join(data,'worker-selection.json'+suffix);
  if(kind==='file')fs.writeFileSync(legacy,'preserved',{mode:0o600});else fs.symlinkSync('missing',legacy);
  assert.throws(()=>prepareWorkerState(data),/Legacy worker selection/);
  assert.equal(fs.existsSync(path.join(data,'worker-state')),false);
  assert.ok(fs.lstatSync(legacy));
 });
 fixture(({data})=>{prepareWorkerState(data);fs.writeFileSync(path.join(data,'worker-selection.json'),'conflict');assert.throws(()=>prepareWorkerState(data),/Legacy/);});
});
test('existing state paths are validated without chmod repair or following links',()=>{
 for(const kind of ['public','sticky','file','link'])fixture(({root,data})=>{
  const child=path.join(data,'worker-state');
  if(kind==='file')fs.writeFileSync(child,'keep');
  else if(kind==='link'){fs.mkdirSync(path.join(root,'other'),{mode:0o700});fs.symlinkSync(path.join(root,'other'),child);}
  else{fs.mkdirSync(child);fs.chmodSync(child,kind==='public'?0o755:0o1700);}
  const before=fs.lstatSync(child);assert.throws(()=>prepareWorkerState(data));assert.equal(fs.lstatSync(child).mode,before.mode);
 });
});
test('a private child left with inherited setgid can be reused without chmod',()=>fixture(({data})=>{
 const child=path.join(data,'worker-state');fs.mkdirSync(child,{mode:0o700});fs.chmodSync(child,0o2700);
 const before=fs.statSync(child),state=prepareWorkerState(data);
 assert.equal(fs.statSync(child).mode,before.mode);assert.equal(fs.statSync(child).ino,before.ino);
 new SelectionJournal(state.selectionFile).initialize({implementation:'managed',manifest_sha256:'a'.repeat(64)});
 assert.equal(fs.statSync(state.selectionFile).mode&0o777,0o600);
}));
test('data must be owned and not writable by others; final symlinks are refused',()=>fixture(({root,data})=>{
 const link=path.join(root,'linked');fs.symlinkSync(data,link);assert.throws(()=>prepareWorkerState(link));
 fs.chmodSync(data,0o777);assert.throws(()=>prepareWorkerState(data),/permissions/);assert.equal(fs.statSync(data).mode&0o777,0o777);
 assert.throws(()=>prepareWorkerState('relative'));
 if(process.geteuid()===0){fs.chmodSync(data,0o755);fs.chownSync(data,12345,12345);assert.throws(()=>prepareWorkerState(data),/ownership/);}
}));
test('service startup passes private selection path and refuses legacy state before launching',()=>{
 const vm=require('node:vm'),{EventEmitter}=require('node:events');
 for(const legacy of [false,true])fixture(({data})=>{
  if(legacy)fs.writeFileSync(path.join(data,'worker-selection.json.writer'),'uncertain');
  const calls=[],proc=new EventEmitter(),server=new EventEmitter();
  server.listen=(_port,_host,ready)=>{calls.push('listen');ready();};server.close=()=>{};
  const agent={start:()=>calls.push('start'),stop:()=>{},status:()=>({})};
  const policy={read:()=>Buffer.from('{"enabled":true,"port":12345}'),config:v=>v,atomic:()=>{},Journal:class{},createBootLaunch:()=>({status:()=> 'disabled'})};
  const modules={
   './policy':policy,
   './mqtt-lifecycle':require('../agent/service/mqtt-lifecycle'),
   './worker-state':{prepareWorkerState:input=>{assert.equal(input,'/opt/usr/home/owner/apps_rw/MiniRoot01/data');return prepareWorkerState(data);}},
   './agent':{createAgent:(_c,options)=>{calls.push(options.selectionFile);return agent;}},
   './api':{createApi:()=>server}
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../agent/service/main.js'),'utf8'),{require:n=>{assert.ok(modules[n]);return modules[n];},process:proc,console:{error:()=>calls.push('error')},setInterval,clearInterval});
  if(legacy){assert.deepEqual(calls,['error']);assert.equal(proc.exitCode,1);}
  else { assert.deepEqual(calls,[path.join(data,'worker-state','worker-selection.json'),'listen','start']); proc.emit('SIGTERM'); }
 });
});
