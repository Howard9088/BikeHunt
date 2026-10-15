'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const gallery=fs.readFileSync('web/gallery.js','utf8'),flows=fs.readFileSync('web/flows.js','utf8');
const home=fs.readFileSync('web/index.html','utf8');
assert.ok(!home.includes('wechatReminder'));assert.ok(!flows.includes('showWechat'));
assert.match(home, /id="wechatCommunity">加入骑游海淘交流群<\/button>/);
assert.ok(home.includes('id="priceMessages"'));assert.ok(home.includes('id="amazonChannels"'));
function section(source,start,end){return source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)))}
function harness(saved=null){
 const storage=new Map(saved?[['bikehuntMessagesReadCursor',saved]]:[]),badge={setAttribute(k,v){this[k]=v}},refs=new Map(),links=[];
 const c=vm.createContext({Date,URL,Number,Map,Set,JSON,activeCategoryGroup:null,activeTab:'products',categories:[{code:'all'},{code:'jerseys'},{code:'bibs'}],categoryGroups:[],roadReferenceData:{brands:[],products:[]},syncBrowseControls(){},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},document:{addEventListener(){},body:{classList:{toggle(){}}},getElementById:()=>badge,querySelectorAll:()=>links},referenceOffers:refs,showExternalExit:()=>{throw Error('Purchase entrances must open local stages before confirmation')},window:{confirm:()=>{throw Error('No native exit prompt')}},guideContext:null,saveBrowseState:()=>{},PURCHASE_DISCLAIMER:'disclaimer',timeText:x=>x,money:(v,c)=>c+v,cny:v=>'CNY'+v});
 vm.runInContext(fs.readFileSync('web/public-visibility.js','utf8'),c);
 vm.runInContext(section(gallery,'const e=value','function money('),c);
 vm.runInContext(section(gallery,'function inventoryVerified(','function offerMarkup('),c);
 vm.runInContext(section(flows,'const messageEvents=','const directoryPage='),c);
 vm.runInContext(section(flows,'function eventProduct(','async function refreshCatalogSilently('),c);
 vm.runInContext(section(flows,'function invalidateReferenceLinks(',"document.addEventListener('click',guardPurchaseExit)"),c);
 return {c,refs,links,badge,storage};
}
function row(id=1,overrides={}){
 const url='https://shop.example/products/26-173-bah?variant='+id;
 return {id,event_key:id.toString(16).padStart(64,'0'),source_code:'bahrain',source_name:'Bahrain',kind:'price_changed',category:'jerseys',offer_id:'o'+id,name_zh:'Short Sleeve Jersey Man Bahrain Victorious',old_price:'148',new_price:'149',currency:'USD',stock:'in_stock',observed_at:'2026-10-14T12:00:00Z',url,product:{offer_id:'o'+id,url,name:'Generic jersey',brand:'Ale',model:'Jersey',color:'red',size:id===1?'M':'L',image:'https://shop.example/red.jpg',product_id:'family-a',variant_id:'v'+id,current_stock:'in_stock'},...overrides};
}
function click(link,type='click',button=0){return {type,button,target:{closest:()=>link},prevented:false,preventDefault(){this.prevented=true}}}
function testGroupingAndExactPictures(){
 const h=harness(),a=row(),b=row(2),different=row(3);different.url=different.product.url='https://shop.example/products/26-175-bah?variant=3';different.product.product_id='family-b';different.product.image='https://shop.example/white.jpg';different.old_price='107';different.new_price='108';
 const groups=h.c.groupMessages([a,b,different]);assert.equal(groups.length,2);assert.equal(groups[0].members.length,2);
 const html=h.c.messageCardMarkup(groups[0],{rates:{USD:7}});assert.ok(html.includes('red.jpg'));assert.ok(html.includes('M / L'));assert.ok(html.includes('data-message-variant="v1"'));assert.ok(html.includes('data-message-variant="v2"'));assert.ok(!html.includes('href='));assert.ok(html.includes('data-message-product="family-a"'));
 for(const [field,value] of [['stock','out_of_stock'],['currency','EUR'],['old_price','147'],['new_price','150'],['kind','inventory_changed'],['observed_at','2026-10-14T13:00:00Z']])assert.equal(h.c.groupMessages([a,{...b,[field]:value}]).length,2,field);
 for(const [field,value] of [['model','other'],['color','white'],['image','https://shop.example/other.jpg']])assert.equal(h.c.groupMessages([a,{...b,product:{...b.product,[field]:value}}]).length,2,field);
 const missing={...a,product:null};assert.ok(h.c.messageCardMarkup(missing,{}).includes('暂无该商品图片'));assert.ok(!h.c.messageCardMarkup(missing,{}).includes('<img'));
 const wrong={...a,product:{...a.product,offer_id:'wrong'}};assert.ok(!h.c.messageCardMarkup(wrong,{}).includes('<img'));
}
function testReadIdsReloadIncrementFilteredAndCap(){
 const h=harness();h.c.rememberMessageEvents({items:[row(1),row(2),row(3,{observed_at:'other-batch'})]});assert.equal(h.badge.textContent,'2');
 h.c.markMessagesRead([row(1),row(2)]);assert.equal(h.badge.textContent,'1','Reading one group does not read unrelated unseen events');
 const reload=harness(h.storage.get('bikehuntMessagesReadCursor'));reload.c.rememberMessageEvents({items:[row(1),row(2),row(3,{observed_at:'other-batch'})]});assert.equal(reload.badge.textContent,'1');
 reload.c.markMessagesRead([row(3)]);assert.equal(reload.badge.hidden,true);
 reload.c.rememberMessageEvents({items:[row(4,{observed_at:'new-batch'}),row(5,{observed_at:'new-batch'})]});assert.equal(reload.badge.textContent,'1');
 reload.c.rememberMessageEvents({items:Array.from({length:101},(_,i)=>row(i+10,{product:null}))});assert.equal(reload.badge.textContent,'99+');
}
async function testReferenceExitCancelContinueSoldoutAndLatestRecheck(){
 const h=harness(),q={reference_product_id:'p',reference_variant_id:'v',offer:{offer_id:'o',url:'https://shop.example/products/stale?variant=m',stock:'in_stock',fetched_at:'2000-01-01T00:00:00Z'}};
 const markup=h.c.referenceLinkMarkup(q);assert.ok(markup.includes('比较路线并核实库存'));assert.ok(markup.includes('target="_self"'));assert.ok(!markup.includes('target="_blank"'));const key='o|'+q.offer.url;
 const link={dataset:{referenceLink:key},href:q.offer.url,getAttribute(){return this.href},removeAttribute(){this.href=null},setAttribute(){}};h.links.push(link);
 let routes=0;h.c.startReferenceRoute=quote=>{assert.equal(quote,q);routes++};
 h.c.showExternalExit=()=>{throw Error('Reference entry must open routes before registration/disclaimer')};let e;
 for(const [type,button] of [['click',0],['auxclick',1]]){e=click(link,type,button);h.c.guardPurchaseExit(e);assert.equal(e.prevented,true,'Reference navigation must be staged');}assert.equal(routes,2);
 h.c.showExternalExit=()=>{throw Error('No prompt for invalid URL')};link.href='javascript:alert(1)';e=click(link);h.c.guardPurchaseExit(e);assert.equal(e.prevented,true);assert.equal(routes,2);link.href=q.offer.url;
 h.c.getJson=async()=>({offers:[{offer:{...q.offer,stock:'out_of_stock'}}]});await h.c.refreshReferenceLinks();assert.equal(q.offer.stock,'out_of_stock');assert.equal(link.href,null);e=click(link);h.c.guardPurchaseExit(e);assert.equal(e.prevented,true);
 assert.equal(h.c.referenceLinkMarkup(q),'');assert.equal(routes,2,'Observed sold-out quote cannot re-enter routes');
 const sold=row(9);sold.product.current_stock='out_of_stock';const html=h.c.messageCardMarkup(sold,{});assert.ok(!html.includes('href='));assert.ok(html.includes('已售罄'));
}
function testXssAndUrlGuards(){
 const h=harness(),evil=row();evil.name_zh='<img src=x onerror=alert(1)>';evil.product.model='\"><script>bad()</script>';evil.product.image='javascript:alert(1)';evil.url=evil.product.url='javascript:alert(1)';const html=h.c.messageCardMarkup(evil,{});assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img'));assert.ok(!html.includes('href='));assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('已售罄'));
 assert.equal(h.c.merchantUrl('https://user:password@shop.example/p'),'');assert.equal(h.c.merchantUrl('data:text/html,test'),'');assert.equal(h.c.merchantUrl('http://shop.example/p'),'');
}
function testCategoryScopeAndExplicitGlobalReset(){
 const h=harness(),categoryButtons=['all','jerseys','bibs'].map(category=>({dataset:{category},setAttribute(){}})),productButton={dataset:{tab:'products'}};
 Object.assign(h.c,{activeSource:'bahrain',activeCategory:'all',directoryData:{brands:[],teams:[{code:'bahrain',name_zh:'巴林车队'}]},navigate:()=>{},profileMatches:()=>true,items:[{source_codes:['bahrain'],category:'jerseys',stock_state:'unknown',brand:'Ale',name:'Jersey'},{source_codes:['other'],category:'jerseys',stock_state:'in_stock',brand:'Other',name:'Jersey'}]});
 h.c.document.querySelectorAll=selector=>selector==='[data-category]'?categoryButtons:selector==='[data-tab]'?[productButton]:[];h.badge.value='';
 vm.runInContext(section(flows,'function chooseCategory(','function renderDirectory('),h.c);
 vm.runInContext(section(gallery,'function featuredBrowse(','function render('),h.c);
 h.c.chooseCategory('jerseys');assert.equal(h.c.activeSource,'bahrain');assert.equal(h.badge.textContent,'巴林车队');assert.equal(h.c.visibleItems().length,1);
 h.c.chooseCategory('all');assert.equal(h.c.activeSource,'bahrain');
 vm.runInContext(section(flows,"document.querySelectorAll('[data-tab]').forEach(b=>b.onclick",'const panelError='),h.c);productButton.onclick();assert.equal(h.c.activeSource,null);assert.equal(h.badge.textContent,'精选好价');assert.equal(h.c.visibleItems().length,0,'Default feed excludes ordinary reference cards');
}
async function testDismissedMessagesDoNotReopenOrReadUnseenRows(){
 const h=harness();let resolve;Object.assign(h.c,{messagesOpen:false,detailSequence:0,sheet:{classList:{contains:()=>true}},openPanel(){h.c.detailSequence++},getJson:()=>new Promise(done=>{resolve=done})});
 const pending=h.c.showMessages();h.c.messagesOpen=false;h.c.detailSequence++;resolve({items:[row()],cursor:1,fx:{}});await pending;assert.equal(h.badge.hidden,false);assert.equal(h.badge.textContent,'1');assert.equal(h.storage.has('bikehuntMessagesReadCursor'),false);
}
function testHistoryScopeValidationAndBackPollingRestart(){
 const h=harness(),buttons=['all','jerseys'].map(category=>({dataset:{category},setAttribute(){}})),input={value:'Stamp Hoodie'},clear={focus(){}};
 Object.assign(h.c,{activeTab:'products',activeSource:'bahrain',activeCategory:'jerseys',categories:[{code:'all'},{code:'jerseys'}],directoryData:{brands:[],teams:[{code:'bahrain',name_zh:'巴林车队'}]},history:{state:{other:'preserved'},replaceState(state){this.state=state}},navigate(tab){h.c.activeTab=tab},updateBrowseLabel(){},});
 h.c.document.querySelectorAll=()=>buttons;h.c.document.getElementById=id=>id==='q'?input:clear;
 vm.runInContext(section(flows,'function saveBrowseState(','function navigate('),h.c);
 h.c.saveBrowseState();assert.equal(h.c.history.state.other,'preserved');assert.equal(h.c.history.state.bikehuntBrowse.source,'bahrain');assert.equal(h.c.history.state.bikehuntBrowse.query,'Stamp Hoodie');
 h.c.activeSource=null;h.c.activeCategory='all';input.value='';h.c.restoreBrowseState();assert.equal(h.c.activeSource,'bahrain');assert.equal(h.c.activeCategory,'all');assert.equal(input.value,'Stamp Hoodie');
 Object.assign(h.c,{profileMatches:()=>true,items:[{brand:'Test',name:'Stamp Hoodie',category:'jerseys',source_codes:['bahrain']},{brand:'Test',name:'Other jersey',category:'jerseys',source_codes:['bahrain']}]});
 vm.runInContext(section(gallery,'function featuredBrowse(','function render('),h.c);assert.equal(h.c.visibleItems().length,1,'Restoring text restores the actual filter, not only the input appearance');
 for(const query of [undefined,null,42,{},[],['Stamp Hoodie'],'x'.repeat(201)]){
  h.c.history.state.bikehuntBrowse.query=query;input.value='old';h.c.restoreBrowseState();assert.equal(input.value,'','Invalid or oversized history query is discarded');assert.equal(h.c.visibleItems().length,2);
  input.value=query;h.c.saveBrowseState();assert.equal(h.c.history.state.bikehuntBrowse.query,'','Invalid or oversized input is never saved');
 }
 for(const query of ['x'.repeat(200),'  Stamp Hoodie  ','<img src=x onerror=alert(1)>']){input.value=query;h.c.saveBrowseState();input.value='';h.c.restoreBrowseState();assert.equal(input.value,query,'Bounded text is restored literally');}
 h.c.history.state.bikehuntBrowse={tab:'invalid',source:'removed-source',category:'removed-category'};h.c.restoreBrowseState();assert.equal(h.c.activeSource,null);assert.equal(h.c.activeCategory,'all');assert.equal(h.c.activeTab,'products');assert.equal(input.value,'');
 let handler,reloads=0;h.c.window={addEventListener(name,fn){assert.equal(name,'pageshow');handler=fn},location:{reload(){reloads++}}};vm.runInContext(flows.slice(flows.lastIndexOf("window.addEventListener('pageshow'")),h.c);handler({persisted:false});assert.equal(reloads,0);handler({persisted:true});assert.equal(reloads,1);
}
function testMessagesOpenOnlyExactInternalProducts(){
 const h=harness();let opened;Object.assign(h.c,{messagesOpen:true,guideContext:{},openProduct(...args){opened=args}});
 const event=row(),route=h.c.messageProductRoute(event);h.c.openMessageProduct(route.productId,route.variantId);assert.deepEqual(opened,['family-a','v1',true]);assert.equal(h.c.messagesOpen,false);assert.equal(h.c.guideContext,null);
 const sold={...event,stock:'out_of_stock'};assert.ok(h.c.messageCardMarkup(sold,{}).includes('data-message-product="family-a"'));assert.ok(!h.c.messageCardMarkup(sold,{}).includes('href='));
 const missing={...event,product:{...event.product,product_id:null,variant_id:null}};assert.equal(h.c.messageProductRoute(missing),null);const html=h.c.messageCardMarkup(missing,{});assert.ok(html.includes('该商品详情暂不可用'));assert.ok(!html.includes('data-message-product='));assert.ok(!html.includes('href='));
}
function testStableReadKeysSurviveIdReuseAndTimestampRepeats(){
 const h=harness(),original=row(50),key=original.event_key;
 h.c.rememberMessageEvents({items:[original]});h.c.markMessagesRead([original]);assert.equal(h.badge.hidden,true);
 const renumbered={...original,id:500};h.c.rememberMessageEvents({items:[renumbered]});assert.equal(h.badge.hidden,true,'Same event key stays read after ID changes');
 const collision={...original,event_key:'f'.repeat(64)};h.c.rememberMessageEvents({items:[collision]});assert.equal(h.badge.textContent,'1');assert.equal(h.badge.hidden,false,'Reused numeric ID with a different event key is unread');
 h.c.markMessagesRead([collision]);assert.equal(h.badge.hidden,true);
 h.c.rememberMessageEvents({items:[{...original,id:700},{...collision,id:701}]});assert.equal(h.badge.hidden,true,'Repeated timestamps and rows do not reset read state');
 const reload=harness(h.storage.get('bikehuntMessagesReadCursor'));reload.c.rememberMessageEvents({items:[renumbered,collision]});assert.equal(reload.badge.hidden,true);
 reload.c.rememberMessageEvents({items:[{...original,id:702,event_key:'e'.repeat(64)}]});assert.equal(reload.badge.textContent,'1');assert.equal(reload.badge.hidden,false,'New key is unread even with an unchanged observation timestamp');
 const saved=JSON.parse(reload.storage.get('bikehuntMessagesReadCursor'));assert.equal(saved.version,2);assert.ok(saved.seenKeys.includes(key));assert.equal(saved.seen,undefined);
}
function testLegacyIdReadsMigrateExactlyOnce(){
 const first=row(7),unseen=row(8,{observed_at:'different-batch'}),h=harness(JSON.stringify({seen:[7]}));
 h.c.rememberMessageEvents({items:[first,unseen]});assert.equal(h.badge.textContent,'1');const saved=JSON.parse(h.storage.get('bikehuntMessagesReadCursor'));assert.deepEqual(saved.seenKeys,[first.event_key]);
 h.c.rememberMessageEvents({items:[{...first,event_key:'b'.repeat(64)},unseen]});assert.equal(h.badge.textContent,'2','Legacy ID is not reused after the one-time migration');
 const reload=harness(h.storage.get('bikehuntMessagesReadCursor'));reload.c.rememberMessageEvents({items:[first]});assert.equal(reload.badge.hidden,true);
 const mixed=harness(JSON.stringify({version:2,seenKeys:[first.event_key],seen:[8]}));mixed.c.rememberMessageEvents({items:[first,unseen]});assert.equal(mixed.badge.textContent,'1','Version 2 ignores any leftover numeric IDs');
 const missing=harness(JSON.stringify({seen:[999]}));missing.c.rememberMessageEvents({items:[first]});missing.c.rememberMessageEvents({items:[row(999,{observed_at:'later-batch'}),first]});assert.equal(missing.badge.textContent,'2','An unresolved old ID does not mark a later event read');
}
function testRecoveredHistoryDoesNotNotifyOrBecomeUnread(){
 const seen=row(1),recovered=row(1500,{event_key:'c'.repeat(64),kind:'new_offer',recovered_history:true}),fresh=row(1501,{event_key:'d'.repeat(64)}),h=harness(JSON.stringify({version:2,seenKeys:[seen.event_key]}));h.c.activeCategory='all';
 h.c.rememberMessageEvents({items:[seen,recovered]});assert.equal(h.badge.hidden,true,'Unseen recovered keys do not create unread messages');assert.equal(h.c.hasNewPriceMessages([recovered]),false,'Historical recovery does not show a new-message toast');
 const html=h.c.messageCardMarkup(recovered,{});assert.ok(html.includes('恢复的历史记录'));assert.ok(html.includes('历史记录：'));assert.ok(!html.includes('新发现报价：'));
 h.c.rememberMessageEvents({items:[fresh]});assert.equal(h.badge.textContent,'1');assert.equal(h.badge.hidden,false);assert.equal(h.c.hasNewPriceMessages([recovered,fresh]),true);
 h.c.markMessagesRead([fresh]);assert.equal(h.badge.hidden,true);const saved=JSON.parse(h.storage.get('bikehuntMessagesReadCursor'));assert.ok(saved.seenKeys.includes(seen.event_key));assert.ok(saved.seenKeys.includes(fresh.event_key));assert.ok(!saved.seenKeys.includes(recovered.event_key),'Suppressing recovered history does not invent read receipts');
 assert.equal(h.c.groupMessages([fresh,{...fresh,id:1600,event_key:'e'.repeat(64),recovered_history:true}]).length,2,'Historical recovery remains distinct from a genuine new group');
 const current={offer:{offer_id:'currently-restocked',url:'https://shop.example/products/current',stock:'in_stock'}};h.c.referenceLinkMarkup(current);
 h.c.invalidateReferenceLinks([{offer_id:current.offer.offer_id,stock:'out_of_stock',recovered_history:true}]);assert.equal(current.offer.stock,'in_stock');assert.equal(h.c.referenceAvailable(current),true,'Recovered old sold-out status cannot invalidate a currently available reference');
 h.c.invalidateReferenceLinks([{offer_id:current.offer.offer_id,stock:'out_of_stock',recovered_history:true},{offer_id:current.offer.offer_id,stock:'out_of_stock'}]);assert.equal(current.offer.stock,'out_of_stock','A genuine current sold-out event still invalidates the reference');
 h.c.activeCategory='bibs';assert.equal(h.c.hasNewPriceMessages([fresh]),true,'Retired leaf state cannot hide new messages');
}
function testAuthoritativeSnapshotsDropSuppressedAndOldWindowRows(){
 const h=harness(),suppressed=row(1,{product:null}),seen=row(2,{product:null}),fresh=row(3,{product:null});
 h.c.rememberMessageEvents({items:[suppressed,seen]});h.c.markMessagesRead([seen]);assert.equal(h.badge.textContent,'1');
 h.c.rememberMessageEvents({items:[fresh,seen]});assert.equal(h.badge.textContent,'1','A suppressed missing key disappears rather than inflating new unread counts');assert.equal(vm.runInContext('messageEvents.has("'+suppressed.event_key+'")',h.c),false);assert.equal(vm.runInContext('messageEvents.size',h.c),2);
 h.c.rememberMessageEvents({items:Array.from({length:100},(_,i)=>row(200+i,{product:null}))});assert.equal(vm.runInContext('messageEvents.size',h.c),100);
 h.c.rememberMessageEvents({items:Array.from({length:100},(_,i)=>row(300+i,{product:null}))});assert.equal(vm.runInContext('messageEvents.size',h.c),100,'Latest-100 snapshots never accumulate an old 500-row window');assert.equal(vm.runInContext('messageEvents.has("'+row(200).event_key+'")',h.c),false);
 h.c.rememberMessageEvents({items:[seen]});assert.equal(h.badge.hidden,true,'Reconciliation does not discard independent seen keys');
 assert.throws(()=>h.c.rememberMessageEvents({items:null}));assert.throws(()=>h.c.rememberMessageEvents({items:[fresh,null]}));assert.throws(()=>h.c.rememberMessageEvents({items:[fresh,{id:4,event_key:'malformed',category:'frames'}]}));assert.equal(vm.runInContext('messageEvents.size',h.c),1,'Malformed responses cannot erase the last valid snapshot');
}
function testGuideExitIsStagedAndBoundToExactHref() {
 const h=harness(),url='https://shop.example/products/verified?variant=M',q={offer:{offer_id:'guide',url,stock:'in_stock',collection_state:'current',fetched_at:new Date().toISOString()}};
 let saved=0,stages=0,referenceStages=0;h.c.saveBrowseState=()=>saved++;h.c.continuePurchaseRoute=()=>stages++;h.c.startReferenceRoute=()=>referenceStages++;h.c.guideContext={quote:q};
 const link={dataset:{},href:url,getAttribute(){return this.href}};
 h.c.showExternalExit=()=>{throw Error('Only the final registration Continue may prompt')};
 for(const [type,button] of [['click',0],['auxclick',1]]){const e=click(link,type,button);h.c.guardPurchaseExit(e);assert.equal(e.prevented,true);}assert.equal(stages,2);assert.equal(saved,0);
 link.href='https://shop.example/products/wrong?variant=L';let e=click(link);h.c.guardPurchaseExit(e);assert.equal(e.prevented,true);assert.equal(stages,2,'A mismatched guide href never advances or navigates');
 link.href=url;q.offer.stock='out_of_stock';e=click(link);h.c.guardPurchaseExit(e);assert.equal(e.prevented,true);assert.equal(stages,2,'Sold-out state remains blocked');
 assert.ok(!flows.includes('data-purchase-link target="_blank"'));
 const reference={offer:{offer_id:'reference',url:'https://shop.example/products/reference',stock:'unknown'}};h.c.referenceLinkMarkup(reference);const ref={dataset:{referenceLink:'reference|'+reference.offer.url},getAttribute:()=>reference.offer.url};e=click(ref);h.c.guardPurchaseExit(e);assert.equal(e.prevented,true);assert.equal(referenceStages,1);assert.equal(saved,0,'Reference stage does not navigate or save final-exit state early');
}

function testCurrencyMarketUpdateLabelWithoutPriceComparison(){
 const h=harness(),event=row(1700,{source_code:'visma',source_name:'Visma',old_price:null,new_price:'63.36',currency:'GBP'});
 const html=h.c.messageCardMarkup(event,{rates:{GBP:9.2}});
 assert.ok(html.includes('报价币种/市场更新：GBP63.36'));
 assert.ok(html.includes('商家响应的报价币种/市场发生变化，并非你切换了市场'));
 assert.ok(html.includes('不同币种报价不直接比较涨跌'));
 assert.ok(!html.includes('价格更新：'));assert.ok(!/涨价|降价|折扣/.test(html));
 assert.ok(!html.match(/<p>报价币种\/市场更新：[^<]* → /),'A changed market has no old/new comparison');
 for(const old_price of ['60','70']){
  const sameCurrency=h.c.messageCardMarkup({...event,old_price},{});
  assert.ok(sameCurrency.includes('价格更新：GBP'+old_price+' → GBP63.36'));
  assert.ok(!sameCurrency.includes('报价币种/市场更新：'));
 }
 for(const overrides of [{kind:'new_offer'},{kind:'inventory_changed'},{old_price:undefined},{recovered_history:true}]){
  const other=h.c.messageCardMarkup({...event,...overrides},{});
  assert.ok(!other.includes('报价币种/市场更新：'));assert.ok(!other.includes('商家响应'));
 }
 assert.ok(h.c.messageCardMarkup({...event,recovered_history:true},{}).includes('历史记录：GBP63.36'));
}
(async()=>{for(const t of [testGroupingAndExactPictures,testReadIdsReloadIncrementFilteredAndCap,testReferenceExitCancelContinueSoldoutAndLatestRecheck,testXssAndUrlGuards,testCategoryScopeAndExplicitGlobalReset,testDismissedMessagesDoNotReopenOrReadUnseenRows,testHistoryScopeValidationAndBackPollingRestart,testMessagesOpenOnlyExactInternalProducts,testStableReadKeysSurviveIdReuseAndTimestampRepeats,testLegacyIdReadsMigrateExactlyOnce,testRecoveredHistoryDoesNotNotifyOrBecomeUnread,testAuthoritativeSnapshotsDropSuppressedAndOldWindowRows,testGuideExitIsStagedAndBoundToExactHref,testCurrencyMarketUpdateLabelWithoutPriceComparison]){await t();console.log('PASS '+t.name)}console.log('Catalog messages: 14 production-JavaScript regression groups passed.')})().catch(e=>{console.error(e);process.exitCode=1});
