import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from app.product_images import publish_product_images

ROOT=Path(__file__).resolve().parents[1]

class ProductImagesTests(unittest.TestCase):
    def test_official_originals_are_exact_and_bound_to_recorded_urls(self):
        data=json.loads((ROOT/'web/product-images.json').read_text(encoding='utf-8'))
        recorded={row['image'] for row in json.loads((ROOT/'data/offers/oakley.json').read_text(encoding='utf-8'))['offers'] if row.get('image')}
        self.assertEqual({row['source_url'] for row in data['assets']},recorded)
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp);(output/'web').mkdir()
            publish_product_images(ROOT,output)
            for row in data['assets']:
                body=(output/'web/assets/product-images'/row['file']).read_bytes()
                self.assertEqual(hashlib.sha256(body).hexdigest(),row['sha256'])
                self.assertEqual(body,(ROOT/'web/assets/product-images'/row['file']).read_bytes())
            self.assertIn('BikeHuntProductImages',(output/'web/product-images.js').read_text(encoding='utf-8'))
