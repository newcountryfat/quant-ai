#!/usr/bin/env python3
"""命令行触发中证 A500 日线同步 + 自选（适合长时间任务，避免 HTTP 超时）。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 保证可 import 项目根
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings
from core.db import init_schema
from core.event_bus import LocalEventBus
from services.data_service.main import DataService


async def main() -> None:
    settings.ensure_dirs()
    init_schema()
    bus = LocalEventBus()
    svc = DataService(bus)
    await svc.start()
    r = await svc.sync_a500()
    print(r)


if __name__ == "__main__":
    asyncio.run(main())
