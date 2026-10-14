'use strict';
window.BIKEHUNT_PAGES=true;
const publicRoot=new URL('../',document.currentScript.src);
const pageRelease=document.currentScript.dataset?.release||'unversioned';
const publicFetch=window.fetch.bind(window);
let publicDataPromise=null,publicLastData=null;
function mapPublicAssets(value){if(Array.isArray(value))return value.map(mapPublicAssets);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,mapPublicAssets(v)]));if(typeof value==='string'&&value.startsWith('/web/'))return new URL(value.slice(1),publicRoot).pathname;return value}
function isoDay(value){if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;const parsed=Date.parse(value);return Number.isFinite(parsed)&&new Date(parsed).toISOString().slice(0,10)===value?parsed/86400000:null}
const STOCK_MAX_AGE_MS=3600000,QUOTE_MAX_AGE_MS=86400000;
function verifiedAge(timestamp,now){if(typeof timestamp!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp)||isoDay(timestamp.slice(0,10))===null)return Infinity;return now-Date.parse(timestamp)}
function stockFresh(offer,now=Date.now()){const age=verifiedAge(offer.fetched_at,now);return Number.isFinite(age)&&age>=0&&age<=STOCK_MAX_AGE_MS}
function quoteFresh(offer,now=Date.now()){const age=verifiedAge(offer.fetched_at,now);const until=offer.price_valid_until;return Number.isFinite(age)&&age>=0&&age<=QUOTE_MAX_AGE_MS&&(!until||isoDay(until)!==null&&isoDay(until)>=Math.floor(now/86400000))}
function publishedOfferAvailable(offer,now){return offer.stock==='in_stock'&&offer.collection_state!=='retained'&&stockFresh(offer,now)&&quoteFresh(offer,now)}
function publishedFxStale(fx,now){const age=now-Date.parse(fx.fetched_at||'');const day=isoDay(fx.rate_date);const dayAge=day===null?null:Math.floor(now/86400000)-day;return !!fx.stale||!/[T ].*(?:Z|[+-]\d{2}:?\d{2})$/i.test(fx.fetched_at||'')||!Number.isFinite(age)||age>3600000||age< -300000||dayAge===null||dayAge<0||dayAge>7}
function refreshPublicInventory(data){
  const now=Date.now(),snapshots=[data.catalog.fx,data.updates.fx,...Object.values(data.details).flatMap(f=>Object.values(f.variants).map(d=>d.fx))];
  const fxStale=snapshots.some(fx=>publishedFxStale(fx,now));snapshots.forEach(fx=>fx.stale=fxStale);
  for(const family of Object.values(data.details))for(const detail of Object.values(family.variants))for(const q of detail.offers){const o=q.offer,s=data.collection_status?.[o.source_code];if(s&&Date.parse(s.attempted_at)>Date.parse(o.fetched_at||'1970-01-01')&&(s.status==='failed'||s.errors?.some(e=>e.url?.split('?')[0]===o.url?.split('?')[0])))o.collection_state='retained';}
  const familyAvailability={};
  for(const [id,family] of Object.entries(data.details))familyAvailability[id]=Object.fromEntries(Object.entries(family.variants).map(([variantId,detail])=>[variantId,detail.offers.some(q=>publishedOfferAvailable(q.offer,now))]));
  for(const family of Object.values(data.details)){
    for(const detail of Object.values(family.variants)){
      detail.variants.forEach(v=>{v.in_stock=!!familyAvailability[detail.product_id][v.variant_id];const variant=family.variants[v.variant_id];v.stock_state=v.in_stock?'in_stock':variant&&variant.offers.length&&variant.offers.every(q=>q.offer.stock==='out_of_stock')?'out_of_stock':'unknown'});
      detail.colors.forEach(color=>color.in_stock=Object.values(familyAvailability[color.product_id]||{}).some(Boolean));
      for(const quote of detail.offers){const reasons=[];if(quote.offer.collection_state==='retained')reasons.push('最近采集失败；历史报价不能确认现货');if(quote.offer.stock!=='in_stock')reasons.push(quote.offer.stock==='out_of_stock'?'已售罄':'库存待核实');if(quote.offer.stock==='in_stock'&&!stockFresh(quote.offer,now))reasons.push('库存核实已过期；等待重新核实');if(!quoteFresh(quote.offer,now))reasons.push('报价已过期');if(fxStale)reasons.push('汇率为过期缓存');if(reasons.length){quote.eligible=false;quote.reasons=[...new Set([...quote.reasons,...reasons])]}}
      if(!detail.offers.some(q=>q.eligible&&q.offer.offer_id===detail.recommended_offer_id))detail.recommended_offer_id=null;
    }
  }
  for(const card of data.catalog.items){const family=data.details[card.product_id],detail=family.variants[family.default];card.available_sizes=detail.variants.filter(v=>v.in_stock&&v.size).map(v=>v.size);const allOffers=Object.values(family.variants).flatMap(d=>d.offers);card.stock_state=Object.values(familyAvailability[card.product_id]).some(Boolean)?'in_stock':allOffers.length&&allOffers.every(q=>q.offer.stock==='out_of_stock')?'out_of_stock':'unknown';if(!detail.recommended_offer_id){card.recommended_total_cny=null;card.status=card.stock_state==='unknown'&&allOffers.some(q=>q.offer.stock==='in_stock'&&!stockFresh(q.offer,now))?'库存核实已过期':'渠道待核实';}if(card.reference_stock==='in_stock'&&(!stockFresh(card,now)||card.reference_collection_state==='retained'))card.reference_stock='unknown';}
}
async function loadPublished(force=false){if(!publicDataPromise||force)publicDataPromise=publicFetch(new URL('data/site-data.json?release='+encodeURIComponent(pageRelease)+'&v='+Date.now(),publicRoot),{cache:'no-store'}).then(async response=>{if(!response.ok)throw new Error('已发布商品数据暂时无法读取');return mapPublicAssets(await response.json())}).catch(error=>{publicDataPromise=null;throw error});const data=await publicDataPromise;refreshPublicInventory(data);publicLastData=data;window.BIKEHUNT_PUBLICATION={...data.publication,generated_at:data.generated_at};const marker=document.getElementById?.('publicationInfo');if(marker){marker.textContent='数据 '+(data.publication?.commit?.slice(0,7)||'本地');marker.title='发布快照 '+data.generated_at+' · '+(data.publication?.commit||'');}return data}
function assessPublishedFit(data,id,profile){
  const family=data.details[id];if(!family)throw new Error('商品不存在');const detail=family.variants[family.default];
  if(!['jerseys','bibs','jackets','suits'].includes(detail.category))return {state:'not_applicable',note_zh:'这类装备按自身规格选择。',candidate_sizes:[],required_measurements:[],chart_rows:[]};
  const urls=detail.offers.map(q=>q.offer.url),chart=data.fit_charts.find(c=>c.product_urls.some(url=>urls.includes(url))&&Date.now()-Date.parse(c.checked_at)>=0&&Date.now()-Date.parse(c.checked_at)<=30*86400000);
  const base={candidate_sizes:[],required_measurements:[],chart_rows:[]};
  if(!chart)return {...base,state:'no_chart',note_zh:'这款完整官网尺码表仍待采集，暂不指定 S/M/L。'};
  if(profile.gender!=='all'&&![profile.gender,'unisex'].includes(chart.gender))return {...base,state:'not_applicable',note_zh:'这款与所选男款／女款偏好不符。'};
  const fields=['height_cm','weight_kg','chest_cm'].filter(key=>chart.rows.some(row=>row[key]));
  const missing=fields.filter(key=>profile[key]==null);
  const common={...base,chart_rows:chart.rows,checked_at:chart.checked_at,source_url:chart.source_url};
  if(missing.length)return {...common,state:'needs_measurement',required_measurements:missing,note_zh:missing.includes('chest_cm')?'官网这款按胸围选码。补一个胸围（厘米），就能对照剩余现货；身高、体重已保留。':'需要补充官网尺码表对应的测量值。'};
  const contains=(range,value)=>range&&(range.minimum==null||value>range.minimum||(range.min_inclusive!==false&&value===range.minimum))&&(range.maximum==null||value<range.maximum||(range.max_inclusive!==false&&value===range.maximum));
  const stocked=new Set(detail.variants.filter(v=>v.in_stock).map(v=>v.size));
  const sizes=chart.rows.filter(row=>stocked.has(row.size)&&fields.every(key=>contains(row[key],Number(profile[key])))).map(row=>row.size);
  return {...common,state:sizes.length?'reference':'unavailable',candidate_sizes:sizes,note_zh:sizes.length?'官网胸围范围对应现货 '+sizes.join(' / ')+'，可作为试穿参考，仍需核对版型及腰围。':'对应尺码目前没有已核实的现货；其他规格继续保留供你比较。'};
}
window.fetch=async(input,init={})=>{
  const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
  if(!url.pathname.startsWith('/api/'))return publicFetch(input,init);
  try{
    const data=await loadPublished();let result;const path=url.pathname;
    if(path==='/api/catalog')result={...data.catalog,items:data.catalog.items.filter(p=>(!url.searchParams.get('category')||url.searchParams.get('category')==='all'||p.category===url.searchParams.get('category'))&&(!url.searchParams.get('q')||(p.name+' '+p.name_zh+' '+p.brand).toLowerCase().includes(url.searchParams.get('q').toLowerCase())))};
    else if(path.startsWith('/api/catalog/')){const family=data.details[decodeURIComponent(path.split('/').at(-1))];if(!family)throw new Error('商品不存在');const variant=url.searchParams.get('variant_id')||family.default;result=family.variants[variant];if(!result)throw new Error('规格不存在');}
    else if(path==='/api/directories')result=data.directories;
    else if(path.startsWith('/api/rules/'))result=data.rules[decodeURIComponent(path.split('/').at(-1))]||{source_code:path.split('/').at(-1),version:0,documents:[]};
    else if(path==='/api/updates'){const category=url.searchParams.get('category')||'all',after=Number(url.searchParams.get('after')||0);result={...data.updates,items:data.updates.items.filter(row=>row.id>after&&(category==='all'||row.category===category)).slice(0,30)}}
    else if(path.startsWith('/api/fit/'))result=assessPublishedFit(data,decodeURIComponent(path.split('/').at(-1)),JSON.parse(init.body||'{}'));
    else if(path==='/api/community')result=data.community;
    else if(path==='/api/notifications/preferences')result={configured:false,bound:false,enabled:false,categories:['all'],provider:'WxPusher',wechat_channel_required:true,public_site:true};
    else if(path==='/api/refresh/prices'){const fresh=await loadPublished(true);result={state:'success',kind:'prices',mode:'published_snapshot',finished_at:fresh.generated_at};}
    else if(path==='/api/refresh/status')result={state:'success',mode:'published_snapshot',finished_at:(await loadPublished()).generated_at};
    else if(path==='/api/fx')result=data.catalog.fx;
    else return new Response(JSON.stringify({detail:'这项服务正在接入后台'}),{status:503,headers:{'Content-Type':'application/json'}});
    return new Response(JSON.stringify(result),{headers:{'Content-Type':'application/json'}});
  }catch(error){return new Response(JSON.stringify({detail:error.message}),{status:503,headers:{'Content-Type':'application/json'}})}
};
function publishedFreshness(data){return JSON.stringify([data.catalog.fx.stale,data.updates.fx.stale,data.catalog.items.map(p=>[p.stock_state,p.available_sizes,p.recommended_total_cny]),Object.values(data.details).map(f=>Object.values(f.variants).map(d=>[d.fx.stale,d.recommended_offer_id,d.variants.map(v=>v.in_stock),d.colors.map(c=>c.in_stock),d.offers.map(q=>[q.eligible,q.reasons,q.offer.stock,q.offer.collection_state,q.offer.price,q.offer.fetched_at])]))])}
let publishedCursor=0,publicationDate='',freshnessState='';
loadPublished().then(data=>{publishedCursor=Math.max(publishedCursor,Number(data.updates.cursor)||0);publicationDate=data.generated_at;freshnessState=publishedFreshness(data)}).catch(()=>{});
async function pollPublished(){let data;try{data=await loadPublished(true)}catch{data=publicLastData;if(!data)return;refreshPublicInventory(data)}const nextFreshness=publishedFreshness(data),freshnessChanged=nextFreshness!==freshnessState;const events=data.updates.items.filter(row=>row.id>publishedCursor);publishedCursor=Math.max(publishedCursor,Number(data.updates.cursor)||0);if(data.generated_at===publicationDate&&!freshnessChanged&&!events.length)return;publicationDate=data.generated_at;freshnessState=nextFreshness;window.dispatchEvent(new CustomEvent('bikehunt-published',{detail:{events,freshnessChanged}}));}
const publishedTimer=setInterval(()=>pollPublished().catch(()=>{}),60000);
window.addEventListener('focus',()=>pollPublished().catch(()=>{}));
window.addEventListener('pagehide',()=>clearInterval(publishedTimer),{once:true});
