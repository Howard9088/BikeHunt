'use strict';
window.BIKEHUNT_PAGES=true;
const publicRoot=new URL('../',document.currentScript.src);
const pageRelease=document.currentScript.dataset?.release||'unversioned';
const publicFetch=window.fetch.bind(window);
let publicDataPromise=null,publicLastData=null,publicLastManifest=null;
// The verified catalog base never receives local expiry mutations or status overlays.
let publicLastBase=null,publicLastStatus=null,publicPendingSafetyChange=false;
// Keep high-water marks even if an identity disappears and later reappears.
const publicObservationTimes=new Map(),publicFxTimes=new Map();
function mapPublicAssets(value){if(Array.isArray(value))return value.map(mapPublicAssets);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,mapPublicAssets(v)]));if(typeof value==='string'&&value.startsWith('/web/'))return new URL(value.slice(1),publicRoot).pathname;return value}
function isoDay(value){if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;const parsed=Date.parse(value);return Number.isFinite(parsed)&&new Date(parsed).toISOString().slice(0,10)===value?parsed/86400000:null}
const QUOTE_MAX_AGE_MS=86400000;
function verifiedAge(timestamp,now){if(typeof timestamp!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp)||isoDay(timestamp.slice(0,10))===null)return Infinity;return now-Date.parse(timestamp)}
// A successful stock observation has no age timeout; keep its real timestamp.
// Quote/coupon validity and collection failures remain separate price safeguards.
function stockFresh(offer,now=Date.now()){const age=verifiedAge(offer.fetched_at,now);return Number.isFinite(age)&&age>=0}
function quoteFresh(offer,now=Date.now()){const age=verifiedAge(offer.fetched_at,now);const until=offer.price_valid_until;return Number.isFinite(age)&&age>=0&&age<=QUOTE_MAX_AGE_MS&&(!until||isoDay(until)!==null&&isoDay(until)>=Math.floor(now/86400000))}
function publishedOfferAvailable(offer,now){return (offer.data_kind||'live_snapshot')==='live_snapshot'&&offer.stock==='in_stock'&&stockFresh(offer,now)}
function publishedFxStale(fx,now){const age=now-Date.parse(fx.fetched_at||'');const day=isoDay(fx.rate_date);const dayAge=day===null?null:Math.floor(now/86400000)-day;return !!fx.stale||!/[T ].*(?:Z|[+-]\d{2}:?\d{2})$/i.test(fx.fetched_at||'')||!Number.isFinite(age)||age>86400000||age< -300000||dayAge===null||dayAge<0||dayAge>7}
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
      for(const quote of detail.offers){const reasons=[];if(quote.offer.collection_state==='retained')reasons.push('最近价格核对未完成；请以官网结账报价为准');if(quote.offer.stock!=='in_stock')reasons.push(quote.offer.stock==='out_of_stock'?'已售罄':'库存待核实');if(quote.offer.stock==='in_stock'&&!stockFresh(quote.offer,now))reasons.push('库存记录缺少有效核实时间');if(!quoteFresh(quote.offer,now))reasons.push('报价已过期');if(fxStale)reasons.push('汇率为过期缓存');if(reasons.length){quote.eligible=false;quote.reasons=[...new Set([...quote.reasons,...reasons])]}}
      if(!detail.offers.some(q=>q.eligible&&q.offer.offer_id===detail.recommended_offer_id))detail.recommended_offer_id=null;
    }
  }
  for(const card of data.catalog.items){const family=data.details[card.product_id],detail=family.variants[family.default];card.available_sizes=detail.variants.filter(v=>v.in_stock&&v.size).map(v=>v.size);const allOffers=Object.values(family.variants).flatMap(d=>d.offers);card.stock_state=Object.values(familyAvailability[card.product_id]).some(Boolean)?'in_stock':allOffers.length&&allOffers.every(q=>q.offer.stock==='out_of_stock')?'out_of_stock':'unknown';if(!detail.recommended_offer_id){card.recommended_total_cny=null;card.status='渠道待核实';}const reference=allOffers.find(q=>q.offer.offer_id===card.reference_offer_id)?.offer;if(reference){card.reference_collection_state=reference.collection_state;card.reference_stock=publishedOfferAvailable(reference,now)?reference.stock:reference.stock==='out_of_stock'?'out_of_stock':'unknown'}else if(card.reference_stock==='in_stock'&&!stockFresh(card,now))card.reference_stock='unknown';}
  for(const parent of data.catalog.items)for(const [source,card] of Object.entries(parent.channel_quotes||{})){
    const family=data.details[parent.product_id],detail=family.variants[family.default];
    const offers=Object.values(family.variants).flatMap(d=>d.offers).filter(q=>q.offer.source_code===source);
    const available=offers.filter(q=>publishedOfferAvailable(q.offer,now));
    card.stock_state=available.length?'in_stock':offers.length&&offers.every(q=>q.offer.stock==='out_of_stock')?'out_of_stock':'unknown';
    card.available_sizes=detail.variants.filter(v=>v.size&&family.variants[v.variant_id]?.offers.some(q=>q.offer.source_code===source&&publishedOfferAvailable(q.offer,now))).map(v=>v.size);
    const reference=offers.find(q=>q.offer.offer_id===card.reference_offer_id);
    if(reference){card.reference_collection_state=reference.offer.collection_state;card.reference_stock=publishedOfferAvailable(reference.offer,now)?'in_stock':reference.offer.stock==='out_of_stock'?'out_of_stock':'unknown';if(!reference.eligible)card.recommended_total_cny=null;}
    else{card.reference_stock='unknown';card.recommended_total_cny=null;}
  }
}
function publishedUrl(path,version){const url=new URL(path,publicRoot);url.searchParams.set('release',pageRelease);url.searchParams.set('v',String(Date.now()));if(version)url.searchParams.set('version',version);return url}
function isRecord(value){return !!value&&typeof value==='object'&&!Array.isArray(value)}
function validDigest(value){return typeof value==='string'&&/^[a-f0-9]{64}$/.test(value)}
function validDescriptor(value,path){return isRecord(value)&&value.path===path&&Number.isSafeInteger(value.bytes)&&value.bytes>0&&validDigest(value.sha256)}
function validTimestamp(value){return Number.isFinite(verifiedAge(value,0))}
function clonePublished(value){return JSON.parse(JSON.stringify(value))}
function publicFxSnapshots(data){return [data.catalog.fx,data.updates.fx,...Object.values(data.details).flatMap(f=>Object.values(f.variants).map(d=>d.fx))]}
function validPublication(manifest){
  const age=verifiedAge(manifest?.generated_at,Date.now());
  if(!manifest||![1,2].includes(manifest.schema_version)||typeof manifest.version!=='string'||!manifest.version||
    !Number.isFinite(age)||age< -300000||
    !(manifest.commit===null||typeof manifest.commit==='string')||
    !validDescriptor(manifest.snapshot,'data/site-data.json'))throw new Error('发布清单无效；等待重新发布');
  if(manifest.schema_version===2){
    const snapshot=manifest.snapshot;
    if(manifest.version!==(manifest.commit||'local')+':'+manifest.generated_at||
      !validDescriptor(manifest.status,'data/verification.json')||
      !validTimestamp(snapshot.generated_at)||Date.parse(snapshot.generated_at)>Date.parse(manifest.generated_at)||
      snapshot.commit!==manifest.commit||!validDigest(snapshot.semantic_sha256)||
      snapshot.version!==(snapshot.commit||'local')+':catalog:'+snapshot.semantic_sha256)
      throw new Error('发布清单无效；等待重新发布');
  }
  return manifest;
}
function sameSnapshot(a,b){return a.path===b.path&&a.sha256===b.sha256&&a.bytes===b.bytes&&a.version===b.version&&a.generated_at===b.generated_at&&a.commit===b.commit&&a.semantic_sha256===b.semantic_sha256}
function samePublication(a,b){return a.schema_version===b.schema_version&&a.version===b.version&&a.generated_at===b.generated_at&&a.commit===b.commit&&sameSnapshot(a.snapshot,b.snapshot)&&(a.schema_version===1||a.status.path===b.status.path&&a.status.sha256===b.status.sha256&&a.status.bytes===b.status.bytes)}
function publicationMismatch(message){const error=new Error(message);error.publicationMismatch=true;return error}
async function readPublication(){
  const response=await publicFetch(publishedUrl('data/publication.json'),{cache:'no-store'});
  if(!response.ok)throw new Error('最新发布清单暂时无法读取');
  return validPublication(await response.json());
}
async function readPublishedFile(descriptor,version,label){
  const response=await publicFetch(publishedUrl(descriptor.path,version),{cache:'no-store'});
  if(!response.ok)throw new Error(label+'暂时无法读取');
  const bytes=await response.arrayBuffer();
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  if(bytes.byteLength!==descriptor.bytes||digest!==descriptor.sha256)
    throw publicationMismatch('发布文件正在同步或校验失败；等待一致的快照');
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
}
function publishedOfferIndex(data){
  const offers=new Map();
  for(const family of Object.values(data.details))for(const detail of Object.values(family.variants))for(const quote of detail.offers){
    const offer=quote.offer,id=offer.offer_id;
    if(typeof id!=='string'||!id||offers.has(id)&&JSON.stringify(offers.get(id))!==JSON.stringify(offer))
      throw publicationMismatch('商品身份重复或无效；保留上次核实的数据');
    offers.set(id,offer);
  }
  return offers;
}
function publishedCatalogCards(data){return data.catalog.items.flatMap(card=>[card,...Object.values(card.channel_quotes||{})])}
function validateCatalogIdentities(data){
  const offers=publishedOfferIndex(data),identities=data.verification_identities;
  if(!isRecord(identities)||Object.keys(identities).length!==offers.size||
    [...offers].some(([id,offer])=>!validDigest(identities[id])||!['current','retained'].includes(offer.collection_state)||
      offer.fetched_at!==null&&(!validTimestamp(offer.fetched_at)||Date.parse(offer.fetched_at)>Date.parse(data.generated_at))))
    throw publicationMismatch('商品核实身份缺失或不一致；保留上次核实的数据');
  for(const parent of data.catalog.items){
    if(parent.channel_quotes!==undefined&&!isRecord(parent.channel_quotes))throw publicationMismatch('渠道报价无效');
    for(const [source,card] of Object.entries(parent.channel_quotes||{})){
      const quote=data.details[parent.product_id]?.variants[card?.reference_variant_id]?.offers.find(q=>q.offer.offer_id===card.reference_offer_id);
      if(!isRecord(card)||card.product_id!==parent.product_id||!parent.source_codes?.includes(source)||quote?.offer.source_code!==source||
         Object.keys(card.channel_quotes||{}).length)throw publicationMismatch('渠道报价与商品不一致');
    }
  }
  for(const card of publishedCatalogCards(data)){
    const family=data.details[card.product_id];
    if(!family||typeof card.reference_offer_id!=='string'||
      !Object.values(family.variants).some(detail=>detail.offers.some(q=>q.offer.offer_id===card.reference_offer_id)))
      throw publicationMismatch('商品参考报价身份缺失；保留上次核实的数据');
    // New cards must bind all discount facts to the same published quote. Old
    // cards remain readable but cannot qualify for the verified deals feed.
    if('reference_original_price' in card||'reference_variant_id' in card){
      const detail=family.variants[card.reference_variant_id],quote=detail?.offers.find(q=>q.offer.offer_id===card.reference_offer_id),offer=quote?.offer;
      const sameMoney=(a,b)=>a==null&&b==null||!!a&&!!b&&a.currency===b.currency&&Number.isFinite(Number(a.amount))&&Number.isFinite(Number(b.amount))&&Number(a.amount)===Number(b.amount);
      if(!offer||!sameMoney(card.reference_price,offer.price)||!sameMoney(card.reference_original_price,offer.original_price)||
        card.reference_cny!==quote.product_cny||card.reference_source!==offer.source_name||
        ('reference_url' in card&&card.reference_url!==offer.url)||
        card.reference_size!==(offer.identity?.size??null)||card.reference_color!==(offer.identity?.color??null)||
        card.reference_price_valid_until!==(offer.price_valid_until??null)||card.reference_data_kind!==(offer.data_kind||'live_snapshot')||
        card.reference_collection_state!==offer.collection_state||card.fetched_at!==offer.fetched_at)
        throw publicationMismatch('折扣与参考规格报价不一致；保留上次核实的数据');
    }
  }
  return offers;
}
async function readPublishedSnapshot(manifest){
  const payload=await readPublishedFile(manifest.snapshot,manifest.snapshot.version||manifest.version,'已发布商品数据');
  const identity=manifest.schema_version===2?manifest.snapshot:manifest;
  if(payload.generated_at!==identity.generated_at||payload.publication?.version!==identity.version||payload.publication?.commit!==identity.commit)
    throw publicationMismatch('发布清单与商品版本不一致；等待一致的快照');
  if(manifest.schema_version===2)validateCatalogIdentities(payload);
  return mapPublicAssets(payload);
}
function checkedObservation(value,baseline,generatedAt,previous){
  if(value!==null&&(!validTimestamp(value)||Date.parse(value)>Date.parse(generatedAt)))return false;
  // Null is an explicit absence of verification, never permission to erase a
  // previously verified observation or to renew it from the publication clock.
  for(const earlier of [baseline,previous])if(earlier!==undefined&&earlier!==null&&
    (!validTimestamp(earlier)||value===null||Date.parse(value)<Date.parse(earlier)))return false;
  return true;
}
function sameObservation(a,b){return a===b||a!==null&&b!==null&&validTimestamp(a)&&validTimestamp(b)&&Date.parse(a)===Date.parse(b)}
function sourceFailureAffects(status,offer){
  return status&&(status.status==='failed'||status.errors?.some(error=>typeof error.url==='string'&&error.url.split('?')[0]===offer.url?.split('?')[0]));
}
function validatePublishedStatus(manifest,base,status){
  const reject=()=>{throw publicationMismatch('核实状态与商品快照不一致；保留上次核实的数据')};
  if(!isRecord(status)||status.schema_version!==1||status.version!==manifest.version||
    status.generated_at!==manifest.generated_at||status.commit!==manifest.commit||status.snapshot_sha256!==manifest.snapshot.sha256||
    !isRecord(status.offers)||!isRecord(status.fx)||!isRecord(status.collection_status))reject();
  const offers=validateCatalogIdentities(base),identities=base.verification_identities;
  if(Object.keys(status.offers).length!==offers.size||Object.keys(status.offers).some(id=>!offers.has(id)))reject();
  for(const [source,row] of Object.entries(status.collection_status)){
    if(!isRecord(row)||(row.source_code!==undefined&&row.source_code!==source)||
      row.attempted_at!==undefined&&(!validTimestamp(row.attempted_at)||Date.parse(row.attempted_at)>Date.parse(status.generated_at))||
      row.errors!==undefined&&!Array.isArray(row.errors))reject();
  }
  for(const [id,offer] of offers){
    const observation=status.offers[id],previous=publicObservationTimes.get(id)?.get(identities[id]);
    if(!isRecord(observation)||observation.content_sha256!==identities[id]||observation.collection_state!==offer.collection_state||
      !checkedObservation(observation.fetched_at,offer.fetched_at,status.generated_at,previous)||
      offer.collection_state==='retained'&&!sameObservation(observation.fetched_at,offer.fetched_at))reject();
    const source=status.collection_status[offer.source_code];
    if(sourceFailureAffects(source,offer)){
      if(!validTimestamp(source.attempted_at))reject();
      // A failed source/page attempt is not evidence of a fresh observation.
      // If it follows the offer, the catalog must already say retained.
      if(Date.parse(source.attempted_at)>Date.parse(observation.fetched_at||'1970-01-01')&&offer.collection_state!=='retained')reject();
      if(Date.parse(source.attempted_at)>Date.parse(offer.fetched_at||'1970-01-01')&&!sameObservation(observation.fetched_at,offer.fetched_at))reject();
    }
  }
  const fx=base.catalog.fx,previousFx=publicFxTimes.get(base.catalog.fx.snapshot_id);
  if(typeof fx.snapshot_id!=='string'||!fx.snapshot_id||fx.fetched_at!==null&&(!validTimestamp(fx.fetched_at)||Date.parse(fx.fetched_at)>Date.parse(base.generated_at))||
    status.fx.snapshot_id!==fx.snapshot_id||typeof status.fx.stale!=='boolean'||status.fx.stale!==fx.stale||
    !checkedObservation(status.fx.fetched_at,fx.fetched_at,status.generated_at,previousFx)||
    publicFxSnapshots(base).some(item=>item.snapshot_id===fx.snapshot_id&&(item.stale!==fx.stale||!sameObservation(item.fetched_at,fx.fetched_at))))reject();
  return status;
}
function applyPublishedStatus(base,status){
  const data=clonePublished(base);
  for(const family of Object.values(data.details))for(const detail of Object.values(family.variants))for(const quote of detail.offers){
    const observation=status.offers[quote.offer.offer_id];
    quote.offer.fetched_at=observation.fetched_at;
    quote.offer.verification_identity=observation.content_sha256;
    for(const component of quote.landed_cost?.components||[])if(component.key==='product')
      for(const evidence of component.evidence||[])evidence.checked_on=observation.fetched_at?.slice(0,10)||null;
  }
  for(const card of publishedCatalogCards(data)){card.fetched_at=status.offers[card.reference_offer_id].fetched_at;card.reference_verification_identity=status.offers[card.reference_offer_id].content_sha256;}
  for(const fx of publicFxSnapshots(data))if(fx.snapshot_id===status.fx.snapshot_id)fx.fetched_at=status.fx.fetched_at;
  data.collection_status=clonePublished(status.collection_status);
  return data;
}
function notifyVerificationMetadata(previous,data,status){
  if(!previous||!status)return;
  refreshPublicInventory(previous);
  if(publishedFreshness(previous)!==publishedFreshness(data)){publicPendingSafetyChange=true;return;}
  if(publishedContentVersion(previous)!==publishedContentVersion(data))return;
  const oldOffers=publishedOfferIndex(previous),observations={};let changed=false;
  for(const family of Object.values(data.details))for(const detail of Object.values(family.variants))for(const quote of detail.offers){
    const id=quote.offer.offer_id,observation=status.offers[id];
    if(oldOffers.get(id)?.fetched_at!==observation.fetched_at)changed=true;
    observations[id]={...observation,stock:quote.offer.stock,eligible:quote.eligible,reasons:[...quote.reasons]};
  }
  if(previous.catalog.fx.fetched_at!==status.fx.fetched_at)changed=true;
  if(changed)window.dispatchEvent(new CustomEvent('bikehunt-verification',{detail:{offers:observations,fx:{...status.fx}}}));
}
async function readPublishedPair(manifest){
  let base;
  if(publicLastManifest?.schema_version===2&&manifest.schema_version===2&&manifest.snapshot.sha256===publicLastManifest.snapshot.sha256){
    if(!sameSnapshot(manifest.snapshot,publicLastManifest.snapshot))throw publicationMismatch('商品快照标识与校验信息不一致；保留上次核实的数据');
    base=publicLastBase;
  }else base=await readPublishedSnapshot(manifest);
  const status=manifest.schema_version===2?validatePublishedStatus(manifest,base,await readPublishedFile(manifest.status,manifest.version,'最新核实状态')):null;
  const data=status?applyPublishedStatus(base,status):clonePublished(base);
  refreshPublicInventory(data);
  applyPublicVisibility(data);
  // Commit the complete pair atomically. Neither races nor partial downloads can
  // replace the pristine base, accepted observations, or last safe live data.
  const previous=publicLastData;
  publicLastBase=base;publicLastStatus=status;publicLastData=data;publicLastManifest=manifest;
  if(status){
    for(const [id,observation] of Object.entries(status.offers)){
      if(!publicObservationTimes.has(id))publicObservationTimes.set(id,new Map());
      publicObservationTimes.get(id).set(observation.content_sha256,observation.fetched_at);
    }
    publicFxTimes.set(status.fx.snapshot_id,status.fx.fetched_at);
  }
  notifyVerificationMetadata(previous,data,status);
  // A proof may arrive just after the old clock expired, between timer ticks.
  // Preserve that safety transition even if renewed data matches the last UI
  // fingerprint; stale copied selections must take normal invalidation.
  if(publicPendingSafetyChange)notifyPublished(data);
  return data;
}
async function checkPublished(){
  const manifest=await readPublication();
  if(publicLastManifest){
    if(manifest.version===publicLastManifest.version){
      if(!samePublication(manifest,publicLastManifest))
        throw new Error('发布版本与校验信息不一致；保留上次核实的数据');
      return publicLastData;
    }
    // Never roll back after a successful load, including a delayed CDN response.
    if(Date.parse(manifest.generated_at)<=Date.parse(publicLastManifest.generated_at)||manifest.schema_version<publicLastManifest.schema_version)
      throw new Error('发布清单早于已加载版本；保留上次核实的数据');
  }
  try{return await readPublishedPair(manifest)}catch(error){
    if(publicLastData||!error.publicationMismatch)throw error;
    // One bounded startup recovery for a manifest that changed during delivery.
    const latest=await readPublication();
    if(latest.version===manifest.version||Date.parse(latest.generated_at)<=Date.parse(manifest.generated_at))throw error;
    return readPublishedPair(latest);
  }
}
function showPublishedMetadata(data){
  window.BIKEHUNT_PUBLICATION={...data.publication,generated_at:data.generated_at};
  window.BIKEHUNT_VERIFICATION={version:publicLastManifest.version,generated_at:publicLastManifest.generated_at,commit:publicLastManifest.commit};
  for(const key of ['run_id','trigger'])if(publicLastStatus?.[key]!==undefined)window.BIKEHUNT_VERIFICATION[key]=publicLastStatus[key];
  const marker=document.getElementById?.('publicationInfo');
  if(marker){marker.textContent='数据更新时间';marker.title='商品资料更新 '+data.generated_at+' · 页面更新 '+publicLastManifest.generated_at;}
}
async function loadPublished(force=false){
  // One in-flight check for initial, timer, focus and manual callers; cached API
  // reads keep using the last verified data while a newer publication is loading.
  if(!publicLastData||force){
    if(!publicDataPromise)publicDataPromise=checkPublished().finally(()=>{publicDataPromise=null});
    await publicDataPromise;
  }
  const data=publicLastData;refreshPublicInventory(data);applyPublicVisibility(data);showPublishedMetadata(data);
  return data;
}
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
    if(path==='/api/catalog')result={...data.catalog,items:data.catalog.items.filter(p=>(!url.searchParams.get('category_group')||p.category_group===url.searchParams.get('category_group'))&&(!url.searchParams.get('category')||url.searchParams.get('category')==='all'||p.category===url.searchParams.get('category'))&&(!url.searchParams.get('q')||(p.name+' '+p.name_zh+' '+p.brand).toLowerCase().includes(url.searchParams.get('q').toLowerCase())))};
    else if(path.startsWith('/api/catalog/')){const family=data.details[decodeURIComponent(path.split('/').at(-1))];if(!family)throw new Error('商品不存在');const variant=url.searchParams.get('variant_id')||family.default;result=family.variants[variant];if(!result)throw new Error('规格不存在');}
    else if(path==='/api/directories')result=data.directories;
    else if(path.startsWith('/api/rules/'))result=data.rules[decodeURIComponent(path.split('/').at(-1))]||{source_code:path.split('/').at(-1),version:0,documents:[]};
    else if(path==='/api/updates'){const category=url.searchParams.get('category')||'all',after=Number(url.searchParams.get('after')||0);result={...data.updates,items:data.updates.items.filter(row=>row.id>after&&(category==='all'||row.category===category)).slice(0,100)}}
    else if(path.startsWith('/api/fit/'))result=assessPublishedFit(data,decodeURIComponent(path.split('/').at(-1)),JSON.parse(init.body||'{}'));
    else if(path==='/api/community')result=data.community;
    else if(path==='/api/notifications/preferences')result={configured:false,bound:false,enabled:false,categories:['all'],provider:'WxPusher',wechat_channel_required:true,public_site:true};
    else if(path==='/api/refresh/prices'){const fresh=await loadPublished(true);result={state:'success',kind:'prices',mode:'published_snapshot',finished_at:publicLastManifest.generated_at,catalog_generated_at:fresh.generated_at};}
    else if(path==='/api/refresh/status')result={state:'success',mode:'published_snapshot',finished_at:publicLastManifest.generated_at};
    else if(path==='/api/fx')result=data.catalog.fx;
    else return new Response(JSON.stringify({detail:'这项服务正在接入后台'}),{status:503,headers:{'Content-Type':'application/json'}});
    return new Response(JSON.stringify(result),{headers:{'Content-Type':'application/json'}});
  }catch(error){return new Response(JSON.stringify({detail:error.message}),{status:503,headers:{'Content-Type':'application/json'}})}
};
function publishedFreshness(data){return JSON.stringify([data.catalog.fx.stale,data.updates.fx.stale,data.catalog.items.map(p=>[p.stock_state,p.reference_stock,p.reference_collection_state,p.available_sizes,p.recommended_total_cny]),Object.values(data.details).map(f=>Object.values(f.variants).map(d=>[d.fx.stale,d.recommended_offer_id,d.variants.map(v=>v.in_stock),d.colors.map(c=>c.in_stock),d.offers.map(q=>[q.eligible,q.reasons,q.offer.stock,q.offer.collection_state,q.offer.price])]))])}
function publishedContentVersion(data){return data.verification_identities?data.publication.version.slice(-64):data.publication.version}
let publishedCursor=0,publicationVersion='',freshnessState='';
loadPublished().then(data=>{publishedCursor=Math.max(publishedCursor,Number(data.updates.cursor)||0);publicationVersion=publishedContentVersion(data);freshnessState=publishedFreshness(data)}).catch(()=>{});
function notifyPublished(data){refreshPublicInventory(data);const nextFreshness=publishedFreshness(data),freshnessChanged=nextFreshness!==freshnessState||publicPendingSafetyChange;const events=data.updates.items.filter(row=>row.id>publishedCursor);publishedCursor=Math.max(publishedCursor,Number(data.updates.cursor)||0);if(publishedContentVersion(data)===publicationVersion&&!freshnessChanged&&!events.length)return;publicationVersion=publishedContentVersion(data);freshnessState=nextFreshness;publicPendingSafetyChange=false;window.dispatchEvent(new CustomEvent('bikehunt-published',{detail:{events,freshnessChanged}}));}
async function pollPublished(){
  // Expiry is clock-driven, even if this network check hangs or fails offline.
  if(publicLastData)notifyPublished(publicLastData);
  try{notifyPublished(await loadPublished(true))}catch{/* Keep last verified data; never reset its source timestamps. */}
}
const publishedTimer=setInterval(()=>pollPublished().catch(()=>{}),60000);
window.addEventListener('focus',()=>pollPublished().catch(()=>{}));
window.addEventListener('pagehide',()=>clearInterval(publishedTimer),{once:true});
