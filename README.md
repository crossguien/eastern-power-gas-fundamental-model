# Eastern Power & Gas Fundamental Price Model

A weekly fundamental price model for the Eastern Interconnect that derives
power and gas price views from physical supply-and-demand inputs rather
than statistical pattern matching.

The model forms a fundamental view at three major Eastern hubs, **PJM
West, NE Mass (ISO-NE), and Indiana Hub (MISO)**, and compares that view
to the prevailing forward curve to identify mispricings. It mirrors the
workflow a fundamental power desk runs every week before re-marking
positions.

---

## Why this exists

Power prices are set by the variable cost of the marginal generator
dispatched to meet load (plus any scarcity adder when reserves are tight).
A fundamental view follows the physical chain:

```
Weather forecast
    │
    ▼
Load forecast ──────────────────┐
                                │
Gas storage + LNG + production  │
    │                           │
    ▼                           ▼
Fundamental gas price ──► Stack dispatch ──► Marginal unit cost
                                                    │
                                                    ▼
                                         Hub basis ──► Fundamental power price
                                                    │
                                                    ▼
                                         Compare to forward ──► Trade signal
```

Every input is a physical quantity a trader monitors — storage reports,
weather strips, outage bulletins, the gas curve. Every output is
attributable to a real driver. This is what makes it *fundamental* rather
than quantitative.

---

## Project structure

```
eastern-power-gas-model/
├── README.md
├── requirements.txt
├── demo.py                          # End-to-end demo runner
├── src/
│   ├── data/
│   │   ├── synthetic.py             # Synthetic data generator (offline demo)
│   │   └── loaders.py               # Live API loaders (EIA, NOAA, ISOs)
│   ├── fundamentals/
│   │   ├── gas_balance.py           # Henry Hub fundamental model
│   │   ├── load_forecast.py         # Weather → peak load
│   │   ├── stack_dispatch.py        # Generation stack dispatch
│   │   └── power_price.py           # End-to-end orchestration
│   ├── signals/
│   │   └── trade_signals.py         # Fundamental view vs forward curve
│   └── backtest/
│       └── walk_forward.py          # Signal performance evaluation
└── tests/
    └── test_fundamentals.py         # Unit tests
```

---

## Quick start

```bash
pip install -r requirements.txt
python demo.py
```

The demo runs the full pipeline on synthetic data (no API keys needed)
and produces a backtest summary. Sample output:

```
========================================================================
Hub                     N     Hit%    Avg P&L   Sharpe      MaxDD      Total
========================================================================
pjm_west              214    71.0%      4.54     4.13    -75.97    970.95
ne_mass               231    54.5%      3.52     1.87   -129.23    812.89
miso_indiana          201    72.1%      2.53     4.23    -12.34    507.99
========================================================================
```

Run tests:

```bash
python tests/test_fundamentals.py
```

---

## The fundamental logic chain

### 1. Gas balance (`src/fundamentals/gas_balance.py`)

Henry Hub fundamental view from:

| Driver | Direction | Sensitivity |
|---|---|---|
| EIA storage deviation from 5-yr avg | Tight → bullish | $0.0015/MMBtu per Bcf |
| HDD vs normal | Cold → bullish | $0.005/MMBtu per HDD |
| CDD vs normal | Hot → bullish (gas gen) | $0.004/MMBtu per CDD |
| LNG exports > 12 Bcf/d | Bullish | $0.08/MMBtu per Bcf/d |
| Production > 102 Bcf/d | Bearish | $0.12/MMBtu per Bcf/d |

Sensitivities are calibrated to rule-of-thumb storage report reactions.
Production calibration would use rolling regressions on the storage-price
beta in a live implementation.

### 2. Load forecast (`src/fundamentals/load_forecast.py`)

Weather-driven peak load by ISO. Sensitivities derived from public
load-weather relationships:

| ISO | Base (MW) | HDD beta | CDD beta | Summer peak | Winter peak |
|---|---|---|---|---|---|
| PJM | 80,000 | 1,200 MW/HDD | 1,800 MW/CDD | 155,000 | 140,000 |
| MISO | 65,000 | 900 MW/HDD | 1,400 MW/CDD | 125,000 | 110,000 |
| ISO-NE | 12,000 | 220 MW/HDD | 320 MW/CDD | 26,000 | 22,000 |

### 3. Stack dispatch (`src/fundamentals/stack_dispatch.py`)

The heart of the model. For each ISO:

1. **Build the supply curve.** Order every generator by marginal cost
   (`heat_rate × fuel_price + variable_O&M`).
2. **Derate for availability.** Apply outage rates, renewable capacity
   factors by season, hydro seasonality, nuclear refueling.
3. **Dispatch to meet load.** Walk up the cost-ordered stack until
   cumulative available capacity meets forecast load.
4. **Set clearing price.** Marginal unit's cost = clearing price.
5. **Scarcity adder.** When reserve margin < 5%, add a scarcity premium
   that scales linearly to a ~$300/MWh adder at zero reserves.

Fleet composition is calibrated to public EIA-860 data. A live version
would pull unit-level fleet data and apply real outage schedules.

### 4. Hub basis (`src/fundamentals/power_price.py`)

ISO clearing prices are translated to hub prices via average historical
basis spreads. Production version would use node-by-node basis maps from
historical LMP data.

### 5. Trade signals (`src/signals/trade_signals.py`)

For each hub each week:
- `gap = fundamental_price − forward_price`
- If `|gap| > threshold`, fire a directional signal
- Position size scales with `|gap| / full_conviction_threshold`

### 6. Backtest (`src/backtest/walk_forward.py`)

Evaluates P&L of signals against realized prices. Reports hit rate,
Sharpe, max drawdown, and total P&L by hub.

---

## Live data integration

`src/data/loaders.py` documents the production data sources and their
schemas. Each loader is a drop-in replacement for the synthetic equivalent:

| Source | What | Endpoint |
|---|---|---|
| EIA | Weekly working gas storage | `api.eia.gov/v2/natural-gas/stor/wkly` |
| EIA | Henry Hub daily spot | `api.eia.gov/v2/natural-gas/pri/sum` |
| NOAA | Population-weighted HDD/CDD | `ncei.noaa.gov/cdo-web/api/v2/data` |
| PJM Data Miner 2 | Hourly load forecast | `api.pjm.com/api/v1/hrl_load_forecasts` |
| PJM Data Miner 2 | DA hourly LMP | `api.pjm.com/api/v1/da_hrl_lmps` |
| MISO | Public daily peak load | MISO public data |
| ISO-NE | Load and LMP | ISO-NE web services |

Set environment variables `EIA_API_KEY` and `NOAA_TOKEN` to enable live data.

---

## Calibration notes & limitations

This is a *framework* for fundamental price formation, not a production
trading system. Real-world calibration improvements would include:

- **Unit-level fleet data** from EIA-860 rather than fuel-type aggregates
- **Hourly resolution** rather than weekly (intraday shape matters)
- **Real outage schedules** rather than typical outage rates
- **Node-by-node basis** rather than average hub adders
- **Rolling sensitivity recalibration** rather than fixed betas
- **Hydro reservoir modeling** for PNW/NY hydro influence
- **Cross-tie / DC tie flows** between ISOs

The synthetic data generator (`src/data/synthetic.py`) is physically
calibrated so that realized prices respond to gas, weather, and storage
the way a real market would, which lets the backtest produce meaningful
signal performance without API access.

---

## What this demonstrates

- **Physical market logic** — understanding that prices are set by
  marginal generator economics, not statistical patterns
- **Supply stack intuition** — knowing which units are on the margin in
  different weather/gas regimes
- **Cross-commodity fluency** — gas price drives power via heat rate,
  which is the most important relationship in the Eastern markets
- **Signal construction** — translating a fundamental view into a
  directional trade vs the forward curve
- **Backtest discipline** — measuring signal quality with proper P&L
  attribution, hit rates, and risk-adjusted metrics
