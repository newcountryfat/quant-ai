from __future__ import annotations

from datetime import timedelta
import json
from typing import Any

import httpx
import pandas as pd


DEFAULT_INDEX_ASSETS: list[dict[str, Any]] = [
    {
        "symbol": "sh000001",
        "name": "上证指数",
        "asset_type": "index",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "broad_market"},
        "tags": [("style", "broad_market"), ("exchange", "sse")],
    },
    {
        "symbol": "sz399001",
        "name": "深证成指",
        "asset_type": "index",
        "market": "CN",
        "exchange": "SZSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "broad_market"},
        "tags": [("style", "broad_market"), ("exchange", "szse")],
    },
    {
        "symbol": "sz399006",
        "name": "创业板指",
        "asset_type": "index",
        "market": "CN",
        "exchange": "SZSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "growth"},
        "tags": [("style", "growth"), ("exchange", "szse")],
    },
    {
        "symbol": "sh000016",
        "name": "上证50",
        "asset_type": "index",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "large_cap"},
        "tags": [("style", "large_cap"), ("exchange", "sse")],
    },
    {
        "symbol": "sh000300",
        "name": "沪深300",
        "asset_type": "index",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "broad_market"},
        "tags": [("style", "broad_market"), ("factor", "core_benchmark")],
    },
    {
        "symbol": "sh000905",
        "name": "中证500",
        "asset_type": "index",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "mid_cap"},
        "tags": [("style", "mid_cap"), ("factor", "timing_core")],
    },
    {
        "symbol": "sh000852",
        "name": "中证1000",
        "asset_type": "index",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "small_cap"},
        "tags": [("style", "small_cap"), ("factor", "timing_core")],
    },
    {
        "symbol": "sh000510",
        "name": "中证A500",
        "asset_type": "index",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "all_market"},
        "tags": [("style", "all_market"), ("factor", "timing_core")],
    },
]


DEFAULT_ETF_ASSETS: list[dict[str, Any]] = [
    {
        "symbol": "sh510050",
        "name": "上证50ETF",
        "asset_type": "etf",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": "sh000016",
        "status": "active",
        "source": "builtin",
        "extra": {"category": "large_cap"},
        "tags": [("theme", "large_cap"), ("exchange", "sse")],
    },
    {
        "symbol": "sh510300",
        "name": "沪深300ETF",
        "asset_type": "etf",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": "sh000300",
        "status": "active",
        "source": "builtin",
        "extra": {"category": "broad_market"},
        "tags": [("theme", "broad_market"), ("factor", "timing_core")],
    },
    {
        "symbol": "sh510500",
        "name": "中证500ETF",
        "asset_type": "etf",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": "sh000905",
        "status": "active",
        "source": "builtin",
        "extra": {"category": "mid_cap"},
        "tags": [("theme", "mid_cap"), ("factor", "timing_core")],
    },
    {
        "symbol": "sh512100",
        "name": "中证1000ETF",
        "asset_type": "etf",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": "sh000852",
        "status": "active",
        "source": "builtin",
        "extra": {"category": "small_cap"},
        "tags": [("theme", "small_cap"), ("factor", "timing_core")],
    },
    {
        "symbol": "sh512050",
        "name": "中证A500ETF",
        "asset_type": "etf",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": "sh000510",
        "status": "active",
        "source": "builtin",
        "extra": {"category": "all_market"},
        "tags": [("theme", "all_market"), ("factor", "timing_core")],
    },
    {
        "symbol": "sz159915",
        "name": "创业板ETF",
        "asset_type": "etf",
        "market": "CN",
        "exchange": "SZSE",
        "benchmark_symbol": "sz399006",
        "status": "active",
        "source": "builtin",
        "extra": {"category": "growth"},
        "tags": [("theme", "growth"), ("exchange", "szse")],
    },
    {
        "symbol": "sh513100",
        "name": "纳指ETF",
        "asset_type": "etf",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "overseas"},
        "tags": [("theme", "overseas"), ("region", "us")],
    },
    {
        "symbol": "sh518880",
        "name": "黄金ETF",
        "asset_type": "etf",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "commodity"},
        "tags": [("theme", "commodity"), ("sector", "gold")],
    },
    {
        "symbol": "sh512010",
        "name": "医药ETF",
        "asset_type": "etf",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "sector"},
        "tags": [("theme", "sector"), ("sector", "healthcare")],
    },
    {
        "symbol": "sh515790",
        "name": "光伏ETF",
        "asset_type": "etf",
        "market": "CN",
        "exchange": "SSE",
        "benchmark_symbol": None,
        "status": "active",
        "source": "builtin",
        "extra": {"category": "sector"},
        "tags": [("theme", "sector"), ("sector", "solar")],
    },
]


DEFAULT_ASSETS: list[dict[str, Any]] = DEFAULT_INDEX_ASSETS + DEFAULT_ETF_ASSETS
DEFAULT_INDEX_CODES: list[tuple[str, str]] = [(item["symbol"], item["name"]) for item in DEFAULT_INDEX_ASSETS]
DEFAULT_ETF_CODES: list[tuple[str, str]] = [(item["symbol"], item["name"]) for item in DEFAULT_ETF_ASSETS]


def is_market_symbol(symbol: str) -> bool:
    return len(symbol) > 6 and symbol[:2] in ("sh", "sz") and symbol[2:].isdigit()


def default_asset_rows() -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for item in DEFAULT_ASSETS:
        rows.append(
            (
                item["symbol"],
                item["name"],
                item["asset_type"],
                item["market"],
                item["exchange"],
                item["benchmark_symbol"],
                item["status"],
                item["source"],
                None,
                json.dumps(item.get("extra", {}), ensure_ascii=False),
            )
        )
    return rows


def default_mapping_rows() -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for item in DEFAULT_ETF_ASSETS:
        target = item.get("benchmark_symbol")
        if not target:
            continue
        rows.append(
            (
                item["symbol"],
                item["asset_type"],
                target,
                "index",
                "tracks",
                f'{item["name"]} 跟踪 {target}',
            )
        )
    return rows


def default_tag_rows() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for item in DEFAULT_ASSETS:
        for tag_type, tag in item.get("tags", []):
            rows.append((item["symbol"], tag, tag_type))
    return rows


def fetch_market_daily(symbol: str, start: str, end: str, limit: int = 1200) -> pd.DataFrame:
    start_s = str(start)
    end_s = str(end)
    start_d = pd.to_datetime(start_s).date()
    end_d = pd.to_datetime(end_s).date()
    cursor_end = end_d
    chunks: list[pd.DataFrame] = []
    seen_first_dates: set[str] = set()

    for _ in range(32):
        url = (
            "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={symbol},day,{start_s},{cursor_end.isoformat()},{limit},qfq"
        )
        response = httpx.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        payload = response.json().get("data", {}).get(symbol, {})
        rows = payload.get("day", payload.get("qfqday", []))
        if not rows:
            break

        normalized: list[dict[str, Any]] = []
        for row in rows:
            if len(row) < 6:
                continue
            normalized.append(
                {
                    "symbol": symbol,
                    "trade_date": str(row[0]),
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]) if row[5] else None,
                    "amount": float(row[6]) if len(row) > 6 and row[6] else None,
                    "turnover": None,
                }
            )
        if not normalized:
            break

        df = pd.DataFrame(normalized)
        chunks.append(df)

        first_trade = str(df["trade_date"].iloc[0])[:10]
        if first_trade in seen_first_dates:
            break
        seen_first_dates.add(first_trade)

        first_date = pd.to_datetime(first_trade).date()
        if first_date <= start_d:
            break

        next_end = first_date - timedelta(days=1)
        if next_end >= cursor_end:
            break
        cursor_end = next_end

    if not chunks:
        return pd.DataFrame()

    out = (
        pd.concat(chunks, ignore_index=True)
        .drop_duplicates(subset=["symbol", "trade_date"])
        .sort_values("trade_date")
        .reset_index(drop=True)
    )
    return out[(out["trade_date"] >= start_s) & (out["trade_date"] <= end_s)].reset_index(drop=True)
