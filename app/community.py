"""微信群交流入口；仅本机管理员配置，公开端只读取入群二维码。"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.catalog.storage import atomic_json


class Community:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self) -> dict:
        try:
            settings = json.loads((self.root/"config/community.json").read_text(encoding="utf-8"))
            expires = settings.get("expires_at")
            expired = bool(expires and datetime.fromisoformat(expires) < datetime.now(timezone.utc))
            return {"configured":True, "available":not expired, "expired":expired,
                    "title":settings["title"], "image_url":settings["image_url"],
                    "expires_at":expires, "updated_at":settings["updated_at"]}
        except (OSError, ValueError, KeyError, TypeError):
            return {"configured":False, "available":False, "title":"BikeHunt 骑行好价交流群"}

    def configure(self, title: str, image_data: str, expires_at: datetime | None = None) -> dict:
        """接收管理员主动选择的 PNG/JPEG 二维码，禁止脚本或外链图片。"""
        if expires_at and (expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc)):
            raise ValueError("有效期必须为未来的时间")
        header, _, encoded = image_data.partition(",")
        try:
            body = base64.b64decode(encoded,validate=True)
        except ValueError as exc:
            raise ValueError("二维码图片格式无效") from exc
        if len(body)>1_500_000:
            raise ValueError("二维码图片不能超过 1.5 MB")
        if header=="data:image/png;base64" and body.startswith(b"\x89PNG\r\n\x1a\n"):
            extension="png"
        elif header=="data:image/jpeg;base64" and body.startswith(b"\xff\xd8"):
            extension="jpg"
        else:
            raise ValueError("请选择 PNG 或 JPG 二维码图片")
        if not title.strip() or len(title)>60:
            raise ValueError("群名称不能为空，且不得超过 60 个字")
        folder=self.root/"web/assets/community"
        folder.mkdir(parents=True,exist_ok=True)
        filename="group_"+hashlib.sha256(body).hexdigest()[:16]+"."+extension
        (folder/filename).write_bytes(body)
        atomic_json(self.root/"config/community.json", {
            "title":title.strip(), "image_url":"/web/assets/community/"+filename,
            "expires_at":expires_at.isoformat() if expires_at else None,
            "updated_at":datetime.now(timezone.utc).isoformat(),
        })
        return self.get()
