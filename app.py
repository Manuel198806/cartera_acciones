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
from options_dashboard.data import (
    DataValidationError,
    grouped_strategies,
    list_data_csv_files,
    load_trades,
    resolve_default_data_file,
)
from options_dashboard.ib_flex import (
    REQUIRED_IB_COLUMNS,
    download_latest_ib_csv,
    load_import_summary,
    merge_latest_into_master,
    merge_uploaded_csv_into_master,
)
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
    row1[3].metric("Prima ganada", format_currency(kpis["prima_total"]))
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
    st.caption("Open option premium is shown as pending until the position is closed.")

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


def import_summary_view() -> None:
    st.header("Import Summary")
    summary = load_import_summary()
    if not summary:
        st.info("No hay importaciones registradas todavía.")
        return

    st.subheader("1. Import status")
    st.write(f"Last import timestamp: **{summary.get('timestamp_utc', 'N/A')}**")
    st.write(f"Source used: **{summary.get('source_used', 'N/A')}**")
    st.write(f"File loaded: **{summary.get('file_loaded', 'N/A')}**")
    st.write(f"Success: **{summary.get('success', False)}**")

    st.subheader("2. Row summary")
    row_summary = {
        "Rows downloaded in Consulta_latest.csv": summary.get("rows_downloaded_latest", 0),
        "Rows with TradeID": summary.get("rows_with_tradeid", 0),
        "Rows without TradeID dropped": summary.get("rows_without_tradeid_dropped", 0),
        "Rows already existing in master": summary.get("rows_already_existing_master", 0),
        "New rows added to master": summary.get("new_rows_added_to_master", 0),
        "Total rows in Consulta_master.csv": summary.get("total_rows_master", 0),
        "Unique TradeID count": summary.get("unique_tradeid_count", 0),
        "Duplicated TradeID count": summary.get("duplicated_tradeid_count", 0),
    }
    st.dataframe(pd.DataFrame([row_summary]), use_container_width=True, hide_index=True)

    st.subheader("3. New trades added")
    new_rows = pd.DataFrame(summary.get("new_trades_added", []))
    if new_rows.empty:
        st.info("No se añadieron nuevas operaciones en la última importación.")
    else:
        st.dataframe(new_rows, use_container_width=True, hide_index=True)

    st.subheader("4. Warnings")
    warnings = summary.get("warnings", [])
    if warnings:
        for warning in warnings:
            st.warning(warning)
    else:
        st.success("Sin warnings en la última importación.")


def upload_csv_to_master_view() -> None:
    st.header("Upload CSV to Master")
    st.write("Sube un archivo CSV de Interactive Brokers para fusionarlo con `Consulta_master.csv`.")
    uploaded_file = st.file_uploader("Selecciona CSV de IB", type=["csv"])

    if not uploaded_file:
        return

    try:
        uploaded_df = pd.read_csv(uploaded_file, dtype=str)
    except Exception as exc:
        st.error(f"No se pudo leer el CSV subido: {exc}")
        return

    missing_required = sorted(REQUIRED_IB_COLUMNS.difference(set(uploaded_df.columns)))
    if missing_required:
        st.error(f"El archivo no parece un CSV IB válido. Faltan columnas: {', '.join(missing_required)}")
        return

    st.success(f"Archivo cargado correctamente. Filas detectadas: {len(uploaded_df)}")
    if st.button("Merge upload into master", use_container_width=True):
        try:
            summary = merge_uploaded_csv_into_master(uploaded_df)
            st.success(f"Merge completado. Nuevas filas añadidas: {summary.get('new_rows_added_to_master', 0)}")
            st.subheader("Import summary")
            summary_table = {
                "Uploaded rows": summary.get("rows_uploaded", 0),
                "Valid rows with TradeID": summary.get("rows_with_tradeid", 0),
                "Rows without TradeID ignored": summary.get("rows_without_tradeid_dropped", 0),
                "Rows already existing in master": summary.get("rows_already_existing_master", 0),
                "New rows added": summary.get("new_rows_added_to_master", 0),
                "Duplicated TradeID count": summary.get("duplicated_tradeid_count", 0),
                "Total rows in master": summary.get("total_rows_master", 0),
            }
            st.dataframe(pd.DataFrame([summary_table]), use_container_width=True, hide_index=True)

            new_rows = pd.DataFrame(summary.get("new_trades_added", []))
            st.subheader("Preview of new rows added")
            preview_columns = [
                "TradeID",
                "UnderlyingSymbol",
                "Description",
                "TradeDate",
                "Buy/Sell",
                "AssetClass",
                "Quantity",
                "NetCash",
            ]
            if new_rows.empty:
                st.info("No se añadieron nuevas operaciones.")
            else:
                shown_columns = [c for c in preview_columns if c in new_rows.columns]
                st.dataframe(new_rows[shown_columns], use_container_width=True, hide_index=True)

            st.cache_data.clear()
            st.rerun()
        except Exception as exc:
            st.error(f"Error al fusionar el CSV con master: {exc}")


def main() -> None:
    st.sidebar.title("Seguimiento de opciones")
    mode = st.sidebar.radio("Tema", ["Claro", "Oscuro"])
    apply_theme(mode)

    section = st.sidebar.radio(
        "Navegación",
        ["Dashboard", "Operaciones", "Vista por ticker", "Vencimientos", "Import Summary", "Upload CSV to Master"],
    )

    st.sidebar.subheader("Interactive Brokers")
    ib_token = st.sidebar.text_input("IB Flex Token", type="password")
    ib_query_id = st.sidebar.text_input("IB Flex Query ID")
    if st.sidebar.button("Download latest IB data", use_container_width=True):
        if not ib_token or not ib_query_id:
            st.sidebar.error("Debes introducir token y query id.")
        else:
            try:
                download_latest_ib_csv(ib_token, ib_query_id)
                summary = merge_latest_into_master()
                st.sidebar.success(
                    f"Importación OK. Nuevas filas: {summary.get('new_rows_added_to_master', 0)}"
                )
                st.cache_data.clear()
                st.rerun()
            except Exception as exc:
                st.sidebar.error(f"Error importando datos de IB: {exc}")

    available_files = list_data_csv_files()
    default_file = resolve_default_data_file()
    selected_file = str(default_file)
    if available_files:
        labels = [p.name for p in available_files]
        default_idx = labels.index(default_file.name) if default_file.name in labels else 0
        chosen_label = st.sidebar.selectbox("Archivo CSV", labels, index=default_idx)
        selected_file = str(next(p for p in available_files if p.name == chosen_label))

    try:
        df = load_trades(path=selected_file)
    except FileNotFoundError:
        st.error("No se encontró ningún CSV en la carpeta data.")
        return
    except DataValidationError as err:
        st.error(str(err))
        return

    with st.sidebar.expander("Debug de carga", expanded=False):
        st.write(f"Archivo: **{df.attrs.get('file_path', selected_file)}**")
        st.write(f"Fuente detectada: **{df.attrs.get('source', 'desconocida')}**")
        st.write(f"Filas cargadas: **{df.attrs.get('rows_loaded', len(df))}**")
        if df.attrs.get("source") == "ib_csv":
            st.write(f"Filas crudas (raw): **{df.attrs.get('raw_rows_count', 'N/A')}**")
            st.write(f"Filas filtradas (OPT + TradeID + fecha): **{df.attrs.get('filtered_rows_count', 'N/A')}**")
            st.write(f"Filas descartadas: **{df.attrs.get('dropped_rows_count', 'N/A')}**")
        st.write("Columnas detectadas:")
        st.code(", ".join(df.attrs.get("detected_columns", list(df.columns))))
        missing_fields = df.attrs.get("missing_fields", [])
        st.write("Campos faltantes o vacíos:")
        st.code(", ".join(missing_fields) if missing_fields else "Ninguno")
        st.write("Primeras 10 filas normalizadas:")
        st.dataframe(df.head(10), use_container_width=True, hide_index=True)
        normalized_preview = df.attrs.get("normalized_preview")
        if normalized_preview is not None and not normalized_preview.empty:
            st.write("Vista normalizada IB (schema limpio):")
            st.dataframe(normalized_preview, use_container_width=True, hide_index=True)
        contract_results = df.attrs.get("contract_results")
        if contract_results is not None and not contract_results.empty:
            st.write("Resultado por contrato (contract_key / net_quantity / net_cash_total / position_status):")
            st.dataframe(contract_results, use_container_width=True, hide_index=True)

    if section == "Dashboard":
        dashboard_view(df)
    elif section == "Operaciones":
        operations_table_view(df)
    elif section == "Vista por ticker":
        ticker_view(df)
    elif section == "Vencimientos":
        expirations_view(df)
    elif section == "Upload CSV to Master":
        upload_csv_to_master_view()
    else:
        import_summary_view()


if __name__ == "__main__":
    main()
