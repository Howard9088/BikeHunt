'use strict';
(function(root){
  const IMAGE_PATH=/^\/web\/assets\/community\/[A-Za-z0-9][A-Za-z0-9_-]*\.(?:png|jpg|jpeg)$/;
  function expiryTime(value){
    if(typeof value!=='string')return NaN;
    const match=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
    if(!match)return NaN;
    const [,year,month,day,hour,minute,second,,zone,,zoneHour,zoneMinute]=match;
    const date=new Date(0);date.setUTCFullYear(+year,+month-1,+day);date.setUTCHours(+hour,+minute,+second,0);
    if(date.getUTCFullYear()!==+year||date.getUTCMonth()!==+month-1||date.getUTCDate()!==+day||date.getUTCHours()!==+hour||date.getUTCMinutes()!==+minute||date.getUTCSeconds()!==+second||zone!=='Z'&&(+zoneHour>23||+zoneMinute>59))return NaN;
    return Date.parse(value);
  }
  function inspect(data,now=Date.now()){
    if(!data||typeof data!=='object'||data.schema_version!==1)return {status:'invalid'};
    const expires=expiryTime(data.expires_at);
    if(Number.isFinite(expires)&&expires<=now)return {status:'expired'};
    if(data.expired===true)return {status:'expired'};
    if(data.configured===false)return {status:'unconfigured'};
    if(!Number.isFinite(expires)||data.available!==true||data.configured!==true||typeof data.title!=='string'||!data.title.trim()||data.title.length>60||typeof data.image_url!=='string'||!IMAGE_PATH.test(data.image_url))return {status:'invalid'};
    return {status:'available',expires,title:data.title.trim(),image:data.image_url,label:typeof data.expiry_label==='string'&&data.expiry_label.length<=100?data.expiry_label:''};
  }
  function start(document,window){
    const image=document.getElementById('groupQr'),status=document.getElementById('groupStatus'),title=document.getElementById('groupTitle');
    const notices={expired:'群二维码已到期，等待更新。',unconfigured:'群二维码等待更新。',invalid:'群二维码信息待更新。',offline:'当前离线，请联网后重新打开。',error:'暂时无法读取群二维码，请稍后重试。',image:'二维码暂时无法显示，请稍后重试。'};
    let sequence=0,expiryTimer=0,refreshTimer=0,timeoutTimer=0,controller=null,current=null;
    let anchor=Date.now(),anchorTick=window.performance.now();
    const now=()=>Math.max(Date.now(),anchor+Math.max(0,window.performance.now()-anchorTick));
    function hide(message){
      image.onload=null;image.onerror=null;image.hidden=true;image.removeAttribute('src');
      status.textContent=message;window.clearTimeout(expiryTimer);expiryTimer=0;
    }
    function cancel(){++sequence;controller?.abort();controller=null;window.clearTimeout(timeoutTimer);window.clearTimeout(refreshTimer);timeoutTimer=refreshTimer=0;current=null;}
    function stop(reason){cancel();hide(notices[reason]);}
    function check(){
      if(window.navigator.onLine===false){stop('offline');return false;}
      if(!current||inspect(current,now()).status!=='available'){stop(current&&inspect(current,now()).status==='expired'?'expired':'invalid');return false;}
      return true;
    }
    function armExpiry(expires){window.clearTimeout(expiryTimer);expiryTimer=window.setTimeout(()=>{if(check())armExpiry(expires)},Math.max(0,Math.min(expires-now(),2147483647)));}
    async function load(){
      cancel();hide('正在读取群二维码…');
      if(window.navigator.onLine===false){stop('offline');return;}
      const request=sequence;
      controller=new window.AbortController();
      timeoutTimer=window.setTimeout(()=>{if(request===sequence)stop('error')},10000);
      try{
        const url=new URL(document.body.dataset.communitySource,window.location.href);
        if(url.origin!==window.location.origin)throw Error('Unexpected source');
        url.searchParams.set('_',String(Math.floor(now()))+'-'+request);
        const response=await window.fetch(url.href,{cache:'no-store',credentials:'omit',redirect:'error',signal:controller.signal});
        if(!response.ok)throw Error('Group settings unavailable');
        const data=await response.json();
        if(request!==sequence)return;
        window.clearTimeout(timeoutTimer);
        const serverTime=Date.parse(response.headers.get('Date')||'');
        anchor=Math.max(now(),Number.isFinite(serverTime)?serverTime:0);anchorTick=window.performance.now();
        const state=inspect(data,now());
        if(state.status!=='available'){stop(state.status);return;}
        current=data;
        if(!check())return;
        const base=new URL(document.body.dataset.imageBase,window.location.href);
        if(base.origin!==window.location.origin)throw Error('Unexpected image base');
        const imageUrl=new URL(state.image.slice(1),base);
        imageUrl.searchParams.set('v',typeof data.revision==='string'?data.revision:data.expires_at);
        title.textContent=state.title;image.alt=state.title+'入群二维码';
        image.onload=()=>{if(request!==sequence||!check())return;image.hidden=false;status.textContent=state.label||'请按微信提示识别群二维码。';};
        image.onerror=()=>{if(request===sequence)stop('image');};
        image.src=imageUrl.href;
        armExpiry(state.expires);
        // A long-open tab also learns about a replaced/revoked code. Never fall back to cached settings.
        refreshTimer=window.setTimeout(load,60000);
      }catch(error){if(request===sequence)stop('error');}
    }
    window.addEventListener('offline',()=>stop('offline'));
    window.addEventListener('online',load);
    window.addEventListener('focus',load);
    window.addEventListener('pagehide',()=>{cancel();hide('正在读取群二维码…');});
    window.addEventListener('pageshow',event=>{if(event.persisted)load();});
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')load();else if(current)check();});
    document.getElementById('groupBack').addEventListener('click',event=>{
      try{const previous=new URL(document.referrer),home=new URL('../',window.location.href);
        if(previous.origin===home.origin&&previous.pathname===home.pathname){event.preventDefault();window.history.back();}
      }catch{/* Direct and bookmarked visits use the ordinary home link. */}
    });
    load();
    return {load,check,stop};
  }
  if(typeof module==='object'&&module.exports)module.exports={expiryTime,inspect,start};
  else if(root.document)start(root.document,root);
})(typeof window==='object'?window:globalThis);
