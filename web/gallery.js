'use strict';
let items=[],fx={},currentIndex=0,currentProduct=null,detailSequence=0,lastFocus=null,sourceCount=0;
let observer=null,viewMode='feed';
const referenceOffers=new Map();
let activeCategory='all',activeSource=null,activeTab='products';
let swipe=null,animationFrame=0,animationUntil=0,wheelLocked=false,wheelUnlockTimer=0;
const gallery=document.getElementById('grid');
const sheet=document.getElementById('sheet');
const e=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl=value=>{try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)&&!u.username&&!u.password?u.href:''}catch{return ''}};
function money(value,currency='CNY'){
  if(value==null||!Number.isFinite(Number(value))) return '待确认';
  return new Intl.NumberFormat('zh-CN',{style:'currency',currency,maximumFractionDigits:currency==='JPY'?0:2}).format(Number(value));
}
function cny(value){return value==null?'人民币待换算':money(value)}
function timeText(value){if(!value)return '历史缓存 · 采集时间未记录';const d=new Date(value);return Number.isNaN(d.getTime())?'采集时间待确认':new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Shanghai'}).format(d)}
function updateFxLabel(){const label=document.getElementById('fxDate');label.textContent='汇率 '+(fx.rate_date||'待获取')+(fx.stale?' · 过期缓存':'');label.title=(fx.source||'ECB')+' 每日参考汇率；最近成功核对 '+timeText(fx.fetched_at)+'；周末和节假日沿用最近公布日期。';label.classList.toggle('stale',!!fx.stale)}
async function getJson(url){const response=await fetch(url);if(!response.ok)throw new Error('请求失败（'+response.status+'）');return response.json()}
function imageMarkup(url,name,index){
  return '<button class="image-button" type="button" aria-label="查看 '+e(name)+' 的渠道比价"><img '+(index<2?'fetchpriority="high"':'loading="lazy"')+' src="'+e(safeUrl(url))+'" alt="'+e(name)+'"></button><div class="photo-fallback">BikeHunt<span>商品图片暂不可用</span></div>';
}
function visibleItems(){const q=document.getElementById('q').value.trim().toLowerCase().split(/\s+/).filter(Boolean);return items.filter(p=>p.stock_state!=='out_of_stock'&&profileMatches(p)&&(activeCategory==='all'||p.category===activeCategory)&&(!activeSource||p.source_codes?.includes(activeSource))&&q.every(t=>(p.brand+' '+p.name+' '+(p.name_zh||'')+' '+(p.color||'')).toLowerCase().includes(t)))}
function render(preserveId=null){
  if(observer)observer.disconnect();
  const list=visibleItems();
  document.getElementById('count').textContent=list.length+' 件商品';
  document.getElementById('sourceCount').textContent=sourceCount+' 个已采集报价源';
  if(!list.length){gallery.innerHTML='<div class="empty"><strong>没有找到这个商品</strong>试试商品名称或品牌。<br><button type="button" id="resetSearch">清空搜索</button></div>';document.getElementById('resetSearch').onclick=clearSearch;updatePosition(0,0);return}
  gallery.innerHTML=list.map((p,i)=>{
    const stockVerified=p.stock_state==='in_stock'&&inventoryVerified(p)&&p.reference_collection_state!=='retained';
    const isVerified=stockVerified&&p.recommended_total_cny!=null;
    const expired=['库存核实已过期','库存待核实'].includes(p.status)||p.stock_state==='in_stock'&&!stockVerified;
    const sold=p.stock_state==='out_of_stock';
    return '<article class="card" data-id="'+e(p.product_id)+'" aria-label="商品 '+(i+1)+'：'+e(p.name)+'"><div class="card-inner">'+
      '<div class="product-visual">'+imageMarkup(p.image,p.name,i)+
      (p.discount_pct?'<span class="discount">−'+e(p.discount_pct)+'%</span>':'')+
      '<span class="slide-index">'+String(i+1).padStart(2,'0')+' / '+String(list.length).padStart(2,'0')+'</span></div>'+
      '<div class="product-info"><div class="brand">'+e(p.brand)+'</div><h2>'+e(p.name_zh||p.name)+'</h2><div class="original-name">'+e(p.name)+'</div>'+
      '<div class="product-meta"><span>'+p.source_count+' 个渠道</span><span>'+(stockVerified&&p.available_sizes?.length?'现货 '+e(p.available_sizes.join(' / ')):expired?'库存待核实':p.variant_count+' 个规格 · 库存待确认')+'</span>'+
      (sold?'<span class="sold">所示报价已售罄</span>':'')+'</div>'+
      '<div class="buyline"><div class="price-label">'+(sold?'所示报价已售罄':isVerified?'最低预计成本 · 先选规格':stockVerified&&p.available_sizes?.length?'现货商品参考起价 · 先选规格':expired?'历史参考价 · 库存待核实':'参考起价 · 库存待核实')+'</div>'+
      '<div class="best-price">'+e(cny(isVerified?p.recommended_total_cny:p.reference_cny))+'<small> 起</small></div>'+
      '<div class="foreign-price">'+e(money(p.reference_price.amount,p.reference_price.currency))+' · '+e(p.reference_source)+'</div></div>'+
      '<button class="compare-button" type="button">选规格，比较 '+p.source_count+' 个渠道 <span aria-hidden="true">→</span></button>'+
      '<div class="data-time">'+(p.fetched_at?'采集 '+e(timeText(p.fetched_at)):e(timeText(null)))+' · 原币价与人民币参考价</div>'+
      '</div></div></article>';
  }).join('');
  const cards=[...gallery.querySelectorAll('.card')];
  cards.forEach(card=>{
    card.querySelector('.compare-button').onclick=()=>openProduct(card.dataset.id);
    card.querySelector('.image-button').onclick=()=>openProduct(card.dataset.id);
    const img=card.querySelector('img');img.onerror=()=>img.closest('.product-visual').classList.add('image-missing');
  });
  currentIndex=0;gallery.scrollTop=0;updatePosition(0,cards.length);
  observer=new IntersectionObserver(entries=>{
    if(viewMode!=='feed'||swipe||performance.now()<animationUntil)return;
    for(const entry of entries)if(entry.isIntersecting&&entry.intersectionRatio>.6){currentIndex=cards.indexOf(entry.target);updatePosition(currentIndex,cards.length);if(currentIndex>0)document.getElementById('scrollHint').classList.add('hidden')}
  },{root:gallery,threshold:[.6,.8]});cards.forEach(card=>observer.observe(card));
  positionHint();
  if(preserveId){const target=cards.find(c=>c.dataset.id===preserveId);if(target)gallery.scrollTop=target.offsetTop}
}
function updatePosition(index,total){document.getElementById('position').textContent=total?(index+1)+' / '+total:'0 / 0';document.getElementById('prev').disabled=!total||index===0;document.getElementById('next').disabled=!total||index>=total-1}
function positionHint(){const hint=document.getElementById('scrollHint');const visual=gallery.querySelector('.product-visual');if(matchMedia('(max-width:600px)').matches&&viewMode==='feed'&&visual){hint.style.top=(visual.getBoundingClientRect().bottom-42)+'px';hint.style.bottom='auto'}else{hint.style.top='';hint.style.bottom=''}}
function goTo(index){
  const cards=[...gallery.querySelectorAll('.card')];if(!cards.length)return;
  const nextIndex=Math.min(cards.length-1,Math.max(0,index)),target=cards[nextIndex].offsetTop,start=gallery.scrollTop;
  cancelAnimationFrame(animationFrame);gallery.classList.add('gesture-moving');currentIndex=nextIndex;updatePosition(currentIndex,cards.length);
  if(nextIndex>0)document.getElementById('scrollHint').classList.add('hidden');
  const duration=matchMedia('(prefers-reduced-motion:reduce)').matches?0:280,started=performance.now();animationUntil=started+duration;
  function animate(now){const progress=duration?Math.min(1,(now-started)/duration):1;gallery.scrollTop=start+(target-start)*(1-Math.pow(1-progress,3));if(progress<1){animationFrame=requestAnimationFrame(animate)}else{gallery.scrollTop=target;gallery.classList.remove('gesture-moving');animationUntil=0}}
  animationFrame=requestAnimationFrame(animate);
}
function move(direction){goTo(currentIndex+direction)}
function setView(mode,save=true){
  cancelAnimationFrame(animationFrame);swipe=null;animationUntil=0;gallery.classList.remove('gesture-moving');
  const active=gallery.querySelectorAll('.card')[currentIndex]?.dataset.id;
  viewMode=mode==='grid'?'grid':'feed';document.body.classList.toggle('grid-mode',viewMode==='grid');
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===viewMode)));
  if(save){try{localStorage.setItem('bikehuntView',viewMode)}catch{}}
  document.getElementById('scrollHint').classList.remove('hidden');render(active);
}
function clearSearch(){document.getElementById('q').value='';render();document.getElementById('q').focus()}
function tag(status,label){const style=status==='yes'?'ok':status==='no'?'no':'wait';const text=status==='yes'?'已核实':status==='no'?'不支持':'待核实';return '<span class="tag '+style+'">'+e(label)+' '+text+'</span>'}
function landedCostMarkup(compared){
  const landed=compared.landed_cost;
  const cost=(label,value,total=false)=>'<div'+(total?' class="total"':'')+'><dt>'+e(label)+'</dt><dd>'+e(value==null?'待确认':cny(value))+'</dd></div>';
  if(!landed)return '<dl class="costs">'+cost('人民币商品价',compared.product_cny)+cost('寄中国运费',compared.shipping_cny)+cost('税费',compared.tax_cny)+cost('已报价费用合计',compared.total_cny,true)+'</dl>';
  const components=landed.components||[],scenarios=landed.scenarios||[];
  const sources=[...(landed.evidence||[]),...components.flatMap(c=>c.evidence||[]),...scenarios.flatMap(s=>s.evidence||[])];
  const uniqueSources=[...new Map(sources.filter(s=>safeUrl(s.url)).map(s=>[s.url,s])).values()];
  const componentRows=components.map(c=>{
    const label=c.label+(c.status==='included'?'（已含，新增为零）':c.status==='policy_estimate'?'（政策参考）':'');
    const value=c.status==='unsupported'?'此渠道不直邮':c.cny==null?'待确认':cny(c.cny);
    return '<div><dt>'+e(label)+'</dt><dd>'+e(value)+'</dd></div>';
  }).join('');
  const scenariosMarkup=scenarios.map(s=>'<div class="summary-box"><h4>单件寄中国预算 · 条件估算</h4><div class="summary-price">'+e(cny(s.subtotal_cny))+'</div>'+
    '<p>商品 + 整单运费 + 条件税额的小计。实际报关路径未确认，未含待确认费用，不能视为完整到手价。</p>'+
    '<dl class="costs">'+cost('暂用商品价作为计税基数',s.tax_base_cny)+cost('服装税情景（'+Math.round(Number(s.rate)*100)+'%）',s.payable_tax_cny)+'</dl>'+
    '<p>'+e(s.waiver_applied?'此单件整票的情景应征税额不超过 50 元，暂按免征计算；海关审价及合单会改变结果。':'整票超过 50 元免征门槛时计全额税，不扣减 50 元。')+'</p></div>').join('');
  const originalShipping=components.find(c=>c.key==='shipping');
  return '<dl class="costs">'+componentRows+cost('已知费用小计（不含待确认项）',landed.known_subtotal_cny,true)+
    (compared.total_cny!=null?cost('已报价费用合计',compared.total_cny,true):'')+'</dl>'+
    (originalShipping?.original?'<div class="offer-note">运费原币：'+e(money(originalShipping.original.amount,originalShipping.original.currency))+(landed.shipping_scope==='order'?' / 单；单件下单计整单运费，合单不能逐件相加。':'；订单计费范围仍需核实。')+'</div>':'')+
    (landed.missing?.length?'<div class="offer-note">仍待确认：'+landed.missing.map(e).join('、')+'。未知费用没有按 0 元计入。</div>':'')+
    scenariosMarkup+
    '<details><summary>查看运税假设、原币与官方依据</summary>'+
    components.filter(c=>c.note).map(c=>'<p>'+e(c.label)+'：'+e(c.note)+'</p>').join('')+
    scenarios.flatMap(s=>s.assumptions||[]).concat(landed.notes||[]).map(note=>'<p>'+e(note)+'</p>').join('')+
    uniqueSources.map(source=>'<p><a target="_blank" rel="noopener noreferrer" href="'+e(safeUrl(source.url))+'">'+e(source.title)+'</a> · 核实 '+e(source.checked_on||'日期待确认')+'</p>').join('')+'</details>';
}
function inventoryVerified(offer,now=Date.now()){
  const timestamp=offer?.fetched_at;if(typeof timestamp!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp))return false;
  const day=timestamp.slice(0,10),dayTime=Date.parse(day);if(!Number.isFinite(dayTime)||new Date(dayTime).toISOString().slice(0,10)!==day)return false;
  const age=now-Date.parse(timestamp);return Number.isFinite(age)&&age>=0&&age<=3600000;
}
function offerAvailable(quote,now=Date.now()){const o=quote?.offer;if(!o||o.stock!=='in_stock'||o.collection_state==='retained'||!inventoryVerified(o,now))return false;const until=o.price_valid_until;return !until||/^\d{4}-\d{2}-\d{2}$/.test(until)&&Number.isFinite(Date.parse(until))&&new Date(until).toISOString().slice(0,10)===until&&until>=new Date(now).toISOString().slice(0,10);}
function inventoryLabel(offer,now=Date.now()){return offer.stock==='out_of_stock'?'已售罄':offer.collection_state==='retained'?'最近采集失败；库存待重新核实':offer.stock!=='in_stock'?'库存待核实':!inventoryVerified(offer,now)?'库存待核实（上次核实已超过一小时）':offerAvailable({offer},now)?'有库存':'报价有效期已结束；库存待重新核实'}
function merchantUrl(value){const url=safeUrl(value);return url.startsWith('https://')?url:''}
function referenceAvailable(quote){return !!quote?.offer&&!quote.reference_verifying&&quote.offer.stock!=='out_of_stock'&&!!merchantUrl(quote.offer.url)}
function referenceLinkMarkup(quote,label='去官网查看',className='go reference-exit'){
  if(!referenceAvailable(quote))return '';
  const o=quote.offer,key=o.offer_id+'|'+o.url;referenceOffers.set(key,quote);
  return '<a class="'+e(className)+'" data-reference-link="'+e(key)+'" target="_blank" rel="noopener noreferrer" href="'+e(merchantUrl(o.url))+'">'+label+'</a>';
}
function referenceOffersMarkup(detail){
  const quotes=detail.offers.filter(referenceAvailable);
  for(const quote of quotes){quote.reference_product_id=detail.product_id;quote.reference_variant_id=detail.variant_id;}
  if(!quotes.length)return '';
  return '<div class="reference-offers"><h4>查看官网商品页</h4><p class="spec-note">历史报价仅供参考，库存待核实。官网链接不代表所示尺码可购买，请在商家页面重新选择并核对尺码、颜色、价格和库存。</p>'+quotes.map(q=>'<div class="reference-channel"><span>'+e(q.offer.source_name)+'</span>'+referenceLinkMarkup(q)+'</div>').join('')+'</div>';
}
function offerMarkup(compared){
  const o=compared.offer;
  const available=offerAvailable(compared),stock=inventoryLabel(o),recommended=compared.eligible&&available;
  return '<div class="offer" data-source="'+e(o.source_code)+'"><div class="offer-top"><div class="source-name">'+e(o.source_name)+'</div><span class="tag '+(recommended?'ok':o.stock==='out_of_stock'?'no':'wait')+'">'+(recommended?'推荐渠道':stock)+'</span></div>'+
    '<div class="source-logistics">'+e(o.sales_region||'渠道报价')+' · 发货地：'+e(o.dispatch_origin||'尚待官方核实')+'</div>'+
    (o.purchase_requirements?.length?'<div class="offer-note">'+o.purchase_requirements.map(e).join(' · ')+'</div>':'')+
    '<div class="price">'+e(money(o.price.amount,o.price.currency))+' <span>≈ '+e(cny(compared.product_cny))+'</span></div>'+
    landedCostMarkup(compared)+
    '<div class="checks">'+tag(o.shipping_to_china.status,'直邮中国')+(o.china_issued_card.status==='no'?tag('no','中国发行卡'):o.accepted_card_networks?.length?'<span class="tag ok">支持 '+e(o.accepted_card_networks.join(' / '))+'</span>':tag(o.china_issued_card.status,'银行卡支付'))+'</div>'+
    (o.accepted_card_networks?.length?'<div class="offer-note">中国发行、具备境外支付功能的对应卡种可按此条件使用，招商银行等发卡行均按卡种核对。付款结果以银行授权为准。</div>':'')+
    (compared.reasons.length?'<div class="offer-note">'+compared.reasons.map(e).join(' · ')+'</div>':'')+
    '<div class="source-time">'+(o.fetched_at?'采集 '+e(timeText(o.fetched_at)):e(timeText(null)))+'</div>'+
    '<button class="go guide-start" type="button" data-offer="'+e(o.offer_id)+'" '+(!offerAvailable(compared)?'disabled':'')+'>按中文步骤海淘 <span>→</span></button>'+
    (!available?referenceLinkMarkup(compared):'')+
    '<details><summary>来源与核实依据</summary><p>'+e(o.identity_evidence)+'</p>'+
    [o.shipping_to_china,o.china_issued_card].map(check=>'<p>'+e(check.note)+(safeUrl(check.url)?' <a target="_blank" rel="noopener noreferrer" href="'+e(safeUrl(check.url))+'">查看依据</a>':'')+'</p>').join('')+'</details></div>';
}
// Status-only updates preserve existing DOM nodes and selected specifications.
// An exact bound content identity is required before advancing any copied clock.
function updateVerifiedOfferMetadata(compared,observations){
  const offer=compared?.offer,observation=observations?.[offer?.offer_id];
  if(!observation||!offer.verification_identity||offer.verification_identity!==observation.content_sha256||
    offer.collection_state!==observation.collection_state||offer.stock!==observation.stock||
    compared.eligible!==observation.eligible||JSON.stringify(compared.reasons)!==JSON.stringify(observation.reasons)||
    !inventoryVerified(offer)||!inventoryVerified({...offer,fetched_at:observation.fetched_at})||
    Date.parse(observation.fetched_at)<Date.parse(offer.fetched_at))return false;
  offer.fetched_at=observation.fetched_at;
  for(const component of compared.landed_cost?.components||[])if(component.key==='product')
    for(const evidence of component.evidence||[])evidence.checked_on=observation.fetched_at?.slice(0,10)||null;
  return true;
}
function updateVerifiedFxMetadata(snapshot,observation){
  if(snapshot&&observation&&snapshot.snapshot_id===observation.snapshot_id&&snapshot.stale===observation.stale&&
    Number.isFinite(Date.parse(observation.fetched_at))&&Date.parse(observation.fetched_at)<=Date.now()&&
    (!snapshot.fetched_at||Date.parse(observation.fetched_at)>=Date.parse(snapshot.fetched_at)))snapshot.fetched_at=observation.fetched_at;
}
function updateVerifiedDetailMetadata(detail,verification){
  if(!detail)return;
  for(const compared of detail.offers||[])updateVerifiedOfferMetadata(compared,verification.offers);
  updateVerifiedFxMetadata(detail.fx,verification.fx);
}
function updateGalleryVerificationMetadata(verification){
  if(!verification?.offers)return;
  for(const card of items){
    const observation=verification.offers[card.reference_offer_id];
    if(observation&&card.reference_verification_identity&&card.reference_verification_identity===observation.content_sha256&&
      card.reference_collection_state===observation.collection_state&&card.reference_stock===observation.stock&&
      inventoryVerified(card)&&inventoryVerified({...card,fetched_at:observation.fetched_at})&&
      Date.parse(observation.fetched_at)>=Date.parse(card.fetched_at))card.fetched_at=observation.fetched_at;
  }
  updateVerifiedDetailMetadata(currentProduct,verification);
  updateVerifiedFxMetadata(fx,verification.fx);updateFxLabel();
  const byId=new Map(items.map(card=>[card.product_id,card]));
  for(const node of gallery.querySelectorAll('.card')){
    const card=byId.get(node.dataset.id),label=node.querySelector('.data-time');
    if(card&&label)label.textContent=(card.fetched_at?'采集 '+timeText(card.fetched_at):timeText(null))+' · 原币价与人民币参考价';
  }
  for(const node of document.querySelectorAll('.offer')){
    const id=node.querySelector('[data-offer]')?.dataset.offer,quote=currentProduct?.offers.find(q=>q.offer.offer_id===id),label=node.querySelector('.source-time');
    if(quote&&label)label.textContent=quote.offer.fetched_at?'采集 '+timeText(quote.offer.fetched_at):timeText(null);
  }
}
if(window.BIKEHUNT_PAGES)window.addEventListener('bikehunt-verification',event=>updateGalleryVerificationMetadata(event.detail));
async function loadDetail(id,variantId=null){
  const sequence=++detailSequence;
  const body=document.getElementById('sheetBody');body.innerHTML='<div class="loading" role="status">正在读取同款报价…</div>';
  try{
    const detail=await getJson('/api/catalog/'+encodeURIComponent(id)+(variantId?'?variant_id='+encodeURIComponent(variantId):''));
    if(sequence!==detailSequence||!sheet.classList.contains('open'))return;
    currentProduct=detail;for(const quote of detail.offers){quote.reference_product_id=detail.product_id;quote.reference_variant_id=detail.variant_id;}
    document.getElementById('sheetImg').style.display='';document.getElementById('sheetImg').src=safeUrl(detail.image);document.getElementById('sheetBrand').textContent=detail.identity.brand;
    document.getElementById('sheetName').textContent=detail.name_zh||detail.name;
    const best=detail.offers.find(o=>o.offer.offer_id===detail.recommended_offer_id&&offerAvailable(o));
    const inventoryExpired=detail.offers.some(q=>q.offer.stock==='in_stock'&&!inventoryVerified(q.offer));
    const summary=best?'<div class="summary-box verified"><h4>公开条件与费用已齐的最低预计成本</h4><div class="summary-price">'+e(cny(best.total_cny))+'</div><p>'+e(best.offer.source_name)+' · 商品、运费与税费已计入，银行卡仍需实际授权</p></div>':'<div class="summary-box"><h4>已找到报价，购买条件仍需核实</h4><p>运费、税费或直邮及支付条件未齐，暂时无法确认最低到手价。各渠道提供已保存的中文规则和分步指引。</p></div>';
    const available=detail.variants.filter(v=>v.in_stock&&v.size&&(v.variant_id!==detail.variant_id||detail.offers.some(q=>offerAvailable(q))));
    const selected=variantId&&available.some(v=>v.variant_id===variantId);
    const colors=detail.colors?.filter(c=>c.in_stock)||[];
    const variants=(colors.length>1?'<div class="variant-bar"><label for="colorChoice">现货颜色</label><select id="colorChoice">'+colors.map(c=>'<option value="'+e(c.product_id)+'" '+(c.product_id===id?'selected':'')+'>'+e(c.color)+'</option>').join('')+'</select></div>':'')+'<div class="variant-bar"><label for="variant">先选现货尺码</label><select id="variant"><option value="">请选择剩余现货规格</option>'+available.map(v=>'<option value="'+e(v.variant_id)+'" '+(selected&&v.variant_id===detail.variant_id?'selected':'')+'>'+e(v.size)+' · '+v.source_count+' 个渠道 · 商品参考 '+e(cny(v.product_cny_from))+'</option>').join('')+'</select></div><div class="size-choices">'+available.map(v=>'<button type="button" data-variant="'+e(v.variant_id)+'" aria-pressed="'+Boolean(selected&&v.variant_id===detail.variant_id)+'">'+e(v.size)+'</button>').join('')+'</div><p class="spec-note">颜色：'+e(detail.identity.color||'参照当前商品图，原站核对颜色')+'。只列最近一小时内核实有库存的尺码；售罄、核实过期和未知库存不作为现货尺码展示；可从下方官网链接核对当前情况。</p>';
    body.innerHTML=variants+'<div id="fitReference"></div>'+
      (detail.identity.mpn?'<div class="model-code">制造商型号 '+e(detail.identity.mpn)+(detail.identity.color?' · '+e(detail.identity.color):'')+'</div>':'')+
      (selected?summary+'<div class="offers"><h4>已选 '+e(detail.identity.size)+' · '+e(detail.identity.color||'当前款')+' · '+detail.offers.length+' 条同规格报价</h4>'+detail.offers.map(offerMarkup).join('')+'</div>':'<div class="summary-box"><h4>'+(available.length?'选择上方尺码后，显示对应价格':inventoryExpired?'库存待核实':'尚未取得可选的现货规格')+'</h4><p>'+(available.length?'不同尺码的库存与价格可能不同，先选规格再比较。':inventoryExpired?'历史价格仍可参考；上次库存核实已超过一小时，尺码待核实。可前往官网商品页查看当前情况。':'当前报价可供参考；未知库存不会作为现货尺码显示。可前往官网商品页自行核对。')+'</p></div>')+
      (!selected?referenceOffersMarkup(detail):'')+
      '<div class="service-note">汇率日期 '+e(detail.fx.rate_date||'待获取')+(detail.fx.stale?' · 使用过期缓存':'')+'。人民币金额为参考，信用卡入账及手续费以发卡行为准。<br>BikeHunt 只提供信息与外链，付款、订单及售后由第三方网站负责。</div>';
    document.getElementById('variant').onchange=event=>loadDetail(id,event.target.value||null);
    const colorSelect=document.getElementById('colorChoice');if(colorSelect)colorSelect.onchange=event=>loadDetail(event.target.value,null);
    body.querySelectorAll('[data-variant]').forEach(button=>button.onclick=()=>loadDetail(id,button.dataset.variant));
    body.querySelectorAll('.guide-start').forEach(button=>button.onclick=()=>startGuide(detail,button.dataset.offer));
    refreshFitReference(detail,sequence);
  }catch(error){if(sequence!==detailSequence)return;body.innerHTML='<div class="empty"><strong>报价暂时无法读取</strong>'+e(error.message)+'<br><button id="retryDetail" type="button">重试</button></div>';document.getElementById('retryDetail').onclick=()=>loadDetail(id,variantId)}
}
function openProduct(id){
  if(items.find(p=>p.product_id===id)?.stock_state==='out_of_stock')return;
  lastFocus=document.activeElement;gallery.inert=true;sheet.inert=false;
  document.getElementById('sheetImg').style.display='';
  const item=items.find(p=>p.product_id===id);if(item){document.getElementById('sheetName').textContent=item.name;document.getElementById('sheetBrand').textContent=item.brand;document.getElementById('sheetImg').src=safeUrl(item.image)}
  document.getElementById('overlay').classList.add('open');sheet.classList.add('open');sheet.setAttribute('aria-hidden','false');document.getElementById('close').focus();loadDetail(id);
}
function closeSheet(){referenceOffers.clear();if(typeof messagesOpen!=='undefined')messagesOpen=false;if(typeof guideContext!=='undefined')guideContext=null;++detailSequence;sheet.classList.remove('open');sheet.setAttribute('aria-hidden','true');sheet.inert=true;document.getElementById('overlay').classList.remove('open');gallery.inert=false;document.getElementById('directoryPage').inert=false;currentProduct=null;lastFocus?.focus()}
async function init(){
  gallery.innerHTML='<div class="empty loading" role="status"><strong>正在整理骑行好价</strong>读取商品与人民币参考价…</div>';
  try{
    const data=await getJson('/api/catalog');items=data.items;fx=data.fx;sourceCount=data.source_count;
    updateFxLabel();
    try{viewMode=localStorage.getItem('bikehuntView')||'feed'}catch{viewMode='feed'}setView(viewMode,false);
    document.getElementById('sourceCount').textContent=data.source_count+' 个已采集报价源';
  }catch(error){gallery.innerHTML='<div class="empty"><strong>商品暂时无法加载</strong>'+e(error.message)+'<br><button id="retry" type="button">重新加载</button></div>';document.getElementById('retry').onclick=init}
}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
document.getElementById('q').addEventListener('input',()=>render());document.getElementById('clear').onclick=clearSearch;
document.getElementById('prev').onclick=()=>move(-1);document.getElementById('next').onclick=()=>move(1);
document.getElementById('close').onclick=closeSheet;document.getElementById('overlay').onclick=closeSheet;
window.addEventListener('resize',positionHint);
gallery.addEventListener('touchstart',event=>{
  if(viewMode!=='feed'||event.touches.length!==1||sheet.classList.contains('open'))return;
  cancelAnimationFrame(animationFrame);animationUntil=0;
  const cards=[...gallery.querySelectorAll('.card')];if(!cards.length)return;
  currentIndex=Math.min(cards.length-1,Math.max(0,Math.round(gallery.scrollTop/gallery.clientHeight)));
  swipe={y:event.touches[0].clientY,x:event.touches[0].clientX,time:performance.now(),index:currentIndex,top:cards[currentIndex].offsetTop,delta:0,dragged:false};
},{passive:true});
gallery.addEventListener('touchmove',event=>{
  if(!swipe||event.touches.length!==1)return;
  const dy=swipe.y-event.touches[0].clientY,dx=swipe.x-event.touches[0].clientX;
  if(!swipe.dragged&&Math.abs(dx)>Math.abs(dy)+12){swipe=null;return}
  if(Math.abs(dy)<6&&!swipe.dragged)return;
  event.preventDefault();swipe.dragged=true;swipe.delta=dy;gallery.classList.add('gesture-moving');
  gallery.scrollTop=swipe.top+Math.max(-gallery.clientHeight*.9,Math.min(gallery.clientHeight*.9,dy));
},{passive:false});
function finishSwipe(cancelled=false){
  if(!swipe)return;const gesture=swipe;swipe=null;
  if(!gesture.dragged)return;
  const distance=Math.abs(gesture.delta),speed=distance/Math.max(1,performance.now()-gesture.time);
  const change=!cancelled&&(distance>=Math.min(70,gallery.clientHeight*.12)||(distance>18&&speed>.35));
  goTo(gesture.index+(change?(gesture.delta>0?1:-1):0));
}
gallery.addEventListener('touchend',event=>{if(swipe?.dragged)event.preventDefault();finishSwipe()},{passive:false});
gallery.addEventListener('touchcancel',()=>finishSwipe(true),{passive:true});
gallery.addEventListener('wheel',event=>{if(viewMode!=='feed'||sheet.classList.contains('open')||Math.abs(event.deltaY)<8)return;event.preventDefault();clearTimeout(wheelUnlockTimer);wheelUnlockTimer=setTimeout(()=>{wheelLocked=false},200);if(wheelLocked)return;wheelLocked=true;move(event.deltaY>0?1:-1)},{passive:false});
document.addEventListener('keydown',event=>{
  if(sheet.classList.contains('open')){
    if(event.key==='Escape'){closeSheet();return}
    if(event.key==='Tab'){const focusable=[...sheet.querySelectorAll('button,a,select,summary,input')].filter(x=>!x.disabled&&x.getClientRects().length);const first=focusable[0],last=focusable.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}}return;
  }
  if(['INPUT','SELECT','TEXTAREA','BUTTON','A'].includes(event.target.tagName)||viewMode!=='feed')return;
  if(['ArrowDown','PageDown','ArrowUp','PageUp'].includes(event.key)){event.preventDefault();move(['ArrowDown','PageDown'].includes(event.key)?1:-1)}
});
init();
