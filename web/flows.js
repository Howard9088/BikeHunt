'use strict';
let directoryData={brands:[],teams:[]},categories=[],categoryGroups=[],roadReferenceData={brands:[],products:[]},guideContext=null,guideStep=0,messagesOpen=false;
const messageEvents=new Map();
const MESSAGE_READ_KEY='bikehuntMessagesReadCursor';
const messageSeenKeys=new Set(),messageLegacySeenIds=new Set();
let messageLegacyCursor=0,messageReadMigrated=true;
function validMessageKey(value){return typeof value==='string'&&/^[0-9a-f]{64}$/.test(value)?value:null}
try{
  const saved=JSON.parse(localStorage.getItem(MESSAGE_READ_KEY)||'null');
  if(saved?.version===2){if(Array.isArray(saved.seenKeys))for(const key of saved.seenKeys)if(validMessageKey(key))messageSeenKeys.add(key)}
  else if(saved&&Array.isArray(saved.seen)){for(const id of saved.seen)if(Number.isSafeInteger(id)&&id>0)messageLegacySeenIds.add(id);messageReadMigrated=false}
  else if(Number.isSafeInteger(saved)&&saved>=0){messageLegacyCursor=saved;messageReadMigrated=false}
}catch{}
const directoryPage=document.getElementById('directoryPage');
function directoryLogo(item){
  const url=(item.logo_images||[]).find(value=>typeof value==='string'&&/^\/(?:[A-Za-z0-9_-]+\/)*web\/assets\/[A-Za-z0-9_./-]+\.(?:svg|png|webp|jpe?g)$/.test(value)&&!value.includes('..'));
  return '<span class="team-logo directory-logo '+(item.logo_theme==='dark'?'team-logo-monochrome':item.logo_theme==='outline'?'team-logo-outline':'')+'">'+(url?'<img data-directory-logo src="'+e(url)+'" alt="'+e(item.name)+' 标志" decoding="async" hidden>':'')+'<span class="directory-mark">'+e(item.name||item.name_zh||'来源名称待确认')+'</span></span>';
}
function syncDirectoryLogo(img){const ready=img.complete&&img.naturalWidth>0;img.hidden=!ready;if(img.nextElementSibling)img.nextElementSibling.hidden=ready}
function bindDirectoryLogos(root){root.querySelectorAll('img[data-directory-logo]').forEach(syncDirectoryLogo)}
for(const type of ['load','error'])document.addEventListener(type,event=>{if(event.target.matches?.('img[data-directory-logo]'))syncDirectoryLogo(event.target)},true);
function openPanel(title,content,preserveGuide=false){if(typeof roadDetailContext!=='undefined')roadDetailContext=null;if(!preserveGuide){guideContext=null;if(typeof cancelPurchaseContext==='function')cancelPurchaseContext();}messagesOpen=false;++detailSequence;if(!sheet.classList.contains('open'))lastFocus=document.activeElement;gallery.inert=true;directoryPage.inert=true;sheet.inert=false;document.getElementById('sheetName').textContent=title;document.getElementById('sheetBrand').textContent='BikeHunt 中文海淘助手';document.getElementById('sheetImg').src='';document.getElementById('sheetImg').style.display='none';document.getElementById('sheetBody').innerHTML=content;document.getElementById('sheetBody').scrollTop=0;document.getElementById('overlay').classList.add('open');sheet.classList.add('open');sheet.setAttribute('aria-hidden','false');document.getElementById('close').focus()}
async function postJson(url,data={}){const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const body=await response.json();if(!response.ok)throw new Error(body.detail||'请求失败');return body}
function saveBrowseState(){
  activeCategory='all'; // Retire hidden leaf filters from older browser history.
  if(!publicCategoryGroupVisible(activeCategoryGroup))activeCategoryGroup=null;
  if(!publicSourceVisible(activeSource,publicDirectoryData(directoryData,roadReferenceData)))activeSource=null;
  try{const state=history.state&&typeof history.state==='object'?history.state:{};history.replaceState({...state,bikehuntBrowse:{tab:activeTab,source:activeSource,category:activeCategory,categoryGroup:activeCategoryGroup,query:browseQuery(document.getElementById('q').value)}},'')}catch{}
}
function restoreBrowseState(){
  let saved;try{saved=history.state?.bikehuntBrowse}catch{return}
  if(!saved||typeof saved!=='object')return;
  document.getElementById('q').value=browseQuery(saved.query);
  categoryGroups=categoryGroups.filter(c=>publicCategoryGroupVisible(c.code));
  directoryData=publicDirectoryData(directoryData,roadReferenceData);
  activeCategoryGroup=categoryGroups.some(c=>c.code===saved.categoryGroup)?saved.categoryGroup:null;
  activeCategory='all';
  activeSource=[...directoryData.brands,...directoryData.teams].some(entry=>entry.code===saved.source)?saved.source:null;
  document.querySelectorAll('[data-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.category===activeCategory)));
  syncBrowseControls();updateBrowseLabel();navigate(['products','brands','teams'].includes(saved.tab)?saved.tab:'products');
}
function browseQuery(value){return typeof value==='string'&&value.length<=200?value:''}
function navigate(tab){activeTab=tab;saveBrowseState();document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-current',b.dataset.tab===tab?'page':'false'));gallery.hidden=tab!=='products';directoryPage.hidden=tab==='products';document.querySelector('.scroll-controls').hidden=tab!=='products';document.getElementById('scrollHint').classList.toggle('hidden',tab!=='products');document.getElementById('categoryGroupNav').hidden=tab!=='products';syncBrowseControls();document.body.classList.toggle('directory-mode',tab!=='products');if(tab==='products'){render()}else{renderDirectory(tab)}if(typeof syncChannelInfo==='function')syncChannelInfo()}
function chooseCategory(code){activeCategory='all';syncBrowseControls();updateBrowseLabel();navigate('products')}
function chooseCategoryGroup(code){if(!publicCategoryGroupVisible(code))code=null;activeCategoryGroup=activeCategoryGroup===code?null:categoryGroups.some(c=>c.code===code)?code:null;activeCategory='all';syncBrowseControls();updateBrowseLabel();navigate('products')}
function syncBrowseControls(){
  activeCategory='all';
  if(!publicCategoryGroupVisible(activeCategoryGroup))activeCategoryGroup=null;
  if(typeof syncGenderScope==='function')syncGenderScope();
  document.querySelectorAll('[data-category-group]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.categoryGroup===activeCategoryGroup)));
  const visible=activeTab==='products'&&publicCategoryGroupVisible(activeCategoryGroup)&&['road_equipment','other'].includes(activeCategoryGroup)&&(!activeSource||roadReferenceData.brands.some(b=>b.code===activeSource));
  const strip=document.getElementById('roadReferenceStrip');if(strip)strip.hidden=!visible;
  document.body.classList.toggle('road-reference-visible',visible);
}
function updateBrowseLabel(){const entry=[...directoryData.brands,...directoryData.teams].find(x=>x.code===activeSource);const label=activeSource?(entry?.name_zh||entry?.name||activeSource):document.getElementById('q').value.trim()?'搜索结果':'精选好价';const group=categoryGroups.find(c=>c.code===activeCategoryGroup);document.getElementById('browseLabel').textContent=label+(group?' · '+group.name:'')}
function channelProductCount(code){return items.filter(p=>channelCard(p,code)).length}
function renderDirectory(section){
  directoryData=publicDirectoryData(directoryData,roadReferenceData);
  const entries=directoryData[section]||[];document.getElementById('browseLabel').textContent=section==='brands'?'品牌官网':'世巡车队';document.getElementById('count').textContent=entries.length+' 个入口';
  const ranking=section==='teams'?directoryData.team_ranking:null;
  directoryPage.innerHTML='<div class="directory-intro"><h2>'+(section==='brands'?'从品牌发现装备':'世巡车队装备，一处查看')+'</h2><p>'+(ranking?e(ranking.season)+' 年 '+e(ranking.title_zh)+' · '+e(ranking.ranking_date)+'<br>':'')+'查看各渠道的现货商品，购买说明可展开查看。</p></div><div class="directory-grid">'+entries.map(item=>'<button class="directory-card" data-source="'+e(item.code)+'">'+(item.world_rank?'<span class="team-rank">UCI 第 '+e(item.world_rank)+' 名</span>':'')+directoryLogo(item)+'<strong>'+e(item.name_zh)+'</strong><span>'+e(item.name)+'</span><div class="directory-count">'+channelProductCount(item.code)+' 款现货'+(item.catalog_note?' · '+e(item.catalog_note):'')+'</div><div class="directory-link">查看现货商品 →</div></button>').join('')+'</div>';
  bindDirectoryLogos(directoryPage);
  directoryPage.querySelectorAll('[data-source]').forEach(b=>b.onclick=()=>openSource(b.dataset.source));
}
function ruleMarkup(book){
  if(!book.documents.length)return '<div class="summary-box"><h4>购买条件暂未确认</h4><p>请在商店结账前确认配送范围、付款方式和税费。</p></div>';
  return '<div class="rule-meta">购买条件更新 '+e(timeText(book.checked_at))+'</div>'+book.documents.map(doc=>'<section class="rule-section"><h4>'+e(doc.title_zh)+'</h4>'+(doc.state==='translated'?'<ul>'+doc.summary_zh.map(t=>'<li>'+e(t)+'</li>').join('')+'</ul>':'<p class="offer-note">'+(doc.state==='changed'?'官方原文已有变化，最新中文规则正在复核。':'请查看商店最新配送、付款与退换货说明。')+'</p>')+'<details><summary>核对来源</summary><a class="source-original" target="_blank" rel="noopener noreferrer" href="'+e(safeUrl(doc.url))+'">查看官方原文（核对用） ↗</a></details></section>').join('');
}
function domesticChannelInfo(entry){
  return entry?.code==='decathlon_cn'&&Array.isArray(entry.source_codes)&&entry.source_codes.length===1&&entry.source_codes[0]==='decathlon_cn'&&entry.official_url==='https://www.decathlon.com.cn/'&&entry.shop_url==='https://www.decathlon.com.cn/';
}
function channelInfoMarkup(entry,book){
  return '<div class="source-overview">'+(entry.logo_images?.length?directoryLogo(entry):'')+'<strong>'+e(entry.name_zh)+'</strong></div>'+
    (entry.reference_note?'<p class="road-warning">'+e(entry.reference_note)+'</p>':'')+(typeof paymentDirectoryMarkup==='function'?paymentDirectoryMarkup(entry):'')+(domesticChannelInfo(entry)&&typeof domesticPaymentMarkup==='function'?domesticPaymentMarkup():book.documents.length?ruleMarkup(book):'<div data-directory-empty-rules>'+ruleMarkup(book)+'</div>')+'<section data-directory-readiness aria-label="渠道配送与退货说明">'+(typeof readinessDirectoryMarkup==='function'?readinessDirectoryMarkup(entry):'')+'</section>'+
    (entry.official_url?'<details class="official-entrances"><summary>官网与官方商城入口</summary><p><a target="_blank" rel="noopener noreferrer" href="'+e(safeUrl(entry.official_url))+'">品牌或车队官网 ↗</a></p>'+
      (entry.shop_url?'<p><a target="_blank" rel="noopener noreferrer" href="'+e(safeUrl(entry.shop_url))+'">官方公布的商城入口 ↗</a></p>':'')+
      '<p>购买前请核对商品规格、配送地区和最终结账金额。</p></details>':'');
}
function syncChannelInfo(){
  const panel=document.getElementById('channelInfo');if(!panel)return;
  const entry=[...directoryData.brands,...directoryData.teams].find(x=>x.code===activeSource);
  panel.hidden=activeTab!=='products'||!entry;
  if(panel.dataset.source===activeSource)return;
  panel.open=false;panel.dataset.source=activeSource||'';
  const body=panel.querySelector('.channel-info-body');body.innerHTML='';delete panel.dataset.loaded;
  panel.ontoggle=async()=>{
    if(!panel.open||panel.dataset.loaded||!entry)return;
    const code=entry.code;panel.dataset.loaded='loading';body.innerHTML='<p>正在加载购买说明…</p>';
    try{const book=await getJson('/api/rules/'+encodeURIComponent(code));
      if(activeSource!==code||panel.dataset.source!==code)return;
      body.innerHTML=channelInfoMarkup(entry,book);panel.dataset.loaded='yes';bindDirectoryLogos(body);if(typeof refreshDirectoryReadiness==='function')refreshDirectoryReadiness();
    }catch{if(activeSource!==code)return;delete panel.dataset.loaded;body.innerHTML='<p>购买说明暂时无法加载，请稍后重新展开。</p>'}
  };
}
function openSource(code){
  directoryData=publicDirectoryData(directoryData,roadReferenceData);if(!publicSourceVisible(code,directoryData))return;
  activeSource=code;activeCategory='all';activeCategoryGroup=null;
  const info=document.getElementById('channelInfo');if(info)info.open=false;
  document.getElementById('q').value='';
  if(sheet.classList.contains('open'))closeSheet();
  navigate('products');document.getElementById('grid').focus();
}
async function startGuide(detail,offerId){
  if(!publicProductVisible(detail))return;
  const quote=detail.offers.find(x=>x.offer.offer_id===offerId);if(!quote||!offerAvailable(quote))return;
  const saved=history.state?.bikehuntPurchase;
  guideContext={detail,quote,book:null,route:saved?.productId===detail.product_id&&saved.variantId===detail.variant_id&&saved.offerId===offerId?saved.route:null,reference:false};openPanel(typeof routeDomesticChina==='function'&&routeDomesticChina(quote.offer)?'中国官网购买指引':'中文海淘指引','<p class="loading">读取配送与支付说明…</p>',true);const sequence=detailSequence;
  try{const book=await getJson('/api/rules/'+encodeURIComponent(quote.offer.source_code));if(sequence!==detailSequence)return;if(!offerAvailable(quote)){showInventoryInvalidated(quote);return}guideContext={...guideContext,detail,quote,book};guideStep=0;renderGuide()}catch(error){if(sequence!==detailSequence)return;guideContext=null;document.getElementById('sheetBody').innerHTML='<p>暂时无法加载，请稍后重试。</p>'}
}
function renderGuide(){if(typeof renderRouteComparison==='function')renderRouteComparison()}
function updateGuideVerificationMetadata(verification){
  // Never recreate a dismissed guide or revive a quote whose local safety
  // state already expired. Content/safety changes still use the normal event.
  if(!guideContext||!offerAvailable(guideContext.quote)||!updateVerifiedOfferMetadata(guideContext.quote,verification?.offers))return;
  updateVerifiedDetailMetadata(guideContext.detail,verification);
  const label=document.getElementById('guideObservation');
  if(label)label.textContent=timeText(guideContext.quote.offer.fetched_at);
}
if(window.BIKEHUNT_PAGES)window.addEventListener('bikehunt-verification',event=>updateGuideVerificationMetadata(event.detail));
function browseSettings(){openPanel('浏览设置','<p>默认一次滑动看一件商品。平铺便于同时扫看多件商品。</p><div class="settings-choices"><button data-choice="feed">上下滑动 · 一屏一件</button><button data-choice="grid">平铺图库 · 同时看多件</button></div><p class="service-note">浏览方式会保存在这台设备上。</p>');document.querySelectorAll('[data-choice]').forEach(b=>b.onclick=()=>{setView(b.dataset.choice);closeSheet()})}
function eventProduct(event){const p=event.product;return p&&p.offer_id===event.offer_id&&p.url===event.url?p:null}
function messageGroupKey(event){
  const p=eventProduct(event);if(!p||!p.product_id||!p.model)return 'event:'+event.id;
  const url=merchantUrl(event.url);if(!url)return 'event:'+event.id;
  const productUrl=new URL(url);
  // Only proven catalog families may fold the Shopify size selector. Keep all other URL fields.
  if(p.product_id&&productUrl.pathname.includes('/products/'))productUrl.searchParams.delete('variant');
  const sizeKeys=[...new URL(url).searchParams.keys()];
  if(event.source_code==='colnago'&&p.product_id&&productUrl.hostname==='www.colnago.com'&&productUrl.pathname.startsWith('/en-us/products/')&&sizeKeys.length===1&&['Size','size'].includes(sizeKeys[0])&&productUrl.searchParams.get(sizeKeys[0])===p.size)productUrl.searchParams.delete(sizeKeys[0]);
  return JSON.stringify([event.source_code,p.product_id||null,productUrl.href,p.brand,p.model,p.color||null,p.image||null,p.year||null,p.gender||null,event.currency,event.kind,event.stock,event.observed_at,event.recovered_history===true]);
}
function groupMessages(events){
  const grouped=new Map();for(const event of events){const key=messageGroupKey(event);if(!grouped.has(key))grouped.set(key,{...event,members:[]});grouped.get(key).members.push(event)}return [...grouped.values()];
}
function hasNewPriceMessages(events){return events.some(event=>event.recovered_history!==true)}
function updateMessageBadge(){
  const count=groupMessages([...messageEvents.values()].filter(row=>row.recovered_history!==true&&!messageSeenKeys.has(validMessageKey(row.event_key)))).length,badge=document.getElementById('messageBadge');
  badge.hidden=!count;badge.textContent=count>99?'99+':String(count);badge.setAttribute('aria-label',count+' 条未读价格消息');
}
function persistMessageReadState(){try{localStorage.setItem(MESSAGE_READ_KEY,JSON.stringify({version:2,seenKeys:[...messageSeenKeys]}))}catch{}}
function migrateMessageReadState(events){
  if(messageReadMigrated)return;
  // The old release stored only IDs. Resolve known rows once, then never use IDs as read identities again.
  for(const event of events){const key=validMessageKey(event.event_key);if(key&&(messageLegacySeenIds.has(event.id)||event.id<=messageLegacyCursor))messageSeenKeys.add(key)}
  messageReadMigrated=true;messageLegacySeenIds.clear();messageLegacyCursor=0;persistMessageReadState();
}
function rememberMessageEvents(data){
  if(!data||!Array.isArray(data.items))throw new Error('价格消息数据无效');
  const snapshot=data.items.slice(0,100);
  if(snapshot.some(event=>!event||!validMessageKey(event.event_key)||!Number.isSafeInteger(event.id)||event.id<=0))throw new Error('价格消息标识无效');
  const rows=snapshot.filter(publicProductVisible);
  migrateMessageReadState(rows);
  // /api/updates is the authoritative global latest-100 snapshot, not an append-only stream.
  // Reconcile removals/suppression while keeping the independent read-key history intact.
  messageEvents.clear();
  for(const event of rows){const key=validMessageKey(event.event_key);if(key&&Number.isSafeInteger(event.id)&&event.id>0)messageEvents.set(key,event)}
  updateMessageBadge();
}
function markMessagesRead(events){
  for(const event of events){const key=validMessageKey(event.event_key);if(key){messageSeenKeys.delete(key);messageSeenKeys.add(key)}}
  const keys=[...messageSeenKeys].slice(-1000);messageSeenKeys.clear();keys.forEach(key=>messageSeenKeys.add(key));
  persistMessageReadState();updateMessageBadge();
}
function messageQuote(event){
  const p=eventProduct(event),stock=event.stock==='out_of_stock'||p?.current_stock==='out_of_stock'?'out_of_stock':'unknown';
  return {reference_product_id:p?.product_id,reference_variant_id:p?.variant_id,offer:{offer_id:event.offer_id,url:event.url,stock,source_name:event.source_name}};
}
function messageProductRoute(event){
  const p=eventProduct(event);return p&&typeof p.product_id==='string'&&p.product_id&&typeof p.variant_id==='string'&&p.variant_id?{productId:p.product_id,variantId:p.variant_id}:null;
}
function messageProductAttributes(event){const route=messageProductRoute(event);return route?' data-message-product="'+e(route.productId)+'" data-message-variant="'+e(route.variantId)+'"':''}
function messageProductButton(event,label,className){return '<button type="button" class="'+e(className)+'"'+messageProductAttributes(event)+'>'+label+'</button>'}
function openMessageProduct(productId,variantId){messagesOpen=false;guideContext=null;openProduct(productId,variantId,true)}
function messagePriceRows(event,fx){
  const groups=new Map();
  for(const member of event.members||[event]){
    const key=JSON.stringify({old_price:member.old_price,new_price:member.new_price,currency:member.currency,kind:member.kind});
    if(!groups.has(key))groups.set(key,[]);groups.get(key).push(member);
  }
  return [...groups.values()].map(rows=>{
    const row=rows[0],rate=fx?.rates?.[row.currency],converted=rate?Number(row.new_price)*Number(rate):null;
    const sizes=[...new Set(rows.map(member=>eventProduct(member)?.size).filter(Boolean))];
    const marketUpdate=row.recovered_history!==true&&row.kind==='price_changed'&&row.old_price===null;
    const label=row.recovered_history===true?'历史记录：':marketUpdate?'报价币种/市场更新：':row.kind==='price_changed'?'价格更新：':row.kind==='inventory_changed'?'库存更新：':'新发现报价：';
    return '<p class="message-price">'+(groups.size>1?e((sizes.length?sizes.join(' / '):'规格未记录')+'：'):'')+label+e(row.old_price!=null&&row.kind==='price_changed'?money(row.old_price,row.currency)+' → ':'')+e(money(row.new_price,row.currency))+' · '+e(converted==null?'人民币待换算':cny(converted))+'</p>';
  }).join('');
}
function messageCardMarkup(event,fx){
  const p=eventProduct(event);
  const image=p&&safeUrl(p.image),sold=messageQuote(event).offer.stock==='out_of_stock',route=messageProductRoute(event);
  const photo=image?'<img class="message-image" loading="lazy" src="'+e(image)+'" alt="'+e([p.name,p.model,p.color].filter(Boolean).join(' · '))+'"><span class="message-no-image" hidden>暂无该商品图片</span>':'<span class="message-no-image">暂无该商品图片</span>';
  const thumb=route?messageProductButton(event,photo,'message-thumbnail'):'<div class="message-thumbnail">'+photo+'</div>';
  const members=event.members||[event],sizes=[...new Set(members.map(row=>eventProduct(row)?.size).filter(Boolean))];
  const variantLinks=members.length>1?'<div class="message-variants">'+members.map(row=>{const label=e(eventProduct(row)?.size||'规格待核实');return messageProductRoute(row)?messageProductButton(row,label,'message-variant'):'<span>'+label+'</span>'}).join('')+'</div>':'';
  const title=route?messageProductButton(event,e(event.name_zh),'message-title'):e(event.name_zh);
  const marketUpdate=members.some(row=>row.recovered_history!==true&&row.kind==='price_changed'&&row.old_price===null);
  return '<article class="message-card"'+messageProductAttributes(event)+'><div class="message-layout">'+thumb+'<div class="message-copy"><div class="brand">'+e(event.source_name)+' · '+e(timeText(event.observed_at))+'</div>'+(event.recovered_history===true?'<div class="message-stock-note">恢复的历史记录</div>':'')+'<h4>'+title+'</h4><p class="message-spec">型号：'+e(p?.model||'待核实')+'<br>颜色：'+e(p?.color||'未标注，请核对商品图片')+'<br>尺码：'+e(sizes.length?sizes.join(' / '):'未记录')+'</p>'+messagePriceRows(event,fx)+(marketUpdate?'<p class="message-stock-note">商家响应的报价币种/市场发生变化，并非你切换了市场；不同币种报价不直接比较涨跌。</p>':'')+(sold?'<span class="tag no">所示报价已售罄，无购买链接</span>':'')+(route?messageProductButton(event,'查看本站商品详情 →','message-product-link'):'<span class="tag wait">该商品详情暂不可用</span>')+variantLinks+'<p class="message-stock-note">'+(sold?'该规格已售罄，可查看本站记录。':'历史变动记录；点击查看本站商品详情与渠道报价。')+'</p></div></div></article>';
}
async function refreshMessageState(){const data=await getJson('/api/updates');rememberMessageEvents(data);return data}
async function showMessages(){
  openPanel('最新价格消息','<p class="loading">正在读取价格更新…</p>');messagesOpen=true;const sequence=detailSequence;
  const data=await refreshMessageState();if(sequence!==detailSequence||!messagesOpen||!sheet.classList.contains('open'))return;
  const rows=[...messageEvents.values()].sort((a,b)=>b.id-a.id);
  document.getElementById('sheetBody').innerHTML=rows.length?groupMessages(rows).map(event=>messageCardMarkup(event,data.fx)).join(''):'<div class="summary-box"><h4>暂时没有新的价格变动</h4><p>有新的报价或价格变化时，会显示在这里。</p></div>';
  document.getElementById('sheetBody').querySelectorAll('.message-image').forEach(img=>img.onerror=()=>{img.hidden=true;img.nextElementSibling.hidden=false});
  document.getElementById('sheetBody').querySelectorAll('.message-card[data-message-product]').forEach(card=>card.onclick=event=>{const target=event.target.closest('[data-message-product]');if(target)openMessageProduct(target.dataset.messageProduct,target.dataset.messageVariant)});
  markMessagesRead(rows);
}
async function refreshCatalogSilently(invalidateGuide=true){if(catalogLoadState!=='ready')return init();try{if(invalidateGuide&&guideContext){guideContext=null;closeSheet();}const active=gallery.querySelectorAll('.card')[currentIndex]?.dataset.id;const data=publicCatalogData(await getJson('/api/catalog'));items=data.items;if(currentProduct&&!publicProductVisible(currentProduct))closeSheet();fx=data.fx;roadReferenceData=data.road_equipment_references||{brands:[],products:[]};if(document.getElementById('roadReferencePanel')&&sheet.classList.contains('open'))document.getElementById('sheetBody').innerHTML=roadReferenceMarkup();updateFxLabel();sourceCount=data.source_count;if(activeTab==='products')render(active);refreshRoadReferenceDetail()}catch{}}
async function bootFlows(){
  const data=publicCatalogData(await getJson('/api/catalog'));categories=data.categories||[];categoryGroups=data.category_groups||[];roadReferenceData=data.road_equipment_references||{brands:[],products:[]};
  document.getElementById('categoryGroupNav').innerHTML=categoryGroups.map(c=>'<button type="button" data-category-group="'+e(c.code)+'" aria-pressed="false" title="再次点击可取消这个分组">'+e(c.name)+'</button>').join('');
  document.querySelectorAll('[data-category-group]').forEach(b=>b.onclick=()=>chooseCategoryGroup(b.dataset.categoryGroup));
  document.getElementById('roadReferencesButton').onclick=()=>openRoadReferences();
  directoryData=publicDirectoryData(await getJson('/api/directories'),roadReferenceData);
  restoreBrowseState();
  if(typeof restorePurchaseState==='function')restorePurchaseState().catch(()=>{});
  refreshMessageState().catch(()=>{});
    if(activeTab!=='products')renderDirectory(activeTab);
  const onPrices=(events,freshnessChanged=false)=>{const wasMessages=messagesOpen;if(typeof invalidatePurchaseFlow==='function')invalidatePurchaseFlow(events);invalidateReferenceLinks(events);refreshReferenceLinks().catch(()=>{});if(hasNewPriceMessages(events)){document.getElementById('updateToast').hidden=false;setTimeout(()=>document.getElementById('updateToast').hidden=true,5000)}if(wasMessages)showMessages().catch(panelError);else refreshMessageState().catch(()=>{});refreshCatalogSilently(false);if(currentProduct&&(document.getElementById('variant')||document.getElementById('bundleChoices'))&&(freshnessChanged||events.some(x=>currentProduct.offers.some(q=>q.offer.offer_id===x.offer_id))||document.getElementById('bundleChoices'))){refreshOpenProductDetail(events)}};
  if(window.BIKEHUNT_PAGES){window.addEventListener('bikehunt-published',event=>onPrices(event.detail.events,event.detail.freshnessChanged));return}
  const eventSource=new EventSource('/api/updates/stream');eventSource.addEventListener('prices',event=>onPrices(JSON.parse(event.data)));window.addEventListener('pagehide',()=>{eventSource.close()},{once:true});
}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{if(b.dataset.tab==='products'){activeSource=null;activeCategoryGroup=null;activeCategory='all';document.getElementById('q').value='';syncBrowseControls();updateBrowseLabel()}navigate(b.dataset.tab)});
const panelError=error=>{document.getElementById('sheetBody').innerHTML='<p class="offer-note">暂时无法加载，请稍后重试。</p>'};
async function showCommunity(){saveBrowseState();window.location.assign(new URL(window.BIKEHUNT_PAGES?'./group/':'/web/group/',window.location.href).href)}
document.getElementById('wechatCommunity').onclick=()=>showCommunity().catch(panelError);
document.getElementById('browseSettings').onclick=browseSettings;document.getElementById('priceMessages').onclick=()=>showMessages().catch(panelError);document.getElementById('updateToast').onclick=()=>{document.getElementById('updateToast').hidden=true;showMessages().catch(panelError)};
document.getElementById('refreshPrices').onclick=async()=>{const button=document.getElementById('refreshPrices');button.disabled=true;button.textContent='核对中…';const finish=()=>{button.disabled=false;button.textContent=window.BIKEHUNT_PAGES?'刷新价格':'核对最新价格'};try{await postJson('/api/refresh/prices');const poll=async()=>{try{const state=await getJson('/api/refresh/status');if(state.state==='running'){setTimeout(poll,3000);return}finish();await refreshCatalogSilently();if(state.state==='failed'||state.state==='partial'){openPanel('价格核对结果','<p>部分渠道未能取得新报价，已保留上一份有效数据。请查看各商品的更新时间。</p>')}}catch(error){finish();openPanel('价格核对失败','<p>暂时无法加载，请稍后重试。</p>')}};setTimeout(poll,3000)}catch(error){finish();openPanel('价格核对失败','<p>暂时无法加载，请稍后重试。</p>')}};
document.getElementById('close').addEventListener('click',()=>{document.getElementById('sheetImg').style.display=''});
document.body.addEventListener('touchend',event=>{if(event.touches.length>0)return;const touch=event.changedTouches[0];if(!touch)return;const now=performance.now();const previous=document.body._lastTap;if(previous&&now-previous.time<330&&Math.abs(touch.clientX-previous.x)<25&&Math.abs(touch.clientY-previous.y)<25){if(event.cancelable)event.preventDefault()}document.body._lastTap={time:now,x:touch.clientX,y:touch.clientY}},{passive:false});
let flowsStarted=false,flowsStartPromise=null,flowsRecoveryListener=null;
function startFlows(){
  if(flowsStarted)return Promise.resolve();
  if(flowsStartPromise)return flowsStartPromise;
  flowsStartPromise=bootFlows().then(()=>{
    flowsStarted=true;
    if(flowsRecoveryListener){window.removeEventListener('bikehunt-published',flowsRecoveryListener);flowsRecoveryListener=null}
  }).catch(()=>{
    // One recovery listener, shared by automatic publication and manual retry.
    if(window.BIKEHUNT_PAGES&&!flowsRecoveryListener){
      flowsRecoveryListener=()=>{window.removeEventListener('bikehunt-published',flowsRecoveryListener);flowsRecoveryListener=null;init();startFlows()};
      window.addEventListener('bikehunt-published',flowsRecoveryListener,{once:true});
    }
  }).finally(()=>{flowsStartPromise=null});
  return flowsStartPromise;
}

startFlows();

const PURCHASE_DISCLAIMER="本站仅提供商品与优惠信息，不参与交易。价格、库存、尺码及折扣可能变化，信息不保证完全准确，请以实际商家页面及结算信息为准，并在购买前自行核实。购买、付款、配送、退换货，以及买错商品或尺码不合适等问题，请直接联系实际商家。法律规定本站应承担的责任除外。";
document.getElementById('purchaseDisclaimerInfo').onclick=()=>window.alert(PURCHASE_DISCLAIMER);
// Fixed official search entrances only. These are not offers or verified sellers.
const AMAZON_SEARCH_MARKETS=Object.freeze([
  ['amazon_us','美国站','www.amazon.com','road cycling jersey','road cycling bib shorts'],
  ['amazon_uk','英国站','www.amazon.co.uk','road cycling jersey','road cycling bib shorts'],
  ['amazon_de','德国站','www.amazon.de','Rennrad Trikot','Rennrad Trägerhose'],
  ['amazon_jp','日本站','www.amazon.co.jp','ロードバイク サイクルジャージ','ロードバイク ビブショーツ']
].map(([code,name,host,jerseys,bibs])=>Object.freeze({code,name,host,salesRegion:name,searches:Object.freeze([
  ['jerseys','骑行上衣',jerseys],['bibs','背带裤',bibs]
].map(([category,label,query])=>Object.freeze({key:code+'_'+category,label,query,url:'https://'+host+'/s?'+new URLSearchParams({k:query}).toString()})))})));
// Unmodified official artwork, used only to identify the destination retailer.
// Resolve against this script so both /web/ and project-subdirectory Pages work.
const AMAZON_CHANNEL_LOGO_URL=new URL('assets/brands/amazon-official.png',document.currentScript.src).href;
function syncAmazonChannelLogo(img){
  const loaded=img.complete&&img.naturalWidth>0;
  img.hidden=!loaded;img.nextElementSibling.hidden=loaded;
}
function bindAmazonChannelLogos(){
  document.getElementById('sheetBody').querySelectorAll('.amazon-channel-logo').forEach(img=>{
    img.onload=()=>syncAmazonChannelLogo(img);img.onerror=()=>syncAmazonChannelLogo(img);
    syncAmazonChannelLogo(img);
  });
}
// Educational checklist only: never creates an offer, asks for personal data,
// signs in or contacts Amazon. Official references were read on 2026-10-15.
const AMAZON_IMPORT_STEPS=Object.freeze([
  ['market','选站点，认清币种',[
    '从上方选择美国、英国、德国或日本站，再搜索骑行上衣或背带裤。美国站常见 USD 美元、英国站 GBP 英镑、德国站 EUR 欧元、日本站 JPY 日元；最终扣款币种以结账页为准。',
    '切换站点后，重新核对商品、销售方、配送与费用。站点所在地不等于实际发货地，也不代表能直邮中国。'
  ]],
  ['address','先把配送目的地设为中国',[
    '在 Amazon 原站找到 Deliver to / Ship to（配送至），选择 China（中国）。需要登录时，在确认域名无误的 Amazon 页面自行登录。',
    '按原站表单填写真实收件人、完整中国大陆地址、邮编和联系电话；核对国家与城市没有被默认成站点所在地。本教程不收集地址、账号或付款信息。'
  ]],
  ['size','核对型号、男女款和尺码表',[
    '打开具体商品，核对品牌、型号、年份或版本、男女款、颜色、尺码和数量；切换规格后再看价格与卖家。图片相似不代表同一款。',
    '打开该商品的 Size chart（尺码表），用胸围、腰围、臀围等实测数据对照，并确认 cm / inch 单位。不同品牌、男女款和站点的 S / M / L 不能直接等同；不确定时先询问实际卖家。'
  ]],
  ['seller','分清销售方与配送方',[
    '在具体商品页找 Sold by（销售方）与 Ships from / Dispatches from（发货或配送方）；德国站常见 Verkauf durch / Versand，日文常见 販売元 / 出荷元。界面文案可能不同。',
    'Amazon 自营与第三方卖家都可能出现在搜索结果中。点开销售方资料，核对卖家身份、评价及退货条件；品牌旗舰店页面也不能代替销售方核对。',
    'Fulfilled by Amazon（FBA / Amazon 配送）只说明配送履约方式，不等于 Amazon 自营；第三方卖家也可使用 Amazon 配送。售后入口须按本单销售方和履约方式确认。'
  ]],
  ['delivery','确认这一件能寄到你的地址',[
    '选定具体款式、颜色、尺码与销售方后，查看能否配送到你填写的中国大陆地址，以及配送方式、预计送达日期和运费；加入购物车后到结账页再核对一次。',
    '出现无法配送、地址不支持或没有可用配送方式时，先停止该商品下单，可返回比较其他站点或卖家。能搜索到、能加入购物车、Prime 或 FBA 标识，都不保证这件商品能直邮中国。'
  ]],
  ['fees','看清运费、进口税费和币种',[
    '在提交订单前展开费用明细，逐项看商品小计、Shipping（运费）、税费、Import Fees Deposit（进口费用预估押金）或 Import Charges（进口费用），以及 Order total（订单合计）。',
    '预估押金与固定进口费用的规则可能不同，按该站本单说明核对退款、补缴及清关责任。没有列出进口费用，不代表免税或全部税费已预付；不清楚就先向 Amazon 或实际卖家确认。',
    '核对最终扣款币种与汇率；若可选人民币转换或原币付款，对照页面给出的转换费用及发卡行可能收取的费用。本站人民币参考价不是 Amazon 最终到手价。'
  ]],
  ['payment','付款前，最后检查一次',[
    '在最终确认页复核：型号与男女款、颜色尺码、数量、销售方与配送方、中国地址、预计送达日期、运费税费、总额与扣款币种。也要看清退货期限、退货地址、跨境退货运费由谁承担。',
    '确认全部条件后，再由你自行决定是否点击 Place your order（提交订单）等最终按钮。不要仅凭搜索价、免费配送字样或本教程下单；只通过 Amazon 正规结账流程付款。',
    '保留订单确认与费用明细。付款结果不明确时，先查订单和银行扣款记录，避免重复提交。'
  ]],
  ['aftercare','到订单页查物流、办退换货',[
    '下单后在购买的同一站点进入 Your Orders（我的订单），打开该订单查看承运商、追踪号码和物流更新；遇到清关要求，先从订单或承运商官方渠道核实。',
    '到货后及时核对商品和尺码。需要退换货时，从该订单的退货或客服入口联系实际卖家或负责履约的 Amazon 客服，按本单批准的地址、标签和流程办理，保留照片与寄件凭证。',
    '跨境退货期限、运费承担、可否换码及税费退款并不统一，下单前后都应核对本单规则。购买、配送与售后由实际商家处理。'
  ]]
].map(([id,title,paragraphs])=>Object.freeze({id,title,paragraphs:Object.freeze(paragraphs)})));
// UK help is verified as a terminology example, not a policy for US/DE/JP or China.
const AMAZON_IMPORT_HELP=Object.freeze([
  ['seller','英国站：销售方与配送方','https://digprjsurvey.amazon.co.uk/csad/help/node/GEF528GN65XSJ7V8'],
  ['charges','英国站：Import Charges 说明','https://digprjsurvey.amazon.co.uk/csad/help/node/G8VRJ7Y8Z3T5WPV3'],
  ['deposit','英国 Global Store：预估押金与费用条款','https://digprjsurvey.amazon.co.uk/csad/help/node/G9UHGT37MYD2EJPL'],
  ['tracking','英国站：从订单查承运商与追踪号码','https://digprjsurvey.amazon.co.uk/csad/help/node/GBPEXEXYULHB5WCH']
].map(([key,label,url])=>Object.freeze({key,label,url})));
function amazonImportGuideMarkup(){
  return '<section class="amazon-import-guide" aria-labelledby="amazonImportTitle"><h4 id="amazonImportTitle">第一次 Amazon 海淘，照这 8 步核对</h4><p class="amazon-guide-intro">点击步骤展开。这是操作核对清单，不是代购服务；是否直邮中国与实际费用，须按具体商品、销售方、收货地址及结账页确认。</p><ol class="amazon-guide-steps">'+AMAZON_IMPORT_STEPS.map((step,index)=>'<li><details class="amazon-guide-step" name="amazon-import-steps" data-amazon-step="'+e(step.id)+'"'+(index===0?' open':'')+'><summary><span class="amazon-step-number" aria-hidden="true">'+(index+1)+'</span><span>'+e(step.title)+'</span></summary><div class="amazon-step-body">'+step.paragraphs.map(paragraph=>'<p>'+e(paragraph)+'</p>').join('')+'</div></details></li>').join('')+'</ol><details class="amazon-help-sources"><summary>官方帮助与适用范围</summary><p>核对日期：2026-10-15。以下为已核对的英国站官方说明，其中 Global Store 条款仅作费用术语示例，不代表美国、德国、日本站或寄往中国的统一政策。美国、德国、日本站具体帮助本次未能完成核验，请在所选站点查看本单最新说明。</p><ul>'+AMAZON_IMPORT_HELP.map(source=>'<li><a data-amazon-help-link="'+e(source.key)+'" href="'+e(source.url)+'" target="_self" rel="noopener noreferrer">'+e(source.label)+' →</a></li>').join('')+'</ul></details></section>';
}
function showAmazonChannels(){
  openPanel('Amazon购买途径','<div class="summary-box amazon-summary"><h4>搜索入口，非商品实时报价</h4><p>以下链接打开 Amazon 官方站点的公路骑行服搜索。本页未接入 Amazon 商品数据，未核实搜索结果中的卖家、价格或库存。</p></div><div class="amazon-market-grid">'+AMAZON_SEARCH_MARKETS.map(market=>'<section class="amazon-market"><h4 class="amazon-market-title"><span class="amazon-channel-mark"><img class="amazon-channel-logo" src="'+e(AMAZON_CHANNEL_LOGO_URL)+'" alt="Amazon" width="6110" height="2047" decoding="async" hidden><span class="amazon-channel-fallback">Amazon</span></span><span class="amazon-country">'+e(market.name)+'</span></h4><p class="amazon-domain">'+e(market.host)+'</p>'+(typeof paymentFeasibilityMarkup==='function'?paymentFeasibilityMarkup({source_code:market.code,source_name:'Amazon '+market.name,sales_region:market.salesRegion,url:'https://'+market.host+'/'}):'')+'<div class="amazon-search-links">'+market.searches.map(search=>'<a data-amazon-search-link="'+e(search.key)+'" href="'+e(search.url)+'" target="_self" rel="noopener noreferrer" aria-label="Amazon '+e(market.name)+'：搜索'+e(search.label)+'">'+e(search.label)+' →</a>').join('')+'</div></section>').join('')+'</div><p class="amazon-brand-note">Amazon 及相关标志归其权利人所有；仅用于识别第三方购买渠道。BikeHunt 与 Amazon 无合作或隶属关系。</p>'+amazonImportGuideMarkup()+(typeof forwardingExplainerMarkup==='function'?forwardingExplainerMarkup():''));
  bindAmazonChannelLogos();
}
function allowedAmazonHelp(link){
  if(!link?.isConnected||!document.getElementById('sheet')?.classList.contains('open')||!document.getElementById('sheetBody')?.contains(link))return null;
  return AMAZON_IMPORT_HELP.find(source=>source.key===link.dataset?.amazonHelpLink&&source.url===link.getAttribute('href'))||null;
}
function guardAmazonHelpExit(event){
  const link=event.target.closest?.('a[data-amazon-help-link]');
  if(!link||(event.type==='auxclick'&&event.button!==1))return;
  event.preventDefault();
  const source=allowedAmazonHelp(link);if(!source)return;
  showExternalExit({url:source.url,kind:'reference',label:source.label,trigger:link,
    sourceNote:'本站保存了 Amazon 英国站官方帮助记录（2026-10-15 核对）；仅适用于所列英国站资料范围。',
    note:'即将查看 Amazon 英国站官方帮助，仅供核对说明，不是商品报价或中国配送保证。',
    validate:()=>allowedAmazonHelp(link)===source,onConfirm:()=>saveBrowseState()});
}
function allowedAmazonSearch(link){
  const key=link.dataset?.amazonSearchLink;
  return AMAZON_SEARCH_MARKETS.flatMap(market=>market.searches).find(search=>search.key===key&&search.url===link.getAttribute('href'))||null;
}
function guardAmazonSearchExit(event){
  const link=event.target.closest?.('a[data-amazon-search-link]');
  if(!link||(event.type==='auxclick'&&event.button!==1))return;
  // Prevent modifier/middle clicks from opening another tab or bypassing the prompt.
  event.preventDefault();
  const search=allowedAmazonSearch(link);if(!search)return;
  if(typeof openAmazonRegistration==='function')openAmazonRegistration(search);
}
// Standalone marketplace search navigation is retired; retained helpers are not public entrances.
document.addEventListener('click',guardAmazonSearchExit);
document.addEventListener('auxclick',guardAmazonSearchExit);
document.addEventListener('click',guardAmazonHelpExit);
document.addEventListener('auxclick',guardAmazonHelpExit);

// Research references never become Offer objects, purchase routes or featured deals.
const ROAD_REFERENCE_SCOPES=Object.freeze({trek:['www.trekbikes.com','/us/en_US/'],specialized:['www.specialized.com','/us/en/'],canyon:['www.canyon.com','/en-us/'],colnago:['www.colnago.com','/en-us/']});
function roadReferenceUrl(row){
  if(!publicProductVisible(row))return '';
  const scope=ROAD_REFERENCE_SCOPES[row?.source_code||row?.code];if(!scope)return '';
  try{const url=new URL(row.url);return url.protocol==='https:'&&!url.username&&!url.password&&!url.port&&url.hostname===scope[0]&&url.pathname.startsWith(scope[1])?url.href:''}catch{return ''}
}
function roadReferenceMatches(row){const query=document.getElementById('q').value.trim().toLowerCase().split(/\s+/).filter(Boolean);return publicProductVisible(row)&&(!activeCategoryGroup||activeCategoryGroup===row.category_group)&&(!activeSource||row.source_code===activeSource)&&profileMatches(row)&&query.every(term=>(row.brand+' '+row.name+' '+(row.color||'')+' '+row.category_name).toLowerCase().includes(term))}
function roadReferenceLink(row,key,label){const url=roadReferenceUrl(row);return row.stock==='out_of_stock'?'<span class="road-sold">已确认售罄 · 暂无商品访问入口</span>':url?'<a data-road-reference="'+e(key)+'" href="'+e(url)+'" target="_self" rel="noopener noreferrer">'+e(label)+' →</a>':'<span>官方链接待核实</span>'}
function referenceImageMarkup(url,name){
  let source='';try{const parsed=new URL(url);if(parsed.protocol==='https:'&&!parsed.username&&!parsed.password)source=parsed.href}catch{}
  return '<div class="reference-image">'+(source?'<img data-reference-image src="'+e(source)+'" alt="'+e(name)+'" loading="lazy" decoding="async">':'')+'<span class="reference-image-fallback"'+(source?' hidden':'')+'>商品图片'+(source?'暂不可用':'待核实')+'</span></div>';
}
document.addEventListener('error',event=>{const img=event.target;if(!img.matches?.('img[data-reference-image]'))return;img.hidden=true;const fallback=img.nextElementSibling;if(fallback)fallback.hidden=false},true);
let roadDetailContext=null;
function roadReferenceFx(currency,now=Date.now()){
  const data=typeof fx==='object'&&fx?fx:{},rate=Number(data.rates?.[currency]);
  const date=typeof data.rate_date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(data.rate_date)?data.rate_date:null;
  const day=date?Date.parse(date+'T00:00:00Z'):NaN,fetched=Date.parse(data.fetched_at||'');
  const valid=Number.isFinite(rate)&&rate>0&&Number.isFinite(day)&&new Date(day).toISOString().slice(0,10)===date&&Number.isFinite(fetched)&&/[T ].*(?:Z|[+-]\d{2}:?\d{2})$/i.test(data.fetched_at||'');
  if(!valid)return {rate:null,date,state:'unknown'};
  const age=now-fetched,dayAge=Math.floor(now/86400000)-Math.floor(day/86400000);
  return {rate,date,state:data.stale||age>86400000||age< -300000||dayAge<0||dayAge>7?'stale':'current'};
}
function roadReferencePriceMarkup(row){
  const quote=roadReferenceFx(row.currency),converted=value=>quote.rate!==null&&Number.isFinite(Number(value))?'约 '+money(Number(value)*quote.rate,'CNY'):'人民币待换算';
  return '<p class="road-price">记录现价 '+e(money(row.price,row.currency))+' <span class="road-cny">'+e(converted(row.price))+'</span><br><small>记录原价 '+e(money(row.reference_price,row.currency))+' · '+e(converted(row.reference_price))+'</small></p>';
}
function roadReferenceFxMarkup(row){
  const quote=roadReferenceFx(row.currency);
  return '<p class="road-reference-fx" data-fx-state="'+quote.state+'">'+(quote.state==='unknown'?'汇率待获取 · 人民币待换算':'汇率 '+e(quote.date)+' · '+(quote.state==='stale'?'过期缓存，换算仅供参考':'每日参考'))+'</p>';
}
function roadReferenceOptionsMarkup(row){return '<div id="roadReferenceOptions"><p>页面选项（非现货，不可选择）：'+e((row.listed_options||[]).join(' / ')||'待核实')+'</p>'+(row.color?'<p>记录配色：'+e(row.color)+'</p>':'')+'<p>'+e(row.observation_note)+'</p><p class="road-warning">'+e(row.notes)+'</p></div>'}
function roadReferenceCard(row){
  if(!publicProductVisible(row))return '';
  return '<section class="road-reference-card" data-road-reference-card="'+e(row.id)+'"><div class="brand">'+e(row.brand)+' · '+e(row.category_name)+'</div>'+referenceImageMarkup(row.image,row.name)+'<h3>'+e(row.name)+'</h3>'+roadReferencePriceMarkup(row)+roadReferenceFxMarkup(row)+'<p class="road-stock">'+(row.stock==='out_of_stock'?'已确认售罄':'库存待核实')+' · 未取得折扣结束时间</p><p class="road-reference-date">研究核对 '+e((row.research_checked_at||roadReferenceData.research_checked_at||'日期未记录').slice(0,10))+' · 价格观察时间未记录</p><p class="road-item-only">人民币仅为商品价换算；运费、税费待核实，不是到手总价。</p><button type="button" class="compare-button" data-road-open="'+e(row.id)+'">查看详情与怎么买 →</button><details><summary>配色、页面选项与限制</summary>'+(row.color?'<p>记录配色：'+e(row.color)+'</p>':'')+'<p>页面选项（非现货）：'+e((row.listed_options||[]).join(' / '))+'</p><p class="road-warning">'+e(row.notes)+'</p></details></section>';
}
function roadReferenceDetailMarkup(row){
  if(!publicProductVisible(row))return '';
  const brand=roadReferenceData.brands.find(entry=>entry.code===row.source_code),source={code:row.source_code,name:row.brand,name_zh:row.brand,official_url:row.url,shop_url:row.url};
  const fit=row.category==='frames'?'对照身高、跨高、Stack / Reach 与官方几何表，核对车架尺码及变速、轮组等兼容性。':row.category==='road_bikes'?'对照身高、跨高、Stack / Reach 与官方几何表，必要时先向官方确认试骑或 fitting。':'对照容量、尺寸与车架空间，确认安装位置和兼容性。';
  return '<article id="roadReferenceDetail" data-road-detail="'+e(row.id)+'"><button type="button" id="roadReferenceBack" class="merchant-guide-back">← 返回商品列表</button><div class="brand">'+e(row.brand)+' · '+e(row.category_name)+' · 美国站研究记录</div>'+referenceImageMarkup(row.image,row.name)+'<h2>'+e(row.name)+'</h2>'+roadReferencePriceMarkup(row)+roadReferenceFxMarkup(row)+'<p class="road-item-only">人民币仅为商品价换算；运费、税费待核实，不是到手总价。</p><p class="road-stock">'+(row.stock==='out_of_stock'?'已确认售罄':'库存待核实')+' · 原价与现价均为历史记录 · 未取得折扣结束时间</p><p class="road-reference-date">研究核对 '+e((row.research_checked_at||roadReferenceData.research_checked_at||'日期未记录').slice(0,10))+'；价格观察时间未记录。汇率更新不代表商品价格或库存更新。</p><details class="road-options"><summary>记录配色与页面选项（非现货）</summary>'+roadReferenceOptionsMarkup(row)+'</details><section class="road-purchase-guide"><h3>怎么买 · 先核对这五步</h3><p class="road-warning">'+e(brand?.note||'市场、配送和购买条件待核实。')+'</p><ol id="roadPurchaseSteps"><li><strong>确认官方市场</strong><p>记录来自美国站、以 '+e(row.currency)+' 标价。先确认你能使用的官方销售市场；换到其他市场后，重新核对当地价格和规则，不能沿用这里的折扣。</p></li><li><strong>核对尺码、适配与库存</strong><p>'+e(fit)+' 页面列出的选项不是现货，须在原站重新选择并确认交期。</p></li><li><strong>确认中国配送或商家允许的路线</strong><p>'+e(brand?.note||'中国直邮、转运与香港路线都待核实。')+' 只有商家明确允许且目的地、承运限制已核实，才继续安排路线。</p></li><li><strong>补齐运费、税费与退货条件</strong><p>中国运费和税费待核实，不按 0 元处理；美国本土运费不能当作中国运费。配件不套用服装税率。先取得完整报价，并核对运输、关税及退换限制。</p></li><li><strong>核对支付与注册要求</strong><p>支付方式、中国发行卡和账户条件待核实；看见卡组织标志也不能保证支付成功。需要账户时，请在官方页面自行查看注册要求；未实测注册或结账。</p></li></ol></section>'+(typeof paymentDirectoryMarkup==='function'?paymentDirectoryMarkup(source):'<p>支付方式与中国发行卡：待核实。</p>')+'<button type="button" id="roadReferenceLanguage" class="quiet-button">看不懂外文？查看中文操作图解 →</button><section id="roadReferenceRegistration"><h3>离站前：注册与账户帮助</h3><p>Sign in = 登录；Create account = 注册；Guest checkout = 游客结账（是否提供待核实）。本页只提供帮助，不代填资料或创建账户。</p>'+(typeof registrationHelpMarkup==='function'?registrationHelpMarkup(row.source_code,row.market):'<p>注册页面图解待核实；请在原站重新核对。</p>')+'</section><div class="road-reference-final">'+roadReferenceLink(row,'product:'+row.id,'已读购买步骤，去官网核实')+'<p>只访问该商品的官方记录地址，不代表可下单。</p></div></article>';
}
function allowedRoadDetailButton(button){
  if(!button?.isConnected)return null;
  const panel=document.getElementById('roadReferencePanel'),inline=document.getElementById('roadReferenceInline');
  const inPanel=sheet.classList.contains('open')&&panel?.contains(button),inInline=activeTab==='products'&&!gallery.hidden&&!gallery.inert&&inline?.contains(button);
  const row=roadReferenceData.products.find(item=>item.id===button.dataset.roadOpen);
  return (inPanel||inInline)&&row&&roadReferenceMatches(row)?{row,origin:inPanel?'panel':'inline',opener:button}:null;
}
function roadReferenceOpener(context,id){
  if(context?.opener?.isConnected)return context.opener;
  const owner=document.getElementById(context?.origin==='panel'?'roadReferencePanel':'roadReferenceInline');
  return [...(owner?.querySelectorAll('[data-road-open]')||[])].find(button=>button.dataset.roadOpen===id)||null;
}
function openRoadReferenceDetail(id,context=null){
  const row=roadReferenceData.products.find(item=>item.id===id);if(!row||!roadReferenceMatches(row))return;
  const saved=context||{origin:'inline',opener:null};
  openPanel('商品详情与购买指引',roadReferenceDetailMarkup(row));
  roadDetailContext={...saved,id:row.id,url:roadReferenceUrl(row)};saveBrowseState();
  const opener=roadReferenceOpener(saved,id);if(saved.origin==='inline'&&opener)lastFocus=opener;
  document.getElementById('roadReferenceBack').onclick=()=>{
    const previous=roadDetailContext;if(!previous)return;
    if(previous.origin==='panel'){
      openRoadReferences();
      const button=[...document.getElementById('sheetBody').querySelectorAll('[data-road-open]')].find(item=>item.dataset.roadOpen===id);button?.focus();
    }else{const button=roadReferenceOpener(previous,id);closeSheet();button?.focus()}
  };
  document.getElementById('roadReferenceLanguage').onclick=()=>{
    const previous=roadDetailContext;if(!previous||typeof merchantLanguageMarkup!=='function')return;
    openPanel('商家中文操作图解',merchantLanguageMarkup({code:row.source_code,name:row.brand}));
    merchantGuideSource=row.source_code;
    document.getElementById('merchantGuideTitle').focus();
    document.getElementById('merchantGuideBack').onclick=()=>{merchantGuideSource=null;openRoadReferenceDetail(id,previous);document.getElementById('roadReferenceLanguage')?.focus()};
  };
}
document.addEventListener('click',event=>{
  const button=event.target.closest?.('button[data-road-open]');if(!button)return;
  const selected=allowedRoadDetailButton(button);if(selected)openRoadReferenceDetail(selected.row.id,selected);
});
function refreshRoadReferenceDetail(){
  const panel=document.getElementById('roadReferenceDetail');if(!panel||!roadDetailContext||!sheet.classList.contains('open'))return;
  const row=roadReferenceData.products.find(item=>item.id===roadDetailContext.id);
  if(!row||roadReferenceUrl(row)!==roadDetailContext.url||!roadReferenceMatches(row)){closeSheet();return}
  const opener=roadReferenceOpener(roadDetailContext,row.id);if(roadDetailContext.origin==='inline'&&opener)lastFocus=opener;
  const price=panel.querySelector('.road-price'),label=panel.querySelector('.road-reference-fx');
  if(price)price.outerHTML=roadReferencePriceMarkup(row);if(label)label.outerHTML=roadReferenceFxMarkup(row);
}
function refreshRoadReferenceFxLabels(){
  // Expiry must be visible even when the tab resumes without a successful fetch.
  document.querySelectorAll('[data-road-reference-card]').forEach(card=>{
    const row=roadReferenceData.products.find(item=>item.id===card.dataset.roadReferenceCard);if(!row)return;
    const price=card.querySelector('.road-price'),label=card.querySelector('.road-reference-fx');
    if(price)price.outerHTML=roadReferencePriceMarkup(row);if(label)label.outerHTML=roadReferenceFxMarkup(row);
  });
  refreshRoadReferenceDetail();
}
function roadReferenceMarkup(inline=false){
  const visibleReferences=publicReferenceData(roadReferenceData);
  const brands=visibleReferences.brands.filter(row=>!activeSource||row.code===activeSource),products=visibleReferences.products.filter(roadReferenceMatches);
  const brandMarkup='<div class="road-brand-grid">'+brands.map(row=>'<section class="road-brand"><h3>'+e(row.name)+'</h3><p>'+e(row.note)+'</p>'+roadReferenceLink(row,'brand:'+row.code,'查看官方入口')+'</section>').join('')+'</div>';
  return '<article id="'+(inline?'roadReferenceInline':'roadReferencePanel')+'"><h2>官网折扣研究参考 · '+products.length+' 条</h2><p class="road-reference-intro">美国官网标价，库存待核实。不进入精选好价，不代表当前可购买；原价与现价均为历史记录。</p><div class="road-reference-grid">'+products.map(roadReferenceCard).join('')+'</div>'+(!products.length?'<p class="road-empty">这个范围内暂无已保存的报价研究记录；请调整分类或搜索。</p>':'')+'<details class="road-research-method"><summary>研究日期与适用范围</summary><p class="road-reference-date">研究核对：'+e(roadReferenceData.research_checked_at||'日期未记录')+'。'+e(roadReferenceData.method_note||'')+'</p><p>沿用当前品牌、分类和搜索范围；页面选项不是现货尺码。价格、可用规格、运费、税费与支付条件请在原站重新核对。</p><p class="road-warning">这里不计算中国到手总价。配件与零部件不套用服装税费估算；美国本土运费不是中国运费。</p></details>'+ (inline?'<details class="road-brand-entrances"><summary>品牌官网入口 · '+brands.length+' 个（不是商品报价）</summary>'+brandMarkup+'</details>':'<h3>品牌官网入口（不是商品报价）</h3>'+brandMarkup)+'</article>';
}
function resetReferenceFeed(){gallery.classList.remove('reference-feed');document.body.classList.remove('reference-feed-visible')}
function historicalDiscountMarkup(products){products=products.filter(publicProductVisible);return '<section id="historicalDiscountReferences"><h2>历史折扣参考 · '+products.length+' 件</h2><p class="road-reference-intro">库存与价格待重新核实，不计入已核实折扣。记录优惠不代表仍在促销。</p><div class="road-reference-grid">'+products.map(p=>'<article class="historical-reference-card" data-history-product="'+e(p.product_id)+'"><div class="brand">'+e(p.brand)+'</div>'+referenceImageMarkup(p.image,p.name_zh||p.name)+'<h3>'+e(p.name_zh||p.name)+'</h3><p class="road-price">记录现价 '+e(money(p.reference_price.amount,p.reference_price.currency))+'<br><small>同规格记录原价 '+e(money(p.reference_original_price.amount,p.reference_original_price.currency))+'</small></p><p class="road-stock">库存待核实 · '+e(p.reference_source)+'</p><p class="road-reference-date">记录规格：'+e([p.reference_size,p.reference_color].filter(Boolean).join(' / ')||'见商品详情')+'<br>'+(p.fetched_at?'上次更新 '+e(p.fetched_at):'更新时间未记录')+'<br>'+ (p.reference_price_valid_until?'记录有效期至 '+e(p.reference_price_valid_until)+'；请在原站重新核实':'未取得折扣结束时间')+'</p><button type="button" data-history-open="'+e(p.product_id)+'" data-history-variant="'+e(p.reference_variant_id)+'">查看历史报价与官网核实入口 →</button></article>').join('')+'</div></section>'}
function renderEmptyReferences(){
  if(featuredBrowse()||activeSource||!document.getElementById('q').value.trim())return false; // Unsearched categories never fall back to unverified references.
  const road=publicCategoryGroupVisible(activeCategoryGroup)&&['road_equipment','other'].includes(activeCategoryGroup),historical=featuredBrowse()?historicalDiscountItems():[];
  if(!road&&!historical.length)return false;
  // Reference records never enter visibleItems(), the verified count or feed paging.
  gallery.classList.add('reference-feed');document.body.classList.add('reference-feed-visible');
  cancelAnimationFrame(animationFrame);swipe=null;animationUntil=0;gallery.classList.remove('gesture-moving');
  gallery.innerHTML='<header class="reference-feed-intro"><strong>'+ (featuredBrowse()?'暂无符合条件的已核实折扣':'这个筛选范围暂无商品报价')+'</strong><span>下面是单独展示的参考记录，库存与价格需在原站重新核实。</span></header>'+(road?roadReferenceMarkup(true):'')+(historical.length?historicalDiscountMarkup(historical):'');
  gallery.querySelectorAll('[data-history-open]').forEach(button=>button.onclick=()=>{
    const row=historicalDiscountItems().find(p=>p.product_id===button.dataset.historyOpen&&p.reference_variant_id===button.dataset.historyVariant);
    if(row&&button.isConnected)openProduct(row.product_id,row.reference_variant_id);
  });
  currentIndex=0;gallery.scrollTop=0;return true;
}
function openRoadReferences(){openPanel('官网参考 · 库存待核实',roadReferenceMarkup());saveBrowseState()}
function allowedRoadReference(link){
  if(!link?.isConnected)return null;
  const key=link.dataset.roadReference,isBrand=key?.startsWith('brand:');
  const panel=document.getElementById('roadReferencePanel'),inline=document.getElementById('roadReferenceInline'),detail=document.getElementById('roadReferenceDetail');
  const inPanel=sheet.classList.contains('open')&&panel?.contains(link),inInline=activeTab==='products'&&publicCategoryGroupVisible(activeCategoryGroup)&&['road_equipment','other'].includes(activeCategoryGroup)&&!gallery.hidden&&!gallery.inert&&inline?.contains(link);
  const inDetail=activeTab==='products'&&sheet.classList.contains('open')&&detail?.contains(link)&&roadDetailContext&&key==='product:'+roadDetailContext.id&&detail.dataset.roadDetail===roadDetailContext.id;
  // Product exits only exist after the internal detail and purchase guide.
  if(isBrand?!inPanel&&!inInline:!inDetail)return null;
  const row=isBrand?publicReferenceData(roadReferenceData).brands.find(row=>'brand:'+row.code===key):roadReferenceData.products.find(row=>'product:'+row.id===key);
  if(!row||row.stock==='out_of_stock'||roadReferenceUrl(row)!==link.getAttribute('href'))return null;
  return isBrand?(!activeSource||row.code===activeSource?row:null):roadDetailContext.url===roadReferenceUrl(row)&&roadReferenceMatches(row)?row:null;
}
function guardRoadReferenceExit(event){
  const link=event.target.closest?.('a[data-road-reference]');if(!link||(event.type==='auxclick'&&event.button!==1))return;
  event.preventDefault();const row=allowedRoadReference(link);if(!row)return;
  showExternalExit({url:row.url,kind:'reference',label:row.name,sourceCode:row.source_code||row.code,trigger:link,image:row.image||'',
    sourceNote:'本站保存的官方研究来源，按确切域名与美国站路径绑定；这不是实时库存或购买资格证明。',
    note:(roadReferenceData.brands.find(brand=>brand.code===(row.source_code||row.code))?.note||'')+' 仅查看参考页面；请重新核实价格、库存与退货条件。',
    validate:()=>{const current=allowedRoadReference(link);return !!current&&roadReferenceUrl(current)===roadReferenceUrl(row)},onConfirm:()=>saveBrowseState()});
}
document.addEventListener('click',guardRoadReferenceExit);
document.addEventListener('auxclick',guardRoadReferenceExit);


// Merchant-language guide: read-only educational content, separate from stock eligibility.
// Sources are public pages checked on 2026-10-15; no account or checkout was exercised.
const MERCHANT_GUIDE_CHECKED_AT='2026-10-15';
const MERCHANT_LANGUAGE_STEPS=Object.freeze([
  {id:'country',title:'先选收货国家',paragraphs:[
    '分别检查 Country / Region（国家或地区）、Language（语言）和 Currency（币种）。选择中文或英文不会改变收货国家；能选国家也不等于所有商品都能配送。'
  ],diagram:[['Country / Pays','收货国家'],['Language / Langue','网页语言'],['Currency / Devise','付款币种']]},
  {id:'account',title:'登录或注册账户',paragraphs:[
    '从 Account / Mon compte（我的账户）进入。已有账号找 Sign in / Se connecter（登录）；新账号找 Create account / Créer un compte（创建账户）。如果商家提供 Guest checkout（游客结账），可按页面选择。',
    'First name / Prénom 是名字，Last name / Nom 是姓氏；Password / Mot de passe 是密码，Confirm password / Confirmer le mot de passe 是再次输入密码。实际字段与验证方式以商家页面为准。',
    'Newsletter / S’abonner 是营销邮件订阅，不等于注册账户。请自己阅读条款并决定是否接受、是否订阅；在确认域名的商家原站完成操作。'
  ],diagram:[['Account / Mon compte','账户入口'],['Sign in / Create account','登录／创建账户'],['Newsletter','独立判断是否订阅']]},
  {id:'size',title:'看尺码，再选规格',paragraphs:[
    '打开 Size guide / Guide des tailles（尺码表），先核对 cm / in（厘米／英寸），再选 Size / Taille（尺码）、Colour / Couleur（颜色）与男女款。不同品牌的同一码不一定相同。',
    'In stock / En stock 是有货；Sold out / Épuisé 是售罄；Pre-order / Précommande 是预订。原站规格与库存需要重新核对。'
  ],diagram:[['Size guide','先看 cm / in'],['Size · Colour','再选尺码／颜色'],['Stock','确认库存或预订']]},
  {id:'cart',title:'加入购物车，复查规格',paragraphs:[
    '选择 Add to cart / Ajouter au panier（加入购物车）后，打开 Cart / Panier（购物车），复查款式、颜色、尺码和 Quantity / Quantité（数量）。',
    '加入购物车不代表已购买，也不保证库存被保留。Checkout / Passer à la caisse 是前往结账，请继续核对订单，别把它当作付款成功。'
  ],diagram:[['Add to cart','加入购物车'],['Cart / Panier','检查规格和数量'],['Checkout','前往结账']]},
  {id:'address',title:'填写地址，核对付款总额',paragraphs:[
    'Shipping address / Adresse de livraison 是收货地址；Billing address / Adresse de facturation 是账单地址，按支付机构记录填写。先确认商家支持目的地，再在原站按要求填写国家、姓名、街道门牌、城市、省州、邮编和电话。',
    'Country / Pays 是国家，City / Ville 是城市，Postcode / Code postal 是邮编。地址栏示意只解释用途，不提供或代填个人资料。',
    '付款前核对实际币种、Shipping / Livraison（配送或运费）、Tax / Duties（税费）、Discount code / Code de réduction（优惠码）、退货费用和 Total（总额）。Pay now / Payer 是付款；Place order / Commander 可能产生付款义务，请由你自行确认。'
  ],diagram:[['Shipping address','你的收货地址（占位）'],['Billing address','支付机构记录地址（占位）'],['Total','商品＋运费＋税费－优惠']]},
  {id:'returns',title:'保存订单，找到退货入口',paragraphs:[
    '付款完成后保存 Order number / Numéro de commande（订单号）和确认邮件。支付状态不清楚时，先查订单或联系商家，避免重复付款。',
    'Returns / Retours 是退货，Refund / Remboursement 是退款，Exchange / Échange 是换货；单数 Retour 也可能是返回上一页。保留包装、吊牌和退货寄件凭证，期限与费用以对应商店政策为准。'
  ],diagram:[['Order number','付款后保存订单号'],['Confirmation email','保留确认邮件'],['Returns / Retours','核对期限和费用']]}
].map(step=>Object.freeze({...step,paragraphs:Object.freeze(step.paragraphs),diagram:Object.freeze(step.diagram.map(pair=>Object.freeze(pair)))})));
const MERCHANT_GUIDE_HELP=Object.freeze([
  ['maap-login','maap','MAAP：官方免密码登录图解','https://support.maap.cc/hc/en-us/articles/7519428331149-I-can-t-remember-my-password'],
  ['maap-size','maap','MAAP：官方尺码说明','https://support.maap.cc/hc/en-us/articles/360037082112-MAAP-Size-Guide'],
  ['visma-register','visma','Visma：公开注册页（仅供查看字段）','https://www.teamvismaleaseabike.com/register/'],
  ['visma-shop','visma','Visma：官方商店地区说明','https://www.teamvismaleaseabike.com/shop/'],
  ['visma-returns','visma','Visma：官方退货说明','https://www.teamvismaleaseabike.com/shop-returns/'],
  ['decathlon-refunds','decathlon','Decathlon CMA CGM：当前退款政策','https://shop.decathloncmacgmteam.com/en/policies/refund-policy'],
  ['decathlon-shop','decathlon','Decathlon CMA CGM：英文商店账户入口','https://shop.decathloncmacgmteam.com/en'],
  ['decathlon-terms','decathlon','Decathlon CMA CGM：销售条款对照','https://shop.decathloncmacgmteam.com/policies/terms-of-sale'],
  ['safari-iphone','browser','Apple：iPhone Safari 中文翻译帮助','https://support.apple.com/zh-cn/guide/iphone/iph1fbef4daa/ios'],
  ['chrome-android','browser','Google：Android Chrome 中文翻译帮助','https://support.google.com/chrome/answer/173424?co=GENIE.Platform%3DAndroid&hl=zh-Hans'],
  ['chrome-ios','browser','Google：iPhone / iPad Chrome 中文翻译帮助','https://support.google.com/chrome/answer/173424?co=GENIE.Platform%3DiOS&hl=zh-Hans']
].map(([key,scope,label,url])=>Object.freeze({key,scope,label,url})));
const MERCHANT_GUIDE_SPECIAL=Object.freeze({
  maap:Object.freeze({scope:'MAAP 官方账户帮助与尺码说明；不代表某收货国家已成功下单。',evidence:'官方帮助已核对；未实测账户与结账。',paragraphs:Object.freeze([
    '已有 MAAP 账户但忘记密码：官方帮助说明，从官网账户图标进入，填写注册邮箱，选 Get Started（开始），再选邮件免密码登录入口；收到邮件后点 Access your account（进入账户）。收不到时先查垃圾邮件。可在下方查看官方图解。',
    '这是已有账户的找回说明，不能推断新用户注册也一定无需密码。新用户完整注册字段、验证过程、账户内地址管理与实际结账均未核实。',
    '商品页的 Size Guide 是尺码表；Which size fits me? 是尺码建议工具。是否向该工具提供个人资料由你决定。此处不重新判断 MAAP 的中国配送规则。'
  ])}),
  visma:Object.freeze({scope:'仅 teamvismaleaseabike.com 英文公开账户与商店页面。',evidence:'公开登录／注册字段及官方商店、退货说明已核对；未提交表单。',paragraphs:Object.freeze([
    '已有账户填写邮箱与密码后选择 Login（登录）；新用户选择 Register（注册）。公开注册页要求 First name（名字）、Last name（姓氏）、邮箱、Password（密码）、Confirm password（确认密码）及 Country（国家），然后是 Create account（创建账户）。',
    '阅读条款后自行决定是否接受。车队邮件与合作伙伴促销是独立订阅选项，应分别判断。未验证注册成功、登录后地址界面或账号与结账的衔接。',
    '商店说明：选择不同国家会影响可见商品、活动与售价；语言与收货国家要分别核对。',
    '退货页写明发票日期起 30 天；不能直接换码，需要退回再购买，个性化商品有例外。非欧盟退货额外费用由客户承担。店铺延长期限与条款中的法定撤回期限不是同一个概念。'
  ])}),
  decathlon:Object.freeze({scope:'仅 shop.decathloncmacgmteam.com 的 /en 车队商城及所列政策；不是迪卡侬中国商店。',evidence:'公开账户入口与官方政策已核对；身份验证页面未成功读取。',paragraphs:Object.freeze([
    '公开入口为 Account（账户）→ Sign in（登录）；Orders（订单）是订单入口，Profile（个人资料）是账户资料入口。后续按商家实际显示的验证方式操作。',
    '未核实注册和身份验证方式，不能推断需要创建密码、输入六位验证码、可使用迪卡侬中国账户，或必须注册才能结账。',
    '官方页面对退货天数和费用有不同表述：主页宣传区为 14 天，主页 FAQ 与退款政策为收货后 30 天；退款政策称退货标签费用从退款中扣除，销售条款另有不同费用说明。购买前确认适用规则，不能承诺免费退货。'
  ])})
});
let merchantGuideSource=null;
function merchantGuideEntries(detail){
  const entries=new Map();
  for(const quote of detail.offers||[]){
    const o=quote.offer;if(!o||typeof o.source_code!=='string')continue;
    if(!entries.has(o.source_code))entries.set(o.source_code,{code:o.source_code,name:o.source_name||o.source_code,markets:[],offers:[]});
    const market=typeof o.sales_region==='string'?o.sales_region:'';const entry=entries.get(o.source_code);
    if(!entry.markets.includes(market))entry.offers.push(o);
    if(!entry.markets.includes(market))entry.markets.push(market);
  }
  return [...entries.values()];
}
function merchantGuidesMarkup(detail){
  const entries=merchantGuideEntries(detail);if(!entries.length)return '';
  return '<section class="merchant-guide-entrances" aria-labelledby="merchantGuidesTitle"><h4 id="merchantGuidesTitle">商家中文操作图解</h4><p>从注册、地址到退货，保留英法原文对照。只读帮助不代表当前商品可购买，售罄时也能查看。</p><div class="merchant-guide-buttons">'+entries.map(entry=>'<button type="button" data-merchant-guide="'+e(entry.code)+'" aria-label="'+e(entry.name)+'：查看中文操作图解">'+e(entry.name)+' · 查看图解 →</button>').join('')+'</div></section>';
}
function bindMerchantGuides(detail,variantId){
  document.getElementById('sheetBody').querySelectorAll('[data-merchant-guide]').forEach(button=>button.onclick=()=>openMerchantGuide(detail,button.dataset.merchantGuide,variantId));
}
function merchantHelpLink(source){return '<a data-merchant-help-link="'+e(source.key)+'" href="'+e(source.url)+'" target="_self" rel="noopener noreferrer">'+e(source.label)+' →</a>'}
function merchantDiagram(pairs,label){
  return '<figure class="merchant-diagram" aria-label="'+e(label)+'示意图"><figcaption>示意 · 非商家截图</figcaption><div class="merchant-diagram-cells">'+pairs.map(([original,chinese])=>'<div><b>'+e(original)+'</b><span>'+e(chinese)+'</span></div>').join('')+'</div></figure>';
}
function merchantTranslationMarkup(){
  return '<details class="merchant-translation"><summary>先用手机翻译外文网页</summary><div class="merchant-step-body"><p>iPhone Safari：打开商家网页，轻点地址栏附近的“页面菜单”；如果出现翻译选项，选择翻译为中文。功能并非在所有语言和地区可用。</p><p>Android Chrome：在顶部翻译提示中选中文；没有提示时，点地址栏右侧“更多”→“翻译”。目标语言可在翻译设置中调整。</p><p>iPhone / iPad Chrome：在顶部翻译栏选中文；没有翻译栏时，点“更多”→“翻译”。无法翻译可先刷新；仍不可用时，保留原文并参考下面的词语对照。</p>'+merchantDiagram([['页面菜单 / 更多','打开浏览器菜单'],['翻译 → 中文','若提供该选项'],['显示原文','核对金额与按钮']],'手机翻译')+'<p>翻译只帮助理解。金额、币种、尺码单位、国家、邮箱和地址请对照原文检查。不要把密码、银行卡资料或含个人资料的结账截图上传到翻译服务。菜单可能随版本、系统和地区变化。</p><p>Apple / Google 官方帮助核对日期：'+MERCHANT_GUIDE_CHECKED_AT+'；未操作你的手机或更改设置。</p><ul>'+MERCHANT_GUIDE_HELP.filter(source=>source.scope==='browser').map(source=>'<li>'+merchantHelpLink(source)+'</li>').join('')+'</ul></div></details>';
}
function merchantSpecialMarkup(code){
  const special=Object.prototype.hasOwnProperty.call(MERCHANT_GUIDE_SPECIAL,code)?MERCHANT_GUIDE_SPECIAL[code]:null;
  if(!special)return '<section class="merchant-evidence"><h3>通用清单 · 该商家流程未逐步核实</h3><p>以下六步为通用语言与操作提示，不代表该商家使用全部字段或按钮。注册、地址、结账、配送和退货须按当前原站核对；未套用其他商家的账户或退货规则。</p><p>内容整理日期：'+MERCHANT_GUIDE_CHECKED_AT+'。未提交注册、登录或订单。</p></section>';
  return '<section class="merchant-evidence"><h3>这家商店已核对的提示</h3><p class="merchant-scope">适用范围：'+e(special.scope)+'</p><p>核对日期：'+MERCHANT_GUIDE_CHECKED_AT+'。'+e(special.evidence)+'</p><details class="merchant-specific-notes"><summary>展开账户与退货提醒</summary>'+special.paragraphs.map(paragraph=>'<p>'+e(paragraph)+'</p>').join('')+'</details><details class="merchant-sources"><summary>查看官方来源与图解（可选）</summary><p>这些是公开说明或账户入口。打开页面不代表代你注册、登录、填地址或付款。</p><ul>'+MERCHANT_GUIDE_HELP.filter(source=>source.scope===code).map(source=>'<li>'+merchantHelpLink(source)+'</li>').join('')+'</ul></details></section>';
}
function merchantLanguageMarkup(entry){
  return '<article id="merchantLanguageGuide"><button class="merchant-guide-back" id="merchantGuideBack" type="button">← 返回商品详情</button><h2 id="merchantGuideTitle" tabindex="-1">'+e(entry.name)+' · 中文操作图解</h2><p class="merchant-guide-intro">请在商家原站自行完成账户、地址、购物车与付款操作。BikeHunt 不收集本指南中的账号、密码、地址或付款资料。真实截图单独标注核对日期和适用范围；通用图形标为示意，未实测注册或结账成功。</p>'+merchantTranslationMarkup()+merchantSpecialMarkup(entry.code)+'<h3 class="merchant-steps-title">六步通用核对清单</h3><p class="merchant-guide-intro">点击展开。原文标签用于寻找对应含义，不代表每家商店使用相同界面。</p><ol class="merchant-guide-steps">'+MERCHANT_LANGUAGE_STEPS.map((step,index)=>'<li><details class="merchant-guide-step" name="merchant-language-steps" data-merchant-step="'+e(step.id)+'"'+(index===0?' open':'')+'><summary><span class="merchant-step-number" aria-hidden="true">'+(index+1)+'</span><span>'+e(step.title)+'</span></summary><div class="merchant-step-body">'+merchantDiagram(step.diagram,step.title)+step.paragraphs.map(paragraph=>'<p>'+e(paragraph)+'</p>').join('')+'</div></details></li>').join('')+'</ol><p class="merchant-guide-intro">查看帮助不会改变所选商品的库存、购买资格或中国配送核实结果。返回详情后，按当前可用规格继续。</p></article>';
}
function openMerchantGuide(detail,code,variantId=null){
  const entry=merchantGuideEntries(detail).find(item=>item.code===code);if(!entry)return;
  merchantGuideSource=entry.code;
  openPanel('商家中文操作图解',merchantLanguageMarkup(entry));
  document.getElementById('merchantGuideTitle').focus();
  document.getElementById('merchantGuideBack').onclick=async()=>{
    merchantGuideSource=null;
    const sequence=detailSequence+1;
    await loadDetail(detail.product_id,variantId);
    if(sequence!==detailSequence||!sheet.classList.contains('open'))return;
    const button=[...document.getElementById('sheetBody').querySelectorAll('[data-merchant-guide]')].find(item=>item.dataset.merchantGuide===code);
    button?.focus();
  };
}
function allowedMerchantHelp(link){
  if(!sheet.classList.contains('open')||!link?.isConnected||!document.getElementById('merchantLanguageGuide')?.contains(link)||merchantGuideSource===null)return null;
  return MERCHANT_GUIDE_HELP.find(source=>source.key===link.dataset?.merchantHelpLink&&source.url===link.getAttribute('href')&&(source.scope==='browser'||source.scope===merchantGuideSource))||null;
}
function guardMerchantHelpExit(event){
  const link=event.target.closest?.('a[data-merchant-help-link]');if(!link||(event.type==='auxclick'&&event.button!==1))return;
  event.preventDefault();
  const source=allowedMerchantHelp(link);if(!source)return;
  showExternalExit({url:source.url,kind:'reference',label:source.label,trigger:link,
    sourceNote:'本站保存了这项官方帮助或公开账户资料（2026-10-15 核对）；页面记录不代表已实测注册或购买。',
    note:'即将查看官方帮助或公开账户入口，仅供阅读核对。此操作不会代你注册、登录或下单，也不表示商品有货或支持中国配送。',
    validate:()=>allowedMerchantHelp(link)===source,onConfirm:()=>saveBrowseState()});
}
document.addEventListener('click',guardMerchantHelpExit);
document.addEventListener('auxclick',guardMerchantHelpExit);

function invalidateReferenceLinks(events=[]){
  for(const quote of referenceOffers.values()){
    const event=events.find(row=>row.recovered_history!==true&&row.offer_id===quote.offer.offer_id);
    if(event?.stock==='out_of_stock')quote.offer.stock='out_of_stock';
  }
  for(const link of document.querySelectorAll('a[data-reference-link]')){
    const quote=referenceOffers.get(link.dataset.referenceLink);
    if(!referenceAvailable(quote)){link.removeAttribute('href');link.setAttribute('aria-disabled','true');}
  }
}
async function refreshReferenceLinks(){
  const entries=[...referenceOffers.entries()],requests=new Map();
  for(const [key,quote] of entries){
    if(!quote.reference_product_id||!quote.reference_variant_id)continue;
    const route='/api/catalog/'+encodeURIComponent(quote.reference_product_id)+'?variant_id='+encodeURIComponent(quote.reference_variant_id);
    quote.reference_verifying=true;
    if(!requests.has(route))requests.set(route,getJson(route));
    try{const detail=await requests.get(route);if(referenceOffers.get(key)!==quote)continue;
      const exact=detail.offers.find(q=>q.offer.offer_id===quote.offer.offer_id&&q.offer.url===quote.offer.url);
      // Never clear an observed sold-out state from a historical event.
      if(exact&&exact.offer.stock==='out_of_stock')quote.offer.stock='out_of_stock';
    }catch{/* A failed read makes no fresh-stock assertion. The saved page is reference-only. */}
    finally{quote.reference_verifying=false;}
  }
  invalidateReferenceLinks();
}
function guardPurchaseExit(event){
  const link=event.target.closest?.('a[data-purchase-link],a[data-reference-link]');if(!link||(event.type==='auxclick'&&event.button!==1))return;
  event.preventDefault();
  const key=link.dataset?.referenceLink,quote=key?referenceOffers.get(key):guideContext?.quote;
  if(!referenceAvailable(quote)||merchantUrl(link.getAttribute('href'))!==merchantUrl(quote.offer.url))return;
  if(key){if(typeof startReferenceRoute==='function')startReferenceRoute(quote)}
  else if(typeof continuePurchaseRoute==='function')continuePurchaseRoute();
}
document.addEventListener('click',guardPurchaseExit);
document.addEventListener('auxclick',guardPurchaseExit);

function showInventoryInvalidated(quote){
  const reason=quote?inventoryLabel(quote.offer):'库存待核实';
  guideContext=null;closeSheet();
  openPanel('库存待核实','<div class="summary-box"><h4>'+e(reason)+'</h4><p>'+(quote?.offer.stock==='out_of_stock'?'该规格已确认售罄，购买链接已停用。':'现货规格选择已停用；历史价格仍可参考。可去官网查看当前库存，重新核对尺码、颜色和价格。')+'</p>'+(typeof paymentFeasibilityMarkup==='function'?paymentFeasibilityMarkup(quote?.offer):'')+referenceLinkMarkup(quote)+'</div>');
}
function expireLocalInventory(now=Date.now()){
  if(typeof refreshRoadReferenceFxLabels==='function')refreshRoadReferenceFxLabels();
  let changed=false;
  // Elapsed time or a failed refresh never rewrites a reliable stock observation.
  // Re-render only presentation so an expired promotion loses its discount badge.
  changed=activeTab==='products';
  if(guideContext&&!guideContext.reference&&!offerAvailable(guideContext.quote,now))showInventoryInvalidated(guideContext.quote);
  else if(currentProduct&&(document.getElementById('variant')||document.getElementById('bundleChoices'))&&currentProduct.variants.some(v=>v.variant_id===currentProduct.variant_id&&v.in_stock)&&!currentProduct.offers.some(q=>offerAvailable(q,now)))showInventoryInvalidated(currentProduct.offers.find(q=>q.offer.stock==='in_stock')||currentProduct.offers[0]);
  if(changed&&activeTab==='products'){const active=gallery.querySelectorAll('.card')[currentIndex]?.dataset.id;render(active)}
}
// Run independently of network success and price-change events, including resumed tabs.
const inventoryTimer=setInterval(()=>{expireLocalInventory();if(!window.BIKEHUNT_PAGES){refreshCatalogSilently(false);if(!guideContext&&currentProduct&&(document.getElementById('variant')||document.getElementById('bundleChoices')))refreshOpenProductDetail()}},60000);
window.addEventListener('focus',()=>expireLocalInventory());
window.addEventListener('pagehide',()=>clearInterval(inventoryTimer),{once:true});

// Returning from a same-tab merchant visit must restart timers cleared on pagehide.
window.addEventListener('pageshow',event=>{if(event.persisted)window.location.reload()});


