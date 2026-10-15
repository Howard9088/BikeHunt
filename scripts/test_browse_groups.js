'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const gallery=fs.readFileSync('web/gallery.js','utf8'),flows=fs.readFileSync('web/flows.js','utf8'),profile=fs.readFileSync('web/profile.js','utf8');
const data=JSON.parse(fs.readFileSync('data/road_equipment_references.json'));
const groups=[['road_equipment','自行车'],['clothing','骑行服饰'],['cleat_shoes','锁鞋'],['helmets','头盔'],['other','配件与周边']].map(([code,name])=>({code,name}));
function section(source,start,end){return source.slice(source.indexOf(start),end?source.indexOf(end,source.indexOf(start)):undefined)}
function harness(){
 const classes=()=>({values:new Set(),add(v){this.values.add(v)},remove(v){this.values.delete(v)},contains(v){return this.values.has(v)},toggle(v,on){if(on)this.add(v);else this.remove(v)}});
 const eventHandlers=new Map(),elements=new Map(),groupButtons=groups.map(g=>({dataset:{categoryGroup:g.code},setAttribute(k,v){this[k]=v}})),leafButtons=['all','jerseys','accessories','frames','road_bikes','bike_parts','helmets','shoes'].map(code=>({dataset:{category:code},setAttribute(k,v){this[k]=v}})),productButton={dataset:{tab:'products'}};
 const elem=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',classList:classes(),contains:()=>false});return elements.get(id)};
 const c=vm.createContext({Date,URL,Intl,Number,String,Map,Set,JSON,Object,activeCategoryGroup:null,activeCategory:'all',activeTab:'products',activeSource:'team',items:[],categories:leafButtons.map(b=>({code:b.dataset.category})),categoryGroups:groups,roadReferenceData:structuredClone(data),directoryData:{brands:data.brands,teams:[{code:'team',name_zh:'车队'}]},profileMatches:()=>true,featuredDeal:p=>p.featured===true,navigate:tab=>{c.activeTab=tab},history:{state:{unrelated:1},replaceState(state){this.state=state}},sheet:{classList:classes()},gallery:{hidden:false,inert:false,classList:classes(),scrollTop:0,querySelectorAll:()=>[]},cancelAnimationFrame(){},animationFrame:0,swipe:null,animationUntil:0,currentIndex:0,historicalDiscountItems:()=>[],document:{getElementById:elem,querySelectorAll:selector=>selector==='[data-category-group]'?groupButtons:selector==='[data-category]'?leafButtons:selector==='[data-tab]'?[productButton]:[],body:{classList:classes()},addEventListener(type,handler){eventHandlers.set(type,handler)}},showExternalExit:options=>{c.exit=options},openPanel:(title,html)=>{c.panel=html}});
 vm.runInContext(section(gallery,'const e=value','function cny('),c);
 vm.runInContext(section(gallery,'function featuredBrowse(','function render('),c);
 vm.runInContext(section(flows,'function saveBrowseState(','function navigate('),c);
 vm.runInContext(section(flows,'function chooseCategory(','function renderDirectory('),c);
 vm.runInContext(section(flows,'const ROAD_REFERENCE_SCOPES=','// Merchant-language guide:'),c);
 return {c,elem,groupButtons,leafButtons,productButton,eventHandlers};
}
function testGroupLeafSourceSearchAndReset(){
 const {c,elem,groupButtons,productButton}=harness();c.items=[{name:'Jersey',brand:'Test',category:'jerseys',category_group:'clothing',source_codes:['team']},{name:'Bottle',brand:'Test',category:'accessories',category_group:'other',source_codes:['team']},{name:'Bottle',brand:'Other',category:'accessories',category_group:'other',source_codes:['other']}];
 assert.equal(groups.length,5);assert.ok(!fs.readFileSync('web/index.html','utf8').includes('id="categoryNav"'));
 c.chooseCategoryGroup('road_equipment');assert.equal(c.activeSource,'team');assert.equal(c.visibleItems().length,0);assert.equal(elem('browseLabel').textContent,'车队 · 自行车');assert.equal(groupButtons[0]['aria-pressed'],'true');
 c.chooseCategoryGroup('other');assert.equal(c.visibleItems().length,1);assert.equal(elem('browseLabel').textContent,'车队 · 配件与周边');
 c.chooseCategory('frames');assert.equal(c.activeCategory,'all');assert.equal(c.activeCategoryGroup,'other');assert.equal(c.visibleItems().length,1);
 elem('q').value='missing';assert.equal(c.visibleItems().length,0);c.chooseCategoryGroup('clothing');assert.equal(c.activeSource,'team');assert.equal(elem('q').value,'missing');assert.equal(c.activeCategory,'all');elem('q').value='jersey';assert.equal(c.visibleItems().length,1);
 c.chooseCategoryGroup('clothing');assert.equal(c.activeCategoryGroup,null,'Clicking active group clears only group');assert.equal(c.activeSource,'team');
 vm.runInContext(section(flows,"document.querySelectorAll('[data-tab]').forEach(b=>b.onclick",'const panelError='),c);productButton.onclick();assert.equal(c.activeSource,null);assert.equal(c.activeCategoryGroup,null);assert.equal(c.activeCategory,'all');assert.equal(elem('q').value,'');assert.equal(c.visibleItems().length,0,'Ordinary cards never enter featured after reset');
}
function testGroupHistoryAndOldState(){
 const {c,elem}=harness();c.chooseCategoryGroup('other');elem('q').value='Bottle';c.activeCategory='frames';c.saveBrowseState();assert.equal(c.history.state.unrelated,1);assert.equal(c.history.state.bikehuntBrowse.category,'all');c.history.state.bikehuntBrowse.category='frames';c.activeCategoryGroup=null;c.activeSource=null;elem('q').value='';c.restoreBrowseState();assert.equal(c.activeCategoryGroup,'other');assert.equal(c.activeCategory,'all');assert.equal(c.activeSource,'team');assert.equal(elem('q').value,'Bottle');
 delete c.history.state.bikehuntBrowse.categoryGroup;c.restoreBrowseState();assert.equal(c.activeCategoryGroup,null);c.history.state.bikehuntBrowse.categoryGroup='malformed';c.restoreBrowseState();assert.equal(c.activeCategoryGroup,null);
}
function testResearchSeparationFilteringAndExactGuard(){
 const {c,elem,eventHandlers}=harness();c.activeSource=null;c.activeCategoryGroup='road_equipment';let html=c.roadReferenceMarkup();assert.equal((html.match(/data-road-reference-card=/g)||[]).length,3);assert.ok(!html.includes('Canyon Midloader'));for(const required of ['美国官网标价，库存待核实','不进入精选好价','未取得折扣结束时间','仅支持机械变速','退货条件冲突','不接受转运地址'])assert.ok(html.includes(required),required);assert.ok(!html.includes('data-purchase-link'));assert.ok(!html.includes('data-route-select'));assert.ok(!html.includes('target="_blank"'));
 c.activeCategory='frames';assert.equal((c.roadReferenceMarkup().match(/data-road-reference-card=/g)||[]).length,3,'Retired leaf state has no effect');c.activeSource='specialized';elem('q').value='Allez';assert.equal((c.roadReferenceMarkup().match(/data-road-reference-card=/g)||[]).length,1);
 elem('roadReferencePanel').contains=()=>true;c.sheet.classList.add('open');
 const row=c.roadReferenceData.products[0],link={isConnected:true,dataset:{roadReference:'product:'+row.id},href:row.url,getAttribute(){return this.href}};let prevented=false;c.guardRoadReferenceExit({type:'click',target:{closest:()=>link},preventDefault(){prevented=true}});assert.ok(prevented);assert.ok(c.exit.validate());assert.equal(c.exit.url,row.url);link.href=row.url+'&wrong=1';assert.equal(c.exit.validate(),false);assert.equal(c.roadReferenceUrl({...row,url:'https://www.specialized.com.evil/us/en/x'}),'');assert.equal(c.roadReferenceUrl({...row,url:'https://www.specialized.com/gb/en/x'}),'');
 c.items=data.products.map(p=>({...p,name_zh:p.name,source_codes:[p.source_code],stock_state:'unknown'}));c.activeSource=null;elem('q').value='';assert.equal(c.visibleItems().length,0,'Research cards cannot qualify as featured');
 c.activeCategoryGroup='other';html=c.roadReferenceMarkup();assert.equal((html.match(/data-road-reference-card=/g)||[]).length,1);assert.ok(html.includes('Canyon Midloader'));assert.ok(!html.includes('Allez —'));
 assert.equal(data.products.filter(p=>p.image).length,3);assert.ok(html.includes('data-reference-image'));assert.ok(c.referenceImageMarkup(undefined,'missing').includes('商品图片待核实'));for(const url of ['javascript:alert(1)','http://example.com/photo.jpg','https://user:password@example.com/photo.jpg'])assert.ok(!c.referenceImageMarkup(url,'unsafe').includes('<img'));
 const fallback={hidden:true},failedImage={hidden:false,matches:selector=>selector==='img[data-reference-image]',nextElementSibling:fallback};eventHandlers.get('error')({target:failedImage});assert.equal(failedImage.hidden,true);assert.equal(fallback.hidden,false,'Failed exact image exposes text rather than a generic substitute');
 const image='https://example.com/exact-product.jpg';assert.ok(c.historicalDiscountMarkup([{product_id:'history',brand:'Test',name:'Exact product',image,reference_price:{amount:90,currency:'USD'},reference_original_price:{amount:120,currency:'USD'}}]).includes('src="'+image+'"'));
}
function testInlineFallbackFilteringAndLiveGuard(){
 const {c,elem}=harness();c.activeSource=null;c.activeCategoryGroup='road_equipment';
 assert.equal(c.renderEmptyReferences(),true);let html=c.gallery.innerHTML;
 assert.equal((html.match(/data-road-reference-card=/g)||[]).length,3);assert.ok(html.includes('id="roadReferenceInline"'));
 assert.ok(html.indexOf('data-road-reference-card=')<html.indexOf('road-brand-entrances'));
 assert.ok(html.includes('价格观察时间未记录'));assert.ok(html.includes('记录现价'));assert.ok(html.includes('记录原价'));assert.ok(!html.includes('class="card'));
 assert.ok(c.gallery.classList.contains('reference-feed'));assert.ok(c.document.body.classList.contains('reference-feed-visible'));
 c.activeSource='team';c.renderEmptyReferences();assert.equal((c.gallery.innerHTML.match(/data-road-reference-card=/g)||[]).length,0,'Team source must not leak unrelated research');
 c.activeSource='canyon';c.renderEmptyReferences();assert.equal((c.gallery.innerHTML.match(/data-road-reference-card=/g)||[]).length,2);
 elem('q').value='Midloader';c.renderEmptyReferences();assert.equal((c.gallery.innerHTML.match(/data-road-reference-card=/g)||[]).length,0);
 c.chooseCategoryGroup('other');c.renderEmptyReferences();assert.equal((c.gallery.innerHTML.match(/data-road-reference-card=/g)||[]).length,1);
 elem('roadReferenceInline').contains=()=>true;
 const row=c.roadReferenceData.products.find(r=>r.id==='canyon-9102039'),link={isConnected:true,dataset:{roadReference:'product:'+row.id},getAttribute:()=>row.url};
 assert.equal(c.allowedRoadReference(link),row,'Unknown stock allows a guarded reference visit');
 c.guardRoadReferenceExit({type:'click',target:{closest:()=>link},preventDefault(){}});assert.equal(c.exit.kind,'reference');assert.ok(c.exit.validate());
 c.exit.onConfirm();assert.equal(c.history.state.bikehuntBrowse.query,'Midloader');assert.equal(c.history.state.bikehuntBrowse.source,'canyon');assert.equal(c.history.state.bikehuntBrowse.categoryGroup,'other');
 row.stock='out_of_stock';assert.equal(c.exit.validate(),false,'Stock changes invalidate an already-open final gate');c.renderEmptyReferences();html=c.gallery.innerHTML;assert.ok(html.includes('已确认售罄'));assert.ok(!html.includes('data-road-reference="product:'+row.id+'"'));
 row.stock='unknown';assert.equal(c.allowedRoadReference(link),row);elem('q').value='different';assert.equal(c.allowedRoadReference(link),null,'Current filters revalidate the link');elem('q').value='Midloader';
 c.activeCategoryGroup='road_equipment';assert.equal(c.allowedRoadReference(link),null,'Accessory link cannot escape the current group');c.activeCategoryGroup='other';
 c.gallery.inert=true;assert.equal(c.allowedRoadReference(link),null);c.gallery.inert=false;c.activeTab='brands';assert.equal(c.allowedRoadReference(link),null);c.activeTab='products';link.isConnected=false;assert.equal(c.allowedRoadReference(link),null);
 c.activeCategoryGroup='clothing';assert.equal(c.renderEmptyReferences(),false);c.resetReferenceFeed();assert.ok(!c.gallery.classList.contains('reference-feed'));
}
function testEquipmentGenderIndependence(){const c=vm.createContext({shopperProfile:{gender:'female'}});vm.runInContext(section(profile,'function profileMatches(','function updateProfileBar('),c);assert.equal(c.profileMatches({category_group:'road_equipment',gender:'unknown'}),true);assert.equal(c.profileMatches({category_group:'clothing',gender:'male'}),false);assert.equal(c.profileMatches({category_group:'cleat_shoes',gender:'male'}),false)}
function testTrekAndSpecializedRestrictiveFallback(){
 const {harness:routeHarness,quote}=require('./test_route_flow');const h=routeHarness();
 for(const region of ['US','US 市场报价（USD）','unknown'])for(const missing of [true,false]){if(missing)vm.runInContext('readinessData=null;readinessState="error"',h.c);const trek=quote('trek',{url:'https://www.trekbikes.com/us/en_US/bikes/test/p/33101/',sales_region:region,shipping_to_china:{status:'yes'}});assert.deepEqual(Array.from(h.c.routeOptions(trek),r=>r.status),['prohibited','prohibited','prohibited']);const spec=quote('specialized',{url:'https://www.specialized.com/us/en/allez/p/4221796',sales_region:region,shipping_to_china:{status:'yes'}});assert.equal(h.c.routeOptions(spec)[0].status,'prohibited')}
 for(const offer of [{source_code:'trek',url:'https://www.trekbikes.com/gb/en_GB/bikes/test/'},{source_code:'other',url:'https://www.trekbikes.com/us/en_US/bikes/test/'},{source_code:'trek',url:'https://www.trekbikes.com.evil/us/en_US/bikes/test/'}])assert.equal(h.c.routeOptions(quote('trek',offer))[1].status,'unknown');
}
function testNewBrandPaymentsStayUnknown(){
 const c=vm.createContext({URL,Date,Map,Set,Object,JSON,Number,String,Array,Promise,console,document:{currentScript:{src:'https://bikehunt.example/web/payment-methods.js'},addEventListener(){},querySelectorAll:()=>[]},window:{},fetch:()=>{throw Error('No requests permitted')}});
 vm.runInContext(fs.readFileSync('web/payment-methods.js','utf8').replace(/^loadPaymentMethods\(\);$/m,''),c);
 c.channels=JSON.parse(fs.readFileSync('web/payment-channels.json'));c.payments=JSON.parse(fs.readFileSync('tests/fixtures/payment-methods.json'));vm.runInContext('paymentChannels=validatePaymentChannels(channels);paymentData=validatePaymentData(payments,paymentChannels);paymentState="ready"',c);
 for(const brand of data.brands){const offer={source_code:brand.code,url:brand.url,sales_region:'US',china_issued_card:{status:'yes'},accepted_card_networks:['Visa']};assert.equal(c.paymentPolicy(offer),null);assert.equal(c.paymentMethodsFor(offer).length,11);assert.ok(c.paymentMethodsFor(offer).every(row=>row.status==='unknown'));assert.equal(c.paymentSummary(offer).status,'unknown');const html=c.paymentDirectoryContent({...brand,name_zh:brand.name,official_url:brand.url});assert.ok(html.includes('当前来源尚未绑定已核实商家身份'));assert.ok(html.includes('不套用同品牌其他商店'));assert.ok(html.includes('中国发行卡：待核实'))}
}
for(const test of [testGroupLeafSourceSearchAndReset,testGroupHistoryAndOldState,testResearchSeparationFilteringAndExactGuard,testInlineFallbackFilteringAndLiveGuard,testEquipmentGenderIndependence,testTrekAndSpecializedRestrictiveFallback,testNewBrandPaymentsStayUnknown]){test();console.log('PASS '+test.name)}
console.log('Five-group and official-reference tests: seven groups passed.');
