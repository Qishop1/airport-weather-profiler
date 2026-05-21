from __future__ import annotations

import math
from pathlib import Path
from typing import Any


def _import_pyplot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in s)


def _pct_values(d: dict[str, Any], ordered_keys: list[str] | None = None) -> tuple[list[str], list[float]]:
    if ordered_keys is None:
        keys = list(d.keys())
    else:
        keys = ordered_keys
    return keys, [float(d.get(k, 0) or 0) * 100 for k in keys]


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    fig.clf()


def infer_wind_sector_size(wind_sectors: dict[str, Any]) -> int:
    vals = sorted(int(float(k)) % 360 for k in wind_sectors.keys() if str(k).strip())
    if len(vals) < 2:
        return 20
    diffs = []
    for i, v in enumerate(vals):
        nxt = vals[(i + 1) % len(vals)]
        diff = (nxt - v) % 360
        if diff > 0:
            diffs.append(diff)
    return int(min(diffs)) if diffs else 20


def plot_wind_rose(profile: dict[str, Any], path: Path) -> None:
    plt = _import_pyplot()
    sectors = profile.get("overall", {}).get("windSectors", {})
    if not sectors:
        return
    width_deg = infer_wind_sector_size(sectors)
    degrees = sorted(int(float(k)) % 360 for k in sectors.keys())
    values = [float(sectors.get(str(d), 0) or 0) * 100 for d in degrees]
    theta = [math.radians(d) for d in degrees]
    width = math.radians(width_deg * 0.9)

    fig = plt.figure(figsize=(7.2, 7.2))
    ax = fig.add_subplot(111, projection="polar")
    ax.bar(theta, values, width=width, align="center", edgecolor="black", linewidth=0.35)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_title(f"{profile['airport']['icao']} Wind Rose — overall wind direction frequency")
    ax.set_ylabel("Frequency %")
    _save(fig, path)


def plot_monthly_flight_category(profile: dict[str, Any], path: Path) -> None:
    plt = _import_pyplot()
    months = [f"{i:02d}" for i in range(1, 13)]
    monthly = profile.get("monthly", {})
    vfr = [monthly.get(m, {}).get("vfrRate", 0) * 100 for m in months]
    mvfr = [monthly.get(m, {}).get("mvfrRate", 0) * 100 for m in months]
    ifr = [monthly.get(m, {}).get("ifrRate", 0) * 100 for m in months]
    lifr = [monthly.get(m, {}).get("lifrRate", 0) * 100 for m in months]

    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.bar(months, vfr, label="VFR")
    ax.bar(months, mvfr, bottom=vfr, label="MVFR")
    bottom_ifr = [a + b for a, b in zip(vfr, mvfr)]
    ax.bar(months, ifr, bottom=bottom_ifr, label="IFR")
    bottom_lifr = [a + b + c for a, b, c in zip(vfr, mvfr, ifr)]
    ax.bar(months, lifr, bottom=bottom_lifr, label="LIFR")
    ax.set_ylim(0, 100)
    ax.set_ylabel("Observation share %")
    ax.set_xlabel("Month")
    ax.set_title(f"{profile['airport']['icao']} Monthly flight category distribution")
    ax.legend(ncols=4, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    _save(fig, path)


def plot_monthly_weather_rates(profile: dict[str, Any], path: Path) -> None:
    plt = _import_pyplot()
    months = [f"{i:02d}" for i in range(1, 13)]
    monthly = profile.get("monthly", {})
    keys = ["rain", "snow", "fog", "mist", "thunder", "blowingSnow"]
    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    for key in keys:
        vals = [monthly.get(m, {}).get("weatherRates", {}).get(key, 0) * 100 for m in months]
        ax.plot(months, vals, marker="o", label=key)
    ax.set_ylabel("Observation share %")
    ax.set_xlabel("Month")
    ax.set_title(f"{profile['airport']['icao']} Monthly weather phenomenon rates")
    ax.legend(ncols=3, loc="upper center", bbox_to_anchor=(0.5, -0.14))
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_hourly_ifr_lifr(profile: dict[str, Any], path: Path) -> None:
    plt = _import_pyplot()
    hours = [f"{i:02d}" for i in range(24)]
    hourly = profile.get("hourlyLocal", {})
    ifr_low = [(hourly.get(h, {}).get("ifrRate", 0) + hourly.get(h, {}).get("lifrRate", 0)) * 100 for h in hours]
    fogmist = [(hourly.get(h, {}).get("weatherRates", {}).get("fog", 0) + hourly.get(h, {}).get("weatherRates", {}).get("mist", 0)) * 100 for h in hours]
    vis5000 = [hourly.get(h, {}).get("visibilityStats", {}).get("below5000mRate", 0) * 100 for h in hours]
    cig1000 = [hourly.get(h, {}).get("ceilingStats", {}).get("below1000ftRate", 0) * 100 for h in hours]
    gust_reliable = any(hourly.get(h, {}).get("windStats", {}).get("gustReliable") for h in hours)
    gust = [hourly.get(h, {}).get("windStats", {}).get("gustOver20ktObservedRate", hourly.get(h, {}).get("windStats", {}).get("gustOver20ktRate", 0)) * 100 for h in hours]

    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    ax.plot(hours, ifr_low, marker="o", label="IFR + LIFR")
    ax.plot(hours, fogmist, marker="o", label="FG + BR")
    ax.plot(hours, vis5000, marker="o", label="VIS <5000 m")
    ax.plot(hours, cig1000, marker="o", label="CIG <1000 ft")
    if gust_reliable:
        ax.plot(hours, gust, marker="o", label="Gust >20 kt (all obs)")
    ax.set_ylabel("Observation share %")
    ax.set_xlabel("Local hour")
    ax.set_title(f"{profile['airport']['icao']} Local-hour operational weather risk")
    ax.grid(True, alpha=0.25)
    ax.legend(ncols=3, loc="upper center", bbox_to_anchor=(0.5, -0.14))
    _save(fig, path)


def plot_bucket_bar(profile: dict[str, Any], bucket_name: str, title: str, path: Path, order: list[str] | None = None) -> None:
    plt = _import_pyplot()
    data = profile.get("overall", {}).get(bucket_name, {})
    if not data:
        return
    labels, vals = _pct_values(data, order)
    fig, ax = plt.subplots(figsize=(9.2, 5.2))
    ax.bar(labels, vals)
    ax.set_ylabel("Observation share %")
    ax.set_title(f"{profile['airport']['icao']} {title}")
    ax.tick_params(axis="x", rotation=30)
    _save(fig, path)


def plot_runway_operational_risks(profile: dict[str, Any], path: Path) -> None:
    plt = _import_pyplot()
    stats = profile.get("runwayOperationalStats", {})
    if not stats:
        return
    runways = list(stats.keys())
    x = list(range(len(runways)))
    tw5 = [stats[r].get("tailwindOver5ktRate", 0) * 100 for r in runways]
    xw15 = [stats[r].get("crosswindOver15ktRate", 0) * 100 for r in runways]
    xw20 = [stats[r].get("crosswindOver20ktRate", 0) * 100 for r in runways]
    w = 0.25
    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.bar([i - w for i in x], tw5, width=w, label="Tailwind >5 kt")
    ax.bar(x, xw15, width=w, label="Crosswind >15 kt")
    ax.bar([i + w for i in x], xw20, width=w, label="Crosswind >20 kt")
    ax.set_xticks(x)
    ax.set_xticklabels(runways)
    ax.set_ylabel("Observation share %")
    ax.set_title(f"{profile['airport']['icao']} Runway operational wind risk")
    ax.legend(ncols=3, loc="upper center", bbox_to_anchor=(0.5, -0.14))
    _save(fig, path)


def create_all_charts(profile: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    airport = _safe_name(profile.get("airport", {}).get("icao", "airport"))
    charts = {
        "wind_rose": out_dir / f"{airport}_wind_rose.png",
        "monthly_flight_category": out_dir / f"{airport}_monthly_flight_category.png",
        "monthly_weather_rates": out_dir / f"{airport}_monthly_weather_rates.png",
        "hourly_operational_risk": out_dir / f"{airport}_hourly_operational_risk.png",
        "visibility_buckets": out_dir / f"{airport}_visibility_buckets.png",
        "ceiling_buckets": out_dir / f"{airport}_ceiling_buckets.png",
        "wind_speed_buckets": out_dir / f"{airport}_wind_speed_buckets.png",
        "runway_operational_risks": out_dir / f"{airport}_runway_operational_risks.png",
    }
    plot_wind_rose(profile, charts["wind_rose"])
    plot_monthly_flight_category(profile, charts["monthly_flight_category"])
    plot_monthly_weather_rates(profile, charts["monthly_weather_rates"])
    plot_hourly_ifr_lifr(profile, charts["hourly_operational_risk"])
    plot_bucket_bar(profile, "visibilityBuckets", "Visibility bucket distribution", charts["visibility_buckets"], ["<550m", "550-799m", "800-1599m", "1600-2999m", "3000-4999m", "5000-9999m", ">=10000m/capped", "missing"])
    plot_bucket_bar(profile, "ceilingBuckets", "Ceiling bucket distribution", charts["ceiling_buckets"], ["<200ft", "200-499ft", "500-999ft", "1000-2999ft", ">=3000ft", "no_ceiling_or_missing"])
    plot_bucket_bar(profile, "windSpeedBuckets", "Wind speed bucket distribution", charts["wind_speed_buckets"], ["0-5kt", "6-10kt", "11-15kt", "16-25kt", ">25kt", "missing"])
    plot_runway_operational_risks(profile, charts["runway_operational_risks"])
    return {k: str(v) for k, v in charts.items() if v.exists()}
