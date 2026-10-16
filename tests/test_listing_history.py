import copy
import unittest
from app.catalog.listings import (bootstrap_legacy, prepare_listing_history,
    confirm_public_listing, first_listed_at, validate_ledger)

def family(key, alias=None, available=True):
    return {'product_id':key,'aliases':[(alias or key)*64], 'available':available}

class ListingHistoryTests(unittest.TestCase):
    def confirm(self, ledger, rows, when='2026-10-16T12:44:58Z'):
        return confirm_public_listing(ledger,rows,verified_at=when,snapshot_sha256='d'*64,
            commit='e'*40,snapshot_generated_at='2026-10-16T12:40:00Z')
    def test_legacy_dates_are_unknown_even_on_later_refresh_and_receipt(self):
        old=family('a');base=bootstrap_legacy([old]);prepared=prepare_listing_history(base,[old])
        self.assertEqual(base,prepared)
        self.assertIsNone(first_listed_at(self.confirm(prepared,[old]),'a'))
    def test_only_verified_public_receipt_dates_new_available_family(self):
        old,new=family('a'),family('b');base=bootstrap_legacy([old])
        pending=prepare_listing_history(base,[old,new]);self.assertIsNone(first_listed_at(pending,'b'))
        self.assertNotIn('b',base['entries'])
        confirmed=self.confirm(pending,[old,new])
        self.assertEqual(first_listed_at(confirmed,'b'),'2026-10-16T12:44:58+00:00')
        self.assertIsNone(first_listed_at(confirmed,'a'))
        # Receipt retries, newer quotes, FX, and changed build times cannot reset it.
        self.assertEqual(self.confirm(confirmed,[old,new],'2026-10-17T12:44:58Z'),confirmed)
    def test_failed_build_missing_cache_and_unknown_stock_cannot_invent_dates(self):
        rows=[family('b',available=False)];pending=prepare_listing_history(bootstrap_legacy([]),rows)
        self.assertIsNone(first_listed_at(pending,'b'))
        self.assertEqual(self.confirm(pending,rows),pending)
        with self.assertRaises(ValueError):prepare_listing_history({},rows)
    def test_new_size_and_rekey_preserve_existing_family_date(self):
        row=family('b');pending=prepare_listing_history(bootstrap_legacy([]),[row])
        confirmed=self.confirm(pending,[row]);rekey=family('c',alias='b')
        recovered=prepare_listing_history(confirmed,[rekey])
        self.assertEqual(first_listed_at(recovered,'c'),first_listed_at(confirmed,'b'))
        self.assertIn('b',recovered['entries'])
    def test_sold_out_disappearance_and_return_never_rejuvenate(self):
        row=family('b');c=self.confirm(prepare_listing_history(bootstrap_legacy([]),[row]),[row])
        self.assertEqual(prepare_listing_history(c,[]),c)
        sold=family('b',available=False)
        self.assertEqual(self.confirm(prepare_listing_history(c,[sold]),[sold]),c)
        self.assertEqual(self.confirm(c,[row],'2026-10-18T12:00:00Z'),c)
    def test_merger_takes_oldest_or_unknown_not_newest(self):
        a,b=family('a'),family('b');base=prepare_listing_history(bootstrap_legacy([]),[a,b])
        first=self.confirm(base,[a]);both=self.confirm(first,[b],'2026-10-17T12:00:00Z')
        merged={'product_id':'c','aliases':['a'*64,'b'*64],'available':True}
        result=prepare_listing_history(both,[merged]);self.assertEqual(first_listed_at(result,'c'),first_listed_at(first,'a'))
        unknown=bootstrap_legacy([a]);unknown=prepare_listing_history(unknown,[b]);unknown=self.confirm(unknown,[b])
        self.assertIsNone(first_listed_at(prepare_listing_history(unknown,[merged]),'c'))
    def test_bad_receipt_dates_and_wrong_identity_rejected(self):
        row=family('b');p=prepare_listing_history(bootstrap_legacy([]),[row])
        for stamp in ['2026-10-16T12:00:00','invalid','2026-10-15T00:00:00Z']:
            with self.assertRaises(ValueError):self.confirm(p,[row],stamp)
        with self.assertRaises(ValueError):self.confirm(p,[family('b',alias='c')])
        bad=copy.deepcopy(p);bad['entries']['b']['first_listed_at']='2026-10-16T12:44:58Z'
        with self.assertRaises(ValueError):validate_ledger(bad)
    def test_model_date_is_explicit_optional_timezone_aware(self):
        from app.catalog.models import ProductCard
        from app.catalog.service import ComparisonCatalog
        from test_catalog import make_offer, make_fx, NOW
        card=ComparisonCatalog([make_offer()],make_fx(),NOW).search()[0]
        self.assertIsNone(card.first_listed_at)
        raw=card.model_dump(mode='json')
        raw['first_listed_at']='2026-10-16T12:44:58Z'
        dated=ProductCard.model_validate(raw)
        self.assertEqual(dated.first_listed_at.isoformat(),'2026-10-16T12:44:58+00:00')
        raw['first_listed_at']='2026-10-16T12:44:58'
        with self.assertRaises(ValueError):ProductCard.model_validate(raw)

if __name__=='__main__':unittest.main()
