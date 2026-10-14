"""个人提醒绑定与按价格事件去重的推送；密钥不进入公开数据目录。"""
from __future__ import annotations

import json
import secrets
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import certifi
from loguru import logger

from app.catalog.storage import atomic_json
from app.catalog.models import FxSnapshot, Money
from app.catalog.service import convert
from app.fx import FxProvider
from app.localization import CATEGORIES
from app.updates import UpdateStore

API = "https://wxpusher.zjiecode.com/api"


class PersonalNotifier:
    def __init__(self, root: Path, request=None,
                 fx_loader: Callable[[], FxSnapshot] | None = None) -> None:
        self.root = root
        self.events = UpdateStore(root)
        self.request = request or self._request
        self.fx_loader = fx_loader or FxProvider(root / "data" / "fx_latest.json").get
        with self.events.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS subscribers (
                device TEXT PRIMARY KEY, uid TEXT, categories TEXT NOT NULL DEFAULT '["all"]',
                enabled INTEGER NOT NULL DEFAULT 0, cursor INTEGER NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS bindings (
                device TEXT PRIMARY KEY, code TEXT NOT NULL, image_url TEXT NOT NULL,
                expires REAL NOT NULL, last_poll REAL NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
                delivery_key TEXT PRIMARY KEY, device TEXT NOT NULL, state TEXT NOT NULL,
                attempted_at TEXT NOT NULL, provider_record TEXT)""")

    def settings(self) -> dict:
        try:
            return json.loads((self.root / "config" / "notifications.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def configure(self, token: str) -> None:
        """仅由本机管理接口调用；不在返回值或日志中回显密钥。"""
        if not token.startswith("AT_") or len(token) < 10:
            raise ValueError("请输入推送服务应用的有效 AppToken")
        atomic_json(self.root / "config" / "notifications.json", {"app_token":token})

    def preferences(self, device: str) -> dict:
        with self.events.connect() as db:
            db.execute("INSERT OR IGNORE INTO subscribers(device,cursor) VALUES (?,?)", (device,self.events.cursor()))
            row = db.execute("SELECT * FROM subscribers WHERE device=?",(device,)).fetchone()
        return {"configured":bool(self.settings().get("app_token")), "bound":bool(row["uid"]),
                "enabled":bool(row["enabled"]),"categories":json.loads(row["categories"]),
                "provider":"WxPusher", "wechat_channel_required":True}

    def save_preferences(self, device: str, categories: list[str], enabled: bool) -> dict:
        valid = {x["code"] for x in CATEGORIES}
        if not categories or any(code not in valid for code in categories):
            raise ValueError("请选择有效产品类型")
        self.preferences(device)
        with self.events.connect() as db:
            db.execute("UPDATE subscribers SET categories=?,enabled=? WHERE device=?",
                       (json.dumps(categories),int(enabled),device))
        return self.preferences(device)

    def create_binding(self, device: str) -> dict:
        token = self.settings().get("app_token")
        if not token:
            return {"configured":False,"message":"请先在电脑本机设置页配置个人推送服务，之后用户可扫码绑定。"}
        with self.events.connect() as db:
            existing = db.execute("SELECT * FROM bindings WHERE device=?",(device,)).fetchone()
        if existing and existing["expires"] > time.time():
            return {"configured":True,"image_url":existing["image_url"],"expires_at":existing["expires"]}
        response = self.request("POST", "/fun/create/qrcode", {"appToken":token,"extra":secrets.token_hex(16),"validTime":1800})
        data = response.get("data") or {}
        image = data.get("url") or data.get("qrcodeUrl") or data.get("qrcode")
        code = data.get("code")
        parsed = urllib.parse.urlsplit(image or "")
        if not code or parsed.scheme != "https" or parsed.hostname != "wxpusher.zjiecode.com":
            raise ValueError("推送服务未返回有效绑定二维码")
        expires = time.time()+1800
        with self.events.connect() as db:
            db.execute("INSERT OR REPLACE INTO bindings(device,code,image_url,expires,last_poll) VALUES (?,?,?,?,0)",
                       (device,code,image,expires))
        return {"configured":True,"image_url":image,"expires_at":expires}

    def binding_status(self, device: str) -> dict:
        status = self.preferences(device)
        if status["bound"]:
            return status
        with self.events.connect() as db:
            binding = db.execute("SELECT * FROM bindings WHERE device=?",(device,)).fetchone()
            if not binding or binding["expires"] <= time.time() or time.time()-binding["last_poll"]<10:
                return status
            db.execute("UPDATE bindings SET last_poll=? WHERE device=?",(time.time(),device))
        response = self.request("GET", "/fun/scan-qrcode-uid?"+urllib.parse.urlencode({"code":binding["code"]}), None)
        uid = response.get("data")
        if isinstance(uid,str) and uid.startswith("UID_"):
            with self.events.connect() as db:
                db.execute("UPDATE subscribers SET uid=?,enabled=1,cursor=? WHERE device=?",
                           (uid,self.events.cursor(),device))
                db.execute("DELETE FROM bindings WHERE device=?",(device,))
        return self.preferences(device)

    def dispatch(self) -> None:
        """仅向已扫码绑定、主动启用的订阅者发送新事件；不发送模拟价格。"""
        token = self.settings().get("app_token")
        if not token:
            return
        with self.events.connect() as db:
            subscribers = db.execute("SELECT * FROM subscribers WHERE enabled=1 AND uid IS NOT NULL").fetchall()
        if not subscribers:
            return
        fx = self.fx_loader()
        for subscriber in subscribers:
            rows = self.events.pending(subscriber["cursor"],limit=100)
            if not rows:
                continue
            latest_cursor = max(row["id"] for row in rows)
            categories = json.loads(subscriber["categories"])
            selected = [r for r in rows if "all" in categories or r["category"] in categories]
            if not selected:
                with self.events.connect() as db:
                    db.execute("UPDATE subscribers SET cursor=? WHERE device=?",(latest_cursor,subscriber["device"]))
                continue
            delivery_key = f"{subscriber['uid']}:{min(r['id'] for r in selected)}:{max(r['id'] for r in selected)}"
            with self.events.connect() as db:
                inserted = db.execute("INSERT OR IGNORE INTO deliveries(delivery_key,device,state,attempted_at) VALUES (?,?,?,?)",
                                      (delivery_key,subscriber["device"],"sending",datetime.now(timezone.utc).isoformat())).rowcount
                db.execute("UPDATE subscribers SET cursor=? WHERE device=?",(latest_cursor,subscriber["device"]))
            if not inserted:
                continue
            lines=["BikeHunt 精选好价 · 最新价格信息"]
            for event in selected[:5]:
                before = event["old_price"]
                label = "库存更新" if event["kind"] == "inventory_changed" else "价格更新" if before else "新发现报价"
                text = f"{event['source_name']}：{event['name_zh']}\n{label} · {event['currency']} {before+' → ' if before and event['kind']=='price_changed' else ''}{event['new_price']}"
                cny = convert(Money(amount=event["new_price"], currency=event["currency"]), fx)
                text += f" · 约人民币 {cny} 元" if cny is not None else " · 人民币汇率待获取"
                if event["stock"] == "out_of_stock":
                    text += "（所示报价已售罄）"
                lines.append(text)
            if len(selected) > 5:
                lines.append(f"另有 {len(selected)-5} 条更新，请在网站消息查看。")
            lines.append(f"汇率日期：{fx.rate_date or '待获取'}" + ("（过期缓存）" if fx.stale else ""))
            lines.append("商品参考价；直邮、卡种、运费及税费请在 BikeHunt 中文指引中核实。")
            try:
                response = self.request("POST", "/send/message", {
                    "appToken":token,"content":"\n\n".join(lines),"summary":"BikeHunt 有新价格更新",
                    "contentType":1,"uids":[subscriber["uid"]],
                }, allow_ambiguous_retry=False)
                records = response.get("data") or []
                good = bool(records) and all(r.get("code")==1000 for r in records)
                state = "queued" if good else "rejected"
                details = json.dumps([r.get("sendRecordId") for r in records])
            except Exception as exc:
                logger.warning("提醒提交结果未确认 {}",type(exc).__name__)
                state,details = "delivery_unknown",None
            with self.events.connect() as db:
                db.execute("UPDATE deliveries SET state=?,provider_record=? WHERE delivery_key=?",(state,details,delivery_key))

    @staticmethod
    def _request(method: str, path: str, payload: dict | None,
                 allow_ambiguous_retry: bool = True) -> dict:
        body=json.dumps(payload).encode() if payload is not None else None
        context=ssl.create_default_context(cafile=certifi.where())
        for attempt in range(3 if allow_ambiguous_retry else 1):
            try:
                request=urllib.request.Request(API+path,data=body,method=method,
                    headers={"Content-Type":"application/json","User-Agent":"BikeHunt/0.3"})
                with urllib.request.urlopen(request,timeout=12,context=context) as response:
                    result=json.load(response)
                if result.get("code")!=1000 or not result.get("success"):
                    raise ValueError("推送服务未接受请求，状态码 "+str(result.get("code")))
                return result
            except Exception as exc:
                logger.warning("个人提醒接口失败 attempt={}/3 {}",attempt+1,type(exc).__name__)
                if attempt==2 or not allow_ambiguous_retry or isinstance(exc,ValueError):
                    raise
                time.sleep(2**attempt)
        raise RuntimeError("Push request exhausted")
