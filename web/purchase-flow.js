'use strict';
// Route decisions use an exact saved offer. Planning is never a stock/payment
// assertion; unknown charges remain unknown and never enter a complete total.
let registrationExitContext=null,restoringPurchase=false;
const ROUTE_LABELS=Object.freeze({domestic:'中国官网配送',direct:'官网直邮内地',forwarding:'海外转运到内地',hongkong:'香港途径'});
const ROUTE_STATUSES=Object.freeze({confirmed:'已确认',conditional:'有条件',unknown:'待核实',prohibited:'不可用'});
const ROUTE_HELP=Object.freeze([
  {key:'hk-customs',label:'香港海关：货物清关',url:'https://www.customs.gov.hk/en/service-enforcement-information/cargo-clearance/'},
  {key:'hk-post',label:'香港邮政：寄递报关资料',url:'https://www.hongkongpost.hk/tc/sending_mail/clearance/cn22.html'},
  {key:'mainland-post',label:'政府网：个人寄递进境限值更新',url:'https://big5.www.gov.cn/gate/big5/www.gov.cn/lianbo/bumen/202411/content_6990180.htm'},
  {key:'carry',label:'税务机关：港澳入境旅客行李规则',url:'https://liaoning.chinatax.gov.cn/art/2024/6/27/art_5869_7556.html'}
]);
function routeOriginal(value){return value&&/^[A-Z]{3}$/.test(value.currency)&&value.amount!==null&&value.amount!==undefined&&value.amount!==''&&typeof value.amount!=='boolean'&&Number.isFinite(Number(value.amount))&&Number(value.amount)>=0?value.currency+' '+Number(value.amount).toFixed(value.currency==='JPY'?0:2):'待确认'}
function routePolicy(offer){return typeof readinessPolicy==='function'?readinessPolicy(offer):null}
function routeMerchantMatches(offer,code,hosts){try{return offer.source_code===code&&hosts.includes(new URL(offer.url).hostname)}catch{return false}}
function routeUsMarketMatches(offer,code,hosts,path){if(!routeMerchantMatches(offer,code,hosts))return false;try{return new URL(offer.url).pathname.startsWith(path)}catch{return false}}
function routeProhibition(offer){
  if(routeUsMarketMatches(offer,'trek',['www.trekbikes.com','trekbikes.com'],'/us/en_US/'))return {forwarding:{status:'prohibited',note:'Trek 美国站只寄美国地址，明确禁止转运地址；香港中转也不能绕过。'},sources:['https://www.trekbikes.com/us/en_US/customer_service/']};
  const row=routePolicy(offer);if(row?.forwarding.status==='prohibited')return row;
  // Restrictive fallback only: failure to load optional summaries must never
  // turn a known prohibited merchant route into a selectable plan.
  if(routeMerchantMatches(offer,'poc',['poc.com','www.poc.com']))return {forwarding:{status:'prohibited',note:'POC 官方条款禁止 re-shippers / package forwarding services（2026-10-15 核对）；香港中转也不能绕过。'},sources:['https://poc.com/en/terms-and-conditions']};
  // A merchant's explicit anti-reshipper terms remain a safety restriction,
  // even if this offer's currency label differs. Never apply to other retailers.
  if(typeof readinessData==='undefined'||!readinessData)return null;
  return readinessData.entries.find(item=>item.sourceCode===offer.source_code&&item.forwarding.status==='prohibited'&&(()=>{try{return item.merchantHosts.includes(new URL(offer.url).hostname)}catch{return false}})())||null;
}
function routeDomesticChina(offer={}){
  if(offer.source_code!=='decathlon_cn'||offer.sales_region!=='中国大陆 CNY 报价'||offer.price?.currency!=='CNY')return false;
  try{const u=new URL(offer.url);return u.protocol==='https:'&&u.hostname==='www.decathlon.com.cn'&&!u.username&&!u.password&&!u.port&&offer.url.startsWith('https://www.decathlon.com.cn/')&&routeOriginal(offer.price)!=='待确认'}catch{return false}
}
function domesticPaymentMarkup(){return '<div class="payment-feasibility domestic-payment"><strong>中国官网结算</strong><p>官方帮助列示支付宝、微信、银联及部分银行卡／Visa；本件订单可用方式尚未实测，请在结账确认。</p><details class="domestic-shopping-help"><summary>注册、配送与退货须知</summary><p><strong>注册：</strong>官网购物指南按注册、登录后下单；免注册购买未核实。</p><p><strong>配送：</strong>仅限中国大陆。顺丰普通配送按单笔实付满 99 元免运费，未满收 8 元，自行车除外。门店极速达等其他方式另计，能否配送及实际运费以收货地址和结账页面为准。</p><p><strong>退货：</strong>按 2026 年 3 月 18 日生效规则，适用于中国大陆官方渠道迪卡侬自有品牌。商品须未经使用、洗涤或损坏，包装吊牌完整、不影响二次销售，并有有效购买凭证；特殊商品及活动另看具体约定。</p><p>官网订单可退货后重买；官方线上商品也可按规则到门店办理，非原购买店铺退货以礼品卡退款。个人原因退货承担往来邮费，原包邮商品只承担退货邮费；商家责任由商家承担。</p><p>依据官网购物、配送及退换货帮助，核对于 2026-10-16。优惠资格、运费和最终金额请在官网确认。</p></details></div>'}
function domesticRouteOptions(quote){
  const o=quote?.offer||{};if(!routeDomesticChina(o))return [];
  return [{id:'domestic',label:ROUTE_LABELS.domestic,status:'conditional',note:'中国大陆官网报价。请按所选尺码和实际收货地址核对库存、国内运费及配送范围。',advantages:'在中国官网按人民币结算，购买与售后直接联系该商家。',tradeoffs:'具体运费、优惠和配送范围以本件商品结账页面为准。',costs:[[(currentPriceEvidence(o)?'所选规格商品价':'上次记录商品价（官网核对）'),routeOriginal(o.price)],['国内运费','待确认'],['其他结账费用（如有）','待确认']],total:null}];
}
function routeOptions(quote){
  if(quote?.offer?.source_code==='decathlon_cn')return domesticRouteOptions(quote);
  const o=quote?.offer||{},policy=routePolicy(o),prohibited=routeProhibition(o),components=quote?.landed_cost?.components||[];
  const changed=[o.shipping_to_china,o.china_issued_card,o.card_networks_evidence].some(check=>/原文已变化|正在复核/.test(check?.note||''));
  const component=key=>components.find(item=>item.key===key);
  const amount=(key,fallback)=>{const c=component(key);return c?.status==='included'?'已包含（有依据，无新增费用）':routeOriginal(c?.original||fallback)+(c?.status==='policy_estimate'?'（政策参考，结账核对）':'')};
  const ship=o.shipping_to_china||{};
  let direct=routeUsMarketMatches(o,'trek',['www.trekbikes.com','trekbikes.com'],'/us/en_US/')||routeUsMarketMatches(o,'specialized',['www.specialized.com','specialized.com'],'/us/en/')||ship.status==='no'||policy?.directChina.status==='prohibited'||routeMerchantMatches(o,'maap',['maap.cc','www.maap.cc'])?'prohibited':changed?'unknown':policy?.directChina.status==='confirmed'||policy?.directChina.status==='conditional_checkout'||ship.status==='yes'?'conditional':'unknown';
  // Confirmed is reserved for item/address-scoped evidence with complete fees;
  // catalogue-wide destination lists only support a conditional route.
  const verifiedCosts=['product','shipping','tax','clearance','payment'].every(key=>{const c=component(key);return c&&['quoted','included'].includes(c.status)&&c.cny!==null&&c.cny!==undefined&&Number.isFinite(Number(c.cny))&&Number(c.cny)>=0});
  if(direct==='conditional'&&ship.scope==='offer'&&typeof readinessObservation==='function'&&readinessObservation(ship.checked_at)&&verifiedCosts&&offerAvailable(quote)&&currentPriceEvidence(o))direct='confirmed';
  const forwarding=prohibited?'prohibited':changed?'unknown':policy?.forwarding.status==='confirmed'||policy?.forwarding.status==='conditional_checkout'?'conditional':'unknown';
  const directShipping=o.shipping||(!changed&&policy?.directChina.shippingAmount!==undefined?{amount:policy.directChina.shippingAmount,currency:policy.directChina.shippingCurrency}:null);
  const product=routeOriginal(o.price),unknown=['商品外当地税','商家至仓库运费','入库／仓储／合箱费','国际运费及附加费','保障费（如选用）','内地进口税与清关费','支付换汇／银行卡费用'];
  return [
    {id:'direct',label:ROUTE_LABELS.direct,status:direct,note:direct==='prohibited'?'本商店／报价规则不支持直邮中国大陆。':changed?'配送规则有变化，原结论暂停使用。':policy?.directChina.note||ship.note||'须按本件商品、卖家和实际中国地址核实配送。',advantages:'链路较短，订单与配送责任较容易核对。',tradeoffs:'可能不支持中国地址；单件运费较高，退货邮费另核。',costs:[[(currentPriceEvidence(o)?'所选规格商品价':'上次记录商品价（官网核对）'),product],['中国大陆运费',amount('shipping',directShipping)+(!o.shipping&&!component('shipping')&&directShipping?'（官网政策参考，结账核对）':'')],['中国进口税',amount('tax',o.tax)],['清关／代垫手续费',amount('clearance',o.clearance)],['支付换汇／银行卡费用',amount('payment',null)]],total:direct==='confirmed'&&verifiedCosts?['product','shipping','tax','clearance','payment'].reduce((sum,key)=>sum+Number(component(key).cny),0):null},
    {id:'forwarding',label:ROUTE_LABELS.forwarding,status:forwarding,note:prohibited?prohibited.forwarding.note:policy?.forwarding.note||'商家是否允许转运、可用仓库及内地线路都待核实；可选作计划，不能据此下单。',advantages:'商家允许时可接收当地配送商品；合箱可能减少重复运费。',tradeoffs:'多段责任、体积重与仓储费用；国际退件更复杂，转运不能解决拒付。',costs:[['当前市场商品参考',product],...unknown.map(label=>[label,'待确认'])],total:null},
    {id:'hongkong',label:ROUTE_LABELS.hongkong,status:prohibited?'prohibited':'unknown',note:prohibited?'商家禁止转运；香港中转也不能绕过该限制。':o.source_code==='maap'&&policy?'MAAP 官方配送页列有香港；转运仓许可、香港再寄内地及本件费用仍待核实。':'商家能否送香港、香港收件安排及进入内地的下一段均待核实。',advantages:'适合已有可靠香港收件安排或原有赴港行程的人。',tradeoffs:'到香港不等于到内地；再寄、保管或本人交通另计，不保证更便宜。',costs:[['当前市场商品参考（非香港报价）',product],['香港结账商品价／当地税','待确认'],['商家至香港运费','待确认'],['香港收件／保管／本地运输','待确认'],['香港再寄内地或本人交通','待确认'],['内地税费与清关','待确认'],['支付换汇／银行卡费用','待确认']],total:null}
  ];
}
function purchaseIdentity(quote){const o=quote?.offer;return o?JSON.stringify([o.offer_id,o.source_code,o.sales_region,o.url,o.price?.amount,o.price?.currency,o.verification_identity||null,o.stock,o.shipping_to_china?.status,o.china_issued_card?.status,(quote.landed_cost?.components||[]).map(c=>[c.key,c.status,c.original?.amount,c.original?.currency,c.cny])]):null}
function savePurchaseState(stage='route'){
  try{
    if(typeof saveBrowseState==='function')saveBrowseState();
    const g=guideContext,old=history.state&&typeof history.state==='object'?history.state:{};
    if(!g?.detail||!g.quote)return;
    history.replaceState({...old,bikehuntPurchase:{version:1,productId:g.detail.product_id,variantId:g.detail.variant_id,offerId:g.quote.offer.offer_id,sourceCode:g.quote.offer.source_code,url:g.quote.offer.url,identity:purchaseIdentity(g.quote),route:g.route||null,stage,reference:!!g.reference,invalidated:!!g.invalidated}},'');
  }catch{}
}
function rememberPurchaseDetail(detail,selected,bundleSelection=null){
  if(restoringPurchase)return;
  try{const old=history.state&&typeof history.state==='object'?history.state:{},saved=old.bikehuntPurchase;history.replaceState({...old,bikehuntPurchase:{version:1,productId:detail.product_id,variantId:selected?detail.variant_id:null,offerId:saved?.productId===detail.product_id&&saved.variantId===detail.variant_id?saved.offerId:null,route:saved?.productId===detail.product_id&&saved.variantId===detail.variant_id?saved.route:null,stage:'detail',bundleSelection}},'');if(typeof saveBrowseState==='function')saveBrowseState()}catch{}
}
function cancelPurchaseContext(){registrationExitContext=null;guideContext=null}
function clearPurchaseState(){cancelPurchaseContext();try{const old={...(history.state||{})};delete old.bikehuntPurchase;history.replaceState(old,'')}catch{}}
function routeUsableContext(){return guideContext&&publicProductVisible(guideContext.detail)&&!guideContext.invalidated&&referenceAvailable(guideContext.quote)&&(guideContext.reference||offerAvailable(guideContext.quote))}
function routeStepMarkup(stage,domestic=false){return '<ol class="purchase-step-order" aria-label="购买步骤">'+['商品与尺码',domestic?'国内配送':'比较运输路线','注册图解','确认离站'].map((label,index)=>'<li'+(index===stage?' aria-current="step"':'')+'>'+String(index+1)+' '+label+'</li>').join('')+'</ol>'}
function hongKongNotesMarkup(){return '<details class="route-hk-notes"><summary>香港收货、再寄与本人携带有什么不同？</summary><p>香港收货／自提：先确认收件人同意、服务支持、保管期和费用；这里只完成香港交付。</p><p>香港再寄内地：另核正式寄递线路、真实货值申报、进口税与清关，不使用旅客行李额度。个人寄递进境 2,000 元是限值，不是免税额度；超限或不可分割单件由海关审核。</p><p>本人赴港携带入境：按旅客身份、年龄、全部个人合理自用行李及往返情况核定；不能把旅客额度套到邮寄。此处不自动计算免税额，不建议为省税专程赴港。</p><p>香港一般进口无关税，不代表进入内地免税。MyUS／forward2me 的寄香港线路不证明提供香港仓再寄内地；本次未核实 tenso 香港线路。</p><p>官方资料核对：2026-10-15。具体货品、价值、收件安排及费用仍需逐单确认。</p><ul>'+ROUTE_HELP.map(row=>'<li><a data-route-help="'+row.key+'" href="'+e(row.url)+'" target="_self" rel="noopener noreferrer">'+e(row.label)+' →</a></li>').join('')+'</ul></details>'}
function renderRouteComparison(){
  if(!guideContext)return;
  const g=guideContext,o=g.quote.offer,domestic=o.source_code==='decathlon_cn',choices=routeOptions(g.quote).map(row=>g.invalidated&&row.status!=='prohibited'?{...row,status:'unknown',total:null,note:'新报价尚未重新核实；旧费用已停用，请返回商品重新选择。'}:row),selected=choices.find(row=>row.id===g.route);
  if(!selected||selected.status==='prohibited')g.route=null;
  const valid=routeUsableContext();
  const cards=choices.map(row=>'<section class="route-card" data-route="'+row.id+'" data-route-status="'+row.status+'"><div class="route-card-heading"><h3>'+row.label+'</h3><span class="tag '+(row.status==='prohibited'?'no':row.status==='confirmed'?'ok':'wait')+'">'+ROUTE_STATUSES[row.status]+'</span></div><p>'+e(row.note)+'</p><p><b>优点：</b>'+e(row.advantages)+'<br><b>需权衡：</b>'+e(row.tradeoffs)+'</p><details class="route-cost-detail"><summary>费用组成 · '+(row.total===null?'完整总额待确认':e(cny(row.total)))+'</summary>'+(g.invalidated?'<p>报价已变化或无法重新核对，旧金额已停用。</p>':'<dl class="costs">'+row.costs.map(([label,value])=>'<div><dt>'+e(label)+'</dt><dd>'+e(value)+'</dd></div>').join('')+'</dl>')+'<p>不同币种不直接相加。未知费用不等于 0；不把未齐费用称为最终到手价。</p></details><button type="button" data-route-select="'+row.id+'" aria-pressed="'+(g.route===row.id)+'" '+(row.status==='prohibited'||!valid?'disabled':'')+'>'+(row.status==='prohibited'?'此路线不可选':g.route===row.id?'已选此路线':row.status==='unknown'?'选作待核实计划':'选择此路线')+'</button></section>').join('');
  openPanel(domestic?'确认国内配送':'比较运输路线', '<article id="routeComparison">'+routeStepMarkup(1,domestic)+'<p class="route-selected-product"><strong>'+e(g.detail.name_zh||g.detail.name||o.name||'当前商品')+'</strong><br>'+e(o.source_name)+' · '+e(o.sales_region||'报价市场未记录')+' · 尺码 '+e(typeof compactVariantLabel==='function'?compactVariantLabel(g.detail.identity?.size):g.detail.identity?.size||'待核实')+' · '+e(g.detail.identity?.color||'颜色原站核对')+'</p>'+(typeof originalVariantMarkup==='function'?originalVariantMarkup(g.detail.identity?.size,'bundle-original'):'')+'<p class="route-stock-note">'+e(g.invalidated?'报价已变化或暂时无法核对，请返回商品重新选择。':g.reference?'库存待核实；历史报价只作参考，不能视为所选尺码有货。':inventoryLabel(o))+'</p>'+(domestic?domesticPaymentMarkup():paymentFeasibilityMarkup(o))+(domestic&&!choices.length?'<p role="alert">当前中国官网报价信息不完整，请返回商品重新选择。</p>':'')+'<div class="route-comparison-grid">'+cards+'</div>'+(domestic?'':hongKongNotesMarkup())+(g.route==='direct'&&!g.invalidated?'<details class="route-budget"><summary>直邮费用预算与依据（条件估算）</summary>'+landedCostMarkup(g.quote)+'</details>':'')+(domestic?'':forwardingExplainerMarkup())+(g.invalidated||domestic?'':'<details class="route-policy"><summary>支付与配送的详细依据</summary>'+purchaseReadinessMarkup(o)+'</details>')+'<div class="guide-actions"><button type="button" id="routeBack">← 返回商品与尺码</button><button type="button" id="routeContinue" '+(!g.route||!valid?'disabled':'')+'>'+((selected?.status==='confirmed'&&o.china_issued_card?.status==='yes'&&!g.reference)?'去官网':'去官网核实')+' →</button></div><p class="service-note">'+(domestic?'所选商品与尺码已保留；国内运费及支付条件请到官网核对。下一步查看账户说明。':'选路线只保存计划；商家许可、库存、银行卡授权和完整费用仍需核实。下一步才显示这家商店的注册说明。')+'</p></article>',true);
  document.querySelectorAll('[data-route-select]').forEach(button=>button.onclick=()=>selectPurchaseRoute(button.dataset.routeSelect));
  document.getElementById('routeBack').onclick=()=>{const detail=g.detail;registrationExitContext=null;loadDetail(detail.product_id,detail.variant_id)};
  document.getElementById('routeContinue').onclick=continuePurchaseRoute;
  savePurchaseState('route');
}
function selectPurchaseRoute(id){if(!routeUsableContext()||!routeOptions(guideContext.quote).some(row=>row.id===id&&row.status!=='prohibited'))return;guideContext.route=id;renderRouteComparison();document.querySelector('[data-route-select="'+id+'"]')?.focus()}
function continuePurchaseRoute(){if(!routeUsableContext()||!routeOptions(guideContext.quote).some(row=>row.id===guideContext.route&&row.status!=='prohibited'))return;openRegistrationInterstitial({kind:'product',guide:guideContext,identity:purchaseIdentity(guideContext.quote),url:merchantUrl(guideContext.quote.offer.url)})}
function startReferenceRoute(quote){
  if(!referenceAvailable(quote))return;
  const detail=currentProduct?.product_id===quote.reference_product_id?currentProduct:{product_id:quote.reference_product_id,variant_id:quote.reference_variant_id,name:quote.offer.name,identity:quote.offer.identity||{},offers:[quote]};
  guideContext={detail,quote,book:null,route:null,reference:!offerAvailable(quote)};renderRouteComparison();
}
function openAmazonRegistration(search){
  const market=AMAZON_SEARCH_MARKETS.find(row=>row.searches.includes(search));if(!market)return;
  openRegistrationInterstitial({kind:'amazon',search,market,url:search.url});
}
function validRegistrationContext(context){
  if(!context||registrationExitContext!==context||!sheet.classList.contains('open'))return false;
  if(context.kind==='amazon')return AMAZON_SEARCH_MARKETS.some(market=>market===context.market&&market.searches.some(search=>search===context.search&&search.url===context.url));
  return context.kind==='product'&&guideContext===context.guide&&routeUsableContext()&&context.identity===purchaseIdentity(guideContext.quote)&&merchantUrl(guideContext.quote.offer.url)===context.url&&routeOptions(guideContext.quote).some(row=>row.id===guideContext.route&&row.status!=='prohibited');
}
function openRegistrationInterstitial(context){
  const o=context.kind==='product'?context.guide.quote.offer:{source_code:context.market.code,source_name:'Amazon '+context.market.name,sales_region:context.market.salesRegion,url:'https://'+context.market.host+'/'};
  const domestic=context.kind==='product'&&routeDomesticChina(o);
  registrationExitContext=context;
  openPanel('去官网前，查看注册说明','<article id="registrationInterstitial">'+routeStepMarkup(2,domestic)+'<h2>'+e(o.source_name)+' · '+e(o.sales_region||'报价市场未记录')+'</h2><p>'+e(context.kind==='amazon'?'即将打开本站点的官方搜索，未选择具体商品、卖家或尺码，没有路线报价或可购买保证。':'已选运输计划：'+ROUTE_LABELS[context.guide.route]+'。请先在原站核实路线、商品与费用；注册并不证明可以付款或配送。')+'</p>'+(context.kind==='product'&&typeof compactVariantLabel==='function'?'<p class="bundle-selection-summary">已选规格：'+e(compactVariantLabel(context.guide.detail.identity?.size))+'</p>':'')+(domestic?domesticPaymentMarkup():paymentFeasibilityMarkup(o))+(domestic?'':registrationHelpMarkup(o.source_code,o.sales_region))+'<p class="registration-instructions">'+(domestic?'在迪卡侬中国官网按页面提示选择登录或注册；已有账户可直接登录。是否需要账户、验证方式和字段以官网当前页面为准。请自行填写资料并阅读条款；本站不收集账号、密码、地址或支付资料。':'在官方域名找到 Account / Sign in（账户／登录）。有账户可登录；需要新账户时再找 Create account / Register（创建账户／注册），是否必须注册、验证方式和字段以本市场当前页面为准。请自行填写真实资料并阅读条款；本站不收集账号、密码、地址或卡号。')+'</p><details class="registration-disclaimer"><summary>购买提示与免责声明</summary><p>'+e(PURCHASE_DISCLAIMER)+'</p></details><div class="guide-actions"><button type="button" id="registrationCancel">取消，返回'+(context.kind==='amazon'?'搜索入口':domestic?'国内配送':'运输路线')+'</button><button type="button" id="registrationContinue">确认后继续去官网 →</button></div><p class="service-note">下一次确认会在当前标签页打开原商家页面；不会代你注册、付款或下单。</p></article>',true);
  document.getElementById('registrationCancel').onclick=cancelRegistrationExit;
  document.getElementById('registrationContinue').onclick=continueRegistrationExit;
  // The exact-market section is ready to read; a public-account reference stays
  // separately collapsed and explicitly cannot establish a market-specific flow.
  const exact=document.querySelector('#registrationInterstitial .registration-guide[data-registration-scope="market"]');if(exact)exact.open=true;
  if(context.kind==='product')savePurchaseState('registration');
}
function cancelRegistrationExit(){const context=registrationExitContext;registrationExitContext=null;if(context?.kind==='product'&&guideContext===context.guide)renderRouteComparison();else if(context?.kind==='amazon')showAmazonChannels()}
function continueRegistrationExit(){
  const context=registrationExitContext;if(!validRegistrationContext(context))return;
  const product=context.kind==='product',offer=product?context.guide.quote.offer:null;
  const note=product?'所选运输路线仍需商家核实；库存、尺码、价格、支付及到手费用以原站为准。':'Amazon 官方搜索入口，尚无选定商品或路线报价。';
  showExternalExit({url:context.url,kind:product?'merchant':'amazon',label:product?offer.source_name+' · '+(context.guide.detail.name_zh||context.guide.detail.name||offer.name||'当前商品'):'Amazon '+context.market.name,
    sourceCode:offer?.source_code,image:product?(context.guide.detail.image||offer.image||''):'',note,
    validate:()=>validRegistrationContext(context),onCancel:cancelRegistrationExit,
    restoreFocus:()=>product?document.getElementById('routeContinue'):document.querySelector('[data-amazon-search-link="'+context.search.key+'"]'),
    onConfirm:()=>{if(product)savePurchaseState('route');else saveBrowseState()}});
}
async function restorePurchaseState(){
  const saved=history.state?.bikehuntPurchase;
  if(!saved||saved.version!==1||typeof saved.productId!=='string'||saved.productId.length>200||saved.variantId!==null&&(typeof saved.variantId!=='string'||saved.variantId.length>200)||!['detail','route','registration'].includes(saved.stage))return;
  restoringPurchase=true;
  try{
    openPanel('恢复所选商品','<p class="loading">正在重新核对所选商品、尺码与路线…</p>',true);const sequence=detailSequence;
    const detail=await getJson('/api/catalog/'+encodeURIComponent(saved.productId)+(saved.variantId?'?variant_id='+encodeURIComponent(saved.variantId):''));
    if(sequence!==detailSequence||!sheet.classList.contains('open'))return;
    if(detail.product_id!==saved.productId||saved.variantId&&detail.variant_id!==saved.variantId)throw Error('Selected product identity changed');
    if(!publicProductVisible(detail))throw Error('商品暂未公开');
    currentProduct=detail;
    if(saved.stage==='detail'){await loadDetail(detail.product_id,saved.variantId,{bundleSelection:saved.bundleSelection});return}
    const quote=detail.offers.find(row=>row.offer.offer_id===saved.offerId&&row.offer.source_code===saved.sourceCode&&row.offer.url===saved.url);
    if(!quote||quote.offer.stock==='out_of_stock'){await loadDetail(detail.product_id,saved.variantId);return}
    quote.reference_product_id=detail.product_id;quote.reference_variant_id=detail.variant_id;
    guideContext={detail,quote,book:null,route:Object.hasOwn(ROUTE_LABELS,saved.route)?saved.route:null,reference:!offerAvailable(quote),invalidated:saved.invalidated===true||purchaseIdentity(quote)!==saved.identity||(typeof bundleQuoteAllowed==='function'&&!bundleQuoteAllowed(quote))};
    renderRouteComparison();
    if(saved.stage==='registration'&&!guideContext.invalidated)continuePurchaseRoute();
  }catch{openPanel('暂时无法恢复报价','<p>旧报价与购买入口已停用，请关闭后重新打开商品。筛选条件仍保留。</p>')}finally{restoringPurchase=false}
}
function refreshPurchaseRoutePolicy(){if(guideContext&&document.getElementById('routeComparison'))renderRouteComparison();if(registrationExitContext&&!validRegistrationContext(registrationExitContext))cancelRegistrationExit()}
async function invalidatePurchaseFlow(events=[]){
  const g=guideContext;if(!g)return;
  if(typeof recordBundleQuoteChanges==='function')recordBundleQuoteChanges(g.detail,events);
  const changedEvent=events.find(row=>row.recovered_history!==true&&row.offer_id===g.quote.offer.offer_id&&(row.stock==='out_of_stock'||row.new_price!==null&&row.new_price!==undefined&&String(row.new_price)!==String(g.quote.offer.price?.amount)||row.currency&&row.currency!==g.quote.offer.price?.currency));
  if(changedEvent?.stock==='out_of_stock')g.quote.offer.stock='out_of_stock';
  // A confirmed price/currency or sold-out change invalidates the saved quote.
  // A refresh failure or elapsed time alone preserves its last reliable observation.
  registrationExitContext=null;
  if(changedEvent){g.invalidated=true;renderRouteComparison();return}
  const expected=purchaseIdentity(g.quote);
  renderRouteComparison();
  try{
    const detail=await getJson('/api/catalog/'+encodeURIComponent(g.detail.product_id)+'?variant_id='+encodeURIComponent(g.detail.variant_id));
    if(guideContext!==g)return;
    if(detail.product_id!==g.detail.product_id||detail.variant_id!==g.detail.variant_id||!publicProductVisible(detail)){g.invalidated=true;return}
    const exact=detail.offers.find(row=>row.offer.offer_id===g.quote.offer.offer_id);
    if(!exact)return;
    if(exact.offer.stock==='out_of_stock'){g.quote.offer.stock='out_of_stock';g.invalidated=true;return}
    const observed=exact.offer.stock==='unknown'?{...exact,offer:{...exact.offer,stock:g.quote.offer.stock}}:exact;
    if(purchaseIdentity(observed)!==expected){g.invalidated=true;return}
    if(exact.offer.stock==='unknown')return;
    g.detail=detail;g.quote=exact;g.reference=!offerAvailable(exact);g.invalidated=false;
  }catch{/* Keep the last reliable stock observation and its original timestamp. */}
  finally{if(guideContext===g)renderRouteComparison()}
}
function guardRouteHelpExit(event){
  const link=event.target.closest?.('a[data-route-help]');if(!link||(event.type==='auxclick'&&event.button!==1))return;
  event.preventDefault();const allowed=()=>link.isConnected&&sheet.classList.contains('open')&&document.getElementById('routeComparison')?.contains(link)&&ROUTE_HELP.find(row=>row.key===link.dataset.routeHelp&&row.url===link.getAttribute('href'));
  const row=allowed();if(!row)return;
  showExternalExit({url:row.url,kind:'reference',label:row.label,trigger:link,
    sourceNote:'本站保存了这项政府或公共机构资料链接（2026-10-15 核对）；资料适用范围不等于本件商品可运输或免税。',
    note:'即将查看官方说明，仅作资料核对，不确认商品可运输或免税。',
    validate:()=>allowed()===row,onConfirm:()=>savePurchaseState('route')});
}
document.addEventListener('click',guardRouteHelpExit);
document.addEventListener('auxclick',guardRouteHelpExit);
