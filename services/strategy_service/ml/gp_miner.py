"""Genetic Programming (GP) expression miner for timing signal discovery."""

from __future__ import annotations

import json
import math
import operator
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from deap import algorithms, base, creator, gp, tools


def _safe_div(a: float, b: float) -> float:
    return a / b if abs(b) > 1e-12 else 0.0


def _safe_log(a: float) -> float:
    return math.log(abs(a) + 1e-12)


def _safe_sqrt(a: float) -> float:
    return math.sqrt(abs(a))


def _neg(a: float) -> float:
    return -a


def _abs(a: float) -> float:
    return abs(a)


@dataclass
class GPExpression:
    expression: str
    fitness_sharpe: float = 0.0
    fitness_return: float = 0.0
    fitness_ic: float = 0.0
    n_generations: int = 0
    depth: int = 0
    gp_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "expression": self.expression,
            "fitness_sharpe": round(self.fitness_sharpe, 4),
            "fitness_return": round(self.fitness_return, 6),
            "fitness_ic": round(self.fitness_ic, 6),
            "n_generations": self.n_generations,
            "depth": self.depth,
        }
        if self.gp_id:
            d["gp_id"] = self.gp_id
        return d


@dataclass
class GPMiningResult:
    symbol: str = ""
    n_generations: int = 0
    population_size: int = 0
    best_expressions: list[GPExpression] = field(default_factory=list)
    hall_of_fame_size: int = 0
    feature_cols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "n_generations": self.n_generations,
            "population_size": self.population_size,
            "hall_of_fame_size": self.hall_of_fame_size,
            "best_expressions": [e.to_dict() for e in self.best_expressions],
            "feature_cols": self.feature_cols,
        }


class GPMiner:
    """Discover timing expressions via Genetic Programming."""

    MAX_DEPTH = 5
    PARSIMONY_COEFF = 0.005

    def __init__(
        self,
        population_size: int = 200,
        n_generations: int = 30,
        tournament_size: int = 5,
        max_depth: int = 5,
        crossover_prob: float = 0.7,
        mutation_prob: float = 0.2,
        parsimony_coeff: float = 0.005,
        seed: int = 42,
        model_dir: Path | str = "data/models",
    ):
        self.population_size = population_size
        self.n_generations = n_generations
        self.tournament_size = tournament_size
        self.max_depth = min(max_depth, self.MAX_DEPTH)
        self.crossover_prob = crossover_prob
        self.mutation_prob = mutation_prob
        self.parsimony_coeff = parsimony_coeff
        self.seed = seed
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

    def mine(
        self,
        df: pd.DataFrame,
        forward_period: int = 5,
        symbol: str = "",
        metric: str = "sharpe",
        save: bool = False,
    ) -> GPMiningResult:
        random.seed(self.seed)
        np.random.seed(self.seed)

        feature_cols = [c for c in df.columns if c not in (
            "open", "high", "low", "close", "volume", "amount", "turnover",
        ) and not c.startswith("fwd_ret_") and not c.startswith("label_")]

        if not feature_cols or len(df) < 60:
            return GPMiningResult(symbol=symbol)

        fwd_ret = df["close"].pct_change(periods=forward_period).shift(-forward_period)
        valid_mask = fwd_ret.notna()
        data_matrix = df[feature_cols].values
        fwd_values = fwd_ret.values

        pset = self._build_primitive_set(len(feature_cols))

        if hasattr(creator, "FitnessMax"):
            del creator.FitnessMax
        if hasattr(creator, "Individual"):
            del creator.Individual
        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        creator.create("Individual", gp.PrimitiveTree, fitness=creator.FitnessMax)

        toolbox = base.Toolbox()
        toolbox.register("expr", gp.genHalfAndHalf, pset=pset, min_=1, max_=self.max_depth)
        toolbox.register("individual", tools.initIterate, creator.Individual, toolbox.expr)
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)
        toolbox.register("compile", gp.compile, pset=pset)
        toolbox.register("select", tools.selTournament, tournsize=self.tournament_size)
        toolbox.register("mate", gp.cxOnePoint)
        toolbox.register("expr_mut", gp.genFull, min_=0, max_=2)
        toolbox.register("mutate", gp.mutUniform, expr=toolbox.expr_mut, pset=pset)

        toolbox.decorate("mate", gp.staticLimit(key=operator.attrgetter("height"), max_value=self.max_depth))
        toolbox.decorate("mutate", gp.staticLimit(key=operator.attrgetter("height"), max_value=self.max_depth))

        parsimony = self.parsimony_coeff

        def eval_individual(individual):
            func = toolbox.compile(expr=individual)
            try:
                signals = np.array([
                    func(*row) for row in data_matrix
                ], dtype=float)
            except Exception:
                return (-999.0,)

            if np.isnan(signals).all() or np.isinf(signals).any():
                return (-999.0,)

            mask = valid_mask & np.isfinite(signals)
            if mask.sum() < 30:
                return (-999.0,)

            sig = signals[mask]
            ret = fwd_values[mask]

            tree_size = len(individual)
            complexity_penalty = parsimony * tree_size

            if metric == "ic":
                ic = np.corrcoef(sig, ret)[0, 1]
                raw = float(ic) if not np.isnan(ic) else -999.0
                return (raw - complexity_penalty,) if raw > -900 else (-999.0,)

            direction = np.sign(sig)
            pnl = direction * ret
            mean_pnl = np.mean(pnl)
            std_pnl = np.std(pnl)
            sharpe = mean_pnl / std_pnl * np.sqrt(252) if std_pnl > 1e-12 else 0.0
            return (float(sharpe) - complexity_penalty,)

        toolbox.register("evaluate", eval_individual)

        pop = toolbox.population(n=self.population_size)
        hof = tools.HallOfFame(10)

        try:
            algorithms.eaSimple(
                pop, toolbox,
                cxpb=self.crossover_prob,
                mutpb=self.mutation_prob,
                ngen=self.n_generations,
                halloffame=hof,
                verbose=False,
            )
        except Exception as e:
            logger.warning("GP evolution failed: {}", e)
            return GPMiningResult(symbol=symbol)

        best_exprs = []
        for rank, ind in enumerate(hof):
            expr_str = str(ind)
            fit_val = ind.fitness.values[0] if ind.fitness.valid else 0.0
            func = toolbox.compile(expr=ind)
            try:
                signals = np.array([func(*row) for row in data_matrix], dtype=float)
                mask = valid_mask & np.isfinite(signals)
                sig = signals[mask]
                ret = fwd_values[mask]
                direction = np.sign(sig)
                pnl = direction * ret
                total_ret = float(np.sum(pnl))
                ic = float(np.corrcoef(sig, ret)[0, 1]) if len(sig) > 10 else 0.0
                std_pnl = np.std(pnl)
                sharpe = float(np.mean(pnl) / std_pnl * np.sqrt(252)) if std_pnl > 1e-12 else 0.0
            except Exception:
                total_ret = 0.0
                ic = 0.0
                sharpe = 0.0

            gp_id = ""
            if save and rank < 5:
                ds = str(df.index.min())[:10] if hasattr(df.index, 'min') else ""
                de = str(df.index.max())[:10] if hasattr(df.index, 'max') else ""
                gp_id = self._save_expression(
                    ind, pset, feature_cols, symbol, metric,
                    sharpe=sharpe, total_ret=total_ret, ic=ic,
                    data_start=ds, data_end=de, forward_period=forward_period,
                )

            best_exprs.append(GPExpression(
                expression=expr_str,
                fitness_sharpe=sharpe,
                fitness_return=total_ret,
                fitness_ic=ic if not np.isnan(ic) else 0.0,
                n_generations=self.n_generations,
                depth=ind.height,
                gp_id=gp_id,
            ))

        return GPMiningResult(
            symbol=symbol,
            n_generations=self.n_generations,
            population_size=self.population_size,
            best_expressions=best_exprs,
            hall_of_fame_size=len(hof),
            feature_cols=feature_cols,
        )

    def _save_expression(
        self, individual, pset, feature_cols, symbol, metric, *,
        sharpe=0.0, total_ret=0.0, ic=0.0,
        data_start="", data_end="", forward_period=5,
    ) -> str:
        gp_id = f"gp_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{id(individual) % 10000:04d}"

        meta = {
            "gp_id": gp_id,
            "expression": str(individual),
            "symbol": symbol,
            "depth": individual.height,
            "tree_size": len(individual),
            "metric": metric,
            "fitness_sharpe": round(sharpe, 4),
            "fitness_return": round(total_ret, 6),
            "fitness_ic": round(ic, 6),
            "feature_cols": feature_cols,
            "n_features": len(feature_cols),
            "data_start": data_start,
            "data_end": data_end,
            "forward_period": forward_period,
            "population_size": self.population_size,
            "n_generations": self.n_generations,
            "max_depth": self.max_depth,
            "parsimony_coeff": self.parsimony_coeff,
            "created_at": datetime.now().isoformat(),
            "type": "gp_expression",
        }
        meta_path = self.model_dir / f"{gp_id}.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        logger.info("Saved GP expression {} depth={} sharpe={:.4f}", gp_id, individual.height, sharpe)
        return gp_id

    def _load_expression_func(self, gp_id: str):
        """Load a saved GP expression and return (compiled_func, feature_cols)."""
        meta_path = self.model_dir / f"{gp_id}.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"GP expression not found: {meta_path}")

        with open(meta_path) as f:
            meta = json.load(f)

        feature_cols = meta["feature_cols"]
        expr_str = meta["expression"]
        n_features = len(feature_cols)

        pset = self._build_primitive_set(n_features)
        individual = gp.PrimitiveTree.from_string(expr_str, pset)
        func = gp.compile(individual, pset)
        return func, feature_cols

    @staticmethod
    def _normalize_expression(expr_str: str, feature_cols: list[str]) -> str:
        """Replace factor names in expression with x-index notation (sorted by descending length to avoid partial matches)."""
        import re
        name_to_idx = {name: f"x{i}" for i, name in enumerate(feature_cols)}
        sorted_names = sorted(name_to_idx.keys(), key=len, reverse=True)
        result = expr_str
        for name in sorted_names:
            result = re.sub(r'\b' + re.escape(name) + r'\b', name_to_idx[name], result)
        return result

    def _compile_expression_str(self, expr_str: str, feature_cols: list[str]):
        """Compile an expression string with given feature columns into a callable.
        Supports both x-index (x0, x1, ...) and factor name (ma_5, cci, ...) notation."""
        normalized = self._normalize_expression(expr_str, feature_cols)
        pset = self._build_primitive_set(len(feature_cols))
        individual = gp.PrimitiveTree.from_string(normalized, pset)
        func = gp.compile(individual, pset)
        return func

    def _eval_on_matrix(self, func, data_matrix: np.ndarray) -> list[float]:
        signals = []
        for row in data_matrix:
            try:
                v = float(func(*row))
                if not np.isfinite(v):
                    v = 0.0
            except Exception:
                v = 0.0
            signals.append(v)
        return signals

    def predict(
        self,
        gp_id: str,
        df: pd.DataFrame,
        dates: pd.Index | None = None,
    ) -> list[dict[str, Any]]:
        func, feature_cols = self._load_expression_func(gp_id)

        for m in set(feature_cols) - set(df.columns):
            df[m] = 0.0
        data_matrix = df[feature_cols].fillna(0).values

        signals = self._eval_on_matrix(func, data_matrix)

        results = []
        for i, sig in enumerate(signals):
            d = str(dates[i])[:10] if dates is not None else str(i)
            direction = 1 if sig > 0 else (-1 if sig < 0 else 0)
            results.append({
                "date": d,
                "signal": round(sig, 6),
                "direction": direction,
            })
        return results

    def generate_backtest_signals(
        self,
        gp_id: str,
        df: pd.DataFrame,
    ) -> pd.Series:
        """Generate a signal Series (1/0/-1) suitable for VectorizedBacktester."""
        func, feature_cols = self._load_expression_func(gp_id)

        for m in set(feature_cols) - set(df.columns):
            df[m] = 0.0
        data_matrix = df[feature_cols].fillna(0).values

        raw_signals = self._eval_on_matrix(func, data_matrix)
        direction = pd.Series(np.sign(raw_signals).astype(int), index=df.index, dtype=int)
        return direction

    def save_expression_from_str(
        self,
        expression: str,
        symbol: str,
        feature_cols: list[str],
        metric: str = "sharpe",
        sharpe: float = 0.0,
        total_ret: float = 0.0,
        ic: float = 0.0,
        depth: int = 0,
        tree_size: int = 0,
        data_start: str = "",
        data_end: str = "",
        forward_period: int = 5,
    ) -> str:
        """Save a single GP expression given its string representation."""
        normalized = self._normalize_expression(expression, feature_cols)
        gp_id = f"gp_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(0,9999):04d}"
        meta = {
            "gp_id": gp_id,
            "expression": normalized,
            "symbol": symbol,
            "depth": depth,
            "tree_size": tree_size,
            "metric": metric,
            "fitness_sharpe": round(sharpe, 4),
            "fitness_return": round(total_ret, 6),
            "fitness_ic": round(ic, 6),
            "feature_cols": feature_cols,
            "n_features": len(feature_cols),
            "data_start": data_start,
            "data_end": data_end,
            "forward_period": forward_period,
            "population_size": self.population_size,
            "n_generations": self.n_generations,
            "max_depth": self.max_depth,
            "parsimony_coeff": self.parsimony_coeff,
            "created_at": datetime.now().isoformat(),
            "type": "gp_expression",
        }
        meta_path = self.model_dir / f"{gp_id}.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        logger.info("Saved single GP expression {} sharpe={:.4f}", gp_id, sharpe)
        return gp_id

    def evaluate_expression(
        self,
        gp_id: str,
        df: pd.DataFrame,
        forward_period: int = 5,
    ) -> dict[str, Any]:
        """Evaluate a saved GP expression on given data, computing Sharpe, return, IC, win rate etc."""
        func, feature_cols = self._load_expression_func(gp_id)

        for m in set(feature_cols) - set(df.columns):
            df[m] = 0.0
        data_matrix = df[feature_cols].fillna(0).values

        signals = np.array(self._eval_on_matrix(func, data_matrix), dtype=float)
        fwd_ret = df["close"].pct_change(periods=forward_period).shift(-forward_period).values

        valid = np.isfinite(signals) & np.isfinite(fwd_ret)
        if valid.sum() < 10:
            return {"gp_id": gp_id, "error": "insufficient valid data", "valid_rows": int(valid.sum())}

        sig = signals[valid]
        ret = fwd_ret[valid]

        direction = np.sign(sig)
        pnl = direction * ret
        total_return = float(np.sum(pnl))
        mean_pnl = float(np.mean(pnl))
        std_pnl = float(np.std(pnl))
        sharpe = mean_pnl / std_pnl * np.sqrt(252) if std_pnl > 1e-12 else 0.0

        ic = float(np.corrcoef(sig, ret)[0, 1]) if len(sig) > 10 else 0.0
        if np.isnan(ic):
            ic = 0.0

        wins = int(np.sum(pnl > 0))
        losses = int(np.sum(pnl < 0))
        win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0

        cum_pnl = np.cumsum(pnl)
        running_max = np.maximum.accumulate(cum_pnl)
        drawdown = running_max - cum_pnl
        max_drawdown = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

        avg_win = float(np.mean(pnl[pnl > 0])) if wins > 0 else 0.0
        avg_loss = float(np.mean(pnl[pnl < 0])) if losses > 0 else 0.0
        profit_factor = abs(avg_win * wins / (avg_loss * losses)) if losses > 0 and avg_loss != 0 else float('inf')

        dates = df.index
        valid_dates = dates[valid]

        return {
            "gp_id": gp_id,
            "valid_rows": int(valid.sum()),
            "total_rows": len(df),
            "data_start": str(valid_dates.min())[:10] if len(valid_dates) else "",
            "data_end": str(valid_dates.max())[:10] if len(valid_dates) else "",
            "forward_period": forward_period,
            "total_return": round(total_return, 6),
            "annualized_return": round(mean_pnl * 252, 6),
            "sharpe": round(sharpe, 4),
            "ic": round(ic, 6),
            "win_rate": round(win_rate, 4),
            "wins": wins,
            "losses": losses,
            "max_drawdown": round(max_drawdown, 6),
            "avg_win": round(avg_win, 6),
            "avg_loss": round(avg_loss, 6),
            "profit_factor": round(profit_factor, 4) if profit_factor != float('inf') else "inf",
        }

    def evaluate_custom(
        self,
        expr_str: str,
        feature_cols: list[str],
        df: pd.DataFrame,
        forward_period: int = 5,
    ) -> dict[str, Any]:
        """Evaluate a custom expression string on given data."""
        func = self._compile_expression_str(expr_str, feature_cols)

        for m in set(feature_cols) - set(df.columns):
            df[m] = 0.0
        data_matrix = df[feature_cols].fillna(0).values

        signals = np.array(self._eval_on_matrix(func, data_matrix), dtype=float)
        fwd_ret = df["close"].pct_change(periods=forward_period).shift(-forward_period).values

        valid = np.isfinite(signals) & np.isfinite(fwd_ret)
        if valid.sum() < 10:
            return {"error": "insufficient valid data", "valid_rows": int(valid.sum())}

        sig = signals[valid]
        ret = fwd_ret[valid]

        direction = np.sign(sig)
        pnl = direction * ret
        total_return = float(np.sum(pnl))
        mean_pnl = float(np.mean(pnl))
        std_pnl = float(np.std(pnl))
        sharpe = mean_pnl / std_pnl * np.sqrt(252) if std_pnl > 1e-12 else 0.0

        ic = float(np.corrcoef(sig, ret)[0, 1]) if len(sig) > 10 else 0.0
        if np.isnan(ic):
            ic = 0.0

        wins = int(np.sum(pnl > 0))
        losses = int(np.sum(pnl < 0))
        win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0

        cum_pnl = np.cumsum(pnl)
        running_max = np.maximum.accumulate(cum_pnl)
        drawdown = running_max - cum_pnl
        max_drawdown = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

        avg_win = float(np.mean(pnl[pnl > 0])) if wins > 0 else 0.0
        avg_loss = float(np.mean(pnl[pnl < 0])) if losses > 0 else 0.0
        profit_factor = abs(avg_win * wins / (avg_loss * losses)) if losses > 0 and avg_loss != 0 else float('inf')

        dates = df.index
        valid_dates = dates[valid]

        return {
            "expression": expr_str,
            "valid_rows": int(valid.sum()),
            "total_rows": len(df),
            "data_start": str(valid_dates.min())[:10] if len(valid_dates) else "",
            "data_end": str(valid_dates.max())[:10] if len(valid_dates) else "",
            "forward_period": forward_period,
            "total_return": round(total_return, 6),
            "annualized_return": round(mean_pnl * 252, 6),
            "sharpe": round(sharpe, 4),
            "ic": round(ic, 6),
            "win_rate": round(win_rate, 4),
            "wins": wins,
            "losses": losses,
            "max_drawdown": round(max_drawdown, 6),
            "avg_win": round(avg_win, 6),
            "avg_loss": round(avg_loss, 6),
            "profit_factor": round(profit_factor, 4) if profit_factor != float('inf') else "inf",
        }

    def predict_custom(
        self,
        expr_str: str,
        feature_cols: list[str],
        df: pd.DataFrame,
        dates: pd.Index | None = None,
    ) -> list[dict[str, Any]]:
        """Predict signals using a custom expression string."""
        func = self._compile_expression_str(expr_str, feature_cols)

        for m in set(feature_cols) - set(df.columns):
            df[m] = 0.0
        data_matrix = df[feature_cols].fillna(0).values

        signals = self._eval_on_matrix(func, data_matrix)
        results = []
        for i, sig in enumerate(signals):
            d = str(dates[i])[:10] if dates is not None else str(i)
            direction = 1 if sig > 0 else (-1 if sig < 0 else 0)
            results.append({"date": d, "signal": round(sig, 6), "direction": direction})
        return results

    def backtest_signals_custom(
        self,
        expr_str: str,
        feature_cols: list[str],
        df: pd.DataFrame,
    ) -> pd.Series:
        """Generate backtest signal Series from a custom expression string."""
        func = self._compile_expression_str(expr_str, feature_cols)

        for m in set(feature_cols) - set(df.columns):
            df[m] = 0.0
        data_matrix = df[feature_cols].fillna(0).values

        raw_signals = self._eval_on_matrix(func, data_matrix)
        return pd.Series(np.sign(raw_signals).astype(int), index=df.index, dtype=int)

    def list_saved(self) -> list[dict[str, Any]]:
        results = []
        for p in sorted(self.model_dir.glob("gp_*.json"), reverse=True):
            try:
                with open(p) as f:
                    meta = json.load(f)
                if meta.get("type") == "gp_expression":
                    results.append(meta)
            except Exception:
                continue
        return results

    def delete_saved(self, gp_id: str) -> bool:
        meta_path = self.model_dir / f"{gp_id}.json"
        if meta_path.exists():
            meta_path.unlink()
            logger.info("Deleted GP expression {}", gp_id)
            return True
        return False

    @staticmethod
    def _build_primitive_set(n_features: int) -> gp.PrimitiveSet:
        pset = gp.PrimitiveSet("MAIN", n_features)
        pset.addPrimitive(operator.add, 2)
        pset.addPrimitive(operator.sub, 2)
        pset.addPrimitive(operator.mul, 2)
        pset.addPrimitive(_safe_div, 2)
        pset.addPrimitive(_neg, 1)
        pset.addPrimitive(_abs, 1)
        pset.addPrimitive(_safe_log, 1)
        pset.addPrimitive(_safe_sqrt, 1)
        pset.addPrimitive(max, 2)
        pset.addPrimitive(min, 2)
        pset.addEphemeralConstant("rand_const", lambda: round(random.uniform(-1, 1), 3))
        for i in range(n_features):
            pset.renameArguments(**{f"ARG{i}": f"x{i}"})
        return pset
