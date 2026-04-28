"""Carga y preparación de datos de operaciones."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from options_dashboard.config import (
    DATA_FILE,
    DATE_COLUMNS,
    REQUIRED_COLUMNS,
    STRATEGY_TAG_COLUMNS,
    STRATEGY_TAGS_FILE,
)


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


def load_strategy_tags(path: str | None = None) -> pd.DataFrame:
    """Carga etiquetas manuales de estrategia si existen."""
    file_path = path or str(STRATEGY_TAGS_FILE)
    if not pd.io.common.file_exists(file_path):
        return pd.DataFrame(columns=STRATEGY_TAG_COLUMNS)

    tags = pd.read_csv(file_path)
    missing = set(STRATEGY_TAG_COLUMNS).difference(tags.columns)
    if missing:
        raise DataValidationError(
            f"Faltan columnas requeridas en strategy_tags.csv: {', '.join(sorted(missing))}"
        )
    tags["contract_key"] = tags["contract_key"].astype(str)
    tags["strategy_id"] = tags["strategy_id"].astype(str)
    tags["strategy_type"] = tags["strategy_type"].astype(str)
    tags["notes"] = tags["notes"].fillna("").astype(str)
    tags["strategy_step"] = pd.to_numeric(tags["strategy_step"], errors="coerce").fillna(1).astype(int)
    return tags[STRATEGY_TAG_COLUMNS].copy()


def build_contract_groups(df: pd.DataFrame) -> pd.DataFrame:
    """Construye grupos base de contratos (contract_key) a partir de strategy_id original."""
    grouped = (
        df.groupby("strategy_id", dropna=False)
        .agg(
            ticker=("ticker", "first"),
            expiration=("expiration", "max"),
            open_date=("open_date", "min"),
            close_date=("close_date", "max"),
            status=("status", lambda x: ", ".join(sorted(x.dropna().astype(str).unique()))),
            leg_type=("leg_type", lambda x: ", ".join(sorted(x.dropna().astype(str).unique()))),
            contracts=("trade_id", "count"),
            realized_pnl=("realized_pnl", "sum"),
            unrealized_pnl=("unrealized_pnl", "sum"),
        )
        .reset_index()
        .rename(columns={"strategy_id": "contract_key"})
    )
    grouped["total_pnl"] = grouped["realized_pnl"] + grouped["unrealized_pnl"]
    return grouped.sort_values("open_date", ascending=False)


def apply_manual_strategy_tags(df: pd.DataFrame, tags: pd.DataFrame) -> pd.DataFrame:
    """Aplica etiquetas manuales para sobrescribir strategy_id y strategy_type automáticos."""
    output = df.copy()
    output["contract_key"] = output["strategy_id"].astype(str)
    output["auto_strategy_id"] = output["strategy_id"]
    output["auto_strategy_type"] = output["strategy_type"]

    if tags.empty:
        return output

    tags_latest = tags.drop_duplicates(subset=["contract_key"], keep="last")
    tags_latest = tags_latest.set_index("contract_key")
    output["manual_strategy_id"] = output["contract_key"].map(tags_latest["strategy_id"])
    output["manual_strategy_type"] = output["contract_key"].map(tags_latest["strategy_type"])
    output["manual_notes"] = output["contract_key"].map(tags_latest["notes"])

    output["strategy_id"] = output["manual_strategy_id"].fillna(output["strategy_id"])
    output["strategy_type"] = output["manual_strategy_type"].fillna(output["strategy_type"])
    output["notes"] = output["manual_notes"].fillna(output["notes"])
    return output


def upsert_strategy_tags(
    contract_keys: list[str],
    strategy_id: str,
    strategy_type: str,
    notes: str,
    path: str | None = None,
) -> pd.DataFrame:
    """Inserta o actualiza etiquetas manuales para los contract_key seleccionados."""
    file_path = path or str(STRATEGY_TAGS_FILE)
    tags = load_strategy_tags(file_path)

    filtered = tags[~tags["contract_key"].isin(contract_keys)].copy()
    existing_steps = filtered[filtered["strategy_id"] == strategy_id]["strategy_step"]
    base_step = int(existing_steps.max()) if not existing_steps.empty else 0

    new_rows = pd.DataFrame(
        {
            "contract_key": contract_keys,
            "strategy_id": strategy_id,
            "strategy_type": strategy_type,
            "strategy_step": [base_step + i for i, _ in enumerate(contract_keys, start=1)],
            "notes": notes,
        }
    )
    updated = pd.concat([filtered, new_rows], ignore_index=True)
    updated = updated.sort_values(["strategy_id", "strategy_step", "contract_key"]).reset_index(drop=True)
    updated.to_csv(file_path, index=False)
    return updated


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
