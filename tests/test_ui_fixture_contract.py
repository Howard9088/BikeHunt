"""Browser-free identity checks for the shared catalog-message UI fixtures."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from test_catalog_messages_ui import detail_for_request, event, fixture


class UiFixtureContractTests(unittest.TestCase):
    def state(self):
        state = fixture()
        base = state['catalog']['items'][0]
        state['catalog']['items'] += [
            {**base, 'product_id': 'maap-jersey', 'category': 'jerseys'},
            {**base, 'product_id': 'other-jersey', 'category': 'jerseys', 'source_codes': ['other']},
        ]
        state['events'] = [event(2, size='L'), event(1), event(4, 'sold', sold=True)]
        return state

    def test_scoped_card_detail_preserves_requested_family_on_open_and_selection(self):
        state = self.state()
        for product_id in ('partial', 'maap-jersey', 'other-jersey'):
            for variant_id in ('', 'S'):
                detail = detail_for_request(state, product_id, variant_id)
                self.assertEqual(detail['product_id'], product_id)
                self.assertEqual(detail['variant_id'], 'S')
                self.assertEqual(detail['offers'], state['detail']['offers'])

    def test_search_name_change_uses_exact_card_without_mutating_base_detail(self):
        state = self.state()
        original = copy.deepcopy(state['detail'])
        card = next(row for row in state['catalog']['items'] if row['product_id'] == 'maap-jersey')
        card.update(name='Stamp Hoodie', name_zh='Stamp Hoodie 测试商品')
        detail = detail_for_request(state, 'maap-jersey', 'S')
        self.assertEqual(detail['name'], card['name'])
        self.assertEqual(detail['name_zh'], card['name_zh'])
        self.assertEqual(state['detail'], original)
        self.assertIsNot(detail['offers'], state['detail']['offers'])

    def test_exact_message_variant_and_sold_out_identity_remain_bound(self):
        state = self.state()
        for row in state['events']:
            product = row['product']
            detail = detail_for_request(state, product['product_id'], product['variant_id'])
            self.assertEqual(detail['product_id'], product['product_id'])
            self.assertEqual(detail['variant_id'], product['variant_id'])
            self.assertEqual(detail['identity']['size'], product['size'])
            self.assertEqual(detail['offers'][0]['offer']['offer_id'], row['offer_id'])
            self.assertEqual(detail['offers'][0]['offer']['url'], row['url'])
            self.assertEqual(detail['offers'][0]['offer']['stock'], product['current_stock'])

    def test_unknown_family_or_unprovided_exact_quote_is_not_substituted(self):
        state = self.state()
        for product_id, variant_id in [('missing-family', ''), ('maap-jersey', 'XL'), ('173', 'S')]:
            with self.assertRaises(KeyError):
                detail_for_request(state, product_id, variant_id)


if __name__ == '__main__':
    unittest.main()
