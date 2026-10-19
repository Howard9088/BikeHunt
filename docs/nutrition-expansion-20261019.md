# Nutrition catalog expansion — 19 October 2026

## Scope and evidence

The verified public snapshot at 07:06 UTC had two nutrition product families and no SiS, Maurten or Enervit brand-directory entries. This change adds those three directory entries and eight product families to the existing catalog, variant, purchase-warning and source-verification flow.

Enervit EU English store, observed at 07:40 UTC:

| Exact product | SKU | Package | EUR |
| --- | --- | --- | --- |
| [Carbo Gel Mango](https://www.enervit.com/en/products/carbo-gel-c-2-1-pro-mango.html) | 96651 | 1 × 60 ml | 2.95 |
| [Carbo Gel Cola Caffeine](https://www.enervit.com/en/products/carbo-gel-c-2-1-pro-caffeine.html) | 96631 | 1 × 60 ml, 100 mg caffeine | 2.95 |
| [Carbo Bar Brownie](https://www.enervit.com/en/products/the-carbo-bar-c-2-1-pro-brownie.html) | 99190 | 1 × 45 g | 2.95 |
| [Isocarb Lemon](https://www.enervit.com/en/products/isocarb-c-2-1-pro.html) | 90938 | 1 × 650 g jar | 19.90 |

Each selected single-unit package had an enabled purchase control, exact matching form/button SKU and stock attribute `In stock`; OpenGraph EUR price matched the product form and button. The new strict dynamic parser reads those attributes anew, rejecting differing product/market URLs, prices, selected packs or stock conflicts. It does not use recommendation cards or guess multipack prices. Sodium gel was excluded because its live page returned an upstream timeout.

[Enervit's official Pogačar profile](https://www.enervit.com/en/tadej-pogacar) and [official collaboration article](https://www.enervit.com/en/and-it-is-pogacar-right-away) establish C2:1PRO range development with Pogačar/UAE. No claim is made that he personally uses every listed SKU.

Maurten selected France/EUR market, exact structured offers and product-bound package evidence:

| Exact product | SKU | Package | EUR |
| --- | --- | --- | --- |
| [Gel 160](https://www.maurten.com/fr/products/gel-160-box) | 12103 | 12 portions | 54.95 |
| [Gel 100 Caf 100](https://www.maurten.com/fr/products/gel-100-caf-100-box) | 13002 | 12 sachets, caffeine version | 47.50 |
| [Drink Mix 160](https://www.maurten.com/fr/products/drink-mix-160) | 10102 | 18 servings | 39.95 |
| [Drink Mix 320](https://www.maurten.com/fr/products/drink-mix-320) | 10202 | 14 servings | 46.95 |

All four structured offers were InStock. Existing Gel 100 was refreshed without changing its identity. `/fr` alone is not country evidence: the parser now also checks selected France/EUR controls, canonical URL, exact SKU and product-bound pack labels. Five official Maurten product images returned HTTP 200.

Prices and stock are timestamped source observations, not checkout guarantees. No discount, China shipping, China-issued-card acceptance or landed price is inferred. No new health/performance claims, hydrogen-water products, personal-use claims or image permissions are invented. Existing unavailable-product and stock-age safeguards remain active. New directory entries use honest text identities rather than recreated logos.

## Validation and release

- Python aggregate: 618 tests passed.
- Node: all 20 existing suites passed.
- Static build passed after restoring 17 existing product image files from the deployed site and verifying their recorded byte counts/SHA256 hashes. These unchanged assets are not part of the patch.
- Local browser UI attempt was blocked by Chromium sandbox socket permissions. No security bypass was attempted. Desktop/390px/320px browser checks remain a release CI requirement.
- FX refresh encountered the environment's certificate-chain error; the normal cached FX fallback was used. Foreign-currency source prices remain unchanged.
- Changes are uncommitted and unpublished. Do not publish `_site`, local evidence directories, generated histories or local build artifacts. Apply the explicit release manifest to the latest base, run the normal Pages CI, and verify the resulting commit and public snapshot.
