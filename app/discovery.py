"""品牌/车队辅助目录；区分身份登记、商城核查、规则与实际报价接入。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.catalog.storage import OfferRepository
from app.policies import PolicyRepository
from loguru import logger


def directories(root: Path) -> dict:
    data = json.loads((root / "data" / "directories.json").read_text(encoding="utf-8"))
    offers = OfferRepository(root / "data").load()
    rules = PolicyRepository(root)
    try:
        ranking = json.loads((root / "data/team_ranking_2026.json").read_text(encoding="utf-8"))
        if ranking["season"] != 2026 or date.fromisoformat(ranking["ranking_date"]).year != 2026:
            raise ValueError("Ranking season mismatch")
        ranks = {row["code"]: row for row in ranking["rows"]}
        if any(not isinstance(row["rank"], int) or row["rank"] < 1 for row in ranks.values()):
            raise ValueError("Invalid team rank")
        data["team_ranking"] = {key: value for key, value in ranking.items() if key != "rows"}
        for entry in data["teams"]:
            if entry["code"] in ranks:
                entry["world_rank"] = ranks[entry["code"]]["rank"]
                entry["ranking_points"] = ranks[entry["code"]]["points"]
        data["teams"].sort(key=lambda row: row.get("world_rank", float("inf")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("车队排名暂不可读 {}", type(exc).__name__)
    for section in ("brands", "teams"):
        for entry in data[section]:
            code = entry["code"]
            codes = entry.get("source_codes",[code])
            entry["offer_count"] = sum(row.source_code in codes for row in offers)
            book = rules.get(code, entry["name_zh"])
            entry["rule_count"] = sum(doc.state == "translated" for doc in book.documents)
            entry["rules_state"] = "changed" if any(d.state == "changed" for d in book.documents) else "translated" if entry["rule_count"] else "pending"
    return data
