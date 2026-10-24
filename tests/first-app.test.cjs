const {test}=require('node:test');const assert=require('node:assert/strict');
const start=require('../research/first_app/clock.js');
test('clock remote lesson pauses, resumes and exits once without storage or network',()=>{
  let listener,tick,clears=0,exits=0;
  const elements={clock:{},status:{}};
  const document={getElementById:id=>elements[id],addEventListener:(name,fn)=>listener=fn,removeEventListener:()=>{}};
  let date=new Date(2026,9,24,13,5);
  start(document,{application:{getCurrentApplication:()=>({exit:()=>exits++})}},
    {setInterval:fn=>{tick=fn;return 1;},clearInterval:()=>clears++},()=>date);
  const key=code=>listener({keyCode:code,preventDefault(){}});
  assert.equal(elements.clock.textContent,'13:05');key(39);assert.equal(elements.clock.textContent,'1:05 PM');
  key(13);date=new Date(2026,9,24,13,6);tick();assert.equal(elements.clock.textContent,'1:05 PM');
  key(13);assert.equal(elements.clock.textContent,'1:06 PM');key(10009);key(10009);tick();
  assert.equal(exits,1);assert.equal(clears,1);
});
