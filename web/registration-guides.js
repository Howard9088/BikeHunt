'use strict';
// Real screenshots only. Exact source + market lookup never falls back to another
// market. Public account pages are a separate, explicitly unverified-market scope.
const REGISTRATION_BASE=new URL('./',document.currentScript.src);
const REGISTRATION_HOSTS=Object.freeze({
  maap:['maap.cc','www.maap.cc','support.maap.cc'],teamcycles:['www.teamcycles.com'],sigmasports:['www.sigmasports.com'],
  rapha:['www.rapha.cc'],rapha_kr:['www.rapha.cc'],poc:['poc.com'],visma:['www.teamvismaleaseabike.com'],
  amazon_us:['www.amazon.com'],amazon_uk:['www.amazon.co.uk'],amazon_de:['www.amazon.de'],amazon_jp:['www.amazon.co.jp'],
  fizik:['www.fizik.com'],santini:['www.santinicycling.com'],soudal:['thewolfpack.shop'],ineos:['store.netcompanyineos.com'],
  bahrain:['alecycling.com'],decathlon:['shop.decathloncmacgmteam.com'],picnic:['teampicnicpostnl.store'],
  castelli:['www.castelli-cycling.com'],assos:['www.assos.com'],pns:['pasnormalstudios.com'],kask:['www.kask.com'],
  groupama:['shop.bioracer.com'],ef_team_shop:['efprocycling.shop'],uae:['www.pissei.com'],nsn:['www.ekoi.com'],
  lotto:['www.lotto-intermarche.be'],redbull:['www.redbullshop.com']
});
const REGISTRATION_ASSET=/^assets\/registration\/[a-z0-9][a-z0-9_-]*\.(?:png|jpg|jpeg|webp)$/;
let registrationData=null,registrationLoadState='loading',registrationRequest=null;
function registrationEscape(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function registrationText(value,max=300){return typeof value==='string'&&value.trim().length>0&&value.length<=max}
function registrationKey(sourceCode,salesRegion,scope='market'){return JSON.stringify([sourceCode,scope,salesRegion])}
function registrationSourceUrl(value,code){
  if(typeof value!=='string'||value.length>1500||!Object.prototype.hasOwnProperty.call(REGISTRATION_HOSTS,code))return false;
  try{const url=new URL(value);return url.href===value&&url.protocol==='https:'&&!url.username&&!url.password&&!url.port&&!url.search&&!url.hash&&REGISTRATION_HOSTS[code].includes(url.hostname)}catch{return false}
}
function registrationTimestamp(value,now=Date.now()){
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?$/.test(value))return false;
  if(value.length>10&&(Number(value.slice(11,13))>23||Number(value.slice(14,16))>59||Number(value.slice(17,19))>59))return false;
  const parsed=Date.parse(value),day=value.slice(0,10),dayTime=Date.parse(day);
  return Number.isFinite(parsed)&&parsed<=now&&Number.isFinite(dayTime)&&new Date(dayTime).toISOString().slice(0,10)===day;
}
function validateRegistrationData(data,now=Date.now()){
  if(!data||data.schemaVersion!==1||!registrationText(data.revision,100)||!Array.isArray(data.entries)||data.entries.length>200)throw Error('Invalid screenshot configuration');
  const keys=new Set();
  for(const entry of data.entries){
    if(!entry||!Object.prototype.hasOwnProperty.call(REGISTRATION_HOSTS,entry.sourceCode)||!['market','public_account'].includes(entry.scope)||
      (entry.scope==='market'?!registrationText(entry.salesRegion,300):entry.salesRegion!==null)||
      !registrationText(entry.marketLabel,120)||!registrationText(entry.revision,100)||!['verified','needs_review','unverified'].includes(entry.status)||
      !Array.isArray(entry.frames)||entry.frames.length>12||(entry.status==='verified'&&!entry.frames.length)||
      (entry.status!=='verified'&&!registrationText(entry.reviewReason,500))||
      (entry.checkedAt!==undefined&&!registrationTimestamp(entry.checkedAt,now)))throw Error('Invalid screenshot entry');
    const key=registrationKey(entry.sourceCode,entry.salesRegion,entry.scope);if(keys.has(key))throw Error('Duplicate screenshot market');keys.add(key);
    const frames=new Set();
    for(const frame of entry.frames){
      if(!frame||!registrationText(frame.id,80)||frames.has(frame.id)||frame.screenshotKind!=='real'||!REGISTRATION_ASSET.test(frame.asset)||
        !registrationSourceUrl(frame.sourceUrl,entry.sourceCode)||!registrationTimestamp(frame.verifiedAt,now)||
        !registrationText(frame.caption,500)||!registrationText(frame.alt,500)||!frame.viewport||
        !['width','height'].every(key=>Number.isInteger(frame.viewport[key])&&frame.viewport[key]>=100&&frame.viewport[key]<=16000)||
        !Array.isArray(frame.annotations)||!frame.annotations.length||frame.annotations.length>12)throw Error('Invalid real screenshot');
      frames.add(frame.id);
      for(const note of frame.annotations){
        if(!note||!registrationText(note.label,120)||!registrationText(note.description,500)||
          !['x','y','width','height'].every(key=>typeof note[key]==='number'&&Number.isFinite(note[key])&&note[key]>=0&&note[key]<=100)||
          note.width<=0||note.height<=0||note.x+note.width>100||note.y+note.height>100)throw Error('Invalid screenshot annotation');
      }
    }
  }
  return data;
}
function registrationEntry(sourceCode,salesRegion,scope='market'){
  if(!registrationData)return null;
  const key=registrationKey(sourceCode,salesRegion,scope);
  return registrationData.entries.find(entry=>registrationKey(entry.sourceCode,entry.salesRegion,entry.scope)===key)||null;
}
function registrationScopeLabel(salesRegion,scope){return scope==='public_account'?'账户注册':registrationText(salesRegion)?salesRegion:'账户注册'}
function registrationImageMarkup(frame){
  const escape=registrationEscape;
  return '<div class="registration-image-wrap"><img data-registration-image src="'+escape(new URL(frame.asset,REGISTRATION_BASE).href)+'" alt="'+escape(frame.alt)+'" loading="lazy" decoding="async">'+frame.annotations.map((note,index)=>'<span class="registration-annotation" aria-hidden="true" style="left:'+note.x+'%;top:'+note.y+'%;width:'+note.width+'%;height:'+note.height+'%"><span>'+(index+1)+'</span></span>').join('')+'</div><p class="registration-image-error" role="status" hidden>图片暂时无法显示，请参考下方注册步骤。</p>';
}
function registrationFrameMarkup(frame){
  return '<div class="registration-preview">'+registrationImageMarkup(frame)+'</div><details class="registration-zoom"><summary><span class="registration-zoom-open">查看大图（原始分辨率）</span><span class="registration-zoom-close">收起大图</span></summary><p>左右、上下滑动查看，中文编号标注保留。可用浏览器双指缩放；键盘 Tab 进入图片区域后，用方向键滚动，Escape 收起并返回此按钮。</p><div class="registration-zoom-viewport" tabindex="0" role="region" aria-label="原始分辨率注册截图，可用方向键横向及纵向滚动">'+registrationImageMarkup(frame)+'</div></details>';
}
function closeRegistrationZoom(event){
  if(event.key!=='Escape')return;
  const zoom=event.target.closest?.('.registration-zoom[open]');if(!zoom)return;
  event.preventDefault();event.stopImmediatePropagation();zoom.open=false;zoom.querySelector('summary')?.focus();
}
function registrationContent(sourceCode,salesRegion,scope='market'){
  const escape=registrationEscape,scopeLabel=registrationScopeLabel(salesRegion,scope),entry=registrationEntry(sourceCode,salesRegion,scope);
  if(!entry||entry.status!=='verified')return '';
  return '<p class="registration-scope">'+escape(scopeLabel)+(scope!=='public_account'&&entry.marketLabel!==scopeLabel?' · '+escape(entry.marketLabel):'')+'</p>'+
    '<p>'+(scope==='public_account'?'以下图解介绍商家账户注册。配送地区与购买条件请在结账时确认。':'请按所选商店及地区的页面操作。')+'页面可能更新，请以商家当前页面为准。</p>'+
    entry.frames.map(frame=>'<figure class="registration-figure"><figcaption>'+escape(frame.caption)+'</figcaption>'+registrationFrameMarkup(frame)+'<ol class="registration-annotation-list">'+frame.annotations.map(note=>'<li><strong>'+escape(note.label)+'</strong>：'+escape(note.description)+'</li>').join('')+'</ol><p class="registration-meta">更新于 '+escape(frame.verifiedAt.slice(0,10))+'</p><p class="registration-source">图片来源：'+escape(frame.sourceUrl)+'</p></figure>').join('');
}
function registrationGuideMarkup(sourceCode,salesRegion,scope='market'){
  const escape=registrationEscape,market=typeof salesRegion==='string'?salesRegion:'',entry=registrationEntry(sourceCode,scope==='public_account'?null:market,scope);
  return '<details'+(!entry||entry.status!=='verified'?' hidden':'')+' class="registration-guide" data-registration-source="'+escape(sourceCode)+'" data-registration-market="'+escape(market)+'" data-registration-scope="'+escape(scope)+'"><summary>'+(scope==='public_account'?'账户注册图解':'注册图解 · '+escape(registrationScopeLabel(market,scope)))+'</summary><div class="registration-content">'+registrationContent(sourceCode,scope==='public_account'?null:market,scope)+'</div></details>';
}
function registrationPublicAccountMarkup(sourceCode){
  // This is an explicitly separate section, never an exact-market fallback.
  const entry=registrationEntry(sourceCode,null,'public_account');
  return entry?.status==='verified'?registrationGuideMarkup(sourceCode,null,'public_account'):'';
}
function registrationHelpMarkup(sourceCode,salesRegion){
  return '<div class="registration-help" data-registration-help="'+registrationEscape(sourceCode)+'">'+registrationGuideMarkup(sourceCode,salesRegion)+'<div class="registration-public-account">'+registrationPublicAccountMarkup(sourceCode)+'</div></div>';
}
function refreshRegistrationGuides(){
  document.querySelectorAll('.registration-guide').forEach(node=>{
    const scope=node.dataset.registrationScope,market=scope==='public_account'?null:node.dataset.registrationMarket;
    const entry=registrationEntry(node.dataset.registrationSource,market,scope);node.hidden=!entry||entry.status!=='verified';
    const content=node.querySelector('.registration-content');if(content)content.innerHTML=registrationContent(node.dataset.registrationSource,market,scope);
  });
  document.querySelectorAll('[data-registration-help]').forEach(node=>{
    const box=node.querySelector('.registration-public-account'),entry=registrationEntry(node.dataset.registrationHelp,null,'public_account');
    if(box&&!box.querySelector('.registration-guide')&&entry?.status==='verified')box.innerHTML=registrationPublicAccountMarkup(node.dataset.registrationHelp);
    else if(box&&entry?.status!=='verified')box.innerHTML='';
  });
}
async function loadRegistrationGuides(){
  if(registrationRequest)return registrationRequest;
  registrationRequest=(async()=>{
    try{
      const url=new URL('registration-guides.json',REGISTRATION_BASE);url.searchParams.set('check',String(Date.now()));
      const response=await fetch(url.href,{cache:'no-store'});if(!response.ok)throw Error('Screenshot data unavailable');
      const raw=await response.text();if(raw.length>400000)throw Error('Screenshot data too large');
      const data=validateRegistrationData(JSON.parse(raw));
      const changed=JSON.stringify(data)!==JSON.stringify(registrationData)||registrationLoadState!=='ready';
      registrationData=data;registrationLoadState='ready';if(changed)refreshRegistrationGuides();
    }catch{
      // Fail closed: no stale screenshot survives a failed/invalid refresh.
      registrationData=null;registrationLoadState='error';refreshRegistrationGuides();
    }finally{registrationRequest=null;}
  })();return registrationRequest;
}
document.addEventListener('keydown',closeRegistrationZoom);
document.addEventListener('error',event=>{
  const img=event.target;if(!img?.matches?.('[data-registration-image]'))return;
  const wrap=img.closest('.registration-image-wrap'),error=wrap?.nextElementSibling;
  if(wrap)wrap.hidden=true;if(error)error.hidden=false;
},true);
document.addEventListener('toggle',event=>{
  const node=event.target;if(!node?.matches?.('.registration-guide')||!node.open)return;
  if(node.querySelector('.registration-image-wrap[hidden]')){
    const scope=node.dataset.registrationScope;node.querySelector('.registration-content').innerHTML=registrationContent(node.dataset.registrationSource,scope==='public_account'?null:node.dataset.registrationMarket,scope);
  }
  loadRegistrationGuides();
},true);
window.addEventListener('pageshow',()=>loadRegistrationGuides());
document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadRegistrationGuides()});
setInterval(()=>{if(!document.hidden)loadRegistrationGuides()},60000);
loadRegistrationGuides();
