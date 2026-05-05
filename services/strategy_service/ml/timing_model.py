"""Timing model training & prediction — Lasso + LightGBM."""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger


LIGHTGBM_INSTALL_HINT = (
    "lightgbm is required for model_type='lightgbm'. "
    "Install dependencies with `pip install -r requirements.txt` "
    "or switch model_type to 'lasso'."
)


@dataclass
class ModelMetrics:
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    auc: float = 0.0
    log_loss: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {k: round(v, 6) for k, v in self.__dict__.items()}


@dataclass
class TrainResult:
    model_id: str = ""
    model_type: str = ""
    symbol: str = ""
    label_col: str = ""
    n_features: int = 0
    n_train: int = 0
    n_test: int = 0
    train_metrics: ModelMetrics = field(default_factory=ModelMetrics)
    test_metrics: ModelMetrics = field(default_factory=ModelMetrics)
    feature_importance: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_type": self.model_type,
            "symbol": self.symbol,
            "label_col": self.label_col,
            "n_features": self.n_features,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "train_metrics": self.train_metrics.to_dict(),
            "test_metrics": self.test_metrics.to_dict(),
            "feature_importance": self.feature_importance[:20],
            "created_at": self.created_at,
        }


@dataclass
class PredictResult:
    model_id: str = ""
    symbol: str = ""
    predictions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "symbol": self.symbol,
            "count": len(self.predictions),
            "predictions": self.predictions,
        }


def _compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, y_prob: np.ndarray | None = None) -> ModelMetrics:
    from sklearn.metrics import accuracy_score, f1_score, log_loss, precision_score, recall_score, roc_auc_score
    m = ModelMetrics()
    m.accuracy = float(accuracy_score(y_true, y_pred))
    m.precision = float(precision_score(y_true, y_pred, zero_division=0))
    m.recall = float(recall_score(y_true, y_pred, zero_division=0))
    m.f1 = float(f1_score(y_true, y_pred, zero_division=0))
    if y_prob is not None and len(np.unique(y_true)) > 1:
        try:
            m.auc = float(roc_auc_score(y_true, y_prob))
        except ValueError:
            m.auc = 0.0
        try:
            m.log_loss = float(log_loss(y_true, y_prob))
        except ValueError:
            m.log_loss = 0.0
    return m


def ensure_lightgbm_available() -> Any:
    try:
        import lightgbm as lgb
    except ModuleNotFoundError as exc:
        raise RuntimeError(LIGHTGBM_INSTALL_HINT) from exc
    return lgb


class TimingModelTrainer:
    """Train Lasso or LightGBM binary classifiers for index/ETF timing."""

    SUPPORTED_TYPES = ("lasso", "lightgbm")

    def __init__(self, model_dir: Path | str = "data/models"):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        model_type: str = "lightgbm",
        symbol: str = "",
        label_col: str = "",
        params: dict[str, Any] | None = None,
    ) -> TrainResult:
        if model_type not in self.SUPPORTED_TYPES:
            raise ValueError(f"model_type must be one of {self.SUPPORTED_TYPES}")

        model_id = f"{model_type}_{symbol}_{label_col}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if model_type == "lasso":
            model, importance = self._train_lasso(X_train, y_train, params)
        else:
            model, importance = self._train_lightgbm(X_train, y_train, params)

        y_pred_train = model.predict(X_train)
        y_pred_test = model.predict(X_test)

        y_prob_train = self._predict_proba(model, X_train)
        y_prob_test = self._predict_proba(model, X_test)

        train_m = _compute_metrics(y_train.values, y_pred_train, y_prob_train)
        test_m = _compute_metrics(y_test.values, y_pred_test, y_prob_test)

        model_path = self.model_dir / f"{model_id}.pkl"
        with open(model_path, "wb") as f:
            pickle.dump({"model": model, "features": list(X_train.columns), "model_type": model_type}, f)

        meta_path = self.model_dir / f"{model_id}.json"
        result = TrainResult(
            model_id=model_id,
            model_type=model_type,
            symbol=symbol,
            label_col=label_col,
            n_features=X_train.shape[1],
            n_train=len(X_train),
            n_test=len(X_test),
            train_metrics=train_m,
            test_metrics=test_m,
            feature_importance=importance,
            created_at=datetime.now().isoformat(),
        )
        with open(meta_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info("Model {} trained — test acc={:.4f} f1={:.4f} auc={:.4f}",
                     model_id, test_m.accuracy, test_m.f1, test_m.auc)
        return result

    def predict(
        self,
        model_id: str,
        X: pd.DataFrame,
        dates: pd.Index | None = None,
    ) -> PredictResult:
        model_path = self.model_dir / f"{model_id}.pkl"
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")
        with open(model_path, "rb") as f:
            bundle = pickle.load(f)
        model = bundle["model"]
        features = bundle["features"]

        X_aligned = X.reindex(columns=features, fill_value=0)
        y_pred = model.predict(X_aligned)
        y_prob = self._predict_proba(model, X_aligned)

        preds = []
        for i in range(len(X_aligned)):
            d = str(dates[i])[:10] if dates is not None else str(i)
            entry: dict[str, Any] = {
                "date": d,
                "prediction": int(y_pred[i]),
                "probability": round(float(y_prob[i]), 6) if y_prob is not None else None,
            }
            preds.append(entry)

        return PredictResult(model_id=model_id, symbol="", predictions=preds)

    def list_models(self) -> list[dict[str, Any]]:
        models = []
        for p in sorted(self.model_dir.glob("*.json")):
            try:
                with open(p) as f:
                    meta = json.load(f)
                if meta.get("type") == "gp_expression":
                    continue
                models.append(meta)
            except Exception:
                continue
        return models

    def delete_model(self, model_id: str) -> bool:
        deleted = False
        for ext in (".json", ".pkl"):
            p = self.model_dir / f"{model_id}{ext}"
            if p.exists():
                p.unlink()
                deleted = True
        return deleted

    # ---------- internal ----------

    @staticmethod
    def _train_lasso(X: pd.DataFrame, y: pd.Series, params: dict | None) -> tuple[Any, list[dict]]:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        p = params or {}
        C = p.get("C", 1.0)
        clf = LogisticRegression(penalty="l1", C=C, solver="saga", max_iter=2000, random_state=42)
        clf.fit(X_scaled, y)

        from sklearn.pipeline import Pipeline
        pipe = Pipeline([("scaler", scaler), ("clf", clf)])

        coefs = clf.coef_.flatten()
        importance = [
            {"feature": col, "importance": round(abs(float(c)), 6), "coef": round(float(c), 6)}
            for col, c in zip(X.columns, coefs)
        ]
        importance.sort(key=lambda x: x["importance"], reverse=True)
        return pipe, importance

    @staticmethod
    def _train_lightgbm(X: pd.DataFrame, y: pd.Series, params: dict | None) -> tuple[Any, list[dict]]:
        lgb = ensure_lightgbm_available()

        default_p = {
            "objective": "binary",
            "metric": "binary_logloss",
            "verbosity": -1,
            "n_estimators": 200,
            "max_depth": 5,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_samples": 20,
            "random_state": 42,
        }
        if params:
            default_p.update(params)

        clf = lgb.LGBMClassifier(**default_p)
        clf.fit(X, y)

        feat_imp = clf.feature_importances_
        importance = [
            {"feature": col, "importance": int(imp)}
            for col, imp in zip(X.columns, feat_imp)
        ]
        importance.sort(key=lambda x: x["importance"], reverse=True)
        return clf, importance

    @staticmethod
    def _predict_proba(model: Any, X: pd.DataFrame) -> np.ndarray | None:
        try:
            probs = model.predict_proba(X)
            return probs[:, 1] if probs.ndim == 2 else probs
        except Exception:
            return None
