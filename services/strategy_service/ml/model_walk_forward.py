"""Walk-forward model training: rolling-window train → predict → evaluate loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger


@dataclass
class ModelWFResult:
    model_type: str = ""
    symbol: str = ""
    label_col: str = ""
    n_folds: int = 0
    avg_accuracy: float = 0.0
    avg_f1: float = 0.0
    avg_auc: float = 0.0
    cumulative_return: float = 0.0
    cumulative_sharpe: float = 0.0
    folds: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_type": self.model_type,
            "symbol": self.symbol,
            "label_col": self.label_col,
            "n_folds": self.n_folds,
            "avg_accuracy": round(self.avg_accuracy, 4),
            "avg_f1": round(self.avg_f1, 4),
            "avg_auc": round(self.avg_auc, 4),
            "cumulative_return": round(self.cumulative_return, 6),
            "cumulative_sharpe": round(self.cumulative_sharpe, 4),
            "folds": self.folds,
        }


class ModelWalkForward:
    """Rolling-window walk-forward for ML timing models."""

    def __init__(
        self,
        train_days: int = 200,
        test_days: int = 20,
        step_days: int = 20,
    ):
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days

    def run(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        close: pd.Series,
        model_type: str = "lightgbm",
        symbol: str = "",
        label_col: str = "",
        params: dict[str, Any] | None = None,
    ) -> ModelWFResult:
        n = len(X)
        if n < self.train_days + self.test_days:
            return ModelWFResult(model_type=model_type, symbol=symbol, label_col=label_col)

        folds = []
        all_test_preds = []
        all_test_rets = []
        idx = 0
        fold_num = 0

        while idx + self.train_days + self.test_days <= n:
            train_end = idx + self.train_days
            test_end = min(train_end + self.test_days, n)

            X_tr = X.iloc[idx:train_end]
            y_tr = y.iloc[idx:train_end]
            X_te = X.iloc[train_end:test_end]
            y_te = y.iloc[train_end:test_end]

            tr_valid = y_tr.dropna()
            te_valid = y_te.dropna()
            if len(tr_valid) < 30 or len(te_valid) < 5:
                idx += self.step_days
                continue

            X_tr_clean = X_tr.loc[tr_valid.index].fillna(0)
            y_tr_clean = tr_valid
            X_te_clean = X_te.loc[te_valid.index].fillna(0)
            y_te_clean = te_valid

            model = self._fit_model(model_type, X_tr_clean, y_tr_clean, params)
            if model is None:
                idx += self.step_days
                continue

            y_pred = model.predict(X_te_clean)
            y_prob = self._predict_proba(model, X_te_clean)

            from .timing_model import _compute_metrics
            metrics = _compute_metrics(y_te_clean.values, y_pred, y_prob)

            close_te = close.iloc[train_end:test_end].loc[te_valid.index]
            fold_ret, fold_sharpe = self._signal_pnl(y_pred, close_te)

            all_test_preds.extend(y_pred.tolist())
            all_test_rets.append(fold_ret)

            dates = X.index
            fold_info = {
                "fold": fold_num,
                "train_period": f"{str(dates[idx])[:10]}~{str(dates[train_end - 1])[:10]}",
                "test_period": f"{str(dates[train_end])[:10]}~{str(dates[test_end - 1])[:10]}",
                "n_train": len(X_tr_clean),
                "n_test": len(X_te_clean),
                "accuracy": round(metrics.accuracy, 4),
                "f1": round(metrics.f1, 4),
                "auc": round(metrics.auc, 4),
                "fold_return": round(fold_ret, 6),
                "fold_sharpe": round(fold_sharpe, 4),
            }
            folds.append(fold_info)
            fold_num += 1
            idx += self.step_days

        if not folds:
            return ModelWFResult(model_type=model_type, symbol=symbol, label_col=label_col)

        accs = [f["accuracy"] for f in folds]
        f1s = [f["f1"] for f in folds]
        aucs = [f["auc"] for f in folds]
        cum_ret = float(np.prod([1 + r for r in all_test_rets]) - 1) if all_test_rets else 0.0
        rets_arr = np.array(all_test_rets)
        cum_sharpe = float(np.mean(rets_arr) / (np.std(rets_arr) + 1e-12) * np.sqrt(12)) if len(rets_arr) > 1 else 0.0

        return ModelWFResult(
            model_type=model_type,
            symbol=symbol,
            label_col=label_col,
            n_folds=len(folds),
            avg_accuracy=float(np.mean(accs)),
            avg_f1=float(np.mean(f1s)),
            avg_auc=float(np.mean(aucs)),
            cumulative_return=cum_ret,
            cumulative_sharpe=cum_sharpe,
            folds=folds,
        )

    @staticmethod
    def _fit_model(model_type: str, X: pd.DataFrame, y: pd.Series, params: dict | None) -> Any:
        try:
            if model_type == "lasso":
                from sklearn.linear_model import LogisticRegression
                from sklearn.pipeline import Pipeline
                from sklearn.preprocessing import StandardScaler
                p = params or {}
                scaler = StandardScaler()
                clf = LogisticRegression(penalty="l1", C=p.get("C", 1.0), solver="saga", max_iter=2000, random_state=42)
                pipe = Pipeline([("scaler", scaler), ("clf", clf)])
                pipe.fit(X, y)
                return pipe
            else:
                import lightgbm as lgb
                default_p = {
                    "objective": "binary", "verbosity": -1, "n_estimators": 100,
                    "max_depth": 4, "learning_rate": 0.05, "num_leaves": 15,
                    "subsample": 0.8, "colsample_bytree": 0.8, "min_child_samples": 10,
                    "random_state": 42,
                }
                if params:
                    default_p.update(params)
                clf = lgb.LGBMClassifier(**default_p)
                clf.fit(X, y)
                return clf
        except Exception as e:
            logger.warning("Model fitting failed: {}", e)
            return None

    @staticmethod
    def _predict_proba(model: Any, X: pd.DataFrame) -> np.ndarray | None:
        try:
            probs = model.predict_proba(X)
            return probs[:, 1] if probs.ndim == 2 else probs
        except Exception:
            return None

    @staticmethod
    def _signal_pnl(predictions: np.ndarray, close: pd.Series) -> tuple[float, float]:
        if len(close) < 2:
            return 0.0, 0.0
        rets = close.pct_change().fillna(0).values
        signal = np.where(predictions > 0.5, 1.0, 0.0)[: len(rets)]
        pnl = signal * rets
        total_ret = float(np.nansum(pnl))
        std = float(np.nanstd(pnl))
        sharpe = float(np.nanmean(pnl) / std * np.sqrt(252)) if std > 1e-12 else 0.0
        return total_ret, sharpe
