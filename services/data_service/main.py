from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from typing import Sequence

import pandas as pd
from loguru import logger

from core.config import settings
from core.db import get_db, init_schema
from core.event_bus import LocalEventBus
from core.job_logger import record_job_log
from .adapters.base import DataSource
from .market_breadth import rebuild_market_breadth
from .pipeline.cleaner import DataCleaner
from .pipeline.validator import DataValidator
from .research_universe import (
    default_asset_rows,
    default_mapping_rows,
    default_tag_rows,
    fetch_market_daily,
    is_market_symbol,
)


def _build_sources() -> list[DataSource]:
    """Build data source chain: Tushare (preferred) > AKShare (fallback)."""
    sources: list[DataSource] = []
    if settings.tushare_api_key.strip():
        try:
            from .adapters.tushare_adapter import TushareAdapter
            sources.append(TushareAdapter())
        except Exception:
            logger.warning("TushareAdapter init failed, skipping")
    if settings.akshare_enabled:
        try:
            from .adapters.akshare_adapter import AKShareAdapter
            sources.append(AKShareAdapter())
        except Exception:
            logger.warning("AKShareAdapter init failed, skipping")
    if not sources:
        logger.error("No A-share data source available! Check TUSHARE_API_KEY or AKSHARE_ENABLED.")
    return sources


class DataService:
    def __init__(self, event_bus: LocalEventBus) -> None:
        self._bus = event_bus
        self._validator = DataValidator()
        self._cleaner = DataCleaner()
        self._sources: list[DataSource] = _build_sources()

    async def start(self) -> None:
        try:
            settings.ensure_dirs()
            init_schema()
            for i, src in enumerate(self._sources):
                ok = await asyncio.to_thread(src.health_check)
                logger.info("data source [{}] health={}", type(src).__name__, ok)
        except Exception:
            logger.exception("DataService.start failed")

    async def update_stock_list(self, market: str) -> None:
        try:
            df = await self._fetch_stock_list_chain(market)
            if df is None or df.empty:
                logger.warning("no stock list data for market={}", market)
                return
            rows = self._stock_rows(df, market)
            with get_db() as conn:
                conn.executemany(
                    """
                    INSERT INTO stocks (symbol, name, market, industry, list_date, updated_at)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(symbol) DO UPDATE SET
                        name = excluded.name,
                        market = excluded.market,
                        industry = excluded.industry,
                        list_date = excluded.list_date,
                        updated_at = datetime('now')
                    """,
                    rows,
                )
            await self._bus.publish(
                "market.data.update",
                {"kind": "stock_list", "market": market, "rows": len(rows)},
            )
            sector_result = await self.rebuild_sector_universe(market=market)
            record_job_log(
                "stock_list_update",
                "success",
                f"Updated stock list for market={market}",
                {"market": market, "rows": len(rows), "sector_result": sector_result},
            )
            logger.info("updated stock list market={} rows={}", market, len(rows))
        except Exception:
            record_job_log(
                "stock_list_update",
                "failed",
                f"Failed to update stock list for market={market}",
                {"market": market},
            )
            logger.exception("update_stock_list failed market={}", market)

    async def update_daily_data(self, symbol: str, start: str, end: str) -> None:
        try:
            if is_market_symbol(symbol):
                raw = await asyncio.to_thread(fetch_market_daily, symbol, start, end)
            else:
                raw = await self._fetch_daily_chain(symbol, start, end)
            if raw is None or raw.empty:
                logger.warning("no daily data symbol={} start={} end={}", symbol, start, end)
                return
            report = self._validator.validate(raw)
            if report.issues:
                logger.info("validation symbol={} score={} issues={}", symbol, report.quality_score, report.issues)
            cleaned = self._cleaner.clean(raw)
            if cleaned.empty:
                logger.warning("cleaned empty symbol={}", symbol)
                return
            qrows = self._quote_rows(cleaned)
            self._upsert_daily_quotes(qrows)
            await self._bus.publish(
                "market.data.update",
                {
                    "kind": "daily_quotes",
                    "symbol": symbol,
                    "start": start,
                    "end": end,
                    "rows": len(qrows),
                    "quality_score": report.quality_score,
                },
            )
            record_job_log(
                "daily_update",
                "success",
                f"Updated daily quotes for {symbol}",
                {
                    "symbol": symbol,
                    "start": start,
                    "end": end,
                    "rows": len(qrows),
                    "quality_score": report.quality_score,
                },
            )
            logger.info("updated daily quotes symbol={} rows={}", symbol, len(qrows))
        except Exception:
            record_job_log(
                "daily_update",
                "failed",
                f"Failed to update daily quotes for {symbol}",
                {"symbol": symbol, "start": start, "end": end},
            )
            logger.exception("update_daily_data failed symbol={}", symbol)

    async def _fetch_daily_chain(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        for src in self._sources:
            try:
                df = await asyncio.to_thread(src.fetch_daily, symbol, start, end)
                if df is not None and not df.empty:
                    return df
            except Exception:
                logger.exception("fetch_daily failed via {}", type(src).__name__)
        return pd.DataFrame()

    async def _fetch_stock_list_chain(self, market: str) -> pd.DataFrame:
        for src in self._sources:
            try:
                df = await asyncio.to_thread(src.fetch_stock_list, market)
                if df is not None and not df.empty:
                    return df
            except Exception:
                logger.exception("fetch_stock_list failed via {}", type(src).__name__)
        return pd.DataFrame()

    async def sync_a500(
        self,
        *,
        add_watchlist: bool = False,
        refresh_stock_list: bool = True,
    ) -> dict[str, object]:
        """拉取中证 A500 成分日线（限速）并可选加入自选。"""
        from .a500_sync import sync_a500_daily_with_watchlist

        return await sync_a500_daily_with_watchlist(
            self,
            add_watchlist=add_watchlist,
            refresh_stock_list=refresh_stock_list,
        )

    async def bootstrap_research_universe(self) -> dict[str, object]:
        asset_rows = default_asset_rows()
        mapping_rows = default_mapping_rows()
        tag_rows = default_tag_rows()
        with get_db() as conn:
            conn.executemany(
                """
                INSERT INTO asset_universe (
                    symbol, name, asset_type, market, exchange,
                    benchmark_symbol, status, source, list_date, extra_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(symbol) DO UPDATE SET
                    name = excluded.name,
                    asset_type = excluded.asset_type,
                    market = excluded.market,
                    exchange = excluded.exchange,
                    benchmark_symbol = excluded.benchmark_symbol,
                    status = excluded.status,
                    source = excluded.source,
                    list_date = excluded.list_date,
                    extra_json = excluded.extra_json,
                    updated_at = datetime('now')
                """,
                asset_rows,
            )
            conn.executemany(
                """
                INSERT INTO asset_mapping (
                    source_symbol, source_type, target_symbol,
                    target_type, relation_type, note, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(source_symbol, target_symbol, relation_type) DO UPDATE SET
                    source_type = excluded.source_type,
                    target_type = excluded.target_type,
                    note = excluded.note,
                    updated_at = datetime('now')
                """,
                mapping_rows,
            )
            conn.executemany(
                """
                INSERT INTO asset_tags (symbol, tag, tag_type, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(symbol, tag, tag_type) DO UPDATE SET
                    updated_at = datetime('now')
                """,
                tag_rows,
            )
        await self._bus.publish(
            "market.data.update",
            {
                "kind": "research_universe",
                "assets": len(asset_rows),
                "mappings": len(mapping_rows),
                "tags": len(tag_rows),
            },
        )
        record_job_log(
            "research_universe_bootstrap",
            "success",
            "Bootstrapped built-in research universe",
            {"assets": len(asset_rows), "mappings": len(mapping_rows), "tags": len(tag_rows)},
        )
        logger.info(
            "bootstrapped research universe assets={} mappings={} tags={}",
            len(asset_rows),
            len(mapping_rows),
            len(tag_rows),
        )
        return {
            "status": "ok",
            "assets": len(asset_rows),
            "mappings": len(mapping_rows),
            "tags": len(tag_rows),
        }

    async def rebuild_sector_universe(self, market: str = "A") -> dict[str, object]:
        with get_db() as conn:
            sector_rows = conn.execute(
                """
                SELECT industry, COUNT(*) AS stock_count
                FROM stocks
                WHERE market = ?
                  AND industry IS NOT NULL
                  AND TRIM(industry) <> ''
                GROUP BY industry
                ORDER BY stock_count DESC, industry ASC
                """,
                (market,),
            ).fetchall()
            constituent_rows = conn.execute(
                """
                SELECT symbol, industry
                FROM stocks
                WHERE market = ?
                  AND industry IS NOT NULL
                  AND TRIM(industry) <> ''
                ORDER BY industry, symbol
                """,
                (market,),
            ).fetchall()

        sector_assets = []
        sector_tags = []
        for row in sector_rows:
            industry = str(row["industry"]).strip()
            sector_symbol = f"sector:{industry}"
            sector_assets.append(
                (
                    sector_symbol,
                    f"{industry}板块",
                    "sector",
                    "CN",
                    None,
                    None,
                    "active",
                    "derived_stocks",
                    None,
                    json.dumps({"industry": industry, "stock_count": int(row["stock_count"])}, ensure_ascii=False),
                )
            )
            sector_tags.append((sector_symbol, industry, "sector_name"))
            sector_tags.append((sector_symbol, "derived_stocks", "source"))

        sector_mappings = []
        for row in constituent_rows:
            industry = str(row["industry"]).strip()
            sector_symbol = f"sector:{industry}"
            sector_mappings.append(
                (
                    str(row["symbol"]),
                    "stock",
                    sector_symbol,
                    "sector",
                    "belongs_to_sector",
                    industry,
                )
            )

        with get_db() as conn:
            conn.execute(
                "DELETE FROM asset_mapping WHERE relation_type = 'belongs_to_sector' AND target_type = 'sector'"
            )
            conn.execute("DELETE FROM asset_tags WHERE symbol LIKE 'sector:%'")
            conn.execute("DELETE FROM asset_universe WHERE asset_type = 'sector' AND source = 'derived_stocks'")
            if sector_assets:
                conn.executemany(
                    """
                    INSERT INTO asset_universe (
                        symbol, name, asset_type, market, exchange,
                        benchmark_symbol, status, source, list_date, extra_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    sector_assets,
                )
            if sector_tags:
                conn.executemany(
                    """
                    INSERT INTO asset_tags (symbol, tag, tag_type, updated_at)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    sector_tags,
                )
            if sector_mappings:
                conn.executemany(
                    """
                    INSERT INTO asset_mapping (
                        source_symbol, source_type, target_symbol,
                        target_type, relation_type, note, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    sector_mappings,
                )

        result = {
            "status": "ok",
            "market": market,
            "sectors": len(sector_assets),
            "constituents": len(sector_mappings),
        }
        record_job_log(
            "sector_universe_rebuild",
            "success",
            f"Rebuilt sector universe for market={market}",
            result,
        )
        logger.info(
            "rebuilt sector universe market={} sectors={} constituents={}",
            market,
            len(sector_assets),
            len(sector_mappings),
        )
        return result

    async def sync_research_universe(
        self,
        *,
        asset_type: str | None,
        start: str,
        end: str,
        only_active: bool = True,
        limit: int | None = None,
    ) -> dict[str, object]:
        filters = []
        params: list[object] = []
        if asset_type:
            filters.append("asset_type = ?")
            params.append(asset_type)
        if only_active:
            filters.append("status = 'active'")
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        limit_clause = " LIMIT ?" if limit else ""
        if limit:
            params.append(limit)
        with get_db() as conn:
            rows = conn.execute(
                (
                    "SELECT symbol, asset_type FROM asset_universe "
                    f"{where_clause} ORDER BY asset_type, symbol{limit_clause}"
                ),
                params,
            ).fetchall()

        synced: list[dict[str, object]] = []
        for row in rows:
            symbol = row["symbol"]
            await self.update_daily_data(symbol, start, end)
            with get_db() as conn:
                stat = conn.execute(
                    "SELECT COUNT(*) AS cnt, MAX(trade_date) AS max_date FROM daily_quotes WHERE symbol = ?",
                    (symbol,),
                ).fetchone()
            synced.append(
                {
                    "symbol": symbol,
                    "asset_type": row["asset_type"],
                    "count": stat["cnt"],
                    "max_date": stat["max_date"],
                }
            )

        record_job_log(
            "research_universe_sync",
            "success",
            f"Synchronized research universe asset_type={asset_type or 'all'}",
            {"asset_type": asset_type or "all", "count": len(synced), "start": start, "end": end},
        )
        logger.info(
            "synchronized research universe asset_type={} count={} start={} end={}",
            asset_type or "all",
            len(synced),
            start,
            end,
        )
        return {
            "status": "ok",
            "asset_type": asset_type or "all",
            "synced": synced,
            "count": len(synced),
            "start": start,
            "end": end,
        }

    async def rebuild_market_breadth(self, start: str, end: str) -> dict[str, object]:
        result = await asyncio.to_thread(rebuild_market_breadth, start, end)
        await self._bus.publish(
            "market.data.update",
            {
                "kind": "market_breadth",
                "start": start,
                "end": end,
                "days_processed": result.get("days_processed", 0),
            },
        )
        record_job_log(
            "market_breadth_rebuild",
            "success",
            "Rebuilt market breadth features",
            result,
        )
        logger.info(
            "rebuilt market breadth start={} end={} days_processed={}",
            start,
            end,
            result.get("days_processed", 0),
        )
        return result

    async def sync_research_universe_incremental(
        self,
        *,
        asset_type: str | None,
        only_active: bool = True,
        limit: int | None = None,
        default_lookback_days: int = 400,
        overlap_days: int = 5,
    ) -> dict[str, object]:
        today = date.today().isoformat()
        filters = []
        params: list[object] = []
        if asset_type:
            filters.append("asset_type = ?")
            params.append(asset_type)
        if only_active:
            filters.append("status = 'active'")
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        limit_clause = " LIMIT ?" if limit else ""
        if limit:
            params.append(limit)

        with get_db() as conn:
            assets = conn.execute(
                (
                    "SELECT symbol, asset_type FROM asset_universe "
                    f"{where_clause} ORDER BY asset_type, symbol{limit_clause}"
                ),
                params,
            ).fetchall()

        synced: list[dict[str, object]] = []
        default_start = (date.today() - timedelta(days=default_lookback_days)).isoformat()
        for asset in assets:
            symbol = asset["symbol"]
            with get_db() as conn:
                row = conn.execute(
                    "SELECT MAX(trade_date) AS max_date FROM daily_quotes WHERE symbol = ?",
                    (symbol,),
                ).fetchone()
            start = default_start
            if row and row["max_date"]:
                max_date = datetime.strptime(row["max_date"], "%Y-%m-%d").date()
                start = (max_date - timedelta(days=overlap_days)).isoformat()
            await self.update_daily_data(symbol, start, today)
            with get_db() as conn:
                stat = conn.execute(
                    "SELECT COUNT(*) AS cnt, MAX(trade_date) AS max_date FROM daily_quotes WHERE symbol = ?",
                    (symbol,),
                ).fetchone()
            synced.append(
                {
                    "symbol": symbol,
                    "asset_type": asset["asset_type"],
                    "start": start,
                    "end": today,
                    "count": stat["cnt"],
                    "max_date": stat["max_date"],
                }
            )

        record_job_log(
            "research_universe_incremental_sync",
            "success",
            f"Incrementally synchronized research universe asset_type={asset_type or 'all'}",
            {"asset_type": asset_type or "all", "count": len(synced)},
        )
        logger.info(
            "incrementally synchronized research universe asset_type={} count={}",
            asset_type or "all",
            len(synced),
        )
        return {
            "status": "ok",
            "asset_type": asset_type or "all",
            "count": len(synced),
            "synced": synced,
            "mode": "incremental",
        }

    async def rebuild_market_breadth_recent(self, lookback_days: int = 120) -> dict[str, object]:
        start = (date.today() - timedelta(days=lookback_days)).isoformat()
        end = date.today().isoformat()
        return await self.rebuild_market_breadth(start, end)

    def _stock_rows(self, df: pd.DataFrame, market: str) -> Sequence[tuple]:
        rows: list[tuple] = []
        for _, r in df.iterrows():
            sym = str(r.get("symbol", "")).strip()
            if not sym:
                continue
            name = str(r.get("name", sym))
            mkt = str(r.get("market", market) or market)
            industry = r.get("industry")
            industry_s = None if industry is None or (isinstance(industry, float) and pd.isna(industry)) else str(industry)
            ld = r.get("list_date")
            ld_s = None if ld is None or (isinstance(ld, float) and pd.isna(ld)) else str(ld)
            rows.append((sym, name, mkt, industry_s, ld_s))
        return rows

    def _quote_rows(self, df: pd.DataFrame) -> Sequence[tuple]:
        return [
            (
                str(r["symbol"]),
                str(r["trade_date"]),
                float(r["open"]) if pd.notna(r.get("open")) else None,
                float(r["high"]) if pd.notna(r.get("high")) else None,
                float(r["low"]) if pd.notna(r.get("low")) else None,
                float(r["close"]) if pd.notna(r.get("close")) else None,
                float(r["volume"]) if pd.notna(r.get("volume")) else None,
                float(r["amount"]) if pd.notna(r.get("amount")) else None,
                float(r["turnover"]) if pd.notna(r.get("turnover")) else None,
            )
            for _, r in df.iterrows()
        ]

    def _upsert_daily_quotes(self, qrows: Sequence[tuple]) -> None:
        with get_db() as conn:
            conn.executemany(
                """
                INSERT INTO daily_quotes (symbol, trade_date, open, high, low, close, volume, amount, turnover)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, trade_date) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    amount = excluded.amount,
                    turnover = excluded.turnover
                """,
                qrows,
            )
