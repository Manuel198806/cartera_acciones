from __future__ import annotations

import numpy as np
import pandas as pd


def default_leg_price(row: pd.Series, mode: str) -> float:
    bid, ask, mid = row.get("bid"), row.get("ask"), row.get("mid")
    if mode == "mid" and pd.notna(mid):
        return float(mid)
    if row.get("action") == "SELL":
        return float(bid) if pd.notna(bid) else (float(mid) if pd.notna(mid) else 0.0)
    return float(ask) if pd.notna(ask) else (float(mid) if pd.notna(mid) else 0.0)


def cash_secured_put_metrics(leg: pd.Series) -> dict[str, float]:
    credit = float(leg["selected_price"])
    strike = float(leg["strike"])
    return {
        "net_credit": credit,
        "max_profit": credit * 100,
        "max_loss": (strike - credit) * 100,
        "breakeven_low": strike - credit,
        "breakeven_high": np.nan,
        "collateral": strike * 100,
    }


def payoff_at_expiration(legs: pd.DataFrame, price_grid: np.ndarray) -> np.ndarray:
    pnl = np.zeros_like(price_grid, dtype=float)
    for _, leg in legs.iterrows():
        k = float(leg["strike"])
        q = float(leg.get("quantity", 1))
        premium = float(leg["selected_price"])
        right = str(leg["right"]).upper()
        action = str(leg["action"]).upper()
        if right == "C":
            intrinsic = np.maximum(price_grid - k, 0)
        else:
            intrinsic = np.maximum(k - price_grid, 0)
        leg_pnl = (premium - intrinsic) if action == "SELL" else (intrinsic - premium)
        pnl += leg_pnl * q * 100
    return pnl
