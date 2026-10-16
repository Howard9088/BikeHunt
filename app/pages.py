"""只导出公开商品、规则和事件；GitHub Pages 不包含私有配置与订阅数据库。"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.catalog.models import FxSnapshot
from app.catalog.service import ComparisonCatalog
from app.catalog.storage import OfferRepository, atomic_json
from app.community import Community
from app.discovery import directories
from app.fx import FxProvider
from app.localization import CATEGORIES
from app.browse_taxonomy import CATEGORY_GROUPS
from app.public_visibility import public_category_groups, public_categories, public_road_references, public_directories
from app.policies import PolicyRepository
from app.publication import build_publication
from app.updates import UpdateStore
from app.update_views import enrich_events
from app.payment_methods import read_payment_methods
from app.registration_guides import read_registration_guides, registration_assets, publish_registration_guides
from app.brand_icons import export_brand_icons


def build_public_site(root: Path, fx: FxSnapshot | None = None) -> dict:
    """将已核实快照与交互网页导出到固定的 root/_site，返回发布元数据。"""
    root = root.resolve()
    read_payment_methods(root)  # Fail before replacing output when matrix coverage is incomplete.
    registration = read_registration_guides(root)
    registration_assets(root, registration)
    output = (root/"_site").resolve()
    if output.parent != root or output.name != "_site":
        raise ValueError("Public output must stay in the dedicated workspace _site directory")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir()
    web = root/"web"
    (output/"web").mkdir()
    for name in ("public-visibility.js", "gallery.css", "flows.css", "profile.js", "gallery.js", "flows.js", "pages-adapter.js", "group.js", "group.css", "registration-guides.js", "purchase-readiness.js", "purchase-readiness.json", "payment-methods.js", "payment-methods.json", "payment-channels.json", "purchase-flow.js", "bundle-variants.js", "external-exit.js", "external-exit.css"):
        shutil.copy2(web/name, output/"web"/name)
    if (web/"visitor-stats.js").is_file():
        shutil.copy2(web/"visitor-stats.js", output/"web/visitor-stats.js")
    if (web/"icons").is_dir():
        shutil.copytree(web/"icons", output/"web/icons")
        export_brand_icons(output/"web/icons")  # Regenerate approved SVG-derived browser and app icons.
    index = (web/"index.html").read_text(encoding="utf-8")
    index = index.replace('href="/web/"', 'href="./"').replace('="/web/', '="./web/')
    index = index.replace('<script src="./web/profile.js',
                          '<script src="./web/pages-adapter.js?v=BIKEHUNT_RELEASE_COMMIT" data-release="BIKEHUNT_RELEASE_COMMIT" defer></script>\n<script src="./web/profile.js')
    # Tie every copied interactive asset to this exact deployed release.
    # Keep other source HTML and release assets untouched.
    index = re.sub(r'(\./web/(?:gallery|flows|external-exit)\.css|\./web/(?:public-visibility|profile|gallery|flows|pages-adapter|registration-guides|purchase-readiness|payment-methods|purchase-flow|bundle-variants|external-exit|visitor-stats)\.js)(?:\?[^" ]*)?',
                   r'\1?v=BIKEHUNT_RELEASE_COMMIT', index)
    index = index.replace('BIKEHUNT_RELEASE_COMMIT', os.environ.get('GITHUB_SHA', 'local'))
    index = index.replace('>核对最新价格</button>', '>检查最新发布</button>')
    (output/"index.html").write_text(index, encoding="utf-8")
    (output/".nojekyll").touch()
    (output/"group").mkdir()
    group = (web/"group/index.html").read_text(encoding="utf-8")
    group = group.replace('../group.', '../web/group.').replace('../icons/', '../web/icons/').replace(
        'data-community-source="../../api/community"', 'data-community-source="../data/community.json"').replace(
        'data-image-base="../../"', 'data-image-base="../"')
    group = group.replace('BIKEHUNT_RELEASE_COMMIT', os.environ.get('GITHUB_SHA', 'local'))
    (output/"group/index.html").write_text(group, encoding="utf-8")

    repository = OfferRepository(root/"data")
    offers = repository.load()
    snapshot = fx or FxProvider(root/"data/fx_latest.json").get()
    store = ComparisonCatalog(offers, snapshot, public_only=True)
    public_offers = [offer for family in store.families.values() for variant in family for offer in variant]
    catalog = {"items":[row.model_dump(mode="json") for row in store.search()],
               "categories":public_categories(), "category_groups":public_category_groups(),
               "road_equipment_references":public_road_references(root), "fx":snapshot.model_dump(mode="json"),
               "offer_count":len(public_offers), "source_count":len({row.source_code for row in public_offers})}
    details = {}
    for card in catalog["items"]:
        detail = store.compare(card["product_id"])
        details[card["product_id"]] = {"default":detail.variant_id, "variants":{
            row.variant_id:store.compare(card["product_id"], row.variant_id).model_dump(mode="json")
            for row in detail.variants}}
    directory = public_directories(root)
    policies = PolicyRepository(root)
    rules = {entry["code"]:policies.get(entry.get("rules_code", entry["code"])).model_dump(mode="json")
             for entry in repository.sources()}
    for entry in directory["brands"] + directory["teams"]:
        rules.setdefault(entry["code"], policies.get(entry["code"]).model_dump(mode="json"))
    events = UpdateStore(root).latest(limit=100)
    if not events and UpdateStore(root).cursor() == 0:
        try:
            events = json.loads((root/"data/public_updates.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            events = []
    # Keep local history recoverable while publishing only visible categories.
    events = enrich_events(events, store, include_hidden=True)
    atomic_json(root/"data/public_updates.json", events)
    events = enrich_events(events, store)
    try:
        charts = json.loads((root/"data/fit_guides.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        charts = []
    community = Community(root).get()
    atomic_json(output/"data/community.json", community)
    assets = {image for entry in directory["brands"] + directory["teams"] for image in entry.get("logo_images", [])}
    # Explicitly include the single local retailer-identification asset.
    assets.add("/web/assets/brands/amazon-official.png")
    if community.get("available"):
        assets.add(community["image_url"])
    if (web/"assets/community/group-entry.png").is_file():
        assets.add("/web/assets/community/group-entry.png")
    for url in assets:
        source = (root/url.lstrip("/")).resolve()
        if not source.is_relative_to(web.resolve()) or not source.is_file():
            raise ValueError("Public logo asset missing or outside web: " + url)
        target = output/url.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    publish_registration_guides(root, output, registration)
    payload = {"generated_at":datetime.now(timezone.utc).isoformat(), "mode":"published_snapshot",
               "publication":{"commit":os.environ.get("GITHUB_SHA"), "run_id":os.environ.get("GITHUB_RUN_ID"), "trigger":os.environ.get("GITHUB_EVENT_NAME")},
               "collection_status":{p.stem:json.loads(p.read_text(encoding="utf-8")) for p in (root/"data/collection_status").glob("*.json")},
               "catalog":catalog, "details":details, "directories":directory, "rules":rules,
               "updates":{"items":events, "cursor":max(UpdateStore(root).cursor(), max((row["id"] for row in events), default=0)),
                          "fx":snapshot.model_dump(mode="json"), "history_recovery":UpdateStore(root).history_recovery()}, "fit_charts":charts,
               "community":community}
    publication = build_publication(payload, output, root/"data/publication_cache")
    return {"output":str(output), "generated_at":payload["generated_at"],
            "products":len(catalog["items"]), "offers":len(offers), **publication}
