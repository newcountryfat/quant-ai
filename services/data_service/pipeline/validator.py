from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from loguru import logger


@dataclass
class ValidationReport:
    quality_score: float
    issues: list[str] = field(default_factory=list)


class DataValidator:
    def validate(self, df: pd.DataFrame) -> ValidationReport:
        issues: list[str] = []
        score = 1.0

        if df is None or df.empty:
            return ValidationReport(quality_score=0.0, issues=["empty_dataframe"])

        work = df.copy()
        if "trade_date" not in work.columns:
            issues.append("missing_trade_date_column")
            return ValidationReport(quality_score=0.0, issues=issues)

        work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
        if work["trade_date"].isna().any():
            n_bad = int(work["trade_date"].isna().sum())
            issues.append(f"invalid_trade_dates:{n_bad}")
            score -= min(0.4, 0.05 * n_bad)

        price_cols = [c for c in ("open", "high", "low", "close") if c in work.columns]
        if not price_cols:
            issues.append("missing_price_columns")
            score -= 0.5
        else:
            for c in price_cols:
                invalid = (work[c] <= 0) | work[c].isna()
                if invalid.any():
                    n = int(invalid.sum())
                    issues.append(f"non_positive_or_nan_{c}:{n}")
                    score -= min(0.2, 0.02 * n)

            if {"high", "low"}.issubset(work.columns):
                bad_hl = work["high"] < work["low"]
                if bad_hl.any():
                    n = int(bad_hl.sum())
                    issues.append(f"high_less_than_low:{n}")
                    score -= min(0.25, 0.03 * n)

            if {"high", "low", "close", "open"}.issubset(work.columns):
                outside = (
                    (work["close"] > work["high"])
                    | (work["close"] < work["low"])
                    | (work["open"] > work["high"])
                    | (work["open"] < work["low"])
                )
                if outside.any():
                    n = int(outside.sum())
                    issues.append(f"ohlc_inconsistency:{n}")
                    score -= min(0.2, 0.02 * n)

        num_cols = [c for c in ("open", "high", "low", "close", "volume") if c in work.columns]
        if num_cols:
            total_cells = len(work) * len(num_cols)
            missing = int(work[num_cols].isna().sum().sum())
            if missing:
                ratio = missing / max(total_cells, 1)
                issues.append(f"missing_values:{missing}")
                score -= min(0.35, ratio * 2.0)

        if "close" in work.columns and len(work) >= 10:
            s = work["close"].dropna()
            if len(s) >= 10:
                q1, q3 = s.quantile([0.25, 0.75])
                iqr = q3 - q1
                if iqr and iqr > 0:
                    lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
                    out = (work["close"] < lo) | (work["close"] > hi)
                    if out.any():
                        n = int(out.sum())
                        issues.append(f"close_outliers_iqr:{n}")
                        score -= min(0.2, 0.01 * n)

        work = work.sort_values("trade_date")
        dates = work["trade_date"].dropna().dt.normalize().unique()
        if len(dates) >= 2:
            deltas = np.diff(np.sort(dates.astype("datetime64[ns]")))
            max_gap = int(deltas.max() / np.timedelta64(1, "D"))
            if max_gap > 7:
                issues.append(f"large_calendar_gap_days:{max_gap}")
                score -= min(0.15, 0.01 * (max_gap - 7))

        score = float(max(0.0, min(1.0, score)))
        if score < 0.5 and not issues:
            issues.append("low_quality_unspecified")
        logger.debug("validation quality_score={} issues={}", score, issues)
        return ValidationReport(quality_score=score, issues=issues)
