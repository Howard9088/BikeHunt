'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const gallery=fs.readFileSync('web/gallery.js','utf8'),flows=fs.readFileSync('web/flows.js','utf8');
function section(source,start,end){return source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)))}
function harness(saved=null){
 const storage=new Map(saved?[['bikehuntMessagesReadCursor',saved]]:[]),badge={setAttribute(k,v){this[k]=v}},refs=new Map(),links=[];
 const c=vm.createContext({Date,URL,Number,Map,Set,JSON,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},document:{getElementById:()=>badge,querySelectorAll:()=>links},referenceOffers:refs,window:{confirm:()=>true},guideContext:null,PURCHASE_DISCLAIMER:'disclaimer',timeText:x=>x,money:(v,c)=>c+v,cny:v=>'CNY'+v});
 vm.runInContext(section(gallery,'const e=value','function money('),c);
 vm.runInContext(section(gallery,'function inventoryVerified(','function offerMarkup('),c);
 vm.runInContext(section(flows,'const messageEvents=','const directoryPage='),c);
 vm.runInContext(section(flows,'function eventProduct(','async function showWechat('),c);
 vm.runInContext(section(flows,'function invalidateReferenceLinks(',"document.addEventListener('click',guardPurchaseExit)"),c);
 return {c,refs,links,badge,storage};
}
function row(id=1,overrides={}){
 const url='https://shop.example/products/26-173-bah?variant='+id;
 return {id,event_key:'event-'+id,source_code:'bahrain',source_name:'Bahrain',kind:'price_changed',category:'jerseys',offer_id:'o'+id,name_zh:'Short Sleeve Jersey Man Bahrain Victorious',old_price:'148',new_price:'149',currency:'USD',stock:'in_stock',observed_at:'2026-10-14T12:00:00Z',url,product:{offer_id:'o'+id,url,name:'Generic jersey',brand:'Ale',model:'Jersey',color:'red',size:id===1?'M':'L',image:'https://shop.example/red.jpg',product_id:'family-a',variant_id:'v'+id,current_stock:'in_stock'},...overrides};
}
function click(link,type='click',button=0){return {type,button,target:{closest:()=>link},prevented:false,preventDefault(){this.prevented=true}}}
function testGroupingAndExactPictures(){
 const h=harness(),a=row(),b=row(2),different=row(3);different.url=different.product.url='https://shop.example/products/26-175-bah?variant=3';different.product.product_id='family-b';different.product.image='https://shop.example/white.jpg';different.old_price='107';different.new_price='108';
 const groups=h.c.groupMessages([a,b,different]);assert.equal(groups.length,2);assert.equal(groups[0].members.length,2);
 const html=h.c.messageCardMarkup(groups[0],{rates:{USD:7}});assert.ok(html.includes('red.jpg'));assert.ok(html.includes('M / L'));assert.ok(html.includes('variant=1'));assert.ok(html.includes('variant=2'));
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
 const markup=h.c.referenceLinkMarkup(q);assert.ok(markup.includes('去官网查看'));const key='o|'+q.offer.url;
 const link={dataset:{referenceLink:key},href:q.offer.url,getAttribute(){return this.href},removeAttribute(){this.href=null},setAttribute(){}};h.links.push(link);
 h.c.window.confirm=()=>false;let e=click(link);h.c.guardPurchaseExit(e);assert.equal(e.prevented,true);
 h.c.window.confirm=()=>true;for(const [type,button] of [['click',0],['auxclick',1]]){e=click(link,type,button);h.c.guardPurchaseExit(e);assert.equal(e.prevented,false,'Timestamp alone does not block reference navigation')}
 h.c.window.confirm=()=>{throw Error('No prompt for invalid URL')};link.href='javascript:alert(1)';e=click(link);h.c.guardPurchaseExit(e);assert.equal(e.prevented,true);link.href=q.offer.url;
 h.c.getJson=async()=>({offers:[{offer:{...q.offer,stock:'out_of_stock'}}]});await h.c.refreshReferenceLinks();assert.equal(q.offer.stock,'out_of_stock');assert.equal(link.href,null);e=click(link);h.c.guardPurchaseExit(e);assert.equal(e.prevented,true);
 assert.equal(h.c.referenceLinkMarkup(q),'');
 const sold=row(9);sold.product.current_stock='out_of_stock';const html=h.c.messageCardMarkup(sold,{});assert.ok(!html.includes('href='));assert.ok(html.includes('已售罄'));
}
function testXssAndUrlGuards(){
 const h=harness(),evil=row();evil.name_zh='<img src=x onerror=alert(1)>';evil.product.model='\"><script>bad()</script>';evil.product.image='javascript:alert(1)';evil.url=evil.product.url='javascript:alert(1)';const html=h.c.messageCardMarkup(evil,{});assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img'));assert.ok(!html.includes('href='));assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('已售罄'));
 assert.equal(h.c.merchantUrl('https://user:password@shop.example/p'),'');assert.equal(h.c.merchantUrl('data:text/html,test'),'');assert.equal(h.c.merchantUrl('http://shop.example/p'),'');
}
function testCategoryScopeAndExplicitGlobalReset(){
 const h=harness(),categoryButtons=['all','jerseys','bibs'].map(category=>({dataset:{category},setAttribute(){}})),productButton={dataset:{tab:'products'}};
 Object.assign(h.c,{activeSource:'bahrain',activeCategory:'all',directoryData:{brands:[],teams:[{code:'bahrain',name_zh:'巴林车队'}]},navigate:()=>{},profileMatches:()=>true,items:[{source_codes:['bahrain'],category:'jerseys',stock_state:'unknown',brand:'Ale',name:'Jersey'},{source_codes:['other'],category:'jerseys',stock_state:'in_stock',brand:'Other',name:'Jersey'}]});
 h.c.document.querySelectorAll=selector=>selector==='[data-category]'?categoryButtons:[productButton];h.badge.value='';
 vm.runInContext(section(flows,'function chooseCategory(','function renderDirectory('),h.c);
 vm.runInContext(section(gallery,'function visibleItems(','function render('),h.c);
 h.c.chooseCategory('jerseys');assert.equal(h.c.activeSource,'bahrain');assert.equal(h.badge.textContent,'巴林车队');assert.equal(h.c.visibleItems().length,1);
 h.c.chooseCategory('all');assert.equal(h.c.activeSource,'bahrain');
 vm.runInContext(section(flows,"document.querySelectorAll('[data-tab]').forEach(b=>b.onclick",'const panelError='),h.c);productButton.onclick();assert.equal(h.c.activeSource,null);assert.equal(h.badge.textContent,'精选好价');assert.equal(h.c.visibleItems().length,2);
}
async function testDismissedMessagesDoNotReopenOrReadUnseenRows(){
 const h=harness();let resolve;Object.assign(h.c,{messagesOpen:false,detailSequence:0,sheet:{classList:{contains:()=>true}},openPanel(){h.c.detailSequence++},getJson:()=>new Promise(done=>{resolve=done})});
 const pending=h.c.showMessages();h.c.messagesOpen=false;h.c.detailSequence++;resolve({items:[row()],cursor:1,fx:{}});await pending;assert.equal(h.badge.hidden,false);assert.equal(h.badge.textContent,'1');assert.equal(h.storage.has('bikehuntMessagesReadCursor'),false);
}
(async()=>{for(const t of [testGroupingAndExactPictures,testReadIdsReloadIncrementFilteredAndCap,testReferenceExitCancelContinueSoldoutAndLatestRecheck,testXssAndUrlGuards,testCategoryScopeAndExplicitGlobalReset,testDismissedMessagesDoNotReopenOrReadUnseenRows]){await t();console.log('PASS '+t.name)}console.log('Catalog messages: 6 production-JavaScript regression groups passed.')})().catch(e=>{console.error(e);process.exitCode=1});
