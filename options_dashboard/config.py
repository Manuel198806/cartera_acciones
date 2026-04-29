"""Configuración central del dashboard."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = BASE_DIR / "data" / "mock_trades.csv"
MASTER_DATA_FILE = DATA_DIR / "Consulta_master.csv"
LATEST_DATA_FILE = DATA_DIR / "Consulta_latest.csv"
IMPORT_SUMMARY_FILE = DATA_DIR / "import_summary.json"
STRATEGY_TAGS_FILE = DATA_DIR / "strategy_tags.csv"
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
