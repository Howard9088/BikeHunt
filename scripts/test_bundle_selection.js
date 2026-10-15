'use strict';
// Production logic/DOM-state regression. Browser layout is tested separately in CI.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const bundle=fs.readFileSync('web/bundle-variants.js','utf8'),gallery=fs.readFileSync('web/gallery.js','utf8'),flows=fs.readFileSync('web/flows.js','utf8'),purchase=fs.readFileSync('web/purchase-flow.js','utf8');
const fixture=JSON.parse(fs.readFileSync('tests/fixtures/soudal-outfit-variants.json','utf8'));
const NOW=Date.parse(fixture.provenance.snapshot_generated_at);
const clone=value=>JSON.parse(JSON.stringify(value));
function section(source,start,end){const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a);return source.slice(a,b)}
function detail(row=fixture.variants[0],rows=fixture.variants){return {product_id:fixture.product_id,variant_id:row.variant_id,name:fixture.name,name_zh:fixture.name,image:fixture.image,identity:clone(row.offer.identity),variants:rows.map(({offer,...variant})=>clone(variant)),colors:[],fx:{rate_date:'2026-10-15',stale:false},recommended_offer_id:null,offers:[{offer:clone(row.offer),eligible:false,reasons:[],product_cny:row.product_cny_from}]}}
function harness(){
  let html='',focused=null,open=true,now=NOW,result=null,fitCalls=0;const elements=new Map(),nodes=[],requests=[],guides=[];
  const staticElements=new Map(['sheetImg','sheetBrand','sheetName'].map(id=>[id,{style:{}}]));
  const attrs=text=>Object.fromEntries([...text.matchAll(/([\w-]+)="([^"]*)"/g)].map(match=>[match[1],match[2]]));
  const matches=(node,selector)=>selector.startsWith('.')?(node.attrs.class||'').split(' ').includes(selector.slice(1)):selector.startsWith('[')?Object.hasOwn(node.attrs,selector.slice(1,-1)):false;
  function render(content){
    html=content;elements.clear();nodes.splice(0);
    for(const match of content.matchAll(/<(select|button|section|details|p|h4)\b([^>]*)>/g)){
      const a=attrs(match[2]),node={attrs:a,id:a.id,dataset:Object.fromEntries(Object.entries(a).filter(([key])=>key.startsWith('data-')).map(([key,value])=>[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),value])),disabled:/\bdisabled\b/.test(match[2]),value:'',focus(){focused=this.id},getAttribute(key){return this.attrs[key]}};
      if(match[1]==='select'){
        const inner=content.slice(match.index+match[0].length).split('</select>')[0];
        node.options=[...inner.matchAll(/<option([^>]*)>(.*?)<\/option>/g)].map(option=>({value:attrs(option[1]).value,disabled:/\bdisabled\b/.test(option[1]),selected:/\bselected\b/.test(option[1]),text:option[2]}));
        node.value=node.options.find(option=>option.selected)?.value||'';
      }
      nodes.push(node);if(a.id)elements.set(a.id,node);
    }
  }
  const body={querySelectorAll:selector=>nodes.filter(node=>matches(node,selector))};Object.defineProperty(body,'innerHTML',{get:()=>html,set:render});
  class Clock extends Date{constructor(...args){super(...(args.length?args:[now]))}static now(){return now}}
  const c=vm.createContext({Date:Clock,URL,Number,Intl,Set,Map,Object,JSON,String,Array,console,
    currentProduct:null,currentBundleSelection:null,detailSequence:0,guideContext:null,referenceOffers:new Map(),restoringPurchase:false,
    sheet:{classList:{contains:()=>open}},window:{BIKEHUNT_PAGES:false},history:{state:{unrelated:'keep',bikehuntBrowse:{source:'soudal',query:'Cycling outfit',category:'accessories'}},replaceState(value){this.state=value}},
    document:{getElementById:id=>id==='sheetBody'?body:staticElements.get(id)||elements.get(id)||null},
    e:value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),safeUrl:value=>value||'',cny:value=>'CNY '+value,money:(value,currency)=>currency+' '+value,timeText:value=>value,
    cancelPurchaseContext(){c.guideContext=null},saveBrowseState(){},bindMerchantGuides(){},refreshFitReference(){fitCalls++},startGuide(d,offerId){guides.push([d.variant_id,offerId])},
    getJson:async url=>{requests.push(url);return typeof result==='function'?result(url):result},
  });
  vm.runInContext(fs.readFileSync('web/public-visibility.js','utf8'),c);
 vm.runInContext(bundle,c);
  vm.runInContext(section(gallery,'function inventoryVerified(','function detailSelectorVisible('),c);
  vm.runInContext(section(gallery,'function detailSelectorVisible(','function openProduct('),c);
  vm.runInContext(section(purchase,'function rememberPurchaseDetail(','function cancelPurchaseContext('),c);
  return {c,elements,nodes,requests,guides,get html(){return html},get focused(){return focused},get fitCalls(){return fitCalls},get selected(){return c.currentBundleSelection},setResult(value){result=value},setNow(value){now=value},close(){open=false;c.detailSequence++},async change(key,value){const node=elements.get('bundle-'+key);assert.ok(node&&!node.disabled,key);assert.ok(node.options.some(option=>option.value===value&&!option.disabled),value);node.value=value;return node.onchange()},render(d=detail(),variantId=null,options={}){c.renderProductDetail(d,variantId,++c.detailSequence,options)}};
}
function testActualMerchantRowsAndConservativeParsing(){
 const h=harness(),before=JSON.stringify(fixture),model=h.c.bundleVariantModel(detail());
 assert.equal(model.length,60);assert.equal(model.filter(row=>row.variant.in_stock).length,50);
 for(const row of fixture.variants){const parts=h.c.parseBundleSize(row.size);assert.ok(parts);const exact=h.c.exactBundleVariant(model,parts);assert.equal(exact?.variant_id||null,row.in_stock?row.variant_id:null);assert.equal(row.offer.identity.size,row.size);assert.equal(row.offer.price.currency,'EUR');assert.equal(new URL(row.offer.url).hostname,'thewolfpack.shop')}
 assert.equal(JSON.stringify(fixture),before,'No identity, original labels, prices, stock or image mutation');
 for(const invalid of ['M','S / M / L','Bundle: M / Bib: L / Socks: S-M',fixture.variants[0].size+' / Bonus: M',fixture.variants[0].size.replace('Jersey 2026','Jersey 2025'),fixture.variants[0].size.replace('Socks','Other'),fixture.variants[0].size.replace('(Size): M','(Size): <M>')])assert.equal(h.c.parseBundleSize(invalid),null);
 for(const mutate of [d=>d.variants.push({...d.variants[0],variant_id:'ambiguous'}),d=>d.variants[0].size='unknown multi-part variant',d=>d.variants[0].size=d.variants[0].size.replaceAll('2026','2025')]){const d=detail();mutate(d);assert.equal(h.c.bundleVariantModel(d),null,'Mixed/unknown/ambiguous family must fall back')}
 assert.ok(h.c.parseBundleSize(fixture.variants[0].size.replaceAll(' I ',' | ')));
}
function testSparseRelationAndDisabledStock(){
 const h=harness(),first=fixture.variants[0],parts=h.c.parseBundleSize(first.size),other=fixture.variants.find(row=>row.in_stock&&h.c.parseBundleSize(row.size).jersey!==parts.jersey&&h.c.parseBundleSize(row.size).bib!==parts.bib&&h.c.parseBundleSize(row.size).socks!==parts.socks);
 const model=h.c.bundleVariantModel(detail(first,[first,other]));assert.ok(other);
 const values=h.c.bundleOptions(model,{jersey:parts.jersey},1);assert.deepEqual(Array.from(values,row=>row.value),[parts.bib]);
 assert.equal(h.c.exactBundleVariant(model,{...parts,bib:h.c.parseBundleSize(other.size).bib}),null,'Never synthesize an unsold combination');
 const full=h.c.bundleVariantModel(detail()),bib=h.c.bundleOptions(full,{jersey:'S'},1).find(row=>row.value==='3XL');assert.equal(bib.available,false);assert.equal(bib.status,'已售罄');
 const stale=detail();stale.variants.forEach(row=>{row.in_stock=false;row.stock_state='unknown'});assert.ok(h.c.bundleOptions(h.c.bundleVariantModel(stale),{},0).every(row=>!row.available&&row.status==='库存待核实'));
}
async function testProgressiveExactSelectionAndFocus(){
 const h=harness(),row=fixture.variants[0],parts=h.c.parseBundleSize(row.size),d=detail();h.render(d);
 assert.ok(h.html.includes('选择三件套尺码'));assert.equal(h.elements.has('variant'),false);assert.equal(h.elements.get('bundle-bib').disabled,true);assert.equal(h.elements.get('bundle-socks').disabled,true);assert.ok(!h.html.includes('guide-start'));assert.ok(!h.html.includes('data-reference-link'));assert.ok(!h.html.includes(row.size));
 await h.change('jersey',parts.jersey);assert.equal(h.focused,'bundle-bib');assert.ok(!h.html.includes('guide-start'));assert.equal(h.elements.get('bundle-socks').disabled,true);
 await h.change('bib',parts.bib);assert.equal(h.focused,'bundle-socks');assert.ok(!h.html.includes('guide-start'));
 h.setResult(clone(d));await h.change('socks',parts.socks);await new Promise(resolve=>setImmediate(resolve));
 assert.equal(h.requests.at(-1),'/api/catalog/'+fixture.product_id+'?variant_id='+row.variant_id);assert.equal(h.selected.variantId,row.variant_id);assert.ok(h.html.includes('data-offer="'+row.offer.offer_id+'"'));assert.ok(h.html.includes('EUR '+row.offer.price.amount));assert.ok(h.html.includes('class="bundle-original"'));assert.ok(h.html.includes(row.size));
 assert.ok(!h.html.includes('<select id="variant"'));assert.ok(h.nodes.filter(node=>node.options).every(node=>node.options.every(option=>option.text.length<35)));
 const button=h.nodes.find(node=>node.dataset.offer===row.offer.offer_id);button.onclick();assert.deepEqual(h.guides,[[row.variant_id,row.offer.offer_id]]);
 assert.equal(h.c.history.state.bikehuntPurchase.variantId,row.variant_id);assert.equal(h.c.history.state.unrelated,'keep');assert.equal(h.c.history.state.bikehuntBrowse.query,'Cycling outfit');
 await h.change('jersey',parts.jersey);assert.equal(h.selected.variantId,null);assert.equal(h.elements.get('bundle-bib').value,'');assert.equal(h.elements.get('bundle-socks').value,'');assert.ok(!h.html.includes('guide-start'));assert.equal(h.fitCalls,0,'Single-garment fit suggestions must not infer a bundle fit');
}
async function testRefreshInvalidationAndRaceSafety(){
 for(const kind of ['sold','price','currency','retained','observed']){
  const h=harness(),row=fixture.variants[0],fresh=detail();h.render(detail(),row.variant_id);
  if(kind==='sold'){fresh.offers[0].offer.stock='out_of_stock';fresh.variants[0].in_stock=false;fresh.variants[0].stock_state='out_of_stock'}
  if(kind==='price')fresh.offers[0].offer.price.amount='229.00';
  if(kind==='currency')fresh.offers[0].offer.price.currency='USD';
  if(kind==='retained')fresh.offers[0].offer.collection_state='retained';
  let resolve;h.setResult(()=>new Promise(done=>resolve=done));const pending=h.c.refreshOpenProductDetail(kind==='observed'?[{offer_id:row.offer.offer_id,stock:'out_of_stock'}]:[]);
  assert.ok(!h.html.includes('guide-start'),'Disable old action synchronously before waiting');resolve(fresh);await pending;
  assert.equal(h.selected.variantId,null,kind);assert.ok(!h.html.includes('guide-start'));assert.ok(h.html.includes('重新选择袜子'));
 }
 const unchanged=harness(),row=fixture.variants[0];unchanged.render(detail(),row.variant_id);unchanged.setResult(detail());await unchanged.c.refreshOpenProductDetail();assert.equal(unchanged.selected.variantId,row.variant_id);
 const partial=harness();partial.render();await partial.change('jersey','XL');const changedDefault=detail();changedDefault.offers[0].offer.price.amount='229.00';partial.setResult(changedDefault);await partial.c.refreshOpenProductDetail();assert.deepEqual(clone(partial.selected.selection),{jersey:'XL'},'A refreshed default quote must never substitute the user’s partial sizes');assert.equal(partial.selected.variantId,null);
 const cancelled=harness();let resolve;cancelled.setResult(()=>new Promise(done=>resolve=done));const pending=cancelled.c.loadDetail(fixture.product_id,row.variant_id);cancelled.close();resolve(detail());await pending;assert.ok(!cancelled.html.includes('guide-start'));
 const mismatch=harness();mismatch.setResult({...detail(),variant_id:'wrong'});await mismatch.c.loadDetail(fixture.product_id,row.variant_id);assert.ok(mismatch.html.includes('所选规格已变化'));assert.ok(!mismatch.html.includes('guide-start'));
}
async function testObservedChangesCannotReviveStaleBundleQuotes(){
 const row=fixture.variants[0],parts=harness().c.parseBundleSize(row.size);
 for(const change of [{stock:'out_of_stock'},{new_price:'999.00',currency:'EUR'},{new_price:'228.00',currency:'USD'}]){
  const h=harness();h.render(detail(),row.variant_id);h.setResult(detail());const event={offer_id:row.offer.offer_id,...change};await h.c.refreshOpenProductDetail([event]);
  assert.ok(!h.html.includes('guide-start'));assert.equal(h.c.offerAvailable(detail().offers[0]),false);
  // Even a direct exact-ID reload, or history restoration in a new JS context,
  // cannot revive the rejected quote while the API still serves old bytes.
  await h.c.loadDetail(fixture.product_id,row.variant_id);assert.ok(!h.html.includes('guide-start'));
  const restored=harness();restored.c.history.state=clone(h.c.history.state);restored.setResult(detail());await restored.c.loadDetail(fixture.product_id,row.variant_id);assert.ok(!restored.html.includes('guide-start'));
  const latest=detail();if(change.stock){latest.offers[0].offer.stock=change.stock;latest.variants[0].in_stock=false;latest.variants[0].stock_state=change.stock}else{latest.offers[0].offer.price={amount:change.new_price,currency:change.currency}}
  h.setResult(latest);await h.c.loadDetail(fixture.product_id,row.variant_id);assert.equal(h.html.includes('guide-start'),!change.stock,'Only a matching updated quote can become selectable again');
 }
 const recovery=harness();recovery.render(detail(),row.variant_id);recovery.setResult(detail());await recovery.c.refreshOpenProductDetail([{offer_id:row.offer.offer_id,stock:'out_of_stock',observed_at:'2026-10-15T03:30:00Z'}]);
 const newer=detail();newer.offers[0].offer.fetched_at='2026-10-15T03:35:00Z';recovery.setResult(newer);await recovery.c.loadDetail(fixture.product_id,row.variant_id);assert.ok(recovery.html.includes('guide-start'),'A genuinely newer verified observation can resolve an old stock event');
 const {harness:routeHarness}=require('./test_route_flow.js'),route=routeHarness(),d=detail();d.offers[0].offer.fetched_at='2026-10-15T12:00:00Z';vm.runInContext(bundle,route.c);route.open(d);route.c.selectPurchaseRoute('direct');await route.c.invalidatePurchaseFlow([{offer_id:row.offer.offer_id,new_price:'999.00',currency:'EUR'}]);
 assert.equal(route.c.history.state.bikehuntPurchase.invalidated,true);route.setResult(clone(d));await route.c.restorePurchaseState();assert.equal(route.elements.get('routeContinue').disabled,true);assert.equal(route.c.guideContext.invalidated,true);
}
async function testGuardedNonDefaultVariantCanBeRechecked(){
 const h=harness(),row=fixture.variants.find((item,index)=>index>0&&item.in_stock),exact=detail(row);h.render(exact,row.variant_id);h.setResult(exact);
 await h.c.refreshOpenProductDetail([{offer_id:row.offer.offer_id,stock:'out_of_stock',observed_at:'2026-10-15T03:30:00Z'}]);
 h.render(detail());assert.ok(h.html.includes('data-bundle-recheck'));assert.equal(h.c.bundleVariantBlocked(fixture.product_id,row.variant_id),true);
 const updated=detail(row);updated.offers[0].offer.fetched_at='2026-10-15T03:35:00Z';
 h.setResult(url=>url.endsWith(row.variant_id)?clone(updated):detail());await h.c.recheckBundleQuotes();assert.equal(h.c.bundleVariantBlocked(fixture.product_id,row.variant_id),false);assert.ok(!h.html.includes('data-bundle-recheck'));assert.equal(h.selected.variantId,null,'Rechecking never auto-selects a quote');
 const changedUrl=harness();changedUrl.render(exact,row.variant_id);changedUrl.setResult(exact);await changedUrl.c.refreshOpenProductDetail([{offer_id:row.offer.offer_id,new_price:'229.00',currency:'EUR',observed_at:'2026-10-15T03:30:00Z'}]);
 const newer=detail(row);newer.offers[0].offer.price.amount='229.00';newer.offers[0].offer.fetched_at='2026-10-15T03:35:00Z';newer.offers[0].offer.url=newer.offers[0].offer.url.replace('/products/','/products/renamed-');assert.equal(changedUrl.c.bundleQuoteAllowed(newer.offers[0]),true);
 newer.offers[0].offer.url=newer.offers[0].offer.url.replace('thewolfpack.shop','another-merchant.example');assert.equal(changedUrl.c.bundleQuoteAllowed(newer.offers[0]),false);
 const closed=harness();closed.render(exact,row.variant_id);closed.c.recordBundleQuoteChanges(exact,[{offer_id:row.offer.offer_id,stock:'out_of_stock'}]);let resolve;closed.setResult(()=>new Promise(done=>resolve=done));const pending=closed.c.recheckBundleQuotes();closed.close();resolve(updated);await pending;assert.ok(!closed.html.includes('guide-start'));
}
function testUnknownFallbackSingleSizesAndCompactCards(){
 const h=harness(),d=detail();d.variants=d.variants.slice(0,2);d.variants.forEach((row,index)=>row.size='Unsupported merchant long bundle / unverified option schema '+index);d.identity.size=d.variants[0].size;h.render(d,d.variant_id);
 assert.equal(h.elements.has('bundleChoices'),false);assert.ok(h.html.includes('class="variant-original"'));assert.ok(h.html.includes(d.variants[0].size));assert.equal(h.elements.get('variant').options[1].text.startsWith('组合 1'),true);assert.ok(h.elements.get('variant').options.every(option=>option.text.length<70));
 const sold=clone(d);sold.variants[0].in_stock=false;sold.variants[0].stock_state='out_of_stock';sold.offers[0].offer.stock='out_of_stock';h.render(sold,sold.variant_id);assert.ok(h.html.includes(sold.identity.size));assert.ok(!h.html.includes('组合 0'));assert.ok(h.html.includes('组合 1（已售罄）'));
 d.variants[0].size=d.identity.size='M';d.variants[1].size='L';h.render(d,d.variant_id);assert.equal(h.elements.has('bundleChoices'),false);assert.ok(h.html.includes('>M</button>'));assert.ok(h.elements.get('variant').options[1].text.startsWith('M · '));assert.ok(h.fitCalls>0);
 assert.equal(h.c.catalogSizeLabel(fixture.card,false),'三件套 · 50 个现货组合');const sale={...fixture.card,reference_size:fixture.variants[0].size};assert.ok(h.c.catalogSizeLabel(sale,true).length<55);assert.ok(!h.c.catalogSizeLabel(sale,true).includes('Bib Short'));
 assert.equal(h.c.catalogSizeLabel({available_sizes:['M','L']},false),'现货 M / L');assert.equal(h.c.catalogSizeLabel({available_sizes:['unknown long bundle label '.repeat(4)]},false),'1 个现货组合 · 点开核对规格');
 assert.ok(!h.c.originalVariantMarkup('<script>'+('X'.repeat(50))+'</script>').includes('<script>'));
}
async function testExactBundleRouteHistoryAndStockRefresh(){
 const {harness:routeHarness}=require('./test_route_flow.js');const d=detail(),row=fixture.variants[0];d.offers[0].offer.fetched_at='2026-10-15T12:00:00Z';const h=routeHarness();vm.runInContext(bundle,h.c);h.open(d);h.c.selectPurchaseRoute('forwarding');h.c.continuePurchaseRoute();
 assert.ok(h.html.includes('上衣 S · 背带裤 M · 袜子 S-M'));const saved=clone(h.c.history.state.bikehuntPurchase);assert.equal(saved.variantId,row.variant_id);assert.equal(saved.offerId,row.offer.offer_id);assert.equal(saved.url,row.offer.url);
 h.setResult(clone(d));await h.c.restorePurchaseState();assert.equal(h.c.guideContext.detail.variant_id,row.variant_id);assert.equal(h.c.guideContext.route,'forwarding');assert.equal(h.c.guideContext.quote.offer.price.currency,'EUR');h.c.cancelRegistrationExit();h.elements.get('routeBack').onclick();assert.deepEqual(h.loaded.at(-1),[fixture.product_id,row.variant_id]);
 const changed=routeHarness();vm.runInContext(bundle,changed.c);changed.open(d);changed.c.selectPurchaseRoute('direct');changed.c.continuePurchaseRoute();await changed.c.invalidatePurchaseFlow([{offer_id:row.offer.offer_id,new_price:'999',currency:'EUR'}]);assert.equal(changed.elements.get('routeContinue').disabled,true);assert.equal(changed.reg,null);assert.equal(changed.navigated.length,0);
}
async function main(){for(const test of [testActualMerchantRowsAndConservativeParsing,testSparseRelationAndDisabledStock,testProgressiveExactSelectionAndFocus,testRefreshInvalidationAndRaceSafety,testObservedChangesCannotReviveStaleBundleQuotes,testGuardedNonDefaultVariantCanBeRechecked,testUnknownFallbackSingleSizesAndCompactCards,testExactBundleRouteHistoryAndStockRefresh]){await test();console.log('PASS '+test.name)}console.log('Bundle selection: eight real-fixture regression groups passed.');}
main().catch(error=>{console.error(error);process.exitCode=1});
