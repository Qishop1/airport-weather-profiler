from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any, Iterable

from wxprofiler.analysis.flight_category import classify
from wxprofiler.analysis.wind import components, wind_sector
from wxprofiler.config import AirportConfig
from wxprofiler.model import Observation


def pct(n: int | float, d: int | float) -> float:
    return round(float(n) / float(d), 4) if d else 0.0


def med(values: Iterable[float | None]) -> float | None:
    xs = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return round(median(xs), 2) if xs else None


def percentile(values: Iterable[float | None], q: float) -> float | None:
    xs = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not xs:
        return None
    if len(xs) == 1:
        return round(xs[0], 2)
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return round(xs[lo], 2)
    val = xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
    return round(val, 2)


def rate(obs: list[Observation], pred) -> float:
    return pct(sum(1 for o in obs if pred(o)), len(obs))


def has_token(o: Observation, parts: list[str]) -> bool:
    text = " ".join(o.wx_tokens).upper()
    return any(p in text for p in parts)


def bucket_visibility(m: float | None) -> str:
    if m is None:
        return "missing"
    if m < 550:
        return "<550m"
    if m < 800:
        return "550-799m"
    if m < 1600:
        return "800-1599m"
    if m < 3000:
        return "1600-2999m"
    if m < 5000:
        return "3000-4999m"
    if m < 10000:
        return "5000-9999m"
    return ">=10000m/capped"


def bucket_ceiling(ft: float | None) -> str:
    if ft is None:
        return "no_ceiling_or_missing"
    if ft < 200:
        return "<200ft"
    if ft < 500:
        return "200-499ft"
    if ft < 1000:
        return "500-999ft"
    if ft < 3000:
        return "1000-2999ft"
    return ">=3000ft"


def bucket_wind_speed(kt: float | None) -> str:
    if kt is None:
        return "missing"
    if kt <= 5:
        return "0-5kt"
    if kt <= 10:
        return "6-10kt"
    if kt <= 15:
        return "11-15kt"
    if kt <= 25:
        return "16-25kt"
    return ">25kt"


def visibility_stats(obs: list[Observation]) -> dict[str, Any]:
    total = len(obs)
    valid = [float(o.visibility_m) for o in obs if o.visibility_m is not None and math.isfinite(float(o.visibility_m))]
    d = len(valid)
    return {
        "availableRate": pct(d, total),
        "availableCount": d,
        "cappedOr10kmPlusRate": pct(sum(1 for v in valid if v >= 9999), d),
        "below8000mRate": pct(sum(1 for v in valid if v < 8000), d),
        "below5000mRate": pct(sum(1 for v in valid if v < 5000), d),
        "below3000mRate": pct(sum(1 for v in valid if v < 3000), d),
        "below1600mRate": pct(sum(1 for v in valid if v < 1600), d),
        "below800mRate": pct(sum(1 for v in valid if v < 800), d),
        "below550mRate": pct(sum(1 for v in valid if v < 550), d),
        "medianIsCappedAndNotOperationallyMeaningful": bool(d and med(valid) is not None and float(med(valid) or 0) >= 9999),
    }


def ceiling_stats(obs: list[Observation]) -> dict[str, Any]:
    total = len(obs)
    valid = [float(o.ceiling_ft) for o in obs if o.ceiling_ft is not None and math.isfinite(float(o.ceiling_ft))]
    d = len(valid)
    return {
        "availableRate": pct(d, total),
        "availableCount": d,
        "noCeilingOrMissingRate": pct(total - d, total),
        "below3000ftRate": pct(sum(1 for v in valid if v < 3000), d),
        "below1000ftRate": pct(sum(1 for v in valid if v < 1000), d),
        "below500ftRate": pct(sum(1 for v in valid if v < 500), d),
        "below200ftRate": pct(sum(1 for v in valid if v < 200), d),
        "atOrAbove3000ftRate": pct(sum(1 for v in valid if v >= 3000), d),
    }


def wind_stats(obs: list[Observation]) -> dict[str, Any]:
    speeds = [o.wind_speed_kt for o in obs]
    gusts = [float(o.wind_gust_kt) for o in obs if o.wind_gust_kt is not None and math.isfinite(float(o.wind_gust_kt))]
    total = len(obs)
    gust_available = len(gusts)
    gust_over_20 = sum(1 for v in gusts if v > 20)
    gust_over_30 = sum(1 for v in gusts if v > 30)

    # METAR/ASOS gusts are event-style fields: the field is usually omitted
    # unless a gust is present. Therefore there are two different rates:
    #   observed/all-sample rate: P(gust > threshold) across all observations
    #   conditional rate: P(gust > threshold | a gust was reported)
    # The observed/all-sample rate is the correct simulator/weather-risk rate.
    # The conditional rate is kept only as a diagnostic for the reported gust subset.
    reliable = gust_available >= max(100, int(total * 0.01)) if total else False
    return {
        "medianWindKt": med(speeds),
        "p75WindKt": percentile(speeds, 0.75),
        "p90WindKt": percentile(speeds, 0.90),
        "windOver15ktRate": rate(obs, lambda o: o.wind_speed_kt is not None and o.wind_speed_kt > 15),
        "windOver25ktRate": rate(obs, lambda o: o.wind_speed_kt is not None and o.wind_speed_kt > 25),
        "gustDataAvailableRate": pct(gust_available, total),
        "gustReportedRate": pct(gust_available, total),
        "gustAvailableCount": gust_available,
        "gustReliable": reliable,
        "gustOver20ktObservedRate": pct(gust_over_20, total),
        "gustOver30ktObservedRate": pct(gust_over_30, total),
        "gustOver20ktConditionalRate": pct(gust_over_20, gust_available),
        "gustOver30ktConditionalRate": pct(gust_over_30, gust_available),
        # Backward-compatible names. These now mean all-observation rates,
        # not conditional rates. Older builds used these incorrectly.
        "gustOver20ktRate": pct(gust_over_20, total),
        "gustOver30ktRate": pct(gust_over_30, total),
        "gustDataMode": "explicit_reported_gust_field",
    }


def summarize_group(obs: list[Observation], wind_sector_size: int = 20) -> dict[str, Any]:
    cats = Counter(classify(o) for o in obs)
    sectors = Counter(wind_sector(o.wind_dir_deg, wind_sector_size) for o in obs if wind_sector(o.wind_dir_deg, wind_sector_size) is not None)
    vis_buckets = Counter(bucket_visibility(o.visibility_m) for o in obs)
    ceil_buckets = Counter(bucket_ceiling(o.ceiling_ft) for o in obs)
    wind_buckets = Counter(bucket_wind_speed(o.wind_speed_kt) for o in obs)
    total = len(obs)
    wstats = wind_stats(obs)
    return {
        "sampleCount": total,
        "flightCategory": {k: pct(v, total) for k, v in sorted(cats.items())},
        "vfrRate": pct(cats.get("VFR", 0), total),
        "mvfrRate": pct(cats.get("MVFR", 0), total),
        "ifrRate": pct(cats.get("IFR", 0), total),
        "lifrRate": pct(cats.get("LIFR", 0), total),
        "weatherRates": {
            "rain": rate(obs, lambda o: has_token(o, ["RA", "DZ", "SHRA"])),
            "snow": rate(obs, lambda o: has_token(o, ["SN", "SG", "SHSN"])),
            "fog": rate(obs, lambda o: has_token(o, ["FG"])),
            "mist": rate(obs, lambda o: has_token(o, ["BR"])),
            "thunder": rate(obs, lambda o: has_token(o, ["TS"])),
            "freezing": rate(obs, lambda o: has_token(o, ["FZ"])),
            "blowingSnow": rate(obs, lambda o: has_token(o, ["BLSN", "DRSN"])),
        },
        # Kept for schema compatibility. Prefer windStats.gustDataAvailableRate / gustReliable.
        "gustRate": wstats["gustDataAvailableRate"],
        "windStats": wstats,
        "visibilityStats": visibility_stats(obs),
        "ceilingStats": ceiling_stats(obs),
        # Wind median remains useful. Visibility/ceiling medians are kept only as legacy fields.
        "medianWindKt": wstats["medianWindKt"],
        "medianVisibilityM": med(o.visibility_m for o in obs),
        "medianCeilingFt": med(o.ceiling_ft for o in obs),
        "windSectors": {str(int(k)): pct(v, total) for k, v in sorted(sectors.items())},
        "windSpeedBuckets": {k: pct(v, total) for k, v in sorted(wind_buckets.items())},
        "visibilityBuckets": {k: pct(v, total) for k, v in sorted(vis_buckets.items())},
        "ceilingBuckets": {k: pct(v, total) for k, v in sorted(ceil_buckets.items())},
    }


def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            y += 1
            m = 1


def _last_day_of_month(y: int, m: int) -> int:
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    return (nxt - timedelta(days=1)).day


def quality_report(obs: list[Observation], start: date, end: date) -> dict[str, Any]:
    days = max((end - start).days + 1, 1)
    expected = days * 24
    unique_hours = {o.valid_utc.replace(minute=0, second=0, microsecond=0) for o in obs}
    observed_hours = len(unique_hours)
    coverage = observed_hours / expected if expected else 0
    density = len(obs) / observed_hours if observed_hours else 0

    observed_months = {(o.valid_utc.year, o.valid_utc.month) for o in obs}
    all_months = set(_month_iter(start, end))
    missing_months = [f"{y:04d}-{m:02d}" for y, m in sorted(all_months - observed_months)]
    partial_months: list[str] = []
    if start.day != 1:
        partial_months.append(f"{start.year:04d}-{start.month:02d}")
    if end.day != _last_day_of_month(end.year, end.month):
        s = f"{end.year:04d}-{end.month:02d}"
        if s not in partial_months:
            partial_months.append(s)

    warnings = []
    info = []
    if coverage < 0.75:
        warnings.append("Unique-hour coverage is below 75%; climatology may be weak or station/source may be incomplete.")
    if missing_months:
        warnings.append("One or more full calendar months have zero observations.")
    if partial_months:
        info.append("The selected period starts or ends mid-month; first/last month statistics are partial.")
    if any(o.source_quality == "normalized_hourly_non_metar" for o in obs):
        warnings.append("Some observations are non-METAR normalized hourly data; weather-code/cloud detail may be limited.")
    if any(o.source == "noaa_isd" for o in obs):
        info.append("NOAA ISD is a long-history hourly/synoptic source. Gust and present-weather detail may be less complete than raw METAR.")
    return {
        "sampleCount": len(obs),
        "expectedHourlySampleCount": expected,
        "observedUniqueHourlySampleCount": observed_hours,
        "hourCoverageRate": round(coverage, 4),
        "recordDensityPerObservedHour": round(density, 3),
        # Backward-compatible alias now means unique-hour coverage, not raw-record coverage.
        "coverageRate": round(coverage, 4),
        "missingMonths": missing_months,
        "partialMonths": partial_months,
        "usableForClimatology": coverage >= 0.75 and not missing_months,
        "warnings": warnings,
        "info": info,
    }


def runway_stats(obs: list[Observation], cfg: AirportConfig) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rwy in cfg.runways:
        comps = [components(o.wind_dir_deg, o.wind_speed_kt, rwy.heading) for o in obs]
        out[rwy.id] = {
            "heading": rwy.heading,
            "medianHeadwindKt": med(c["headwind"] for c in comps),
            "medianTailwindKt": med(c["tailwind"] for c in comps),
            "medianCrosswindKt": med(c["crosswind"] for c in comps),
            "tailwindOver5ktRate": pct(sum(1 for c in comps if c["tailwind"] is not None and c["tailwind"] > 5), len(comps)),
            "tailwindOver10ktRate": pct(sum(1 for c in comps if c["tailwind"] is not None and c["tailwind"] > 10), len(comps)),
            "crosswindOver15ktRate": pct(sum(1 for c in comps if c["crosswind"] is not None and c["crosswind"] > 15), len(comps)),
            "crosswindOver20ktRate": pct(sum(1 for c in comps if c["crosswind"] is not None and c["crosswind"] > 20), len(comps)),
            "crosswindOver25ktRate": pct(sum(1 for c in comps if c["crosswind"] is not None and c["crosswind"] > 25), len(comps)),
        }
    return out


def archetypes(obs: list[Observation]) -> list[dict[str, Any]]:
    by_season: dict[str, list[Observation]] = defaultdict(list)
    for o in obs:
        m = o.valid_local.month if o.valid_local else o.valid_utc.month
        season = "winter" if m in [12, 1, 2] else "spring" if m in [3, 4, 5] else "summer" if m in [6, 7, 8] else "autumn"
        by_season[season].append(o)
    result = []
    for season, group in by_season.items():
        s = summarize_group(group)
        common = []
        wr = s["weatherRates"]
        for key, threshold in [("snow", .05), ("rain", .08), ("fog", .03), ("mist", .05), ("thunder", .01), ("blowingSnow", .01)]:
            if wr.get(key, 0) >= threshold:
                common.append(key)
        impact = []
        if s.get("ifrRate", 0) + s.get("lifrRate", 0) > .12:
            impact.append("instrument/low-ceiling operations likely")
        if wr.get("snow", 0) > .05:
            impact.append("snow or runway contamination risk")
        if s.get("windStats", {}).get("gustReliable") and s.get("windStats", {}).get("gustOver20ktObservedRate", s.get("windStats", {}).get("gustOver20ktRate", 0)) > .03:
            impact.append("gusty wind and spacing instability")
        if s.get("visibilityStats", {}).get("below5000mRate", 0) > .10:
            impact.append("low-visibility risk")
        result.append({
            "id": f"{season}_typical",
            "season": season,
            "sampleCount": len(group),
            "commonWeather": common,
            "vfrRate": s.get("vfrRate"),
            "ifrOrLowerRate": round(s.get("ifrRate", 0) + s.get("lifrRate", 0), 4),
            "medianWindKt": s.get("medianWindKt"),
            "visibilityBelow5000mRate": s.get("visibilityStats", {}).get("below5000mRate"),
            "ceilingBelow1000ftRate": s.get("ceilingStats", {}).get("below1000ftRate"),
            "operationalImpact": impact,
        })
    return result


def full_profile(airport: str, obs: list[Observation], cfg: AirportConfig, start, end, wind_sector_size: int = 20) -> dict[str, Any]:
    obs = sorted(obs, key=lambda o: o.valid_utc)
    monthly: dict[str, Any] = {}
    hourly: dict[str, Any] = {}
    by_month: dict[int, list[Observation]] = defaultdict(list)
    by_hour: dict[int, list[Observation]] = defaultdict(list)
    for o in obs:
        local = o.valid_local or o.valid_utc
        by_month[local.month].append(o)
        by_hour[local.hour].append(o)
    for m in range(1, 13):
        monthly[f"{m:02d}"] = summarize_group(by_month.get(m, []), wind_sector_size) if by_month.get(m) else {"sampleCount": 0}
    for h in range(24):
        hourly[f"{h:02d}"] = summarize_group(by_hour.get(h, []), wind_sector_size) if by_hour.get(h) else {"sampleCount": 0}
    sources = Counter(o.source for o in obs)
    return {
        "schemaVersion": "1.2",
        "airport": {
            "icao": airport.upper(),
            "timezone": cfg.timezone,
            "latitude": cfg.latitude,
            "longitude": cfg.longitude,
            "elevation_m": cfg.elevation_m,
            "runways": [{"id": r.id, "heading": r.heading} for r in cfg.runways],
        },
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "sources": [{"name": k, "records": v} for k, v in sorted(sources.items())],
        "quality": quality_report(obs, start, end),
        "overall": summarize_group(obs, wind_sector_size),
        "monthly": monthly,
        "hourlyLocal": hourly,
        "runwayOperationalStats": runway_stats(obs, cfg) if cfg.runways else {},
        "weatherArchetypes": archetypes(obs),
        "simulatorProfile": simulator_profile(monthly),
    }


def simulator_profile(monthly: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for month, s in monthly.items():
        if not s or s.get("sampleCount", 0) == 0:
            continue
        wr = s.get("weatherRates", {})
        vs = s.get("visibilityStats", {})
        cs = s.get("ceilingStats", {})
        ws = s.get("windStats", {})
        out[month] = {
            "vfrWeight": s.get("vfrRate", 0),
            "mvfrWeight": s.get("mvfrRate", 0),
            "ifrWeight": s.get("ifrRate", 0),
            "lifrWeight": s.get("lifrRate", 0),
            "snowRisk": wr.get("snow", 0),
            "rainRisk": wr.get("rain", 0),
            "fogMistRisk": round(wr.get("fog", 0) + wr.get("mist", 0), 4),
            "thunderRisk": wr.get("thunder", 0),
            # All-observation gust probability for simulator weather generation.
            "gustRisk": ws.get("gustOver20ktObservedRate", ws.get("gustOver20ktRate", 0)) if ws.get("gustReliable") else None,
            "gustOver20ktObservedRate": ws.get("gustOver20ktObservedRate", ws.get("gustOver20ktRate", 0)),
            "gustOver30ktObservedRate": ws.get("gustOver30ktObservedRate", ws.get("gustOver30ktRate", 0)),
            "gustOver20ktConditionalRate": ws.get("gustOver20ktConditionalRate", 0),
            "gustOver30ktConditionalRate": ws.get("gustOver30ktConditionalRate", 0),
            "gustDataAvailableRate": ws.get("gustDataAvailableRate", 0),
            "visibilityBelow5000mRisk": vs.get("below5000mRate", 0),
            "visibilityBelow1600mRisk": vs.get("below1600mRate", 0),
            "ceilingBelow3000ftRisk": cs.get("below3000ftRate", 0),
            "ceilingBelow1000ftRisk": cs.get("below1000ftRate", 0),
            "dominantWindSectors": top_items(s.get("windSectors", {}), 5),
        }
    return out


def top_items(d: dict[str, float], n: int) -> list[dict[str, float | str]]:
    return [{"sector": k, "rate": v} for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]]
