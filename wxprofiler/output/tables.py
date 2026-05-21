from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for k in row.keys():
            if k not in fields:
                fields.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _rates(prefix: str, d: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}_{k}": v for k, v in d.items()}


def _summary_row(period_key: str, period_value: str, s: dict[str, Any]) -> dict[str, Any]:
    wr = s.get("weatherRates", {})
    vs = s.get("visibilityStats", {})
    cs = s.get("ceilingStats", {})
    ws = s.get("windStats", {})
    row = {
        period_key: period_value,
        "sampleCount": s.get("sampleCount"),
        "vfrRate": s.get("vfrRate"),
        "mvfrRate": s.get("mvfrRate"),
        "ifrRate": s.get("ifrRate"),
        "lifrRate": s.get("lifrRate"),
        "visibility10kmPlusRate": vs.get("cappedOr10kmPlusRate"),
        "visibilityBelow8000mRate": vs.get("below8000mRate"),
        "visibilityBelow5000mRate": vs.get("below5000mRate"),
        "visibilityBelow3000mRate": vs.get("below3000mRate"),
        "visibilityBelow1600mRate": vs.get("below1600mRate"),
        "visibilityBelow800mRate": vs.get("below800mRate"),
        "visibilityBelow550mRate": vs.get("below550mRate"),
        "ceilingBelow3000ftRate": cs.get("below3000ftRate"),
        "ceilingBelow1000ftRate": cs.get("below1000ftRate"),
        "ceilingBelow500ftRate": cs.get("below500ftRate"),
        "ceilingBelow200ftRate": cs.get("below200ftRate"),
        "medianWindKt": ws.get("medianWindKt"),
        "p75WindKt": ws.get("p75WindKt"),
        "p90WindKt": ws.get("p90WindKt"),
        "windOver15ktRate": ws.get("windOver15ktRate"),
        "windOver25ktRate": ws.get("windOver25ktRate"),
        "gustDataAvailableRate": ws.get("gustDataAvailableRate"),
        "gustReliable": ws.get("gustReliable"),
        "gustReportedRate": ws.get("gustReportedRate", ws.get("gustDataAvailableRate")),
        "gustOver20ktObservedRate": ws.get("gustOver20ktObservedRate", ws.get("gustOver20ktRate")),
        "gustOver30ktObservedRate": ws.get("gustOver30ktObservedRate", ws.get("gustOver30ktRate")),
        "gustOver20ktConditionalRate": ws.get("gustOver20ktConditionalRate"),
        "gustOver30ktConditionalRate": ws.get("gustOver30ktConditionalRate"),
        "gustOver20ktRate_legacy_allObs": ws.get("gustOver20ktRate"),
        "gustOver30ktRate_legacy_allObs": ws.get("gustOver30ktRate"),
        "legacyMedianVisibilityM_doNotUseForOps": s.get("medianVisibilityM"),
        "legacyMedianCeilingFt_auxOnly": s.get("medianCeilingFt"),
    }
    row.update(_rates("wx", wr))
    return row


def write_stat_tables(profile: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}

    monthly_rows = []
    for month, s in profile.get("monthly", {}).items():
        if not s or s.get("sampleCount", 0) == 0:
            continue
        monthly_rows.append(_summary_row("month", month, s))
    monthly_path = out_dir / "monthly_summary.csv"
    _write_rows(monthly_path, monthly_rows)
    artifacts["monthly_summary"] = str(monthly_path)

    hourly_rows = []
    for hour, s in profile.get("hourlyLocal", {}).items():
        if not s or s.get("sampleCount", 0) == 0:
            continue
        hourly_rows.append(_summary_row("hourLocal", hour, s))
    hourly_path = out_dir / "hourly_local_summary.csv"
    _write_rows(hourly_path, hourly_rows)
    artifacts["hourly_local_summary"] = str(hourly_path)

    wind_rows = []
    for sector, rate in profile.get("overall", {}).get("windSectors", {}).items():
        wind_rows.append({"sectorDeg": sector, "rate": rate})
    wind_path = out_dir / "wind_rose_table.csv"
    _write_rows(wind_path, wind_rows)
    artifacts["wind_rose_table"] = str(wind_path)

    bucket_rows = []
    for bucket_name in ["windSpeedBuckets", "visibilityBuckets", "ceilingBuckets"]:
        for bucket, rate in profile.get("overall", {}).get(bucket_name, {}).items():
            bucket_rows.append({"bucketType": bucket_name, "bucket": bucket, "rate": rate})
    bucket_path = out_dir / "bucket_distributions.csv"
    _write_rows(bucket_path, bucket_rows)
    artifacts["bucket_distributions"] = str(bucket_path)

    runway_rows = []
    for runway, s in profile.get("runwayOperationalStats", {}).items():
        row = {"runway": runway}
        row.update(s)
        runway_rows.append(row)
    runway_path = out_dir / "runway_operational_stats.csv"
    _write_rows(runway_path, runway_rows)
    artifacts["runway_operational_stats"] = str(runway_path)

    archetype_path = out_dir / "weather_archetypes.csv"
    _write_rows(archetype_path, profile.get("weatherArchetypes", []))
    artifacts["weather_archetypes"] = str(archetype_path)

    return artifacts
