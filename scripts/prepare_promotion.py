"""Prepare evidence-bound local drafts; never publish or contact a platform."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.promotion import PromotionPreparer, timestamp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成本地待人工复核包，默认从现在开始，不回填旧消息、不联网、不发布。")
    parser.add_argument("--root", type=Path, default=ROOT, help="BikeHunt 数据目录所在项目根目录")
    parser.add_argument("--since", help="显式历史复核开始时间（含时区），必须同时指定 --until")
    parser.add_argument("--until", help="显式历史复核结束时间（含时区），窗口最多 7 天")
    args = parser.parse_args(argv)
    if bool(args.since) != bool(args.until):
        parser.error("--since 和 --until 必须一起提供")
    since, until = timestamp(args.since), timestamp(args.until)
    if args.since and (since is None or until is None):
        parser.error("历史复核时间必须是带时区的 ISO 8601 时间")
    try:
        report = PromotionPreparer(args.root).prepare(since=since, until=until)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
