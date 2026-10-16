'use strict';
// Offline production-JS checks. No merchant requests or browser-rendering claims.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/registration-guides.js','utf8');new vm.Script(source);
const core=source.slice(0,source.indexOf("document.addEventListener('keydown'"));
const data=JSON.parse(fs.readFileSync('tests/fixtures/registration-guides.json','utf8'));
const current=JSON.parse(fs.readFileSync('web/registration-guides.json','utf8'));
const now=Date.parse('2026-10-16T00:00:00Z');
let requests=[],response=data,failed=false;
const context={URL,Date,Set,JSON,Object,Number,fetch:async(url,options)=>{requests.push([url,options]);if(failed)throw Error('Offline');return {ok:true,text:async()=>JSON.stringify(response)}},document:{currentScript:{src:'https://bikehunt.example/BikeHunt/web/registration-guides.js?v=release'},querySelectorAll:()=>[]},input:null};
vm.createContext(context);vm.runInContext(core,context);
function install(value){context.input=JSON.parse(JSON.stringify(value));vm.runInContext("registrationData=validateRegistrationData(input);registrationLoadState='ready'",context)}
assert.equal(context.validateRegistrationData(current),current);assert.equal(context.validateRegistrationData(data,now),data);install(data);
const publicEntry=context.registrationEntry('visma',null,'public_account');assert.ok(publicEntry);assert.equal(publicEntry.frames.length,3);
for(const market of ['',undefined,'US','US 市场报价（USD）','欧洲站 EUR 报价']){
  assert.equal(context.registrationEntry('visma',market),null,'Public account page cannot satisfy any exact-market lookup');
  const html=context.registrationGuideMarkup('visma',market);assert.ok(!html.includes('<details hidden'));assert.ok(html.includes('3 步中文注册图解'));assert.ok(html.includes('示意 · 非官网截图'));assert.ok(!html.includes('<img'));
}
const hostCodes=vm.runInContext('Object.keys(REGISTRATION_HOSTS)',context);assert.equal(hostCodes.length,28);
for(const code of hostCodes){const guide=context.registrationGuideMarkup(code,'测试市场');assert.ok(guide.includes('registration-schematic-steps'),code);assert.ok(!/<(?:img|form|input|select|textarea|iframe|a)\b/i.test(guide));}
for(const [code,market,word] of [['rapha','日本站报价','アカウント'],['rapha_kr','韩国站报价','회원가입'],['amazon_jp','日本站','新規登録'],['amazon_de','德国站','Konto erstellen']])assert.ok(context.registrationGuideMarkup(code,market).includes(word));
const html=context.registrationPublicAccountMarkup('visma');assert.equal((html.match(/<img/g)||[]).length,6);assert.ok(html.includes('账户注册图解'));
assert.ok(html.includes('配送地区与购买条件请在结账时确认'));assert.ok(html.includes('页面可能更新'));assert.ok(html.includes('2026-10-15'));assert.ok(!html.includes('visma-public-account-20261015-v1'));
assert.ok(html.includes('https://bikehunt.example/BikeHunt/web/assets/registration/visma-login-register-entry-20261015.jpg'));
assert.equal((html.match(/class="registration-annotation-list"/g)||[]).length,3);
assert.equal((html.match(/class="registration-zoom"/g)||[]).length,3);
assert.ok(html.includes('查看大图（原始分辨率）'));assert.ok(html.includes('收起大图'));assert.ok(html.includes('tabindex="0" role="region"'));
let zoomFocus=false,zoomPrevented=false,zoomStopped=false;const zoom={open:true,querySelector:()=>({focus:()=>zoomFocus=true})};context.closeRegistrationZoom({key:'Escape',target:{closest:()=>zoom},preventDefault:()=>zoomPrevented=true,stopImmediatePropagation:()=>zoomStopped=true});assert.equal(zoom.open,false);assert.ok(zoomFocus&&zoomPrevented&&zoomStopped);
const css=fs.readFileSync('web/flows.css','utf8');assert.ok(css.includes('.registration-zoom .registration-image-wrap>img{width:auto;max-width:none}'));assert.ok(css.includes('pan-x pan-y pinch-zoom'));assert.ok(css.includes('.registration-schematic-steps'));assert.ok(css.includes('@media(max-width:700px)'));

assert.ok(!/<(?:form|input|select|textarea|iframe|a)\b|data-purchase-link|data-reference-link/.test(html));
assert.ok(!html.includes(' open>'),'Help is optional and initially collapsed');
for(const diagnostic of ['reviewReason','图解版本','截图视口','本次云端','未提交注册或登录'])assert.ok(!html.includes(diagnostic));
for(const [code,market] of [['amazon_us','美国站'],['amazon_uk','英国站'],['amazon_de','德国站'],['amazon_jp','日本站']]){
  const html=context.registrationHelpMarkup(code,market);assert.ok(!html.includes('<details hidden'));assert.ok(html.includes('示意 · 非官网截图'));assert.ok(!html.includes('本次云端未能打开页面'));assert.ok(!html.includes('<img'));
  assert.equal(context.registrationEntry(code,'其他市场'),null);assert.equal(context.registrationPublicAccountMarkup(code),'');
}
assert.equal(context.registrationEntry('__proto__','US'),null);assert.ok(!context.registrationHelpMarkup('__proto__','US').includes('<img'));
assert.ok(context.registrationHelpMarkup('<img>','<script>').includes('&lt;script&gt;'));
const exact=structuredClone(data);const marketEntry=structuredClone(exact.entries[0]);marketEntry.scope='market';marketEntry.salesRegion='US 市场报价（USD）';marketEntry.marketLabel='US market';exact.entries.push(marketEntry);install(exact);
assert.ok(context.registrationEntry('visma','US 市场报价（USD）'));assert.equal(context.registrationEntry('visma','US 市场报价（USD） '),null);assert.equal(context.registrationEntry('visma','UK 市场报价（GBP）'),null);
const stale=structuredClone(data);stale.entries[0].status='needs_review';stale.entries[0].reviewReason='账户页面布局已变更。';install(stale);
assert.equal(context.registrationPublicAccountMarkup('visma'),'');assert.equal(context.registrationContent('visma',null,'public_account'),'');
const old=structuredClone(data);old.entries[0].frames[0].verifiedAt='2000-01-01';install(old);assert.ok(context.registrationPublicAccountMarkup('visma').includes('<img'),'Age alone never invents an expiry');
for(const bad of ['https://evil.example/a.jpg','assets/registration/../a.jpg','assets/registration/a.svg','assets/registration/a.jpg?x','assets/registration/%61.jpg']){const invalid=structuredClone(data);invalid.entries[0].frames[0].asset=bad;assert.throws(()=>context.validateRegistrationData(invalid,now))}
for(const bad of ['https://evil.example/register/','https://www.teamvismaleaseabike.com.evil.example/register/','https://person@www.teamvismaleaseabike.com/register/','https://www.teamvismaleaseabike.com/register/?secret=x','javascript:alert(1)']){const invalid=structuredClone(data);invalid.entries[0].frames[0].sourceUrl=bad;assert.throws(()=>context.validateRegistrationData(invalid,now))}
assert.equal(context.registrationSourceUrl('https://account.decathlon.com/','decathlon'),false);
for(const bad of ['2030-01-01','2026-02-30','2026-10-15T04:00:00','2026-10-15T99:00:00Z','2026-10-15T24:00:00Z',null]){const invalid=structuredClone(data);invalid.entries[0].frames[0].verifiedAt=bad;assert.throws(()=>context.validateRegistrationData(invalid,now))}
for(const modify of [d=>d.entries.push(structuredClone(d.entries[0])),d=>d.entries[0].sourceCode='__proto__',d=>d.entries[0].frames[0].screenshotKind='schematic',d=>d.entries[0].frames[0].annotations[0].width=100,d=>d.entries[0].frames[0].annotations[0].x=NaN,d=>d.entries[0].frames[0].annotations=[]]){const invalid=structuredClone(data);modify(invalid);assert.throws(()=>context.validateRegistrationData(invalid,now))}
const malicious=structuredClone(data);malicious.entries[0].frames[0].caption='<img src=x onerror=alert(1)>';install(malicious);assert.ok(context.registrationPublicAccountMarkup('visma').includes('&lt;img src=x onerror=alert(1)&gt;'));
const flows=fs.readFileSync('web/flows.js','utf8'),gallery=fs.readFileSync('web/gallery.js','utf8'),index=fs.readFileSync('web/index.html','utf8');
assert.ok(index.indexOf('/web/registration-guides.js')<index.indexOf('/web/gallery.js'));
const purchaseFlow=fs.readFileSync('web/purchase-flow.js','utf8');
assert.ok(index.indexOf('/web/flows.js')<index.indexOf('/web/purchase-flow.js'));
assert.ok(!gallery.includes('registrationHelpMarkup('),'Product details must not start account instructions');
const referenceDetail=flows.slice(flows.indexOf('function roadReferenceDetailMarkup('),flows.indexOf('function allowedRoadDetailButton('));
assert.ok(referenceDetail.includes('registrationHelpMarkup(row.source_code,row.market)'), 'Research guide has scoped, read-only help immediately before its final exit');
assert.ok(!flows.replace(referenceDetail,'').includes('registrationHelpMarkup('),'Amazon, inventory and read-only language panels must not contain early registration');
for(const code of ['trek','specialized','canyon','colnago']){
  const markup=context.registrationHelpMarkup(code,'US');
  assert.ok(!markup.includes('<details hidden'));assert.ok(markup.includes('示意 · 非官网截图'));
  assert.ok(!/<(?:form|input|select|textarea|iframe|img)\b/.test(markup), 'Unverified new brands cannot borrow a screenshot or submit account data');
}
assert.ok(purchaseFlow.includes('registrationHelpMarkup('),'Registration help belongs to the final interstitial');
assert.ok(purchaseFlow.includes('registrationInterstitial'));
assert.ok(flows.includes("if(!entry.markets.includes(market))entry.markets.push(market)"));
(async()=>{
 response=data;await context.loadRegistrationGuides();assert.equal(requests.length,1);assert.equal(requests[0][1].cache,'no-store');assert.ok(requests[0][0].startsWith('https://bikehunt.example/BikeHunt/web/registration-guides.json?check='));
 assert.ok(context.registrationPublicAccountMarkup('visma').includes('<img'));
 failed=true;await context.loadRegistrationGuides();assert.equal(vm.runInContext('registrationData',context),null);assert.ok(!context.registrationHelpMarkup('visma','US').includes('<img'));
 failed=false;response=data;await context.loadRegistrationGuides();assert.ok(context.registrationPublicAccountMarkup('visma').includes('<img'));
 response={schemaVersion:99};await context.loadRegistrationGuides();assert.equal(vm.runInContext('registrationData',context),null);
 console.log('Registration screenshots passed: exact source/market/scope, three-frame Visma fixture, four distinct fallback Amazon markets, buyer date without internal version, withdrawal, no invented expiry, trusted paths/origins, escaped annotations, local-only help and fail-closed refresh.');
})().catch(error=>{console.error(error);process.exitCode=1});
