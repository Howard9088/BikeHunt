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
  // Two Beijing slots: 11:30 and 18:00. The evening batch lasts overnight.
  function homeSlot(now=Date.now()){
    const day=86400000,local=now+8*3600000,date=Math.floor(local/day),minute=(local-date*day)/60000;
    const index=minute<690?date*2-1:minute<1080?date*2:date*2+1;
    const start=(minute<690?(date-1)*day+1080*60000:date*day+(minute<1080?690:1080)*60000)-8*3600000;
    const next=(minute<690?date*day+690*60000:minute<1080?date*day+1080*60000:(date+1)*day+690*60000)-8*3600000;
    return {index,start,next,label:minute>=690&&minute<1080?'午间精选':'晚间精选'};
  }
  // Caller supplies exact-quote eligibility and model/channel keys. Selection
  // changes only presentation; the original cards and listing ledger stay intact.
  function selectHome(cards,{eligible,channelKey,modelKey,now=Date.now(),explicitCompare=null,rotate=false}){
    const buckets=new Map(),cmp=explicitCompare||((a,b)=>compareHome(a,b,now));
    for(const card of cards){if(!eligible(card,now))continue;const key=channelKey(card);if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push(card);}
    const chosen=[];
    for(const pool of buckets.values()){
      const seen=new Set(),models=[];
      for(const card of pool.sort((a,b)=>cmp(a,b)||stableID(a,b))){const key=modelKey(card);if(!seen.has(key)){seen.add(key);models.push(card);}}
      if(!rotate||models.length<=2){chosen.push(...models.slice(0,2));continue;}
      // Keep the newest real publication for 24h, leaving the second slot free
      // to rotate even when many first-listing receipts arrive together.
      const fresh=models.filter(card=>{const stamp=listingTime(card,now);return stamp!==null&&now-stamp<86400000}).slice(0,1);
      const rest=models.filter(card=>!fresh.includes(card)),take=2-fresh.length;
      const offset=((homeSlot(now).index%rest.length)+rest.length)%rest.length;
      chosen.push(...fresh,...Array.from({length:take},(_,i)=>rest[(offset+i)%rest.length]));
    }
    return chosen.sort((a,b)=>cmp(a,b)||stableID(a,b));
  }
  const api={listingTime,listingLabel,compareListing,compareHome,orderCatalog,selectHome,homeSlot};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.BikeHuntListingOrder=Object.freeze(api);
})(typeof globalThis==='object'?globalThis:this);
