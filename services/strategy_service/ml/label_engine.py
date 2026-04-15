"""Label engineering for timing signal targets."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class LabelEngine:
    """Generate forward-looking labels for supervised ML timing models."""

    @staticmethod
    def add_forward_returns(df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
        periods = periods or [5, 10, 20]
        out = df.copy()
        for p in periods:
            out[f"fwd_ret_{p}"] = out["close"].pct_change(periods=p).shift(-p)
        return out

    @staticmethod
    def add_direction_labels(
        df: pd.DataFrame,
        periods: list[int] | None = None,
        threshold: float = 0.0,
    ) -> pd.DataFrame:
        """Binary direction labels: 1 = up, 0 = down/flat.

        Rows where fwd_ret is NaN (last *p* trading days) are kept as NaN
        so they are never mistaken for valid "down" signals.
        """
        periods = periods or [5, 10, 20]
        out = df.copy()
        for p in periods:
            col = f"fwd_ret_{p}"
            if col not in out.columns:
                out[col] = out["close"].pct_change(periods=p).shift(-p)
            direction = pd.Series(np.nan, index=out.index)
            mask = out[col].notna()
            direction[mask] = (out.loc[mask, col] > threshold).astype(int)
            out[f"label_dir_{p}"] = direction
        return out

    @staticmethod
    def add_bucket_labels(
        df: pd.DataFrame,
        period: int = 5,
        n_buckets: int = 3,
    ) -> pd.DataFrame:
        """Quantile-bucket labels for the forward return."""
        out = df.copy()
        col = f"fwd_ret_{period}"
        if col not in out.columns:
            out[col] = out["close"].pct_change(periods=period).shift(-period)
        valid = out[col].dropna()
        if len(valid) < n_buckets * 10:
            out[f"label_bucket_{period}"] = np.nan
            return out
        try:
            out[f"label_bucket_{period}"] = pd.qcut(
                out[col], q=n_buckets, labels=False, duplicates="drop",
            )
        except ValueError:
            out[f"label_bucket_{period}"] = np.nan
        return out

    @staticmethod
    def add_volatility_regime(
        df: pd.DataFrame,
        window: int = 20,
        n_regimes: int = 3,
    ) -> pd.DataFrame:
        """Label volatility regime from realized vol quintiles."""
        out = df.copy()
        log_ret = np.log(out["close"] / out["close"].shift(1))
        rvol = log_ret.rolling(window=window).std() * np.sqrt(252)
        try:
            out["label_vol_regime"] = pd.qcut(rvol, q=n_regimes, labels=False, duplicates="drop")
        except ValueError:
            out["label_vol_regime"] = np.nan
        return out

    @classmethod
    def generate_all_labels(
        cls,
        df: pd.DataFrame,
        forward_periods: list[int] | None = None,
        direction_threshold: float = 0.0,
        bucket_period: int = 5,
        n_buckets: int = 3,
    ) -> pd.DataFrame:
        forward_periods = forward_periods or [5, 10, 20]
        out = cls.add_forward_returns(df, forward_periods)
        out = cls.add_direction_labels(out, forward_periods, direction_threshold)
        out = cls.add_bucket_labels(out, bucket_period, n_buckets)
        out = cls.add_volatility_regime(out)
        return out

    @staticmethod
    def label_columns(df: pd.DataFrame) -> list[str]:
        return [c for c in df.columns if c.startswith("label_") or c.startswith("fwd_ret_")]
