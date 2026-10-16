/* First public receipt time only. Inventory/FX timestamps are never fallbacks. */
(function(root){
  'use strict';
  const ISO=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
  function listingTime(card,now=Date.now()){
    const value=card&&card.first_listed_at;
    if(typeof value!=='string'||!ISO.test(value))return null;
    const [year,month,day]=value.slice(0,10).split('-').map(Number);
    const calendar=new Date(Date.UTC(year,month-1,day));
    if(calendar.getUTCFullYear()!==year||calendar.getUTCMonth()!==month-1||calendar.getUTCDate()!==day)return null;
    const stamp=Date.parse(value);
    return Number.isFinite(stamp)&&stamp<=now?stamp:null;
  }
  function listingLabel(card,now=Date.now()){
    const stamp=listingTime(card,now);
    if(stamp===null)return '本站发布：未记录';
    const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(stamp));
    const p=Object.fromEntries(parts.map(x=>[x.type,x.value]));
    return `本站发布：${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
  }
  function stableID(a,b){const x=String(a.product_id||''),y=String(b.product_id||'');return x<y?-1:x>y?1:0;}
  function compareListing(a,b,now=Date.now()){
    const x=listingTime(a,now),y=listingTime(b,now);
    if(x===null&&y!==null)return 1;if(y===null&&x!==null)return -1;
    return x!==null&&y!==null&&x!==y?y-x:0;
  }
  function price(card){const n=Number(card.reference_cny);return card.reference_cny!=null&&card.reference_cny!==''&&Number.isFinite(n)&&n>0?n:Infinity;}
  function compareHome(a,b,now=Date.now()){return compareListing(a,b,now)||(price(a)-price(b)||0)||stableID(a,b);}
  function orderCatalog(cards,{now=Date.now(),explicitCompare=null}={}){
    return [...cards].sort((a,b)=>Number(a.stock_state!=='in_stock')-Number(b.stock_state!=='in_stock')||
      (explicitCompare?explicitCompare(a,b):compareListing(a,b,now))||stableID(a,b));
  }
  // Caller supplies existing exact-quote eligibility and model/channel keys.
  function selectHome(cards,{eligible,channelKey,modelKey,now=Date.now(),explicitCompare=null}){
    const buckets=new Map(),cmp=explicitCompare||((a,b)=>compareHome(a,b,now));
    for(const card of cards){if(!eligible(card,now))continue;const key=channelKey(card);if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push(card);}
    const chosen=[];
    for(const pool of buckets.values()){
      const seen=new Set();let count=0;
      for(const card of pool.sort((a,b)=>cmp(a,b)||stableID(a,b))){const key=modelKey(card);if(seen.has(key))continue;seen.add(key);chosen.push(card);if(++count===2)break;}
    }
    return chosen.sort((a,b)=>cmp(a,b)||stableID(a,b));
  }
  const api={listingTime,listingLabel,compareListing,compareHome,orderCatalog,selectHome};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.BikeHuntListingOrder=Object.freeze(api);
})(typeof globalThis==='object'?globalThis:this);
