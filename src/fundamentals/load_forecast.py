"""
Weather-Driven Peak Load Forecaster

Converts weekly HDD/CDD forecasts into expected peak load (MW) for each
ISO. This is the demand side of the stack dispatch — the load number that
the marginal generator has to be dispatched to meet.

Calibration uses rough empirical load-weather sensitivities by ISO. In
production this would be a rolling regression on the ISO's own load history
with day-of-week and holiday controls.
"""

from dataclasses import dataclass
import pandas as pd


@dataclass
class ISOLoadParams:
    base_load_mw: float
    hdd_sensitivity_mw_per_unit: float
    cdd_sensitivity_mw_per_unit: float
    summer_peak_mw: float
    winter_peak_mw: float


# Rough calibrations consistent with public ISO peak-load reports.
ISO_LOAD_PARAMS = {
    "PJM": ISOLoadParams(80_000, 1_200, 1_800, 155_000, 140_000),
    "MISO": ISOLoadParams(65_000, 900, 1_400, 125_000, 110_000),
    "ISONE": ISOLoadParams(12_000, 220, 320, 26_000, 22_000),
}


class LoadForecaster:
    """
    Weekly peak-load forecaster for a single ISO.

    Usage
    -----
    >>> lf = LoadForecaster("PJM")
    >>> lf.forecast_peak_load(hdd=45, cdd=0)
    134000.0
    """

    def __init__(self, iso: str):
        if iso not in ISO_LOAD_PARAMS:
            raise ValueError(f"Unknown ISO: {iso}. Choose from {list(ISO_LOAD_PARAMS)}")
        self.iso = iso
        self.params = ISO_LOAD_PARAMS[iso]

    def forecast_peak_load(self, hdd: float, cdd: float,
                          dow_factor: float = 1.0) -> float:
        """
        Forecast weekly on-peak load (MW).

        dow_factor lets you toggle a weekday vs weekend adjustment
        (default 1.0 = average weekday).
        """
        p = self.params
        load = p.base_load_mw
        load += p.hdd_sensitivity_mw_per_unit * max(0, hdd)
        load += p.cdd_sensitivity_mw_per_unit * max(0, cdd)
        # Cap at extreme heat/cold peak (avoids unrealistic blow-outs)
        cap = max(p.summer_peak_mw, p.winter_peak_mw) * 1.05
        return min(load * dow_factor, cap)

    def forecast_series(self, weather_df: pd.DataFrame) -> pd.DataFrame:
        """Apply forecast across a weather DataFrame."""
        out = weather_df.copy()
        out["peak_load_mw_forecast"] = out.apply(
            lambda r: self.forecast_peak_load(r["hdd_actual"], r["cdd_actual"]),
            axis=1,
        )
        out["iso"] = self.iso
        return out[["date", "iso", "peak_load_mw_forecast", "hdd_actual", "cdd_actual"]]
