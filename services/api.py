"""FastAPI application — RESTful API for the quant platform."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.config import settings
from core.db import get_db
from core.event_bus import LocalEventBus
from core.job_logger import list_job_logs, record_job_log
from services.data_service.market_breadth import list_market_breadth
from services.data_service.research_universe import (
    DEFAULT_ETF_CODES,
    DEFAULT_INDEX_CODES,
    is_market_symbol,
)

app = FastAPI(title="QuantAI Guardian API", version="0.3.0")

_WEB_UI_DIR = Path(__file__).resolve().parent.parent / "web_ui"
if _WEB_UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_WEB_UI_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(str(_WEB_UI_DIR / "index.html"))

_bus: LocalEventBus | None = None
_data_svc = None
_strategy_svc = None
_monitor_svc = None
_report_svc = None
_risk_svc = None
_paper_svc = None


def set_services(
    bus: LocalEventBus,
    data_svc,
    strategy_svc,
    monitor_svc,
    report_svc,
    risk_svc=None,
    paper_svc=None,
) -> None:
    global _bus, _data_svc, _strategy_svc, _monitor_svc, _report_svc, _risk_svc, _paper_svc
    _bus = bus
    _data_svc = data_svc
    _strategy_svc = strategy_svc
    _monitor_svc = monitor_svc
    _report_svc = report_svc
    _risk_svc = risk_svc
    _paper_svc = paper_svc


# ---------- Pydantic models ----------

class StockListResponse(BaseModel):
    count: int
    stocks: list[dict[str, Any]]


class DailyQuoteResponse(BaseModel):
    symbol: str
    count: int
    data: list[dict[str, Any]]


class UpdateRequest(BaseModel):
    symbol: str
    start: str = Field(default="2024-01-01")
    end: str = Field(default_factory=lambda: date.today().isoformat())


class UniverseSyncRequest(BaseModel):
    asset_type: str | None = Field(default=None, description="index / etf / stock；为空表示全部")
    start: str = Field(default="2024-01-01")
    end: str = Field(default_factory=lambda: date.today().isoformat())
    only_active: bool = True
    limit: int | None = Field(default=None, ge=1, le=500)


class BreadthRebuildRequest(BaseModel):
    start: str = Field(default="2024-01-01")
    end: str = Field(default_factory=lambda: date.today().isoformat())


class BacktestRequest(BaseModel):
    strategy_id: str = "ma_cross"
    symbol: str
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())
    params: dict[str, Any] = Field(default_factory=lambda: {"fast": 5, "slow": 20})


class BacktestFolderRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)


class BacktestCommentRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


class BacktestBatchDeleteRequest(BaseModel):
    record_ids: list[int] = Field(default_factory=list)


class BacktestBatchMoveRequest(BaseModel):
    record_ids: list[int] = Field(default_factory=list)
    folder_id: int | None = None


class TradeRecord(BaseModel):
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    pnl_pct: float
    holding_days: int
    side: str

class BacktestResponse(BaseModel):
    strategy_id: str
    symbol: str
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    trade_count: int
    trades: list[TradeRecord] = []


class FactorResponse(BaseModel):
    symbol: str
    rows: int
    columns: list[str]
    sample: list[dict[str, Any]]


class HealthResponse(BaseModel):
    status: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    timestamp: str


class ReportResponse(BaseModel):
    content: str


# ---------- Health ----------

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    if _monitor_svc is None:
        return HealthResponse(
            status="ok",
            cpu_percent=0,
            memory_percent=0,
            disk_percent=0,
            timestamp=datetime.now().isoformat(),
        )
    h = await _monitor_svc.check_system_health()
    return HealthResponse(
        status="ok",
        cpu_percent=h.get("cpu_percent", 0),
        memory_percent=h.get("memory_percent", 0),
        disk_percent=h.get("disk_percent", 0),
        timestamp=datetime.now().isoformat(),
    )


@app.get("/metrics", tags=["System"])
async def metrics():
    with get_db() as conn:
        cur = conn.execute(
            "SELECT metric_name, value, tags_json, recorded_at "
            "FROM system_metrics ORDER BY id DESC LIMIT 50"
        )
        rows = [dict(r) for r in cur.fetchall()]
    return {"metrics": rows}


@app.get("/alerts", tags=["System"])
async def alerts(limit: int = Query(20, ge=1, le=100)):
    if _monitor_svc is None:
        return {"alerts": []}
    return {"alerts": await _monitor_svc.get_recent_alerts(limit)}


@app.get("/api/v1/logs/jobs", tags=["System"])
async def job_logs(
    job_name: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    items = list_job_logs(job_name=job_name, status=status, limit=limit)
    return {"count": len(items), "items": items}


@app.get("/api/v1/data/summary", tags=["System"])
async def data_summary():
    """Return a comprehensive snapshot of all data stored in the platform."""
    with get_db() as conn:
        stocks_total = conn.execute("SELECT COUNT(*) AS c FROM stocks").fetchone()["c"]

        quote_stats = conn.execute(
            "SELECT COUNT(DISTINCT symbol) AS symbols, COUNT(*) AS rows, "
            "MIN(trade_date) AS min_date, MAX(trade_date) AS max_date "
            "FROM daily_quotes"
        ).fetchone()

        universe_counts = conn.execute(
            "SELECT asset_type, COUNT(*) AS c FROM asset_universe GROUP BY asset_type"
        ).fetchall()

        breadth_stats = conn.execute(
            "SELECT COUNT(*) AS rows, MIN(trade_date) AS min_date, MAX(trade_date) AS max_date "
            "FROM market_breadth_features"
        ).fetchone()

        factor_stats = conn.execute(
            "SELECT COUNT(*) AS c, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active "
            "FROM factors"
        ).fetchone()

        factor_val_stats = conn.execute(
            "SELECT COUNT(DISTINCT symbol) AS symbols, COUNT(DISTINCT factor_name) AS factors, "
            "COUNT(*) AS rows FROM factor_values"
        ).fetchone()

        eval_stats = conn.execute(
            "SELECT COUNT(*) AS c, COUNT(DISTINCT symbol) AS symbols "
            "FROM factor_eval_results"
        ).fetchone()

        strategy_stats = conn.execute(
            "SELECT COUNT(*) AS c, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active "
            "FROM strategies"
        ).fetchone()

        backtest_stats = conn.execute(
            "SELECT COUNT(*) AS c FROM backtest_results"
        ).fetchone()

        watchlist_cnt = conn.execute("SELECT COUNT(*) AS c FROM watchlist").fetchone()["c"]

        mapping_cnt = conn.execute("SELECT COUNT(*) AS c FROM asset_mapping").fetchone()["c"]
        tag_cnt = conn.execute("SELECT COUNT(*) AS c FROM asset_tags").fetchone()["c"]

        job_stats = conn.execute(
            "SELECT status, COUNT(*) AS c FROM job_logs GROUP BY status"
        ).fetchall()

        alert_stats = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) AS unresolved "
            "FROM alerts"
        ).fetchone()

    return {
        "stocks": {"total": stocks_total},
        "daily_quotes": {
            "symbols": quote_stats["symbols"],
            "rows": quote_stats["rows"],
            "date_range": [quote_stats["min_date"], quote_stats["max_date"]],
        },
        "asset_universe": {t["asset_type"]: t["c"] for t in universe_counts},
        "asset_mapping": {"total": mapping_cnt},
        "asset_tags": {"total": tag_cnt},
        "market_breadth": {
            "rows": breadth_stats["rows"],
            "date_range": [breadth_stats["min_date"], breadth_stats["max_date"]],
        },
        "factors": {
            "total": factor_stats["c"],
            "active": factor_stats["active"] or 0,
        },
        "factor_values": {
            "symbols": factor_val_stats["symbols"],
            "factor_types": factor_val_stats["factors"],
            "rows": factor_val_stats["rows"],
        },
        "factor_eval_results": {
            "total": eval_stats["c"],
            "symbols": eval_stats["symbols"],
        },
        "strategies": {
            "total": strategy_stats["c"],
            "active": strategy_stats["active"] or 0,
        },
        "backtest_results": {"total": backtest_stats["c"]},
        "watchlist": {"total": watchlist_cnt},
        "job_logs": {r["status"]: r["c"] for r in job_stats},
        "alerts": {
            "total": alert_stats["total"],
            "unresolved": alert_stats["unresolved"] or 0,
        },
        "generated_at": datetime.now().isoformat(),
    }


# ---------- Market Indices ----------

INDEX_CODES = DEFAULT_INDEX_CODES
ETF_CODES = DEFAULT_ETF_CODES

@app.get("/api/v1/market/indices", tags=["Data"])
async def market_indices():
    try:
        result = await asyncio.to_thread(_fetch_indices_qq)
        return {"indices": result}
    except Exception:
        return {"indices": []}


@app.get("/api/v1/market/etfs", tags=["Data"])
async def market_etfs(
    scope: str = Query("default", description="default | all"),
    persist: bool = Query(False, description="Persist full ETF list into asset_universe"),
):
    try:
        if scope == "all":
            result = await asyncio.to_thread(_fetch_all_etfs_ak)
            persisted = 0
            if persist and result:
                persisted = await asyncio.to_thread(_persist_etf_universe, result)
            return {"etfs": result, "persisted": persisted}
        else:
            result = await asyncio.to_thread(_fetch_etf_qq)
        return {"etfs": result}
    except Exception:
        if scope == "all":
            try:
                result = await asyncio.to_thread(_fetch_etf_qq)
                return {"etfs": result}
            except Exception:
                return {"etfs": []}
        return {"etfs": []}


def _fetch_indices_qq() -> list[dict]:
    """Fetch index data from Tencent Finance API (highly reliable)."""
    import requests
    codes = ",".join(c for c, _ in INDEX_CODES)
    name_map = {c: n for c, n in INDEX_CODES}
    try:
        resp = requests.get(f"http://qt.gtimg.cn/q={codes}", timeout=6)
        resp.encoding = "gbk"
        text = resp.text
    except Exception:
        return []
    out = []
    for line in text.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        key = line.split("=")[0].replace("v_", "").strip()
        val = line.split("=")[1].strip().strip('"')
        parts = val.split("~")
        if len(parts) < 35:
            continue
        try:
            close = float(parts[3])
            prev_close = float(parts[4])
            chg = close - prev_close
            chg_pct = float(parts[32]) if parts[32] else (chg / prev_close * 100 if prev_close else 0)
            out.append({
                "code": key,
                "name": name_map.get(key, parts[1]),
                "close": round(close, 2),
                "change": round(chg, 2),
                "change_pct": round(chg_pct, 2),
                "volume": float(parts[6]) if parts[6] else 0,
                "amount": float(parts[37]) if len(parts) > 37 and parts[37] else 0,
            })
        except (ValueError, IndexError):
            continue
    return out


def _fetch_etf_qq() -> list[dict]:
    """Fetch ETF data from Tencent Finance API."""
    import requests
    codes = ",".join(c for c, _ in ETF_CODES)
    name_map = {c: n for c, n in ETF_CODES}
    try:
        resp = requests.get(f"http://qt.gtimg.cn/q={codes}", timeout=6)
        resp.encoding = "gbk"
        text = resp.text
    except Exception:
        return []
    out = []
    for line in text.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        key = line.split("=")[0].replace("v_", "").strip()
        val = line.split("=")[1].strip().strip('"')
        parts = val.split("~")
        if len(parts) < 35:
            continue
        try:
            close = float(parts[3])
            prev_close = float(parts[4])
            chg = close - prev_close
            chg_pct = float(parts[32]) if parts[32] else (chg / prev_close * 100 if prev_close else 0)
            out.append({
                "code": key,
                "name": name_map.get(key, parts[1]),
                "close": round(close, 4),
                "prev_close": round(prev_close, 4),
                "change": round(chg, 4),
                "change_pct": round(chg_pct, 2),
                "volume": float(parts[6]) if parts[6] else 0,
                "amount": float(parts[37]) if len(parts) > 37 and parts[37] else 0,
                "high": float(parts[33]) if len(parts) > 33 and parts[33] else close,
                "low": float(parts[34]) if len(parts) > 34 and parts[34] else close,
                "open": float(parts[5]) if parts[5] else close,
            })
        except (ValueError, IndexError):
            continue
    return out


def _normalize_etf_market_code(code: str) -> str:
    raw = "".join(ch for ch in str(code) if ch.isdigit())
    if len(raw) != 6:
        return str(code).strip().lower()
    return f"sh{raw}" if raw.startswith(("5", "6")) else f"sz{raw}"


def _fetch_all_etfs_ak() -> list[dict]:
    """Fetch full ETF universe from AKShare."""
    import akshare as ak
    import pandas as pd

    try:
        raw = ak.fund_etf_spot_ths()
    except Exception:
        raw = ak.fund_etf_category_sina()
    if raw is None or raw.empty:
        return []

    code_col = next((c for c in raw.columns if str(c) in ("基金代码", "代码") or "代码" in str(c)), None)
    name_col = next((c for c in raw.columns if str(c) in ("基金名称", "名称") or "名称" in str(c)), None)
    price_col = next((c for c in raw.columns if "当前-单位净值" in str(c) or "最新价" in str(c)), None)
    change_col = next((c for c in raw.columns if "增长值" in str(c) or "涨跌额" in str(c)), None)
    change_pct_col = next((c for c in raw.columns if "增长率" in str(c) or "涨跌幅" in str(c)), None)
    volume_col = next((c for c in raw.columns if "成交量" in str(c)), None)
    amount_col = next((c for c in raw.columns if "成交额" in str(c)), None)

    if not code_col or not name_col:
        return []

    out = []
    for _, row in raw.iterrows():
        code = _normalize_etf_market_code(row.get(code_col))
        name = str(row.get(name_col) or "").strip()
        if not code or not name:
            continue
        if len("".join(ch for ch in code if ch.isdigit())) != 6:
            continue
        close = pd.to_numeric(row.get(price_col), errors="coerce") if price_col else None
        chg = pd.to_numeric(row.get(change_col), errors="coerce") if change_col else None
        chg_pct = pd.to_numeric(row.get(change_pct_col), errors="coerce") if change_pct_col else None
        volume = pd.to_numeric(row.get(volume_col), errors="coerce") if volume_col else None
        amount = pd.to_numeric(row.get(amount_col), errors="coerce") if amount_col else None
        out.append({
            "code": code,
            "name": name,
            "close": round(float(close), 3) if pd.notna(close) else 0.0,
            "change": round(float(chg), 4) if pd.notna(chg) else 0.0,
            "change_pct": round(float(chg_pct), 2) if pd.notna(chg_pct) else 0.0,
            "volume": float(volume) if pd.notna(volume) else 0.0,
            "amount": float(amount) if pd.notna(amount) else 0.0,
        })
    out.sort(key=lambda x: x["code"])
    return out


def _persist_etf_universe(items: list[dict[str, Any]]) -> int:
    rows = []
    for item in items:
        symbol = str(item.get("code") or "").strip()
        name = str(item.get("name") or "").strip()
        if not symbol or not name:
            continue
        exchange = "SSE" if symbol.startswith("sh") else "SZSE" if symbol.startswith("sz") else None
        extra_json = json.dumps(
            {
                "close": item.get("close"),
                "change": item.get("change"),
                "change_pct": item.get("change_pct"),
                "volume": item.get("volume"),
                "amount": item.get("amount"),
            },
            ensure_ascii=False,
        )
        rows.append((
            symbol,
            name,
            "etf",
            "CN",
            exchange,
            None,
            "active",
            "akshare_ths_full_etf",
            None,
            extra_json,
        ))

    if not rows:
        return 0

    with get_db() as conn:
        conn.executemany(
            """
            INSERT INTO asset_universe (
                symbol, name, asset_type, market, exchange,
                benchmark_symbol, status, source, list_date, extra_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(symbol) DO UPDATE SET
                name = excluded.name,
                asset_type = excluded.asset_type,
                market = excluded.market,
                exchange = excluded.exchange,
                benchmark_symbol = excluded.benchmark_symbol,
                status = excluded.status,
                source = excluded.source,
                list_date = excluded.list_date,
                extra_json = excluded.extra_json,
                updated_at = datetime('now')
            """,
            rows,
        )
    record_job_log(
        "market_etfs_full_persist",
        "success",
        "Persisted full ETF universe into asset_universe",
        {"count": len(rows)},
    )
    return len(rows)


# ---------- Index Daily Data ----------

@app.get("/api/v1/index/{code}/daily", tags=["Data"])
async def index_daily(code: str, days: int = Query(120, ge=5, le=500)):
    result = await asyncio.to_thread(_fetch_index_kline, code, days)
    return {"code": code, "count": len(result), "data": result}


def _fetch_index_kline(code: str, days: int) -> list[dict]:
    """Fetch index K-line from Tencent Finance API."""
    import requests
    from datetime import datetime, timedelta
    start = (datetime.now() - timedelta(days=int(days * 1.6))).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,{start},{end},{days},qfq",
            timeout=8, allow_redirects=True,
        )
        data = resp.json().get("data", {}).get(code, {})
        rows = data.get("day", data.get("qfqday", []))
        out = []
        for r in rows:
            if len(r) < 6:
                continue
            out.append({
                "trade_date": r[0],
                "open": float(r[1]),
                "close": float(r[2]),
                "high": float(r[3]),
                "low": float(r[4]),
                "volume": float(r[5]),
            })
        return out
    except Exception:
        return []


# ---------- Data ----------

@app.get("/api/v1/stocks", response_model=StockListResponse, tags=["Data"])
async def list_stocks(market: str = Query("A", description="市场类型，默认 A 股")):
    with get_db() as conn:
        cur = conn.execute(
            "SELECT symbol, name, market, industry, list_date FROM stocks WHERE market = ? ORDER BY symbol",
            (market,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    return StockListResponse(count=len(rows), stocks=rows)


@app.post("/api/v1/stocks/update", tags=["Data"])
async def update_stock_list(market: str = Query("A", description="市场类型，默认 A 股")):
    if _data_svc is None:
        raise HTTPException(503, "DataService not available")
    await _data_svc.update_stock_list(market)
    return {"status": "ok", "market": market}


@app.get("/api/v1/data/{symbol}/daily", response_model=DailyQuoteResponse, tags=["Data"])
async def get_daily(
    symbol: str,
    start: str = Query("2024-01-01"),
    end: str = Query(default_factory=lambda: date.today().isoformat()),
    limit: int = Query(500, ge=1, le=20000),
):
    with get_db() as conn:
        cur = conn.execute(
            "SELECT trade_date, open, high, low, close, volume, amount, turnover "
            "FROM daily_quotes WHERE symbol = ? AND trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date DESC LIMIT ?",
            (symbol, start, end, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
    return DailyQuoteResponse(symbol=symbol, count=len(rows), data=rows)


@app.get("/api/v1/data/{symbol}/info", tags=["Data"])
async def data_info(symbol: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt, MIN(trade_date) as min_date, MAX(trade_date) as max_date "
            "FROM daily_quotes WHERE symbol = ?", (symbol,)
        ).fetchone()
    return {"symbol": symbol, "count": row["cnt"], "min_date": row["min_date"], "max_date": row["max_date"]}


@app.get("/api/v1/data/statuses", tags=["Data"])
async def data_statuses():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT symbol, COUNT(*) AS cnt, MAX(trade_date) AS max_date
            FROM daily_quotes
            GROUP BY symbol
            """
        ).fetchall()
    return {
        "items": [
            {"symbol": r["symbol"], "count": r["cnt"], "max_date": r["max_date"]}
            for r in rows
        ]
    }


@app.post("/api/v1/data/update", tags=["Data"])
async def update_daily(req: UpdateRequest):
    if _data_svc is None:
        raise HTTPException(503, "DataService not available")
    await _data_svc.update_daily_data(req.symbol, req.start, req.end)
    with get_db() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) AS cnt FROM daily_quotes WHERE symbol = ?", (req.symbol,)
        )
        cnt = cur.fetchone()["cnt"]
    return {"status": "ok", "symbol": req.symbol, "rows_in_db": cnt}


@app.post("/api/v1/data/a500/sync", tags=["Data"])
async def sync_a500_constituents(
    add_watchlist: bool = Query(False, description="同步完成后将成分加入自选"),
    refresh_stock_list: bool = Query(True, description="先刷新 A 股基础列表"),
):
    """
    拉取中证 A500（000510.SH）成分日线，按 TUSHARE_MIN_INTERVAL_SEC 限速；
    默认只拉数据，不自动加入自选。
    """
    if _data_svc is None:
        raise HTTPException(503, "DataService not available")
    return await _data_svc.sync_a500(
        add_watchlist=add_watchlist,
        refresh_stock_list=refresh_stock_list,
    )


# ---------- Research Universe / Breadth ----------

@app.post("/api/v1/universe/bootstrap", tags=["Data"])
async def bootstrap_universe():
    if _data_svc is None:
        raise HTTPException(503, "DataService not available")
    return await _data_svc.bootstrap_research_universe()


@app.get("/api/v1/universe/assets", tags=["Data"])
async def list_universe_assets(
    asset_type: str | None = Query(None, description="index / etf / stock"),
    only_active: bool = Query(True),
    limit: int = Query(500, ge=1, le=2000),
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                u.symbol,
                u.name,
                u.asset_type,
                u.market,
                u.exchange,
                u.benchmark_symbol,
                u.status,
                u.source,
                u.list_date,
                u.updated_at,
                u.extra_json,
                COALESCE(s.count, 0) AS data_count,
                s.min_date,
                s.max_date
            FROM asset_universe u
            LEFT JOIN asset_data_status s ON s.symbol = u.symbol
            WHERE (? IS NULL OR u.asset_type = ?)
              AND (? = 0 OR u.status = 'active')
            ORDER BY u.asset_type, u.symbol
            LIMIT ?
            """,
            (asset_type, asset_type, 1 if only_active else 0, limit),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["extra"] = json.loads(item.pop("extra_json") or "{}")
        items.append(item)
    return {"count": len(items), "items": items}


@app.get("/api/v1/universe/statuses", tags=["Data"])
async def list_universe_statuses(asset_type: str | None = Query(None, description="index / etf / stock")):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                u.symbol,
                u.name,
                u.asset_type,
                COALESCE(s.count, 0) AS data_count,
                s.min_date,
                s.max_date
            FROM asset_universe u
            LEFT JOIN asset_data_status s ON s.symbol = u.symbol
            WHERE (? IS NULL OR u.asset_type = ?)
            ORDER BY u.asset_type, u.symbol
            """,
            (asset_type, asset_type),
        ).fetchall()
    return {"count": len(rows), "items": [dict(r) for r in rows]}


@app.get("/api/v1/universe/mappings", tags=["Data"])
async def list_universe_mappings(
    relation_type: str | None = Query(None, description="如 tracks"),
    source_symbol: str | None = Query(None),
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                source_symbol,
                source_type,
                target_symbol,
                target_type,
                relation_type,
                note,
                updated_at
            FROM asset_mapping
            WHERE (? IS NULL OR relation_type = ?)
              AND (? IS NULL OR source_symbol = ?)
            ORDER BY source_symbol, relation_type, target_symbol
            """,
            (relation_type, relation_type, source_symbol, source_symbol),
        ).fetchall()
    return {"count": len(rows), "items": [dict(r) for r in rows]}


@app.get("/api/v1/universe/tags", tags=["Data"])
async def list_universe_tags(
    symbol: str | None = Query(None),
    tag_type: str | None = Query(None),
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT symbol, tag, tag_type, updated_at
            FROM asset_tags
            WHERE (? IS NULL OR symbol = ?)
              AND (? IS NULL OR tag_type = ?)
            ORDER BY symbol, tag_type, tag
            """,
            (symbol, symbol, tag_type, tag_type),
        ).fetchall()
    return {"count": len(rows), "items": [dict(r) for r in rows]}


@app.post("/api/v1/universe/sectors/rebuild", tags=["Data"])
async def rebuild_sector_assets(market: str = Query("A", description="默认基于 A 股股票列表派生")):
    if _data_svc is None:
        raise HTTPException(503, "DataService not available")
    return await _data_svc.rebuild_sector_universe(market=market)


@app.get("/api/v1/universe/sectors/constituents", tags=["Data"])
async def sector_constituents(
    sector_symbol: str | None = Query(None, description="如 sector:银行"),
    industry: str | None = Query(None, description="如 银行"),
    limit: int = Query(200, ge=1, le=5000),
):
    target_symbol = sector_symbol or (f"sector:{industry}" if industry else None)
    if not target_symbol:
        raise HTTPException(400, "sector_symbol or industry is required")
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                m.target_symbol AS sector_symbol,
                m.note AS industry,
                s.symbol,
                s.name,
                s.market,
                s.industry,
                s.list_date
            FROM asset_mapping m
            JOIN stocks s ON s.symbol = m.source_symbol
            WHERE m.relation_type = 'belongs_to_sector'
              AND m.target_type = 'sector'
              AND m.target_symbol = ?
            ORDER BY s.symbol
            LIMIT ?
            """,
            (target_symbol, limit),
        ).fetchall()
    return {"count": len(rows), "items": [dict(r) for r in rows]}


@app.post("/api/v1/universe/sync", tags=["Data"])
async def sync_universe(req: UniverseSyncRequest):
    if _data_svc is None:
        raise HTTPException(503, "DataService not available")
    return await _data_svc.sync_research_universe(
        asset_type=req.asset_type,
        start=req.start,
        end=req.end,
        only_active=req.only_active,
        limit=req.limit,
    )


@app.post("/api/v1/features/breadth/rebuild", tags=["Data"])
async def rebuild_breadth(req: BreadthRebuildRequest):
    if _data_svc is None:
        raise HTTPException(503, "DataService not available")
    return await _data_svc.rebuild_market_breadth(req.start, req.end)


@app.get("/api/v1/features/breadth", tags=["Data"])
async def get_breadth(
    start: str | None = Query(None),
    end: str | None = Query(None),
    limit: int = Query(60, ge=1, le=500),
):
    items = list_market_breadth(start=start, end=end, limit=limit)
    return {"count": len(items), "items": items}


# ---------- Strategy / Factors ----------

# --- P2 Pydantic models ---

class BatchComputeRequest(BaseModel):
    symbol: str
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())
    persist: bool = True


class EvaluateFactorsRequest(BaseModel):
    symbol: str
    forward_period: int = Field(5, ge=1, le=60)
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())
    persist: bool = True


class WalkForwardRequest(BaseModel):
    symbol: str
    factor_names: list[str] | None = None
    train_days: int = Field(120, ge=30)
    test_days: int = Field(20, ge=5)
    step_days: int = Field(20, ge=5)
    forward_period: int = Field(5, ge=1, le=60)
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())


# Static factor routes MUST be registered before the {symbol} catch-all

@app.get("/api/v1/factors/library/list", tags=["Strategy"])
async def list_factor_library():
    """Return the list of all factor names available in the library."""
    from services.strategy_service.factor_mining.library import FactorLibrary
    return {"factors": FactorLibrary.list_factor_names()}


@app.get("/api/v1/factors/eval-history", tags=["Strategy"])
async def factor_eval_history(
    symbol: str | None = Query(None),
    factor_name: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """Query persisted factor evaluation results."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    rows = await _strategy_svc.get_factor_eval_history(symbol=symbol, factor_name=factor_name, limit=limit)
    return {"count": len(rows), "items": rows}


@app.get("/api/v1/factors/values/{symbol}", tags=["Strategy"])
async def get_factor_values(
    symbol: str,
    factor_name: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    limit: int = Query(60, ge=1, le=5000),
):
    """Query persisted factor values for a symbol."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    data = await _strategy_svc.get_persisted_factor_values(
        symbol=symbol,
        factor_name=factor_name,
        start=start,
        end=end,
        limit=limit,
    )
    return {
        "symbol": symbol,
        "count": len(data["items"]),
        "items": data["items"],
        "summary": data["summary"],
        "requested_start": start,
        "requested_end": end,
    }


@app.post("/api/v1/factors/batch-compute", tags=["Strategy"])
async def batch_compute_factors(req: BatchComputeRequest):
    """Compute all 40+ factors for a symbol, optionally persist to DB."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.batch_compute_factors(
        symbol=req.symbol, start=req.start, end=req.end, persist=req.persist,
    )


@app.post("/api/v1/factors/evaluate", tags=["Strategy"])
async def evaluate_factors(req: EvaluateFactorsRequest):
    """Evaluate all factors' IC/IR/ICIR against forward returns."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    results = await _strategy_svc.evaluate_factors(
        symbol=req.symbol, forward_period=req.forward_period,
        start=req.start, end=req.end, persist=req.persist,
    )
    return {"symbol": req.symbol, "forward_period": req.forward_period, "count": len(results), "results": results}


@app.post("/api/v1/factors/walk-forward", tags=["Strategy"])
async def walk_forward_validate(req: WalkForwardRequest):
    """Run walk-forward validation on factors for a symbol."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    results = await _strategy_svc.walk_forward_validate(
        symbol=req.symbol,
        factor_names=req.factor_names,
        train_days=req.train_days,
        test_days=req.test_days,
        step_days=req.step_days,
        forward_period=req.forward_period,
        start=req.start,
        end=req.end,
    )
    return {"symbol": req.symbol, "count": len(results), "results": results}


# Dynamic {symbol} route — must be AFTER all /api/v1/factors/... static routes

@app.get("/api/v1/factors/{symbol}", response_model=FactorResponse, tags=["Strategy"])
async def compute_factors(symbol: str, full: bool = Query(False, description="Return all rows")):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    df = await _strategy_svc.compute_factors(symbol)
    if df.empty:
        raise HTTPException(404, f"No data for symbol {symbol}")
    factor_cols = [c for c in df.columns if c not in ("open", "high", "low", "close", "volume")]
    tail_n = len(df) if full else 10
    sample = df.tail(tail_n).reset_index()
    if "trade_date" in sample.columns:
        sample["trade_date"] = sample["trade_date"].astype(str)
    return FactorResponse(
        symbol=symbol,
        rows=len(df),
        columns=factor_cols,
        sample=sample.to_dict(orient="records"),
    )


# ---------- P3: ML Models ----------

class GenerateLabelsRequest(BaseModel):
    symbol: str
    forward_periods: list[int] = Field(default_factory=lambda: [5, 10, 20])
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())


class TrainModelRequest(BaseModel):
    symbol: str
    model_type: str = Field("lightgbm", description="lasso | lightgbm")
    label_col: str = "label_dir_5"
    forward_period: int = Field(5, ge=1, le=60)
    train_ratio: float = Field(0.8, gt=0.1, lt=1.0)
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())
    params: dict[str, Any] | None = None


class ModelWFRequest(BaseModel):
    symbol: str
    model_type: str = "lightgbm"
    label_col: str = "label_dir_5"
    forward_period: int = Field(5, ge=1, le=60)
    train_days: int = Field(200, ge=60)
    test_days: int = Field(20, ge=5)
    step_days: int = Field(20, ge=5)
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())
    params: dict[str, Any] | None = None


class PredictSignalRequest(BaseModel):
    model_id: str
    symbol: str
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())


class GPMineRequest(BaseModel):
    symbol: str
    forward_period: int = Field(5, ge=1, le=60)
    population_size: int = Field(200, ge=20, le=1000)
    n_generations: int = Field(30, ge=5, le=200)
    max_depth: int = Field(5, ge=2, le=5, description="Max tree depth, hard-capped at 5")
    parsimony_coeff: float = Field(0.005, ge=0.0, le=0.1, description="Complexity penalty coefficient")
    metric: str = Field("sharpe", description="sharpe | ic")
    save: bool = Field(False, description="Save top-5 expressions for later predict/backtest")
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())


class GPPredictRequest(BaseModel):
    gp_id: str
    symbol: str
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())


class GPBacktestRequest(BaseModel):
    gp_id: str
    symbol: str
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())
    initial_capital: float = Field(1_000_000, gt=0)
    commission: float = Field(0.001, ge=0)


class GPSaveSingleRequest(BaseModel):
    expression: str
    symbol: str
    metric: str = "sharpe"
    sharpe: float = 0.0
    total_ret: float = 0.0
    ic: float = 0.0
    depth: int = 0
    tree_size: int = 0
    data_start: str = ""
    data_end: str = ""
    forward_period: int = 5


class GPEvaluateRequest(BaseModel):
    gp_id: str
    symbol: str
    forward_period: int = Field(5, ge=1, le=60)
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())


class MLBacktestRequest(BaseModel):
    model_id: str
    symbol: str
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())
    initial_capital: float = Field(1_000_000, gt=0)
    commission: float = Field(0.001, ge=0)
    threshold: float = Field(0.5, ge=0.0, le=1.0, description="Probability threshold for buy signal")


class PipelineRequest(BaseModel):
    symbol: str
    model_type: str = "lightgbm"
    label_col: str = "label_dir_5"
    forward_period: int = Field(5, ge=1, le=60)
    train_ratio: float = Field(0.8, gt=0.1, lt=1.0)
    wf_train_days: int = Field(200, ge=60)
    wf_test_days: int = Field(20, ge=5)
    wf_step_days: int = Field(20, ge=5)
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())
    model_params: dict[str, Any] | None = None


@app.post("/api/v1/ml/labels", tags=["ML"])
async def generate_labels(req: GenerateLabelsRequest):
    """Generate forward returns + direction labels + bucket labels."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.generate_labels(
        symbol=req.symbol, forward_periods=req.forward_periods,
        start=req.start, end=req.end,
    )


@app.post("/api/v1/ml/feature-select", tags=["ML"])
async def feature_select(req: GenerateLabelsRequest):
    """Run feature selection pipeline and return report."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.select_features(symbol=req.symbol, start=req.start, end=req.end)


@app.post("/api/v1/ml/train", tags=["ML"])
async def train_model(req: TrainModelRequest):
    """Train a timing model (Lasso or LightGBM)."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    try:
        return await _strategy_svc.train_model(
            symbol=req.symbol, model_type=req.model_type,
            label_col=req.label_col, forward_period=req.forward_period,
            train_ratio=req.train_ratio, start=req.start, end=req.end,
            params=req.params,
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/v1/ml/walk-forward", tags=["ML"])
async def model_walk_forward(req: ModelWFRequest):
    """Run walk-forward ML model validation."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    try:
        return await _strategy_svc.model_walk_forward(
            symbol=req.symbol, model_type=req.model_type,
            label_col=req.label_col, forward_period=req.forward_period,
            train_days=req.train_days, test_days=req.test_days,
            step_days=req.step_days, start=req.start, end=req.end,
            params=req.params,
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/v1/ml/predict", tags=["ML"])
async def predict_signal(req: PredictSignalRequest):
    """Predict timing signal using a trained model."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.predict_signal(
        model_id=req.model_id, symbol=req.symbol,
        start=req.start, end=req.end,
    )


@app.get("/api/v1/ml/models", tags=["ML"])
async def list_models():
    """List all trained models."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    models = await _strategy_svc.list_models()
    return {"count": len(models), "models": models}


@app.post("/api/v1/ml/gp-mine", tags=["ML"])
async def gp_mine(req: GPMineRequest):
    """Run GP expression mining for timing signal discovery."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.gp_mine(
        symbol=req.symbol, forward_period=req.forward_period,
        population_size=req.population_size,
        n_generations=req.n_generations,
        metric=req.metric, max_depth=req.max_depth,
        parsimony_coeff=req.parsimony_coeff,
        save=req.save, start=req.start, end=req.end,
    )


@app.post("/api/v1/ml/gp-predict", tags=["ML"])
async def gp_predict(req: GPPredictRequest):
    """Predict signals using a saved GP expression."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.gp_predict(
        gp_id=req.gp_id, symbol=req.symbol,
        start=req.start, end=req.end,
    )


@app.get("/api/v1/ml/gp-list", tags=["ML"])
async def gp_list():
    """List all saved GP expressions."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    exprs = await _strategy_svc.gp_list()
    return {"count": len(exprs), "expressions": exprs}


@app.post("/api/v1/ml/gp-save", tags=["ML"])
async def gp_save_single(req: GPSaveSingleRequest):
    """Save a single GP expression."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.gp_save_single(
        expression=req.expression, symbol=req.symbol, metric=req.metric,
        sharpe=req.sharpe, total_ret=req.total_ret, ic=req.ic,
        depth=req.depth, tree_size=req.tree_size,
        data_start=req.data_start, data_end=req.data_end,
        forward_period=req.forward_period,
    )


@app.post("/api/v1/ml/gp-evaluate", tags=["ML"])
async def gp_evaluate(req: GPEvaluateRequest):
    """Evaluate a GP expression on specified symbol and date range."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.gp_evaluate(
        gp_id=req.gp_id, symbol=req.symbol,
        forward_period=req.forward_period,
        start=req.start, end=req.end,
    )


class CustomExprRequest(BaseModel):
    expression: str
    symbol: str
    forward_period: int = Field(5, ge=1)
    start: str = "2024-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())
    initial_capital: float = Field(1_000_000, gt=0)
    commission: float = Field(0.001, ge=0)


@app.post("/api/v1/ml/custom-expression/evaluate", tags=["ML"])
async def custom_expr_evaluate(req: CustomExprRequest):
    """Evaluate a custom expression string on specified symbol and date range."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.custom_expr_evaluate(
        expression=req.expression, symbol=req.symbol,
        forward_period=req.forward_period,
        start=req.start, end=req.end,
    )


@app.post("/api/v1/ml/custom-expression/predict", tags=["ML"])
async def custom_expr_predict(req: CustomExprRequest):
    """Predict signals using a custom expression string."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.custom_expr_predict(
        expression=req.expression, symbol=req.symbol,
        start=req.start, end=req.end,
    )


@app.post("/api/v1/ml/custom-expression/backtest", tags=["ML"])
async def custom_expr_backtest(req: CustomExprRequest):
    """Backtest a custom expression string."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    result = await _strategy_svc.custom_expr_backtest(
        expression=req.expression, symbol=req.symbol,
        start=req.start, end=req.end,
        initial_capital=req.initial_capital,
        commission=req.commission,
    )
    from dataclasses import asdict
    trades = [TradeRecord(**asdict(t)) for t in (result.trades or [])]
    return BacktestResponse(
        strategy_id="custom_expr",
        symbol=req.symbol,
        total_return=round(result.total_return, 6),
        annual_return=round(result.annual_return, 6),
        sharpe_ratio=round(result.sharpe_ratio, 4),
        max_drawdown=round(result.max_drawdown, 6),
        win_rate=round(result.win_rate, 4),
        trade_count=result.trade_count,
        trades=trades,
    )


@app.delete("/api/v1/ml/gp/{gp_id}", tags=["ML"])
async def delete_gp_expression(gp_id: str):
    """Delete a saved GP expression."""
    from services.strategy_service.ml.gp_miner import GPMiner
    miner = GPMiner()
    ok = miner.delete_saved(gp_id)
    if not ok:
        raise HTTPException(404, f"GP expression {gp_id} not found")
    return {"deleted": gp_id}


@app.delete("/api/v1/ml/models/{model_id}", tags=["ML"])
async def delete_ml_model(model_id: str):
    """Delete a trained ML model."""
    from services.strategy_service.ml.timing_model import TimingModelTrainer
    trainer = TimingModelTrainer()
    ok = trainer.delete_model(model_id)
    if not ok:
        raise HTTPException(404, f"Model {model_id} not found")
    return {"deleted": model_id}


@app.delete("/api/v1/backtest/history/{record_id}", tags=["Strategy"])
async def delete_backtest_record(record_id: int):
    """Delete a single backtest record."""
    with get_db() as conn:
        cur = conn.execute("DELETE FROM backtest_results WHERE id = ?", (record_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, f"Backtest record {record_id} not found")
    return {"deleted": record_id}


@app.post("/api/v1/backtest/history/batch-delete", tags=["Strategy"])
async def batch_delete_backtest_records(req: BacktestBatchDeleteRequest):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.batch_delete_backtest_records(req.record_ids)


@app.post("/api/v1/backtest/history/batch-move", tags=["Strategy"])
async def batch_move_backtest_records(req: BacktestBatchMoveRequest):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    try:
        return await _strategy_svc.move_backtest_records(req.record_ids, req.folder_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/v1/backtest/folders", tags=["Strategy"])
async def list_backtest_folders():
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return {"folders": await _strategy_svc.list_backtest_folders()}


@app.post("/api/v1/backtest/folders", tags=["Strategy"])
async def create_backtest_folder(req: BacktestFolderRequest):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    try:
        return await _strategy_svc.create_backtest_folder(req.name)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.put("/api/v1/backtest/folders/{folder_id}", tags=["Strategy"])
async def update_backtest_folder(folder_id: int, req: BacktestFolderRequest):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    try:
        return await _strategy_svc.update_backtest_folder(folder_id, req.name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/v1/backtest/folders/{folder_id}", tags=["Strategy"])
async def delete_backtest_folder(folder_id: int):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    try:
        return await _strategy_svc.delete_backtest_folder(folder_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/v1/backtest/history/{record_id}/comments", tags=["Strategy"])
async def list_backtest_comments(record_id: int):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return {"comments": await _strategy_svc.list_backtest_comments(record_id)}


@app.post("/api/v1/backtest/history/{record_id}/comments", tags=["Strategy"])
async def create_backtest_comment(record_id: int, req: BacktestCommentRequest):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    try:
        return await _strategy_svc.create_backtest_comment(record_id, req.content)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.put("/api/v1/backtest/comments/{comment_id}", tags=["Strategy"])
async def update_backtest_comment(comment_id: int, req: BacktestCommentRequest):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    try:
        return await _strategy_svc.update_backtest_comment(comment_id, req.content)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.delete("/api/v1/backtest/comments/{comment_id}", tags=["Strategy"])
async def delete_backtest_comment(comment_id: int):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    try:
        return await _strategy_svc.delete_backtest_comment(comment_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/v1/backtest/gp", tags=["Strategy"])
async def backtest_gp(req: GPBacktestRequest):
    """Backtest a saved GP expression on a symbol."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    result = await _strategy_svc.backtest_gp_expression(
        gp_id=req.gp_id, symbol=req.symbol,
        start=req.start, end=req.end,
        initial_capital=req.initial_capital,
        commission=req.commission,
    )
    from dataclasses import asdict
    trades = [TradeRecord(**asdict(t)) for t in (result.trades or [])]
    return BacktestResponse(
        strategy_id=f"gp:{req.gp_id}",
        symbol=req.symbol,
        total_return=round(result.total_return, 6),
        annual_return=round(result.annual_return, 6),
        sharpe_ratio=round(result.sharpe_ratio, 4),
        max_drawdown=round(result.max_drawdown, 6),
        win_rate=round(result.win_rate, 4),
        trade_count=result.trade_count,
        trades=trades,
    )


@app.post("/api/v1/backtest/ml", tags=["Strategy"])
async def backtest_ml(req: MLBacktestRequest):
    """Backtest a trained ML model on a symbol."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    result = await _strategy_svc.backtest_ml_model(
        model_id=req.model_id, symbol=req.symbol,
        start=req.start, end=req.end,
        initial_capital=req.initial_capital,
        commission=req.commission,
        threshold=req.threshold,
    )
    from dataclasses import asdict
    trades = [TradeRecord(**asdict(t)) for t in (result.trades or [])]
    return BacktestResponse(
        strategy_id=f"ml:{req.model_id}",
        symbol=req.symbol,
        total_return=round(result.total_return, 6),
        annual_return=round(result.annual_return, 6),
        sharpe_ratio=round(result.sharpe_ratio, 4),
        max_drawdown=round(result.max_drawdown, 6),
        win_rate=round(result.win_rate, 4),
        trade_count=result.trade_count,
        trades=trades,
    )


@app.post("/api/v1/ml/pipeline", tags=["ML"])
async def run_pipeline(req: PipelineRequest):
    """One-click end-to-end pipeline: factors → labels → select → train → WF → signal."""
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    try:
        return await _strategy_svc.run_pipeline(
            symbol=req.symbol, model_type=req.model_type,
            label_col=req.label_col, forward_period=req.forward_period,
            train_ratio=req.train_ratio,
            wf_train_days=req.wf_train_days, wf_test_days=req.wf_test_days,
            wf_step_days=req.wf_step_days,
            start=req.start, end=req.end, model_params=req.model_params,
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


# ---------- Backtest ----------

@app.post("/api/v1/backtest", response_model=BacktestResponse, tags=["Strategy"])
async def run_backtest(req: BacktestRequest):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    result = await _strategy_svc.run_backtest(
        strategy_id=req.strategy_id,
        symbol=req.symbol,
        start=req.start,
        end=req.end,
        params=req.params,
    )
    from dataclasses import asdict
    trades = [TradeRecord(**asdict(t)) for t in (result.trades or [])]
    return BacktestResponse(
        strategy_id=req.strategy_id,
        symbol=req.symbol,
        total_return=round(result.total_return, 6),
        annual_return=round(result.annual_return, 6),
        sharpe_ratio=round(result.sharpe_ratio, 4),
        max_drawdown=round(result.max_drawdown, 6),
        win_rate=round(result.win_rate, 4),
        trade_count=result.trade_count,
        trades=trades,
    )


@app.get("/api/v1/strategies", tags=["Strategy"])
async def list_strategies():
    from services.strategy_service.main import STRATEGY_CATALOG
    with get_db() as conn:
        cur = conn.execute(
            "SELECT strategy_id, name, status, sharpe, max_dd, win_rate, total_return, updated_at "
            "FROM strategies ORDER BY updated_at DESC"
        )
        db_rows = {r["strategy_id"]: dict(r) for r in cur.fetchall()}
    result = []
    for sid, meta in STRATEGY_CATALOG.items():
        row = db_rows.pop(sid, {})
        result.append({
            "strategy_id": sid,
            "name": meta["name"],
            "description": meta["description"],
            "default_params": meta["default_params"],
            "param_space": {k: list(v) if isinstance(v, tuple) else v for k, v in meta["param_space"].items()},
            "status": row.get("status", "active"),
        })
    for sid, row in db_rows.items():
        result.append(row)
    return {"strategies": result}


class OptimizeRequest(BaseModel):
    strategy_id: str = "ma_cross"
    symbol: str
    start: str = "2025-01-01"
    end: str = Field(default_factory=lambda: date.today().isoformat())
    n_trials: int = Field(30, ge=5, le=200)
    metric: str = "sharpe_ratio"


@app.post("/api/v1/optimize", tags=["Strategy"])
async def optimize_strategy(req: OptimizeRequest):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    try:
        result = await _strategy_svc.optimize_strategy(
            strategy_id=req.strategy_id, symbol=req.symbol,
            start=req.start, end=req.end,
            n_trials=req.n_trials, metric=req.metric,
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/v1/backtest/history", tags=["Strategy"])
async def backtest_history(
    strategy_id: str = Query(None, description="Filter by strategy ID"),
    folder_id: int | None = Query(None, description="Filter by folder ID"),
    limit: int = Query(20, ge=1, le=100),
):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    rows = await _strategy_svc.get_backtest_history(strategy_id, limit, folder_id)
    return {"history": rows}


class StrategyRegisterRequest(BaseModel):
    strategy_id: str
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


@app.post("/api/v1/strategies/register", tags=["Strategy"])
async def register_strategy(req: StrategyRegisterRequest):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.register_strategy(req.strategy_id, req.name, req.params)


@app.put("/api/v1/strategies/{strategy_id}/status", tags=["Strategy"])
async def update_strategy_status(strategy_id: str, status: str = Query(...)):
    if _strategy_svc is None:
        raise HTTPException(503, "StrategyService not available")
    return await _strategy_svc.update_strategy_status(strategy_id, status)


# ---------- Risk Control ----------

class RiskCheckRequest(BaseModel):
    portfolio: dict[str, Any] = Field(default_factory=dict)
    equity_curve: list[float] = Field(default_factory=list)


@app.post("/api/v1/risk/check", tags=["Risk"])
async def risk_check(req: RiskCheckRequest):
    if _risk_svc is None:
        raise HTTPException(503, "RiskService not available")
    pos = await _risk_svc.check_position_risk(req.portfolio) if req.portfolio else {"passed": True, "violations": []}
    dd = await _risk_svc.check_drawdown(req.equity_curve) if req.equity_curve else {"current_dd": 0, "max_dd": 0, "breached": False}
    return {"position_risk": pos, "drawdown": dd}


@app.get("/api/v1/risk/thresholds", tags=["Risk"])
async def risk_thresholds():
    if _risk_svc is None:
        raise HTTPException(503, "RiskService not available")
    t = _risk_svc.RISK_THRESHOLDS
    return {
        "max_drawdown": t.max_drawdown,
        "var_95": t.var_95,
        "concentration": t.concentration,
        "single_stock_limit": t.single_stock_limit,
    }


# ---------- Paper Trading ----------

class PaperAccountRequest(BaseModel):
    account_id: str = "default"
    initial_capital: float = 1_000_000
    commission_rate: float = 0.001
    stop_loss_pct: float = 0.10
    take_profit_pct: float = 0.20


class PaperOrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    account_id: str = "default"
    price: float | None = None


@app.post("/api/v1/paper/accounts", tags=["Paper Trading"])
async def create_paper_account(req: PaperAccountRequest):
    if _paper_svc is None:
        raise HTTPException(503, "PaperTradingService not available")
    return await _paper_svc.create_account(
        req.account_id, req.initial_capital, req.commission_rate, req.stop_loss_pct, req.take_profit_pct,
    )


@app.get("/api/v1/paper/accounts", tags=["Paper Trading"])
async def list_paper_accounts():
    if _paper_svc is None:
        raise HTTPException(503, "PaperTradingService not available")
    return {"accounts": await _paper_svc.list_accounts()}


@app.get("/api/v1/paper/accounts/{account_id}", tags=["Paper Trading"])
async def get_paper_account(account_id: str):
    if _paper_svc is None:
        raise HTTPException(503, "PaperTradingService not available")
    return await _paper_svc.get_account(account_id)


@app.post("/api/v1/paper/accounts/{account_id}/reset", tags=["Paper Trading"])
async def reset_paper_account(account_id: str):
    if _paper_svc is None:
        raise HTTPException(503, "PaperTradingService not available")
    return await _paper_svc.reset_account(account_id)


@app.post("/api/v1/paper/orders", tags=["Paper Trading"])
async def place_paper_order(req: PaperOrderRequest):
    if _paper_svc is None:
        raise HTTPException(503, "PaperTradingService not available")
    return await _paper_svc.place_order(req.symbol, req.side, req.quantity, req.account_id, req.price)


@app.get("/api/v1/paper/orders", tags=["Paper Trading"])
async def list_paper_orders(account_id: str = Query("default"), limit: int = Query(50, ge=1, le=200)):
    if _paper_svc is None:
        raise HTTPException(503, "PaperTradingService not available")
    return {"orders": await _paper_svc.get_orders(account_id, limit)}


# ---------- Watchlist ----------

class WatchlistAddRequest(BaseModel):
    symbol: str
    note: str = ""


_INDEX_ETF_NAME_MAP: dict[str, str] = {}

def _build_index_etf_name_map():
    """Populate name map from INDEX_CODES + ETF_CODES once."""
    if not _INDEX_ETF_NAME_MAP:
        for code, name in INDEX_CODES:
            _INDEX_ETF_NAME_MAP[code] = name
        for code, name in ETF_CODES:
            _INDEX_ETF_NAME_MAP[code] = name


def _is_market_code(sym: str) -> bool:
    """Check if symbol is an index/ETF code (e.g. sh510050, sz399001)."""
    return is_market_symbol(sym)


def _fetch_realtime_qq(codes: list[str]) -> dict[str, dict]:
    """Fetch real-time quote for a list of codes from Tencent Finance API."""
    import requests
    if not codes:
        return {}
    try:
        resp = requests.get(f"http://qt.gtimg.cn/q={','.join(codes)}", timeout=6)
        resp.encoding = "gbk"
        text = resp.text
    except Exception:
        return {}
    out = {}
    for line in text.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        key = line.split("=")[0].replace("v_", "").strip()
        val = line.split("=")[1].strip().strip('"')
        parts = val.split("~")
        if len(parts) < 35:
            continue
        try:
            close = float(parts[3])
            prev_close = float(parts[4])
            chg = close - prev_close
            chg_pct = float(parts[32]) if parts[32] else (chg / prev_close * 100 if prev_close else 0)
            out[key] = {
                "name": parts[1],
                "close": round(close, 4),
                "change": round(chg, 4),
                "change_pct": round(chg_pct, 2),
            }
        except (ValueError, IndexError):
            continue
    return out


@app.get("/api/v1/watchlist", tags=["Watchlist"])
async def get_watchlist():
    _build_index_etf_name_map()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT w.symbol, w.added_at, w.note, s.name, s.industry "
            "FROM watchlist w LEFT JOIN stocks s ON w.symbol = s.symbol "
            "ORDER BY w.added_at DESC"
        ).fetchall()
        result = []
        market_codes = []
        market_indices = []
        for idx, r in enumerate(rows):
            item = dict(r)
            if _is_market_code(r["symbol"]):
                market_codes.append(r["symbol"])
                market_indices.append(idx)
                item["_type"] = "market"
            result.append(item)

        rt_data = {}
        if market_codes:
            rt_data = await asyncio.to_thread(_fetch_realtime_qq, market_codes)

        for i, item in enumerate(result):
            sym = item["symbol"]
            if item.pop("_type", None) == "market":
                rt = rt_data.get(sym, {})
                item["name"] = _INDEX_ETF_NAME_MAP.get(sym, rt.get("name", sym))
                item["industry"] = "ETF" if not sym[2:].startswith("00") else "指数"
                item["close"] = rt.get("close")
                item["change"] = rt.get("change", 0)
                item["change_pct"] = rt.get("change_pct", 0)
            else:
                last = conn.execute(
                    "SELECT close, trade_date FROM daily_quotes WHERE symbol=? ORDER BY trade_date DESC LIMIT 2",
                    (sym,),
                ).fetchall()
                if last:
                    item["close"] = last[0]["close"]
                    item["trade_date"] = last[0]["trade_date"]
                    if len(last) >= 2 and last[1]["close"]:
                        chg = float(last[0]["close"]) - float(last[1]["close"])
                        item["change"] = round(chg, 4)
                        item["change_pct"] = round(chg / float(last[1]["close"]) * 100, 2) if float(last[1]["close"]) else 0
                    else:
                        item["change"] = 0
                        item["change_pct"] = 0
                else:
                    item["close"] = None
                    item["change"] = 0
                    item["change_pct"] = 0

    return {"count": len(result), "items": result}


@app.post("/api/v1/watchlist", tags=["Watchlist"])
async def add_to_watchlist(req: WatchlistAddRequest):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO watchlist (symbol, note, added_at) VALUES (?, ?, datetime('now'))",
            (req.symbol, req.note),
        )
        conn.commit()
    return {"status": "ok", "symbol": req.symbol}


@app.delete("/api/v1/watchlist/{symbol}", tags=["Watchlist"])
async def remove_from_watchlist(symbol: str):
    with get_db() as conn:
        conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
        conn.commit()
    return {"status": "ok", "symbol": symbol}


# ---------- Reports ----------

@app.post("/api/v1/reports/daily", response_model=ReportResponse, tags=["Reports"])
async def generate_daily_report():
    if _report_svc is None:
        raise HTTPException(503, "ReportService not available")
    md = await _report_svc.generate_daily_report()
    return ReportResponse(content=md)


# ---------- Event bus ----------

@app.get("/api/v1/events/channels", tags=["System"])
async def event_channels():
    if _bus is None:
        return {"channels": []}
    return {"channels": _bus.channels}
