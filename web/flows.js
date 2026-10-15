'use strict';
let directoryData={brands:[],teams:[]},categories=[],guideContext=null,guideStep=0,messagesOpen=false;
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
function directoryLogo(item){return item.logo_images?.length?'<span class="team-logo '+(item.logo_theme==='dark'?'team-logo-monochrome':item.logo_theme==='outline'?'team-logo-outline':'')+'">'+item.logo_images.filter(url=>url.startsWith('/web/assets/')||(window.BIKEHUNT_PAGES&&url.startsWith('/')&&url.includes('/web/assets/')&&!url.includes('..'))).slice(0,1).map(url=>'<img src="'+e(url)+'" alt="'+e(item.name)+' 标志" decoding="async">').join('')+'</span>':'<span class="directory-mark">'+e(item.name.split(' ')[0])+'</span>'}
function openPanel(title,content,preserveGuide=false){if(!preserveGuide)guideContext=null;messagesOpen=false;++detailSequence;if(!sheet.classList.contains('open'))lastFocus=document.activeElement;gallery.inert=true;directoryPage.inert=true;sheet.inert=false;document.getElementById('sheetName').textContent=title;document.getElementById('sheetBrand').textContent='BikeHunt 中文海淘助手';document.getElementById('sheetImg').src='';document.getElementById('sheetImg').style.display='none';document.getElementById('sheetBody').innerHTML=content;document.getElementById('sheetBody').scrollTop=0;document.getElementById('overlay').classList.add('open');sheet.classList.add('open');sheet.setAttribute('aria-hidden','false');document.getElementById('close').focus()}
async function postJson(url,data={}){const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const body=await response.json();if(!response.ok)throw new Error(body.detail||'请求失败');return body}
function saveBrowseState(){
  try{const state=history.state&&typeof history.state==='object'?history.state:{};history.replaceState({...state,bikehuntBrowse:{tab:activeTab,source:activeSource,category:activeCategory,query:browseQuery(document.getElementById('q').value)}},'')}catch{}
}
function restoreBrowseState(){
  let saved;try{saved=history.state?.bikehuntBrowse}catch{return}
  if(!saved||typeof saved!=='object')return;
  document.getElementById('q').value=browseQuery(saved.query);
  activeCategory=categories.some(c=>c.code===saved.category)?saved.category:'all';
  activeSource=[...directoryData.brands,...directoryData.teams].some(entry=>entry.code===saved.source)?saved.source:null;
  document.querySelectorAll('[data-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.category===activeCategory)));
  updateBrowseLabel();navigate(['products','brands','teams'].includes(saved.tab)?saved.tab:'products');
}
function browseQuery(value){return typeof value==='string'&&value.length<=200?value:''}
function navigate(tab){activeTab=tab;saveBrowseState();document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-current',b.dataset.tab===tab?'page':'false'));gallery.hidden=tab!=='products';directoryPage.hidden=tab==='products';document.querySelector('.scroll-controls').hidden=tab!=='products';document.getElementById('scrollHint').classList.toggle('hidden',tab!=='products');document.getElementById('categoryNav').hidden=tab!=='products';document.body.classList.toggle('directory-mode',tab!=='products');if(tab==='products'){render()}else{renderDirectory(tab)}}
function chooseCategory(code){activeCategory=code;document.querySelectorAll('[data-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.category===code)));updateBrowseLabel();navigate('products')}
function updateBrowseLabel(){const entry=[...directoryData.brands,...directoryData.teams].find(x=>x.code===activeSource);document.getElementById('browseLabel').textContent=activeSource?(entry?.name_zh||entry?.name||activeSource):document.getElementById('q').value.trim()?'搜索结果':'精选好价'}
function renderDirectory(section){
  const entries=directoryData[section]||[];document.getElementById('browseLabel').textContent=section==='brands'?'品牌官网':'世巡车队';document.getElementById('count').textContent=entries.length+' 个入口';
  const ranking=section==='teams'?directoryData.team_ranking:null;
  directoryPage.innerHTML='<div class="directory-intro"><h2>'+(section==='brands'?'从品牌发现装备':'世巡车队装备，一处查看')+'</h2><p>'+(ranking?e(ranking.season)+' 年 '+e(ranking.title_zh)+' · '+e(ranking.ranking_date)+'<br>':'')+'先看本地商品和中文规则，再决定前往哪个渠道。</p></div><div class="directory-grid">'+entries.map(item=>'<button class="directory-card" data-source="'+e(item.code)+'">'+(item.world_rank?'<span class="team-rank">UCI 第 '+e(item.world_rank)+' 名</span>':'')+directoryLogo(item)+'<strong>'+e(item.name_zh)+'</strong><span>'+e(item.name)+'</span><div class="directory-count">'+(item.product_count??0)+' 款商品 · '+item.offer_count+' 个规格 · '+e(item.catalog_note||'部分目录')+'</div><div class="directory-link">查看商品与中文规则 →</div></button>').join('')+'</div>';
  directoryPage.querySelectorAll('[data-source]').forEach(b=>b.onclick=()=>openSource(b.dataset.source));
}
function ruleMarkup(book){
  if(!book.documents.length)return '<div class="summary-box"><h4>规则正在采集核实</h4><p>这个来源已经登记，完整配送、支付与税费规则尚未取得。当前不会给出未经确认的中国购买保证。</p></div>';
  return '<div class="rule-meta">规则版本 '+book.version+' · 核对 '+e(timeText(book.checked_at))+'</div>'+book.documents.map(doc=>'<section class="rule-section"><h4>'+e(doc.title_zh)+'</h4>'+(doc.state==='translated'?'<ul>'+doc.summary_zh.map(t=>'<li>'+e(t)+'</li>').join('')+'</ul>':'<p class="offer-note">'+(doc.state==='changed'?'官方原文已有变化，最新中文规则正在复核。':'原文已保存，中文规则正在核实。')+'</p>')+'<details><summary>核对来源</summary><a class="source-original" target="_blank" rel="noopener noreferrer" href="'+e(safeUrl(doc.url))+'">查看官方原文（核对用） ↗</a></details></section>').join('');
}
async function openSource(code){
  const entry=[...directoryData.brands,...directoryData.teams].find(x=>x.code===code);openPanel(entry?.name_zh||'中文规则','<p class="loading">正在读取已保存的中文规则…</p>');
  try{const book=await getJson('/api/rules/'+encodeURIComponent(code));document.getElementById('sheetBody').innerHTML=(entry?'<div class="source-overview">'+(entry.logo_images?.length?directoryLogo(entry):'')+'<strong>'+e(entry.name_zh)+'</strong><p>'+entry.offer_count+' 条本地报价 · '+entry.rule_count+' 项中文规则</p><button id="sourceProducts" class="compare-button" '+(!entry.offer_count?'disabled':'')+'>'+(entry.offer_count?'查看该来源商品 →':'商品价格正在接入')+'</button></div>':'')+ruleMarkup(book)+(entry?.official_url?'<details class="official-entrances"><summary>官网与官方商城入口</summary><p><a target="_blank" rel="noopener noreferrer" href="'+e(safeUrl(entry.official_url))+'">品牌或车队官网 ↗</a></p>'+(entry.shop_url?'<p><a target="_blank" rel="noopener noreferrer" href="'+e(safeUrl(entry.shop_url))+'">官方公布的商城入口 ↗</a></p>':'')+'<p>入口已找到不代表中国配送、库存或到手费用已核实。</p></details>':'')+'<div class="service-note">规则按原文变化更新；未核实的条件会明确标记。</div>';const button=document.getElementById('sourceProducts');if(button)button.onclick=()=>{activeCategory='all';activeSource=code;document.querySelectorAll('[data-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.category==='all')));document.getElementById('browseLabel').textContent=entry.name_zh;closeSheet();navigate('products')}}catch(error){document.getElementById('sheetBody').innerHTML='<p>'+e(error.message)+'</p>'}
}
async function startGuide(detail,offerId){
  const quote=detail.offers.find(x=>x.offer.offer_id===offerId);if(!quote||!offerAvailable(quote))return;
  guideContext={detail,quote,book:null};openPanel('中文海淘指引','<p class="loading">读取中文配送与支付规则…</p>',true);const sequence=detailSequence;
  try{const book=await getJson('/api/rules/'+encodeURIComponent(quote.offer.source_code));if(sequence!==detailSequence)return;if(!offerAvailable(quote)){showInventoryInvalidated(quote);return}guideContext={detail,quote,book};guideStep=0;renderGuide()}catch(error){if(sequence!==detailSequence)return;guideContext=null;document.getElementById('sheetBody').innerHTML='<p>'+e(error.message)+'</p>'}
}
const GUIDE_ICONS=[
'<path d="M8 5l4 2 4-2 5 4-3 4-2-2v13H8V11l-2 2-3-4z"/>',
'<path d="M3 7h12v12H3zM15 11h4l3 4v4h-7"/><circle cx="7" cy="20" r="2"/><circle cx="19" cy="20" r="2"/>',
'<rect x="6" y="3" width="14" height="22" rx="3"/><path d="M9 7h8M9 12h2M15 12h2M9 17h2M15 17h2M9 21h2M15 21h2"/>',
'<rect x="3" y="6" width="22" height="16" rx="3"/><path d="M3 11h22M7 17h5M18 16l3 3-3 3"/>'
];
function guideMap(){return '<ol class="guide-map" aria-label="购买四步图示">'+['选规格','看配送','算费用','原站购买'].map((name,index)=>'<li class="'+(index===guideStep?'active':index<guideStep?'done':'')+'" '+(index===guideStep?'aria-current="step"':'')+'><span class="guide-icon"><svg viewBox="0 0 28 28" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">'+GUIDE_ICONS[index]+'</svg></span><b>'+(index+1)+'</b><span>'+name+'</span></li>').join('')+'</ol>'}
function renderGuide(){
  if(!guideContext)return;if(!offerAvailable(guideContext.quote)){showInventoryInvalidated(guideContext.quote);return;}
  const {detail,quote,book}=guideContext,o=quote.offer;const changed=book.documents.some(d=>d.state==='changed');
  const titles=['核对选中的现货规格','确认发货地和中国配送','核对人民币商品价与费用','按中文提示到原站购买'];
  let content='';
  if(guideStep===0)content='<img class="guide-product" src="'+e(safeUrl(detail.image))+'" alt="'+e(detail.name_zh||detail.name)+'"><p>商品：<strong>'+e(detail.name_zh||detail.name)+'</strong></p><div class="selected-spec"><span>尺码 <strong>'+e(detail.identity.size||'尚待核实')+'</strong></span><span>颜色 <strong>'+e(detail.identity.color||'当前商品图配色')+'</strong></span><span class="tag '+(offerAvailable(quote)?'ok':'wait')+'">'+e(inventoryLabel(o))+'</span></div>'+(o.purchase_requirements?.length?'<p class="offer-note">'+o.purchase_requirements.map(e).join(' · ')+'</p>':'')+'<p>库存核对 <span id="guideObservation">'+e(timeText(o.fetched_at))+'</span>，核实结果最多保留一小时。下单前在原站再次核对尺码、颜色和男女款。</p><div class="term-box"><b>Size</b> 尺码　<b>Color</b> 颜色　<b>Quantity</b> 数量</div>';
  if(guideStep===1)content='<div class="logistics-map"><span>发货地<br><b>'+e(o.dispatch_origin||'官方仓库尚待核实')+'</b></span><i>→</i><span>目的地<br><b>中国大陆</b></span></div><p class="guide-conclusion">'+(o.shipping_to_china.status==='no'?'这个渠道不直邮中国大陆，请返回选择其他渠道。':o.shipping_to_china.status==='yes'&&!changed?'官方规则已确认中国配送目的地。':'中国目的地尚需核实，请在原站确认中国地址可配送。')+'</p><p>'+e(o.sales_region||o.source_name)+'的标价不等于该地区的仓库发货。</p>'+ruleMarkup({...book,documents:book.documents.filter(d=>d.key==='shipping')})+'<div class="term-box"><b>Ship to / Country</b> 配送国家，选择 <b>China</b>（中国）。</div>';
  if(guideStep===2)content='<p>选中规格：'+e(detail.identity.size||'尺码待核实')+'；原币商品价 '+e(money(o.price.amount,o.price.currency))+'。</p>'+landedCostMarkup(quote)+'<p class="service-note">预估仅用于预算，最终运费、税费与银行卡费用以商家结账、承运商和海关实际核定为准。</p><div class="term-box"><b>Shipping</b> 运费　<b>Tax / Duties</b> 税费　<b>Total</b> 合计</div>';
  if(guideStep===3)content='<p>中国发行、支持境外付款的对应卡种可按商家条件使用，包括招商银行等银行的 Visa、Mastercard 信用卡。</p><p>该渠道公布的卡种：<strong>'+e(o.accepted_card_networks?.join(' / ')||'尚待取得完整规则')+'</strong>。确认境外支付权限、额度和银行安全验证。</p>'+ruleMarkup({...book,documents:book.documents.filter(d=>d.key==='payment')})+'<div class="checkout-path"><span>选择 '+e(detail.identity.size)+' / '+e(detail.identity.color||'当前配色')+'</span><i>↓</i><span>配送国家选中国，填写真实地址</span><i>↓</i><span>核对运费税费，再完成付款</span></div><div class="term-box"><b>Add to cart</b> 加入购物车<br><b>Checkout</b> 结账<br><b>First / Last name</b> 名 / 姓<br><b>Postal code</b> 邮政编码<br><b>Billing address</b> 账单地址<br><b>Place order</b> 提交订单</div><a class="compare-button" data-purchase-link target="_self" rel="noopener noreferrer" href="'+e(safeUrl(o.url))+'">去该商品原页面购买 ↗</a><p class="service-note">实际付款以银行授权为准。扣款结果不明确时先核对账单与订单确认。交易、配送和售后由原网站完成。</p>';
  openPanel('中文购买指引',guideMap()+'<div class="guide-progress">第 '+(guideStep+1)+' 步 / 4 · '+e(o.source_name)+'</div><h2 class="guide-title">'+titles[guideStep]+'</h2><div class="guide-content">'+content+'</div><div class="guide-actions"><button id="guideBack">'+(guideStep?'上一步':'返回比价')+'</button>'+(guideStep<3?'<button id="guideNext" '+(guideStep===1&&o.shipping_to_china.status==='no'?'disabled':'')+'>下一步 →</button>':'')+'</div>',true);
  document.getElementById('guideBack').onclick=()=>{if(guideStep){guideStep--;renderGuide()}else{guideContext=null;loadDetail(detail.product_id,detail.variant_id)}};
  const next=document.getElementById('guideNext');if(next)next.onclick=()=>{guideStep++;renderGuide()};
}
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
  const p=eventProduct(event);if(!p||!p.model)return 'event:'+event.id;
  const url=merchantUrl(event.url);if(!url)return 'event:'+event.id;
  const productUrl=new URL(url);
  // Only proven catalog families may fold the Shopify size selector. Keep all other URL fields.
  if(p.product_id&&productUrl.pathname.includes('/products/'))productUrl.searchParams.delete('variant');
  return JSON.stringify([event.source_code,p.product_id||null,productUrl.href,p.brand,p.model,p.color||null,p.image||null,event.currency,event.old_price,event.new_price,event.kind,event.stock,event.observed_at,event.recovered_history===true]);
}
function groupMessages(events){
  const grouped=new Map();for(const event of events){const key=messageGroupKey(event);if(!grouped.has(key))grouped.set(key,{...event,members:[]});grouped.get(key).members.push(event)}return [...grouped.values()];
}
function hasNewPriceMessages(events){return events.some(event=>event.recovered_history!==true&&(activeCategory==='all'||event.category===activeCategory))}
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
  const rows=data.items.slice(0,100);
  if(rows.some(event=>!event||!validMessageKey(event.event_key)||!Number.isSafeInteger(event.id)||event.id<=0))throw new Error('价格消息标识无效');
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
function messageCardMarkup(event,fx){
  const p=eventProduct(event),rate=fx?.rates?.[event.currency],converted=rate?Number(event.new_price)*Number(rate):null;
  const image=p&&safeUrl(p.image),sold=messageQuote(event).offer.stock==='out_of_stock',route=messageProductRoute(event);
  const photo=image?'<img class="message-image" loading="lazy" src="'+e(image)+'" alt="'+e([p.name,p.model,p.color].filter(Boolean).join(' · '))+'"><span class="message-no-image" hidden>暂无该商品图片</span>':'<span class="message-no-image">暂无该商品图片</span>';
  const thumb=route?messageProductButton(event,photo,'message-thumbnail'):'<div class="message-thumbnail">'+photo+'</div>';
  const members=event.members||[event],sizes=[...new Set(members.map(row=>eventProduct(row)?.size).filter(Boolean))];
  const variantLinks=members.length>1?'<div class="message-variants">'+members.map(row=>{const label=e(eventProduct(row)?.size||'规格待核实');return messageProductRoute(row)?messageProductButton(row,label,'message-variant'):'<span>'+label+'</span>'}).join('')+'</div>':'';
  const title=route?messageProductButton(event,e(event.name_zh),'message-title'):e(event.name_zh);
  const marketUpdate=event.recovered_history!==true&&event.kind==='price_changed'&&event.old_price===null;
  return '<article class="message-card"'+messageProductAttributes(event)+'><div class="message-layout">'+thumb+'<div class="message-copy"><div class="brand">'+e(event.source_name)+' · '+e(timeText(event.observed_at))+'</div>'+(event.recovered_history===true?'<div class="message-stock-note">恢复的历史记录</div>':'')+'<h4>'+title+'</h4><p class="message-spec">型号：'+e(p?.model||'待核实')+'<br>颜色：'+e(p?.color||'未标注，请核对商品图片')+'<br>尺码：'+e(sizes.length?sizes.join(' / '):'未记录')+'</p><p>'+(event.recovered_history===true?'历史记录：':marketUpdate?'报价币种/市场更新：':event.kind==='price_changed'?'价格更新：':event.kind==='inventory_changed'?'库存更新：':'新发现报价：')+e(event.old_price!=null&&event.kind==='price_changed'?money(event.old_price,event.currency)+' → ':'')+e(money(event.new_price,event.currency))+' · '+e(converted==null?'人民币待换算':cny(converted))+'</p>'+(marketUpdate?'<p class="message-stock-note">商家响应的报价币种/市场发生变化，并非你切换了市场；不同币种报价不直接比较涨跌。</p>':'')+(sold?'<span class="tag no">所示报价已售罄，无购买链接</span>':'')+(route?messageProductButton(event,'查看本站商品详情 →','message-product-link'):'<span class="tag wait">该商品详情暂不可用</span>')+variantLinks+'<p class="message-stock-note">'+(sold?'该规格已售罄，可查看本站记录。':'历史变动记录；点击查看本站商品详情与渠道报价。')+'</p></div></div></article>';
}
async function refreshMessageState(){const data=await getJson('/api/updates');rememberMessageEvents(data);return data}
async function showMessages(){
  openPanel('最新价格消息','<p class="loading">正在读取价格更新…</p>');messagesOpen=true;const sequence=detailSequence;
  const data=await refreshMessageState();if(sequence!==detailSequence||!messagesOpen||!sheet.classList.contains('open'))return;
  const rows=[...messageEvents.values()].sort((a,b)=>b.id-a.id);
  document.getElementById('sheetBody').innerHTML=rows.length?groupMessages(rows).map(event=>messageCardMarkup(event,data.fx)).join(''):'<div class="summary-box"><h4>暂时没有新的价格变动</h4><p>同价重复采集不会制造降价提醒。新报价或价格变化会出现在这里。</p></div>';
  document.getElementById('sheetBody').querySelectorAll('.message-image').forEach(img=>img.onerror=()=>{img.hidden=true;img.nextElementSibling.hidden=false});
  document.getElementById('sheetBody').querySelectorAll('.message-card[data-message-product]').forEach(card=>card.onclick=event=>{const target=event.target.closest('[data-message-product]');if(target)openMessageProduct(target.dataset.messageProduct,target.dataset.messageVariant)});
  markMessagesRead(rows);
}
async function refreshCatalogSilently(invalidateGuide=true){try{if(invalidateGuide&&guideContext){guideContext=null;closeSheet();}const active=gallery.querySelectorAll('.card')[currentIndex]?.dataset.id;const data=await getJson('/api/catalog');items=data.items;fx=data.fx;updateFxLabel();sourceCount=data.source_count;if(activeTab==='products')render(active)}catch{}}
async function bootFlows(){
  const data=await getJson('/api/catalog');categories=data.categories||[];
  document.getElementById('categoryNav').innerHTML=categories.map(c=>'<button data-category="'+c.code+'" aria-pressed="'+(c.code==='all')+'">'+e(c.name)+'</button>').join('');document.querySelectorAll('[data-category]').forEach(b=>b.onclick=()=>chooseCategory(b.dataset.category));
  directoryData=await getJson('/api/directories');
  restoreBrowseState();
  refreshMessageState().catch(()=>{});
    if(activeTab!=='products')renderDirectory(activeTab);
  const onPrices=(events,freshnessChanged=false)=>{const wasMessages=messagesOpen;invalidateReferenceLinks(events);refreshReferenceLinks().catch(()=>{});if(guideContext){guideContext=null;closeSheet();}if(hasNewPriceMessages(events)){document.getElementById('updateToast').hidden=false;setTimeout(()=>document.getElementById('updateToast').hidden=true,5000)}if(wasMessages)showMessages().catch(panelError);else refreshMessageState().catch(()=>{});refreshCatalogSilently();if(currentProduct&&document.getElementById('variant')&&(freshnessChanged||events.some(x=>currentProduct.offers.some(q=>q.offer.offer_id===x.offer_id)))){loadDetail(currentProduct.product_id,document.getElementById('variant').value||null)}};
  if(window.BIKEHUNT_PAGES){window.addEventListener('bikehunt-published',event=>onPrices(event.detail.events,event.detail.freshnessChanged));return}
  const eventSource=new EventSource('/api/updates/stream');eventSource.addEventListener('prices',event=>onPrices(JSON.parse(event.data)));window.addEventListener('pagehide',()=>{eventSource.close()},{once:true});
}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{if(b.dataset.tab==='products'){activeSource=null;document.getElementById('q').value='';updateBrowseLabel()}navigate(b.dataset.tab)});
const panelError=error=>{document.getElementById('sheetBody').innerHTML='<p class="offer-note">'+e(error.message)+'</p>'};
async function showCommunity(){saveBrowseState();window.location.assign(new URL(window.BIKEHUNT_PAGES?'./group/':'/web/group/',window.location.href).href)}
document.getElementById('wechatCommunity').onclick=()=>showCommunity().catch(panelError);
document.getElementById('browseSettings').onclick=browseSettings;document.getElementById('priceMessages').onclick=()=>showMessages().catch(panelError);document.getElementById('updateToast').onclick=()=>{document.getElementById('updateToast').hidden=true;showMessages().catch(panelError)};
document.getElementById('refreshPrices').onclick=async()=>{const button=document.getElementById('refreshPrices');button.disabled=true;button.textContent='核对中…';const finish=()=>{button.disabled=false;button.textContent=window.BIKEHUNT_PAGES?'检查最新发布':'核对最新价格'};try{await postJson('/api/refresh/prices');const poll=async()=>{try{const state=await getJson('/api/refresh/status');if(state.state==='running'){setTimeout(poll,3000);return}finish();await refreshCatalogSilently();if(state.state==='failed'||state.state==='partial'){openPanel('价格核对结果','<p>部分渠道未能取得新报价，已保留上一份有效数据。请查看各商品的采集时间。</p>')}}catch(error){finish();openPanel('价格核对失败','<p>'+e(error.message)+'</p>')}};setTimeout(poll,3000)}catch(error){finish();openPanel('价格核对失败','<p>'+e(error.message)+'</p>')}};
document.getElementById('close').addEventListener('click',()=>{document.getElementById('sheetImg').style.display=''});
document.body.addEventListener('touchend',event=>{if(event.touches.length>0)return;const touch=event.changedTouches[0];if(!touch)return;const now=performance.now();const previous=document.body._lastTap;if(previous&&now-previous.time<330&&Math.abs(touch.clientX-previous.x)<25&&Math.abs(touch.clientY-previous.y)<25){if(event.cancelable)event.preventDefault()}document.body._lastTap={time:now,x:touch.clientX,y:touch.clientY}},{passive:false});
function startFlows(){
  return bootFlows().catch(()=>{
    // A failed initial publication must not permanently prevent UI subscriptions.
    // Wait for a verified publication; recovery does not start extra downloads.
    if(window.BIKEHUNT_PAGES)window.addEventListener('bikehunt-published',()=>{init();startFlows();},{once:true});
  });
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
].map(([code,name,host,jerseys,bibs])=>Object.freeze({code,name,host,searches:Object.freeze([
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
  openPanel('Amazon购买途径','<div class="summary-box amazon-summary"><h4>搜索入口，非商品实时报价</h4><p>以下链接打开 Amazon 官方站点的公路骑行服搜索。本页未接入 Amazon 商品数据，未核实搜索结果中的卖家、价格或库存。</p></div><div class="amazon-market-grid">'+AMAZON_SEARCH_MARKETS.map(market=>'<section class="amazon-market"><h4 class="amazon-market-title"><span class="amazon-channel-mark"><img class="amazon-channel-logo" src="'+e(AMAZON_CHANNEL_LOGO_URL)+'" alt="Amazon" width="6110" height="2047" decoding="async" hidden><span class="amazon-channel-fallback">Amazon</span></span><span class="amazon-country">'+e(market.name)+'</span></h4><p class="amazon-domain">'+e(market.host)+'</p><div class="amazon-search-links">'+market.searches.map(search=>'<a data-amazon-search-link="'+e(search.key)+'" href="'+e(search.url)+'" target="_self" rel="noopener noreferrer" aria-label="Amazon '+e(market.name)+'：搜索'+e(search.label)+'">'+e(search.label)+' →</a>').join('')+'</div></section>').join('')+'</div><p class="amazon-brand-note">Amazon 及相关标志归其权利人所有；仅用于识别第三方购买渠道。BikeHunt 与 Amazon 无合作或隶属关系。</p>'+amazonImportGuideMarkup());
  bindAmazonChannelLogos();
}
function allowedAmazonHelp(link){
  return AMAZON_IMPORT_HELP.find(source=>source.key===link.dataset?.amazonHelpLink&&source.url===link.getAttribute('href'))||null;
}
function guardAmazonHelpExit(event){
  const link=event.target.closest?.('a[data-amazon-help-link]');
  if(!link||(event.type==='auxclick'&&event.button!==1))return;
  event.preventDefault();
  const source=allowedAmazonHelp(link);if(!source)return;
  if(!window.confirm(PURCHASE_DISCLAIMER+'\n\n即将查看 Amazon 英国站官方帮助，仅供核对说明，不是商品报价或中国配送保证。\n确定：继续查看；取消：留在本站。'))return;
  if(allowedAmazonHelp(link)!==source)return;
  saveBrowseState();window.location.assign(source.url);
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
  if(!window.confirm(PURCHASE_DISCLAIMER+'\n\nAmazon 官方站点搜索入口，非商品实时报价。\n确定：继续前往搜索；取消：留在本站。'))return;
  // Revalidate after the dialog; never accept a substituted URL, query or affiliate tag.
  if(allowedAmazonSearch(link)!==search)return;
  saveBrowseState();window.location.assign(search.url);
}
document.getElementById('amazonChannels').onclick=showAmazonChannels;
document.addEventListener('click',guardAmazonSearchExit);
document.addEventListener('auxclick',guardAmazonSearchExit);
document.addEventListener('click',guardAmazonHelpExit);
document.addEventListener('auxclick',guardAmazonHelpExit);

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
  for(const quote of detail.offers||[]){const o=quote.offer;if(o&&typeof o.source_code==='string'&&!entries.has(o.source_code))entries.set(o.source_code,{code:o.source_code,name:o.source_name||o.source_code})}
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
  return '<article id="merchantLanguageGuide"><button class="merchant-guide-back" id="merchantGuideBack" type="button">← 返回商品详情</button><h2 id="merchantGuideTitle" tabindex="-1">'+e(entry.name)+' · 中文操作图解</h2><p class="merchant-guide-intro">请在商家原站自行完成账户、地址、购物车与付款操作。BikeHunt 不收集本指南中的账号、密码、地址或付款资料。所有图形都是示意，未实测注册或结账成功。</p>'+merchantTranslationMarkup()+merchantSpecialMarkup(entry.code)+'<h3 class="merchant-steps-title">六步通用核对清单</h3><p class="merchant-guide-intro">点击展开。原文标签用于寻找对应含义，不代表每家商店使用相同界面。</p><ol class="merchant-guide-steps">'+MERCHANT_LANGUAGE_STEPS.map((step,index)=>'<li><details class="merchant-guide-step" name="merchant-language-steps" data-merchant-step="'+e(step.id)+'"'+(index===0?' open':'')+'><summary><span class="merchant-step-number" aria-hidden="true">'+(index+1)+'</span><span>'+e(step.title)+'</span></summary><div class="merchant-step-body">'+merchantDiagram(step.diagram,step.title)+step.paragraphs.map(paragraph=>'<p>'+e(paragraph)+'</p>').join('')+'</div></details></li>').join('')+'</ol><p class="merchant-guide-intro">查看帮助不会改变所选商品的库存、购买资格或中国配送核实结果。返回详情后，按当前可用规格继续。</p></article>';
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
  if(!window.confirm(PURCHASE_DISCLAIMER+'\n\n即将查看官方帮助或公开账户入口，仅供阅读核对。此操作不会代你注册、登录或下单，也不表示商品有货或支持中国配送。\n确定：继续查看；取消：留在本站。'))return;
  if(allowedMerchantHelp(link)!==source)return;
  saveBrowseState();window.location.assign(source.url);
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
  const referenceKey=link.dataset?.referenceLink;
  const valid=()=>referenceKey?referenceAvailable(referenceOffers.get(referenceKey))&&merchantUrl(link.getAttribute('href'))===merchantUrl(referenceOffers.get(referenceKey).offer.url):!!guideContext&&offerAvailable(guideContext.quote)&&!!merchantUrl(guideContext.quote.offer.url)&&merchantUrl(link.getAttribute('href'))===merchantUrl(guideContext.quote.offer.url);
  if(!valid()){event.preventDefault();if(!referenceKey&&guideContext)showInventoryInvalidated(guideContext.quote);return}
  if(!window.confirm(PURCHASE_DISCLAIMER+'\n\n确定：继续前往商家；取消：留在本站。')){event.preventDefault();return}
  if(!valid()){event.preventDefault();if(!referenceKey&&guideContext)showInventoryInvalidated(guideContext.quote);return}
  saveBrowseState();
}
document.addEventListener('click',guardPurchaseExit);
document.addEventListener('auxclick',guardPurchaseExit);

function showInventoryInvalidated(quote){
  const reason=quote?inventoryLabel(quote.offer):'库存待核实';
  guideContext=null;closeSheet();
  openPanel('库存待核实','<div class="summary-box"><h4>'+e(reason)+'</h4><p>'+(quote?.offer.stock==='out_of_stock'?'该规格已确认售罄，购买链接已停用。':'现货规格选择已停用；历史价格仍可参考。可去官网查看当前库存，重新核对尺码、颜色和价格。')+'</p>'+referenceLinkMarkup(quote)+'</div>');
}
function expireLocalInventory(now=Date.now()){
  let changed=false;
  for(const card of items){if(card.stock_state==='in_stock'&&!inventoryVerified(card,now)){card.stock_state='unknown';card.reference_stock='unknown';card.available_sizes=[];card.recommended_total_cny=null;card.status='库存待核实';changed=true}else if(card.reference_stock==='in_stock'&&!offerAvailable({offer:{stock:card.reference_stock,collection_state:card.reference_collection_state,fetched_at:card.fetched_at,price_valid_until:card.reference_price_valid_until}},now)){card.reference_stock='unknown';card.recommended_total_cny=null;changed=true}}
  if(guideContext&&!offerAvailable(guideContext.quote,now))showInventoryInvalidated(guideContext.quote);
  else if(currentProduct&&document.getElementById('variant')&&currentProduct.variants.some(v=>v.variant_id===currentProduct.variant_id&&v.in_stock)&&!currentProduct.offers.some(q=>offerAvailable(q,now)))showInventoryInvalidated(currentProduct.offers.find(q=>q.offer.stock==='in_stock')||currentProduct.offers[0]);
  if(changed&&activeTab==='products'){const active=gallery.querySelectorAll('.card')[currentIndex]?.dataset.id;render(active)}
}
// Run independently of network success and price-change events, including resumed tabs.
const inventoryTimer=setInterval(()=>{expireLocalInventory();if(!window.BIKEHUNT_PAGES){refreshCatalogSilently(false);if(!guideContext&&currentProduct&&document.getElementById('variant'))loadDetail(currentProduct.product_id,document.getElementById('variant').value||null)}},60000);
window.addEventListener('focus',()=>expireLocalInventory());
window.addEventListener('pagehide',()=>clearInterval(inventoryTimer),{once:true});

// Returning from a same-tab merchant visit must restart timers cleared on pagehide.
window.addEventListener('pageshow',event=>{if(event.persisted)window.location.reload()});
