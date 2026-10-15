'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {installExternalExitStub}=require('./external_exit_test_helper');
const gallery=fs.readFileSync('web/gallery.js','utf8'),flows=fs.readFileSync('web/flows.js','utf8'),index=fs.readFileSync('web/index.html','utf8');
const externalExit=fs.readFileSync('web/external-exit.js','utf8');
new vm.Script(gallery);new vm.Script(flows);
new vm.Script(externalExit);
assert.ok(externalExit.includes('完整购买提示与免责声明')&&externalExit.includes('PURCHASE_DISCLAIMER'),'Shared UI retains the complete original disclaimer');
assert.ok(!/\bwindow\.confirm\s*\(/.test(gallery+flows+fs.readFileSync('web/purchase-flow.js','utf8')+fs.readFileSync('web/purchase-readiness.js','utf8')),'All legacy native exit prompts are removed');
const helper=gallery.slice(gallery.indexOf('function inventoryVerified('),gallery.indexOf('function offerMarkup('));
const context={Date,Number,URL,safeUrl:value=>{try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:''}catch{return ''}}};vm.createContext(context);vm.runInContext(helper,context);
const fresh={offer:{url:'https://shop.example/products/jersey',stock:'in_stock',fetched_at:new Date().toISOString()}};
assert.equal(context.offerAvailable(fresh),true);
assert.equal(context.offerAvailable({offer:{...fresh.offer,stock:'out_of_stock'}}),false);
assert.equal(context.offerAvailable({offer:{...fresh.offer,stock:'unknown'}}),false);
assert.equal(context.offerAvailable({offer:{...fresh.offer,collection_state:'retained'}}),false);
assert.equal(context.offerAvailable({offer:{...fresh.offer,fetched_at:'2000-01-01T00:00:00Z'}}),false);
assert.ok(gallery.includes("p.stock_state!=='out_of_stock'&&profileMatches(p)"));
assert.ok(gallery.includes("?.stock_state==='out_of_stock')return;"));
assert.ok(gallery.includes("!offerAvailable(compared)?'disabled'"));
assert.ok(index.includes('世巡车队')&&!index.includes('骑行车队')&&!flows.includes('骑行车队'));
assert.ok(index.includes('class="bikehunt-mark"'));
assert.ok(flows.includes("本站仅提供商品与优惠信息，不参与交易。价格、库存、尺码及折扣可能变化，信息不保证完全准确，请以实际商家页面及结算信息为准，并在购买前自行核实。购买、付款、配送、退换货，以及买错商品或尺码不合适等问题，请直接联系实际商家。法律规定本站应承担的责任除外。"));
const guard=flows.slice(flows.indexOf('function guardPurchaseExit('),flows.indexOf("document.addEventListener('click',guardPurchaseExit)"));
let confirmed=0,prevented=0,stages=0;const ctx={guideContext:{quote:fresh},referenceAvailable:context.referenceAvailable,merchantUrl:context.merchantUrl,continuePurchaseRoute:()=>stages++,showExternalExit:()=>{confirmed++;return false;},window:{confirm:()=>{throw Error('No native exit prompt')}}};vm.createContext(ctx);vm.runInContext(guard,ctx);
const event={target:{closest:()=>({getAttribute:()=>fresh.offer.url})},type:'click',preventDefault:()=>prevented++};
ctx.guardPurchaseExit(event);assert.equal(confirmed,0);assert.equal(prevented,1);assert.equal(stages,1);
ctx.guideContext=null;ctx.guardPurchaseExit(event);assert.equal(prevented,2);assert.equal(stages,1);
console.log('Safety regression: fresh/expired/soldout/unknown/retained guards, intercepted staged purchase, logo and labels passed');

// Amazon entrances must be exact fixed searches, not catalogue offers.
const amazonSource=flows.slice(flows.indexOf('const AMAZON_SEARCH_MARKETS='),flows.indexOf("document.getElementById('amazonChannels').onclick"));
let amazonSaved=0,amazonPrevented=0,amazonPanel='',amazonNavigated=[],amazonStages=[],amazonOpen=true,amazonConnected=true;
const amazonSheet={classList:{contains:()=>amazonOpen}},amazonBody={querySelectorAll:()=>[],contains:()=>amazonConnected};
const amazonContext={URL,URLSearchParams,sheet:amazonSheet,document:{currentScript:{src:'https://bikehunt.example/BikeHunt/web/flows.js?v=release'},getElementById:id=>id==='sheet'?amazonSheet:amazonBody},PURCHASE_DISCLAIMER:'full disclaimer sentinel',e:value=>String(value),
  openPanel:(title,html)=>{assert.equal(title,'Amazon购买途径');amazonPanel=html;},
  openAmazonRegistration:search=>amazonStages.push(search),saveBrowseState:()=>amazonSaved++,window:{location:{assign:url=>amazonNavigated.push(url)}}};
const amazonExit=installExternalExitStub(amazonContext);
vm.createContext(amazonContext);vm.runInContext(amazonSource,amazonContext);
const amazonLogo=vm.runInContext('AMAZON_CHANNEL_LOGO_URL',amazonContext);
assert.equal(amazonLogo,'https://bikehunt.example/BikeHunt/web/assets/brands/amazon-official.png');
const logoDeclaration=amazonSource.slice(amazonSource.indexOf('const AMAZON_CHANNEL_LOGO_URL='),amazonSource.indexOf('function syncAmazonChannelLogo('));
for(const base of ['https://bikehunt.example/web/flows.js','https://bikehunt.example/BikeHunt/web/flows.js?v=release']){
  const logoContext={URL,document:{currentScript:{src:base}}};vm.createContext(logoContext);vm.runInContext(logoDeclaration,logoContext);
  assert.equal(vm.runInContext('AMAZON_CHANNEL_LOGO_URL',logoContext),new URL('assets/brands/amazon-official.png',base).href);
}
const logoState={complete:false,naturalWidth:0,hidden:true,nextElementSibling:{hidden:false}};
amazonContext.syncAmazonChannelLogo(logoState);assert.equal(logoState.hidden,true);assert.equal(logoState.nextElementSibling.hidden,false);
logoState.complete=true;logoState.naturalWidth=6110;amazonContext.syncAmazonChannelLogo(logoState);assert.equal(logoState.hidden,false);assert.equal(logoState.nextElementSibling.hidden,true);
logoState.naturalWidth=0;amazonContext.syncAmazonChannelLogo(logoState);assert.equal(logoState.hidden,true);assert.equal(logoState.nextElementSibling.hidden,false);
assert.equal(require('node:crypto').createHash('sha256').update(fs.readFileSync('web/assets/brands/amazon-official.png')).digest('hex'),'5d26b516f9cf43e65c114ea65369c6fb209e4528678ad7c1d7d67623cbd3efab');
const amazonMarkets=vm.runInContext('AMAZON_SEARCH_MARKETS',amazonContext);
assert.equal(amazonMarkets.length,4);
assert.ok(Object.isFrozen(amazonMarkets));
const expectedAmazon=[['amazon_us','www.amazon.com','road cycling jersey','road cycling bib shorts'],['amazon_uk','www.amazon.co.uk','road cycling jersey','road cycling bib shorts'],['amazon_de','www.amazon.de','Rennrad Trikot','Rennrad Trägerhose'],['amazon_jp','www.amazon.co.jp','ロードバイク サイクルジャージ','ロードバイク ビブショーツ']];
for(let i=0;i<expectedAmazon.length;i++){
  const [code,host,...queries]=expectedAmazon[i],market=amazonMarkets[i];
  assert.equal(market.code,code);assert.ok(Object.isFrozen(market)&&Object.isFrozen(market.searches));assert.equal(market.searches.length,2);
  for(let j=0;j<queries.length;j++){
    const search=market.searches[j],parsed=new URL(search.url);assert.ok(Object.isFrozen(search));
    assert.equal(parsed.origin,'https://'+host);assert.equal(parsed.pathname,'/s');assert.equal(parsed.searchParams.get('k'),queries[j]);assert.deepEqual([...parsed.searchParams.keys()],['k']);assert.equal(parsed.hash,'');
    let href=search.url;const link={dataset:{amazonSearchLink:search.key},getAttribute:()=>href};
    const click={target:{closest:()=>link},type:'click',button:0,preventDefault:()=>amazonPrevented++};
    const before=amazonStages.length;
    for(const options of [{},{ctrlKey:true},{metaKey:true},{shiftKey:true},{type:'auxclick',button:1}])amazonContext.guardAmazonSearchExit({...click,...options});
    assert.equal(amazonStages.length,before+5);assert.ok(amazonStages.slice(before).every(item=>item.url===search.url));
    assert.equal(amazonNavigated.length,0);assert.equal(amazonExit.prompts.length,0,'Search opens local registration before any purchase disclaimer');
    for(const bad of [search.url+'&tag=affiliate-20',search.url+'#fragment',search.url.replace(host,host+'.evil.example'),search.url.replace(host,host+'@evil.example'),search.url.replace('https:','http:'),search.url.replace('/s?','/dp/B000FAKE00?'),search.url.replace('k=','q='),'javascript:alert(1)','']){
      href=bad;assert.equal(amazonContext.allowedAmazonSearch(link),null);amazonContext.guardAmazonSearchExit(click);assert.equal(amazonStages.length,before+5);
    }
    href=search.url;link.dataset.amazonSearchLink='unknown';amazonContext.guardAmazonSearchExit(click);assert.equal(amazonStages.length,before+5);
    link.dataset.amazonSearchLink=search.key;amazonContext.guardAmazonSearchExit({...click,type:'auxclick',button:2});assert.equal(amazonStages.length,before+5,'Right click never opens a stage');
  }
}
assert.equal(amazonSaved,0);assert.equal(amazonExit.prompts.length,0);assert.equal(amazonStages.length,40);assert.ok(amazonPrevented>40);
amazonContext.showAmazonChannels();assert.equal((amazonPanel.match(/data-amazon-search-link=/g)||[]).length,8);assert.equal((amazonPanel.match(/data-amazon-search-link="[^"]+"[^>]+target="_self"/g)||[]).length,8);assert.ok(!amazonPanel.includes('data-purchase-link')&&!amazonPanel.includes('data-reference-link'));
for(const note of ['搜索入口，非商品实时报价','Amazon 自营','第三方卖家','Fulfilled by Amazon','不等于 Amazon 自营','中国大陆','运费','进口税费','结账页'])assert.ok(amazonPanel.includes(note),note);
assert.equal((amazonPanel.match(/class="amazon-channel-logo"/g)||[]).length,4);
assert.equal((amazonPanel.match(/alt="Amazon"/g)||[]).length,4);
for(const country of ['美国站','英国站','德国站','日本站'])assert.ok(amazonPanel.includes('class="amazon-country">'+country+'</span>'));
assert.equal((amazonPanel.match(/class="amazon-channel-fallback">Amazon/g)||[]).length,4);
assert.ok(amazonPanel.includes('BikeHunt 与 Amazon 无合作或隶属关系'));
assert.ok(!/<a[^>]*>\s*(?:<span[^>]*>\s*)?<img[^>]*amazon-channel-logo/.test(amazonPanel));
assert.ok(index.includes('id="amazonChannels">Amazon购买途径</button>'));
console.log('Amazon safety: eight fixed official category searches, honest labels, exact allowlist, URL/key tampering, registration-first dispatch for click/modifier/middle and no premature navigation passed');

// The guide is educational content only. References have a separate exact allowlist.
const importSteps=vm.runInContext('AMAZON_IMPORT_STEPS',amazonContext);
assert.deepEqual(Array.from(importSteps,step=>step.id),['market','address','size','seller','delivery','fees','payment','aftercare']);
assert.ok(Object.isFrozen(importSteps));
for(const step of importSteps)assert.ok(Object.isFrozen(step)&&Object.isFrozen(step.paragraphs));
assert.equal((amazonPanel.match(/data-amazon-step=/g)||[]).length,8);
assert.equal((amazonPanel.match(/name="amazon-import-steps"/g)||[]).length,8);
assert.equal((amazonPanel.match(/ open>/g)||[]).length,1);
assert.ok(!/<(?:form|input|select|iframe)\b/.test(amazonPanel));
for(const note of ['USD','GBP','EUR','JPY','Deliver to / Ship to','China（中国）','真实收件人','男女款','Size chart','cm / inch','Sold by','Ships from / Dispatches from','Verkauf durch / Versand','販売元 / 出荷元','不等于 Amazon 自营','没有列出进口费用，不代表免税或全部税费已预付','Import Fees Deposit','Import Charges','最终扣款币种','退货期限','跨境退货运费由谁承担','避免重复提交','Your Orders','追踪号码','美国、德国、日本站具体帮助本次未能完成核验'])assert.ok(amazonPanel.includes(note),note);
const expectedHelp=[['seller','GEF528GN65XSJ7V8'],['charges','G8VRJ7Y8Z3T5WPV3'],['deposit','G9UHGT37MYD2EJPL'],['tracking','GBPEXEXYULHB5WCH']];
const importHelp=vm.runInContext('AMAZON_IMPORT_HELP',amazonContext);
assert.ok(Object.isFrozen(importHelp));assert.equal(importHelp.length,4);
assert.equal((amazonPanel.match(/data-amazon-help-link=/g)||[]).length,4);
for(let i=0;i<expectedHelp.length;i++){
  const [key,node]=expectedHelp[i],source=importHelp[i];
  assert.ok(Object.isFrozen(source));assert.equal(source.key,key);
  assert.equal(source.url,'https://digprjsurvey.amazon.co.uk/csad/help/node/'+node);
  let href=source.url;const link={isConnected:true,dataset:{amazonHelpLink:key},getAttribute:()=>href};
  const click={target:{closest:()=>link},type:'click',button:0,preventDefault:()=>amazonPrevented++};
  const before=amazonNavigated.length;
  amazonExit.setAnswer(options=>{assert.equal(options.kind,'reference');assert.equal(options.url,source.url);assert.equal(options.trigger,link);assert.ok(options.note.includes('官方帮助'));return false});
  amazonContext.guardAmazonHelpExit(click);assert.equal(amazonNavigated.length,before);
  amazonExit.setAnswer(true);
  for(const options of [{},{ctrlKey:true},{metaKey:true},{shiftKey:true},{type:'auxclick',button:1}])amazonContext.guardAmazonHelpExit({...click,...options});
  assert.equal(amazonNavigated.length,before+5);assert.ok(amazonNavigated.slice(before).every(url=>url===source.url));
  for(const bad of [source.url+'?tag=affiliate-20',source.url+'#changed',source.url.replace('amazon.co.uk','amazon.co.uk.evil.example'),'https://www.amazon.com/s?k=road','javascript:alert(1)','']){
    href=bad;assert.equal(amazonContext.allowedAmazonHelp(link),null);amazonContext.guardAmazonHelpExit(click);assert.equal(amazonNavigated.length,before+5);
  }
  href=source.url;link.dataset.amazonHelpLink='unknown';amazonContext.guardAmazonHelpExit(click);assert.equal(amazonNavigated.length,before+5);
  link.dataset.amazonHelpLink=key;amazonExit.setAnswer(()=>{href+='?changed';return true});amazonContext.guardAmazonHelpExit(click);assert.equal(amazonNavigated.length,before+5);
  href=source.url;amazonExit.setAnswer(true);
  link.isConnected=false;amazonContext.guardAmazonHelpExit(click);assert.equal(amazonNavigated.length,before+5);link.isConnected=true;
  amazonOpen=false;amazonContext.guardAmazonHelpExit(click);assert.equal(amazonNavigated.length,before+5);amazonOpen=true;
  amazonConnected=false;amazonContext.guardAmazonHelpExit(click);assert.equal(amazonNavigated.length,before+5);amazonConnected=true;
  for(const invalidate of [()=>{link.isConnected=false},()=>{amazonOpen=false},()=>{amazonConnected=false}]){
    amazonExit.setAnswer(()=>{invalidate();return true});amazonContext.guardAmazonHelpExit(click);assert.equal(amazonNavigated.length,before+5,'A detached or dismissed help context cannot navigate after confirmation');link.isConnected=true;amazonOpen=true;amazonConnected=true;
  }
  href=source.url;amazonExit.setAnswer(()=>{throw new Error('Right click must be ignored')});amazonContext.guardAmazonHelpExit({...click,type:'auxclick',button:2});
}
assert.equal(amazonSaved,amazonNavigated.length,'Cancel, invalid links, and stale contexts never persist exit state');
console.log('Amazon import guide: eight ordered educational steps, no data collection or checkout, scoped official sources, exact help allowlist, disclaimer Cancel/Continue and forced same-tab links passed');
