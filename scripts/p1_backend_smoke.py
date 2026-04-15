#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    url = f"{client.base_url}{path}"
    print(f"\n==> {method} {url}")
    if clean_params:
        print(f"    params={clean_params}")
    if payload is not None:
        print(f"    payload={json.dumps(payload, ensure_ascii=False)}")
    response = client.request(method, path, params=clean_params or None, json=payload)
    print(f"<== HTTP {response.status_code}")
    response.raise_for_status()
    body = response.json()
    print(json.dumps(body, ensure_ascii=False, indent=2)[:3000])
    return body


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _run_step(results: list[StepResult], name: str, func) -> dict[str, Any] | None:
    try:
        payload = func()
        results.append(StepResult(name=name, ok=True, detail="ok"))
        return payload
    except Exception as exc:
        results.append(StepResult(name=name, ok=False, detail=str(exc)))
        raise


def _default_symbol(asset_type: str | None) -> str:
    return "sh510300" if asset_type == "etf" else "sh000300"


def _write_report(path: str | None, results: list[StepResult], context: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "context": context,
        "results": [asdict(item) for item in results],
        "passed": sum(1 for item in results if item.ok),
        "failed": sum(1 for item in results if not item.ok),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport written to {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backend API checks for the P1 flow.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--asset-type", default="index", choices=["index", "etf", "stock", "all"])
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--profile", default="full", choices=["core", "research", "sector", "full"])
    parser.add_argument("--symbol", default=None, help="Default: sh000300 for index/all, sh510300 for etf")
    parser.add_argument("--sector-symbol", default="sector:银行")
    parser.add_argument("--output-json", default=None, help="Optional path to write a JSON report")
    args = parser.parse_args()

    asset_type = None if args.asset_type == "all" else args.asset_type
    symbol = args.symbol or _default_symbol(asset_type)
    results: list[StepResult] = []
    context = {
        "base_url": args.base_url,
        "profile": args.profile,
        "asset_type": asset_type or "all",
        "start": args.start,
        "end": args.end,
        "symbol": symbol,
        "sector_symbol": args.sector_symbol,
    }

    try:
        with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
            health = _run_step(results, "health", lambda: _request(client, "GET", "/health"))
            _assert(health["status"] == "ok", "health status must be ok")

            universe_bootstrap = _run_step(
                results,
                "universe_bootstrap",
                lambda: _request(client, "POST", "/api/v1/universe/bootstrap"),
            )
            _assert(universe_bootstrap["assets"] >= 10, "expected at least 10 built-in assets")

            if args.profile in {"core", "full", "research"}:
                universe_assets = _run_step(
                    results,
                    "universe_assets",
                    lambda: _request(client, "GET", "/api/v1/universe/assets", params={"limit": 100}),
                )
                _assert(universe_assets["count"] >= 18, "expected built-in universe assets")

                mappings = _run_step(
                    results,
                    "universe_mappings",
                    lambda: _request(
                        client,
                        "GET",
                        "/api/v1/universe/mappings",
                        params={"relation_type": "tracks"},
                    ),
                )
                _assert(mappings["count"] >= 6, "expected ETF tracking mappings")

            if args.profile in {"research", "full"}:
                sync_result = _run_step(
                    results,
                    "universe_sync",
                    lambda: _request(
                        client,
                        "POST",
                        "/api/v1/universe/sync",
                        payload={
                            "asset_type": asset_type,
                            "start": args.start,
                            "end": args.end,
                            "only_active": True,
                            "limit": args.limit,
                        },
                    ),
                )
                _assert(sync_result["count"] >= 1, "expected at least one synced asset")

                statuses = _run_step(
                    results,
                    "universe_statuses",
                    lambda: _request(
                        client,
                        "GET",
                        "/api/v1/universe/statuses",
                        params={"asset_type": asset_type},
                    ),
                )
                _assert(statuses["count"] >= 1, "expected universe statuses")

                breadth_rebuild = _run_step(
                    results,
                    "breadth_rebuild",
                    lambda: _request(
                        client,
                        "POST",
                        "/api/v1/features/breadth/rebuild",
                        payload={"start": args.start, "end": args.end},
                    ),
                )
                _assert(breadth_rebuild["days_processed"] >= 1, "expected breadth rebuild rows")

                breadth_list = _run_step(
                    results,
                    "breadth_list",
                    lambda: _request(
                        client,
                        "GET",
                        "/api/v1/features/breadth",
                        params={"limit": 5},
                    ),
                )
                _assert(breadth_list["count"] >= 1, "expected breadth rows")

                data_info = _run_step(
                    results,
                    "symbol_data_info",
                    lambda: _request(client, "GET", f"/api/v1/data/{symbol}/info"),
                )
                _assert(data_info["count"] >= 1, f"expected stored data for {symbol}")

                factors = _run_step(
                    results,
                    "factor_compute",
                    lambda: _request(client, "GET", f"/api/v1/factors/{symbol}"),
                )
                _assert(factors["rows"] >= 1, f"expected factor rows for {symbol}")

                backtest = _run_step(
                    results,
                    "backtest",
                    lambda: _request(
                        client,
                        "POST",
                        "/api/v1/backtest",
                        payload={
                            "strategy_id": "ma_cross",
                            "symbol": symbol,
                            "start": args.start,
                            "end": args.end,
                            "params": {"fast": 5, "slow": 20},
                        },
                    ),
                )
                _assert(backtest["trade_count"] >= 1, "expected at least one trade in backtest")

            if args.profile in {"sector", "full"}:
                sector_rebuild = _run_step(
                    results,
                    "sector_rebuild",
                    lambda: _request(
                        client,
                        "POST",
                        "/api/v1/universe/sectors/rebuild",
                        params={"market": "A"},
                    ),
                )
                _assert(sector_rebuild["sectors"] >= 1, "expected derived sector assets")

                sector_assets = _run_step(
                    results,
                    "sector_assets",
                    lambda: _request(
                        client,
                        "GET",
                        "/api/v1/universe/assets",
                        params={"asset_type": "sector", "limit": 20},
                    ),
                )
                _assert(sector_assets["count"] >= 1, "expected sector assets")

                sector_constituents = _run_step(
                    results,
                    "sector_constituents",
                    lambda: _request(
                        client,
                        "GET",
                        "/api/v1/universe/sectors/constituents",
                        params={"sector_symbol": args.sector_symbol, "limit": 100},
                    ),
                )
                _assert(sector_constituents["count"] >= 1, "expected sector constituents")

            logs = _run_step(
                results,
                "job_logs",
                lambda: _request(client, "GET", "/api/v1/logs/jobs", params={"limit": 20}),
            )
            _assert(logs["count"] >= 1, "expected job logs")

        passed = sum(1 for item in results if item.ok)
        failed = sum(1 for item in results if not item.ok)
        print("\n=== Summary ===")
        for item in results:
            marker = "PASS" if item.ok else "FAIL"
            print(f"[{marker}] {item.name}: {item.detail}")
        print(f"\nPassed: {passed}, Failed: {failed}")
        _write_report(args.output_json, results, context)
        print("\nP1 backend test suite completed.")
    except Exception:
        passed = sum(1 for item in results if item.ok)
        failed = sum(1 for item in results if not item.ok)
        print("\n=== Summary ===")
        for item in results:
            marker = "PASS" if item.ok else "FAIL"
            print(f"[{marker}] {item.name}: {item.detail}")
        print(f"\nPassed: {passed}, Failed: {failed}")
        _write_report(args.output_json, results, context)
        sys.exit(1)


if __name__ == "__main__":
    main()
