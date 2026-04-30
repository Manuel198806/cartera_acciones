"""Read-only Interactive Brokers options data access via ib_insync."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from options_dashboard.async_compat import ensure_event_loop
from options_dashboard.config import BASE_DIR

LOG_PATH = BASE_DIR / "logs" / "options_builder.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("options_builder.ib")
if not logger.handlers:
    handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(module)s.%(funcName)s | %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

ensure_event_loop()
logger.info("Preparing ib_insync import")
try:
    from ib_insync import IB, Option, Stock
    logger.info("ib_insync imported successfully")
except Exception:
    logger.exception("Failed to import ib_insync")
    IB = None
    Option = None
    Stock = None


@dataclass
class IBConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 7496
    client_id: int = 10


_ib: IB | None = None


def nan_to_none(value):
    try:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        if pd.isna(value):
            return None
        return value
    except Exception:
        return value


def _safe_number(value: Any) -> float | None:
    value = nan_to_none(value)
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _ensure_ib_available() -> None:
    if IB is None:
        raise RuntimeError("ib_insync no está instalado. Instala ib_insync para habilitar IB API.")


def connect_ib(host: str = "127.0.0.1", port: int = 7496, client_id: int = 10) -> IB:
    ensure_event_loop()
    global _ib
    _ensure_ib_available()
    if _ib is not None and _ib.isConnected():
        return _ib
    logger.info("Connecting to IB host=%s port=%s client_id=%s", host, port, client_id)
    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=8)
    ib.reqMarketDataType(3)
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
    try:
        ib = connect_ib()
        logger.info("Qualifying stock ticker=%s", ticker)
        contract = Stock(ticker.upper().strip(), "SMART", "USD")
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            raise ValueError(f"No se pudo calificar contrato de subyacente para {ticker}.")
        ticker_obj = ib.reqMktData(qualified[0], "", False, False)
        ib.sleep(1.2)
        price = _safe_number(ticker_obj.marketPrice())
        return {"symbol": qualified[0].symbol, "con_id": qualified[0].conId, "exchange": qualified[0].exchange, "currency": qualified[0].currency, "market_price": price}
    except Exception:
        logger.exception("Error getting underlying ticker=%s", ticker)
        raise


def get_option_chain_metadata(ticker: str) -> dict[str, Any]:
    ensure_event_loop()
    try:
        ib = connect_ib()
        logger.info("reqSecDefOptParams start ticker=%s", ticker)
        under = Stock(ticker.upper().strip(), "SMART", "USD")
        under = ib.qualifyContracts(under)[0]
        chains = ib.reqSecDefOptParams(under.symbol, "", under.secType, under.conId)
        if not chains:
            raise ValueError(f"No se encontró cadena de opciones para {ticker}.")
        chain = next((c for c in chains if c.exchange == "SMART"), chains[0])
        expirations = sorted(chain.expirations)
        strikes = sorted(float(s) for s in chain.strikes)
        logger.info("SMART chain selected ticker=%s expirations=%s strikes=%s", ticker, len(expirations), len(strikes))
        return {"ticker": ticker.upper().strip(), "expirations": expirations, "strikes": strikes, "multiplier": chain.multiplier, "trading_class": chain.tradingClass}
    except Exception:
        logger.exception("Error getting option chain metadata ticker=%s", ticker)
        raise


def get_option_quotes_for_contracts(contracts: list[Any], ticker: str = "", expiry: str = "") -> pd.DataFrame:
    ensure_event_loop()
    try:
        ib = connect_ib()
        if not contracts:
            return pd.DataFrame()
        logger.info("Qualifying option contracts ticker=%s expiry=%s raw_contracts=%s", ticker, expiry, len(contracts))
        qualified = ib.qualifyContracts(*contracts)
        logger.info("Qualified option contracts ticker=%s expiry=%s qualified=%s", ticker, expiry, len(qualified))
        logger.info("Requesting market data ticker=%s expiry=%s", ticker, expiry)
        tickers = [ib.reqMktData(c, "", False, False) for c in qualified]
        ib.sleep(1.5)
        rows = []
        for tk in tickers:
            md = tk.modelGreeks
            bid = _safe_number(tk.bid)
            ask = _safe_number(tk.ask)
            mid = ((bid + ask) / 2) if bid is not None and ask is not None else None
            rows.append({"local_symbol": tk.contract.localSymbol, "con_id": tk.contract.conId, "strike": _safe_number(tk.contract.strike), "expiry": tk.contract.lastTradeDateOrContractMonth, "right": tk.contract.right, "bid": bid, "ask": ask, "last": _safe_number(tk.last), "mid": mid, "market_price": _safe_number(tk.marketPrice()), "iv": _safe_number(getattr(md, "impliedVol", None)) if md else None, "delta": _safe_number(getattr(md, "delta", None)) if md else None, "gamma": _safe_number(getattr(md, "gamma", None)) if md else None, "theta": _safe_number(getattr(md, "theta", None)) if md else None, "vega": _safe_number(getattr(md, "vega", None)) if md else None, "volume": _safe_number(tk.volume), "open_interest": _safe_number(getattr(tk, "callOpenInterest", None) or getattr(tk, "putOpenInterest", None))})
        return pd.DataFrame(rows)
    except Exception:
        logger.exception("Error getting option quotes ticker=%s expiry=%s", ticker, expiry)
        raise


def get_filtered_option_chain(ticker: str, expiry: str, underlying_price: float | None = None, strike_range_pct: float = 0.20) -> pd.DataFrame:
    ensure_event_loop()
    try:
        metadata = get_option_chain_metadata(ticker)
        logger.info("Filtering expirations ticker=%s expiry=%s total_expirations=%s", ticker, expiry, len(metadata["expirations"]))
        if underlying_price is None:
            underlying_price = get_underlying_contract(ticker).get("market_price")
        if underlying_price is None:
            if not metadata["strikes"]:
                raise ValueError("No hay strikes disponibles para construir la cadena filtrada.")
            underlying_price = float(pd.Series(metadata["strikes"]).median())
            logger.warning(
                "Underlying price missing; using strikes median fallback ticker=%s expiry=%s fallback_price=%s",
                ticker,
                expiry,
                underlying_price,
            )
        lo = underlying_price * (1 - strike_range_pct)
        hi = underlying_price * (1 + strike_range_pct)
        strikes = [s for s in metadata["strikes"] if lo <= s <= hi]
        if not strikes:
            strikes = sorted(metadata["strikes"], key=lambda x: abs(x - underlying_price))[:10]
            logger.warning(
                "No strikes in pct range; using nearest strikes fallback ticker=%s expiry=%s fallback_count=%s",
                ticker,
                expiry,
                len(strikes),
            )
        logger.info("Filtering strikes ticker=%s expiry=%s strike_range=%s-%s strikes_found=%s", ticker, expiry, lo, hi, len(strikes))
        contracts = [Option(symbol=ticker.upper().strip(), lastTradeDateOrContractMonth=expiry, strike=float(strike), right=right, exchange="SMART", currency="USD") for right in ("C", "P") for strike in strikes]
        return get_option_quotes_for_contracts(contracts, ticker=ticker, expiry=expiry)
    except Exception:
        logger.exception("Error in filtered chain ticker=%s expiry=%s strike_range_pct=%s", ticker, expiry, strike_range_pct)
        raise


def get_open_option_positions() -> pd.DataFrame:
    ensure_event_loop()
    try:
        ib = connect_ib()
        positions = ib.positions()
        rows = []
        for pos in positions:
            c = pos.contract
            if getattr(c, "secType", "") != "OPT":
                continue
            rows.append({"account": pos.account, "ticker": c.symbol, "con_id": c.conId, "local_symbol": c.localSymbol, "expiry": c.lastTradeDateOrContractMonth, "strike": c.strike, "right": c.right, "position": pos.position, "avg_cost": pos.avgCost})
        return pd.DataFrame(rows)
    except Exception:
        logger.exception("Error getting open option positions")
        raise
