"""GitHub Pages 导出独立 Mock 测试：python tests/test_pages.py。"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.catalog.storage import atomic_json, OfferRepository
from app.pages import build_public_site
from test_catalog import NOW, make_fx, make_offer


class PagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        web = self.root/'web'; web.mkdir()
        for name in ('gallery.css','flows.css','profile.js','gallery.js','flows.js','pages-adapter.js'):
            (web/name).write_text('/* Mock public asset */',encoding='utf-8')
        (web/'index.html').write_text('<a href="/web/">Home</a><script src="/web/profile.js" defer></script>',encoding='utf-8')
        atomic_json(self.root/'data/sources.json',[{'code':'a','name':'Mock'}])
        atomic_json(self.root/'data/directories.json',{'brands':[],'teams':[]})
        OfferRepository(self.root/'data').save('a',[make_offer()],NOW,[])
        (self.root/'config').mkdir()
        (self.root/'config/notifications.json').write_text('{"app_token":"AT_private_do_not_publish"}',encoding='utf-8')

    def test_public_output_keeps_prices_and_all_exact_variants(self) -> None:
        result=build_public_site(self.root,make_fx())
        self.assertEqual(result['products'],1)
        data=json.loads((self.root/'_site/data/site-data.json').read_text(encoding='utf-8'))
        family=next(iter(data['details'].values()))
        self.assertEqual(family['variants'][family['default']]['offers'][0]['offer']['price']['amount'],'100')
        self.assertEqual(data['catalog']['source_count'],1)

    def test_export_never_copies_private_config_database_or_admin_forms(self) -> None:
        build_public_site(self.root,make_fx())
        paths=[str(p.relative_to(self.root/'_site')) for p in (self.root/'_site').rglob('*') if p.is_file()]
        self.assertFalse(any('config' in p or 'sqlite' in p or 'settings.html' in p for p in paths))
        content=(self.root/'_site/data/site-data.json').read_text(encoding='utf-8')
        self.assertNotIn('AT_private',content)
        self.assertNotIn('subscribers',content)

    def test_project_subdirectory_uses_relative_assets_and_adapter_first(self) -> None:
        build_public_site(self.root,make_fx())
        html=(self.root/'_site/index.html').read_text(encoding='utf-8')
        self.assertIn('href="./"',html)
        self.assertIn('src="./web/profile.js"',html)
        self.assertLess(html.index('pages-adapter.js'),html.index('profile.js'))

    def test_manifest_matches_exact_snapshot_bytes_and_publication_identity(self) -> None:
        commit = 'a' * 40
        with patch.dict(os.environ, {'GITHUB_SHA': commit}):
            result = build_public_site(self.root, make_fx())
        output = self.root / '_site'
        raw = (output / 'data/site-data.json').read_bytes()
        data = json.loads(raw)
        manifest = json.loads((output / 'data/publication.json').read_bytes())
        self.assertEqual(manifest, {
            'schema_version': 1,
            'version': commit + ':' + data['generated_at'],
            'generated_at': data['generated_at'],
            'commit': commit,
            'snapshot': {'path': 'data/site-data.json', 'bytes': len(raw),
                         'sha256': hashlib.sha256(raw).hexdigest()},
        })
        self.assertEqual(data['publication']['version'], manifest['version'])
        self.assertEqual(data['publication']['commit'], manifest['commit'])
        self.assertEqual(result['generated_at'], manifest['generated_at'])
        self.assertIn('data-release="' + commit + '"',
                      (output / 'index.html').read_text(encoding='utf-8'))
        self.assertLess((output / 'data/publication.json').stat().st_size, 1024)
        snapshots = []
        for path in output.rglob('*.json'):
            document = json.loads(path.read_bytes())
            if isinstance(document, dict) and document.get('mode') == 'published_snapshot':
                snapshots.append(path.relative_to(output).as_posix())
        self.assertEqual(snapshots, ['data/site-data.json'])

    def test_rebuilding_same_commit_changes_version_and_replaces_snapshot(self) -> None:
        start = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
        commit = 'b' * 40
        with patch.dict(os.environ, {'GITHUB_SHA': commit}), patch('app.pages.datetime') as clock:
            clock.now.side_effect = [start, start + timedelta(microseconds=1)]
            build_public_site(self.root, make_fx())
            first = json.loads((self.root / '_site/data/publication.json').read_bytes())
            build_public_site(self.root, make_fx())
            second = json.loads((self.root / '_site/data/publication.json').read_bytes())
        self.assertEqual(first['commit'], second['commit'])
        self.assertNotEqual(first['version'], second['version'])
        self.assertNotEqual(first['snapshot']['sha256'], second['snapshot']['sha256'])
        self.assertEqual(first['snapshot']['path'], second['snapshot']['path'])
        self.assertEqual(sorted(p.name for p in (self.root / '_site/data').iterdir()),
                         ['publication.json', 'site-data.json'])
        raw = (self.root / '_site/data/site-data.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), second['snapshot']['sha256'])
        self.assertEqual(json.loads(raw)['publication']['version'], second['version'])

    def test_local_manifest_uses_local_version_without_inventing_commit(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            build_public_site(self.root, make_fx())
        manifest = json.loads((self.root / '_site/data/publication.json').read_bytes())
        self.assertIsNone(manifest['commit'])
        self.assertEqual(manifest['version'], 'local:' + manifest['generated_at'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
