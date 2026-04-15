"""End-to-end research pipeline: data → factors → labels → select → train → evaluate → signal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.strategy_service.factor_mining.library import FactorLibrary
from .feature_selector import FeatureSelector
from .label_engine import LabelEngine
from .model_walk_forward import ModelWalkForward
from .timing_model import TimingModelTrainer


@dataclass
class PipelineResult:
    symbol: str = ""
    n_rows: int = 0
    n_features_original: int = 0
    n_features_selected: int = 0
    label_col: str = ""
    model_type: str = ""
    selection_report: dict[str, Any] = field(default_factory=dict)
    train_result: dict[str, Any] = field(default_factory=dict)
    walk_forward_result: dict[str, Any] = field(default_factory=dict)
    latest_signal: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "n_rows": self.n_rows,
            "n_features_original": self.n_features_original,
            "n_features_selected": self.n_features_selected,
            "label_col": self.label_col,
            "model_type": self.model_type,
            "selection_report": self.selection_report,
            "train_result": self.train_result,
            "walk_forward_result": self.walk_forward_result,
            "latest_signal": self.latest_signal,
        }


class ResearchPipeline:
    """One-click pipeline: factors → labels → feature select → ML train → WF validate → signal."""

    def run(
        self,
        df: pd.DataFrame,
        symbol: str = "",
        model_type: str = "lightgbm",
        label_col: str = "label_dir_5",
        forward_period: int = 5,
        train_ratio: float = 0.8,
        wf_train_days: int = 200,
        wf_test_days: int = 20,
        wf_step_days: int = 20,
        model_params: dict[str, Any] | None = None,
    ) -> PipelineResult:
        result = PipelineResult(symbol=symbol)

        if df.empty or len(df) < 100:
            logger.warning("Insufficient data for pipeline: {} rows", len(df))
            return result

        factor_df = FactorLibrary.compute_all(df)

        labeled = LabelEngine.generate_all_labels(factor_df, forward_periods=[forward_period])
        result.n_rows = len(labeled)

        base_cols = {"open", "high", "low", "close", "volume", "amount", "turnover"}
        label_cols = set(LabelEngine.label_columns(labeled))
        feature_cols = [c for c in labeled.columns if c not in base_cols and c not in label_cols]
        result.n_features_original = len(feature_cols)

        if label_col not in labeled.columns:
            logger.warning("Label column {} not found", label_col)
            return result

        clean = labeled.dropna(subset=[label_col])
        X_raw = clean[feature_cols].fillna(0)
        y = clean[label_col]
        close = clean["close"]

        selector = FeatureSelector(variance_threshold=1e-6, correlation_threshold=0.92)
        X_selected, sel_report = selector.select(X_raw, y)
        result.n_features_selected = X_selected.shape[1]
        result.selection_report = sel_report.to_dict()
        result.label_col = label_col
        result.model_type = model_type

        split_idx = int(len(X_selected) * train_ratio)
        if split_idx < 60 or len(X_selected) - split_idx < 20:
            logger.warning("Not enough data to split train/test")
            return result

        X_train = X_selected.iloc[:split_idx]
        y_train = y.iloc[:split_idx]
        X_test = X_selected.iloc[split_idx:]
        y_test = y.iloc[split_idx:]

        trainer = TimingModelTrainer()
        try:
            train_res = trainer.train(
                X_train, y_train, X_test, y_test,
                model_type=model_type, symbol=symbol,
                label_col=label_col, params=model_params,
            )
            result.train_result = train_res.to_dict()
        except Exception as e:
            logger.exception("Model training failed: {}", e)
            return result

        wf = ModelWalkForward(
            train_days=wf_train_days,
            test_days=wf_test_days,
            step_days=wf_step_days,
        )
        try:
            wf_res = wf.run(
                X_selected, y, close,
                model_type=model_type, symbol=symbol,
                label_col=label_col, params=model_params,
            )
            result.walk_forward_result = wf_res.to_dict()
        except Exception as e:
            logger.exception("Walk-forward failed: {}", e)

        try:
            pred_res = trainer.predict(
                train_res.model_id,
                X_selected.tail(5),
                dates=X_selected.tail(5).index,
            )
            result.latest_signal = {
                "model_id": pred_res.model_id,
                "predictions": pred_res.predictions,
            }
        except Exception as e:
            logger.warning("Signal generation failed: {}", e)

        return result
