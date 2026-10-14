"""独立规则采集入口；中文摘要发布前应对应最新原文指纹。"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from app.policies import collect_rules


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source")
    args = parser.parse_args()
    print(json.dumps(collect_rules(ROOT, args.source), ensure_ascii=False))
