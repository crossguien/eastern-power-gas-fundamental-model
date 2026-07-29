"""
Synthetic Data Generator

Generates physically realistic synthetic data for all model inputs.
Used for offline demos, unit tests, and backtest scaffolding when
live API data is unavailable.

The synthetic data is calibrated to plausible Eastern Interconnect
behavior so the fundamental logic can be exercised end-to-end without
requiring API keys.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta


def _seasonal(week_of_year: int, amp: float, peak_week: int = 4) -> float:
    """Sinusoidal seasonal pattern. peak_week=4 → mid-winter peak (HDD)."""
    return amp * np.cos(2 * np.pi * (week_of_year - peak_week) / 52)


def generate_weather_history(start_date: str, end_date: str, region: str = "PJM",
                             seed: int = 42) -> pd.DataFrame:
    """
    Synthetic weekly weather data: HDD, CDD, and normal references.

    HDD = heating degree days (cold = high)
    CDD = cooling degree days (hot = high)
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start_date, end_date, freq="W-MON")
    out = []

    region_offsets = {"PJM": 0, "MISO": 5, "ISONE": 10}
    offset = region_offsets.get(region, 0)

    for d in dates:
        woy = d.isocalendar().week
        # Realistic weekly-average daily HDD/CDD
        # Winter peak (HDD): weeks 1-12 and 48-52, peak ~40
        hdd_normal = max(0, _seasonal(woy, amp=30, peak_week=4) + 12)
        # Summer peak (CDD): weeks 24-36, peak ~22
        cdd_normal = max(0, _seasonal(woy, amp=20, peak_week=30) - 3)

        # Weather noise — deviations from normal drive the trade signal
        hdd_actual = hdd_normal + rng.normal(0, 6) + offset * 0.2
        cdd_actual = max(0, cdd_normal + rng.normal(0, 4))

        out.append({
            "date": d,
            "week_of_year": woy,
            "hdd_normal": hdd_normal,
            "cdd_normal": cdd_normal,
            "hdd_actual": max(0, hdd_actual),
            "cdd_actual": cdd_actual,
            "hdd_deviation": hdd_actual - hdd_normal,
            "cdd_deviation": cdd_actual - cdd_normal,
            "region": region,
        })
    return pd.DataFrame(out)


def generate_gas_storage_history(start_date: str, end_date: str,
                                 seed: int = 43) -> pd.DataFrame:
    """
    Synthetic EIA-style weekly natural gas storage data.

    Replicates seasonal injection/withdrawal cycle plus stochastic
    deviations that drive price signal.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start_date, end_date, freq="W-FRI")
    out = []
    storage_level = 2500  # Bcf starting point

    for d in dates:
        woy = d.isocalendar().week
        # Injection season (April-Oct): weeks 14-43
        # Withdrawal season (Nov-March): weeks 44-13
        if 14 <= woy <= 43:
            net_change = 75 + rng.normal(0, 20)  # injection
        else:
            net_change = -110 + rng.normal(0, 30)  # withdrawal

        storage_level += net_change
        storage_level = max(1000, min(4200, storage_level))

        # 5-year seasonal average (deterministic reference)
        seasonal_avg = 2500 + _seasonal(woy, amp=800, peak_week=44)

        out.append({
            "date": d,
            "week_of_year": woy,
            "storage_bcf": storage_level,
            "storage_5yr_avg_bcf": seasonal_avg,
            "storage_deviation_bcf": storage_level - seasonal_avg,
            "net_change_bcf": net_change,
        })
    return pd.DataFrame(out)


def generate_gas_supply_demand(start_date: str, end_date: str,
                               seed: int = 44) -> pd.DataFrame:
    """Synthetic LNG export and dry gas production data."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start_date, end_date, freq="W-MON")
    out = []

    # Trend: LNG growing, production roughly flat
    for i, d in enumerate(dates):
        lng_trend = 11 + (i / len(dates)) * 4  # 11 → 15 Bcf/d
        lng_exports = lng_trend + rng.normal(0, 0.5)

        prod_baseline = 102 + (i / len(dates)) * 3
        production = prod_baseline + rng.normal(0, 1.2)

        out.append({
            "date": d,
            "lng_exports_bcfd": max(8, lng_exports),
            "production_bcfd": max(95, production),
        })
    return pd.DataFrame(out)


def generate_iso_load_history(start_date: str, end_date: str, iso: str = "PJM",
                              seed: int = 45) -> pd.DataFrame:
    """
    Synthetic weekly peak load data calibrated to each ISO's footprint.
    """
    rng = np.random.default_rng(seed)
    weather = generate_weather_history(start_date, end_date, region=iso, seed=seed)

    iso_params = {
        "PJM": {"base": 80000, "hdd_sens": 1200, "cdd_sens": 1800},
        "MISO": {"base": 65000, "hdd_sens": 900, "cdd_sens": 1400},
        "ISONE": {"base": 12000, "hdd_sens": 220, "cdd_sens": 320},
    }
    p = iso_params.get(iso, iso_params["PJM"])

    weather["peak_load_mw"] = (
        p["base"]
        + p["hdd_sens"] * weather["hdd_actual"]
        + p["cdd_sens"] * weather["cdd_actual"]
        + rng.normal(0, p["base"] * 0.02, len(weather))
    )
    weather["iso"] = iso
    return weather[["date", "iso", "peak_load_mw", "hdd_actual", "cdd_actual"]]


def generate_gas_prices(start_date: str, end_date: str, seed: int = 46) -> pd.DataFrame:
    """
    Synthetic Henry Hub + basis to regional hubs.

    Basis spreads to NE Mass widen in winter (heating demand).
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start_date, end_date, freq="W-MON")
    out = []

    for d in dates:
        woy = d.isocalendar().week
        # Henry Hub baseline with seasonal kick
        hh = 3.0 + _seasonal(woy, amp=1.0, peak_week=4) + rng.normal(0, 0.4)
        hh = max(1.50, hh)

        # Basis widens sharply in winter for NE
        algonquin_basis = max(0.20, _seasonal(woy, amp=4.0, peak_week=4) + 0.5
                              + rng.normal(0, 0.6))
        chicago_basis = -0.10 + rng.normal(0, 0.15)
        transco_z6_basis = max(0.10, _seasonal(woy, amp=1.5, peak_week=4) + 0.30
                               + rng.normal(0, 0.30))

        out.append({
            "date": d,
            "henry_hub_usd_mmbtu": hh,
            "algonquin_basis": algonquin_basis,
            "chicago_basis": chicago_basis,
            "transco_z6_basis": transco_z6_basis,
            "algonquin_price": hh + algonquin_basis,
            "chicago_price": hh + chicago_basis,
            "transco_z6_price": hh + transco_z6_basis,
        })
    return pd.DataFrame(out)


def generate_power_prices(start_date: str, end_date: str, seed: int = 47) -> pd.DataFrame:
    """
    Synthetic realized weekly on-peak power prices at three hubs.

    Generated to be physically driven by gas prices, weather, and storage
    deviation so the fundamental model has a real signal to extract.

    realized = base + gas_price_effect + weather_effect + storage_effect + noise
    """
    rng = np.random.default_rng(seed)

    # Pull the same gas and storage series the model will see
    gas_df = generate_gas_prices(start_date, end_date, seed=46).set_index("date")
    storage_df = generate_gas_storage_history(start_date, end_date, seed=43)
    weather_df = generate_weather_history(start_date, end_date, "PJM", seed=42)

    # Reindex storage and weather to weekly Monday
    storage_df["date"] = storage_df["date"] - pd.Timedelta(days=4)  # Fri → Mon
    storage_df = storage_df.set_index("date")
    weather_df = weather_df.set_index("date")

    dates = pd.date_range(start_date, end_date, freq="W-MON")
    out = []

    for d in dates:
        woy = d.isocalendar().week
        # Look up nearest gas/storage/weather observation
        try:
            hh = gas_df.iloc[gas_df.index.get_indexer([d], method="nearest")[0]]["henry_hub_usd_mmbtu"]
        except Exception:
            hh = 3.0
        try:
            storage_dev = storage_df.iloc[storage_df.index.get_indexer([d], method="nearest")[0]]["storage_deviation_bcf"]
        except Exception:
            storage_dev = 0
        try:
            w = weather_df.iloc[weather_df.index.get_indexer([d], method="nearest")[0]]
            hdd_dev = w["hdd_deviation"]
            cdd_dev = w["cdd_deviation"]
        except Exception:
            hdd_dev = cdd_dev = 0

        winter_kick = max(0, _seasonal(woy, amp=18, peak_week=4))
        summer_kick = max(0, _seasonal(woy, amp=12, peak_week=30))

        # Physical drivers: gas price × heat rate, weather demand, storage tightness
        # PJM West marginal HR ~7500 in winter, ~10500 in summer peak
        marginal_hr = 8500 + winter_kick * 50 + summer_kick * 80
        gas_pass_through = (marginal_hr / 1000.0) * hh
        weather_premium = 0.25 * hdd_dev + 0.20 * cdd_dev
        storage_premium = -0.008 * storage_dev  # tight storage → power premium

        pjm_west = (
            6.0 + gas_pass_through + weather_premium * 0.7
            + storage_premium * 0.5 + winter_kick * 0.4 + rng.normal(0, 5)
        )
        ne_mass = (
            14.0 + gas_pass_through * 1.15 + weather_premium * 1.3
            + storage_premium + winter_kick * 1.1 + rng.normal(0, 8)
        )
        miso_indiana = (
            5.0 + gas_pass_through + weather_premium * 0.6
            + storage_premium * 0.4 + summer_kick * 0.7 + rng.normal(0, 4)
        )

        out.append({
            "date": d,
            "pjm_west_realized": max(15, pjm_west),
            "ne_mass_realized": max(20, ne_mass),
            "miso_indiana_realized": max(15, miso_indiana),
        })
    return pd.DataFrame(out)


def generate_forward_curve(start_date: str, end_date: str, seed: int = 48) -> pd.DataFrame:
    """
    Synthetic weekly forward curve marks.

    Forward curves reflect a smoothed seasonal expectation of fundamentals.
    They DON'T fully react to weather or storage surprises — that's exactly
    where the fundamental model finds its edge.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start_date, end_date, freq="W-MON")
    out = []

    for d in dates:
        woy = d.isocalendar().week
        # Forward curve reflects normalized seasonal expectations
        winter_kick = max(0, _seasonal(woy, amp=18, peak_week=4))
        summer_kick = max(0, _seasonal(woy, amp=12, peak_week=30))
        # Implied gas heat rate around 8500 at $3.20 = ~$27 + small premium
        baseline_power = 32 + winter_kick + summer_kick * 0.8

        out.append({
            "date": d,
            "pjm_west_forward": baseline_power + rng.normal(0, 2),
            "ne_mass_forward": baseline_power * 1.25 + winter_kick * 0.4 + rng.normal(0, 3),
            "miso_indiana_forward": baseline_power * 0.95 + rng.normal(0, 2),
            "hh_forward": 3.20 + 0.5 * np.cos(2 * np.pi * (woy - 4) / 52) + rng.normal(0, 0.10),
        })
    return pd.DataFrame(out)


def build_full_dataset(start_date: str = "2021-01-01",
                      end_date: str = "2025-12-31") -> dict:
    """
    Build a complete synthetic dataset for all three ISOs.

    Returns a dict of DataFrames keyed by data source.
    """
    return {
        "gas_storage": generate_gas_storage_history(start_date, end_date),
        "gas_supply_demand": generate_gas_supply_demand(start_date, end_date),
        "gas_prices": generate_gas_prices(start_date, end_date),
        "weather_pjm": generate_weather_history(start_date, end_date, "PJM"),
        "weather_miso": generate_weather_history(start_date, end_date, "MISO"),
        "weather_isone": generate_weather_history(start_date, end_date, "ISONE"),
        "load_pjm": generate_iso_load_history(start_date, end_date, "PJM"),
        "load_miso": generate_iso_load_history(start_date, end_date, "MISO"),
        "load_isone": generate_iso_load_history(start_date, end_date, "ISONE"),
        "power_prices_realized": generate_power_prices(start_date, end_date),
        "forward_curve": generate_forward_curve(start_date, end_date),
    }


if __name__ == "__main__":
    data = build_full_dataset()
    for name, df in data.items():
        print(f"{name}: {len(df)} rows")
        print(df.head(2))
        print()
