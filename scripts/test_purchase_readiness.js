'use strict';
// Delivery and reference behavior are independent of the dedicated payment matrix.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {installExternalExitStub}=require('./external_exit_test_helper');
const script=fs.readFileSync('web/purchase-readiness.js','utf8'),data=JSON.parse(fs.readFileSync('web/purchase-readiness.json','utf8'));
let navigated=[],open=true,connected=true;
const context={URL,Date,Map,Set,Object,JSON,Number,String,Array,document:{currentScript:{src:'https://example.org/BikeHunt/web/purchase-readiness.js'},addEventListener(){},querySelectorAll:()=>[],getElementById:id=>id==='sheet'?{classList:{contains:()=>open}}:{contains:()=>connected}},window:{location:{assign:url=>navigated.push(url)}},fetch:async()=>({ok:true,text:async()=>JSON.stringify(data)}),saveBrowseState(){}};
const exit=installExternalExitStub(context);vm.createContext(context);vm.runInContext(script.replace(/^loadPurchaseReadiness\(\);$/m,''),context);context.data=data;vm.runInContext('readinessData=validateReadinessData(data);readinessState="ready"',context);
const offer=(code,market='',url)=>({source_code:code,source_name:code,sales_region:market,url,china_issued_card:{status:'unknown'},shipping_to_china:{status:'unknown'},accepted_card_networks:[]});
for(const [code,market] of [['amazon_us','美国站'],['amazon_uk','英国站'],['amazon_de','德国站'],['amazon_jp','日本站']]){
 const row=offer(code,market);assert.ok(context.readinessPolicy(row));assert.equal(context.readinessPolicy({...row,sales_region:'其他站'}),null);assert.equal(context.readinessPolicy({...row,url:'https://evil.example/product'}),null);
 assert.ok(context.readinessContent(row).includes('注册前，先确认能不能买'));
}
const visma=context.readinessContent({...offer('visma','US 市场报价（USD）','https://www.teamvismaleaseabike.com/shop/item/'),price:{amount:100,currency:'USD'},shipping:null});assert.ok(visma.includes('EUR 47.95'));assert.ok(!visma.includes('USD 47.95'));assert.ok(visma.includes('独立于商品币种'));
const maap=context.readinessContent(offer('maap','','https://maap.cc/products/item'));assert.ok(maap.includes('不直邮中国大陆'));assert.ok(maap.includes('优先寻找经官网验证的本地授权渠道'));
const poc=context.readinessContent(offer('poc','Global EN','https://poc.com/en/item'));assert.ok(poc.includes('package forwarding services'));
const pocUS=context.readinessContent(offer('poc','美国站报价','https://poc.com/en-us/item'));assert.ok(pocUS.includes('其他范围的官方参考'));assert.ok(!pocUS.includes('data-readiness-link="myus"'));
for(const code of ['teamcycles','sigmasports','decathlon','rapha_kr','__proto__']){const html=context.readinessContent(offer(code,'中国'));assert.ok(!html.includes('不直邮中国大陆'));assert.ok(!html.includes('EUR 47.95'));assert.ok(!html.includes('data-readiness-link='))}
assert.ok(context.readinessContent(offer('other')).includes('运费待确认'));
assert.ok(context.readinessContent({...offer('visma'),shipping_to_china:{note:'配送原文已变化，正在复核'}}).includes('报价规则待复核'));
// Card-only fields cannot revive stale, incomplete, or another market's payment claims.
for(const status of ['yes','no','unknown'])for(const code of ['maap','visma','amazon_us','teamcycles']){
 const o={...offer(code),china_issued_card:{status,note:'Legacy claim',url:'https://www.teamvismaleaseabike.com/shop-payment/',scope:'offer',checked_at:'2026-10-14T00:00:00Z'},accepted_card_networks:['Legacy Card']};
 for(const html of [context.readinessContent(o),context.paymentFeasibilityMarkup(o)]){assert.ok(html.includes('data-china-card-status="unknown"'));assert.ok(!html.includes('Legacy claim'));assert.ok(!html.includes('Legacy Card'))}
}
for(const mutation of [d=>d.entries[0].sources=['https://evil.example/policy'],d=>d.entries.push(d.entries[0]),d=>d.checkedAt='2026-02-30',d=>d.entries.find(r=>r.sourceCode==='visma').directChina.shippingCurrency=null,d=>d.forwarders[0].calculator='javascript:alert(1)',d=>{d.entries[0].scope='merchant';d.entries[0].salesRegion=null},d=>d.entries[0].merchantHosts=['evil.example']]){const copy=structuredClone(data);mutation(copy);assert.throws(()=>context.validateReadinessData(copy))}
const forwarding=context.forwardingExplainerContent();for(const text of ['US$9.99/月','体积重','长宽高','不低报','税','退件','没有完整含税总价'])assert.ok(forwarding.includes(text));assert.ok(!/CNY.?1000|¥.?1000|￥.?1000/.test(forwarding));
let href=data.forwarders[0].calculator;const link={isConnected:true,dataset:{readinessLink:'myus'},getAttribute:()=>href};const event={target:{closest:()=>link},preventDefault(){},type:'click',button:0};
assert.equal(context.allowedReadinessLink(link),href);exit.setAnswer(false);context.guardReadinessExit(event);assert.equal(navigated.length,0);assert.equal(exit.prompts[0].kind,'reference');exit.setAnswer(true);context.guardReadinessExit(event);assert.deepEqual(navigated,[href]);
for(const extra of [{ctrlKey:true},{shiftKey:true},{metaKey:true},{type:'auxclick',button:1}])context.guardReadinessExit({...event,...extra});assert.equal(navigated.length,5);
const count=navigated.length;for(const bad of ['https://evil.example/',href+'?tag=tracking',href+'#replace','javascript:alert(1)']){href=bad;assert.equal(context.allowedReadinessLink(link),null);context.guardReadinessExit(event);assert.equal(navigated.length,count)}
href=data.forwarders[0].calculator;open=false;assert.equal(context.allowedReadinessLink(link),null);open=true;connected=false;assert.equal(context.allowedReadinessLink(link),null);connected=true;link.isConnected=false;assert.equal(context.allowedReadinessLink(link),null);link.isConnected=true;exit.setAnswer(()=>{href+='?substituted';return true});context.guardReadinessExit(event);assert.equal(navigated.length,count);
vm.runInContext('readinessData=null;readinessState="error"',context);assert.ok(context.readinessContent(offer('visma')).includes('data-china-card-status="unknown"'));assert.ok(!context.readinessContent(offer('visma')).includes('47.95'));
console.log('Readiness passed: scoped delivery and forwarding, honest missing fees, same-tab guarded references, and no legacy card-only payment conclusions.');
