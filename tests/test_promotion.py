"""Local promotion regression suite; synthetic observations stay in temporary roots."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.catalog.models import Money, ProductIdentity
from app.catalog.storage import atomic_json
from app.promotion import HOMEPAGE_URL, PromotionPreparer, safe_https
from app.updates import UpdateStore
from scripts.prepare_promotion import main
from scripts.seed_updates import restore_public_cursor, validate_events
from test_catalog import make_offer

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        atomic_json(self.root / 'data/sources.json', [{
            'code': 'brand', 'name': 'Brand official', 'base_url': 'https://shop.example', 'enabled': True}])
        atomic_json(self.root / 'data/crawl_sources.json', [{'code': 'brand', 'domains': ['shop.example']}])
        self.store = UpdateStore(self.root)
        self.preparer = PromotionPreparer(self.root)
        self.preparer.prepare(now=NOW)

    def offer(self, size='M', price='100', stock='in_stock', at=None, **kwargs):
        return make_offer('brand-' + size, price, source_code='brand', source_name='Brand official',
            url='https://shop.example/products/exact-red?variant=' + size,
            identity=ProductIdentity(brand='Brand', model='Exact Jersey', mpn='EXACT-RED', size=size, color='Red'),
            image='https://images.example/exact-red.jpg', sales_region='US',
            fetched_at=at or NOW - timedelta(minutes=5), stock=stock, **kwargs)

    def snapshot(self, offers, **status):
        atomic_json(self.root / 'data/offers/brand.json', {'source_code': 'brand',
            'offers': [row.model_dump(mode='json') for row in offers]})
        state = {'source_code': 'brand', 'status': 'success', 'errors': [],
                 'attempted_at': max(row.fetched_at for row in offers).isoformat()}
        state.update(status)
        atomic_json(self.root / 'data/collection_status/brand.json', state)

    def transition(self, *, old_price='100', price='80', old_stock='in_stock', stock='in_stock',
                   sizes=('M',), at=None):
        at = at or NOW + timedelta(seconds=1)
        previous = [self.offer(size, old_price, old_stock) for size in sizes]
        current = [self.offer(size, price, stock, at) for size in sizes]
        events = self.store.capture(previous, current)
        self.snapshot(current)
        return previous, current, events

    def run_now(self, seconds=2, **kwargs):
        return self.preparer.prepare(now=NOW + timedelta(seconds=seconds), **kwargs)

    def packages(self):
        return json.loads((self.root / 'storage/promotions/queue.json').read_text())['drafts']

    def test_default_initialization_skips_backlog_and_does_not_publish(self):
        self.transition()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            UpdateStore(root).capture([self.offer()], [self.offer(price='80', at=NOW)])
            result = PromotionPreparer(root).prepare(now=NOW + timedelta(seconds=2))
            self.assertTrue(result['initialized'])
            self.assertEqual(result['selected_events'], 0)
            self.assertEqual(result['created'], 0)
            self.assertEqual(result['published'], 0)
            self.assertEqual(result['network_requests'], 0)
            self.assertFalse((root / '_site').exists())

    def test_real_price_drop_sizes_aggregate_and_exact_references(self):
        self.transition(sizes=('M', 'L'))
        with patch('urllib.request.urlopen', side_effect=AssertionError('No network allowed')):
            result = self.run_now()
        self.assertEqual(result['created'], 1)
        package = self.packages()[0]
        self.assertEqual(package['sizes'], ['L', 'M'])
        self.assertEqual(package['group']['changes'], ['price_drop'])
        self.assertEqual(package['group']['old_price'], '100')
        self.assertEqual(package['group']['new_price'], '80')
        self.assertEqual(package['homepage_url'], HOMEPAGE_URL)
        self.assertEqual(package['publication_state'], 'not_published')
        self.assertEqual(package['status'], 'pending_review')
        self.assertNotIn('#', package['homepage_url'])
        for evidence in package['evidence']:
            self.assertRegex(evidence['product_id'], '^[0-9a-f]{20}$')
            self.assertIn(evidence['product_url'], package['draft_text'])
        self.assertNotIn('最低', package['draft_text'])
        self.assertNotIn('包邮', package['draft_text'])
        self.assertTrue((self.root / 'storage/promotions/drafts' / package['draft_key'] / 'draft.txt').exists())
        self.assertFalse((self.root / '_site').exists())

    def test_restock_only_requires_proven_previous_soldout(self):
        self.transition(price='100', old_stock='out_of_stock')
        self.assertEqual(self.run_now()['created'], 1)
        self.assertEqual(self.packages()[0]['group']['changes'], ['restock'])

    def test_restock_with_price_increase_never_claims_price_drop(self):
        self.transition(price='120', old_stock='out_of_stock')
        self.assertEqual(self.run_now()['created'], 1)
        package = self.packages()[0]
        self.assertEqual(package['group']['changes'], ['restock'])
        self.assertNotIn('降价', package['draft_text'])

    def test_retained_legacy_or_expired_current_offer_is_rejected(self):
        _, current, _ = self.transition()
        for updates, reason in [({'collection_state': 'retained'}, 'retained_or_failed_offer'),
                                ({'data_kind': 'legacy_cache'}, 'legacy_offer_evidence'),
                                ({'price_valid_until': '2026-10-14'}, 'expired_price')]:
            with self.subTest(updates=updates):
                self.snapshot([current[0].model_copy(update=updates)])
                result = self.run_now(since=NOW, until=NOW + timedelta(seconds=2))
                self.assertEqual(result['created'], 0)
                self.assertEqual(result['skipped'], {reason: 1})

    def test_event_classification_must_match_actual_transition(self):
        _, _, events = self.transition()
        with self.store.connect() as db:
            db.execute("UPDATE events SET kind='inventory_changed' WHERE id=?", (events[0]['id'],))
        self.assertEqual(self.run_now()['skipped'], {'event_kind_evidence_mismatch': 1})

    def test_combined_price_and_stock_change_is_one_package_with_both_signals(self):
        _, _, events = self.transition(old_stock='out_of_stock')
        self.assertEqual(events[0]['kind'], 'price_changed')
        self.assertEqual(events[0]['old_stock'], 'out_of_stock')
        self.assertEqual(self.run_now()['created'], 1)
        self.assertEqual(self.packages()[0]['group']['changes'], ['price_drop', 'restock'])

    def test_unknown_previous_stock_does_not_claim_restock(self):
        self.transition(price='100', old_stock='unknown')
        result = self.run_now()
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['skipped'], {'not_price_drop_or_proven_restock': 1})

    def test_unknown_stock_can_support_only_a_proven_price_drop(self):
        self.transition(old_stock='unknown')
        self.assertEqual(self.run_now()['created'], 1)
        self.assertEqual(self.packages()[0]['group']['changes'], ['price_drop'])

    def test_same_price_repeated_fetch_creates_neither_event_nor_repost(self):
        _, current, _ = self.transition()
        self.assertEqual(self.run_now()['created'], 1)
        key = self.packages()[0]['draft_key']
        self.assertEqual(self.run_now()['created'], 0)
        fresh = [current[0].model_copy(update={'fetched_at': NOW + timedelta(seconds=3)})]
        self.assertEqual(self.store.capture(current, fresh), [])
        self.snapshot(fresh)
        self.assertEqual(self.run_now(4)['created'], 0)
        self.assertEqual(self.packages()[0]['draft_key'], key)
        self.assertEqual(len(self.packages()), 1)

    def test_same_transition_new_size_updates_existing_package(self):
        self.transition()
        self.run_now()
        previous = self.offer('L')
        current = self.offer('L', '80', at=NOW + timedelta(seconds=3))
        self.store.capture([previous], [current])
        self.snapshot([self.offer('M', '80', at=NOW + timedelta(seconds=1)), current])
        result = self.run_now(4)
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['updated'], 1)
        self.assertEqual(self.packages()[0]['sizes'], ['L', 'M'])

    def test_later_same_offer_event_supersedes_prior_drop(self):
        _, current, _ = self.transition()
        increased = current[0].model_copy(update={
            'price': Money(amount='90', currency='USD'), 'fetched_at': NOW + timedelta(seconds=3)})
        self.store.capture(current, [increased])
        self.snapshot([increased])
        result = self.run_now(4)
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['skipped']['superseded_event'], 1)

    def test_existing_draft_invalidates_after_newer_price_event(self):
        _, current, _ = self.transition()
        self.run_now()
        increased = current[0].model_copy(update={
            'price': Money(amount='90', currency='USD'), 'fetched_at': NOW + timedelta(seconds=3)})
        self.store.capture(current, [increased])
        self.snapshot([increased])
        result = self.run_now(4)
        self.assertEqual(result['invalidated'], 1)
        self.assertEqual(result['pending_review'], 0)
        package = self.packages()[0]
        self.assertEqual(package['status'], 'invalidated')
        self.assertTrue(package['draft_text'].startswith('[已失效'))
        self.assertEqual(package['invalidation_reasons'], {'superseded_event': 1})

    def test_price_must_still_equal_event_even_without_new_event(self):
        _, current, _ = self.transition()
        self.snapshot([current[0].model_copy(update={'price': Money(amount='70', currency='USD')})])
        self.assertEqual(self.run_now()['skipped'], {'current_price_changed': 1})

    def test_current_stock_must_remain_in_stock(self):
        _, current, _ = self.transition()
        self.snapshot([current[0].model_copy(update={'stock': 'out_of_stock'})])
        self.assertEqual(self.run_now()['skipped'], {'current_stock_not_in_stock': 1})

    def test_provider_failed_or_partial_is_rejected(self):
        for state in ('failed', 'partial'):
            with self.subTest(state=state):
                _, current, _ = self.transition()
                self.snapshot(current, status=state, errors=[{'error': 'blocked'}])
                result = self.run_now(since=NOW, until=NOW + timedelta(seconds=2))
                self.assertEqual(result['created'], 0)
                self.assertEqual(result['skipped'], {'source_not_healthy': 1})

    def test_existing_package_invalidates_on_failure_without_new_events(self):
        _, current, _ = self.transition()
        self.run_now()
        self.snapshot(current, status='failed', errors=[{'error': 'provider unavailable'}])
        result = self.run_now(3)
        self.assertEqual(result['invalidated'], 1)
        self.assertEqual(result['pending_review'], 0)

    def test_stale_offer_and_stale_health_are_rejected(self):
        self.transition()
        result = self.run_now(3602)
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['skipped'], {'stale_offer': 1})

    def test_current_offer_and_source_verification_cannot_be_future(self):
        _, current, _ = self.transition()
        self.snapshot(current, attempted_at=(NOW + timedelta(seconds=20)).isoformat())
        self.assertEqual(self.run_now()['skipped'], {'source_verification_stale_or_incoherent': 1})

    def test_first_discovery_recovered_and_suppressed_events_are_excluded(self):
        current = self.offer(price='80', at=NOW + timedelta(seconds=1))
        self.store.capture([], [current])
        self.snapshot([current])
        self.assertEqual(self.run_now()['skipped'], {'first_discovery': 1})
        for marker, reason in [('recovered', 'recovered_history'), ('suppressed', 'suppressed_event')]:
            self.store.capture([current], [current.model_copy(update={
                'price': Money(amount='70', currency='USD'), 'fetched_at': NOW + timedelta(seconds=3)})])
            with self.store.connect() as db:
                event = db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 1').fetchone()
                if marker == 'recovered':
                    db.execute('UPDATE events SET recovered_history=1 WHERE id=?', (event['id'],))
                else:
                    db.execute('INSERT INTO suppressed_events VALUES (?,?,?,?)', (event['event_key'], 'test', 'a', 'b'))
            result = self.run_now(4, since=NOW + timedelta(seconds=2), until=NOW + timedelta(seconds=4))
            self.assertEqual(result['skipped'], {reason: 1})
            with self.store.connect() as db:
                db.execute('UPDATE events SET recovered_history=0')

    def test_currency_switch_never_becomes_price_drop(self):
        old = self.offer()
        new = self.offer(price='80', at=NOW + timedelta(seconds=1)).model_copy(update={
            'price': Money(amount='80', currency='EUR')})
        event = self.store.capture([old], [new])[0]
        self.snapshot([new])
        self.assertIsNone(event['old_price'])
        self.assertEqual(self.run_now()['created'], 0)

    def test_market_change_in_same_currency_is_rejected(self):
        old = self.offer().model_copy(update={'sales_region': 'CA'})
        new = self.offer(price='80', at=NOW + timedelta(seconds=1))
        self.store.capture([old], [new])
        self.snapshot([new])
        self.assertEqual(self.run_now()['skipped'], {'exact_identity_or_market_changed': 1})

    def test_missing_market_and_missing_metadata_have_explicit_skip_reasons(self):
        for field, value, reason in [('sales_region', '', 'missing_or_mismatched_market'),
                                     ('identity', ProductIdentity(brand='Brand', model='Exact Jersey', mpn='EXACT-RED', size='M'), 'missing_product_metadata')]:
            old = self.offer().model_copy(update={field: value})
            new = old.model_copy(update={'price': Money(amount='80', currency='USD'), 'fetched_at': NOW + timedelta(seconds=1)})
            self.store.capture([old], [new])
            self.snapshot([new])
            result = self.run_now(since=NOW, until=NOW + timedelta(seconds=2))
            self.assertEqual(result['skipped'], {reason: 1})
            with self.store.connect() as db:
                db.execute('DELETE FROM events')

    def test_different_currencies_or_price_transitions_never_aggregate(self):
        old = [self.offer('M'), self.offer('L').model_copy(update={'price': Money(amount='100', currency='EUR')})]
        new = [self.offer('M', '80', at=NOW + timedelta(seconds=1)),
               self.offer('L', at=NOW + timedelta(seconds=1)).model_copy(update={'price': Money(amount='80', currency='EUR')})]
        self.store.capture(old, new)
        self.snapshot(new)
        self.assertEqual(self.run_now()['created'], 2)
        self.assertEqual({x['group']['currency'] for x in self.packages()}, {'USD', 'EUR'})

    def test_tampered_old_price_or_old_stock_fails_evidence_check(self):
        _, _, events = self.transition()
        with self.store.connect() as db:
            db.execute('UPDATE events SET old_price=? WHERE id=?', ('200', events[0]['id']))
        self.assertEqual(self.run_now()['skipped'], {'event_price_evidence_mismatch': 1})

    def test_explicit_bounded_window_is_required_for_old_events(self):
        _, _, events = self.transition(at=NOW - timedelta(seconds=1))
        result = self.run_now()
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['skipped'], {'before_monitoring_start': 1})
        result = self.run_now(since=NOW - timedelta(minutes=10), until=NOW)
        self.assertEqual(result['created'], 1)
        for kwargs in ({'since': NOW}, {'since': NOW - timedelta(days=8), 'until': NOW},
                       {'since': NOW, 'until': NOW + timedelta(days=1)},
                       {'since': NOW.replace(tzinfo=None), 'until': NOW}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_now(**kwargs)

    def test_legacy_schema_migration_has_null_old_stock_and_no_fake_backfill(self):
        old, _, events = self.transition(old_stock='out_of_stock')
        with self.store.connect() as db:
            db.execute('ALTER TABLE events DROP COLUMN old_stock')
            db.execute('ALTER TABLE events DROP COLUMN old_context_json')
            db.execute('ALTER TABLE events DROP COLUMN current_context_json')
        migrated = UpdateStore(self.root)
        self.assertEqual(migrated.cursor(), events[0]['id'])
        self.assertIsNone(migrated.latest()[0]['old_stock'])
        self.assertEqual(self.run_now()['skipped'], {'missing_transition_evidence': 1})
        new = self.offer(price='70', at=NOW + timedelta(seconds=3))
        self.assertEqual(migrated.capture(old, [new])[0]['old_stock'], 'out_of_stock')

    def test_public_old_stock_roundtrip_keeps_private_context_unavailable(self):
        _, _, events = self.transition(old_stock='out_of_stock')
        validated, _ = validate_events(events, events[0]['id'])
        self.assertEqual(validated[0]['old_stock'], 'out_of_stock')
        self.assertNotIn('old_context_json', events[0])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            atomic_json(root / 'data/public_updates.json', events)
            restore_public_cursor(root)
            restored = UpdateStore(root)
            self.assertEqual(restored.latest()[0]['old_stock'], 'out_of_stock')
            with restored.connect() as db:
                row = db.execute('SELECT * FROM events').fetchone()
                self.assertIsNone(row['old_context_json'])
                self.assertIsNone(row['current_context_json'])

    def test_safe_product_url_rejects_unsafe_unbound_and_nonproduct_links(self):
        for url in ('javascript:alert(1)', 'http://shop.example/products/x',
                    'https://evil.example/products/x', 'https://shop.example@evil.example/products/x',
                    'https://shop.example/', 'https://shop.example/en-us/',
                    'https://shop.example/collections/all', 'https://shop.example/redirect?url=https://evil.example',
                    'https://shop.example/products/x?utm_source=spam', 'https://shop.example/products/x#spoof',
                    'https://shop.example/products/%2e%2e/cart', 'https://127.0.0.1/products/x',
                    'https://shop.example:444/products/x', 'https://shop.example/products/x%0anewline'):
            with self.subTest(url=url):
                self.assertFalse(safe_https(url, {'shop.example'}, product=True))
        self.assertTrue(safe_https('https://shop.example/products/exact?variant=12', {'shop.example'}, product=True))

    def test_unsafe_product_url_is_skipped_in_real_generation(self):
        old = self.offer().model_copy(update={'url': 'https://evil.example/products/x'})
        new = old.model_copy(update={'price': Money(amount='80', currency='USD'), 'fetched_at': NOW + timedelta(seconds=1)})
        self.store.capture([old], [new])
        self.snapshot([new])
        self.assertEqual(self.run_now()['skipped'], {'unsafe_or_unbound_product_url': 1})

    def test_cli_rejects_unbounded_or_naive_window(self):
        for args in (['--since', NOW.isoformat()], ['--since', '2026-10-15T01:00:00', '--until', NOW.isoformat()]):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                main(['--root', str(self.root), *args])

    def test_output_cannot_escape_via_storage_symlink(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as other:
            root = Path(temp)
            (root / 'storage').symlink_to(Path(other), target_is_directory=True)
            with self.assertRaises(ValueError):
                PromotionPreparer(root)


if __name__ == '__main__':
    unittest.main(verbosity=2)
