"""Métricas de negocio para la operativa con opciones."""
from __future__ import annotations

import pandas as pd


def _capital_estimado(df: pd.DataFrame) -> float:
    return float((df["strike"] * df["quantity"].abs() * 100).sum())


def build_kpis(df: pd.DataFrame) -> dict[str, float]:
    now = pd.Timestamp.utcnow().tz_localize(None)
    monthly_mask = df["open_date"].dt.to_period("M") == now.to_period("M")
    yearly_mask = df["open_date"].dt.year == now.year

    total_realized = float(df["realized_pnl"].sum())
    total_unrealized = float(df["unrealized_pnl"].sum())
    total_pnl = total_realized + total_unrealized

    closed_status = {"cerrada", "expirada", "asignada"}
    closed = df[df["status"].isin(closed_status)]
    winners = (closed["realized_pnl"] > 0).sum()
    win_rate = (winners / len(closed) * 100) if len(closed) else 0.0

    capital = _capital_estimado(df[df["status"] == "abierta"])
    rentabilidad = (total_pnl / capital * 100) if capital else 0.0

    return {
        "pnl_total": total_pnl,
        "pnl_mensual": float(df.loc[monthly_mask, "realized_pnl"].sum()),
        "pnl_anual": float(df.loc[yearly_mask, "realized_pnl"].sum()),
        "prima_total": float(df["premium"].sum()),
        "prima_cerrada": float(closed["premium"].sum()),
        "prima_pendiente": float(df[df["status"] == "abierta"]["premium"].sum()),
        "operaciones_abiertas": int((df["status"] == "abierta").sum()),
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
