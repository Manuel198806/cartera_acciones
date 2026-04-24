from __future__ import annotations

import pandas as pd
import streamlit as st

from options_dashboard.charts import (
    chart_cumulative_pnl,
    chart_expiration_calendar,
    chart_exposure_by_ticker,
    chart_monthly_pnl,
    chart_pnl_by_strategy,
    chart_pnl_by_ticker,
    chart_premium_by_month,
    chart_win_loss,
)
from options_dashboard.data import DataValidationError, grouped_strategies, load_trades
from options_dashboard.metrics import build_kpis, cumulative_pnl, monthly_pnl

st.set_page_config(page_title="Dashboard de Opciones", layout="wide")


def format_currency(value: float) -> str:
    return f"${value:,.2f}"


def apply_theme(mode: str) -> None:
    if mode == "Oscuro":
        st.markdown(
            """
            <style>
                .stApp { background-color: #0e1117; color: #f5f5f5; }
            </style>
            """,
            unsafe_allow_html=True,
        )


def render_kpis(kpis: dict[str, float]) -> None:
    row1 = st.columns(6)
    row2 = st.columns(5)

    row1[0].metric("P&L Total", format_currency(kpis["pnl_total"]))
    row1[1].metric("P&L Mensual", format_currency(kpis["pnl_mensual"]))
    row1[2].metric("P&L Anual", format_currency(kpis["pnl_anual"]))
    row1[3].metric("Prima total", format_currency(kpis["prima_total"]))
    row1[4].metric("Prima cerrada", format_currency(kpis["prima_cerrada"]))
    row1[5].metric("Prima pendiente", format_currency(kpis["prima_pendiente"]))

    row2[0].metric("Operaciones abiertas", int(kpis["operaciones_abiertas"]))
    row2[1].metric("Operaciones cerradas", int(kpis["operaciones_cerradas"]))
    row2[2].metric("Win rate", f"{kpis['win_rate']:.1f}%")
    row2[3].metric("Capital usado", format_currency(kpis["capital_usado"]))
    row2[4].metric("Rentabilidad/Capital", f"{kpis['rentabilidad_capital']:.2f}%")


def dashboard_view(df: pd.DataFrame) -> None:
    st.header("Dashboard principal")
    render_kpis(build_kpis(df))

    monthly = monthly_pnl(df)
    cumulative = cumulative_pnl(df)

    c1, c2 = st.columns(2)
    c1.plotly_chart(chart_cumulative_pnl(cumulative), use_container_width=True)
    c2.plotly_chart(chart_monthly_pnl(monthly), use_container_width=True)

    c3, c4 = st.columns(2)
    c3.plotly_chart(chart_pnl_by_ticker(df), use_container_width=True)
    c4.plotly_chart(chart_pnl_by_strategy(df), use_container_width=True)

    c5, c6 = st.columns(2)
    c5.plotly_chart(chart_win_loss(df), use_container_width=True)
    c6.plotly_chart(chart_premium_by_month(df), use_container_width=True)

    c7, c8 = st.columns(2)
    c7.plotly_chart(chart_exposure_by_ticker(df), use_container_width=True)
    c8.plotly_chart(chart_expiration_calendar(df), use_container_width=True)


def operations_table_view(df: pd.DataFrame) -> None:
    st.header("Tabla de operaciones")
    col1, col2, col3 = st.columns(3)
    selected_ticker = col1.multiselect("Ticker", sorted(df["ticker"].unique()))
    selected_strategy = col2.multiselect("Estrategia", sorted(df["strategy_type"].unique()))
    selected_status = col3.multiselect("Estado", sorted(df["status"].unique()))

    filtered = df.copy()
    if selected_ticker:
        filtered = filtered[filtered["ticker"].isin(selected_ticker)]
    if selected_strategy:
        filtered = filtered[filtered["strategy_type"].isin(selected_strategy)]
    if selected_status:
        filtered = filtered[filtered["status"].isin(selected_status)]

    st.dataframe(
        filtered.sort_values("open_date", ascending=False),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Operaciones agrupadas por estrategia")
    grouped = grouped_strategies(filtered)
    for _, row in grouped.iterrows():
        with st.expander(
            f"{row['strategy_id']} · {row['ticker']} · {row['strategy_type']} · {row['status']} · P&L {format_currency(row['total_pnl'])}"
        ):
            legs = filtered[filtered["strategy_id"] == row["strategy_id"]]
            st.dataframe(legs, use_container_width=True, hide_index=True)


def ticker_view(df: pd.DataFrame) -> None:
    st.header("Vista por ticker")
    ticker = st.selectbox("Selecciona ticker", sorted(df["ticker"].unique()))
    tdf = df[df["ticker"] == ticker].copy()

    st.write(f"**P&L acumulado {ticker}:** {format_currency((tdf['realized_pnl'] + tdf['unrealized_pnl']).sum())}")
    st.write(f"**Primas cobradas:** {format_currency(tdf['premium'].sum())}")
    st.write(f"**Operaciones abiertas:** {(tdf['status'] == 'abierta').sum()}")

    upcoming = tdf[(tdf["status"] == "abierta") & (tdf["expiration"] >= pd.Timestamp.utcnow().tz_localize(None))]
    st.subheader("Vencimientos próximos")
    st.dataframe(upcoming.sort_values("expiration"), use_container_width=True, hide_index=True)

    assigned = tdf[tdf["status"] == "asignada"]
    avg_assignment = assigned["strike"].mean() if not assigned.empty else 0
    st.write(f"**Precio medio de asignación:** {format_currency(avg_assignment) if avg_assignment else 'N/A'}")

    rolls = tdf[tdf["strategy_type"].str.contains("Roll", case=False)]
    st.subheader("Histórico de rolls")
    st.dataframe(rolls.sort_values("open_date", ascending=False), use_container_width=True, hide_index=True)

    st.subheader("Notas de seguimiento")
    st.dataframe(tdf[["open_date", "strategy_type", "status", "notes"]], use_container_width=True, hide_index=True)


def expirations_view(df: pd.DataFrame) -> None:
    st.header("Vista de vencimientos")
    open_df = df[df["status"] == "abierta"].copy()
    if open_df.empty:
        st.info("No hay operaciones abiertas.")
        return

    now = pd.Timestamp.utcnow().tz_localize(None)
    grouped = (
        open_df.groupby(["expiration", "ticker", "strategy_type", "status"], as_index=False)
        .agg(
            strikes=("strike", lambda x: ", ".join(map(lambda y: f"{y:.0f}", sorted(x.unique())))),
            prima_pendiente=("premium", "sum"),
            riesgo_max=("strike", lambda x: (x.max() * 100)),
        )
        .sort_values("expiration")
    )
    grouped["dias_restantes"] = (grouped["expiration"] - now).dt.days

    st.dataframe(grouped, use_container_width=True, hide_index=True)
    st.plotly_chart(chart_expiration_calendar(df), use_container_width=True)


def main() -> None:
    st.sidebar.title("Seguimiento de opciones")
    mode = st.sidebar.radio("Tema", ["Claro", "Oscuro"])
    apply_theme(mode)

    section = st.sidebar.radio(
        "Navegación",
        ["Dashboard", "Operaciones", "Vista por ticker", "Vencimientos"],
    )

    try:
        df = load_trades()
    except FileNotFoundError:
        st.error("No se encontró data/mock_trades.csv. Añade un dataset para continuar.")
        return
    except DataValidationError as err:
        st.error(str(err))
        return

    if section == "Dashboard":
        dashboard_view(df)
    elif section == "Operaciones":
        operations_table_view(df)
    elif section == "Vista por ticker":
        ticker_view(df)
    else:
        expirations_view(df)


if __name__ == "__main__":
    main()
