'use strict';
// One final, same-tab gate for external navigation. A recorded destination is
// never an assurance about later redirects, seller identity or checkout safety.
let externalExitState=null;
function externalExitUrl(value){
  if(typeof value!=='string'||value!==value.trim()||/[\u0000-\u0020\u007f\\]/.test(value))return null;
  try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password&&!url.port&&url.hostname?url:null}catch{return null}
}
function externalExitEscape(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function externalExitDirectory(url,code){
  if(typeof directoryData==='undefined'||!directoryData)return null;
  return [...(directoryData.brands||[]),...(directoryData.teams||[])].find(row=>(!code||(row.source_codes||[row.code]).includes(code))&&[row.official_url,row.shop_url].some(value=>externalExitUrl(value)?.hostname===url.hostname))||null;
}
function externalExitIdentity(options,url){
  const row=externalExitDirectory(url,options.sourceCode),amazon=options.kind==='amazon'&&typeof AMAZON_SEARCH_MARKETS!=='undefined'&&AMAZON_SEARCH_MARKETS.some(market=>market.searches.some(search=>search.url===options.url));
  const official=amazon||options.kind==='merchant'&&!!row;
  let note=options.sourceNote||'本站记录的来源链接；尚无该目标的独立官方身份核验记录。';
  if(amazon)note='本站记录的 Amazon 官方站点搜索入口；未核验搜索结果中的卖家、商品或交易条件。';
  else if(row&&options.kind==='merchant')note=['verified_shop','official_link_found'].includes(row.status)&&row.shop_evidence_url?'本站目录记录了该商家的官方来源及商城入口依据；该记录不代表本次交易或后续跳转已经核验。':'本站目录将该域名登记为品牌或车队网站；尚无完整的独立官方身份核验记录。';
  let image=options.image||'';
  if(!image&&amazon&&typeof AMAZON_CHANNEL_LOGO_URL!=='undefined')image=AMAZON_CHANNEL_LOGO_URL;
  if(!image&&row)image=(row.logo_images||[]).find(value=>typeof value==='string'&&/^\/(?:[A-Za-z0-9_-]+\/)*web\/assets\/[A-Za-z0-9_./-]+\.(?:svg|png|webp|jpe?g)$/.test(value)&&!value.includes('..'))||'';
  try{const parsed=new URL(image,window.location.href);if(!image||!['https:','http:'].includes(parsed.protocol)||parsed.username||parsed.password||parsed.origin!==window.location.origin&&parsed.protocol!=='https:')image='';else image=parsed.href}catch{image=''}
  return {official,note,image,label:options.label||row?.name_zh||row?.name||url.hostname};
}
function externalExitIsValid(state){
  try{return externalExitState===state&&externalExitUrl(state.options.url)?.href===state.url.href&&state.options.validate()===true}catch{return false}
}
function closeExternalExit(cancel=true){
  const state=externalExitState;if(!state)return;
  externalExitState=null;state.dialog.close();document.body.style.overflow=state.overflow;
  if(cancel)state.options.onCancel?.();
  if(cancel){const target=state.trigger?.isConnected?state.trigger:state.options.restoreFocus?.();target?.focus({preventScroll:true})}
}
function confirmExternalExit(){
  const state=externalExitState;if(!state)return;
  if(!externalExitIsValid(state)){
    document.getElementById('externalExitError').hidden=false;
    document.getElementById('externalExitConfirm').disabled=true;
    document.getElementById('externalExitCancel').focus();return;
  }
  // Revalidation happens after the potentially long reading interval, immediately
  // before preserving history and navigating. No async gap or second prompt.
  state.options.onConfirm?.();
  if(!externalExitIsValid(state))return;
  closeExternalExit(false);window.location.assign(state.url.href);
}
function showExternalExit(options){
  if(externalExitState)return false;
  const url=externalExitUrl(options?.url);if(!url||typeof options.validate!=='function')return false;
  try{if(options.validate()!==true)return false}catch{return false}
  const identity=externalExitIdentity(options,url),esc=externalExitEscape;
  let dialog=document.getElementById('externalExitDialog');
  if(!dialog){dialog=document.createElement('dialog');dialog.id='externalExitDialog';dialog.className='external-exit-dialog';dialog.setAttribute('aria-labelledby','externalExitTitle');dialog.setAttribute('aria-describedby','externalExitIntro');document.body.append(dialog);dialog.addEventListener('cancel',event=>{event.preventDefault();closeExternalExit()})}
  const icons=['↗','⚠','⇄','✓'];
  const points=[['信息服务','本站仅提供商品与优惠信息及链接，不参与交易。'],['核对来源与域名',identity.note+' 请始终核对浏览器地址栏中的域名，警惕仿冒网站。'],['离站后保持警惕','离站后的重定向、第三方链接、访问环境及用户操作不由本站控制；发现异常请停止访问或操作。'],['购买前再次核实','价格、库存、尺码、付款、配送与退换以实际商家为准，请在购买前自行核实。法律规定本站应承担的责任除外。']];
  dialog.innerHTML='<div class="external-exit-scroll"><header class="external-exit-hero"><div class="external-exit-art" aria-hidden="true"><span></span><span></span><i></i></div><div class="external-exit-brand">BikeHunt <span>离站确认</span></div><div class="external-exit-identity"><div class="external-exit-picture"><img id="externalExitImage" alt="'+esc(identity.label)+'" hidden><span id="externalExitImageFallback">'+esc(identity.label)+'</span></div><div class="external-exit-heading"><p>'+esc(options.kind==='reference'?'资料与费用参考':options.kind==='amazon'?'Amazon 搜索入口':'当前商品与商家')+'</p><h2 id="externalExitTitle">即将前往'+(identity.official?'商家官网':'目标网站')+'</h2><p class="external-exit-name">'+esc(identity.label)+'</p></div></div></header><div class="external-exit-content"><p id="externalExitIntro">请花一点时间，核对这次离站信息。</p><div class="external-exit-destination"><span>本次目标域名</span><strong id="externalExitDomain" dir="ltr">'+esc(url.hostname)+'</strong><small>请与跳转后浏览器地址栏逐字核对</small></div><ol id="externalExitPoints">'+points.map(([title,text],i)=>'<li'+(i===1?' class="external-exit-important"':'')+'><span class="external-exit-number" aria-label="第'+(i+1)+'点">'+(i+1)+'</span><div><h3><span aria-hidden="true">'+icons[i]+'</span> '+title+(i===1?' · 重点提醒':'')+'</h3><p>'+(i===1?esc(identity.note)+' <strong>请始终核对浏览器地址栏中的域名，警惕仿冒网站。</strong>':esc(text))+'</p></div></li>').join('')+'</ol>'+(options.note?'<p class="external-exit-context">'+esc(options.note)+'</p>':'')+'<details class="external-exit-disclaimer"><summary>完整购买提示与免责声明</summary><p>'+esc(typeof PURCHASE_DISCLAIMER==='string'?PURCHASE_DISCLAIMER:'本站仅提供信息，不参与交易。法律规定本站应承担的责任除外。')+'</p></details><p id="externalExitError" class="external-exit-error" role="alert" hidden>链接或商品状态已变化，此入口已停用。请取消后重新核对。</p></div></div><footer class="external-exit-actions"><button type="button" id="externalExitCancel">取消</button><button type="button" id="externalExitConfirm">确认并前往'+(identity.official?'官网':'目标网站')+'</button></footer>';
  const img=document.getElementById('externalExitImage'),fallback=document.getElementById('externalExitImageFallback');
  const syncImage=()=>{const ready=img.complete&&img.naturalWidth>0;img.hidden=!ready;fallback.hidden=ready};img.onload=syncImage;img.onerror=()=>{img.hidden=true;fallback.hidden=false};if(identity.image){img.src=identity.image;syncImage()}
  const state={dialog,options:{...options},url,trigger:options.trigger||document.activeElement,overflow:document.body.style.overflow};externalExitState=state;
  document.getElementById('externalExitCancel').onclick=()=>closeExternalExit();document.getElementById('externalExitConfirm').onclick=confirmExternalExit;
  document.body.style.overflow='hidden';dialog.showModal();document.getElementById('externalExitCancel').focus({preventScroll:true});return true;
}
// Capture protects the underlying product sheet/zoom from the same Escape/Tab.
document.addEventListener('keydown',event=>{
  const state=externalExitState;if(!state)return;
  if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();closeExternalExit();return}
  if(event.key==='Tab'){
    event.stopImmediatePropagation();const nodes=[...state.dialog.querySelectorAll('button,summary,a,[tabindex="0"]')].filter(node=>!node.disabled&&node.getClientRects().length),first=nodes[0],last=nodes.at(-1);
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}
  }
},true);
// Covers dynamically rendered policy, fit, cost and directory references. Earlier
// exact-allowlist guards own purchase/search/help links and already preventDefault.
function guardOtherExternalExit(event){
  if(event.defaultPrevented||(event.type==='auxclick'&&event.button!==1))return;
  const link=event.target.closest?.('a[href]');if(!link)return;
  const href=link.getAttribute('href');let target;try{target=new URL(href,window.location.href)}catch{event.preventDefault();return}
  if(target.origin===window.location.origin&&['https:','http:'].includes(target.protocol))return;
  event.preventDefault();const url=externalExitUrl(href);if(!url)return;
  const owner=link.closest('#sheetBody')||link.closest('#directoryPage')||link.parentElement;
  showExternalExit({url:href,kind:'reference',label:link.textContent.trim()||url.hostname,trigger:link,
    validate:()=>link.isConnected&&owner?.contains(link)&&link.getAttribute('href')===href&&link.getClientRects().length>0&&(!link.closest('#sheet')||link.closest('#sheet').classList.contains('open')),
    onConfirm:()=>{if(typeof saveBrowseState==='function')saveBrowseState()}});
}
for(const type of ['click','auxclick'])document.addEventListener(type,guardOtherExternalExit);
