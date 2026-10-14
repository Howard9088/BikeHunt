'use strict';

// Independent Pages regression: node scripts/test_pages_freshness.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/pages-adapter.js'), 'utf8');
const START = Date.parse('2026-10-14T12:00:00Z');

function snapshot() {
  const fx = {
    snapshot_id: 'fx-mock', rate_date: '2026-10-14',
    fetched_at: new Date(START).toISOString(), rates: {CNY: '1', EUR: '7.5'}, stale: false,
  };
  const colors = [
    {product_id: 'red', color: '红色', in_stock: true},
    {product_id: 'blue', color: '蓝色', in_stock: true},
  ];
  const details = {};
  const cards = [];
  for (const productId of ['red', 'blue']) {
    const variantId = productId + '-M';
    const eligible = productId === 'red';
    const offer = {
      offer_id: productId + '-offer', stock: 'in_stock',
      fetched_at: new Date(START).toISOString(), price_valid_until: null,
      url: 'https://merchant.example/' + productId,
    };
    details[productId] = {default: variantId, variants: {[variantId]: {
      product_id: productId, variant_id: variantId, category: 'jerseys',
      variants: [{variant_id: variantId, size: 'M', in_stock: true}],
      colors: structuredClone(colors), fx: structuredClone(fx),
      offers: [{offer, eligible, reasons: eligible ? [] : ['中国运费待确认']}],
      recommended_offer_id: eligible ? offer.offer_id : null,
    }}};
    cards.push({product_id: productId, name: productId, name_zh: productId, brand: 'Mock',
      category: 'jerseys', stock_state: 'in_stock', available_sizes: ['M'],
      recommended_total_cny: eligible ? '120.00' : null,
      status: eligible ? '公开条件与费用已齐' : '渠道待核实'});
  }
  return {
    generated_at: new Date(START).toISOString(),
    catalog: {items: cards, fx: structuredClone(fx)}, details,
    updates: {cursor: 10, items: [{id: 9}, {id: 10}], fx: structuredClone(fx)},
    directories: {brands: [], teams: [{logo_images: ['/web/assets/teams/mock.png']}]},
    rules: {}, fit_charts: [], community: {available: false},
  };
}

async function harness(payload = snapshot()) {
  let now = START;
  let publication = structuredClone(payload);
  let poll;
  const calls = [];
  const events = [];
  class MockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  }
  const context = vm.createContext({
    URL, Response, Date: MockDate,
    location: {href: 'https://owner.github.io/BikeHunt/'},
    document: {currentScript: {src: 'https://owner.github.io/BikeHunt/web/pages-adapter.js'}},
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    window: {
      fetch: async (input, init) => {
        const url = String(input);
        calls.push({url, init});
        if (url.includes('/data/site-data.json')) {
          return new Response(JSON.stringify(publication), {headers: {'Content-Type': 'application/json'}});
        }
        return new Response('external request');
      },
      addEventListener() {},
      dispatchEvent(event) { events.push(event); },
    },
    setInterval(callback) { poll = callback; return 1; },
    clearInterval() {},
  });
  vm.runInContext(source, context, {filename: 'pages-adapter.js'});
  await context.loadPublished();
  await Promise.resolve();
  return {
    context, calls, events,
    setNow(value) { now = value; },
    publish(value) { publication = structuredClone(value); },
    async request(url) {
      const response = await context.window.fetch(url);
      assert.equal(response.status, 200);
      return response.json();
    },
    async poll() { await poll(); },
  };
}

async function testCachedApiRechecksFxAndEligibility() {
  const h = await harness();
  assert.equal((await h.request(new URL('https://owner.github.io/api/fx'))).stale, false);
  h.setNow(START + 3600000);
  assert.equal((await h.request('/api/fx')).stale, false, 'Exactly one hour remains valid');
  const reads = h.calls.length;
  h.setNow(START + 3600001);
  assert.equal((await h.request('/api/fx')).stale, true);
  assert.equal(h.calls.length, reads, 'Cached API calls must recheck without a network request');
  assert.equal((await h.request('/api/updates')).fx.stale, true);
  const detail = await h.request('/api/catalog/red?variant_id=red-M');
  assert.equal(detail.fx.stale, true);
  assert.equal(detail.offers[0].eligible, false);
  assert.equal(detail.recommended_offer_id, null);
  assert.ok(detail.offers[0].reasons.includes('汇率为过期缓存'));
  const catalog = await h.request('/api/catalog');
  assert.equal(catalog.items[0].recommended_total_cny, null);
  h.setNow(START);
  const repeat = await h.request('/api/catalog/red');
  assert.equal(repeat.offers[0].eligible, false, 'A repeated refresh must not restore false eligibility');
  assert.equal(repeat.recommended_offer_id, null);
  assert.equal(repeat.offers[0].reasons.filter(x => x === '汇率为过期缓存').length, 1);
  assert.equal((await h.request('/api/catalog/blue')).offers[0].eligible, false);
  const response = await h.context.window.fetch(new URL('https://merchant.example/shop'));
  assert.equal(await response.text(), 'external request', 'URL inputs still preserve external fetches');
}

async function testFxAgeDateAndTimezoneBoundaries() {
  const cases = [
    ['future 300 seconds', {fetched_at: new Date(START + 300000).toISOString()}, false],
    ['future over 300 seconds', {fetched_at: new Date(START + 300001).toISOString()}, true],
    ['seven day rate', {rate_date: '2026-10-07'}, false],
    ['eight day rate', {rate_date: '2026-10-06'}, true],
    ['future rate date', {rate_date: '2026-10-15'}, true],
    ['invalid calendar date', {rate_date: '2026-02-30'}, true],
    ['missing timestamp', {fetched_at: null}, true],
    ['missing timezone', {fetched_at: '2026-10-14T12:00:00'}, true],
    ['declared stale cache', {stale: true}, true],
  ];
  for (const [label, fields, expected] of cases) {
    const data = snapshot();
    Object.assign(data.catalog.fx, fields);
    const h = await harness(data);
    assert.equal((await h.request('/api/fx')).stale, expected, label);
    assert.equal((await h.request('/api/updates')).fx.stale, expected, label + ' propagates to updates');
    assert.equal((await h.request('/api/catalog/red')).fx.stale, expected, label + ' propagates to details');
  }
}

async function testInventoryAndColorsExpireTogether() {
  const h = await harness();
  h.setNow(START + 86400000);
  let detail = await h.request('/api/catalog/red');
  assert.equal(detail.variants[0].in_stock, true, 'Quote exactly 24 hours old remains available');
  h.setNow(START + 86400001);
  detail = await h.request('/api/catalog/red');
  assert.equal(detail.variants[0].in_stock, false);
  assert.equal(detail.colors.every(color => color.in_stock === false), true);
  assert.ok(detail.offers[0].reasons.includes('报价已过期'));
  const catalog = await h.request('/api/catalog');
  assert.deepEqual(catalog.items[0].available_sizes, []);
  assert.equal(catalog.items[0].stock_state, 'unknown');
  const data = snapshot();
  data.details.blue.variants['blue-M'].offers[0].offer.fetched_at = new Date(START - 86400001).toISOString();
  const mixed = await harness(data);
  const colors = (await mixed.request('/api/catalog/red')).colors;
  assert.deepEqual(colors.map(color => color.in_stock), [true, false], 'Other colors use their own families');
}

async function testSamePublicationNotifiesOnFreshnessChanges() {
  const h = await harness();
  await h.poll();
  assert.equal(h.events.length, 0, 'Unchanged publication and freshness remain quiet');
  h.setNow(START + 3600001);
  await h.request('/api/catalog');
  await h.poll();
  assert.equal(h.events.length, 1, 'A cached API check does not consume the poll notification');
  assert.equal(h.events[0].type, 'bikehunt-published');
  assert.equal(h.events[0].detail.freshnessChanged, true);
  assert.equal(h.events[0].detail.events.length, 0);
  await h.poll();
  assert.equal(h.events.length, 1, 'Repeated expired snapshots do not generate repeated alerts');
  h.setNow(START + 86400001);
  await h.poll();
  assert.equal(h.events.length, 2, 'Inventory expiry also notifies without a new generated_at');
  assert.equal(h.events[1].detail.freshnessChanged, true);
}

async function testPublicationCursorNeverMovesBackwards() {
  const h = await harness();
  const older = snapshot();
  older.generated_at = new Date(START + 1000).toISOString();
  older.updates.cursor = 5;
  older.updates.items = [{id: 4}, {id: 5}];
  h.publish(older);
  await h.poll();
  assert.equal(vm.runInContext('publishedCursor', h.context), 10);
  assert.equal(h.events[0].detail.events.length, 0);
  const newer = snapshot();
  newer.generated_at = new Date(START + 2000).toISOString();
  newer.updates.cursor = 11;
  newer.updates.items = [{id: 9}, {id: 10}, {id: 11}];
  h.publish(newer);
  await h.poll();
  assert.equal(vm.runInContext('publishedCursor', h.context), 11);
  assert.deepEqual(h.events[1].detail.events.map(event => event.id), [11]);
}

async function testSoldOutAndFailedRefreshInvalidateActions() {
  const h = await harness();
  const changed = snapshot();
  changed.details.red.variants['red-M'].offers[0].offer.stock = 'out_of_stock';
  changed.details.blue.variants['blue-M'].offers[0].offer.collection_state = 'retained';
  h.publish(changed);
  await h.poll();
  const red = await h.request('/api/catalog/red');
  const blue = await h.request('/api/catalog/blue');
  assert.equal(red.variants[0].stock_state, 'out_of_stock');
  assert.equal(red.variants[0].in_stock, false);
  assert.equal(red.offers[0].eligible, false);
  assert.equal(red.recommended_offer_id, null);
  assert.equal(blue.variants[0].stock_state, 'unknown');
  assert.equal(blue.variants[0].in_stock, false);
  assert.equal(blue.offers[0].eligible, false);
  assert.ok(blue.offers[0].reasons.some(x => x.includes('最近采集失败')));
  const cards = (await h.request('/api/catalog')).items;
  assert.equal(cards[0].stock_state, 'out_of_stock');
  assert.equal(cards[1].stock_state, 'unknown');
  assert.ok(h.events.some(x => x.detail.freshnessChanged), 'Refresh invalidates open purchase flows even without event IDs');
}

async function main() {
  for (const test of [testCachedApiRechecksFxAndEligibility, testFxAgeDateAndTimezoneBoundaries,
    testInventoryAndColorsExpireTogether, testSamePublicationNotifiesOnFreshnessChanges,
    testPublicationCursorNeverMovesBackwards, testSoldOutAndFailedRefreshInvalidateActions]) {
    await test();
    console.log('PASS ' + test.name);
  }
  console.log('Pages freshness: 6 regression groups passed.');
}

main().catch(error => { console.error(error); process.exitCode = 1; });

