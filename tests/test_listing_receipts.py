"""Synthetic publication receipts; never merchant observation evidence."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from app.catalog.listings import (bootstrap_legacy,prepare_listing_history,confirm_public_listing,
    snapshot_families,recover_listing_history,first_listed_at,read_listing_history)
from app.catalog.storage import atomic_json
from test_seed_updates import payload,offer


def fixture():
    data=payload([],0,[offer()]);data['catalog']['items']=[{'product_id':'family','stock_state':'in_stock','reference_stock':'in_stock','reference_data_kind':'live_snapshot','fetched_at':offer().fetched_at.isoformat()}]
    families=snapshot_families(data)
    data['listing_history']=prepare_listing_history(bootstrap_legacy([]),families)
    manifest={'commit':'e'*40,'generated_at':'2026-10-16T12:40:00Z','snapshot':{'sha256':'d'*64}}
    confirmed=confirm_public_listing(data['listing_history'],families,verified_at='2026-10-16T12:44:58Z',snapshot_sha256='d'*64,commit='e'*40,snapshot_generated_at=manifest['generated_at'])
    return data,manifest,confirmed

class ListingReceiptTests(unittest.TestCase):
    def test_valid_receipt_cache_survives_next_run_without_new_date(self):
        data,manifest,confirmed=fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);atomic_json(root/'data/listing_receipts/ledger.json',confirmed)
            recovered=recover_listing_history(root,data,manifest)
            self.assertEqual(first_listed_at(recovered,'family'),'2026-10-16T12:44:58+00:00')
            self.assertEqual(read_listing_history(root),recovered)
            data['listing_history']=recovered
            (root/'data/listing_receipts/ledger.json').unlink()
            # After next normal publication, public ledger is the durable recovery source.
            self.assertEqual(recover_listing_history(root,data,manifest),recovered)
    def test_lost_wrong_commit_or_wrong_snapshot_cache_never_rejuvenates(self):
        for mode in ['missing','wrong_commit','wrong_sha','future','wrong_family']:
            data,manifest,confirmed=fixture()
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                if mode!='missing':
                    if mode=='wrong_commit':confirmed['entries']['family']['receipt']['commit']='f'*40
                    if mode=='wrong_sha':confirmed['entries']['family']['receipt']['snapshot_sha256']='f'*64
                    if mode=='future':
                        confirmed['entries']['family']['first_listed_at']='2099-01-01T00:00:00Z';confirmed['entries']['family']['receipt']['verified_at']='2099-01-01T00:00:00Z'
                    if mode=='wrong_family':confirmed['entries']['family']['aliases']=['f'*64]
                    atomic_json(root/'data/listing_receipts/ledger.json',confirmed)
                recovered=recover_listing_history(root,data,manifest)
                self.assertIsNone(first_listed_at(recovered,'family'))
                self.assertEqual(recovered['entries']['family']['state'],'legacy_unknown')
                self.assertEqual(confirm_public_listing(recovered,snapshot_families(data),verified_at='2026-10-17T12:00:00Z',snapshot_sha256='d'*64,commit='e'*40,snapshot_generated_at=manifest['generated_at']),recovered)
    def test_workflow_records_only_after_successful_public_check(self):
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/pages.yml').read_text()
        check=text.index('run: python scripts/verify_public_release.py --record-listings')
        save=text.index('- name: Persist successfully verified first listing receipts')
        self.assertGreater(save,check)
        self.assertNotIn('always()',text[save:])
        self.assertEqual(text.count('path: data/listing_receipts/ledger.json'),2)
        self.assertNotIn('contents: write',text)
    def test_migration_only_dates_exact_verified_gobik_members(self):
        root=Path(__file__).resolve().parents[1]
        ledger=json.loads((root/'data/listing_history.json').read_text())
        dated=[r for r in ledger['entries'].values() if r['state']=='confirmed']
        self.assertEqual(len(dated),19)
        self.assertEqual({r['receipt']['commit'] for r in dated},{'1ed1a22ee951d12f78e70306df9bb4045ac50847'})
        self.assertEqual({r['receipt']['snapshot_sha256'] for r in dated},{'27b461401098d2eb7e3cf7c745b207ecf74004827efc80ab725a2f4e3ae94295'})
        self.assertTrue(all(r['first_listed_at'] is None for r in ledger['entries'].values() if r['state']=='legacy_unknown'))

    def test_failed_public_verifier_never_writes_receipt(self):
        from unittest.mock import patch
        from scripts import verify_public_release as verifier
        with patch.dict('os.environ',{'GITHUB_SHA':'e'*40}), \
             patch.object(verifier,'verify_public_release',side_effect=RuntimeError('synthetic unavailable')), \
             patch('app.catalog.storage.atomic_json') as write:
            with self.assertRaises(RuntimeError):verifier.main(['--record-listings'])
            write.assert_not_called()
