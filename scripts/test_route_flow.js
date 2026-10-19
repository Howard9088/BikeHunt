'use strict';
// Executes production route/registration state in an isolated DOM harness.
// No network request, Chromium rendering, real account or merchant transaction.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {installExternalExitStub}=require('./external_exit_test_helper');
const gallery=fs.readFileSync('web/gallery.js','utf8'),flows=fs.readFileSync('web/flows.js','utf8');
const source=fs.readFileSync('web/purchase-flow.js','utf8'),readiness=fs.readFileSync('web/purchase-readiness.js','utf8');
const policy=JSON.parse(fs.readFileSync('web/purchase-readiness.json','utf8'));
const NOW=Date.parse('2026-10-19T08:00:00Z');
function slice(text,start,end){const a=text.indexOf(start),b=text.indexOf(end,a);assert.ok(a>=0&&b>a,start);return text.slice(a,b)}
function quote(code='visma',extra={}){return {eligible:false,reasons:[],product_cny:'700',offer:{offer_id:'offer-'+code,source_code:code,source_name:code,sales_region:code==='poc'?'Global EN':'US 市场报价（USD）',url:code==='maap'?'https://maap.cc/products/jersey?variant=M':code==='poc'?'https://poc.com/en/jersey?variant=M':code==='visma'?'https://www.teamvismaleaseabike.com/shop/jersey/?variant=M':'https://shop.example/jersey?variant=M',stock:'in_stock',collection_state:'current',fetched_at:new Date(NOW).toISOString(),price:{amount:'100',currency:'USD'},shipping_to_china:{status:'unknown'},china_issued_card:{status:'unknown'},accepted_card_networks:['Visa'],...extra}}}
function detail(q=quote()){return {product_id:'jersey',variant_id:'variant-m',name:'Test jersey',name_zh:'骑行服测试',identity:{size:'M',color:'red'},variants:[{variant_id:'variant-m',in_stock:true}],offers:[q]}}
function harness(){
 let now=NOW,html='',title='',open=false,focused=null,saved=0,loadResult=null;
 const elements=new Map(),nodes=[],navigated=[],requested=[],loaded=[],historyCalls=[],listeners=[];
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const node=attrs=>({attrs,dataset:Object.fromEntries(Object.entries(attrs).filter(([key])=>key.startsWith('data-')).map(([key,value])=>[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),value])),disabled:Object.hasOwn(attrs,'disabled'),isConnected:true,style:{},classList:{contains:()=>open},contains:x=>nodes.includes(x),getAttribute(key){return this.attrs[key]??null},setAttribute(key,value){this.attrs[key]=String(value)},focus(){focused=this.attrs.id||this.dataset.routeSelect},querySelectorAll:()=>[]});
 function render(content){html=content;elements.clear();nodes.splice(0);for(const match of content.matchAll(/<[a-z][^>]*>/g)){const attrs={};for(const attr of match[0].matchAll(/([\w-]+)="([^"]*)"/g))attrs[attr[1]]=attr[2];if(/\sdisabled(?:\s|>)/.test(match[0]))attrs.disabled='';const item=node(attrs);nodes.push(item);if(attrs.id)elements.set(attrs.id,item)}}
 function query(selector){if(selector.startsWith('#'))return elements.get(selector.slice(1))||null;const m=selector.match(/^\[([^=\]]+)(?:="([^"]+)")?\]$/);return m?nodes.find(item=>Object.hasOwn(item.attrs,m[1])&&(m[2]===undefined||item.attrs[m[1]]===m[2]))||null:null}
 class MockDate extends Date{constructor(...args){super(...(args.length?args:[now]))}static now(){return now}}
 const c=vm.createContext({Date:MockDate,URL,URLSearchParams,Map,Set,Object,JSON,Number,String,Array,Promise,console,
  document:{currentScript:{src:'https://bikehunt.example/BikeHunt/web/flows.js'},addEventListener:(...args)=>listeners.push(args),getElementById:id=>id==='sheet'?sheet:id==='sheetBody'?body:elements.get(id)||null,querySelector:query,querySelectorAll:selector=>selector==='[data-route-select]'?nodes.filter(item=>item.dataset.routeSelect):[]},
  window:{location:{assign:url=>navigated.push(url)},addEventListener(){}},
  history:{state:{unrelated:'keep',bikehuntBrowse:{source:'visma',category:'jerseys',query:'Test jersey'}},replaceState(value,...args){historyCalls.push([value,...args]);this.state=value}},
  guideContext:null,currentProduct:null,detailSequence:0,guideStep:0,referenceOffers:new Map(),e:esc,safeUrl:value=>{try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:''}catch{return ''}},
  cny:value=>'CNY '+value,timeText:value=>value,landedCostMarkup:()=>'<div class="landed-cost-fixture">budget</div>',
  registrationHelpMarkup:(code,market)=>'<div class="registration-help" data-registration-help="'+esc(code)+'">'+esc(market)+'</div>',
  PURCHASE_DISCLAIMER:'本站仅提供商品与优惠信息，不参与交易。价格、库存、尺码及折扣可能变化，信息不保证完全准确，请以实际商家页面及结算信息为准，并在购买前自行核实。购买、付款、配送、退换货，以及买错商品或尺码不合适等问题，请直接联系实际商家。法律规定本站应承担的责任除外。',
  saveBrowseState:()=>saved++,openPanel(name,content,preserve=false){if(!preserve){c.guideContext=null;if(c.cancelPurchaseContext)c.cancelPurchaseContext()}c.detailSequence++;open=true;title=name;render(content)},
  getJson:async url=>{requested.push(url);return typeof loadResult==='function'?loadResult(url):loadResult},
  loadDetail:async(id,variant)=>{loaded.push([id,variant]);c.detailSequence++;c.guideContext=null;render('<p id="detailFixture">selected detail</p>')},
  showInventoryInvalidated(){c.guideContext=null;c.openPanel('库存待核实','<p>库存待核实</p>')},
  fetch:async()=>{throw Error('No network allowed')},
 });
 const exit=installExternalExitStub(c),prompts=exit.prompts;
 const sheet={classList:{contains:()=>open}},body={contains:item=>nodes.includes(item),querySelectorAll:()=>[]};c.sheet=sheet;
 vm.runInContext(fs.readFileSync('web/public-visibility.js','utf8'),c);
 vm.runInContext(slice(gallery,'function inventoryVerified(','function offerMarkup('),c);
 vm.runInContext(readiness.replace(/^loadPurchaseReadiness\(\);$/m,''),c);c.input=policy;vm.runInContext('readinessData=validateReadinessData(input);readinessState="ready"',c);
 vm.runInContext(slice(flows,'const AMAZON_SEARCH_MARKETS=',"// Standalone marketplace search navigation is retired;"),c);
 vm.runInContext(slice(flows,'async function startGuide(','function updateGuideVerificationMetadata('),c);
 vm.runInContext(source,c);
 vm.runInContext(slice(flows,'function ruleMarkup(','function syncChannelInfo('),c);
 return {c,elements,nodes,navigated,prompts,requested,loaded,historyCalls,get html(){return html},get title(){return title},get saved(){return saved},get focused(){return focused},setNow:value=>now=value,setAnswer:value=>exit.setAnswer(value),setResult:value=>loadResult=value,get reg(){return vm.runInContext('registrationExitContext',c)},open(d=detail(),options={}){c.currentProduct=d;c.guideContext={detail:d,quote:d.offers[0],route:null,reference:false,book:{documents:[]},...options};c.renderRouteComparison();return c.guideContext},close(){open=false;c.clearPurchaseState();render('')}};
}
function statuses(h,q){return Object.fromEntries(h.c.routeOptions(q).map(row=>[row.id,row.status]))}
function testThreeScopedRoutesAndHonestCosts(){
 const h=harness(),q=quote(),before=JSON.stringify(q);
 assert.deepEqual(statuses(h,q),{direct:'conditional',forwarding:'unknown',hongkong:'unknown'});
 assert.deepEqual(statuses(h,quote('maap')),{direct:'prohibited',forwarding:'unknown',hongkong:'unknown'});
 assert.deepEqual(statuses(h,quote('poc')),{direct:'prohibited',forwarding:'prohibited',hongkong:'prohibited'});
 assert.deepEqual(statuses(h,quote('poc',{sales_region:'US'})),{direct:'unknown',forwarding:'prohibited',hongkong:'prohibited'},'Explicit same-merchant reshipper ban cannot be bypassed by currency label');
 assert.deepEqual(statuses(h,quote('retailer',{identity:{brand:'POC'}})),{direct:'unknown',forwarding:'unknown',hongkong:'unknown'},'Brand identity never imports another merchant policy');
 assert.equal(statuses(h,quote('visma',{url:'https://evil.example/product'})).direct,'unknown');
 const routes=h.c.routeOptions(q);for(const route of routes){assert.equal(route.total,null);assert.ok(route.costs.some(([,value])=>value==='待确认'))}
 assert.ok(routes[2].costs.some(([label])=>label.includes('非香港报价')));assert.equal(JSON.stringify(q),before);
 q.offer.shipping_to_china={status:'yes',scope:'offer',checked_at:'2026-10-15T00:00:00Z'};
 q.landed_cost={components:['product','shipping','tax','clearance','payment'].map((key,index)=>({key,status:'quoted',original:{amount:10,currency:'USD'},cny:index+1}))};
 assert.equal(statuses(h,q).direct,'confirmed');assert.equal(h.c.routeOptions(q)[0].total,15);
 for(const key of ['product','shipping','tax','clearance','payment']){const copy=structuredClone(q);copy.landed_cost.components.find(c=>c.key===key).status='unknown';assert.equal(statuses(h,copy).direct,'conditional');assert.equal(h.c.routeOptions(copy)[0].total,null)}
 const changed=structuredClone(q);changed.offer.shipping_to_china.note='原文已变化，正在复核';assert.equal(statuses(h,changed).direct,'unknown');
 h.setNow(NOW+3600001);assert.equal(statuses(h,q).direct,'confirmed','One hour alone cannot revoke observed stock');
 h.setNow(NOW+86400001);assert.notEqual(statuses(h,q).direct,'confirmed');assert.equal(h.c.routeOptions(q)[0].total,null,'Old prices cannot promise a current total');
 const offline=harness();vm.runInContext('readinessData=null;readinessState="error"',offline.c);
 assert.equal(statuses(offline,quote('maap')).direct,'prohibited','Unavailable policy data cannot make a known MAAP direct ban selectable');
 for(const market of ['Global EN','US']){const routes=statuses(offline,quote('poc',{sales_region:market}));assert.equal(routes.forwarding,'prohibited');assert.equal(routes.hongkong,'prohibited')}
 assert.deepEqual(statuses(offline,quote('retailer',{identity:{brand:'POC'}})),{direct:'unknown',forwarding:'unknown',hongkong:'unknown'});
 assert.deepEqual(statuses(offline,quote('poc',{url:'https://evil.example/product'})),{direct:'unknown',forwarding:'unknown',hongkong:'unknown'},'Restrictive fallbacks stay bound to the exact merchant host');
}
function testRouteSelectionPrecedesRegistration(){
 const h=harness();h.open(detail(quote('maap')));
 assert.equal((h.html.match(/class="route-card"/g)||[]).length,3);assert.ok(!h.html.includes('registration-help'));assert.equal(h.elements.get('routeContinue').disabled,true);
 h.c.continuePurchaseRoute();assert.equal(h.reg,null);h.c.selectPurchaseRoute('direct');assert.equal(h.c.guideContext.route,null);
 h.c.selectPurchaseRoute('hongkong');assert.equal(h.c.guideContext.route,'hongkong');assert.equal(h.elements.get('routeContinue').disabled,false);assert.ok(h.html.includes('去官网核实'));
 assert.ok(!h.html.includes('registration-help'));assert.equal(h.prompts.length,0);assert.equal(h.navigated.length,0);
 h.c.continuePurchaseRoute();assert.ok(h.html.includes('id="registrationInterstitial"'));assert.equal((h.html.match(/class="registration-help"/g)||[]).length,1);assert.ok(h.html.includes('data-registration-help="maap"'));assert.equal(h.prompts.length,0);
 h.c.cancelRegistrationExit();assert.ok(h.html.includes('id="routeComparison"'));assert.equal(h.c.guideContext.route,'hongkong');assert.ok(!h.html.includes('registration-help'));
 h.elements.get('routeBack').onclick();assert.deepEqual(h.loaded,[['jersey','variant-m']]);
}
function testSharedConfirmationOnlyAtFinalSameTabExit(){
 const h=harness();h.open();h.c.selectPurchaseRoute('direct');h.c.continuePurchaseRoute();
 h.setAnswer(false);h.c.continueRegistrationExit();assert.equal(h.prompts.length,1);assert.equal(h.prompts[0].kind,'merchant');assert.equal(h.prompts[0].url,h.c.guideContext.quote.offer.url);assert.ok(h.prompts[0].note.includes('所选运输路线仍需商家核实'));assert.equal(h.navigated.length,0);assert.ok(h.html.includes('routeComparison'));
 h.c.continuePurchaseRoute();h.setAnswer(true);h.c.continueRegistrationExit();assert.deepEqual(h.navigated,[h.c.guideContext.quote.offer.url]);assert.equal(h.c.history.state.bikehuntPurchase.stage,'route');assert.equal(h.c.history.state.bikehuntPurchase.route,'direct');
 for(const mutate of [g=>g.quote.offer.url+='&variant=L',g=>g.quote.offer.price.amount='99',g=>g.quote.offer.source_code='other',g=>g.quote.offer.stock='out_of_stock',g=>g.invalidated=true]){
  const x=harness();x.open();x.c.selectPurchaseRoute('direct');x.c.continuePurchaseRoute();x.setAnswer(()=>{mutate(x.c.guideContext);return true});x.c.continueRegistrationExit();assert.equal(x.navigated.length,0,'Revalidate exact offer, price, source, status and route after the shared confirmation decision');
 }
 const expired=harness();expired.open();expired.c.selectPurchaseRoute('direct');expired.c.continuePurchaseRoute();expired.setAnswer(()=>{expired.setNow(NOW+3600001);return true});expired.c.continueRegistrationExit();assert.equal(expired.navigated.length,1,'Elapsed time alone preserves the guarded exact merchant entrance');
 const hidden=harness();hidden.open();hidden.c.selectPurchaseRoute('direct');hidden.c.continuePurchaseRoute();hidden.close();hidden.setAnswer(true);hidden.c.continueRegistrationExit();assert.equal(hidden.navigated.length,0);assert.equal(hidden.prompts.length,0);
}
function testLastKnownStockAndAmazonRegistration(){
 const h=harness(),q=quote('visma',{fetched_at:'2000-01-01T00:00:00Z'});q.reference_product_id='jersey';q.reference_variant_id='variant-m';h.c.currentProduct=detail(q);h.c.startReferenceRoute(q);
 assert.equal(h.c.guideContext.reference,false);assert.ok(h.html.includes('上次确认有货'));assert.ok(h.html.includes('上次记录商品价（官网核对）'));assert.equal(h.c.routeOptions(q)[0].total,null);assert.ok(!h.html.includes('registration-help'));
 h.c.selectPurchaseRoute('direct');h.c.continuePurchaseRoute();h.setAnswer(true);h.c.continueRegistrationExit();assert.deepEqual(h.navigated,[q.offer.url]);
 const markets=vm.runInContext('AMAZON_SEARCH_MARKETS',h.c);
 for(const market of markets)for(const search of market.searches){
  const before=h.navigated.length;h.c.openAmazonRegistration(search);assert.ok(h.html.includes('data-registration-help="'+market.code+'"'));assert.ok(h.html.includes(market.salesRegion));assert.ok(!h.html.includes('id="routeComparison"'));
  h.setAnswer(false);h.c.continueRegistrationExit();assert.equal(h.navigated.length,before);assert.equal(h.title,'Amazon购买途径');assert.ok(!h.html.includes('registration-help'));
  h.c.openAmazonRegistration(search);h.setAnswer(true);h.c.continueRegistrationExit();assert.equal(h.navigated.at(-1),search.url);
 }
 const last=h.navigated.length;h.c.openAmazonRegistration({...markets[0].searches[0],url:'https://evil.example/'});assert.equal(h.navigated.length,last);assert.equal(h.reg.search,markets.at(-1).searches.at(-1),'Unknown search object cannot replace a trusted context');
}
async function testHistoryRestoresExactVerifiedSelection(){
 const h=harness(),d=detail();h.open(d);h.c.selectPurchaseRoute('forwarding');h.c.continuePurchaseRoute();
 const saved=structuredClone(h.c.history.state.bikehuntPurchase);assert.equal(saved.productId,'jersey');assert.equal(saved.variantId,'variant-m');assert.equal(saved.offerId,'offer-visma');assert.equal(saved.sourceCode,'visma');assert.equal(saved.url,d.offers[0].offer.url);assert.equal(saved.route,'forwarding');assert.equal(saved.stage,'registration');
 assert.equal(h.c.history.state.unrelated,'keep');assert.deepEqual(h.c.history.state.bikehuntBrowse,{source:'visma',category:'jerseys',query:'Test jersey'});assert.ok(h.historyCalls.every(call=>call.length===2),'State never writes identity or personal data into the browser URL');
 h.setResult(structuredClone(d));await h.c.restorePurchaseState();assert.equal(h.requested.at(-1),'/api/catalog/jersey?variant_id=variant-m');assert.ok(h.html.includes('registrationInterstitial'));assert.equal(h.c.guideContext.route,'forwarding');assert.equal(h.c.guideContext.quote.offer.offer_id,saved.offerId);
 for(const stage of ['route','registration']){const x=harness();x.c.history.state.bikehuntPurchase={...saved,stage};const changed=structuredClone(d);changed.offers[0].offer.price.amount='999';x.setResult(changed);await x.c.restorePurchaseState();assert.ok(x.html.includes('routeComparison'));assert.equal(x.c.guideContext.invalidated,true);assert.equal(x.elements.get('routeContinue').disabled,true);assert.ok(!x.html.includes('USD 999'));assert.ok(!x.html.includes('registration-help'))}
 const sold=harness();sold.c.history.state.bikehuntPurchase=saved;const unavailable=structuredClone(d);unavailable.offers[0].offer.stock='out_of_stock';sold.setResult(unavailable);await sold.c.restorePurchaseState();assert.deepEqual(sold.loaded,[['jersey','variant-m']]);assert.equal(sold.reg,null);
 const offline=harness();offline.c.history.state.bikehuntPurchase=saved;offline.setResult(()=>Promise.reject(Error('offline')));await offline.c.restorePurchaseState();assert.ok(offline.html.includes('旧报价与购买入口已停用'));assert.equal(offline.reg,null);assert.equal(offline.navigated.length,0);
 const cancelled=harness();cancelled.c.history.state.bikehuntPurchase=saved;let resolve;cancelled.setResult(()=>new Promise(done=>resolve=done));const pending=cancelled.c.restorePurchaseState();cancelled.close();resolve(d);await pending;assert.equal(cancelled.reg,null);assert.equal(cancelled.c.guideContext,null);
}
async function testPublicationChangeDisablesBeforeRechecking(){
 for(const result of ['price','missing','sold','retained','offline','unknown','unchanged']){
  const h=harness(),d=detail();h.open(d);h.c.selectPurchaseRoute('direct');h.c.continuePurchaseRoute();let resolve,reject;h.setResult(()=>new Promise((yes,no)=>{resolve=yes;reject=no}));
  const beforeTime=d.offers[0].offer.fetched_at;
  const pending=h.c.invalidatePurchaseFlow([]);assert.equal(h.reg,null);assert.equal(h.elements.get('routeContinue').disabled,false);
  const fresh=structuredClone(d);if(result==='price')fresh.offers[0].offer.price.amount='99';if(result==='missing')fresh.offers=[];if(result==='sold')fresh.offers[0].offer.stock='out_of_stock';if(result==='retained')fresh.offers[0].offer.collection_state='retained';if(result==='unknown')fresh.offers[0].offer.stock='unknown';
  if(result==='offline')reject(Error('offline'));else resolve(fresh);await pending;
  const changed=['price','sold'].includes(result);
  assert.equal(Boolean(h.c.guideContext.invalidated),changed,result);assert.equal(h.elements.get('routeContinue').disabled,changed,result);assert.equal(h.c.guideContext.route,'direct');
  if(!changed){assert.equal(h.c.guideContext.quote.offer.fetched_at,beforeTime,'Refresh must not invent a stock timestamp');h.c.continuePurchaseRoute();h.setAnswer(true);h.c.continueRegistrationExit();assert.equal(h.navigated.length,1,result);}
 }
 const h=harness(),q=quote(),other=structuredClone(q);other.offer.collection_state='retained';other.eligible=false;other.reasons=['Old quote; verify on merchant site'];
 assert.equal(h.c.purchaseIdentity(q),h.c.purchaseIdentity(other),'Refresh metadata is not a product identity change');
}
async function testObservedChangesCannotBeOverruledOrResurrectClosedStages(){
 for(const event of [{offer_id:'offer-visma',stock:'out_of_stock'},{offer_id:'offer-visma',new_price:'99',currency:'USD'},{offer_id:'offer-visma',new_price:'100',currency:'EUR'}]){
  const h=harness(),d=detail();h.open(d);h.c.selectPurchaseRoute('direct');h.c.continuePurchaseRoute();h.setResult(structuredClone(d));await h.c.invalidatePurchaseFlow([event]);
  assert.equal(h.reg,null);assert.equal(h.c.guideContext.invalidated,true);assert.equal(h.elements.get('routeContinue').disabled,true);h.setAnswer(true);h.c.continuePurchaseRoute();h.c.continueRegistrationExit();assert.equal(h.navigated.length,0);
 }
 for(const close of [true,false]){
  const h=harness(),d=detail();h.open(d);h.c.selectPurchaseRoute('direct');h.c.continuePurchaseRoute();let resolve;h.setResult(()=>new Promise(done=>resolve=done));const pending=h.c.invalidatePurchaseFlow([]);
  if(close)h.close();else h.elements.get('routeBack').onclick();resolve(structuredClone(d));await pending;
  assert.equal(h.reg,null);assert.equal(h.c.guideContext,null);assert.ok(!h.html.includes('routeComparison'));assert.ok(!h.html.includes('registrationInterstitial'));
 }
 const recovered=harness(),d=detail();recovered.open(d);recovered.c.selectPurchaseRoute('direct');recovered.setResult(structuredClone(d));await recovered.c.invalidatePurchaseFlow([{offer_id:'offer-visma',stock:'out_of_stock',recovered_history:true}]);assert.equal(recovered.c.guideContext.invalidated,false);assert.equal(recovered.c.guideContext.quote.offer.stock,'in_stock');
}
function testOfficialRouteHelpIsExactAndSameTab(){
 const h=harness();h.open();const links=h.nodes.filter(node=>node.dataset.routeHelp);assert.equal(links.length,4);
 for(const link of links){const event={target:{closest:()=>link},type:'click',button:0,preventDefault(){this.prevented=true}},url=link.getAttribute('href');h.setAnswer(false);h.c.guardRouteHelpExit(event);assert.ok(event.prevented);const before=h.navigated.length;h.setAnswer(true);h.c.guardRouteHelpExit({...event,type:'auxclick',button:1});assert.equal(h.navigated.length,before+1);assert.equal(h.navigated.at(-1),url);link.setAttribute('href',url+'?tracking=1');h.c.guardRouteHelpExit(event);assert.equal(h.navigated.length,before+1);link.setAttribute('href',url);h.setAnswer(()=>{link.setAttribute('href','https://evil.example/');return true});h.c.guardRouteHelpExit(event);assert.equal(h.navigated.length,before+1)}
}

function domesticQuote(){return quote('decathlon_cn',{source_name:'迪卡侬中国官网',sales_region:'中国大陆 CNY 报价',url:'https://www.decathlon.com.cn/p/test-jersey?size=M',price:{amount:'399.90',currency:'CNY'}})}
async function testDomesticScopeCostsAndExit(){
 const h=harness(),q=domesticQuote(),d=detail(q);d.identity.size='M';
 assert.deepEqual(statuses(h,q),{domestic:'conditional'});assert.equal(h.c.routeOptions(q)[0].total,null);
 assert.ok(h.c.routeOptions(q)[0].costs.some(([label,value])=>label==='国内运费'&&value==='待确认'));
 assert.equal(h.c.routeOptions(quote('visma',{price:{amount:'399.90',currency:'CNY'}})).length,3,'CNY never means domestic');
 for(const extra of [{sales_region:''},{sales_region:'海外 CNY 报价'},{price:{amount:399.90,currency:'USD'}},{price:{amount:null,currency:'CNY'}},
   ...['https://www.decathlon.com.cn.evil.test/p','https://evil.test/p','http://www.decathlon.com.cn/p','https://user@www.decathlon.com.cn/p','https://www.decathlon.com.cn:444/p'].map(url=>({url}))]){
   const bad=structuredClone(q);Object.assign(bad.offer,extra);assert.equal(h.c.routeOptions(bad).length,0);
 }
 h.open(d,{route:'direct'});assert.equal(h.c.guideContext.route,null);assert.equal(h.elements.get('routeContinue').disabled,true);
 assert.equal((h.html.match(/class="route-card"/g)||[]).length,1);
 for(const term of ['中国进口税','清关','海外转运','香港','landed-cost-fixture','route-hk-notes'])assert.ok(!h.html.includes(term),term);
 assert.ok(h.html.includes('CNY 399.90'));assert.ok(h.html.includes('尺码 M'));
 const help=h.c.domesticPaymentMarkup();
 for(const text of ['支付宝','微信','银联','Visa','本件订单可用方式尚未实测','免注册购买未核实','单笔实付满 99 元','未满收 8 元','自行车除外','门店极速达等其他方式另计','2026 年 3 月 18 日','迪卡侬自有品牌','有效购买凭证','非原购买店铺退货以礼品卡退款','原包邮商品只承担退货邮费'])assert.ok(help.includes(text),text);
 assert.ok(/<details class="domestic-shopping-help">/.test(help),'Buying help starts collapsed');
 assert.ok(!/<a\b|href=|<details[^>]*\sopen(?:[\s=>])/.test(help),'Help cannot bypass the final exit or start expanded');
 assert.ok(!/无条件退货|所有地址包邮|已实测可支付|七天无理由|7天无理由/.test(help));
 assert.equal(h.c.routeOptions(q)[0].total,null,'Policy threshold is not a shipping quote');
 assert.ok(h.c.routeOptions(q)[0].costs.some(([label,value])=>label==='国内运费'&&value==='待确认'));

 h.c.selectPurchaseRoute('direct');assert.equal(h.c.guideContext.route,null);
 h.c.selectPurchaseRoute('domestic');h.c.continuePurchaseRoute();
 assert.ok(h.html.includes('id="registrationInterstitial"'));assert.ok(h.html.includes('登录或注册'));assert.ok(!h.html.includes('Account / Sign in'));
 const saved=structuredClone(h.c.history.state.bikehuntPurchase);assert.equal(saved.route,'domestic');
 h.setAnswer(false);h.c.continueRegistrationExit();assert.equal(h.navigated.length,0);assert.equal(h.c.guideContext.route,'domestic');
 h.c.continuePurchaseRoute();h.setAnswer(true);h.c.continueRegistrationExit();assert.deepEqual(h.navigated,[q.offer.url]);
 const restored=harness();restored.c.history.state.bikehuntPurchase=saved;restored.setResult(structuredClone(d));await restored.c.restorePurchaseState();assert.equal(restored.c.guideContext.route,'domestic');assert.ok(restored.html.includes('registrationInterstitial'));
 for(const mutate of [g=>g.quote.offer.sales_region='其他市场',g=>g.quote.offer.source_code='decathlon',g=>g.quote.offer.url='https://evil.test/p',g=>g.quote.offer.price.amount='400',g=>g.quote.offer.price.currency='USD',g=>g.quote.offer.stock='out_of_stock']){
   const x=harness();x.open(detail(domesticQuote()));x.c.selectPurchaseRoute('domestic');x.c.continuePurchaseRoute();x.setAnswer(()=>{mutate(x.c.guideContext);return true});x.c.continueRegistrationExit();assert.equal(x.navigated.length,0);
 }
 const changed=harness();changed.c.history.state.bikehuntPurchase=saved;const changedDetail=structuredClone(d);changedDetail.offers[0].offer.sales_region='其他市场';changed.setResult(changedDetail);await changed.c.restorePurchaseState();assert.equal(changed.c.guideContext.invalidated,true);assert.equal(changed.elements.get('routeContinue').disabled,true);
}

function testDomesticChannelUsesSharedHelp(){
 const h=harness(),book={documents:[]},entry={code:'decathlon_cn',name_zh:'迪卡侬中国官网',source_codes:['decathlon_cn'],official_url:'https://www.decathlon.com.cn/',shop_url:'https://www.decathlon.com.cn/'};
 h.c.paymentDirectoryMarkup=()=>'<div class="payment-matrix-fixture">付款方式矩阵</div>';
 const shared=h.c.domesticPaymentMarkup(),html=h.c.channelInfoMarkup(entry,book);
 assert.ok(html.includes(shared),'Channel must reuse the exact purchase helper');
 assert.ok(html.includes('payment-matrix-fixture')&&html.includes('official-entrances'));
 assert.ok(!html.includes('购买条件暂未确认'));
 assert.ok(/<details class="domestic-shopping-help">/.test(html));
 for(const change of [{code:'decathlon'},{source_codes:undefined},{source_codes:[]},{source_codes:['decathlon']},{source_codes:['decathlon_cn','decathlon']},{source_codes:['decathlon_cn','decathlon_cn']},
   ...['https://www.decathlon.com.cn.evil.test/','http://www.decathlon.com.cn/','https://user@www.decathlon.com.cn/','https://www.decathlon.com.cn:443/','https://www.decathlon.com.cn/?redirect=other','https://www.decathlon.com.cn/#other','https://www.decathlon.com.cn/path','https://www.decathlon.fr/'].flatMap(url=>[{official_url:url},{shop_url:url}])]){
   const invalid=h.c.channelInfoMarkup({...entry,...change},book);
   assert.ok(!invalid.includes('domestic-shopping-help'),JSON.stringify(change));
   assert.ok(invalid.includes('购买条件暂未确认'),JSON.stringify(change));
 }
 const original=h.c.domesticPaymentMarkup;
 h.c.domesticPaymentMarkup=()=>'<div>SHARED_POLICY_SENTINEL</div>';
 assert.ok(h.c.channelInfoMarkup(entry,book).includes('SHARED_POLICY_SENTINEL'),'No duplicate policy copy');
 h.c.domesticPaymentMarkup=undefined;
 assert.ok(h.c.channelInfoMarkup(entry,book).includes('购买条件暂未确认'),'Optional helper failure stays safe');
 h.c.domesticPaymentMarkup=original;
}

async function main(){for(const test of [testDomesticChannelUsesSharedHelp,testDomesticScopeCostsAndExit,testThreeScopedRoutesAndHonestCosts,testRouteSelectionPrecedesRegistration,testSharedConfirmationOnlyAtFinalSameTabExit,testLastKnownStockAndAmazonRegistration,testHistoryRestoresExactVerifiedSelection,testPublicationChangeDisablesBeforeRechecking,testObservedChangesCannotBeOverruledOrResurrectClosedStages,testOfficialRouteHelpIsExactAndSameTab]){await test();console.log('PASS '+test.name)}console.log('Ordered purchase flow: ten production-JavaScript regression groups passed.');}
if(require.main===module)main().catch(error=>{console.error(error);process.exitCode=1});
module.exports={harness,quote,detail,NOW};
