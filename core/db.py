"""Database helpers — SQLite for relational data, DuckDB for analytics."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import duckdb
from loguru import logger

_local = threading.local()


def _get_sqlite_conn(db_path: Path) -> sqlite3.Connection:
    conn = getattr(_local, "sqlite_conn", None)
    if conn is None:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        _local.sqlite_conn = conn
        logger.debug("Opened SQLite connection: {}", db_path)
    return conn


@contextmanager
def get_db(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    from core.config import settings
    path = db_path or settings.db_path
    conn = _get_sqlite_conn(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_duckdb(data_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    from core.config import settings
    path = data_dir or settings.data_dir
    return duckdb.connect(str(path / "analytics.duckdb"))


def init_schema(db_path: Path | None = None) -> None:
    from core.config import settings
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA_SQL)
    _run_migrations(conn)
    conn.commit()
    conn.close()
    logger.info("Database schema initialized at {}", path)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _run_migrations(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "backtest_results", "folder_id"):
        conn.execute(
            "ALTER TABLE backtest_results ADD COLUMN folder_id INTEGER "
            "REFERENCES backtest_folders(id) ON DELETE SET NULL"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_backtest_results_folder_id "
        "ON backtest_results(folder_id, run_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_backtest_comments_record_id "
        "ON backtest_comments(record_id, updated_at)"
    )


_SCHEMA_SQL = """
-- Stock basic info
CREATE TABLE IF NOT EXISTS stocks (
    symbol      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    market      TEXT NOT NULL DEFAULT 'A',
    industry    TEXT,
    list_date   TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Daily OHLCV
CREATE TABLE IF NOT EXISTS daily_quotes (
    symbol      TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    amount      REAL,
    turnover    REAL,
    PRIMARY KEY (symbol, trade_date)
);

-- Factors
CREATE TABLE IF NOT EXISTS factors (
    factor_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    ic          REAL,
    ir          REAL,
    max_dd      REAL,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    params_json TEXT
);

-- Persisted factor values (symbol + date + factor → value)
CREATE TABLE IF NOT EXISTS factor_values (
    symbol      TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    factor_name TEXT NOT NULL,
    value       REAL,
    PRIMARY KEY (symbol, trade_date, factor_name)
);

-- Factor evaluation snapshots
CREATE TABLE IF NOT EXISTS factor_eval_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    factor_name     TEXT NOT NULL,
    forward_period  INTEGER NOT NULL DEFAULT 5,
    ic_mean         REAL,
    ic_std          REAL,
    icir            REAL,
    rank_ic_mean    REAL,
    rank_icir       REAL,
    ic_positive_ratio REAL,
    monotonicity    REAL,
    sub_period_json TEXT NOT NULL DEFAULT '{}',
    evaluated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (symbol, factor_name, forward_period)
);

-- Strategies
CREATE TABLE IF NOT EXISTS strategies (
    strategy_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft',
    sharpe      REAL,
    max_dd      REAL,
    win_rate    REAL,
    total_return REAL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    params_json TEXT
);

-- Backtest results
CREATE TABLE IF NOT EXISTS backtest_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id     TEXT NOT NULL,
    symbol          TEXT NOT NULL DEFAULT '',
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    params_json     TEXT,
    initial_capital REAL NOT NULL DEFAULT 1000000,
    final_capital   REAL,
    total_return    REAL,
    annual_return   REAL,
    sharpe          REAL,
    max_dd          REAL,
    win_rate        REAL,
    trade_count     INTEGER,
    folder_id       INTEGER REFERENCES backtest_folders(id) ON DELETE SET NULL,
    run_at          TEXT NOT NULL DEFAULT (datetime('now')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS backtest_folders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS backtest_comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id   INTEGER NOT NULL REFERENCES backtest_results(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Alerts
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    level       TEXT NOT NULL,
    source      TEXT NOT NULL,
    message     TEXT NOT NULL,
    resolved    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- System metrics
CREATE TABLE IF NOT EXISTS system_metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    value       REAL NOT NULL,
    tags_json   TEXT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Watchlist
CREATE TABLE IF NOT EXISTS watchlist (
    symbol      TEXT PRIMARY KEY,
    added_at    TEXT NOT NULL DEFAULT (datetime('now')),
    note        TEXT DEFAULT ''
);

-- Research asset universe
CREATE TABLE IF NOT EXISTS asset_universe (
    symbol           TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    asset_type       TEXT NOT NULL,
    market           TEXT NOT NULL DEFAULT 'CN',
    exchange         TEXT,
    benchmark_symbol TEXT,
    status           TEXT NOT NULL DEFAULT 'active',
    source           TEXT NOT NULL DEFAULT 'manual',
    list_date        TEXT,
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    extra_json       TEXT NOT NULL DEFAULT '{}'
);

-- Asset tags / themes
CREATE TABLE IF NOT EXISTS asset_tags (
    symbol      TEXT NOT NULL,
    tag         TEXT NOT NULL,
    tag_type    TEXT NOT NULL DEFAULT 'theme',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, tag, tag_type)
);

-- Asset mapping such as ETF -> tracked index
CREATE TABLE IF NOT EXISTS asset_mapping (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_symbol  TEXT NOT NULL,
    source_type    TEXT NOT NULL,
    target_symbol  TEXT NOT NULL,
    target_type    TEXT NOT NULL,
    relation_type  TEXT NOT NULL,
    note           TEXT DEFAULT '',
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source_symbol, target_symbol, relation_type)
);

-- Derived market breadth features from existing daily_quotes
CREATE TABLE IF NOT EXISTS market_breadth_features (
    trade_date            TEXT PRIMARY KEY,
    total_count           INTEGER NOT NULL DEFAULT 0,
    up_count              INTEGER NOT NULL DEFAULT 0,
    down_count            INTEGER NOT NULL DEFAULT 0,
    flat_count            INTEGER NOT NULL DEFAULT 0,
    avg_return_pct        REAL NOT NULL DEFAULT 0,
    median_return_pct     REAL NOT NULL DEFAULT 0,
    total_amount          REAL NOT NULL DEFAULT 0,
    high_turnover_count   INTEGER NOT NULL DEFAULT 0,
    high_turnover_ratio   REAL NOT NULL DEFAULT 0,
    new_high_count        INTEGER NOT NULL DEFAULT 0,
    new_high_ratio        REAL NOT NULL DEFAULT 0,
    new_low_count         INTEGER NOT NULL DEFAULT 0,
    new_low_ratio         REAL NOT NULL DEFAULT 0,
    industry_strength_json TEXT NOT NULL DEFAULT '{}',
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Structured job / task logs for backend observability
CREATE TABLE IF NOT EXISTS job_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name     TEXT NOT NULL,
    status       TEXT NOT NULL,
    message      TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Compatibility layer for the v2 data module plan
CREATE VIEW IF NOT EXISTS asset_daily_quotes AS
SELECT
    symbol,
    trade_date,
    open,
    high,
    low,
    close,
    volume,
    amount,
    turnover
FROM daily_quotes;

CREATE VIEW IF NOT EXISTS asset_data_status AS
SELECT
    symbol,
    COUNT(*) AS count,
    MIN(trade_date) AS min_date,
    MAX(trade_date) AS max_date
FROM daily_quotes
GROUP BY symbol;

CREATE INDEX IF NOT EXISTS idx_daily_quotes_date ON daily_quotes(trade_date);
CREATE INDEX IF NOT EXISTS idx_alerts_level ON alerts(level, resolved);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON system_metrics(metric_name, recorded_at);
CREATE INDEX IF NOT EXISTS idx_asset_universe_type ON asset_universe(asset_type, status);
CREATE INDEX IF NOT EXISTS idx_asset_tags_symbol ON asset_tags(symbol, tag_type);
CREATE INDEX IF NOT EXISTS idx_asset_mapping_source ON asset_mapping(source_symbol, relation_type);
CREATE INDEX IF NOT EXISTS idx_market_breadth_date ON market_breadth_features(trade_date);
CREATE INDEX IF NOT EXISTS idx_job_logs_name ON job_logs(job_name, created_at);
CREATE INDEX IF NOT EXISTS idx_factor_values_symbol ON factor_values(symbol, factor_name);
CREATE INDEX IF NOT EXISTS idx_factor_eval_symbol ON factor_eval_results(symbol, factor_name);
""".strip()
