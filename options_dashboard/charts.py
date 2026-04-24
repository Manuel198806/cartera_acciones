"""Gráficos de apoyo para el dashboard."""
from __future__ import annotations

import pandas as pd
import plotly.express as px


def chart_cumulative_pnl(df: pd.DataFrame):
    return px.line(
        df,
        x="date",
        y="cumulative_pnl",
        title="Evolución del P&L acumulado",
        markers=True,
    )


def chart_monthly_pnl(df: pd.DataFrame):
    return px.bar(df, x="month", y="realized_pnl", title="P&L mensual")


def chart_pnl_by_ticker(df: pd.DataFrame):
    grouped = df.groupby("ticker", as_index=False).agg(total_pnl=("realized_pnl", "sum"))
    return px.bar(grouped, x="ticker", y="total_pnl", title="P&L por subyacente")


def chart_pnl_by_strategy(df: pd.DataFrame):
    grouped = df.groupby("strategy_type", as_index=False).agg(total_pnl=("realized_pnl", "sum"))
    return px.pie(grouped, names="strategy_type", values="total_pnl", title="P&L por estrategia")


def chart_win_loss(df: pd.DataFrame):
    closed = df[df["status"].isin(["cerrada", "expirada", "asignada"])]
    winners = int((closed["realized_pnl"] > 0).sum())
    losers = int((closed["realized_pnl"] <= 0).sum())
    source = pd.DataFrame(
        {"resultado": ["Ganadoras", "Perdedoras"], "cantidad": [winners, losers]}
    )
    return px.pie(source, names="resultado", values="cantidad", title="Distribución ganadoras/perdedoras")


def chart_premium_by_month(df: pd.DataFrame):
    grouped = (
        df.assign(month=df["open_date"].dt.to_period("M").astype(str))
        .groupby("month", as_index=False)
        .agg(premium=("premium", "sum"))
    )
    return px.bar(grouped, x="month", y="premium", title="Primas cobradas por mes")


def chart_exposure_by_ticker(df: pd.DataFrame):
    open_df = df[df["status"] == "abierta"].copy()
    open_df["exposure"] = open_df["strike"] * open_df["quantity"].abs() * 100
    grouped = open_df.groupby("ticker", as_index=False).agg(exposure=("exposure", "sum"))
    return px.treemap(grouped, path=["ticker"], values="exposure", title="Exposición por ticker")


def chart_expiration_calendar(df: pd.DataFrame):
    grouped = (
        df[df["status"] == "abierta"]
        .groupby(["expiration", "ticker"], as_index=False)
        .agg(contratos=("trade_id", "count"), prima_pendiente=("premium", "sum"))
    )
    return px.scatter(
        grouped,
        x="expiration",
        y="ticker",
        size="contratos",
        color="prima_pendiente",
        title="Calendario de vencimientos",
    )
