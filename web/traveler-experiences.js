'use strict';
let travelerData=null,travelerPromise=null,travelerBrand='';
async function loadTravelerExperiences(){
  if(travelerData)return travelerData;
  if(!travelerPromise)travelerPromise=(async()=>{
    const path=window.BIKEHUNT_PAGES?'./web/traveler-forum-data.json':'/web/traveler-forum-data.json';
    const revision=window.BIKEHUNT_PUBLICATION?.commit;
    const response=await fetch(new URL(path+(revision?'?v='+encodeURIComponent(revision):''),location.href));if(!response.ok)throw Error('经验内容暂时无法读取');
    const data=await response.json();if(!Array.isArray(data.cards))throw Error('经验内容格式有误');return travelerData=data;
  })().finally(()=>{travelerPromise=null});
  return travelerPromise;
}
function travelerLink(url,label){const value=safeUrl(url);return value.startsWith('https://')?'<a href="'+e(value)+'" target="_blank" rel="noopener noreferrer">'+e(label)+' ↗</a>':''}
function travelerSources(row){return Array.isArray(row.sources)?row.sources:[]}
function publishedTravelerThreads(data){
  return data.cards.filter(row=>travelerSources(row).length&&travelerSources(row).every(source=>{try{const u=new URL(source.url);return u.protocol==='https:'&&u.hostname==='post.smzdm.com'}catch{return false}}));
}
function travelerThreadMarkup(row){
  const brand=(row.brands||[]).join(' / '),year=String(row.date).slice(0,4);
  return '<article class="traveler-topic"><button class="traveler-thread-card" type="button" data-traveler-id="'+e(row.id)+'" aria-label="在本站阅读：'+e(row.title)+'"><span class="traveler-thread-brand">'+e(brand)+'</span><span class="traveler-thread-tag">'+e((row.tags||[]).slice(0,2).join(' · '))+'</span><strong>'+e(row.title)+'</strong><span class="traveler-thread-excerpt">'+e(row.excerpt||'')+'</span><span class="traveler-thread-footer"><span>什么值得买 · '+e(year)+' 年旧帖</span><span>站内阅读 →</span></span></button></article>';
}
function openTravelerThread(id){
  const row=publishedTravelerThreads(travelerData||{cards:[]}).find(item=>item.id===id);if(!row)return;
  const sources=travelerSources(row);
  const sections=(row.sections||[]).map(section=>'<section class="traveler-reading-section">'+(section.title?'<h4>'+e(section.title)+'</h4>':'')+(section.paragraphs||[]).map(text=>'<p>'+e(text)+'</p>').join('')+'</section>').join('');
  openPanel(row.title,'<article class="traveler-thread-detail" data-traveler-detail="'+e(row.id)+'"><div class="traveler-reading-meta">'+e((row.brands||[]).join(' / '))+' · '+e(row.date)+'</div><p class="traveler-reading-market">适用市场：'+e(row.market)+'</p><p class="traveler-reading-note">中文摘要，依据什么值得买公开文章整理；非本站亲测、非本站用户投稿。</p>'+sections+'<aside class="traveler-history-note"><h4>放回当年的背景看</h4><p>'+e(row.warning)+'</p></aside><details class="traveler-reading-sources"><summary>原文出处与日期</summary>'+sources.map(source=>'<p><strong>'+e(source.title)+'</strong><br>'+(source.author?'原文作者：'+e(source.author)+' · ':'')+'原文日期：'+e(source.date)+'<br>'+travelerLink(source.url,'可选：查看什么值得买原文')+'</p>').join('')+'<p>整理日期：'+e(travelerData.verified_at)+'。历史价格、付款、配送、税费与退换办法不能作为当前承诺。</p></details><button type="button" class="traveler-return" id="travelerReturn">← 返回经验列表</button></article>');
  document.getElementById('sheetBrand').textContent='淘友经验 · 站内阅读';
  document.getElementById('travelerReturn').onclick=closeSheet;
}
async function renderExperiences(){
  document.getElementById('browseLabel').textContent='淘友经验';
  directoryPage.innerHTML='<div class="directory-intro"><h2>淘友经验</h2><p>正在读取中文经验…</p></div>';
  try{
    const data=await loadTravelerExperiences();if(activeTab!=='experiences')return;
    const rows=publishedTravelerThreads(data),brands=[...new Set(rows.flatMap(row=>row.brands||[]))].sort();
    if(!brands.includes(travelerBrand))travelerBrand='';
    directoryPage.innerHTML='<div class="traveler-forum-head"><div><h2>淘友经验</h2><p>骑行海淘旧帖，中文整理。点开卡片，在本站读完。</p></div><label for="travelerBrand">按品牌查找 <select id="travelerBrand"><option value="">全部品牌</option>'+brands.map(brand=>'<option value="'+e(brand)+'"'+(brand===travelerBrand?' selected':'')+'>'+e(brand)+'</option>').join('')+'</select></label></div><p class="traveler-forum-note">个人经历只代表当时那笔订单，历史价格和购买办法请与现行规则分开看。</p><div id="travelerCards"></div>';
    const paint=()=>{
      const filtered=rows.filter(row=>!travelerBrand||(row.brands||[]).includes(travelerBrand));
      const main=filtered.filter(row=>row.primary!==false),extra=filtered.filter(row=>row.primary===false);
      document.getElementById('count').textContent=filtered.length+' 个经验主题';
      document.getElementById('travelerCards').innerHTML=(main.length?'<section aria-label="骑行海淘经验"><div class="traveler-forum-grid">'+main.map(travelerThreadMarkup).join('')+'</div></section>':'')+(extra.length?'<section class="traveler-extra" aria-label="配件与延伸阅读"><h3>配件与延伸阅读</h3><div class="traveler-forum-grid">'+extra.map(travelerThreadMarkup).join('')+'</div></section>':'');
      directoryPage.querySelectorAll('[data-traveler-id]').forEach(button=>button.onclick=()=>openTravelerThread(button.dataset.travelerId));
    };
    document.getElementById('travelerBrand').onchange=event=>{travelerBrand=event.target.value;paint()};paint();
  }catch{if(activeTab==='experiences')directoryPage.innerHTML='<div class="directory-intro"><h2>淘友经验暂时无法加载</h2><button type="button" id="retryExperiences">重试</button></div>';const retry=document.getElementById('retryExperiences');if(retry)retry.onclick=renderExperiences;}
}
