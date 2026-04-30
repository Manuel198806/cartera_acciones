# Gestión de Inversiones - Dashboard de Opciones

Aplicación web para seguimiento de operativa con opciones financieras: puts vendidas, calls cubiertas, spreads, iron condors, jade lizards, rolls y asignaciones.

## Stack detectado
El repositorio original estaba en Python sin framework web definido. Se implementó una interfaz en **Streamlit** por ser coherente con Python, rápida de iterar y adecuada para dashboards analíticos.

## Estructura del proyecto

```text
.
├── app.py
├── data/
│   └── mock_trades.csv
├── options_dashboard/
│   ├── __init__.py
│   ├── charts.py
│   ├── config.py
│   ├── data.py
│   └── metrics.py
└── requirements.txt
```

## Funcionalidades implementadas

- Dashboard principal con KPIs:
  - P&L total, mensual y anual.
  - Prima total, cerrada y pendiente.
  - Operaciones abiertas/cerradas.
  - Win rate.
  - Capital estimado utilizado.
  - Rentabilidad sobre capital.
- Gráficos interactivos:
  - Evolución de P&L acumulado.
  - P&L mensual.
  - P&L por subyacente y estrategia.
  - Distribución ganadoras/perdedoras.
  - Primas por mes.
  - Exposición por ticker.
  - Calendario de vencimientos.
- Tabla de operaciones filtrable (ticker, estrategia, estado) y ordenable.
- Seguimiento de estrategias complejas con vista agrupada por `strategy_id` y desglose de legs.
- Vista por ticker:
  - Historial completo.
  - P&L acumulado.
  - Primas cobradas.
  - Operaciones abiertas.
  - Vencimientos próximos.
  - Precio medio en asignaciones.
  - Histórico de rolls.
  - Notas.
- Vista de vencimientos:
  - Agrupación por fecha de expiración.
  - Ticker, estrategia, strikes, prima pendiente, riesgo estimado y días restantes.
- Tema claro/oscuro y navegación por sidebar.
- Manejo básico de errores por dataset ausente o columnas incompletas.

## Dataset
La app detecta automáticamente los CSV en `data/`:

- Si existe `Consulta_master.csv`, lo usa por defecto.
- Si no existe, intenta `Consulta.csv`.
- Si no existe, usa `mock_trades.csv`.
- En la barra lateral puedes seleccionar otro CSV disponible desde un desplegable.

### Descarga IB Flex Query (acumulación incremental)

Desde la barra lateral (`Interactive Brokers`) puedes lanzar la descarga:

1. `SendRequest` (token + query_id) para obtener `ReferenceCode`.
2. `GetStatement` para descargar CSV.

Flujo de archivos:

- Descarga temporal: `data/Consulta_latest.csv`
- Fuente de verdad acumulada: `data/Consulta_master.csv`

Reglas de acumulación:

- Clave única: `TradeID`
- Solo se agregan filas nuevas (TradeID no existente en master)
- Se descartan filas sin `TradeID`
- Se guarda resumen de importación en `data/import_summary.json`

Para IB se incluye una capa de normalización automática:

- Sin preprocesado manual en Excel.
- Conversión de tipos y columnas al esquema interno.
- Filtro automático a últimos 12 meses por `open_date`.
- Vinculación de aperturas/cierres por contrato (`strategy_id` por ciclo).

### Mock de respaldo
Se incluye `data/mock_trades.csv` con estructura preparada para:

- Operaciones individuales (`trade_id`).
- Estrategias agrupadas (`strategy_id`).
- Estado de ciclo de vida (`abierta`, `cerrada`, `rolada`, `asignada`, `expirada`).

Campos mínimos incluidos:

- `trade_id`
- `strategy_id`
- `ticker`
- `underlying_price`
- `strategy_type`
- `leg_type`
- `action`
- `quantity`
- `strike`
- `expiration`
- `open_date`
- `close_date`
- `premium`
- `commission`
- `realized_pnl`
- `unrealized_pnl`
- `status`
- `notes`

## Ejecutar localmente

1. Crear entorno virtual (opcional):

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Instalar dependencias:

```bash
pip install -r requirements.txt
```

3. Lanzar la app:

```bash
streamlit run app.py
```

4. Abrir en navegador la URL indicada por Streamlit (por defecto `http://localhost:8501`).

## Próximos pasos sugeridos

- Conectar capa de datos a exportaciones reales (Interactive Brokers / FlexQuery).
- Añadir autenticación y persistencia.
- Separar vistas en páginas nativas de Streamlit para crecimiento modular.
- Incorporar testing unitario de métricas y validaciones de esquemas.
