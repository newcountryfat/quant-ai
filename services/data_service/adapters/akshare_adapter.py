from __future__ import annotations

import re

import akshare as ak
import pandas as pd
from loguru import logger

from .base import DataSource


def _normalize_a_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    s = re.sub(r"\.(SS|SZ|BJ)$", "", s, flags=re.IGNORECASE)
    return s.zfill(6) if s.isdigit() else s


class AKShareAdapter(DataSource):
    def fetch_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        code = _normalize_a_symbol(symbol)
        start_d = start.replace("-", "")
        end_d = end.replace("-", "")
        try:
            raw = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_d,
                end_date=end_d,
                adjust="",
            )
        except Exception:
            logger.exception("akshare stock_zh_a_hist failed symbol={} start={} end={}", code, start, end)
            return pd.DataFrame()

        if raw is None or raw.empty:
            logger.warning("akshare returned empty daily data symbol={}", code)
            return pd.DataFrame()

        col_map = {
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "换手率": "turnover",
        }
        df = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})
        if "trade_date" not in df.columns:
            logger.error("akshare hist missing date column columns={}", list(raw.columns))
            return pd.DataFrame()

        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        df["symbol"] = code
        for c in ("open", "high", "low", "close", "volume", "amount", "turnover"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    def fetch_stock_list(self, market: str) -> pd.DataFrame:
        m = market.upper()
        if m not in ("A", "CN", "ASHARE", "沪深", ""):
            logger.debug("AKShareAdapter only supports A-share market; got {}", market)
            return pd.DataFrame(columns=["symbol", "name", "market", "industry", "list_date"])

        try:
            raw = ak.stock_zh_a_spot_em()
        except Exception:
            logger.exception("akshare stock_zh_a_spot_em failed")
            return pd.DataFrame()

        if raw is None or raw.empty:
            return pd.DataFrame()

        code_col = next((c for c in raw.columns if "代码" in str(c)), None)
        name_col = next((c for c in raw.columns if "名称" in str(c)), None)
        if not code_col or not name_col:
            logger.error("unexpected spot_em columns {}", list(raw.columns))
            return pd.DataFrame()

        out = pd.DataFrame(
            {
                "symbol": raw[code_col].astype(str).str.replace(r"\..*", "", regex=True).str.zfill(6),
                "name": raw[name_col].astype(str),
                "market": "A",
                "industry": None,
                "list_date": None,
            }
        )
        return out.drop_duplicates(subset=["symbol"])

    def health_check(self) -> bool:
        try:
            df = ak.stock_zh_a_hist(symbol="000001", period="daily", start_date="20240101", end_date="20240110", adjust="")
            return df is not None and not df.empty
        except Exception:
            logger.warning("akshare health_check failed")
            return False
