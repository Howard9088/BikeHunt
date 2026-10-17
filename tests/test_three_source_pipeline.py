"""Exercise scheduled collect_offers dispatch using synthetic official-shaped pages."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_gobik as gobik
import test_oakley as oakley
import test_decathlon_cn as decathlon
from scripts import collect_offers
from app.collectors.fetch_policy import CapturedPage
from app.collectors.transport import CollectionError


class ThreeSourcePipelineTests(unittest.TestCase):
    def run_source(self, code, fixture, source, url, at, expected, *, variants=()):
        class Fetcher:
            def __init__(self, *args, **kwargs):
                self.deferred = {}
                self.variant_pages = []
                self.page_action = None
            def fetch(self, requested, **kwargs):
                body = fixture(requested)
                return CapturedPage(body.encode(), 200, requested, {},
                    'dynamic' if variants else 'static', at, list(variants))
        repository = Mock()
        repository.load.return_value = []
        settings = {'code': code, 'parser': code, 'domains': [urlsplit(url).hostname], 'urls': [url],
                    'fetch_policy': {'mode': 'dynamic' if variants else 'static'}}
        with tempfile.TemporaryDirectory() as d, patch.object(collect_offers, 'ROOT', Path(d)), \
                patch.object(collect_offers, 'PublicPageFetcher', Fetcher):
            (Path(d)/'data').mkdir()
            collect_offers._collect_source(settings, repository, {code: source})
        args = repository.save.call_args.args
        self.assertEqual(args[0], code)
        self.assertEqual(len(args[1]), expected)
        self.assertEqual(args[3], [])
        self.assertTrue(all(row.fetched_at == at and row.evidence_sha256 for row in args[1]))
        self.assertEqual(args[4]['collected_product_count'], 1)
        return args[1]

    def test_gobik_dispatch_uses_verified_inline_size_parser(self):
        rows = self.run_source('gobik', lambda _: gobik.page(), gobik.SOURCE, gobik.URL, gobik.NOW, 2)
        self.assertEqual({row.stock for row in rows}, {'in_stock', 'out_of_stock'})

    def test_oakley_dispatch_fetches_each_exact_upc(self):
        reverse = {upc: size for size, upc in oakley.UPCS.items()}
        def fixture(url):
            upc = parse_qs(urlsplit(url).query).get('variant', [None])[0]
            return oakley.document(size=reverse[upc] if upc else 'M')
        self.run_source('oakley', fixture, oakley.SOURCE, oakley.URL, oakley.NOW, len(reverse))

    def test_decathlon_dispatch_ignores_raw_page_and_uses_selected_capture(self):
        rows = self.run_source('decathlon_cn', lambda _: decathlon.dom(), decathlon.SOURCE,
            decathlon.URL, decathlon.NOW, 1, variants=[decathlon.fixture().encode()])
        self.assertEqual(rows[0].stock_quantity, 443)
        self.assertEqual(rows[0].identity.mpn, '8969603')


if __name__ == '__main__':
    unittest.main()
