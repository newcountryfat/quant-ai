"""Walk-forward (rolling window) validation for factor-based timing signals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class WalkForwardFold:
    fold_idx: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_ic: float = 0.0
    test_ic: float = 0.0
    test_return: float = 0.0
    test_sharpe: float = 0.0
    n_train: int = 0
    n_test: int = 0


@dataclass
class WalkForwardResult:
    factor_name: str
    symbol: str
    n_folds: int = 0
    avg_test_ic: float = 0.0
    avg_test_return: float = 0.0
    avg_test_sharpe: float = 0.0
    ic_consistency: float = 0.0
    folds: list[WalkForwardFold] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_name": self.factor_name,
            "symbol": self.symbol,
            "n_folds": self.n_folds,
            "avg_test_ic": round(self.avg_test_ic, 6),
            "avg_test_return": round(self.avg_test_return, 6),
            "avg_test_sharpe": round(self.avg_test_sharpe, 4),
            "ic_consistency": round(self.ic_consistency, 4),
            "folds": [
                {
                    "fold_idx": f.fold_idx,
                    "train_period": f"{f.train_start}~{f.train_end}",
                    "test_period": f"{f.test_start}~{f.test_end}",
                    "train_ic": round(f.train_ic, 6),
                    "test_ic": round(f.test_ic, 6),
                    "test_return": round(f.test_return, 6),
                    "test_sharpe": round(f.test_sharpe, 4),
                    "n_train": f.n_train,
                    "n_test": f.n_test,
                }
                for f in self.folds
            ],
        }


class WalkForwardValidator:
    """Rolling-window walk-forward validation for single-asset timing factors."""

    def __init__(
        self,
        train_days: int = 120,
        test_days: int = 20,
        step_days: int = 20,
        forward_period: int = 5,
    ):
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days
        self.forward_period = forward_period

    def validate(
        self,
        factor_series: pd.Series,
        price_series: pd.Series,
        factor_name: str = "",
        symbol: str = "",
    ) -> WalkForwardResult:
        aligned = pd.concat(
            [factor_series.rename("factor"), price_series.rename("close")], axis=1
        ).dropna()

        if len(aligned) < self.train_days + self.test_days:
            return WalkForwardResult(factor_name=factor_name, symbol=symbol)

        aligned["fwd_ret"] = aligned["close"].pct_change(periods=self.forward_period).shift(
            -self.forward_period
        )

        n = len(aligned)
        folds: list[WalkForwardFold] = []
        idx = 0
        fold_num = 0

        while idx + self.train_days + self.test_days <= n:
            train_slice = aligned.iloc[idx : idx + self.train_days]
            test_start = idx + self.train_days
            test_end = min(test_start + self.test_days, n)
            test_slice = aligned.iloc[test_start:test_end]

            train_valid = train_slice[["factor", "fwd_ret"]].dropna()
            test_valid = test_slice[["factor", "fwd_ret"]].dropna()

            train_ic = (
                float(train_valid["factor"].corr(train_valid["fwd_ret"]))
                if len(train_valid) >= 10
                else 0.0
            )
            test_ic = (
                float(test_valid["factor"].corr(test_valid["fwd_ret"]))
                if len(test_valid) >= 5
                else 0.0
            )

            if np.isnan(train_ic):
                train_ic = 0.0
            if np.isnan(test_ic):
                test_ic = 0.0

            test_ret, test_sharpe = self._simple_long_short_pnl(test_valid)

            dates = aligned.index
            fold = WalkForwardFold(
                fold_idx=fold_num,
                train_start=str(dates[idx])[:10],
                train_end=str(dates[idx + self.train_days - 1])[:10],
                test_start=str(dates[test_start])[:10],
                test_end=str(dates[test_end - 1])[:10],
                train_ic=train_ic,
                test_ic=test_ic,
                test_return=test_ret,
                test_sharpe=test_sharpe,
                n_train=len(train_valid),
                n_test=len(test_valid),
            )
            folds.append(fold)
            fold_num += 1
            idx += self.step_days

        if not folds:
            return WalkForwardResult(factor_name=factor_name, symbol=symbol)

        test_ics = [f.test_ic for f in folds]
        test_rets = [f.test_return for f in folds]
        test_sharpes = [f.test_sharpe for f in folds]

        ic_arr = np.array(test_ics)
        consistency = float(np.mean(np.sign(ic_arr) == np.sign(np.mean(ic_arr)))) if len(ic_arr) > 0 else 0.0

        return WalkForwardResult(
            factor_name=factor_name,
            symbol=symbol,
            n_folds=len(folds),
            avg_test_ic=float(np.nanmean(test_ics)),
            avg_test_return=float(np.nanmean(test_rets)),
            avg_test_sharpe=float(np.nanmean(test_sharpes)),
            ic_consistency=consistency,
            folds=folds,
        )

    @staticmethod
    def _simple_long_short_pnl(df: pd.DataFrame) -> tuple[float, float]:
        """Use factor sign as position direction to compute simple PnL."""
        if df.empty or "factor" not in df.columns or "fwd_ret" not in df.columns:
            return 0.0, 0.0
        valid = df.dropna(subset=["factor", "fwd_ret"])
        if len(valid) < 2:
            return 0.0, 0.0
        direction = np.sign(valid["factor"].values)
        rets = valid["fwd_ret"].values
        pnl = direction * rets
        total_ret = float(np.nansum(pnl))
        std = float(np.nanstd(pnl))
        sharpe = float(np.nanmean(pnl) / std * np.sqrt(252)) if std > 1e-12 else 0.0
        return total_ret, sharpe
