from __future__ import annotations

import re

import pandas as pd
import tushare as ts
from loguru import logger

from core.config import settings
from .base import DataSource


def _normalize_ts_code(symbol: str) -> str:
    """Convert bare 6-digit code to Tushare ts_code format (e.g. 000001.SZ)."""
    s = symbol.strip().upper()
    s = re.sub(r"\.(SS|SH|SZ|BJ)$", "", s, flags=re.IGNORECASE)
    if not s.isdigit():
        return symbol.strip()
    s = s.zfill(6)
    if s.startswith(("6", "9")):
        return f"{s}.SH"
    if s.startswith(("4", "8")):
        return f"{s}.BJ"
    return f"{s}.SZ"


def _bare_code(ts_code: str) -> str:
    return re.sub(r"\.(SH|SZ|BJ)$", "", ts_code.strip(), flags=re.IGNORECASE).zfill(6)


class TushareAdapter(DataSource):
    def __init__(self) -> None:
        token = settings.tushare_api_key.strip()
        if not token:
            raise ValueError("TUSHARE_API_KEY not set")
        ts.set_token(token)
        self._pro = ts.pro_api()

    def fetch_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        ts_code = _normalize_ts_code(symbol)
        start_d = start.replace("-", "")
        end_d = end.replace("-", "")
        try:
            raw = self._pro.daily(ts_code=ts_code, start_date=start_d, end_date=end_d)
        except Exception:
            logger.exception("tushare daily failed ts_code={}", ts_code)
            return pd.DataFrame()

        if raw is None or raw.empty:
            logger.warning("tushare empty daily ts_code={}", ts_code)
            return pd.DataFrame()

        col_map = {
            "trade_date": "trade_date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "vol": "volume",
            "amount": "amount",
            "pct_chg": "pct_chg",
            "change": "change",
        }
        df = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})

        if "trade_date" not in df.columns:
            logger.error("tushare missing trade_date column, cols={}", list(raw.columns))
            return pd.DataFrame()

        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        df["symbol"] = _bare_code(ts_code)

        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce") * 100
        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1000

        turnover_col = next((c for c in raw.columns if c in ("turnover_rate", "turnover_rate_f")), None)
        if turnover_col:
            df["turnover"] = pd.to_numeric(raw[turnover_col], errors="coerce")
        else:
            df["turnover"] = None

        for c in ("open", "high", "low", "close"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        return df.sort_values("trade_date").reset_index(drop=True)

    def fetch_stock_list(self, market: str) -> pd.DataFrame:
        m = market.upper()
        if m not in ("A", "CN", "ASHARE", "", "沪深"):
            logger.debug("TushareAdapter only supports A-share; got {}", market)
            return pd.DataFrame(columns=["symbol", "name", "market", "industry", "list_date"])

        try:
            raw = self._pro.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,symbol,name,area,industry,list_date",
            )
        except Exception:
            logger.exception("tushare stock_basic failed")
            return pd.DataFrame()

        if raw is None or raw.empty:
            return pd.DataFrame()

        out = pd.DataFrame({
            "symbol": raw["symbol"].astype(str).str.zfill(6),
            "name": raw["name"].astype(str),
            "market": "A",
            "industry": raw.get("industry"),
            "list_date": raw.get("list_date"),
        })
        return out.drop_duplicates(subset=["symbol"])

    def health_check(self) -> bool:
        try:
            df = self._pro.daily(ts_code="000001.SZ", start_date="20240101", end_date="20240110")
            return df is not None and not df.empty
        except Exception:
            logger.warning("tushare health_check failed")
            return False
