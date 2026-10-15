'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const gallery=fs.readFileSync('web/gallery.js','utf8'),flows=fs.readFileSync('web/flows.js','utf8'),index=fs.readFileSync('web/index.html','utf8');
new vm.Script(gallery);new vm.Script(flows);
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
let confirmed=0,prevented=0;const ctx={guideContext:{quote:fresh},offerAvailable:context.offerAvailable,merchantUrl:context.merchantUrl,PURCHASE_DISCLAIMER:'test',saveBrowseState:()=>{},window:{confirm:()=>{confirmed++;return false;}}};vm.createContext(ctx);vm.runInContext(guard,ctx);
const event={target:{closest:()=>({getAttribute:()=>fresh.offer.url})},type:'click',preventDefault:()=>prevented++};
ctx.guardPurchaseExit(event);assert.equal(confirmed,1);assert.equal(prevented,1);
ctx.window.confirm=()=>true;ctx.guardPurchaseExit(event);assert.equal(prevented,1);
ctx.guideContext=null;ctx.guardPurchaseExit(event);assert.equal(prevented,2);
console.log('Safety regression: fresh/expired/soldout/unknown/retained guards, cancel/continue, logo and labels passed');

// Amazon entrances must be exact fixed searches, not catalogue offers.
const amazonSource=flows.slice(flows.indexOf('const AMAZON_SEARCH_MARKETS='),flows.indexOf("document.getElementById('amazonChannels').onclick"));
let amazonPromptCount=0,amazonSaved=0,amazonPrevented=0,amazonPanel='',amazonNavigated=[];
const amazonContext={URLSearchParams,PURCHASE_DISCLAIMER:'full disclaimer sentinel',e:value=>String(value),
  openPanel:(title,html)=>{assert.equal(title,'Amazon购买途径');amazonPanel=html;},
  saveBrowseState:()=>amazonSaved++,window:{confirm:message=>{amazonPromptCount++;assert.ok(message.includes('full disclaimer sentinel'));return false;},location:{assign:url=>amazonNavigated.push(url)}}};
vm.createContext(amazonContext);vm.runInContext(amazonSource,amazonContext);
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
    const before=amazonNavigated.length;
    amazonContext.window.confirm=message=>{amazonPromptCount++;assert.ok(message.startsWith('full disclaimer sentinel'));return false;};
    amazonContext.guardAmazonSearchExit(click);assert.equal(amazonNavigated.length,before);
    amazonContext.window.confirm=()=>true;
    for(const options of [{},{ctrlKey:true},{metaKey:true},{shiftKey:true},{type:'auxclick',button:1}])amazonContext.guardAmazonSearchExit({...click,...options});
    assert.equal(amazonNavigated.length,before+5);assert.ok(amazonNavigated.slice(before).every(url=>url===search.url));
    for(const bad of [search.url+'&tag=affiliate-20',search.url+'#fragment',search.url.replace(host,host+'.evil.example'),search.url.replace(host,host+'@evil.example'),search.url.replace('https:','http:'),search.url.replace('/s?','/dp/B000FAKE00?'),search.url.replace('k=','q='),'javascript:alert(1)','']){
      href=bad;assert.equal(amazonContext.allowedAmazonSearch(link),null);amazonContext.guardAmazonSearchExit(click);assert.equal(amazonNavigated.length,before+5);
    }
    href=search.url;link.dataset.amazonSearchLink='unknown';amazonContext.guardAmazonSearchExit(click);assert.equal(amazonNavigated.length,before+5);
    link.dataset.amazonSearchLink=search.key;amazonContext.window.confirm=()=>{href=search.url+'&tag=changed-20';return true;};amazonContext.guardAmazonSearchExit(click);assert.equal(amazonNavigated.length,before+5);
    href=search.url;amazonContext.window.confirm=()=>{throw new Error('Right click must be ignored');};amazonContext.guardAmazonSearchExit({...click,type:'auxclick',button:2});
  }
}
assert.equal(amazonSaved,40);assert.equal(amazonPromptCount,8);assert.ok(amazonPrevented>40);
amazonContext.showAmazonChannels();assert.equal((amazonPanel.match(/data-amazon-search-link=/g)||[]).length,8);assert.equal((amazonPanel.match(/target="_self"/g)||[]).length,8);assert.ok(!amazonPanel.includes('data-purchase-link')&&!amazonPanel.includes('data-reference-link'));
for(const note of ['搜索入口，非商品实时报价','Amazon 自营','第三方卖家','Fulfilled by Amazon','不等于 Amazon 自营','中国大陆','运费','进口税费','结账页'])assert.ok(amazonPanel.includes(note),note);
assert.ok(index.includes('id="amazonChannels">Amazon购买途径</button>'));
console.log('Amazon safety: eight fixed official category searches, honest labels, exact allowlist, URL/key tampering, cancel/continue and forced same-tab modifier/middle clicks passed');
