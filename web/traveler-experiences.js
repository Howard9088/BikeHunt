'use strict';
let travelerData=null,travelerPromise=null,travelerBrand='';
async function loadTravelerExperiences(){
  if(travelerData)return travelerData;
  if(!travelerPromise)travelerPromise=(async()=>{
    const path=window.BIKEHUNT_PAGES?'./web/traveler-experiences.json':'/web/traveler-experiences.json';
    const response=await fetch(new URL(path,location.href));if(!response.ok)throw Error('经验来源暂时无法读取');
    const data=await response.json();if(!Array.isArray(data.cards))throw Error('经验内容格式有误');return travelerData=data;
  })().finally(()=>{travelerPromise=null});
  return travelerPromise;
}
function travelerLink(url,label){const value=safeUrl(url);return value.startsWith('https://')?'<a href="'+e(value)+'" target="_blank" rel="noopener noreferrer">'+e(label)+' ↗</a>':''}
async function renderExperiences(){
  document.getElementById('browseLabel').textContent='淘友经验';
  directoryPage.innerHTML='<div class="directory-intro"><h2>淘友经验</h2><p>正在读取经验来源…</p></div>';
  try{
    const data=await loadTravelerExperiences();if(activeTab!=='experiences')return;
    const brands=[...new Set(data.cards.map(row=>row.brand))].sort();
    directoryPage.innerHTML='<div class="directory-intro"><h2>淘友经验</h2><p>'+e(data.notice)+'</p><label for="travelerBrand">按品牌查找</label> <select id="travelerBrand"><option value="">全部品牌</option>'+brands.map(brand=>'<option value="'+e(brand)+'"'+(brand===travelerBrand?' selected':'')+'>'+e(brand)+'</option>').join('')+'</select></div><div id="travelerCards" class="traveler-cards"></div>';
    const paint=()=>{
      const rows=data.cards.filter(row=>!travelerBrand||row.brand===travelerBrand);
      document.getElementById('count').textContent=rows.length+' 篇来源摘要';
      document.getElementById('travelerCards').innerHTML=rows.map(row=>'<article class="traveler-card" data-traveler-id="'+e(row.id)+'"><div class="traveler-meta">'+e(row.brand)+' · '+e(row.kind)+'</div><h3>'+e(row.title)+'</h3><p class="traveler-meta">经历／原文日期：'+e(row.date)+'<br>适用市场：'+e(row.market)+'</p><p>'+e(row.summary)+'</p><details><summary>来源与时效提醒</summary><p>'+e(row.warning)+'</p><p>'+travelerLink(row.url,'查看原文')+(row.backup?' · '+travelerLink(row.backup,'评价列表备用入口'):'')+'</p><p class="traveler-meta">公开来源整理，非本站亲测或投稿 · 整理核对 '+e(data.verified_at)+'</p></details><details><summary>官网规则对照（另行核对）</summary><p class="traveler-meta">以下为整理时取得的官网说明，与个人经历分开。付款、物流和退换规定可能变化，下单前请核对相应市场的官网。</p>'+row.official.map(source=>'<p>'+e(source.text)+'<br>'+travelerLink(source.url,'官网来源')+'<span class="traveler-meta"> · '+(source.date?'原文 '+e(source.date)+' · ':'')+'核对 '+e(data.verified_at)+'</span></p>').join('')+'</details></article>').join('');
    };
    document.getElementById('travelerBrand').onchange=event=>{travelerBrand=event.target.value;paint()};paint();
  }catch{if(activeTab==='experiences')directoryPage.innerHTML='<div class="directory-intro"><h2>淘友经验暂时无法加载</h2><button type="button" id="retryExperiences">重试</button></div>';const retry=document.getElementById('retryExperiences');if(retry)retry.onclick=renderExperiences;}
}
