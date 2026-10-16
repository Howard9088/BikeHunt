'use strict';
// Hermetic checks of the production feed, clock expiry and publication binding.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const gallery=fs.readFileSync('web/gallery.js','utf8'),flows=fs.readFileSync('web/flows.js','utf8'),adapter=fs.readFileSync('web/pages-adapter.js','utf8');
const NOW=Date.parse('2026-10-15T12:00:00Z');
function section(source,start,end){const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a);return source.slice(a,b)}
function card(changes={}){return {product_id:'sale',name:'Sale Jersey',name_zh:'折扣骑行服',brand:'Mock',category:'jerseys',color:'Black',source_codes:['brand'],source_count:2,variant_count:2,available_sizes:['M','L'],stock_state:'in_stock',reference_stock:'in_stock',reference_collection_state:'current',reference_data_kind:'live_snapshot',reference_offer_id:'offer-sale',reference_variant_id:'v-L',reference_size:'L',reference_color:'Black',reference_source:'Merchant',reference_url:'https://merchant.invalid/item',reference_price:{amount:'90',currency:'USD'},reference_original_price:{amount:'120',currency:'USD'},reference_cny:'630',reference_price_valid_until:null,recommended_total_cny:'9999',discount_pct:25,fetched_at:new Date(NOW).toISOString(),...changes}}
function harness(){
 let now=NOW;class Clock extends Date{constructor(...args){super(...(args.length?args:[now]))}static now(){return now}}
 const elements=new Map([['q',{value:''}]]);const c=vm.createContext({Date:Clock,Number,URL,Map,Set,JSON,Intl,activeSource:null,activeCategory:'all',activeCategoryGroup:null,categoryGroups:[],activeTab:'products',items:[],sourceCount:2,currentIndex:0,currentProduct:null,guideContext:null,observer:null,viewMode:'grid',swipe:null,animationUntil:0,performance:{now:()=>0},document:{getElementById(id){if(!elements.has(id))elements.set(id,{textContent:'',classList:{add(){}}});return elements.get(id)},querySelectorAll:()=>[]},gallery:{innerHTML:'',scrollTop:0,querySelectorAll:()=>[]},profileMatches:()=>true,IntersectionObserver:class{observe(){}disconnect(){}},positionHint(){},updatePosition(){},clearSearch(){},directoryData:{brands:[{code:'brand',name_zh:'品牌目录'}],teams:[]}});
 vm.runInContext(fs.readFileSync('web/public-visibility.js','utf8'),c);
 vm.runInContext(fs.readFileSync('web/listing-order.js','utf8'),c);
 vm.runInContext(fs.readFileSync('web/bundle-variants.js','utf8'),c);
 vm.runInContext(section(gallery,'const e=value','async function getJson('),c);
 vm.runInContext(section(gallery,'function imageMarkup(','function updatePosition('),c);
 vm.runInContext(section(gallery,'function inventoryVerified(','function merchantUrl('),c);
 vm.runInContext(section(flows,'function updateBrowseLabel(','function renderDirectory('),c);
 vm.runInContext(section(flows,'function expireLocalInventory(','// Run independently'),c);
 return {c,elements,setNow(value){now=value}};
}
function testEligibility(){
 const h=harness();assert.equal(h.c.featuredDeal(card()),true);
 for(const changes of [{reference_original_price:null},{reference_original_price:{amount:'90',currency:'USD'}},{reference_original_price:{amount:'80',currency:'USD'}},{reference_original_price:{amount:'120',currency:'EUR'}},{reference_price:{amount:'NaN',currency:'USD'}},{reference_original_price:{amount:'Infinity',currency:'USD'}},{reference_price:{amount:'0',currency:'USD'}},{reference_offer_id:null},{reference_variant_id:null},{stock_state:'unknown'},{reference_stock:'out_of_stock'},{reference_stock:'unknown'},{reference_collection_state:'retained'},{reference_data_kind:'legacy_cache'},{fetched_at:null},{fetched_at:'2026-10-15T12:00:00'},{fetched_at:new Date(NOW+1).toISOString()},{fetched_at:new Date(NOW-86400001).toISOString()},{reference_price_valid_until:'2026-10-14'},{reference_price_valid_until:'2026-02-30'}])assert.equal(h.c.featuredDeal(card(changes)),false,JSON.stringify(changes));
 assert.equal(h.c.featuredDeal(card({fetched_at:new Date(NOW-3600000).toISOString()})),true);
 assert.equal(h.c.featuredDeal(card({reference_price_valid_until:'2026-10-15'})),true);
 const tiny=card({reference_price:{amount:'99.99',currency:'USD'},reference_original_price:{amount:'100',currency:'USD'},discount_pct:0});assert.equal(h.c.featuredDeal(tiny),true);assert.equal(h.c.discountLabel(tiny),'优惠不足 1%');assert.equal(h.c.discountLabel(card({reference_price:{amount:'0.01',currency:'USD'},reference_original_price:{amount:'100',currency:'USD'}})),'优惠超过 99.9%');
}
function testScopeAndRendering(){
 const h=harness(),ordinary=card({product_id:'ordinary',name:'Stamp Hoodie',reference_original_price:null,discount_pct:null}),stale=card({product_id:'stale',fetched_at:new Date(NOW-86400001).toISOString()}),sold=card({product_id:'sold',stock_state:'out_of_stock'});
 h.c.items=[card(),ordinary,stale,sold];assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['ordinary','sale']);
 h.c.render();let html=h.c.gallery.innerHTML;assert.ok(html.includes('−25%'));assert.ok(html.includes('商家原价 <s>US$120.00</s>'));assert.ok(html.includes('现价 US$90.00'));assert.ok(html.includes('¥630.00'));assert.ok(html.includes('L / Black'));assert.ok(!html.includes('9,999'));assert.ok(html.includes('未取得折扣结束时间'));assert.ok(!/限时|倒计时/.test(html));
 h.elements.get('q').value='Stamp Hoodie';h.c.render();assert.equal(h.elements.get('browseLabel').textContent,'搜索结果');assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['ordinary']);assert.ok(!h.c.gallery.innerHTML.includes('class="discount"'));
 h.elements.get('q').value='';h.c.activeSource='brand';h.c.render();assert.equal(h.elements.get('browseLabel').textContent,'品牌目录');assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['ordinary','sale','stale'],'Channel preserves last-known stock and excludes sold-out quotes; unknown listing dates use stable product IDs');
 h.elements.get('q').value='Stamp Hoodie';assert.equal(h.c.visibleItems().length,1);h.c.items.push(card({...ordinary,product_id:'other',source_codes:['other']}));assert.equal(h.c.visibleItems().length,1,'Search keeps brand scope');
 h.c.activeSource=null;h.elements.get('q').value='';h.c.items=[stale,sold];h.c.render();assert.equal(h.c.visibleItems().length,1);assert.ok(h.c.gallery.innerHTML.includes('上次记录商品价'));assert.ok(!h.c.gallery.innerHTML.includes('没有找到这个商品'));
}
function testLocalExpiryAndPriceDate(){
 const h=harness();h.c.items=[card()];h.c.render();h.setNow(NOW+86400001);h.c.expireLocalInventory();assert.equal(h.c.visibleItems().length,1);assert.equal(h.c.items[0].stock_state,'in_stock');assert.equal(h.c.featuredDeal(h.c.items[0]),false);assert.ok(h.c.gallery.innerHTML.includes('上次记录商品价'));
 const date=Date.parse('2026-10-16T00:00:00Z');h.setNow(date-1);h.c.items=[card({fetched_at:new Date(date-1000).toISOString(),reference_price_valid_until:'2026-10-15'})];h.c.render();assert.equal(h.c.visibleItems().length,1);h.setNow(date);h.c.expireLocalInventory();assert.equal(h.c.visibleItems().length,1);assert.equal(h.c.items[0].reference_stock,'in_stock');assert.equal(h.c.featuredDeal(h.c.items[0]),false);
}
function testHistoricalDiscountFallbackEligibility(){
 const h=harness(),stale=card({product_id:'stale',category_group:'clothing',fetched_at:new Date(NOW-86400001).toISOString()});
 assert.equal(h.c.recordedDiscount(stale),true);assert.equal(h.c.featuredDeal(stale),false);
 for(const changes of [{reference_original_price:null},{reference_price:{amount:'90',currency:'USD'},reference_original_price:{amount:'90',currency:'USD'}},{reference_original_price:{amount:'120',currency:'EUR'}},{reference_price:{amount:'NaN',currency:'USD'}},{reference_original_price:{amount:'Infinity',currency:'USD'}},{reference_price:{amount:'0',currency:'USD'}},{reference_offer_id:null},{reference_variant_id:null},{stock_state:'out_of_stock'},{reference_stock:'out_of_stock'},{reference_data_kind:'research_reference'},{reference_price_valid_until:'2026-10-14'},{reference_price_valid_until:'2026-02-30'}])assert.equal(h.c.recordedDiscount({...stale,...changes}),false,JSON.stringify(changes));
 for(const changes of [{reference_stock:'unknown',stock_state:'unknown'},{reference_collection_state:'retained'},{reference_data_kind:'legacy_cache'},{fetched_at:null}])assert.equal(h.c.recordedDiscount({...stale,...changes}),true);
 const ordinary=card({product_id:'ordinary',reference_original_price:null}),sold=card({product_id:'sold',stock_state:'out_of_stock'}),expired=card({...stale,product_id:'expired',reference_price_valid_until:'2026-10-14'});
 h.c.items=[card(),stale,ordinary,sold,expired];assert.deepEqual(Array.from(h.c.historicalDiscountItems(),p=>p.product_id),['stale']);
 h.c.activeCategoryGroup='road_equipment';assert.equal(h.c.historicalDiscountItems().length,0);h.c.activeCategoryGroup='clothing';assert.equal(h.c.historicalDiscountItems().length,1);
 h.c.activeCategory='helmets';assert.equal(h.c.historicalDiscountItems().length,1,'Retired leaf state never hides products');h.c.activeCategory='all';h.c.activeSource='other';assert.equal(h.c.historicalDiscountItems().length,0);h.c.activeSource='brand';h.elements.get('q').value='missing';assert.equal(h.c.historicalDiscountItems().length,0);
 h.elements.get('q').value='';h.c.profileMatches=()=>false;assert.equal(h.c.historicalDiscountItems().length,0,'Personal filters are retained');
}
function testHistoricalEmptyRenderAndExactDetail(){
 const h=harness(),classes=()=>({values:new Set(),add(v){this.values.add(v)},remove(v){this.values.delete(v)},contains(v){return this.values.has(v)}});
 h.c.gallery.classList=classes();h.c.document.body={classList:classes()};h.c.cancelAnimationFrame=()=>{};h.c.animationFrame=0;
 const stale=card({product_id:'stale',fetched_at:new Date(NOW-86400001).toISOString()});
 const button={isConnected:true,dataset:{historyOpen:stale.product_id,historyVariant:stale.reference_variant_id}};
 h.c.gallery.querySelectorAll=selector=>selector==='[data-history-open]'?[button]:[];
 let opened=[];h.c.openProduct=(...args)=>opened.push(args);
 vm.runInContext(section(flows,'function referenceImageMarkup(','document.addEventListener(\'error\''),h.c);
 vm.runInContext(section(flows,'function resetReferenceFeed(','function openRoadReferences('),h.c);
 h.c.items=[stale,card({product_id:'ordinary',reference_original_price:null,fetched_at:new Date(NOW-7200000).toISOString()}),card({product_id:'sold',stock_state:'out_of_stock'})];h.c.render();
 assert.equal(h.c.visibleItems().length,1);const html=h.c.gallery.innerHTML;
 h.c.items=[stale];h.c.render();assert.ok(h.c.gallery.innerHTML.includes('上次记录商品价'));assert.ok(!html.includes('历史折扣参考'));assert.ok(!html.includes('historical-reference-card'));assert.equal(opened.length,0);
 assert.equal(h.c.renderEmptyReferences(),false);assert.ok(!h.c.gallery.classList.contains('reference-feed'));

}
function testPublishedFactsCannotCrossOffers(){
 const h=harness();Object.assign(h.c,{isRecord:x=>!!x&&typeof x==='object',validDigest:x=>/^[a-f0-9]{64}$/.test(x),validTimestamp:x=>Number.isFinite(Date.parse(x)),publicationMismatch:message=>Error(message)});
 vm.runInContext(section(adapter,'function publishedOfferIndex(','async function readPublishedSnapshot('),h.c);
 const p=card(),offer={offer_id:p.reference_offer_id,url:p.reference_url,collection_state:'current',fetched_at:p.fetched_at,stock:'in_stock',price:p.reference_price,original_price:p.reference_original_price,identity:{size:'L',color:'Black'},source_name:'Merchant',data_kind:'live_snapshot',price_valid_until:null};
 const payload={generated_at:p.fetched_at,catalog:{items:[p]},verification_identities:{'offer-sale':'a'.repeat(64)},details:{sale:{variants:{'v-L':{offers:[{offer,product_cny:'630'}]}}}}};
 h.c.validateCatalogIdentities(payload);
 const withUrl=structuredClone(payload);withUrl.catalog.items[0].reference_url='https://merchant.invalid/sale';withUrl.details.sale.variants['v-L'].offers[0].offer.url='https://merchant.invalid/sale';h.c.validateCatalogIdentities(withUrl);withUrl.catalog.items[0].reference_url='https://wrong.invalid/sale';assert.throws(()=>h.c.validateCatalogIdentities(withUrl),/折扣与参考规格/);
 for(const [key,value] of [['reference_original_price',{amount:'150',currency:'USD'}],['reference_price',{amount:'50',currency:'USD'}],['reference_cny','350'],['reference_size','M'],['reference_color','Blue'],['reference_variant_id','v-M'],['reference_price_valid_until','2026-10-18'],['reference_data_kind','legacy_cache'],['reference_source','Cheaper merchant'],['fetched_at',new Date(NOW+1000).toISOString()]]){const bad=structuredClone(payload);bad.catalog.items[0][key]=value;assert.throws(()=>h.c.validateCatalogIdentities(bad),/折扣与参考规格/,key)}
}
function helmet(id,amount,changes={}){return card({product_id:id,name:'Helmet '+id,brand:'Brand '+id,category:'helmets',category_group:'helmets',gender:'unisex',reference_url:'https://merchant.invalid/'+id,reference_original_price:null,reference_cny:String(amount),...changes})}
function testBrandDiversityAndLowPrices(){
 const h=harness(),a=helmet('a',100),b=helmet('b',200),c=helmet('c',300),other=helmet('d',400,{reference_source:'Other channel',brand:a.brand});
 h.c.items=[c,b,a,other];
 assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['a','b','d']);
 h.c.render();assert.equal(h.elements.get('count').textContent,'3 件渠道精选 · 0 件有折扣');assert.ok(h.c.gallery.innerHTML.includes('渠道精选'));assert.ok(!h.c.gallery.innerHTML.includes('商家原价'));assert.ok(h.c.gallery.innerHTML.includes('不是同类比价或全网最低价'));
 h.c.activeSource='brand';assert.equal(h.c.visibleItems().length,4,'Directory remains complete');h.c.activeSource=null;
 h.elements.get('q').value='Helmet';assert.equal(h.c.visibleItems().length,4,'Search remains complete');h.elements.get('q').value='';
 for(const change of [{stock_state:'out_of_stock'},{reference_stock:'unknown'},{reference_url:null},{reference_cny:null}])assert.equal(h.c.channelOfferEligible({...a,...change}),false,JSON.stringify(change));
 const duplicate={...a,product_id:'a-color',name:a.name+' - Blue',reference_cny:'101'};
 assert.deepEqual(Array.from(h.c.channelSelections([a,duplicate,b,c]),p=>p.product_id),['a','b']);
 h.c.activeCategoryGroup='clothing';assert.equal(h.c.visibleItems().length,0);
 h.c.activeCategoryGroup='helmets';h.c.profileMatches=p=>p.product_id!=='a';assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['b','c','d'],'Global category is uncapped and unknown listing dates use stable product IDs');
}
function testLowPriceSafetyAndComparability(){
 const h=harness(),base=helmet('a',100),pool=[base,helmet('b',200),helmet('c',300)];
 for(const changes of [{reference_cny:null},{reference_cny:'Infinity'},{reference_cny:0},{reference_price:{amount:0,currency:'USD'}},{reference_url:null},{reference_url:'http://merchant.invalid/'},{reference_url:'https://user:secret@merchant.invalid/'},{reference_url:'javascript:alert(1)'},{reference_offer_id:''},{reference_variant_id:null},{stock_state:'out_of_stock'},{reference_stock:'out_of_stock'},{reference_price_valid_until:'2026-10-14'},{reference_price_valid_until:'2026-02-30'},{gender:'unknown'},{name:'Child Helmet'},{name:'Helmet Kit'},{category_group:'road_equipment'},{category:'accessories',name:'Bottle'},{category:'accessories',name:'Gloves'}])assert.equal(h.c.lowPriceRecommendations([{...base,...changes},...pool.slice(1)]).size,0,JSON.stringify(changes));
 const stale={...base,fetched_at:new Date(NOW-7200000).toISOString(),reference_stock:'unknown',stock_state:'unknown',reference_collection_state:'retained'};
 assert.equal(h.c.lowPriceRecommendations([stale,...pool.slice(1)]).size,1);assert.equal(h.c.featuredDeal(stale),false);assert.ok(h.c.lowPriceMarkup(stale,{label:'头盔',count:3,rank:1}).includes('历史价格与库存待重新核实'));
 assert.equal(h.c.lowPriceRecommendations(pool.map(p=>({...p,reference_cny:'100'}))).size,0,'Equal-price sample does not demonstrate low price');
 const colors=[helmet('a',100,{name:'Same Helmet - White',brand:'Same'}),helmet('b',200,{name:'Same Helmet - Black',brand:'Same'}),helmet('c',300,{name:'Same Helmet - Red',brand:'Same'})];assert.equal(h.c.lowPriceRecommendations(colors).size,0,'Color variants cannot manufacture a three-model sample');
 const clothing=(name,category='jerseys',gender='male')=>({...base,name,category,category_group:'clothing',gender});
 assert.notEqual(h.c.lowPriceBucket(clothing('Short Sleeve Jersey')).key,h.c.lowPriceBucket(clothing('Long Sleeve Jersey')).key);
 assert.notEqual(h.c.lowPriceBucket(clothing('Short Sleeve Jersey')).key,h.c.lowPriceBucket(clothing('Short Sleeve Jersey','jerseys','female')).key);
 assert.notEqual(h.c.lowPriceBucket(clothing('Bib Shorts','bibs')).key,h.c.lowPriceBucket(clothing('Bib Tight','bibs')).key);
 assert.equal(h.c.lowPriceBucket(clothing('Jersey')),null);assert.equal(h.c.lowPriceBucket(clothing('Rain Jacket','jackets')),null);assert.ok(h.c.lowPriceBucket(clothing('Wind Vest','jackets')));
}

function testVerifiedStockWithoutSizeMetadata(){
 const h=harness(),fresh=card({product_id:'no-size',name:'No Size Jersey',reference_original_price:null,discount_pct:null,reference_size:null,available_sizes:[],recommended_total_cny:null,variant_count:1,source_count:1});
 h.c.activeSource='brand';h.c.items=[{...fresh,channel_quotes:{brand:fresh}}];h.c.render();
 assert.equal(h.c.visibleItems().length,1);assert.ok(h.c.gallery.innerHTML.includes('已核实有货 · 规格请到官网核对'));
 assert.ok(h.c.gallery.innerHTML.includes('已核实有货 · 所示商品价，规格请到官网核对'));
 assert.ok(!h.c.gallery.innerHTML.includes('1 个规格 · 库存待确认'));assert.ok(!h.c.gallery.innerHTML.includes('参考起价 · 库存待核实'));
 assert.equal(h.c.visibleItems()[0].reference_offer_id,fresh.reference_offer_id);
 const sized={...fresh,reference_size:'M',available_sizes:['M']};
 h.c.items=[{...sized,channel_quotes:{brand:sized}}];h.c.render();
 assert.ok(!h.c.gallery.innerHTML.includes('已核实有货 · 规格请到官网核对'));
 assert.ok(h.c.gallery.innerHTML.includes('现货商品参考起价 · 先选规格'));
 for(const changes of [{stock_state:'unknown',reference_stock:'unknown'},{stock_state:'out_of_stock',reference_stock:'out_of_stock'}]){
  const unavailable={...fresh,...changes};h.c.items=[{...unavailable,channel_quotes:{brand:unavailable}}];h.c.render();
  assert.equal(h.c.visibleItems().length,0);assert.ok(!h.c.gallery.innerHTML.includes('已核实有货 · 规格请到官网核对'));
  assert.ok(h.c.gallery.innerHTML.includes('该渠道暂无已核实有货的商品'));
 }
 h.c.activeSource=null;h.elements.get('q').value='No Size';
 for(const changes of [{stock_state:'unknown',reference_stock:'unknown'},{fetched_at:null}]){
  h.c.items=[{...fresh,...changes}];h.c.render();
  assert.ok(!h.c.gallery.innerHTML.includes('已核实有货 · 规格请到官网核对'));
  assert.ok(h.c.gallery.innerHTML.includes('库存待'));
 }
}

function testGlobalCategoryCompleteness(){
 const h=harness(),a=helmet('a',100,{color:null}),b=helmet('b',200,{color:null}),c=helmet('c',300,{color:null}),d=helmet('d',400,{color:null});
 const unknown=helmet('unknown',1,{stock_state:'unknown',reference_stock:'unknown'});
 const sold=helmet('sold',1,{stock_state:'out_of_stock',reference_stock:'out_of_stock'});
 const legacy=helmet('legacy',1,{reference_data_kind:'legacy_cache'});
 h.c.items=[a,b,c,d,unknown,sold,legacy];
 assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['a','b'],'Only the homepage applies the two-model channel cap');
 h.c.activeCategoryGroup='helmets';assert.equal(h.c.featuredBrowse(),false);
 assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['a','b','c','d'],'Global helmets show every reliable product in the channel');
 assert.deepEqual(Array.from(h.c.visibleItems(true),p=>p.product_id),['a','b','c','d'],'Category mode never bypasses stock eligibility');
 h.c.render();assert.equal(h.elements.get('count').textContent,'4 件商品');
 assert.ok(!h.c.gallery.innerHTML.includes('class="low-price-label"'));assert.ok(!h.c.gallery.innerHTML.includes('渠道精选'));
 h.elements.get('q').value='Helmet';assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['a','b','c','d']);
 h.elements.get('q').value='Helmet c';assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['c']);h.elements.get('q').value='';
 const other=helmet('other',500,{source_codes:['other'],reference_source:'Other merchant'});
 h.c.items.push(other);h.c.activeSource='brand';assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['a','b','c','d']);
 h.c.activeSource=null;assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['a','b','c','d','other']);
 h.c.shopperProfile={gender:'female'};
 vm.runInContext(section(fs.readFileSync('web/profile.js','utf8'),'function profileMatches(','function syncGenderScope('),h.c);
 assert.equal(h.c.visibleItems().length,5,'Hidden female clothing preference never removes helmets');
 const shoe=card({product_id:'shoe',name:'Verified Cleat Shoe',category:'shoes',category_group:'cleat_shoes',gender:'male'});
 h.c.items.push(shoe);h.c.activeCategoryGroup='cleat_shoes';assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['shoe']);
 const button={dataset:{tab:'products'}};
 h.c.document.querySelectorAll=selector=>selector==='[data-tab]'?[button]:[];h.c.syncBrowseControls=()=>{};h.c.navigate=tab=>{h.c.activeTab=tab};
 h.c.categoryGroups=[{code:'helmets',name:'头盔'},{code:'cleat_shoes',name:'锁鞋'}];
 vm.runInContext(section(flows,'function chooseCategoryGroup(','function syncBrowseControls('),h.c);
 vm.runInContext(section(flows,"document.querySelectorAll('[data-tab]').forEach(b=>b.onclick",'const panelError='),h.c);
 h.c.items=[a,b,c,d,other,unknown,sold];h.c.activeSource='brand';h.c.activeCategoryGroup='helmets';h.elements.get('q').value='Helmet c';
 button.onclick();assert.equal(h.c.activeSource,null);assert.equal(h.c.activeCategoryGroup,null);assert.equal(h.elements.get('q').value,'');assert.equal(h.c.featuredBrowse(),true);assert.equal(h.c.visibleItems().length,3);
 h.c.chooseCategoryGroup('helmets');assert.equal(h.c.activeSource,null);assert.equal(h.c.featuredBrowse(),false);
 assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['a','b','c','d','other']);
 h.c.chooseCategoryGroup('helmets');assert.equal(h.c.activeCategoryGroup,null);assert.equal(h.c.visibleItems().length,3);
}
function testGlobalCategoryExactQuoteFallback(){
 const h=harness(),aggregate=helmet('mixed',1,{source_codes:['brand','other'],stock_state:'unknown',reference_stock:'unknown',reference_data_kind:'legacy_cache',reference_offer_id:'old-offer',reference_variant_id:'old-size',fetched_at:new Date(NOW-86400001).toISOString()});
 const quote=helmet('mixed',2380,{source_codes:['other'],reference_source:'US official merchant',reference_url:'https://official.example/exact-helmet',reference_offer_id:'current-offer',reference_variant_id:'exact-L',reference_size:'L',reference_color:'Black/Red Pro',reference_price:{amount:'340',currency:'USD'}});
 aggregate.channel_quotes={brand:helmet('different-product',1),other:quote,undeclared:helmet('mixed',1)};
 const retained=helmet('retained',500,{reference_collection_state:'retained',fetched_at:new Date(NOW-86400001).toISOString()});
 h.c.items=[aggregate,retained];h.c.activeCategoryGroup='helmets';assert.equal(h.c.visibleItems().length,2);
 const selected=h.c.visibleItems().find(p=>p.product_id==='mixed');assert.equal(selected,quote,'Return whole exact quote, never field-mix');
 for(const key of ['reference_source','reference_url','reference_offer_id','reference_variant_id','reference_size','reference_color','reference_price','reference_cny','fetched_at'])assert.equal(selected[key],quote[key],key);
 assert.equal(h.c.visibleItems().find(p=>p.product_id==='retained'),retained);
 h.c.render();assert.ok(h.c.gallery.innerHTML.includes('340.00'));assert.ok(h.c.gallery.innerHTML.includes('上次记录商品价'));assert.ok(!h.c.gallery.innerHTML.includes('old-offer'));
 for(const changes of [{stock_state:'out_of_stock',reference_stock:'out_of_stock'},{stock_state:'unknown',reference_stock:'unknown'},{fetched_at:null},{product_id:'wrong-product'},{category_group:'other'}]){
 aggregate.channel_quotes.other={...quote,...changes};assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['retained'],'Invalid/mismatched/undeclared quote: '+JSON.stringify(changes));}
 aggregate.channel_quotes.other=quote;h.elements.get('q').value='Helmet mixed';assert.equal(h.c.visibleItems()[0],quote);h.elements.get('q').value='';aggregate.stock_state='out_of_stock';assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['retained']);
 h.c.activeCategoryGroup=null;h.elements.get('q').value='Helmet';h.c.items=[helmet('unknown',10,{stock_state:'unknown',reference_stock:'unknown'})];assert.equal(h.c.visibleItems().length,1);
}

function testFirstPublicationOrderAndLabels(){
 const html=fs.readFileSync('web/index.html','utf8');
 assert.ok(html.indexOf('/web/listing-order.js')>=0&&html.indexOf('/web/listing-order.js')<html.indexOf('/web/gallery.js'),'Listing module loads before gallery');
 const h=harness(),older=helmet('older',100,{first_listed_at:'2026-10-13T16:00:00Z'}),newer=helmet('newer',800,{first_listed_at:'2026-10-14T16:00:00Z'}),tie=helmet('tie',700,{first_listed_at:newer.first_listed_at}),unrecorded=helmet('unrecorded',1),other=helmet('other',900,{reference_source:'Other channel',first_listed_at:'2026-10-15T01:00:00Z'});
 h.c.items=[unrecorded,older,newer,tie,other];
 assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['other','tie','newer'],'Homepage takes newest eligible models per channel, breaks timestamp ties by price, and orders channels together newest first');
 assert.equal(h.c.visibleItems().filter(p=>p.reference_source==='Merchant').length,2);
 h.c.render();assert.ok(h.c.gallery.innerHTML.includes('本站发布：2026-10-15 09:00'));assert.ok(h.c.gallery.innerHTML.includes('本站发布：2026-10-15 00:00'));assert.ok(!h.c.gallery.innerHTML.includes('class="discount"'),'Ordering cannot create discount qualifications');
 const duplicate={...newer,product_id:'newer-blue',name:newer.name+' - Blue',first_listed_at:'2026-10-15T02:00:00Z'};
 assert.deepEqual(Array.from(h.c.channelSelections([newer,duplicate,tie,older]),p=>p.product_id),['newer-blue','tie'],'New color/size aliases still do not consume another model slot');
 h.c.activeCategoryGroup='helmets';assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),['other','newer','tie','older','unrecorded'],'Global category is newest first, unknown last, uncapped, and has stable non-price ties');
 h.c.render();assert.ok(h.c.gallery.innerHTML.includes('本站发布：未记录'));assert.ok(h.c.gallery.innerHTML.includes('上次核验'),'Publication and verification remain separate labels');
 const before=Array.from(h.c.visibleItems(),p=>p.product_id);older.fetched_at=new Date(NOW+5000).toISOString();h.setNow(NOW+10000);
 assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),before,'Refreshing inventory cannot bump first-publication order');
 h.c.activeCategoryGroup=null;h.elements.get('q').value='Helmet';assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),before,'Search uses the same uncapped ordering');
 h.elements.get('q').value='';h.c.activeSource='brand';assert.deepEqual(Array.from(h.c.visibleItems(),p=>p.product_id),before,'Channel browse uses the same uncapped ordering');
 const quote={...newer,first_listed_at:null};newer.channel_quotes={brand:quote};
 assert.equal(h.c.visibleItems().find(p=>p.product_id==='newer'),quote,'Channel cards retain their exact backend publication field without mixing or inventing a fallback');
 h.c.render();assert.ok(h.c.gallery.innerHTML.includes('本站发布：未记录'));
}

for(const test of [testFirstPublicationOrderAndLabels,testGlobalCategoryCompleteness,testGlobalCategoryExactQuoteFallback,testVerifiedStockWithoutSizeMetadata,testEligibility,testScopeAndRendering,testLocalExpiryAndPriceDate,testHistoricalDiscountFallbackEligibility,testHistoricalEmptyRenderAndExactDetail,testPublishedFactsCannotCrossOffers,testBrandDiversityAndLowPrices,testLowPriceSafetyAndComparability]){test();console.log('PASS '+test.name)}
