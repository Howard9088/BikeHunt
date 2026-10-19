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
for(const code of ['unmapped_shop','unmapped_other','__proto__']){const html=context.readinessContent(offer(code,'中国'));assert.ok(!html.includes('不直邮中国大陆'));assert.ok(!html.includes('EUR 47.95'));assert.ok(!html.includes('data-readiness-link='))}
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
// Newly verified policies match exact merchant and observed quote market.
const cnOffer=offer('decathlon_cn','中国大陆 CNY 报价','https://www.decathlon.com.cn/product-detail?dsm_code=367685');
const cnHtml=context.readinessContent(cnOffer);
for(const word of ['官网支持中国大陆配送','未满 99 元收 8 元','港澳台','不套用境外进口税估算'])assert.ok(cnHtml.includes(word));
assert.ok(!cnHtml.includes('进口税、清关和银行卡费用未齐全'));
assert.equal(context.readinessPolicy({...cnOffer,sales_region:'US 市场'}),null);
const jaycoHtml=context.readinessContent(offer('jayco','MAAP国际站；以逐规格实际币种报价为准，配送另核','https://maap.cc/products/team'));
for(const word of ['不直邮中国大陆','香港','墨尔本','关税'])assert.ok(jaycoHtml.includes(word));
assert.equal(context.readinessPolicy(offer('jayco','','https://shop.greenedgecycling.com/item')),null);
const colOffer=offer('colnago','US 市场 · USD 商品报价；配送另核','https://www.colnago.com/en-us/products/jersey');
const colHtml=context.readinessContent(colOffer);
for(const word of ['14 天','15 天','美国市场报价','重新确认','顾客承担','未验证游客结账'])assert.ok(colHtml.includes(word));
assert.equal(context.readinessPolicy({...colOffer,sales_region:'中国区 CNY'}),null);
assert.ok(!colHtml.includes('官网列中国配送；'));
assert.ok(!colHtml.includes('Visa'));
for(const code of ['decathlon_cn','jayco','colnago']){
 const row=data.entries.find(e=>e.sourceCode===code);assert.equal(row.checkedAt,'2026-10-16');
 for(const url of row.sources)assert.equal(context.readinessUrl(url,code),true);
}
// Reference fallbacks and external-exit notes retain each policy's own date.
assert.equal(context.readinessSourceDate('colnago','https://www.colnago.com/countries'),'2026-10-16');
assert.equal(context.readinessSourceDate('myus',data.forwarders[0].calculator),data.checkedAt);
const colOther=context.readinessContent({...colOffer,sales_region:'中国区 CNY'});assert.ok(colOther.includes('核对 2026-10-16'));
let capturedExit=null;context.showExternalExit=opts=>{capturedExit=opts};
const datedLink={isConnected:true,dataset:{readinessLink:'colnago'},getAttribute:()=> 'https://www.colnago.com/countries',textContent:'官方来源'};
context.guardReadinessExit({target:{closest:()=>datedLink},preventDefault(){},type:'click',button:0});
assert.ok(capturedExit.sourceNote.includes('2026-10-16'));
const badDate=structuredClone(data);badDate.entries.find(e=>e.sourceCode==='colnago').checkedAt='2026-02-30';assert.throws(()=>context.validateReadinessData(badDate));
const missingDate=structuredClone(data);delete missingDate.entries.find(e=>e.sourceCode==='colnago').checkedAt;assert.doesNotThrow(()=>context.validateReadinessData(missingDate));
vm.runInContext('readinessData=null;readinessState="error"',context);assert.ok(context.readinessContent(offer('visma')).includes('data-china-card-status="unknown"'));assert.ok(!context.readinessContent(offer('visma')).includes('47.95'));
console.log('Readiness passed: scoped delivery and forwarding, honest missing fees, same-tab guarded references, and no legacy card-only payment conclusions.');
// Directory summaries never fabricate an exact offer market or trust injected links.
vm.runInContext('readinessData=validateReadinessData(data);readinessState="ready"',context);
const directoryEntry={code:'colnago',source_codes:['colnago'],shop_url:'https://www.colnago.com/en-us/collections/cycling-apparel-for-men'};
const directoryHtml=context.readinessDirectoryMarkup(directoryEntry);
for(const text of ['指定市场参考','US 市场','目录未提供精确报价市场','14 天','15 天','2026-10-16','已核官网说明'])assert.ok(directoryHtml.includes(text));
for(const shop_url of ['', 'https://evil.example/', 'http://www.colnago.com/', 'https://user@www.colnago.com/'])assert.equal(context.readinessDirectoryMarkup({...directoryEntry,shop_url}),'');
assert.equal(context.readinessDirectoryMarkup({...directoryEntry,source_codes:['other']}),'');
assert.equal(context.readinessDirectoryMarkup({code:'jayco',shop_url:'https://shop.greenedgecycling.com/'}),'');
assert.ok(context.readinessDirectoryMarkup({code:'jayco',shop_url:'https://maap.cc/'}).includes('商家范围'));
assert.equal(context.readinessDirectoryRows({code:'both',source_codes:['maap','jayco'],shop_url:'https://maap.cc/'}).length,2);
const directoryUrl='https://www.colnago.com/countries';
let directoryHref=directoryUrl;
const directoryLink={isConnected:true,dataset:{readinessLink:'colnago'},getAttribute:()=>directoryHref};
const emptyRules={hidden:false};let directoryLinks=[directoryLink];
const slot={innerHTML:'',querySelectorAll:()=>directoryLinks,contains:link=>directoryLinks.includes(link)};
const panel={open:true,hidden:false,dataset:{source:'colnago',loaded:'yes'},querySelector:selector=>selector==='[data-directory-readiness]'?slot:emptyRules,contains:node=>node===slot};
context.activeSource='colnago';context.activeTab='products';context.directoryData={brands:[directoryEntry],teams:[]};
const previousGet=context.document.getElementById;
context.document.getElementById=id=>id==='channelInfo'?panel:id==='sheet'?{classList:{contains:()=>false}}:id==='sheetBody'?{contains:()=>false}:previousGet(id);
assert.equal(context.allowedReadinessLink(directoryLink),null);
context.refreshDirectoryReadiness();
assert.ok(slot.innerHTML.includes('14 天'));assert.equal(emptyRules.hidden,true);
assert.equal(context.allowedReadinessLink(directoryLink),directoryUrl);
const injected={...directoryLink};assert.equal(context.allowedReadinessLink(injected),null);
for(const mutate of [()=>panel.open=false,()=>panel.hidden=true,()=>context.activeSource='maap',()=>context.activeTab='brands',()=>panel.dataset.source='maap',()=>panel.dataset.loaded='loading',()=>directoryEntry.shop_url='https://evil.example/',()=>directoryHref=directoryUrl+'?changed',()=>directoryLink.dataset.readinessLink='maap']){
 mutate();assert.equal(context.allowedReadinessLink(directoryLink),null);
 panel.open=true;panel.hidden=false;context.activeSource='colnago';context.activeTab='products';panel.dataset.source='colnago';panel.dataset.loaded='yes';directoryEntry.shop_url='https://www.colnago.com/';directoryHref=directoryUrl;directoryLink.dataset.readinessLink='colnago';
}
context.showExternalExit=opts=>{capturedExit=opts};
context.guardReadinessExit({target:{closest:()=>directoryLink},preventDefault(){},type:'click',button:0});assert.ok(capturedExit.sourceNote.includes('2026-10-16'));assert.equal(capturedExit.validate(),true);panel.open=false;assert.equal(capturedExit.validate(),false);panel.open=true;
vm.runInContext('readinessData=null;readinessState="loading"',context);context.refreshDirectoryReadiness();assert.equal(slot.innerHTML,'');assert.equal(emptyRules.hidden,false);
vm.runInContext('readinessData=validateReadinessData(data);readinessState="ready"',context);context.refreshReadinessMarkup();assert.ok(slot.innerHTML.includes('15 天'));assert.equal(emptyRules.hidden,true);
console.log('Directory readiness passed: scoped references, async refresh, dated evidence, exact merchant matching, and registered current-panel links only.');

// Second policy batch is bound to observed markets, never a purchase or issuer guarantee.
for(const [code,market,host,words] of [
 ['uae','US / USD 报价','www.pissei.com',['USA AND UK','不能外推中国','14 天','游客']],
 ['fizik','US 市场 · USD 报价；未验证其他市场库存','www.fizik.com',['15 天','购买日期','全订单免运','不证明当前商品单价']],
 ['santini','IT 市场 · EUR 报价；未验证其他市场库存','www.santinicycling.com',['45 天','14 天','仅限欧盟','意大利仓']],
 ['lidl_trek','IT 市场 · EUR 报价；未验证其他市场库存','www.santinicycling.com',['45 天','初始运费不退','us.santinicycling.com']]
]){
 const quote=offer(code,market,'https://'+host+'/products/example'),before=JSON.stringify(quote);
 const row=context.readinessPolicy(quote);assert.ok(row);assert.equal(row.scope,'market');assert.equal(row.checkedAt,'2026-10-16');
 assert.equal(row.payment.chinaIssuedCard,'unknown');assert.equal(row.directChina.status,'conditional_checkout');assert.equal(row.directChina.shippingAmount,undefined);
 assert.equal(context.readinessPolicy({...quote,sales_region:'中国市场'}),null);
 assert.equal(context.readinessPolicy({...quote,url:'https://evil.example/product'}),null);
 const html=context.readinessContent(quote);for(const word of words)assert.ok(html.includes(word),code+': '+word);
 assert.ok(html.includes('data-china-card-status="unknown"'));assert.ok(!html.includes('官网列中国配送；'));
 assert.equal(JSON.stringify(quote),before);
 const directory=context.readinessDirectoryMarkup({code,source_codes:[code],shop_url:'https://'+host+'/'});
 assert.ok(directory.includes('指定市场参考'));assert.ok(directory.includes('目录未提供精确报价市场'));for(const word of words)assert.ok(directory.includes(word));
 for(const url of row.sources)assert.equal(context.readinessUrl(url,code),true);
}
assert.equal(data.checkedAt,'2026-10-15');
console.log('Second batch passed: four exact-market policies, dated conflict visibility, unchanged offers/costs, and no China-issued-card guarantee.');

// Gobik and Alé destination policies cannot upgrade an unverified mainland order.
for(const [code,market,host,words] of [
 ['movistar','US 市场 · EUR 报价；未验证其他市场库存','gobik.com',['低于 €150','达到 €150','下单起 45 个自然日','不是收货起','未列中国大陆']],
 ['bahrain','US 市场 · USD 报价；未验证其他市场库存','alecycling.com',['Hong Kong SAR','未列中国大陆','€40','€250','€25','30 天']]
]){
 const quote=offer(code,market,'https://'+host+'/products/example'),before=JSON.stringify(quote),row=context.readinessPolicy(quote);
 assert.ok(row);assert.equal(row.scope,'market');assert.equal(row.checkedAt,'2026-10-16');assert.equal(row.directChina.status,'conditional_checkout');assert.equal(row.directChina.shippingAmount,undefined);assert.equal(row.payment.chinaIssuedCard,'unknown');
 assert.equal(context.readinessPolicy({...quote,sales_region:'香港市场'}),null);assert.equal(context.readinessPolicy({...quote,url:'https://www.tradeinn.com/item'}),null);
 const html=context.readinessContent(quote),directory=context.readinessDirectoryMarkup({code,shop_url:'https://'+host+'/'});
 for(const word of words){assert.ok(html.includes(word),code+': '+word);assert.ok(directory.includes(word))}
 assert.ok(directory.includes('指定市场参考'));assert.ok(html.includes('data-china-card-status="unknown"'));assert.ok(!html.includes('官网列中国配送；'));assert.equal(JSON.stringify(quote),before);
 for(const url of row.sources)assert.equal(context.readinessUrl(url,code),true);
}
console.log('Third batch passed: exact Gobik/Alé markets, PayPal threshold and destination limits, return mechanisms, no China-card or landed-total promotion.');

// Real directory entrances must follow the same supplier as offers and policy evidence.
const actualDirectories=JSON.parse(fs.readFileSync('data/directories.json','utf8'));
const actualSources=JSON.parse(fs.readFileSync('data/sources.json','utf8'));
const actualCrawlers=JSON.parse(fs.readFileSync('data/crawl_sources.json','utf8'));
for(const [code,shop,evidence,oldShop,teamOfficial] of [
 ['movistar','https://gobik.com/en/collections/movistar-team','https://gobik.com/en/blogs/gobik-stories/inside-the-worldtour-2026','https://www.tradeinn.com/bikeinn/es/movistar_team','https://movistarteam.com/'],
 ['jayco','https://maap.cc/greenedge-cycling','https://maap.cc/greenedge-cycling','https://shop.greenedgecycling.com/','https://greenedgecycling.com/2026/']
]){
 const entry=actualDirectories.teams.find(row=>row.code===code),source=actualSources.find(row=>row.code===code),crawl=actualCrawlers.find(row=>row.code===code);
 assert.equal(entry.shop_url,shop);assert.equal(entry.shop_evidence_url,evidence);assert.equal(entry.shop_evidence_url,source.official_evidence_url);
 assert.equal(entry.official_url,teamOfficial);assert.deepEqual(entry.source_codes,[code]);assert.ok(entry.logo_images.length);
 assert.equal(new URL(entry.shop_url).hostname,new URL(source.base_url).hostname);assert.ok(crawl.domains.includes(new URL(shop).hostname));
 assert.ok([crawl.catalog_url,...(crawl.discovery?.catalog_urls||[])].includes(shop));
 const rows=context.readinessDirectoryRows(entry);assert.equal(rows.length,1);assert.equal(rows[0].sourceCode,code);assert.ok(rows[0].merchantHosts.includes(new URL(shop).hostname));
 assert.ok(context.readinessDirectoryMarkup(entry).includes('已核官网说明'));
 assert.equal(context.readinessDirectoryRows({...entry,shop_url:oldShop}).length,0);assert.equal(context.readinessDirectoryRows({...entry,shop_url:teamOfficial}).length,0);
}
console.log('Directory supplier identities passed: real Gobik/MAAP entrances match crawler, source evidence and scoped readiness; legacy hosts stay rejected.');

// Fourth batch distinguishes official exclusions, checked-but-unspecified policies and missing applicable text.
for(const [code,market,host,status,words] of [
 ['redbull','日本市场 JPY 报价','www.redbullshop.com','prohibited',['不支持中国大陆直邮','明确列香港','不能套日本门槛','自付退邮']],
 ['picnic','US 市场 · EUR 报价；未验证其他市场库存','teampicnicpostnl.store','unknown',['未找到中国大陆或香港','不能直接推断禁止','特价商品及礼品卡明确不退','已查官方政策，具体账户与地址仍须结账核对']],
 ['pns','欧洲站 EUR 报价','pasnormalstudios.com','conditional_checkout',['30 天通知、45 天寄回','不能外推中国或香港包税','不能保证中国或香港免费']],
 ['assos','国际站 USD 报价','www.assos.com','unknown',['未能确认适用于国际站的完整政策内容','不能借美国或意大利市场','辅助旁证','不能保证当前 /int 订单']]
]){
 const quote=offer(code,market,'https://'+host+'/products/example'),before=JSON.stringify(quote),row=context.readinessPolicy(quote);
 assert.ok(row);assert.equal(row.scope,'market');assert.equal(row.checkedAt,'2026-10-16');assert.equal(row.directChina.status,status);assert.equal(row.directChina.shippingAmount,undefined);assert.equal(row.payment.chinaIssuedCard,'unknown');
 assert.equal(context.readinessPolicy({...quote,sales_region:'other market'}),null);assert.equal(context.readinessPolicy({...quote,url:'https://other.example/product'}),null);
 const html=context.readinessContent(quote),directory=context.readinessDirectoryMarkup({code,shop_url:'https://'+host+'/'});
 for(const word of words){assert.ok(html.includes(word),code+': '+word);assert.ok(directory.includes(word))}
 assert.ok(directory.includes('指定市场参考'));assert.ok(html.includes('data-china-card-status="unknown"'));assert.equal(JSON.stringify(quote),before);
 for(const url of row.sources)assert.equal(context.readinessUrl(url,code),true);
}
const assosIntl=context.readinessPolicy(offer('assos','国际站 USD 报价','https://www.assos.com/int/item'));assert.equal(assosIntl.payment.status,'unknown');assert.equal(assosIntl.payment.methods.length,0);assert.ok(assosIntl.sources.every(url=>!url.includes('/us/')));
console.log('Fourth batch passed: scoped Red Bull/Picnic/PNS/ASSOS evidence, mainland exclusions versus unknowns, international-page limits and no cost/card upgrades.');

for(const code of ['redbull','picnic','assos']){const row=data.entries.find(r=>r.sourceCode===code);assert.ok(!/GET|缓存|脚本|读取工具|支付矩阵/.test(JSON.stringify(row)));}

// Destination restrictions stay limited to the exact store/market and product scope.
for(const [code,market,host,status,words] of [
 ['kask','意大利站 EUR 报价','www.kask.com','prohibited',['中国大陆和香港均不在','限当前意大利站','14 天']],
 ['teamcycles','','www.teamcycles.com','unknown',['自行车配送部分','不能因此推断所有骑行服','£100','£150']],
 ['unox','挪威商城 / NOK 报价','internshop.no','prohibited',['必填注册码','带 logo 或特殊设计','不能笼统承诺 14 天可退']],
 ['canyon','US 市场 · USD 商品报价；配送另核','www.canyon.com','prohibited',['不支持中国大陆或香港直邮','不能自动套用当前采集的 Midloader 车包','退货条件有冲突']],
 ['specialized','US 市场 · USD 商品报价；配送另核','www.specialized.com','prohibited',['美国发行卡及美国账单','中国跨境回邮','mail center']],
 ['rapha','日本站报价','www.rapha.cc','conditional_checkout',['明确不寄货运转运商','日本及韩国本地回邮安排尚未核实','未单独明确中国大陆']],
 ['rapha_kr','韩国站报价','www.rapha.cc','conditional_checkout',['明确不寄货运转运商','日本及韩国本地回邮安排尚未核实','£15']]
]){
 const quote=offer(code,market,'https://'+host+'/item'),before=JSON.stringify(quote),row=context.readinessPolicy(quote);
 assert.ok(row);assert.equal(row.checkedAt,'2026-10-16');assert.equal(row.directChina.status,status);assert.equal(row.directChina.shippingAmount,undefined);assert.equal(row.payment.chinaIssuedCard,'unknown');
 if(code!=='teamcycles'){assert.equal(row.scope,'market');assert.equal(context.readinessPolicy({...quote,sales_region:'other market'}),null)}else{assert.equal(row.scope,'merchant');assert.equal(row.salesRegion,null)}
 assert.equal(context.readinessPolicy({...quote,url:'https://other.example/item'}),null);
 const html=context.readinessContent(quote),directory=context.readinessDirectoryMarkup({code,shop_url:'https://'+host+'/'});
 for(const word of words){assert.ok(html.includes(word),code+': '+word);assert.ok(directory.includes(word))}
 assert.ok(html.includes('data-china-card-status="unknown"'));assert.equal(JSON.stringify(quote),before);for(const url of row.sources)assert.equal(context.readinessUrl(url,code),true);
 assert.ok(!/GET|缓存|脚本|读取工具|支付矩阵/.test(JSON.stringify(row)));
 if(code.startsWith('rapha'))assert.equal(row.forwarding.status,'prohibited');
}
console.log('Fifth batch passed: regional exclusions, Teamcycles apparel uncertainty, Uno-X eligibility, Canyon product boundaries and Rapha forwarding prohibition.');

// Final existing-source batch; no country selector or general international statement proves an order.
for(const [code,market,host,words] of [
 ['sigmasports','','www.sigmasports.com',['购买起 30 天','收货起 30 天','起算口径有冲突','非英国退邮买家承担']],
 ['soudal','BE 市场 · EUR 报价；未验证其他市场库存','thewolfpack.shop',['未取得中国大陆或香港','14 日但未明确起算日']],
 ['ineos','US 市场 · USD 报价；未验证其他市场库存','store.netcompanyineos.com',['Global-e','2026 年 6 月 16 日','不能一律称包税']],
 ['decathlon','US 市场 · USD 报价；未验证其他市场库存','shop.decathloncmacgmteam.com',['30 个日历日','14 天撤回权','不能归纳为全部免费或全部自费','仅法国本土']],
 ['castelli','AF 市场 · EUR 报价；未验证其他市场库存','www.castelli-cycling.com',['AF/EUR','香港另列运费 USD 15','不能套用于其他市场']],
 ['groupama','US 市场 · USD 报价；未验证其他市场库存','shop.bioracer.com',['独立于当前美元商品价格','VAT 的措辞存在差异','14 天撤回权']],
 ['ef_team_shop','美国','efprocycling.shop',['所有商品按需生产','颜色或尺寸导致的退换','15 天内']],
 ['nsn','阿联酋站 USD 报价','www.ekoi.com',['官方付款页明确','登录或创建账户','个性文字或图案头盔']],
 ['lotto','比利时站 EUR 报价','www.lotto-intermarche.be',['第 5.2 节','第 6.1 节','官方文字有冲突']],
 ['alpecin','比利时商城 EUR 页面显示价；配送费用另核','shops.topfanz.com',['Topfanz','Kalas','不是客户使用的商业转运仓']]
]){
 const quote=offer(code,market,'https://'+host+'/item'),before=JSON.stringify(quote),row=context.readinessPolicy(quote);
 assert.ok(row);assert.equal(row.checkedAt,'2026-10-16');assert.equal(row.payment.chinaIssuedCard,'unknown');assert.equal(row.directChina.shippingAmount,undefined);
 if(code==='sigmasports'){assert.equal(row.scope,'merchant');assert.equal(row.salesRegion,null)}else{assert.equal(row.scope,'market');assert.equal(context.readinessPolicy({...quote,sales_region:'other market'}),null)}
 assert.equal(context.readinessPolicy({...quote,url:'https://other.example/item'}),null);
 const html=context.readinessContent(quote),directory=context.readinessDirectoryMarkup({code,shop_url:'https://'+host+'/'});
 for(const word of words){assert.ok(html.includes(word),code+': '+word);assert.ok(directory.includes(word))}
 assert.ok(html.includes('data-china-card-status="unknown"'));assert.equal(JSON.stringify(quote),before);
 for(const url of row.sources)assert.equal(context.readinessUrl(url,code),true);
 assert.ok(!/GET|缓存|脚本|读取工具|支付矩阵/.test(JSON.stringify(row)));
}
assert.equal(context.readinessPolicy(offer('alpecin','比利时商城 EUR 页面显示价；配送费用另核','https://www.kalas.cc/product')),null);
assert.equal(context.readinessPolicy(offer('decathlon','US 市场 · USD 报价；未验证其他市场库存','https://www.decathlon.com.cn/product')),null);
const ae=context.readinessPolicy(offer('nsn','阿联酋站 USD 报价','https://www.ekoi.com/en-ae/item'));assert.equal(ae.payment.status,'conditional_checkout');assert.ok(ae.payment.methods.includes('PayPal'));
for(const source of actualSources)assert.ok(data.entries.some(row=>row.sourceCode===source.code),'Missing researched source: '+source.code);
assert.equal(data.entries.length,42);assert.ok(JSON.stringify(data).length<100000);assert.equal(data.checkedAt,'2026-10-15');
console.log('Final batch passed: all 35 non-Amazon sources mapped, exact merchant/market boundaries, scoped exceptions, honest evidence gaps and no price/card guarantees.');

const oakleyUS=offer('oakley','美国站 USD 报价','https://www.oakley.com/en-us/product/FOS902243');
const oakleyBefore=JSON.stringify(oakleyUS),oakley=context.readinessPolicy(oakleyUS);
assert.ok(oakley);assert.equal(oakley.scope,'market');assert.equal(oakley.checkedAt,'2026-10-16');
assert.deepEqual(oakley.merchantHosts,['www.oakley.com']);
assert.equal(oakley.directChina.status,'prohibited');assert.equal(oakley.directChina.shippingAmount,undefined);
assert.equal(oakley.forwarding.status,'unknown');assert.equal(oakley.payment.chinaIssuedCard,'unknown');
for(const sales_region of ['未核实','日本站报价','JP/JPY','US','',undefined])assert.equal(context.readinessPolicy({...oakleyUS,sales_region}),null);
for(const url of ['https://hk.oakley.com/product','https://www.oakley.com.evil.example/en-us/product','https://other.example/product'])assert.equal(context.readinessPolicy({...oakleyUS,url}),null);
for(const url of oakley.sources){assert.equal(context.readinessUrl(url,'oakley'),true);assert.ok(url.startsWith('https://www.oakley.com/en-us/'))}
assert.equal(context.readinessUrl('https://hk.oakley.com/support','oakley'),false);
const oakleyHtml=context.readinessContent(oakleyUS);
for(const word of ['不直邮中国大陆','中国大陆或香港','未找到明确商业转运许可','30 天','2026-10-16'])assert.ok(oakleyHtml.includes(word),word);
assert.ok(oakleyHtml.includes('data-china-card-status="unknown"'));assert.ok(!oakleyHtml.includes('官网列中国配送；'));
assert.equal(JSON.stringify(oakleyUS),oakleyBefore);
const oakleyDirectory=context.readinessDirectoryMarkup({code:'oakley',source_codes:['oakley'],shop_url:'https://www.oakley.com/en-us'});
assert.ok(oakleyDirectory.includes('指定市场参考'));assert.ok(oakleyDirectory.includes('目录未提供精确报价市场'));assert.ok(oakleyDirectory.includes('美国站 USD 报价'));
assert.equal(context.readinessDirectoryMarkup({code:'oakley',source_codes:['oakley'],shop_url:'https://hk.oakley.com/'}),'');
console.log('Oakley US readiness exact-market isolation passed.');

// Brand observations are Spain/EUR, independent of the existing US Movistar scope.
const gobikQuote=offer('gobik','西班牙站 EUR 报价','https://gobik.com/en/products/short-sleeve-jersey-cx-pro-4-0-unisex-gobik-factory-team-26');
const gobikBefore=JSON.stringify(gobikQuote),gobikPolicy=context.readinessPolicy(gobikQuote);
assert.equal(gobikPolicy.sourceCode,'gobik');assert.equal(gobikPolicy.payment.chinaIssuedCard,'unknown');
assert.equal(context.readinessPolicy({...gobikQuote,sales_region:'US 市场 · EUR 报价；未验证其他市场库存'}),null);
assert.equal(context.readinessPolicy({...gobikQuote,url:'https://other.example/product'}),null);
assert.equal(JSON.stringify(gobikQuote),gobikBefore);
assert.ok(context.readinessDirectoryMarkup({code:'gobik',source_codes:['gobik'],shop_url:'https://gobik.com/en/collections/gobik-factory-team'}).includes('西班牙'));

for(const code of ["sis_nutrition","maurten_nutrition","pelotan"]){const row=data.entries.find(x=>x.sourceCode===code);assert.equal(row.payment.status,"unknown");assert.equal(row.forwarding.status,"unknown");assert.equal(row.directChina.status,code==="pelotan"?"prohibited":"unknown");}
