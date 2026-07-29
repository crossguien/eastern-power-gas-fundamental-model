"""
Natural Gas Fundamental Balance Model

Derives a fundamental view on Henry Hub natural gas prices from physical
supply/demand inputs:

    Drivers              Direction
    ─────────────────────────────────
    Storage deviation    Tight  → bullish
    HDD vs normal        Above  → bullish (heating demand)
    CDD vs normal        Above  → bullish (gas-fired power gen)
    LNG exports          Higher → bullish
    Dry gas production   Higher → bearish

Empirical sensitivities are calibrated to historical EIA storage report
reactions and rough rules of thumb traders use to handicap Thursday's
print. Real production calibration would use rolling regressions on the
storage-price beta.
"""

from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class GasModelConfig:
    baseline_price: float = 3.50       # $/MMBtu reference
    storage_beta: float = 0.0015       # $/MMBtu per Bcf storage deviation
    hdd_beta: float = 0.005            # $/MMBtu per HDD vs normal
    cdd_beta: float = 0.004            # $/MMBtu per CDD vs normal
    lng_beta: float = 0.08             # $/MMBtu per Bcf/d LNG above 12
    production_beta: float = 0.12      # $/MMBtu per Bcf/d production above 102
    price_floor: float = 1.50          # $/MMBtu — no model below this
    price_ceiling: float = 15.00       # $/MMBtu — winter scarcity cap


class GasFundamentalModel:
    """
    Weekly fundamental price model for Henry Hub.

    Usage
    -----
    >>> model = GasFundamentalModel()
    >>> price = model.fundamental_price(
    ...     storage_deviation_bcf=-150,    # tight
    ...     hdd_deviation=45,              # cold week
    ...     cdd_deviation=0,
    ...     lng_exports_bcfd=14.0,
    ...     production_bcfd=104.5,
    ... )
    """

    def __init__(self, config: GasModelConfig | None = None):
        self.config = config or GasModelConfig()

    def fundamental_price(self, storage_deviation_bcf: float, hdd_deviation: float,
                         cdd_deviation: float, lng_exports_bcfd: float,
                         production_bcfd: float) -> float:
        """Single-week fundamental price view in $/MMBtu."""
        cfg = self.config
        # Storage tight (negative deviation) is bullish: subtract negative = add
        price = cfg.baseline_price
        price -= cfg.storage_beta * storage_deviation_bcf
        price += cfg.hdd_beta * hdd_deviation
        price += cfg.cdd_beta * cdd_deviation
        price += cfg.lng_beta * max(0.0, lng_exports_bcfd - 12.0)
        price -= cfg.production_beta * max(0.0, production_bcfd - 102.0)
        return float(np.clip(price, cfg.price_floor, cfg.price_ceiling))

    def run_history(self, storage_df: pd.DataFrame, weather_df: pd.DataFrame,
                    supply_demand_df: pd.DataFrame) -> pd.DataFrame:
        """
        Run the gas model across a historical window and return a DataFrame
        with weekly fundamental price views.
        """
        # Use the gas-region weather (PJM-ish proxy for Eastern HDD demand)
        merged = storage_df.merge(weather_df, on="week_of_year", suffixes=("", "_w"))
        # Align by closest week
        merged = pd.merge_asof(
            storage_df.sort_values("date"),
            supply_demand_df.sort_values("date"),
            on="date",
            direction="nearest",
        )
        merged = pd.merge_asof(
            merged.sort_values("date"),
            weather_df.sort_values("date")[["date", "hdd_deviation", "cdd_deviation"]],
            on="date",
            direction="nearest",
        )

        rows = []
        for _, r in merged.iterrows():
            p = self.fundamental_price(
                storage_deviation_bcf=r["storage_deviation_bcf"],
                hdd_deviation=r["hdd_deviation"],
                cdd_deviation=r["cdd_deviation"],
                lng_exports_bcfd=r["lng_exports_bcfd"],
                production_bcfd=r["production_bcfd"],
            )
            rows.append({"date": r["date"], "hh_fundamental": p})
        return pd.DataFrame(rows)
