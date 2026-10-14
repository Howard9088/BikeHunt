'use strict';

// Independent Pages regression: node scripts/test_pages_freshness.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash, webcrypto} = require('node:crypto');

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

function publication(payload) {
  const data = structuredClone(payload);
  data.publication = {...data.publication, commit: data.publication?.commit ?? 'commit-test',
    version: (data.publication?.commit ?? 'commit-test') + ':' + data.generated_at};
  const body = JSON.stringify(data);
  const manifest = {schema_version: 1, version: data.publication.version,
    generated_at: data.generated_at, commit: data.publication.commit,
    snapshot: {path: 'data/site-data.json', bytes: Buffer.byteLength(body),
      sha256: createHash('sha256').update(body).digest('hex')}};
  return {body, manifest};
}

async function harness(payload = snapshot(), options = {}) {
  let now = START;
  let published = publication(payload);
  let manifest = options.manifest ?? published.manifest;
  let body = options.body ?? published.body;
  let poll;
  let offline = options.offline ?? false;
  let manifestGate = null, snapshotGate = null;
  let manifestStatus = 200, snapshotStatus = 200;
  const marker = {};
  const calls = [];
  const events = [];
  class MockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  }
  const context = vm.createContext({
    URL, Response, Date: MockDate, crypto: webcrypto, TextDecoder,
    location: {href: 'https://owner.github.io/BikeHunt/'},
    document: {currentScript: {src: 'https://owner.github.io/BikeHunt/web/pages-adapter.js',dataset:{release:'commit-test'}},
      getElementById(id) { return id === 'publicationInfo' ? marker : null; }},
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    window: {
      fetch: async (input, init) => {
        const url = String(input);
        calls.push({url, init});
        if (url.includes('/data/publication.json')) {
          if (offline) throw new Error('offline');
          const captured = JSON.stringify(manifest);
          if (manifestGate) await manifestGate;
          if (options.onManifestRead) options.onManifestRead(calls.filter(c => c.url.includes('/data/publication.json')).length, value => { published = publication(value); manifest = published.manifest; body = published.body; });
          return new Response(captured, {status: manifestStatus, headers: {'Content-Type': 'application/json'}});
        }
        if (url.includes('/data/site-data.json')) {
          if (offline) throw new Error('offline');
          // Model an old browser-cached stable alias. Only the cache-busted,
          // no-store request may see the currently published response.
          const captured = options.cachedBody && (!new URL(url).searchParams.has('v') || init?.cache !== 'no-store') ? options.cachedBody : body;
          if (snapshotGate) await snapshotGate;
          return new Response(captured, {status: snapshotStatus, headers: {'Content-Type': 'application/json'}});
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
  let initialError;
  try { await context.loadPublished(); } catch (error) {
    initialError = error;
    if (!options.expectInitialFailure) throw error;
  }
  await Promise.resolve();
  return {
    context, calls, events, marker, initialError,
    setNow(value) { now = value; },
    publish(value) { published = publication(value); manifest = published.manifest; body = published.body; },
    setManifest(value) { manifest = structuredClone(value); },
    setBody(value) { body = value; },
    setOffline(value) { offline = value; },
    setManifestGate(value) { manifestGate = value; },
    setSnapshotGate(value) { snapshotGate = value; },
    setManifestStatus(value) { manifestStatus = value; },
    setSnapshotStatus(value) { snapshotStatus = value; },
    manifestReads() { return calls.filter(c => c.url.includes('/data/publication.json')); },
    snapshotReads() { return calls.filter(c => c.url.includes('/data/site-data.json')); },
    async request(url) {
      const response = await context.window.fetch(url);
      assert.equal(response.status, 200);
      return response.json();
    },
    async poll() { await poll(); },
  };
}

async function testInitialSnapshotBypassesBrowserCache() {
  const stale=snapshot();stale.generated_at=new Date(START-60000).toISOString();
  const h=await harness(snapshot(),{cachedBody:publication(stale).body});
  assert.equal(h.manifestReads().length,1);
  assert.equal(h.calls[0].url,h.manifestReads()[0].url,'Initial load checks manifest before any full snapshot');
  assert.equal(h.manifestReads()[0].init.cache,'no-store');
  const first=h.calls.find(c=>c.url.includes('/data/site-data.json'));
  assert.equal(first.init.cache,'no-store');
  assert.equal(new URL(first.url).searchParams.get('release'),'commit-test');
  assert.equal(new URL(first.url).searchParams.get('v'),String(START));
  assert.equal(new URL(first.url).searchParams.get('version'),publication(snapshot()).manifest.version);
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.generated_at,new Date(START).toISOString());
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.commit,'commit-test');
  assert.equal(h.marker.textContent,'数据 commit-');
  assert.ok(h.marker.title.includes(new Date(START).toISOString()));
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
  h.setNow(START + 3600000);
  let detail = await h.request('/api/catalog/red');
  assert.equal(detail.variants[0].in_stock, true, 'Stock exactly one hour old remains available');
  h.setNow(START + 3600001);
  detail = await h.request('/api/catalog/red');
  assert.equal(detail.variants[0].in_stock, false);
  assert.equal(detail.colors.every(color => color.in_stock === false), true);
  assert.ok(detail.offers[0].reasons.includes('库存核实已过期；等待重新核实'));
  assert.ok(!detail.offers[0].reasons.includes('报价已过期'));
  assert.ok(!detail.offers[0].reasons.includes('已售罄'));
  const catalog = await h.request('/api/catalog');
  assert.deepEqual(catalog.items[0].available_sizes, []);
  assert.equal(catalog.items[0].stock_state, 'unknown');
  assert.equal(catalog.items[0].status, '库存核实已过期');
  const data = snapshot();
  data.details.blue.variants['blue-M'].offers[0].offer.fetched_at = new Date(START - 3600001).toISOString();
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
  assert.equal(h.events.length, 2, 'Historical quote expiry also notifies without a new generated_at');
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
  assert.deepEqual(Array.from(h.events[1].detail.events,event => event.id), [11]);
}

async function testSoldOutAndFailedRefreshInvalidateActions() {
  const h = await harness();
  const changed = snapshot();
  changed.generated_at = new Date(START + 1000).toISOString();
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

async function testStockTimestampBoundariesFailClosed() {
  const cases = [
    ['exact hour', new Date(START - 3600000).toISOString(), true],
    ['past hour', new Date(START - 3600001).toISOString(), false],
    ['missing', null, false],
    ['date only', '2026-10-14', false],
    ['missing timezone', '2026-10-14T12:00:00', false],
    ['future', new Date(START + 1).toISOString(), false],
    ['invalid date', '2026-02-30T12:00:00Z', false],
    ['explicit offset', '2026-10-14T20:00:00+08:00', true],
  ];
  for (const [label, timestamp, expected] of cases) {
    const data = snapshot();
    data.details.red.variants['red-M'].offers[0].offer.fetched_at = timestamp;
    const h = await harness(data);
    const detail = await h.request('/api/catalog/red');
    assert.equal(detail.variants[0].in_stock, expected, label);
    assert.equal(detail.offers[0].eligible, expected, label + ' eligibility');
    assert.equal(detail.colors[0].in_stock, expected, label + ' colors');
  }
}

async function testOfflinePollStillExpiresStock() {
  const h = await harness();
  h.setOffline(true);
  h.setNow(START + 3600001);
  await h.poll();
  assert.equal(h.events.length, 1, 'Offline clock expiry must still notify open dialogs');
  assert.equal(h.events[0].detail.freshnessChanged, true);
  const cached = vm.runInContext('publicLastData', h.context);
  assert.equal(cached.details.red.variants['red-M'].variants[0].in_stock, false);
  assert.equal(cached.catalog.items[0].stock_state, 'unknown');
  assert.equal(cached.catalog.items[0].status, '库存核实已过期');
  await h.poll();
  assert.equal(h.events.length, 1, 'Repeated offline polls remain quiet');
}

async function testUnchangedManifestAvoidsFullSnapshotTransfers() {
  const h = await harness();
  for (let i = 1; i <= 3; i++) {
    h.setNow(START + i * 60000);
    await h.poll();
  }
  const manual = await h.request('/api/refresh/prices');
  assert.equal(manual.finished_at, new Date(START).toISOString());
  assert.equal(h.manifestReads().length, 5, 'Initial, timer and manual checks use the tiny manifest');
  assert.equal(h.snapshotReads().length, 1, 'An unchanged publication never transfers the full snapshot again');
  assert.ok(h.manifestReads().every(c => c.init.cache === 'no-store'));
  const detail = await h.request('/api/catalog/red');
  assert.equal(detail.offers[0].offer.fetched_at, new Date(START).toISOString(), 'Polling must not reset source freshness');
  h.setNow(START + 3600001);
  await h.poll();
  assert.equal(h.snapshotReads().length, 1, 'Clock expiry still needs no new snapshot');
  assert.equal((await h.request('/api/catalog/red')).variants[0].in_stock, false);
  assert.equal(h.events.length, 1);
}

async function testNewVersionSharesOneInflightSnapshot() {
  const h = await harness();
  const changed = snapshot();
  changed.generated_at = new Date(START + 60000).toISOString();
  changed.details.red.variants['red-M'].offers[0].offer.stock = 'out_of_stock';
  h.publish(changed);
  let releaseManifest, releaseSnapshot;
  h.setManifestGate(new Promise(resolve => { releaseManifest = resolve; }));
  h.setSnapshotGate(new Promise(resolve => { releaseSnapshot = resolve; }));
  const first = h.context.loadPublished(true);
  const timer = h.poll();
  const manual = h.context.window.fetch('/api/refresh/prices');
  await Promise.resolve();
  assert.equal(h.manifestReads().length, 2, 'Timer and manual callers join the pending manifest check');
  assert.equal(h.snapshotReads().length, 1);
  assert.equal((await h.request('/api/catalog/red')).variants[0].in_stock, true, 'Cached APIs remain usable during a refresh');
  releaseManifest();
  // Let Response.json() and the manifest validation reach the snapshot request.
  for (let i = 0; i < 20 && h.snapshotReads().length < 2; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.snapshotReads().length, 2);
  const concurrent = h.context.loadPublished(true);
  assert.equal(h.manifestReads().length, 2, 'A caller during download shares the same in-flight check');
  releaseSnapshot();
  const [data, , response, shared] = await Promise.all([first, timer, manual, concurrent]);
  assert.equal(response.status, 200);
  assert.equal(data, shared);
  assert.equal(data.generated_at, changed.generated_at);
  assert.equal(h.snapshotReads().length, 2, 'Exactly one new full snapshot for a changed version');
  assert.equal((await h.request('/api/catalog/red')).variants[0].stock_state, 'out_of_stock');
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.generated_at, changed.generated_at);
  assert.ok(h.marker.title.includes(changed.generated_at));
  h.setManifestGate(null); h.setSnapshotGate(null);
  await h.poll();
  assert.equal(h.snapshotReads().length, 2);
}

async function testCdnRacesNeverCommitMismatchedSnapshots() {
  const old = snapshot(), newer = snapshot();
  newer.generated_at = new Date(START + 60000).toISOString();
  newer.details.red.variants['red-M'].offers[0].offer.stock = 'out_of_stock';
  // Both propagation directions must fail on initial load.
  for (const [manifest, body] of [
    [publication(old).manifest, publication(newer).body],
    [publication(newer).manifest, publication(old).body],
  ]) {
    const h = await harness(old, {manifest, body, expectInitialFailure: true});
    assert.match(h.initialError.message, /校验失败/);
    assert.equal(vm.runInContext('publicLastData', h.context), null);
    assert.equal(h.context.window.BIKEHUNT_PUBLICATION, undefined);
  }
  const h = await harness(old);
  h.setManifest(publication(newer).manifest); // New manifest, old CDN alias.
  await assert.rejects(h.context.loadPublished(true), /校验失败/);
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.generated_at, old.generated_at);
  assert.equal((await h.request('/api/catalog/red')).variants[0].in_stock, true);
  h.setBody(publication(newer).body);
  await h.poll(); // A failed promise must be cleared so the coherent publication can retry.
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.generated_at, newer.generated_at);
  assert.equal((await h.request('/api/catalog/red')).variants[0].in_stock, false);
}

async function testDigestAndPublicationMetadataAreBothRequired() {
  for (const field of ['generated_at', 'version', 'commit']) {
    const good = publication(snapshot());
    const data = JSON.parse(good.body);
    if (field === 'generated_at') data.generated_at = new Date(START - 1000).toISOString();
    else data.publication[field] = 'different-' + field;
    const body = JSON.stringify(data);
    const manifest = structuredClone(good.manifest);
    manifest.snapshot.bytes = Buffer.byteLength(body);
    manifest.snapshot.sha256 = createHash('sha256').update(body).digest('hex');
    const h = await harness(snapshot(), {manifest, body, expectInitialFailure: true});
    assert.match(h.initialError.message, /商品版本不一致/, field);
    assert.equal(vm.runInContext('publicLastData', h.context), null);
  }
  const good = publication(snapshot());
  // Whitespace has identical parsed JSON but different bytes; it is not the signed snapshot.
  const changedBytes = await harness(snapshot(), {body: good.body + ' ', expectInitialFailure: true});
  assert.match(changedBytes.initialError.message, /校验失败/);
  const wrongLength = structuredClone(good.manifest);
  wrongLength.snapshot.bytes++;
  const h = await harness(snapshot(), {manifest: wrongLength, expectInitialFailure: true});
  assert.match(h.initialError.message, /校验失败/);
}

async function testRollbackAndReusedVersionAreRejected() {
  const h = await harness();
  const newer = snapshot();
  newer.generated_at = new Date(START + 60000).toISOString();
  h.publish(newer);
  await h.poll();
  const before = h.snapshotReads().length;
  h.publish(snapshot());
  await assert.rejects(h.context.loadPublished(true), /早于已加载版本/);
  assert.equal(h.snapshotReads().length, before, 'Rollback is rejected before downloading another snapshot');
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.generated_at, newer.generated_at);
  const reused = publication(newer).manifest;
  reused.snapshot.sha256 = '0'.repeat(64);
  h.setManifest(reused);
  await assert.rejects(h.context.loadPublished(true), /校验信息不一致/);
  assert.equal(h.snapshotReads().length, before);
  const equalTimestamp = structuredClone(publication(newer).manifest);
  equalTimestamp.version = 'another-release';
  h.setManifest(equalTimestamp);
  await assert.rejects(h.context.loadPublished(true), /早于已加载版本/);
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.generated_at, newer.generated_at);
}

async function testManifestFailuresFailClosedAndRetry() {
  const mutations = [
    m => { m.schema_version = 2; }, m => { m.version = ''; },
    m => { m.generated_at = '2026-10-14'; },
    m => { m.generated_at = new Date(START + 300001).toISOString(); }, m => { m.commit = 123; },
    m => { m.snapshot.path = 'https://untrusted.example/data.json'; },
    m => { m.snapshot.sha256 = 'bad-digest'; }, m => { m.snapshot.bytes = -1; },
  ];
  for (const mutate of mutations) {
    const manifest = publication(snapshot()).manifest;
    mutate(manifest);
    const h = await harness(snapshot(), {manifest, expectInitialFailure: true});
    assert.match(h.initialError.message, /发布清单无效/);
    assert.equal(h.snapshotReads().length, 0);
  }
  const h = await harness(snapshot(), {offline: true, expectInitialFailure: true});
  assert.equal(h.snapshotReads().length, 0);
  assert.equal((await h.context.window.fetch('/api/catalog')).status, 503);
  h.setOffline(false);
  assert.equal((await h.request('/api/catalog')).items.length, 2);
  const newer = snapshot(); newer.generated_at = new Date(START + 60000).toISOString();
  h.publish(newer); h.setSnapshotStatus(503);
  await assert.rejects(h.context.loadPublished(true), /商品数据暂时无法读取/);
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.generated_at, snapshot().generated_at);
  h.setSnapshotStatus(200); h.setManifestStatus(503);
  await assert.rejects(h.context.loadPublished(true), /发布清单暂时无法读取/);
  h.setManifestStatus(200);
  await h.context.loadPublished(true);
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.generated_at, newer.generated_at);
}

async function testHungNetworkDoesNotDelayClockExpiry() {
  const h = await harness();
  let release;
  h.setManifestGate(new Promise(resolve => { release = resolve; }));
  const pending = h.poll();
  h.setNow(START + 3600001);
  const concurrent = h.poll();
  assert.equal(h.events.length, 1, 'Clock-driven expiry dispatches before the hanging network check settles');
  assert.equal((await h.request('/api/catalog/red')).variants[0].in_stock, false);
  assert.equal(h.snapshotReads().length, 1);
  release();
  await Promise.all([pending, concurrent]);
  assert.equal(h.events.length, 1);
  assert.equal(h.manifestReads().length, 2);
}

async function testInitialCdnRaceRecoversWithBoundedRetry() {
  const old = snapshot(), newer = snapshot();
  newer.generated_at = new Date(START + 60000).toISOString();
  const h = await harness(old, {
    onManifestRead(reads, publish) { if (reads === 1) publish(newer); },
  });
  assert.equal(h.manifestReads().length, 2, 'Only one extra startup manifest check');
  assert.equal(h.snapshotReads().length, 2, 'New full transfer is warranted by a newer manifest');
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.generated_at, newer.generated_at);
  const inconsistent = await harness(old, {body: publication(newer).body, expectInitialFailure: true});
  assert.match(inconsistent.initialError.message, /校验失败/);
  assert.equal(inconsistent.manifestReads().length, 2);
  assert.equal(inconsistent.snapshotReads().length, 1, 'Same manifest does not trigger an unbounded alias download loop');
  inconsistent.publish(newer);
  await inconsistent.poll();
  assert.equal(inconsistent.context.window.BIKEHUNT_PUBLICATION.generated_at, newer.generated_at);
  assert.equal(inconsistent.events.length, 1, 'Later coherent publication notifies the waiting UI');
  const future = snapshot(); future.generated_at = new Date(START + 300000).toISOString();
  assert.equal((await harness(future)).context.window.BIKEHUNT_PUBLICATION.generated_at, future.generated_at, 'Five minutes of clock skew is allowed');
}

async function testFailedUiBootResubscribesOnVerifiedPublication() {
  const flows = fs.readFileSync(path.join(__dirname, '../web/flows.js'), 'utf8');
  const fragment = flows.slice(flows.indexOf('function startFlows('), flows.indexOf('const PURCHASE_DISCLAIMER='));
  let listener, boots = 0, galleryInitializations = 0;
  const context = vm.createContext({
    window: {BIKEHUNT_PAGES: true, addEventListener(type, callback, options) {
      assert.equal(type, 'bikehunt-published'); assert.equal(options.once, true); listener = callback;
    }},
    async bootFlows() { if (++boots === 1) throw new Error('Initial publication still propagating'); },
    init() { galleryInitializations++; },
  });
  vm.runInContext(fragment, context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(boots, 1);
  assert.ok(listener, 'Recovery listener must exist even though normal flow initialization failed');
  listener();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(boots, 2);
  assert.equal(galleryInitializations, 1, 'Catalog and flow initialization both resume without a page reload');
}

async function main() {
  const tests = [testInitialSnapshotBypassesBrowserCache, testCachedApiRechecksFxAndEligibility, testFxAgeDateAndTimezoneBoundaries,
    testInventoryAndColorsExpireTogether, testSamePublicationNotifiesOnFreshnessChanges,
    testPublicationCursorNeverMovesBackwards, testSoldOutAndFailedRefreshInvalidateActions,
    testStockTimestampBoundariesFailClosed, testOfflinePollStillExpiresStock,
    testUnchangedManifestAvoidsFullSnapshotTransfers, testNewVersionSharesOneInflightSnapshot,
    testCdnRacesNeverCommitMismatchedSnapshots, testDigestAndPublicationMetadataAreBothRequired,
    testRollbackAndReusedVersionAreRejected, testManifestFailuresFailClosedAndRetry,
    testHungNetworkDoesNotDelayClockExpiry, testInitialCdnRaceRecoversWithBoundedRetry,
    testFailedUiBootResubscribesOnVerifiedPublication];
  for (const test of tests) {
    await test();
    console.log('PASS ' + test.name);
  }
  console.log('Pages freshness: ' + tests.length + ' regression groups passed.');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
