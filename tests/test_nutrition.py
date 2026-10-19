"""Nutrition products require exact reviewed classification, not brand-only assumptions."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.browse_taxonomy import browse_classification, CATEGORY_GROUPS
from app.public_visibility import public_category_groups

class NutritionTests(unittest.TestCase):
    def test_group_does_not_restore_bicycles(self):
        self.assertIn('nutrition', [x['code'] for x in CATEGORY_GROUPS])
        self.assertIn('nutrition', [x['code'] for x in public_category_groups()])
        self.assertNotIn('road_equipment', [x['code'] for x in public_category_groups()])

    def test_brand_alone_is_not_reviewed_product_classification(self):
        row=SimpleNamespace(source_code='maurten', url='https://www.maurten.com/products/unreviewed', name='Maurten accessory')
        self.assertEqual(browse_classification('unknown', [row]).category_group, 'other')

    def test_nutrition_review_is_bound_to_exact_product_and_source(self):
        url='https://www.maurten.com/products/gel-100-box-us'
        row=SimpleNamespace(source_code='maurten', url=url, name='Gel 100')
        review={'fixture':{'category':'energy_gels','category_group':'nutrition','source_codes':['maurten'],'canonical_url':url}}
        with patch('app.browse_taxonomy._reviewed_products', return_value=review):
            self.assertEqual(browse_classification('fixture',[row]).category_group,'nutrition')
            row.url+='-other'
            self.assertEqual(browse_classification('fixture',[row]).category_group,'other')
            row.url=url;row.source_code='unknown_seller'
            self.assertEqual(browse_classification('fixture',[row]).category_group,'other')
