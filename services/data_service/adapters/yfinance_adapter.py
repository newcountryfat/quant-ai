from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Final

import pandas as pd
import yfinance as yf
from loguru import logger

from .base import DataSource

_US_BLUE_CHIPS: Final[tuple[str, ...]] = (
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "TSLA",
    "BRK-B",
    "JPM",
    "V",
    "UNH",
    "JNJ",
    "WMT",
    "PG",
    "MA",
    "HD",
    "DIS",
    "BAC",
    "XOM",
    "CVX",
    "ABBV",
    "PFE",
    "KO",
    "CSCO",
    "PEP",
    "COST",
    "AVGO",
    "MRK",
    "TMO",
    "MCD",
)


def _yahoo_symbol_for_a_share(symbol: str) -> str:
    s = symbol.strip().upper()
    s = re.sub(r"\.(SS|SZ|BJ)$", "", s, flags=re.IGNORECASE)
    if not s.isdigit():
        return symbol.strip().upper()
    s = s.zfill(6)
    if s.startswith(("6", "9")):
        return f"{s}.SS"
    return f"{s}.SZ"


def _is_cn_numeric_code(symbol: str) -> bool:
    s = re.sub(r"\.(SS|SZ|BJ)$", "", symbol.strip(), flags=re.IGNORECASE)
    return bool(re.fullmatch(r"\d{1,6}", s))


class YFinanceAdapter(DataSource):
    def fetch_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        raw = symbol.strip()
        ysym = _yahoo_symbol_for_a_share(raw) if _is_cn_numeric_code(raw) else raw.upper()
        end_exclusive = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            t = yf.Ticker(ysym)
            hist = t.history(start=start, end=end_exclusive, auto_adjust=False, interval="1d")
        except Exception:
            logger.exception("yfinance history failed symbol={} start={} end={}", ysym, start, end)
            return pd.DataFrame()

        if hist is None or hist.empty:
            logger.warning("yfinance empty history symbol={}", ysym)
            return pd.DataFrame()

        df = hist.reset_index()
        date_col = "Date" if "Date" in df.columns else df.columns[0]
        df["trade_date"] = pd.to_datetime(df[date_col], utc=True).dt.tz_localize(None)
        df = df[df["trade_date"] <= pd.Timestamp(end)]
        df["trade_date"] = df["trade_date"].dt.strftime("%Y-%m-%d")
        rename = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
        df = df.rename(columns=rename)
        if "Adj Close" in df.columns:
            df["amount"] = df["close"] * df["volume"]
        else:
            df["amount"] = df.get("close", 0) * df.get("volume", 0)
        df["turnover"] = None
        base = re.sub(r"\.(SS|SZ)$", "", ysym)
        df["symbol"] = base.zfill(6) if base.isdigit() else ysym
        cols = ["symbol", "trade_date", "open", "high", "low", "close", "volume", "amount", "turnover"]
        for c in ("open", "high", "low", "close", "volume", "amount"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df[[c for c in cols if c in df.columns]]

    def fetch_stock_list(self, market: str) -> pd.DataFrame:
        m = market.upper()
        if m not in ("US", "NYSE", "NASDAQ", "AMEX"):
            logger.debug("YFinanceAdapter stock list only implemented for US-style markets; got {}", market)
            return pd.DataFrame(columns=["symbol", "name", "market", "industry", "list_date"])

        rows: list[dict] = []

        def _one(sym: str) -> dict | None:
            try:
                info = yf.Ticker(sym).info or {}
                name = info.get("shortName") or info.get("longName") or sym
                return {"symbol": sym, "name": str(name), "market": "US", "industry": info.get("industry"), "list_date": None}
            except Exception:
                logger.debug("yfinance info failed symbol={}", sym)
                return None

        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_one, sym): sym for sym in _US_BLUE_CHIPS}
            for fut in as_completed(futs):
                r = fut.result()
                if r:
                    rows.append(r)

        if not rows:
            return pd.DataFrame(columns=["symbol", "name", "market", "industry", "list_date"])
        return pd.DataFrame(rows).drop_duplicates(subset=["symbol"])

    def health_check(self) -> bool:
        try:
            h = yf.Ticker("AAPL").history(period="5d", interval="1d")
            return h is not None and not h.empty
        except Exception:
            logger.warning("yfinance health_check failed")
            return False
