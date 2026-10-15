"""Offline regression for exact-market, local real-page screenshot publishing."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.registration_guides import (read_registration_guides, validate_registration_guides,
                                     registration_assets, publish_registration_guides, TRUSTED_HOSTS)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def fixture():
    data = json.loads((ROOT / 'tests/fixtures/registration-guides.json').read_text())
    data['entries'] = [copy.deepcopy(next(e for e in data['entries'] if e['sourceCode'] == 'visma'))]
    return data


class RegistrationGuideTests(unittest.TestCase):
    def test_current_configuration_and_any_active_images_are_valid(self):
        # Adding new markets or withdrawing every image remains a valid release.
        data = read_registration_guides(ROOT)
        assets = registration_assets(ROOT, data)
        self.assertEqual(set(assets), {f['asset'] for e in data['entries'] if e['status'] == 'verified' for f in e['frames']})

    def test_four_amazon_markets_are_explicitly_unverified_and_separate(self):
        entries = [e for e in json.loads((ROOT / 'tests/fixtures/registration-guides.json').read_text())['entries'] if e['sourceCode'].startswith('amazon_')]
        self.assertEqual([(e['sourceCode'], e['salesRegion']) for e in entries], [
            ('amazon_us', '美国站'), ('amazon_uk', '英国站'), ('amazon_de', '德国站'), ('amazon_jp', '日本站')])
        for entry in entries:
            self.assertEqual(entry['status'], 'unverified')
            self.assertEqual(entry['frames'], [])
            self.assertIn('本次云端未能打开页面', entry['reviewReason'])

    def test_original_bytes_and_only_referenced_active_assets_are_published(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            output = Path(temp) / 'output'
            data = fixture()
            for frame in data['entries'][0]['frames']:
                path = source / 'web' / frame['asset']
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'\xff\xd8\xffTEST-ONLY-IMAGE-BYTES')
            self.assertEqual(publish_registration_guides(source, output, data), 3)
            self.assertEqual(json.loads((output / 'web/registration-guides.json').read_text()), data)
            for asset, path in registration_assets(source, data).items():
                self.assertEqual((output / 'web' / asset).read_bytes(), path.read_bytes())
            self.assertEqual(len(list((output / 'web/assets/registration').glob('*'))), 3)

    def test_safety_withdrawal_all_disabled_or_removed_does_not_block_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            data = fixture()
            entry = data['entries'][0]
            entry.update(status='needs_review', reviewReason='原站布局已变化，等待重新核对。')
            entry['frames'][0]['asset'] = 'assets/registration/removed-old-image.jpg'
            validate_registration_guides(data, NOW)
            self.assertEqual(publish_registration_guides(ROOT, temp, data), 0)
            self.assertFalse((Path(temp) / 'web/assets').exists())
            data['entries'] = []
            validate_registration_guides(data, NOW)
            self.assertEqual(publish_registration_guides(ROOT, temp, data), 0)

    def test_old_observation_date_is_not_an_invented_expiry(self):
        data = fixture()
        data['entries'][0]['frames'][0]['verifiedAt'] = '2000-01-01'
        self.assertEqual(validate_registration_guides(data, NOW)['entries'][0]['status'], 'verified')
        self.assertNotIn('expires', json.dumps(data))

    def test_rejects_missing_future_or_impossible_dates(self):
        for value in [None, '', '2030-01-01', '2026-02-30', '2026-10-15T04:17:00', '2026-10-15T99:99:99Z', '2026-10-15T24:00:00Z']:
            data = fixture()
            data['entries'][0]['frames'][0]['verifiedAt'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_registration_guides(data, NOW)

    def test_exact_source_host_no_retail_decathlon_alias_or_external_urls(self):
        self.assertNotIn('account.decathlon.com', TRUSTED_HOSTS['decathlon'])
        for value in ['https://evil.example/register/', 'https://www.teamvismaleaseabike.com.evil.example/register/',
                      'http://www.teamvismaleaseabike.com/register/', 'https://name@www.teamvismaleaseabike.com/register/',
                      'https://www.teamvismaleaseabike.com/register/?secret=anything',
                      'https://www.teamvismaleaseabike.com/register/#fragment', 'javascript:alert(1)',
                      'https://www.teamvismaleaseabike.com:443/register/']:
            data = fixture()
            data['entries'][0]['frames'][0]['sourceUrl'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_registration_guides(data, NOW)
        data = fixture()
        data['entries'][0]['sourceCode'] = 'decathlon'
        data['entries'][0]['frames'][0]['sourceUrl'] = 'https://account.decathlon.com/'
        with self.assertRaises(ValueError):
            validate_registration_guides(data, NOW)

    def test_rejects_external_traversal_encoded_and_non_image_assets(self):
        for value in ['https://evil.example/image.jpg', '//evil.example/a.jpg', '/web/assets/registration/a.jpg',
                      'assets/registration/../a.jpg', 'assets/registration/%2e%2e/a.jpg', 'assets/registration/a.svg',
                      'assets/registration/a.jpg?cache=1', 'assets/registration/a.jpg#x', 'assets/registration/a\\b.jpg']:
            data = fixture()
            data['entries'][0]['frames'][0]['asset'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_registration_guides(data, NOW)

    def test_rejects_missing_or_outside_root_active_asset(self):
        data = fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, 'missing or outside'):
                registration_assets(root, data)
            target = root / 'web/assets/registration'
            target.mkdir(parents=True)
            first = data['entries'][0]['frames'][0]
            (root / 'outside.jpg').write_bytes(b'\xff\xd8\xff')
            (root / 'web' / first['asset']).symlink_to(root / 'outside.jpg')
            with self.assertRaisesRegex(ValueError, 'missing or outside'):
                registration_assets(root, data)

    def test_rejects_duplicate_scope_invalid_scope_or_unknown_source(self):
        for change in ['duplicate', 'unknown', 'public_with_market', 'empty_market']:
            data = fixture()
            if change == 'duplicate':
                data['entries'].append(copy.deepcopy(data['entries'][0]))
            elif change == 'unknown':
                data['entries'][0]['sourceCode'] = '__proto__'
            elif change == 'public_with_market':
                data['entries'][0]['salesRegion'] = 'US'
            else:
                data['entries'][0].update(scope='market', salesRegion='')
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_registration_guides(data, NOW)

    def test_non_real_images_bad_annotations_and_missing_review_reason_rejected(self):
        for change in ['fake', 'x', 'bounds', 'nan', 'boolean', 'empty', 'reason']:
            data = fixture()
            entry, frame = data['entries'][0], data['entries'][0]['frames'][0]
            if change == 'fake':
                frame['screenshotKind'] = 'schematic'
            elif change == 'x':
                frame['annotations'][0]['x'] = '<script>'
            elif change == 'bounds':
                frame['annotations'][0]['width'] = 100
            elif change == 'nan':
                frame['annotations'][0]['x'] = float('nan')
            elif change == 'boolean':
                frame['annotations'][0]['x'] = True
            elif change == 'empty':
                frame['annotations'] = []
            else:
                entry['status'] = 'needs_review'
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_registration_guides(data, NOW)


if __name__ == '__main__':
    unittest.main()
