'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {expiryTime,inspect,start}=require('../web/group.js');
const NOW=Date.parse('2026-10-15T00:00:00Z'),EXPIRES=Date.parse('2026-10-22T00:00:00+08:00');
const valid=()=>({schema_version:1,configured:true,available:true,title:'骑游海淘交流群',image_url:'/web/assets/community/group-20261015.png',expires_at:'2026-10-22T00:00:00+08:00',expiry_label:'微信标注10月22日前有效',revision:'2026-10-15'});
function flush(){return new Promise(resolve=>setImmediate(resolve))}
function harness(path='/BikeHunt/group/',data=valid()){
 let tick=0,next=1,body=data,pending=null;const timers=new Map(),listeners={},docListeners={},requests=[];
 const image={hidden:true,removeAttribute(k){delete this[k]}},status={},title={},back={addEventListener(type,callback){this[type]=callback}};
 const document={body:{dataset:{communitySource:'../data/community.json',imageBase:'../'}},visibilityState:'visible',referrer:'https://example.org/BikeHunt/',getElementById:id=>({groupQr:image,groupStatus:status,groupTitle:title,groupBack:back})[id],addEventListener:(name,cb)=>docListeners[name]=cb};
 const window={location:{href:'https://example.org'+path,origin:'https://example.org'},navigator:{onLine:true},performance:{now:()=>tick},AbortController,history:{back(){this.called=true}},setTimeout(callback,delay){let id=next++;timers.set(id,{callback,at:tick+delay});return id},clearTimeout:id=>timers.delete(id),addEventListener:(name,cb)=>listeners[name]=cb,
  fetch:async(url,options)=>{requests.push({url,options});if(pending)return pending;if(body instanceof Error)throw body;return {ok:true,headers:{get:()=>null},json:async()=>body}}};
 const controller=start(document,window);
 return {window,document,image,status,title,back,requests,listeners,docListeners,controller,timers,setBody(value){body=value},setPending(value){pending=value},async advance(ms){tick+=ms;for(const [id,timer] of [...timers])if(timer.at<=tick){timers.delete(id);timer.callback()}await flush()}};
}
async function main(){
 for(const bad of [undefined,null,'','invalid','2026-10-22','2026-10-22T00:00:00','2026-02-30T00:00:00Z','2026-10-22T24:00:00Z','2026-10-22T00:00:00+24:00'])assert.ok(Number.isNaN(expiryTime(bad)),String(bad));
 assert.equal(expiryTime(valid().expires_at),EXPIRES);assert.equal(inspect(valid(),EXPIRES-1).status,'available');assert.equal(inspect(valid(),EXPIRES).status,'expired');
 for(const image of ['https://evil.example/qr.png','//evil.example/x.png','/web/assets/community/../qr.png','/web/assets/community/%2e%2e.png','/web/assets/community/qr.svg','/web/assets/community/qr.png?token=x'])assert.equal(inspect({...valid(),image_url:image},NOW).status,'invalid');
 for(const fields of [{expires_at:null},{expires_at:'invalid'},{schema_version:2},{configured:false},{available:false},{title:'x'.repeat(61)}])assert.notEqual(inspect({...valid(),...fields},NOW).status,'available');
 const realNow=Date.now;Date.now=()=>NOW;
 try{
  let h=harness();await flush();assert.equal(h.image.hidden,true,'Only a successfully loaded real image can be shown');assert.match(h.image.src,/^https:\/\/example.org\/BikeHunt\/web\/assets\/community\/group-20261015.png\?v=/);h.image.onload();assert.equal(h.image.hidden,false);assert.equal(h.status.textContent,'微信标注10月22日前有效');
  assert.equal(h.requests[0].options.cache,'no-store');assert.match(h.requests[0].url,/\/BikeHunt\/data\/community.json\?_=/);
  h.back.click({preventDefault(){}});assert.equal(h.window.history.called,true);
  h.window.navigator.onLine=false;h.listeners.offline();assert.equal(h.image.hidden,true);assert.equal(h.image.src,undefined);assert.match(h.status.textContent,/离线/);
  h.window.navigator.onLine=true;h.listeners.online();await flush();h.image.onload();assert.equal(h.image.hidden,false);
  h.setBody({...valid(),image_url:'/web/assets/community/group-new.png',revision:'new'});await h.controller.load();h.image.onload();assert.match(h.image.src,/group-new.png\?v=new/);
  const late=h.image.onload;h.image.onerror();assert.equal(h.image.src,undefined);assert.equal(h.image.hidden,true);assert.match(h.status.textContent,/无法显示/);late();assert.equal(h.image.hidden,true);
  h=harness('/BikeHunt/group/',{...valid(),expires_at:'2026-10-15T00:00:01Z'});await flush();h.image.onload();await h.advance(1000);assert.equal(h.image.hidden,true);assert.equal(h.image.src,undefined);assert.match(h.status.textContent,/已到期/);
  h=harness();await flush();h.image.onload();h.setBody(new Error('offline'));await h.controller.load();assert.equal(h.image.hidden,true);assert.equal(h.image.src,undefined);assert.match(h.status.textContent,/无法读取/);
  h=harness();await flush();h.image.onload();h.listeners.pagehide();assert.equal(h.image.hidden,true);assert.equal(h.image.src,undefined);h.listeners.pageshow({persisted:true});await flush();h.image.onload();assert.equal(h.image.hidden,false);
  h.setBody({...valid(),available:false,expired:true});await h.advance(60000);assert.equal(h.image.hidden,true);assert.match(h.status.textContent,/已到期/);
  h=harness();await flush();let resolve;h.setPending(new Promise(done=>resolve=done));const wait=h.controller.load();await h.advance(10000);assert.equal(h.image.hidden,true);assert.match(h.status.textContent,/无法读取/);resolve({ok:true,headers:{get:()=>null},json:async()=>valid()});await wait;assert.equal(h.image.src,undefined,'Late network result cannot resurrect a timed-out QR');
  h=harness();await flush();h.image.onload();h.listeners.offline();assert.equal(h.image.src,undefined);h.docListeners.visibilitychange();await flush();
 }finally{Date.now=realNow}
 const flows=fs.readFileSync('web/flows.js','utf8'),fn=flows.slice(flows.indexOf('async function showCommunity(){'),flows.indexOf('\n',flows.indexOf('async function showCommunity(){')));
 for(const [pages,path,expected] of [[true,'/BikeHunt/','/BikeHunt/group/'],[false,'/web/','/web/group/']]){
  let saved=false,navigated='';const context={URL,saveBrowseState:()=>saved=true,window:{BIKEHUNT_PAGES:pages,location:{href:'https://example.org'+path,assign:url=>{assert.ok(saved);navigated=url}}}};vm.createContext(context);vm.runInContext(fn,context);await context.showCommunity();assert.equal(navigated,'https://example.org'+expected);
 }
 console.log('Group safety passed: explicit expiry, safe image path, Pages prefix, no-store reads, image errors, offline, replacement, exact deadline, timeout, Back, resumed pages, same-tab browse preservation.');
}
main().catch(error=>{console.error(error);process.exitCode=1});
