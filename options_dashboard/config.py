"""Configuración central del dashboard."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "mock_trades.csv"
STRATEGY_TAGS_FILE = BASE_DIR / "data" / "strategy_tags.csv"
DATE_COLUMNS = ["open_date", "close_date", "expiration"]
STRATEGY_TAG_COLUMNS = ["contract_key", "strategy_id", "strategy_type", "strategy_step", "notes"]
SUPPORTED_STRATEGY_TYPES = [
    "IRON_CONDOR",
    "VERTICAL_SPREAD",
    "JADE_LIZARD",
    "WHEEL",
    "COVERED_CALL",
    "SYNTHETIC_LONG",
    "SINGLE_LEG",
    "OTHER",
]
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
