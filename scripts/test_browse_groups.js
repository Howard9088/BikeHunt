'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const gallery=fs.readFileSync('web/gallery.js','utf8'),flows=fs.readFileSync('web/flows.js','utf8'),profile=fs.readFileSync('web/profile.js','utf8');
const data=JSON.parse(fs.readFileSync('data/road_equipment_references.json'));
const groups=[['clothing','骑行服饰'],['cleat_shoes','锁鞋'],['helmets','头盔'],['other','配件与周边']].map(([code,name])=>({code,name}));
function section(source,start,end){return source.slice(source.indexOf(start),end?source.indexOf(end,source.indexOf(start)):undefined)}
function harness(){
 const classes=()=>({values:new Set(),add(v){this.values.add(v)},remove(v){this.values.delete(v)},contains(v){return this.values.has(v)},toggle(v,on){if(on)this.add(v);else this.remove(v)}});
 const genderButtons=['all','male','female'].map(gender=>({dataset:{gender},setAttribute(k,v){this[k]=v}}));
 const eventHandlers=new Map(),elements=new Map(),groupButtons=groups.map(g=>({dataset:{categoryGroup:g.code},setAttribute(k,v){this[k]=v}})),leafButtons=['all','jerseys','accessories','frames','road_bikes','bike_parts','helmets','shoes'].map(code=>({dataset:{category:code},setAttribute(k,v){this[k]=v}})),productButton={dataset:{tab:'products'}};
 const elem=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',dataset:{},classList:classes(),contains:()=>false,focus(){c.focus=this},querySelectorAll:()=>[],querySelector:()=>null});return elements.get(id)};
 const c=vm.createContext({Date,URL,Intl,Number,String,Map,Set,JSON,Object,fx:{rates:{USD:'7'},rate_date:new Date().toISOString().slice(0,10),fetched_at:new Date().toISOString(),stale:false},shopperProfile:{gender:'all'},PROFILE_KEY:'test',localStorage:{setItem(k,v){c.savedProfile=JSON.parse(v)}},activeCategoryGroup:null,activeCategory:'all',activeTab:'products',activeSource:'team',items:[],categories:leafButtons.map(b=>({code:b.dataset.category})),categoryGroups:groups,roadReferenceData:structuredClone(data),directoryData:{brands:data.brands.map(row=>({...row,road_reference:true})),teams:[{code:'team',name_zh:'车队'}]},profileMatches:()=>true,featuredDeal:p=>p.featured===true,navigate:tab=>{c.activeTab=tab},history:{state:{unrelated:1},replaceState(state){this.state=state}},sheet:{classList:classes()},gallery:{hidden:false,inert:false,classList:classes(),scrollTop:0,querySelectorAll:()=>[]},cancelAnimationFrame(){},animationFrame:0,swipe:null,animationUntil:0,currentIndex:0,historicalDiscountItems:()=>[],document:{getElementById:elem,querySelectorAll:selector=>selector==='[data-gender]'?genderButtons:selector==='[data-category-group]'?groupButtons:selector==='[data-category]'?leafButtons:selector==='[data-tab]'?[productButton]:[],body:{classList:classes()},addEventListener(type,handler){eventHandlers.set(type,handler)}},showExternalExit:options=>{c.exit=options},openPanel:(title,html)=>{c.panel=html;c.sheet.classList.add('open');c.gallery.inert=true},closeSheet:()=>{vm.runInContext('roadDetailContext=null',c);c.sheet.classList.remove('open');c.gallery.inert=false}});
 vm.runInContext(fs.readFileSync('web/public-visibility.js','utf8'),c);
 vm.runInContext(section(profile,'function profileMatches(','function saveProfile('),c);
 vm.runInContext(section(gallery,'const e=value','function cny('),c);
 vm.runInContext(section(gallery,'function featuredBrowse(','function render('),c);
 vm.runInContext(section(flows,'function saveBrowseState(','function navigate('),c);
 vm.runInContext(section(flows,'function chooseCategory(','function renderDirectory('),c);
 vm.runInContext(section(flows,'const ROAD_REFERENCE_SCOPES=','// Merchant-language guide:'),c);
 return {c,elem,groupButtons,leafButtons,productButton,eventHandlers,genderButtons};
}
function mountDetail(c,elem,row){c.openRoadReferenceDetail(row.id);elem('roadReferenceDetail').dataset.roadDetail=row.id;elem('roadReferenceDetail').contains=()=>true}
function testPublicProjectionRejectsOldPayload(){
 const {c}=harness();const original=JSON.stringify(data);
 const bike=data.products.find(row=>row.category_group==='road_equipment'),bag=data.products.find(row=>row.id==='canyon-9102039');
 const projected=c.publicCatalogData({category_groups:[{code:'road_equipment',name:'自行车'},...groups],categories:[{code:'road_bikes'},{code:'frames'},{code:'bike_parts'},{code:'accessories'}],items:[{...bike,product_id:'old-bike'}, {...bag,product_id:'bag'}],road_equipment_references:data});
 assert.deepEqual(Array.from(projected.category_groups,row=>row.code),groups.map(row=>row.code));assert.deepEqual(Array.from(projected.categories,row=>row.code),['bike_parts','accessories']);assert.deepEqual(Array.from(projected.items,row=>row.product_id),['bag']);assert.deepEqual(Array.from(projected.road_equipment_references.products,row=>row.id),['canyon-9102039']);assert.equal(projected.road_equipment_references.brands[0].url,bag.url);
 const directory=c.publicDirectoryData({brands:data.brands.map(row=>({...row,road_reference:true})),teams:[{code:'team'}]},data);assert.deepEqual(Array.from(directory.brands,row=>row.code),['canyon']);assert.equal(directory.brands[0].reference_category_group,'other');assert.equal(directory.brands[0].official_url,bag.url);assert.equal(directory.teams[0].code,'team');assert.equal(JSON.stringify(data),original);
 const stale={catalog:projected,directories:directory,details:{'old-bike':{variants:{v:{...bike,product_id:'old-bike'}}},bag:{variants:{v:{...bag,product_id:'bag',colors:[{product_id:'old-bike'},{product_id:'bag'}]}}}},updates:{items:[{id:1,event_key:'a'.repeat(64),product:{...bike,product_id:'old-bike'}},{id:2,event_key:'b'.repeat(64),product:{...bag,product_id:'bag'}}]}};
 c.applyPublicVisibility(stale);assert.deepEqual(Object.keys(stale.details),['bag']);assert.deepEqual(Array.from(stale.details.bag.variants.v.colors,row=>row.product_id),['bag']);assert.equal(stale.updates.items.length,1);assert.equal(stale.updates.items[0].product.product_id,'bag');
 for(const row of data.products.filter(row=>row.category_group==='road_equipment')){assert.equal(c.publicProductVisible({product_id:row.id}),false);assert.equal(c.publicProductVisible({offer:{url:row.url}}),false)}
 assert.equal(c.publicProductVisible({offer:{url:bag.url}}),true);
 const malformed={id:4,event_key:'bad',category:'frames'};stale.updates.items=[null,malformed];c.applyPublicVisibility(stale);assert.equal(stale.updates.items.length,2,'Invalid event rows must reach the existing authoritative snapshot validator');assert.equal(stale.updates.items[0],null);assert.equal(stale.updates.items[1],malformed);stale.updates.items=null;c.applyPublicVisibility(stale);assert.equal(stale.updates.items,null,'Invalid snapshot shape is not repaired by visibility projection');
}
function testGroupLeafSourceSearchAndReset(){
 const {c,elem,groupButtons,productButton}=harness();c.items=[{name:'Jersey',brand:'Test',category:'jerseys',category_group:'clothing',source_codes:['team']},{name:'Bottle',brand:'Test',category:'accessories',category_group:'other',source_codes:['team']},{name:'Bottle',brand:'Other',category:'accessories',category_group:'other',source_codes:['other']}];
 assert.equal(groups.length,4);assert.ok(!fs.readFileSync('web/index.html','utf8').includes('id="categoryNav"'));
 c.chooseCategoryGroup('road_equipment');assert.equal(c.activeCategoryGroup,null);assert.equal(c.activeSource,'team');assert.equal(c.visibleItems().length,2);assert.equal(elem('browseLabel').textContent,'车队');assert.ok(groupButtons.every(button=>button['aria-pressed']==='false')); 
 c.chooseCategoryGroup('other');assert.equal(c.visibleItems().length,1);assert.equal(elem('browseLabel').textContent,'车队 · 配件与周边');
 c.chooseCategory('frames');assert.equal(c.activeCategory,'all');assert.equal(c.activeCategoryGroup,'other');assert.equal(c.visibleItems().length,1);
 elem('q').value='missing';assert.equal(c.visibleItems().length,0);c.chooseCategoryGroup('clothing');assert.equal(c.activeSource,'team');assert.equal(elem('q').value,'missing');assert.equal(c.activeCategory,'all');elem('q').value='jersey';assert.equal(c.visibleItems().length,1);
 c.chooseCategoryGroup('clothing');assert.equal(c.activeCategoryGroup,null,'Clicking active group clears only group');assert.equal(c.activeSource,'team');
 vm.runInContext(section(flows,"document.querySelectorAll('[data-tab]').forEach(b=>b.onclick",'const panelError='),c);productButton.onclick();assert.equal(c.activeSource,null);assert.equal(c.activeCategoryGroup,null);assert.equal(c.activeCategory,'all');assert.equal(elem('q').value,'');assert.equal(c.visibleItems().length,0,'Ordinary cards never enter featured after reset');
}
function testGroupHistoryAndOldState(){
 const {c,elem}=harness();c.chooseCategoryGroup('other');elem('q').value='Bottle';c.activeCategory='frames';c.saveBrowseState();assert.equal(c.history.state.unrelated,1);assert.equal(c.history.state.bikehuntBrowse.category,'all');c.history.state.bikehuntBrowse.category='frames';c.activeCategoryGroup=null;c.activeSource=null;elem('q').value='';c.restoreBrowseState();assert.equal(c.activeCategoryGroup,'other');assert.equal(c.activeCategory,'all');assert.equal(c.activeSource,'team');assert.equal(elem('q').value,'Bottle');
 delete c.history.state.bikehuntBrowse.categoryGroup;c.restoreBrowseState();assert.equal(c.activeCategoryGroup,null);c.history.state.bikehuntBrowse.categoryGroup='malformed';c.restoreBrowseState();assert.equal(c.activeCategoryGroup,null);
 // A cached five-group payload cannot resurrect the hidden group or bike-only source.
 c.categoryGroups=[{code:'road_equipment',name:'自行车'},...groups];
 for(const source of ['trek','specialized','colnago']){c.history.state.bikehuntBrowse={tab:'products',categoryGroup:'road_equipment',category:'frames',source,query:'Allez'};c.restoreBrowseState();assert.equal(c.activeCategoryGroup,null);assert.equal(c.activeCategory,'all');assert.equal(c.activeSource,null);assert.equal(elem('q').value,'Allez')}
 c.chooseCategoryGroup('road_equipment');assert.equal(c.activeCategoryGroup,null);
 c.history.state.bikehuntBrowse={tab:'products',categoryGroup:'other',category:'frames',source:'canyon',query:'Midloader'};c.restoreBrowseState();assert.equal(c.activeCategoryGroup,'other');assert.equal(c.activeSource,'canyon');assert.equal(c.activeCategory,'all');assert.equal(elem('q').value,'Midloader');
}
function testResearchSeparationFilteringAndExactGuard(){
 const {c,elem,eventHandlers}=harness();c.activeSource=null;c.activeCategoryGroup='other';let html=c.roadReferenceMarkup();assert.equal((html.match(/data-road-reference-card=/g)||[]).length,1);assert.ok(html.includes('Canyon Midloader'));for(const required of ['美国官网标价，库存待核实','不进入精选好价','未取得折扣结束时间'])assert.ok(html.includes(required),required);assert.ok(!html.includes('data-purchase-link'));assert.ok(!html.includes('data-route-select'));assert.ok(!html.includes('target="_blank"'));
 for(const row of data.products.filter(row=>row.category_group==='road_equipment'))assert.ok(!html.includes(row.id),'Stale bike/frame research stays hidden');
 for(const code of ['trek','specialized','colnago'])assert.ok(!html.includes('brand:'+code),'Bike-only brand entrances stay hidden');
 c.activeCategory='frames';assert.equal((c.roadReferenceMarkup().match(/data-road-reference-card=/g)||[]).length,1,'Retired leaf state has no effect');c.activeSource='canyon';elem('q').value='Midloader';
 const row=c.roadReferenceData.products.find(row=>row.id==='canyon-9102039');mountDetail(c,elem,row);
 const link={isConnected:true,dataset:{roadReference:'product:'+row.id},href:row.url,getAttribute(){return this.href}};let prevented=false;c.guardRoadReferenceExit({type:'click',target:{closest:()=>link},preventDefault(){prevented=true}});assert.ok(prevented);assert.ok(c.exit.validate());assert.equal(c.exit.url,row.url);link.href=row.url+'?wrong=1';assert.equal(c.exit.validate(),false);assert.equal(c.roadReferenceUrl({...row,url:'https://www.canyon.com.evil/en-us/x'}),'');assert.equal(c.roadReferenceUrl({...row,url:'https://www.canyon.com/en-gb/x'}),'');
 c.items=data.products.map(p=>({...p,name_zh:p.name,source_codes:[p.source_code],stock_state:'unknown'}));c.activeSource=null;elem('q').value='';assert.equal(c.visibleItems().length,0,'Research cards cannot qualify as featured');
 assert.equal(data.products.filter(p=>p.image).length,3);assert.ok(html.includes('data-reference-image'));assert.ok(c.referenceImageMarkup(undefined,'missing').includes('商品图片待核实'));for(const url of ['javascript:alert(1)','http://example.com/photo.jpg','https://user:password@example.com/photo.jpg'])assert.ok(!c.referenceImageMarkup(url,'unsafe').includes('<img'));
 const fallback={hidden:true},failedImage={hidden:false,matches:selector=>selector==='img[data-reference-image]',nextElementSibling:fallback};eventHandlers.get('error')({target:failedImage});assert.equal(failedImage.hidden,true);assert.equal(fallback.hidden,false,'Failed exact image exposes text rather than a generic substitute');
 const image='https://example.com/exact-product.jpg';assert.ok(c.historicalDiscountMarkup([{product_id:'history',brand:'Test',name:'Exact product',image,reference_price:{amount:90,currency:'USD'},reference_original_price:{amount:120,currency:'USD'}}]).includes('src="'+image+'"'));
}
function testStalePayloadAndHiddenIdRejection(){
 const {c,elem}=harness();c.activeSource=null;c.activeCategoryGroup=null;
 c.items=[{product_id:'bike',name:'Road Bike',brand:'Test',category:'road_bikes',category_group:'road_equipment',source_codes:['canyon'],featured:true},{product_id:'frame',name:'Frameset',brand:'Test',category:'frames',category_group:'other',source_codes:['canyon'],featured:true},{product_id:'group-only',name:'Old model',brand:'Test',category:'accessories',category_group:'road_equipment',source_codes:['canyon'],featured:true},{product_id:'accessory',name:'Bag',brand:'Test',category:'accessories',category_group:'other',source_codes:['canyon'],featured:true}];
 for(const includeUnverified of [false,true])assert.deepEqual(Array.from(c.visibleItems(includeUnverified),row=>row.product_id),['accessory']);
 c.activeSource='canyon';elem('q').value='';assert.deepEqual(Array.from(c.visibleItems(),row=>row.product_id),['accessory']);elem('q').value='Road Bike';assert.equal(c.visibleItems(true).length,0);elem('q').value='';
 elem('roadReferenceInline').contains=()=>true;
 for(const row of c.roadReferenceData.products.filter(row=>row.category_group==='road_equipment')){
   const opener={isConnected:true,dataset:{roadOpen:row.id}};assert.equal(c.allowedRoadDetailButton(opener),null);c.openRoadReferenceDetail(row.id);assert.equal(c.panel,undefined,'Old reference IDs cannot open a detail');
   c.sheet.classList.add('open');elem('roadReferenceDetail').dataset.roadDetail=row.id;elem('roadReferenceDetail').contains=()=>true;c.oldId=row.id;c.oldUrl=row.url;vm.runInContext('roadDetailContext={id:oldId,url:oldUrl}',c);
   const link={isConnected:true,dataset:{roadReference:'product:'+row.id},getAttribute:()=>row.url};assert.equal(c.allowedRoadReference(link),null,'Restored detail context cannot restore a hidden exit');c.sheet.classList.remove('open');
 }
 c.activeCategoryGroup='road_equipment';assert.equal((c.roadReferenceMarkup().match(/data-road-reference-card=/g)||[]).length,0);
 c.activeCategoryGroup='other';assert.equal((c.roadReferenceMarkup().match(/data-road-reference-card=/g)||[]).length,1);
}
function testInlineFallbackFilteringAndLiveGuard(){
 const {c,elem}=harness();c.activeSource=null;c.activeCategoryGroup='other';
 assert.equal(c.renderEmptyReferences(),true);let html=c.gallery.innerHTML;
 assert.equal((html.match(/data-road-reference-card=/g)||[]).length,1);assert.ok(html.includes('id="roadReferenceInline"'));
 assert.ok(html.indexOf('data-road-reference-card=')<html.indexOf('road-brand-entrances'));
 assert.ok(html.includes('价格观察时间未记录'));assert.ok(html.includes('记录现价'));assert.ok(html.includes('记录原价'));assert.ok(!html.includes('class="card'));
 assert.ok(c.gallery.classList.contains('reference-feed'));assert.ok(c.document.body.classList.contains('reference-feed-visible'));
 c.activeSource='team';c.renderEmptyReferences();assert.equal((c.gallery.innerHTML.match(/data-road-reference-card=/g)||[]).length,0,'Team source must not leak unrelated research');
 c.activeSource='canyon';c.renderEmptyReferences();assert.equal((c.gallery.innerHTML.match(/data-road-reference-card=/g)||[]).length,1);
 elem('q').value='Frameset';c.renderEmptyReferences();assert.equal((c.gallery.innerHTML.match(/data-road-reference-card=/g)||[]).length,0);
 elem('q').value='Midloader';c.renderEmptyReferences();assert.equal((c.gallery.innerHTML.match(/data-road-reference-card=/g)||[]).length,1);
 elem('roadReferenceInline').contains=()=>true;
 const row=c.roadReferenceData.products.find(r=>r.id==='canyon-9102039'),link={isConnected:true,dataset:{roadReference:'product:'+row.id},getAttribute:()=>row.url};
 assert.equal(c.allowedRoadReference(link),null,'A product cannot exit directly from its card');
 const opener={isConnected:true,dataset:{roadOpen:row.id},focus(){c.focus=this}};
 const selected=c.allowedRoadDetailButton(opener);assert.equal(selected.row,row);assert.equal(selected.origin,'inline');
 c.openRoadReferenceDetail(row.id,selected);elem('roadReferenceDetail').dataset.roadDetail=row.id;elem('roadReferenceDetail').contains=()=>true;
 assert.ok(c.panel.includes('id="roadReferenceDetail"'));assert.ok(c.panel.includes('data-road-reference="product:'+row.id+'"'));
 assert.equal(c.allowedRoadReference(link),row,'Unknown stock allows a guarded reference visit after the guide');
 c.guardRoadReferenceExit({type:'click',target:{closest:()=>link},preventDefault(){}});assert.equal(c.exit.kind,'reference');assert.ok(c.exit.validate());
 c.exit.onConfirm();assert.equal(c.history.state.bikehuntBrowse.query,'Midloader');assert.equal(c.history.state.bikehuntBrowse.source,'canyon');assert.equal(c.history.state.bikehuntBrowse.categoryGroup,'other');
 row.stock='out_of_stock';assert.equal(c.exit.validate(),false,'Stock changes invalidate an already-open final gate');assert.ok(c.roadReferenceDetailMarkup(row).includes('已确认售罄'));assert.ok(!c.roadReferenceDetailMarkup(row).includes('data-road-reference="product:'+row.id+'"'));
 row.stock='unknown';assert.equal(c.allowedRoadReference(link),row);elem('q').value='different';assert.equal(c.allowedRoadReference(link),null,'Current filters revalidate the link');elem('q').value='Midloader';
 c.activeCategoryGroup='road_equipment';assert.equal(c.allowedRoadReference(link),null,'Accessory link cannot escape the current group');c.activeCategoryGroup='other';
 c.activeTab='brands';assert.equal(c.allowedRoadReference(link),null);c.activeTab='products';link.isConnected=false;assert.equal(c.allowedRoadReference(link),null);link.isConnected=true;
 elem('roadReferenceDetail').dataset.roadDetail='wrong';assert.equal(c.allowedRoadReference(link),null);elem('roadReferenceDetail').dataset.roadDetail=row.id;
 elem('roadReferenceBack').onclick();assert.equal(c.sheet.classList.contains('open'),false);assert.equal(c.focus,opener);assert.equal(c.allowedRoadReference(link),null);
 c.activeCategoryGroup='clothing';assert.equal(c.renderEmptyReferences(),false);c.resetReferenceFeed();assert.ok(!c.gallery.classList.contains('reference-feed'));
}
function testEquipmentGenderIndependence(){
 const {c,elem,genderButtons}=harness();c.activeCategoryGroup='clothing';c.syncBrowseControls();assert.equal(elem('genderFilter').hidden,false);c.shopperProfile.gender='female';
 assert.equal(c.profileMatches({category_group:'clothing',gender:'male'}),false);assert.equal(c.profileMatches({category_group:'clothing',gender:'unisex'}),true);
 for(const group of ['road_equipment','cleat_shoes','helmets','other',null]){c.shopperProfile.gender='female';c.activeCategoryGroup=group;c.syncBrowseControls();assert.equal(elem('genderFilter').hidden,true);assert.equal(c.shopperProfile.gender,'all');assert.equal(c.savedProfile.gender,'all');assert.equal(c.profileMatches({category_group:group,gender:'male'}),true);assert.equal(genderButtons[0]['aria-pressed'],'true')}
 c.activeCategoryGroup='clothing';c.syncBrowseControls();assert.equal(elem('genderFilter').hidden,false);assert.equal(c.shopperProfile.gender,'all');c.activeTab='brands';c.syncBrowseControls();assert.equal(elem('genderFilter').hidden,true);
}
function testReferenceGuideAndCurrencySafety(){
 const {c}=harness();c.activeSource=null;c.activeCategoryGroup='other';const row=c.roadReferenceData.products.find(row=>row.id==='canyon-9102039'),original=JSON.stringify(c.roadReferenceData);
 const html=c.roadReferenceDetailMarkup(row);
 for(const text of ['id="roadReferenceDetail"','记录现价','记录原价','¥391.65','¥489.65','人民币仅为商品价换算','运费、税费待核实','不是到手总价','价格观察时间未记录','库存待核实','非现货，不可选择','容量、尺寸与车架空间','中国直邮和转运许可均待核实','不套用服装税率','支付方式与中国发行卡：待核实','Create account','id="roadReferenceRegistration"','id="roadReferenceLanguage"','target="_self"'])assert.ok(html.includes(text),text);
 for(const forbidden of ['<select','data-purchase-link','data-route-select','recommended_total_cny','data-bundle','20%','target="_blank"'])assert.ok(!html.includes(forbidden),forbidden);
 assert.ok(!c.roadReferenceCard(row).includes('data-road-reference='),'Cards open internal detail only');assert.ok(c.roadReferenceCard(row).includes('data-road-open='));
 assert.equal(c.roadReferenceFx('USD').state,'current');assert.ok(c.roadReferenceFxMarkup(row).includes('每日参考'));
 c.fx.stale=true;assert.equal(c.roadReferenceFx('USD').state,'stale');assert.ok(c.roadReferenceFxMarkup(row).includes('过期缓存'));assert.ok(c.roadReferencePriceMarkup(row).includes('¥391.65'));
 c.fx.stale=false;c.fx.fetched_at=new Date(Date.now()-86400001).toISOString();assert.equal(c.roadReferenceFx('USD').state,'stale');
 c.fx.fetched_at=new Date(Date.now()+600000).toISOString();assert.equal(c.roadReferenceFx('USD').state,'stale');
 c.fx.fetched_at=new Date().toISOString();c.fx.rate_date='2026-02-30';assert.equal(c.roadReferenceFx('USD').state,'unknown');
 for(const invalid of [null,'',0,-1,'NaN','Infinity']){c.fx.rate_date=new Date().toISOString().slice(0,10);c.fx.rates.USD=invalid;assert.equal(c.roadReferenceFx('USD').state,'unknown');assert.ok(c.roadReferencePriceMarkup(row).includes('人民币待换算'));assert.ok(!c.roadReferencePriceMarkup(row).includes('¥0.00'))}
 c.fx={};assert.ok(c.roadReferenceFxMarkup(row).includes('汇率待获取'));assert.equal(JSON.stringify(c.roadReferenceData),original,'FX never edits reference or inventory facts');
}
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
for(const test of [testPublicProjectionRejectsOldPayload,testGroupLeafSourceSearchAndReset,testGroupHistoryAndOldState,testResearchSeparationFilteringAndExactGuard,testStalePayloadAndHiddenIdRejection,testInlineFallbackFilteringAndLiveGuard,testEquipmentGenderIndependence,testReferenceGuideAndCurrencySafety,testTrekAndSpecializedRestrictiveFallback,testNewBrandPaymentsStayUnknown]){test();console.log('PASS '+test.name)}
console.log('Four public groups and accessory-reference tests: ten groups passed.');
