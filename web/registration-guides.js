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
function registrationProvenance(frame,code){
  const hasOrigin=Object.prototype.hasOwnProperty.call(frame,'screenshotOrigin'),hasLabel=Object.prototype.hasOwnProperty.call(frame,'sourceLabel');
  if(!hasOrigin&&!hasLabel)return true;
  const origins={rapha:'https://auth.rapha.cc',maap:'https://shopify.com',fizik:'https://shopify.com'};
  return hasOrigin&&hasLabel&&Object.prototype.hasOwnProperty.call(origins,code)&&frame.screenshotOrigin===origins[code]&&frame.sourceLabel==='官网进入链接';
}
function registrationProvenanceMarkup(frame){
  const escape=registrationEscape;
  return frame.screenshotOrigin?'<p class="registration-source">实际截图来源：'+escape(frame.screenshotOrigin)+'</p><p class="registration-source">官网进入链接：'+escape(frame.sourceUrl)+'</p>':'<p class="registration-source">图片来源：'+escape(frame.sourceUrl)+'</p>';
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
        !registrationSourceUrl(frame.sourceUrl,entry.sourceCode)||!registrationProvenance(frame,entry.sourceCode)||!registrationTimestamp(frame.verifiedAt,now)||
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

/* Untested markets keep a clearly labeled, read-only illustration, never a fake screenshot. */
function registrationWords(code,market){
  const region=String(market??'');
  if(code==='amazon_jp'||(code==='rapha'&&/日本|Japan/i.test(region)))return ['Account / アカウント','Sign in / サインイン','Create account / 新規登録'];
  if(code==='amazon_de')return ['Konto / Account','Anmelden / Sign in','Konto erstellen / 注册'];
  if(code==='rapha_kr'||/韩国|Korea|한국/.test(region))return ['Account / 계정','로그인 / Sign in','회원가입 / Register'];
  return ['Account / 账户','Sign in / 登录','Create account / Register'];
}
function registrationSchematicMarkup(code,market){
  const escape=registrationEscape,words=registrationWords(code,market);
  const extra=code==='rapha'?'Rapha 的普通账户、RCC 付费会员和邮件订阅不是同一种注册。':
    code==='decathlon'?'此处是 Decathlon CMA CGM 车队商城，不能预设迪卡侬零售账户通用。':
    String(code??'').startsWith('amazon_')?'Amazon 不同国家站要分别核对，不把一站的注册步骤当成其他站已核实。':
    '若商家提供游客结账，不必为了购买强制注册。';
  const pictures=[
    '<div class="registration-demo-window"><div class="registration-demo-bar"><span>官网导航 · 示意</span><span>☰</span></div><div class="registration-demo-ghost"></div><div class="registration-demo-target">'+escape(words[0])+'<span>①</span></div><div class="registration-demo-muted">商品 · 购物车 · 账户</div></div>',
    '<div class="registration-demo-window"><div class="registration-demo-bar"><span>账户页面 · 示意</span><span>×</span></div><div class="registration-demo-subtle">'+escape(words[1])+'</div><div class="registration-demo-muted">已有账户可直接登录</div><div class="registration-demo-target">'+escape(words[2])+'<span>②</span></div></div>',
    '<div class="registration-demo-window"><div class="registration-demo-bar"><span>新用户页面 · 示意</span><span>×</span></div><div class="registration-demo-field">Email / 邮箱</div><div class="registration-demo-field">Name / 姓名（如要求）</div><div class="registration-demo-field">Password / 验证（如要求）</div><div class="registration-demo-target">继续 / Continue<span>③</span></div></div>'
  ];
  const titles=['找到账户入口','选择新用户注册','核对资料与验证'];
  const help=['在原站页头或菜单中寻找账户／登录入口，位置以该站当前页面为准。',
    '有账户直接登录；需要新账户时，再寻找注册入口。','只在官网填写资料，邮箱验证、密码及协议按实际要求办理。'];
  return '<section class="registration-schematic" aria-label="注册操作步骤示意，非官网截图">'+
    '<div class="registration-schematic-heading"><strong>3 步中文注册图解</strong><span>示意 · 非官网截图</span></div>'+
    '<p class="registration-schematic-note">本商家／市场暂时没有已核实的真实注册截图。以下<strong>画面是辅助理解的示意图</strong>，外文只是可参考的常见按钮名称，不能当作原站实拍。</p>'+
    '<ol class="registration-schematic-steps">'+pictures.map((picture,i)=>
      '<li class="registration-schematic-step"><div class="registration-schematic-number">'+(i+1)+'</div><strong>'+titles[i]+'</strong>'+picture+'<p>'+help[i]+'</p></li>').join('')+'</ol>'+
    '<p class="registration-schematic-foot">'+extra+' 注册不证明中国银行卡可用或支持直邮中国，结账时仍要核实。</p></section>';
}

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
  if(!entry||entry.status!=='verified')return scope==='market'?registrationSchematicMarkup(sourceCode,salesRegion):'';
  return '<p class="registration-scope">'+escape(scopeLabel)+(scope!=='public_account'&&entry.marketLabel!==scopeLabel?' · '+escape(entry.marketLabel):'')+'</p>'+
    '<p>'+(scope==='public_account'?'以下图解介绍商家账户注册。配送地区与购买条件请在结账时确认。':'请按所选商店及地区的页面操作。')+'页面可能更新，请以商家当前页面为准。</p>'+
    entry.frames.map(frame=>'<figure class="registration-figure"><figcaption>'+escape(frame.caption)+'</figcaption>'+registrationFrameMarkup(frame)+'<ol class="registration-annotation-list">'+frame.annotations.map(note=>'<li><strong>'+escape(note.label)+'</strong>：'+escape(note.description)+'</li>').join('')+'</ol><p class="registration-meta">更新于 '+escape(frame.verifiedAt.slice(0,10))+'</p>'+registrationProvenanceMarkup(frame)+'</figure>').join('');
}
function registrationGuideMarkup(sourceCode,salesRegion,scope='market'){
  const escape=registrationEscape,market=typeof salesRegion==='string'?salesRegion:'',entry=registrationEntry(sourceCode,scope==='public_account'?null:market,scope);
  return '<details'+(scope==='public_account'&&(!entry||entry.status!=='verified')?' hidden':'')+' class="registration-guide" data-registration-source="'+escape(sourceCode)+'" data-registration-market="'+escape(market)+'" data-registration-scope="'+escape(scope)+'"><summary>'+(scope==='public_account'?'账户注册图解':'注册图解 · '+escape(registrationScopeLabel(market,scope)))+'</summary><div class="registration-content">'+registrationContent(sourceCode,scope==='public_account'?null:market,scope)+'</div></details>';
}
function registrationPublicAccountMarkup(sourceCode){
  // This is an explicitly separate section, never an exact-market fallback.
  const entry=registrationEntry(sourceCode,null,'public_account');
  return entry?.status==='verified'?registrationGuideMarkup(sourceCode,null,'public_account'):'';
}
function registrationLanguageGuide(sourceCode,salesRegion){
  const market=String(salesRegion||'');
  if(sourceCode==='rapha'&&/日本|\bJP\b|JPY/i.test(market))return {
    title:'Rapha 日本站：先找到「アカウント」',scope:'日本站账户入口与账户帮助',
    steps:[
      {title:'进入账户',pairs:[['アカウント','账户入口'],['サインイン','登录']],text:'在官网找到「アカウント」。已有账户可在账户页登录。不要把首页的邮件订阅当成购物账户注册。'},
      {title:'看懂账户提示',pairs:[['メールアドレス','邮箱'],['パスワードをお忘れですか？','忘记密码？'],['続行','继续']],text:'忘记密码时，按账户页提示使用自己的邮箱。继续前核对原文；新用户的创建账户方式以当前账户页为准。'},
      {title:'区分邮件订阅',pairs:[['ニュースレター','邮件资讯订阅'],['登録する','登记／订阅（取决于所在区域）']],text:'首页「ニュースレター」下的「登録する」是邮件订阅入口，不代表已创建购物账户。'}
    ],
    sources:[['日本站首页','https://www.rapha.cc/jp/ja'],['日文账户帮助','https://support.rapha.cc/ja/articles/469']]
  };
  if(sourceCode==='maap')return {
    title:'MAAP：用自己的邮箱进入账户',scope:'MAAP 官方账户帮助；各地区购买条件另行确认',
    steps:[
      {title:'准备能收信的邮箱',pairs:[['Email','邮箱'],['Account','账户']],text:'使用自己能收到邮件的邮箱。已有订单建议使用下单时的同一邮箱。'},
      {title:'按页面选择登录方式',pairs:[['Passwordless login','免密码登录'],['Secure link','安全登录链接']],text:'官方帮助介绍了发送安全链接到已登记邮箱的登录方式。如页面提供该方式，打开自己的邮箱并按邮件提示继续，不必在本站填写密码。'},
      {title:'核对账户与订单',pairs:[['Orders','订单'],['Email address','邮箱地址']],text:'官方帮助说明，同一邮箱下的订单可关联到账户。具体入口与登录选项请以当前 MAAP 页面为准。'}
    ],
    sources:[['MAAP 官方账户帮助','https://support.maap.cc/hc/en-us/articles/7580094532749-I-want-to-reset-my-password']]
  };
  if(sourceCode==='uae')return {
    title:'PISSEI：注册表单中文对照',scope:'英文公开注册页；请另外核对所选配送国家',
    steps:[
      {title:'先选账户类型',pairs:[['user type','用户类型'],['country','国家']],text:'先确认用户类型。企业信息可能随所选类型出现；普通购物者按自己实际类型及页面必填标记填写。国家选项不代表已确认能够配送。'},
      {title:'填写自己的资料',pairs:[['name','名字'],['surname','姓氏'],['email address','邮箱'],['password','密码'],['confirm password','确认密码'],['date of birth','出生日期']],text:'字段旁的星号表示必填。只在 PISSEI 官网填写个人资料，并按原站密码要求操作。'},
      {title:'分开看隐私与推广选项',pairs:[['privacy policy','隐私政策'],['promotional emails','推广邮件']],text:'阅读隐私政策，分别判断资料处理与推广邮件选项，再按官网当前按钮继续。不要把订阅推广邮件理解为付款。'}
    ],
    sources:[['PISSEI 英文注册页','https://www.pissei.com/en/registration']]
  };
  return null;
}
function registrationLanguageMarkup(sourceCode,salesRegion){
  const guide=registrationLanguageGuide(sourceCode,salesRegion),escape=registrationEscape;
  if(!guide)return '';
  return '<section class="registration-language-guide" aria-label="官网账户中文指引"><h3>'+escape(guide.title)+'</h3><p>'+escape(guide.scope)+'</p><p>下面是根据官网文字整理的操作示意，不是官网截图；卡片位置不代表官网按钮位置。</p>'+
    guide.steps.map((step,index)=>'<figure class="merchant-diagram"><figcaption>'+String(index+1)+'. '+escape(step.title)+' · 操作示意</figcaption><div class="merchant-diagram-cells">'+step.pairs.map(pair=>'<div><b>'+escape(pair[0])+'</b><span>'+escape(pair[1])+'</span></div>').join('')+'</div><p>'+escape(step.text)+'</p></figure>').join('')+
    '<p>参考：'+guide.sources.map(pair=>'<a href="'+escape(pair[1])+'" target="_blank" rel="noopener noreferrer">'+escape(pair[0])+'</a>').join(' · ')+'</p></section>';
}

function registrationHelpMarkup(sourceCode,salesRegion){
  return '<div class="registration-help" data-registration-help="'+registrationEscape(sourceCode)+'">'+registrationLanguageMarkup(sourceCode,salesRegion)+registrationGuideMarkup(sourceCode,salesRegion)+'<div class="registration-public-account">'+registrationPublicAccountMarkup(sourceCode)+'</div></div>';
}
function refreshRegistrationGuides(){
  document.querySelectorAll('.registration-guide').forEach(node=>{
    const scope=node.dataset.registrationScope,market=scope==='public_account'?null:node.dataset.registrationMarket;
    const entry=registrationEntry(node.dataset.registrationSource,market,scope);node.hidden=scope==='public_account'&&(!entry||entry.status!=='verified');
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
