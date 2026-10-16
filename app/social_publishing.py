"""Private daily Xiaohongshu outbox; browser execution and receipts are explicit."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from loguru import logger

from app.catalog.storage import atomic_json
from app.localization import title_zh
from app.promotion import HOMEPAGE_URL, PromotionPreparer, timestamp

SHANGHAI = ZoneInfo("Asia/Shanghai")


class DailyPublisher:
    """One account, one daily reservation, and no automatic retry after submission."""

    def __init__(self, root: Path, account_id: str) -> None:
        if not re.fullmatch(r"\d{4,20}", account_id):
            raise ValueError("A verified Xiaohongshu account ID is required")
        self.root = root.resolve()
        self.account = account_id
        self.folder = self.root / "storage/social"
        if not self.folder.resolve().is_relative_to(self.root / "storage"):
            raise ValueError("Social data must remain in private storage")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.preparer = PromotionPreparer(root)
        self.path = self.folder / "publishing.sqlite3"
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS posts (
                job_id TEXT PRIMARY KEY, account TEXT NOT NULL, day TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL, note_id TEXT, note_url TEXT,
                updated_at TEXT NOT NULL, UNIQUE(account,day))""")
            db.execute("""CREATE TABLE IF NOT EXISTS members (
                account TEXT NOT NULL, draft_key TEXT NOT NULL, job_id TEXT NOT NULL,
                PRIMARY KEY(account,draft_key))""")

    @contextmanager
    def connect(self):
        """Close the SQLite connection after a bounded transaction."""
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def check_schedule(self, now: datetime | None = None) -> dict:
        """Persist Shanghai publishing-window status before inspecting deal changes."""
        now = timestamp(now or datetime.now(timezone.utc))
        if now is None:
            raise ValueError("Timezone-aware time required")
        local = now.astimezone(SHANGHAI)
        scheduled = local.replace(hour=18, minute=0, second=0, microsecond=0)
        preparation = scheduled - timedelta(minutes=15)
        closes = scheduled + timedelta(hours=1)
        if local < preparation:
            status = "outside_preparation"
        elif local < scheduled:
            status = "waiting"
        else:
            status = "open" if local < closes else "missed"
        result = {
            "schema_version": 1,
            "day": local.date().isoformat(),
            "timezone": "Asia/Shanghai",
            "checked_at": local.isoformat(),
            "preparation_at": preparation.isoformat(),
            "scheduled_at": scheduled.isoformat(),
            "window_closes_at": closes.isoformat(),
            "status": status,
            "can_publish": status == "open",
            "wait_seconds": max(0, ceil((scheduled - local).total_seconds())) if status == "waiting" else 0,
            "lateness_seconds": max(0, int((local - scheduled).total_seconds())),
            "alert_required": status in {"missed", "outside_preparation"},
        }
        atomic_json(self.folder / "schedule.json", result)
        if status == "missed":
            logger.warning("Daily publication window missed on {} at {}", result["day"], result["checked_at"])
        return result

    def prepare(self, now: datetime | None = None) -> dict:
        """Revalidate exact evidence and export public text only; never submit a note."""
        now = timestamp(now or datetime.now(timezone.utc))
        if now is None:
            raise ValueError("Timezone-aware time required")
        self.preparer.prepare(now=now)
        queue = json.loads((self.preparer.output / "queue.json").read_text(encoding="utf-8"))
        with self.connect() as db:
            used = {
                r[0]
                for r in db.execute(
                    "SELECT draft_key FROM members WHERE account=?", (self.account,)
                )
            }
        candidates = [
            p
            for p in queue["drafts"]
            if p["status"] == "pending_review"
            and p["draft_key"] not in used
            and timestamp(p["valid_until"]) > now + timedelta(minutes=10)
        ]
        candidates.sort(key=lambda p: (p["created_at"], p["draft_key"]), reverse=True)
        chosen, blocks = [], []
        for package in candidates:
            g, e = package["group"], package["evidence"][0]
            change = " / ".join({"price_drop": "降价", "restock": "补货"}[c] for c in g["changes"])
            price = g["currency"] + " " + g["new_price"]
            if "price_drop" in g["changes"]:
                price = g["currency"] + " " + g["old_price"] + " → " + price
            block = (
                f"{change}｜{title_zh(e['name'])}\n{title_zh(g['color'])} · 尺码 {' / '.join(package['sizes'])}\n"
                f"{price}\n{e['source_name']} · {g['market']}"
            )
            if len(block) > 350 or sum(map(len, blocks)) + len(block) > 680:
                continue
            chosen.append(package)
            blocks.append(block)
            if len(chosen) == 3:
                break
        local = now.astimezone(SHANGHAI)
        payload = {
            "schema_version": 1,
            "account_id": self.account,
            "day": local.date().isoformat(),
            "status": "ready" if chosen else "no_changes",
            "prepared_at": now.isoformat(),
            "draft_keys": [p["draft_key"] for p in chosen],
            "valid_until": min(p["valid_until"] for p in chosen) if chosen else None,
            "title": local.strftime("%m月%d日骑行好价更新"),
            "text": (
                (
                    "今天核实的降价与补货：\n\n"
                    + "\n\n".join(blocks)
                    + "\n\n核实于 "
                    + local.strftime("%m-%d %H:%M")
                    + "（北京时间）。价格为商品原币价，运费税费另核；库存随时变化。"
                    + "\n中文购买步骤及同规格比价："
                    + HOMEPAGE_URL
                    + "\n#骑行装备 #骑行服 #海淘"
                )
                if chosen
                else ""
            ),
            "cards": [
                {
                    "name": title_zh(p["evidence"][0]["name"]),
                    "group": p["group"],
                    "sizes": p["sizes"],
                }
                for p in chosen
            ],
        }
        payload["content_hash"] = hashlib.sha256(
            json.dumps(
                {
                    k: payload[k]
                    for k in ("account_id", "day", "draft_keys", "title", "text", "cards")
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        atomic_json(self.folder / "candidate.json", payload)
        (self.folder / "note.txt").write_text(payload["text"], encoding="utf-8")
        return payload

    def reserve(self, now: datetime | None = None) -> dict:
        """Reserve only within today's 18:00 hour and stop on unresolved submissions."""
        now = timestamp(now or datetime.now(timezone.utc))
        if now is None or now.astimezone(SHANGHAI).hour != 18:
            raise ValueError("Publishing is limited to 18:00–18:59 Asia/Shanghai")
        payload = self.prepare(now)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM posts WHERE account=? AND status IN ('attempting','unknown')",
                (self.account,),
            ).fetchone():
                raise ValueError("Reconcile the unresolved note before any further publication")
            previous = db.execute(
                "SELECT * FROM posts WHERE account=? AND day=?", (self.account, payload["day"])
            ).fetchone()
            if previous:
                return {"status": "daily_limit", "job_id": previous["job_id"]}
            if payload["status"] != "ready":
                return {"status": "no_changes"}
            job_id = payload["content_hash"]
            db.execute(
                "INSERT INTO posts VALUES (?,?,?,?,?,NULL,NULL,?)",
                (
                    job_id,
                    self.account,
                    payload["day"],
                    "reserved",
                    json.dumps(payload, ensure_ascii=False),
                    now.isoformat(),
                ),
            )
        logger.info("Reserved Xiaohongshu daily note {}", job_id)
        return {"status": "reserved", "job_id": job_id, "payload": payload}

    def begin(self, job_id: str, now: datetime | None = None) -> dict:
        """Recheck just before the final browser click; subsequent crashes fence retries."""
        now = timestamp(now or datetime.now(timezone.utc))
        if now is None or now.astimezone(SHANGHAI).hour != 18:
            raise ValueError("Outside the approved publishing hour")
        fresh = self.prepare(now)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM posts WHERE job_id=? AND account=?", (job_id, self.account)
            ).fetchone()
            if not row or row["status"] != "reserved" or row["day"] != fresh["day"]:
                raise ValueError("No current reserved daily note")
            payload = json.loads(row["payload"])
            # Ignore the display time changing by a minute, but require exactly the same products/claims.
            if (
                payload["draft_keys"] != fresh["draft_keys"]
                or payload["cards"] != fresh["cards"]
                or fresh["status"] != "ready"
                or timestamp(payload["valid_until"]) <= now
            ):
                raise ValueError("Price, stock, size or eligibility changed; do not publish")
            for key in payload["draft_keys"]:
                db.execute("INSERT INTO members VALUES (?,?,?)", (self.account, key, job_id))
            db.execute(
                "UPDATE posts SET status='attempting',updated_at=? WHERE job_id=?",
                (now.isoformat(), job_id),
            )
        return {"status": "attempting", "job_id": job_id}

    def receipt(self, job_id: str, note_id: str, note_url: str) -> dict:
        """Record an ID only after the operator verifies the published note in the UI."""
        url = urlsplit(note_url)
        if (
            not re.fullmatch(r"[0-9a-f]{24}", note_id)
            or url.scheme != "https"
            or url.hostname not in {"www.xiaohongshu.com", "creator.xiaohongshu.com"}
            or url.username
            or url.password
            or url.port not in (None, 443)
            or note_id not in url.path.split("/")
        ):
            raise ValueError("An exact published Xiaohongshu note URL and ID are required")
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE posts SET status='published',note_id=?,note_url=?,updated_at=? "
                "WHERE job_id=? AND account=? AND status IN ('attempting','unknown')",
                (note_id, note_url, datetime.now(timezone.utc).isoformat(), job_id, self.account),
            )
            if cursor.rowcount != 1:
                raise ValueError("No unresolved submission matches the receipt")
        logger.info("Recorded published Xiaohongshu note {}", note_id)
        return {"status": "published", "job_id": job_id, "note_id": note_id, "note_url": note_url}

    def unknown(self, job_id: str) -> None:
        """Fence an ambiguous browser result; never auto-resubmit an attempted note."""
        with self.connect() as db:
            db.execute(
                "UPDATE posts SET status='unknown' WHERE job_id=? AND account=? AND status='attempting'",
                (job_id, self.account),
            )


def render_card(payload: dict, output: Path, font_path: Path) -> None:
    """Render a factual PNG from the validated public text, without merchant image downloads."""
    from PIL import Image, ImageDraw, ImageFont

    if payload["status"] != "ready":
        raise ValueError("No verified updates to render")
    canvas = Image.new("RGB", (1080, 1440), "#f5f5f7")
    draw = ImageDraw.Draw(canvas)
    large = ImageFont.truetype(str(font_path), 66)
    normal = ImageFont.truetype(str(font_path), 32)
    small = ImageFont.truetype(str(font_path), 26)
    draw.text((65, 65), "BikeHunt", font=large, fill="#0069e0")
    draw.text((65, 165), payload["title"], font=large, fill="#17191c")
    y = 290
    for card in payload["cards"]:
        g = card["group"]
        lines = [
            card["name"],
            title_zh(g["color"]) + " · 尺码 " + " / ".join(card["sizes"]),
            g["currency"] + " " + g["new_price"],
            g["market"],
        ]
        for index, line in enumerate(lines):
            remaining = line
            limit = 2 if index in (0, 3) else 1
            for line_number in range(limit):
                if not remaining:
                    break
                take = 1
                while (
                    take < len(remaining)
                    and draw.textlength(remaining[: take + 1], font=normal) < 940
                ):
                    take += 1
                text = remaining[:take]
                if line_number == limit - 1 and take < len(remaining):
                    text = text[:-1] + "…"
                draw.text((65, y), text, font=normal, fill="#17191c")
                remaining = remaining[take:]
                y += 44
        y += 30
    if y > 1280:
        raise ValueError("Cover text does not fit; shorten the chosen summary before upload")
    draw.text(
        (65, 1300), "原币商品价｜运费税费另核｜库存以商家结账为准", font=small, fill="#6e737a"
    )
    draw.text((65, 1350), "howard9088.github.io/BikeHunt/", font=small, fill="#0069e0")
    canvas.save(output, format="PNG")
