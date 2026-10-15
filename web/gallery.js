'use strict';
let items=[],fx={},currentIndex=0,currentProduct=null,detailSequence=0,lastFocus=null,sourceCount=0;
let observer=null,viewMode='feed',currentBundleSelection=null;
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
function featuredBrowse(){return !activeSource&&!document.getElementById('q').value.trim()}
function visibleItems(){const q=document.getElementById('q').value.trim().toLowerCase().split(/\s+/).filter(Boolean);return items.filter(p=>p.stock_state!=='out_of_stock'&&profileMatches(p)&&(!featuredBrowse()||featuredDeal(p))&&(activeCategory==='all'||p.category===activeCategory)&&(!activeSource||p.source_codes?.includes(activeSource))&&q.every(t=>(p.brand+' '+p.name+' '+(p.name_zh||'')+' '+(p.color||'')).toLowerCase().includes(t)))}
function render(preserveId=null){
  if(observer)observer.disconnect();
  if(typeof updateBrowseLabel==='function'&&activeTab==='products')updateBrowseLabel();
  const list=visibleItems();
  document.getElementById('count').textContent=list.length+' 件商品';
  document.getElementById('sourceCount').textContent=sourceCount+' 个已采集报价源';
  if(!list.length){gallery.innerHTML=featuredBrowse()?'<div class="empty"><strong>暂无符合条件的已核实折扣</strong>精选只展示最近一小时内核实有货、商家同规格原价高于现价的商品。<br>可搜索商品，或前往品牌官网、世巡车队浏览完整目录。</div>':'<div class="empty"><strong>没有找到这个商品</strong>试试商品名称或品牌。<br><button type="button" id="resetSearch">清空搜索</button></div>';const reset=document.getElementById('resetSearch');if(reset)reset.onclick=clearSearch;updatePosition(0,0);return}
  gallery.innerHTML=list.map((p,i)=>{
    const deal=featuredDeal(p);
    const stockVerified=p.stock_state==='in_stock'&&inventoryVerified(p)&&p.reference_collection_state!=='retained';
    const isVerified=stockVerified&&p.recommended_total_cny!=null;
    const expired=['库存核实已过期','库存待核实'].includes(p.status)||p.stock_state==='in_stock'&&!stockVerified;
    const sold=p.stock_state==='out_of_stock';
    return '<article class="card'+(deal?' has-deal':'')+'" data-id="'+e(p.product_id)+'" aria-label="商品 '+(i+1)+'：'+e(p.name)+'"><div class="card-inner">'+
      '<div class="product-visual">'+imageMarkup(p.image,p.name,i)+
      (deal?'<span class="discount">'+e(discountLabel(p))+'</span>':'')+
      '<span class="slide-index">'+String(i+1).padStart(2,'0')+' / '+String(list.length).padStart(2,'0')+'</span></div>'+
      '<div class="product-info"><div class="brand">'+e(p.brand)+'</div><h2>'+e(p.name_zh||p.name)+'</h2><div class="original-name">'+e(p.name)+'</div>'+
      '<div class="product-meta"><span>'+p.source_count+' 个渠道</span><span>'+(deal?e(catalogSizeLabel(p,true)):stockVerified&&p.available_sizes?.length?e(catalogSizeLabel(p,false)):expired?'库存待核实':p.variant_count+' 个规格 · 库存待确认')+'</span>'+
      (sold?'<span class="sold">所示报价已售罄</span>':'')+'</div>'+
      '<div class="buyline"><div class="price-label">'+(deal?'已核实折扣 · 商品价，不含运税':sold?'所示报价已售罄':isVerified?'已核实商品参考价 · 先选规格':stockVerified&&p.available_sizes?.length?'现货商品参考起价 · 先选规格':expired?'历史参考价 · 库存待核实':'参考起价 · 库存待核实')+'</div>'+
      '<div class="best-price">'+e(cny(p.reference_cny))+(deal?'':'<small> 起</small>')+'</div>'+
      '<div class="foreign-price">'+(deal?'<span class="original-price">商家原价 <s>'+e(money(p.reference_original_price.amount,p.reference_original_price.currency))+'</s></span> · 现价 ':'')+e(money(p.reference_price.amount,p.reference_price.currency))+' · '+e(p.reference_source)+'</div>'+
      (deal?'<div class="deal-spec">未取得折扣结束时间</div>':'')+'</div>'+
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
  const scenariosMarkup=scenarios.map((s,index)=>{
    const shipping=components.find(c=>c.key==='shipping'),clearance=components.find(c=>c.key==='clearance');
    const included=s.included_components?.length?s.included_components:['product','tax',...(shipping?.cny!=null?['shipping']:[]),...(clearance?.cny!=null?['clearance']:[])];
    const extraLabels=[...(included.includes('shipping')?['运费']:[]),...(included.includes('clearance')?['手续费']:[])];
    const subtotalLabel='商品 + 预估税'+(extraLabels.length?' + '+extraLabels.join(' + '):'')+'小计';
    const unknownLabels=[...(shipping?.cny==null?['寄中国运费']:[]),...(clearance?.cny==null?['清关／代垫手续费']:[])];
    const budgetId='shipping-budget-'+encodeURIComponent(compared.offer?.offer_id||'offer')+'-'+index;
    const budgetMarkup=shipping?.cny==null&&shipping?.status!=='unsupported'&&!included.includes('shipping')?
      '<div class="shipping-budget" data-shipping-budget-box data-subtotal="'+e(s.subtotal_cny)+'">'+
      '<label for="'+e(budgetId)+'">运费预算（选填，人民币）</label><input id="'+e(budgetId)+'" data-shipping-budget type="text" inputmode="decimal" autocomplete="off" placeholder="留空表示未知" aria-describedby="'+e(budgetId)+'-help '+e(budgetId)+'-error" aria-invalid="false">'+
      '<p id="'+e(budgetId)+'-help" class="budget-help">填写你自己的运费预算，不是商家报价；不会改变上方待确认运费。支持 0–100,000 元，最多两位小数。</p>'+
      '<p id="'+e(budgetId)+'-error" class="budget-error" data-budget-error role="alert" hidden></p>'+
      '<div data-budget-result role="status" aria-live="polite" hidden><dl class="costs"><div><dt>自填运费预算</dt><dd data-budget-shipping></dd></div><div class="total"><dt>加上自填预算后的小计</dt><dd data-budget-subtotal></dd></div></dl>'+
      '<p>仅在上述预估小计上加自填运费；'+(clearance?.cny==null?'未知清关／代垫手续费仍需另计。':'已知清关／代垫手续费已含在上述小计中。')+'不是商家报价，也不是完整到手价。</p><p data-budget-zero hidden>你填写了 0 元，仅是自己的预算假设，不代表商家免邮。</p></div></div>':'';
    return '<section class="summary-box cost-estimate" aria-label="条件费用预估"><h4>费用预估 · 服装个人寄递情景</h4>'+
      '<p>若海关按个人寄递服装征税，暂用商品价估算 '+Math.round(Number(s.rate)*100)+'% 税费。</p>'+
      '<dl class="costs">'+cost('商品参考价',s.tax_base_cny)+cost('预估进口税（条件估算）',s.payable_tax_cny)+
      cost('寄中国运费'+(shipping?.status==='policy_estimate'?'（政策参考）':''),shipping?.cny)+cost('清关／代垫手续费',clearance?.cny)+cost(subtotalLabel,s.subtotal_cny,true)+'</dl>'+
      '<p>'+(unknownLabels.length?'还需另加待确认的'+unknownLabels.map(e).join('、')+'。':'')+'实际报关路径未确认，不能视为完整到手价。</p>'+
      (!s.china_delivery_confirmed?'<p class="offer-note">中国大陆配送仍待核实；税费预估不代表已确认可寄中国。</p>':'')+
      '<p>'+e(s.waiver_applied?'此单件整票的情景应征税额不超过 50 元，暂按免征计算；海关审价及合单会改变结果。':'整票超过 50 元免征门槛时计全额税，不扣减 50 元。')+'</p>'+budgetMarkup+'</section>';
  }).join('');
  const originalShipping=components.find(c=>c.key==='shipping');
  return scenariosMarkup+(scenarios.length?'<details><summary>查看已报价费用（与预估分开）</summary>':'')+'<dl class="costs">'+componentRows+cost('已知费用小计（不含待确认项）',landed.known_subtotal_cny,true)+
    (compared.total_cny!=null?cost('已报价费用合计',compared.total_cny,true):'')+'</dl>'+(scenarios.length?'</details>':'')+
    (originalShipping?.original?'<div class="offer-note">运费原币：'+e(money(originalShipping.original.amount,originalShipping.original.currency))+(landed.shipping_scope==='order'?' / 单；单件下单计整单运费，合单不能逐件相加。':'；订单计费范围仍需核实。')+'</div>':'')+
    (landed.missing?.length?'<div class="offer-note">仍待确认：'+landed.missing.map(e).join('、')+'。未知费用没有按 0 元计入。</div>':'')+
    '<details><summary>查看运税假设、原币与官方依据</summary>'+
    components.filter(c=>c.note).map(c=>'<p>'+e(c.label)+'：'+e(c.note)+'</p>').join('')+
    scenarios.flatMap(s=>s.assumptions||[]).concat(landed.notes||[]).map(note=>'<p>'+e(note)+'</p>').join('')+
    uniqueSources.map(source=>'<p><a target="_blank" rel="noopener noreferrer" href="'+e(safeUrl(source.url))+'">'+e(source.title)+'</a> · 核实 '+e(source.checked_on||'日期待确认')+'</p>').join('')+'</details>';
}
function shippingBudgetPreview(raw,base){
  const value=String(raw??'').trim();
  if(!value)return {status:'empty'};
  const invalid={status:'invalid',error:'请输入 0–100,000 元的数字，最多两位小数；留空可取消预算。'};
  // A blank field is unknown. Exponents, signs, non-finite values and excessive
  // amounts are rejected rather than coerced into zero or an apparent quote.
  if(!/^\d{1,6}(?:\.\d{1,2})?$/.test(value))return invalid;
  const amount=Number(value),baseAmount=Number(base);
  if(!Number.isFinite(amount)||amount<0||amount>100000)return invalid;
  const cents=Math.round(amount*100),baseCents=Math.round(baseAmount*100);
  if(base==null||base===''||!Number.isFinite(baseAmount)||baseAmount<0||!Number.isSafeInteger(baseCents)||!Number.isSafeInteger(baseCents+cents))return {status:'invalid',error:'当前预估小计不可用，请重新打开商品。'};
  return {status:'valid',shipping_cny:cents/100,subtotal_cny:(baseCents+cents)/100};
}
function updateShippingBudget(event){
  const input=event.target;if(!input?.matches?.('[data-shipping-budget]'))return;
  const box=input.closest('[data-shipping-budget-box]');if(!box)return;
  const preview=shippingBudgetPreview(input.value,box.dataset.subtotal),error=box.querySelector('[data-budget-error]'),result=box.querySelector('[data-budget-result]');
  input.setAttribute('aria-invalid',String(preview.status==='invalid'));
  error.textContent=preview.error||'';error.hidden=preview.status!=='invalid';
  result.hidden=preview.status!=='valid';
  box.querySelector('[data-budget-shipping]').textContent=preview.status==='valid'?cny(preview.shipping_cny):'';
  box.querySelector('[data-budget-subtotal]').textContent=preview.status==='valid'?cny(preview.subtotal_cny):'';
  box.querySelector('[data-budget-zero]').hidden=preview.status!=='valid'||preview.shipping_cny!==0;
}
function inventoryVerified(offer,now=Date.now()){
  const timestamp=offer?.fetched_at;if(typeof timestamp!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp))return false;
  const day=timestamp.slice(0,10),dayTime=Date.parse(day);if(!Number.isFinite(dayTime)||new Date(dayTime).toISOString().slice(0,10)!==day)return false;
  const age=now-Date.parse(timestamp);return Number.isFinite(age)&&age>=0&&age<=3600000;
}
function offerAvailable(quote,now=Date.now()){if(typeof bundleQuoteAllowed==='function'&&!bundleQuoteAllowed(quote))return false;const o=quote?.offer;if(!o||o.stock!=='in_stock'||o.collection_state==='retained'||!inventoryVerified(o,now))return false;const until=o.price_valid_until;return !until||/^\d{4}-\d{2}-\d{2}$/.test(until)&&Number.isFinite(Date.parse(until))&&new Date(until).toISOString().slice(0,10)===until&&until>=new Date(now).toISOString().slice(0,10);}
function inventoryLabel(offer,now=Date.now()){return offer.stock==='out_of_stock'?'已售罄':offer.collection_state==='retained'?'最近采集失败；库存待重新核实':offer.stock!=='in_stock'?'库存待核实':!inventoryVerified(offer,now)?'库存待核实（上次核实已超过一小时）':offerAvailable({offer},now)?'有库存':'报价有效期已结束；库存待重新核实'}
function featuredDeal(card,now=Date.now()){
  const current=card.reference_price,original=card.reference_original_price;
  return card.stock_state==='in_stock'&&card.reference_stock==='in_stock'&&card.reference_collection_state==='current'&&
    card.reference_data_kind==='live_snapshot'&&typeof card.reference_offer_id==='string'&&!!card.reference_offer_id&&
    typeof card.reference_variant_id==='string'&&!!card.reference_variant_id&&
    !!current&&!!original&&/^[A-Z]{3}$/.test(current.currency)&&current.currency===original.currency&&
    Number.isFinite(Number(current.amount))&&Number.isFinite(Number(original.amount))&&Number(current.amount)>0&&Number(original.amount)>Number(current.amount)&&
    offerAvailable({offer:{stock:card.reference_stock,collection_state:card.reference_collection_state,fetched_at:card.fetched_at,price_valid_until:card.reference_price_valid_until}},now);
}
function discountLabel(card){const percent=(1-Number(card.reference_price.amount)/Number(card.reference_original_price.amount))*100;return percent<1?'优惠不足 1%':percent>=99.95?'优惠超过 99.9%':'−'+Number(percent.toFixed(1))+'%'}
function merchantUrl(value){const url=safeUrl(value);return url.startsWith('https://')?url:''}
function referenceAvailable(quote){if(typeof bundleQuoteAllowed==='function'&&!bundleQuoteAllowed(quote))return false;return !!quote?.offer&&!quote.reference_verifying&&quote.offer.stock!=='out_of_stock'&&!!merchantUrl(quote.offer.url)}
function referenceLinkMarkup(quote,label='比较路线并核实库存',className='go reference-exit'){
  if(!referenceAvailable(quote))return '';
  const o=quote.offer,key=o.offer_id+'|'+o.url;referenceOffers.set(key,quote);
  return '<a class="'+e(className)+'" data-reference-link="'+e(key)+'" target="_self" rel="noopener noreferrer" href="'+e(merchantUrl(o.url))+'">'+label+'</a>';
}
function referenceOffersMarkup(detail){
  const quotes=detail.offers.filter(referenceAvailable);
  for(const quote of quotes){quote.reference_product_id=detail.product_id;quote.reference_variant_id=detail.variant_id;}
  if(!quotes.length)return '';
  return '<div class="reference-offers"><h4>库存待核实的报价参考</h4><p class="spec-note">历史报价仅供参考，库存待核实。官网链接不代表所示尺码可购买，请在商家页面重新选择并核对尺码、颜色、价格和库存。</p>'+quotes.map(q=>'<div class="reference-channel"><span>'+e(q.offer.source_name)+'</span>'+(typeof paymentFeasibilityMarkup==='function'?paymentFeasibilityMarkup(q.offer):'')+referenceLinkMarkup(q)+'</div>').join('')+'</div>';
}
function offerMarkup(compared){
  const o=compared.offer;
  const available=offerAvailable(compared),stock=inventoryLabel(o),recommended=compared.eligible&&available;
  return '<div class="offer" data-source="'+e(o.source_code)+'"><div class="offer-top"><div class="source-name">'+e(o.source_name)+'</div><span class="tag '+(recommended?'ok':o.stock==='out_of_stock'?'no':'wait')+'">'+stock+'</span></div>'+
    '<div class="source-logistics">'+e(o.sales_region||'渠道报价')+' · 发货地：'+e(o.dispatch_origin||'尚待官方核实')+'</div>'+
    (o.purchase_requirements?.length?'<div class="offer-note">'+o.purchase_requirements.map(e).join(' · ')+'</div>':'')+
    '<div class="price">'+e(money(o.price.amount,o.price.currency))+' <span>≈ '+e(cny(compared.product_cny))+'</span></div>'+
    '<p class="offer-note">先比较运输路线，再核对该路线的费用。未知运费、税费和银行卡费用不按 0 计算。</p>'+ 
    (typeof paymentFeasibilityMarkup==='function'?paymentFeasibilityMarkup(o):'')+
    (compared.reasons.length?'<div class="offer-note">'+compared.reasons.map(e).join(' · ')+'</div>':'')+
    '<div class="source-time">'+(o.fetched_at?'采集 '+e(timeText(o.fetched_at)):e(timeText(null)))+'</div>'+
    '<button class="go guide-start" type="button" data-offer="'+e(o.offer_id)+'" '+(!offerAvailable(compared)?'disabled':'')+'>比较运输路线 <span>→</span></button>'+
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
function detailSelectorVisible(){return !!(document.getElementById('variant')||document.getElementById('bundleChoices'))}
function detailSelectionId(){return document.getElementById('variant')?.value||currentBundleSelection?.variantId||null}
function detailQuoteIdentity(detail){return JSON.stringify((detail?.offers||[]).map(q=>[q.offer.offer_id,q.offer.source_code,q.offer.url,q.offer.identity?.size,q.offer.price?.amount,q.offer.price?.currency,q.offer.stock,q.offer.collection_state,q.offer.verification_identity||null]))}
function refreshOpenProductDetail(events=[]){
  if(!currentProduct||!detailSelectorVisible())return;
  recordBundleQuoteChanges(currentProduct,events);
  const selection=currentBundleSelection?.productId===currentProduct.product_id?currentBundleSelection.selection:null;
  const observedChange=events.some(event=>event.recovered_history!==true&&currentProduct.offers.some(q=>event.offer_id===q.offer.offer_id&&(event.stock==='out_of_stock'||event.new_price!=null&&String(event.new_price)!==String(q.offer.price?.amount)||event.currency&&event.currency!==q.offer.price?.currency)));
  const selectedId=detailSelectionId();
  return loadDetail(currentProduct.product_id,selectedId||(selection?currentProduct.variant_id:null),{bundleSelection:selection,preservePartial:!!selection&&!selectedId,refresh:true,forceReset:observedChange});
}
async function recheckBundleQuotes(){
  if(!currentProduct||!document.getElementById('bundleChoices'))return;
  const id=currentProduct.product_id,selection=currentBundleSelection?.selection||{},selectedId=detailSelectionId(),sequence=++detailSequence;
  const pending=[...bundleQuoteGuards().values()].filter(guard=>guard.productId===id&&!guard.confirmed);
  document.getElementById('sheetBody').innerHTML='<p class="loading" role="status">正在重新核对变化的组合…</p>';
  await Promise.all([...new Set(pending.map(guard=>guard.variantId))].map(async variantId=>{
    try{const detail=await getJson('/api/catalog/'+encodeURIComponent(id)+'?variant_id='+encodeURIComponent(variantId));
      if(sequence!==detailSequence||!sheet.classList.contains('open')||detail.product_id!==id||detail.variant_id!==variantId)return;
      observeBundleDetail(detail);
    }catch{/* Keep the exact offer fenced until it can actually be verified. */}
  }));
  if(sequence!==detailSequence||!sheet.classList.contains('open'))return;
  return loadDetail(id,selectedId,{bundleSelection:selection,refresh:true,message:'已重新读取当前报价；仍未同步的组合继续停用。',focusId:'bundle-jersey'});
}
async function loadDetail(id,variantId=null,options={}){
  if(typeof cancelPurchaseContext==='function')cancelPurchaseContext();
  const previous=currentProduct?.product_id===id?currentProduct:null,sequence=++detailSequence;
  const body=document.getElementById('sheetBody');body.innerHTML='<div class="loading" role="status">正在读取同款报价…</div>';
  try{
    const detail=await getJson('/api/catalog/'+encodeURIComponent(id)+(variantId?'?variant_id='+encodeURIComponent(variantId):''));
    if(sequence!==detailSequence||!sheet.classList.contains('open'))return;
    if(detail.product_id!==id||variantId&&detail.variant_id!==variantId)throw Error('所选规格已变化，请重新选择商品');
    const resetBundle=!!bundleVariantModel(detail)&&options.refresh&&!options.preservePartial&&variantId&&(options.forceReset||previous&&detailQuoteIdentity(previous)!==detailQuoteIdentity(detail));
    if(resetBundle){const parts=parseBundleSize(detail.identity.size)||options.bundleSelection||{};options={...options,bundleSelection:{jersey:parts.jersey,bib:parts.bib},message:'所选组合的价格或库存已变化，请重新选择袜子，确认最新报价。'};variantId=null;}
    renderProductDetail(detail,options.preservePartial?null:variantId,sequence,options);
    if(options.focusId)document.getElementById(options.focusId)?.focus();
  }catch(error){if(sequence!==detailSequence)return;currentBundleSelection=null;body.innerHTML='<div class="empty"><strong>报价暂时无法读取</strong>'+e(error.message)+'<br><button id="retryDetail" type="button">重试</button></div>';document.getElementById('retryDetail').onclick=()=>loadDetail(id,variantId,options)}
}
function renderProductDetail(detail,variantId,sequence,options={}){
  const id=detail.product_id,body=document.getElementById('sheetBody');
  observeBundleDetail(detail);
  currentProduct=detail;referenceOffers.clear();for(const quote of detail.offers){quote.reference_product_id=detail.product_id;quote.reference_variant_id=detail.variant_id;}
  document.getElementById('sheetImg').style.display='';document.getElementById('sheetImg').src=safeUrl(detail.image);document.getElementById('sheetBrand').textContent=detail.identity.brand;
  document.getElementById('sheetName').textContent=detail.name_zh||detail.name;
  const confirmedSoldOut=detail.offers.length>0&&detail.offers.every(q=>q.offer.stock==='out_of_stock');
  const inventoryExpired=detail.offers.some(q=>q.offer.stock==='in_stock'&&!inventoryVerified(q.offer));
  const summary='<div class="summary-box"><h4>下一步：比较运输路线</h4><p>先选择具体商店报价，再比较直邮、转运和香港途径。费用、库存或中国发卡条件未齐时，仅供核实，不确认最低到手价。</p></div>';
  const available=detail.variants.filter(v=>v.in_stock&&v.size&&(v.variant_id!==detail.variant_id||detail.offers.some(q=>offerAvailable(q))));
  // VariantChoice.in_stock comes from the server's exact-offer freshness check.
  // Recheck the loaded variant's quotes as well before allowing an action.
  const model=bundleVariantModel(detail)?.map(row=>({...row,variant:{...row.variant,in_stock:available.some(v=>v.variant_id===row.variant.variant_id)&&!bundleVariantBlocked(id,row.variant.variant_id)}}));
  let selected=!!variantId&&available.some(v=>v.variant_id===variantId),selection={};
  if(model){
    const saved=history.state?.bikehuntPurchase;
    const wanted=selected?parseBundleSize(detail.identity.size):options.bundleSelection||(saved?.productId===id&&saved.stage==='detail'?saved.bundleSelection:null);
    selection=normalizeBundleSelection(model,wanted);
    selected=selected&&exactBundleVariant(model,selection)?.variant_id===detail.variant_id;
    currentBundleSelection={productId:id,selection,variantId:selected?detail.variant_id:null};
  }else currentBundleSelection=null;
  const colors=detail.colors?.filter(c=>c.in_stock)||[];
  const colorMarkup=colors.length>1?'<div class="variant-bar"><label for="colorChoice">现货颜色</label><select id="colorChoice">'+colors.map(c=>'<option value="'+e(c.product_id)+'" '+(c.product_id===id?'selected':'')+'>'+e(c.color)+'</option>').join('')+'</select></div>':'';
  const longLabels=!model&&detail.variants.some(v=>String(v.size).length>40);
  const ordinaryMarkup='<div class="variant-bar"><label for="variant">先选现货尺码</label><select id="variant"><option value="">请选择剩余现货规格</option>'+available.map((v,index)=>'<option value="'+e(v.variant_id)+'" '+(selected&&v.variant_id===detail.variant_id?'selected':'')+'>'+e(compactVariantLabel(v.size,detail.variants.indexOf(v)))+' · '+v.source_count+' 个渠道 · 商品参考 '+e(cny(v.product_cny_from))+'</option>').join('')+'</select></div><div class="size-choices">'+available.map((v,index)=>'<button type="button" data-variant="'+e(v.variant_id)+'" aria-pressed="'+Boolean(selected&&v.variant_id===detail.variant_id)+'">'+e(compactVariantLabel(v.size,detail.variants.indexOf(v)))+'</button>').join('')+'</div>'+(longLabels?'<details class="variant-original"><summary>查看组合编号与商家原始规格</summary>'+detail.variants.map((v,index)=>'<p>'+e(compactVariantLabel(v.size,index))+(v.in_stock?'':v.stock_state==='out_of_stock'?'（已售罄）':'（库存待核实）')+'：'+e(v.size)+'</p>').join('')+'</details>':'');
  const retryGuards=model&&[...bundleQuoteGuards().values()].some(guard=>guard.productId===id&&!guard.confirmed)?'<button type="button" class="bundle-recheck" data-bundle-recheck>重新核对变化的组合</button>':'';
  const variants=colorMarkup+(model?bundleSelectorMarkup(model,selection,options.message||(variantId&&!selected?'原选组合已售罄、报价更新尚未同步或库存待核实，请重新选择。':'')):ordinaryMarkup)+retryGuards+'<p class="spec-note">颜色：'+e(detail.identity.color||'参照当前商品图，原站核对颜色')+'。只列最近一小时内核实有库存的尺码；售罄、核实过期和未知库存不作为现货尺码展示；可从官网核对当前情况。</p>';
  const selectedLabel=compactVariantLabel(detail.identity.size,detail.variants.findIndex(v=>v.variant_id===detail.variant_id));
  body.innerHTML=variants+'<div id="fitReference"></div>'+
    (detail.identity.mpn?'<div class="model-code">制造商型号 '+e(detail.identity.mpn)+(detail.identity.color?' · '+e(detail.identity.color):'')+'</div>':'')+
    (selected?summary+'<div class="offers"><h4>已选 '+e(selectedLabel)+' · '+e(detail.identity.color||'当前款')+' · '+detail.offers.length+' 条同规格报价</h4>'+detail.offers.map(offerMarkup).join('')+'</div>':'<div class="summary-box"><h4>'+(model?'选齐三件套后，显示对应价格':confirmedSoldOut?'所示规格 '+e(selectedLabel)+' 已售罄':available.length?'选择上方尺码后，显示对应价格':inventoryExpired?'库存待核实':'尚未取得可选的现货规格')+'</h4><p>'+(model?'每个完整组合对应商家的一个实际规格；未选齐时不显示购买入口。':confirmedSoldOut?'该规格已确认售罄，目前没有购买链接。其他尺码请分别核对。':available.length?'不同尺码的库存与价格可能不同，先选规格再比较。':inventoryExpired?'历史价格仍可参考；上次库存核实已超过一小时，尺码待核实。可前往官网商品页查看当前情况。':'当前报价可供参考；未知库存不会作为现货尺码显示。可前往官网商品页自行核对。')+'</p></div>')+
    (!selected&&!model?referenceOffersMarkup(detail):'')+
    '<div class="service-note">汇率日期 '+e(detail.fx.rate_date||'待获取')+(detail.fx.stale?' · 使用过期缓存':'')+'。人民币金额为参考，信用卡入账及手续费以发卡行为准。<br>BikeHunt 只提供信息与外链，付款、订单及售后由第三方网站负责。</div>';
  const single=document.getElementById('variant');if(single)single.onchange=event=>loadDetail(id,event.target.value||null);
  const colorSelect=document.getElementById('colorChoice');if(colorSelect)colorSelect.onchange=event=>loadDetail(event.target.value,null);
  body.querySelectorAll('[data-variant]').forEach(button=>button.onclick=()=>loadDetail(id,button.dataset.variant));
  body.querySelectorAll('[data-bundle-part]').forEach(select=>select.onchange=()=>{
    const index=BUNDLE_PARTS.findIndex(part=>part.key===select.dataset.bundlePart),next={};
    for(const part of BUNDLE_PARTS.slice(0,index))next[part.key]=selection[part.key];
    next[select.dataset.bundlePart]=select.value;
    const clean=normalizeBundleSelection(model,next),exact=exactBundleVariant(model,clean),focusId='bundle-'+BUNDLE_PARTS[Math.min(index+1,2)].key;
    if(exact){loadDetail(id,exact.variant_id,{bundleSelection:clean,focusId});return}
    if(typeof cancelPurchaseContext==='function')cancelPurchaseContext();
    renderProductDetail(detail,null,++detailSequence,{bundleSelection:clean});
    const target=document.getElementById(focusId);(target&&!target.disabled?target:document.getElementById(select.id))?.focus();
  });
  body.querySelectorAll('[data-bundle-recheck]').forEach(button=>button.onclick=()=>recheckBundleQuotes());
  body.querySelectorAll('.guide-start').forEach(button=>button.onclick=()=>startGuide(detail,button.dataset.offer));
  bindMerchantGuides(detail,selected?detail.variant_id:null);
  if(!model)refreshFitReference(detail,sequence);
  if(typeof rememberPurchaseDetail==='function')rememberPurchaseDetail(detail,selected,model?selection:null);
}
function openProduct(id,variantId=null,allowSoldOut=false){
  if(!allowSoldOut&&items.find(p=>p.product_id===id)?.stock_state==='out_of_stock')return;
  lastFocus=document.activeElement;gallery.inert=true;sheet.inert=false;
  document.getElementById('sheetImg').style.display='';
  const item=items.find(p=>p.product_id===id);if(item){document.getElementById('sheetName').textContent=item.name;document.getElementById('sheetBrand').textContent=item.brand;document.getElementById('sheetImg').src=safeUrl(item.image)}
  document.getElementById('overlay').classList.add('open');sheet.classList.add('open');sheet.setAttribute('aria-hidden','false');document.getElementById('close').focus();loadDetail(id,variantId);
}
function closeSheet(){currentBundleSelection=null;if(typeof clearPurchaseState==='function')clearPurchaseState();referenceOffers.clear();if(typeof merchantGuideSource!=='undefined')merchantGuideSource=null;if(typeof messagesOpen!=='undefined')messagesOpen=false;if(typeof guideContext!=='undefined')guideContext=null;++detailSequence;sheet.classList.remove('open');sheet.setAttribute('aria-hidden','true');sheet.inert=true;document.getElementById('overlay').classList.remove('open');gallery.inert=false;document.getElementById('directoryPage').inert=false;currentProduct=null;lastFocus?.focus()}
async function init(){
  gallery.innerHTML='<div class="empty loading" role="status"><strong>正在整理骑行好价</strong>读取商品与人民币参考价…</div>';
  try{
    const data=await getJson('/api/catalog');items=data.items;fx=data.fx;sourceCount=data.source_count;
    updateFxLabel();
    try{viewMode=localStorage.getItem('bikehuntView')||'feed'}catch{viewMode='feed'}setView(viewMode,false);
    document.getElementById('sourceCount').textContent=data.source_count+' 个已采集报价源';
  }catch(error){gallery.innerHTML='<div class="empty"><strong>商品暂时无法加载</strong>'+e(error.message)+'<br><button id="retry" type="button">重新加载</button></div>';document.getElementById('retry').onclick=init}
}
document.addEventListener('input',updateShippingBudget);
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
    if(event.key==='Tab'){const focusable=[...sheet.querySelectorAll('button,a,select,summary,input,[tabindex="0"]')].filter(x=>!x.disabled&&x.getClientRects().length);const first=focusable[0],last=focusable.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}}return;
  }
  if(['INPUT','SELECT','TEXTAREA','BUTTON','A'].includes(event.target.tagName)||viewMode!=='feed')return;
  if(['ArrowDown','PageDown','ArrowUp','PageUp'].includes(event.key)){event.preventDefault();move(['ArrowDown','PageDown'].includes(event.key)?1:-1)}
});
init();
