"""Carga y preparación de datos de operaciones."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import streamlit as st

from options_dashboard.config import DATA_DIR, DATA_FILE, DATE_COLUMNS, MASTER_DATA_FILE, REQUIRED_COLUMNS, STRATEGY_TAGS_FILE


class DataValidationError(Exception):
    """Error cuando faltan columnas mínimas para el dashboard."""


IB_REQUIRED_COLUMNS = {"TradeDate", "Buy/Sell", "Put/Call", "Expiry", "Quantity"}


def list_data_csv_files() -> list[Path]:
    """Lista CSV disponibles en carpeta data."""
    if not DATA_DIR.exists():
        return []
    return sorted([p for p in DATA_DIR.glob("*.csv") if p.is_file()], key=lambda p: p.name.lower())


def resolve_default_data_file() -> Path:
    """Prioridad: Consulta_master.csv -> Consulta.csv -> mock_trades.csv."""
    files = list_data_csv_files()
    by_name = {p.name.lower(): p for p in files}
    if MASTER_DATA_FILE.exists():
        return MASTER_DATA_FILE
    if "consulta.csv" in by_name:
        return by_name["consulta.csv"]
    if DATA_FILE.exists():
        return DATA_FILE
    if files:
        return files[0]
    return DATA_FILE


def _parse_ib_date(series: pd.Series) -> pd.Series:
    raw = series.astype(str).str.strip()
    parsed = pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
    missing = parsed.isna()
    if missing.any():
        parsed_alt = pd.to_datetime(raw[missing], format="%d-%m-%y", errors="coerce")
        parsed.loc[missing] = parsed_alt
    missing = parsed.isna()
    if missing.any():
        parsed_alt = pd.to_datetime(raw[missing], format="%d/%m/%Y", errors="coerce")
        parsed.loc[missing] = parsed_alt
    return parsed


def _extract_strike_from_description(description: pd.Series) -> pd.Series:
    text = description.fillna("").astype(str).str.upper()
    extracted = text.str.extract(r"\s(-?\d+(?:\.\d+)?)\s[CP]\s*$", expand=False)
    return pd.to_numeric(extracted, errors="coerce")


def _clean_str(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    return df


def normalize_ib_csv(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Convierte export de IB a esquema interno del dashboard."""
    raw_rows_count = int(len(df_raw))
    df = df_raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = _clean_str(df)

    # Mantener solo opciones con TradeID válido
    for col in ["TradeID", "Open/CloseIndicator", "OrigTradeID", "AssetClass", "Description"]:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[df["AssetClass"].fillna("").str.upper() == "OPT"].copy()
    trade_id_raw = df["TradeID"].fillna("").astype(str).str.strip()
    df = df[trade_id_raw.ne("")].copy()
    df = df[df["TradeDate"].notna()].copy()

    for col in ["TradeID", "Open/CloseIndicator", "OrigTradeID"]:
        if col not in df.columns:
            df[col] = pd.NA

    df["open_date"] = _parse_ib_date(df["TradeDate"])
    df["expiration"] = _parse_ib_date(df["Expiry"])

    qty = pd.to_numeric(df.get("Quantity"), errors="coerce").fillna(0.0)
    multiplier = pd.to_numeric(df.get("Multiplier"), errors="coerce").fillna(100.0)
    strike = _extract_strike_from_description(df.get("Description", pd.Series(index=df.index, dtype="object")))
    net_cash = pd.to_numeric(df.get("NetCash"), errors="coerce").fillna(0.0)
    leg_type_mapped = df["Put/Call"].fillna("").str.upper().map({"C": "CALL", "P": "PUT"}).fillna("UNKNOWN")
    open_close = df["Open/CloseIndicator"].fillna("").str.upper().map({"O": "OPENING", "C": "CLOSING"}).fillna("UNKNOWN")

    df["quantity"] = qty
    df["quantity_abs"] = qty.abs()
    df["strike"] = strike
    df["net_cash"] = net_cash
    df["action"] = df["Buy/Sell"].fillna("UNKNOWN").str.upper()
    df["leg_type"] = leg_type_mapped
    df["open_close_indicator"] = open_close
    df["ticker"] = df.get("UnderlyingSymbol", pd.Series(index=df.index, dtype="object")).fillna("UNKNOWN")
    df["description"] = df.get("Description", pd.Series(index=df.index, dtype="object")).fillna("")
    df["asset"] = "OPTION"

    # TradeID puede venir vacío o en notación científica
    raw_trade_id = df["TradeID"].fillna("").astype(str)
    raw_trade_id = raw_trade_id.str.replace(r"\.0$", "", regex=True)
    raw_trade_id = raw_trade_id.apply(
        lambda x: re.sub(r"\D", "", f"{float(x):.0f}") if x and "e" in x.lower() else re.sub(r"\D", "", x)
    )
    df["trade_id"] = raw_trade_id
    df = df[df["trade_id"].str.len() > 0].copy()

    normalized_ib = df[
        [
            "trade_id",
            "OrigTradeID",
            "ticker",
            "description",
            "asset",
            "leg_type",
            "action",
            "open_close_indicator",
            "open_date",
            "expiration",
            "strike",
            "quantity",
            "quantity_abs",
            "Multiplier",
            "net_cash",
        ]
    ].rename(columns={"OrigTradeID": "orig_trade_id", "Multiplier": "multiplier"})

    normalized_ib["contract_key"] = (
        normalized_ib["ticker"].astype(str)
        + "|"
        + normalized_ib["leg_type"].astype(str)
        + "|"
        + normalized_ib["strike"].round(4).astype(str)
        + "|"
        + normalized_ib["expiration"].dt.strftime("%Y-%m-%d").fillna("NA")
    )

    contract_results = (
        normalized_ib.groupby("contract_key", dropna=False, as_index=False)
        .agg(
            ticker=("ticker", "first"),
            leg_type=("leg_type", "first"),
            strike=("strike", "first"),
            expiration=("expiration", "first"),
            net_quantity=("quantity", "sum"),
            net_cash_total=("net_cash", "sum"),
        )
    )
    contract_results["position_status"] = contract_results["net_quantity"].apply(
        lambda x: "CLOSED" if abs(x) < 1e-9 else "OPEN"
    )
    contract_results["realized_pnl"] = contract_results["net_cash_total"].where(
        contract_results["position_status"] == "CLOSED", 0.0
    )
    contract_results["pending_cash"] = contract_results["net_cash_total"].where(
        contract_results["position_status"] == "OPEN", 0.0
    )

    # Detección automática de estrategias con legs OPENING por ticker/open_date/expiration.
    opening = normalized_ib[normalized_ib["open_close_indicator"] == "OPENING"].copy()
    auto_assignments: dict[str, tuple[str, str]] = {}
    audit_rows: list[dict] = []

    def _pick(g: pd.DataFrame, leg_type: str, action: str, mode: str) -> pd.Series | None:
        subset = g[(g["leg_type"] == leg_type) & (g["action"] == action)].sort_values("strike")
        if subset.empty:
            return None
        return subset.iloc[0] if mode == "min" else subset.iloc[-1]

    for (ticker, open_date, expiration), group in opening.groupby(["ticker", "open_date", "expiration"], dropna=False):
        sc = _pick(group, "CALL", "SELL", "min")
        lc = _pick(group, "CALL", "BUY", "max")
        sp = _pick(group, "PUT", "SELL", "max")
        lp = _pick(group, "PUT", "BUY", "min")
        detected_type = None
        involved: list[str] = []
        confidence = "low"

        if sc is not None and lc is not None and sp is not None and lp is not None and lc["strike"] > sc["strike"] and lp["strike"] < sp["strike"]:
            if abs(sc["strike"] - sp["strike"]) < 1e-9:
                detected_type = "IRON_BUTTERFLY"
                confidence = "high"
            elif sp["strike"] < sc["strike"]:
                detected_type = "IRON_CONDOR"
                confidence = "high"
            involved = [sc["contract_key"], lc["contract_key"], sp["contract_key"], lp["contract_key"]]
        elif sc is not None and lc is not None and lc["strike"] > sc["strike"]:
            detected_type = "CALL_CREDIT_SPREAD"
            confidence = "medium"
            involved = [sc["contract_key"], lc["contract_key"]]
        elif sp is not None and lp is not None and lp["strike"] < sp["strike"]:
            detected_type = "PUT_CREDIT_SPREAD"
            confidence = "medium"
            involved = [sp["contract_key"], lp["contract_key"]]
        elif lc is not None and sc is not None and lc["strike"] < sc["strike"]:
            detected_type = "CALL_DEBIT_SPREAD"
            confidence = "medium"
            involved = [lc["contract_key"], sc["contract_key"]]
        elif lp is not None and sp is not None and lp["strike"] > sp["strike"]:
            detected_type = "PUT_DEBIT_SPREAD"
            confidence = "medium"
            involved = [lp["contract_key"], sp["contract_key"]]

        if detected_type and involved:
            anchor = int(round(sc["strike"] if sc is not None else sp["strike"]))
            strategy_id = f"{ticker}_{detected_type}_{open_date.strftime('%Y%m%d')}_{anchor}"
            opening_cash = float(group[group["contract_key"].isin(involved)]["net_cash"].sum())
            for ck in involved:
                auto_assignments[ck] = (strategy_id, detected_type)
            audit_rows.append(
                {
                    "ticker": ticker,
                    "open_date": open_date,
                    "expiration": expiration,
                    "detected_strategy_type": detected_type,
                    "strategy_id": strategy_id,
                    "contracts_included": ", ".join(involved),
                    "total_opening_credit_debit": opening_cash,
                    "confidence_level": confidence,
                }
            )

    # Mapeo al esquema actual del dashboard (sin romper vistas existentes)
    normalized = normalized_ib.copy()
    normalized["strategy_id"] = normalized["contract_key"].map(lambda ck: auto_assignments.get(ck, ("", ""))[0]).replace("", normalized["contract_key"])
    normalized["underlying_price"] = 0.0
    normalized["strategy_type"] = normalized["contract_key"].map(lambda ck: auto_assignments.get(ck, ("", ""))[1]).replace("", "Contrato opción (IB)")
    normalized["close_date"] = pd.NaT
    normalized["premium"] = normalized["net_cash"].abs()
    normalized["commission"] = 0.0
    normalized["realized_pnl"] = normalized["net_cash"]
    normalized["unrealized_pnl"] = 0.0
    normalized["status"] = "abierta"
    normalized["notes"] = normalized["description"]
    normalized["quantity"] = normalized["quantity_abs"]

    if STRATEGY_TAGS_FILE.exists():
        tags = pd.read_csv(STRATEGY_TAGS_FILE, dtype=str)
        if {"contract_key", "strategy_id", "strategy_type"}.issubset(tags.columns):
            tags["contract_key"] = tags["contract_key"].astype(str).str.strip()
            tags = tags.dropna(subset=["contract_key"]).drop_duplicates(subset=["contract_key"], keep="last")
            normalized = normalized.merge(
                tags[["contract_key", "strategy_id", "strategy_type"]].rename(
                    columns={"strategy_id": "manual_strategy_id", "strategy_type": "manual_strategy_type"}
                ),
                on="contract_key",
                how="left",
            )
            normalized["strategy_id"] = normalized["manual_strategy_id"].fillna(normalized["strategy_id"])
            normalized["strategy_type"] = normalized["manual_strategy_type"].fillna(normalized["strategy_type"])
            normalized.drop(columns=["manual_strategy_id", "manual_strategy_type"], inplace=True)
    normalized = normalized.merge(
        contract_results[["contract_key", "position_status", "realized_pnl", "pending_cash"]],
        on="contract_key",
        how="left",
        suffixes=("", "_contract"),
    )
    normalized.loc[normalized["position_status"] == "CLOSED", "status"] = "cerrada"
    normalized.loc[normalized["position_status"] == "OPEN", "status"] = "abierta"

    normalized = normalized[
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
    ].copy().reset_index(drop=True)

    normalized.attrs["source"] = "ib_csv"
    normalized.attrs["raw_rows_count"] = raw_rows_count
    normalized.attrs["filtered_rows_count"] = int(len(normalized_ib))
    normalized.attrs["dropped_rows_count"] = int(raw_rows_count - len(normalized_ib))
    normalized.attrs["normalized_preview"] = normalized_ib.head(10).copy()
    normalized.attrs["contract_results"] = contract_results
    normalized.attrs["strategy_detection_audit"] = pd.DataFrame(audit_rows)
    return normalized


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
