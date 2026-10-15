'use strict';
const PROFILE_KEY='bikehunt.profile.v1';
const emptyProfile=()=>({gender:'all',height_cm:null,weight_kg:null,chest_cm:null});
let shopperProfile=emptyProfile();
try{const saved=JSON.parse(localStorage.getItem(PROFILE_KEY)||'null');if(saved&&['all','male','female'].includes(saved.gender))shopperProfile={...shopperProfile,...saved}}catch{}
function profileMatches(product){return activeCategoryGroup!=='clothing'||product.category_group!=='clothing'||shopperProfile.gender==='all'||product.gender===shopperProfile.gender||product.gender==='unisex'}
function syncGenderScope(){
  const visible=activeTab==='products'&&activeCategoryGroup==='clothing';
  const group=document.getElementById('genderFilter');if(group)group.hidden=!visible;
  // A hidden clothing preference must never remove bikes, shoes or accessories.
  if(!visible&&shopperProfile.gender!=='all'){
    shopperProfile.gender='all';
    try{localStorage.setItem(PROFILE_KEY,JSON.stringify(shopperProfile))}catch{}
  }
  updateProfileBar();
}
function updateProfileBar(){
  document.querySelectorAll('[data-gender]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.gender===shopperProfile.gender)));
  document.getElementById('bodyProfile').textContent=[shopperProfile.height_cm?shopperProfile.height_cm+' cm':'',shopperProfile.weight_kg?shopperProfile.weight_kg+' kg':''].filter(Boolean).join(' / ')||'身高 / 体重';
}
function saveProfile(){localStorage.setItem(PROFILE_KEY,JSON.stringify(shopperProfile));updateProfileBar();render();}
function showBodyProfile(){
  openPanel('设置身高与体重','<form id="profileForm" class="profile-form"><p>记住你的基本信息，浏览时按偏好筛选。</p><label for="heightCm">身高 <span>厘米</span></label><input id="heightCm" type="number" inputmode="decimal" min="100" max="230" step="1" value="'+e(shopperProfile.height_cm??'')+'" placeholder="例如 175"><label for="weightKg">体重 <span>公斤</span></label><input id="weightKg" type="number" inputmode="decimal" min="25" max="250" step="0.5" value="'+e(shopperProfile.weight_kg??'')+'" placeholder="例如 68"><p class="spec-note">尺码按本款官网尺码表判断。只有身高、体重不足以确定所有品牌的 S/M/L。</p><button type="submit" class="compare-button">保存，开始浏览 →</button><button type="button" class="quiet-button" id="clearProfile">清除个人筛选</button></form>');
  document.getElementById('profileForm').onsubmit=event=>{event.preventDefault();const form=event.target;if(!form.reportValidity())return;const height=form.querySelector('#heightCm').value,weight=form.querySelector('#weightKg').value;const h=height?Number(height):null,w=weight?Number(weight):null;if(h!==shopperProfile.height_cm||w!==shopperProfile.weight_kg)shopperProfile.chest_cm=null;shopperProfile.height_cm=h;shopperProfile.weight_kg=w;saveProfile();closeSheet()};
  document.getElementById('clearProfile').onclick=()=>{shopperProfile=emptyProfile();localStorage.removeItem(PROFILE_KEY);updateProfileBar();render();closeSheet()};
}
async function refreshFitReference(detail,sequence){
  const target=document.getElementById('fitReference');if(!target||!['jerseys','bibs','jackets','suits'].includes(detail.category))return;
  try{
    const response=await fetch('/api/fit/'+encodeURIComponent(detail.product_id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(shopperProfile)});
    if(!response.ok)throw new Error('尺码参考暂时无法读取');const fit=await response.json();
    if(sequence!==detailSequence||!target.isConnected)return;
    const dimensions=[shopperProfile.height_cm?shopperProfile.height_cm+' 厘米':'',shopperProfile.weight_kg?shopperProfile.weight_kg+' 公斤':''].filter(Boolean).join(' / ');
    target.innerHTML='<details class="fit-panel" '+(dimensions?'open':'')+'><summary>我的尺码参考'+(dimensions?' · '+e(dimensions):'')+'</summary><p>'+e(fit.note_zh)+'</p>'+(fit.required_measurements.includes('chest_cm')?'<form id="chestForm" class="chest-form"><label for="chestCm">胸围（厘米）</label><input id="chestCm" type="number" inputmode="decimal" min="50" max="180" step="0.5" required placeholder="绕胸部最丰满处一圈"><button type="submit">对照现货尺码</button></form>':'')+(fit.candidate_sizes.length?'<div class="fit-candidates">参考现货 '+fit.candidate_sizes.map(size=>'<strong>'+e(size)+'</strong>').join(' ')+'</div>':'')+(fit.chart_rows.length?'<details class="fit-chart"><summary>查看已保存的中文尺码表</summary><ul>'+fit.chart_rows.map(row=>'<li><b>'+e(row.size)+'</b> '+e(row.description_zh)+'</li>').join('')+'</ul><a href="'+e(safeUrl(fit.source_url))+'" target="_blank" rel="noopener noreferrer">官网尺码依据 ↗</a></details>':'')+'</details>';
    const form=document.getElementById('chestForm');if(form)form.onsubmit=event=>{event.preventDefault();if(!form.reportValidity())return;shopperProfile.chest_cm=Number(document.getElementById('chestCm').value);localStorage.setItem(PROFILE_KEY,JSON.stringify(shopperProfile));refreshFitReference(detail,sequence)};
  }catch(error){if(sequence===detailSequence&&target.isConnected)target.textContent=error.message}
}
document.querySelectorAll('[data-gender]').forEach(button=>button.onclick=()=>{if(activeTab!=='products'||activeCategoryGroup!=='clothing')return;shopperProfile.gender=button.dataset.gender;saveProfile()});
document.getElementById('bodyProfile').onclick=showBodyProfile;
updateProfileBar();

