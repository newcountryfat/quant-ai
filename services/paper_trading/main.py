"""Paper Trading Service — simulated order execution against live/historical prices."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from loguru import logger

from core.config import settings
from core.db import get_db
from core.event_bus import Event, LocalEventBus


@dataclass
class Position:
    symbol: str
    shares: float = 0.0
    avg_cost: float = 0.0
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def pnl(self) -> float:
        return self.shares * (self.current_price - self.avg_cost)

    @property
    def pnl_pct(self) -> float:
        if self.avg_cost <= 0:
            return 0.0
        return (self.current_price - self.avg_cost) / self.avg_cost


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str  # buy / sell
    quantity: float
    price: float
    status: str = "pending"  # pending / filled / rejected
    filled_at: str = ""
    reason: str = ""


@dataclass
class PaperAccount:
    account_id: str = "default"
    initial_capital: float = 1_000_000.0
    cash: float = 1_000_000.0
    positions: dict[str, Position] = field(default_factory=dict)
    orders: list[Order] = field(default_factory=list)
    commission_rate: float = 0.001
    stop_loss_pct: float = 0.10
    take_profit_pct: float = 0.20

    @property
    def equity(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())

    @property
    def total_return(self) -> float:
        return (self.equity / self.initial_capital) - 1.0

    def to_summary(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "equity": round(self.equity, 2),
            "total_return": round(self.total_return, 6),
            "positions": {sym: asdict(p) for sym, p in self.positions.items()},
            "open_orders": len([o for o in self.orders if o.status == "pending"]),
            "filled_orders": len([o for o in self.orders if o.status == "filled"]),
        }


class PaperTradingService:
    def __init__(self, bus: LocalEventBus) -> None:
        self._bus = bus
        self._accounts: dict[str, PaperAccount] = {}
        self._order_seq = 0
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._bus.on("strategy.signal", self._on_signal)
        self._started = True
        self._load_accounts()
        logger.info("PaperTradingService started, accounts={}", len(self._accounts))

    def _load_accounts(self) -> None:
        try:
            with get_db() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS paper_accounts ("
                    "  account_id TEXT PRIMARY KEY,"
                    "  data_json TEXT NOT NULL,"
                    "  updated_at TEXT NOT NULL"
                    ")"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS paper_orders ("
                    "  order_id TEXT PRIMARY KEY,"
                    "  account_id TEXT NOT NULL,"
                    "  symbol TEXT NOT NULL,"
                    "  side TEXT NOT NULL,"
                    "  quantity REAL NOT NULL,"
                    "  price REAL NOT NULL,"
                    "  status TEXT NOT NULL,"
                    "  filled_at TEXT,"
                    "  reason TEXT,"
                    "  created_at TEXT NOT NULL"
                    ")"
                )
                conn.commit()
                rows = conn.execute("SELECT account_id, data_json FROM paper_accounts").fetchall()
                for r in rows:
                    data = json.loads(r["data_json"])
                    acct = PaperAccount(
                        account_id=r["account_id"],
                        initial_capital=data.get("initial_capital", 1_000_000),
                        cash=data.get("cash", 1_000_000),
                        commission_rate=data.get("commission_rate", 0.001),
                        stop_loss_pct=data.get("stop_loss_pct", 0.10),
                        take_profit_pct=data.get("take_profit_pct", 0.20),
                    )
                    for sym, pos_data in data.get("positions", {}).items():
                        acct.positions[sym] = Position(**pos_data)
                    self._accounts[acct.account_id] = acct
        except Exception:
            logger.exception("Failed to load paper accounts")

    def _save_account(self, acct: PaperAccount) -> None:
        data = {
            "initial_capital": acct.initial_capital,
            "cash": acct.cash,
            "commission_rate": acct.commission_rate,
            "stop_loss_pct": acct.stop_loss_pct,
            "take_profit_pct": acct.take_profit_pct,
            "positions": {sym: asdict(p) for sym, p in acct.positions.items()},
        }
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO paper_accounts (account_id, data_json, updated_at) VALUES (?,?,?)",
                    (acct.account_id, json.dumps(data), datetime.now().isoformat()),
                )
                conn.commit()
        except Exception:
            logger.warning("Failed to persist paper account {}", acct.account_id)

    def _save_order(self, acct: PaperAccount, order: Order) -> None:
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO paper_orders "
                    "(order_id, account_id, symbol, side, quantity, price, status, filled_at, reason, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (order.order_id, acct.account_id, order.symbol, order.side,
                     order.quantity, order.price, order.status, order.filled_at, order.reason,
                     datetime.now().isoformat()),
                )
                conn.commit()
        except Exception:
            logger.warning("Failed to persist paper order {}", order.order_id)

    # --- account management ---

    async def create_account(
        self, account_id: str = "default", initial_capital: float = 1_000_000,
        commission_rate: float = 0.001, stop_loss_pct: float = 0.10, take_profit_pct: float = 0.20,
    ) -> dict[str, Any]:
        acct = PaperAccount(
            account_id=account_id, initial_capital=initial_capital, cash=initial_capital,
            commission_rate=commission_rate, stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct,
        )
        self._accounts[account_id] = acct
        self._save_account(acct)
        return acct.to_summary()

    async def get_account(self, account_id: str = "default") -> dict[str, Any]:
        acct = self._accounts.get(account_id)
        if not acct:
            return await self.create_account(account_id)
        return acct.to_summary()

    async def list_accounts(self) -> list[dict[str, Any]]:
        return [a.to_summary() for a in self._accounts.values()]

    async def reset_account(self, account_id: str = "default") -> dict[str, Any]:
        acct = self._accounts.get(account_id)
        if not acct:
            return await self.create_account(account_id)
        acct.cash = acct.initial_capital
        acct.positions.clear()
        acct.orders.clear()
        self._save_account(acct)
        return acct.to_summary()

    # --- order execution ---

    def _next_order_id(self) -> str:
        self._order_seq += 1
        return f"PT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self._order_seq:04d}"

    def _get_latest_price(self, symbol: str) -> float | None:
        try:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT close FROM daily_quotes WHERE symbol=? ORDER BY trade_date DESC LIMIT 1",
                    (symbol,),
                ).fetchone()
                return float(row["close"]) if row else None
        except Exception:
            return None

    async def place_order(
        self, symbol: str, side: str, quantity: float,
        account_id: str = "default", price: float | None = None,
    ) -> dict[str, Any]:
        acct = self._accounts.get(account_id)
        if not acct:
            acct = PaperAccount(account_id=account_id)
            self._accounts[account_id] = acct

        if price is None:
            price = self._get_latest_price(symbol)
        if price is None or price <= 0:
            order = Order(self._next_order_id(), symbol, side, quantity, 0, "rejected", reason="price unavailable")
            acct.orders.append(order)
            self._save_order(acct, order)
            return asdict(order)

        order = Order(self._next_order_id(), symbol, side, quantity, price)
        cost = price * quantity
        commission = cost * acct.commission_rate

        if side == "buy":
            total_cost = cost + commission
            if total_cost > acct.cash:
                order.status = "rejected"
                order.reason = f"insufficient cash: need {total_cost:.2f}, have {acct.cash:.2f}"
            else:
                acct.cash -= total_cost
                pos = acct.positions.get(symbol, Position(symbol=symbol))
                new_shares = pos.shares + quantity
                pos.avg_cost = ((pos.avg_cost * pos.shares) + cost) / new_shares if new_shares > 0 else price
                pos.shares = new_shares
                pos.current_price = price
                acct.positions[symbol] = pos
                order.status = "filled"
                order.filled_at = datetime.now().isoformat()
        elif side == "sell":
            pos = acct.positions.get(symbol)
            if not pos or pos.shares < quantity:
                order.status = "rejected"
                order.reason = f"insufficient shares: need {quantity}, have {pos.shares if pos else 0}"
            else:
                acct.cash += cost - commission
                pos.shares -= quantity
                pos.current_price = price
                if pos.shares <= 0:
                    del acct.positions[symbol]
                order.status = "filled"
                order.filled_at = datetime.now().isoformat()
        else:
            order.status = "rejected"
            order.reason = f"unknown side: {side}"

        acct.orders.append(order)
        self._save_order(acct, order)
        self._save_account(acct)

        if order.status == "filled":
            await self._bus.publish("paper.order.filled", {
                "account_id": account_id, "order_id": order.order_id,
                "symbol": symbol, "side": side, "quantity": quantity, "price": price,
            })

        return asdict(order)

    async def get_orders(self, account_id: str = "default", limit: int = 50) -> list[dict]:
        try:
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT * FROM paper_orders WHERE account_id=? ORDER BY created_at DESC LIMIT ?",
                    (account_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            acct = self._accounts.get(account_id)
            if acct:
                return [asdict(o) for o in acct.orders[-limit:]]
            return []

    # --- event-driven auto-trading ---

    async def _on_signal(self, event: Event) -> None:
        sig = event.payload
        if not isinstance(sig, dict) or "symbol" not in sig:
            return
        symbol = sig["symbol"]
        signal_val = sig.get("signal", 0)
        if signal_val == 0:
            return
        side = "buy" if signal_val > 0 else "sell"
        acct = self._accounts.get("default")
        if not acct:
            return
        qty = 100
        try:
            await self.place_order(symbol, side, qty)
            logger.info("Paper auto-trade: {} {} x{}", side, symbol, qty)
        except Exception:
            logger.warning("Paper auto-trade failed for {}", symbol)