'use strict';
// Execute the production browser guards in an isolated DOM/clock harness.
// No network, merchant navigation, or browser-rendering claim is involved.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const gallery = fs.readFileSync(path.join(root, 'web/gallery.js'), 'utf8');
const flows = fs.readFileSync(path.join(root, 'web/flows.js'), 'utf8');
const START = Date.parse('2026-10-14T12:00:00.000Z');
function section(source, first, next) {
  const start = source.indexOf(first), end = source.indexOf(next, start);
  assert.ok(start >= 0 && end > start, first);
  return source.slice(start, end);
}
function quote(fields = {}) {
  return {eligible: true, reasons: [], product_cny: '700', offer: {
    offer_id: 'offer', stock: 'in_stock', collection_state: 'current',
    fetched_at: new Date(START).toISOString(), source_code: 'mock', source_name: 'Mock',
    url:'https://shop.example/products/jersey?variant=m', price: {amount: '100', currency: 'USD'}, shipping_to_china: {status: 'yes'},
    china_issued_card: {status: 'yes'}, ...fields,
  }};
}
function harness() {
  let now = START, timer, confirmCalls = 0, rendered = 0, panel = '', closed = 0;
  const elements = new Map(), listeners = new Map();
  const cardNodes = [], offerNodes = [];
  class MockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  }
  const context = vm.createContext({
    Date: MockDate, URL, referenceOffers:new Map(), guideContext: null, currentProduct: null, detailSequence: 0,
    guideStep: 0, items: [], fx: {}, currentIndex: 0, activeTab: 'products',
    gallery: {querySelectorAll: () => cardNodes},
    document: {getElementById: id => elements.get(id) || null, querySelectorAll: selector => selector === '.offer' ? offerNodes : []},
    window: {BIKEHUNT_PAGES: true, addEventListener(type, listener) { if (!listeners.has(type)) listeners.set(type, []); listeners.get(type).push(listener); },
      confirm() { confirmCalls++; return false; }},
    setInterval(callback) { timer = callback; return 1; }, clearInterval() {},
    e: x => String(x ?? ''), safeUrl: x => x || '', timeText: x => x || '',
    money: x => String(x), cny: x => String(x), tag: () => '', landedCostMarkup: () => '',
    render() { rendered++; }, updateFxLabel() {},
    closeSheet() { closed++; context.guideContext = null; context.currentProduct = null; context.detailSequence++; elements.delete('variant'); },
    openPanel(title, content) { context.detailSequence++; panel = title + ' ' + content; elements.delete('variant'); },
    getJson: async () => ({documents: []}),
    refreshCatalogSilently: async () => {}, loadDetail() {},
    PURCHASE_DISCLAIMER: 'test disclaimer', saveBrowseState() {},
  });
  vm.runInContext(section(gallery, 'function inventoryVerified(', 'async function loadDetail('), context);
  vm.runInContext(section(flows, 'async function startGuide(', 'const GUIDE_ICONS='), context);
  vm.runInContext(section(flows, 'function renderGuide(', 'function browseSettings('), context);
  vm.runInContext(section(flows, 'function guardPurchaseExit(', "document.addEventListener('click',guardPurchaseExit)"), context);
  vm.runInContext(flows.slice(flows.indexOf('function showInventoryInvalidated(')), context);
  return {context, elements, cardNodes, offerNodes, metadata(detail) { for (const callback of listeners.get('bikehunt-verification') || []) callback({detail}); }, setNow(value) { now = value; }, poll() { timer(); },
    get panel() { return panel; }, get closed() { return closed; },
    get rendered() { return rendered; }, get confirmCalls() { return confirmCalls; }};
}
function event(type = 'click', button = 0) {
  return {type, button, prevented: false, target: {closest: () => ({getAttribute: () => 'https://shop.example/products/jersey?variant=m'})},
    preventDefault() { this.prevented = true; }};
}

function testGalleryStockBoundariesAndLabels() {
  const h = harness();
  for (const [timestamp, available] of [
    [new Date(START - 3600000).toISOString(), true],
    [new Date(START - 3600001).toISOString(), false],
    [new Date(START + 1).toISOString(), false],
    [null, false], ['2026-10-14', false], ['2026-10-14T12:00:00', false],
    ['2026-02-30T12:00:00Z', false], ['2026-10-14T20:00:00+08:00', true],
  ]) assert.equal(h.context.offerAvailable(quote({fetched_at: timestamp})), available, timestamp);
  for (const fields of [{stock: 'out_of_stock'}, {collection_state: 'retained'},
    {price_valid_until: '2026-10-13'}, {price_valid_until: '2026-02-30'}]) {
    assert.equal(h.context.offerAvailable(quote(fields)), false);
  }
  const stale = quote({fetched_at: new Date(START - 3600001).toISOString()});
  const html = h.context.offerMarkup(stale);
  assert.ok(html.includes('库存待核实'));
  assert.ok(html.includes('disabled'));
  assert.ok(!html.includes('推荐渠道'));
  assert.ok(!html.includes('有库存'));
  assert.ok(!html.includes('已售罄'));
  assert.equal(h.context.inventoryLabel(quote({stock: 'out_of_stock'}).offer), '已售罄');
}

function testClockTimerInvalidatesOpenSelectionAndGuide() {
  for (const isGuide of [false, true]) {
    const h = harness(), q = quote();
    h.context.items = [{product_id: 'p', stock_state: 'in_stock', fetched_at: q.offer.fetched_at,
      reference_stock: 'in_stock', available_sizes: ['M'], recommended_total_cny: '700'}];
    h.context.currentProduct = {variant_id: 'v', variants: [{variant_id: 'v', in_stock: true}], offers: [q]};
    if (isGuide) h.context.guideContext = {quote: q};
    else h.elements.set('variant', {value: 'v'});
    h.setNow(START + 3600000); h.poll();
    assert.equal(h.closed, 0, 'Exact one-hour boundary stays available');
    h.setNow(START + 3600001); h.poll();
    assert.equal(h.context.guideContext, null);
    assert.equal(h.context.currentProduct, null);
    assert.ok(h.panel.includes('库存待核实'));
    assert.ok(!h.panel.includes('已售罄'));
    assert.equal(h.context.items[0].stock_state, 'unknown');
    assert.equal(h.context.items[0].available_sizes.length, 0);
    assert.equal(h.context.items[0].recommended_total_cny, null);
    assert.equal(h.rendered, 1);
    h.poll();
    assert.equal(h.rendered, 1, 'Repeated timer does not render unchanged expiry again');
  }
}

function testPurchaseDisclaimerCancelContinueAndStaleConfirmation() {
  const h = harness();
  h.context.guideContext = {quote: quote()};
  const cancelled = event(); h.context.guardPurchaseExit(cancelled);
  assert.equal(cancelled.prevented, true);
  assert.notEqual(h.context.guideContext, null, 'Cancel preserves guide');
  assert.equal(h.confirmCalls, 1);
  h.context.window.confirm = () => true;
  for (const [type, button] of [['click', 0], ['auxclick', 1]]) {
    const accepted = event(type, button); h.context.guardPurchaseExit(accepted);
    assert.equal(accepted.prevented, false, 'Accept preserves normal and middle-click navigation');
  }
  h.context.window.confirm = () => { throw new Error('Right click must not prompt'); };
  h.context.guardPurchaseExit(event('auxclick', 2));
  h.context.window.confirm = () => { h.setNow(START + 3600001); return true; };
  const expiredWhileConfirming = event(); h.context.guardPurchaseExit(expiredWhileConfirming);
  assert.equal(expiredWhileConfirming.prevented, true);
  assert.equal(h.context.guideContext, null);
  assert.ok(h.panel.includes('库存待核实'));
  h.context.window.confirm = () => { throw new Error('Expired selection must not prompt'); };
  const repeated = event(); h.context.guardPurchaseExit(repeated);
  assert.equal(repeated.prevented, true);
}

async function testAsyncGuideCannotReviveExpiredOrDismissedSelection() {
  for (const dismiss of [false, true]) {
    const h = harness(), q = quote();
    let resolve;
    h.context.getJson = () => new Promise(done => { resolve = done; });
    let rendered = 0;
    h.context.renderGuide = () => rendered++;
    const work = h.context.startGuide({offers: [q]}, 'offer');
    assert.ok(h.context.guideContext, 'Pending guide participates in invalidation');
    if (dismiss) h.context.closeSheet();
    else h.setNow(START + 3600001);
    resolve({documents: []}); await work;
    assert.equal(rendered, 0);
    assert.equal(h.context.guideContext, null);
    if (!dismiss) assert.ok(h.panel.includes('库存待核实'));
  }
  const h = harness();
  h.context.guideContext = {quote: quote({fetched_at: new Date(START - 3600001).toISOString()})};
  h.context.renderGuide();
  assert.equal(h.context.guideContext, null, 'Advancing an expired guide closes stale controls');
  assert.ok(h.panel.includes('库存待核实'));
}

function verificationFor(q, timestamp) {
  return {offers: {[q.offer.offer_id]: {content_sha256: q.offer.verification_identity,
    fetched_at: new Date(timestamp).toISOString(), collection_state: q.offer.collection_state,
    stock: q.offer.stock, eligible: q.eligible, reasons: [...q.reasons]}},
    fx: {snapshot_id: 'fx', fetched_at: new Date(timestamp).toISOString(), stale: false}};
}
function prepareOpenSelection(h, withGuide) {
  const q = quote({verification_identity: 'a'.repeat(64)});
  q.landed_cost = {components: [{key: 'product', evidence: [{checked_on: '2026-10-14'}]},
    {key: 'shipping', evidence: [{checked_on: '2026-10-01'}]}]};
  const detail = {product_id: 'p', variant_id: 'v', variants: [{variant_id: 'v', in_stock: true}],
    offers: [q], fx: {snapshot_id: 'fx', fetched_at: q.offer.fetched_at, stale: false}};
  const card = {product_id: 'p', stock_state: 'in_stock', fetched_at: q.offer.fetched_at,
    reference_offer_id: 'offer', reference_verification_identity: q.offer.verification_identity,
    reference_stock: 'in_stock', reference_collection_state: 'current', available_sizes: ['M'], recommended_total_cny: '700'};
  h.context.items = [card]; h.context.currentProduct = detail; h.context.fx = structuredClone(detail.fx);
  const cardLabel = {}, offerLabel = {}, guideLabel = {};
  h.cardNodes.push({dataset: {id: 'p'}, querySelector: selector => selector === '.data-time' ? cardLabel : null});
  h.offerNodes.push({querySelector: selector => selector === '[data-offer]' ? {dataset: {offer: 'offer'}} : selector === '.source-time' ? offerLabel : null});
  h.elements.set('variant', {value: 'v'});
  if (withGuide) { h.context.guideContext = {detail, quote: q}; h.elements.set('guideObservation', guideLabel); }
  return {q, detail, card, cardLabel, offerLabel, guideLabel};
}
function testVerifiedHeartbeatPreservesOpenSelectionAndGuideWithoutRendering() {
  for (const withGuide of [false, true]) {
    const h = harness(), ui = prepareOpenSelection(h, withGuide);
    const existingGuide = h.context.guideContext;
    h.setNow(START + 1800000); h.metadata(verificationFor(ui.q, START + 1800000));
    const renewed = new Date(START + 1800000).toISOString();
    assert.equal(ui.q.offer.fetched_at, renewed); assert.equal(ui.card.fetched_at, renewed);
    assert.equal(ui.detail.fx.fetched_at, renewed); assert.equal(h.context.fx.fetched_at, renewed);
    assert.equal(h.context.currentProduct, ui.detail, 'Metadata update preserves the selected detail object');
    assert.equal(h.context.guideContext, existingGuide, 'Metadata update preserves the active guide and step');
    assert.equal(h.elements.get('variant').value, 'v');
    assert.ok(ui.cardLabel.textContent.includes(renewed)); assert.ok(ui.offerLabel.textContent.includes(renewed));
    if (withGuide) assert.equal(ui.guideLabel.textContent, renewed);
    assert.equal(h.rendered, 0); assert.equal(h.closed, 0, 'Healthy verification does not close dialogs');
    h.setNow(START + 3600001); h.poll();
    assert.equal(h.closed, 0); assert.equal(h.context.currentProduct, ui.detail, 'Original clock expiry must not invalidate a genuinely renewed selection');
    assert.equal(h.context.offerAvailable(ui.q), true);
    h.setNow(START + 1800000 + 3600001); h.poll();
    assert.equal(h.context.guideContext, null); assert.equal(h.context.currentProduct, null);
    assert.equal(h.rendered, 1, 'Without another genuine recheck, offline stock expiry still invalidates confirmed-stock controls');
  }
}
function testMetadataRejectsWrongIdentityAndChangedSafety() {
  const mutations = [
    data => { data.offers.offer.content_sha256 = 'b'.repeat(64); },
    data => { data.offers.offer.stock = 'out_of_stock'; },
    data => { data.offers.offer.collection_state = 'retained'; },
    data => { data.offers.offer.eligible = false; },
    data => { data.offers.offer.reasons = ['Shipping newly unavailable']; },
    data => { data.offers.offer.fetched_at = new Date(START - 1).toISOString(); },
    data => { data.offers.offer.fetched_at = new Date(START + 1800001).toISOString(); },
  ];
  for (const mutate of mutations) {
    const h = harness(), ui = prepareOpenSelection(h, true), proof = verificationFor(ui.q, START + 1800000);
    h.setNow(START + 1800000); mutate(proof); h.metadata(proof);
    assert.equal(ui.q.offer.fetched_at, new Date(START).toISOString());
    assert.equal(h.rendered, 0); assert.equal(h.closed, 0);
  }
  const legacy = harness(), old = prepareOpenSelection(legacy, true), proof = verificationFor(old.q, START + 1800000);
  delete old.q.offer.verification_identity; delete old.card.reference_verification_identity;
  legacy.setNow(START + 1800000); legacy.metadata(proof);
  assert.equal(old.q.offer.fetched_at, new Date(START).toISOString(), 'Legacy/unbound copies cannot accept status overlays');
  assert.equal(old.card.fetched_at, new Date(START).toISOString());
}
function testMetadataCannotReviveExpiredOrDismissedGuide() {
  for (const dismissed of [false, true]) {
    const h = harness(), ui = prepareOpenSelection(h, true), proof = verificationFor(ui.q, START + 3600001);
    if (dismissed) h.context.closeSheet();
    h.setNow(START + 3600001); h.metadata(proof);
    assert.equal(ui.q.offer.fetched_at, new Date(START).toISOString(), 'An expired quote cannot be silently rejuvenated inside an existing guide');
    if (!dismissed) h.poll();
    assert.equal(h.context.guideContext, null); assert.equal(h.context.currentProduct, null);
  }
}
async function testPendingGuideReceivesIdentityBoundHeartbeatWithoutResurrection() {
  for (const dismiss of [false, true]) {
    const h = harness(), ui = prepareOpenSelection(h, false);
    let resolve, renders = 0; h.context.getJson = () => new Promise(done => { resolve = done; });
    h.context.renderGuide = () => renders++;
    const pending = h.context.startGuide(ui.detail, 'offer');
    if (dismiss) h.context.closeSheet();
    h.setNow(START + 1800000); h.metadata(verificationFor(ui.q, START + 1800000));
    h.setNow(START + 3600001); resolve({documents: []}); await pending;
    if (dismiss) { assert.equal(h.context.guideContext, null); assert.equal(renders, 0); }
    else {
      assert.equal(renders, 1); assert.equal(h.context.guideContext.quote, ui.q);
      assert.equal(h.context.offerAvailable(ui.q), true, 'The async guide captured the same safely updated quote object');
      assert.equal(ui.q.offer.fetched_at, new Date(START + 1800000).toISOString());
    }
  }
}

(async () => {
  for (const test of [testGalleryStockBoundariesAndLabels, testClockTimerInvalidatesOpenSelectionAndGuide,
    testPurchaseDisclaimerCancelContinueAndStaleConfirmation, testAsyncGuideCannotReviveExpiredOrDismissedSelection,
    testVerifiedHeartbeatPreservesOpenSelectionAndGuideWithoutRendering, testMetadataRejectsWrongIdentityAndChangedSafety,
    testMetadataCannotReviveExpiredOrDismissedGuide, testPendingGuideReceivesIdentityBoundHeartbeatWithoutResurrection]) {
    await test(); console.log('PASS ' + test.name);
  }
  console.log('Stock guards: 8 production-JavaScript regression groups passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
