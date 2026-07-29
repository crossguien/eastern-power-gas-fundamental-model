"""
Walk-Forward Backtest

Evaluates signal performance against realized prices.

P&L convention
--------------
Going long the forward at price F and the realized price R clears at:
    P&L = (R - F) * position_size * scaling

This is a paper backtest — no execution costs, no slippage, no margin.
It measures whether the fundamental signal carries information about
forward-realized mispricings.
"""

from dataclasses import dataclass
import pandas as pd
import numpy as np


HUB_REALIZED_COL = {
    "pjm_west": "pjm_west_realized",
    "ne_mass": "ne_mass_realized",
    "miso_indiana": "miso_indiana_realized",
}


@dataclass
class BacktestSummary:
    hub: str
    n_signals: int
    hit_rate: float          # % of signals where direction was correct
    avg_pnl_per_signal: float  # $/MWh
    sharpe_annualized: float
    max_drawdown: float
    total_pnl: float
    long_hit_rate: float
    short_hit_rate: float


def run_power_backtest(signals_df: pd.DataFrame, realized_df: pd.DataFrame,
                      mwh_per_unit: float = 100.0) -> tuple[pd.DataFrame, list[BacktestSummary]]:
    """
    Backtest power signals against realized prices.

    Returns:
        trades_df    — per-signal P&L
        summaries    — one summary per hub
    """
    trades_rows = []
    summaries = []

    for hub, realized_col in HUB_REALIZED_COL.items():
        hub_signals = signals_df[signals_df["hub"] == hub].copy()
        merged = pd.merge_asof(
            hub_signals.sort_values("date"),
            realized_df[["date", realized_col]].sort_values("date"),
            on="date",
            direction="nearest",
        )
        merged["realized_price"] = merged[realized_col]
        # P&L per signal: (realized - forward) * direction * conviction * scaling
        merged["pnl_usd_mwh"] = (
            (merged["realized_price"] - merged["forward_price"])
            * merged["direction"]
            * merged["conviction"]
        )
        merged["pnl_total"] = merged["pnl_usd_mwh"] * mwh_per_unit

        trades_rows.append(merged.assign(hub=hub))

        active = merged[merged["direction"] != 0].copy()
        if len(active) == 0:
            continue

        # Hit rate: correct direction calls (realized moved in our favor)
        active["was_correct"] = (
            ((active["direction"] > 0) & (active["realized_price"] > active["forward_price"]))
            | ((active["direction"] < 0) & (active["realized_price"] < active["forward_price"]))
        )
        long_signals = active[active["direction"] > 0]
        short_signals = active[active["direction"] < 0]

        # Sharpe — weekly P&L variance scaled to annualized
        weekly_pnl = active["pnl_usd_mwh"].values
        sharpe = (weekly_pnl.mean() / weekly_pnl.std() * np.sqrt(52)
                  if weekly_pnl.std() > 0 else 0)

        # Max drawdown on cumulative P&L
        cum = active["pnl_usd_mwh"].cumsum()
        running_max = cum.cummax()
        drawdown = (cum - running_max).min()

        summaries.append(BacktestSummary(
            hub=hub,
            n_signals=len(active),
            hit_rate=float(active["was_correct"].mean()),
            avg_pnl_per_signal=float(active["pnl_usd_mwh"].mean()),
            sharpe_annualized=float(sharpe),
            max_drawdown=float(drawdown),
            total_pnl=float(active["pnl_usd_mwh"].sum()),
            long_hit_rate=float(long_signals["was_correct"].mean()) if len(long_signals) else 0,
            short_hit_rate=float(short_signals["was_correct"].mean()) if len(short_signals) else 0,
        ))

    trades_df = pd.concat(trades_rows, ignore_index=True) if trades_rows else pd.DataFrame()
    return trades_df, summaries


def print_summaries(summaries: list[BacktestSummary]) -> None:
    """Print a clean summary table."""
    print("\n" + "=" * 88)
    print(f"{'Hub':<18} {'N':>6} {'Hit%':>8} {'Avg P&L':>10} {'Sharpe':>8} {'MaxDD':>10} {'Total':>10}")
    print("=" * 88)
    for s in summaries:
        print(f"{s.hub:<18} {s.n_signals:>6} {s.hit_rate*100:>7.1f}% "
              f"{s.avg_pnl_per_signal:>9.2f} {s.sharpe_annualized:>8.2f} "
              f"{s.max_drawdown:>9.2f} {s.total_pnl:>9.2f}")
    print("=" * 88)
