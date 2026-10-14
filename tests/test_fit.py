"""独立尺码与性别 Mock 测试：python tests/test_fit.py，不写入生产数据。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.catalog.models import ProductIdentity
from app.catalog.service import ComparisonCatalog
from app.fit import FitGuideService, ShopperProfile, garment_gender
from test_catalog import NOW, make_fx, make_offer


class FitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/"data").mkdir()
        rows = [make_offer("s", identity=ProductIdentity(brand="Mock",model="Jersey",mpn="M-1",size="S")),
                make_offer("m", stock="out_of_stock", identity=ProductIdentity(brand="Mock",model="Jersey",mpn="M-1",size="M"))]
        catalog = ComparisonCatalog(rows, make_fx(), NOW)
        self.detail = catalog.compare(catalog.search()[0].product_id)
        self.chart = {"product_urls":[row.url for row in rows],"source_url":"https://example.org/official-size",
                      "checked_at":NOW.isoformat(),"gender":"male",
                      "rows":[{"size":"S","chest_cm":{"minimum":94,"maximum":98},"description_zh":"胸围 94–98 厘米"},
                              {"size":"M","chest_cm":{"minimum":98,"maximum":102},"description_zh":"胸围 98–102 厘米"}]}
        self.service = FitGuideService(self.root)

    def write_chart(self) -> None:
        (self.root/"data/fit_guides.json").write_text(json.dumps([self.chart]),encoding="utf-8")

    def test_height_weight_alone_does_not_invent_an_apparel_size(self) -> None:
        self.write_chart()
        fit = self.service.assess(self.detail, ShopperProfile(height_cm=175,weight_kg=68), NOW)
        self.assertEqual(fit.state,"needs_measurement")
        self.assertEqual(fit.required_measurements,["chest_cm"])
        self.assertFalse(fit.candidate_sizes)

    def test_matching_chest_selects_only_the_stocked_size(self) -> None:
        self.write_chart()
        fit = self.service.assess(self.detail, ShopperProfile(chest_cm=96), NOW)
        self.assertEqual(fit.candidate_sizes,["S"])
        sold = self.service.assess(self.detail, ShopperProfile(chest_cm=100), NOW)
        self.assertEqual(sold.state,"unavailable")
        self.assertFalse(sold.candidate_sizes)

    def test_boundary_reference_keeps_stock_and_does_not_auto_select(self) -> None:
        self.write_chart()
        fit = self.service.assess(self.detail, ShopperProfile(chest_cm=98), NOW)
        self.assertEqual(fit.candidate_sizes,["S"])
        self.assertIn("参考",fit.note_zh)

    def test_verified_height_weight_ranges_are_supported(self) -> None:
        self.chart["rows"]=[{"size":"S","height_cm":{"minimum":170,"maximum":180},
                             "weight_kg":{"minimum":60,"maximum":75},"description_zh":"Mock 官网范围"}]
        self.write_chart()
        fit = self.service.assess(self.detail,ShopperProfile(height_cm=175,weight_kg=68),NOW)
        self.assertEqual(fit.candidate_sizes,["S"])

    def test_stale_or_unrelated_chart_does_not_claim_a_match(self) -> None:
        for changes in ({"checked_at":(NOW-timedelta(days=31)).isoformat()},
                        {"product_urls":["https://example.org/other"]}):
            self.chart.update(changes)
            self.write_chart()
            self.assertEqual(self.service.assess(self.detail,ShopperProfile(chest_cm=96),NOW).state,"no_chart")

    def test_wrong_gender_never_produces_a_size_reference(self) -> None:
        self.write_chart()
        fit = self.service.assess(self.detail,ShopperProfile(gender="female",chest_cm=96),NOW)
        self.assertEqual(fit.state,"not_applicable")

    def test_invalid_units_values_and_extra_fields_are_rejected(self) -> None:
        for data in ({"height_cm":1.75},{"weight_kg":-5},{"weight_kg":float("nan")},{"gender":"guess"},{"bank_card":"secret"}):
            with self.assertRaises(ValidationError):
                ShopperProfile.model_validate(data)

    def test_official_gender_labels_and_neutral_equipment(self) -> None:
        self.assertEqual(garment_gender("Women's jersey",None,"jerseys"),"female")
        self.assertEqual(garment_gender("Men's bib shorts",None,"bibs"),"male")
        self.assertEqual(garment_gender("Jersey","Womens","jerseys"),"female")
        self.assertEqual(garment_gender("Jersey",None,"jerseys"),"unknown")
        self.assertEqual(garment_gender("Helmet",None,"helmets"),"unisex")

    def test_conflicting_gender_never_shares_one_product_card(self) -> None:
        rows = [make_offer(gender, identity=ProductIdentity(brand="Mock",model="Jersey",mpn="M-1",size="M",gender=gender))
                for gender in ("male", "female")]
        cards = ComparisonCatalog(rows, make_fx(), NOW).search()
        self.assertEqual(len(cards), 2)
        self.assertEqual({row.gender for row in cards}, {"male", "female"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
