'use strict';
// Read-only language help must never acquire purchase eligibility or collect data.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {installExternalExitStub}=require('./external_exit_test_helper');
const flows=fs.readFileSync('web/flows.js','utf8'),gallery=fs.readFileSync('web/gallery.js','utf8'),css=fs.readFileSync('web/flows.css','utf8');
new vm.Script(flows);new vm.Script(gallery);
const start=flows.indexOf('// Merchant-language guide:'),end=flows.indexOf('function invalidateReferenceLinks(',start);
assert.ok(start>0&&end>start);
const source=flows.slice(start,end);
let rendered='',title='',focus='',saved=0,prevented=0,confirmations=0,connected=true,loaded=[],navigated=[];
const buttons=['maap','visma','decathlon','other'].map(code=>({dataset:{merchantGuide:code},focus(){focus=code}}));
const elements={merchantGuideTitle:{focus(){focus='title'}},merchantGuideBack:{},merchantLanguageGuide:{contains:()=>connected},sheetBody:{querySelectorAll:()=>buttons}};
const listeners=[];
const context={Object,Map,URL,Date,document:{getElementById:id=>elements[id],addEventListener:(event,handler)=>listeners.push([event,handler])},e:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  openPanel:(name,html)=>{title=name;rendered=html;context.detailSequence++},detailSequence:10,sheet:{classList:{contains:()=>true}},loadDetail:async(id,variant)=>{loaded.push([id,variant]);context.detailSequence++},
  PURCHASE_DISCLAIMER:'full disclaimer sentinel',saveBrowseState:()=>saved++,window:{location:{assign:url=>navigated.push(url)}}};
const exit=installExternalExitStub(context);
vm.createContext(context);vm.runInContext(source,context);
assert.deepEqual(listeners.map(row=>row[0]),['click','auxclick']);
const detail={product_id:'jersey',variant_id:'M',offers:['maap','visma','decathlon','other'].flatMap(code=>['in_stock','unknown','out_of_stock'].map(stock=>({eligible:false,offer:{source_code:code,source_name:code+' official',stock,url:'https://merchant.example/product?variant=M'}})))};
const unchanged=JSON.stringify(detail),entrances=context.merchantGuidesMarkup(detail);
assert.equal((entrances.match(/data-merchant-guide=/g)||[]).length,4,'Every merchant, including sold-out offers, gets read-only help');
assert.ok(!/disabled|data-purchase-link|data-reference-link/.test(entrances));
assert.equal(context.merchantGuidesMarkup({offers:[]}), '');
assert.ok(context.merchantGuidesMarkup({offers:[{offer:{source_code:'<img>',source_name:'<script>alert(1)</script>'}}]}).includes('&lt;script&gt;'));
const steps=vm.runInContext('MERCHANT_LANGUAGE_STEPS',context);
assert.deepEqual(Array.from(steps,step=>step.id),['country','account','size','cart','address','returns']);
assert.ok(Object.isFrozen(steps));
for(const step of steps)assert.ok(Object.isFrozen(step)&&Object.isFrozen(step.paragraphs)&&Object.isFrozen(step.diagram));
for(const code of ['maap','visma','decathlon','other','__proto__']){
  const html=context.merchantLanguageMarkup({code,name:code});
  assert.equal((html.match(/data-merchant-step=/g)||[]).length,6);
  assert.equal((html.match(/class="merchant-guide-step"[^>]* open>/g)||[]).length,1);
  assert.equal((html.match(/示意 · 非商家截图/g)||[]).length,7);
  assert.ok(!/<(?:form|input|select|textarea|iframe|img)\b/.test(html),'No credentials/address forms, images or fake screenshots');
  assert.ok(!/data-purchase-link|data-reference-link/.test(html),'Read-only links cannot act as purchase links');
  for(const term of ['2026-10-15','未实测注册或结账成功','Country / Pays','Language / Langue','Currency / Devise','Create account / Créer un compte','Newsletter / S’abonner','Size guide / Guide des tailles','Add to cart / Ajouter au panier','Shipping address / Adresse de livraison','Billing address / Adresse de facturation','Pay now / Payer','Order number / Numéro de commande','Returns / Retours','iPhone Safari','Android Chrome','iPhone / iPad Chrome','不要把密码','该商家使用全部字段']){
    if(term==='该商家使用全部字段'&&!['other','__proto__'].includes(code))continue;
    assert.ok(html.includes(term),code+': '+term);
  }
  if(code==='maap')for(const text of ['Get Started','Access your account','Which size fits me?','不能推断新用户注册也一定无需密码','账户内地址管理与实际结账均未核实'])assert.ok(html.includes(text));
  if(code==='visma')for(const text of ['英文公开账户','未提交表单','发票日期起 30 天','不能直接换码','个性化商品','非欧盟','车队邮件与合作伙伴促销'])assert.ok(html.includes(text));
  if(code==='decathlon')for(const text of ['/en 车队商城','不是迪卡侬中国商店','身份验证页面未成功读取','不同表述','14 天','30 天','退货标签费用','不能承诺免费退货'])assert.ok(html.includes(text));
  if(['other','__proto__'].includes(code)){assert.ok(html.includes('该商家流程未逐步核实'));assert.equal((html.match(/data-merchant-help-link=/g)||[]).length,3)}
}
const sources=vm.runInContext('MERCHANT_GUIDE_HELP',context);
assert.ok(Object.isFrozen(sources));assert.equal(sources.length,11);
for(const item of sources){assert.ok(Object.isFrozen(item));assert.equal(new URL(item.url).protocol,'https:');assert.ok(!/account\/|join\.maap/.test(item.url))}
for(const entry of ['maap','visma','decathlon','other']){
  context.openMerchantGuide(detail,entry,'M');assert.equal(focus,'title');assert.equal(title,'商家中文操作图解');assert.ok(rendered.includes(entry+' official'));
  for(const item of sources){
    let href=item.url;const link={isConnected:true,dataset:{merchantHelpLink:item.key},getAttribute:()=>href};
    const event={target:{closest:()=>link},type:'click',button:0,preventDefault:()=>prevented++};
    const permitted=item.scope==='browser'||item.scope===entry;
    assert.equal(context.allowedMerchantHelp(link),permitted?item:null);
    const before=navigated.length;
    exit.setAnswer(options=>{confirmations++;assert.equal(options.kind,'reference');assert.equal(options.url,item.url);assert.equal(options.trigger,link);assert.ok(options.note.includes('不会代你注册'));return false});
    context.guardMerchantHelpExit(event);assert.equal(navigated.length,before);
    exit.setAnswer(true);
    for(const options of [{},{ctrlKey:true},{metaKey:true},{shiftKey:true},{type:'auxclick',button:1}])context.guardMerchantHelpExit({...event,...options});
    assert.equal(navigated.length,before+(permitted?5:0));
    const after=navigated.length;
    for(const bad of [item.url+'#fake',item.url+'?tag=affiliate',item.url.replace('https://','http://'),item.url.replace('https://','https://evil.example/'),'javascript:alert(1)','']){href=bad;assert.equal(context.allowedMerchantHelp(link),null);context.guardMerchantHelpExit(event);assert.equal(navigated.length,after)}
    href=item.url;link.dataset.merchantHelpLink='wrong';context.guardMerchantHelpExit(event);assert.equal(navigated.length,after);link.dataset.merchantHelpLink=item.key;
    exit.setAnswer(()=>{href+='?substituted';return true});context.guardMerchantHelpExit(event);assert.equal(navigated.length,after);
    href=item.url;exit.setAnswer(true);link.isConnected=false;context.guardMerchantHelpExit(event);assert.equal(navigated.length,after);link.isConnected=true;
    connected=false;context.guardMerchantHelpExit(event);assert.equal(navigated.length,after);connected=true;
    exit.setAnswer(()=>{throw Error('Right click must not open a prompt')});context.guardMerchantHelpExit({...event,type:'auxclick',button:2});
  }
}
// Detached, hidden or dismissed help never keeps a live outbound action.
context.openMerchantGuide(detail,'maap','M');
const hiddenSource=sources.find(item=>item.scope==='maap'),hiddenLink={isConnected:true,dataset:{merchantHelpLink:hiddenSource.key},getAttribute:()=>hiddenSource.url};
context.sheet.classList.contains=()=>false;assert.equal(context.allowedMerchantHelp(hiddenLink),null);context.sheet.classList.contains=()=>true;
vm.runInContext('merchantGuideSource=null',context);assert.equal(context.allowedMerchantHelp(hiddenLink),null);
assert.equal(saved,navigated.length);assert.ok(prevented>saved);assert.ok(confirmations>0);
assert.equal(JSON.stringify(detail),unchanged,'Guide never changes any offer');
assert.ok(gallery.includes("if(typeof merchantGuideSource!=='undefined')merchantGuideSource=null;"));
assert.ok(!gallery.includes('merchantGuidesMarkup(detail)+'),'Account instructions are not an early product-detail entry');
assert.ok(!source.includes('registrationHelpMarkup(')&&!source.includes('registrationGuideMarkup('),'Read-only language guide does not duplicate registration');
assert.ok(!source.includes('purchaseReadinessMarkup('));
assert.ok(css.includes('.merchant-guide-buttons button:focus-visible'));assert.ok(css.includes('@media(max-width:450px)'));assert.ok(css.includes('.merchant-diagram-cells{grid-template-columns:1fr}'));
(async()=>{
  context.openMerchantGuide(detail,'maap','M');await elements.merchantGuideBack.onclick();assert.deepEqual(loaded.at(-1),['jersey','M']);assert.equal(focus,'maap');assert.equal(vm.runInContext('merchantGuideSource',context),null);
  context.openMerchantGuide(detail,'visma',null);await elements.merchantGuideBack.onclick();assert.deepEqual(loaded.at(-1),['jersey',null]);assert.equal(focus,'visma');
  context.openMerchantGuide(detail,'decathlon','M');context.loadDetail=async()=>{context.detailSequence+=2;focus='closed'};await elements.merchantGuideBack.onclick();assert.equal(focus,'closed','Late Back response must not steal focus from a new panel');
  console.log('Merchant guides passed: every merchant/read-only soldout, six accessible schematic steps, scoped official evidence, translations, no forms or purchase links, exact same-tab allowlists, Cancel/Continue/tampering and focus-safe Back');
})().catch(error=>{console.error(error);process.exitCode=1});
