'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const gallery=fs.readFileSync('web/gallery.js','utf8'),flows=fs.readFileSync('web/flows.js','utf8');
function section(s,a,b){return s.slice(s.indexOf(a),s.indexOf(b,s.indexOf(a)))}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
async function main(){
 const nodes=new Map(),listeners=new Set(),onPrices=()=>{};let request=deferred(),reads=0,boots=0,boot=deferred(),renders=0;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',innerHTML:'',disabled:false});return nodes.get(id)};
 const c=vm.createContext({Promise,console,document:{getElementById:node},window:{BIKEHUNT_PAGES:true,addEventListener:(name,f)=>listeners.add(f),removeEventListener:(name,f)=>listeners.delete(f)},localStorage:{getItem:()=>null},gallery:node('grid'),observer:null,items:[],fx:{},sourceCount:0,viewMode:'feed',catalogLoadState:'loading',catalogLoadPromise:null,updatePosition(){},publicCatalogData:x=>x,getJson:()=>{reads++;return request.promise},updateFxLabel(){},setView(){renders++},bootFlows:()=>{boots++;return boot.promise.then(()=>{listeners.add(onPrices)})}});
 vm.runInContext(section(gallery,'function renderCatalogLoadState(){','function render(preserveId='),c);
 vm.runInContext(section(gallery,'function init(){',"document.addEventListener('input'"),c);
 vm.runInContext(section(flows,'let flowsStarted=false','\nstartFlows();'),c);
 assert.ok(gallery.includes('function render(preserveId=null){\n  if(renderCatalogLoadState())return;'));
 assert.ok(flows.includes("if(catalogLoadState!=='ready')return init();"));
 const pending=c.init();assert.equal(c.init(),pending);assert.equal(reads,1);
 c.renderCatalogLoadState();assert.match(node('grid').innerHTML,/正在整理/);assert.doesNotMatch(node('count').textContent,/0 件/);
 request.reject(Error('offline'));await pending;
 c.renderCatalogLoadState();assert.match(node('grid').innerHTML,/商品暂时无法加载/);assert.equal(node('retry').onclick,c.init);
 // Failed startup and repeated navigation/retry must never add subscriptions.
 const first=c.startFlows();assert.equal(c.startFlows(),first);boot.reject(Error('offline'));await first;assert.equal(listeners.size,1);
 request=deferred();boot=deferred();const retry=node('retry').onclick();request.resolve({items:[{id:'verified'}],fx:{},source_count:2});await retry;
 assert.equal(c.catalogLoadState,'ready');assert.equal(c.items.length,1);assert.equal(renders,1);assert.equal(boots,2);
 const recovery=c.startFlows();boot.resolve();await recovery;await c.startFlows();assert.equal(boots,2);assert.equal(listeners.size,1);assert.ok(listeners.has(onPrices));
 // A later failed refresh keeps the last verified catalog and observations.
 const saved=c.items;request=deferred();const refresh=c.init();request.reject(Error('offline again'));await refresh;
 assert.equal(listeners.size,1);assert.equal(boots,2);assert.equal(c.catalogLoadState,'ready');assert.equal(c.items,saved);assert.equal(c.renderCatalogLoadState(),false);
 // A successful empty catalog is distinct from load failure.
 request=deferred();const empty=c.init();request.resolve({items:[],fx:{},source_count:0});await empty;
 assert.equal(c.catalogLoadState,'ready');assert.equal(c.items.length,0);assert.equal(c.renderCatalogLoadState(),false);
 console.log('Catalog loading/error/retry, single-flight boot, listener cleanup, retained catalog and genuine empty: PASS');
}
main().catch(error=>{console.error(error);process.exitCode=1});
