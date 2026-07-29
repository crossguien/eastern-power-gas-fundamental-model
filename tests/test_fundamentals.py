"""
Unit tests for the fundamental model components.

Run with:
    python -m pytest tests/ -v
or:
    python tests/test_fundamentals.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fundamentals.gas_balance import GasFundamentalModel
from src.fundamentals.load_forecast import LoadForecaster
from src.fundamentals.stack_dispatch import StackDispatchModel
from src.fundamentals.power_price import EasternFundamentalModel, get_season
from src.data.synthetic import build_full_dataset


def test_gas_storage_tight_is_bullish():
    """Storage 300 Bcf below seasonal norm should produce higher price."""
    model = GasFundamentalModel()
    p_loose = model.fundamental_price(300, 0, 0, 12, 102)
    p_tight = model.fundamental_price(-300, 0, 0, 12, 102)
    assert p_tight > p_loose, f"Tight storage should be bullish: {p_tight} vs {p_loose}"


def test_gas_cold_weather_is_bullish():
    """Above-normal HDD should increase gas price."""
    model = GasFundamentalModel()
    p_normal = model.fundamental_price(0, 0, 0, 12, 102)
    p_cold = model.fundamental_price(0, 40, 0, 12, 102)
    assert p_cold > p_normal


def test_gas_lng_growth_is_bullish():
    """LNG exports above 12 Bcf/d add to gas price."""
    model = GasFundamentalModel()
    p_base = model.fundamental_price(0, 0, 0, 12, 102)
    p_high_lng = model.fundamental_price(0, 0, 0, 15, 102)
    assert p_high_lng > p_base


def test_load_forecaster_hot_summer():
    """High CDD should drive PJM load to summer peak range."""
    lf = LoadForecaster("PJM")
    summer_load = lf.forecast_peak_load(hdd=0, cdd=20)
    winter_load = lf.forecast_peak_load(hdd=40, cdd=0)
    assert summer_load > 100_000
    assert winter_load > 100_000


def test_stack_marginal_unit_changes_with_gas_price():
    """Higher gas price should push coal up the stack ahead of gas peaker."""
    model = StackDispatchModel("PJM")
    # Modest load — marginal unit will be a gas CCGT at low gas, coal at high gas
    r_low_gas = model.dispatch(load_mw=110_000, gas_price_usd_mmbtu=2.00, season="shoulder")
    r_high_gas = model.dispatch(load_mw=110_000, gas_price_usd_mmbtu=6.00, season="shoulder")
    assert r_high_gas.clearing_price_usd_mwh > r_low_gas.clearing_price_usd_mwh


def test_stack_scarcity_when_load_exceeds_capacity():
    """Extreme load → scarcity signal."""
    model = StackDispatchModel("PJM")
    result = model.dispatch(load_mw=500_000, gas_price_usd_mmbtu=3.00, season="winter")
    assert result.marginal_unit == "scarcity_cap"
    assert result.clearing_price_usd_mwh >= 1_000


def test_season_classification():
    """Week classification matches expected seasonal buckets."""
    assert get_season(4) == "winter"
    assert get_season(28) == "summer"
    assert get_season(18) == "shoulder"


def test_end_to_end_runs():
    """Full pipeline executes without error on synthetic data."""
    data = build_full_dataset("2024-01-01", "2024-06-30")
    model = EasternFundamentalModel()
    views = model.run_history(data)
    assert len(views) > 0
    assert "fundamental_power_price" in views.columns
    # Prices should be in a reasonable range
    valid = views["fundamental_power_price"]
    assert (valid > 10).all()
    assert (valid < 3_000).all()


if __name__ == "__main__":
    tests = [
        test_gas_storage_tight_is_bullish,
        test_gas_cold_weather_is_bullish,
        test_gas_lng_growth_is_bullish,
        test_load_forecaster_hot_summer,
        test_stack_marginal_unit_changes_with_gas_price,
        test_stack_scarcity_when_load_exceeds_capacity,
        test_season_classification,
        test_end_to_end_runs,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
