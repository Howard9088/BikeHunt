'use strict';
// Dated, read-only policy summaries. These never alter an offer or cost estimate.
const READINESS_BASE=new URL('./',document.currentScript.src);
const READINESS_HOSTS=Object.freeze({
  amazon_us:['www.amazonforum.com','www.amazon.com'],amazon_uk:['www.aboutamazon.co.uk','sellercentral-europe.amazon.com','digprjsurvey.amazon.co.uk'],
  amazon_de:['www.aboutamazon.de'],amazon_jp:['press.aboutamazon.com','www.unionpayintl.com'],
  visma:['www.teamvismaleaseabike.com'],maap:['support.maap.cc'],poc:['poc.com'],
  myus:['www.myus.com'],forward2me:['www.forward2me.com','forward2me.zendesk.com'],tenso:['www.tenso.com','faq.tenso.com']
});
const READINESS_SCOPES=Object.freeze({
  amazon_us:['market','美国站',['amazon.com','www.amazon.com']],amazon_uk:['market','英国站',['amazon.co.uk','www.amazon.co.uk']],
  amazon_de:['market','德国站',['amazon.de','www.amazon.de']],amazon_jp:['market','日本站',['amazon.co.jp','www.amazon.co.jp']],
  visma:['merchant',null,['teamvismaleaseabike.com','www.teamvismaleaseabike.com']],maap:['merchant',null,['maap.cc','www.maap.cc']],poc:['market','Global EN',['poc.com','www.poc.com']]
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
  // Existing offer evidence remains explicit; absent dates are never invented.
  return ['china_issued_card','card_networks_evidence','shipping_to_china'].map(key=>{
    const check=offer[key];if(!check||!check.note)return '';
    return '<p>'+readinessEscape({china_issued_card:'中国发卡证据',card_networks_evidence:'卡种证据',shipping_to_china:'配送证据'}[key])+'：'+readinessEscape(check.note)+'（核对日期：'+readinessEscape(check.checked_at||'未记录')+'）</p>';
  }).join('');
}
function readinessContent(offer){
  const esc=readinessEscape,row=readinessPolicy(offer),china=offer.china_issued_card||{},shipping=offer.shipping_to_china||{};
  const changed=[china,shipping,offer.card_networks_evidence||{}].some(check=>/原文已变化|正在复核/.test(check.note||''));
  // A model yes is only a dated evidence claim, never a guarantee of authorization.
  const verified=readinessState==='ready'&&!!row&&!changed&&china.status==='yes'&&china.scope==='offer'&&readinessUrl(china.url,offer.source_code)&&readinessObservation(china.checked_at);
  const issuer=china.status==='no'?'不支持：报价证据列明限制':verified?'已有接受中国发卡的证据，仍需本卡授权':row&&!changed?'有条件，未确认：中国发行卡仍需商家与银行逐卡授权':'待核实：没有已确认的中国发行卡依据';
  const methods=row&&!changed?row.payment.methods.join(' / '):offer.accepted_card_networks?.length?'未经本商店／市场验证的卡组织记录：'+offer.accepted_card_networks.join(' / ')+'；完整适用范围待核实':'尚未取得本商店、本市场的完整支付方式';
  let delivery=shipping.status==='no'?'报价证据：不直邮中国大陆':row?.directChina.status==='prohibited'?'官网规则：不直邮中国大陆':row?.directChina.status==='confirmed'?'官网列中国配送；本件商品、地址及最终费用仍须结账核对':row?.directChina.status==='conditional_checkout'?'部分合格商品可出口中国；逐商品、卖家和地址核对':'中国直邮待核实；先确认商品与地址，再决定注册';
  if(changed)delivery='报价规则待复核，暂不确认中国配送';
  const freight=changed?'运费规则待复核':row?.directChina.shippingAmount!==undefined?row.directChina.shippingCurrency+' '+row.directChina.shippingAmount.toFixed(2)+'（官网公布运费，独立于商品币种；非含税总价）':offer.shipping&&offer.shipping.amount!==null&&offer.shipping.amount!==undefined?String(offer.shipping.currency)+' '+String(offer.shipping.amount)+'（报价记录，结账再确认）':'运费待确认';
  let historical=row?.payment.status==='historical_official_only';
  const reference=readinessData?.entries.find(item=>item.sourceCode===offer.source_code&&item.scope==='market'&&item.salesRegion!==offer.sales_region&&!item.sourceCode.startsWith('amazon_'));
  return '<h4>注册前，先确认能不能买</h4><p class="readiness-scope">'+esc(offer.source_name||row?.label||offer.source_code||'当前商店')+' · '+esc(offer.sales_region||'报价市场未记录')+'</p><dl class="readiness-checks"><div><dt>中国发行卡</dt><dd data-china-card-status="'+(china.status==='no'?'no':verified?'evidence':row&&!changed?'conditional':'unknown')+'">'+esc(issuer)+'</dd></div><div><dt>支付方式</dt><dd>'+esc(methods)+(historical?'。仅有历史官方资料，当前方式待重新核实':'')+'</dd></div><div><dt>寄往中国</dt><dd>'+esc(delivery)+'</dd></div><div><dt>运费与税</dt><dd>'+esc(freight)+'；进口税、清关和银行卡费用未齐全不等于 0，不作为最终到手价。</dd></div></dl><p class="readiness-warning">卡组织支持不等于中国发行卡获批。Apple Pay / Google Pay / PayPal 也不能保证底层卡成功。先确认境外线上支付权限、真实账单地址及可能的 3DS 验证；扣款不明时先查订单和账单，别重复试付。</p>'+
    (row?'<p class="readiness-meta">官方资料核对：'+esc(readinessData.checkedAt)+' · '+esc(row.policyScope)+(historical?' · 历史官方资料，非现行确认':'')+'</p><details class="readiness-evidence"><summary>支付、配送与转运依据</summary><p>'+esc(row.payment.note)+'</p><p>'+esc(row.directChina.note)+'</p><p>转运：'+esc(row.forwarding.note)+'</p>'+(row.sourceLimitations?'<p>'+esc(row.sourceLimitations)+'</p>':'')+'<p>这是上述范围的网页记录，未实测注册、绑卡或付款；不适用于销售同品牌的其他商店。未知条件不计作 0，也不改变商品推荐或购买资格。</p>'+readinessEvidenceMarkup(offer)+'<ul>'+row.sources.map((url,i)=>'<li>'+readinessLink(url,row.sourceCode,'官方来源 '+(i+1))+'</li>').join('')+'</ul></details>':'<p class="readiness-meta">'+(readinessState==='loading'?'正在读取本地政策摘要；尚未确认购买条件。':'尚无匹配本商店和报价市场的完整政策摘要；不套用品牌官网或其他国家站点的规则。')+'</p>'+
      (reference?'<p class="readiness-warning">其他范围的官方参考（'+esc(reference.policyScope)+'，核对 '+esc(readinessData.checkedAt)+'）：'+esc(reference.directChina.note)+' 转运：'+esc(reference.forwarding.note)+' 这些条款不作为当前报价市场已核实的支付依据。</p>':'')+
      '<details class="readiness-evidence"><summary>查看现有报价证据</summary>'+ (readinessEvidenceMarkup(offer)||'<p>来源与核对日期待补齐。</p>')+(reference?reference.sources.map((url,i)=>readinessLink(url,reference.sourceCode,'范围参考来源 '+(i+1))).join(''):'')+'</details>');
}
function purchaseReadinessMarkup(offer){
  const key=String(++readinessSequence);readinessContexts.set(key,offer||{});
  return '<section class="purchase-readiness" data-readiness-context="'+key+'" aria-label="注册前购买条件">'+readinessContent(offer||{})+'</section>';
}
function forwardingExplainerContent(){
  if(!readinessData)return '<p>转运费用参考'+(readinessState==='loading'?'正在读取':'暂不可用')+'。未知运费、税费和退件费用均不能按 0 计算。</p>';
  const esc=readinessEscape;
  return '<p>'+esc(readinessData.forwardingExplainer)+'</p><p class="readiness-warning">下面只解释服务与费用，不推荐任何当前商品通过转运下单。商家是否允许尚未知时，先取得许可；明确禁止时不要使用。MAAP 官网不寄中国，转运许可未核实，优先找官网确认的本地渠道；POC Global EN 条款明确禁止转运。</p><h4>别只看“国际运费”</h4><ul>'+readinessData.costChecklist.map(text=>'<li>'+esc(text)+'</li>').join('')+'</ul><p>先索取包装后的实重与长宽高，再选中国目的地估算。按真实成交价、品名和数量申报，不低报。计算器估值、未列税费、DDP / DAP 标签都需结合本单明细确认；这里没有完整含税总价，也不把旧服务商金额提示当现行中国法律。</p>'+readinessData.forwarders.map(row=>'<section class="forwarder-reference"><h4>'+esc(row.name)+'</h4><p>'+esc(row.note)+'</p><p class="readiness-warning">'+esc(row.warning)+'</p><p>'+readinessLink(row.calculator,row.id,'官方运费计算器')+'</p><details><summary>费用规则来源</summary><ul>'+row.sources.map((url,i)=>'<li>'+readinessLink(url,row.id,'服务商官方说明 '+(i+1))+'</li>').join('')+'</ul></details></section>').join('')+'<p class="readiness-meta">资料核对：'+esc(readinessData.checkedAt)+'。未开户、订阅或提交报价；具体线路、附加费与退货成本仍需按包裹核对。</p>';
}
function forwardingExplainerMarkup(){return '<details class="forwarding-explainer"><summary>看懂转运和额外费用（一般知识）</summary><div data-forwarding-content>'+forwardingExplainerContent()+'</div></details>'}
function refreshReadinessMarkup(){
  document.querySelectorAll('[data-feasibility-context]').forEach(node=>{const offer=readinessContexts.get(node.dataset.feasibilityContext);if(offer)node.innerHTML=paymentFeasibilityContent(offer)});
  if(typeof refreshPurchaseRoutePolicy==='function')refreshPurchaseRoutePolicy();
  document.querySelectorAll('[data-readiness-context]').forEach(node=>{const offer=readinessContexts.get(node.dataset.readinessContext);if(offer)node.innerHTML=readinessContent(offer)});
  document.querySelectorAll('[data-forwarding-content]').forEach(node=>{node.innerHTML=forwardingExplainerContent()});
}
function allowedReadinessLink(link){
  if(!readinessData||!link?.isConnected||!document.getElementById('sheet')?.classList.contains('open')||!document.getElementById('sheetBody')?.contains(link))return null;
  const code=link.dataset.readinessLink,url=link.getAttribute('href');
  const links=readinessData.entries.filter(row=>row.sourceCode===code).flatMap(row=>row.sources).concat(readinessData.forwarders.filter(row=>row.id===code).flatMap(row=>[row.calculator,...row.sources]));
  return readinessUrl(url,code)&&links.includes(url)?url:null;
}
function guardReadinessExit(event){
  const link=event.target.closest?.('a[data-readiness-link]');if(!link||(event.type==='auxclick'&&event.button!==1))return;
  event.preventDefault();const url=allowedReadinessLink(link);if(!url)return;
  showExternalExit({url,kind:'reference',label:link.textContent?.trim()||'规则与费用参考',trigger:link,
    sourceNote:'本站保存了该规则或服务商资料，资料核对：'+readinessData.checkedAt+'；记录可能有市场、日期或历史资料限制，不等于本次服务已核验。',
    note:'即将打开官方规则或费用计算器，仅作资料核对，不代表商家允许转运、接受中国银行卡或保证总费用。不会代你注册、订阅、填卡或付款。',
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
  const row=readinessPolicy(offer),card=offer.china_issued_card||{};
  const changed=[card,offer.shipping_to_china||{},offer.card_networks_evidence||{}].some(check=>/原文已变化|正在复核/.test(check.note||''));
  const verified=readinessState==='ready'&&!!row&&!changed&&card.status==='yes'&&card.scope==='offer'&&readinessUrl(card.url,offer.source_code)&&readinessObservation(card.checked_at);
  const status=card.status==='no'?'no':verified?'evidence':row&&!changed?'conditional':'unknown';
  const label=card.status==='no'?'中国发行卡：已知限制，先核对其他支付方式':verified?'中国发行卡：有接受依据，仍需本卡授权':row&&!changed?'中国发行卡：有条件，未确认本卡获批':'中国发行卡：待核实';
  const methods=row&&!changed?row.payment.methods.join(' / '):offer.accepted_card_networks?.join(' / ')||'支付方式待核实';
  return '<strong data-china-card-status="'+status+'">'+readinessEscape(label)+'</strong><span>'+readinessEscape(methods)+(row?.payment.status==='historical_official_only'?'（历史官方资料，当前方式待核实）':'')+'。卡组织和钱包支持不保证中国发卡获批；扣款不明先查订单，勿重复试付。</span>';
}
function paymentFeasibilityMarkup(offer={}){
  const key=String(++readinessSequence);readinessContexts.set(key,offer);
  return '<div class="payment-feasibility" data-feasibility-context="'+key+'">'+paymentFeasibilityContent(offer)+'</div>';
}
