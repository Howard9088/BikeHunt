# Amazon road-cycling apparel channels

Verified against official documentation on 2026-10-15 (UTC).

## Current release

US, UK, Germany and Japan are official Amazon **search entrances only**, with road-cycling jersey and bib-short queries. They are not verified product offers, ASINs, prices, remaining sizes, sellers or delivery routes. They do not enter the product comparison, stock counts, price events or landed-cost calculation. No affiliate tag is appended.

Users must distinguish **Sold by** (seller) from **Ships from** (fulfilment). Amazon fulfilment or Prime does not establish Amazon retail ownership or China delivery. Confirm the exact listing, variant, seller, mainland-China destination, shipping, taxes and final checkout on Amazon.

## Licensed product-data route

Use Amazon **Creators API**, not the retired PA-API 5. The current official deprecation notice says PA-API calls receive HTTP 403 AccessDenied. Do not retry that restriction or scrape around it.

Creators API requires the appropriate marketplace Associates enrollment/acceptance and eligibility, including at least 10 qualifying sales in the trailing 30 days. Only the primary account owner can register Creators API; approved marketplace Partner Tags and server-side OAuth credentials are needed. This repository currently has no Creators API adapter or authorized credentials. This release does not verify whether the owner has an eligible account and does not request or create credentials. Any subsequent account/access setup must use the supported secure flow.

OffersV2 can expose merchant identity, prices and availability, but does not provide the former DeliveryInfo shipping-cost/Prime/fulfilment fields or seller default shipping country. Marketplace-local prices cannot be presented as confirmed China-destination checkout totals. Future integration must retain per-marketplace, per-listing currency and seller evidence and independently validate destination shipping and taxes.

Official references:
- https://affiliate-program.amazon.com/creatorsapi/docs/en-us/paapiv5-deprecation
- https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction
- https://affiliate-program.amazon.com/creatorsapi/docs/en-us/onboarding/register-for-creators-api
- https://affiliate-program.amazon.com/creatorsapi/docs/en-us/onboarding/sign-up-as-an-amazon-associate
- https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/resources/offersV2
- https://digprjsurvey.amazon.com/csad/help/node/GEF528GN65XSJ7V8

No paid service, purchase, account signup, credential issuance, bot access or continuous Amazon page crawling is included.
