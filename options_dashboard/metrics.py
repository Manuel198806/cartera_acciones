"""Métricas de negocio para la operativa con opciones."""
from __future__ import annotations

import pandas as pd


def _capital_estimado(df: pd.DataFrame) -> float:
    return float((df["strike"] * df["quantity"].abs() * 100).sum())


def build_kpis(df: pd.DataFrame) -> dict[str, float]:
    now = pd.Timestamp.utcnow().tz_localize(None)
    monthly_mask = df["open_date"].dt.to_period("M") == now.to_period("M")
    yearly_mask = df["open_date"].dt.year == now.year

    closed_status = {"cerrada", "expirada", "asignada"}
    closed = df[df["status"].isin(closed_status)]
    open_positions = df[df["status"] == "abierta"]

    total_pnl = float(closed["realized_pnl"].sum())
    winners = (closed["realized_pnl"] > 0).sum()
    win_rate = (winners / len(closed) * 100) if len(closed) else 0.0

    capital = _capital_estimado(open_positions)
    rentabilidad = (total_pnl / capital * 100) if capital else 0.0

    return {
        "pnl_total": total_pnl,
        "pnl_mensual": float(df.loc[monthly_mask & df["status"].isin(closed_status), "realized_pnl"].sum()),
        "pnl_anual": float(df.loc[yearly_mask & df["status"].isin(closed_status), "realized_pnl"].sum()),
        "prima_total": float(closed["premium"].sum()),
        "prima_cerrada": float(closed["premium"].sum()),
        "prima_pendiente": float(open_positions["premium"].sum()),
        "operaciones_abiertas": int(open_positions.shape[0]),
        "operaciones_cerradas": int(df["status"].isin(closed_status).sum()),
        "win_rate": win_rate,
        "capital_usado": capital,
        "rentabilidad_capital": rentabilidad,
    }


def monthly_pnl(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.assign(month=df["open_date"].dt.to_period("M").astype(str))
        .groupby("month", as_index=False)
        .agg(realized_pnl=("realized_pnl", "sum"), premium=("premium", "sum"))
        .sort_values("month")
    )


def cumulative_pnl(df: pd.DataFrame) -> pd.DataFrame:
    daily = (
        df.groupby("open_date", as_index=False)
        .agg(realized_pnl=("realized_pnl", "sum"))
        .sort_values("open_date")
        .rename(columns={"open_date": "date"})
    )
    daily["cumulative_pnl"] = daily["realized_pnl"].cumsum()
    return daily
