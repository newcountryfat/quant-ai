from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from typing import Any

import httpx
from loguru import logger

from core.config import settings
from core.db import get_db
from core.event_bus import Event, LocalEventBus


class MonitorService:
    def __init__(self, bus: LocalEventBus) -> None:
        self._bus = bus

    async def start(self) -> None:
        try:
            self._bus.on("risk.alert", self._on_risk_alert)
            self._bus.on("system.health", self._on_system_health)
            logger.info("MonitorService subscribed to risk.alert, system.health")
        except Exception:
            logger.exception("MonitorService.start failed")

    async def _on_risk_alert(self, event: Event) -> None:
        try:
            p = event.payload
            level = str(p.get("level", "info"))
            message = str(p.get("message", ""))
            await self.send_notification(level, message, extra=p)
        except Exception:
            logger.exception("MonitorService risk.alert handler failed")

    async def _on_system_health(self, event: Event) -> None:
        try:
            health = await self.check_system_health()
            for name, value in health.items():
                if isinstance(value, (int, float)):
                    await self.record_metric(
                        name,
                        float(value),
                        tags={"trigger": event.payload.get("trigger", "event")},
                    )
            await self._bus.publish(
                "system.health.result",
                {"health": health, "source_event": event.payload},
            )
        except Exception:
            logger.exception("MonitorService system.health handler failed")

    async def check_system_health(self) -> dict[str, float]:
        try:
            disk = shutil.disk_usage(str(settings.data_dir.resolve()))
            disk_percent = round(100.0 * disk.used / disk.total, 2) if disk.total else 0.0

            cpu_percent = _cpu_percent_best_effort()
            memory_percent = _memory_percent_best_effort()

            return {
                "cpu_percent": float(cpu_percent),
                "memory_percent": float(memory_percent),
                "disk_percent": float(disk_percent),
            }
        except Exception:
            logger.exception("check_system_health failed")
            return {"cpu_percent": 0.0, "memory_percent": 0.0, "disk_percent": 0.0}

    async def record_metric(
        self,
        name: str,
        value: float,
        tags: dict[str, Any] | None = None,
    ) -> None:
        try:
            tags_json = json.dumps(tags) if tags else None
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO system_metrics (metric_name, value, tags_json) VALUES (?, ?, ?)",
                    (name, value, tags_json),
                )
        except Exception:
            logger.exception("record_metric failed name={}", name)

    async def get_recent_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            with get_db() as conn:
                cur = conn.execute(
                    """
                    SELECT id, level, source, message, resolved, created_at
                    FROM alerts
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("get_recent_alerts failed")
            return []

    async def send_notification(
        self,
        level: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        try:
            lv = level.lower()
            if lv in ("critical", "error"):
                logger.error("[alert] {} — {}", level, message)
            elif lv in ("warning", "warn"):
                logger.warning("[alert] {} — {}", level, message)
            else:
                logger.info("[alert] {} — {}", level, message)
            source = "monitor"
            if extra:
                source = str(extra.get("source", source))
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO alerts (level, source, message) VALUES (?, ?, ?)",
                    (level, source, message),
                )
            token = settings.telegram_bot_token.strip()
            chat = settings.telegram_critical_chat.strip()
            if token and chat:
                text = f"[{level}] {message}"
                if extra:
                    text += f"\n{json.dumps(extra, ensure_ascii=False)[:3500]}"
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.post(
                        url,
                        json={"chat_id": chat, "text": text[:4096]},
                    )
                    r.raise_for_status()
        except Exception:
            logger.exception("send_notification failed")


def _cpu_percent_best_effort() -> float:
    try:
        import psutil  # type: ignore

        return float(psutil.cpu_percent(interval=0.1))
    except Exception:
        pass
    try:
        if hasattr(os, "getloadavg"):
            load1, _, _ = os.getloadavg()
            return float(min(100.0, load1 * (100.0 / (os.cpu_count() or 4))))
    except Exception:
        pass
    return 0.0


def _memory_percent_best_effort() -> float:
    try:
        import psutil  # type: ignore

        return float(psutil.virtual_memory().percent)
    except Exception:
        pass
    system = platform.system().lower()
    try:
        if system == "darwin":
            total = int(
                subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            )
            page_size = int(
                subprocess.check_output(["sysctl", "-n", "hw.pagesize"], text=True).strip()
            )
            vm = subprocess.check_output(["vm_stat"], text=True)
            pages_free = pages_active = pages_inactive = pages_spec = pages_wired = 0
            for line in vm.splitlines():
                if "Pages free" in line and ":" in line:
                    pages_free = int(line.split(":")[1].strip().rstrip(".").strip())
                elif "Pages active" in line:
                    pages_active = int(line.split(":")[1].strip().rstrip(".").strip())
                elif "Pages inactive" in line:
                    pages_inactive = int(line.split(":")[1].strip().rstrip(".").strip())
                elif "Pages speculative" in line:
                    pages_spec = int(line.split(":")[1].strip().rstrip(".").strip())
                elif "Pages wired down" in line:
                    parts = line.split(":")[1]
                    pages_wired = int(parts.split()[0].strip().rstrip(".").strip())
            used = (pages_active + pages_wired + pages_spec) * page_size
            if total > 0:
                return round(100.0 * used / total, 2)
        if system == "linux":
            meminfo: dict[str, int] = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = int(parts[1].strip().split()[0]) * 1024
                        meminfo[key] = val
            total = meminfo.get("MemTotal", 0)
            avail = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            if total > 0:
                return round(100.0 * (total - avail) / total, 2)
    except Exception:
        logger.debug("memory percent fallback used")
    return 0.0
