'use strict';
// Editorial links only: never Offer records, stock, prices or featured deals.
const NUTRITION_REFERENCES=Object.freeze([
  ['maurten','Maurten','Gel 100','https://www.maurten.com/products/gel-100-box-us'],
  ['sis','SiS','BETA Fuel Gel','https://www.scienceinsport.com/beta-fuel-gel-pack'],
  ['precision','Precision Fuel & Hydration','PF 30 Gel','https://www.precisionhydration.com/us/en/products/pf-30-gel/'],
  ['enervit','Enervit','Enervit Lactate','https://www.enervit.com/en/enervit-lactate'],
  ['skratch','Skratch Labs','Recovery Sport Drink Mix','https://www.skratchlabs.com/products/recovery-sport-drink-mix']
].map(([id,brand,name,url])=>Object.freeze({id,brand,name,url})));
function nutritionSpecLabel(row={}){return row.category_group==='nutrition'?'口味与包装规格':'尺码'}
function nutritionReferenceMatches(row){
  const terms=document.getElementById('q').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return terms.every(term=>(row.brand+' '+row.name+' 运动营养 补给').toLowerCase().includes(term));
}
function resetNutritionReferenceFeed(){gallery.classList.remove('nutrition-reference-feed')}
function renderNutritionReferences(){
  if(activeTab!=='products'||activeCategoryGroup!=='nutrition'||activeSource)return false;
  const rows=NUTRITION_REFERENCES.filter(nutritionReferenceMatches);
  gallery.classList.add('nutrition-reference-feed');
  document.getElementById('count').textContent=rows.length+' 个品牌资料';
  document.getElementById('scrollHint').classList.add('hidden');
  gallery.innerHTML='<section class="nutrition-reference-page" aria-labelledby="nutritionTitle"><h2 id="nutritionTitle">运动补能</h2><p>从品牌官网了解产品，先核对口味、每份含量、包装数量、咖啡因版本及过敏原。</p><p>目前提供官网资料入口，尚未接入已核实的商品报价与库存。中国官方销售渠道、配送与购买条件另行核实。</p><div class="nutrition-brand-grid">'+rows.map(row=>'<article class="nutrition-brand-reference"><div class="brand">'+e(row.brand)+'</div><h3>'+e(row.name)+'</h3><p>官网产品资料 · 无现货或价格保证</p><a href="'+e(row.url)+'" data-nutrition-reference="'+e(row.id)+'" target="_self" rel="noopener noreferrer">查看官网资料 →</a></article>').join('')+'</div>'+(!rows.length?'<p role="status">没有匹配的品牌资料，请调整搜索词。</p>':'')+'<p>比较商品前须确认同一口味、配方和包装。单袋、整盒、含咖啡因与无咖啡因版本不能直接当作同款比价。食品补给不能替代均衡饮食；请以商品标签为准。</p></section>';
  return true;
}
function allowedNutritionReference(link){
  if(!link?.isConnected||activeTab!=='products'||activeCategoryGroup!=='nutrition'||activeSource||gallery.hidden||gallery.inert||!gallery.contains(link))return null;
  return NUTRITION_REFERENCES.find(row=>row.id===link.dataset.nutritionReference&&row.url===link.getAttribute('href')&&nutritionReferenceMatches(row))||null;
}
function guardNutritionReference(event){
  const link=event.target.closest?.('a[data-nutrition-reference]');
  if(!link||(event.type==='auxclick'&&event.button!==1))return;
  event.preventDefault();const row=allowedNutritionReference(link);if(!row)return;
  showExternalExit({url:row.url,kind:'reference',label:row.brand+' · '+row.name,trigger:link,
    sourceNote:'品牌官网产品资料入口；不是中国官方销售渠道的认定。',
    note:'将打开海外官网资料。本站未核实当前价格、库存、中国配送或支付条件。',
    validate:()=>allowedNutritionReference(link)===row,onConfirm:()=>saveBrowseState()});
}
document.addEventListener('click',guardNutritionReference);
document.addEventListener('auxclick',guardNutritionReference);
