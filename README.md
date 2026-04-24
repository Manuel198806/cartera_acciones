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

## Dataset mock
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
