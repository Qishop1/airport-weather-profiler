from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def _pct(v: Any) -> str:
    try:
        return f"{float(v):.1%}"
    except Exception:
        return "n/a"


def _num(v: Any, suffix: str = "") -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.1f}{suffix}"
    except Exception:
        return f"{v}{suffix}"


def _rel(path: str | Path, base: Path) -> str:
    try:
        return Path(path).resolve().relative_to(base.resolve()).as_posix()
    except Exception:
        return Path(path).as_posix()


def _table(rows: list[list[Any]], headers: list[str]) -> str:
    out = ["<table>", "<thead><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + "</tr></thead>", "<tbody>"]
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def _interpretation(profile: dict[str, Any]) -> list[str]:
    monthly = profile.get("monthly", {})
    lines: list[str] = []
    valid_months = [(m, s) for m, s in monthly.items() if s and s.get("sampleCount")]
    if not valid_months:
        return lines
    worst_ifr = max(valid_months, key=lambda kv: (kv[1].get("ifrRate", 0) or 0) + (kv[1].get("lifrRate", 0) or 0))
    best_vfr = max(valid_months, key=lambda kv: kv[1].get("vfrRate", 0) or 0)
    snow_peak = max(valid_months, key=lambda kv: kv[1].get("weatherRates", {}).get("snow", 0) or 0)
    lowvis_peak = max(valid_months, key=lambda kv: kv[1].get("visibilityStats", {}).get("below5000mRate", 0) or 0)
    lowcig_peak = max(valid_months, key=lambda kv: kv[1].get("ceilingStats", {}).get("below1000ftRate", 0) or 0)

    lines.append(f"Worst IFR/LIFR month: {worst_ifr[0]} ({_pct((worst_ifr[1].get('ifrRate',0) or 0) + (worst_ifr[1].get('lifrRate',0) or 0))}).")
    lines.append(f"Best VFR month: {best_vfr[0]} ({_pct(best_vfr[1].get('vfrRate',0))}).")
    if snow_peak[1].get("weatherRates", {}).get("snow", 0) > 0:
        lines.append(f"Peak snow month: {snow_peak[0]} ({_pct(snow_peak[1].get('weatherRates',{}).get('snow',0))}).")
    lines.append(f"Peak VIS <5000 m month: {lowvis_peak[0]} ({_pct(lowvis_peak[1].get('visibilityStats',{}).get('below5000mRate',0))}).")
    lines.append(f"Peak ceiling <1000 ft month: {lowcig_peak[0]} ({_pct(lowcig_peak[1].get('ceilingStats',{}).get('below1000ftRate',0))}).")

    overall = profile.get("overall", {})
    if overall.get("visibilityStats", {}).get("medianIsCappedAndNotOperationallyMeaningful"):
        lines.append("Visibility median is capped at 9999/10 km+ and is intentionally not used as a primary operating metric; threshold rates are used instead.")
    if not overall.get("windStats", {}).get("gustReliable"):
        lines.append("Gust data is unavailable or too sparse for this source; gust risk is not treated as a reliable zero.")
    return lines


def write_html_report(profile: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    airport = profile.get("airport", {}).get("icao", "AIRPORT")
    period = profile.get("period", {})
    q = profile.get("quality", {})
    o = profile.get("overall", {})
    wr = o.get("weatherRates", {})
    vs = o.get("visibilityStats", {})
    cs = o.get("ceilingStats", {})
    ws = o.get("windStats", {})
    charts = profile.get("generatedArtifacts", {}).get("charts", {}) or {}
    station_report = profile.get("stationResolution", {})
    runway_report = profile.get("runwayResolution", {})
    merge_report = profile.get("mergeReport", {})

    monthly_rows = []
    for m, s in profile.get("monthly", {}).items():
        if not s or not s.get("sampleCount"):
            continue
        mw = s.get("weatherRates", {})
        mvs = s.get("visibilityStats", {})
        mcs = s.get("ceilingStats", {})
        mws = s.get("windStats", {})
        gust_text = _pct(mws.get("gustOver20ktObservedRate", mws.get("gustOver20ktRate", 0))) if mws.get("gustReliable") else "unavailable"
        monthly_rows.append([
            m,
            s.get("sampleCount", 0),
            _pct(s.get("vfrRate", 0)),
            _pct(s.get("mvfrRate", 0)),
            _pct(s.get("ifrRate", 0)),
            _pct(s.get("lifrRate", 0)),
            _pct(mvs.get("cappedOr10kmPlusRate", 0)),
            _pct(mvs.get("below5000mRate", 0)),
            _pct(mvs.get("below1600mRate", 0)),
            _pct(mcs.get("below3000ftRate", 0)),
            _pct(mcs.get("below1000ftRate", 0)),
            _pct(mw.get("snow", 0)),
            _pct(mw.get("rain", 0)),
            _pct(mw.get("fog", 0) + mw.get("mist", 0)),
            gust_text,
            _num(mws.get("p90WindKt"), " kt"),
        ])

    runway_rows = []
    for rwy, s in profile.get("runwayOperationalStats", {}).items():
        runway_rows.append([
            rwy, s.get("heading"),
            s.get("medianHeadwindKt"), s.get("medianCrosswindKt"),
            _pct(s.get("tailwindOver5ktRate", 0)), _pct(s.get("tailwindOver10ktRate", 0)),
            _pct(s.get("crosswindOver15ktRate", 0)), _pct(s.get("crosswindOver20ktRate", 0)), _pct(s.get("crosswindOver25ktRate", 0)),
        ])

    chart_html = []
    for name, p in charts.items():
        rel = _rel(p, path.parent)
        chart_html.append(f"<section class='chart'><h3>{html.escape(name.replace('_', ' ').title())}</h3><img src='{html.escape(rel)}' alt='{html.escape(name)}'></section>")

    cards = [
        ("Samples", q.get("sampleCount", 0)),
        ("Hour coverage", _pct(q.get("hourCoverageRate", q.get("coverageRate", 0)))),
        ("Record density", f"{q.get('recordDensityPerObservedHour', 0)} / hr"),
        ("VFR", _pct(o.get("vfrRate", 0))),
        ("IFR + LIFR", _pct(o.get("ifrRate", 0) + o.get("lifrRate", 0))),
        ("VIS <5000 m", _pct(vs.get("below5000mRate", 0))),
        ("CIG <1000 ft", _pct(cs.get("below1000ftRate", 0))),
        ("Snow", _pct(wr.get("snow", 0))),
        ("Fog + Mist", _pct(wr.get("fog", 0) + wr.get("mist", 0))),
        ("Gust >20 kt", _pct(ws.get("gustOver20ktObservedRate", ws.get("gustOver20ktRate", 0))) if ws.get("gustReliable") else "unavailable"),
    ]

    body = f"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(airport)} Weather Profile</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif; margin: 28px; color: #111; background: #f7f7f7; }}
main {{ max-width: 1280px; margin: auto; background: white; padding: 28px; border-radius: 14px; box-shadow: 0 3px 18px rgba(0,0,0,.08); }}
h1 {{ margin-top: 0; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 18px 0; }}
.card {{ border: 1px solid #ddd; border-radius: 12px; padding: 14px; background: #fafafa; }}
.card b {{ display: block; font-size: 13px; color: #555; margin-bottom: 6px; }}
.card span {{ font-size: 22px; }}
section {{ margin-top: 28px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
th, td {{ border: 1px solid #ddd; padding: 7px 9px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ background: #f0f0f0; position: sticky; top: 0; }}
.chart img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 10px; background: white; }}
pre {{ background: #111; color: #eee; padding: 14px; border-radius: 10px; overflow: auto; font-size: 12px; }}
.warn {{ background: #fff7df; border: 1px solid #e7c765; padding: 10px 14px; border-radius: 10px; }}
.info {{ background: #eef6ff; border: 1px solid #9fc6ee; padding: 10px 14px; border-radius: 10px; }}
.note {{ color: #555; font-size: 13px; }}
</style>
</head>
<body><main>
<h1>{html.escape(airport)} Weather Profile</h1>
<p>Period: {html.escape(str(period.get('start')))} to {html.escape(str(period.get('end')))}</p>
<div class="cards">
"""
    for label, value in cards:
        body += f"  <div class='card'><b>{html.escape(str(label))}</b><span>{html.escape(str(value))}</span></div>\n"
    body += "</div>\n"
    body += "<p class='note'>Visibility and ceiling are threshold-based in this report. Visibility median is not used as a primary metric because aviation visibility is commonly capped at 9999 / 10 km+.</p><p class='note'>Gust is reported as an all-observation probability. Conditional gust rates are retained in JSON/CSV only as diagnostics for the subset where a gust was explicitly reported.</p>"

    interp = _interpretation(profile)
    if interp:
        body += "<section><h2>Operational interpretation</h2><ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in interp) + "</ul></section>"
    if q.get("warnings"):
        body += "<section class='warn'><h2>Data warnings</h2><ul>" + "".join(f"<li>{html.escape(str(w))}</li>" for w in q.get("warnings", [])) + "</ul></section>"
    if q.get("info"):
        body += "<section class='info'><h2>Data notes</h2><ul>" + "".join(f"<li>{html.escape(str(w))}</li>" for w in q.get("info", [])) + "</ul></section>"
    body += "<section><h2>Charts</h2>" + "\n".join(chart_html) + "</section>"
    body += "<section><h2>Monthly operating summary</h2>" + _table(monthly_rows, ["Month", "Samples", "VFR", "MVFR", "IFR", "LIFR", "10km+", "VIS<5000", "VIS<1600", "CIG<3000", "CIG<1000", "Snow", "Rain", "FG+BR", "Gust>20 all obs", "P90 wind"]) + "</section>"
    if runway_rows:
        body += "<section><h2>Runway wind-risk summary</h2>" + _table(runway_rows, ["Runway", "Heading", "Median HW", "Median XW", "TW >5", "TW >10", "XW >15", "XW >20", "XW >25"]) + "</section>"
    body += "<section><h2>Station / fallback report</h2><pre>" + html.escape(json.dumps(station_report, ensure_ascii=False, indent=2)) + "</pre></section>"
    body += "<section><h2>Runway resolver report</h2><pre>" + html.escape(json.dumps(runway_report, ensure_ascii=False, indent=2)) + "</pre></section>"
    body += "<section><h2>Merge / deduplication report</h2><pre>" + html.escape(json.dumps(merge_report, ensure_ascii=False, indent=2)) + "</pre></section>"
    body += "</main></body></html>\n"
    path.write_text(body, encoding="utf-8")
