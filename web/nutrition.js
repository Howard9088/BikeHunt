'use strict';
// Nutrition and sunscreen use the same verified product/offer flow as other goods.
function nutritionSpecLabel(row={}){return row.category_group==='nutrition'?'口味与包装规格':row.category==='sunscreen'?'容量规格':'尺码'}
function nonFitProduct(row={}){return row.category_group==='nutrition'||row.category==='sunscreen'}
function nutritionDetailMarkup(detail={}){
  if(detail.category_group!=='nutrition')return '';
  const references=[...new Map((detail.offers||[]).filter(q=>q.offer?.url).map(q=>[q.offer.source_code+'|'+q.offer.url,q.offer])).values()];
  // Plain source evidence only; all outbound purchases retain the normal guarded flow.
  return '<details class="nutrition-product-reference"><summary>官网资料与补给说明</summary><div>'+references.map(row=>'<p>'+e(row.source_name)+' · '+e(row.name)+'<br><span class="nutrition-source">'+e(row.url)+'</span></p>').join('')+'<p>按所选商品标签核对口味、每份含量、包装数量、咖啡因版本及过敏原。单袋、整盒及不同配方应分别比较。价格与库存以所选商家规格为准；中国配送与支付条件需另行核实。食品补给不能替代均衡饮食。</p></div></details>';
}
