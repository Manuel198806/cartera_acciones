"""Carga y preparación de datos de operaciones."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import streamlit as st

from options_dashboard.config import DATA_DIR, DATA_FILE, DATE_COLUMNS, REQUIRED_COLUMNS


class DataValidationError(Exception):
    """Error cuando faltan columnas mínimas para el dashboard."""


IB_REQUIRED_COLUMNS = {"TradeDate", "Buy/Sell", "Put/Call", "Expiry", "Quantity"}


def list_data_csv_files() -> list[Path]:
    """Lista CSV disponibles en carpeta data."""
    if not DATA_DIR.exists():
        return []
    return sorted([p for p in DATA_DIR.glob("*.csv") if p.is_file()], key=lambda p: p.name.lower())


def resolve_default_data_file() -> Path:
    """Prioriza Consulta.csv; si no existe, usa mock_trades.csv."""
    files = list_data_csv_files()
    by_name = {p.name.lower(): p for p in files}
    if "consulta.csv" in by_name:
        return by_name["consulta.csv"]
    if DATA_FILE.exists():
        return DATA_FILE
    if files:
        return files[0]
    return DATA_FILE


def _parse_ib_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype(str).str.strip(), format="%Y%m%d", errors="coerce")


def _clean_str(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    return df


def normalize_ib_csv(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Convierte export de IB a esquema interno del dashboard."""
    df = df_raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = _clean_str(df)

    # Mantener solo filas operables
    df = df[df["TradeDate"].notna()].copy()
    for col in ["TradeID", "Open/CloseIndicator", "OrigTradeID"]:
        if col not in df.columns:
            df[col] = pd.NA

    df["open_date"] = _parse_ib_date(df["TradeDate"])
    df["expiration"] = _parse_ib_date(df["Expiry"])
    df["close_date"] = pd.NaT

    qty = pd.to_numeric(df.get("Quantity"), errors="coerce").fillna(0)
    multiplier = pd.to_numeric(df.get("Multiplier"), errors="coerce").fillna(100)
    strike = pd.to_numeric(df.get("Strike"), errors="coerce")
    trade_price = pd.to_numeric(df.get("TradePrice"), errors="coerce").fillna(0.0)
    trade_money = pd.to_numeric(df.get("TradeMoney"), errors="coerce").fillna(0.0)
    net_cash = pd.to_numeric(df.get("NetCash"), errors="coerce").fillna(0.0)
    close_price = pd.to_numeric(df.get("ClosePrice"), errors="coerce")

    df["quantity"] = qty.abs()
    df["strike"] = strike.fillna(0.0)
    df["underlying_price"] = close_price.fillna(0.0)
    df["premium"] = trade_price.abs()
    df["commission"] = (trade_money.abs() - net_cash.abs()).abs().fillna(0.0)
    df["unrealized_pnl"] = 0.0
    df["action"] = df["Buy/Sell"].fillna("UNKNOWN").str.upper()
    df["leg_type"] = df["Put/Call"].fillna("UNK").str.upper()
    df["ticker"] = df.get("UnderlyingSymbol", pd.Series(index=df.index, dtype="object")).fillna("UNKNOWN")
    df["strategy_type"] = "Opción simple (IB)"
    df["notes"] = (
        "IB "
        + df.get("OrderType", pd.Series(index=df.index, dtype="object")).fillna("NA")
        + " · "
        + df.get("Description", pd.Series(index=df.index, dtype="object")).fillna("")
    )

    # TradeID puede venir vacío o en notación científica
    raw_trade_id = df["TradeID"].fillna("").astype(str)
    raw_trade_id = raw_trade_id.str.replace(r"\.0$", "", regex=True)
    raw_trade_id = raw_trade_id.apply(
        lambda x: re.sub(r"\D", "", f"{float(x):.0f}") if x and "e" in x.lower() else re.sub(r"\D", "", x)
    )
    fallback_id = pd.Series([f"IB-{i+1:06d}" for i in range(len(df))], index=df.index)
    df["trade_id"] = raw_trade_id.where(raw_trade_id.str.len() > 0, fallback_id)

    contract_key = (
        df["ticker"].astype(str)
        + "-"
        + df["expiration"].dt.strftime("%Y%m%d").fillna("NA")
        + "-"
        + df["strike"].round(4).astype(str)
        + "-"
        + df["leg_type"].astype(str)
    )

    indicator = df["Open/CloseIndicator"].fillna("").str.upper()
    inferred_close = (
        ((df["action"] == "BUY") & (qty < 0))
        | ((df["action"] == "SELL") & (qty > 0))
    )
    close_mask = (indicator == "C") | inferred_close
    open_mask = (indicator == "O") | ~close_mask

    df.loc[close_mask, "close_date"] = df.loc[close_mask, "open_date"]
    df["status"] = "abierta"
    df.loc[close_mask, "status"] = "cerrada"
    df["realized_pnl"] = 0.0
    df.loc[close_mask, "realized_pnl"] = net_cash.loc[close_mask]

    # Vincular cierres con aperturas por ciclo en cada contrato
    cycle = open_mask.groupby(contract_key).cumsum()
    df["strategy_id"] = "IB-" + contract_key + "-C" + cycle.astype(int).astype(str)

    normalized = df[
        [
            "trade_id",
            "strategy_id",
            "ticker",
            "underlying_price",
            "strategy_type",
            "leg_type",
            "action",
            "quantity",
            "strike",
            "expiration",
            "open_date",
            "close_date",
            "premium",
            "commission",
            "realized_pnl",
            "unrealized_pnl",
            "status",
            "notes",
        ]
    ].copy()

    cutoff = pd.Timestamp.utcnow().tz_localize(None) - pd.DateOffset(months=12)
    normalized = normalized[normalized["open_date"] >= cutoff].copy()
    normalized.attrs["source"] = "ib_csv"
    return normalized.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_trades(path: str | None = None) -> pd.DataFrame:
    """Carga el dataset de operaciones y valida campos mínimos."""
    if path:
        file_path = path
    else:
        file_path = str(resolve_default_data_file())

    df = pd.read_csv(file_path, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    if IB_REQUIRED_COLUMNS.issubset(set(df.columns)):
        df = normalize_ib_csv(df)
    else:
        missing = REQUIRED_COLUMNS.difference(df.columns)
        if missing:
            raise DataValidationError(
                f"Faltan columnas requeridas: {', '.join(sorted(missing))}"
            )

        df.attrs["source"] = "standard_csv"

    for col in DATE_COLUMNS:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    numeric_columns = [
        "underlying_price",
        "quantity",
        "strike",
        "premium",
        "commission",
        "realized_pnl",
        "unrealized_pnl",
    ]
    for col in numeric_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df.attrs["detected_columns"] = list(df.columns)
    missing_after = [col for col in REQUIRED_COLUMNS if col not in df.columns or df[col].isna().all()]
    df.attrs["missing_fields"] = sorted(missing_after)
    df.attrs["rows_loaded"] = int(len(df))
    df.attrs["file_path"] = file_path

    return df


def grouped_strategies(df: pd.DataFrame) -> pd.DataFrame:
    """Agrupa legs por estrategia para visualización consolidada."""
    grouped = (
        df.groupby(["strategy_id", "ticker", "strategy_type", "status"], dropna=False)
        .agg(
            open_date=("open_date", "min"),
            close_date=("close_date", "max"),
            expiration=("expiration", "max"),
            legs=("trade_id", "count"),
            premium=("premium", "sum"),
            commission=("commission", "sum"),
            realized_pnl=("realized_pnl", "sum"),
            unrealized_pnl=("unrealized_pnl", "sum"),
            notes=("notes", lambda x: " | ".join(x.dropna().astype(str).head(2))),
        )
        .reset_index()
    )
    grouped["total_pnl"] = grouped["realized_pnl"] + grouped["unrealized_pnl"]
    return grouped.sort_values("open_date", ascending=False)
