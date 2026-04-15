from __future__ import annotations

import shutil
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from core.config import settings
from core.event_bus import LocalEventBus
from core.job_logger import record_job_log


class SchedulerService:
    def __init__(self, bus: LocalEventBus, data_svc=None) -> None:
        self._bus = bus
        self._data_svc = data_svc
        self._scheduler: AsyncIOScheduler | None = None

    async def start(self) -> None:
        try:
            settings.ensure_dirs()
            settings.backup_dir.mkdir(parents=True, exist_ok=True)
            (settings.data_dir / "reports").mkdir(parents=True, exist_ok=True)

            if settings.research_universe_bootstrap_on_start and self._data_svc is not None:
                result = await self._data_svc.bootstrap_research_universe()
                record_job_log(
                    "scheduler_startup_bootstrap",
                    "success",
                    "Bootstrapped research universe during scheduler startup",
                    result,
                )
                logger.info("Research universe bootstrapped on start: {}", result)

            self._scheduler = AsyncIOScheduler()
            self._scheduler.add_job(
                self._job_data_update,
                IntervalTrigger(hours=4),
                id="data_update",
                replace_existing=True,
            )
            self._scheduler.add_job(
                self._job_health_check,
                IntervalTrigger(minutes=5),
                id="health_check",
                replace_existing=True,
            )
            self._scheduler.add_job(
                self._job_daily_report,
                CronTrigger(day_of_week="mon-fri", hour=20, minute=0),
                id="daily_report",
                replace_existing=True,
            )
            self._scheduler.add_job(
                self._job_backup,
                CronTrigger(hour=2, minute=0),
                id="backup",
                replace_existing=True,
            )
            if settings.research_universe_sync_enabled and self._data_svc is not None:
                self._scheduler.add_job(
                    self._job_research_universe_sync,
                    CronTrigger(
                        day_of_week="mon-fri",
                        hour=settings.research_universe_sync_hour,
                        minute=settings.research_universe_sync_minute,
                    ),
                    id="research_universe_sync",
                    replace_existing=True,
                )
            if settings.market_breadth_sync_enabled and self._data_svc is not None:
                self._scheduler.add_job(
                    self._job_market_breadth_sync,
                    CronTrigger(
                        day_of_week="mon-fri",
                        hour=settings.market_breadth_sync_hour,
                        minute=settings.market_breadth_sync_minute,
                    ),
                    id="market_breadth_sync",
                    replace_existing=True,
                )
            if settings.a500_sync_enabled and self._data_svc is not None:
                self._scheduler.add_job(
                    self._job_a500_sync,
                    CronTrigger(day_of_week="mon-fri", hour=18, minute=20),
                    id="a500_sync",
                    replace_existing=True,
                )
            self._scheduler.start()
            logger.info("SchedulerService started (data/health/report/backup/universe/breadth/A500 jobs)")
        except Exception:
            logger.exception("SchedulerService.start failed")

    async def _job_data_update(self) -> None:
        try:
            await self._bus.publish(
                "data.update",
                {"trigger": "scheduler", "ts": datetime.now().isoformat()},
            )
        except Exception:
            logger.exception("data_update job failed")

    async def _job_health_check(self) -> None:
        try:
            await self._bus.publish(
                "system.health",
                {"trigger": "scheduler", "ts": datetime.now().isoformat()},
            )
        except Exception:
            logger.exception("health_check job failed")

    async def _job_daily_report(self) -> None:
        try:
            await self._bus.publish(
                "report.daily",
                {"trigger": "scheduler", "ts": datetime.now().isoformat()},
            )
        except Exception:
            logger.exception("daily_report job failed")

    async def _job_a500_sync(self) -> None:
        if not settings.a500_sync_enabled or self._data_svc is None:
            return
        try:
            r = await self._data_svc.sync_a500()
            record_job_log("scheduler_a500_sync", "success", "Scheduled A500 sync finished", r)
            logger.info("A500 sync job finished: {}", r)
        except Exception:
            record_job_log("scheduler_a500_sync", "failed", "Scheduled A500 sync failed")
            logger.exception("A500 sync job failed")

    async def _job_research_universe_sync(self) -> None:
        if not settings.research_universe_sync_enabled or self._data_svc is None:
            return
        try:
            index_result = await self._data_svc.sync_research_universe_incremental(
                asset_type="index",
                default_lookback_days=settings.research_sync_lookback_days,
                overlap_days=settings.research_sync_overlap_days,
            )
            etf_result = await self._data_svc.sync_research_universe_incremental(
                asset_type="etf",
                default_lookback_days=settings.research_sync_lookback_days,
                overlap_days=settings.research_sync_overlap_days,
            )
            record_job_log(
                "scheduler_research_universe_sync",
                "success",
                "Scheduled research universe incremental sync finished",
                {"index": index_result, "etf": etf_result},
            )
            logger.info("Research universe sync finished: index={}, etf={}", index_result, etf_result)
        except Exception:
            record_job_log(
                "scheduler_research_universe_sync",
                "failed",
                "Scheduled research universe incremental sync failed",
            )
            logger.exception("Research universe sync job failed")

    async def _job_market_breadth_sync(self) -> None:
        if not settings.market_breadth_sync_enabled or self._data_svc is None:
            return
        try:
            result = await self._data_svc.rebuild_market_breadth_recent(
                lookback_days=settings.market_breadth_lookback_days
            )
            record_job_log(
                "scheduler_market_breadth_sync",
                "success",
                "Scheduled market breadth rebuild finished",
                result,
            )
            logger.info("Market breadth sync finished: {}", result)
        except Exception:
            record_job_log(
                "scheduler_market_breadth_sync",
                "failed",
                "Scheduled market breadth rebuild failed",
            )
            logger.exception("Market breadth sync job failed")

    async def _job_backup(self) -> None:
        try:
            src = settings.db_path.resolve()
            if not src.exists():
                logger.warning("backup skipped: db not found at {}", src)
                return
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dst = settings.backup_dir / f"quant_platform_{stamp}.db"
            shutil.copy2(src, dst)
            await self._bus.publish(
                "backup.completed",
                {"path": str(dst), "trigger": "scheduler"},
            )
            logger.info("database backup written to {}", dst)
        except Exception:
            logger.exception("backup job failed")
