"""
Fundamental Power Price Model — End-to-End Orchestration

Wires the components together into a weekly fundamental price forecast
for each Eastern Interconnect hub:

    Weather → Load forecast
    Gas storage + weather + LNG + production → Fundamental gas price
    Gas price + load + season → Stack dispatch → Fundamental power price
    Add hub basis to localize from ISO clearing price to hub price

The output is a weekly fundamental view that can be compared against the
forward curve to identify mispricings.
"""

from dataclasses import dataclass
import pandas as pd

from src.fundamentals.gas_balance import GasFundamentalModel
from src.fundamentals.load_forecast import LoadForecaster
from src.fundamentals.stack_dispatch import StackDispatchModel


# Map ISO clearing price → hub price via average historical basis.
# In production these would be node-by-node basis maps.
HUB_BASIS_ADDER = {
    "pjm_west": 1.50,        # PJM West Hub small adder over ISO clearing
    "ne_mass": 4.50,         # NE Mass historically trades over ISO-NE clearing
    "miso_indiana": 0.75,    # Indiana Hub vs MISO clearing
}

HUB_TO_ISO = {
    "pjm_west": "PJM",
    "ne_mass": "ISONE",
    "miso_indiana": "MISO",
}


def get_season(week_of_year: int) -> str:
    if 22 <= week_of_year <= 38:
        return "summer"
    if week_of_year <= 11 or week_of_year >= 48:
        return "winter"
    return "shoulder"


@dataclass
class FundamentalView:
    date: pd.Timestamp
    hub: str
    fundamental_power_price: float
    fundamental_gas_price: float
    marginal_unit: str
    forecast_load_mw: float
    reserve_margin: float


class EasternFundamentalModel:
    """
    End-to-end fundamental price model for the Eastern Interconnect.

    Usage
    -----
    >>> from src.data.synthetic import build_full_dataset
    >>> data = build_full_dataset()
    >>> model = EasternFundamentalModel()
    >>> views = model.run_history(data)
    """

    def __init__(self):
        self.gas_model = GasFundamentalModel()
        self.load_forecasters = {
            "PJM": LoadForecaster("PJM"),
            "MISO": LoadForecaster("MISO"),
            "ISONE": LoadForecaster("ISONE"),
        }
        self.dispatchers = {
            "PJM": StackDispatchModel("PJM"),
            "MISO": StackDispatchModel("MISO"),
            "ISONE": StackDispatchModel("ISONE"),
        }

    def run_single_week(self, week_data: dict) -> list[FundamentalView]:
        """
        Run the fundamental model for a single week.

        week_data keys:
            date, week_of_year, storage_deviation_bcf, hdd_deviation,
            cdd_deviation, lng_exports_bcfd, production_bcfd,
            hdd_actual_pjm, cdd_actual_pjm, hdd_actual_miso, cdd_actual_miso,
            hdd_actual_isone, cdd_actual_isone,
            coal_price (optional)
        """
        # Step 1: fundamental gas price
        gas_price = self.gas_model.fundamental_price(
            storage_deviation_bcf=week_data["storage_deviation_bcf"],
            hdd_deviation=week_data["hdd_deviation"],
            cdd_deviation=week_data["cdd_deviation"],
            lng_exports_bcfd=week_data["lng_exports_bcfd"],
            production_bcfd=week_data["production_bcfd"],
        )

        season = get_season(week_data["week_of_year"])
        coal_price = week_data.get("coal_price", 2.20)

        views = []
        for hub, iso in HUB_TO_ISO.items():
            # Step 2: load forecast for this ISO
            hdd = week_data[f"hdd_actual_{iso.lower()}"]
            cdd = week_data[f"cdd_actual_{iso.lower()}"]
            load = self.load_forecasters[iso].forecast_peak_load(hdd, cdd)

            # Step 3: dispatch stack
            result = self.dispatchers[iso].dispatch(
                load_mw=load,
                gas_price_usd_mmbtu=gas_price,
                coal_price_usd_mmbtu=coal_price,
                season=season,
            )

            # Step 4: add hub basis to localize
            hub_price = result.clearing_price_usd_mwh + HUB_BASIS_ADDER[hub]

            views.append(FundamentalView(
                date=week_data["date"],
                hub=hub,
                fundamental_power_price=hub_price,
                fundamental_gas_price=gas_price,
                marginal_unit=result.marginal_unit,
                forecast_load_mw=load,
                reserve_margin=result.reserve_margin,
            ))
        return views

    def run_history(self, data: dict) -> pd.DataFrame:
        """
        Run the model across all weeks in the synthetic dataset.

        Returns a long-format DataFrame with one row per (date, hub).
        """
        # Merge all weekly inputs together
        gas_storage = data["gas_storage"].copy()
        gas_sd = data["gas_supply_demand"].copy()
        # PJM weather: keep deviations, rename actuals — drop week_of_year (already in gas_storage)
        weather_pjm = data["weather_pjm"].rename(columns={
            "hdd_actual": "hdd_actual_pjm", "cdd_actual": "cdd_actual_pjm",
        })[["date", "hdd_actual_pjm", "cdd_actual_pjm",
            "hdd_deviation", "cdd_deviation"]]
        weather_miso = data["weather_miso"].rename(columns={
            "hdd_actual": "hdd_actual_miso", "cdd_actual": "cdd_actual_miso",
        })[["date", "hdd_actual_miso", "cdd_actual_miso"]]
        weather_isone = data["weather_isone"].rename(columns={
            "hdd_actual": "hdd_actual_isone", "cdd_actual": "cdd_actual_isone",
        })[["date", "hdd_actual_isone", "cdd_actual_isone"]]

        # Align on date — gas storage is W-FRI, others are W-MON.
        # Use merge_asof to nearest weekly bucket.
        base = gas_storage.sort_values("date")
        for df in [gas_sd, weather_pjm, weather_miso, weather_isone]:
            base = pd.merge_asof(
                base.sort_values("date"),
                df.sort_values("date"),
                on="date",
                direction="nearest",
            )

        # The hdd_deviation/cdd_deviation columns came in from weather_pjm and
        # serve as the Eastern proxy for the gas model. No further renaming.

        all_views = []
        for _, r in base.iterrows():
            wd = {
                "date": r["date"],
                "week_of_year": int(r["week_of_year"]),
                "storage_deviation_bcf": r["storage_deviation_bcf"],
                "hdd_deviation": r["hdd_deviation"],
                "cdd_deviation": r["cdd_deviation"],
                "lng_exports_bcfd": r["lng_exports_bcfd"],
                "production_bcfd": r["production_bcfd"],
                "hdd_actual_pjm": r["hdd_actual_pjm"],
                "cdd_actual_pjm": r["cdd_actual_pjm"],
                "hdd_actual_miso": r["hdd_actual_miso"],
                "cdd_actual_miso": r["cdd_actual_miso"],
                "hdd_actual_isone": r["hdd_actual_isone"],
                "cdd_actual_isone": r["cdd_actual_isone"],
            }
            for v in self.run_single_week(wd):
                all_views.append({
                    "date": v.date,
                    "hub": v.hub,
                    "fundamental_power_price": v.fundamental_power_price,
                    "fundamental_gas_price": v.fundamental_gas_price,
                    "marginal_unit": v.marginal_unit,
                    "forecast_load_mw": v.forecast_load_mw,
                    "reserve_margin": v.reserve_margin,
                })
        return pd.DataFrame(all_views)
