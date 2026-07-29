"""
Generation Stack Dispatch Model

This is the heart of the fundamental power price model.

Theory
------
Wholesale power prices are set by the variable cost of the marginal
generator dispatched to meet load (plus any scarcity adder when reserves
are tight). To derive a fundamental price view, you:

    1. Build the supply curve: rank every generator by marginal cost
       (heat rate × fuel price + variable O&M).
    2. Derate for availability: outages, renewable capacity factors,
       hydro conditions.
    3. Dispatch the stack to meet forecast load.
    4. The marginal unit's cost = clearing price.
    5. If reserve margin is thin, add a scarcity adder.

This is what fundamental power desks do — though with deeper fleet data,
hourly resolution, and unit-by-unit derates from real outage schedules.
"""

from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class Generator:
    fuel: str                  # 'nuclear', 'hydro', 'wind', 'solar', 'gas_ccgt', 'gas_peaker', 'coal', 'oil'
    capacity_mw: float         # nameplate
    heat_rate_btu_kwh: float   # 0 for renewables/hydro
    variable_om_usd_mwh: float
    typical_outage_rate: float = 0.08  # planned + forced

    def marginal_cost_usd_mwh(self, gas_price: float, coal_price: float,
                              oil_price: float, uranium_price: float = 0.80) -> float:
        """Variable cost in $/MWh."""
        if "gas" in self.fuel:
            fuel_price = gas_price
        elif "coal" in self.fuel:
            fuel_price = coal_price
        elif "oil" in self.fuel:
            fuel_price = oil_price
        elif "nuclear" in self.fuel:
            fuel_price = uranium_price
        else:
            fuel_price = 0.0
        return (self.heat_rate_btu_kwh / 1000.0) * fuel_price + self.variable_om_usd_mwh


# Simplified representative fleets. Real implementation pulls from EIA-860.
PJM_FLEET = [
    Generator("nuclear", 33_000, 10_500, 2.0),
    Generator("hydro", 8_000, 0, 1.0),
    Generator("wind", 14_000, 0, 0.0),
    Generator("solar", 11_000, 0, 0.0),
    Generator("gas_ccgt_efficient", 48_000, 6_800, 3.0),
    Generator("gas_ccgt_average", 22_000, 7_500, 3.5),
    Generator("coal_subbit", 32_000, 9_800, 4.5),
    Generator("gas_peaker", 28_000, 10_500, 5.0),
    Generator("oil_peaker", 4_500, 12_000, 6.0),
]

MISO_FLEET = [
    Generator("nuclear", 13_000, 10_500, 2.0),
    Generator("hydro", 4_000, 0, 1.0),
    Generator("wind", 30_000, 0, 0.0),
    Generator("solar", 6_000, 0, 0.0),
    Generator("gas_ccgt_efficient", 25_000, 6_800, 3.0),
    Generator("gas_ccgt_average", 18_000, 7_500, 3.5),
    Generator("coal_subbit", 40_000, 9_800, 4.5),
    Generator("gas_peaker", 22_000, 10_500, 5.0),
    Generator("oil_peaker", 2_000, 12_000, 6.0),
]

ISONE_FLEET = [
    Generator("nuclear", 3_300, 10_500, 2.0),
    Generator("hydro", 2_000, 0, 1.0),
    Generator("wind", 1_400, 0, 0.0),
    Generator("solar", 5_000, 0, 0.0),
    Generator("gas_ccgt_efficient", 8_500, 6_800, 3.0),
    Generator("gas_ccgt_average", 5_500, 7_500, 3.5),
    Generator("coal_subbit", 600, 9_800, 4.5),
    Generator("gas_peaker", 4_000, 10_500, 5.0),
    Generator("oil_peaker", 2_500, 12_000, 6.0),
]

FLEETS = {"PJM": PJM_FLEET, "MISO": MISO_FLEET, "ISONE": ISONE_FLEET}

# Renewable capacity factors by season
RENEWABLE_CF = {
    "wind":  {"summer": 0.22, "winter": 0.38, "shoulder": 0.30},
    "solar": {"summer": 0.30, "winter": 0.13, "shoulder": 0.20},
}

NUCLEAR_CF = 0.92
HYDRO_CF_SEASONAL = {"summer": 0.35, "winter": 0.45, "shoulder": 0.55}


@dataclass
class DispatchResult:
    clearing_price_usd_mwh: float
    marginal_unit: str
    marginal_heat_rate: Optional[float]
    total_available_mw: float
    load_mw: float
    reserve_margin: float
    scarcity_adder: float
    stack_used: pd.DataFrame = field(default_factory=pd.DataFrame)


class StackDispatchModel:
    """
    Dispatches a regional generation stack to meet forecast load and
    returns the marginal clearing price.

    Usage
    -----
    >>> model = StackDispatchModel("PJM")
    >>> result = model.dispatch(
    ...     load_mw=125_000,
    ...     gas_price_usd_mmbtu=3.50,
    ...     coal_price_usd_mmbtu=2.20,
    ...     season="winter",
    ... )
    >>> result.clearing_price_usd_mwh
    """

    def __init__(self, iso: str):
        if iso not in FLEETS:
            raise ValueError(f"Unknown ISO: {iso}. Choose from {list(FLEETS)}")
        self.iso = iso
        self.fleet = FLEETS[iso]

    def _available_mw(self, gen: Generator, season: str) -> float:
        """Derate capacity for renewables CF, hydro, nuclear refueling, thermal outages."""
        cap = gen.capacity_mw
        if gen.fuel in RENEWABLE_CF:
            return cap * RENEWABLE_CF[gen.fuel][season]
        if gen.fuel == "nuclear":
            return cap * NUCLEAR_CF
        if gen.fuel == "hydro":
            return cap * HYDRO_CF_SEASONAL[season]
        # Thermal: account for planned + forced outages
        return cap * (1.0 - gen.typical_outage_rate)

    def build_stack(self, gas_price: float, coal_price: float, oil_price: float,
                   season: str) -> pd.DataFrame:
        """Build the cost-ordered supply stack with available capacity."""
        rows = []
        for g in self.fleet:
            mc = g.marginal_cost_usd_mwh(gas_price, coal_price, oil_price)
            avail = self._available_mw(g, season)
            rows.append({
                "fuel": g.fuel,
                "marginal_cost_usd_mwh": mc,
                "available_mw": avail,
                "heat_rate": g.heat_rate_btu_kwh,
                "capacity_mw": g.capacity_mw,
            })
        df = pd.DataFrame(rows).sort_values("marginal_cost_usd_mwh").reset_index(drop=True)
        df["cumulative_available_mw"] = df["available_mw"].cumsum()
        return df

    def dispatch(self, load_mw: float, gas_price_usd_mmbtu: float,
                coal_price_usd_mmbtu: float = 2.20,
                oil_price_usd_mmbtu: float = 12.00,
                season: str = "shoulder") -> DispatchResult:
        """
        Dispatch the stack to meet load.

        Returns the marginal unit's cost as the clearing price plus a
        scarcity adder if reserve margin < 5%.
        """
        stack = self.build_stack(
            gas_price_usd_mmbtu, coal_price_usd_mmbtu,
            oil_price_usd_mmbtu, season,
        )
        total_avail = stack["available_mw"].sum()

        # Find marginal unit
        in_money = stack[stack["cumulative_available_mw"] >= load_mw]
        if in_money.empty:
            # Scarcity — load exceeds available capacity
            return DispatchResult(
                clearing_price_usd_mwh=2_000.0,  # offer cap proxy
                marginal_unit="scarcity_cap",
                marginal_heat_rate=None,
                total_available_mw=total_avail,
                load_mw=load_mw,
                reserve_margin=(total_avail - load_mw) / load_mw,
                scarcity_adder=2_000.0 - 200.0,
                stack_used=stack,
            )

        marginal = in_money.iloc[0]
        base_price = marginal["marginal_cost_usd_mwh"]

        # Scarcity adder kicks in when reserve margin < 5%
        reserve_margin = (total_avail - load_mw) / load_mw
        scarcity_adder = 0.0
        if reserve_margin < 0.05:
            # Linearly scales — at 0% margin you're paying ~$300 over MC
            scarcity_adder = 300.0 * (0.05 - max(0, reserve_margin)) / 0.05

        return DispatchResult(
            clearing_price_usd_mwh=base_price + scarcity_adder,
            marginal_unit=marginal["fuel"],
            marginal_heat_rate=marginal["heat_rate"],
            total_available_mw=total_avail,
            load_mw=load_mw,
            reserve_margin=reserve_margin,
            scarcity_adder=scarcity_adder,
            stack_used=stack,
        )
