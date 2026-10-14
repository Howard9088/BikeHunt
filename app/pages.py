"""只导出公开商品、规则和事件；GitHub Pages 不包含私有配置与订阅数据库。"""
from __future__ import annotations

import json
import os
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
from app.policies import PolicyRepository
from app.updates import UpdateStore


def build_public_site(root: Path, fx: FxSnapshot | None = None) -> dict:
    """将已核实快照与交互网页导出到固定的 root/_site，返回发布元数据。"""
    root = root.resolve()
    output = (root/"_site").resolve()
    if output.parent != root or output.name != "_site":
        raise ValueError("Public output must stay in the dedicated workspace _site directory")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir()
    web = root/"web"
    (output/"web").mkdir()
    for name in ("gallery.css", "flows.css", "profile.js", "gallery.js", "flows.js", "pages-adapter.js"):
        shutil.copy2(web/name, output/"web"/name)
    index = (web/"index.html").read_text(encoding="utf-8")
    index = index.replace('href="/web/"', 'href="./"').replace('="/web/', '="./web/')
    index = index.replace('<script src="./web/profile.js',
                          '<script src="./web/pages-adapter.js?v=cache13" data-release="BIKEHUNT_RELEASE_COMMIT" defer></script>\n<script src="./web/profile.js')
    index = index.replace('BIKEHUNT_RELEASE_COMMIT', os.environ.get('GITHUB_SHA', 'local'))
    index = index.replace('>核对最新价格</button>', '>检查最新发布</button>')
    (output/"index.html").write_text(index, encoding="utf-8")
    (output/".nojekyll").touch()

    repository = OfferRepository(root/"data")
    offers = repository.load()
    snapshot = fx or FxProvider(root/"data/fx_latest.json").get()
    store = ComparisonCatalog(offers, snapshot)
    catalog = {"items":[row.model_dump(mode="json") for row in store.search()],
               "categories":CATEGORIES, "fx":snapshot.model_dump(mode="json"),
               "offer_count":len(offers), "source_count":len({row.source_code for row in offers})}
    details = {}
    for card in catalog["items"]:
        detail = store.compare(card["product_id"])
        details[card["product_id"]] = {"default":detail.variant_id, "variants":{
            row.variant_id:store.compare(card["product_id"], row.variant_id).model_dump(mode="json")
            for row in detail.variants}}
    directory = directories(root)
    policies = PolicyRepository(root)
    rules = {entry["code"]:policies.get(entry.get("rules_code", entry["code"])).model_dump(mode="json")
             for entry in repository.sources()}
    for entry in directory["brands"] + directory["teams"]:
        rules.setdefault(entry["code"], policies.get(entry["code"]).model_dump(mode="json"))
    events = UpdateStore(root).latest(limit=100)
    if not events:
        try:
            events = json.loads((root/"data/public_updates.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            events = []
    atomic_json(root/"data/public_updates.json", events)
    try:
        charts = json.loads((root/"data/fit_guides.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        charts = []
    community = Community(root).get()
    assets = {image for entry in directory["brands"] + directory["teams"] for image in entry.get("logo_images", [])}
    if community.get("available"):
        assets.add(community["image_url"])
    for url in assets:
        source = (root/url.lstrip("/")).resolve()
        if not source.is_relative_to(web.resolve()) or not source.is_file():
            raise ValueError("Public logo asset missing or outside web: " + url)
        target = output/url.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    payload = {"generated_at":datetime.now(timezone.utc).isoformat(), "mode":"published_snapshot",
               "publication":{"commit":os.environ.get("GITHUB_SHA"), "run_id":os.environ.get("GITHUB_RUN_ID"), "trigger":os.environ.get("GITHUB_EVENT_NAME")},
               "collection_status":{p.stem:json.loads(p.read_text(encoding="utf-8")) for p in (root/"data/collection_status").glob("*.json")},
               "catalog":catalog, "details":details, "directories":directory, "rules":rules,
               "updates":{"items":events, "cursor":max((row["id"] for row in events), default=0),
                          "fx":snapshot.model_dump(mode="json")}, "fit_charts":charts,
               "community":community}
    atomic_json(output/"data/site-data.json", payload)
    return {"output":str(output), "generated_at":payload["generated_at"],
            "products":len(catalog["items"]), "offers":len(offers)}
