from __future__ import annotations

import json
from typing import Any

import pandas as pd

from core.db import get_db


_BREADTH_SQL = """
SELECT
    enriched.trade_date,
    enriched.symbol,
    enriched.close,
    enriched.amount,
    enriched.turnover,
    enriched.industry,
    enriched.prev_close,
    enriched.rolling_20_high,
    enriched.rolling_20_low
FROM (
    SELECT
        q.trade_date,
        q.symbol,
        q.close,
        q.amount,
        q.turnover,
        COALESCE(NULLIF(s.industry, ''), 'unknown') AS industry,
        LAG(q.close) OVER (
            PARTITION BY q.symbol
            ORDER BY q.trade_date
        ) AS prev_close,
        MAX(q.close) OVER (
            PARTITION BY q.symbol
            ORDER BY q.trade_date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ) AS rolling_20_high,
        MIN(q.close) OVER (
            PARTITION BY q.symbol
            ORDER BY q.trade_date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ) AS rolling_20_low
    FROM daily_quotes q
    LEFT JOIN stocks s ON s.symbol = q.symbol
) enriched
WHERE enriched.trade_date >= ?
  AND enriched.trade_date <= ?
ORDER BY enriched.trade_date, enriched.symbol
""".strip()


def rebuild_market_breadth(start: str, end: str) -> dict[str, Any]:
    with get_db() as conn:
        df = pd.read_sql_query(_BREADTH_SQL, conn, params=(start, end))
        if df.empty:
            return {
                "status": "ok",
                "days_processed": 0,
                "start": start,
                "end": end,
            }

        df = df[df["prev_close"].notna() & (df["prev_close"] != 0)].copy()
        if df.empty:
            return {
                "status": "ok",
                "days_processed": 0,
                "start": start,
                "end": end,
            }

        df["return_pct"] = (df["close"] - df["prev_close"]) / df["prev_close"] * 100.0
        df["amount"] = df["amount"].fillna(0.0)
        df["turnover"] = df["turnover"].fillna(0.0)
        df["is_up"] = df["return_pct"] > 0
        df["is_down"] = df["return_pct"] < 0
        df["is_flat"] = df["return_pct"] == 0
        df["is_high_turnover"] = df["turnover"] >= 3.0
        df["is_new_high"] = df["close"] >= df["rolling_20_high"]
        df["is_new_low"] = df["close"] <= df["rolling_20_low"]

        rows: list[tuple[Any, ...]] = []
        for trade_date, group in df.groupby("trade_date", sort=True):
            total_count = int(len(group))
            if total_count == 0:
                continue

            industry_returns = (
                group.groupby("industry")["return_pct"].mean().sort_values(ascending=False)
            )
            top_industries = [
                {"industry": industry, "mean_return_pct": round(float(value), 4)}
                for industry, value in industry_returns.head(5).items()
            ]
            bottom_industries = [
                {"industry": industry, "mean_return_pct": round(float(value), 4)}
                for industry, value in industry_returns.tail(5).items()
            ]
            industry_strength = {"top": top_industries, "bottom": bottom_industries}

            up_count = int(group["is_up"].sum())
            down_count = int(group["is_down"].sum())
            flat_count = int(group["is_flat"].sum())
            high_turnover_count = int(group["is_high_turnover"].sum())
            new_high_count = int(group["is_new_high"].sum())
            new_low_count = int(group["is_new_low"].sum())

            rows.append(
                (
                    str(trade_date),
                    total_count,
                    up_count,
                    down_count,
                    flat_count,
                    round(float(group["return_pct"].mean()), 6),
                    round(float(group["return_pct"].median()), 6),
                    round(float(group["amount"].sum()), 2),
                    high_turnover_count,
                    round(high_turnover_count / total_count, 6),
                    new_high_count,
                    round(new_high_count / total_count, 6),
                    new_low_count,
                    round(new_low_count / total_count, 6),
                    json.dumps(industry_strength, ensure_ascii=False),
                )
            )

        conn.executemany(
            """
            INSERT INTO market_breadth_features (
                trade_date,
                total_count,
                up_count,
                down_count,
                flat_count,
                avg_return_pct,
                median_return_pct,
                total_amount,
                high_turnover_count,
                high_turnover_ratio,
                new_high_count,
                new_high_ratio,
                new_low_count,
                new_low_ratio,
                industry_strength_json,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(trade_date) DO UPDATE SET
                total_count = excluded.total_count,
                up_count = excluded.up_count,
                down_count = excluded.down_count,
                flat_count = excluded.flat_count,
                avg_return_pct = excluded.avg_return_pct,
                median_return_pct = excluded.median_return_pct,
                total_amount = excluded.total_amount,
                high_turnover_count = excluded.high_turnover_count,
                high_turnover_ratio = excluded.high_turnover_ratio,
                new_high_count = excluded.new_high_count,
                new_high_ratio = excluded.new_high_ratio,
                new_low_count = excluded.new_low_count,
                new_low_ratio = excluded.new_low_ratio,
                industry_strength_json = excluded.industry_strength_json,
                updated_at = datetime('now')
            """,
            rows,
        )

    return {
        "status": "ok",
        "days_processed": len(rows),
        "start": start,
        "end": end,
        "latest_trade_date": rows[-1][0] if rows else None,
    }


def list_market_breadth(start: str | None = None, end: str | None = None, limit: int = 60) -> list[dict[str, Any]]:
    sql = """
    SELECT
        trade_date,
        total_count,
        up_count,
        down_count,
        flat_count,
        avg_return_pct,
        median_return_pct,
        total_amount,
        high_turnover_count,
        high_turnover_ratio,
        new_high_count,
        new_high_ratio,
        new_low_count,
        new_low_ratio,
        industry_strength_json,
        updated_at
    FROM market_breadth_features
    WHERE (? IS NULL OR trade_date >= ?)
      AND (? IS NULL OR trade_date <= ?)
    ORDER BY trade_date DESC
    LIMIT ?
    """.strip()
    with get_db() as conn:
        rows = conn.execute(sql, (start, start, end, end, limit)).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["industry_strength"] = json.loads(item.pop("industry_strength_json") or "{}")
        result.append(item)
    return result
