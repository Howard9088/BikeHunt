'use strict';
// Executes the real shared dialog state machine without a browser/network.
// Rendering, native modal behavior and mobile layout are separately covered in CI.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/external-exit.js','utf8');
function harness(){
 const nodes=new Map(),listeners=[],outbound=[];let active,html='';
 class Node{
  constructor(id=''){this.id=id;this.isConnected=true;this.hidden=false;this.disabled=false;this.style={};this.attrs={};this.listeners={};this.complete=false;this.naturalWidth=0;this.textContent='';}
  setAttribute(key,value){this.attrs[key]=value}getAttribute(key){return this.attrs[key]??null}
  addEventListener(name,handler){this.listeners[name]=handler}focus(){active=this}
  showModal(){this.open=true}close(){this.open=false}getClientRects(){return [1]}
  querySelectorAll(){return ['summary','externalExitCancel','externalExitConfirm'].map(id=>nodes.get(id)).filter(Boolean)}
  set innerHTML(value){html=value;for(const match of value.matchAll(/id="([^"]+)"/g)){const n=new Node(match[1]);nodes.set(n.id,n)}nodes.set('summary',new Node('summary'))}
 }
 const doc={getElementById:id=>nodes.get(id)||null,createElement:()=>new Node(),addEventListener:(name,handler,capture)=>listeners.push({name,handler,capture}),body:{style:{overflow:'scroll'},append(node){nodes.set(node.id,node)}},get activeElement(){return active}};
 const c=vm.createContext({URL,Object,String,Array,document:doc,window:{location:{href:'https://bikehunt.example/BikeHunt/',origin:'https://bikehunt.example',assign:url=>outbound.push(url)}},directoryData:{brands:[{code:'known',name:'Known shop',official_url:'https://known.example/',shop_url:'https://known.example/shop',status:'verified_shop',shop_evidence_url:'https://known.example/'}],teams:[]},AMAZON_SEARCH_MARKETS:[{searches:[{url:'https://www.amazon.com/s?k=jersey'}]}],AMAZON_CHANNEL_LOGO_URL:'https://bikehunt.example/BikeHunt/web/assets/brands/amazon-official.png',PURCHASE_DISCLAIMER:'完整免责声明，法律规定本站应承担的责任除外。',saveBrowseState:()=>{}});
 vm.runInContext(source,c);
 const trigger=new Node('trigger');trigger.focus();
 return {c,nodes,listeners,outbound,trigger,get html(){return html},get active(){return active},get overflow(){return doc.body.style.overflow},options(extra={}){return {url:'https://known.example/product?variant=exact-M',kind:'merchant',sourceCode:'known',label:'Known shop · 当前真实商品',image:'https://images.example/current-product.jpg',validate:()=>true,...extra}}};
}
function testStrictUrls(){
 const h=harness();for(const value of ['javascript:alert(1)','data:text/html,hello','http://unsafe.example/','//evil.example/','/same-origin','https://user@known.example/','https://u:p@known.example/','https://known.example:444/','https://known.example/\n',' https://known.example/','https://known.example\\@evil.example/'])assert.equal(h.c.externalExitUrl(value),null,value);
 assert.equal(h.c.externalExitUrl('https://例子.测试/path').hostname,'xn--fsqu00a.xn--0zwm56d');
 assert.equal(h.c.externalExitUrl('https://known.example/?variant=exact-M').search,'?variant=exact-M');
}
function testIdentityAndLayout(){
 const h=harness();assert.equal(h.c.showExternalExit(h.options()),true);
 assert.equal((h.html.match(/<li>/g)||[]).length,4);for(let i=1;i<=4;i++)assert.ok(h.html.includes('aria-label="第'+i+'点">'+i+'</span>'));
 for(const text of ['本站仅提供商品与优惠信息及链接，不参与交易。','地址栏','仿冒','重定向','访问环境','库存','退换','法律规定本站应承担的责任除外。','完整免责声明','known.example','确认并前往官网'])assert.ok(h.html.includes(text),text);
 assert.equal(h.nodes.get('externalExitImage').src,'https://images.example/current-product.jpg');
 const img=h.nodes.get('externalExitImage'),fallback=h.nodes.get('externalExitImageFallback');img.complete=true;img.naturalWidth=800;img.onload();assert.equal(img.hidden,false);assert.equal(fallback.hidden,true);img.onerror();assert.equal(img.hidden,true);assert.equal(fallback.hidden,false);
 assert.equal(h.active.id,'externalExitCancel');assert.equal(h.overflow,'hidden');
 const unknown=h.c.externalExitIdentity(h.options({sourceCode:'other'}),new URL('https://known.example/'));assert.equal(unknown.official,false);assert.ok(unknown.note.includes('尚无'));
 const reference=h.c.externalExitIdentity(h.options({kind:'reference'}),new URL('https://known.example/'));assert.equal(reference.official,false);
 const registered=h.c.directoryData.brands[0];registered.status='registered';assert.ok(h.c.externalExitIdentity(h.options(),new URL('https://known.example/')).note.includes('尚无完整'));
 h.c.closeExternalExit();h.c.showExternalExit(h.options({kind:'reference',label:'<img src=x onerror=alert(1)>'}));assert.ok(h.html.includes('确认并前往目标网站'));assert.ok(h.html.includes('&lt;img'));assert.ok(!h.html.includes('<img src=x'));
 h.c.closeExternalExit();h.c.showExternalExit(h.options({kind:'amazon',url:'https://www.amazon.com/s?k=jersey',image:'',sourceCode:undefined}));assert.ok(h.html.includes('确认并前往官网'));assert.ok(h.nodes.get('externalExitImage').src.endsWith('/amazon-official.png'));
}
function testCancelFocusAndSinglePrompt(){
 const h=harness();let cancelled=0;h.c.showExternalExit(h.options({onCancel:()=>cancelled++}));const original=h.html;
 assert.equal(h.c.showExternalExit(h.options({url:'https://replacement.example/'})),false);assert.equal(h.html,original);
 const key=h.listeners.find(x=>x.name==='keydown'&&x.capture).handler;let prevented=0,stopped=0;
 h.nodes.get('externalExitConfirm').focus();key({key:'Tab',preventDefault:()=>prevented++,stopImmediatePropagation:()=>stopped++});assert.equal(h.active.id,'summary');
 // Escape is consumed in capture, so the underlying route/sheet stays open.
 key({key:'Escape',preventDefault:()=>prevented++,stopImmediatePropagation:()=>stopped++});assert.equal(cancelled,1);assert.equal(h.nodes.get('externalExitDialog').open,false);assert.equal(h.active,h.trigger);assert.equal(h.overflow,'scroll');assert.equal(h.outbound.length,0);assert.equal(stopped,2);
 let next=h.trigger;h.trigger.isConnected=false;h.c.showExternalExit(h.options({onCancel:()=>{next=h.nodes.get('externalExitCancel')},restoreFocus:()=>next}));h.c.closeExternalExit();assert.equal(h.active,next);
}
function testLateStateChangesAndNavigation(){
 const h=harness();let valid=true,persisted=0;
 h.c.showExternalExit(h.options({validate:()=>valid,onConfirm:()=>persisted++}));valid=false;h.c.confirmExternalExit();assert.equal(h.outbound.length,0);assert.equal(persisted,0);assert.equal(h.nodes.get('externalExitConfirm').disabled,true);assert.equal(h.nodes.get('externalExitError').hidden,false);assert.equal(h.active.id,'externalExitCancel');h.c.closeExternalExit();
 valid=true;h.c.showExternalExit(h.options({onConfirm:()=>persisted++}));h.c.confirmExternalExit();h.c.confirmExternalExit();assert.deepEqual(h.outbound,['https://known.example/product?variant=exact-M']);assert.equal(persisted,1);assert.equal(h.overflow,'scroll');
 assert.equal(h.c.showExternalExit(h.options({validate:()=>false})),false);assert.equal(h.c.showExternalExit(h.options({url:'http://known.example/'})),false);
}
function testGenericReferencesAndInternalExclusions(){
 const h=harness();let href='https://unknown.example/size-chart',connected=true,visible=true,prevented=0;
 const owner={contains:()=>connected},link={isConnected:true,textContent:'尺码依据',parentElement:owner,focus(){},getAttribute:()=>href,getClientRects:()=>visible?[1]:[],closest:selector=>selector==='#sheetBody'?owner:null};
 const event=(extra={})=>({target:{closest:()=>link},preventDefault:()=>prevented++,type:'click',...extra});
 h.c.guardOtherExternalExit(event());assert.ok(h.html.includes('unknown.example'));assert.ok(h.html.includes('尚无该目标的独立官方身份核验记录'));assert.ok(h.html.includes('确认并前往目标网站'));
 href='https://evil.example/';h.c.confirmExternalExit();assert.equal(h.outbound.length,0);h.c.closeExternalExit();
 for(const mutation of [()=>{link.isConnected=false},()=>{connected=false},()=>{visible=false}]){link.isConnected=true;connected=true;visible=true;h.c.guardOtherExternalExit(event());mutation();h.c.confirmExternalExit();assert.equal(h.outbound.length,0);h.c.closeExternalExit()}
 link.isConnected=true;connected=true;visible=true;href='https://unknown.example/rule';for(const extra of [{ctrlKey:true},{metaKey:true},{shiftKey:true},{type:'auxclick',button:1}]){h.c.guardOtherExternalExit(event(extra));h.c.confirmExternalExit()}assert.equal(h.outbound.length,4);
 const count=prevented;href='/BikeHunt/group/';h.c.guardOtherExternalExit(event());href='#internal-message';h.c.guardOtherExternalExit(event());href='https://unknown.example/';h.c.guardOtherExternalExit(event({defaultPrevented:true}));h.c.guardOtherExternalExit(event({type:'auxclick',button:2}));assert.equal(prevented,count);
}
function testDirectoryLogoFallback(){
 const h=harness(),flows=fs.readFileSync('web/flows.js','utf8');h.c.e=h.c.externalExitEscape;
 vm.runInContext(flows.slice(flows.indexOf('function directoryLogo('),flows.indexOf('function openPanel(')),h.c);
 const plain=h.c.directoryLogo({name:'Pas Normal Studios'});assert.ok(plain.includes('>Pas Normal Studios</span>'));assert.ok(!plain.includes('<img'));
 const valid=h.c.directoryLogo({name:'Real brand',logo_images:['/BikeHunt/web/assets/brands/real.svg']});assert.ok(valid.includes('data-directory-logo'));assert.ok(valid.includes('/BikeHunt/web/assets/brands/real.svg'));
 for(const url of ['https://remote.example/logo.svg','//evil.example/web/assets/logo.svg','/web/assets/../fake.svg','/web/assets/evil.svg?tracking'])assert.ok(!h.c.directoryLogo({name:'Fallback',logo_images:[url]}).includes('<img'));
 const image={complete:false,naturalWidth:0,hidden:false,nextElementSibling:{hidden:true}};h.c.syncDirectoryLogo(image);assert.equal(image.hidden,true);assert.equal(image.nextElementSibling.hidden,false);image.complete=true;image.naturalWidth=200;h.c.syncDirectoryLogo(image);assert.equal(image.hidden,false);assert.equal(image.nextElementSibling.hidden,true);image.naturalWidth=0;h.c.syncDirectoryLogo(image);assert.equal(image.hidden,true);assert.equal(image.nextElementSibling.hidden,false);
}
for(const test of [testStrictUrls,testIdentityAndLayout,testCancelFocusAndSinglePrompt,testLateStateChangesAndNavigation,testGenericReferencesAndInternalExclusions,testDirectoryLogoFallback]){test();console.log('PASS '+test.name)}
const index=fs.readFileSync('web/index.html','utf8'),pages=fs.readFileSync('app/pages.py','utf8');for(const file of ['external-exit.js','external-exit.css']){assert.ok(index.includes('/web/'+file));assert.ok(pages.includes('"'+file+'"'))}
console.log('External exit passed: strict URL/domain identity, four visual points, genuine assets/fallback, one modal, capture Escape, cancel focus, late invalidation, same-tab and generic references.');
