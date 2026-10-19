const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),os=require('os'),path=require('path'),https=require('https'),crypto=require('crypto'),{execFileSync,execFile}=require('child_process');
const {Journal,config,validateRequest,hash,sdkRuntimeGuard}=require('../research/autonomous-root/service/policy');
const {createApi}=require('../research/autonomous-root/service/api');
const {createAgent,launchRequest}=require('../research/autonomous-root/service/agent');
const tmp=()=>fs.mkdtempSync(path.join(os.tmpdir(),'tv-agent-test-'));
const command=id=>({id:id||crypto.randomUUID(),command:'id',timeout_ms:2000});
test('SDK launch uses a staged script within the transport limit',()=>{
 const pkg='archive-root-0123456789abcdef',stage='/home/owner/share/tmp/sdk_tools/'+pkg;
 const request=launchRequest(stage,'/tmp/'+pkg+'-launch-once');
 assert.ok(Buffer.byteLength(request)<=510);
 const encoded=request.match(/printf\$\{IFS\}%s\$\{IFS\}([^|]+)/)[1];
 assert.ok(Buffer.from(encoded,'base64').toString().includes(". '"+stage+"/launch-sdk.sh'"));
 assert.throws(()=>launchRequest('/'+ 'x'.repeat(1000),'/tmp/gate'),/transport limit/);
});
test('SDK runtime guard blocks payload execution on mismatch or unreadable bytes',()=>{
 const c={schema:1,device:'s90d',enabled:false,port:28443,firmware:'test',client_sha256:'a'.repeat(64),hashes:{'/usr/bin/dotnet':'b'.repeat(64),'/usr/sbin/sdbd-tarlauncher':'b'.repeat(64)}};
 const guard=sdkRuntimeGuard(c),run=body=>require('child_process').spawnSync('/bin/sh',['-c',body+'\n'+guard+'printf PAYLOAD_REACHED'],{encoding:'utf8'});
 assert.equal(run("sha256sum(){ printf '%s file\\n' '"+'b'.repeat(64)+"'; }").stdout,'PAYLOAD_REACHED');
 for(const body of ["sha256sum(){ printf '%s file\\n' '"+'c'.repeat(64)+"'; }",'sha256sum(){ return 1; }']){
  const result=run(body);assert.equal(result.status,74);assert.equal(result.stdout.includes('PAYLOAD_REACHED'),false);
 }
 assert.throws(()=>sdkRuntimeGuard({...c,hashes:{'/tmp/untrusted':'b'.repeat(64)}}));
});
test('journal rejects replay across restart, including uncertain outcomes',()=>{
 const dir=tmp();try{const file=dir+'/requests.json',v=command(),j=new Journal(file);j.begin(v);assert.throws(()=>j.begin(v),/already submitted/);const restarted=new Journal(file);assert.equal(restarted.rows[0].state,'submitted');assert.throws(()=>restarted.begin(v));restarted.finish(v.id,{exit_code:0,timed_out:false});assert.equal(new Journal(file).rows[0].state,'completed');assert.equal(fs.readFileSync(file,'utf8').includes('"command"'),false);}finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('request and configuration bounds fail closed',()=>{
 for(const v of [{},command('short'),{...command(),timeout_ms:25001},{...command(),command:'x'.repeat(16385)},{...command(),command:'id\0'},{...command(),extra:true}])assert.throws(()=>validateRequest(v));
 const c={schema:1,device:'qn90a',enabled:false,port:28443,firmware:'test',client_sha256:'a'.repeat(64),hashes:{'/usr/bin/dotnet':'b'.repeat(64),'/usr/sbin/sdbd-tarlauncher':'c'.repeat(64)}};assert.equal(config(c),c);assert.throws(()=>config({...c,hashes:{'/tmp/bad':'d'.repeat(64)}}));assert.throws(()=>config({...c,enabled:'yes'}));
});
test('firmware failure never reaches SDK; explicit stop cancels retry',async()=>{
 const a=createAgent({device:'qn90a'},{verifyFirmware:()=>{throw Error('firmware drift');}});assert.equal(a.status().enabled,false);a.start();await new Promise(r=>setImmediate(r));assert.equal(a.status().connected,false);assert.equal(a.status().attempts,1);assert.match(a.status().last_error,/firmware drift/);a.stop();assert.equal(a.status().enabled,false);
});
test('permission failures retain the acquisition step and file path',async()=>{
 const a=createAgent({device:'s90d'},{verifyFirmware:()=>{throw Object.assign(new Error("EACCES: permission denied, open '/usr/bin/dotnet'"),{code:'EACCES'});}});
 try {a.start();await new Promise(r=>setImmediate(r));assert.match(a.status().last_error,/^firmware verification: EACCES:.*\/usr\/bin\/dotnet/);}
 finally {a.stop();}
});
test('mutual TLS, enrollment pin, request replay, disable and unknown outcomes',async()=>{
 // Keep the test's TLS policy on its agent so current Node can reuse sockets.
 const checkServerIdentity=()=>undefined;
 const dir=tmp();let server;const pool=new https.Agent({keepAlive:true,maxSockets:1,checkServerIdentity});
 try{
  function cert(name){execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-keyout',dir+'/'+name+'-key.pem','-out',dir+'/'+name+'.pem','-days','1','-subj','/CN='+name],{stdio:'ignore'});return {key:fs.readFileSync(dir+'/'+name+'-key.pem'),cert:fs.readFileSync(dir+'/'+name+'.pem')};}
  const serverCert=cert('server'),clientCert=cert('client'),foreign=cert('foreign');
  const pin=hash(new crypto.X509Certificate(clientCert.cert).raw);
  let calls=0,enabled=true,uncertain=false,exitCode=0,badChunk=false;
  const downloadBytes=Buffer.from([0,10,13,128,255]);
  const agent={status:()=>({connected:enabled}),start:()=>{enabled=true;},stop:()=>{enabled=false;},execute:async()=>{calls++;if(uncertain)throw Error('lost response');return {exit_code:exitCode,timed_out:false,stdout:'uid=0',stderr:''};},operation:async (op,data)=>{if(op.op==='file.read')return {data:downloadBytes,offset:7,sha256:badChunk?'0'.repeat(64):hash(downloadBytes)};if(op.op==='file.commit')throw Object.assign(Error('Target hash conflict'),{outcome:'failed'});if(op.op==='file.write'){assert.equal(op.data,undefined);assert.equal(op.length,5);assert.ok(Buffer.isBuffer(data));assert.equal(data.toString(),'chunk');return {offset:5};}return {state:'running'};}};
  const journal=new Journal(dir+'/requests.json');
  server=createApi({credentials:{...serverCert,ca:clientCert.cert},clientPin:pin,agent,journal,setEnabled:v=>{enabled=v;}});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const port=server.address().port;
  function request(route,body,credentials=clientCert,extra={},reuse=false){return new Promise((resolve,reject)=>{const r=https.request({host:'127.0.0.1',port,path:route,method:body===undefined?'GET':'POST',...credentials,ca:serverCert.cert,checkServerIdentity,agent:reuse?pool:false,headers:{'Content-Type':'application/json',...extra}},res=>{const socket=res.socket;let parts=[];res.on('data',d=>parts.push(d));res.on('end',()=>{const data=Buffer.concat(parts);resolve({socket,status:res.statusCode,headers:res.headers,body:res.headers['content-type']==='application/octet-stream'?data:JSON.parse(data)});});});r.on('error',reject);r.end(body===undefined?undefined:Buffer.isBuffer(body)?body:JSON.stringify(body));});}
  let connections=0;server.on('secureConnection',()=>connections++);
  const clientConfig={host:'127.0.0.1',port,server_certificate:dir+'/server.pem',client_certificate:dir+'/client.pem',client_key:dir+'/client-key.pem',server_sha256:hash(new crypto.X509Certificate(serverCert.cert).raw)};
  fs.writeFileSync(dir+'/client.json',JSON.stringify(clientConfig),{mode:0o600});
  const script=`import hashlib,importlib.util,json,sys
spec=importlib.util.spec_from_file_location('client',sys.argv[1]);api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
c=json.load(open(sys.argv[2]))
with api.Session(c) as session:
 assert api.request(c,'GET','/v1/status',session=session)['connected']
 assert api.operation(c,dict(op='file.write',offset=0,sha256=hashlib.sha256(b'chunk').hexdigest()),binary=b'chunk',session=session)['offset']==5
 assert api.operation(c,dict(op='file.read',offset=7,length=5),session=session)==bytes([0,10,13,128,255])
 assert api.request(c,'GET','/v1/status',session=session)['connected']
`;
  await new Promise((resolve,reject)=>execFile('python3',['-c',script,path.resolve(__dirname,'../research/autonomous-root/client.py'),dir+'/client.json'],{timeout:10000},(err,out,stderr)=>err?reject(Error(stderr||err.message)):resolve(out)));
  assert.equal(connections,1,'Python JSON and binary requests must share one pinned TLS socket');
  let prior;
  for(let i=1;i<=129;i++){
   const r=await request('/v1/status',undefined,clientCert,{'Connection':'keep-alive'},true);
   assert.equal(r.status,200);assert.ok(Number(r.headers['content-length'])>0);
   if(i>1&&i<=128)assert.equal(r.socket,prior);
   if(i===128)assert.equal(r.headers.connection,'close');
   if(i===129)assert.notEqual(r.socket,prior);
   prior=r.socket;
  }
  const rejected=await request('/v1/status',undefined,clientCert,{Connection:'keep-alive',Origin:'https://example.invalid'},true);
  assert.equal(rejected.status,403);assert.equal(rejected.socket,prior);assert.equal(rejected.headers.connection,'close');
  const next=await request('/v1/status',undefined,clientCert,{Connection:'keep-alive'},true);assert.notEqual(next.socket,prior);
  assert.equal(server.keepAliveTimeout,5000);
  await assert.rejects(request('/v1/status',undefined,{}));await assert.rejects(request('/v1/status',undefined,foreign));
  assert.equal((await request('/v1/status')).status,200);
  assert.equal((await request('/v1/status',undefined,clientCert,{Origin:'https://example.invalid'})).status,403);
  const v=command();assert.equal((await request('/v1/exec',v)).body.stdout,'uid=0');assert.equal(calls,1);assert.equal((await request('/v1/exec',v)).status,409);assert.equal(calls,1);
  exitCode=1;const nonzero=await request('/v1/exec',command());assert.equal(nonzero.status,200);assert.equal(nonzero.body.exit_code,1);assert.equal(nonzero.body.stdout,'uid=0');calls=1;
  const operationId=crypto.randomUUID();
  const failed=await request('/v1/op',{id:operationId,operation:{op:'file.commit',transfer_id:'example'}});
  assert.equal(failed.body.outcome,'failed');assert.equal(journal.rows.find(r=>r.id===operationId).state,'completed');
  const binary=await request('/v1/files/write',Buffer.from('chunk'),clientCert,{'X-Operation':JSON.stringify({id:crypto.randomUUID(),operation:{op:'file.write',transfer_id:'example',offset:0,sha256:hash('chunk')}})});
  assert.equal(binary.status,200);assert.equal(binary.body.offset,5);
  const uploadId=crypto.randomUUID(),uploadOp={op:'file.write',transfer_id:'example',offset:0,sha256:hash('chunk')};
  const upload=op=>request('/v1/files/write',Buffer.from('chunk'),clientCert,{'X-Operation':JSON.stringify({id:uploadId,operation:op})});
  assert.equal((await upload({...uploadOp,sha256:hash('other')})).body.outcome,'rejected');
  assert.ok(!journal.rows.some(r=>r.id===uploadId));
  assert.equal((await upload({...uploadOp,data:'unexpected'})).body.outcome,'rejected');
  assert.equal((await upload(uploadOp)).status,200);
  assert.equal(journal.rows.find(r=>r.id===uploadId).sha256,hash('operation:'+hash(JSON.stringify({...uploadOp,length:5}))));
  assert.equal((await upload(uploadOp)).body.outcome,'rejected');

  assert.equal((await request('/v1/op',{id:crypto.randomUUID(),operation:{op:'file.write'}})).body.outcome,'rejected');
  const read=()=>request('/v1/files/read',{id:crypto.randomUUID(),operation:{op:'file.read',transfer_id:'example',offset:7,length:5}});
  const downloaded=await read();assert.equal(downloaded.status,200);assert.deepEqual(downloaded.body,downloadBytes);assert.equal(downloaded.headers['x-sha256'],hash(downloadBytes));assert.equal(downloaded.headers['x-offset'],'7');
  badChunk=true;assert.equal((await read()).status,409);
  uncertain=true;const lost=command();assert.equal((await request('/v1/exec',lost)).status,409);assert.equal((await request('/v1/exec',lost)).status,409);assert.equal(calls,2);assert.equal(journal.rows.find(r=>r.id===lost.id).state,'submitted');
  assert.equal((await request('/v1/disable',{})).status,200);assert.equal((await request('/v1/exec',command())).status,503);
  const snapshot=await request('/v1/requests');assert.equal(snapshot.body.sha256,journal.digest());
  assert.equal((await request('/v1/journal/archive',{})).status,409);
  assert.equal((await request('/v1/journal/archive',{expected_sha256:'0'.repeat(64)})).status,409);
  await assert.rejects(request('/v1/journal/archive',{expected_sha256:journal.digest()},foreign));
  assert.equal((await request('/v1/journal/archive',{expected_sha256:journal.digest()},clientCert,{Origin:'https://example.invalid'})).status,403);
  assert.equal((await request('/v1/journal/archive',{expected_sha256:journal.digest()})).status,200);assert.equal(calls,2);
  assert.equal((await request('/v1/enable',{})).status,200);assert.equal((await request('/unknown')).status,404);
 }finally{pool.destroy();if(server)await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true});}
});
