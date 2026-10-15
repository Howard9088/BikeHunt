'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const script=fs.readFileSync('web/purchase-readiness.js','utf8'),data=JSON.parse(fs.readFileSync('web/purchase-readiness.json','utf8'));
let navigated=[],prevented=0,confirmations=0,open=true,connected=true,callbacks=[];
const context={URL,Date,Map,Set,Object,JSON,Number,String,Array,document:{currentScript:{src:'https://example.org/BikeHunt/web/purchase-readiness.js'},addEventListener:(...args)=>callbacks.push(args),querySelectorAll:()=>[],getElementById:id=>id==='sheet'?{classList:{contains:()=>open}}:{contains:()=>connected}},window:{confirm:()=>{confirmations++;return false},location:{assign:url=>navigated.push(url)}},fetch:async()=>({ok:true,text:async()=>JSON.stringify(data)}),PURCHASE_DISCLAIMER:'disclaimer',saveBrowseState:()=>{}};
vm.createContext(context);vm.runInContext(script,context);
assert.equal(context.validateReadinessData(data),data);
vm.runInContext('readinessData=validateReadinessData('+JSON.stringify(data)+');readinessState="ready"',context);
assert.equal(callbacks.length,2);
const before=JSON.stringify(data);
const offer=(code,market='',url)=>({source_code:code,source_name:code,sales_region:market,url,china_issued_card:{status:'unknown'},shipping_to_china:{status:'unknown'},accepted_card_networks:[]});
for(const [code,market] of [['amazon_us','美国站'],['amazon_uk','英国站'],['amazon_de','德国站'],['amazon_jp','日本站']]){
 const row=offer(code,market);let html=context.purchaseReadinessMarkup(row);
 assert.ok(html.includes('注册前，先确认能不能买'));assert.ok(html.includes('data-china-card-status="conditional"'));assert.ok(!html.includes('data-china-card-status="evidence"'));assert.ok(html.includes('2026-10-15'));assert.ok(html.includes('不能保证底层卡成功'));
 assert.ok(context.readinessPolicy(row));assert.equal(context.readinessPolicy({...row,sales_region:'其他站'}),null);assert.equal(context.readinessPolicy({...row,url:'https://evil.example/product'}),null);
 if(['amazon_de','amazon_jp'].includes(code))assert.ok(html.includes('仅有历史官方资料，当前方式待重新核实'));
}
let visma=context.readinessContent({...offer('visma','US 市场报价（USD）','https://www.teamvismaleaseabike.com/shop/item/'),price:{amount:100,currency:'USD'},shipping:null});
assert.ok(visma.includes('EUR 47.95'));assert.ok(!visma.includes('USD 47.95'));assert.ok(visma.includes('独立于商品币种'));
let maap=context.readinessContent(offer('maap','', 'https://maap.cc/products/item'));
assert.ok(maap.includes('官网规则：不直邮中国大陆'));assert.ok(maap.includes('优先寻找经官网验证的本地授权渠道'));assert.ok(!maap.includes('data-readiness-link="myus"'));
let poc=context.readinessContent(offer('poc','Global EN','https://poc.com/en/item'));
assert.ok(poc.includes('package forwarding services'));assert.ok(poc.includes('不直邮中国大陆'));
let pocUS=context.readinessContent(offer('poc','美国站报价','https://poc.com/en-us/item'));
assert.ok(pocUS.includes('其他范围的官方参考'));assert.ok(pocUS.includes('data-china-card-status="unknown"'));assert.ok(!pocUS.includes('data-china-card-status="conditional"'));assert.ok(!pocUS.includes('data-readiness-link="myus"'));
for(const code of ['teamcycles','sigmasports','decathlon','rapha_kr','__proto__']){
 const html=context.readinessContent({...offer(code,'中国'),identity:{brand:'MAAP'},accepted_card_networks:['Visa']});
 assert.ok(html.includes('data-china-card-status="unknown"'));assert.ok(!html.includes('不直邮中国大陆'));assert.ok(!html.includes('EUR 47.95'));assert.ok(!html.includes('data-readiness-link='));assert.ok(html.includes('完整适用范围待核实'));
}
const unknown=context.readinessContent(offer('other'));assert.ok(unknown.includes('运费待确认'));assert.ok(unknown.includes('不等于 0'));
const no=context.readinessContent({...offer('visma'),china_issued_card:{status:'no',note:'Issuer unsupported'}});assert.ok(no.includes('data-china-card-status="no"'));
const invalidYes=context.readinessContent({...offer('visma'),china_issued_card:{status:'yes',scope:'offer',url:'https://evil.example',checked_at:'2026-10-15'}});assert.ok(!invalidYes.includes('data-china-card-status="evidence"'));
const validEvidence={status:'yes',scope:'offer',url:'https://www.teamvismaleaseabike.com/shop-payment/',checked_at:'2026-10-14T00:00:00Z'};
assert.ok(context.readinessContent({...offer('visma'),china_issued_card:validEvidence}).includes('data-china-card-status="evidence"'));
for(const date of ['2030-01-01T00:00:00Z','2026-02-30T00:00:00Z','2026-10-14T24:00:00Z','2026-10-14'])assert.ok(!context.readinessContent({...offer('visma'),china_issued_card:{...validEvidence,checked_at:date}}).includes('data-china-card-status="evidence"'));
assert.ok(!context.readinessContent({...offer('visma'),china_issued_card:{...validEvidence,note:'原文已变化'}}).includes('data-china-card-status="evidence"'));
assert.ok(!context.readinessContent({...offer('visma'),china_issued_card:{...validEvidence,scope:'site'}}).includes('data-china-card-status="evidence"'));
const changed=context.readinessContent({...offer('visma'),card_networks_evidence:{note:'支付原文已变化，正在复核'}});assert.ok(changed.includes('data-china-card-status="unknown"'));assert.ok(changed.includes('报价规则待复核'));
const bad=structuredClone(data);bad.entries[0].payment.chinaIssuedCard='confirmed';assert.throws(()=>context.validateReadinessData(bad));
for(const mutation of [d=>d.entries[0].sources=['https://evil.example/policy'],d=>d.entries.push(d.entries[0]),d=>d.checkedAt='2026-02-30',d=>d.entries.find(r=>r.sourceCode==='visma').directChina.shippingCurrency=null,d=>d.forwarders[0].calculator='javascript:alert(1)',d=>{d.entries[0].scope='merchant';d.entries[0].salesRegion=null},d=>d.entries[0].merchantHosts=['evil.example','www.evil.example']]){const copy=structuredClone(data);mutation(copy);assert.throws(()=>context.validateReadinessData(copy))}
const forwarding=context.forwardingExplainerContent();for(const text of ['US$9.99/月','体积重','长宽高','不低报','税','退件','没有完整含税总价'])assert.ok(forwarding.includes(text));assert.ok(!/CNY.?1000|¥.?1000|￥.?1000/.test(forwarding));
for(const row of data.forwarders){assert.ok(forwarding.includes(row.calculator));assert.equal(new URL(row.calculator).protocol,'https:')}
let href=data.forwarders[0].calculator;
const link={isConnected:true,dataset:{readinessLink:'myus'},getAttribute:()=>href};
const event={target:{closest:()=>link},preventDefault:()=>prevented++,type:'click',button:0};
assert.equal(context.allowedReadinessLink(link),href);
context.guardReadinessExit(event);assert.equal(navigated.length,0);
context.window.confirm=()=>true;context.guardReadinessExit(event);assert.deepEqual(navigated,[href]);
for(const options of [{ctrlKey:true},{shiftKey:true},{metaKey:true},{type:'auxclick',button:1}])context.guardReadinessExit({...event,...options});assert.equal(navigated.length,5);
const count=navigated.length;
for(const badUrl of ['https://evil.example/',href+'?tag=tracking',href+'#replace','javascript:alert(1)']){href=badUrl;assert.equal(context.allowedReadinessLink(link),null);context.guardReadinessExit(event);assert.equal(navigated.length,count)}
href=data.forwarders[0].calculator;open=false;assert.equal(context.allowedReadinessLink(link),null);open=true;connected=false;assert.equal(context.allowedReadinessLink(link),null);connected=true;link.isConnected=false;assert.equal(context.allowedReadinessLink(link),null);link.isConnected=true;
context.window.confirm=()=>{href+='?substituted';return true};context.guardReadinessExit(event);assert.equal(navigated.length,count);
assert.equal(JSON.stringify(data),before,'No offer, cost engine or policy mutations');
// The first purchase stage is compact payment feasibility, never account help.
for(const code of ['visma','maap','poc','teamcycles']){
 const html=context.paymentFeasibilityMarkup(offer(code,code==='poc'?'Global EN':''));
 assert.ok(html.includes('class="payment-feasibility"'));assert.ok(html.includes('中国发行卡'));assert.ok(html.includes('不保证'));assert.ok(!/<(?:form|input|select|textarea|iframe|img|a|details)\b/.test(html));assert.ok(!html.includes('registration-help'));assert.ok(!html.includes('purchase-readiness'));
 assert.ok(html.includes('data-china-card-status="'+(code==='teamcycles'?'unknown':'conditional')+'"'));
}
for(const code of ['amazon_de','amazon_jp'])assert.ok(context.paymentFeasibilityContent(offer(code,code==='amazon_de'?'德国站':'日本站')).includes('历史官方资料'));
assert.ok(context.paymentFeasibilityContent({...offer('visma'),china_issued_card:{status:'no'}}).includes('data-china-card-status="no"'));
assert.ok(context.paymentFeasibilityContent({...offer('visma'),china_issued_card:validEvidence}).includes('data-china-card-status="evidence"'));
assert.ok(context.paymentFeasibilityContent({...offer('visma'),china_issued_card:{...validEvidence,checked_at:'2030-01-01T00:00:00Z'}}).includes('data-china-card-status="conditional"'));
assert.ok(context.paymentFeasibilityContent({...offer('visma'),card_networks_evidence:{note:'原文已变化'}}).includes('data-china-card-status="unknown"'));
assert.ok(context.paymentFeasibilityContent(offer('visma','US','https://evil.example/product')).includes('data-china-card-status="unknown"'));
const flows=fs.readFileSync('web/flows.js','utf8'),gallery=fs.readFileSync('web/gallery.js','utf8');
assert.ok(flows.includes('entry.offers.push(o)'));assert.ok(flows.includes('paymentFeasibilityMarkup({source_code:market.code'));
assert.ok(gallery.includes('paymentFeasibilityMarkup(q.offer)'));assert.ok(gallery.includes('paymentFeasibilityMarkup(o)'));
assert.ok(!gallery.includes('purchaseReadinessMarkup('));
assert.ok(!flows.includes('purchaseReadinessMarkup('));
assert.ok(!gallery.includes('对应卡种可按此条件使用'));
vm.runInContext('readinessData=null;readinessState="error"',context);assert.ok(context.readinessContent(offer('visma')).includes('data-china-card-status="unknown"'));assert.ok(!context.readinessContent(offer('visma')).includes('47.95'));assert.ok(!context.readinessContent({...offer('visma'),china_issued_card:validEvidence}).includes('data-china-card-status="evidence"'));assert.ok(context.paymentFeasibilityContent(offer('visma')).includes('data-china-card-status="unknown"'));assert.ok(context.paymentFeasibilityContent({...offer('visma'),china_issued_card:validEvidence}).includes('data-china-card-status="unknown"'),'Policy failure cannot upgrade compact card evidence');
console.log('Purchase readiness passed: exact merchant/market scopes, conditional Chinese card status, no global brand mapping, dated historical Amazon policies, EUR shipping, MAAP/POC restrictions, honest forwarding costs, safe same-tab exits and unavailable-data fallback.');
