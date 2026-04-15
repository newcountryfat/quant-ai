from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class DataSource(ABC):
    @abstractmethod
    def fetch_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Return daily OHLCV-like bars for ``symbol`` between ``start`` and ``end`` (inclusive).

        Expected columns include at least: trade_date, open, high, low, close, volume.
        Dates are ISO strings ``YYYY-MM-DD`` where possible.
        """

    @abstractmethod
    def fetch_stock_list(self, market: str) -> pd.DataFrame:
        """Return listing metadata; columns should align with ``stocks`` table usage."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the upstream data source is reachable."""
