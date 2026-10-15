"""Deterministic public group settings, safe export, and expiry tests."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.community import Community
from app.catalog.storage import atomic_json
from app.pages import build_public_site
import test_pages
from test_catalog import make_fx

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)
EXPIRY = datetime(2026, 10, 21, 16, tzinfo=timezone.utc)
PNG = b'\x89PNG\r\n\x1a\n'


def settings(**fields):
    return {"schema_version": 1, "revision": "2026-10-15", "title": "骑游海淘交流群",
            "image_url": "/web/assets/community/group-20261015.png",
            "expires_at": "2026-10-22T00:00:00+08:00", "expiry_label": "微信标注10月22日前有效", **fields}


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.service = Community(self.root)
        self.asset = self.root/'web/assets/community/group-20261015.png'
        self.asset.parent.mkdir(parents=True);self.asset.write_bytes(PNG)
        atomic_json(self.root/'data/community.json', settings())

    def test_public_fallback_and_exact_expiry_boundary(self):
        self.assertTrue(self.service.get(NOW)['available'])
        self.assertTrue(self.service.get(EXPIRY-timedelta(microseconds=1))['available'])
        for now in (EXPIRY, EXPIRY+timedelta(days=7)):
            result=self.service.get(now)
            self.assertFalse(result['available']);self.assertTrue(result['expired'])
            self.assertNotIn('image_url',result)

    def test_local_override_and_invalid_override_never_fall_back(self):
        atomic_json(self.root/'config/community.json',settings(title='本地群',app_token='private',subscribers=['private']))
        result=self.service.get(NOW)
        self.assertEqual(result['title'],'本地群');self.assertTrue(result['available'])
        self.assertNotIn('app_token',result);self.assertNotIn('subscribers',result)
        (self.root/'config/community.json').write_text('{broken')
        self.assertFalse(self.service.get(NOW)['available'])

    def test_invalid_unknown_expiry_and_unsafe_assets_fail_closed(self):
        for field,values in {
            'expires_at':[None,'','invalid','2026-10-22','2026-10-22T00:00:00','2026-02-30T00:00:00Z','2026-10-22T00:00:00+24:00'],
            'image_url':['https://evil.example/qr.png','//evil.example/qr.png','/web/assets/community/../../secret.png','/web/assets/community/%2e%2e.png','/web/assets/community/test.svg','/web/assets/community/missing.png','/web/assets/community/group-20261015.png?token=private'],
            'schema_version':[0,2,'1'], 'title':['',None,'x'*61],
        }.items():
            for value in values:
                with self.subTest(field=field,value=value):
                    atomic_json(self.root/'data/community.json',settings(**{field:value}))
                    result=self.service.get(NOW)
                    self.assertFalse(result['available']);self.assertNotIn('image_url',result)

    def test_symlink_cannot_export_files_outside_web(self):
        self.asset.unlink();outside=self.root/'private.png';outside.write_bytes(PNG)
        self.asset.symlink_to(outside)
        self.assertFalse(self.service.get(NOW)['available'])

    def test_unknown_expiry_cannot_be_saved_as_permanent(self):
        with self.assertRaisesRegex(ValueError,'有效期'):
            self.service.configure('骑游海淘交流群','data:image/png;base64,iVBORw0KGgo=')


class CommunityExportTests(unittest.TestCase):
    setUp = test_pages.PagesTests.setUp

    def test_public_group_page_paths_config_and_separate_stable_code(self):
        root_asset=self.root/'web/assets/community';root_asset.mkdir(parents=True)
        (root_asset/'group-20261015.png').write_bytes(PNG)
        (root_asset/'group-entry.png').write_bytes(PNG+b'stable')
        atomic_json(self.root/'data/community.json',settings(app_token='must-not-export'))
        with patch('app.community.datetime') as clock:
            clock.now.return_value=NOW
            # Parsing uses the actual datetime implementation.
            clock.fromisoformat.side_effect=datetime.fromisoformat
            build_public_site(self.root,make_fx())
        out=self.root/'_site';html=(out/'group/index.html').read_text()
        self.assertIn('data-community-source="../data/community.json"',html)
        self.assertIn('data-image-base="../"',html)
        self.assertIn('../web/group.js?v=',html)
        self.assertIn('../web/icons/favicon.ico',html)
        self.assertIn('<title>BikeHunt</title>',html)
        self.assertIn('id="groupQr"',html);self.assertNotIn('src="/web/assets/community',html)
        self.assertTrue((out/'web/assets/community/group-20261015.png').is_file())
        self.assertTrue((out/'web/assets/community/group-entry.png').is_file())
        public=json.loads((out/'data/community.json').read_text())
        self.assertTrue(public['available']);self.assertNotIn('must-not-export',json.dumps(public))
        with patch('app.community.datetime') as clock:
            clock.now.return_value=EXPIRY;clock.fromisoformat.side_effect=datetime.fromisoformat
            build_public_site(self.root,make_fx())
        public=json.loads((out/'data/community.json').read_text())
        self.assertTrue(public['expired']);self.assertNotIn('image_url',public)
        self.assertFalse((out/'web/assets/community/group-20261015.png').exists())
        self.assertTrue((out/'web/assets/community/group-entry.png').is_file())


if __name__=='__main__':unittest.main()
