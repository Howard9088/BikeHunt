"""GitHub Pages 导出独立 Mock 测试：python tests/test_pages.py。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
