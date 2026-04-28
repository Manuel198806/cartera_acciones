"""Carga y preparación de datos de operaciones."""
from __future__ import annotations

import re
from io import BytesIO
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
import streamlit as st

from options_dashboard.config import DATA_FILE, DATE_COLUMNS, REQUIRED_COLUMNS


class DataValidationError(Exception):
    """Error cuando faltan columnas mínimas para el dashboard."""


@st.cache_data(show_spinner=False)
def load_trades(path: str | None = None) -> pd.DataFrame:
    """Carga el dataset de operaciones y valida campos mínimos."""
    file_path = path or str(DATA_FILE)
    df = pd.read_csv(file_path)

    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise DataValidationError(
            f"Faltan columnas requeridas: {', '.join(sorted(missing))}"
        )

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


def _first_present_column(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    for candidate in candidates:
        if candidate in df.columns:
            return df[candidate]
    return pd.Series([None] * len(df), index=df.index)


def _extract_option_fields(description: str) -> tuple[float | None, str | None]:
    if not isinstance(description, str):
        return None, None
    strike_match = re.search(r"(\d+(?:\.\d+)?)\s*([CP])\b", description)
    if not strike_match:
        return None, None
    strike = float(strike_match.group(1))
    leg = "CALL" if strike_match.group(2) == "C" else "PUT"
    return strike, leg


def normalize_ib_trades(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza CSV de IB/Flex hacia el esquema del dashboard."""
    if raw_df.empty:
        return pd.DataFrame(columns=sorted(REQUIRED_COLUMNS))

    df = raw_df.copy()

    trade_id = _first_present_column(df, ["TradeID", "Trade Id", "trade_id"]).astype(str)
    strategy_id = _first_present_column(df, ["OrderReference", "Strategy", "order_ref"]).astype(str)
    ticker = _first_present_column(df, ["UnderlyingSymbol", "Symbol", "ticker"]).astype(str).str.upper()
    description = _first_present_column(df, ["Description", "description"]).fillna("")
    strike_source = pd.to_numeric(_first_present_column(df, ["Strike", "strike"]), errors="coerce")
    right_source = _first_present_column(df, ["Right", "Put/Call", "right"]).astype(str).str.upper()
    quantity = pd.to_numeric(_first_present_column(df, ["Quantity", "quantity"]), errors="coerce").fillna(0)
    action = _first_present_column(df, ["Buy/Sell", "BuySell", "action"]).astype(str).str.upper()
    expiration = pd.to_datetime(_first_present_column(df, ["Expiry", "Expiration", "expiry"]), errors="coerce")
    open_date = pd.to_datetime(_first_present_column(df, ["TradeDate", "OpenDate", "open_date"]), errors="coerce")
    close_date = pd.to_datetime(_first_present_column(df, ["CloseDate", "close_date"]), errors="coerce")
    premium = pd.to_numeric(_first_present_column(df, ["Proceeds", "premium"]), errors="coerce").fillna(0.0)
    commission = pd.to_numeric(_first_present_column(df, ["IBCommission", "Comm/Fee", "commission"]), errors="coerce").fillna(0.0)
    realized_pnl = pd.to_numeric(_first_present_column(df, ["FifoPnlRealized", "Realized P/L", "realized_pnl"]), errors="coerce").fillna(0.0)
    unrealized_pnl = pd.to_numeric(_first_present_column(df, ["MtmPnl", "Unrealized P/L", "unrealized_pnl"]), errors="coerce").fillna(0.0)

    inferred = description.apply(_extract_option_fields)
    inferred_strike = inferred.apply(lambda value: value[0])
    inferred_leg = inferred.apply(lambda value: value[1])
    strike = strike_source.fillna(inferred_strike).fillna(0.0)
    leg_type = right_source.replace({"C": "CALL", "P": "PUT"})
    leg_type = leg_type.where(leg_type.isin(["CALL", "PUT"]), inferred_leg).fillna("PUT")

    strategy_id = strategy_id.replace({"None": "", "nan": ""})
    strategy_id = strategy_id.where(strategy_id.str.len() > 0, trade_id)
    strategy_type = _first_present_column(df, ["StrategyType", "strategy_type"]).fillna("IB_IMPORT")
    status = _first_present_column(df, ["status", "Status"]).fillna("")
    status = status.where(status.str.len() > 0, close_date.notna().map({True: "cerrada", False: "abierta"}))
    underlying_price = pd.to_numeric(_first_present_column(df, ["UnderlyingPrice", "underlying_price"]), errors="coerce").fillna(0.0)
    notes = _first_present_column(df, ["Notes", "notes"]).fillna("Importado desde IB")

    normalized = pd.DataFrame(
        {
            "trade_id": trade_id.where(trade_id.str.len() > 0, "IB-UNKNOWN"),
            "strategy_id": strategy_id,
            "ticker": ticker,
            "underlying_price": underlying_price,
            "strategy_type": strategy_type,
            "leg_type": leg_type,
            "action": action.where(action.isin(["BUY", "SELL"]), "SELL"),
            "quantity": quantity.abs(),
            "strike": strike,
            "expiration": expiration,
            "open_date": open_date,
            "close_date": close_date,
            "premium": premium,
            "commission": commission.abs(),
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "status": status,
            "notes": notes,
        }
    )
    normalized = normalized.dropna(subset=["ticker", "open_date"], how="any")
    normalized["ticker"] = normalized["ticker"].str.replace(r"[^A-Z.]", "", regex=True)
    normalized["trade_id"] = normalized["trade_id"].astype(str)
    missing = REQUIRED_COLUMNS.difference(normalized.columns)
    if missing:
        raise DataValidationError(f"No se pudieron mapear columnas requeridas: {', '.join(sorted(missing))}")
    return normalized[list(REQUIRED_COLUMNS)].copy()


def download_ib_flex_csv(token: str, query_id: str) -> pd.DataFrame:
    """Descarga trades desde Flex Web Service de Interactive Brokers."""
    if not token or not query_id:
        raise DataValidationError("Token y Query ID son obligatorios para descargar de IB.")

    base = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService."
    request_url = f"{base}SendRequest?{urlencode({'t': token, 'q': query_id, 'v': 3})}"
    with urlopen(request_url, timeout=30) as response:
        send_xml = response.read().decode("utf-8", errors="ignore")

    ref_match = re.search(r"<ReferenceCode>([^<]+)</ReferenceCode>", send_xml)
    if not ref_match:
        error_msg = re.search(r"<ErrorMessage>([^<]+)</ErrorMessage>", send_xml)
        detail = error_msg.group(1) if error_msg else "No se obtuvo ReferenceCode."
        raise DataValidationError(f"IB SendRequest falló: {detail}")
    reference_code = ref_match.group(1)

    get_url = f"{base}GetStatement?{urlencode({'t': token, 'q': reference_code, 'v': 3})}"
    with urlopen(get_url, timeout=30) as response:
        csv_bytes = response.read()

    raw_df = pd.read_csv(BytesIO(csv_bytes))
    return raw_df
