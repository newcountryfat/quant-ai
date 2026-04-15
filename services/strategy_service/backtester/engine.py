from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Trade:
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    pnl_pct: float
    holding_days: int
    side: str  # "buy" / "sell"

@dataclass
class BacktestResult:
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    trade_count: int
    equity_curve: pd.Series
    trades: list[Trade] | None = None


class VectorizedBacktester:
    @staticmethod
    def _positions_from_signals(signals: np.ndarray) -> np.ndarray:
        raw = np.full(len(signals), np.nan, dtype=float)
        raw[signals == 1] = 1.0
        raw[signals == -1] = 0.0
        return pd.Series(raw).ffill().fillna(0.0).to_numpy(dtype=float)

    @classmethod
    def run(
        cls,
        prices: pd.DataFrame,
        signals: pd.Series,
        initial_capital: float = 1_000_000,
        commission: float = 0.001,
        trading_days_per_year: int = 252,
    ) -> BacktestResult:
        if "close" not in prices.columns:
            raise ValueError("prices must contain 'close' column")
        price = prices["close"].astype(float).to_numpy()
        sig = signals.reindex(prices.index).fillna(0).astype(int).to_numpy()
        n = len(price)
        if n == 0:
            eq = pd.Series(dtype=float)
            return BacktestResult(0.0, 0.0, 0.0, 0.0, 0.0, 0, eq)

        w = cls._positions_from_signals(sig)
        mret = np.zeros(n, dtype=float)
        mret[1:] = price[1:] / price[:-1] - 1.0

        equity = np.zeros(n, dtype=float)
        equity[0] = initial_capital
        dw = np.abs(np.diff(w, prepend=0.0))
        if dw[0] > 1e-12:
            equity[0] = max(equity[0] - commission * dw[0] * initial_capital, 0.0)

        for t in range(1, n):
            gross = w[t - 1] * mret[t]
            cost = commission * dw[t] * equity[t - 1]
            equity[t] = max(equity[t - 1] * (1.0 + gross) - cost, 0.0)

        eq_series = pd.Series(equity, index=prices.index, name="equity")
        total_return = float(equity[-1] / initial_capital - 1.0)

        if n > 1:
            ann = float((equity[-1] / initial_capital) ** (trading_days_per_year / (n - 1)) - 1.0)
        else:
            ann = 0.0

        strat_ret = np.zeros(n, dtype=float)
        strat_ret[1:] = equity[1:] / equity[:-1] - 1.0
        active = w[:-1] > 0
        if active.any():
            sr_slice = strat_ret[1:][active]
            if sr_slice.std(ddof=1) > 1e-12:
                sharpe = float(np.sqrt(trading_days_per_year) * sr_slice.mean() / sr_slice.std(ddof=1))
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0

        peak = np.maximum.accumulate(equity)
        dd = 1.0 - equity / (peak + 1e-12)
        max_dd = float(dd.max())

        held_ret = strat_ret[1:][w[:-1] > 0]
        if len(held_ret) > 0:
            win_rate = float((held_ret > 0).sum() / len(held_ret))
        else:
            win_rate = 0.0

        trade_count = int((dw > 1e-12).sum())

        trades = cls._extract_trades(prices, w, price)

        return BacktestResult(
            total_return=total_return,
            annual_return=ann,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            trade_count=trade_count,
            equity_curve=eq_series,
            trades=trades,
        )

    @staticmethod
    def _extract_trades(prices: pd.DataFrame, positions: np.ndarray, price_arr: np.ndarray) -> list[Trade]:
        trades: list[Trade] = []
        dates = prices.index
        in_pos = False
        entry_idx = 0
        for i in range(1, len(positions)):
            if positions[i] > 0.5 and positions[i - 1] < 0.5:
                in_pos = True
                entry_idx = i
            elif positions[i] < 0.5 and positions[i - 1] > 0.5 and in_pos:
                ep = float(price_arr[entry_idx])
                xp = float(price_arr[i])
                pnl = (xp - ep) / ep if ep > 0 else 0
                ed = str(dates[entry_idx])[:10]
                xd = str(dates[i])[:10]
                trades.append(Trade(
                    entry_date=ed, entry_price=round(ep, 2),
                    exit_date=xd, exit_price=round(xp, 2),
                    pnl_pct=round(pnl * 100, 2),
                    holding_days=i - entry_idx,
                    side="buy",
                ))
                in_pos = False
        if in_pos and entry_idx < len(price_arr):
            ep = float(price_arr[entry_idx])
            xp = float(price_arr[-1])
            pnl = (xp - ep) / ep if ep > 0 else 0
            trades.append(Trade(
                entry_date=str(dates[entry_idx])[:10], entry_price=round(ep, 2),
                exit_date=str(dates[-1])[:10] + " (持有中)", exit_price=round(xp, 2),
                pnl_pct=round(pnl * 100, 2),
                holding_days=len(price_arr) - 1 - entry_idx,
                side="buy",
            ))
        return trades
