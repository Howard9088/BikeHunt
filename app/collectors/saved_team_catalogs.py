"""Evidence-strict Lotto detail and Red Bull catalog parsers, with no I/O.

Red Bull category tiles are product-reference quotes only: their selected color
code and InStock JSON-LD do not establish a size's availability. Three observed
PRE-ORDER markers even contradict those generic availability flags.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import _nodes, evidence, money, offer_id
from app.collectors.variants import formatted_money


REDBULL_PAGE = 'https://www.redbullshop.com/en-jp/c/redbullborahansgrohe/'
REDBULL_KEY = 'productSearchData:redbullborahansgrohe'
SIZE_UNKNOWN = '仅商品级报价；逐尺码库存尚未核实'
PREORDER = '官方商品卡标注预售；预计发货时间须在商品页核实'


def _base(source: dict, url: str, fetched_at: datetime) -> dict:
    return dict(source_code=source['code'], source_name=source['name'], url=url,
                fetched_at=fetched_at, sales_region=source.get('sales_region', ''),
                shipping_to_china=evidence(source, 'china_shipping'),
                china_issued_card=evidence(source, 'china_credit_card'))


def parse_lotto(html: str, source: dict, page_url: str,
                fetched_at: datetime) -> list[Offer]:
    """One explicitly bound default variant; never spread its stock to sizes."""
    parsed_url = urlsplit(page_url)
    path = re.fullmatch(r'/nl/shop/product/(\d+)/[^/]+/?', parsed_url.path)
    if (parsed_url.scheme != 'https' or parsed_url.netloc != 'www.lotto-intermarche.be'
            or parsed_url.query or parsed_url.fragment or not path
            or source.get('currency') != 'EUR'):
        return []
    page = Selector(html)
    variants = page.css('.variant-trigger[data-hash]')
    active = page.css('.variant-trigger.is-active[data-hash]')
    if len(variants) != 1 or len(active) != 1:
        return []
    identifier = active[0].attrib['data-hash']
    if not re.fullmatch(re.escape(path[1]) + r'---\d+', identifier):
        return []
    forms = page.css('form.spacing-bottom-huge')
    names = page.css('h1')
    if len(forms) != 1 or len(names) != 1:
        return []
    form = forms[0]
    selected = form.css('input[name="variant"]::attr(value)').getall()
    wrappers = form.css('.price-stock .variant-wrap[data-hash]')
    if selected != [identifier] or len(wrappers) != 1 or wrappers[0].attrib['data-hash'] != identifier:
        return []
    prices = wrappers[0].css('.product-price.product-detail')
    if len(prices) != 1:
        return []
    price_text = str(prices[0].get_all_text(strip=True)).strip()
    # The saved page explicitly quotes EUR; a source default alone proves nothing.
    if not re.fullmatch(r'€\s*\d+(?:[.,]\d{2})?', price_text):
        return []
    price = formatted_money(price_text, 'EUR')
    name = str(names[0].get_all_text(strip=True)).strip()
    if price is None or not name:
        return []
    quantity_text = active[0].attrib.get('data-stock', '')
    quantity = int(quantity_text) if re.fullmatch(r'\d+', quantity_text) else None
    stock_labels = wrappers[0].css('.product-stock')
    label = (str(stock_labels[0].get_all_text(strip=True)).strip().casefold()
             if len(stock_labels) == 1 else '')
    buttons = form.css('button[type="submit"]')
    enabled = (len(buttons) == 1 and 'disabled' not in buttons[0].attrib
               and buttons[0].attrib.get('aria-disabled') != 'true')
    stock = 'unknown'
    if quantity is not None and quantity > 0 and label == 'op voorraad' and enabled:
        stock = 'in_stock'
    elif quantity == 0 and label in ('niet op voorraad', 'uitverkocht'):
        stock = 'out_of_stock'
    requirements = []
    if re.search(r'pre[-\s]?order|voorverkoop', name, re.I):
        stock = 'unknown'
        requirements.append('官方商品名称标注预售；发货时间须核实')
    image = page.css('meta[property="og:image"]::attr(content)').get()
    return [Offer(**_base(source, page_url, fetched_at),
                  offer_id=offer_id(source['code'], page_url, identifier),
                  identity=ProductIdentity(brand=source['brand'], model=name),
                  name=name, image=image, price=price, stock=stock,
                  family_hint=page_url, purchase_requirements=requirements,
                  identity_evidence='Lotto 官方单一默认变体；商品 ID、表单、EUR 价格和库存绑定核对；未推断尺码')]


def _decode_cache(payload):
    """Decode only the inert reference-table forms present in the saved page.

    The table uses base-62 references, arrays, shared object-key arrays, integer
    and boolean literals. Unknown formats, cycles, oversized/deep tables and
    malformed references fail closed. No JavaScript is evaluated.
    """
    if (not isinstance(payload, list) or len(payload) != 2
            or not isinstance(payload[0], list) or len(payload[0]) > 100_000
            or not all(isinstance(atom, str) for atom in payload[0])):
        raise ValueError('Unsupported cache table')
    atoms, root = payload
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    cache, visiting = {}, set()

    def number(value):
        if not isinstance(value, str) or not re.fullmatch(r'-?[0-9A-Za-z]{1,12}', value):
            raise ValueError('Invalid base-62 number')
        negative = value.startswith('-')
        value = value.lstrip('-')
        result = 0
        for char in value:
            result = result * 62 + alphabet.index(char)
        return -result if negative else result

    def decode(ref, depth=0):
        if ref == '':
            return None
        index = number(ref)
        if index < 0 or index >= len(atoms) or depth > 100 or index in visiting:
            raise ValueError('Invalid or recursive cache reference')
        if index in cache:
            return cache[index]
        visiting.add(index)
        value = atoms[index]
        if value.startswith('a|'):
            fields = value[2:].split('|') if value[2:] else []
            value = [decode(field, depth + 1) for field in fields]
        elif value.startswith('o|'):
            fields = value.split('|')
            keys = decode(fields[1], depth + 1) if fields[1] else []
            values = [decode(field, depth + 1) for field in fields[2:]]
            if (not isinstance(keys, list) or not all(isinstance(key, str) for key in keys)
                    or len(set(keys)) != len(keys) or len(keys) != len(values)):
                raise ValueError('Invalid object keys')
            value = dict(zip(keys, values))
        elif value.startswith('n|'):
            value = number(value[2:])
        elif value.startswith('b|'):
            if value not in ('b|T', 'b|F'):
                raise ValueError('Invalid boolean')
            value = value == 'b|T'
        elif re.match(r'^[A-Za-z]\|', value):
            raise ValueError('Unsupported typed cache atom')
        visiting.remove(index)
        cache[index] = value
        return value

    return decode(root)


def _redbull_search(page: Selector):
    scripts = page.css('script#state-body::text').getall()
    marker = 'window.__INITIAL_DATA_CACHE__ = '
    if len(scripts) != 1 or scripts[0].count(marker) != 1:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(scripts[0].split(marker, 1)[1])
        entries = _decode_cache(payload['data'])
        if not isinstance(entries, list):
            return None
        matching = [entry[1] for entry in entries if isinstance(entry, list)
                    and len(entry) == 2 and entry[0] == REDBULL_KEY]
        if len(matching) != 1 or matching[0].get('key') != REDBULL_KEY:
            return None
        response = matching[0]['data']['response']
        return response if isinstance(response, dict) else None
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
        return None


def parse_redbull_catalog(html: str, source: dict, page_url: str,
                          fetched_at: datetime) -> list[Offer]:
    """Saved Japan-market category page: verified prices, unknown size stock.

    Require matching product, selected code, URL and JPY price in both JSON-LD
    and category state. Never use base-site default currency (EUR in this page),
    derive size stock from tiles, or claim the unsaved pagination is covered.
    """
    if page_url != REDBULL_PAGE or source.get('currency') != 'JPY':
        return []
    page = Selector(html)
    if page.css('link[rel="canonical"]::attr(href)').getall() != [REDBULL_PAGE]:
        return []
    search = _redbull_search(page)
    if not search or search.get('categoryCode') != 'redbullborahansgrohe':
        return []
    products = search.get('products')
    if not isinstance(products, list):
        return []
    by_code, duplicate_codes = {}, set()
    for item in products:
        if not isinstance(item, dict) or not isinstance(item.get('code'), str):
            continue
        code = item['code'].upper()
        if code in by_code:
            duplicate_codes.add(code)
        by_code[code] = item
    for code in duplicate_codes:
        by_code.pop(code)
    result, seen = [], set()
    for block in page.css('script[type="application/ld+json"]::text').getall():
        try:
            document = json.loads(block)
        except (ValueError, TypeError):
            continue
        if not isinstance(document, dict) or document.get('@type') != 'ItemList':
            continue
        for product, _ in _nodes(document):
            sku = product.get('sku')
            item = by_code.get(sku) if isinstance(sku, str) else None
            quote = product.get('offers')
            if not item or not isinstance(quote, dict) or quote.get('@type') != 'Offer':
                continue
            url, name = quote.get('url'), product.get('name')
            if not isinstance(url, str) or not name or name != item.get('name'):
                continue
            parts = urlsplit(url)
            base_product = item.get('baseProduct')
            relative = parts.path.removeprefix('/en-jp') + ('?' + parts.query if parts.query else '')
            if (parts.scheme != 'https' or parts.netloc != 'www.redbullshop.com'
                    or parts.fragment or not re.fullmatch(r'/en-jp/p/(?:Men/)?[^/]+/[^/]+/', parts.path)
                    or parts.path.rstrip('/').rsplit('/', 1)[-1] != base_product
                    or parse_qs(parts.query) != {'preselectedVariant': [sku]}
                    or relative != item.get('url') or url in seen):
                continue
            state_quote = item.get('price') or {}
            if not isinstance(state_quote, dict):
                continue
            price = money(quote.get('price'), quote.get('priceCurrency'))
            state_price = money(state_quote.get('value'), state_quote.get('currencyIso'))
            if (price is None or price.currency != 'JPY' or state_price != price
                    or state_quote.get('priceType') != 'BUY'):
                continue
            # An explicit product-level sold-out assertion may conservatively
            # suppress purchase. An InStock tile never proves a size is in stock.
            stock = 'out_of_stock' if item.get('soldOut') is True else 'unknown'
            requirements = [SIZE_UNKNOWN]
            markers = [item.get('marker'), item.get('secondMarker')]
            marker_text = ' '.join(str(value) for marker in markers if isinstance(marker, dict)
                                   for key, value in marker.items() if key in ('code', 'title', 'info'))
            if item.get('preorder') is True or re.search(r'pre[-\s]?order', marker_text, re.I):
                stock = 'unknown'
                requirements.append(PREORDER)
            if item.get('hasRestrictedVariants') is True:
                requirements.append('商品含受限变体；购买资格须在商品页核实')
                stock = 'unknown'
            colors = [v.get('colorSwatchName') for v in item.get('colorSwatchesVariants', [])
                      if isinstance(v, dict) and v.get('codeVariant') == sku]
            color = colors[0] if len(colors) == 1 and isinstance(colors[0], str) else None
            gender = item.get('gender') or {}
            gender = gender.get('name') if isinstance(gender, dict) else None
            image = product.get('image') or {}
            image = image.get('contentUrl') if isinstance(image, dict) else None
            seen.add(url)
            result.append(Offer(**_base(source, url, fetched_at),
                                offer_id=offer_id(source['code'], url, sku),
                                identity=ProductIdentity(brand=source['brand'], model=name,
                                                         color=color, gender=gender),
                                name=name, image=image, price=price, stock=stock,
                                family_hint=base_product, purchase_requirements=requirements,
                                identity_evidence='Red Bull 日本站目录 JSON-LD 与商品状态匹配；明确 JPY 价格和商品链接；未核实逐尺码库存或跨站型号'))
    return result
