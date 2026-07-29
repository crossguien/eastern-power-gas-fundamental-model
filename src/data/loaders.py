"""
Live Data Loaders

Production data sources for the fundamental model. Stubs are provided
showing the canonical API endpoints; in production each function returns
a DataFrame matching the schema of the synthetic equivalent in
src/data/synthetic.py so they're drop-in replaceable.

API keys are loaded from environment variables:
    EIA_API_KEY       — https://www.eia.gov/opendata/register.php
    NOAA_TOKEN        — https://www.ncdc.noaa.gov/cdo-web/token
    PJM_API_KEY       — Data Miner 2 (PJM)
    MISO_PUBLIC_API   — MISO public data (no key required)
"""

import os
import pandas as pd
import requests


# --- EIA: Natural Gas Storage (weekly) -----------------------------------------

def fetch_eia_weekly_storage(start_date: str, end_date: str) -> pd.DataFrame:
    """
    EIA Weekly Working Gas in Underground Storage (lower 48).

    Series ID: NG.NW2_EPG0_SWO_R48_BCF.W
    Endpoint: https://api.eia.gov/v2/natural-gas/stor/wkly/data/
    """
    api_key = os.getenv("EIA_API_KEY")
    if not api_key:
        raise RuntimeError("EIA_API_KEY not set — fall back to synthetic data")
    url = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
    params = {
        "api_key": api_key,
        "frequency": "weekly",
        "data[0]": "value",
        "facets[series][]": "NW2_EPG0_SWO_R48_BCF",
        "start": start_date,
        "end": end_date,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()["response"]["data"]
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["period"])
    df["storage_bcf"] = df["value"].astype(float)
    return df[["date", "storage_bcf"]].sort_values("date").reset_index(drop=True)


def fetch_eia_lng_exports(start_date: str, end_date: str) -> pd.DataFrame:
    """
    EIA Natural Gas Pipeline & LNG Exports (monthly, interpolated to weekly).

    Series: NG.N9133US2.M (LNG Exports)
    """
    raise NotImplementedError("Implement EIA monthly export pull and weekly interp")


# --- NOAA: Weather (HDD/CDD) ---------------------------------------------------

def fetch_noaa_hdd_cdd(start_date: str, end_date: str, region: str) -> pd.DataFrame:
    """
    NOAA CDO Weather data — population-weighted HDD/CDD by region.

    Endpoint: https://www.ncei.noaa.gov/cdo-web/api/v2/data
    Dataset: GHCND for raw temperature, then compute HDD/CDD with base 65°F.
    Region mapping uses NERC subregion FIPS codes.
    """
    raise NotImplementedError("Implement NOAA station pull + HDD/CDD computation")


# --- PJM Data Miner 2 ----------------------------------------------------------

def fetch_pjm_load_forecast(start_date: str, end_date: str) -> pd.DataFrame:
    """
    PJM hourly load forecast → roll up to weekly peak.

    Dataset: hrl_load_forecasts
    Endpoint: https://api.pjm.com/api/v1/hrl_load_forecasts
    """
    raise NotImplementedError("Implement PJM Data Miner 2 load pull")


def fetch_pjm_da_lmp(start_date: str, end_date: str, pnodes: list) -> pd.DataFrame:
    """
    PJM Day-Ahead hourly LMP by pnode → roll up to weekly on-peak average.

    Dataset: da_hrl_lmps
    """
    raise NotImplementedError("Implement PJM Data Miner 2 LMP pull")


# --- MISO / ISO-NE -------------------------------------------------------------

def fetch_miso_load(start_date: str, end_date: str) -> pd.DataFrame:
    """MISO public data — daily peak load, aggregated to weekly."""
    raise NotImplementedError("Implement MISO public data pull")


def fetch_isone_load(start_date: str, end_date: str) -> pd.DataFrame:
    """ISO-NE web services API."""
    raise NotImplementedError("Implement ISO-NE web services pull")


# --- Henry Hub & Basis ---------------------------------------------------------

def fetch_henry_hub_spot(start_date: str, end_date: str) -> pd.DataFrame:
    """
    EIA Henry Hub daily spot → weekly average.

    Series: NG.RNGWHHD.D
    """
    api_key = os.getenv("EIA_API_KEY")
    if not api_key:
        raise RuntimeError("EIA_API_KEY not set")
    url = "https://api.eia.gov/v2/natural-gas/pri/sum/data/"
    raise NotImplementedError("Implement EIA HH daily spot pull")
