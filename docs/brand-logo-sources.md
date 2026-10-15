# Brand directory logo sources

Asset verification: 2026-10-15T06:09:19Z.

## Diagnosis and coverage

The directory contains ten brand entries. Before this change, only Rapha had `logo_images`; the other nine displayed the first word of the brand name from `directoryLogo`. This was missing configuration/assets, not nine failed image downloads. Seven official SVGs are now supplied, Rapha is unchanged, and POC/Oakley remain name fallbacks.

## Artwork rules

- All assets are official source artwork; no AI generation, tracing, redraw, or font replacement.
- Keep original viewBox proportions and colors. Use `object-fit: contain`; do not stretch, crop, recolor, or apply the team monochrome filter.
- Keep surrounding padding/clear space in the card. The original viewBox is intact; no separate brand-specific clear-space licence/manual is asserted.
- These files identify destinations only. Their availability is not a grant of trademark rights or evidence of a commercial relationship.

## Asset inventory

| Brand | SVG viewport | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| maap | 0 0 76 20 | 1187 | `664e49fc71db5831e45e76d7f3cc071d61e26d1e3d27cdf6bf2b8bcf4a30d279` |
| assos | 0 0 330 200 | 527 | `0e5d84f0660f844ca7c0267c17c3588f90a6df75805ce3e2aef49b4a02a0cea1` |
| castelli | 0 0 800 83 | 3616 | `70e10730b54fee14707d7700fb77f8462cf0d674cedd42682ca6f4ed811f129c` |
| santini | 0 0 1920 393.62 | 3562 | `8ebba08d6590eb4103b6d8c4917c5c794f67ac8c2e51adb6e8db4eaed6ce1b90` |
| pns | 0 0 106 40 | 8125 | `3a20c9e3c7d26c555cbd471e4c9ad11844070454a20333cd8e688fcd888d529c` |
| kask | 0 0 95 26 | 559 | `832a6b61621f8e81a8f4b3d4be338007a9a511fdccf4c4a707ea5e73d1b74c11` |
| fizik | 0 0 71.67 20 | 1953 | `60f92f36477e738bd6bf30037b8687c6c3993e5fda7f1f09604b900cf3bcab79` |
| rapha | 0 0 465 208 | 4896 | `e6f845e483ba4b92e865ccb80967a4f95a01c5421202e9df68821f49d97512d7` |

## maap

- Local file: `web/assets/brands/maap.svg`
- Official source: https://maap.cc/tw
- Evidence page: https://maap.cc/tw
- Element: `[data-testid="dn-logo"] a[title="MAAP Cycling Apparel Home"] svg`
- Verification: Verbatim inline SVG from a successful official homepage HTTP 200 download on 2026-10-15.
- Colors: currentColor; black standalone rendering
- Note: Official slanted wordmark; no retyping.

## assos

- Local file: `web/assets/brands/assos.svg`
- Official source: https://www.assos.com/int/
- Evidence page: https://www.assos.com/int/
- Element: `svg[viewBox="0 0 330 200"] with title ASSOS Of Switzerland - Official Online Shop`
- Verification: Verbatim inline SVG extracted from previously saved official homepage HTML, reviewed on 2026-10-15. No new homepage request.
- Colors: currentColor; black standalone rendering
- Note: The current saved official header uses the ASSOS 50th-anniversary emblem. Preserve the complete 50 mark; do not substitute a typed ASSOS wordmark.

## castelli

- Local file: `web/assets/brands/castelli.svg`
- Official source: https://www.castelli-cycling.com/cdn/shop/files/logo-castelli.svg?v=1775823031
- Evidence page: https://www.castelli-cycling.com
- Element: `img in .logo__img--color; original referenced logo-castelli.svg`
- Verification: Original official CDN SVG downloaded successfully (HTTP 200) on 2026-10-15. Source reference found in saved official product HTML.
- Colors: #1D1D1B; white clipping rect
- Note: Official 2026 wordmark; preserve its naturally wide proportions.

## santini

- Local file: `web/assets/brands/santini.svg`
- Official source: https://www.santinicycling.com/cdn/shop/files/Santini_Home.svg?height=24&v=1769097266
- Evidence page: https://www.santinicycling.com/
- Element: `img.header-logo__image[alt="Santini Cycling – Home"]`
- Verification: Original official CDN SVG downloaded successfully (HTTP 200) on 2026-10-15. Source reference found in saved official homepage HTML.
- Colors: #1d1d1b
- Note: The source preserves its original 1920 × 393.62 viewBox despite the URL height parameter.

## pns

- Local file: `web/assets/brands/pns.svg`
- Official source: https://pasnormalstudios.com/eu
- Evidence page: https://pasnormalstudios.com/eu
- Element: `.logo svg[viewBox="0 0 106 40"] within homepage link`
- Verification: Verbatim inline SVG extracted from previously saved official homepage HTML, reviewed on 2026-10-15. No new homepage request.
- Colors: currentColor; black standalone rendering
- Note: Full Pas Normal Studios / International Cycling Club artwork, including its registered mark.

## kask

- Local file: `web/assets/brands/kask.svg`
- Official source: https://www.kask.com/on/demandware.static/Sites-KASK_EU-Site/-/en_IT/v1791943516209/images/sprite.svg#logo-kask
- Evidence page: https://www.kask.com/en-it/Cycling/Road
- Element: `a.logo-home use pointing to sprite.svg#logo-kask`
- Verification: Official sprite downloaded successfully (HTTP 200) on 2026-10-15. The exact logo-kask symbol children/viewBox/fill were placed in a standalone svg wrapper; path geometry and colors are unchanged.
- Colors: #94D500
- Note: Preserve the official lime-green fill. Do not use KOO or the DNV certification logo.

## fizik

- Local file: `web/assets/brands/fizik.svg`
- Official source: https://www.fizik.com/en-us/
- Evidence page: https://www.fizik.com/en-us/
- Element: `svg#Fizik_Logo`
- Verification: Verbatim inline SVG extracted from previously saved official homepage HTML, reviewed on 2026-10-15. No new homepage request.
- Colors: #222222
- Note: Official fi’zi:k artwork; not its parent Selle Royal or a retailer logo.

## rapha

- Official source: https://www.rapha.cc/us/en
- Existing file retained without modification. Its complete path data was found verbatim in the successfully fetched official homepage HTML on 2026-10-15.

## poc

- No requests made to poc.com: known prior 429/robots access restrictions; no verified local brand logo found.

## oakley

- No requests made to oakley.com. The separate public official media center https://oakley-media-hub.prezly.com/ca returned HTTP 403 for its HTML download; no retry or circumvention attempted. No verified local brand logo found.

## Validation

- All eight SVG files parse as SVG with finite, positive viewBoxes and render as nonempty images in Inkscape.
- Source colors, artwork and proportions were visually reviewed together.
- The isolated Chromium render was blocked by this executor’s process/socket sandbox, so this is asset-render verification rather than browser layout QA. Final browser/card layout QA belongs to the integrated release.
- `tests/test_brand_logos.py` checks the exact seven new assets, ten-brand separation, provenance/date, finite viewBoxes, hashes, unchanged Rapha, and absence of active/external SVG payloads.
