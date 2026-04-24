"""Configuración central del dashboard."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "mock_trades.csv"
DATE_COLUMNS = ["open_date", "close_date", "expiration"]
REQUIRED_COLUMNS = {
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
}
