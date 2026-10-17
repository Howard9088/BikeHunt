'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const data=JSON.parse(fs.readFileSync('web/traveler-forum-data.json','utf8'));
assert.equal(data.cards.length,5);assert.equal(data.cards.filter(x=>x.primary).length,3);
const sources=data.cards.flatMap(x=>x.sources);assert.equal(sources.length,5);assert.equal(new Set(sources.map(x=>x.url)).size,5);
assert.equal(sources.filter(x=>x.author).length,2,'Unverified nicknames are omitted');
assert.ok(!JSON.stringify(data).includes('indexed_article_body'));assert.ok(!JSON.stringify(data).includes('Fizik'));
for(const row of data.cards){assert.ok(row.sections.length&&row.warning&&row.market);for(const s of row.sources){assert.equal(new URL(s.url).hostname,'post.smzdm.com');assert.match(s.date,/^\d{4}-\d{2}-\d{2}$/)}for(const section of row.sections)for(const text of section.paragraphs)assert.match(text,/\p{Script=Han}/u)}
assert.ok(!JSON.stringify(data).includes('post.smzdm.com/p/558113/'),'The complaint article is not published');
for(const row of data.cards)assert.ok(!/拆单|被骗|诈骗|坑爹/.test(row.title));
const related=data.cards.find(x=>x.id==='smzdm-osprey-service-2018');assert.equal(related.sources.length,1);assert.equal(related.sections.length,1);assert.match(related.warning,/同一订单/);
let panel,closed=0;const nodes=new Map();
const c=vm.createContext({URL,console,fixture:data,window:{location:{assign(){throw Error('Cards cannot navigate externally')}}},document:{getElementById:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id)}},safeUrl:v=>{try{const u=new URL(v);return u.protocol==='https:'&&!u.username&&!u.password?u.href:''}catch{return ''}},e:v=>String(v??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x])),openPanel:(title,html)=>panel={title,html},closeSheet:()=>closed++});
vm.runInContext(fs.readFileSync('web/traveler-experiences.js','utf8'),c);vm.runInContext('travelerData=fixture',c);
assert.equal(c.publishedTravelerThreads(data).length,5);
assert.equal(c.publishedTravelerThreads(JSON.parse(fs.readFileSync('web/traveler-experiences.json','utf8'))).length,0,'Legacy English-platform sources are not the main forum');
for(const row of data.cards){const tile=c.travelerThreadMarkup(row);assert.ok(tile.includes('<button'));assert.ok(!/<a(?:\s|>)/.test(tile));assert.ok(!/点赞|浏览量|回复数|<img/.test(tile));c.openTravelerThread(row.id);assert.equal(panel.title,row.title);for(const section of row.sections)for(const text of section.paragraphs)assert.ok(panel.html.includes(c.e(text)));assert.ok(panel.html.includes('原文出处与日期'));assert.ok(!panel.html.includes('昵称待核实'));nodes.get('travelerReturn').onclick();}
assert.equal(closed,5);
console.log('PASS Chinese SMZDM summaries, 5 internal threads / 5 positive practical sources, related-order context, no fake authors/stats/images, optional source links and internal full reading');
