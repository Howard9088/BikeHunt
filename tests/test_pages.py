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
from app.catalog.service import ComparisonCatalog
from app.publication import digest, semantic_projection
from test_catalog import NOW, make_fx, make_offer


class PagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        web = self.root/'web'; web.mkdir()
        for name in ('listing-order.js','public-visibility.js','gallery.css','flows.css','profile.js','gallery.js','flows.js','pages-adapter.js','group.js','group.css','registration-guides.js','purchase-readiness.js','purchase-readiness.json','payment-methods.js','payment-methods.json','payment-channels.json','purchase-flow.js','bundle-variants.js','external-exit.js','external-exit.css','visitor-stats.js'):
            (web/name).write_text('/* Mock public asset */',encoding='utf-8')
        repo = Path(__file__).resolve().parents[1]
        (web/'payment-channels.json').write_bytes((repo/'web/payment-channels.json').read_bytes())
        (web/'payment-methods.json').write_bytes((repo/'tests/fixtures/payment-methods.json').read_bytes())
        atomic_json(web/'registration-guides.json', {'schemaVersion': 1, 'revision': 'empty-test', 'entries': []})
        (web/'index.html').write_text('<a href="/web/">Home</a><script src="/web/profile.js" defer></script>',encoding='utf-8')
        (web/'why-overseas.html').write_text((repo/'web/why-overseas.html').read_text(), encoding='utf-8')
        (web/'group').mkdir()
        (web/'group/index.html').write_text(Path(__file__).resolve().parents[1].joinpath('web/group/index.html').read_text(), encoding='utf-8')
        (web/'assets/brands').mkdir(parents=True)
        (web/'assets/brands/amazon-official.png').write_bytes(b'Mock retailer image')
        atomic_json(self.root/'data/sources.json',[{'code':'a','name':'Mock'}])
        atomic_json(self.root/'data/directories.json',{'brands':[],'teams':[]})
        OfferRepository(self.root/'data').save('a',[make_offer()],NOW,[])
        (self.root/'config').mkdir()
        (self.root/'config/notifications.json').write_text('{"app_token":"AT_private_do_not_publish"}',encoding='utf-8')

    def test_why_overseas_article_is_public_and_links_home(self):
        repo = Path(__file__).resolve().parents[1]
        (self.root/'web/index.html').write_text((repo/'web/index.html').read_text(), encoding='utf-8')
        build_public_site(self.root, make_fx())
        home = (self.root/'_site/index.html').read_text()
        article = (self.root/'_site/why-overseas/index.html').read_text()
        self.assertIn('href="./why-overseas/">为什么海淘？</a>', home)
        self.assertIn('href="../"', article)
        self.assertIn('src="../web/icons/bikehunt-logo.svg"', article)
        self.assertIn('各有所爱，不必说服谁。', article)
        self.assertIn('便宜不能直接等于假货。', article)
        self.assertNotIn('<script', article)

    def test_private_collection_errors_are_projected_before_pages_and_cache(self):
        marker = 'SYNTHETIC_PRIVATE_ERROR_BODY'
        source = self.root/'data/collection_status/a.json'
        status = json.loads(source.read_text())
        status['errors'] = [{'url': make_offer().url, 'error': marker, 'response_body': marker}]
        atomic_json(source, status)
        build_public_site(self.root, make_fx())
        for path in (self.root/'_site').rglob('*.json'):
            self.assertNotIn(marker, path.read_text())
        self.assertNotIn(marker, (self.root/'data/publication_cache/site-data.json').read_text())
        self.assertIn(marker, source.read_text(), 'Local diagnostics stay local and unchanged')

    def test_all_public_assets_are_pinned_to_release_without_editing_source_index(self):
        commit = "a" * 40
        index = self.root / "web/index.html"
        original = Path(__file__).resolve().parents[1].joinpath("web/index.html").read_text(encoding="utf-8")
        index.write_text(original, encoding="utf-8")
        with patch.dict(os.environ, {"GITHUB_SHA": commit}):
            build_public_site(self.root, make_fx())
        html = (self.root / "_site/index.html").read_text(encoding="utf-8")
        for asset in ("public-visibility.js", "gallery.css", "flows.css", "profile.js", "gallery.js", "flows.js", "pages-adapter.js", "registration-guides.js", "purchase-readiness.js", "payment-methods.js", "purchase-flow.js", "bundle-variants.js", "external-exit.js", "external-exit.css", "visitor-stats.js"):
            self.assertIn(f'./web/{asset}?v={commit}', html)
        self.assertIn(f'data-release="{commit}"', html)
        self.assertEqual(index.read_text(encoding="utf-8"), original)
        self.assertLess(html.index('public-visibility.js'), html.index('pages-adapter.js'))
        self.assertLess(html.index('bundle-variants.js'), html.index('gallery.js'))
        self.assertLess(html.index('purchase-flow.js'), html.index('external-exit.js'))
        for asset in ('external-exit.js', 'external-exit.css','visitor-stats.js'):
            self.assertEqual((self.root/'_site/web'/asset).read_bytes(), (self.root/'web'/asset).read_bytes())
        self.assertEqual((self.root/'_site/web/bundle-variants.js').read_bytes(),
                         (self.root/'web/bundle-variants.js').read_bytes())

    def test_browse_groups_and_reference_evidence_are_published_and_hashed(self):
        from app.public_visibility import public_category_groups, public_categories, public_road_references
        from app.road_equipment import read_road_references
        root = Path(__file__).resolve().parents[1]
        refs = read_road_references(root)
        atomic_json(self.root/'data/road_equipment_references.json', refs)
        build_public_site(self.root, make_fx())
        data = json.loads((self.root/'_site/data/site-data.json').read_bytes())
        self.assertEqual(data['catalog']['category_groups'], public_category_groups())
        self.assertEqual(data['catalog']['categories'], public_categories())
        self.assertEqual(data['catalog']['road_equipment_references'], public_road_references(root))
        self.assertEqual(len(data['catalog']['items']), 1, 'Research is not mixed into live inventory')
        before = digest(semantic_projection(data))
        data['catalog']['road_equipment_references']['products'][0]['observation_note'] += ' Updated research context.'
        self.assertNotEqual(before, digest(semantic_projection(data)))

    def test_public_export_hides_bike_families_details_and_old_updates(self):
        from test_public_visibility import offers, classify
        rows = offers()
        # Replace the complete temporary fixture; save() deliberately retains unrelated old URLs.
        atomic_json(self.root/'data/offers/a.json', {
            'source_code': 'a', 'offers': [row.model_dump(mode='json') for row in rows]})
        from app.updates import UpdateStore
        store = UpdateStore(self.root)
        with store.connect() as db:
            db.execute('DELETE FROM events')
        store.capture([], rows)
        with patch('app.catalog.service.browse_classification', side_effect=classify):
            internal = ComparisonCatalog(rows, make_fx(), NOW)
            hidden_ids = {card.product_id for card in internal.search()
                          if card.category_group == 'road_equipment'}
            build_public_site(self.root, make_fx())
        data = json.loads((self.root/'_site/data/site-data.json').read_bytes())
        self.assertEqual([card['category'] for card in data['catalog']['items']], ['accessories'])
        self.assertEqual(data['catalog']['offer_count'], 1)
        self.assertEqual(data['catalog']['source_count'], 1)
        self.assertTrue(hidden_ids.isdisjoint(data['details']))
        self.assertEqual(set(data['details']), {card['product_id'] for card in data['catalog']['items']})
        self.assertEqual([row['offer_id'] for row in data['updates']['items']], ['bag'])
        self.assertEqual(len(OfferRepository(self.root/'data').load()), 3,
                         'Public projection never deletes saved internal offers')

    def test_official_amazon_channel_logo_is_copied_unchanged(self):
        build_public_site(self.root, make_fx())
        asset = 'web/assets/brands/amazon-official.png'
        self.assertEqual((self.root/'_site'/asset).read_bytes(), (self.root/asset).read_bytes())

    def test_published_cursor_keeps_reserved_history_floor(self):
        from app.updates import UpdateStore
        with UpdateStore(self.root).connect() as db:
            db.execute("UPDATE sqlite_sequence SET seq=1257 WHERE name='events'")
        build_public_site(self.root, make_fx())
        data = json.loads((self.root/'_site/data/site-data.json').read_bytes())
        self.assertEqual(data['updates']['cursor'], 1257)
        self.assertLess(max(row['id'] for row in data['updates']['items']), 1257)

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
        with (self.root/"web/index.html").open("a") as handle:
            handle.write('<script src="/web/gallery.js?v=old"></script><script src="/web/flows.js?v=old"></script>')
        build_public_site(self.root,make_fx())
        html=(self.root/'_site/index.html').read_text(encoding='utf-8')
        self.assertIn('href="./"',html)
        self.assertIn('src="./web/profile.js?v='+os.environ.get('GITHUB_SHA','local')+'"',html)
        self.assertLess(html.index('pages-adapter.js'),html.index('profile.js'))
        self.assertIn('src="./web/gallery.js?v='+os.environ.get('GITHUB_SHA','local')+'"', html)
        self.assertIn('src="./web/flows.js?v='+os.environ.get('GITHUB_SHA','local')+'"', html)

    def build_at(self, at, fx=None, commit="a" * 40):
        with patch.dict(os.environ, {"GITHUB_SHA": commit}), patch("app.pages.datetime") as clock, \
                patch("app.pages.ComparisonCatalog", side_effect=lambda offers, snapshot, **options:
                      ComparisonCatalog(offers, snapshot, at, **options)):
            clock.now.return_value = at
            return build_public_site(self.root, fx or make_fx())

    def publication(self):
        directory = self.root / "_site/data"
        return (json.loads((directory / "publication.json").read_bytes()),
                json.loads((directory / "verification.json").read_bytes()),
                (directory / "site-data.json").read_bytes())

    def test_manifest_matches_exact_catalog_and_verification_bytes(self):
        result = self.build_at(NOW + timedelta(seconds=1))
        manifest, status, raw = self.publication()
        data = json.loads(raw)
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["snapshot"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(manifest["snapshot"]["bytes"], len(raw))
        self.assertEqual(manifest["snapshot"]["semantic_sha256"], digest(semantic_projection(data)))
        self.assertEqual(data["publication"]["version"], manifest["snapshot"]["version"])
        status_raw = (self.root / "_site/data/verification.json").read_bytes()
        self.assertEqual(manifest["status"]["sha256"], hashlib.sha256(status_raw).hexdigest())
        self.assertEqual(manifest["status"]["bytes"], len(status_raw))
        self.assertEqual(status["snapshot_sha256"], manifest["snapshot"]["sha256"])
        self.assertEqual(status["version"], manifest["version"])
        self.assertEqual(result["generated_at"], manifest["generated_at"])
        self.assertEqual(data["catalog"]["items"][0]["reference_offer_id"], "a")
        self.assertLess(result["manifest_bytes"], 1500)
        self.assertNotIn("publication_cache", " ".join(str(p) for p in (self.root / "_site").rglob("*")))

    def test_same_successful_observation_reuses_exact_catalog_bytes(self):
        self.build_at(NOW + timedelta(seconds=1))
        first, old_status, old_bytes = self.publication()
        verified = NOW + timedelta(minutes=15)
        fresh = make_offer(fetched_at=verified)
        OfferRepository(self.root / "data").save("a", [fresh], verified, [])
        result = self.build_at(verified + timedelta(seconds=1), make_fx(fetched_at=verified))
        latest, status, raw = self.publication()
        self.assertFalse(result["catalog_changed"])
        self.assertEqual(raw, old_bytes)
        self.assertEqual(first["snapshot"], latest["snapshot"])
        self.assertNotEqual(first["version"], latest["version"])
        self.assertNotEqual(first["status"]["sha256"], latest["status"]["sha256"])
        self.assertEqual(status["offers"]["a"]["fetched_at"], fresh.model_dump(mode="json")["fetched_at"])
        self.assertEqual(status["fx"]["fetched_at"], make_fx(fetched_at=verified).model_dump(mode="json")["fetched_at"])
        self.assertEqual(status["offers"]["a"]["content_sha256"], old_status["offers"]["a"]["content_sha256"])

    def test_discount_reference_and_heartbeat_keep_exact_variant_and_semantic_facts(self):
        from app.catalog.models import Money
        from scripts.verify_public_release import snapshot_offers
        cheap = make_offer("cheap", "50", source_code="a")
        sale = make_offer("sale", "90", source_code="a",
                          identity=cheap.identity.model_copy(update={"size": "L"}),
                          original_price=Money(amount="120", currency="USD"))
        repo = OfferRepository(self.root / "data")
        repo.save("a", [cheap, sale], NOW, [])
        self.build_at(NOW + timedelta(seconds=1))
        _, _, old_bytes = self.publication()
        payload = json.loads(old_bytes)
        card = payload["catalog"]["items"][0]
        self.assertEqual(card["reference_offer_id"], "sale")
        self.assertEqual(card["reference_size"], "L")
        self.assertEqual(card["reference_url"], sale.url)
        snapshot_offers(payload)
        verified = NOW + timedelta(minutes=15)
        repo.save("a", [offer.model_copy(update={"fetched_at": verified}) for offer in [cheap, sale]], verified, [])
        result = self.build_at(verified + timedelta(seconds=1), make_fx(fetched_at=verified))
        _, status, raw = self.publication()
        self.assertFalse(result["catalog_changed"])
        self.assertEqual(raw, old_bytes)
        self.assertEqual(status["offers"]["sale"]["fetched_at"], verified.isoformat().replace("+00:00", "Z"))
        import copy
        for key, value in [("reference_original_price", {"amount": "200", "currency": "USD"}),
                           ("reference_cny", "350.00"), ("reference_size", "M"),
                           ("reference_url", "https://wrong.invalid/product"),
                           ("reference_price_valid_until", "2099-01-01")]:
            changed = copy.deepcopy(payload)
            changed["catalog"]["items"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "discount facts differ"):
                snapshot_offers(changed)

    def test_rebuild_without_source_verification_does_not_freshen_stock(self):
        self.build_at(NOW + timedelta(seconds=1))
        _, old_status, old_bytes = self.publication()
        result = self.build_at(NOW + timedelta(minutes=15))
        _, status, raw = self.publication()
        self.assertFalse(result["catalog_changed"])
        self.assertEqual(raw, old_bytes)
        self.assertEqual(status["offers"], old_status["offers"])
        self.assertEqual(status["fx"], old_status["fx"])
        self.assertEqual(status["collection_status"], old_status["collection_status"])

    def test_observed_stock_expiry_failure_and_recovery_replace_catalog(self):
        self.build_at(NOW + timedelta(seconds=1))
        first, status, _ = self.publication()
        expired = self.build_at(NOW + timedelta(hours=1, seconds=1))
        second, expired_status, raw = self.publication()
        self.assertTrue(expired["catalog_changed"])
        self.assertNotEqual(first["snapshot"]["sha256"], second["snapshot"]["sha256"])
        self.assertEqual(status["offers"], expired_status["offers"])
        self.assertEqual(json.loads(raw)["catalog"]["items"][0]["available_sizes"], ["M"])
        failed_at = NOW + timedelta(hours=1, minutes=1)
        repo = OfferRepository(self.root / "data")
        repo.save("a", [], failed_at, [{"url": make_offer().url, "error": "HTTP 429"}])
        self.assertTrue(self.build_at(failed_at + timedelta(seconds=1))["catalog_changed"])
        _, failed_status, _ = self.publication()
        self.assertEqual(failed_status["offers"]["a"]["fetched_at"], status["offers"]["a"]["fetched_at"])
        self.assertEqual(failed_status["offers"]["a"]["collection_state"], "retained")
        recovered_at = failed_at + timedelta(minutes=15)
        repo.save("a", [make_offer(fetched_at=recovered_at)], recovered_at, [])
        self.assertTrue(self.build_at(recovered_at + timedelta(seconds=1))["catalog_changed"])
        _, recovered_status, raw = self.publication()
        self.assertEqual(recovered_status["offers"]["a"]["collection_state"], "current")
        self.assertEqual(json.loads(raw)["catalog"]["items"][0]["available_sizes"], ["M"])

    def test_partial_success_never_renews_other_offer_or_unknown_stock(self):
        repo = OfferRepository(self.root / "data")
        second = make_offer("b", source_code="a", url="https://example.org/b", stock="unknown")
        repo.save("a", [make_offer(), second], NOW, [])
        self.build_at(NOW + timedelta(seconds=1))
        _, old_status, _ = self.publication()
        verified = NOW + timedelta(minutes=15)
        repo.save("a", [make_offer(fetched_at=verified)], verified,
                  [{"url": second.url, "error": "HTTP 429"}])
        self.assertTrue(self.build_at(verified + timedelta(seconds=1))["catalog_changed"])
        _, status, raw = self.publication()
        self.assertEqual(status["offers"]["b"]["fetched_at"], old_status["offers"]["b"]["fetched_at"])
        self.assertEqual(status["offers"]["b"]["collection_state"], "retained")
        self.assertNotEqual(status["offers"]["a"]["fetched_at"], old_status["offers"]["a"]["fetched_at"])
        from app.publication import offers_by_id
        self.assertEqual(offers_by_id(json.loads(raw))["b"]["stock"], "unknown")

    def test_price_stock_size_cost_and_evidence_are_semantic_changes(self):
        self.build_at(NOW + timedelta(seconds=1))
        _, _, raw = self.publication()
        original = json.loads(raw)
        variants = next(iter(original["details"].values()))["variants"]
        variant_id = next(iter(variants))
        baseline = digest(semantic_projection(original))
        import copy
        mutations = [
            lambda q: q["offer"]["price"].update(amount="101"),
            lambda q: q["offer"].update(stock="out_of_stock"),
            lambda q: q["offer"]["identity"].update(size="L"),
            lambda q: q["offer"]["shipping"].update(amount="11"),
            lambda q: q["offer"]["shipping_to_china"].update(checked_at=(NOW + timedelta(minutes=1)).isoformat()),
            lambda q: q.update(eligible=False, reasons=["费用待确认"]),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(original)
            quote = next(iter(changed["details"].values()))["variants"][variant_id]["offers"][0]
            mutate(quote)
            self.assertNotEqual(digest(semantic_projection(changed)), baseline)
        for fields in [{"stale": True}, {"rate_date": (NOW + timedelta(days=1)).date().isoformat()},
                       {"rates": {"USD": "8", "CNY": "1"}}]:
            changed = copy.deepcopy(original)
            changed["catalog"]["fx"].update(fields)
            self.assertNotEqual(digest(semantic_projection(changed)), baseline)

    def test_only_product_observation_day_and_recency_order_are_ignored(self):
        self.build_at(NOW + timedelta(seconds=1))
        _, _, raw = self.publication()
        data = json.loads(raw)
        import copy
        second_card = copy.deepcopy(data["catalog"]["items"][0])
        second_card["product_id"] = "second-product"
        data["catalog"]["items"].append(second_card)
        before = digest(semantic_projection(data))
        data["catalog"]["items"].reverse()
        for family in data["details"].values():
            for detail in family["variants"].values():
                for quote in detail["offers"]:
                    product = next(c for c in quote["landed_cost"]["components"] if c["key"] == "product")
                    product["evidence"][0]["checked_on"] = "2099-01-01"
        self.assertEqual(before, digest(semantic_projection(data)))
        quote = next(iter(next(iter(data["details"].values()))["variants"].values()))["offers"][0]
        quote["landed_cost"]["evidence"][0]["checked_on"] = "2099-01-01"
        self.assertNotEqual(before, digest(semantic_projection(data)))

    def test_changed_code_commit_and_corrupt_cache_force_safe_rebuild(self):
        self.build_at(NOW + timedelta(seconds=1))
        self.assertTrue(self.build_at(NOW + timedelta(seconds=2), commit="b" * 40)["catalog_changed"])
        (self.root / "data/publication_cache/site-data.json").write_text("{corrupt")
        self.assertTrue(self.build_at(NOW + timedelta(seconds=3), commit="b" * 40)["catalog_changed"])
        manifest, _, raw = self.publication()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest["snapshot"]["sha256"])

    def test_valid_json_poisoned_cache_observations_are_rebuilt(self):
        import copy
        self.build_at(NOW + timedelta(seconds=1))
        cache = self.root / "data/publication_cache/site-data.json"
        baseline = json.loads(cache.read_bytes())
        for kind in ("generated_at", "offer_time", "card_time", "fx_time", "price_evidence_day"):
            poisoned = copy.deepcopy(baseline)
            quote = next(iter(next(iter(poisoned["details"].values()))["variants"].values()))["offers"][0]
            if kind == "generated_at":
                poisoned["generated_at"] = "2099-01-01T00:00:00+00:00"
            elif kind == "offer_time":
                quote["offer"]["fetched_at"] = "2099-01-01T00:00:00Z"
            elif kind == "card_time":
                poisoned["catalog"]["items"][0]["fetched_at"] = "not-a-date"
            elif kind == "fx_time":
                poisoned["catalog"]["fx"]["fetched_at"] = "2026-10-14"
            else:
                product = next(c for c in quote["landed_cost"]["components"] if c["key"] == "product")
                product["evidence"][0]["checked_on"] = "2099-01-01"
            atomic_json(cache, poisoned)
            with self.subTest(kind=kind):
                self.assertTrue(self.build_at(NOW + timedelta(seconds=2))["catalog_changed"])
                _, _, raw = self.publication()
                self.assertNotIn(b"2099-01-01", raw)

    def test_local_manifest_does_not_invent_a_commit(self):
        with patch.dict(os.environ, {}, clear=True):
            build_public_site(self.root, make_fx())
        manifest, _, _ = self.publication()
        self.assertIsNone(manifest["commit"])
        self.assertEqual(manifest["version"], "local:" + manifest["generated_at"])
        self.assertTrue(manifest["snapshot"]["version"].startswith("local:catalog:"))


if __name__ == '__main__':
    unittest.main(verbosity=2)
