"""Public browser icons share the approved vector geometry and project scope."""
import json
import re
import shutil
import struct
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import test_pages
import unittest

ROOT=Path(__file__).resolve().parents[1]

class BrowserIconTests(unittest.TestCase):
    setUp = test_pages.PagesTests.setUp
    def test_real_icons_export_with_project_scoped_urls(self):
        shutil.copytree(ROOT/'web/icons',self.root/'web/icons')
        shutil.copy2(ROOT/'web/index.html',self.root/'web/index.html')
        from app.pages import build_public_site
        from test_catalog import make_fx
        build_public_site(self.root,make_fx())
        out=self.root/'_site'
        html=(out/'index.html').read_text()
        for href in re.findall(r'href="([^"]*(?:icons/)[^"]*)"',html):
            self.assertIn('?v=20261014-logo1',href)
            absolute=urljoin('https://owner.github.io/BikeHunt/',href)
            self.assertTrue(absolute.startswith('https://owner.github.io/BikeHunt/web/icons/'))
            self.assertTrue((out/urlsplit(href).path.removeprefix('./')).is_file())
        self.assertIn('<title>BikeHunt</title>',html)
        self.assertIn('name="apple-mobile-web-app-title" content="BikeHunt"',html)
        icons=out/'web/icons'
        manifest=json.loads((icons/'site.webmanifest').read_text())
        self.assertEqual(manifest['name'],'BikeHunt')
        self.assertEqual(manifest['short_name'],'BikeHunt')
        base='https://owner.github.io/BikeHunt/web/icons/site.webmanifest'
        for key in ['id','start_url','scope']:
            self.assertEqual(urljoin(base,manifest[key]),'https://owner.github.io/BikeHunt/')
        for name,size in [('favicon-16.png',16),('favicon-32.png',32),('apple-touch-icon.png',180),('icon-192.png',192),('icon-512.png',512)]:
            raw=(icons/name).read_bytes()
            self.assertEqual(raw[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II',raw[16:24]),(size,size))
        raw=(icons/'favicon.ico').read_bytes()
        self.assertEqual(struct.unpack('<HHH',raw[:6]),(0,1,3))
        self.assertEqual({(raw[6+i*16],raw[7+i*16]) for i in range(3)},{(16,16),(32,32),(48,48)})
        svg=(icons/'favicon.svg').read_text()
        source=(ROOT/'web/index.html').read_text()
        for shape in re.findall(r'<(?:circle|path)\b[^>]*>',re.search(r'<svg class="bikehunt-mark".*?</svg>',source).group()):
            self.assertIn(shape.replace('currentColor','#202631'),svg)
