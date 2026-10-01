# BESS-Sizer

## Run the Python app

```sh
python3 -m pip install -r requirements.txt
python3 app.py
```

Open <http://localhost:8001>. Paste interval load data or upload a CSV containing
date-time and kW columns. The original standalone calculator remains available
in `BESS Sizing Calculator (1).html`.

The BESS model selector includes 216 kWh / 130 kW at RM215,000 and 522 kWh /
260 kW at RM430,000, plus editable custom specifications. Selecting a preset
fills its dimensions and per-unit price; manual edits switch to custom. The
default model is 522 kWh / 260 kW. Both use 92% round-trip efficiency and 90%
usable depth of discharge unless changed. Choose automatic sizing to optimize
against the payback target, or fixed sizing to calculate a specified number of
units.

After calculation, the app compares up to five BESS configurations by unit
count, rated and usable energy, power, estimated capital cost, annual savings,
annual/lifetime ROI, and payback. Recommendations use the uploaded interval
load profile and tariff assumptions; a peak kW figure alone is not enough to
estimate savings or payback reliably.

The tariff selector includes the supplied Peninsular Malaysia domestic, LV, MV,
and HV schedules. Select a domestic ToU usage band explicitly. Add public
holidays as `dd-mm-yyyy`, one date per line. Monthly retail charges are shown
but excluded from battery savings because they are fixed; maximum-demand savings
are estimated from the uploaded interval readings (30-minute data is needed
for billed MD precision). HV energy rates were not provided, so enter those
manually from the bill.