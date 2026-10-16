const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const api=require('../web/listing-order.js');
const NOW=Date.parse('2026-10-18T00:00:00Z');
const card=(id,date,price=10,more={})=>({product_id:id,first_listed_at:date,reference_cny:price,stock_state:'in_stock',channel:'one',model:id,...more});
const a=card('a','2026-10-16T12:44:58Z'),b=card('b','2026-10-17T12:44:58Z',20),u=card('u',null,1);
assert.equal(api.listingLabel(a,NOW),'本站发布：2026-10-16 20:44');
assert.equal(api.listingLabel(card('x','2026-10-16T16:00:00Z'),NOW),'本站发布：2026-10-17 00:00');
for(const value of [null,undefined,'bad','2026-02-30T00:00:00Z','2026-10-16','2026-10-16T12:00:00','2026-10-19T00:00:00Z'])assert.equal(api.listingLabel(card('x',value),NOW),'本站发布：未记录');
assert.deepEqual(api.orderCatalog([u,a,b],{now:NOW}).map(x=>x.product_id),['b','a','u']);
const opts={now:NOW,eligible:p=>p.stock_state==='in_stock'&&p.reliable!==false,channelKey:p=>p.channel,modelKey:p=>p.model};
const c=card('c',b.first_listed_at,15),d=card('d',b.first_listed_at,5,{channel:'two'});
const sold=card('sold',b.first_listed_at,1,{stock_state:'out_of_stock'}),unknown=card('unknown',b.first_listed_at,1,{stock_state:'unknown'});
assert.deepEqual(api.selectHome([u,a,b,c,d,sold,unknown],opts).map(x=>x.product_id),['d','c','b']);
assert.equal(api.orderCatalog([a,b,c,d],{now:NOW}).length,4,'Global category ordering has no channel cap');
assert.deepEqual(api.selectHome([a,b,c,d],{...opts,explicitCompare:(a,b)=>a.reference_cny-b.reference_cny}).map(x=>x.product_id),['d','a','c']);
assert.deepEqual(api.orderCatalog([a,b,c],{now:NOW,explicitCompare:(a,b)=>a.reference_cny-b.reference_cny}).map(x=>x.product_id),['a','c','b']);
const original=JSON.stringify([a,b]);api.orderCatalog([a,b],{now:NOW});assert.equal(JSON.stringify([a,b]),original);
assert.equal(api.listingLabel({...a,fetched_at:'2026-10-17T23:00:00Z',stock_state:'out_of_stock'},NOW),api.listingLabel(a,NOW));
assert.equal(api.selectHome([a,{...a,product_id:'size-added'},b,c],opts).filter(x=>x.model==='a').length,0,'Size alias does not create another homepage model');
for(const order of [[a,{...a,product_id:'aa'}],[{...a,product_id:'aa'},a]])assert.deepEqual(api.orderCatalog(order,{now:NOW}).map(x=>x.product_id),['a','aa']);
for(const TZ of ['UTC','America/Los_Angeles','Asia/Tokyo']){
 const result=execFileSync(process.execPath,['-e',`const a=require('./web/listing-order');process.stdout.write(a.listingLabel(${JSON.stringify(a)},${NOW}))`],{env:{...process.env,TZ,LANG:'ar_EG.UTF-8'}}).toString();
 assert.equal(result,'本站发布：2026-10-16 20:44');
}
console.log('Listing order passed: actual receipt only, Shanghai minute label, unknown/future, stable ties, explicit sort, two per channel, uncapped categories.');
