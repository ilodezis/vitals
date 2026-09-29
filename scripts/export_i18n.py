"""Export the UI strings for the React app: ``frontend/src/i18n/<lang>.json``.

``vitals/i18n.py`` stays the one source of every string, server-rendered or not;
the client gets the same dictionaries as JSON (``npm --prefix frontend run
gen:i18n`` calls this). ``tests/test_api_contract.py`` fails when they drift.

    python scripts/export_i18n.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vitals.i18n import STRINGS  # noqa: E402

OUT_DIR = ROOT / "frontend" / "src" / "i18n"


def render(lang: str) -> str:
    """Keys sorted: the two dictionaries line up row for row, and a new string is
    a one-line diff wherever it was added in ``vitals/i18n.py``."""
    return json.dumps(STRINGS[lang], indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for lang in STRINGS:
        path = OUT_DIR / f"{lang}.json"
        path.write_text(render(lang), encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)} ({len(STRINGS[lang])} strings)")


if __name__ == "__main__":
    main()
