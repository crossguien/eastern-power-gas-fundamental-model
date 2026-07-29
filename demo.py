"""
Eastern Power & Gas Fundamental Price Model — End-to-End Demo

Runs the full pipeline on synthetic data:

    1. Generate synthetic input data
    2. Run fundamental gas + power price model across history
    3. Generate trade signals vs forward curve
    4. Backtest signal performance
    5. Print summary statistics

Run with:
    python demo.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data.synthetic import build_full_dataset
from src.fundamentals.power_price import EasternFundamentalModel
from src.signals.trade_signals import SignalGenerator
from src.backtest.walk_forward import run_power_backtest, print_summaries


def main():
    print("=" * 88)
    print("Eastern Power & Gas Fundamental Price Model — Demo Run")
    print("=" * 88)

    # 1. Generate data
    print("\n[1/4] Generating synthetic dataset (2021-2025)...")
    data = build_full_dataset("2021-01-01", "2025-12-31")
    print(f"      Gas storage:   {len(data['gas_storage'])} weekly observations")
    print(f"      Weather (PJM): {len(data['weather_pjm'])} weeks")
    print(f"      Power prices:  {len(data['power_prices_realized'])} weeks")

    # 2. Run fundamental model
    print("\n[2/4] Running fundamental model across history...")
    model = EasternFundamentalModel()
    fundamental_views = model.run_history(data)
    print(f"      Generated {len(fundamental_views)} weekly views across 3 hubs")
    print("\n      Sample fundamental views:")
    print(fundamental_views.head(6).to_string(index=False))

    # 3. Generate signals vs forward curve
    print("\n[3/4] Generating trade signals vs forward curve...")
    sig_gen = SignalGenerator()
    power_signals = sig_gen.generate_power_signals(fundamental_views, data["forward_curve"])
    gas_signals = sig_gen.generate_gas_signal(fundamental_views, data["forward_curve"])

    n_active = (power_signals["direction"] != 0).sum()
    n_long = (power_signals["direction"] > 0).sum()
    n_short = (power_signals["direction"] < 0).sum()
    print(f"      Active power signals: {n_active} / {len(power_signals)} "
          f"({n_long} long, {n_short} short)")

    # 4. Backtest
    print("\n[4/4] Backtesting signals against realized prices...")
    trades_df, summaries = run_power_backtest(
        power_signals, data["power_prices_realized"]
    )
    print_summaries(summaries)

    # Show a few example signals
    print("\nExample signals (high-conviction):")
    high_conv = power_signals[power_signals["conviction"] > 0.5].head(8)
    if not high_conv.empty:
        cols = ["date", "hub", "fundamental_power_price", "forward_price",
                "gap", "direction", "conviction"]
        print(high_conv[cols].to_string(index=False))

    print("\n" + "=" * 88)
    print("Demo complete.")
    print("=" * 88)


if __name__ == "__main__":
    main()
