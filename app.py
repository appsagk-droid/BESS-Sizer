from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date
from typing import Any

from flask import Flask, render_template, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200_000

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
    "target": 5,
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
    billable_months = max(len(demand_peaks), 1)
    shaving_peak = max(demand_peaks.values(), default=0)

    def size_for(units: int) -> dict[str, float | int]:
        energy = units * settings["unit_kwh"] * settings["dod"]
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

        demand_saving = (
            sum(max(month_peak - low, 0) for month_peak in demand_peaks.values())
            / billable_months * 12 * settings["demand_charge"]
        )
        arbitrage = 0
        for readings in days:
            peak_energy = sum(
                reading["kw"] * interval for reading in readings
                if settings["tou"] and is_tou_peak(reading, settings)
            )
            shifted_energy = min(energy, peak_energy)
            daily_arbitrage = (
                shifted_energy * settings["peak_tariff"]
                - shifted_energy / settings["efficiency"] * settings["offpeak_tariff"]
            )
            arbitrage += max(daily_arbitrage, 0)
        annual_saving = demand_saving + arbitrage / len(days) * 365
        cost = units * settings["price"]
        return {
            "units": units,
            "saving": annual_saving,
            "cost": cost,
            "threshold": low,
            "demand_peak": shaving_peak,
            "monthly_md_saving": demand_saving,
            "payback": cost / annual_saving if annual_saving > 0 else math.inf,
        }

    def add_metrics(candidate: dict[str, Any]) -> dict[str, Any]:
        candidate["payback_display"] = (
            f"{candidate['payback']:.1f}"
            if math.isfinite(candidate["payback"]) else "n/a"
        )
        candidate["energy"] = candidate["units"] * settings["unit_kwh"]
        candidate["power"] = candidate["units"] * settings["unit_kw"]
        candidate["usable_energy"] = candidate["energy"] * settings["dod"]
        candidate["annual_roi"] = candidate["saving"] / candidate["cost"] * 100
        candidate["lifetime_roi"] = (
            (candidate["saving"] * settings["life"] - candidate["cost"])
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


@app.route("/", methods=["GET", "POST"])
def index():
    form_values = {name: str(value) for name, value in DEFAULTS.items()}
    form_values["tariff_profile"] = "custom"
    form_values["bess_model"] = "model_522_260"
    form_values["sizing_mode"] = "automatic"
    form_values["public_holidays"] = ""
    data_text = SAMPLE_TEXT
    error = None
    if request.method == "POST":
        form_values.update({name: request.form.get(name, str(value))
                            for name, value in DEFAULTS.items()})
        form_values["tariff_profile"] = request.form.get("tariff_profile", "custom")
        form_values["bess_model"] = request.form.get("bess_model", "custom")
        form_values["sizing_mode"] = request.form.get("sizing_mode", "automatic")
        form_values["public_holidays"] = request.form.get("public_holidays", "")
        selected_profile = TARIFF_PROFILES.get(
            form_values["tariff_profile"], TARIFF_PROFILES["custom"]
        )
        if form_values["tariff_profile"] != "custom":
            for name in DEFAULTS:
                if name in selected_profile:
                    form_values[name] = str(selected_profile[name])
        data_text = request.form.get("data", "")
        uploaded_file = request.files.get("file")
        if uploaded_file and uploaded_file.filename:
            try:
                data_text = uploaded_file.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                error = "The uploaded file must be a UTF-8 CSV or text file."

    settings = {name: float(value) for name, value in DEFAULTS.items()}
    result = None
    chart = None
    stats = None
    days, interval, peak = parse_data(data_text)
    if not error:
        try:
            settings = read_settings(form_values)
        except ValueError as exc:
            error = str(exc)

    if not error and not days:
        error = "No valid rows found. Expected a date-time like 01-01-26 0:30 followed by kW."
    if not error:
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
        chart_peak = max(reading["kw"] for reading in peak_day)
        chart = make_chart(peak_day, chart_peak, result["threshold"])

    return render_template(
        "index.html", defaults=DEFAULTS, values=form_values, data=data_text,
        tariff_profiles=TARIFF_PROFILES,
        tariff_note=TARIFF_PROFILES.get(form_values["tariff_profile"], TARIFF_PROFILES["custom"])["note"],
        stats=stats, day_count=len(days), result=result, chart=chart, peak=peak,
        error=error, target=settings["target"],
        sizing_mode=settings["sizing_mode"],
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)