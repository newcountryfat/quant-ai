from __future__ import annotations

import pandas as pd
from loguru import logger


class DataCleaner:
    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        try:
            out = df.copy()
            if "trade_date" in out.columns:
                out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
            num_cols = [c for c in ("open", "high", "low", "close", "volume", "amount", "turnover") if c in out.columns]
            if num_cols:
                out[num_cols] = out[num_cols].apply(pd.to_numeric, errors="coerce")
                out[num_cols] = out[num_cols].ffill()
            out = out.dropna(subset=["trade_date"] if "trade_date" in out.columns else [])
            if "trade_date" in out.columns:
                out = out.sort_values("trade_date")
            if "symbol" in out.columns:
                out = out.drop_duplicates(subset=["symbol", "trade_date"], keep="last")
            else:
                out = out.drop_duplicates(subset=["trade_date"], keep="last")
            if "trade_date" in out.columns:
                out["trade_date"] = out["trade_date"].dt.strftime("%Y-%m-%d")
            return out.reset_index(drop=True)
        except Exception:
            logger.exception("DataCleaner.clean failed")
            return pd.DataFrame()
