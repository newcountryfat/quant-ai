from __future__ import annotations

from typing import Any

from loguru import logger

from core.event_bus import Event, LocalEventBus


class RiskService:
    class RISK_THRESHOLDS:
        max_drawdown: float = 0.15
        var_95: float = 0.05
        concentration: float = 0.10
        single_stock_limit: float = 0.05

    def __init__(self, bus: LocalEventBus) -> None:
        self._bus = bus

    async def start(self) -> None:
        try:
            self._bus.on("strategy.signal", self._on_strategy_signal)
            logger.info("RiskService subscribed to strategy.signal")
        except Exception:
            logger.exception("RiskService.start failed")

    async def _on_strategy_signal(self, event: Event) -> None:
        try:
            sig = event.payload.get("signal", event.payload)
            if not isinstance(sig, dict):
                return
            await self.evaluate_signal(sig)
        except Exception:
            logger.exception("RiskService strategy.signal handler failed")

    async def check_position_risk(
        self,
        portfolio: dict[str, Any],
        *,
        emit_alert: bool = True,
    ) -> dict[str, Any]:
        violations: list[str] = []
        try:
            weights = portfolio.get("weights")
            if weights is None and isinstance(portfolio.get("positions"), dict):
                weights = portfolio["positions"]
            if not isinstance(weights, dict):
                return {"passed": True, "violations": []}

            lim_single = float(self.RISK_THRESHOLDS.single_stock_limit)
            lim_conc = float(self.RISK_THRESHOLDS.concentration)

            abs_weights = {k: abs(float(v)) for k, v in weights.items() if isinstance(v, (int, float))}
            for sym, w in abs_weights.items():
                if w > lim_single + 1e-9:
                    violations.append(f"{sym} weight {w:.4f} exceeds single_stock_limit {lim_single}")

            if abs_weights:
                top = max(abs_weights.values())
                if top > lim_conc + 1e-9:
                    violations.append(
                        f"largest position {top:.4f} exceeds concentration limit {lim_conc}"
                    )

            total_abs = sum(abs_weights.values())
            if total_abs > 1.0 + 1e-6:
                violations.append(f"absolute weights sum {total_abs:.4f} exceeds 1.0")

            passed = len(violations) == 0
            if not passed and emit_alert:
                await self._bus.publish(
                    "risk.alert",
                    {
                        "level": "high",
                        "source": "risk_service",
                        "message": "position risk violations",
                        "violations": violations,
                        "portfolio": portfolio,
                    },
                )
            return {"passed": passed, "violations": violations}
        except Exception:
            logger.exception("check_position_risk failed")
            return {"passed": False, "violations": ["check_position_risk error"]}

    async def check_drawdown(
        self,
        equity_curve: list[Any],
        *,
        emit_alert: bool = True,
    ) -> dict[str, Any]:
        try:
            series = _normalize_equity_series(equity_curve)
            if len(series) < 2:
                return {"current_dd": 0.0, "max_dd": 0.0, "breached": False}

            peak = series[0]
            max_dd = 0.0
            for x in series:
                peak = max(peak, x)
                if peak > 0:
                    dd = (peak - x) / peak
                    max_dd = max(max_dd, dd)

            peak = max(series)
            last = series[-1]
            current_dd = (peak - last) / peak if peak > 0 else 0.0
            breached = max_dd > float(self.RISK_THRESHOLDS.max_drawdown) + 1e-9

            if breached and emit_alert:
                await self._bus.publish(
                    "risk.alert",
                    {
                        "level": "critical",
                        "source": "risk_service",
                        "message": "max drawdown threshold breached",
                        "current_dd": current_dd,
                        "max_dd": max_dd,
                        "threshold": self.RISK_THRESHOLDS.max_drawdown,
                    },
                )

            return {
                "current_dd": round(float(current_dd), 6),
                "max_dd": round(float(max_dd), 6),
                "breached": breached,
            }
        except Exception:
            logger.exception("check_drawdown failed")
            return {"current_dd": 0.0, "max_dd": 0.0, "breached": False}

    async def evaluate_signal(self, signal: dict[str, Any]) -> dict[str, Any]:
        try:
            violations: list[str] = []

            w = signal.get("weight") or signal.get("target_weight")
            if isinstance(w, (int, float)):
                if abs(float(w)) > float(self.RISK_THRESHOLDS.single_stock_limit) + 1e-9:
                    violations.append("signal weight exceeds single_stock_limit")

            if "var_95" in signal and isinstance(signal["var_95"], (int, float)):
                if float(signal["var_95"]) > float(self.RISK_THRESHOLDS.var_95) + 1e-9:
                    violations.append("signal var_95 exceeds threshold")

            portfolio = signal.get("portfolio") or signal.get("post_trade_portfolio")
            if isinstance(portfolio, dict):
                pr = await self.check_position_risk(portfolio, emit_alert=False)
                if not pr.get("passed", True):
                    violations.extend(pr.get("violations", []))

            equity = signal.get("equity_curve")
            if isinstance(equity, list) and len(equity) >= 2:
                dd_info = await self.check_drawdown(equity, emit_alert=False)
                if dd_info.get("breached"):
                    violations.append("equity drawdown breached threshold")

            if violations:
                reason = "; ".join(violations)
                await self._bus.publish(
                    "risk.alert",
                    {
                        "level": "warning",
                        "source": "risk_service",
                        "message": reason,
                        "violations": violations,
                        "signal": signal,
                    },
                )
                return {"approved": False, "reason": reason}

            return {"approved": True, "reason": "ok"}
        except Exception:
            logger.exception("evaluate_signal failed")
            return {"approved": False, "reason": "evaluate_signal error"}


def _normalize_equity_series(equity_curve: list[Any]) -> list[float]:
    out: list[float] = []
    for item in equity_curve:
        if isinstance(item, (int, float)):
            out.append(float(item))
        elif isinstance(item, dict):
            v = item.get("equity") or item.get("nav") or item.get("value")
            if isinstance(v, (int, float)):
                out.append(float(v))
    return out
