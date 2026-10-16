"""Synthetic secrets must not cross public collection health boundaries."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from app.public_status import public_collection_status
from app.publication import build_publication
from test_seed_updates import payload, offer

SECRET='SYNTHETIC_PRIVATE_RESPONSE_DO_NOT_PUBLISH'
URL='https://example.org/product/known'
class PublicStatusTests(unittest.TestCase):
    def test_allowlist_never_repeats_exception_or_unknown_fields(self):
        raw={'mock':{'source_code':'mock','attempted_at':'2026-10-16T00:00:00Z','status':'failed',
            'new_offer_count':0,'retained_offer_count':1,'private':SECRET,
            'coverage':{'complete':False,'scope_note':SECRET},
            'errors':[{'url':URL,'error':SECRET,'body':SECRET,'retry_at':'2026-10-17T00:00:00Z'},
                      {'url':URL+'?token='+SECRET,'error':SECRET}]}}
        before=copy.deepcopy(raw);safe=public_collection_status(raw,{URL})
        self.assertNotIn(SECRET,json.dumps(safe));self.assertEqual(raw,before)
        self.assertEqual(safe['mock']['errors'][0],{'url':URL,'error':'collection_deferred','retry_at':'2026-10-17T00:00:00Z'})
        self.assertEqual(safe['mock']['errors'][1],{'error':'collection_failed'})
        self.assertEqual(safe['mock']['status'],'failed')
        self.assertEqual(safe['mock']['retained_offer_count'],1)
        self.assertEqual(public_collection_status(safe,{URL}),safe)

    def test_publication_rejects_poisoned_old_cache_even_same_semantics(self):
        data=payload([],0,[offer()]);data['collection_status']['mock']['errors']=[{'url':URL,'error':SECRET}]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'out';cache=root/'cache'
            build_publication(data,out,cache)
            for p in [cache/'site-data.json',out/'data/site-data.json',out/'data/verification.json']:
                self.assertNotIn(SECRET,p.read_text())
            bad=json.loads((cache/'site-data.json').read_text())
            bad['collection_status']['mock']['errors'][0]['error']=SECRET
            (cache/'site-data.json').write_text(json.dumps(bad))
            self.assertTrue(build_publication(data,out,cache)['catalog_changed'])
            self.assertNotIn(SECRET,(out/'data/site-data.json').read_text())
            self.assertIn(SECRET,json.dumps(data),'Caller local diagnostic record is preserved')

    def test_collection_failure_console_is_safe_local_diagnostic_preserved(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        from unittest.mock import patch, Mock
        from loguru import logger
        from scripts.collect_offers import collect_source, print_public_collection_result
        out, err = io.StringIO(), io.StringIO()
        sink = logger.add(err, format='{message}')
        self.addCleanup(logger.remove, sink)
        repository = Mock()
        with tempfile.TemporaryDirectory() as folder, patch('scripts.collect_offers.ROOT', Path(folder)), \
             patch('scripts.collect_offers.PublicPageFetcher') as fetcher, redirect_stdout(out), redirect_stderr(err):
            fetcher.return_value.fetch.side_effect = RuntimeError(SECRET)
            collect_source({'code':'mock','domains':['example.org'],'parser':'jsonld','urls':[URL]}, repository, {'mock':{'code':'mock'}})
            print_public_collection_result('mock',0,[{'error':SECRET,'url':URL+'?token='+SECRET,'retry_at':'2026-10-17T00:00:00Z'}])
        self.assertNotIn(SECRET,out.getvalue()+err.getvalue())
        self.assertIn('collection_failed',out.getvalue())
        self.assertIn('collection_deferred',out.getvalue())
        self.assertEqual(repository.save.call_args.args[3][0]['error'],SECRET)

    def test_collector_warning_sinks_do_not_interpolate_exception_bodies(self):
        root=Path(__file__).resolve().parents[1]
        for file in ['app/collectors/parsers.py','app/collectors/transport.py','scripts/collect_offers.py']:
            for line in (root/file).read_text().splitlines():
                if 'logger.warning(' in line or 'logger.error(' in line:
                    self.assertNotIn(', exc)',line)
