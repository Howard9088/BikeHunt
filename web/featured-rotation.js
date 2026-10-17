'use strict';
let featuredBatch=null,featuredBoundaryTimer;
function markFeaturedBatch(){
  const label=document.getElementById('featuredSchedule');
  if(!featuredBrowse()||activeTab!=='products'){if(label)label.hidden=true;return;}
  const slot=BikeHuntListingOrder.homeSlot();featuredBatch=slot.index;
  if(label){label.hidden=false;label.textContent=slot.label+' · 11:30 / 18:00 换批';label.title='北京时间；新发布优先，商品真实发布时间不变';}
}
function refreshFeaturedBatch(){
  const slot=BikeHuntListingOrder.homeSlot();
  if(catalogLoadState==='ready'&&featuredBrowse()&&activeTab==='products'&&!sheet.classList.contains('open')&&featuredBatch!==slot.index)render();
  clearTimeout(featuredBoundaryTimer);
  featuredBoundaryTimer=setTimeout(refreshFeaturedBatch,Math.max(50,slot.next-Date.now()+20));
}
window.addEventListener('focus',refreshFeaturedBatch);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshFeaturedBatch()});
// Closing a detail/guide applies any deferred batch without altering the dialog.
document.getElementById('close').addEventListener('click',refreshFeaturedBatch);
document.getElementById('overlay').addEventListener('click',refreshFeaturedBatch);
document.addEventListener('keydown',event=>{if(event.key==='Escape')setTimeout(refreshFeaturedBatch,0)});
window.addEventListener('pagehide',()=>clearTimeout(featuredBoundaryTimer));
refreshFeaturedBatch();
