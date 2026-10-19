'use strict';
// Local-only product bookmarks. Prices/stock are never persisted or replayed.
const BikeHuntFavorites = (() => {
  const key='bikehuntFavoritesV1';
  const text=(value,max=200)=>typeof value==='string'?value.slice(0,max):'';
  const id=value=>typeof value==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(value)?value:null;
  function parse(raw){
    if(raw===null)return [];
    const data=JSON.parse(raw);
    if(data?.version!==1||!Array.isArray(data.items))throw Error('Invalid favorites');
    const unique=new Map();
    for(const row of data.items.slice(0,1000)){
      if(!row||!id(row.productId)||unique.has(row.productId))continue;
      unique.set(row.productId,{productId:row.productId,name:text(row.name),brand:text(row.brand),color:text(row.color),variantId:id(row.variantId),size:text(row.size),savedAt:text(row.savedAt,40)});
    }
    return [...unique.values()];
  }
  function create(storage){
    let rows=[],warning='';
    function read(){try{rows=parse(storage().getItem(key));warning=''}catch{warning='本地收藏暂时无法读取；本次操作仍可使用。'}}
    read();
    return {list:()=>rows.map(row=>({...row})),has:productId=>rows.some(row=>row.productId===productId),warning:()=>warning,reload:read,
      toggle(row){
        if(!id(row.productId))return false;
        const exists=rows.some(saved=>saved.productId===row.productId);
        rows=exists?rows.filter(saved=>saved.productId!==row.productId):parse(JSON.stringify({version:1,items:[...rows,row]}));
        try{storage().setItem(key,JSON.stringify({version:1,items:rows}));warning=''}catch{warning='浏览器未能保存收藏；刷新或离开后，本次更改可能丢失。'}
        return !exists;
      }};
  }
  return {key,parse,create};
})();
if(typeof module!=='undefined')module.exports=BikeHuntFavorites;

if(typeof document!=='undefined'){
  const favorites=BikeHuntFavorites.create(()=>window.localStorage);
  let explicitSelection=null;
  const heart='<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/></svg>';
  function button(productId,name,detail=false){return '<button type="button" class="favorite-toggle'+(detail?' favorite-detail':'')+'" data-favorite="'+e(productId)+'" data-favorite-name="'+e(name)+'" aria-pressed="'+favorites.has(productId)+'" aria-label="'+(favorites.has(productId)?'取消收藏':'收藏')+' '+e(name)+'">'+heart+(detail?'<span>收藏商品</span>':'')+'</button>'}
  function sync(){
    document.querySelectorAll('[data-favorite]').forEach(node=>{
      const saved=favorites.has(node.dataset.favorite);node.setAttribute('aria-pressed',String(saved));node.setAttribute('aria-label',(saved?'取消收藏 ':'收藏 ')+node.dataset.favoriteName);
      const label=node.querySelector('span');if(label)label.textContent=saved?'已收藏':'收藏商品';
    });
    const count=favorites.list().length,entry=document.getElementById('myFavorites');if(entry){entry.textContent='我的收藏'+(count?' ('+count+')':'');entry.setAttribute('aria-label','我的收藏，'+count+' 件商品')}
    const notice=document.getElementById('favoriteNotice');if(notice)notice.textContent=favorites.warning();
  }
  function announce(message){const status=document.getElementById('favoriteStatus');if(status){status.textContent=message+(favorites.warning()?' '+favorites.warning():'');status.className=favorites.warning()?'favorite-storage-warning':'sr-only'}}
  function toggle(productId){
    const detail=typeof currentProduct!=='undefined'&&currentProduct?.product_id===productId?currentProduct:null;
    const product=items.find(row=>row.product_id===productId),saved=favorites.list().find(row=>row.productId===productId);
    const explicit=detail&&explicitSelection?.productId===productId&&explicitSelection.variantId===detail.variant_id;
    const added=favorites.toggle({productId,name:product?.name||detail?.name||saved?.name||'商品',brand:product?.brand||detail?.identity?.brand||saved?.brand||'',color:product?.color||detail?.identity?.color||'',variantId:explicit?detail.variant_id:null,size:explicit?detail.identity.size:'',savedAt:new Date().toISOString()});
    sync();announce(added?'已加入收藏':'已取消收藏');
  }
  function listMarkup(){
    const rows=favorites.list();
    const intro='<p class="favorites-note">仅保存在此浏览器，无需登录；清除浏览器数据会移除收藏。价格与库存以最新核验及官网为准。</p><p id="favoriteNotice" class="favorites-warning" role="status">'+e(favorites.warning())+'</p>';
    if(!rows.length)return intro+'<div class="favorites-empty"><strong>还没有收藏商品</strong><p>点商品上的爱心，留着下次慢慢比较。</p><button type="button" data-favorites-browse>继续逛逛</button></div>';
    return intro+'<div class="favorites-list">'+rows.map(saved=>{
      const row=items.find(p=>p.product_id===saved.productId&&publicProductVisible(p));
      const unavailable=!row,loading=catalogLoadState!=='ready';
      const status=loading?'商品资料尚未加载，请稍后重试':unavailable?'当前目录暂无此商品，可能已下架；库存无法确认':row.stock_state==='out_of_stock'?'所示报价已售罄':row.reference_collection_state==='retained'?'保留的历史报价 · 库存待重新核实':row.stock_state==='in_stock'&&inventoryVerified(row)?'上次核验有货 · 当前库存请到官网确认':'库存待核实';
      const price=row&&!loading&&row.reference_price?'<p>'+(currentPriceEvidence({fetched_at:row.fetched_at,collection_state:row.reference_collection_state,price_valid_until:row.reference_price_valid_until})?'当前目录参考商品价':'上次记录商品价')+' '+e(money(row.reference_price.amount,row.reference_price.currency))+' · '+e(row.reference_source)+'<br>所示规格 '+e(row.reference_size||'待核实')+' · 不含运税</p><p>上次核验 '+e(timeText(row.fetched_at))+'</p>':'';
      return '<article class="favorite-item" data-saved-product="'+e(saved.productId)+'"><div class="favorite-item-title"><h4>'+e(row?.name_zh||row?.name||saved.name)+'</h4>'+button(saved.productId,row?.name||saved.name)+'</div><p>'+e(row?.brand||saved.brand)+(saved.color?' · '+e(saved.color):'')+'</p>'+(saved.size?'<p>收藏时所选规格：'+e(saved.size)+'<br>打开后重新选择规格，核对库存与价格</p>':'')+'<p class="favorite-availability">'+e(status)+'</p>'+price+(!unavailable&&!loading?'<button type="button" class="favorite-open" data-favorite-open="'+e(saved.productId)+'">查看商品与最新规格 →</button>':'')+'</article>';
    }).join('')+'</div>';
  }
  function renderList(){const body=document.getElementById('sheetBody'),focused=document.activeElement,focusId=focused?.dataset.favorite||focused?.dataset.favoriteOpen,wasOpen=!!focused?.dataset.favoriteOpen,scroll=body.scrollTop;body.innerHTML='<section id="favoritesPanel">'+listMarkup()+'</section>';sync();body.scrollTop=scroll;if(focusId){const nodes=body.querySelectorAll(wasOpen?'[data-favorite-open]':'[data-favorite]');[...nodes].find(node=>(wasOpen?node.dataset.favoriteOpen:node.dataset.favorite)===focusId)?.focus({preventScroll:true})}}
  function open(){openPanel('我的收藏', '');renderList()}
  window.favoriteButtonMarkup=button;
  window.favoriteSelectionChanged=(productId,variantId)=>{explicitSelection=productId&&variantId?{productId,variantId}:null};
  window.syncFavoriteControls=sync;
  window.refreshFavoritesPanel=()=>{if(document.getElementById('favoritesPanel')&&sheet.classList.contains('open'))renderList();else sync()};
  document.addEventListener('click',event=>{
    const target=event.target.closest?.('[data-favorite]');
    if(target){event.preventDefault();event.stopPropagation();const productId=target.dataset.favorite;toggle(productId);if(target.closest('#favoritesPanel')){const index=[...document.querySelectorAll('#favoritesPanel [data-favorite]')].indexOf(target);renderList();const buttons=[...document.querySelectorAll('#favoritesPanel [data-favorite]')];(buttons[Math.min(index,buttons.length-1)]||document.querySelector('[data-favorites-browse]'))?.focus()}return}
    const openButton=event.target.closest?.('[data-favorite-open]');
    if(openButton){const saved=favorites.list().find(row=>row.productId===openButton.dataset.favoriteOpen);openProduct(saved.productId,null,true);lastFocus=document.getElementById('myFavorites');return}
    if(event.target.closest?.('[data-favorites-browse]'))closeSheet();
  });
  window.addEventListener('storage',event=>{if(event.key===BikeHuntFavorites.key||event.key===null){favorites.reload();refreshFavoritesPanel()}});
  document.getElementById('myFavorites').onclick=open;
  sync();
}
