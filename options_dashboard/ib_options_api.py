"""Read-only Interactive Brokers options data access via ib_insync."""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from options_dashboard.async_compat import ensure_event_loop

ensure_event_loop()
try:
    from ib_insync import IB, Option, Stock, util
except Exception:  # pragma: no cover - optional dependency at runtime
    IB = None
    Option = None
    Stock = None
    util = None

logger = logging.getLogger(__name__)


@dataclass
class IBConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 7496
    client_id: int = 10


_ib: IB | None = None


def _ensure_asyncio_loop() -> None:
    ensure_event_loop()


def _ensure_ib_available() -> None:
    if IB is None:
        raise RuntimeError("ib_insync no está instalado. Instala ib_insync para habilitar IB API.")


def connect_ib(host: str = "127.0.0.1", port: int = 7496, client_id: int = 10) -> IB:
    """Connect to IB Gateway/TWS in read-only usage mode."""
    ensure_event_loop()
    global _ib
    _ensure_ib_available()
    if _ib is not None and _ib.isConnected():
        return _ib

    _ensure_asyncio_loop()
    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=8)
    ib.reqMarketDataType(3)  # delayed/frozen fallback when live subs unavailable
    _ib = ib
    return ib


def disconnect_ib() -> None:
    ensure_event_loop()
    global _ib
    if _ib is not None and _ib.isConnected():
        _ib.disconnect()
    _ib = None


def get_underlying_contract(ticker: str) -> dict[str, Any]:
    ensure_event_loop()
    ib = connect_ib()
    contract = Stock(ticker.upper().strip(), "SMART", "USD")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        raise ValueError(f"No se pudo calificar contrato de subyacente para {ticker}.")
    ticker_obj = ib.reqMktData(qualified[0], "", False, False)
    ib.sleep(1.2)
    price = util.nanToNone(ticker_obj.marketPrice())
    return {
        "symbol": qualified[0].symbol,
        "con_id": qualified[0].conId,
        "exchange": qualified[0].exchange,
        "currency": qualified[0].currency,
        "market_price": price,
    }


def get_option_chain_metadata(ticker: str) -> dict[str, Any]:
    ensure_event_loop()
    ib = connect_ib()
    under = Stock(ticker.upper().strip(), "SMART", "USD")
    under = ib.qualifyContracts(under)[0]
    chains = ib.reqSecDefOptParams(under.symbol, "", under.secType, under.conId)
    if not chains:
        raise ValueError(f"No se encontró cadena de opciones para {ticker}.")
    chain = next((c for c in chains if c.exchange == "SMART"), chains[0])
    expirations = sorted(chain.expirations)
    strikes = sorted(float(s) for s in chain.strikes)
    return {
        "ticker": ticker.upper().strip(),
        "expirations": expirations,
        "strikes": strikes,
        "multiplier": chain.multiplier,
        "trading_class": chain.tradingClass,
    }


def _safe_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except Exception:
        return None
    if math.isnan(f):
        return None
    return f


def get_option_quotes_for_contracts(contracts: list[Any]) -> pd.DataFrame:
    ensure_event_loop()
    ib = connect_ib()
    if not contracts:
        return pd.DataFrame()
    qualified = ib.qualifyContracts(*contracts)
    tickers = [ib.reqMktData(c, "", False, False) for c in qualified]
    ib.sleep(1.5)

    rows = []
    for tk in tickers:
        md = tk.modelGreeks
        bid = _safe_number(tk.bid)
        ask = _safe_number(tk.ask)
        mid = ((bid + ask) / 2) if bid is not None and ask is not None else None
        rows.append(
            {
                "local_symbol": tk.contract.localSymbol,
                "con_id": tk.contract.conId,
                "strike": _safe_number(tk.contract.strike),
                "expiry": tk.contract.lastTradeDateOrContractMonth,
                "right": tk.contract.right,
                "bid": bid,
                "ask": ask,
                "last": _safe_number(tk.last),
                "mid": mid,
                "market_price": _safe_number(tk.marketPrice()),
                "iv": _safe_number(getattr(md, "impliedVol", None)) if md else None,
                "delta": _safe_number(getattr(md, "delta", None)) if md else None,
                "gamma": _safe_number(getattr(md, "gamma", None)) if md else None,
                "theta": _safe_number(getattr(md, "theta", None)) if md else None,
                "vega": _safe_number(getattr(md, "vega", None)) if md else None,
                "volume": _safe_number(tk.volume),
                "open_interest": _safe_number(getattr(tk, "callOpenInterest", None) or getattr(tk, "putOpenInterest", None)),
            }
        )
    return pd.DataFrame(rows)


def get_filtered_option_chain(
    ticker: str,
    expiry: str,
    underlying_price: float | None = None,
    strike_range_pct: float = 0.20,
) -> pd.DataFrame:
    ensure_event_loop()
    metadata = get_option_chain_metadata(ticker)
    if underlying_price is None:
        underlying_price = get_underlying_contract(ticker).get("market_price")
    if underlying_price is None:
        raise ValueError("No se pudo obtener el precio del subyacente para filtrar strikes.")

    lo = underlying_price * (1 - strike_range_pct)
    hi = underlying_price * (1 + strike_range_pct)
    strikes = [s for s in metadata["strikes"] if lo <= s <= hi]
    contracts = []
    for right in ("C", "P"):
        for strike in strikes:
            contracts.append(
                Option(
                    symbol=ticker.upper().strip(),
                    lastTradeDateOrContractMonth=expiry,
                    strike=float(strike),
                    right=right,
                    exchange="SMART",
                    currency="USD",
                )
            )
    return get_option_quotes_for_contracts(contracts)


def get_open_option_positions() -> pd.DataFrame:
    ensure_event_loop()
    ib = connect_ib()
    positions = ib.positions()
    rows = []
    for pos in positions:
        c = pos.contract
        if getattr(c, "secType", "") != "OPT":
            continue
        rows.append(
            {
                "account": pos.account,
                "ticker": c.symbol,
                "con_id": c.conId,
                "local_symbol": c.localSymbol,
                "expiry": c.lastTradeDateOrContractMonth,
                "strike": c.strike,
                "right": c.right,
                "position": pos.position,
                "avg_cost": pos.avgCost,
            }
        )
    return pd.DataFrame(rows)
