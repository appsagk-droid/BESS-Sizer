from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date
from typing import Any

import altair as alt
import streamlit as st

SAMPLE = [
    166, 150, 111, 111, 109, 110, 106, 106, 107, 106, 106, 106,
    107, 106, 172, 465, 562, 570, 522, 494, 562, 433, 265, 283,
    112, 118, 271, 342, 211, 247, 306, 284, 377, 388, 477, 501,
    500, 460, 400, 340, 290, 250, 220, 200, 190, 180, 170, 160,
]
SAMPLE_TEXT = "\n".join(
    f"01-01-26 {index // 2}:{'30' if index % 2 else '00'}\t{load}"
    for index, load in enumerate(SAMPLE)
)
DEFAULTS = {
    "target": 3,
    "price": 430000,
    "unit_kwh": 522,
    "unit_kw": 260,
    "unit_count": 1,
    "efficiency": 92,
    "dod": 90,
    "peak_tariff": 0.50,
    "offpeak_tariff": 0.30,
    "peak_start": 14,
    "peak_end": 22,
    "demand_charge": 30,
    "retail_charge": 0,
    "life": 10,
}
REFERENCE_CAPACITY_KWH = [
    455.39, 438.08, 430.88, 424.89, 417.54,
    410.57, 403.96, 397.21, 390.18, 378.68,
]
TARIFF_PROFILES = {
    "custom": {
        "label": "Custom rates",
        "note": "Enter your peak/off-peak rates and maximum-demand charge manually.",
        "tou": True,
        "demand_period": "all",
    },
    "domestic_tou_under_1500": {
        "label": "Domestic ToU, up to 1,500 kWh/month",
        "note": "Requires a smart meter. All-in rates before AFA/incentives: RM0.4592 peak / RM0.4183 off-peak. Retail charge RM10/month (waived at 600 kWh or less).",
        "peak_tariff": 0.4592, "offpeak_tariff": 0.4183,
        "peak_start": 14, "peak_end": 22, "demand_charge": 0, "retail_charge": 10,
        "tou": True, "demand_period": "peak",
    },
    "domestic_tou_over_1500": {
        "label": "Domestic ToU, above 1,500 kWh/month",
        "note": "Requires a smart meter. All-in rates before AFA/incentives: RM0.5592 peak / RM0.5183 off-peak. Retail charge RM10/month (waived at 600 kWh or less).",
        "peak_tariff": 0.5592, "offpeak_tariff": 0.5183,
        "peak_start": 14, "peak_end": 22, "demand_charge": 0, "retail_charge": 10,
        "tou": True, "demand_period": "peak",
    },
    "domestic_standard": {
        "label": "Domestic standard (non-ToU)",
        "note": "Flat comparison rate: RM0.4443/kWh. Retail charge RM10/month (waived at 600 kWh or less).",
        "peak_tariff": 0.4443, "offpeak_tariff": 0.4443,
        "peak_start": 0, "peak_end": 24, "demand_charge": 0, "retail_charge": 10,
        "tou": False, "demand_period": "all",
    },
    "lv_general": {
        "label": "Low-voltage commercial/industrial, general (B/C1/D)",
        "note": "All-in flat energy rate: RM0.5068/kWh. Retail charge RM20/month.",
        "peak_tariff": 0.5068, "offpeak_tariff": 0.5068,
        "peak_start": 0, "peak_end": 24, "demand_charge": 0, "retail_charge": 20,
        "tou": False, "demand_period": "all",
    },
    "lv_tou": {
        "label": "Low-voltage commercial/industrial, ToU (B/C1/D)",
        "note": "All-in energy rates: RM0.5217 peak / RM0.4808 off-peak. Retail charge RM20/month.",
        "peak_tariff": 0.5217, "offpeak_tariff": 0.4808,
        "peak_start": 14, "peak_end": 22, "demand_charge": 0, "retail_charge": 20,
        "tou": True, "demand_period": "peak",
    },
    "mv_general": {
        "label": "Medium-voltage commercial/industrial, general (C1/E1)",
        "note": "Energy rate RM0.2983/kWh; maximum demand RM89.27/kW/month all periods. Retail charge RM200/month.",
        "peak_tariff": 0.2983, "offpeak_tariff": 0.2983,
        "peak_start": 0, "peak_end": 24, "demand_charge": 89.27, "retail_charge": 200,
        "tou": False, "demand_period": "all",
    },
    "mv_tou": {
        "label": "Medium-voltage commercial/industrial, ToU (C2/E2)",
        "note": "Energy rates RM0.3132 peak / RM0.2723 off-peak; maximum demand RM97.06/kW/month in peak periods only (excludes the optional RE fund). Retail charge RM200/month.",
        "peak_tariff": 0.3132, "offpeak_tariff": 0.2723,
        "peak_start": 14, "peak_end": 22, "demand_charge": 97.06, "retail_charge": 200,
        "tou": True, "demand_period": "peak",
    },
    "hv_tou": {
        "label": "High-voltage ToU (E3)",
        "note": "Maximum demand RM44.82/kW/month in peak periods. HV energy rates were not supplied; enter the rates from your bill.",
        "peak_start": 14, "peak_end": 22, "demand_charge": 44.82, "retail_charge": 0,
        "tou": True, "demand_period": "peak", "requires_energy_rates": True,
    },
}
DATE_RE = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})[ T]+(\d{1,2}):(\d{2})")
VALUE_RE = re.compile(r"-?\d[\d,]*\.?\d*")
HOLIDAY_RE = re.compile(r"^\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\s*$")


def parse_data(text: str) -> tuple[list[list[dict[str, Any]]], float, float]:
    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for line in text.splitlines():
        match = DATE_RE.search(line)
        if not match:
            continue
        day, month, year, hour, minute = map(int, match.groups())
        if year < 100:
            year += 2000
        try:
            reading_day = date(year, month, day)
        except ValueError:
            continue
        value_match = VALUE_RE.search(line[match.end():])
        if not value_match:
            continue
        try:
            load = float(value_match.group().replace(",", ""))
        except ValueError:
            continue
        by_day[reading_day].append({
            "time": hour + minute / 60,
            "kw": load,
            "weekday": reading_day.weekday(),
            "date": reading_day.isoformat(),
        })

    days = [sorted(readings, key=lambda reading: reading["time"])
            for _, readings in sorted(by_day.items())]
    interval = 0.5
    for readings in days:
        if len(readings) > 1:
            gaps = [readings[i]["time"] - readings[i - 1]["time"]
                    for i in range(1, len(readings))]
            positive_gaps = [gap for gap in gaps if gap > 0]
            if positive_gaps:
                interval = min(positive_gaps)
            break
    peak = max((reading["kw"] for readings in days for reading in readings), default=0)
    return days, interval, peak


def is_tou_peak(reading: dict[str, Any], settings: dict[str, Any]) -> bool:
    return (
        reading["weekday"] < 5
        and reading["date"] not in settings["public_holidays"]
        and settings["peak_start"] <= reading["time"] < settings["peak_end"]
    )


def calculate(days: list[list[dict[str, Any]]], interval: float,
              peak: float, settings: dict[str, Any]) -> dict[str, Any]:
    demand_peaks: dict[str, float] = defaultdict(float)
    for readings in days:
        for reading in readings:
            if settings["demand_period"] == "all" or is_tou_peak(reading, settings):
                month = reading["date"][:7]
                demand_peaks[month] = max(demand_peaks[month], reading["kw"])
    shaving_peak = max(demand_peaks.values(), default=0)

    def performance_for(units: int, capacity_retention: float) -> dict[str, float]:
        energy = units * settings["unit_kwh"] * settings["dod"] * capacity_retention
        power = units * settings["unit_kw"]

        def maximum_daily_energy(threshold: float) -> float:
            return max(
                (sum(
                    max(reading["kw"] - threshold, 0) for reading in readings
                    if not settings["tou"] or is_tou_peak(reading, settings)
                ) * interval for readings in days),
                default=0,
            )

        low, high = max(0, shaving_peak - power), shaving_peak
        if maximum_daily_energy(low) > energy:
            for _ in range(40):
                midpoint = (low + high) / 2
                if maximum_daily_energy(midpoint) > energy:
                    low = midpoint
                else:
                    high = midpoint
            low = high

        shaving_amount = max(shaving_peak - low, 0)
        demand_saving = shaving_amount * settings["demand_charge"] * 12
        return {
            "saving": demand_saving,
            "threshold": low,
            "monthly_md_saving": demand_saving,
        }

    def size_for(units: int) -> dict[str, Any]:
        cost = units * settings["price"]
        cumulative_saving = 0.0
        elapsed_years = 0.0
        payback = math.inf
        capacity_retention = 1.0
        projection = []
        year_count = math.ceil(settings["life"])

        for year in range(1, year_count + 1):
            duration = min(1.0, settings["life"] - (year - 1))
            reference_capacity = REFERENCE_CAPACITY_KWH[min(year - 1, len(REFERENCE_CAPACITY_KWH) - 1)]
            capacity_retention = reference_capacity / 522
            performance = performance_for(units, capacity_retention)
            annual_saving = performance["saving"]
            year_saving = annual_saving * duration
            if math.isinf(payback) and annual_saving > 0 and cumulative_saving + year_saving >= cost:
                payback = elapsed_years + (cost - cumulative_saving) / annual_saving
            cumulative_saving += year_saving
            elapsed_years += duration
            projection.append({
                "year": year,
                "capacity_retention": capacity_retention,
                "usable_energy": units * settings["unit_kwh"] * settings["dod"] * capacity_retention,
                "available_power": units * settings["unit_kw"],
                "threshold": performance["threshold"],
                "shaving_amount": max(shaving_peak - performance["threshold"], 0),
                "annual_saving": annual_saving,
                "monthly_md_saving": performance["monthly_md_saving"],
                "cumulative_saving": cumulative_saving,
            })

        first_year = projection[0]
        return {
            "units": units,
            "saving": first_year["annual_saving"],
            "lifetime_saving": cumulative_saving,
            "cost": cost,
            "threshold": first_year["threshold"],
            "demand_peak": shaving_peak,
            "shaving_amount": first_year["shaving_amount"],
            "monthly_md_saving": first_year["monthly_md_saving"],
            "payback": payback,
            "yearly_projection": projection,
        }

    def add_metrics(candidate: dict[str, Any]) -> dict[str, Any]:
        candidate["payback_display"] = (
            f"{candidate['payback']:.1f}"
            if math.isfinite(candidate["payback"]) else "n/a"
        )
        candidate["energy"] = candidate["units"] * settings["unit_kwh"]
        candidate["power"] = candidate["units"] * settings["unit_kw"]
        candidate["usable_energy"] = candidate["yearly_projection"][0]["usable_energy"]
        candidate["annual_roi"] = candidate["saving"] / candidate["cost"] * 100
        candidate["lifetime_roi"] = (
            (candidate["lifetime_saving"] - candidate["cost"])
            / candidate["cost"] * 100
        )
        candidate["met_target"] = candidate["payback"] <= settings["target"]
        return candidate

    candidates = [add_metrics(size_for(units)) for units in range(1, 201)]
    if settings["sizing_mode"] == "fixed":
        result = add_metrics(size_for(int(settings["unit_count"])))
    else:
        eligible = [candidate for candidate in candidates if candidate["met_target"]]
        result = eligible[-1] if eligible else min(candidates, key=lambda item: item["payback"])

    eligible = [candidate for candidate in candidates if candidate["met_target"]]
    if eligible:
        option_source = eligible
    else:
        option_source = sorted(
            candidates, key=lambda item: (item["payback"], item["units"])
        )[:5]
        option_source.sort(key=lambda item: item["units"])

    option_count = min(5, len(option_source))
    option_indices = {
        round(index * (len(option_source) - 1) / max(option_count - 1, 1))
        for index in range(option_count)
    }
    result["options"] = [option_source[index] for index in sorted(option_indices)]
    return result


def read_settings(form) -> dict[str, Any]:
    settings = {}
    profile_key = form.get("tariff_profile", "custom")
    profile = TARIFF_PROFILES.get(profile_key, TARIFF_PROFILES["custom"])
    for name, default in DEFAULTS.items():
        raw = form.get(name, str(default)).strip()
        if profile.get("requires_energy_rates") and name in {"peak_tariff", "offpeak_tariff"} and not raw:
            raise ValueError("Enter both high-voltage ToU energy rates from your electricity bill.")
        settings[name] = float(raw) if raw else float(default)
        if not math.isfinite(settings[name]):
            raise ValueError("Enter finite numeric values for all settings.")

    if (settings["target"] <= 0 or settings["price"] <= 0
            or settings["unit_kwh"] <= 0 or settings["unit_kw"] <= 0
            or settings["unit_count"] < 1 or settings["unit_count"] > 200
            or not settings["unit_count"].is_integer()
            or settings["life"] <= 0):
        raise ValueError("Target, unit sizes, price, and battery life must be greater than zero; BESS unit count must be a whole number from 1 to 200.")
    if not 0 < settings["efficiency"] <= 100 or not 0 < settings["dod"] <= 100:
        raise ValueError("Efficiency and usable depth of discharge must be between 0 and 100%.")
    if (settings["peak_tariff"] < 0 or settings["offpeak_tariff"] < 0
            or settings["demand_charge"] < 0 or settings["retail_charge"] < 0):
        raise ValueError("Tariffs and charges cannot be negative.")
    if not 0 <= settings["peak_start"] < settings["peak_end"] <= 24:
        raise ValueError("Peak window must run forward within hours 0 to 24.")
    settings["sizing_mode"] = form.get("sizing_mode", "automatic")
    if settings["sizing_mode"] not in {"automatic", "fixed"}:
        raise ValueError("Choose automatic sizing or a fixed BESS unit count.")
    settings["tariff_profile"] = profile_key
    settings["tou"] = profile["tou"]
    settings["demand_period"] = profile["demand_period"]
    settings["public_holidays"] = parse_holidays(form.get("public_holidays", ""))
    settings["efficiency"] /= 100
    settings["dod"] /= 100
    return settings


def parse_holidays(text: str) -> set[str]:
    holidays = set()
    for line in text.splitlines():
        match = HOLIDAY_RE.match(line)
        if not match:
            continue
        day, month, year = map(int, match.groups())
        if year < 100:
            year += 2000
        try:
            holidays.add(date(year, month, day).isoformat())
        except ValueError:
            continue
    return holidays


def make_chart(readings: list[dict[str, float]], peak: float,
               threshold: float) -> dict[str, float | list[dict[str, float | str]]]:
    width, height, bottom, top = 480, 190, 22, 10
    scale = peak * 1.1 or 1
    slot = width / max(len(readings), 1)
    bars = []
    tick_every = max(math.ceil(len(readings) / 8), 1)
    for index, reading in enumerate(readings):
        bar_height = reading["kw"] / scale * (height - bottom - top)
        bars.append({
            "x": index * slot + 1,
            "y": height - bottom - bar_height,
            "width": max(slot - 2, 1),
            "height": bar_height,
            "label": f"{int(reading['time'])}h" if index % tick_every == 0 else "",
        })
    return {
        "bars": bars,
        "threshold_y": height - bottom - threshold / scale * (height - bottom - top),
        "threshold": threshold,
    }


def apply_tariff_profile() -> None:
    profile = TARIFF_PROFILES[st.session_state.tariff_profile]
    for name in DEFAULTS:
        if name in profile:
            st.session_state[name] = profile[name]


def apply_bess_model() -> None:
    model_specs = {
        "model_216_130": {"unit_kwh": 216, "unit_kw": 130, "price": 215000},
        "model_522_260": {"unit_kwh": 522, "unit_kw": 260, "price": 430000},
    }
    for name, value in model_specs.get(st.session_state.bess_model, {}).items():
        st.session_state[name] = value


def mark_custom_tariff() -> None:
    st.session_state.tariff_profile = "custom"


def mark_custom_model() -> None:
    st.session_state.bess_model = "custom"


def update_simulated_load_peak() -> None:
    load_peak = st.session_state.simulation_load_peak
    shaved_peak = min(st.session_state.simulation_shaved_peak, load_peak)
    st.session_state.simulation_shaved_peak = shaved_peak
    st.session_state.simulation_shaving_amount = load_peak - shaved_peak


def update_simulated_shaved_peak() -> None:
    load_peak = st.session_state.simulation_load_peak
    shaved_peak = min(st.session_state.simulation_shaved_peak, load_peak)
    st.session_state.simulation_shaved_peak = shaved_peak
    st.session_state.simulation_shaving_amount = load_peak - shaved_peak


def update_simulated_shaving_amount() -> None:
    load_peak = st.session_state.simulation_load_peak
    amount = min(st.session_state.simulation_shaving_amount, load_peak)
    st.session_state.simulation_shaving_amount = amount
    st.session_state.simulation_shaved_peak = load_peak - amount


def render_number_setting(
    panel: Any, label: str, key: str, *, min_value: float | int | None = None,
    max_value: float | int | None = None, step: float | int | None = None,
    disabled: bool = False, on_change: Any = None,
) -> None:
    label_column, input_column = panel.columns([1.2, 0.9], vertical_alignment="center")
    label_column.markdown(f"<div class='setting-label'>{label}</div>", unsafe_allow_html=True)
    kwargs = {name: value for name, value in {
        "min_value": min_value,
        "max_value": max_value,
        "step": step,
        "disabled": disabled,
        "on_change": on_change,
    }.items() if value is not None}
    input_column.number_input(label, key=key, label_visibility="collapsed", **kwargs)


def render_select_setting(
    panel: Any, label: str, options: list[str], key: str,
    *, format_func: Any = None, on_change: Any = None,
) -> None:
    label_column, input_column = panel.columns([1.2, 0.9], vertical_alignment="center")
    label_column.markdown(f"<div class='setting-label'>{label}</div>", unsafe_allow_html=True)
    input_column.selectbox(
        label, options, key=key, format_func=format_func,
        on_change=on_change, label_visibility="collapsed",
    )


def render_settings(panel: Any) -> None:
    for name, value in DEFAULTS.items():
        st.session_state.setdefault(name, value)
    st.session_state.setdefault("tariff_profile", "custom")
    st.session_state.setdefault("bess_model", "model_522_260")
    st.session_state.setdefault("sizing_mode", "automatic")
    st.session_state.setdefault("public_holidays", "")

    panel.subheader("Fixed variables")
    short_tariff_labels = {
        "custom": "Custom rates",
        "domestic_tou_under_1500": "Domestic ToU <= 1,500 kWh",
        "domestic_tou_over_1500": "Domestic ToU > 1,500 kWh",
        "domestic_standard": "Domestic standard",
        "lv_general": "LV general",
        "lv_tou": "LV ToU",
        "mv_general": "MV general",
        "mv_tou": "MV ToU",
        "hv_tou": "HV ToU",
    }
    render_select_setting(
        panel, "Malaysia tariff profile", list(TARIFF_PROFILES), "tariff_profile",
        format_func=lambda key: short_tariff_labels[key], on_change=apply_tariff_profile,
    )
    profile = TARIFF_PROFILES[st.session_state.tariff_profile]
    panel.markdown(f"**{profile['label']}**")
    panel.caption(profile["note"])
    tariff_rates = panel.columns(2)
    tariff_rates[0].markdown(f"**Peak energy**  \nRM {st.session_state.peak_tariff:.4f}/kWh")
    tariff_rates[1].markdown(f"**Off-peak energy**  \nRM {st.session_state.offpeak_tariff:.4f}/kWh")
    tariff_rates = panel.columns(2)
    tariff_rates[0].markdown(f"**Demand charge**  \nRM {st.session_state.demand_charge:,.2f}/kW/month")
    tariff_rates[1].markdown(f"**Retail charge**  \nRM {st.session_state.retail_charge:,.2f}/month")
    render_select_setting(
        panel, "BESS model",
        ["model_216_130", "model_522_260", "custom"],
        format_func=lambda key: {
            "model_216_130": "216 kWh / 130 kW",
            "model_522_260": "522 kWh / 260 kW",
            "custom": "Custom specs",
        }[key],
        key="bess_model", on_change=apply_bess_model,
    )
    render_number_setting(panel, "Price per BESS unit (RM)", "price", min_value=0.01, on_change=mark_custom_model)
    render_number_setting(panel, "Unit energy (kWh)", "unit_kwh", min_value=0.01, on_change=mark_custom_model)
    render_number_setting(panel, "Unit power (kW)", "unit_kw", min_value=0.01, on_change=mark_custom_model)
    render_select_setting(
        panel, "BESS sizing mode", ["automatic", "fixed"], "sizing_mode",
        format_func=lambda mode: "Optimize to payback target" if mode == "automatic" else "Set number of units",
    )
    render_number_setting(
        panel, "Number of BESS units", "unit_count", min_value=1, max_value=200,
        step=1, disabled=st.session_state.sizing_mode != "fixed",
    )
    render_number_setting(panel, "Round-trip efficiency (%)", "efficiency", min_value=0.01, max_value=100.0)
    render_number_setting(panel, "Usable depth of discharge (%)", "dod", min_value=0.01, max_value=100.0)
    panel.caption("Battery capacity follows the fixed reference degradation profile; rated kW power does not degrade.")
    render_number_setting(panel, "Peak tariff (RM/kWh)", "peak_tariff", min_value=0.0, on_change=mark_custom_tariff)
    render_number_setting(panel, "Off-peak tariff (RM/kWh)", "offpeak_tariff", min_value=0.0, on_change=mark_custom_tariff)
    render_number_setting(panel, "Peak window start hour", "peak_start", min_value=0, max_value=23, step=1, on_change=mark_custom_tariff)
    render_number_setting(panel, "Peak window end hour", "peak_end", min_value=1, max_value=24, step=1, on_change=mark_custom_tariff)
    render_number_setting(panel, "Maximum demand charge (RM/kW/month)", "demand_charge", min_value=0.0, on_change=mark_custom_tariff)
    render_number_setting(panel, "Retail charge (RM/month)", "retail_charge", min_value=0.0, on_change=mark_custom_tariff)
    render_number_setting(panel, "Battery life (years)", "life", min_value=0.01)
    panel.text_area(
        "Public holidays (one dd-mm-yyyy date per line)", key="public_holidays",
        placeholder="01-05-26\n31-08-26", height=70,
    )
    if profile.get("requires_energy_rates"):
        panel.info("Enter the high-voltage ToU energy rates from your bill.")


def calculate_from_inputs(data_text: str, uploaded_data: str | None) -> dict[str, Any]:
    if uploaded_data is not None:
        data_text = uploaded_data
    settings_input = {name: str(st.session_state[name]) for name in DEFAULTS}
    settings_input.update({
        "tariff_profile": st.session_state.tariff_profile,
        "sizing_mode": st.session_state.sizing_mode,
        "public_holidays": st.session_state.public_holidays,
    })
    try:
        settings = read_settings(settings_input)
    except ValueError as exc:
        return {"error": str(exc)}

    days, interval, peak = parse_data(data_text)
    if not days:
        return {"error": "No valid rows found. Expected a date-time like 01-01-26 0:30 followed by kW."}

    reading_count = sum(map(len, days))
    daily_energy = sum(
        sum(reading["kw"] * interval for reading in readings) for readings in days
    ) / len(days)
    stats = (f"{reading_count:,} readings, {len(days)} day(s), "
             f"{round(interval * 60)}-min interval, peak {peak:.0f} kW, "
             f"average {daily_energy:,.0f} kWh/day")
    result = calculate(days, interval, peak, settings)
    demand_days = [
        readings for readings in days
        if any(not settings["tou"] or is_tou_peak(reading, settings) for reading in readings)
    ]
    peak_day = max(
        demand_days or days,
        key=lambda readings: max(
            (reading["kw"] for reading in readings
             if not settings["tou"] or is_tou_peak(reading, settings)),
            default=max(reading["kw"] for reading in readings),
        ),
    )
    return {
        "result": result,
        "settings": settings,
        "stats": stats,
        "day_count": len(days),
        "peak_day": peak_day,
        "peak": peak,
    }


def render_results(calculation: dict[str, Any]) -> dict[str, Any] | None:
    if calculation.get("error"):
        st.error(calculation["error"])
        return None

    recommendation = calculation["result"]
    settings = calculation["settings"]
    st.caption(calculation["stats"])
    if calculation["day_count"] < 28:
        st.warning("Under a month of data: results assume these days repeat throughout the year.")

    st.markdown("**Suggested BESS options**")
    options = recommendation["options"]
    option_rows = [{
        "Units": option["units"],
        "Rated (kWh)": f"{option['energy']:,.0f}",
        "Usable (kWh)": f"{option['usable_energy']:,.0f}",
        "Power (kW)": f"{option['power']:,.0f}",
        "Capex (RM)": f"{option['cost']:,.0f}",
        "Year 1 saving (RM)": f"{option['saving']:,.0f}",
        "Payback (years)": option["payback_display"],
        "Annual ROI": f"{option['annual_roi']:.1f}%",
        "Lifetime ROI": f"{option['lifetime_roi']:.1f}%",
    } for option in options]
    table_event = st.dataframe(
        option_rows, hide_index=True, width="stretch", height=220,
        key="suggested_options_table", on_select="rerun", selection_mode="single-row",
    )
    selected_rows = table_event.selection.rows
    selected_units = (
        options[selected_rows[0]]["units"] if selected_rows
        else st.session_state.get("selected_option_units", recommendation["units"])
    )
    if selected_units not in {option["units"] for option in options}:
        selected_units = recommendation["units"]
    st.session_state.selected_option_units = selected_units
    result = next(option for option in options if option["units"] == selected_units)

    first_row = st.columns(3)
    first_row[0].metric("BESS size", f"{result['energy']:,.0f} kWh")
    first_row[1].metric("Units", str(result["units"]))
    first_row[2].metric("Lifetime ROI", f"{result['lifetime_roi']:.0f}%")
    second_row = st.columns(3)
    second_row[0].metric("Power", f"{result['power']:,.0f} kW")
    second_row[1].metric("Capital cost", f"RM {result['cost']:,.0f}")
    second_row[2].metric("Year 1 saving", f"RM {result['saving']:,.0f}")
    third_row = st.columns(2)
    third_row[0].metric("Payback", f"{result['payback_display']} years")
    third_row[1].metric("Annual ROI", f"{result['annual_roi']:.1f}%")

    if result["met_target"]:
        st.success(
            f"Meets the {settings['target']:g}-year target. Tariff-period peak shaved "
            f"from {result['demand_peak']:.0f} kW to {result['threshold']:.0f} kW."
        )
    elif settings["sizing_mode"] == "fixed":
        st.warning(
            f"The selected {result['units']}-unit system exceeds the "
            f"{settings['target']:g}-year payback target ({result['payback_display']} years)."
        )
    else:
        st.warning(
            f"No size pays back within {settings['target']:g} years. "
            f"Showing the best case ({result['payback_display']} years)."
        )

    st.caption(
        f"Lifetime ROI sums yearly savings over {settings['life']:g} years after battery degradation; "
        "financing and replacement costs are excluded."
    )
    st.subheader("Degradation-adjusted yearly projection")
    projection_rows = [{
        "Year": year["year"],
        "Shaving amount (kW)": f"{year['shaving_amount']:,.1f}",
        "Annual saving (RM)": f"{year['annual_saving']:,.0f}",
    } for year in result["yearly_projection"]]
    st.dataframe(projection_rows, hide_index=True, width="stretch", height=260)
    return result


def render_peak_chart(calculation: dict[str, Any], result: dict[str, Any] | None) -> None:
    if calculation.get("error") or result is None:
        return
    peak_day = calculation["peak_day"]
    actual_peak = max(reading["kw"] for reading in peak_day)
    maximum_input = max(actual_peak * 5, 1000)
    if st.session_state.get("simulation_selected_units") != result["units"]:
        st.session_state.simulation_load_peak = actual_peak
        st.session_state.simulation_shaved_peak = min(result["threshold"], actual_peak)
        st.session_state.simulation_shaving_amount = max(
            st.session_state.simulation_load_peak - st.session_state.simulation_shaved_peak, 0,
        )
        st.session_state.simulation_selected_units = result["units"]
    else:
        st.session_state.setdefault("simulation_load_peak", actual_peak)
        st.session_state.setdefault("simulation_shaved_peak", min(result["threshold"], actual_peak))
        st.session_state.setdefault(
            "simulation_shaving_amount",
            max(st.session_state.simulation_load_peak - st.session_state.simulation_shaved_peak, 0),
        )
    peak_boxes = st.columns(3)
    peak_boxes[0].number_input(
        "Load peak (kW)", min_value=0.0, max_value=maximum_input,
        step=0.1, key="simulation_load_peak", on_change=update_simulated_load_peak,
    )
    peak_boxes[1].number_input(
        "Shaved peak (kW)", min_value=0.0, max_value=maximum_input,
        step=0.1, key="simulation_shaved_peak", on_change=update_simulated_shaved_peak,
    )
    peak_boxes[2].number_input(
        "Shaving amount (kW)", min_value=0.0, max_value=maximum_input,
        step=0.1, key="simulation_shaving_amount", on_change=update_simulated_shaving_amount,
    )
    simulation_load_peak = st.session_state.simulation_load_peak
    peak_limit = st.session_state.simulation_shaved_peak
    maximum_shaved = st.session_state.simulation_shaving_amount
    load_scale = simulation_load_peak / actual_peak if actual_peak > 0 else 1
    chart_data = [{
        "time": reading["time"],
        "load": reading["kw"] * load_scale,
    } for reading in peak_day]
    load_bars = alt.Chart(alt.Data(values=chart_data)).mark_bar(
        color="#2877c7", size=12, opacity=0.9,
    ).encode(
        x=alt.X(
            "time:Q", title="Time of day",
            axis=alt.Axis(values=list(range(0, 25, 3)), labelExpr="datum.value + 'h'"),
            scale=alt.Scale(domain=[0, 24]),
        ),
        y=alt.Y("load:Q", title="Load (kW)", scale=alt.Scale(zero=True)),
        tooltip=[
            alt.Tooltip("time:Q", title="Hour", format=".1f"),
            alt.Tooltip("load:Q", title="Load (kW)", format=".1f"),
        ],
    )
    peak_line = alt.Chart().mark_rule(
        color="#d97706", strokeDash=[7, 4], strokeWidth=2,
    ).encode(y=alt.datum(peak_limit))
    chart = alt.layer(load_bars, peak_line).properties(height=300).configure(
        background="#ffffff",
    ).configure_view(
        stroke="transparent",
    ).configure_axis(
        labelColor="#52666c", titleColor="#30464e", gridColor="#e7ecee",
    )
    legend = st.columns(2)
    legend[0].markdown(
        "<span style='color:#2877c7;font-weight:700'>■</span> Load (bars)",
        unsafe_allow_html=True,
    )
    legend[1].markdown(
        "<span style='color:#d97706;font-weight:700'>━</span> Shaved peak (line)",
        unsafe_allow_html=True,
    )
    st.altair_chart(chart, width="stretch")
    st.markdown(f"**Maximum shaved amount: {maximum_shaved:,.1f} kW**")
    st.caption("Adjusting load peak rescales the plotted profile proportionally. To update financial results, edit the interval data above and calculate again.")


def main() -> None:
    st.set_page_config(page_title="BESS Sizing Calculator", page_icon="🔋", layout="wide")
    st.markdown("""
        <style>
        .stApp { background: #e9eeeb; color: #1d2b31; }
        [data-testid="stAppViewContainer"] { background: #e9eeeb; }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stMainBlockContainer"] { max-width: 1440px; padding: 1.25rem 1.4rem 2.5rem; }
        [data-testid="stMarkdownContainer"] { color: #26363d; }
        [data-testid="stMarkdownContainer"] p { font-size: 1rem; line-height: 1.5; }
        h1 { color: #172b33; font-size: 1.9rem !important; font-weight: 700 !important; margin: 0 0 .2rem; }
        h2, h3 { color: #20343c; font-size: 1.2rem !important; font-weight: 650 !important; margin-bottom: .55rem !important; }
        [data-testid="stVerticalBlockBorderWrapper"],
        [data-testid="stVerticalBlockBorderWrapper"] > div,
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] { background: #fff !important; background-image: none !important; border-color: #c5d1d1; border-radius: 7px; box-shadow: 0 2px 8px rgba(22, 48, 54, .08); }
        .st-key-load-input-panel, .st-key-results-panel,
        .st-key-load-input-panel [data-testid="stVerticalBlock"],
        .st-key-results-panel [data-testid="stVerticalBlock"],
        .st-key-settings-panel, .st-key-peak-chart-panel,
        .st-key-settings-panel [data-testid="stVerticalBlock"],
        .st-key-peak-chart-panel [data-testid="stVerticalBlock"] { background-color: #fff !important; background-image: none !important; }
        [data-testid="stMetric"] { background: #fff !important; border: 1px solid #d0dadb; border-radius: 6px; padding: .55rem .65rem; min-height: 72px; }
        [data-testid="stMetricLabel"] { color: #52666c; font-size: .9rem; }
        [data-testid="stMetricValue"] { color: #183b43; font-size: 1.35rem; font-weight: 650; }
        .setting-label { color: #30464e; font-size: .98rem; line-height: 1.4; padding: .4rem 0; }
        [data-testid="stCaptionContainer"] { color: #52666c; font-size: .92rem; line-height: 1.5; }
        [data-testid="stWidgetLabel"] p { color: #30464e; font-size: .95rem; }
        [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
        [data-testid="stSelectbox"] [data-baseweb="select"] > div,
        [data-testid="stTextArea"] textarea { background: #fff; border-color: #bdccce; font-size: 1rem; }
        [data-testid="stNumberInput"] button { display: none !important; }
        [data-testid="stBaseButton-primary"] { background: #13766d; border-color: #13766d; color: #fff; }
        [data-testid="stBaseButton-primary"]:hover { background: #0d625a; border-color: #0d625a; color: #fff; }
        [data-testid="stAlert"] { border-radius: 6px; }
        [data-testid="stAlert"] p { font-size: .98rem; line-height: 1.5; }
        [data-testid="stHorizontalBlock"] { gap: .65rem; }
        [data-testid="stDataFrame"] { font-size: .92rem; }
        @media (max-width: 700px) {
            [data-testid="stMainBlockContainer"] { padding: 1rem .8rem 2rem; }
            h1 { font-size: 1.65rem !important; }
        }
        </style>
    """, unsafe_allow_html=True)
    st.title("BESS sizing calculator")
    st.caption("Size a battery against your interval load profile, tariff, and payback target.")
    input_column, output_column = st.columns([0.38, 0.62], gap="small")
    with input_column:
        with st.container(border=True, key="load-input-panel"):
            st.subheader("Manipulating variables")
            st.slider("Expected payback (years)", 1.0, 15.0, step=0.5, key="target")
            optimize_clicked = st.button("Calculate optimal sizing", type="primary", width="stretch")
            if optimize_clicked:
                st.session_state.sizing_mode = "automatic"
            st.markdown("**Load data (kW import)**")
            st.caption("Paste timestamp and kW columns, or upload a CSV. Each row should contain a date-time and kW value.")
            uploaded_file = st.file_uploader("Choose a CSV or text file", type=["csv", "txt", "tsv"])
            uploaded_data = None
            upload_error = None
            if uploaded_file is not None:
                if uploaded_file.size > 200_000:
                    upload_error = "The uploaded file must be 200 kB or smaller."
                else:
                    try:
                        uploaded_data = uploaded_file.getvalue().decode("utf-8-sig")
                    except UnicodeDecodeError:
                        upload_error = "The uploaded file must be a UTF-8 CSV or text file."
            data_text = st.text_area(
                "Load data", value=SAMPLE_TEXT, height=120, label_visibility="collapsed",
            )
            calculate_clicked = st.button("Calculate", type="primary", width="content")
        with st.container(border=True, key="settings-panel"):
            render_settings(st)

    with output_column:
        with st.container(border=True, key="results-panel"):
            st.subheader("Results")
            if optimize_clicked or calculate_clicked or "calculation" not in st.session_state:
                st.session_state.pop("chart_selected_units", None)
                st.session_state.pop("simulation_selected_units", None)
                st.session_state.pop("suggested_options_table", None)
                st.session_state.calculation = (
                    {"error": upload_error} if upload_error
                    else calculate_from_inputs(data_text, uploaded_data)
                )
                if not st.session_state.calculation.get("error"):
                    st.session_state.selected_option_units = st.session_state.calculation["result"]["units"]
            selected_result = render_results(st.session_state.calculation)
        with st.container(border=True, key="peak-chart-panel"):
            render_peak_chart(st.session_state.calculation, selected_result)


main()

