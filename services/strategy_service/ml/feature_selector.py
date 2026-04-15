"""Feature selection pipeline: variance filter → correlation dedup → importance ranking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class SelectionReport:
    original_count: int = 0
    after_variance: int = 0
    after_correlation: int = 0
    final_count: int = 0
    dropped_variance: list[str] = field(default_factory=list)
    dropped_correlation: list[str] = field(default_factory=list)
    feature_ranking: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_count": self.original_count,
            "after_variance": self.after_variance,
            "after_correlation": self.after_correlation,
            "final_count": self.final_count,
            "dropped_variance": self.dropped_variance,
            "dropped_correlation": self.dropped_correlation,
            "feature_ranking": self.feature_ranking[:20],
        }


class FeatureSelector:
    """Three-stage feature selection for timing factor research."""

    def __init__(
        self,
        variance_threshold: float = 1e-6,
        correlation_threshold: float = 0.95,
    ):
        self.variance_threshold = variance_threshold
        self.correlation_threshold = correlation_threshold

    def select(
        self,
        X: pd.DataFrame,
        y: pd.Series | None = None,
    ) -> tuple[pd.DataFrame, SelectionReport]:
        report = SelectionReport(original_count=X.shape[1])

        X_var, dropped_var = self._variance_filter(X)
        report.after_variance = X_var.shape[1]
        report.dropped_variance = dropped_var

        X_corr, dropped_corr = self._correlation_filter(X_var)
        report.after_correlation = X_corr.shape[1]
        report.dropped_correlation = dropped_corr

        ranking = self._importance_ranking(X_corr, y) if y is not None else []
        report.feature_ranking = ranking
        report.final_count = X_corr.shape[1]

        return X_corr, report

    def _variance_filter(self, X: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        variances = X.var()
        low_var = variances[variances < self.variance_threshold].index.tolist()
        return X.drop(columns=low_var), low_var

    def _correlation_filter(self, X: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        if X.shape[1] < 2:
            return X, []
        corr_matrix = X.corr().abs()
        upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape, dtype=bool), k=1))
        to_drop = []
        for col in upper.columns:
            if any(upper[col] > self.correlation_threshold):
                if col not in to_drop:
                    to_drop.append(col)
        return X.drop(columns=to_drop), to_drop

    @staticmethod
    def _importance_ranking(X: pd.DataFrame, y: pd.Series) -> list[dict[str, Any]]:
        aligned = pd.concat([X, y.rename("__target__")], axis=1).dropna()
        if len(aligned) < 30:
            return []
        target = aligned["__target__"]
        features = aligned.drop(columns=["__target__"])

        scores = []
        for col in features.columns:
            ic = features[col].corr(target)
            abs_ic = abs(ic) if not np.isnan(ic) else 0.0
            scores.append({"feature": col, "abs_ic": round(abs_ic, 6), "ic": round(ic, 6) if not np.isnan(ic) else 0.0})

        scores.sort(key=lambda x: x["abs_ic"], reverse=True)
        return scores
