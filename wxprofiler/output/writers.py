from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from wxprofiler.model import Observation


def write_observations_csv(obs: list[Observation], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [o.to_row() for o in obs]
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown_report(profile: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    airport = profile["airport"]["icao"]
    q = profile["quality"]
    o = profile["overall"]
    charts = profile.get("generatedArtifacts", {}).get("charts", {})
    tables = profile.get("generatedArtifacts", {}).get("tables", {})
    wr_overall = o.get("weatherRates", {})
    vs = o.get("visibilityStats", {})
    cs = o.get("ceilingStats", {})
    ws = o.get("windStats", {})
    gust_summary = (
        f"gust reported {ws.get('gustReportedRate', ws.get('gustDataAvailableRate',0)):.2%}; "
        f"gust >20 kt {ws.get('gustOver20ktObservedRate', ws.get('gustOver20ktRate',0)):.2%} of all observations; "
        f"conditional {ws.get('gustOver20ktConditionalRate',0):.2%} when gust is reported"
    ) if ws.get("gustReliable") else "gust data unavailable / not reliable"

    lines = [
        f"# {airport} Weather Profile",
        "",
        f"Period: {profile['period']['start']} to {profile['period']['end']}",
        f"Samples: {q['sampleCount']} / expected hourly {q['expectedHourlySampleCount']} / unique-hour coverage {q.get('hourCoverageRate', q.get('coverageRate')):.2%} / record density {q.get('recordDensityPerObservedHour')} per observed hour",
        "",
        "## Overall",
        f"VFR {o.get('vfrRate',0):.2%}, MVFR {o.get('mvfrRate',0):.2%}, IFR {o.get('ifrRate',0):.2%}, LIFR {o.get('lifrRate',0):.2%}",
        f"Wind: median {ws.get('medianWindKt')} kt, p75 {ws.get('p75WindKt')} kt, p90 {ws.get('p90WindKt')} kt, wind >15 kt {ws.get('windOver15ktRate',0):.2%}",
        f"Visibility: 10km+ {vs.get('cappedOr10kmPlusRate',0):.2%}, VIS <5000m {vs.get('below5000mRate',0):.2%}, VIS <1600m {vs.get('below1600mRate',0):.2%}, VIS <800m {vs.get('below800mRate',0):.2%}",
        f"Ceiling: CIG <3000ft {cs.get('below3000ftRate',0):.2%}, CIG <1000ft {cs.get('below1000ftRate',0):.2%}, CIG <500ft {cs.get('below500ftRate',0):.2%}",
        f"Gust: {gust_summary}",
        "",
        "Visibility median is intentionally not used as a primary metric because aviation visibility is often capped at 9999 / 10km+.",
        "",
        "## Weather rates",
    ]
    for k, v in wr_overall.items():
        lines.append(f"- {k}: {v:.2%}")

    if charts:
        lines += ["", "## Charts"]
        for name, chart_path in charts.items():
            try:
                rel = Path(chart_path).resolve().relative_to(path.parent.resolve())
            except Exception:
                rel = Path(chart_path)
            lines.append(f"### {name}")
            lines.append(f"![{name}]({rel.as_posix()})")
            lines.append(f"`{chart_path}`")
    if tables:
        lines += ["", "## CSV statistical tables"]
        for name, table_path in tables.items():
            lines.append(f"- {name}: `{table_path}`")

    if profile.get("runwayOperationalStats"):
        lines += ["", "## Runway operational stats"]
        for rwy, s in profile["runwayOperationalStats"].items():
            lines.append(f"- {rwy}: TW >5 kt {s.get('tailwindOver5ktRate',0):.2%}, TW >10 kt {s.get('tailwindOver10ktRate',0):.2%}, XW >15 kt {s.get('crosswindOver15ktRate',0):.2%}, XW >20 kt {s.get('crosswindOver20ktRate',0):.2%}")
    if q.get("warnings"):
        lines += ["", "## Data warnings"]
        for w in q["warnings"]:
            lines.append(f"- {w}")
    if q.get("info"):
        lines += ["", "## Data notes"]
        for w in q["info"]:
            lines.append(f"- {w}")

    lines += ["", "## Operational interpretation"]
    if o.get("ifrRate", 0) + o.get("lifrRate", 0) >= 0.15:
        lines.append("- IFR/LIFR share is high enough to matter for approach capacity, runway acceptance rate, spacing, and missed-approach modeling.")
    else:
        lines.append("- IFR/LIFR share is not dominant overall, but monthly and hourly distribution should still be checked before scenario design.")
    if wr_overall.get("snow", 0) >= 0.05:
        lines.append("- Snow appears frequently enough to justify runway contamination, snow-removal, braking-action, and visibility degradation logic.")
    if wr_overall.get("fog", 0) + wr_overall.get("mist", 0) >= 0.05:
        lines.append("- Fog/mist appears frequently enough to justify local-hour low-visibility templates.")
    if not ws.get("gustReliable"):
        lines.append("- Gust field is unavailable or too sparse; do not interpret gust as 0%.")
    elif ws.get("gustOver20ktObservedRate", ws.get("gustOver20ktRate", 0)) >= 0.03:
        lines.append("- Observed gust >20 kt rate is high enough to affect runway selection, final spacing, and stabilized-approach failures.")

    lines += ["", "## Monthly summary", "", "| Month | Samples | VFR | MVFR | IFR | LIFR | 10km+ | VIS<5000 | VIS<1600 | CIG<3000 | CIG<1000 | Snow | Rain | Fog/Mist | Gust>20 all obs | P90 wind |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for m, s in profile.get("monthly", {}).items():
        if not s or s.get("sampleCount", 0) == 0:
            continue
        wr = s.get("weatherRates", {})
        mvs = s.get("visibilityStats", {})
        mcs = s.get("ceilingStats", {})
        mws = s.get("windStats", {})
        fogmist = wr.get("fog", 0) + wr.get("mist", 0)
        gust = f"{mws.get('gustOver20ktObservedRate', mws.get('gustOver20ktRate',0)):.1%}" if mws.get("gustReliable") else "n/a"
        lines.append(f"| {m} | {s.get('sampleCount',0)} | {s.get('vfrRate',0):.1%} | {s.get('mvfrRate',0):.1%} | {s.get('ifrRate',0):.1%} | {s.get('lifrRate',0):.1%} | {mvs.get('cappedOr10kmPlusRate',0):.1%} | {mvs.get('below5000mRate',0):.1%} | {mvs.get('below1600mRate',0):.1%} | {mcs.get('below3000ftRate',0):.1%} | {mcs.get('below1000ftRate',0):.1%} | {wr.get('snow',0):.1%} | {wr.get('rain',0):.1%} | {fogmist:.1%} | {gust} | {mws.get('p90WindKt')} kt |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
