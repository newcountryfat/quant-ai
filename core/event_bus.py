"""Local event bus based on asyncio.Queue — replaces Kafka for single-machine deployment."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from loguru import logger


@dataclass
class Event:
    channel: str
    payload: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class LocalEventBus:
    """Publish / subscribe event bus running entirely in-process."""

    def __init__(self, max_queue_size: int = 10_000):
        self._subscribers: dict[str, list[asyncio.Queue[Event]]] = defaultdict(list)
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._max_queue_size = max_queue_size

    def subscribe(self, channel: str) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers[channel].append(q)
        logger.debug("New queue subscriber on channel={}", channel)
        return q

    def on(self, channel: str, handler: Callable[..., Coroutine]) -> None:
        self._handlers[channel].append(handler)
        logger.debug("Registered handler {} on channel={}", handler.__name__, channel)

    async def publish(self, channel: str, payload: dict[str, Any]) -> int:
        event = Event(channel=channel, payload=payload)
        delivered = 0

        for q in self._subscribers[channel]:
            try:
                q.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                logger.warning("Queue full on channel={}, dropping event", channel)

        for handler in self._handlers[channel]:
            try:
                await handler(event)
                delivered += 1
            except Exception:
                logger.exception("Handler error on channel={}", channel)

        return delivered

    @property
    def channels(self) -> list[str]:
        all_ch = set(self._subscribers.keys()) | set(self._handlers.keys())
        return sorted(all_ch)
