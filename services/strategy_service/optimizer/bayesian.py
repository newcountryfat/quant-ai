from __future__ import annotations

from collections.abc import Callable
from typing import Any

import optuna
from optuna.samplers import TPESampler


class StrategyOptimizer:
    def optimize(
        self,
        objective_fn: Callable[[dict[str, Any]], float],
        param_space: dict[str, Any],
        n_trials: int = 50,
        seed: int | None = None,
        direction: str = "maximize",
    ) -> dict[str, Any]:
        def objective(trial: optuna.Trial) -> float:
            params: dict[str, Any] = {}
            for name, spec in param_space.items():
                params[name] = _suggest_one(trial, name, spec)
            return float(objective_fn(params))

        study = optuna.create_study(
            direction=direction,
            sampler=TPESampler(seed=seed),
        )
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
        return dict(study.best_params)


def _suggest_one(trial: optuna.Trial, name: str, spec: Any) -> Any:
    if isinstance(spec, list):
        return trial.suggest_categorical(name, spec)
    if isinstance(spec, tuple) and len(spec) == 2:
        lo, hi = spec
        if isinstance(lo, int) and isinstance(hi, int) and not isinstance(lo, bool):
            return trial.suggest_int(name, lo, hi)
        return trial.suggest_float(name, float(lo), float(hi))
    raise TypeError(f"Unsupported param spec for {name!r}: {spec!r}")
