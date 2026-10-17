"""Offline acceptance tests for manifest-based public deployment verification."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import verify_public_release as verifier

COMMIT = 'a' * 40
OLD_COMMIT = 'b' * 40
BASE = 'https://example.org/BikeHunt/'
NOW = datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)


def release(commit=COMMIT, generated_at='2026-10-14T12:00:00+00:00'):
    version = commit + ':' + generated_at
    data = {
        'generated_at': generated_at,
        'publication': {'commit': commit, 'version': version},
        'collection_status': {'shop': {'coverage': {
            'method': 'shopify_public_feed_plus_product_jsonld', 'market_country': '美国'}}},
        'details': {'product': {'variants': {'variant': {'offers': [{'offer': {
            'source_code': 'shop', 'price': {'currency': 'USD'},
            'sales_region': '美国 市场 · USD 报价',
        }}]}}}},
    }
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'
    manifest = {'schema_version': 1, 'version': version, 'generated_at': generated_at,
                'commit': commit, 'snapshot': {'path': 'data/site-data.json',
                    'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}
    html = ('世巡车队 bikehunt-lockup bikehunt-logo.svg purchaseDisclaimerInfo publicationInfo '
            f'data-release="{commit}"').encode('utf-8')
    return manifest, raw, html


def rehash(manifest, data):
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    manifest['snapshot'].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return raw

def rehash_status(manifest, status):
    raw = json.dumps(status, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    manifest['status'].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return raw


def rehash_split_snapshot(manifest, data):
    semantic_hash = verifier.digest(verifier.semantic_projection(data))
    data['publication']['version'] = data['publication']['commit'] + ':catalog:' + semantic_hash
    manifest['snapshot'].update(version=data['publication']['version'],
                                generated_at=data['generated_at'],
                                commit=data['publication']['commit'], semantic_sha256=semantic_hash)
    return rehash(manifest, data)


def split_release(generated_at='2026-10-15T12:00:00+00:00'):
    """An older byte-identical catalog bound to a newly verified observation run."""
    manifest, raw, html = release()
    data = json.loads(raw)
    offer = data['details']['product']['variants']['variant']['offers'][0]['offer']
    offer.update(offer_id='shop-blue-M', collection_state='current',
                 fetched_at='2026-10-14T11:00:00+00:00', url='https://shop.example/blue?variant=M')
    fx = {'snapshot_id': 'fx-2026-10-14', 'fetched_at': '2026-10-14T10:00:00+00:00',
          'stale': False, 'rates': {'CNY': '1', 'USD': '7'}, 'rate_date': '2026-10-14'}
    data['details']['product']['variants']['variant']['fx'] = copy.deepcopy(fx)
    data['catalog'] = {'items': [{'product_id': 'product', 'reference_offer_id': 'shop-blue-M',
                                 'reference_collection_state': 'current',
                                 'fetched_at': offer['fetched_at']}], 'fx': copy.deepcopy(fx)}
    data['updates'] = {'items': [], 'fx': copy.deepcopy(fx)}
    data['verification_identities'] = {offer['offer_id']: verifier.offer_identity(offer)}
    manifest.update(schema_version=2, version=COMMIT + ':' + generated_at, generated_at=generated_at,
                    status={'path': 'data/verification.json'})
    raw = rehash_split_snapshot(manifest, data)
    status = {'schema_version': 1, 'version': manifest['version'],
              'generated_at': generated_at, 'commit': COMMIT,
              'snapshot_sha256': manifest['snapshot']['sha256'],
              'offers': {offer['offer_id']: {'content_sha256': data['verification_identities'][offer['offer_id']],
                                          'fetched_at': '2026-10-15T11:00:00+00:00',
                                          'collection_state': 'current'}},
              'fx': {'snapshot_id': fx['snapshot_id'], 'fetched_at': '2026-10-15T10:00:00+00:00',
                     'stale': False},
              'collection_status': copy.deepcopy(data['collection_status'])}
    status['collection_status']['shop'].update(status='success', attempted_at=generated_at, errors=[])
    status_raw = rehash_status(manifest, status)
    return manifest, raw, status_raw, html



class PublicReleaseTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(verifier, 'datetime', wraps=datetime)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.clock.now.return_value = NOW

    def test_fetches_manifest_before_exact_snapshot_and_html(self):
        manifest, raw, html = release()
        responses = [json.dumps(manifest).encode(), raw, html]
        with patch.object(verifier.urllib.request, 'urlopen',
                          side_effect=[io.BytesIO(body) for body in responses]) as fetch:
            receipt = verifier.verify_public_release(BASE.rstrip('/'), COMMIT, attempts=1)
        urls = [call.args[0] for call in fetch.call_args_list]
        self.assertEqual([urlsplit(url).path for url in urls],
                         ['/BikeHunt/data/publication.json', '/BikeHunt/data/site-data.json', '/BikeHunt/'])
        self.assertEqual(parse_qs(urlsplit(urls[1]).query)['version'], [manifest['version']])
        self.assertTrue(all(call.kwargs['timeout'] == 20 for call in fetch.call_args_list))
        self.assertEqual(receipt['manifest'], manifest)
        self.assertEqual(receipt['publication']['version'], manifest['version'])
        self.assertEqual(receipt['verified_public_url'], BASE)

    def test_rejects_truncated_bytes_and_same_length_corruption(self):
        manifest, raw, _ = release()
        for changed, error in [(raw[:-1], 'byte length'),
                               (raw.replace(b'USD', b'EUR'), 'SHA-256')]:
            with self.subTest(error=error), self.assertRaisesRegex(verifier.VerificationError, error):
                verifier.validate_snapshot(manifest, changed, COMMIT)

    def test_hash_is_over_exact_bytes_not_reserialized_json(self):
        manifest, raw, _ = release()
        equivalent = json.dumps(json.loads(raw), ensure_ascii=False).encode('utf-8')
        manifest['snapshot']['bytes'] = len(equivalent)
        with self.assertRaisesRegex(verifier.VerificationError, 'SHA-256'):
            verifier.validate_snapshot(manifest, equivalent, COMMIT)

    def test_rejects_invalid_manifest_contract(self):
        manifest, _, _ = release()
        changes = [('schema_version', 2), ('schema_version', True), ('generated_at', ''),
                   ('version', 'unrelated-build')]
        for field, value in changes:
            changed = copy.deepcopy(manifest)
            changed[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(verifier.VerificationError):
                verifier.validate_manifest(changed, COMMIT)
        for field, value in [('path', 'https://other.example/snapshot.json'),
                             ('path', '../site-data.json'), ('bytes', True), ('bytes', 0),
                             ('sha256', 'invalid')]:
            changed = copy.deepcopy(manifest)
            changed['snapshot'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(verifier.VerificationError):
                verifier.validate_manifest(changed, COMMIT)

    def test_rejects_non_iso_naive_and_impossible_timestamps(self):
        for timestamp in [None, 42, 'not-a-date', '2026-10-14',
                          '2026-10-14T12:00:00', '2026-10-14 12:00:00Z',
                          '2026-10-14T12:00Z', '2026-02-29T12:00:00Z',
                          '2026-13-14T12:00:00Z', '2026-10-14T25:00:00Z',
                          '2026-10-14T12:60:00Z', '2026-10-14T12:00:60Z',
                          '2026-10-14T12:00:00+24:00', '2026-10-14T12:00:00+00:60']:
            manifest, _, _ = release()
            manifest['generated_at'] = timestamp
            manifest['version'] = COMMIT + ':' + str(timestamp)
            with self.subTest(timestamp=timestamp), self.assertRaisesRegex(
                    verifier.VerificationError, 'generated_at.*ISO timestamp'):
                verifier.validate_manifest(manifest, COMMIT)

    def test_accepts_valid_timezone_and_fractional_timestamp_formats(self):
        for timestamp in ['2026-10-14T12:00:00Z', '2026-10-14t12:00:00z',
                          '2026-10-14T12:00:00.123456+00:00',
                          '2026-10-14T12:00:00+0800', '2026-10-14T12:00:00-04:00']:
            manifest, raw, _ = release(generated_at=timestamp)
            with self.subTest(timestamp=timestamp):
                verifier.validate_snapshot(manifest, raw, COMMIT)

    def test_rejects_more_than_five_minutes_future_but_accepts_boundary(self):
        boundary = NOW + timedelta(minutes=5)
        for timestamp in [NOW.isoformat(), boundary.isoformat(),
                          boundary.astimezone(timezone(timedelta(hours=8))).isoformat()]:
            manifest, raw, _ = release(generated_at=timestamp)
            with self.subTest(timestamp=timestamp):
                verifier.validate_snapshot(manifest, raw, COMMIT)
        for future in [boundary + timedelta(microseconds=1), NOW + timedelta(days=1)]:
            manifest, raw, _ = release(generated_at=future.isoformat())
            with self.subTest(timestamp=future), self.assertRaisesRegex(
                    verifier.VerificationError, 'more than five minutes in the future'):
                verifier.validate_snapshot(manifest, raw, COMMIT)
        self.clock.now.assert_called_with(timezone.utc)

    def test_rejects_identity_conflicts_even_with_valid_length_and_hash(self):
        for field, value in [('commit', OLD_COMMIT), ('version', 'other-version'),
                             ('generated_at', '2026-10-13T12:00:00+00:00')]:
            manifest, raw, _ = release()
            data = json.loads(raw)
            (data if field == 'generated_at' else data['publication'])[field] = value
            raw = rehash(manifest, data)
            with self.subTest(field=field), self.assertRaises(verifier.VerificationError):
                verifier.validate_snapshot(manifest, raw, COMMIT)

    def test_coherent_older_commit_is_rejected_even_with_newer_timestamp(self):
        manifest, raw, _ = release(OLD_COMMIT, '2026-10-15T12:00:00+00:00')
        with self.assertRaisesRegex(verifier.VerificationError, 'older manifest'):
            verifier.validate_snapshot(manifest, raw, COMMIT)
        with patch.object(verifier, 'fetch_bytes', return_value=json.dumps(manifest).encode()) as fetch:
            with self.assertRaisesRegex(RuntimeError, 'older manifest'):
                verifier.verify_public_release(BASE, COMMIT, attempts=1)
        self.assertEqual(fetch.call_count, 1)

    def test_retries_out_of_order_cdn_snapshot_until_coherent(self):
        manifest, raw, html = release()
        _, old_raw, _ = release(COMMIT, '2026-10-13T12:00:00+00:00')
        encoded_manifest = json.dumps(manifest).encode()
        with patch.object(verifier, 'fetch_bytes',
                          side_effect=[encoded_manifest, old_raw, encoded_manifest, raw, html]) as fetch, \
                patch.object(verifier.time, 'sleep') as sleep:
            result = verifier.verify_public_release(BASE, COMMIT, attempts=2, retry_delay=0.25)
        self.assertEqual(result['manifest']['version'], manifest['version'])
        sleep.assert_called_once_with(0.25)
        self.assertEqual(parse_qs(urlsplit(fetch.call_args_list[2].args[0]).query)['attempt'], ['1'])

    def test_retries_old_manifest_until_expected_commit_arrives(self):
        old_manifest, _, _ = release(OLD_COMMIT)
        manifest, raw, html = release()
        with patch.object(verifier, 'fetch_bytes', side_effect=[json.dumps(old_manifest).encode(),
                          json.dumps(manifest).encode(), raw, html]), patch.object(verifier.time, 'sleep'):
            self.assertEqual(verifier.verify_public_release(BASE, COMMIT, attempts=2)['commit'], COMMIT)

    def test_never_reports_success_after_repeated_mismatch(self):
        manifest, raw, _ = release()
        with patch.object(verifier, 'fetch_bytes',
                          side_effect=[json.dumps(manifest).encode(), raw[:-1]] * 2), \
                patch.object(verifier.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'Public deployment not verified:.*byte length'):
                verifier.verify_public_release(BASE, COMMIT, attempts=2)
        sleep.assert_called_once_with(10)

    def test_preserves_public_html_checks(self):
        _, _, raw_html = release()
        html = raw_html.decode('utf-8')
        verifier.validate_html(html, COMMIT)
        for bad in [html.replace(COMMIT, OLD_COMMIT), html.replace('世巡车队', '骑行车队'),
                    html.replace('bikehunt-lockup', ''), html.replace('bikehunt-logo.svg', ''),
                     html.replace('purchaseDisclaimerInfo', ''),
                    html.replace('publicationInfo', '')]:
            with self.subTest(html=bad), self.assertRaises(verifier.VerificationError):
                verifier.validate_html(bad, COMMIT)

    def test_preserves_projected_currency_and_country_checks(self):
        _, raw, _ = release()
        data = json.loads(raw)
        verifier.validate_offer_labels(data)
        offer = data['details']['product']['variants']['variant']['offers'][0]['offer']
        for bad_region in ['美国 市场 · EUR 报价', '英国 市场 · USD 报价']:
            offer['sales_region'] = bad_region
            with self.subTest(region=bad_region), self.assertRaises(verifier.VerificationError):
                verifier.validate_offer_labels(data)
        offer['sales_region'] = '地区未核实 市场 · USD 报价'
        verifier.validate_offer_labels(data)
        offer.update(sales_region='legacy label', collection_state='retained')
        verifier.validate_offer_labels(data)

    def test_workflow_validates_build_before_deploy(self):
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/pages.yml').read_text()
        self.assertLess(workflow.index('python scripts/verify_public_release.py --local-dir _site'),workflow.index('name: Deploy public website'))

    def test_predeployment_validation_checks_local_bytes_without_network(self):
        manifest, raw, html = release()
        with tempfile.TemporaryDirectory() as tmp, patch.object(verifier, 'fetch_bytes') as network:
            root=Path(tmp);(root/'data').mkdir()
            (root/'data/publication.json').write_text(json.dumps(manifest))
            (root/'data/site-data.json').write_bytes(raw)
            (root/'index.html').write_bytes(html)
            receipt=verifier.validate_local_release(root,COMMIT)
            self.assertEqual(receipt['snapshot_bytes'],len(raw))
            network.assert_not_called()

    def test_predeployment_validation_blocks_coherent_but_wrong_market_label(self):
        manifest, raw, html = release()
        data=json.loads(raw)
        data['details']['product']['variants']['variant']['offers'][0]['offer']['sales_region']='欧洲站 EUR 报价'
        raw=rehash(manifest,data)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir()
            (root/'data/publication.json').write_text(json.dumps(manifest))
            (root/'data/site-data.json').write_bytes(raw)
            (root/'index.html').write_bytes(html)
            with self.assertRaisesRegex(verifier.VerificationError,'market/currency label'):
                verifier.validate_local_release(root,COMMIT)

    def test_command_reads_environment_and_prints_json_receipt(self):
        receipt = {'commit': COMMIT, 'verified_public_url': BASE}
        with patch.dict(os.environ, {'GITHUB_SHA': COMMIT, 'BIKEHUNT_PUBLIC_URL': BASE}), \
                patch.object(verifier, 'verify_public_release', return_value=receipt) as verify, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            verifier.main([])
        verify.assert_called_once_with(BASE, COMMIT, expected_run_id=None, expected_run_attempt=None)
        self.assertEqual(json.loads(output.getvalue()), receipt)

class SplitPublicReleaseTests(unittest.TestCase):
    """Schema 2 validates both byte streams without rewriting catalog timestamps."""
    setUp = PublicReleaseTests.setUp

    def test_split_fetches_bound_catalog_status_then_html(self):
        manifest, raw, status_raw, html = split_release()
        snapshot = json.loads(raw)
        status = json.loads(status_raw)
        with patch.object(verifier, 'fetch_bytes',
                          side_effect=[json.dumps(manifest).encode(), raw, status_raw, html]) as fetch:
            receipt = verifier.verify_public_release(BASE, COMMIT, attempts=1)
        urls = [call.args[0] for call in fetch.call_args_list]
        self.assertEqual([urlsplit(url).path for url in urls], [
            '/BikeHunt/data/publication.json', '/BikeHunt/data/site-data.json',
            '/BikeHunt/data/verification.json', '/BikeHunt/'])
        self.assertTrue(all(parse_qs(urlsplit(url).query)['version'] == [manifest['version']]
                            for url in urls[1:3]))
        self.assertEqual(receipt['generated_at'], manifest['generated_at'])
        self.assertEqual(receipt['publication']['version'], manifest['version'])
        self.assertEqual(receipt['snapshot_publication'], snapshot['publication'])
        self.assertEqual(receipt['snapshot_generated_at'], snapshot['generated_at'])
        self.assertEqual(receipt['verification'], status)
        self.assertEqual(receipt['collection_status'], status['collection_status'])
        self.assertNotEqual(receipt['generated_at'], receipt['snapshot_generated_at'])

    def test_exact_run_and_attempt_reject_same_commit_previous_publication(self):
        manifest, raw, status_raw, html = split_release()
        status = json.loads(status_raw)
        status.update(run_id='1234', run_attempt='2')
        status_raw = rehash_status(manifest, status)
        for expected_run, expected_attempt, valid in [('1234', '2', True), ('1233', '2', False), ('1234', '1', False)]:
            with self.subTest(run=expected_run, attempt=expected_attempt), patch.object(
                    verifier, 'fetch_bytes', side_effect=[json.dumps(manifest).encode(), raw, status_raw, html]):
                if valid:
                    receipt = verifier.verify_public_release(BASE, COMMIT, attempts=1,
                        expected_run_id=expected_run, expected_run_attempt=expected_attempt)
                    self.assertEqual(receipt['verification']['run_id'], '1234')
                else:
                    with self.assertRaisesRegex(RuntimeError, 'different workflow'):
                        verifier.verify_public_release(BASE, COMMIT, attempts=1,
                            expected_run_id=expected_run, expected_run_attempt=expected_attempt)

    def test_split_accepts_older_catalog_identity_and_exact_reused_bytes(self):
        first, raw, _, _ = split_release()
        second, identical_raw, status_raw, _ = split_release('2026-10-15T13:00:00+00:00')
        self.assertEqual(raw, identical_raw)
        self.assertEqual(first['snapshot'], second['snapshot'])
        self.assertNotEqual(first['version'], second['version'])
        data = verifier.validate_snapshot(second, raw, COMMIT)
        checked = verifier.verify_status(second, status_raw, data, COMMIT)
        self.assertEqual(checked['generated_at'], second['generated_at'])
        self.assertNotEqual(checked['version'], data['publication']['version'])

    def test_split_status_rejects_a_different_catalog_argument(self):
        for field, value in [('version', 'different'), ('commit', OLD_COMMIT),
                             ('generated_at', '2026-10-13T12:00:00Z')]:
            manifest, raw, status_raw, _ = split_release()
            data = json.loads(raw)
            (data if field == 'generated_at' else data['publication'])[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                    verifier.VerificationError, 'catalog argument differs'):
                verifier.verify_status(manifest, status_raw, data, COMMIT)

    def test_split_rejects_status_byte_length_hash_and_reserialization(self):
        manifest, raw, status_raw, _ = split_release()
        data = verifier.validate_snapshot(manifest, raw, COMMIT)
        for bad, message in [(status_raw[:-1], 'Status byte length'),
                             (status_raw.replace(b'current', b'invalid'), 'Status SHA-256')]:
            with self.subTest(message=message), self.assertRaisesRegex(verifier.VerificationError, message):
                verifier.verify_status(manifest, bad, data, COMMIT)
        equivalent = json.dumps(json.loads(status_raw), ensure_ascii=False, indent=2).encode()
        manifest['status']['bytes'] = len(equivalent)
        with self.assertRaisesRegex(verifier.VerificationError, 'Status SHA-256'):
            verifier.verify_status(manifest, equivalent, data, COMMIT)

    def test_split_rejects_unbound_status_even_with_correct_hash(self):
        for field, value in [('schema_version', True), ('schema_version', 2),
                             ('version', 'different'), ('generated_at', '2026-10-15T11:00:00+00:00'),
                             ('commit', OLD_COMMIT), ('snapshot_sha256', '0' * 64)]:
            manifest, raw, status_raw, _ = split_release()
            status = json.loads(status_raw)
            status[field] = value
            changed = rehash_status(manifest, status)
            with self.subTest(field=field), self.assertRaises(verifier.VerificationError):
                verifier.verify_status(manifest, changed, json.loads(raw), COMMIT)

    def test_split_rejects_unsafe_paths_and_invalid_metadata_before_fetch(self):
        for section, field, value in [
                ('snapshot', 'path', '../site-data.json'),
                ('status', 'path', 'https://other.example/verification.json'),
                ('status', 'path', 'data/../verification.json'),
                ('status', 'path', '/data/verification.json'),
                ('status', 'bytes', True), ('status', 'bytes', 0),
                ('status', 'sha256', 'bad'), ('snapshot', 'semantic_sha256', 'bad'),
                ('snapshot', 'commit', OLD_COMMIT), ('snapshot', 'version', 'different'),
                ('snapshot', 'generated_at', '2026-10-15T13:00:00+00:00')]:
            manifest, _, _, _ = split_release()
            manifest[section][field] = value
            with self.subTest(section=section, field=field, value=value), \
                    patch.object(verifier, 'fetch_bytes', return_value=json.dumps(manifest).encode()) as fetch:
                with self.assertRaises(RuntimeError):
                    verifier.verify_public_release(BASE, COMMIT, attempts=1)
                self.assertEqual(fetch.call_count, 1)
        manifest, _, _, _ = split_release()
        manifest.pop('status')
        with self.assertRaisesRegex(verifier.VerificationError, 'status metadata missing'):
            verifier.validate_manifest(manifest, COMMIT)

    def test_split_rejects_snapshot_own_identity_conflicts(self):
        for field, value in [('commit', OLD_COMMIT), ('version', 'other-catalog'),
                             ('generated_at', '2026-10-13T12:00:00+00:00')]:
            manifest, raw, _, _ = split_release()
            data = json.loads(raw)
            (data if field == 'generated_at' else data['publication'])[field] = value
            changed = rehash(manifest, data)
            with self.subTest(field=field), self.assertRaises(verifier.VerificationError):
                verifier.validate_snapshot(manifest, changed, COMMIT)

    def test_split_rejects_semantic_changes_hidden_behind_rehashed_bytes(self):
        manifest, raw, _, _ = split_release()
        data = json.loads(raw)
        data['catalog']['items'][0]['reference_price'] = {'amount': '1', 'currency': 'USD'}
        changed = rehash(manifest, data)
        with self.assertRaisesRegex(verifier.VerificationError, 'semantic SHA-256'):
            verifier.validate_snapshot(manifest, changed, COMMIT)

    def test_split_reconstructs_offer_identity_instead_of_trusting_map(self):
        manifest, raw, _, _ = split_release()
        data = json.loads(raw)
        offer = data['details']['product']['variants']['variant']['offers'][0]['offer']
        offer['price']['currency'] = 'EUR'
        # Changing both file/semantic hashes cannot hide a false content identity.
        changed = rehash_split_snapshot(manifest, data)
        with self.assertRaisesRegex(verifier.VerificationError, 'Snapshot offer content identity'):
            verifier.validate_snapshot(manifest, changed, COMMIT)

    def test_split_requires_exact_snapshot_and_status_offer_ids(self):
        for target, mutation in [
                ('snapshot', lambda data: data['verification_identities'].clear()),
                ('snapshot', lambda data: data['verification_identities'].update(extra='0' * 64)),
                ('status', lambda data: data['offers'].clear()),
                ('status', lambda data: data['offers'].update(extra=copy.deepcopy(data['offers']['shop-blue-M'])))]:
            manifest, raw, status_raw, _ = split_release()
            data, status = json.loads(raw), json.loads(status_raw)
            mutation(data if target == 'snapshot' else status)
            with self.subTest(target=target), self.assertRaisesRegex(verifier.VerificationError, 'offer IDs'):
                if target == 'snapshot':
                    verifier.validate_snapshot(manifest, rehash_split_snapshot(manifest, data), COMMIT)
                else:
                    verifier.verify_status(manifest, rehash_status(manifest, status), data, COMMIT)

    def test_split_rejects_status_identity_or_state_changes_without_new_catalog(self):
        for field, value in [('content_sha256', '0' * 64), ('collection_state', 'retained'),
                             ('collection_state', 'unknown')]:
            manifest, raw, status_raw, _ = split_release()
            status = json.loads(status_raw)
            status['offers']['shop-blue-M'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(verifier.VerificationError):
                verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)

    def test_split_rejects_missing_or_wrong_catalog_reference_offer(self):
        for reference in [None, '', 'other-offer']:
            manifest, raw, _, _ = split_release()
            data = json.loads(raw)
            data['catalog']['items'][0]['reference_offer_id'] = reference
            with self.subTest(reference=reference), self.assertRaisesRegex(
                    verifier.VerificationError, 'reference offer ID'):
                verifier.validate_snapshot(manifest, rehash_split_snapshot(manifest, data), COMMIT)

    def test_split_rejects_duplicate_offer_with_conflicting_content(self):
        manifest, raw, _, _ = split_release()
        data = json.loads(raw)
        variants = data['details']['product']['variants']
        variants['duplicate'] = copy.deepcopy(variants['variant'])
        variants['duplicate']['offers'][0]['offer']['sales_region'] = 'different'
        with self.assertRaisesRegex(verifier.VerificationError, 'Conflicting duplicate'):
            verifier.validate_snapshot(manifest, rehash_split_snapshot(manifest, data), COMMIT)

    def test_split_rejects_fx_identity_stale_state_and_invalid_timestamp(self):
        for field, value in [('snapshot_id', 'different'), ('stale', True), ('stale', 0),
                             ('fetched_at', '2026-10-15T10:00:00'),
                             ('fetched_at', '2026-10-13T10:00:00+00:00'),
                             ('fetched_at', '2026-10-15T13:00:00+00:00')]:
            manifest, raw, status_raw, _ = split_release()
            status = json.loads(status_raw)
            status['fx'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(verifier.VerificationError):
                verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)

    def test_split_rejects_naive_regressed_future_and_missing_observation_times(self):
        for timestamp in [None, '', '2026-10-15T11:00:00', '2026-10-15',
                          '2026-02-29T11:00:00Z', '2026-10-13T11:00:00+00:00',
                          '2026-10-15T12:00:00.000001+00:00']:
            manifest, raw, status_raw, _ = split_release()
            status = json.loads(status_raw)
            status['offers']['shop-blue-M']['fetched_at'] = timestamp
            with self.subTest(timestamp=timestamp), self.assertRaises(verifier.VerificationError):
                verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)
        manifest, raw, status_raw, _ = split_release()
        status = json.loads(status_raw)
        status['offers']['shop-blue-M'].pop('fetched_at')
        with self.assertRaisesRegex(verifier.VerificationError, 'fetched_at missing'):
            verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)

    def test_split_accepts_null_unknown_offer_and_fx_times_without_inventing_them(self):
        manifest, raw, status_raw, _ = split_release()
        data, status = json.loads(raw), json.loads(status_raw)
        detail = data['details']['product']['variants']['variant']
        detail['offers'][0]['offer']['fetched_at'] = None
        for fx in [data['catalog']['fx'], data['updates']['fx'], detail['fx']]:
            fx['fetched_at'] = None
        status['offers']['shop-blue-M']['fetched_at'] = None
        status['fx']['fetched_at'] = None
        raw = rehash_split_snapshot(manifest, data)
        status['snapshot_sha256'] = manifest['snapshot']['sha256']
        checked = verifier.verify_status(manifest, rehash_status(manifest, status),
                                         verifier.validate_snapshot(manifest, raw, COMMIT), COMMIT)
        self.assertIsNone(checked['offers']['shop-blue-M']['fetched_at'])
        self.assertIsNone(checked['fx']['fetched_at'])

    def test_split_retained_offers_cannot_get_new_verification_times(self):
        manifest, raw, status_raw, _ = split_release()
        data, status = json.loads(raw), json.loads(status_raw)
        offer = data['details']['product']['variants']['variant']['offers'][0]['offer']
        offer['collection_state'] = 'retained'
        data['catalog']['items'][0]['reference_collection_state'] = 'retained'
        data['verification_identities']['shop-blue-M'] = verifier.offer_identity(offer)
        raw = rehash_split_snapshot(manifest, data)
        status['snapshot_sha256'] = manifest['snapshot']['sha256']
        status['offers']['shop-blue-M'].update(collection_state='retained',
                content_sha256=data['verification_identities']['shop-blue-M'])
        with self.assertRaisesRegex(verifier.VerificationError, 'Retained offer verification time changed'):
            verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)
        status['offers']['shop-blue-M']['fetched_at'] = offer['fetched_at']
        verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)
        status['offers']['shop-blue-M']['fetched_at'] = '2026-10-14T11:00:00Z'
        verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)

    def test_split_newer_source_failure_or_product_error_requires_retained_state(self):
        for failure in [{'status': 'failed'},
                        {'status': 'partial', 'errors': [{'url': 'https://shop.example/blue?variant=L'}]}]:
            manifest, raw, status_raw, _ = split_release()
            status = json.loads(status_raw)
            status['collection_status']['shop'].update(failure)
            with self.subTest(failure=failure), self.assertRaisesRegex(
                    verifier.VerificationError, 'Failed source offer is not retained'):
                verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)
        status['collection_status']['shop']['errors'] = [{'url': 'https://shop.example/other'}]
        verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)

    def test_split_failed_source_cannot_claim_newer_time_as_recovery(self):
        manifest, raw, status_raw, _ = split_release()
        status = json.loads(status_raw)
        status['collection_status']['shop'].update(status='failed', attempted_at='2026-10-15T10:00:00Z')
        with self.assertRaisesRegex(verifier.VerificationError, 'Failed source cannot renew'):
            verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)

    def test_split_validates_all_source_process_identities_and_attempt_times(self):
        for update in [{'source_code': 'another'}, {'attempted_at': '2026-10-15T10:00:00'},
                       {'attempted_at': '2026-10-15T13:00:00Z'}, {'errors': None},
                       {'errors': ['malformed']}]:
            manifest, raw, status_raw, _ = split_release()
            status = json.loads(status_raw)
            # Validate even successful sources with no matching current catalog offer.
            status['collection_status']['unlisted-source'] = {'status': 'success', **update}
            with self.subTest(update=update), self.assertRaises(verifier.VerificationError):
                verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)

    def test_split_rejects_inconsistent_fx_copies(self):
        for key, value in [('snapshot_id', 'other'), ('stale', True),
                           ('fetched_at', '2026-10-14T09:00:00Z')]:
            manifest, raw, status_raw, _ = split_release()
            data, status = json.loads(raw), json.loads(status_raw)
            data['updates']['fx'][key] = value
            raw = rehash_split_snapshot(manifest, data)
            status['snapshot_sha256'] = manifest['snapshot']['sha256']
            with self.subTest(key=key), self.assertRaisesRegex(verifier.VerificationError, 'FX copies'):
                verifier.verify_status(manifest, rehash_status(manifest, status), json.loads(raw), COMMIT)

    def test_split_label_checks_use_latest_collection_status(self):
        manifest, raw, status_raw, html = split_release()
        data, status = json.loads(raw), json.loads(status_raw)
        data['collection_status'] = {}
        data['details']['product']['variants']['variant']['offers'][0]['offer']['sales_region'] = '英国 市场 · USD 报价'
        data['verification_identities']['shop-blue-M'] = verifier.offer_identity(
            data['details']['product']['variants']['variant']['offers'][0]['offer'])
        raw = rehash_split_snapshot(manifest, data)
        status['snapshot_sha256'] = manifest['snapshot']['sha256']
        status['offers']['shop-blue-M']['content_sha256'] = data['verification_identities']['shop-blue-M']
        status_raw = rehash_status(manifest, status)
        with patch.object(verifier, 'fetch_bytes',
                          side_effect=[json.dumps(manifest).encode(), raw, status_raw, html]):
            with self.assertRaisesRegex(RuntimeError, 'country label'):
                verifier.verify_public_release(BASE, COMMIT, attempts=1)
        self.assertEqual(data['collection_status'], {})

    def test_split_retries_old_status_until_bound_release_arrives(self):
        _, _, old_status, _ = split_release('2026-10-15T11:30:00+00:00')
        manifest, raw, status_raw, html = split_release()
        encoded = json.dumps(manifest).encode()
        with patch.object(verifier, 'fetch_bytes', side_effect=[encoded, raw, old_status,
                encoded, raw, status_raw, html]) as fetch, patch.object(verifier.time, 'sleep') as sleep:
            receipt = verifier.verify_public_release(BASE, COMMIT, attempts=2, retry_delay=0.25)
        self.assertEqual(receipt['verification']['version'], manifest['version'])
        sleep.assert_called_once_with(0.25)
        self.assertEqual(parse_qs(urlsplit(fetch.call_args_list[3].args[0]).query)['attempt'], ['1'])

    def test_split_never_reports_success_with_unbound_status(self):
        manifest, raw, status_raw, _ = split_release()
        status = json.loads(status_raw)
        status['snapshot_sha256'] = '0' * 64
        invalid = rehash_status(manifest, status)
        with patch.object(verifier, 'fetch_bytes',
                          side_effect=[json.dumps(manifest).encode(), raw, invalid] * 2) as fetch, \
                patch.object(verifier.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Status snapshot SHA-256'):
                verifier.verify_public_release(BASE, COMMIT, attempts=2)
        self.assertEqual(fetch.call_count, 6)

    def test_split_local_validation_requires_both_exact_files_without_network(self):
        manifest, raw, status_raw, html = split_release()
        with tempfile.TemporaryDirectory() as tmp, patch.object(verifier, 'fetch_bytes') as network:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'data/publication.json').write_text(json.dumps(manifest))
            (root / 'data/site-data.json').write_bytes(raw)
            (root / 'index.html').write_bytes(html)
            with self.assertRaises(FileNotFoundError):
                verifier.validate_local_release(root, COMMIT)
            (root / 'data/verification.json').write_bytes(status_raw)
            receipt = verifier.validate_local_release(root, COMMIT)
            self.assertEqual(receipt['status_bytes'], len(status_raw))
            self.assertEqual(receipt['snapshot_bytes'], len(raw))
            (root / 'data/verification.json').write_bytes(status_raw[:-1])
            with self.assertRaisesRegex(verifier.VerificationError, 'Status byte length'):
                verifier.validate_local_release(root, COMMIT)
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
