'use strict';
// Dated, read-only policy summaries. These never alter an offer or cost estimate.
const READINESS_BASE=new URL('./',document.currentScript.src);
const READINESS_HOSTS=Object.freeze({
  pelotan:["pelotan.cc"],
  maurten_nutrition:["www.maurten.com"],
  sis_nutrition:["www.scienceinsport.com"],
  oakley:["www.oakley.com"],
  soudal:["thewolfpack.shop"],
  ineos:["store.netcompanyineos.com"],
  decathlon:["shop.decathloncmacgmteam.com"],
  castelli:["www.castelli-cycling.com"],
  groupama:["shop.bioracer.com"],
  ef_team_shop:["efprocycling.shop"],
  alpecin:["shops.topfanz.com"],
  sigmasports:["www.sigmasports.com"],
  lotto:["www.lotto-intermarche.be"],
  nsn:["www.ekoi.com"],

  kask:['www.kask.com'],teamcycles:['www.teamcycles.com'],unox:['internshop.no'],canyon:['www.canyon.com'],specialized:['www.specialized.com'],rapha:['support.rapha.cc'],rapha_kr:['support.rapha.cc'],
  redbull:['customerservice.redbullshop.com'],picnic:['teampicnicpostnl.store'],pns:['pasnormalstudios.com'],assos:['www.assos.com'],
  gobik:['gobik.com'],movistar:['gobik.com'],bahrain:['alecycling.com'],
  uae:['www.pissei.com'],fizik:['www.fizik.com','www.iubenda.com'],santini:['www.santinicycling.com'],lidl_trek:['www.santinicycling.com'],
  amazon_us:['www.amazonforum.com','www.amazon.com'],amazon_uk:['www.aboutamazon.co.uk','sellercentral-europe.amazon.com','digprjsurvey.amazon.co.uk'],
  amazon_de:['www.aboutamazon.de'],amazon_jp:['press.aboutamazon.com','www.unionpayintl.com'],
  visma:['www.teamvismaleaseabike.com'],maap:['support.maap.cc'],poc:['poc.com'],
  jayco:['support.maap.cc'],decathlon_cn:['www.decathlon.com.cn'],colnago:['www.colnago.com'],
  myus:['www.myus.com'],forward2me:['www.forward2me.com','forward2me.zendesk.com'],tenso:['www.tenso.com','faq.tenso.com']
});
const READINESS_SCOPES=Object.freeze({
  pelotan:["market", "UK", ["pelotan.cc"]],
  maurten_nutrition:["market", "法国市场 · EUR 报价；中国配送与支付待核实", ["www.maurten.com"]],
  sis_nutrition:["market", "UK", ["www.scienceinsport.com"]],
  gobik:["market", "西班牙站 EUR 报价", ["gobik.com"]],
  oakley:["market", "美国站 USD 报价", ["www.oakley.com"]],
  soudal:["market", "BE 市场 · EUR 报价；未验证其他市场库存", ["thewolfpack.shop"]],
  ineos:["market", "US 市场 · USD 报价；未验证其他市场库存", ["store.netcompanyineos.com"]],
  decathlon:["market", "US 市场 · USD 报价；未验证其他市场库存", ["shop.decathloncmacgmteam.com"]],
  castelli:["market", "AF 市场 · EUR 报价；未验证其他市场库存", ["www.castelli-cycling.com"]],
  groupama:["market", "US 市场 · USD 报价；未验证其他市场库存", ["shop.bioracer.com"]],
  ef_team_shop:["market", "美国", ["efprocycling.shop"]],
  alpecin:["market", "比利时商城 EUR 页面显示价；配送费用另核", ["shops.topfanz.com"]],
  sigmasports:["merchant", null, ["www.sigmasports.com"]],
  lotto:["market", "比利时站 EUR 报价", ["www.lotto-intermarche.be"]],
  nsn:["market", "阿联酋站 USD 报价", ["www.ekoi.com"]],

  kask:["market", "意大利站 EUR 报价", ["www.kask.com"]],
  teamcycles:["merchant", null, ["www.teamcycles.com"]],
  unox:["market", "挪威商城 / NOK 报价", ["internshop.no"]],
  canyon:["market", "US 市场 · USD 商品报价；配送另核", ["www.canyon.com"]],
  specialized:["market", "US 市场 · USD 商品报价；配送另核", ["www.specialized.com"]],
  rapha:["market", "日本站报价", ["www.rapha.cc"]],
  rapha_kr:["market", "韩国站报价", ["www.rapha.cc"]],

  redbull:["market", "日本市场 JPY 报价", ["www.redbullshop.com"]],
  picnic:["market", "US 市场 · EUR 报价；未验证其他市场库存", ["teampicnicpostnl.store"]],
  pns:["market", "欧洲站 EUR 报价", ["pasnormalstudios.com"]],
  assos:["market", "国际站 USD 报价", ["www.assos.com"]],

  movistar:["market", "US 市场 · EUR 报价；未验证其他市场库存", ["gobik.com"]],
  bahrain:["market", "US 市场 · USD 报价；未验证其他市场库存", ["alecycling.com"]],

  uae:["market", "US / USD 报价", ["www.pissei.com"]],
  fizik:["market", "US 市场 · USD 报价；未验证其他市场库存", ["www.fizik.com"]],
  santini:["market", "IT 市场 · EUR 报价；未验证其他市场库存", ["www.santinicycling.com"]],
  lidl_trek:["market", "IT 市场 · EUR 报价；未验证其他市场库存", ["www.santinicycling.com"]],

  amazon_us:['market','美国站',['amazon.com','www.amazon.com']],amazon_uk:['market','英国站',['amazon.co.uk','www.amazon.co.uk']],
  amazon_de:['market','德国站',['amazon.de','www.amazon.de']],amazon_jp:['market','日本站',['amazon.co.jp','www.amazon.co.jp']],
  visma:['merchant',null,['teamvismaleaseabike.com','www.teamvismaleaseabike.com']],maap:['merchant',null,['maap.cc','www.maap.cc']],poc:['market','Global EN',['poc.com','www.poc.com']],
  jayco:['merchant',null,['maap.cc','www.maap.cc']],decathlon_cn:['market','中国大陆 CNY 报价',['www.decathlon.com.cn','decathlon.com.cn']],
  colnago:['market','US 市场 · USD 商品报价；配送另核',['www.colnago.com']]
});
let readinessData=null,readinessState='loading',readinessSequence=0;
const readinessContexts=new Map();
function readinessEscape(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function readinessUrl(value,code){
  try{const u=new URL(value);return typeof value==='string'&&u.href===value&&u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&Object.prototype.hasOwnProperty.call(READINESS_HOSTS,code)&&READINESS_HOSTS[code].includes(u.hostname)}catch{return false}
}
function readinessText(value,max=2000){return typeof value==='string'&&value.trim().length>0&&value.length<=max}
function readinessDate(value){return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value&&Date.parse(value)<=Date.now()}
function readinessObservation(value){
  return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number(value.slice(11,13))<24&&Number(value.slice(14,16))<60&&Number(value.slice(17,19))<60&&readinessDate(value.slice(0,10))&&Number.isFinite(Date.parse(value))&&Date.parse(value)<=Date.now();
}
function validateReadinessData(data){
  const states=['confirmed','conditional_checkout','unknown','prohibited','historical_official_only'];
  if(!data||data.schemaVersion!==1||!readinessText(data.revision,100)||!readinessDate(data.checkedAt)||!readinessText(data.paymentCaveat)||!readinessText(data.forwardingExplainer)||!Array.isArray(data.costChecklist)||!data.costChecklist.every(x=>readinessText(x,300))||!Array.isArray(data.entries)||data.entries.length>50||!Array.isArray(data.forwarders)||data.forwarders.length>3)throw Error('Invalid purchase readiness data');
  const keys=new Set();
  for(const entry of data.entries){
    const key=JSON.stringify([entry.sourceCode,entry.scope,entry.salesRegion]);
    if(!Object.prototype.hasOwnProperty.call(READINESS_HOSTS,entry.sourceCode)||!['market','merchant'].includes(entry.scope)||keys.has(key)||!readinessText(entry.label,100)||!readinessText(entry.policyScope,300)||(entry.scope==='market'?!readinessText(entry.salesRegion,200):entry.salesRegion!==null)||!Array.isArray(entry.merchantHosts)||!entry.merchantHosts.length||!entry.merchantHosts.every(x=>/^[a-z0-9.-]+$/.test(x))||!Array.isArray(entry.sources)||!entry.sources.length||!entry.sources.every(url=>readinessUrl(url,entry.sourceCode)))throw Error('Invalid purchase readiness scope');
    const scope=READINESS_SCOPES[entry.sourceCode];if(!scope||entry.scope!==scope[0]||entry.salesRegion!==scope[1]||entry.merchantHosts.length!==scope[2].length||!entry.merchantHosts.every(host=>scope[2].includes(host)))throw Error('Wrong merchant or market policy scope');
    if(entry.checkedAt!==undefined&&!readinessDate(entry.checkedAt))throw Error('Invalid policy verification date');
    keys.add(key);
    for(const field of ['payment','directChina','forwarding'])if(!entry[field]||!states.includes(entry[field].status)||!readinessText(entry[field].note))throw Error('Invalid purchase readiness claim');
    if(!Array.isArray(entry.payment.methods)||!entry.payment.methods.every(x=>readinessText(x,100))||!['unknown','conditional_checkout'].includes(entry.payment.chinaIssuedCard))throw Error('No verified China-issued card transaction in this research');
    if(entry.directChina.shippingAmount!==undefined&&(!(typeof entry.directChina.shippingAmount==='number')||!Number.isFinite(entry.directChina.shippingAmount)||entry.directChina.shippingAmount<0||! /^[A-Z]{3}$/.test(entry.directChina.shippingCurrency)))throw Error('Shipping needs its own currency');
  }
  const forwarders=new Set();
  for(const row of data.forwarders){
    if(!['myus','forward2me','tenso'].includes(row.id)||forwarders.has(row.id)||!readinessText(row.name,100)||!readinessText(row.note)||!readinessText(row.warning)||!readinessUrl(row.calculator,row.id)||!Array.isArray(row.sources)||!row.sources.every(url=>readinessUrl(url,row.id)))throw Error('Invalid forwarding reference');
    forwarders.add(row.id);
  }
  return data;
}
// Directory cards have no exact offer market. Market policies remain labelled references.
const readinessDirectoryLinks=new WeakMap();
function readinessDirectoryRows(entry){
  if(!readinessData||!entry)return [];
  const codes=Array.isArray(entry.source_codes)&&entry.source_codes.length?entry.source_codes:[entry.code];
  let shop;try{shop=new URL(entry.shop_url);if(shop.protocol!=='https:'||shop.username||shop.password||shop.port)return []}catch{return []}
  return readinessData.entries.filter(row=>codes.includes(row.sourceCode)&&row.merchantHosts.includes(shop.hostname));
}
function readinessDirectoryMarkup(entry){
  const rows=readinessDirectoryRows(entry),esc=readinessEscape;
  if(!rows.length)return '';
  return '<p class="readiness-meta">已核官网说明，配送及退货条件请展开查看</p>'+rows.map(row=>'<details class="readiness-evidence"><summary>'+esc(row.label)+' · 配送、退货与适用范围</summary><p class="readiness-scope">'+esc(row.scope==='market'?'指定市场参考：'+row.salesRegion+'；目录未提供精确报价市场，本说明不确认当前商品可购买。':'商家范围的政策资料；具体商品与地址仍须结账确认。')+'</p><p>'+esc(row.directChina.note)+'</p><p>转运：'+esc(row.forwarding.note)+'</p>'+(row.sourceLimitations?'<p>'+esc(row.sourceLimitations)+'</p>':'')+'<p class="readiness-meta">核对：'+esc(row.checkedAt||readinessData.checkedAt)+' · '+esc(row.policyScope)+'</p><ul>'+row.sources.map((url,i)=>'<li>'+readinessLink(url,row.sourceCode,'官方来源 '+(i+1))+'</li>').join('')+'</ul></details>').join('');
}
function refreshDirectoryReadiness(){
  const panel=document.getElementById('channelInfo');
  if(!panel||typeof activeSource==='undefined'||typeof directoryData==='undefined'||panel.dataset.source!==activeSource||panel.dataset.loaded!=='yes')return;
  const entry=[...directoryData.brands,...directoryData.teams].find(row=>row.code===activeSource);
  const slot=panel.querySelector('[data-directory-readiness]');if(!entry||!slot)return;
  slot.innerHTML=readinessDirectoryMarkup(entry);
  const empty=panel.querySelector('[data-directory-empty-rules]');if(empty)empty.hidden=readinessDirectoryRows(entry).length>0;
  slot.querySelectorAll('a[data-readiness-link]').forEach(link=>readinessDirectoryLinks.set(link,{panel,slot,source:entry.code,code:link.dataset.readinessLink,url:link.getAttribute('href')}));
}
function allowedDirectoryReadinessLink(link){
  const saved=readinessDirectoryLinks.get(link);
  if(!saved||typeof activeSource==='undefined'||typeof activeTab==='undefined'||typeof directoryData==='undefined')return null;
  const panel=document.getElementById('channelInfo');
  if(panel!==saved.panel||!panel.open||panel.hidden||activeTab!=='products'||panel.dataset.loaded!=='yes'||panel.dataset.source!==activeSource||activeSource!==saved.source||!panel.contains(saved.slot)||!saved.slot.contains(link))return null;
  const entry=[...directoryData.brands,...directoryData.teams].find(row=>row.code===activeSource);
  const code=link.dataset.readinessLink,url=link.getAttribute('href');
  return code===saved.code&&url===saved.url&&readinessUrl(url,code)&&readinessDirectoryRows(entry).some(row=>row.sourceCode===code&&row.sources.includes(url))?url:null;
}
function readinessPolicy(offer){
  if(!readinessData)return null;
  return readinessData.entries.find(row=>{
    if(row.sourceCode!==offer.source_code||row.scope==='market'&&row.salesRegion!==offer.sales_region)return false;
    if(offer.url){try{if(!row.merchantHosts.includes(new URL(offer.url).hostname))return false}catch{return false}}
    return true;
  })||null;
}
function readinessLink(url,code,label){return readinessUrl(url,code)?'<a data-readiness-link="'+readinessEscape(code)+'" href="'+readinessEscape(url)+'" target="_self" rel="noopener noreferrer">'+readinessEscape(label)+' →</a>':''}
function readinessEvidenceMarkup(offer){
  // Card-only legacy fields never override the dedicated payment matrix.
  const check=offer.shipping_to_china;
  return check?.note?'<p>配送证据：'+readinessEscape(check.note)+'（核对日期：'+readinessEscape(check.checked_at||'未记录')+'）</p>':'';
}
function readinessContent(offer){
  const esc=readinessEscape,row=readinessPolicy(offer),shipping=offer.shipping_to_china||{};
  const changed=/原文已变化|正在复核/.test(shipping.note||'');
  const domestic=offer.source_code==='decathlon_cn'&&row?.salesRegion==='中国大陆 CNY 报价';
  let delivery=shipping.status==='no'?'报价证据：不直邮中国大陆':row?.directChina.status==='prohibited'?'官网规则：不直邮中国大陆':row?.directChina.status==='confirmed'?'官网列中国配送；本件商品、地址及最终费用仍须结账核对':row?.directChina.status==='conditional_checkout'?'配送有市场或订单条件，需核对商品和收货地址':'中国直邮待核实；先确认商品与地址，再决定注册';
  if(domestic)delivery='官网支持中国大陆配送；具体地址、商品与配送方式以结账为准';
  if(changed)delivery='报价规则待复核，暂不确认中国配送';
  const freight=changed?'运费规则待复核':row?.directChina.shippingAmount!==undefined?row.directChina.shippingCurrency+' '+row.directChina.shippingAmount.toFixed(2)+'（官网公布运费，独立于商品币种；非含税总价）':offer.shipping&&offer.shipping.amount!==null&&offer.shipping.amount!==undefined?String(offer.shipping.currency)+' '+String(offer.shipping.amount)+'（报价记录，结账再确认）':'运费待确认';
  const reference=readinessData?.entries.find(item=>item.sourceCode===offer.source_code&&item.scope==='market'&&item.salesRegion!==offer.sales_region&&!item.sourceCode.startsWith('amazon_'));
  const payment=typeof paymentMethodsMarkup==='function'?paymentMethodsMarkup(offer,false):'<p data-china-card-status="unknown">支付说明暂时无法加载。中国发行卡或其他支付方式是否可用，请在商家结账页确认。</p>';
  return '<h4>注册前，先确认能不能买</h4><p class="readiness-scope">'+esc(offer.source_name||row?.label||offer.source_code||'当前商店')+' · '+esc(offer.sales_region||'报价市场未记录')+'</p>'+payment+'<dl class="readiness-checks"><div><dt>寄往中国</dt><dd>'+esc(delivery)+'</dd></div><div><dt>运费与税</dt><dd>'+esc(freight)+(domestic?'；国内订单按所选配送方式和实付金额计算，不套用境外进口税估算。':'；进口税、清关和银行卡费用未齐全不等于 0，不作为最终到手价。')+'</dd></div></dl>'+
    (row?'<p class="readiness-meta">配送资料核对：'+esc(row.checkedAt||readinessData.checkedAt)+' · '+esc(row.policyScope)+'</p><details class="readiness-evidence"><summary>配送与转运依据</summary><p>'+esc(row.directChina.note)+'</p><p>转运：'+esc(row.forwarding.note)+'</p>'+(row.sourceLimitations?'<p>'+esc(row.sourceLimitations)+'</p>':'')+'<p>这些说明仅适用于所列商店与地区。付款与配送以当前订单为准，未确认的费用不按 0 计算。</p>'+readinessEvidenceMarkup(offer)+'<ul>'+row.sources.map((url,i)=>'<li>'+readinessLink(url,row.sourceCode,'官方来源 '+(i+1))+'</li>').join('')+'</ul></details>':'<p class="readiness-meta">'+(readinessState==='loading'?'正在加载配送说明，请稍候。':'这家商店当前地区的配送条件尚未确认，请先向商家咨询。')+'</p>'+
      (reference?'<p class="readiness-warning">其他范围的官方参考（'+esc(reference.policyScope)+'，核对 '+esc(reference.checkedAt||readinessData.checkedAt)+'）：'+esc(reference.directChina.note)+' 转运：'+esc(reference.forwarding.note)+' 这些条款不作为当前报价市场已核实的支付依据。</p>':'')+
      '<details class="readiness-evidence"><summary>查看现有配送证据</summary>'+ (readinessEvidenceMarkup(offer)||'<p>配送来源与核对日期待补齐。</p>')+(reference?reference.sources.map((url,i)=>readinessLink(url,reference.sourceCode,'范围参考来源 '+(i+1))).join(''):'')+'</details>');
}
function purchaseReadinessMarkup(offer){
  const key=String(++readinessSequence);readinessContexts.set(key,offer||{});
  return '<section class="purchase-readiness" data-readiness-context="'+key+'" aria-label="注册前购买条件">'+readinessContent(offer||{})+'</section>';
}
function forwardingExplainerContent(){
  if(!readinessData)return '<p>转运费用参考'+(readinessState==='loading'?'正在读取':'暂不可用')+'。未知运费、税费和退件费用均不能按 0 计算。</p>';
  const esc=readinessEscape;
  return '<p>'+esc(readinessData.forwardingExplainer)+'</p><p class="readiness-warning">下面只解释服务与费用，不推荐任何当前商品通过转运下单。商家是否允许尚未知时，先取得许可；明确禁止时不要使用。MAAP 官网不寄中国，转运许可未核实，优先找官网确认的本地渠道；POC Global EN 条款明确禁止转运。</p><h4>别只看“国际运费”</h4><ul>'+readinessData.costChecklist.map(text=>'<li>'+esc(text)+'</li>').join('')+'</ul><p>先索取包装后的实重与长宽高，再选中国目的地估算。按真实成交价、品名和数量申报，不低报。计算器估值、未列税费、DDP / DAP 标签都需结合本单明细确认；这里没有完整含税总价，也不把旧服务商金额提示当现行中国法律。</p>'+readinessData.forwarders.map(row=>'<section class="forwarder-reference"><h4>'+esc(row.name)+'</h4><p>'+esc(row.note)+'</p><p class="readiness-warning">'+esc(row.warning)+'</p><p>'+readinessLink(row.calculator,row.id,'官方运费计算器')+'</p><details><summary>费用规则来源</summary><ul>'+row.sources.map((url,i)=>'<li>'+readinessLink(url,row.id,'服务商官方说明 '+(i+1))+'</li>').join('')+'</ul></details></section>').join('')+'<p class="readiness-meta">资料核对：'+esc(readinessData.checkedAt)+'。具体线路、附加费与退货成本仍需按包裹确认。</p>';
}
function forwardingExplainerMarkup(){return '<details class="forwarding-explainer"><summary>看懂转运和额外费用（一般知识）</summary><div data-forwarding-content>'+forwardingExplainerContent()+'</div></details>'}
function refreshReadinessMarkup(){
  refreshDirectoryReadiness();
  document.querySelectorAll('[data-feasibility-context]').forEach(node=>{const offer=readinessContexts.get(node.dataset.feasibilityContext);if(offer)node.innerHTML=paymentFeasibilityContent(offer)});
  if(typeof refreshPurchaseRoutePolicy==='function')refreshPurchaseRoutePolicy();
  document.querySelectorAll('[data-readiness-context]').forEach(node=>{const offer=readinessContexts.get(node.dataset.readinessContext);if(offer)node.innerHTML=readinessContent(offer)});
  document.querySelectorAll('[data-forwarding-content]').forEach(node=>{node.innerHTML=forwardingExplainerContent()});
}
function allowedReadinessLink(link){
  if(!readinessData||!link?.isConnected)return null;
  const directoryUrl=allowedDirectoryReadinessLink(link);if(directoryUrl)return directoryUrl;
  if(!document.getElementById('sheet')?.classList.contains('open')||!document.getElementById('sheetBody')?.contains(link))return null;
  const code=link.dataset.readinessLink,url=link.getAttribute('href');
  const links=readinessData.entries.filter(row=>row.sourceCode===code).flatMap(row=>row.sources).concat(readinessData.forwarders.filter(row=>row.id===code).flatMap(row=>[row.calculator,...row.sources]));
  return readinessUrl(url,code)&&links.includes(url)?url:null;
}
function readinessSourceDate(code,url){
  const rows=readinessData?.entries.filter(row=>row.sourceCode===code&&row.sources.includes(url))||[];
  const dates=[...new Set(rows.map(row=>row.checkedAt||readinessData.checkedAt))];
  return dates.length?dates.join('、'):(readinessData?.checkedAt||'未记录');
}
function guardReadinessExit(event){
  const link=event.target.closest?.('a[data-readiness-link]');if(!link||(event.type==='auxclick'&&event.button!==1))return;
  event.preventDefault();const url=allowedReadinessLink(link);if(!url)return;
  showExternalExit({url,kind:'reference',label:link.textContent?.trim()||'规则与费用参考',trigger:link,
    sourceNote:'本站保存了该规则或服务商资料，资料核对：'+readinessSourceDate(link.dataset.readinessLink,url)+'；记录可能有市场、日期或历史资料限制，不等于本次服务已核验。',
    note:'即将打开官方规则或费用计算器，仅作资料核对，不代表商家允许转运、接受中国银行卡或保证总费用。请自行确认服务条款及费用后再使用。',
    validate:()=>allowedReadinessLink(link)===url,onConfirm:()=>{if(typeof saveBrowseState==='function')saveBrowseState()}});
}
for(const event of ['click','auxclick'])document.addEventListener(event,guardReadinessExit);
async function loadPurchaseReadiness(){
  try{const response=await fetch(new URL('purchase-readiness.json',READINESS_BASE).href,{cache:'no-store'});if(!response.ok)throw Error('Purchase readiness unavailable');const raw=await response.text();if(raw.length>100000)throw Error('Purchase readiness too large');readinessData=validateReadinessData(JSON.parse(raw));readinessState='ready'}catch{readinessData=null;readinessState='error'}
  refreshReadinessMarkup();
}
loadPurchaseReadiness();

// One short, visible payment warning before route selection. Detailed evidence
// stays optional; card networks and wallets never imply issuer approval.
function paymentFeasibilityContent(offer={}){
  if(typeof paymentSummary==='function'){
    const s=paymentSummary(offer);return '<strong data-china-card-status="'+s.status+'">'+readinessEscape(s.label)+'</strong><span>'+readinessEscape(s.methodsLabel)+' 卡组织和钱包支持不保证中国发卡获批；扣款不明先查订单，勿重复试付。</span>';
  }
  return '<strong data-china-card-status="unknown">中国发行卡：待核实</strong><span>支付说明暂时无法加载，请先确认商家是否接受你的银行卡或账户。扣款不明先查订单，勿重复试付。</span>';
}
function paymentFeasibilityMarkup(offer={}){
  if(typeof paymentMethodsMarkup==='function')return paymentMethodsMarkup(offer);
  const key=String(++readinessSequence);readinessContexts.set(key,offer);
  return '<div class="payment-feasibility" data-feasibility-context="'+key+'">'+paymentFeasibilityContent(offer)+'</div>';
}





