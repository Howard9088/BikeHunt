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
    html = ('世巡车队 bikehunt-mark purchaseDisclaimerInfo publicationInfo '
            f'data-release="{commit}"').encode('utf-8')
    return manifest, raw, html


def rehash(manifest, data):
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    manifest['snapshot'].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return raw


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
                    html.replace('bikehunt-mark', ''), html.replace('purchaseDisclaimerInfo', ''),
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
        verify.assert_called_once_with(BASE, COMMIT)
        self.assertEqual(json.loads(output.getvalue()), receipt)


if __name__ == '__main__':
    unittest.main(verbosity=2)
