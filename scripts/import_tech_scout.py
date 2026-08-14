#!/usr/bin/env python3
"""
CLI wrapper for the one-off import: copy tools already saved in tech-scout's
SQLite DB into call-copilot's tools catalog. Same logic the Settings panel's
"Sincronizar tech-scout" button calls (src/processing/tool_extractor.py's
import_from_tech_scout) — this script exists for scripted/headless use.

Usage:
    .venv/bin/python scripts/import_tech_scout.py [--db PATH]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config_defaults import tech_scout_db_path
from src.db.database import init_db
from src.processing.tool_extractor import import_from_tech_scout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=Path(tech_scout_db_path()),
        help="Path to tech-scout's tools.db",
    )
    args = parser.parse_args()

    init_db()

    try:
        imported, skipped = import_from_tech_scout(str(args.db))
    except FileNotFoundError:
        print(f"source DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    print(f"{imported} imported, {skipped} skipped (already in catalog)")


if __name__ == "__main__":
    main()
