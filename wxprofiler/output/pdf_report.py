from __future__ import annotations

from pathlib import Path
from typing import Any


def _pct(v: Any) -> str:
    try:
        return f"{float(v):.1%}"
    except Exception:
        return "n/a"


def write_pdf_report(profile: dict[str, Any], path: Path) -> None:
    """Write a compact PDF report.

    ReportLab is imported lazily so the profiler still runs when PDF support is not installed.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError("PDF export requires reportlab. Install with: pip install reportlab") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    airport = profile.get("airport", {}).get("icao", "AIRPORT")
    period = profile.get("period", {})
    q = profile.get("quality", {})
    o = profile.get("overall", {})
    wr = o.get("weatherRates", {})
    vs = o.get("visibilityStats", {})
    cs = o.get("ceilingStats", {})
    ws = o.get("windStats", {})
    charts = profile.get("generatedArtifacts", {}).get("charts", {}) or {}

    story = []
    story.append(Paragraph(f"{airport} Weather Profile", styles["Title"]))
    story.append(Paragraph(f"Period: {period.get('start')} to {period.get('end')}", styles["Normal"]))
    story.append(Paragraph("Visibility is summarized by threshold rates because aviation visibility is commonly capped at 9999 / 10 km+.", styles["BodyText"]))
    story.append(Spacer(1, 0.15 * inch))

    gust_label = _pct(ws.get("gustOver20ktObservedRate", ws.get("gustOver20ktRate", 0))) if ws.get("gustReliable") else "unavailable"
    summary = [
        ["Samples", q.get("sampleCount", 0), "Hour coverage", _pct(q.get("hourCoverageRate", q.get("coverageRate", 0)))],
        ["VFR", _pct(o.get("vfrRate", 0)), "IFR+LIFR", _pct((o.get("ifrRate", 0) or 0) + (o.get("lifrRate", 0) or 0))],
        ["VIS <5000m", _pct(vs.get("below5000mRate", 0)), "CIG <1000ft", _pct(cs.get("below1000ftRate", 0))],
        ["Snow", _pct(wr.get("snow", 0)), "FG+BR", _pct((wr.get("fog", 0) or 0) + (wr.get("mist", 0) or 0))],
        ["P90 wind", ws.get("p90WindKt"), "Gust >20kt all obs", gust_label],
    ]
    t = Table(summary, hAlign="LEFT", colWidths=[1.4*inch, 1.4*inch, 1.4*inch, 1.4*inch])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(t)

    if q.get("warnings"):
        story.append(Spacer(1, 0.15 * inch))
        story.append(Paragraph("Data warnings", styles["Heading2"]))
        for w in q.get("warnings", []):
            story.append(Paragraph(f"- {w}", styles["BodyText"]))
    if q.get("info"):
        story.append(Spacer(1, 0.15 * inch))
        story.append(Paragraph("Data notes", styles["Heading2"]))
        for w in q.get("info", []):
            story.append(Paragraph(f"- {w}", styles["BodyText"]))

    # Add the most useful charts; keep PDF compact.
    for key in ["wind_rose", "monthly_flight_category", "monthly_weather_rates", "hourly_operational_risk", "visibility_buckets", "ceiling_buckets", "runway_operational_risks"]:
        chart = charts.get(key)
        if chart and Path(chart).exists():
            story.append(Spacer(1, 0.18 * inch))
            story.append(Paragraph(key.replace("_", " ").title(), styles["Heading2"]))
            story.append(Image(str(chart), width=6.5*inch, height=3.8*inch, kind="proportional"))

    story.append(Spacer(1, 0.18 * inch))
    story.append(Paragraph("Monthly operating summary", styles["Heading2"]))
    rows = [["Month", "Samples", "VFR", "IFR+LIFR", "10km+", "VIS<5000", "CIG<1000", "Snow", "FG+BR"]]
    for m, s in profile.get("monthly", {}).items():
        if not s or not s.get("sampleCount"):
            continue
        mw = s.get("weatherRates", {})
        mvs = s.get("visibilityStats", {})
        mcs = s.get("ceilingStats", {})
        rows.append([
            m, s.get("sampleCount"),
            _pct(s.get("vfrRate", 0)),
            _pct((s.get("ifrRate", 0) or 0) + (s.get("lifrRate", 0) or 0)),
            _pct(mvs.get("cappedOr10kmPlusRate", 0)),
            _pct(mvs.get("below5000mRate", 0)),
            _pct(mcs.get("below1000ftRate", 0)),
            _pct(mw.get("snow", 0)),
            _pct((mw.get("fog", 0) or 0) + (mw.get("mist", 0) or 0)),
        ])
    mt = Table(rows, repeatRows=1, hAlign="LEFT")
    mt.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(mt)

    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=0.45*inch, leftMargin=0.45*inch, topMargin=0.45*inch, bottomMargin=0.45*inch)
    doc.build(story)
