#!/usr/bin/env python3
"""Initialize the SQLite database schema."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings
from core.db import init_schema


def main():
    settings.ensure_dirs()
    init_schema()
    print(f"Database initialized at {settings.db_path}")


if __name__ == "__main__":
    main()
