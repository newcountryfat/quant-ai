from __future__ import annotations

from datetime import date, datetime
from typing import Any

import asyncio
import json
import pandas as pd
import numpy as np
from loguru import logger

from core.config import settings
from core.db import get_db
from core.event_bus import Event, LocalEventBus

from services.strategy_service.backtester.engine import BacktestResult, VectorizedBacktester
from services.strategy_service.factor_mining.evaluator import FactorEvaluator, FactorEvalResult
from services.strategy_service.factor_mining.library import FactorLibrary
from services.strategy_service.factor_mining.walk_forward import WalkForwardValidator, WalkForwardResult
from services.strategy_service.ml.feature_selector import FeatureSelector
from services.strategy_service.ml.gp_miner import GPMiner
from services.strategy_service.ml.label_engine import LabelEngine
from services.strategy_service.ml.model_walk_forward import ModelWalkForward
from services.strategy_service.ml.pipeline import ResearchPipeline
from services.strategy_service.ml.timing_model import TimingModelTrainer
from services.strategy_service.optimizer.bayesian import StrategyOptimizer


STRATEGY_CATALOG: dict[str, dict[str, Any]] = {
    "ma_cross": {
        "name": "MA 均线交叉",
        "description": "短期均线上穿/下穿长期均线产生买卖信号",
        "default_params": {"fast": 5, "slow": 20},
        "param_space": {"fast": (2, 30), "slow": (10, 120)},
    },
    "rsi_reversal": {
        "name": "RSI 超买超卖反转",
        "description": "RSI 低于超卖线买入，高于超买线卖出",
        "default_params": {"period": 14, "oversold": 30, "overbought": 70},
        "param_space": {"period": (5, 30), "oversold": (15, 40), "overbought": (60, 85)},
    },
    "bollinger_breakout": {
        "name": "布林通道突破",
        "description": "价格突破布林上轨做多，跌破下轨做空",
        "default_params": {"period": 20, "num_std": 2.0},
        "param_space": {"period": (10, 40), "num_std": (1.5, 3.0)},
    },
}


class StrategyService:
    def __init__(self, bus: LocalEventBus) -> None:
        self._bus = bus
        self._started = False
        self._optimizer = StrategyOptimizer()

    async def start(self) -> None:
        if self._started:
            return
        self._bus.on("market.data.update", self._on_market_data_update)
        self._started = True
        settings.ensure_dirs()
        self._init_strategy_catalog()
        logger.info("StrategyService started with {} strategies", len(STRATEGY_CATALOG))

    def _init_strategy_catalog(self) -> None:
        with get_db() as conn:
            for sid, meta in STRATEGY_CATALOG.items():
                conn.execute(
                    "INSERT OR IGNORE INTO strategies (strategy_id, name, status, params_json, updated_at) "
                    "VALUES (?, ?, 'active', ?, ?)",
                    (sid, meta["name"], json.dumps(meta["default_params"]), datetime.now().isoformat()),
                )
            conn.commit()

    async def _on_market_data_update(self, event: Event) -> None:
        symbol = event.payload.get("symbol")
        if not symbol:
            return
        try:
            df = await self.compute_factors(symbol)
            cols = [c for c in df.columns if c not in ("open", "high", "low", "close", "volume")]
            tail = df.tail(5).reset_index()
            date_col = "trade_date" if "trade_date" in tail.columns else tail.columns[0]
            tail[date_col] = pd.to_datetime(tail[date_col]).dt.strftime("%Y-%m-%d")
            await self._bus.publish("factor.mining.result", {"symbol": symbol, "columns": cols, "rows": int(len(df)), "preview": tail.to_dict(orient="records")})
            sig = self._signal_from_frame(df)
            await self._bus.publish("strategy.signal", {"symbol": symbol, "signal": int(sig), "source": "strategy_service"})
        except Exception:
            logger.exception("market.data.update handler failed symbol={}", symbol)

    # ---------- data loading ----------

    def _load_ohlcv(self, symbol: str, start: str | date | None = None, end: str | date | None = None) -> pd.DataFrame:
        start_s = str(start) if start is not None else None
        end_s = str(end) if end is not None else None
        with get_db() as conn:
            q = "SELECT trade_date, open, high, low, close, volume FROM daily_quotes WHERE symbol = ?"
            args: list[Any] = [symbol]
            if start_s:
                q += " AND trade_date >= ?"; args.append(start_s)
            if end_s:
                q += " AND trade_date <= ?"; args.append(end_s)
            q += " ORDER BY trade_date"
            rows = conn.execute(q, args).fetchall()
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame([dict(r) for r in rows])
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date")
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna(how="any")

    # ---------- factors ----------

    async def compute_factors(self, symbol: str) -> pd.DataFrame:
        return await asyncio.to_thread(self._compute_factors_sync, symbol)

    def _compute_factors_sync(self, symbol: str) -> pd.DataFrame:
        df = self._load_ohlcv(symbol)
        if df.empty:
            logger.warning("No OHLCV for symbol={}", symbol)
            return df
        return FactorLibrary.compute_all(df)

    def _signal_from_frame(self, df: pd.DataFrame) -> int:
        if df.empty or "ma_5" not in df.columns or "ma_20" not in df.columns:
            return 0
        last, prev = df.iloc[-1], df.iloc[-2] if len(df) > 1 else df.iloc[-1]
        if last["ma_5"] > last["ma_20"] and prev["ma_5"] <= prev["ma_20"]:
            return 1
        if last["ma_5"] < last["ma_20"] and prev["ma_5"] >= prev["ma_20"]:
            return -1
        return 0

    # ---------- signal builders ----------

    def _build_signals_ma_cross(self, df: pd.DataFrame, fast: int, slow: int) -> pd.Series:
        c = df["close"]
        ma_f = c.rolling(window=fast, min_periods=fast).mean()
        ma_s = c.rolling(window=slow, min_periods=slow).mean()
        up = (ma_f > ma_s) & (ma_f.shift(1) <= ma_s.shift(1))
        down = (ma_f < ma_s) & (ma_f.shift(1) >= ma_s.shift(1))
        sig = pd.Series(0, index=df.index, dtype=int)
        return sig.mask(up, 1).mask(down, -1)

    def _build_signals_rsi_reversal(self, df: pd.DataFrame, period: int, oversold: float, overbought: float) -> pd.Series:
        delta = df["close"].diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-12)
        rsi = 100 - (100 / (1 + rs))
        sig = pd.Series(0, index=df.index, dtype=int)
        buy = (rsi < oversold) & (rsi.shift(1) >= oversold)
        sell = (rsi > overbought) & (rsi.shift(1) <= overbought)
        return sig.mask(buy, 1).mask(sell, -1)

    def _build_signals_bollinger_breakout(self, df: pd.DataFrame, period: int, num_std: float) -> pd.Series:
        c = df["close"]
        mid = c.rolling(window=period, min_periods=period).mean()
        std = c.rolling(window=period, min_periods=period).std()
        upper = mid + num_std * std
        lower = mid - num_std * std
        sig = pd.Series(0, index=df.index, dtype=int)
        buy = (c > upper) & (c.shift(1) <= upper.shift(1))
        sell = (c < lower) & (c.shift(1) >= lower.shift(1))
        return sig.mask(buy, 1).mask(sell, -1)

    def _build_signals(self, strategy_id: str, df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
        if strategy_id == "rsi_reversal":
            return self._build_signals_rsi_reversal(
                df, int(params.get("period", 14)),
                float(params.get("oversold", 30)), float(params.get("overbought", 70)),
            )
        if strategy_id == "bollinger_breakout":
            return self._build_signals_bollinger_breakout(
                df, int(params.get("period", 20)), float(params.get("num_std", 2.0)),
            )
        return self._build_signals_ma_cross(df, int(params.get("fast", 5)), int(params.get("slow", 20)))

    # ---------- backtest ----------

    async def run_backtest(
        self, strategy_id: str, symbol: str,
        start: str | date, end: str | date,
        params: dict[str, Any] | None = None,
    ) -> BacktestResult:
        params = params or STRATEGY_CATALOG.get(strategy_id, {}).get("default_params", {})

        def job() -> BacktestResult:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return BacktestResult(0.0, 0.0, 0.0, 0.0, 0.0, 0, pd.Series(dtype=float))
            signals = self._build_signals(strategy_id, df, params)
            return VectorizedBacktester.run(
                df, signals,
                initial_capital=float(params.get("initial_capital", 1_000_000)),
                commission=float(params.get("commission", 0.001)),
            )

        result = await asyncio.to_thread(job)
        self._save_backtest_result(strategy_id, symbol, str(start), str(end), params, result)
        logger.info("Backtest done {}:{} return={:.4f} trades={}", strategy_id, symbol, result.total_return, result.trade_count)
        return result

    def _save_backtest_result(self, strategy_id: str, symbol: str, start: str, end: str, params: dict, result: BacktestResult) -> None:
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO backtest_results (strategy_id, symbol, start_date, end_date, params_json, "
                    "total_return, annual_return, sharpe, max_dd, win_rate, trade_count, run_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (strategy_id, symbol, start, end, json.dumps(params),
                     result.total_return, result.annual_return, result.sharpe_ratio,
                     result.max_drawdown, result.win_rate, result.trade_count, datetime.now().isoformat()),
                )
                conn.commit()
        except Exception:
            logger.warning("Failed to save backtest result")

    # ---------- optimizer ----------

    async def optimize_strategy(
        self, strategy_id: str, symbol: str,
        start: str | date, end: str | date,
        n_trials: int = 30, metric: str = "sharpe_ratio",
    ) -> dict[str, Any]:
        catalog = STRATEGY_CATALOG.get(strategy_id)
        if not catalog:
            raise ValueError(f"Unknown strategy: {strategy_id}")
        param_space = catalog["param_space"]

        def objective(params: dict[str, Any]) -> float:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return -999.0
            if strategy_id == "bollinger_breakout":
                params = {**params, "period": int(params.get("period", 20))}
            else:
                params = {k: int(v) if isinstance(v, float) and v == int(v) else v for k, v in params.items()}
            signals = self._build_signals(strategy_id, df, params)
            result = VectorizedBacktester.run(df, signals)
            return getattr(result, metric, result.sharpe_ratio)

        best = await asyncio.to_thread(
            self._optimizer.optimize, objective, param_space, n_trials=n_trials, direction="maximize",
        )
        bt = await self.run_backtest(strategy_id, symbol, start, end, best)
        return {
            "best_params": best,
            "n_trials": n_trials,
            "metric": metric,
            "result": {
                "total_return": round(bt.total_return, 6),
                "annual_return": round(bt.annual_return, 6),
                "sharpe_ratio": round(bt.sharpe_ratio, 4),
                "max_drawdown": round(bt.max_drawdown, 6),
                "win_rate": round(bt.win_rate, 4),
                "trade_count": bt.trade_count,
            },
        }

    # ---------- strategy CRUD ----------

    async def register_strategy(self, strategy_id: str, name: str, params: dict[str, Any]) -> dict:
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO strategies (strategy_id, name, status, params_json, updated_at) VALUES (?,?,?,?,?)",
                (strategy_id, name, "active", json.dumps(params), datetime.now().isoformat()),
            )
            conn.commit()
        return {"strategy_id": strategy_id, "status": "registered"}

    async def update_strategy_status(self, strategy_id: str, status: str) -> dict:
        with get_db() as conn:
            conn.execute(
                "UPDATE strategies SET status=?, updated_at=? WHERE strategy_id=?",
                (status, datetime.now().isoformat(), strategy_id),
            )
            conn.commit()
        return {"strategy_id": strategy_id, "status": status}

    async def get_backtest_history(self, strategy_id: str | None = None, limit: int = 20) -> list[dict]:
        with get_db() as conn:
            if strategy_id:
                rows = conn.execute(
                    "SELECT * FROM backtest_results WHERE strategy_id=? ORDER BY run_at DESC LIMIT ?",
                    (strategy_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM backtest_results ORDER BY run_at DESC LIMIT ?", (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    # ================================================================
    # P2 — Batch factor compute, evaluate, walk-forward
    # ================================================================

    async def batch_compute_factors(
        self,
        symbol: str,
        start: str | date | None = None,
        end: str | date | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        """Compute all factors for *symbol*, optionally persist to factor_values."""

        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"symbol": symbol, "rows": 0, "factors": []}
            out = FactorLibrary.compute_all(df)
            factor_cols = FactorLibrary.list_factor_names(out)

            if persist:
                self._persist_factor_values(symbol, out, factor_cols)

            sample = out.tail(5).reset_index()
            if "trade_date" in sample.columns:
                sample["trade_date"] = sample["trade_date"].astype(str)
            return {
                "symbol": symbol,
                "rows": len(out),
                "factors": factor_cols,
                "data_start": str(out.index.min())[:10],
                "data_end": str(out.index.max())[:10],
                "sample": json.loads(sample.to_json(orient="records")),
            }

        return await asyncio.to_thread(_job)

    def _persist_factor_values(self, symbol: str, df: pd.DataFrame, factor_cols: list[str]) -> None:
        rows = []
        idx = df.index
        for i in range(len(df)):
            d = str(idx[i])[:10]
            for col in factor_cols:
                val = df[col].iloc[i]
                if pd.notna(val):
                    rows.append((symbol, d, col, float(val)))
        if not rows:
            return
        with get_db() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO factor_values (symbol, trade_date, factor_name, value) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        logger.info("Persisted {} factor_values rows for {}", len(rows), symbol)

    async def evaluate_factors(
        self,
        symbol: str,
        forward_period: int = 5,
        start: str | date | None = None,
        end: str | date | None = None,
        persist: bool = True,
    ) -> list[dict[str, Any]]:
        """Evaluate all factors for *symbol* against forward returns."""

        def _job() -> list[dict[str, Any]]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return []
            factor_df = FactorLibrary.compute_all(df)
            evaluator = FactorEvaluator(forward_periods=[forward_period])
            results = evaluator.evaluate_batch(factor_df, df, forward_period=forward_period)

            if persist:
                self._persist_eval_results(symbol, results, forward_period)

            return [r.to_dict() for r in results]

        return await asyncio.to_thread(_job)

    def _persist_eval_results(self, symbol: str, results: list[FactorEvalResult], forward_period: int) -> None:
        rows = []
        now = datetime.now().isoformat()
        for r in results:
            rows.append((
                symbol, r.factor_name, forward_period,
                r.ic_mean, r.ic_std, r.icir,
                r.rank_ic_mean, r.rank_icir,
                r.ic_positive_ratio, r.monotonicity,
                json.dumps(r.sub_period_ics),
                now,
            ))
        if not rows:
            return
        with get_db() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO factor_eval_results "
                "(symbol, factor_name, forward_period, ic_mean, ic_std, icir, "
                "rank_ic_mean, rank_icir, ic_positive_ratio, monotonicity, "
                "sub_period_json, evaluated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        logger.info("Persisted {} eval results for {}", len(rows), symbol)

    async def walk_forward_validate(
        self,
        symbol: str,
        factor_names: list[str] | None = None,
        train_days: int = 120,
        test_days: int = 20,
        step_days: int = 20,
        forward_period: int = 5,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> list[dict[str, Any]]:
        """Run walk-forward validation for specified factors on *symbol*."""

        def _job() -> list[dict[str, Any]]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return []
            factor_df = FactorLibrary.compute_all(df)
            base_cols = {"open", "high", "low", "close", "volume", "amount", "turnover"}
            cols = factor_names or [c for c in factor_df.columns if c not in base_cols]

            validator = WalkForwardValidator(
                train_days=train_days,
                test_days=test_days,
                step_days=step_days,
                forward_period=forward_period,
            )
            results = []
            for col in cols:
                if col not in factor_df.columns:
                    continue
                res = validator.validate(
                    factor_df[col],
                    df["close"],
                    factor_name=col,
                    symbol=symbol,
                )
                results.append(res.to_dict())
            return results

        return await asyncio.to_thread(_job)

    async def get_factor_eval_history(
        self,
        symbol: str | None = None,
        factor_name: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        with get_db() as conn:
            q = "SELECT * FROM factor_eval_results WHERE 1=1"
            args: list[Any] = []
            if symbol:
                q += " AND symbol = ?"
                args.append(symbol)
            if factor_name:
                q += " AND factor_name = ?"
                args.append(factor_name)
            q += " ORDER BY evaluated_at DESC LIMIT ?"
            args.append(limit)
            rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    async def get_persisted_factor_values(
        self,
        symbol: str,
        factor_name: str | None = None,
        start: str | date | None = None,
        end: str | date | None = None,
        limit: int = 60,
    ) -> dict[str, Any]:
        with get_db() as conn:
            where = ["symbol = ?"]
            args: list[Any] = [symbol]

            if factor_name:
                where.append("factor_name = ?")
                args.append(factor_name)
            if start:
                where.append("trade_date >= ?")
                args.append(str(start))
            if end:
                where.append("trade_date <= ?")
                args.append(str(end))

            where_sql = " AND ".join(where)
            summary = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS row_count,
                    COUNT(DISTINCT trade_date) AS date_count,
                    COUNT(DISTINCT factor_name) AS factor_count,
                    MIN(trade_date) AS min_date,
                    MAX(trade_date) AS max_date
                FROM factor_values
                WHERE {where_sql}
                """,
                args,
            ).fetchone()

            rows = conn.execute(
                f"""
                SELECT trade_date, factor_name, value
                FROM factor_values
                WHERE {where_sql}
                ORDER BY trade_date DESC, factor_name
                LIMIT ?
                """,
                [*args, limit],
            ).fetchall()

        return {
            "items": [dict(r) for r in rows],
            "summary": {
                "row_count": summary["row_count"] or 0,
                "date_count": summary["date_count"] or 0,
                "factor_count": summary["factor_count"] or 0,
                "min_date": summary["min_date"],
                "max_date": summary["max_date"],
            },
        }

    # ================================================================
    # P3 — Label engineering, feature selection, ML models
    # ================================================================

    async def generate_labels(
        self,
        symbol: str,
        forward_periods: list[int] | None = None,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> dict[str, Any]:
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"symbol": symbol, "rows": 0, "labels": []}
            periods = forward_periods or [5, 10, 20]
            out = LabelEngine.generate_all_labels(df, forward_periods=periods)
            label_cols = LabelEngine.label_columns(out)

            max_period = max(periods)
            min_period = min(periods)

            nan_per_period = {}
            for p in sorted(periods):
                col = f"label_dir_{p}"
                if col in out.columns:
                    nan_per_period[p] = int(out[col].isna().sum())

            dir_cols = [c for c in label_cols if c.startswith("label_dir_")]
            if dir_cols:
                all_valid_mask = out[dir_cols].notna().all(axis=1)
                any_valid_mask = out[dir_cols].notna().any(axis=1)
            else:
                fwd_cols = [f"fwd_ret_{p}" for p in periods if f"fwd_ret_{p}" in out.columns]
                all_valid_mask = out[fwd_cols].notna().all(axis=1) if fwd_cols else pd.Series(True, index=out.index)
                any_valid_mask = all_valid_mask

            all_valid_df = out[all_valid_mask]
            any_valid_df = out[any_valid_mask]
            full_invalid_tail = len(out) - len(any_valid_df)
            partial_invalid_tail = len(out) - len(all_valid_df)

            sample = any_valid_df[label_cols].tail(10).reset_index()
            if "trade_date" in sample.columns:
                sample["trade_date"] = sample["trade_date"].astype(str)
            records = json.loads(sample.to_json(orient="records"))

            note_parts = []
            for p in sorted(periods):
                n = nan_per_period.get(p, 0)
                if n > 0:
                    note_parts.append(f"label_dir_{p} 最后 {n} 天为 NaN")
            note = "；".join(note_parts) + "。已自动截断，不参与训练和挖掘" if note_parts else ""

            return {
                "symbol": symbol,
                "rows": len(out),
                "valid_rows": len(all_valid_df),
                "truncated_tail": partial_invalid_tail,
                "full_invalid_tail": full_invalid_tail,
                "max_forward_period": max_period,
                "nan_per_period": nan_per_period,
                "labels": label_cols,
                "data_start": str(out.index.min())[:10],
                "data_end": str(out.index.max())[:10],
                "valid_end": str(all_valid_df.index.max())[:10] if not all_valid_df.empty else "",
                "sample": records,
                "note": note,
            }
        return await asyncio.to_thread(_job)

    async def select_features(
        self,
        symbol: str,
        label_col: str = "label_dir_5",
        forward_period: int = 5,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> dict[str, Any]:
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"symbol": symbol, "error": "no data"}
            factor_df = FactorLibrary.compute_all(df)
            labeled = LabelEngine.generate_all_labels(factor_df, forward_periods=[forward_period])
            base_cols = {"open", "high", "low", "close", "volume", "amount", "turnover"}
            label_cols = set(LabelEngine.label_columns(labeled))
            feature_cols = [c for c in labeled.columns if c not in base_cols and c not in label_cols]
            clean = labeled.dropna(subset=[label_col])
            X = clean[feature_cols].fillna(0)
            y = clean[label_col]
            selector = FeatureSelector()
            _, report = selector.select(X, y)
            return {
                "symbol": symbol,
                "label_col": label_col,
                "data_start": str(df.index.min())[:10],
                "data_end": str(df.index.max())[:10],
                "report": report.to_dict(),
            }
        return await asyncio.to_thread(_job)

    async def train_model(
        self,
        symbol: str,
        model_type: str = "lightgbm",
        label_col: str = "label_dir_5",
        forward_period: int = 5,
        train_ratio: float = 0.8,
        start: str | date | None = None,
        end: str | date | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"error": "no data"}
            factor_df = FactorLibrary.compute_all(df)
            labeled = LabelEngine.generate_all_labels(factor_df, forward_periods=[forward_period])
            base_cols = {"open", "high", "low", "close", "volume", "amount", "turnover"}
            label_cols = set(LabelEngine.label_columns(labeled))
            feature_cols = [c for c in labeled.columns if c not in base_cols and c not in label_cols]
            clean = labeled.dropna(subset=[label_col])
            X = clean[feature_cols].fillna(0)
            y = clean[label_col]
            selector = FeatureSelector()
            X_sel, _ = selector.select(X, y)
            split_idx = int(len(X_sel) * train_ratio)
            trainer = TimingModelTrainer()
            result = trainer.train(
                X_sel.iloc[:split_idx], y.iloc[:split_idx],
                X_sel.iloc[split_idx:], y.iloc[split_idx:],
                model_type=model_type, symbol=symbol,
                label_col=label_col, params=params,
            )
            return result.to_dict()
        return await asyncio.to_thread(_job)

    async def model_walk_forward(
        self,
        symbol: str,
        model_type: str = "lightgbm",
        label_col: str = "label_dir_5",
        forward_period: int = 5,
        train_days: int = 200,
        test_days: int = 20,
        step_days: int = 20,
        start: str | date | None = None,
        end: str | date | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"error": "no data"}
            factor_df = FactorLibrary.compute_all(df)
            labeled = LabelEngine.generate_all_labels(factor_df, forward_periods=[forward_period])
            base_cols = {"open", "high", "low", "close", "volume", "amount", "turnover"}
            label_cols = set(LabelEngine.label_columns(labeled))
            feature_cols = [c for c in labeled.columns if c not in base_cols and c not in label_cols]
            clean = labeled.dropna(subset=[label_col])
            X = clean[feature_cols].fillna(0)
            y = clean[label_col]
            selector = FeatureSelector()
            X_sel, _ = selector.select(X, y)
            wf = ModelWalkForward(train_days=train_days, test_days=test_days, step_days=step_days)
            result = wf.run(X_sel, y, clean["close"], model_type=model_type, symbol=symbol, label_col=label_col, params=params)
            return result.to_dict()
        return await asyncio.to_thread(_job)

    async def predict_signal(
        self,
        model_id: str,
        symbol: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> dict[str, Any]:
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"error": "no data"}
            factor_df = FactorLibrary.compute_all(df)
            base_cols = {"open", "high", "low", "close", "volume", "amount", "turnover"}
            feature_cols = [c for c in factor_df.columns if c not in base_cols]
            X = factor_df[feature_cols].fillna(0)
            trainer = TimingModelTrainer()
            result = trainer.predict(model_id, X, dates=factor_df.index)
            result.symbol = symbol
            return result.to_dict()
        return await asyncio.to_thread(_job)

    async def list_models(self) -> list[dict[str, Any]]:
        trainer = TimingModelTrainer()
        return trainer.list_models()

    # ================================================================
    # P4 — GP mining, full pipeline
    # ================================================================

    async def gp_mine(
        self,
        symbol: str,
        forward_period: int = 5,
        population_size: int = 200,
        n_generations: int = 30,
        metric: str = "sharpe",
        max_depth: int = 5,
        parsimony_coeff: float = 0.005,
        save: bool = False,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> dict[str, Any]:
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"error": "no data"}
            factor_df = FactorLibrary.compute_all(df)
            miner = GPMiner(
                population_size=population_size,
                n_generations=n_generations,
                max_depth=max_depth,
                parsimony_coeff=parsimony_coeff,
            )
            result = miner.mine(
                factor_df, forward_period=forward_period,
                symbol=symbol, metric=metric, save=save,
            )
            return result.to_dict()
        return await asyncio.to_thread(_job)

    async def gp_predict(
        self,
        gp_id: str,
        symbol: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> dict[str, Any]:
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"error": "no data"}
            factor_df = FactorLibrary.compute_all(df)
            miner = GPMiner()
            preds = miner.predict(gp_id, factor_df, dates=factor_df.index)
            return {"gp_id": gp_id, "symbol": symbol, "count": len(preds), "predictions": preds}
        return await asyncio.to_thread(_job)

    async def gp_list(self) -> list[dict[str, Any]]:
        miner = GPMiner()
        return miner.list_saved()

    async def gp_save_single(
        self,
        expression: str,
        symbol: str,
        metric: str = "sharpe",
        sharpe: float = 0.0,
        total_ret: float = 0.0,
        ic: float = 0.0,
        depth: int = 0,
        tree_size: int = 0,
        data_start: str = "",
        data_end: str = "",
        forward_period: int = 5,
    ) -> dict[str, Any]:
        """Save a single GP expression by its string form, recomputing feature_cols from current factor library."""
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start="2025-01-01")
            if df.empty:
                return {"error": "no data to derive feature columns"}
            factor_df = FactorLibrary.compute_all(df)
            base_cols = {"open", "high", "low", "close", "volume", "amount", "turnover"}
            feature_cols = [c for c in factor_df.columns if c not in base_cols
                           and not c.startswith("fwd_ret_") and not c.startswith("label_")]
            miner = GPMiner()
            gp_id = miner.save_expression_from_str(
                expression=expression, symbol=symbol, feature_cols=feature_cols,
                metric=metric, sharpe=sharpe, total_ret=total_ret, ic=ic,
                depth=depth, tree_size=tree_size,
                data_start=data_start, data_end=data_end,
                forward_period=forward_period,
            )
            return {"gp_id": gp_id, "expression": expression, "symbol": symbol}
        return await asyncio.to_thread(_job)

    async def gp_evaluate(
        self,
        gp_id: str,
        symbol: str,
        forward_period: int = 5,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> dict[str, Any]:
        """Evaluate a saved GP expression on specified symbol and date range."""
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"gp_id": gp_id, "error": "no data"}
            factor_df = FactorLibrary.compute_all(df)
            miner = GPMiner()
            return miner.evaluate_expression(gp_id, factor_df, forward_period=forward_period)
        return await asyncio.to_thread(_job)

    # ================================================================
    # Custom expression (no gp_id required)
    # ================================================================

    def _derive_feature_cols(self, df: pd.DataFrame) -> list[str]:
        """Get ordered list of factor column names from a factor-computed DataFrame."""
        base_cols = {"open", "high", "low", "close", "volume", "amount", "turnover"}
        return [c for c in df.columns if c not in base_cols
                and not c.startswith("fwd_ret_") and not c.startswith("label_")]

    async def custom_expr_evaluate(
        self,
        expression: str,
        symbol: str,
        forward_period: int = 5,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> dict[str, Any]:
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"error": "no data"}
            factor_df = FactorLibrary.compute_all(df)
            feature_cols = self._derive_feature_cols(factor_df)
            miner = GPMiner()
            result = miner.evaluate_custom(expression, feature_cols, factor_df, forward_period=forward_period)
            result["symbol"] = symbol
            result["feature_cols"] = feature_cols
            return result
        return await asyncio.to_thread(_job)

    async def custom_expr_predict(
        self,
        expression: str,
        symbol: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> dict[str, Any]:
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"error": "no data"}
            factor_df = FactorLibrary.compute_all(df)
            feature_cols = self._derive_feature_cols(factor_df)
            miner = GPMiner()
            preds = miner.predict_custom(expression, feature_cols, factor_df, dates=factor_df.index)
            return {"expression": expression, "symbol": symbol, "count": len(preds),
                    "predictions": preds, "feature_cols": feature_cols}
        return await asyncio.to_thread(_job)

    async def custom_expr_backtest(
        self,
        expression: str,
        symbol: str,
        start: str | date = "2024-01-01",
        end: str | date | None = None,
        initial_capital: float = 1_000_000,
        commission: float = 0.001,
    ) -> BacktestResult:
        end = end or date.today().isoformat()

        def _job() -> BacktestResult:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return BacktestResult(0.0, 0.0, 0.0, 0.0, 0.0, 0, pd.Series(dtype=float))
            factor_df = FactorLibrary.compute_all(df)
            feature_cols = self._derive_feature_cols(factor_df)
            miner = GPMiner()
            signals = miner.backtest_signals_custom(expression, feature_cols, factor_df)
            return VectorizedBacktester.run(
                df, signals,
                initial_capital=initial_capital,
                commission=commission,
            )

        result = await asyncio.to_thread(_job)
        self._save_backtest_result(f"custom_expr", symbol, str(start), str(end),
                                   {"expression": expression}, result)
        return result

    # ================================================================
    # Expression / Model backtest
    # ================================================================

    async def backtest_gp_expression(
        self,
        gp_id: str,
        symbol: str,
        start: str | date = "2024-01-01",
        end: str | date | None = None,
        initial_capital: float = 1_000_000,
        commission: float = 0.001,
    ) -> BacktestResult:
        end = end or date.today().isoformat()

        def _job() -> BacktestResult:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return BacktestResult(0.0, 0.0, 0.0, 0.0, 0.0, 0, pd.Series(dtype=float))
            factor_df = FactorLibrary.compute_all(df)
            miner = GPMiner()
            signals = miner.generate_backtest_signals(gp_id, factor_df)
            return VectorizedBacktester.run(
                df, signals,
                initial_capital=initial_capital,
                commission=commission,
            )

        result = await asyncio.to_thread(_job)
        self._save_backtest_result(f"gp:{gp_id}", symbol, str(start), str(end), {"gp_id": gp_id}, result)
        logger.info("GP backtest done {}:{} return={:.4f} trades={}", gp_id, symbol, result.total_return, result.trade_count)
        return result

    async def backtest_ml_model(
        self,
        model_id: str,
        symbol: str,
        start: str | date = "2024-01-01",
        end: str | date | None = None,
        initial_capital: float = 1_000_000,
        commission: float = 0.001,
        threshold: float = 0.5,
    ) -> BacktestResult:
        end = end or date.today().isoformat()

        def _job() -> BacktestResult:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return BacktestResult(0.0, 0.0, 0.0, 0.0, 0.0, 0, pd.Series(dtype=float))
            factor_df = FactorLibrary.compute_all(df)
            base_cols = {"open", "high", "low", "close", "volume", "amount", "turnover"}
            feature_cols = [c for c in factor_df.columns if c not in base_cols]
            X = factor_df[feature_cols].fillna(0)

            trainer = TimingModelTrainer()
            pred_result = trainer.predict(model_id, X, dates=factor_df.index)

            sig = pd.Series(0, index=factor_df.index, dtype=int)
            for p in pred_result.predictions:
                d = pd.Timestamp(p["date"])
                prob = p.get("probability", 0.5)
                if prob >= threshold:
                    sig.loc[d] = 1
                elif prob < (1 - threshold):
                    sig.loc[d] = -1

            return VectorizedBacktester.run(
                df, sig,
                initial_capital=initial_capital,
                commission=commission,
            )

        result = await asyncio.to_thread(_job)
        self._save_backtest_result(f"ml:{model_id}", symbol, str(start), str(end), {"model_id": model_id, "threshold": threshold}, result)
        logger.info("ML backtest done {}:{} return={:.4f} trades={}", model_id, symbol, result.total_return, result.trade_count)
        return result

    async def run_pipeline(
        self,
        symbol: str,
        model_type: str = "lightgbm",
        label_col: str = "label_dir_5",
        forward_period: int = 5,
        train_ratio: float = 0.8,
        wf_train_days: int = 200,
        wf_test_days: int = 20,
        wf_step_days: int = 20,
        start: str | date | None = None,
        end: str | date | None = None,
        model_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        def _job() -> dict[str, Any]:
            df = self._load_ohlcv(symbol, start=start, end=end)
            if df.empty:
                return {"error": "no data"}
            pipeline = ResearchPipeline()
            result = pipeline.run(
                df, symbol=symbol, model_type=model_type,
                label_col=label_col, forward_period=forward_period,
                train_ratio=train_ratio,
                wf_train_days=wf_train_days, wf_test_days=wf_test_days,
                wf_step_days=wf_step_days, model_params=model_params,
            )
            return result.to_dict()
        return await asyncio.to_thread(_job)
