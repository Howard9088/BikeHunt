"""BikeHunt 信息聚合与导航接口。"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.catalog.models import ProductComparison
from app.catalog.service import ComparisonCatalog
from app.catalog.storage import OfferRepository
from app.fx import FxProvider
from app.background import RefreshWorker
from app.discovery import directories
from app.localization import CATEGORIES
from app.browse_taxonomy import CATEGORY_GROUPS
from app.public_visibility import public_category_groups, public_categories, public_road_references, public_directories, public_product
from app.notifications import PersonalNotifier
from app.policies import PolicyRepository
from app.updates import UpdateStore
from app.update_views import enrich_events
from app.community import Community
from app.fit import FitGuideService, ShopperProfile, FitAssessment

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
WEB = ROOT / "web"
repository = OfferRepository(DATA)
fx_provider = FxProvider(DATA / "fx_latest.json")
worker = RefreshWorker(ROOT)
notifier = PersonalNotifier(ROOT)
updates = UpdateStore(ROOT)
community = Community(ROOT)


@asynccontextmanager
async def lifespan(application: FastAPI):
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="BikeHunt 全球骑行好价", version="0.4.2", lifespan=lifespan)


def catalog() -> ComparisonCatalog:
    """一次请求固定一个汇率快照，全部报价使用相同口径。"""
    from app.catalog.listings import read_listing_history
    return ComparisonCatalog(repository.load(), fx_provider.get(), public_only=True, listing_history=read_listing_history(ROOT))


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "BikeHunt", "version": "0.4.2"}


@app.get("/api/sources")
def sources() -> list[dict]:
    offers = repository.load()
    result = repository.sources()
    for source in result:
        code = source["code"]
        rows = [x for x in offers if x.source_code == code]
        source["offer_count"] = len(rows)
        source["integration_status"] = "snapshot_available" if rows else "not_connected"
        try:
            source["last_collection"] = json.loads(
                (DATA / "collection_status" / f"{code}.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            logger.debug("尚无采集记录 {} {}", code, exc)
    from app.public_status import public_collection_status, public_urls
    allowed = public_urls(ROOT)
    for source in result:
        if 'last_collection' in source:
            source['last_collection'] = public_collection_status({source['code']: source['last_collection']}, allowed)[source['code']]
    return result


@app.get("/api/products")
def products() -> list[dict]:
    """兼容旧版 MAAP 列表；新版页面使用 /api/catalog。"""
    try:
        return json.loads((DATA / "products_maap.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


@app.get("/api/fx")
def fx() -> dict:
    return fx_provider.get().model_dump(mode="json")


@app.get("/api/fx/refresh")
def refresh_fx() -> dict:
    return fx_provider.get(force=True).model_dump(mode="json")


@app.get("/api/catalog")
def search_catalog(q: str = Query(default="", max_length=200), category: str = "all", category_group: str | None = None) -> dict:
    store = catalog()
    return {"items": [x.model_dump(mode="json") for x in store.search(q,category,category_group)],
            "categories":public_categories(), "category_groups":public_category_groups(),
            "road_equipment_references":public_road_references(ROOT),
            "fx": store.fx.model_dump(mode="json"),
            "offer_count": sum(len(v) for family in store.families.values() for v in family),
            "source_count": len({x.source_code for family in store.families.values()
                                 for variant in family for x in variant})}


@app.get("/api/catalog/{product_id}", response_model=ProductComparison)
def compare_product(product_id: str, variant_id: str | None = None) -> ProductComparison:
    try:
        return catalog().compare(product_id, variant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="商品或规格不存在，请刷新目录") from exc


@app.get("/api/directories")
def discovery_directory() -> dict:
    return public_directories(ROOT)


@app.post("/api/fit/{product_id}", response_model=FitAssessment)
def assess_fit(product_id: str, profile: ShopperProfile) -> FitAssessment:
    """个人测量值只参与当前请求，不保存到服务器或推送服务。"""
    try:
        return FitGuideService(ROOT).assess(catalog().compare(product_id), profile)
    except KeyError as exc:
        raise HTTPException(404, detail="商品不存在") from exc


@app.get("/api/rules/{source_code}")
def source_rules(source_code: str) -> dict:
    try:
        source=next((s for s in repository.sources() if s['code']==source_code), {})
        book=PolicyRepository(ROOT).get(source.get('rules_code',source_code))
    except ValueError as exc:
        raise HTTPException(400,detail="无效来源") from exc
    return book.model_dump(mode="json")


@app.get("/api/updates")
def price_updates(after: int = Query(default=0,ge=0), category: str = "all") -> dict:
    return {"items":enrich_events(updates.latest(after,limit=100,category=category),catalog()),"cursor":updates.cursor(),
            "fx":fx_provider.get().model_dump(mode="json")}


@app.get("/api/updates/stream")
async def price_stream(request: Request) -> StreamingResponse:
    async def events():
        raw=request.headers.get("last-event-id","")
        cursor=int(raw) if raw.isdigit() else updates.cursor()
        yield "event: ready\ndata: {}\n\n"
        while not await request.is_disconnected():
            rows=updates.pending(cursor,limit=100)
            if rows:
                cursor=max(x["id"] for x in rows)
                rows = enrich_events(rows, catalog())
                yield f"id: {cursor}\nevent: prices\ndata: {json.dumps(rows,ensure_ascii=False)}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(events(),media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@app.get("/api/refresh/status")
def refresh_status() -> dict:
    return worker.status


@app.post("/api/refresh/{kind}")
async def refresh_data(kind: str) -> dict:
    if kind not in ("prices","rules"):
        raise HTTPException(400,detail="无效刷新类型")
    return worker.refresh(kind)


def device(request: Request, response: Response) -> str:
    value=request.cookies.get("bikehunt_device","")
    if not re.fullmatch(r"[a-f0-9]{48}",value):
        value=secrets.token_hex(24)
        response.set_cookie("bikehunt_device",value,httponly=True,samesite="lax",max_age=31536000)
    return value


class Preferences(BaseModel):
    categories: list[str] = Field(default_factory=lambda:["all"])
    enabled: bool = True


class PushSettings(BaseModel):
    app_token: str = Field(min_length=10,max_length=200)


@app.get("/api/notifications/preferences")
def reminder_preferences(request: Request,response: Response) -> dict:
    return notifier.preferences(device(request,response))


@app.post("/api/notifications/preferences")
def save_reminder_preferences(payload: Preferences,request: Request,response: Response) -> dict:
    try:
        return notifier.save_preferences(device(request,response),payload.categories,payload.enabled)
    except ValueError as exc:
        raise HTTPException(400,detail=str(exc)) from exc


@app.post("/api/notifications/bind")
def bind_wechat(request: Request,response: Response) -> dict:
    try:
        return notifier.create_binding(device(request,response))
    except Exception as exc:
        logger.warning("绑定二维码获取失败 {}",type(exc).__name__)
        raise HTTPException(502,detail="暂时无法获取绑定二维码，请核对推送服务配置") from exc


@app.get("/api/notifications/binding")
def wechat_binding_status(request: Request,response: Response) -> dict:
    try:
        return notifier.binding_status(device(request,response))
    except Exception as exc:
        raise HTTPException(502,detail="绑定状态查询失败，请稍后重试") from exc


@app.post("/api/admin/push-settings")
def configure_push(payload: PushSettings,request: Request) -> dict:
    require_local_admin(request)
    try:
        notifier.configure(payload.app_token)
    except ValueError as exc:
        raise HTTPException(400,detail=str(exc)) from exc
    return {"configured":True}


def require_local_admin(request: Request) -> None:
    if not request.client or request.client.host not in ("127.0.0.1","::1"):
        raise HTTPException(403,detail="推送密钥只能在电脑本机页面配置")
    origin=request.headers.get("origin")
    if origin and origin not in ("http://127.0.0.1:18888","http://localhost:18888"):
        raise HTTPException(403,detail="配置来源不匹配")


@app.get("/api/community")
def community_entry(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return community.get()


class CommunitySettings(BaseModel):
    title: str = Field(min_length=1,max_length=60)
    image_data: str = Field(max_length=2_000_100)
    expires_at: datetime | None = None


@app.post("/api/admin/community")
def configure_community(payload: CommunitySettings, request: Request) -> dict:
    require_local_admin(request)
    try:
        return community.configure(payload.title,payload.image_data,payload.expires_at)
    except ValueError as exc:
        raise HTTPException(400,detail=str(exc)) from exc


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/web/")


@app.get("/data/road_equipment_references.json")
def public_reference_file() -> dict:
    return public_road_references(ROOT)


@app.get("/data/directories.json")
def public_directory_file() -> dict:
    return public_directories(ROOT)


app.mount("/data", StaticFiles(directory=str(DATA)), name="data")
app.mount("/web", StaticFiles(directory=str(WEB), html=True), name="web")

