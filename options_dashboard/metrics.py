"""Métricas de negocio para la operativa con opciones."""
from __future__ import annotations

import pandas as pd


CLOSED_STATUS = {"cerrada", "expirada", "asignada"}


def _capital_estimado(df: pd.DataFrame) -> float:
    return float((df["strike"] * df["quantity"].abs() * 100).sum())


def build_kpis(df: pd.DataFrame) -> dict[str, float]:
    now = pd.Timestamp.utcnow().tz_localize(None)
    monthly_mask = df["open_date"].dt.to_period("M") == now.to_period("M")
    yearly_mask = df["open_date"].dt.year == now.year

    closed = df[df["status"].isin(CLOSED_STATUS)]
    open_positions = df[df["status"] == "abierta"]

    total_pnl = float(closed["realized_pnl"].sum())
    winners = (closed["realized_pnl"] > 0).sum()
    win_rate = (winners / len(closed) * 100) if len(closed) else 0.0

    capital = _capital_estimado(open_positions)
    rentabilidad = (total_pnl / capital * 100) if capital else 0.0

    return {
        "pnl_total": total_pnl,
        "pnl_mensual": float(df.loc[monthly_mask & df["status"].isin(CLOSED_STATUS), "realized_pnl"].sum()),
        "pnl_anual": float(df.loc[yearly_mask & df["status"].isin(CLOSED_STATUS), "realized_pnl"].sum()),
        "prima_total": float(closed["premium"].sum()),
        "prima_cerrada": float(closed["premium"].sum()),
        "prima_pendiente": float(open_positions["premium"].sum()),
        "operaciones_abiertas": int(open_positions.shape[0]),
        "operaciones_cerradas": int(df["status"].isin(CLOSED_STATUS).sum()),
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


def daily_realized_pnl(df: pd.DataFrame) -> pd.DataFrame:
    closed = df[df["status"].isin(CLOSED_STATUS)].copy()
    if closed.empty:
        return pd.DataFrame(columns=["date", "daily_pnl", "trades", "winning_trades", "losing_trades"])

    closed["date"] = closed["open_date"].dt.normalize()
    return (
        closed.groupby("date", as_index=False)
        .agg(
            daily_pnl=("realized_pnl", "sum"),
            trades=("trade_id", "count"),
            winning_trades=("realized_pnl", lambda s: int((s > 0).sum())),
            losing_trades=("realized_pnl", lambda s: int((s < 0).sum())),
        )
        .sort_values("date")
    )


def weekly_pnl_summary(df: pd.DataFrame) -> pd.DataFrame:
    daily = daily_realized_pnl(df)
    if daily.empty:
        return pd.DataFrame(columns=["year", "week", "weekly_pnl", "trades", "winning_days", "losing_days"])

    iso = daily["date"].dt.isocalendar()
    daily = daily.assign(year=iso.year, week=iso.week)
    return (
        daily.groupby(["year", "week"], as_index=False)
        .agg(
            weekly_pnl=("daily_pnl", "sum"),
            trades=("trades", "sum"),
            winning_days=("daily_pnl", lambda s: int((s > 0).sum())),
            losing_days=("daily_pnl", lambda s: int((s < 0).sum())),
        )
        .sort_values(["year", "week"])
    )


def monthly_pnl_summary(df: pd.DataFrame) -> pd.DataFrame:
    daily = daily_realized_pnl(df)
    if daily.empty:
        return pd.DataFrame(columns=["year", "month", "monthly_pnl", "trades", "operated_days"])

    daily = daily.assign(year=daily["date"].dt.year, month=daily["date"].dt.month)
    return (
        daily.groupby(["year", "month"], as_index=False)
        .agg(monthly_pnl=("daily_pnl", "sum"), trades=("trades", "sum"), operated_days=("date", "count"))
        .sort_values(["year", "month"])
    )
