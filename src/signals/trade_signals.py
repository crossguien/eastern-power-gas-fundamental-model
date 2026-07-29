"""
Trade Signal Generation

Compares the model's fundamental view to the prevailing forward curve and
generates directional signals when the gap exceeds a configurable threshold.

This is the spec trader's core workflow:
    fundamental view > forward curve  →  buy (length) the forward
    fundamental view < forward curve  →  sell (short) the forward

A signal's "edge" is the size of the gap relative to historical noise.
Position sizing scales with edge confidence.
"""

from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class SignalConfig:
    # Minimum gap (in $/MWh for power, $/MMBtu for gas) to fire a signal
    min_power_gap_usd_mwh: float = 3.00
    min_gas_gap_usd_mmbtu: float = 0.20
    # Position sizing: scale up to this much at max conviction
    max_position_size: float = 1.0
    # Conviction normalizer — how big a gap counts as "max conviction"
    full_conviction_power_gap: float = 12.00
    full_conviction_gas_gap: float = 0.80


HUB_FORWARD_COL = {
    "pjm_west": "pjm_west_forward",
    "ne_mass": "ne_mass_forward",
    "miso_indiana": "miso_indiana_forward",
}

HUB_REALIZED_COL = {
    "pjm_west": "pjm_west_realized",
    "ne_mass": "ne_mass_realized",
    "miso_indiana": "miso_indiana_realized",
}


class SignalGenerator:
    """
    Generates directional trade signals from fundamental views.

    Usage
    -----
    >>> gen = SignalGenerator()
    >>> signals = gen.generate_power_signals(fundamental_views, forward_curve)
    """

    def __init__(self, config: SignalConfig | None = None):
        self.config = config or SignalConfig()

    def generate_power_signals(self, fundamental_df: pd.DataFrame,
                               forward_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate power signals across all hubs.

        Returns a DataFrame with one row per (date, hub) including:
            direction (-1/0/+1), gap, conviction, position_size
        """
        cfg = self.config
        out_rows = []

        for hub, fwd_col in HUB_FORWARD_COL.items():
            sub = fundamental_df[fundamental_df["hub"] == hub].copy()
            merged = pd.merge_asof(
                sub.sort_values("date"),
                forward_df[["date", fwd_col]].sort_values("date"),
                on="date",
                direction="nearest",
            )
            merged["forward_price"] = merged[fwd_col]
            merged["gap"] = merged["fundamental_power_price"] - merged["forward_price"]

            # Direction
            merged["direction"] = 0
            merged.loc[merged["gap"] >= cfg.min_power_gap_usd_mwh, "direction"] = 1
            merged.loc[merged["gap"] <= -cfg.min_power_gap_usd_mwh, "direction"] = -1

            # Conviction & sizing
            merged["conviction"] = (
                merged["gap"].abs() / cfg.full_conviction_power_gap
            ).clip(0, 1)
            merged["position_size"] = (
                merged["direction"] * merged["conviction"] * cfg.max_position_size
            )

            out_rows.append(merged[[
                "date", "hub", "fundamental_power_price", "forward_price",
                "gap", "direction", "conviction", "position_size",
            ]])

        return pd.concat(out_rows, ignore_index=True).sort_values(["date", "hub"])

    def generate_gas_signal(self, fundamental_df: pd.DataFrame,
                           forward_df: pd.DataFrame) -> pd.DataFrame:
        """Generate Henry Hub directional signal."""
        cfg = self.config
        # All hubs share the gas fundamental — just take pjm_west rows
        sub = fundamental_df[fundamental_df["hub"] == "pjm_west"].copy()
        merged = pd.merge_asof(
            sub.sort_values("date"),
            forward_df[["date", "hh_forward"]].sort_values("date"),
            on="date",
            direction="nearest",
        )
        merged["gas_gap"] = merged["fundamental_gas_price"] - merged["hh_forward"]
        merged["gas_direction"] = 0
        merged.loc[merged["gas_gap"] >= cfg.min_gas_gap_usd_mmbtu, "gas_direction"] = 1
        merged.loc[merged["gas_gap"] <= -cfg.min_gas_gap_usd_mmbtu, "gas_direction"] = -1
        merged["gas_conviction"] = (
            merged["gas_gap"].abs() / cfg.full_conviction_gas_gap
        ).clip(0, 1)
        return merged[[
            "date", "fundamental_gas_price", "hh_forward",
            "gas_gap", "gas_direction", "gas_conviction",
        ]]
