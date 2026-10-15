'use strict';
// Presentation only. Never produce a Cartesian product, rewrite merchant text,
// or derive an offer ID from component sizes. Unsupported/ambiguous data falls
// back to exact variant selection with expandable original merchant labels.
const BUNDLE_PARTS=Object.freeze([{key:'jersey',label:'上衣'},{key:'bib',label:'背带裤'},{key:'socks',label:'袜子'}]);
function parseBundleSize(raw){
  if(typeof raw!=='string'||raw.length>600)return null;
  const match=/^Bib Short (20\d{2}) [I|] Soudal Quick-Step \(Size\): (XS|S|M|L|XL|2XL|3XL|XXL|XXXL) \/ Jersey \1 [I|] Soudal Quick-Step \(Size\): (XS|S|M|L|XL|2XL|3XL|XXL|XXXL) \/ Socks \1 [I|] Soudal Quick-Step \(Accessory size\): (S-M|L-XL)$/.exec(raw);
  return match?{year:match[1],bib:match[2],jersey:match[3],socks:match[4]}:null;
}
function bundleVariantModel(detail){
  if(!Array.isArray(detail?.variants)||!detail.variants.length)return null;
  const rows=detail.variants.map(variant=>({variant,parts:parseBundleSize(variant.size)}));
  if(rows.some(row=>!row.parts)||new Set(rows.map(row=>row.parts.year)).size!==1||
    new Set(rows.map(row=>row.variant.variant_id)).size!==rows.length||
    new Set(rows.map(row=>BUNDLE_PARTS.map(part=>row.parts[part.key]).join('|'))).size!==rows.length)return null;
  return rows;
}
function bundleOptions(model,selection,index){
  if(index<0||index>=BUNDLE_PARTS.length||BUNDLE_PARTS.slice(0,index).some(part=>!selection?.[part.key]))return [];
  const key=BUNDLE_PARTS[index].key,rows=model.filter(row=>BUNDLE_PARTS.slice(0,index).every(part=>row.parts[part.key]===selection[part.key]));
  const order=['XS','S','M','L','XL','2XL','XXL','3XL','XXXL','S-M','L-XL'];
  return [...new Set(rows.map(row=>row.parts[key]))].sort((a,b)=>order.indexOf(a)-order.indexOf(b)).map(value=>{
    const exact=rows.filter(row=>row.parts[key]===value);
    return {value,available:exact.some(row=>row.variant.in_stock===true),status:exact.every(row=>row.variant.stock_state==='out_of_stock')?'已售罄':'库存待核实'};
  });
}
function normalizeBundleSelection(model,selection){
  const clean={};
  for(let index=0;index<BUNDLE_PARTS.length;index++){
    const key=BUNDLE_PARTS[index].key,value=selection?.[key];
    if(typeof value!=='string'||!bundleOptions(model,clean,index).some(option=>option.value===value&&option.available))break;
    clean[key]=value;
  }
  return clean;
}
function exactBundleVariant(model,selection){
  if(BUNDLE_PARTS.some(part=>!selection?.[part.key]))return null;
  const matches=model.filter(row=>row.variant.in_stock===true&&BUNDLE_PARTS.every(part=>row.parts[part.key]===selection[part.key]));
  return matches.length===1?matches[0].variant:null;
}
function bundleSelectionLabel(selection){return BUNDLE_PARTS.map(part=>part.label+' '+(selection?.[part.key]||'待选')).join(' · ')}
function compactVariantLabel(raw,index=null){
  const parts=parseBundleSize(raw);if(parts)return bundleSelectionLabel(parts);
  const text=String(raw||'规格待核实');
  return text.length>40?(!Number.isInteger(index)||index<0?'复杂规格（展开核对）':'组合 '+(index+1)):text;
}
function catalogSizeLabel(card,deal){
  if(deal)return '折扣规格 '+[compactVariantLabel(card.reference_size),card.reference_color].filter(Boolean).join(' / ');
  const sizes=card.available_sizes||[];
  if(sizes.length&&sizes.every(size=>parseBundleSize(size)))return '三件套 · '+sizes.length+' 个现货组合';
  if(sizes.some(size=>String(size).length>40))return sizes.length+' 个现货组合 · 点开核对规格';
  return '现货 '+sizes.join(' / ');
}
function originalVariantMarkup(raw,className='variant-original'){
  if(!raw||String(raw).length<=40)return '';
  return '<details class="'+className+'"><summary>查看商家原始规格</summary><p>'+e(raw)+'</p></details>';
}
function bundleSelectorMarkup(model,selection,message=''){
  const exact=exactBundleVariant(model,selection);
  return '<section id="bundleChoices" aria-labelledby="bundleTitle"><h4 id="bundleTitle">选择三件套尺码</h4><p id="bundleHelp" class="spec-note">依次选择上衣、背带裤和袜子。只匹配商家已有且最近核实有货的组合；灰色规格不可选。</p><div class="bundle-parts">'+BUNDLE_PARTS.map((part,index)=>{
    const options=bundleOptions(model,selection,index),disabled=index>0&&!selection[BUNDLE_PARTS[index-1].key];
    return '<div class="bundle-part"><label for="bundle-'+part.key+'">'+(index+1)+' · '+part.label+'</label><select id="bundle-'+part.key+'" data-bundle-part="'+part.key+'" aria-describedby="bundleHelp bundleStatus" '+(disabled?'disabled':'')+'><option value="">请选择'+part.label+'</option>'+options.map(option=>'<option value="'+e(option.value)+'" '+(selection[part.key]===option.value?'selected ':'')+(!option.available?'disabled':'')+'>'+e(option.value)+(option.available?'':' · '+option.status)+'</option>').join('')+'</select></div>';
  }).join('')+'</div><p id="bundleStatus" class="bundle-selection-summary" role="status" aria-live="polite">'+e(bundleSelectionLabel(selection))+(exact?'':'。选齐后查看对应报价。')+'</p>'+(message?'<p class="bundle-change-note" role="status">'+e(message)+'</p>':'')+(exact?originalVariantMarkup(exact.size,'bundle-original'):'')+'</section>';
}

// A published change is a safety observation even if the detail endpoint/CDN
// still serves an older snapshot. Keep its exact-offer fence across local Back
// and reload, and do not revive it merely because the user reselects the size.
const BUNDLE_QUOTE_GUARDS=new Map();
function bundleQuoteGuards(){
  if(typeof history==='undefined')return BUNDLE_QUOTE_GUARDS;
  const saved=history.state?.bikehuntBundleGuards;
  if(Array.isArray(saved))for(const row of saved.slice(-100)){
    if(row&&['offerId','productId','variantId','url'].every(key=>typeof row[key]==='string'&&row[key].length<=1000)&&
      (!row.currency||/^[A-Z]{3}$/.test(row.currency))&&(!row.stock||['in_stock','out_of_stock','unknown'].includes(row.stock))&&
      (!row.amount||typeof row.amount==='string'&&row.amount.length<=40)&&!BUNDLE_QUOTE_GUARDS.has(row.offerId))BUNDLE_QUOTE_GUARDS.set(row.offerId,row);
  }
  return BUNDLE_QUOTE_GUARDS;
}
function saveBundleQuoteGuards(){
  try{while(BUNDLE_QUOTE_GUARDS.size>100)BUNDLE_QUOTE_GUARDS.delete(BUNDLE_QUOTE_GUARDS.keys().next().value);history.replaceState({...history.state,bikehuntBundleGuards:[...BUNDLE_QUOTE_GUARDS.values()]},'')}catch{}
}
function recordBundleQuoteChanges(detail,events=[]){
  if(!bundleVariantModel(detail))return;
  const guards=bundleQuoteGuards();let changed=false;
  for(const event of events){
    if(event.recovered_history===true)continue;
    const quote=detail.offers?.find(q=>q.offer.offer_id===event.offer_id),old=guards.get(event.offer_id);
    if(!quote&&!old)continue;
    const offer=quote?.offer,stock=['in_stock','out_of_stock','unknown'].includes(event.stock)?event.stock:null;
    const amount=event.new_price!==null&&event.new_price!==undefined&&Number.isFinite(Number(event.new_price))?String(event.new_price):null;
    const currency=/^[A-Z]{3}$/.test(event.currency||'')?event.currency:null;
    if(!old&&!(stock&&stock!==offer.stock||amount!==null&&amount!==String(offer.price?.amount)||currency&&currency!==offer.price?.currency))continue;
    const observedAt=Number.isFinite(Date.parse(event.observed_at))?event.observed_at:null;
    if(old?.observedAt&&observedAt&&Date.parse(observedAt)<Date.parse(old.observedAt))continue;
    guards.set(event.offer_id,{offerId:event.offer_id,productId:old?.productId||detail.product_id,variantId:old?.variantId||detail.variant_id,url:old?.url||offer.url,sourceCode:old?.sourceCode||offer?.source_code||null,
      stock:stock||old?.stock||null,amount:amount??old?.amount??null,currency:currency||old?.currency||null,observedAt:observedAt||old?.observedAt||null,
      baselineFetchedAt:old?.baselineFetchedAt||offer?.fetched_at||null,confirmed:false});changed=true;
  }
  if(changed)saveBundleQuoteGuards();
}
function bundleQuoteAllowed(quote){
  const offer=quote?.offer,guard=bundleQuoteGuards().get(offer?.offer_id);if(!guard)return true;
  const matches=(!guard.stock||offer.stock===guard.stock)&&(guard.amount===null||String(offer.price?.amount)===guard.amount)&&(!guard.currency||offer.price?.currency===guard.currency);
  if(offer.url!==guard.url){
    // A deliberate exact-detail recheck may follow a merchant's renamed path,
    // but cannot silently move the guard to another source or host.
    try{if(!matches||offer.source_code!==guard.sourceCode||new URL(offer.url).origin!==new URL(guard.url).origin||new URL(offer.url).protocol!=='https:'||
      !(Date.parse(offer.fetched_at)>Date.parse(guard.baselineFetchedAt||0))||guard.observedAt&&!(Date.parse(offer.fetched_at)>Date.parse(guard.observedAt)))return false;}catch{return false}
  }
  if(matches)return true;
  // A genuinely newer merchant observation can establish a later change.
  return !!guard.observedAt&&Date.parse(offer.fetched_at)>Date.parse(guard.observedAt)&&Date.parse(offer.fetched_at)>Date.parse(guard.baselineFetchedAt||0);
}
function observeBundleDetail(detail){
  let changed=false;
  for(const quote of detail.offers||[]){const guard=bundleQuoteGuards().get(quote.offer.offer_id);if(guard){const confirmed=bundleQuoteAllowed(quote);if(guard.confirmed!==confirmed){guard.confirmed=confirmed;changed=true}}}
  if(changed)saveBundleQuoteGuards();
}
function bundleVariantBlocked(productId,variantId){return [...bundleQuoteGuards().values()].some(guard=>guard.productId===productId&&guard.variantId===variantId&&!guard.confirmed&&guard.stock==='out_of_stock')}
