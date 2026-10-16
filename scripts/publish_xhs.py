"""Private Xiaohongshu daily outbox CLI; browser publication is a separate explicit step."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.catalog.storage import atomic_json
from app.social_publishing import DailyPublisher, render_card


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["configure", "prepare", "reserve", "begin", "receipt", "unknown"]
    )
    parser.add_argument("--account")
    parser.add_argument("--job")
    parser.add_argument("--note-id")
    parser.add_argument("--note-url")
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/msyh.ttc"))
    args = parser.parse_args()
    config_path = ROOT / "storage/social/config.json"
    if args.action == "configure":
        DailyPublisher(ROOT, args.account or "")
        atomic_json(
            config_path, {"account_id": args.account, "timezone": "Asia/Shanghai", "hour": 18}
        )
        print(json.dumps({"status": "configured", "account_id": args.account}))
        return
    config = json.loads(config_path.read_text(encoding="utf-8"))
    publisher = DailyPublisher(ROOT, config["account_id"])
    if args.action in {"prepare", "reserve"}:
        result = getattr(publisher, args.action)()
        payload = result.get("payload", result)
        if payload.get("status") == "ready":
            render_card(payload, publisher.folder / "cover.png", args.font)
        result = {k: v for k, v in result.items() if k not in {"payload", "text", "cards"}}
    elif args.action == "begin":
        result = publisher.begin(args.job or "")
    elif args.action == "receipt":
        result = publisher.receipt(args.job or "", args.note_id or "", args.note_url or "")
    else:
        publisher.unknown(args.job or "")
        result = {"status": "unknown"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
