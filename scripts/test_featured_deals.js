'use strict';
// Hermetic checks of the production feed, clock expiry and publication binding.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const gallery=fs.readFileSync('web/gallery.js','utf8'),flows=fs.readFileSync('web/flows.js','utf8'),adapter=fs.readFileSync('web/pages-adapter.js','utf8');
const NOW=Date.parse('2026-10-15T12:00:00Z');
function section(source,start,end){const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a);return source.slice(a,b)}
function card(changes={}){return {product_id:'sale',name:'Sale Jersey',name_zh:'折扣骑行服',brand:'Mock',category:'jerseys',color:'Black',source_codes:['brand'],source_count:2,variant_count:2,available_sizes:['M','L'],stock_state:'in_stock',reference_stock:'in_stock',reference_collection_state:'current',reference_data_kind:'live_snapshot',reference_offer_id:'offer-sale',reference_variant_id:'v-L',reference_size:'L',reference_color:'Black',reference_source:'Merchant',reference_price:{amount:'90',currency:'USD'},reference_original_price:{amount:'120',currency:'USD'},reference_cny:'630',reference_price_valid_until:null,recommended_total_cny:'9999',discount_pct:25,fetched_at:new Date(NOW).toISOString(),...changes}}
function harness(){
 let now=NOW;class Clock extends Date{constructor(...args){super(...(args.length?args:[now]))}static now(){return now}}
 const elements=new Map([['q',{value:''}]]);const c=vm.createContext({Date:Clock,Number,URL,Map,Set,JSON,Intl,activeSource:null,activeCategory:'all',activeTab:'products',items:[],sourceCount:2,currentIndex:0,currentProduct:null,guideContext:null,observer:null,viewMode:'grid',swipe:null,animationUntil:0,performance:{now:()=>0},document:{getElementById(id){if(!elements.has(id))elements.set(id,{textContent:'',classList:{add(){}}});return elements.get(id)},querySelectorAll:()=>[]},gallery:{innerHTML:'',scrollTop:0,querySelectorAll:()=>[]},profileMatches:()=>true,IntersectionObserver:class{observe(){}disconnect(){}},positionHint(){},updatePosition(){},clearSearch(){},directoryData:{brands:[{code:'brand',name_zh:'品牌目录'}],teams:[]}});
 vm.runInContext(section(gallery,'const e=value','async function getJson('),c);
 vm.runInContext(section(gallery,'function imageMarkup(','function updatePosition('),c);
 vm.runInContext(section(gallery,'function inventoryVerified(','function merchantUrl('),c);
 vm.runInContext(section(flows,'function updateBrowseLabel(','function renderDirectory('),c);
 vm.runInContext(section(flows,'function expireLocalInventory(','// Run independently'),c);
 return {c,elements,setNow(value){now=value}};
}
function testEligibility(){
 const h=harness();assert.equal(h.c.featuredDeal(card()),true);
 for(const changes of [{reference_original_price:null},{reference_original_price:{amount:'90',currency:'USD'}},{reference_original_price:{amount:'80',currency:'USD'}},{reference_original_price:{amount:'120',currency:'EUR'}},{reference_price:{amount:'NaN',currency:'USD'}},{reference_original_price:{amount:'Infinity',currency:'USD'}},{reference_price:{amount:'0',currency:'USD'}},{reference_offer_id:null},{reference_variant_id:null},{stock_state:'unknown'},{reference_stock:'out_of_stock'},{reference_stock:'unknown'},{reference_collection_state:'retained'},{reference_data_kind:'legacy_cache'},{fetched_at:null},{fetched_at:'2026-10-15T12:00:00'},{fetched_at:new Date(NOW+1).toISOString()},{fetched_at:new Date(NOW-3600001).toISOString()},{reference_price_valid_until:'2026-10-14'},{reference_price_valid_until:'2026-02-30'}])assert.equal(h.c.featuredDeal(card(changes)),false,JSON.stringify(changes));
 assert.equal(h.c.featuredDeal(card({fetched_at:new Date(NOW-3600000).toISOString()})),true);
 assert.equal(h.c.featuredDeal(card({reference_price_valid_until:'2026-10-15'})),true);
 const tiny=card({reference_price:{amount:'99.99',currency:'USD'},reference_original_price:{amount:'100',currency:'USD'},discount_pct:0});assert.equal(h.c.featuredDeal(tiny),true);assert.equal(h.c.discountLabel(tiny),'优惠不足 1%');assert.equal(h.c.discountLabel(card({reference_price:{amount:'0.01',currency:'USD'},reference_original_price:{amount:'100',currency:'USD'}})),'优惠超过 99.9%');
}
function testScopeAndRendering(){
 const h=harness(),ordinary=card({product_id:'ordinary',name:'Stamp Hoodie',reference_original_price:null,discount_pct:null}),stale=card({product_id:'stale',fetched_at:new Date(NOW-3600001).toISOString()}),sold=card({product_id:'sold',stock_state:'out_of_stock'});
 h.c.items=[card(),ordinary,stale,sold];assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['sale']);
 h.c.render();let html=h.c.gallery.innerHTML;assert.ok(html.includes('−25%'));assert.ok(html.includes('商家原价 <s>US$120.00</s>'));assert.ok(html.includes('现价 US$90.00'));assert.ok(html.includes('¥630.00'));assert.ok(html.includes('L / Black'));assert.ok(!html.includes('9,999'));assert.ok(html.includes('未取得折扣结束时间'));assert.ok(!/限时|倒计时/.test(html));
 h.elements.get('q').value='Stamp Hoodie';h.c.render();assert.equal(h.elements.get('browseLabel').textContent,'搜索结果');assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['ordinary']);assert.ok(!h.c.gallery.innerHTML.includes('class="discount"'));
 h.elements.get('q').value='';h.c.activeSource='brand';h.c.render();assert.equal(h.elements.get('browseLabel').textContent,'品牌目录');assert.equal(h.c.visibleItems().length,3);
 h.elements.get('q').value='Stamp Hoodie';assert.equal(h.c.visibleItems().length,1);h.c.items.push(card({...ordinary,product_id:'other',source_codes:['other']}));assert.equal(h.c.visibleItems().length,1,'Search keeps brand scope');
 h.c.activeSource=null;h.elements.get('q').value='';h.c.items=[ordinary,stale,sold];h.c.render();assert.ok(h.c.gallery.innerHTML.includes('暂无符合条件的已核实折扣'));assert.ok(!h.c.gallery.innerHTML.includes('没有找到这个商品'));
}
function testLocalExpiryAndPriceDate(){
 const h=harness();h.c.items=[card()];h.c.render();h.setNow(NOW+3600001);h.c.expireLocalInventory();assert.equal(h.c.visibleItems().length,0);assert.ok(h.c.gallery.innerHTML.includes('暂无符合条件'));
 const date=Date.parse('2026-10-16T00:00:00Z');h.setNow(date-1);h.c.items=[card({fetched_at:new Date(date-1000).toISOString(),reference_price_valid_until:'2026-10-15'})];h.c.render();assert.equal(h.c.visibleItems().length,1);h.setNow(date);h.c.expireLocalInventory();assert.equal(h.c.visibleItems().length,0);assert.equal(h.c.items[0].reference_stock,'unknown');
}
function testPublishedFactsCannotCrossOffers(){
 const h=harness();Object.assign(h.c,{isRecord:x=>!!x&&typeof x==='object',validDigest:x=>/^[a-f0-9]{64}$/.test(x),validTimestamp:x=>Number.isFinite(Date.parse(x)),publicationMismatch:message=>Error(message)});
 vm.runInContext(section(adapter,'function publishedOfferIndex(','async function readPublishedSnapshot('),h.c);
 const p=card(),offer={offer_id:p.reference_offer_id,collection_state:'current',fetched_at:p.fetched_at,stock:'in_stock',price:p.reference_price,original_price:p.reference_original_price,identity:{size:'L',color:'Black'},source_name:'Merchant',data_kind:'live_snapshot',price_valid_until:null};
 const payload={generated_at:p.fetched_at,catalog:{items:[p]},verification_identities:{'offer-sale':'a'.repeat(64)},details:{sale:{variants:{'v-L':{offers:[{offer,product_cny:'630'}]}}}}};
 h.c.validateCatalogIdentities(payload);
 for(const [key,value] of [['reference_original_price',{amount:'150',currency:'USD'}],['reference_price',{amount:'50',currency:'USD'}],['reference_cny','350'],['reference_size','M'],['reference_color','Blue'],['reference_variant_id','v-M'],['reference_price_valid_until','2026-10-18'],['reference_data_kind','legacy_cache'],['reference_source','Cheaper merchant'],['fetched_at',new Date(NOW+1000).toISOString()]]){const bad=structuredClone(payload);bad.catalog.items[0][key]=value;assert.throws(()=>h.c.validateCatalogIdentities(bad),/折扣与参考规格/,key)}
}
for(const test of [testEligibility,testScopeAndRendering,testLocalExpiryAndPriceDate,testPublishedFactsCannotCrossOffers]){test();console.log('PASS '+test.name)}
