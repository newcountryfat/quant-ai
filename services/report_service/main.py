from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from core.config import settings
from core.db import get_db
from core.event_bus import Event, LocalEventBus
from services.data_service.research_universe import DEFAULT_ETF_CODES, DEFAULT_INDEX_CODES


def _df_to_md(df: pd.DataFrame) -> str:
    if df.empty:
        return "_empty_\n"
    cols = [str(c) for c in df.columns]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body_lines = []
    for _, row in df.iterrows():
        cells = ["" if pd.isna(row[c]) else str(row[c]) for c in df.columns]
        body_lines.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep, *body_lines]) + "\n"


def _safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


class ReportService:
    def __init__(self, bus: LocalEventBus, data_svc=None, strategy_svc=None, monitor_svc=None) -> None:
        self._bus = bus
        self._data_svc = data_svc
        self._strategy_svc = strategy_svc
        self._monitor_svc = monitor_svc

    def _reports_dir(self) -> Path:
        d = settings.data_dir / "reports"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.exception("failed to create reports dir")
        return d

    async def start(self) -> None:
        try:
            self._bus.on("report.daily", self._on_report_daily)
            logger.info("ReportService subscribed to report.daily")
        except Exception:
            logger.exception("ReportService.start failed")

    async def _on_report_daily(self, event: Event) -> None:
        try:
            await self.generate_daily_report()
        except Exception:
            logger.exception("report.daily handler failed")

    def _quote_refresh_start(self, symbol: str) -> str:
        with get_db() as conn:
            row = conn.execute(
                "SELECT MAX(trade_date) AS max_date FROM daily_quotes WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        if row and row["max_date"]:
            dt = datetime.fromisoformat(str(row["max_date"]))
            return (dt - timedelta(days=180)).date().isoformat()
        return (datetime.now() - timedelta(days=365)).date().isoformat()

    def _auto_refresh_allowed_symbols(self, symbols: list[str]) -> set[str]:
        if not symbols:
            return set()
        placeholders = ",".join("?" for _ in symbols)
        with get_db() as conn:
            watchlist_rows = conn.execute(
                f"SELECT symbol FROM watchlist WHERE symbol IN ({placeholders})",
                symbols,
            ).fetchall()
            asset_rows = conn.execute(
                f"SELECT symbol, asset_type FROM asset_universe WHERE symbol IN ({placeholders})",
                symbols,
            ).fetchall()

        watchlist_symbols = {row["symbol"] for row in watchlist_rows}
        asset_type_map = {row["symbol"]: row["asset_type"] for row in asset_rows}
        allowed: set[str] = set()
        for symbol in symbols:
            asset_type = asset_type_map.get(symbol)
            if asset_type in {"index", "etf"}:
                if symbol in watchlist_symbols:
                    allowed.add(symbol)
                continue
            allowed.add(symbol)
        return allowed

    async def _refresh_symbols(self, symbols: list[str]) -> None:
        if self._data_svc is None:
            return
        allowed_symbols = self._auto_refresh_allowed_symbols(symbols)
        skipped_symbols = [symbol for symbol in symbols if symbol not in allowed_symbols]
        if skipped_symbols:
            logger.info(
                "dashboard auto refresh skipped non-watchlist index/etf symbols={}",
                skipped_symbols,
            )
        for symbol in sorted(allowed_symbols):
            try:
                await self._data_svc.update_daily_data(
                    symbol,
                    self._quote_refresh_start(symbol),
                    datetime.now().date().isoformat(),
                )
            except Exception:
                logger.exception("dashboard refresh failed symbol={}", symbol)

    def _latest_quote_map(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if not symbols:
            return {}
        placeholders = ",".join("?" for _ in symbols)
        sql = (
            "SELECT q.symbol, q.trade_date, q.close "
            "FROM daily_quotes q "
            "JOIN (SELECT symbol, MAX(trade_date) AS max_date FROM daily_quotes "
            f"WHERE symbol IN ({placeholders}) GROUP BY symbol) x "
            "ON q.symbol = x.symbol AND q.trade_date = x.max_date"
        )
        with get_db() as conn:
            rows = conn.execute(sql, symbols).fetchall()
        return {
            r["symbol"]: {
                "trade_date": r["trade_date"],
                "close": _safe_float(r["close"]),
            }
            for r in rows
        }

    def _symbol_name_map(self, symbols: list[str]) -> dict[str, str]:
        if not symbols:
            return {}
        placeholders = ",".join("?" for _ in symbols)
        builtin_name_map = {code: name for code, name in (DEFAULT_INDEX_CODES + DEFAULT_ETF_CODES)}
        with get_db() as conn:
            watchlist_rows = conn.execute(
                f"SELECT symbol FROM watchlist WHERE symbol IN ({placeholders})",
                symbols,
            ).fetchall()
            asset_rows = conn.execute(
                f"SELECT symbol, name FROM asset_universe WHERE symbol IN ({placeholders})",
                symbols,
            ).fetchall()
            stock_rows = conn.execute(
                f"SELECT symbol, name FROM stocks WHERE symbol IN ({placeholders})",
                symbols,
            ).fetchall()
        watchlist_symbols = {row["symbol"] for row in watchlist_rows}
        out: dict[str, str] = {}
        for row in stock_rows:
            if row["name"]:
                out[row["symbol"]] = row["name"]
        for row in asset_rows:
            if row["name"]:
                out[row["symbol"]] = row["name"]
        for symbol in symbols:
            if symbol in watchlist_symbols and builtin_name_map.get(symbol):
                out[symbol] = builtin_name_map[symbol]
        return out

    def _normalize_action(self, position: int | None, prev_position: int | None = None) -> str:
        if position is None:
            return "无数据"
        if prev_position is None:
            return "买入" if position > 0 else "继续空仓"
        if position > prev_position:
            return "买入"
        if position < prev_position:
            return "卖出"
        return "继续持仓" if position > 0 else "继续空仓"

    def _position_from_ml_prediction(self, prediction: Any) -> int | None:
        if prediction is None:
            return None
        return 1 if int(prediction) == 1 else 0

    def _position_from_direction(self, direction: Any) -> int | None:
        if direction is None:
            return None
        return 1 if int(direction) > 0 else 0

    def _action_reason(self, position: int | None, prev_position: int | None = None) -> str:
        if position is None:
            return "缺少足够信号，暂时无法判断目标仓位。"
        if prev_position is None:
            return "这是当前窗口里的首个可用信号，先按今天建议的目标仓位解释。"
        if position > prev_position:
            return "昨天还是空仓，今天模型转为建议持仓，因此给出买入。"
        if position < prev_position:
            return "昨天建议持仓，今天模型转为建议空仓，因此给出卖出。"
        if position > 0:
            return "昨天和今天都建议持仓，所以不切换动作，继续持仓。"
        return "昨天和今天都建议空仓，所以不切换动作，继续空仓。"

    def _signal_window_start(self, latest_trade_date: str | None) -> str:
        if latest_trade_date:
            dt = datetime.fromisoformat(str(latest_trade_date))
            return (dt - timedelta(days=220)).date().isoformat()
        return (datetime.now() - timedelta(days=365)).date().isoformat()

    def _persist_strategy_snapshots(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with get_db() as conn:
            conn.executemany(
                """
                INSERT INTO strategy_daily_snapshots (
                    strategy_key, strategy_name, strategy_type, symbol, snapshot_date,
                    action, signal_value, probability, latest_price, latest_trade_date,
                    meta_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_key, symbol, snapshot_date) DO UPDATE SET
                    strategy_name = excluded.strategy_name,
                    strategy_type = excluded.strategy_type,
                    action = excluded.action,
                    signal_value = excluded.signal_value,
                    probability = excluded.probability,
                    latest_price = excluded.latest_price,
                    latest_trade_date = excluded.latest_trade_date,
                    meta_json = excluded.meta_json,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        row["strategy_key"],
                        row["strategy_name"],
                        row["strategy_type"],
                        row["symbol"],
                        row["snapshot_date"],
                        row["action"],
                        row.get("signal_value"),
                        row.get("probability"),
                        row.get("latest_price"),
                        row.get("latest_trade_date"),
                        json.dumps(row.get("meta", {}), ensure_ascii=False),
                        datetime.now().isoformat(),
                        datetime.now().isoformat(),
                    )
                    for row in rows
                ],
            )

    def _recent_alerts(self, limit: int = 10) -> list[dict[str, Any]]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT level, source, message, resolved, created_at
                FROM alerts
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _build_report_summary_cards(
        self,
        summary: dict[str, Any],
        snapshots: list[dict[str, Any]],
        generated_at: str,
    ) -> list[dict[str, str]]:
        daily_range = "暂无数据"
        if summary.get("daily_quote_min_date") and summary.get("daily_quote_max_date"):
            daily_range = f"{summary['daily_quote_min_date']} 至 {summary['daily_quote_max_date']}"
        breadth_range = "暂无数据"
        if summary.get("breadth_min_date") and summary.get("breadth_max_date"):
            breadth_range = f"{summary['breadth_min_date']} 至 {summary['breadth_max_date']}"
        return [
            {"label": "报告时间", "value": generated_at, "subtext": "基于最新可得数据生成"},
            {
                "label": "行情覆盖",
                "value": f"{summary.get('daily_quote_symbols', 0)} 个标的",
                "subtext": daily_range,
            },
            {
                "label": "收藏策略",
                "value": f"{len(snapshots)} 个",
                "subtext": f"自选 {summary.get('watchlist_total', 0)} 个",
            },
            {
                "label": "回测记录",
                "value": str(summary.get("backtests_total", 0)),
                "subtext": f"活跃策略 {summary.get('strategies_active', 0)} 个",
            },
            {
                "label": "市场宽度",
                "value": f"{summary.get('breadth_rows', 0)} 条",
                "subtext": breadth_range,
            },
            {
                "label": "风险提示",
                "value": f"{summary.get('alerts_unresolved', 0)} 条未解决",
                "subtext": f"累计告警 {summary.get('alerts_total', 0)} 条",
            },
        ]

    def _build_strategy_groups(self, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in snapshots:
            grouped.setdefault(item["symbol"], []).append(item)

        groups: list[dict[str, Any]] = []
        for symbol, rows in sorted(grouped.items(), key=lambda x: x[0]):
            normalized_rows = []
            dates = []
            for row in rows:
                signal_date = row.get("snapshot_date") or row.get("latest_trade_date") or "--"
                if signal_date and signal_date != "--":
                    dates.append(signal_date)
                normalized_rows.append(
                    {
                        "strategy_name": row.get("strategy_name", "--"),
                        "strategy_type": row.get("strategy_type", "--"),
                        "action": row.get("action", "无数据"),
                        "action_reason": row.get("action_reason", ""),
                        "signal_date": signal_date,
                        "signal_value": row.get("signal_value"),
                        "probability": row.get("probability"),
                        "latest_price": row.get("latest_price"),
                        "latest_trade_date": row.get("latest_trade_date") or "--",
                    }
                )
            latest_signal_date = max(dates) if dates else "--"
            groups.append(
                {
                    "symbol": symbol,
                    "symbol_name": rows[0].get("symbol_name") or symbol,
                    "strategy_count": len(normalized_rows),
                    "latest_signal_date": latest_signal_date,
                    "rows": normalized_rows,
                }
            )
        return groups

    async def build_daily_report_payload(self, refresh_data: bool = True) -> dict[str, Any]:
        overview = await self.build_dashboard_overview(refresh_data=refresh_data)
        summary = overview["summary"]
        snapshots = overview["saved_strategies"]
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        alerts = self._recent_alerts(limit=10)
        return {
            "generated_at": generated_at,
            "headline": "每日报告",
            "subheadline": "摘要卡片、按标的归类的策略建议，以及最近风险提示",
            "summary_cards": self._build_report_summary_cards(summary, snapshots, generated_at),
            "strategy_groups": self._build_strategy_groups(snapshots),
            "risk": {
                "unresolved_count": summary.get("alerts_unresolved", 0),
                "total_count": summary.get("alerts_total", 0),
                "items": alerts,
            },
        }

    async def collect_strategy_snapshots(
        self,
        refresh_data: bool = True,
        persist: bool = True,
    ) -> list[dict[str, Any]]:
        if self._strategy_svc is None:
            return []

        models = await self._strategy_svc.list_models()
        gp_exprs = await self._strategy_svc.gp_list()
        items = [
            {
                "strategy_key": m["model_id"],
                "strategy_name": m["model_id"],
                "strategy_type": m.get("model_type", "ml"),
                "symbol": m.get("symbol", ""),
                "meta": m,
            }
            for m in models
            if m.get("symbol")
        ] + [
            {
                "strategy_key": g["gp_id"],
                "strategy_name": g["gp_id"],
                "strategy_type": "gp",
                "symbol": g.get("symbol", ""),
                "meta": g,
            }
            for g in gp_exprs
            if g.get("symbol")
        ]

        symbols = sorted({item["symbol"] for item in items if item["symbol"]})
        if refresh_data:
            await self._refresh_symbols(symbols)
        latest_quotes = self._latest_quote_map(symbols)
        symbol_names = self._symbol_name_map(symbols)

        snapshots: list[dict[str, Any]] = []
        for item in items:
            symbol = item["symbol"]
            quote = latest_quotes.get(symbol, {})
            latest_trade_date = quote.get("trade_date")
            start = self._signal_window_start(latest_trade_date)
            end = latest_trade_date or datetime.now().date().isoformat()
            try:
                if item["strategy_type"] == "gp":
                    payload = await self._strategy_svc.gp_predict(
                        gp_id=item["strategy_key"],
                        symbol=symbol,
                        start=start,
                        end=end,
                    )
                    preds = payload.get("predictions") or []
                    latest = preds[-1] if preds else {}
                    prev = preds[-2] if len(preds) >= 2 else None
                    current_position = self._position_from_direction(latest.get("direction"))
                    prev_position = self._position_from_direction(prev.get("direction")) if prev else None
                    signal_value = _safe_float(latest.get("signal"))
                    probability = None
                else:
                    payload = await self._strategy_svc.predict_signal(
                        model_id=item["strategy_key"],
                        symbol=symbol,
                        start=start,
                        end=end,
                    )
                    preds = payload.get("predictions") or []
                    latest = preds[-1] if preds else {}
                    prev = preds[-2] if len(preds) >= 2 else None
                    current_position = self._position_from_ml_prediction(latest.get("prediction"))
                    prev_position = self._position_from_ml_prediction(prev.get("prediction")) if prev else None
                    probability = _safe_float(latest.get("probability"))
                    signal_value = probability

                snapshot_date = latest.get("date") or latest_trade_date or datetime.now().date().isoformat()
                snapshots.append(
                    {
                        "strategy_key": item["strategy_key"],
                        "strategy_name": item["strategy_name"],
                        "strategy_type": item["strategy_type"],
                        "symbol": symbol,
                        "symbol_name": symbol_names.get(symbol, symbol),
                        "snapshot_date": snapshot_date,
                        "action": self._normalize_action(current_position, prev_position),
                        "action_reason": self._action_reason(current_position, prev_position),
                        "signal_value": signal_value,
                        "probability": probability,
                        "latest_price": quote.get("close"),
                        "latest_trade_date": latest_trade_date,
                        "meta": item["meta"],
                    }
                )
            except Exception as exc:
                logger.exception("collect strategy snapshot failed key={}", item["strategy_key"])
                snapshots.append(
                    {
                        "strategy_key": item["strategy_key"],
                        "strategy_name": item["strategy_name"],
                        "strategy_type": item["strategy_type"],
                        "symbol": symbol,
                        "symbol_name": symbol_names.get(symbol, symbol),
                        "snapshot_date": latest_trade_date or datetime.now().date().isoformat(),
                        "action": "无数据",
                        "action_reason": "信号计算失败，暂时无法生成动作原因。",
                        "signal_value": None,
                        "probability": None,
                        "latest_price": quote.get("close"),
                        "latest_trade_date": latest_trade_date,
                        "meta": {**item["meta"], "error": str(exc)},
                    }
                )

        snapshots.sort(key=lambda x: (x["snapshot_date"], x["strategy_type"], x["strategy_name"]), reverse=True)
        if persist:
            self._persist_strategy_snapshots(snapshots)
        return snapshots

    def _query_platform_summary(self) -> dict[str, Any]:
        with get_db() as conn:
            stocks_total = conn.execute("SELECT COUNT(*) AS c FROM stocks").fetchone()["c"]
            quote_stats = conn.execute(
                "SELECT COUNT(DISTINCT symbol) AS symbols, COUNT(*) AS rows, "
                "MIN(trade_date) AS min_date, MAX(trade_date) AS max_date FROM daily_quotes"
            ).fetchone()
            universe_counts = conn.execute(
                "SELECT asset_type, COUNT(*) AS c FROM asset_universe GROUP BY asset_type"
            ).fetchall()
            factor_val_stats = conn.execute(
                "SELECT COUNT(DISTINCT symbol) AS symbols, COUNT(*) AS rows FROM factor_values"
            ).fetchone()
            eval_stats = conn.execute("SELECT COUNT(*) AS c FROM factor_eval_results").fetchone()
            strategy_stats = conn.execute(
                "SELECT COUNT(*) AS total, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active FROM strategies"
            ).fetchone()
            backtest_stats = conn.execute("SELECT COUNT(*) AS total FROM backtest_results").fetchone()
            watchlist_stats = conn.execute("SELECT COUNT(*) AS total FROM watchlist").fetchone()
            breadth_stats = conn.execute(
                "SELECT COUNT(*) AS rows, MIN(trade_date) AS min_date, MAX(trade_date) AS max_date FROM market_breadth_features"
            ).fetchone()
            alert_stats = conn.execute(
                "SELECT COUNT(*) AS total, SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) AS unresolved FROM alerts"
            ).fetchone()
            job_total = conn.execute("SELECT COUNT(*) AS total FROM job_logs").fetchone()
        return {
            "stocks_total": stocks_total,
            "daily_quote_symbols": quote_stats["symbols"] or 0,
            "daily_quote_rows": quote_stats["rows"] or 0,
            "daily_quote_min_date": quote_stats["min_date"],
            "daily_quote_max_date": quote_stats["max_date"],
            "asset_universe": {r["asset_type"]: r["c"] for r in universe_counts},
            "factor_value_symbols": factor_val_stats["symbols"] or 0,
            "factor_value_rows": factor_val_stats["rows"] or 0,
            "factor_eval_total": eval_stats["c"] or 0,
            "strategies_total": strategy_stats["total"] or 0,
            "strategies_active": strategy_stats["active"] or 0,
            "backtests_total": backtest_stats["total"] or 0,
            "watchlist_total": watchlist_stats["total"] or 0,
            "breadth_rows": breadth_stats["rows"] or 0,
            "breadth_min_date": breadth_stats["min_date"],
            "breadth_max_date": breadth_stats["max_date"],
            "alerts_total": alert_stats["total"] or 0,
            "alerts_unresolved": alert_stats["unresolved"] or 0,
            "job_logs_total": job_total["total"] or 0,
        }

    async def build_dashboard_overview(self, refresh_data: bool = True) -> dict[str, Any]:
        health = {"cpu_percent": 0.0, "memory_percent": 0.0, "disk_percent": 0.0}
        if self._monitor_svc is not None:
            health = await self._monitor_svc.check_system_health()
        summary = self._query_platform_summary()
        snapshots = await self.collect_strategy_snapshots(refresh_data=refresh_data, persist=True)
        return {
            "generated_at": datetime.now().isoformat(),
            "health": health,
            "services": {
                "data_service": self._data_svc is not None,
                "strategy_service": self._strategy_svc is not None,
                "monitor_service": self._monitor_svc is not None,
                "report_service": True,
            },
            "summary": summary,
            "saved_strategies": snapshots,
        }

    async def generate_daily_report(self) -> str:
        try:
            payload = await self.build_daily_report_payload(refresh_data=True)
            lines: list[str] = []
            lines.append(f"# 每日报告 — {payload['generated_at']}\n")
            lines.append("## 摘要\n")
            for card in payload["summary_cards"]:
                lines.append(f"- {card['label']}: **{card['value']}**；{card['subtext']}\n")

            lines.append("\n## 下一交易日操作建议\n")
            if not payload["strategy_groups"]:
                lines.append("- 暂无已保存模型或 GP 表达式。\n")
            else:
                for group in payload["strategy_groups"]:
                    lines.append(f"### {group['symbol']}（{group['strategy_count']} 个策略）\n")
                    df = pd.DataFrame(group["rows"])
                    lines.append(_df_to_md(df))
                    lines.append("\n")

            lines.append("\n## 风险提示\n")
            alerts = payload["risk"]["items"]
            if not alerts:
                lines.append("- 当前没有最近风险告警。\n")
            else:
                alert_df = pd.DataFrame(alerts)
                lines.append(_df_to_md(alert_df))
                lines.append("\n")

            md = "\n".join(lines)
            path = self._reports_dir() / f"daily_report_{datetime.now():%Y%m%d_%H%M}.md"
            try:
                path.write_text(md, encoding="utf-8")
                logger.info("Daily report saved {}", path)
            except Exception:
                logger.exception("failed to write daily report file")
            return md
        except Exception:
            logger.exception("generate_daily_report failed")
            return "# Daily report\n\n_Generation failed._\n"

    async def generate_backtest_report(self, backtest_result: dict[str, Any]) -> str:
        try:
            lines: list[str] = ["# Backtest report\n"]
            sid = backtest_result.get("strategy_id", "—")
            lines.append(f"- Strategy: `{sid}`\n")

            metrics_keys = [
                "start_date",
                "end_date",
                "initial_capital",
                "final_capital",
                "total_return",
                "annual_return",
                "sharpe",
                "max_dd",
                "win_rate",
                "trade_count",
            ]
            rows = []
            for k in metrics_keys:
                if k in backtest_result:
                    rows.append({"metric": k, "value": backtest_result[k]})
            if rows:
                df = pd.DataFrame(rows)
                lines.append("\n## Metrics\n")
                lines.append(_df_to_md(df))
                lines.append("\n")

            trades = backtest_result.get("trades")
            if isinstance(trades, list) and trades:
                tdf = pd.DataFrame(trades)
                lines.append("\n## Trades (sample)\n")
                lines.append(_df_to_md(tdf.head(50)))
                lines.append("\n")
            else:
                lines.append("\n## Trade summary\n")
                lines.append("- No per-trade rows supplied.\n")

            summary = backtest_result.get("summary")
            if isinstance(summary, str) and summary.strip():
                lines.append("\n## Notes\n")
                lines.append(summary.strip() + "\n")

            md = "\n".join(lines)
            safe_sid = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(sid))[:80]
            path = self._reports_dir() / f"backtest_{safe_sid}_{datetime.now():%Y%m%d_%H%M%S}.md"
            try:
                path.write_text(md, encoding="utf-8")
            except Exception:
                logger.exception("failed to write backtest report")
            return md
        except Exception:
            logger.exception("generate_backtest_report failed")
            return "# Backtest report\n\n_Generation failed._\n"
