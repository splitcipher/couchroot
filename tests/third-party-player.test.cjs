const {test}=require('node:test');
const assert=require('node:assert/strict');
const {create}=require('../web/bridge.js');
const model=require('../web/model.js');
const fixtures=require('../preview/fixtures.js');
const player=fixtures.catalog('third-party')[2];
test('installed player discovers, persists beside stock apps and dispatches exact ID',()=>{
  const apps=fixtures.catalog('third-party').concat([
    {...player}, {...player,id:'xvvl3S1TT1.StandaloneService',show:false},
    {...player,id:'xvvl3S1TT1.Hidden',show:false},null,{}, {id:123,name:'bad'},
    {...player,id:'invalid/url'}, {...player,id:'xvvl3S1TT1.Bad',name:44},
    {...player,id:'xvvl3S1TT1.BadPackage',packageId:{}}]);
  let saved=null,found;
  const storage={getItem:()=>saved,setItem:(key,value)=>{assert.equal(key,'minimal-hub.shortcuts.v1');saved=value;}};
  const bridge=create({application:{getAppsInfo:ok=>ok(apps),launch:(id,ok)=>{assert.equal(id,player.id);ok();}}});
  bridge.discover(value=>found=value,assert.fail);
  assert.equal(found.length,3);
  model.save(storage,model.defaults.concat(found.find(a=>a.id===player.id)));
  assert.deepEqual(model.load(storage).apps.map(a=>a.id),model.defaults.map(a=>a.id).concat(player.id));
  bridge.launchApp(model.load(storage).apps[2],()=>{},assert.fail);
  const before=saved;
  create({application:{getAppsInfo:(ok,fail)=>fail({name:'SecurityError'})}}).discover(assert.fail,()=>{});
  assert.equal(saved,before);
});
test('player quiet-launch errors preserve existing one-shot fallback contract',()=>{
  for(const error of ['NotFoundError','SecurityError','NotSupportedError']){
    let ordinary=0;
    const bridge=create({ApplicationControl:function(){},ApplicationControlData:function(){},application:{
      launchAppControl:(control,id,ok,fail)=>{assert.equal(id,player.id);fail({name:error});ok();},
      launch:(id,ok,fail)=>{ordinary++;assert.equal(id,player.id);fail({name:'SecurityError'});}
    }});
    let failure;
    bridge.launchApp(player,assert.fail,e=>failure=e.name);
    assert.equal(ordinary,error==='NotFoundError'?0:1);
    assert.equal(failure,error==='NotFoundError'?'NotFoundError':'SecurityError');
  }
});
