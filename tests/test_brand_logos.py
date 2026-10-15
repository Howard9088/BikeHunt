"""Official directory artwork must stay local, attributable, inert and unmodified."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import unittest
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SVG_NS = 'http://www.w3.org/2000/svg'
EXPECTED_BRANDS = {'maap', 'rapha', 'assos', 'castelli', 'santini', 'pns', 'poc', 'kask', 'fizik', 'oakley'}
# Hashes are of official source artwork, not a recreation in a substitute font.
ASSETS = {
    'maap': ('664e49fc71db5831e45e76d7f3cc071d61e26d1e3d27cdf6bf2b8bcf4a30d279', '0 0 76 20', 'maap.cc'),
    'assos': ('0e5d84f0660f844ca7c0267c17c3588f90a6df75805ce3e2aef49b4a02a0cea1', '0 0 330 200', 'www.assos.com'),
    'castelli': ('70e10730b54fee14707d7700fb77f8462cf0d674cedd42682ca6f4ed811f129c', '0 0 800 83', 'www.castelli-cycling.com'),
    'santini': ('8ebba08d6590eb4103b6d8c4917c5c794f67ac8c2e51adb6e8db4eaed6ce1b90', '0 0 1920 393.62', 'www.santinicycling.com'),
    'pns': ('3a20c9e3c7d26c555cbd471e4c9ad11844070454a20333cd8e688fcd888d529c', '0 0 106 40', 'pasnormalstudios.com'),
    'kask': ('832a6b61621f8e81a8f4b3d4be338007a9a511fdccf4c4a707ea5e73d1b74c11', '0 0 95 26', 'www.kask.com'),
    'fizik': ('60f92f36477e738bd6bf30037b8687c6c3993e5fda7f1f09604b900cf3bcab79', '0 0 71.67 20', 'www.fizik.com'),
}


class BrandLogoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = json.loads((ROOT / 'data/directories.json').read_text(encoding='utf-8'))
        cls.brands = {entry['code']: entry for entry in cls.directory['brands']}

    def test_brand_directory_stays_distinct_from_teams_and_retailers(self):
        self.assertEqual(set(self.brands), EXPECTED_BRANDS)
        self.assertEqual(len(self.directory['brands']), len(EXPECTED_BRANDS))
        self.assertTrue(set(self.brands).isdisjoint(entry['code'] for entry in self.directory['teams']))
        self.assertNotIn('amazon', self.brands)
        self.assertEqual(self.brands['pns']['name'], 'Pas Normal Studios')

    def test_seven_official_assets_have_local_paths_and_source_metadata(self):
        for code, (_, _, host) in ASSETS.items():
            with self.subTest(code=code):
                entry = self.brands[code]
                self.assertEqual(entry['logo_images'], [f'/web/assets/brands/{code}.svg'])
                self.assertEqual(entry['logo_theme'], 'light')
                self.assertEqual(len(entry['logo_source_urls']), 1)
                for source in [entry['logo_evidence_url'], *entry['logo_source_urls']]:
                    url = urlparse(source)
                    self.assertEqual(url.scheme, 'https')
                    self.assertEqual(url.hostname, host)
                checked = datetime.fromisoformat(entry['logo_checked_at'].replace('Z', '+00:00'))
                self.assertIsNotNone(checked.tzinfo)
                self.assertEqual(checked.date().isoformat(), '2026-10-15')

    def test_official_svg_bytes_and_viewports_are_preserved(self):
        for code, (expected_hash, expected_viewbox, _) in ASSETS.items():
            with self.subTest(code=code):
                path = ROOT / self.brands[code]['logo_images'][0].lstrip('/')
                data = path.read_bytes()
                self.assertGreater(len(data), 100)
                self.assertLess(len(data), 20_000)
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected_hash)
                svg = ET.fromstring(data)
                self.assertEqual(svg.tag, f'{{{SVG_NS}}}svg')
                self.assertEqual(svg.get('viewBox'), expected_viewbox)
                values = [float(value) for value in svg.get('viewBox').split()]
                self.assertEqual(len(values), 4)
                self.assertTrue(all(math.isfinite(value) for value in values))
                self.assertGreater(values[2], 0)
                self.assertGreater(values[3], 0)
                self.assertTrue(svg.findall(f'.//{{{SVG_NS}}}path'))

    def test_assets_do_not_execute_or_hotlink(self):
        for code in [*ASSETS, 'rapha']:
            with self.subTest(code=code):
                data = (ROOT / f'web/assets/brands/{code}.svg').read_text(encoding='utf-8')
                self.assertNotRegex(data.lower(), r'<!doctype|<!entity|javascript:')
                svg = ET.fromstring(data)
                for node in svg.iter():
                    tag = node.tag.rsplit('}', 1)[-1].lower()
                    self.assertNotIn(tag, {'script', 'foreignobject', 'image', 'iframe', 'animate', 'set'})
                    for key, value in node.attrib.items():
                        name = key.rsplit('}', 1)[-1].lower()
                        self.assertFalse(name.startswith('on'), (code, name))
                        if name in {'href', 'src'}:
                            self.assertTrue(value.startswith('#'), (code, value))
                for target in re.findall(r'url\(\s*[\'"]?([^\)\'\"]+)', data, flags=re.I):
                    self.assertTrue(target.strip().startswith('#'), (code, target))

    def test_rapha_is_unchanged_and_restricted_sources_keep_names(self):
        self.assertEqual(self.brands['rapha']['logo_images'], ['/web/assets/brands/rapha.svg'])
        data = (ROOT / 'web/assets/brands/rapha.svg').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), 'bd168607ffc195bbfb7935615bc849dd4968e256890180960710802bfa255dc8')
        for code in ['poc', 'oakley']:
            self.assertFalse(self.brands[code].get('logo_images'))
            self.assertEqual(self.brands[code]['name'].lower(), code)
        self.assertIn('#94D500', (ROOT / 'web/assets/brands/kask.svg').read_text())


if __name__ == '__main__':
    unittest.main()
