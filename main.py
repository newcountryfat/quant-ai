#!/usr/bin/env python3
"""QuantAI Guardian — single-command entry point."""

from __future__ import annotations

import asyncio
import signal
import subprocess
import sys
from pathlib import Path

import uvicorn
from loguru import logger

from core.config import settings
from core.db import init_schema
from core.event_bus import LocalEventBus
from services.api import app as fastapi_app, set_services
from services.data_service.main import DataService
from services.strategy_service.main import StrategyService
from services.monitor_service.main import MonitorService
from services.report_service.main import ReportService
from services.risk_service.main import RiskService
from services.paper_trading.main import PaperTradingService
from services.scheduler import SchedulerService

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def _setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, format=LOG_FORMAT, level="INFO")
    log_file = settings.log_dir / "quant_platform.log"
    logger.add(str(log_file), rotation="50 MB", retention="30 days", level="DEBUG")


async def _run_api_server() -> None:
    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=settings.api_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    _setup_logging()
    logger.info("=== QuantAI Guardian starting ===")

    settings.ensure_dirs()
    init_schema()

    bus = LocalEventBus()

    data_svc = DataService(bus)
    strategy_svc = StrategyService(bus)
    monitor_svc = MonitorService(bus)
    report_svc = ReportService(bus)
    risk_svc = RiskService(bus)
    paper_svc = PaperTradingService(bus)
    scheduler_svc = SchedulerService(bus, data_svc=data_svc)

    set_services(bus, data_svc, strategy_svc, monitor_svc, report_svc, risk_svc, paper_svc)

    await data_svc.start()
    await strategy_svc.start()
    await monitor_svc.start()
    await report_svc.start()
    await risk_svc.start()
    await paper_svc.start()
    await scheduler_svc.start()

    logger.info(
        "All services started. API at http://localhost:{}", settings.api_port
    )

    await _run_api_server()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down …")
