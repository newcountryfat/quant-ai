"""Factor evaluation framework — IC, IR, ICIR, stability, and sub-period analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class FactorEvalResult:
    factor_name: str
    ic_mean: float = 0.0
    ic_std: float = 0.0
    icir: float = 0.0
    ic_positive_ratio: float = 0.0
    ic_series: list[float] = field(default_factory=list)
    rank_ic_mean: float = 0.0
    rank_ic_std: float = 0.0
    rank_icir: float = 0.0
    monotonicity: float = 0.0
    sub_period_ics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_name": self.factor_name,
            "ic_mean": round(self.ic_mean, 6),
            "ic_std": round(self.ic_std, 6),
            "icir": round(self.icir, 4),
            "ic_positive_ratio": round(self.ic_positive_ratio, 4),
            "rank_ic_mean": round(self.rank_ic_mean, 6),
            "rank_ic_std": round(self.rank_ic_std, 6),
            "rank_icir": round(self.rank_icir, 4),
            "monotonicity": round(self.monotonicity, 4),
            "sub_period_ics": {k: round(v, 6) for k, v in self.sub_period_ics.items()},
        }


class FactorEvaluator:
    """Evaluate predictive power of factors for timing signals."""

    def __init__(self, forward_periods: list[int] | None = None):
        self._forward_periods = forward_periods or [1, 5, 10, 20]

    def evaluate_single(
        self,
        factor_series: pd.Series,
        forward_return: pd.Series,
        factor_name: str = "",
    ) -> FactorEvalResult:
        aligned = pd.concat([factor_series, forward_return], axis=1).dropna()
        if len(aligned) < 30:
            return FactorEvalResult(factor_name=factor_name)

        f_col, r_col = aligned.columns[0], aligned.columns[1]
        f_vals = aligned[f_col]
        r_vals = aligned[r_col]

        ic_series = self._rolling_ic(f_vals, r_vals, window=20)
        rank_ic_series = self._rolling_rank_ic(f_vals, r_vals, window=20)

        ic_mean = float(np.nanmean(ic_series))
        ic_std = float(np.nanstd(ic_series))
        icir = ic_mean / ic_std if ic_std > 1e-12 else 0.0
        ic_pos = float(np.nanmean(np.array(ic_series) > 0)) if ic_series else 0.0

        ric_mean = float(np.nanmean(rank_ic_series))
        ric_std = float(np.nanstd(rank_ic_series))
        ricir = ric_mean / ric_std if ric_std > 1e-12 else 0.0

        mono = self._monotonicity_score(f_vals, r_vals)

        sub_ics = self._sub_period_ic(f_vals, r_vals)

        return FactorEvalResult(
            factor_name=factor_name,
            ic_mean=ic_mean,
            ic_std=ic_std,
            icir=icir,
            ic_positive_ratio=ic_pos,
            ic_series=ic_series,
            rank_ic_mean=ric_mean,
            rank_ic_std=ric_std,
            rank_icir=ricir,
            monotonicity=mono,
            sub_period_ics=sub_ics,
        )

    def evaluate_batch(
        self,
        factor_df: pd.DataFrame,
        returns_df: pd.DataFrame,
        forward_period: int = 5,
    ) -> list[FactorEvalResult]:
        base_cols = {"open", "high", "low", "close", "volume", "amount", "turnover"}
        factor_cols = [c for c in factor_df.columns if c not in base_cols]

        ret_col = f"fwd_ret_{forward_period}"
        if ret_col not in returns_df.columns:
            returns_df = returns_df.copy()
            returns_df[ret_col] = returns_df["close"].pct_change(periods=forward_period).shift(-forward_period)

        results = []
        for col in factor_cols:
            res = self.evaluate_single(
                factor_df[col],
                returns_df[ret_col],
                factor_name=col,
            )
            results.append(res)
        return results

    # ---------- helpers ----------

    @staticmethod
    def _rolling_ic(f: pd.Series, r: pd.Series, window: int = 20) -> list[float]:
        combined = pd.concat([f.rename("f"), r.rename("r")], axis=1).dropna()
        if len(combined) < window:
            return []
        ics = []
        for i in range(window, len(combined) + 1):
            chunk = combined.iloc[i - window : i]
            corr = chunk["f"].corr(chunk["r"])
            if not np.isnan(corr):
                ics.append(float(corr))
        return ics

    @staticmethod
    def _rolling_rank_ic(f: pd.Series, r: pd.Series, window: int = 20) -> list[float]:
        combined = pd.concat([f.rename("f"), r.rename("r")], axis=1).dropna()
        if len(combined) < window:
            return []
        ics = []
        for i in range(window, len(combined) + 1):
            chunk = combined.iloc[i - window : i]
            corr = chunk["f"].rank().corr(chunk["r"].rank())
            if not np.isnan(corr):
                ics.append(float(corr))
        return ics

    @staticmethod
    def _monotonicity_score(f: pd.Series, r: pd.Series, n_bins: int = 5) -> float:
        combined = pd.concat([f.rename("f"), r.rename("r")], axis=1).dropna()
        if len(combined) < n_bins * 10:
            return 0.0
        try:
            combined["bin"] = pd.qcut(combined["f"], q=n_bins, labels=False, duplicates="drop")
        except ValueError:
            return 0.0
        group_means = combined.groupby("bin")["r"].mean().values
        if len(group_means) < 2:
            return 0.0
        diffs = np.diff(group_means)
        if np.all(diffs > 0):
            return 1.0
        if np.all(diffs < 0):
            return -1.0
        return float(np.mean(np.sign(diffs)))

    @staticmethod
    def _sub_period_ic(f: pd.Series, r: pd.Series, n_splits: int = 4) -> dict[str, float]:
        combined = pd.concat([f.rename("f"), r.rename("r")], axis=1).dropna()
        n = len(combined)
        if n < n_splits * 20:
            return {}
        chunk_size = n // n_splits
        result = {}
        for i in range(n_splits):
            start = i * chunk_size
            end = start + chunk_size if i < n_splits - 1 else n
            chunk = combined.iloc[start:end]
            ic = chunk["f"].corr(chunk["r"])
            result[f"Q{i + 1}"] = float(ic) if not np.isnan(ic) else 0.0
        return result
