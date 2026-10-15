"""Public group QR settings, with a private local-admin override and strict expiry."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.catalog.storage import atomic_json

DEFAULT_TITLE = "骑游海淘交流群"
IMAGE_PATH = re.compile(r"/web/assets/community/[A-Za-z0-9][A-Za-z0-9_-]*\.(?:png|jpg|jpeg)\Z")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z")


def expiry_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


class Community:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self, now: datetime | None = None) -> dict:
        """Project only public fields. Invalid overrides never revive an older QR."""
        result = {"schema_version": 1, "configured": False, "available": False,
                  "expired": False, "title": DEFAULT_TITLE, "status": "unconfigured"}
        local = self.root / "config/community.json"
        source = local if local.exists() else self.root / "data/community.json"
        try:
            settings = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                raise ValueError("Invalid settings")
            result.update(configured=True, status="invalid")
            if settings.get("schema_version", 1 if source == local else None) != 1:
                return result
            title = settings.get("title")
            if not isinstance(title, str) or not title.strip() or len(title) > 60:
                return result
            result["title"] = title.strip()
            expires = expiry_time(settings.get("expires_at"))
            if expires is None:
                return result
            result["expires_at"] = expires.isoformat()
            result["expired"] = expires <= (now or datetime.now(timezone.utc))
            if result["expired"]:
                result["status"] = "expired"
                return result
            image = settings.get("image_url")
            if not isinstance(image, str) or not IMAGE_PATH.fullmatch(image):
                return result
            source_image = (self.root / image.lstrip("/")).resolve()
            asset_folder = (self.root / "web/assets/community").resolve()
            if (not source_image.is_relative_to(asset_folder)
                    or not source_image.is_relative_to((self.root / "web").resolve())
                    or not source_image.is_file()):
                return result
            result.update(available=True, status="available", image_url=image)
            for field in ("revision", "updated_at", "expiry_label"):
                value = settings.get(field)
                if isinstance(value, str) and 0 < len(value) <= 100:
                    result[field] = value
            return result
        except (OSError, ValueError, KeyError, TypeError):
            return result

    def configure(self, title: str, image_data: str, expires_at: datetime | None = None) -> dict:
        """Accept an explicitly chosen PNG/JPEG; unknown expiry stays fail-closed."""
        if not expires_at or expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc):
            raise ValueError("请填写微信标注的有效期，且必须为未来的时间")
        header, _, encoded = image_data.partition(",")
        try:
            body = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("二维码图片格式无效") from exc
        if len(body) > 1_500_000:
            raise ValueError("二维码图片不能超过 1.5 MB")
        if header == "data:image/png;base64" and body.startswith(b"\x89PNG\r\n\x1a\n"):
            extension = "png"
        elif header == "data:image/jpeg;base64" and body.startswith(b"\xff\xd8"):
            extension = "jpg"
        else:
            raise ValueError("请选择 PNG 或 JPG 二维码图片")
        if not title.strip() or len(title) > 60:
            raise ValueError("群名称不能为空，且不得超过 60 个字")
        folder = self.root / "web/assets/community"
        folder.mkdir(parents=True, exist_ok=True)
        revision = hashlib.sha256(body).hexdigest()[:16]
        filename = "group_" + revision + "." + extension
        (folder / filename).write_bytes(body)
        atomic_json(self.root / "config/community.json", {
            "schema_version": 1, "revision": revision,
            "title": title.strip(), "image_url": "/web/assets/community/" + filename,
            "expires_at": expires_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        return self.get()
