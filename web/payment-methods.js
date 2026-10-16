'use strict';
// Payment claims are isolated from delivery, eligibility and price calculations.
// A brand, a card logo or another country's checkout never supplies this market's policy.
const PAYMENT_BASE=new URL('./',document.currentScript.src);
const PAYMENT_REQUIRED=Object.freeze({cards:'银行卡／卡组织',china_issued_cards:'中国大陆发行卡',paypal:'PayPal',apple_pay:'Apple Pay',google_pay:'Google Pay',alipay:'支付宝 Alipay',wechat_pay:'微信支付 WeChat Pay',unionpay:'银联 UnionPay',bank_transfer_local:'银行转账／本地支付',gift_cards:'礼品卡',instalments:'分期付款'});
const PAYMENT_STATUSES=Object.freeze({supported:'官方列明支持',conditional:'有条件／需核对',not_supported:'官方明确不支持',unknown:'待核实',historical:'历史资料，当前待核实'});
const PAYMENT_EVIDENCE=Object.freeze({official_text:'官方文字说明',official_icons_only:'仅官方图标，未确认适用条件',historical_official:'历史官方资料',unavailable:'未取得可读官方依据',mixed:'逐项证据类型不同，请看说明'});
const PAYMENT_UNKNOWNS=Object.freeze({cards:'尚未确认本市场接受的信用卡、借记卡及卡组织完整清单。',china_issued_cards:'卡组织受支持不等于中国大陆发行卡获批；未确认发卡地、境外线上交易及 3DS 条件。',paypal:'尚未确认本市场 PayPal 入口及中国大陆注册账户是否适用。',apple_pay:'尚未确认本市场 Apple Pay 入口、设备地区及所绑定中国发行卡条件。',google_pay:'尚未确认本市场 Google Pay 入口、账户地区及所绑定中国发行卡条件。',alipay:'尚未确认是否接入支付宝及中国大陆支付宝账户范围。',wechat_pay:'尚未确认是否接入微信支付及中国大陆微信账户范围。',unionpay:'尚未确认银联入口、信用／借记卡范围及中国发行卡条件。',bank_transfer_local:'尚未确认银行转账、本地账户或当地支付方式清单及居民限制。',gift_cards:'尚未确认本市场礼品卡的购买、兑换及跨地区限制。',instalments:'尚未确认分期服务商、当地居民／信用审核及中国用户资格。'});
let paymentData=null,paymentChannels=null,paymentState='loading',paymentSequence=0;
const paymentContexts=new Map(),paymentDirectoryContexts=new Map();
function paymentEscape(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function paymentText(value,max=2500){return typeof value==='string'&&value.trim().length>0&&value.length<=max}
function paymentChinaValid(value){return paymentText(value)||(value&&typeof value==='object'&&!Array.isArray(value)&&paymentText(value.status,100)&&(value.evidence_class===undefined||paymentText(value.evidence_class,100))&&paymentText(value.note))}
function paymentDate(value){return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value&&Date.parse(value)<=Date.now()}
function paymentHost(value){return typeof value==='string'&&/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/.test(value)}
function paymentHttps(value,hosts){try{const u=new URL(value);return typeof value==='string'&&(u.href===value||u.origin===value)&&u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&(!hosts||hosts.includes(u.hostname))}catch{return false}}
function paymentEvidenceUrl(url,channel,urls){return paymentHttps(url,channel.reference_hosts)||(channel.reference_assets||[]).some(asset=>asset.url===url&&urls.includes(asset.owner_page))}
function validatePaymentChannels(data){
  if(!data||data.schema_version!==1||!paymentText(data.revision,100)||!Array.isArray(data.channels)||!data.channels.length||data.channels.length>100)throw Error('Invalid payment channel catalog');
  const codes=new Set();
  for(const c of data.channels){
    if(!/^[a-z][a-z0-9_]{0,70}$/.test(c.source_code)||codes.has(c.source_code)||!paymentText(c.merchant_name,200)||!paymentText(c.identity_note)||!Array.isArray(c.sales_regions)||!c.sales_regions.length||!c.sales_regions.every(x=>paymentText(x,200))||!Array.isArray(c.merchant_hosts)||!c.merchant_hosts.length||!c.merchant_hosts.every(paymentHost)||!Array.isArray(c.reference_hosts)||!c.reference_hosts.every(paymentHost)||!Array.isArray(c.directory_codes)||!c.directory_codes.every(x=>/^[a-z][a-z0-9_]{0,70}$/.test(x))||!paymentHttps(c.base_url,c.merchant_hosts))throw Error('Invalid payment channel identity');
    if(c.reference_assets!==undefined&&(!Array.isArray(c.reference_assets)||!c.reference_assets.every(asset=>paymentHttps(asset.url)&&paymentHttps(asset.owner_page,c.reference_hosts))))throw Error('Invalid owned payment asset');
    codes.add(c.source_code);
  }
  return data;
}
function validatePaymentData(data,catalog=paymentChannels){
  if(!catalog||!data||data.schema_version!==1||!paymentText(data.revision,100)||!paymentDate(data.checked_at)||!paymentText(data.payment_caveat)||!Array.isArray(data.entries)||data.entries.length>150)throw Error('Invalid payment data');
  const keys=new Set();
  for(const row of data.entries){
    const channel=catalog.channels.find(x=>x.source_code===row.source_code),key=JSON.stringify([row.source_code,row.scope,row.sales_region]);
    if(!channel||keys.has(key)||!paymentText(row.merchant_name,200)||!['market','merchant'].includes(row.scope)||!paymentText(row.scope_note)||!Object.hasOwn(PAYMENT_EVIDENCE,row.merchant_evidence_status)||!Array.isArray(row.merchant_hosts)||!row.merchant_hosts.length||!row.merchant_hosts.every(x=>channel.merchant_hosts.includes(x))||new Set(row.merchant_hosts).size!==row.merchant_hosts.length||!Array.isArray(row.scope_evidence_urls)||!row.scope_evidence_urls.every(x=>paymentHttps(x,channel.reference_hosts)))throw Error('Invalid payment merchant scope');
    if(row.scope==='market'?!channel.sales_regions.includes(row.sales_region):(row.sales_region!==null||!row.scope_evidence_urls.length||!['official_text','mixed'].includes(row.merchant_evidence_status)))throw Error('Payment market scope needs official evidence');
    if(!Array.isArray(row.methods)||row.methods.length<Object.keys(PAYMENT_REQUIRED).length||row.methods.length>60)throw Error('Incomplete payment matrix');
    keys.add(key);const methods=new Set();
    for(const method of row.methods){
      if(!/^[a-z][a-z0-9_]{0,70}$/.test(method.method_key)||methods.has(method.method_key)||!paymentText(method.name,200)||!Object.hasOwn(PAYMENT_STATUSES,method.status)||!paymentText(method.note)||!paymentChinaValid(method.china_applicability)||!paymentText(method.account_region_constraints)||!Array.isArray(method.evidence_urls)||!method.evidence_urls.every(url=>paymentEvidenceUrl(url,channel,method.evidence_urls))||!(paymentDate(method.checked_at)||(method.checked_at===null&&method.status==='unknown'&&!method.evidence_urls.length)))throw Error('Invalid payment method evidence');
      for(const field of ['card_networks','networks'])if(method[field]!==undefined&&(!Array.isArray(method[field])||method[field].length>30||!method[field].every(value=>paymentText(value,100))))throw Error('Invalid card network details');
      for(const field of ['evidence_class','merchant_evidence_detail'])if(method[field]!==undefined&&!paymentText(method[field]))throw Error('Invalid payment evidence detail');
      if(method.status!=='unknown'&&(!method.evidence_urls.length||!method.checked_at))throw Error('Payment claim requires dated evidence');
      if(row.merchant_evidence_status==='unavailable'&&method.status!=='unknown')throw Error('Unavailable evidence cannot support a payment claim');
      if(row.merchant_evidence_status==='official_icons_only'&&['supported','not_supported'].includes(method.status))throw Error('Logos alone cannot prove support or rejection');
      if(row.merchant_evidence_status==='historical_official'&&!['historical','unknown'].includes(method.status))throw Error('Historical evidence cannot assert current support');
      if(method.merchant_evidence_status!==undefined&&!Object.hasOwn(PAYMENT_EVIDENCE,method.merchant_evidence_status))throw Error('Invalid per-method evidence type');
      if(method.merchant_evidence_status==='official_icons_only'&&['supported','not_supported'].includes(method.status))throw Error('Logo-only method must remain conditional or unknown');
      methods.add(method.method_key);
    }
    if(!Object.keys(PAYMENT_REQUIRED).every(key=>methods.has(key)))throw Error('Missing payment method category');
    if(row.channels!==undefined){
      if(!Array.isArray(row.channels)||row.channels.length<2||row.channels.length>10)throw Error('Invalid separate merchant channels');
      const hosts=new Set();
      for(const child of row.channels){
        if(child.channels||child.source_code!==row.source_code||child.sales_region!==row.sales_region||child.scope!==row.scope||!Array.isArray(child.merchant_hosts)||!child.merchant_hosts.every(host=>row.merchant_hosts.includes(host)&&!hosts.has(host)))throw Error('Mixed merchant subchannel scope');
        child.merchant_hosts.forEach(host=>hosts.add(host));
        const otherHosts=row.merchant_hosts.filter(host=>!child.merchant_hosts.includes(host));
        const childCatalog={...catalog,channels:catalog.channels.map(item=>item.source_code===row.source_code?{...item,reference_hosts:item.reference_hosts.filter(host=>!otherHosts.includes(host))}:item)};
        validatePaymentData({...data,entries:[child]},childCatalog);
      }
      if(row.merchant_hosts.some(host=>!hosts.has(host)))throw Error('Unbound aggregate merchant');
    }
  }
  return data;
}
function paymentMarket(value){return typeof value==='string'&&value.trim()?value:'未记录市场'}
function paymentPolicy(offer={}){
  if(!paymentData||!paymentChannels)return null;
  const channel=paymentChannels.channels.find(x=>x.source_code===offer.source_code);
  // Even an absent URL must not bypass merchant identity. Directory callers supply the registered URL.
  if(!channel||!paymentHttps(offer.url,channel.merchant_hosts))return null;
  const matching=paymentData.entries.flatMap(row=>row.channels||[row]).filter(row=>row.source_code===offer.source_code&&row.merchant_hosts.includes(new URL(offer.url).hostname));
  return matching.find(row=>row.scope==='market'&&row.sales_region===paymentMarket(offer.sales_region))||matching.find(row=>row.scope==='merchant')||null;
}
function paymentMissingReason(offer={}){
  if(paymentState==='loading')return '正在加载这家商店的支付说明，请稍候。';
  if(paymentState==='error')return '支付说明暂时无法加载，请稍后重试；付款前请在商家结账页确认。';
  const channel=paymentChannels?.channels.find(x=>x.source_code===offer.source_code);
  if(!channel)return '这家商店的身份与支付方式尚未确认，请先向品牌核实。';
  if(!paymentHttps(offer.url,channel.merchant_hosts))return '当前链接与已核实商店不一致，请返回商品重新选择。';
  if(!channel.sales_regions.includes(paymentMarket(offer.sales_region)))return '这份支付说明不适用于当前国家或地区，请在商家结账页确认。';
  return '尚未取得本商店、本市场可用的逐项支付依据；官网未列某方式也不等于明确不支持。';
}
function paymentDisplayText(value){
  const names={cash_on_delivery:'货到付款',cycle_to_work:'骑行通勤福利计划',gift_card_online_purchase:'在线购买礼品卡',paypal_cheque:'PayPal 电子支票',prepaid_cards:'预付卡',revolut_pay:'Revolut Pay',shop_pay:'Shop Pay',unionpay_debit:'银联借记卡',requires_eligible_foreign_account:'需符合资格的境外账户，中国本地账户不自动满足'};
  return names[value]||String(value).replaceAll('observed_market=JP/JPY','本次观察为日本站／日元报价');
}
function paymentEvidenceClassLabel(value){return ({official_confirmed:'官方文字有明确说明',page_visible_china_unknown:'当前订单及中国用户是否适用尚未确认',insufficient_evidence:'依据不足',explicitly_unsupported:'官方明确限制',historical_official:'历史官方依据',official_text:'官方文字',official_icons_only:'仅页面图标'})[value]||'具体条件请查看商家说明'}
function paymentEvidenceDetailLabel(value){return ({not_found:'未找到足够说明',hidden_template:'当前订单是否提供此方式尚未确认',footer_icons:'仅页脚图标',blocked:'页面访问受限',page_template:'当前订单是否提供此方式尚未确认'})[value]||(/^[a-z_]+$/.test(value)?'具体条件请查看本项说明':value)}
function paymentChinaLabel(value){
  if(value&&typeof value==='object'){
    // A merchant-wide rejection does not need separate China-account proof.
    // Keep the original restriction note without appending a contradictory default uncertainty label.
    const classification=value.evidence_class||'insufficient_evidence';
    const suffix=value.status==='not_supported'&&classification==='insufficient_evidence'?'':'（'+paymentEvidenceClassLabel(classification)+'）';
    return paymentChinaLabel(value.status)+'。'+paymentDisplayText(value.note)+suffix;
  }
  const labels={unknown:'中国卡／中国账户适用性待核实',not_supported:'官方明确不支持',supported:'官方有适用说明，仍须本笔交易授权',conditional:'有条件适用，请核对本项限制',historical:'仅历史资料，当前适用性待核实',requires_eligible_foreign_account:'需符合资格的境外账户，中国本地账户不自动满足',requires_local_account:'需当地适用账户',requires_local_residency:'需符合当地居民资格',not_applicable:'不适用本方式',unverified:'尚未核实中国用户适用性'};
  return labels[value]||(/^[a-z_]+$/.test(value)?'适用条件尚需核对，详见地区说明':value);
}
function paymentMethodsFor(offer={}){
  const row=paymentPolicy(offer);if(row)return row.methods;
  const reason=paymentMissingReason(offer);
  return Object.entries(PAYMENT_REQUIRED).map(([method_key,name])=>({method_key,name,status:'unknown',note:reason+' '+PAYMENT_UNKNOWNS[method_key],china_applicability:method_key==='china_issued_cards'?'未确认中国大陆发行卡；不得据卡组织或钱包标志推断获批。':'中国大陆发卡／账户适用性未确认，需按本方式核对。',account_region_constraints:'未取得本市场的发卡地、账户地区、账单地址或居民条件。',evidence_urls:[],checked_at:null}));
}
function paymentSummary(offer={}){
  const row=paymentPolicy(offer),methods=paymentMethodsFor(offer),china=methods.find(x=>x.method_key==='china_issued_cards');
  const status=({supported:'evidence',conditional:'conditional',not_supported:'no',unknown:'unknown',historical:'historical'})[china.status];
  const label=({supported:'中国发行卡：官方有适用说明，仍须本卡授权',conditional:'中国发行卡：有条件，先核对发卡与账户限制',not_supported:'中国发行卡：官方有明确限制',unknown:'中国发行卡：待核实',historical:'中国发行卡：仅历史依据，当前待核实'})[china.status];
  const current=methods.filter(x=>x.method_key!=='china_issued_cards'&&['supported','conditional'].includes(x.status));
  const names=current.slice(0,4).map(x=>paymentDisplayText(x.name)+(x.status==='conditional'?'（有条件）':''));
  const methodsLabel=names.length?'可核对的支付入口：'+names.join(' / ')+(current.length>4?'等；完整方式见下方':'')+'。':methods.some(x=>x.status==='historical')?'只有历史支付资料，当前方式需重新确认。':'尚无已确认的当前支付入口；逐项原因见下方。';
  const suitability=row?(china.status==='not_supported'?'中国用户判断：已有明确发卡限制，其他方式仍须分别看账户资格。':china.status==='supported'||china.status==='conditional'?'中国用户判断：存在适用说明或条件；不代表本次交易一定获批。':'中国用户判断：商家方式与中国发卡／账户资格分开核对，当前仍有未确认条件。'):paymentMissingReason(offer);
  return {status,label,methodsLabel,suitability,row,methods};
}
function paymentEvidenceLink(url,context,method,index){
  const embedded=paymentChannels?.channels.some(row=>(row.reference_assets||[]).some(asset=>asset.url===url));
  return '<a data-payment-link="'+context+'" data-payment-method="'+paymentEscape(method.method_key)+'" data-payment-evidence="'+index+'" href="'+paymentEscape(url)+'" target="_self" rel="noopener noreferrer">'+(embedded?'官方页面嵌入图':'官方依据 '+(index+1))+' →</a>';
}
function paymentMethodContent(method,context){
  const esc=paymentEscape,networks=method.card_networks||method.networks||[],evidenceClass=method.evidence_class;
  return '<div class="payment-method" data-payment-method-key="'+esc(method.method_key)+'"><dt>'+esc(paymentDisplayText(method.name))+' <span class="payment-status" data-payment-status="'+esc(method.status)+'">'+esc(PAYMENT_STATUSES[method.status])+'</span></dt><dd>'+
    '<p>'+esc(method.note)+'</p>'+
    (Array.isArray(networks)&&networks.length?'<p>记录的卡组织（条件见本项说明）：'+networks.map(esc).join(' / ')+'。不代表中国发行卡获批。</p>':'')+
    '<p><b>中国卡／账户：</b>'+esc(paymentChinaLabel(method.china_applicability))+'</p>'+
    '<p><b>地区条件：</b>'+esc(method.account_region_constraints)+'</p>'+
    (evidenceClass?'<p class="payment-method-meta">商家说明：'+esc(paymentEvidenceClassLabel(evidenceClass))+'</p>':'')+
    (method.merchant_evidence_detail?'<p class="payment-method-meta">使用前请确认：'+esc(paymentEvidenceDetailLabel(method.merchant_evidence_detail))+'</p>':'')+
    '<p class="payment-method-meta">核对日期：'+esc(method.checked_at||'未取得可核对资料')+(method.merchant_evidence_status?' · '+esc(PAYMENT_EVIDENCE[method.merchant_evidence_status]):'')+'</p>'+
    (method.evidence_urls.length?'<div class="payment-evidence-links">'+method.evidence_urls.map((url,i)=>paymentEvidenceLink(url,context,method,i)).join('')+'</div>':'<p class="payment-method-meta">本项暂无可引用的官方依据；不据此判定不支持。</p>')+'</dd></div>';
}
function paymentDetailsContent(offer,context){
  const result=paymentSummary(offer),row=result.row,esc=paymentEscape;
  return '<p class="payment-scope">'+esc(row?.merchant_name||offer.source_name||offer.source_code||'当前商店')+' · '+esc(offer.sales_region||'未记录市场')+'</p>'+
    (row?'<p class="payment-evidence-type">'+esc(PAYMENT_EVIDENCE[row.merchant_evidence_status])+'。'+esc(paymentDisplayText(row.scope_note))+'</p>':'<p>'+esc(paymentMissingReason(offer))+'</p>')+
    '<p class="payment-caveat">卡组织支持不等于中国发行卡获批；钱包也不能保证底层卡成功。页面未列或未见标志不等于明确不支持。最终能否付款，以商家结账页和支付机构授权结果为准。</p>'+
    '<dl class="payment-method-list">'+result.methods.map(method=>paymentMethodContent(method,context)).join('')+'</dl>';
}
function paymentPanelContent(offer,context,compact=true){
  const s=paymentSummary(offer),esc=paymentEscape;
  return (compact?'<span class="payment-market-scope">'+esc(s.row?.merchant_name||offer.source_name||offer.source_code||'当前商店')+' · '+esc(offer.sales_region||'未记录市场')+'</span>'+(['未核实','未记录市场'].includes(paymentMarket(offer.sales_region))&&s.row?'<span class="payment-market-scope">'+esc(paymentDisplayText(s.row.scope_note))+'</span>':'')+'<strong data-china-card-status="'+s.status+'">'+esc(s.label)+'</strong><span>'+esc(s.methodsLabel)+'</span><span class="payment-suitability">'+esc(s.suitability)+'</span><span class="payment-caveat">卡组织和钱包支持不保证中国发卡获批；扣款不明先查订单，勿重复试付。</span>':'')+'<details class="payment-method-details"><summary>查看全部支付方式、中国账户限制与依据</summary><div>'+paymentDetailsContent(offer,context)+'</div></details>';
}
function paymentMethodsMarkup(offer={},compact=true){
  const key=String(++paymentSequence);paymentContexts.set(key,{offer,compact});
  return '<div class="'+(compact?'payment-feasibility ':'')+'payment-matrix" data-payment-context="'+key+'">'+paymentPanelContent(offer,key,compact)+'</div>';
}
function paymentDirectoryContent(entry={}){
  const channels=paymentChannels?.channels.filter(x=>x.directory_codes.includes(entry.code))||[];
  if(!channels.length)return paymentMethodsMarkup({source_code:entry.code,source_name:entry.name_zh||entry.name,sales_region:'未核实',url:entry.shop_url||entry.official_url});
  return '<section class="source-payment-overview"><h4>这家商城怎么付款</h4>'+channels.map(channel=>{
    const grouped=paymentData?.entries.find(row=>row.source_code===channel.source_code&&row.channels);
    if(grouped)return '<p class="payment-identity-note">'+paymentEscape(grouped.scope_note)+'</p>'+grouped.channels.map(child=>{
      const url=child.scope_evidence_urls.find(value=>paymentHttps(value,child.merchant_hosts));
      return '<section class="payment-separate-merchant"><h5>'+paymentEscape(child.merchant_name)+'</h5><p class="payment-identity-note">'+paymentEscape(child.scope_note)+'</p>'+paymentMethodsMarkup({source_code:child.source_code,source_name:child.merchant_name,sales_region:child.sales_region,url})+'</section>';
    }).join('');
    return '<p class="payment-identity-note">'+paymentEscape(channel.identity_note)+'</p>'+channel.sales_regions.map(market=>paymentMethodsMarkup({source_code:channel.source_code,source_name:channel.merchant_name,sales_region:market,url:channel.base_url})).join('');
  }).join('')+'</section>';
}
function paymentDirectoryMarkup(entry={}){const key=String(++paymentSequence);paymentDirectoryContexts.set(key,entry);return '<div data-payment-directory="'+key+'">'+paymentDirectoryContent(entry)+'</div>'}
function refreshPaymentMarkup(){
  // Preserve a user's expanded state when asynchronous data finishes loading.
  document.querySelectorAll('[data-payment-directory]').forEach(node=>{const entry=paymentDirectoryContexts.get(node.dataset.paymentDirectory);if(entry)node.innerHTML=paymentDirectoryContent(entry)});
  document.querySelectorAll('[data-payment-context]').forEach(node=>{const context=paymentContexts.get(node.dataset.paymentContext);if(context){const expanded=node.querySelector?.('.payment-method-details')?.open;node.innerHTML=paymentPanelContent(context.offer,node.dataset.paymentContext,context.compact);if(expanded){const details=node.querySelector?.('.payment-method-details');if(details)details.open=true}}});
  // Payment refresh never re-renders routes, changes selection, or steals focus.
}
function allowedPaymentLink(link){
  if(paymentState!=='ready'||!link?.isConnected||!document.getElementById('sheet')?.classList.contains('open')||!document.getElementById('sheetBody')?.contains(link))return null;
  const context=paymentContexts.get(link.dataset.paymentLink),row=context&&paymentPolicy(context.offer),method=row?.methods.find(x=>x.method_key===link.dataset.paymentMethod);
  const index=link.dataset.paymentEvidence,url=link.getAttribute('href'),channel=paymentChannels?.channels.find(x=>x.source_code===row?.source_code);
  if(!/^\d+$/.test(index||'')||!channel||method?.evidence_urls[Number(index)]!==url||!paymentEvidenceUrl(url,channel,method.evidence_urls))return null;
  return {url,checkedAt:method.checked_at,sourceCode:row.source_code};
}
function guardPaymentExit(event){
  const link=event.target.closest?.('a[data-payment-link]');if(!link||(event.type==='auxclick'&&event.button!==1))return;
  event.preventDefault();const allowed=allowedPaymentLink(link);if(!allowed)return;
  showExternalExit({url:allowed.url,kind:'reference',label:'支付方式官方依据',trigger:link,sourceNote:'本项资料核对：'+allowed.checkedAt+'。仅适用该商家及记录市场；历史资料、图标和账户地区限制见逐项说明。',note:'即将查看官方支付说明。方式受支持不代表中国发行卡或中国账户一定可用。请在商家页面自行完成账户与付款操作。',validate:()=>allowedPaymentLink(link)?.url===allowed.url,onConfirm:()=>{if(typeof saveBrowseState==='function')saveBrowseState()}});
}
for(const type of ['click','auxclick'])document.addEventListener(type,guardPaymentExit);
async function loadPaymentMethods(){
  try{
    const read=async(name,max)=>{const response=await fetch(new URL(name,PAYMENT_BASE).href,{cache:'no-store'});if(!response.ok)throw Error('Payment data unavailable');const raw=await response.text();if(raw.length>max)throw Error('Payment data too large');return JSON.parse(raw)};
    const [channels,data]=await Promise.all([read('payment-channels.json',100000),read('payment-methods.json',1500000)]);
    paymentChannels=validatePaymentChannels(channels);paymentData=validatePaymentData(data,paymentChannels);paymentState='ready';
  }catch{paymentData=null;paymentState='error'}
  refreshPaymentMarkup();
}
loadPaymentMethods();
