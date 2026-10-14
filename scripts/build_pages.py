"""构建 GitHub Pages：python scripts/build_pages.py。"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pages import build_public_site

if __name__ == "__main__":
    print(json.dumps(build_public_site(ROOT), ensure_ascii=True))
