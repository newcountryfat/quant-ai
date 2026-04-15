"""
中证 A500 成分股日线同步 + 自动加入自选。

依赖 Tushare `index_weight`（指数成分与权重，需足够积分）或 `index_member` 回退。
拉取按配置的间隔限速，避免触发接口频率限制。
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pandas as pd
import tushare as ts
from loguru import logger

from core.config import settings

if TYPE_CHECKING:
    from services.data_service.main import DataService


def _bare_from_ts(ts_code: str) -> str:
    s = str(ts_code).strip().upper()
    if "." in s:
        return s.split(".")[0].zfill(6)
    return s.zfill(6)


def _get_pro():
    if not settings.tushare_api_key.strip():
        raise ValueError("TUSHARE_API_KEY 未配置")
    ts.set_token(settings.tushare_api_key.strip())
    return ts.pro_api()


def _fetch_a500_via_index_weight(pro) -> pd.DataFrame | None:
    """使用 index_weight 取最新一期的全部成分。"""
    end = date.today()
    start = end - timedelta(days=120)
    start_s, end_s = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    try:
        df = pro.index_weight(
            index_code=settings.tushare_a500_index_code,
            start_date=start_s,
            end_date=end_s,
        )
    except Exception as e:
        logger.warning("tushare index_weight A500 failed: {}", e)
        return None
    if df is None or df.empty:
        return None
    if "con_code" not in df.columns:
        logger.warning("index_weight missing con_code, cols={}", list(df.columns))
        return None
    df = df.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    latest = df["trade_date"].max()
    df = df[df["trade_date"] == latest]
    logger.info("A500 index_weight latest trade_date={} rows={}", latest, len(df))
    return df


def _fetch_a500_via_index_member(pro) -> pd.DataFrame | None:
    """回退：index_member（部分环境可用）。"""
    try:
        df = pro.index_member(index_code=settings.tushare_a500_index_code, is_new="Y")
    except Exception as e:
        logger.warning("tushare index_member A500 failed: {}", e)
        return None
    if df is None or df.empty:
        return None
    if "con_code" in df.columns:
        return df
    if "ts_code" in df.columns:
        return df.rename(columns={"ts_code": "con_code"})
    logger.warning("index_member unexpected columns: {}", list(df.columns))
    return None


def fetch_a500_constituent_codes() -> list[str]:
    """返回 A500 成分 6 位代码列表（去重、有序）。"""
    pro = _get_pro()
    df = _fetch_a500_via_index_weight(pro)
    if df is None or df.empty:
        df = _fetch_a500_via_index_member(pro)
    if df is None or df.empty:
        logger.error(
            "无法获取中证A500成分，请检查 Tushare 积分与接口权限（index_weight 通常需较高积分）"
        )
        return []
    codes = [_bare_from_ts(x) for x in df["con_code"].unique()]
    codes = sorted(set(codes))
    logger.info("A500 constituent count={}", len(codes))
    return codes


async def add_symbols_to_watchlist(symbols: list[str], note: str) -> int:
    """将代码加入自选（已存在则跳过）。返回本次新增条数。"""
    from core.db import get_db

    if not symbols:
        return 0
    with get_db() as conn:
        before = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        conn.executemany(
            """
            INSERT OR IGNORE INTO watchlist (symbol, note, added_at)
            VALUES (?, ?, datetime('now'))
            """,
            [(s, note) for s in symbols],
        )
        after = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    return max(0, after - before)


async def sync_a500_daily_with_watchlist(
    data_svc: DataService,
    *,
    add_watchlist: bool = False,
    refresh_stock_list: bool = True,
) -> dict[str, object]:
    """
    拉取 A500 成分日线（增量区间），并按限速请求；可选加入自选。
    """
    symbols = await asyncio.to_thread(fetch_a500_constituent_codes)
    if not symbols:
        return {
            "ok": False,
            "error": "no_constituents",
            "symbols": 0,
            "daily_updated": 0,
            "watchlist_new": 0,
            "hint": "检查 Tushare 积分；index_weight 通常需 2000+ 积分",
        }

    if refresh_stock_list:
        await data_svc.update_stock_list("A")

    end_d = date.today().isoformat()
    start_d = (date.today() - timedelta(days=settings.a500_lookback_days)).isoformat()

    interval = max(0.05, float(settings.tushare_min_interval_sec))
    updated = 0

    for i, sym in enumerate(symbols):
        await data_svc.update_daily_data(sym, start_d, end_d)
        updated += 1
        if i + 1 < len(symbols):
            await asyncio.sleep(interval)

        if (i + 1) % 50 == 0:
            logger.info("A500 sync progress {}/{}", i + 1, len(symbols))

    watch_new = 0
    if add_watchlist and symbols:
        watch_new = await add_symbols_to_watchlist(symbols, settings.a500_watchlist_note)

    return {
        "ok": True,
        "symbols": len(symbols),
        "daily_updated": updated,
        "date_range": {"start": start_d, "end": end_d},
        "watchlist_new": watch_new,
        "interval_sec": interval,
    }
