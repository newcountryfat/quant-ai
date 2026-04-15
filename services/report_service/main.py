from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from core.config import settings
from core.db import get_db
from core.event_bus import Event, LocalEventBus


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


class ReportService:
    def __init__(self, bus: LocalEventBus) -> None:
        self._bus = bus

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

    async def generate_daily_report(self) -> str:
        try:
            lines: list[str] = []
            today = datetime.now().strftime("%Y-%m-%d %H:%M")
            lines.append(f"# Daily quant report — {today}\n")

            with get_db() as conn:
                try:
                    dq = pd.read_sql(
                        """
                        SELECT COUNT(*) AS rows, MIN(trade_date) AS min_d, MAX(trade_date) AS max_d
                        FROM daily_quotes
                        """,
                        conn,
                    )
                    if not dq.empty and dq.iloc[0]["rows"]:
                        r = dq.iloc[0]
                        lines.append("## Market summary\n")
                        lines.append(
                            f"- Daily quote rows: **{int(r['rows'])}** "
                            f"(date range {r['min_d']} → {r['max_d']})\n"
                        )
                    else:
                        lines.append("## Market summary\n")
                        lines.append("- No daily quote rows in database.\n")
                except Exception:
                    logger.exception("daily_quotes summary failed")
                    lines.append("## Market summary\n")
                    lines.append("- Market data unavailable.\n")

                try:
                    st = pd.read_sql(
                        "SELECT strategy_id, name, status, sharpe, max_dd, total_return FROM strategies",
                        conn,
                    )
                    lines.append("\n## Strategy performance\n")
                    if st.empty:
                        lines.append("- No strategies registered.\n")
                    else:
                        lines.append(_df_to_md(st))
                        lines.append("\n")
                except Exception:
                    logger.exception("strategies query failed")
                    lines.append("\n## Strategy performance\n")
                    lines.append("- Strategy data unavailable.\n")

                try:
                    al = pd.read_sql(
                        """
                        SELECT level, source, message, created_at
                        FROM alerts
                        ORDER BY id DESC
                        LIMIT 10
                        """,
                        conn,
                    )
                    lines.append("\n## Risk status (recent alerts)\n")
                    if al.empty:
                        lines.append("- No recent alerts.\n")
                    else:
                        lines.append(_df_to_md(al))
                        lines.append("\n")
                except Exception:
                    logger.exception("alerts query failed")
                    lines.append("\n## Risk status\n")
                    lines.append("- Alerts unavailable.\n")

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
