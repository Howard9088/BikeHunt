'use strict';
// Reversible merchandising policy. Restore alongside app/public_visibility.py.
// Apply independently of server data so an older cached payload cannot revive bikes.
const BICYCLES_PUBLIC=false;
const PUBLIC_CATEGORY_GROUPS=Object.freeze([
  {code:'clothing',name:'骑行服饰'},{code:'cleat_shoes',name:'锁鞋'},
  {code:'helmets',name:'头盔'},{code:'other',name:'配件与周边'}
]);
const HIDDEN_PUBLIC_PRODUCT_IDS=new Set();
const HIDDEN_BICYCLE_IDS=new Set(['specialized-4221796-5368180','canyon-4563-R101_P02','canyon-4066-R100_P08']);
function publicCategoryGroupVisible(code){return BICYCLES_PUBLIC||code!=='road_equipment'}
function publicProductVisible(row){
  if(!row||typeof row!=='object')return false;
  if(BICYCLES_PUBLIC)return true;
  if(row.category_group==='road_equipment'||['road_bikes','frames'].includes(row.category)||HIDDEN_BICYCLE_IDS.has(row.id||row.product_id||row.reference_product_id)||HIDDEN_PUBLIC_PRODUCT_IDS.has(row.product_id||row.reference_product_id||row.id))return false;
  // Older quote/history records may lack the reviewed leaf and group fields.
  for(const url of [row.url,row.offer?.url])try{const u=new URL(url);if(u.hostname==='www.canyon.com'&&u.pathname.startsWith('/en-us/outlet-bikes/')||u.hostname==='www.specialized.com'&&u.pathname.includes('/allez-shimano-claris/p/4221796'))return false}catch{}
  if(row.product&&!publicProductVisible(row.product)||row.offer&&!publicProductVisible(row.offer))return false;
  return !Array.isArray(row.offers)||row.offers.every(publicProductVisible);
}
function publicReferenceData(data={}){
  if(BICYCLES_PUBLIC)return data;
  const products=(data.products||[]).filter(publicProductVisible),brands=[];
  for(const row of data.brands||[]){const product=products.find(p=>p.source_code===row.code);if(product)brands.push({...row,url:product.url,note:'美国站配件研究参考；中国直邮、转运许可、库存、支付和退换条件均待核实。'})}
  return {...data,products,brands};
}
function publicDirectoryData(data={},references={}){
  if(BICYCLES_PUBLIC)return data;
  const brands=publicReferenceData(references).brands;
  return {...data,brands:(data.brands||[]).flatMap(row=>{
    if(!row.road_reference)return [row];
    const reference=brands.find(b=>b.code===row.code);return reference?[{...row,name_zh:row.name+' 配件',official_url:reference.url,shop_url:reference.url,shop_evidence_url:reference.url,reference_note:reference.note,reference_category_group:'other'}]:[];
  }),teams:data.teams||[]};
}
function publicSourceVisible(code,directory){return !code||[...(directory?.brands||[]),...(directory?.teams||[])].some(row=>row.code===code)}
function publicCatalogData(data){
  for(const row of data.items||[])if(!publicProductVisible(row)&&row.product_id)HIDDEN_PUBLIC_PRODUCT_IDS.add(row.product_id);
  return {...data,items:(data.items||[]).filter(publicProductVisible),
    categories:(data.categories||[]).filter(row=>BICYCLES_PUBLIC||!['road_bikes','frames'].includes(row.code)),
    category_groups:BICYCLES_PUBLIC?data.category_groups:PUBLIC_CATEGORY_GROUPS.map(row=>({...row})),
    road_equipment_references:publicReferenceData(data.road_equipment_references)};
}
function applyPublicVisibility(data){
  data.catalog=publicCatalogData(data.catalog);
  data.directories=publicDirectoryData(data.directories,data.catalog.road_equipment_references);
  const hidden=new Set(Object.entries(data.details||{}).filter(([id,family])=>!Object.values(family.variants||{}).every(publicProductVisible)).map(([id])=>id));
  for(const id of hidden){HIDDEN_PUBLIC_PRODUCT_IDS.add(id);delete data.details[id];}
  data.catalog.items=data.catalog.items.filter(row=>!hidden.has(row.product_id));
  for(const family of Object.values(data.details||{}))for(const detail of Object.values(family.variants||{}))detail.colors=(detail.colors||[]).filter(row=>!hidden.has(row.product_id));
  // Leave malformed legacy event rows for the existing message validator to reject.
  // Visibility filtering must never turn an invalid authoritative snapshot into a valid one.
  if(data.updates&&Array.isArray(data.updates.items))data.updates.items=data.updates.items.filter(row=>
    !row||!Number.isSafeInteger(row.id)||row.id<=0||typeof row.event_key!=='string'||!/^[0-9a-f]{64}$/.test(row.event_key)||
    publicProductVisible(row)&&!hidden.has(row.product?.product_id));
  return data;
}
