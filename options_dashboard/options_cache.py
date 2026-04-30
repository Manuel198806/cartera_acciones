from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from options_dashboard.config import DATA_DIR

DB_PATH = DATA_DIR / "options_cache.sqlite"


def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS option_chain_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT, underlying_price REAL, expiry TEXT, strike REAL, right TEXT,
                local_symbol TEXT, con_id INTEGER, bid REAL, ask REAL, last REAL, mid REAL,
                market_price REAL, iv REAL, delta REAL, gamma REAL, theta REAL, vega REAL,
                volume REAL, open_interest REAL, updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_strategy_simulations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT, ticker TEXT, expiry TEXT, underlying_price REAL,
                net_credit REAL, max_profit REAL, max_loss REAL, breakeven_low REAL,
                breakeven_high REAL, notes TEXT, created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id INTEGER, action TEXT, quantity REAL, right TEXT, strike REAL,
                expiry TEXT, bid REAL, ask REAL, mid REAL, selected_price REAL,
                con_id INTEGER, local_symbol TEXT
            )
            """
        )


def get_cached_chain(ticker: str, expiry: str, max_age_minutes: int = 5) -> pd.DataFrame:
    with _conn() as conn:
        query = """
            SELECT * FROM option_chain_cache
            WHERE ticker=? AND expiry=?
              AND datetime(updated_at) >= datetime('now', ?)
            ORDER BY strike, right
        """
        df = pd.read_sql_query(query, conn, params=[ticker.upper(), expiry, f"-{max_age_minutes} minutes"])
    return df


def upsert_chain(ticker: str, expiry: str, underlying_price: float, df: pd.DataFrame) -> None:
    if df.empty:
        return
    payload = df.copy()
    payload["ticker"] = ticker.upper()
    payload["underlying_price"] = underlying_price
    payload["updated_at"] = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        conn.execute("DELETE FROM option_chain_cache WHERE ticker=? AND expiry=?", [ticker.upper(), expiry])
        payload.to_sql("option_chain_cache", conn, if_exists="append", index=False)
