'use strict';
const assert = require('node:assert/strict');
const {readVisits, start} = require('../web/visitor-stats.js');
const prod = {hostname:'howard9088.github.io', pathname:'/BikeHunt/'};
function dom() { const el={dataset:{},textContent:''};return {el,getElementById:()=>el}; }
(async () => {
  let requests=0;
  const fetcher=async (url,options)=>{
    requests++;
    assert.equal(url,'https://bsz.iirose.cn/api');
    assert.deepEqual(options.headers,{'x-bsz-referer':'https://howard9088.github.io/BikeHunt/'});
    assert.equal(options.credentials,'omit');
    assert.equal(options.referrerPolicy,'no-referrer');
    return {ok:true,json:async()=>({success:true,data:{page_pv:'1234',site_pv:999999}})};
  };
  const doc=dom(); await start(doc,prod,fetcher);await start(doc,prod,fetcher);
  assert.equal(requests,1);assert.match(doc.el.textContent,/1,234/);assert.doesNotMatch(doc.el.textContent,/999/);
  const local=dom();await start(local,{hostname:'localhost',pathname:'/'},fetcher);assert.equal(requests,1);
  for(const value of [null,undefined,-1,1.1,'<script>','1e3',{},Number.MAX_SAFE_INTEGER+1])
    await assert.rejects(readVisits(async()=>({ok:true,json:async()=>({success:true,data:{page_pv:value}})})));
  const fail=dom();await start(fail,prod,async()=>{throw new Error('offline')});
  assert.equal(fail.el.dataset.state,'unavailable');assert.doesNotMatch(fail.el.textContent,/0/);
  console.log('Visitor statistics: 12 mock checks passed; no external requests.');
})().catch(e=>{console.error(e);process.exit(1)});
