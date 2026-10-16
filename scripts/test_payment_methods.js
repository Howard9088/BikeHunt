'use strict';
// Hermetic validation and display/exit tests. No merchant network is used.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {installExternalExitStub}=require('./external_exit_test_helper');
const catalog=JSON.parse(fs.readFileSync('web/payment-channels.json','utf8'));
const fixture=JSON.parse(fs.readFileSync('tests/fixtures/payment-methods.json','utf8'));
let open=true,inside=true,navigated=[],prevented=0,body='',fetchMode='good';
const c={URL,Date,Map,Set,Object,JSON,Number,String,Array,Promise,console,document:{currentScript:{src:'https://test.example/BikeHunt/web/payment-methods.js'},addEventListener(){},querySelectorAll:()=>[],getElementById:id=>id==='sheet'?{classList:{contains:()=>open}}:{contains:()=>inside}},window:{location:{assign:url=>navigated.push(url)}},saveBrowseState(){},fetch:async url=>({ok:fetchMode==='good',text:async()=>JSON.stringify(url.endsWith('payment-channels.json')?catalog:fixture)})};
const exit=installExternalExitStub(c);vm.createContext(c);
vm.runInContext(fs.readFileSync('web/payment-methods.js','utf8').replace(/^loadPaymentMethods\(\);$/m,''),c);
c.catalog=catalog;c.fixture=fixture;
vm.runInContext('paymentChannels=validatePaymentChannels(catalog);paymentData=validatePaymentData(fixture,paymentChannels);paymentState="ready"',c);
const clone=x=>JSON.parse(JSON.stringify(x));
function offer(code,extra={}){const row=catalog.channels.find(x=>x.source_code===code),child=fixture.entries.find(x=>x.source_code===code)?.channels?.[0];return {source_code:code,source_name:row?.merchant_name,sales_region:row?.sales_regions[0],url:child?.scope_evidence_urls[0]||row?.base_url,china_issued_card:{status:'yes'},accepted_card_networks:['Legacy unsupported network'],...extra}}
assert.equal(catalog.channels.length,37);
// The China official store is a separate exact market, never the French team shop.
function assertChinaStore(data){
 const channel=catalog.channels.find(r=>r.source_code==='decathlon_cn');
 assert.deepEqual(channel.sales_regions,['中国大陆 CNY 报价']);
 assert.deepEqual(channel.merchant_hosts,['www.decathlon.com.cn','decathlon.com.cn']);
 assert.equal(channel.base_url,'https://www.decathlon.com.cn/');
 const row=data.entries.find(r=>r.source_code==='decathlon_cn');assert.ok(row);
 assert.equal(row.scope,'market');assert.equal(row.sales_region,'中国大陆 CNY 报价');
 assert.deepEqual(row.merchant_hosts,channel.merchant_hosts);
 assert.deepEqual(row.methods.map(m=>m.method_key).sort(),['cards','china_issued_cards','paypal','apple_pay','google_pay','alipay','wechat_pay','unionpay','bank_transfer_local','gift_cards','instalments'].sort());
 for(const method of row.methods){
  const listed=['cards','china_issued_cards','alipay','wechat_pay','unionpay'].includes(method.method_key);
  assert.equal(method.status,listed?'conditional':'unknown');assert.equal(method.china_applicability.status,'unknown');
  assert.equal(method.merchant_evidence_status,listed?'official_text':'unavailable');
  assert.deepEqual(method.evidence_urls,listed?['https://www.decathlon.com.cn/help/introduction']:[]);
  assert.equal(method.checked_at,listed?'2026-10-16':null);assert.ok(method.note.trim());assert.ok(method.account_region_constraints.trim());
  if(listed){assert.equal(method.evidence_class,'official_confirmed');assert.ok(method.note.includes('官方帮助'));assert.ok(method.note.includes('未实测'));}
  if(method.method_key==='cards')assert.deepEqual(method.card_networks,['Visa']);
 }
 assert.ok(data.entries.some(r=>r.source_code==='decathlon'),'The existing French team merchant remains separately covered');
}
assertChinaStore(fixture);

const correctedMerchants=[
 ['movistar','gobik.com','US 市场 · EUR 报价；未验证其他市场库存','https://www.tradeinn.com/bikeinn/es/movistar_team'],
 ['jayco','maap.cc','MAAP国际站；以逐规格实际币种报价为准，配送另核','https://shop.greenedgecycling.com/'],
 ['colnago','www.colnago.com','US 市场 · USD 商品报价；配送另核','https://www.colnago.com/en-cn/']
];
for(const [code,host,market,oldUrl] of correctedMerchants){
 const row=c.paymentPolicy(offer(code));assert.ok(row,code);
 assert.equal(row.sales_region,market);assert.ok(row.merchant_hosts.includes(host));
 assert.equal(c.paymentPolicy(offer(code,{sales_region:'unrelated market'})),null);
 if(code!=='colnago')assert.equal(c.paymentPolicy(offer(code,{url:oldUrl})),null,'A team name cannot authorize the old retailer');
 assert.equal(c.paymentPolicy(offer(code,{url:'https://'+host+'.evil.example/'})),null);
 assert.equal(c.paymentMethodsFor(offer(code)).length,11);
}

assert.equal(c.paymentPolicy(offer('decathlon_cn')).source_code,'decathlon_cn');
assert.equal(c.paymentPolicy(offer('decathlon_cn',{url:'https://shop.decathloncmacgmteam.com/'})),null);
assert.equal(c.paymentPolicy(offer('decathlon_cn',{sales_region:'法国站 EUR 报价'})),null);

for(const channel of catalog.channels){
 const o=offer(channel.source_code),before=JSON.stringify(o),html=c.paymentMethodsMarkup(o);
 assert.ok(c.paymentPolicy(o));assert.equal(c.paymentMethodsFor(o).length,11);
 for(const name of ['PayPal','Apple Pay','Google Pay','支付宝','微信','银联','礼品卡','分期'])assert.ok(html.includes(name),channel.source_code+' '+name);
 assert.ok(html.includes(channel.source_code==='decathlon_cn'?'中国发行卡：有条件，先核对发卡与账户限制':'中国发行卡：待核实'));assert.ok(html.includes('不保证'));assert.ok(!html.includes('Legacy unsupported network'));
 assert.equal(JSON.stringify(o),before,'No source offer or eligibility mutations');
 assert.equal(c.paymentPolicy({...o,sales_region:'another market'}),null);assert.equal(c.paymentPolicy({...o,url:'https://wrong.example/product'}),null);assert.equal(c.paymentPolicy({...o,url:undefined}),null);
}
assert.equal(c.paymentPolicy(offer('maap',{sales_region:''})).source_code,'maap');
assert.equal(c.paymentPolicy(offer('rapha',{sales_region:'韩国站报价'})),null);
assert.equal(c.paymentPolicy(offer('teamcycles',{identity:{brand:'MAAP'}})).source_code,'teamcycles');
assert.equal(c.paymentPolicy(offer('__proto__')),null);
assert.equal(c.paymentSummary(offer('poc')).status,'unknown','UnionPay support is not proof of China issuer approval');
let html=c.paymentMethodsMarkup(offer('maap'));assert.ok(html.includes('data-payment-status="not_supported"'));assert.ok(!html.includes('仅有历史官方资料'));
assert.ok(c.paymentMethodsMarkup(offer('visma')).includes('需符合资格的境外账户'));assert.ok(!c.paymentMethodsMarkup(offer('visma')).includes('requires_eligible_foreign_account'));
for(const code of ['amazon_de','amazon_jp'])assert.ok(c.paymentMethodsMarkup(offer(code)).includes('历史资料，当前待核实'));
for(const code of ['oakley','alpecin','lidl_trek','movistar','jayco','unox','astana'])assert.ok(c.paymentDirectoryContent({code}).includes('data-payment-method-key="wechat_pay"'));
assert.ok(c.paymentDirectoryContent({code:'rapha'}).includes('日本站报价'));assert.ok(c.paymentDirectoryContent({code:'rapha'}).includes('韩国站报价'));
assert.ok(c.paymentDirectoryContent({code:'ef'}).includes('EF'));
for(const mutation of [
 d=>d.entries[0].methods.pop(),d=>d.entries[0].methods[0].note='',d=>d.entries[0].methods[0].status='yes',
 d=>d.entries.push(d.entries[0]),d=>d.entries[0].methods.push(d.entries[0].methods[0]),d=>d.checked_at='2030-01-01',d=>d.checked_at='2026-02-30',
 d=>d.entries[0].merchant_hosts=['evil.example'],d=>d.entries[0].sales_region='Australia',d=>d.entries[0].scope='merchant',
 d=>d.entries[0].methods[2].evidence_urls=['https://evil.example/'],d=>d.entries[0].methods[2].evidence_urls=[],
 d=>d.entries[0].methods[2].checked_at=null,d=>d.entries[0].methods[0].evidence_urls=['javascript:alert(1)'],
 d=>d.entries[0].merchant_evidence_status='official_icons_only',d=>d.entries[0].merchant_evidence_status='unavailable',
 d=>d.entries[0].merchant_evidence_status='historical_official',d=>d.entries[0].methods[2].merchant_evidence_status='official_icons_only'
]){const bad=clone(fixture);mutation(bad);assert.throws(()=>c.validatePaymentData(bad,catalog))}
const merchant=clone(fixture);merchant.entries[0].scope='merchant';merchant.entries[0].sales_region=null;merchant.entries[0].scope_evidence_urls=['https://support.maap.cc/fixture-wide-policy'];assert.equal(c.validatePaymentData(merchant,catalog),merchant);
const icon=clone(fixture);icon.entries[0].merchant_evidence_status='official_icons_only';icon.entries[0].methods.forEach(m=>{if(m.status!=='unknown')m.status='conditional'});assert.equal(c.validatePaymentData(icon,catalog),icon);
const undated=clone(fixture);undated.entries[0].methods[0].checked_at=null;assert.equal(c.validatePaymentData(undated,catalog),undated);
// A directory's two trading merchants are never collapsed into one supported list.
assert.equal(c.paymentPolicy(offer('alpecin',{url:'https://www.alpecin-premiertech.com/webshops/'})),null);
assert.equal(c.paymentPolicy(offer('alpecin',{url:'https://shops.topfanz.com/fixture'})).methods.find(m=>m.method_key==='gift_cards').status,'unknown');
assert.equal(c.paymentPolicy(offer('alpecin',{url:'https://www.kalas.cc/fixture'})).methods.find(m=>m.method_key==='gift_cards').status,'supported');
assert.equal((c.paymentDirectoryContent({code:'alpecin'}).match(/class="payment-separate-merchant"/g)||[]).length,2);
const crossed=clone(fixture),topfanz=crossed.entries.find(r=>r.source_code==='alpecin').channels[0];topfanz.methods[0].evidence_urls=['https://www.kalas.cc/fixture-policy'];assert.throws(()=>c.validatePaymentData(crossed,catalog));
// Third-party-hosted logos require the exact reviewed asset and its owning official page.
const assetData=clone(fixture),ef=assetData.entries.find(r=>r.source_code==='ef_team_shop'),asset=catalog.channels.find(r=>r.source_code==='ef_team_shop').reference_assets[0];
ef.methods[0].status='conditional';ef.methods[0].merchant_evidence_status='official_icons_only';ef.methods[0].evidence_urls=[asset.owner_page,asset.url];assert.equal(c.validatePaymentData(assetData,catalog),assetData);
ef.methods[0].evidence_urls=[asset.url];assert.throws(()=>c.validatePaymentData(assetData,catalog));ef.methods[0].evidence_urls=[asset.owner_page,asset.url+'&tampered=1'];assert.throws(()=>c.validatePaymentData(assetData,catalog));
// Exact reference links retain the shared same-tab confirmation and live binding.
html=c.paymentMethodsMarkup(offer('maap'));const id=html.match(/data-payment-context="(\d+)"/)[1],method=fixture.entries[0].methods.find(m=>m.method_key==='paypal');
let href=method.evidence_urls[0];const link={isConnected:true,dataset:{paymentLink:id,paymentMethod:'paypal',paymentEvidence:'0'},getAttribute:()=>href};
const event={type:'click',button:0,target:{closest:()=>link},preventDefault(){prevented++}};
assert.equal(c.allowedPaymentLink(link).url,href);exit.setAnswer(false);c.guardPaymentExit(event);assert.equal(navigated.length,0);assert.equal(exit.prompts[0].kind,'reference');
exit.setAnswer(true);for(const extra of [{},{ctrlKey:true},{metaKey:true},{shiftKey:true},{type:'auxclick',button:1}])c.guardPaymentExit({...event,...extra});assert.equal(navigated.length,5);
for(const bad of [href+'?replace=1',href+'#replace','javascript:alert(1)','https://wrong.example/']){href=bad;assert.equal(c.allowedPaymentLink(link),null)}
href=method.evidence_urls[0];open=false;assert.equal(c.allowedPaymentLink(link),null);open=true;inside=false;assert.equal(c.allowedPaymentLink(link),null);inside=true;link.isConnected=false;assert.equal(c.allowedPaymentLink(link),null);link.isConnected=true;
const count=navigated.length;exit.setAnswer(()=>{href+='?changed';return true});c.guardPaymentExit(event);assert.equal(navigated.length,count);
// Research content is text, never markup.
const malicious=clone(fixture);malicious.entries[0].methods[0].note='<img src=x onerror=alert(1)>';c.malicious=malicious;vm.runInContext('paymentData=validatePaymentData(malicious,paymentChannels)',c);assert.ok(!c.paymentMethodsMarkup(offer('maap')).includes('<img'));assert.ok(c.paymentMethodsMarkup(offer('maap')).includes('&lt;img'));
vm.runInContext('paymentData=null;paymentState="error"',c);html=c.paymentMethodsMarkup(offer('maap'));assert.equal((html.match(/data-payment-status="unknown"/g)||[]).length,11);assert.ok(html.includes('支付说明暂时无法加载'));assert.ok(!html.includes('读取或校验'));assert.ok(!html.includes('旧卡种字段'));assert.ok(!html.includes('data-payment-link='));
// An unavailable payment matrix cannot alter established route restrictions.
vm.runInContext(fs.readFileSync('web/purchase-readiness.js','utf8').replace(/^loadPurchaseReadiness\(\);$/m,''),c);c.shipping=JSON.parse(fs.readFileSync('web/purchase-readiness.json','utf8'));vm.runInContext('readinessData=validateReadinessData(shipping);readinessState="ready"',c);assert.ok(c.readinessContent(offer('maap')).includes('不直邮中国大陆'));assert.ok(!c.paymentFeasibilityMarkup(offer('maap')).includes('Legacy unsupported network'));
if(!process.argv.includes('--fixtures-only')){
 const production=JSON.parse(fs.readFileSync('web/payment-methods.json','utf8'));c.validatePaymentData(production,catalog);assertChinaStore(production);
 assert.equal(production.entries.length,37,'Release must cover all 37 current channels, including zero-offer directories');
 for(const channel of catalog.channels)assert.ok(production.entries.some(r=>r.source_code===channel.source_code&&(r.scope==='merchant'||channel.sales_regions.includes(r.sales_region))));
}

// Explicit merchant-wide rejection must not acquire a contradictory China uncertainty suffix.
assert.equal(c.paymentChinaLabel({status:'not_supported',note:'官网明确不接受此方式。',evidence_class:'insufficient_evidence'}),'官方明确不支持。官网明确不接受此方式。');
assert.ok(c.paymentChinaLabel({status:'unknown',note:'中国账户适用性未核实。',evidence_class:'insufficient_evidence'}).includes('依据不足'));
assert.ok(c.paymentChinaLabel({status:'not_supported',note:'官方限制。',evidence_class:'explicitly_unsupported'}).includes('官方明确限制'));
assert.equal(c.paymentDisplayText('cash_on_delivery'),'货到付款');
assert.ok(!c.paymentChinaLabel({status:'unknown',note:'requires_eligible_foreign_account'}).includes('requires_'));
assert.equal(c.paymentDisplayText('记录 observed_market=JP/JPY'),'记录 本次观察为日本站／日元报价');
console.log('Payment matrix passed: complete method categories, exact merchant/market scope, China issuer independence, honest missing evidence, source-directory coverage, escaped text, and guarded official links.');
