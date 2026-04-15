from __future__ import annotations

import numpy as np
import pandas as pd


class FactorLibrary:
    """Comprehensive factor library for index / ETF timing research.

    Groups:
      - Trend: MA, EMA, MACD, ADX
      - Momentum: RSI, ROC, CCI, Williams %R, Stochastic %K/%D, MOM
      - Volatility: Bollinger, ATR, Realized Vol
      - Volume: OBV, VWAP, Volume Ratio
      - Price patterns: returns, log-returns, high-low range
    """

    _REQUIRED = ("open", "high", "low", "close", "volume")

    @classmethod
    def _ensure_columns(cls, df: pd.DataFrame) -> None:
        missing = [c for c in cls._REQUIRED if c not in df.columns]
        if missing:
            raise ValueError(f"DataFrame missing columns: {missing}")

    # ---------- Trend ----------

    @classmethod
    def compute_ma(cls, df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
        cls._ensure_columns(df)
        periods = periods or [5, 10, 20, 60]
        out = df.copy()
        for p in periods:
            out[f"ma_{p}"] = out["close"].rolling(window=p, min_periods=p).mean()
        return out

    @classmethod
    def compute_ema(cls, df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
        cls._ensure_columns(df)
        periods = periods or [5, 10, 20, 60]
        out = df.copy()
        for p in periods:
            out[f"ema_{p}"] = out["close"].ewm(span=p, adjust=False).mean()
        return out

    @classmethod
    def compute_macd(
        cls,
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        ema_fast = out["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = out["close"].ewm(span=slow, adjust=False).mean()
        out["macd"] = ema_fast - ema_slow
        out["macd_signal"] = out["macd"].ewm(span=signal, adjust=False).mean()
        out["macd_hist"] = out["macd"] - out["macd_signal"]
        return out

    @classmethod
    def compute_adx(cls, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        h, l, c = out["high"], out["low"], out["close"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        plus_dm = (h - h.shift()).clip(lower=0)
        minus_dm = (l.shift() - l).clip(lower=0)
        plus_dm[plus_dm < minus_dm] = 0
        minus_dm[minus_dm < plus_dm] = 0
        atr_s = tr.ewm(span=period, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / (atr_s + 1e-12))
        minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / (atr_s + 1e-12))
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12))
        out["adx"] = dx.ewm(span=period, adjust=False).mean()
        out["plus_di"] = plus_di
        out["minus_di"] = minus_di
        return out

    # ---------- Momentum ----------

    @classmethod
    def compute_rsi(cls, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        delta = out["close"].diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-12)
        out[f"rsi_{period}"] = 100 - (100 / (1 + rs))
        return out

    @classmethod
    def compute_roc(cls, df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
        cls._ensure_columns(df)
        periods = periods or [5, 10, 20]
        out = df.copy()
        for p in periods:
            out[f"roc_{p}"] = out["close"].pct_change(periods=p) * 100
        return out

    @classmethod
    def compute_cci(cls, df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        tp = (out["high"] + out["low"] + out["close"]) / 3
        sma = tp.rolling(window=period, min_periods=period).mean()
        mad = tp.rolling(window=period, min_periods=period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
        out["cci"] = (tp - sma) / (0.015 * mad + 1e-12)
        return out

    @classmethod
    def compute_williams_r(cls, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        hh = out["high"].rolling(window=period, min_periods=period).max()
        ll = out["low"].rolling(window=period, min_periods=period).min()
        out[f"wr_{period}"] = -100 * (hh - out["close"]) / (hh - ll + 1e-12)
        return out

    @classmethod
    def compute_stochastic(cls, df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        hh = out["high"].rolling(window=k_period, min_periods=k_period).max()
        ll = out["low"].rolling(window=k_period, min_periods=k_period).min()
        out["stoch_k"] = 100 * (out["close"] - ll) / (hh - ll + 1e-12)
        out["stoch_d"] = out["stoch_k"].rolling(window=d_period, min_periods=d_period).mean()
        return out

    @classmethod
    def compute_momentum(cls, df: pd.DataFrame, period: int = 10) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        out[f"mom_{period}"] = out["close"] / out["close"].shift(period) - 1.0
        return out

    # ---------- Volatility ----------

    @classmethod
    def compute_bollinger(cls, df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        mid = out["close"].rolling(window=period, min_periods=period).mean()
        std = out["close"].rolling(window=period, min_periods=period).std()
        out["bb_mid"] = mid
        out["bb_upper"] = mid + num_std * std
        out["bb_lower"] = mid - num_std * std
        out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / (mid + 1e-12)
        return out

    @classmethod
    def compute_atr(cls, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        h, l, c = out["high"], out["low"], out["close"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        out["atr"] = tr.ewm(span=period, adjust=False).mean()
        out["atr_pct"] = out["atr"] / (out["close"] + 1e-12) * 100
        return out

    @classmethod
    def compute_realized_vol(cls, df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
        cls._ensure_columns(df)
        periods = periods or [5, 10, 20]
        out = df.copy()
        log_ret = np.log(out["close"] / out["close"].shift(1))
        for p in periods:
            out[f"rvol_{p}"] = log_ret.rolling(window=p, min_periods=p).std() * np.sqrt(252)
        return out

    # ---------- Volume ----------

    @classmethod
    def compute_obv(cls, df: pd.DataFrame) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        direction = np.sign(out["close"].diff()).fillna(0)
        out["obv"] = (out["volume"] * direction).cumsum()
        return out

    @classmethod
    def compute_vwap(cls, df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        tp = (out["high"] + out["low"] + out["close"]) / 3
        tpv = tp * out["volume"]
        out["vwap"] = tpv.rolling(window=period, min_periods=period).sum() / (
            out["volume"].rolling(window=period, min_periods=period).sum() + 1e-12
        )
        return out

    @classmethod
    def compute_volume_ratio(cls, df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        avg_vol = out["volume"].rolling(window=period, min_periods=period).mean()
        out["vol_ratio"] = out["volume"] / (avg_vol + 1e-12)
        return out

    # ---------- Price patterns ----------

    @classmethod
    def compute_returns(cls, df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
        cls._ensure_columns(df)
        periods = periods or [1, 5, 10, 20]
        out = df.copy()
        for p in periods:
            out[f"ret_{p}"] = out["close"].pct_change(periods=p)
        out["log_ret"] = np.log(out["close"] / out["close"].shift(1))
        return out

    @classmethod
    def compute_hl_range(cls, df: pd.DataFrame) -> pd.DataFrame:
        cls._ensure_columns(df)
        out = df.copy()
        out["hl_range"] = (out["high"] - out["low"]) / (out["close"] + 1e-12)
        out["co_range"] = (out["close"] - out["open"]) / (out["open"] + 1e-12)
        return out

    # ---------- Aggregate ----------

    @classmethod
    def compute_all(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Compute the full factor set (30+ factors)."""
        out = cls.compute_ma(df)
        out = cls.compute_ema(out)
        out = cls.compute_macd(out)
        out = cls.compute_adx(out)
        out = cls.compute_rsi(out)
        out = cls.compute_roc(out)
        out = cls.compute_cci(out)
        out = cls.compute_williams_r(out)
        out = cls.compute_stochastic(out)
        out = cls.compute_momentum(out)
        out = cls.compute_bollinger(out)
        out = cls.compute_atr(out)
        out = cls.compute_realized_vol(out)
        out = cls.compute_obv(out)
        out = cls.compute_vwap(out)
        out = cls.compute_volume_ratio(out)
        out = cls.compute_returns(out)
        out = cls.compute_hl_range(out)
        return out

    @classmethod
    def list_factor_names(cls, df: pd.DataFrame | None = None) -> list[str]:
        """Return the list of factor column names produced by compute_all."""
        base_cols = {"open", "high", "low", "close", "volume", "amount", "turnover"}
        if df is not None:
            return [c for c in df.columns if c not in base_cols]
        return [
            "ma_5", "ma_10", "ma_20", "ma_60",
            "ema_5", "ema_10", "ema_20", "ema_60",
            "macd", "macd_signal", "macd_hist",
            "adx", "plus_di", "minus_di",
            "rsi_14",
            "roc_5", "roc_10", "roc_20",
            "cci",
            "wr_14",
            "stoch_k", "stoch_d",
            "mom_10",
            "bb_mid", "bb_upper", "bb_lower", "bb_width",
            "atr", "atr_pct",
            "rvol_5", "rvol_10", "rvol_20",
            "obv",
            "vwap",
            "vol_ratio",
            "ret_1", "ret_5", "ret_10", "ret_20", "log_ret",
            "hl_range", "co_range",
        ]
