from __future__ import annotations

import numpy as np
import pandas as pd


class FactorValidator:
    @staticmethod
    def validate_factor(factor_values: pd.Series, returns: pd.Series) -> dict:
        aligned = pd.DataFrame({"f": factor_values, "r": returns}).dropna()
        n = len(aligned)
        if n < 10:
            return {
                "ic": float("nan"),
                "ir": float("nan"),
                "turnover": float("nan"),
                "is_valid": False,
            }

        ic = float(aligned["f"].corr(aligned["r"], method="spearman"))

        window = min(60, max(10, n // 5))
        rolling_ics: list[float] = []
        for i in range(window, n + 1):
            sub = aligned.iloc[i - window : i]
            rolling_ics.append(float(sub["f"].corr(sub["r"], method="spearman")))
        ic_roll = pd.Series(rolling_ics)
        ic_std = float(ic_roll.std(ddof=1)) if len(ic_roll) > 1 else 0.0
        ir = float(ic_roll.mean() / (ic_std + 1e-12))

        fstd = float(aligned["f"].std(ddof=1)) or 1e-12
        turnover = float(aligned["f"].diff().abs().mean() / fstd)

        is_valid = (not np.isnan(ic)) and (not np.isnan(ir)) and ic > 0.03 and ir > 0.5
        return {"ic": ic, "ir": ir, "turnover": turnover, "is_valid": bool(is_valid)}
