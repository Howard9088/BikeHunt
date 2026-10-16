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

function digestBytes(body) { return createHash('sha256').update(body).digest('hex'); }
function v2Publication(payload = snapshot()) {
  const data = structuredClone(payload);
  data.publication = {commit: 'commit-test'};
  data.collection_status ||= {};
  data.verification_identities = {};
  const offers = {};
  for (const family of Object.values(data.details)) for (const detail of Object.values(family.variants)) for (const quote of detail.offers) {
    const offer = quote.offer;
    offer.source_code ||= 'merchant';
    offer.collection_state ||= 'current';
    const identity = structuredClone(offer); delete identity.fetched_at;
    data.verification_identities[offer.offer_id] = digestBytes(JSON.stringify(identity));
    offers[offer.offer_id] = {content_sha256: data.verification_identities[offer.offer_id],
      fetched_at: offer.fetched_at, collection_state: offer.collection_state};
  }
  for (const card of data.catalog.items) {
    card.reference_offer_id ||= data.details[card.product_id].variants[data.details[card.product_id].default].offers[0].offer.offer_id;
    card.fetched_at = offers[card.reference_offer_id].fetched_at;
    card.reference_collection_state = offers[card.reference_offer_id].collection_state;
    card.reference_stock ||= 'in_stock';
  }
  const semantic = digestBytes(JSON.stringify(data));
  data.publication.version = 'commit-test:catalog:' + semantic;
  const body = JSON.stringify(data);
  const manifest = {schema_version: 2, version: 'commit-test:' + data.generated_at,
    generated_at: data.generated_at, commit: 'commit-test',
    snapshot: {path: 'data/site-data.json', bytes: Buffer.byteLength(body), sha256: digestBytes(body),
      version: data.publication.version, generated_at: data.generated_at, commit: 'commit-test', semantic_sha256: semantic}};
  const status = {schema_version: 1, version: manifest.version, generated_at: manifest.generated_at,
    commit: manifest.commit, snapshot_sha256: manifest.snapshot.sha256, offers,
    fx: {snapshot_id: data.catalog.fx.snapshot_id, fetched_at: data.catalog.fx.fetched_at, stale: data.catalog.fx.stale},
    collection_status: structuredClone(data.collection_status)};
  return bindStatus({body, manifest}, status);
}
function bindStatus(release, status) {
  release = structuredClone(release);
  release.statusBody = JSON.stringify(status);
  release.manifest.status = {path: 'data/verification.json', bytes: Buffer.byteLength(release.statusBody), sha256: digestBytes(release.statusBody)};
  return release;
}
function heartbeat(release, timestamp, mutate = () => {}) {
  const next = structuredClone(release), status = JSON.parse(release.statusBody);
  next.manifest.generated_at = new Date(timestamp).toISOString();
  next.manifest.version = next.manifest.commit + ':' + next.manifest.generated_at;
  status.generated_at = next.manifest.generated_at; status.version = next.manifest.version;
  for (const observation of Object.values(status.offers)) if (observation.collection_state === 'current') observation.fetched_at = status.generated_at;
  status.fx.fetched_at = status.generated_at;
  mutate(status, next);
  return bindStatus(next, status);
}

async function harness(payload = snapshot(), options = {}) {
  let now = options.now ?? START;
  let published = options.release ?? publication(payload);
  let manifest = options.manifest ?? published.manifest;
  let body = options.body ?? published.body;
  let statusBody = options.statusBody ?? published.statusBody;
  let poll;
  let offline = options.offline ?? false;
  let manifestGate = null, snapshotGate = null, statusGate = null;
  let manifestStatus = 200, snapshotStatus = 200, verificationStatus = 200;
  const marker = {};
  const calls = [];
  const events = [];
  const verificationEvents = [];
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
        if (url.includes('/data/verification.json')) {
          if (offline) throw new Error('offline');
          const captured = statusBody;
          if (statusGate) await statusGate;
          return new Response(captured, {status: verificationStatus, headers: {'Content-Type': 'application/json'}});
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
      dispatchEvent(event) { (event.type === 'bikehunt-verification' ? verificationEvents : events).push(event); },
    },
    setInterval(callback) { poll = callback; return 1; },
    clearInterval() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/public-visibility.js'), 'utf8'), context);
  vm.runInContext(source, context, {filename: 'pages-adapter.js'});
  let initialError;
  try { await context.loadPublished(); } catch (error) {
    initialError = error;
    if (!options.expectInitialFailure) throw error;
  }
  await Promise.resolve();
  return {
    context, calls, events, verificationEvents, marker, initialError,
    setNow(value) { now = value; },
    publish(value) { published = publication(value); manifest = published.manifest; body = published.body; },
    setRelease(value) { published = structuredClone(value); manifest = published.manifest; body = published.body; statusBody = published.statusBody; },
    setManifest(value) { manifest = structuredClone(value); },
    setStatusBody(value) { statusBody = value; },
    setStatusGate(value) { statusGate = value; },
    setVerificationStatus(value) { verificationStatus = value; },
    setBody(value) { body = value; },
    setOffline(value) { offline = value; },
    setManifestGate(value) { manifestGate = value; },
    setSnapshotGate(value) { snapshotGate = value; },
    setManifestStatus(value) { manifestStatus = value; },
    setSnapshotStatus(value) { snapshotStatus = value; },
    manifestReads() { return calls.filter(c => c.url.includes('/data/publication.json')); },
    snapshotReads() { return calls.filter(c => c.url.includes('/data/site-data.json')); },
    statusReads() { return calls.filter(c => c.url.includes('/data/verification.json')); },
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
  assert.equal(h.marker.textContent,'数据更新时间');
  assert.ok(!h.marker.title.includes('commit-'));
  assert.ok(h.marker.title.includes(new Date(START).toISOString()));
}

async function testCachedApiRechecksFxAndEligibility() {
  const h = await harness();
  assert.equal((await h.request(new URL('https://owner.github.io/api/fx'))).stale, false);
  h.setNow(START + 86400000);
  assert.equal((await h.request('/api/fx')).stale, false, 'Exactly 24 hours remains valid');
  const reads = h.calls.length;
  h.setNow(START + 86400001);
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
    ['hourly recheck due is not stale', {fetched_at: new Date(START - 3600001).toISOString()}, false],
    ['daily validity exceeded', {fetched_at: new Date(START - 86400001).toISOString()}, true],
    ['China midnight keeps UTC reference valid', {fetched_at: '2026-10-14T02:00:00+08:00', rate_date: '2026-10-13'}, false],
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

async function testSchema2HeartbeatUsesOnlyStatusAndStaysQuiet() {
  const initial = v2Publication(), h = await harness(snapshot(), {release: initial});
  assert.equal(h.snapshotReads().length, 1); assert.equal(h.statusReads().length, 1);
  assert.equal(h.calls[0].url, h.manifestReads()[0].url);
  await h.poll();
  assert.equal(h.statusReads().length, 1, 'An unchanged proof needs only the manifest check');
  const next = heartbeat(initial, START + 60000);
  h.setNow(START + 60000); h.setRelease(next); await h.poll();
  assert.equal(h.snapshotReads().length, 1, 'A verified heartbeat reuses the original full catalog');
  assert.equal(h.statusReads().length, 2);
  assert.equal(h.events.length, 0, 'Metadata-only proof must not rerender catalog or open purchase dialogs');
  assert.equal(h.verificationEvents.length, 1, 'Accepted source observations update existing UI copies through a separate metadata signal');
  assert.equal(h.verificationEvents[0].detail.offers['red-offer'].content_sha256, JSON.parse(initial.statusBody).offers['red-offer'].content_sha256);
  assert.equal((await h.request('/api/catalog/red')).offers[0].offer.fetched_at, next.manifest.generated_at);
  assert.equal((await h.request('/api/catalog')).items[0].fetched_at, next.manifest.generated_at);
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.generated_at, initial.manifest.snapshot.generated_at);
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.version, initial.manifest.snapshot.version);
  assert.equal(h.context.window.BIKEHUNT_VERIFICATION.generated_at, next.manifest.generated_at);
  assert.ok(h.marker.title.includes('页面更新 ' + next.manifest.generated_at));
  const manual = await h.request('/api/refresh/prices');
  assert.equal(manual.finished_at, next.manifest.generated_at);
  assert.equal(manual.catalog_generated_at, initial.manifest.snapshot.generated_at);
  assert.equal(h.statusReads().length, 2);
  assert.ok(h.statusReads().every(call => call.init.cache === 'no-store'));
  assert.equal(new URL(h.statusReads()[1].url).searchParams.get('version'), next.manifest.version);
}

async function testSchema2HeartbeatRestoresOnlyLocallyExpiredSafety() {
  const initial = v2Publication(), h = await harness(snapshot(), {release: initial});
  h.setNow(START + 86400001); h.setOffline(true); await h.poll();
  assert.equal((await h.request('/api/catalog/red')).offers[0].eligible, false);
  assert.equal((await h.request('/api/fx')).stale, true);
  assert.equal(h.events.length, 1);
  const next = heartbeat(initial, START + 86400001);
  h.setRelease(next); h.setOffline(false); await h.poll();
  const red = await h.request('/api/catalog/red'), blue = await h.request('/api/catalog/blue');
  assert.equal(red.offers[0].eligible, true, 'A genuine newer verification restores the pristine eligible quote');
  assert.equal(red.recommended_offer_id, 'red-offer');
  assert.deepEqual(red.offers[0].reasons, []);
  assert.equal(red.variants[0].in_stock, true);
  assert.equal((await h.request('/api/catalog')).items[0].recommended_total_cny, '120.00');
  assert.equal(blue.offers[0].eligible, false, 'An unrelated shipping restriction must never be cleared');
  assert.deepEqual(blue.offers[0].reasons, ['中国运费待确认']);
  assert.equal((await h.request('/api/fx')).stale, false);
  assert.equal(h.events.length, 2); assert.equal(h.events[1].detail.freshnessChanged, true);
  assert.equal(h.verificationEvents.length, 0, 'Restored safety must use the normal invalidation path, never in-place revival');
  assert.equal(h.snapshotReads().length, 1);
  const base = vm.runInContext('publicLastBase', h.context);
  assert.equal(base.details.red.variants['red-M'].offers[0].offer.fetched_at, new Date(START).toISOString());
  assert.equal(base.details.red.variants['red-M'].offers[0].eligible, true);
  await h.poll(); assert.equal(h.events.length, 2, 'Successful same-proof polls cannot repeatedly restore or notify');
  h.setNow(START + 86400001 + 3600001); await h.poll();
  assert.equal((await h.request('/api/catalog/red')).variants[0].in_stock, false);
  assert.equal(h.events.length, 3, 'The renewed observation still expires normally');
}

async function testSchema2ExactReferenceAndEvidenceOverlay() {
  const payload = snapshot(), detail = payload.details.red.variants['red-M'];
  const extra = structuredClone(detail.offers[0]); extra.offer.offer_id = 'red-reference';
  extra.offer.url += '?variant=reference'; detail.offers.push(extra);
  payload.catalog.items[0].reference_offer_id = 'red-reference';
  for (const quote of detail.offers) {
    quote.offer.shipping_to_china = {checked_at: '2026-10-01T08:00:00Z'};
    quote.landed_cost = {components: [
      {key: 'product', evidence: [{checked_on: '2026-10-14', url: quote.offer.url}]},
      {key: 'shipping', evidence: [{checked_on: '2026-10-02'}]},
      {key: 'tax', evidence: [{checked_on: '2026-10-03'}]},
    ], evidence: [{checked_on: '2026-10-04'}]};
  }
  payload.fit_charts = [{checked_at: '2026-10-05T08:00:00Z'}];
  const initial = v2Publication(payload), h = await harness(payload, {release: initial});
  const latest = START + 86400000;
  const next = heartbeat(initial, latest, status => {
    status.offers['red-reference'].fetched_at = new Date(START + 60000).toISOString();
    status.offers['blue-offer'].fetched_at = new Date(START + 120000).toISOString();
  });
  h.setNow(latest); h.setRelease(next); await h.poll();
  const data = vm.runInContext('publicLastData', h.context), red = await h.request('/api/catalog/red');
  assert.equal(data.catalog.items[0].fetched_at, new Date(START + 60000).toISOString(), 'Reference card must use its exact offer, not freshest family offer');
  assert.equal(data.catalog.items[1].fetched_at, new Date(START + 120000).toISOString());
  assert.equal(red.offers[0].landed_cost.components[0].evidence[0].checked_on, '2026-10-15');
  assert.equal(red.offers[1].landed_cost.components[0].evidence[0].checked_on, '2026-10-14');
  assert.equal(red.offers[0].landed_cost.components[1].evidence[0].checked_on, '2026-10-02');
  assert.equal(red.offers[0].landed_cost.components[2].evidence[0].checked_on, '2026-10-03');
  assert.equal(red.offers[0].landed_cost.evidence[0].checked_on, '2026-10-04');
  assert.equal(red.offers[0].offer.shipping_to_china.checked_at, '2026-10-01T08:00:00Z');
  assert.equal(data.fit_charts[0].checked_at, '2026-10-05T08:00:00Z');
  for (const fx of [data.catalog.fx, data.updates.fx, ...Object.values(data.details).flatMap(f => Object.values(f.variants).map(d => d.fx))])
    assert.equal(fx.fetched_at, next.manifest.generated_at, 'Every repeated bound FX snapshot receives its genuine recheck time');
}

async function testSchema2DiscountReferenceMetadata() {
  const payload=snapshot(),detail=payload.details.red.variants['red-M'],quote=detail.offers[0];
  Object.assign(quote.offer,{price:{amount:'90',currency:'USD'},original_price:{amount:'120',currency:'USD'},identity:{size:'M',color:'Red'},data_kind:'live_snapshot',source_name:'Sale merchant'});quote.product_cny='630';
  const cheaper=structuredClone(quote);cheaper.offer.offer_id='red-cheaper';cheaper.offer.price.amount='50';cheaper.offer.original_price=null;cheaper.product_cny='350';detail.offers.push(cheaper);
  Object.assign(payload.catalog.items[0],{reference_offer_id:'red-offer',reference_variant_id:'red-M',reference_original_price:structuredClone(quote.offer.original_price),reference_price:structuredClone(quote.offer.price),reference_cny:'630',reference_source:'Sale merchant',reference_size:'M',reference_color:'Red',reference_price_valid_until:null,reference_data_kind:'live_snapshot'});
  const initial=v2Publication(payload),h=await harness(payload,{release:initial});
  let card=(await h.request('/api/catalog')).items[0];assert.equal(card.reference_stock,'in_stock');
  const renewed=START+1800000;h.setNow(renewed);h.setRelease(heartbeat(initial,renewed));await h.poll();
  card=(await h.request('/api/catalog')).items[0];assert.equal(card.fetched_at,new Date(renewed).toISOString());assert.equal(card.reference_original_price.amount,'120');assert.equal(card.reference_price.amount,'90');assert.equal(card.reference_cny,'630');assert.equal(card.reference_variant_id,'red-M');assert.equal(h.snapshotReads().length,1);assert.equal(h.events.length,0);
  const later=START+5460000;h.setNow(later);h.setRelease(heartbeat(initial,later,status=>{status.offers['red-offer'].fetched_at=new Date(renewed).toISOString()}));await h.poll();
  card=(await h.request('/api/catalog')).items[0];assert.equal(card.stock_state,'in_stock','A full-price offer remains freshly stocked');assert.equal(card.reference_stock,'unknown','Another fresh full-price quote cannot renew the expired discounted quote');assert.equal(card.fetched_at,new Date(renewed).toISOString());assert.equal(card.reference_original_price.amount,'120');assert.ok(h.events.some(event=>event.detail.freshnessChanged));
}

async function testSchema2NewContentAndEventsNotifyOnce() {
  const initial = v2Publication(), h = await harness(snapshot(), {release: initial});
  const payload = snapshot(); payload.generated_at = new Date(START + 60000).toISOString();
  payload.catalog.items[0].name = 'New product name';
  payload.updates.cursor = 11; payload.updates.items.push({id: 11});
  const next = v2Publication(payload); h.setRelease(next); h.setNow(START + 60000); await h.poll();
  assert.equal(h.snapshotReads().length, 2); assert.equal(h.statusReads().length, 2);
  assert.equal((await h.request('/api/catalog')).items[0].name, 'New product name');
  assert.equal(h.events.length, 1); assert.equal(h.events[0].detail.freshnessChanged, false);
  assert.equal(h.verificationEvents.length, 0, 'Catalog content changes cannot take the in-place heartbeat path');
  assert.deepEqual(Array.from(h.events[0].detail.events, event => event.id), [11]);
  await h.poll(); assert.equal(h.events.length, 1);
  h.setRelease(heartbeat(next, START + 120000)); h.setNow(START + 120000); await h.poll();
  assert.equal(h.events.length, 1, 'Heartbeat must not replay existing update events');
  assert.equal(h.snapshotReads().length, 2);
}

async function testSchema2InvalidStatusCannotCommit() {
  const mutations = [
    ['schema', s => { s.schema_version = 2; }],
    ['version', s => { s.version = 'foreign-release'; }],
    ['generated_at', s => { s.generated_at = new Date(START).toISOString(); }],
    ['commit', s => { s.commit = 'foreign-commit'; }],
    ['snapshot binding', s => { s.snapshot_sha256 = '0'.repeat(64); }],
    ['missing identity', s => { delete s.offers['blue-offer']; }],
    ['extra identity', s => { s.offers.extra = structuredClone(s.offers['red-offer']); }],
    ['wrong identity', s => { s.offers['red-offer'].content_sha256 = '0'.repeat(64); }],
    ['changed state', s => { s.offers['red-offer'].collection_state = 'retained'; }],
    ['future observation', s => { s.offers['red-offer'].fetched_at = new Date(START + 60001).toISOString(); }],
    ['observation predates baseline', s => { s.offers['red-offer'].fetched_at = new Date(START - 1).toISOString(); }],
    ['missing observation', s => { delete s.offers['red-offer'].fetched_at; }],
    ['invalid observation date', s => { s.offers['red-offer'].fetched_at = '2026-02-30T12:00:00Z'; }],
    ['unbound timezone', s => { s.offers['red-offer'].fetched_at = '2026-10-14T12:00:00'; }],
    ['erase known observation', s => { s.offers['red-offer'].fetched_at = null; }],
    ['wrong FX identity', s => { s.fx.snapshot_id = 'foreign-fx'; }],
    ['changed FX safety', s => { s.fx.stale = true; }],
    ['future FX observation', s => { s.fx.fetched_at = new Date(START + 60001).toISOString(); }],
    ['future source attempt', s => { s.collection_status.merchant = {attempted_at: new Date(START + 60001).toISOString(), status: 'success'}; }],
    ['failed source renewal', s => { s.collection_status.merchant = {attempted_at: s.generated_at, status: 'failed', errors: []}; }],
    ['failed page renewal', s => { s.collection_status.merchant = {attempted_at: s.generated_at, status: 'partial', errors: [{url: 'https://merchant.example/red?variant=unavailable'}]}; }],
  ];
  for (const [label, mutate] of mutations) {
    const initial = v2Publication(), h = await harness(snapshot(), {release: initial});
    const last = vm.runInContext('publicLastData', h.context), base = vm.runInContext('publicLastBase', h.context);
    const invalid = heartbeat(initial, START + 60000, mutate); h.setRelease(invalid); h.setNow(START + 60000);
    await assert.rejects(h.context.loadPublished(true), /核实状态.*不一致/, label);
    assert.equal(vm.runInContext('publicLastData', h.context), last, label + ' must preserve live data');
    assert.equal(vm.runInContext('publicLastBase', h.context), base, label + ' must preserve pristine catalog');
    assert.equal(h.context.window.BIKEHUNT_VERIFICATION.generated_at, initial.manifest.generated_at);
    assert.equal(h.snapshotReads().length, 1);
    assert.equal((await h.request('/api/catalog/red')).offers[0].offer.fetched_at, initial.manifest.generated_at);
  }
}

async function testSchema2ManifestAndCatalogIdentityValidation() {
  const mutations = [
    m => { m.status.path = 'https://untrusted.example/status.json'; },
    m => { m.status.path = 'data/../verification.json'; },
    m => { m.status.sha256 = 'bad'; }, m => { m.status.bytes = 0; },
    m => { m.snapshot.semantic_sha256 = 'bad'; }, m => { m.snapshot.version = 'unbound-catalog'; },
    m => { m.snapshot.commit = 'another-commit'; },
    m => { m.snapshot.generated_at = new Date(START + 1).toISOString(); },
    m => { m.version = 'unbound-status'; },
  ];
  for (const mutate of mutations) {
    const release = v2Publication(); mutate(release.manifest);
    const h = await harness(snapshot(), {release, expectInitialFailure: true});
    assert.match(h.initialError.message, /发布清单无效/);
    assert.equal(h.snapshotReads().length, 0); assert.equal(h.statusReads().length, 0);
  }
  const invalidCatalogs = [
    data => { delete data.verification_identities; },
    data => { delete data.verification_identities['red-offer']; },
    data => { data.verification_identities['red-offer'] = 'invalid'; },
    data => { data.verification_identities.extra = '0'.repeat(64); },
    data => { delete data.catalog.items[0].reference_offer_id; },
    data => { data.catalog.items[0].reference_offer_id = 'blue-offer'; },
    data => { const quote = structuredClone(data.details.red.variants['red-M'].offers[0]); quote.offer.stock = 'unknown'; data.details.red.variants['red-M'].offers.push(quote); },
  ];
  for (const mutate of invalidCatalogs) {
    const release = v2Publication(), data = JSON.parse(release.body); mutate(data);
    release.body = JSON.stringify(data); release.manifest.snapshot.bytes = Buffer.byteLength(release.body); release.manifest.snapshot.sha256 = digestBytes(release.body);
    const status = JSON.parse(release.statusBody); status.snapshot_sha256 = release.manifest.snapshot.sha256;
    const h = await harness(snapshot(), {release: bindStatus(release, status), expectInitialFailure: true});
    assert.match(h.initialError.message, /身份/); assert.equal(vm.runInContext('publicLastData', h.context), null);
  }
}

async function testSchema2RetainedFailureAndRecovery() {
  const initial = v2Publication(), h = await harness(snapshot(), {release: initial});
  const failed = snapshot(); failed.generated_at = new Date(START + 60000).toISOString();
  failed.details.red.variants['red-M'].offers[0].offer.collection_state = 'retained';
  failed.details.blue.variants['blue-M'].offers[0].offer.fetched_at = failed.generated_at;
  failed.collection_status = {merchant: {source_code: 'merchant', attempted_at: failed.generated_at, status: 'partial', errors: [{url: 'https://merchant.example/red?variant=failed'}]}};
  const failure = v2Publication(failed); h.setRelease(failure); h.setNow(START + 60000); await h.poll();
  let red = await h.request('/api/catalog/red');
  assert.equal(red.offers[0].offer.collection_state, 'retained'); assert.equal(red.offers[0].eligible, false);
  assert.equal(red.offers[0].offer.fetched_at, initial.manifest.generated_at, 'A failed source keeps its genuine previous observation');
  assert.equal((await h.request('/api/catalog/blue')).variants[0].in_stock, true, 'Partial failures only invalidate the affected product URL');
  assert.equal(h.snapshotReads().length, 2);
  assert.equal(h.verificationEvents.length, 0, 'A retained failure must take ordinary safety invalidation');
  const failedAgain = heartbeat(failure, START + 120000, s => { s.collection_status.merchant.attempted_at = s.generated_at; });
  h.setNow(START + 120000); h.setRelease(failedAgain); await h.poll();
  assert.equal(h.snapshotReads().length, 2); assert.equal(h.events.length, 1, 'Repeating the same retained failure is metadata-only');
  const badRenewal = heartbeat(failure, START + 180000, s => { s.offers['red-offer'].fetched_at = s.generated_at; });
  h.setNow(START + 180000); h.setRelease(badRenewal); await assert.rejects(h.context.loadPublished(true), /核实状态/);
  const recovered = snapshot(); recovered.generated_at = new Date(START + 240000).toISOString();
  for (const family of Object.values(recovered.details)) for (const d of Object.values(family.variants)) for (const quote of d.offers) quote.offer.fetched_at = recovered.generated_at;
  for (const fx of [recovered.catalog.fx, recovered.updates.fx, ...Object.values(recovered.details).flatMap(f => Object.values(f.variants).map(d => d.fx))]) fx.fetched_at = recovered.generated_at;
  recovered.collection_status = {merchant: {source_code: 'merchant', attempted_at: recovered.generated_at, status: 'success', errors: []}};
  h.setNow(START + 240000); h.setRelease(v2Publication(recovered)); await h.poll();
  red = await h.request('/api/catalog/red');
  assert.equal(red.offers[0].offer.collection_state, 'current'); assert.equal(red.offers[0].eligible, true);
  assert.equal(red.offers[0].offer.fetched_at, recovered.generated_at);
  assert.equal(h.snapshotReads().length, 3); assert.equal(h.events.length, 2);
}

async function testSchema2StatusRollbackAndCatalogRollbackProtection() {
  const initial = v2Publication(), h = await harness(snapshot(), {release: initial});
  const accepted = heartbeat(initial, START + 60000); h.setNow(START + 60000); h.setRelease(accepted); await h.poll();
  const previousReads = h.statusReads().length;
  h.setRelease(initial); await assert.rejects(h.context.loadPublished(true), /早于已加载版本/);
  assert.equal(h.statusReads().length, previousReads);
  const reused = structuredClone(accepted); reused.manifest.status.sha256 = '0'.repeat(64); h.setRelease(reused);
  await assert.rejects(h.context.loadPublished(true), /校验信息不一致/); assert.equal(h.statusReads().length, previousReads);
  for (const field of ['offer', 'fx', 'null']) {
    const regressed = heartbeat(initial, START + 120000, status => {
      if (field === 'fx') status.fx.fetched_at = new Date(START + 30000).toISOString();
      else status.offers['red-offer'].fetched_at = field === 'null' ? null : new Date(START + 30000).toISOString();
    });
    h.setNow(START + 120000); h.setRelease(regressed);
    await assert.rejects(h.context.loadPublished(true), /核实状态/);
    assert.equal(h.context.window.BIKEHUNT_VERIFICATION.generated_at, accepted.manifest.generated_at);
  }
  const changed = snapshot(); changed.generated_at = new Date(START + 120000).toISOString(); changed.catalog.items[0].name = 'Unrelated catalog edit';
  const oldObservationInNewCatalog = v2Publication(changed); h.setRelease(oldObservationInNewCatalog);
  await assert.rejects(h.context.loadPublished(true), /核实状态/, 'A new catalog cannot roll back observations for unchanged content identities');
  const legacy = snapshot(); legacy.generated_at = new Date(START + 180000).toISOString(); h.publish(legacy);
  await assert.rejects(h.context.loadPublished(true), /早于已加载版本/, 'A newer manifest cannot downgrade away the verification contract');
  const metadataRewrite = heartbeat(accepted, START + 180000); metadataRewrite.manifest.snapshot.bytes++;
  h.setRelease(metadataRewrite); await assert.rejects(h.context.loadPublished(true), /快照标识/);
  assert.equal(h.snapshotReads().length, 2, 'Reused catalog hashes with conflicting metadata never download');
}

async function testSchema2ByteRacesAndUnavailableProofFailClosed() {
  const initial = v2Publication(), next = heartbeat(initial, START + 60000);
  for (const statusBody of [initial.statusBody, next.statusBody + ' ']) {
    const h = await harness(snapshot(), {release: next, statusBody, expectInitialFailure: true});
    assert.match(h.initialError.message, /校验失败/); assert.equal(vm.runInContext('publicLastData', h.context), null);
    assert.equal(h.statusReads().length, 1, 'A stable inconsistent manifest does not loop on the status alias');
    assert.equal(h.manifestReads().length, 2);
  }
  const h = await harness(snapshot(), {release: initial}); h.setNow(START + 60000);
  h.setRelease(next); h.setStatusBody(initial.statusBody);
  await assert.rejects(h.context.loadPublished(true), /校验失败/);
  assert.equal((await h.request('/api/catalog/red')).offers[0].offer.fetched_at, initial.manifest.generated_at);
  h.setStatusBody(next.statusBody); h.setVerificationStatus(503);
  await assert.rejects(h.context.loadPublished(true), /核实状态暂时无法读取/);
  h.setVerificationStatus(200); await h.poll();
  assert.equal(h.context.window.BIKEHUNT_VERIFICATION.generated_at, next.manifest.generated_at);
  assert.equal(h.snapshotReads().length, 1); assert.equal(h.events.length, 0);
  // A valid new catalog must not leak into the UI until its proof is valid too.
  const payload = snapshot(); payload.generated_at = new Date(START + 120000).toISOString(); payload.catalog.items[0].name = 'Pending new catalog';
  const changed = v2Publication(payload); h.setNow(START + 120000); h.setRelease(changed); h.setStatusBody(next.statusBody);
  await assert.rejects(h.context.loadPublished(true), /校验失败/);
  assert.equal((await h.request('/api/catalog')).items[0].name, 'red');
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.version, initial.manifest.snapshot.version);
}

async function testSchema2RemovedIdentityCannotReappearWithOlderObservation() {
  const initial = v2Publication(), h = await harness(snapshot(), {release: initial});
  const first = heartbeat(initial, START + 60000); h.setNow(START + 60000); h.setRelease(first); await h.poll();
  const withoutRed = snapshot(); withoutRed.generated_at = new Date(START + 120000).toISOString();
  delete withoutRed.details.red; withoutRed.catalog.items.shift();
  const removal = heartbeat(v2Publication(withoutRed), START + 120000); h.setNow(START + 120000); h.setRelease(removal); await h.poll();
  assert.equal((await h.request('/api/catalog')).items.length, 1);
  const restore = snapshot(); restore.generated_at = new Date(START + 180000).toISOString();
  const staleReturn = heartbeat(v2Publication(restore), START + 180000, s => { s.offers['red-offer'].fetched_at = new Date(START + 30000).toISOString(); });
  h.setNow(START + 180000); h.setRelease(staleReturn);
  await assert.rejects(h.context.loadPublished(true), /核实状态/, 'Temporarily removing an offer cannot clear its accepted observation high-water mark');
  assert.equal((await h.request('/api/catalog')).items.length, 1);
}

async function testSchema2ProcessOnlyProofDoesNotRenewObservations() {
  const initial = v2Publication();
  const catalog = JSON.parse(initial.body); catalog.publication.run_id = 'catalog-run'; catalog.publication.trigger = 'initial';
  initial.body = JSON.stringify(catalog); initial.manifest.snapshot.bytes = Buffer.byteLength(initial.body); initial.manifest.snapshot.sha256 = digestBytes(initial.body);
  const firstStatus = JSON.parse(initial.statusBody); firstStatus.snapshot_sha256 = initial.manifest.snapshot.sha256;
  const release = bindStatus(initial, firstStatus), h = await harness(snapshot(), {release});
  const next = heartbeat(release, START + 60000, s => {
    for (const o of Object.values(s.offers)) o.fetched_at = release.manifest.generated_at;
    s.fx.fetched_at = release.manifest.generated_at; s.run_id = 'latest-run'; s.trigger = 'manual';
  });
  h.setNow(START + 60000); h.setRelease(next); await h.poll();
  assert.equal(h.events.length, 0);
  assert.equal(h.context.window.BIKEHUNT_PUBLICATION.run_id, 'catalog-run');
  assert.equal(h.context.window.BIKEHUNT_VERIFICATION.run_id, 'latest-run');
  assert.equal(h.context.window.BIKEHUNT_VERIFICATION.trigger, 'manual');
  assert.equal((await h.request('/api/catalog/red')).offers[0].offer.fetched_at, release.manifest.generated_at);
  h.setNow(START + 3600001); await h.poll();
  assert.equal((await h.request('/api/catalog/red')).variants[0].in_stock, false, 'A rebuild timestamp cannot extend the true source verification window');
  assert.equal(h.events.length, 1); assert.equal(h.snapshotReads().length, 1);
  assert.ok(!h.marker.title.includes('最近核实'), 'Status publication must not be described as a source recheck');
}

async function testSchema2ProofCrossingOldExpiryStillInvalidatesCopiedControls() {
  const initial = v2Publication(), h = await harness(snapshot(), {release: initial});
  const next = heartbeat(initial, START + 3599999, status => {
    for (const observation of Object.values(status.offers)) observation.fetched_at = new Date(START + 3599000).toISOString();
  });
  h.setRelease(next); h.setNow(START + 3599999);
  let release; h.setStatusGate(new Promise(resolve => { release = resolve; }));
  const pending = h.poll();
  for (let i = 0; i < 20 && h.statusReads().length < 2; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.events.length, 0, 'The pre-request inventory check is still fresh');
  h.setNow(START + 3600001); release(); await pending;
  assert.equal((await h.request('/api/catalog/red')).offers[0].eligible, true);
  assert.equal(h.events.length, 1, 'Crossing expiry during the proof request must not disappear between matching fresh fingerprints');
  assert.equal(h.events[0].detail.freshnessChanged, true);
  assert.equal(h.verificationEvents.length, 0, 'Expired copied controls take normal invalidation, never a metadata-only revival');
  assert.equal(h.snapshotReads().length, 1);
  await h.poll(); assert.equal(h.events.length, 1, 'The transition signal is consumed exactly once');
}

async function testSchema2HungStatusSharesInflightAndStillExpires() {
  const initial = v2Publication(), h = await harness(snapshot(), {release: initial});
  const next = heartbeat(initial, START + 60000); h.setNow(START + 60000); h.setRelease(next);
  let release; h.setStatusGate(new Promise(resolve => { release = resolve; }));
  const first = h.poll();
  for (let i = 0; i < 20 && h.statusReads().length < 2; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.statusReads().length, 2);
  const manual = h.context.window.fetch('/api/refresh/prices');
  h.setNow(START + 3600001); const second = h.poll();
  assert.equal(h.events.length, 1, 'Expiry runs while the status network is hung');
  assert.equal((await h.request('/api/catalog/red')).offers[0].eligible, false);
  assert.equal(h.manifestReads().length, 2); assert.equal(h.snapshotReads().length, 1);
  release(); await Promise.all([first, manual, second]);
  assert.equal(h.statusReads().length, 2);
  assert.equal((await h.request('/api/catalog/red')).offers[0].eligible, true, 'The accepted actual observation is still within its own hour');
  assert.equal(h.events.length, 2, 'Concurrent waiters dispatch one safety restoration event');
  h.setNow(START + 60000 + 3600001); h.setOffline(true); await h.poll();
  assert.equal((await h.request('/api/catalog/red')).offers[0].eligible, false);
  assert.equal(h.events.length, 3);
}

async function testSourceQuotesBindIdentityAndExpire(){
 const payload=snapshot();
 for(const card of payload.catalog.items){
  const family=payload.details[card.product_id],detail=family.variants[family.default],q=detail.offers[0],o=q.offer;
  Object.assign(o,{source_code:'merchant',source_name:'Merchant',collection_state:'current',data_kind:'live_snapshot',price:{amount:'10',currency:'EUR'},original_price:null,identity:{size:'M',color:'Red'}});
  q.product_cny='75.00';
  Object.assign(card,{source_codes:['merchant'],reference_offer_id:o.offer_id,reference_variant_id:detail.variant_id,
   reference_price:o.price,reference_original_price:null,reference_cny:q.product_cny,reference_source:o.source_name,
   reference_url:o.url,reference_size:'M',reference_color:'Red',reference_price_valid_until:null,
   reference_data_kind:'live_snapshot',reference_collection_state:'current',reference_stock:'in_stock',fetched_at:o.fetched_at});
  card.channel_quotes={merchant:{...card,channel_quotes:{}}};
 }
 const release=v2Publication(payload),h=await harness(payload,{release});
 let catalog=await h.request('/api/catalog');
 assert.equal(catalog.items[0].channel_quotes.merchant.reference_stock,'in_stock');
 h.setRelease(heartbeat(release,START+60000));h.setNow(START+60000);await h.poll();
 catalog=await h.request('/api/catalog');
 assert.equal(catalog.items[0].channel_quotes.merchant.fetched_at,new Date(START+60000).toISOString());
 h.setOffline(true);h.setNow(START+3660001);await h.poll();catalog=await h.request('/api/catalog');
 assert.equal(catalog.items[0].channel_quotes.merchant.reference_stock,'unknown');
 assert.equal(catalog.items[0].channel_quotes.merchant.available_sizes.length,0);
 const wrong=structuredClone(payload);wrong.catalog.items[0].source_codes.push('wrong');
 wrong.catalog.items[0].channel_quotes.wrong=wrong.catalog.items[0].channel_quotes.merchant;
 const invalid=await harness(wrong,{release:v2Publication(wrong),expectInitialFailure:true});
 assert.ok(invalid.initialError,'A source mapping cannot reuse another merchant offer');
}

async function main() {
  const tests = [testSourceQuotesBindIdentityAndExpire,testInitialSnapshotBypassesBrowserCache, testCachedApiRechecksFxAndEligibility, testFxAgeDateAndTimezoneBoundaries,
    testInventoryAndColorsExpireTogether, testSamePublicationNotifiesOnFreshnessChanges,
    testPublicationCursorNeverMovesBackwards, testSoldOutAndFailedRefreshInvalidateActions,
    testStockTimestampBoundariesFailClosed, testOfflinePollStillExpiresStock,
    testUnchangedManifestAvoidsFullSnapshotTransfers, testNewVersionSharesOneInflightSnapshot,
    testCdnRacesNeverCommitMismatchedSnapshots, testDigestAndPublicationMetadataAreBothRequired,
    testRollbackAndReusedVersionAreRejected, testManifestFailuresFailClosedAndRetry,
    testHungNetworkDoesNotDelayClockExpiry, testInitialCdnRaceRecoversWithBoundedRetry,
    testFailedUiBootResubscribesOnVerifiedPublication,
    testSchema2HeartbeatUsesOnlyStatusAndStaysQuiet, testSchema2HeartbeatRestoresOnlyLocallyExpiredSafety,
    testSchema2ExactReferenceAndEvidenceOverlay, testSchema2DiscountReferenceMetadata, testSchema2NewContentAndEventsNotifyOnce,
    testSchema2InvalidStatusCannotCommit, testSchema2ManifestAndCatalogIdentityValidation,
    testSchema2RetainedFailureAndRecovery, testSchema2StatusRollbackAndCatalogRollbackProtection,
    testSchema2ByteRacesAndUnavailableProofFailClosed, testSchema2RemovedIdentityCannotReappearWithOlderObservation,
    testSchema2ProcessOnlyProofDoesNotRenewObservations, testSchema2ProofCrossingOldExpiryStillInvalidatesCopiedControls,
    testSchema2HungStatusSharesInflightAndStillExpires];
  for (const test of tests) {
    await test();
    console.log('PASS ' + test.name);
  }
  console.log('Pages freshness: ' + tests.length + ' regression groups passed.');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
