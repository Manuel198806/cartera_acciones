from __future__ import annotations

import pandas as pd

CONTRACT_SIZE_DEFAULT = 100


def load_wheel_data(df: pd.DataFrame) -> pd.DataFrame:
    wheel_df = df.copy()
    wheel_df["instrument_type"] = wheel_df["leg_type"].astype(str).str.upper().apply(
        lambda x: "STK" if x == "STOCK" else "OPT"
    )
    wheel_df["event_date"] = wheel_df["open_date"].fillna(wheel_df["close_date"]) 
    return wheel_df


def get_wheel_operations_for_ticker(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    ops = df[df["ticker"].astype(str).str.upper() == ticker.upper()].copy()
    return ops.sort_values(["event_date", "trade_id"], ascending=[False, False])


def calculate_break_even_from_premiums(strike: float, premium_net: float, contract_size: int = CONTRACT_SIZE_DEFAULT) -> float:
    return float(strike) - (float(premium_net) / float(contract_size))


def _derive_operation_label(row: pd.Series) -> str:
    leg = str(row.get("leg_type", "")).upper()
    action = str(row.get("action", "")).upper()
    oc = str(row.get("open_close_indicator", "")).upper()
    strategy = str(row.get("strategy_type", "")).upper()

    if leg == "STOCK":
        return "Stock Buy" if action == "BUY" else "Stock Sold" if action == "SELL" else "Stock Operation"

    if "ROLL" in strategy:
        return "Roll Put" if leg == "PUT" else "Roll Call" if leg == "CALL" else "Roll"

    if leg == "PUT":
        if action == "SELL" and oc == "OPENING":
            return "Short Put Open"
        if action == "BUY" and oc == "CLOSING":
            return "Short Put Close"
    if leg == "CALL":
        if action == "SELL" and oc == "OPENING":
            return "Covered Call Open"
        if action == "BUY" and oc == "CLOSING":
            return "Covered Call Close"

    return "Option Operation"


def calculate_wheel_metrics(ops: pd.DataFrame) -> dict[str, float | str | None]:
    if ops.empty:
        return {
            "net_premiums": 0.0,
            "active_short_put_strike": None,
            "active_covered_call_strike": None,
            "break_even": None,
            "shares_held": 0.0,
            "net_stock_cost_basis": None,
            "wheel_status": "No activity",
        }

    opts = ops[ops["leg_type"].isin(["PUT", "CALL"])].copy()
    stocks = ops[ops["leg_type"] == "STOCK"].copy()

    net_premiums = float(opts["realized_pnl"].sum())

    open_puts = opts[(opts["leg_type"] == "PUT") & (opts["status"] == "abierta") & (opts["action"] == "SELL")]
    open_calls = opts[(opts["leg_type"] == "CALL") & (opts["status"] == "abierta") & (opts["action"] == "SELL")]

    active_put_strike = float(open_puts.sort_values("open_date").iloc[-1]["strike"]) if not open_puts.empty else None
    active_call_strike = float(open_calls.sort_values("open_date").iloc[-1]["strike"]) if not open_calls.empty else None

    shares_held = float((stocks["signed_quantity"] if "signed_quantity" in stocks else 0).sum())
    stock_buys_cash = float(stocks.loc[stocks["signed_quantity"] > 0, "net_cash_effect"].sum()) if not stocks.empty else 0.0
    stock_sells_cash = float(stocks.loc[stocks["signed_quantity"] < 0, "net_cash_effect"].sum()) if not stocks.empty else 0.0
    stock_net_cash_out = -(stock_buys_cash + stock_sells_cash)

    break_even = calculate_break_even_from_premiums(active_put_strike, net_premiums) if active_put_strike is not None else None

    net_stock_cost_basis = None
    if shares_held > 0:
        net_stock_cost_basis = (stock_net_cash_out - net_premiums) / shares_held

    if shares_held > 0 and active_call_strike is not None:
        wheel_status = "Covered call phase"
    elif shares_held > 0:
        wheel_status = "Holding assigned shares"
    elif active_put_strike is not None:
        wheel_status = "Cash-secured put phase"
    else:
        wheel_status = "Wheel cycle closed / no active legs"

    return {
        "net_premiums": net_premiums,
        "active_short_put_strike": active_put_strike,
        "active_covered_call_strike": active_call_strike,
        "break_even": break_even,
        "shares_held": shares_held,
        "net_stock_cost_basis": net_stock_cost_basis,
        "wheel_status": wheel_status,
    }


def build_wheel_summary(ticker: str, metrics: dict[str, float | str | None]) -> str:
    status = metrics["wheel_status"]
    net_premiums = metrics["net_premiums"]
    put_strike = metrics["active_short_put_strike"]
    call_strike = metrics["active_covered_call_strike"]
    shares = metrics["shares_held"]
    break_even = metrics["break_even"]
    cost_basis = metrics["net_stock_cost_basis"]

    if put_strike is not None and shares <= 0:
        return (
            f"You currently have an active short put on {ticker} at strike {put_strike:.2f}. "
            f"You have collected {net_premiums:,.2f} USD in net premiums, so your estimated break-even is {break_even:.2f}. "
            "You do not currently hold shares."
        )

    if shares > 0:
        summary = (
            f"You currently hold {shares:.0f} shares of {ticker}. "
            f"Your adjusted net cost basis is {cost_basis:.2f} per share after collected premiums ({net_premiums:,.2f} USD)."
        )
        if call_strike is not None:
            summary += f" You also have an active covered call at strike {call_strike:.2f}."
        return summary

    return f"Wheel status for {ticker}: {status}. Net premiums so far: {net_premiums:,.2f} USD."


def build_wheel_operations_table(ops: pd.DataFrame) -> pd.DataFrame:
    if ops.empty:
        return ops
    table = ops.copy()
    table["derived_operation"] = table.apply(_derive_operation_label, axis=1)
    table["put_call"] = table["leg_type"].where(table["leg_type"].isin(["PUT", "CALL"]), "-")
    return table[[
        "event_date",
        "ticker",
        "instrument_type",
        "derived_operation",
        "put_call",
        "strike",
        "expiration",
        "quantity",
        "premium",
        "execution_price",
        "net_cash_effect",
        "status",
        "notes",
    ]].rename(columns={"event_date": "date", "ticker": "asset", "derived_operation": "operation_type"})
