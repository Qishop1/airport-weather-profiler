from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import Any

from wxprofiler.output.charts import _import_pyplot, _save


def compare_rows(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for p in profiles:
        o = p.get("overall", {})
        wr = o.get("weatherRates", {})
        vs = o.get("visibilityStats", {})
        cs = o.get("ceilingStats", {})
        ws = o.get("windStats", {})
        rows.append({
            "airport": p.get("airport", {}).get("icao"),
            "samples": p.get("quality", {}).get("sampleCount"),
            "hour_coverage": p.get("quality", {}).get("hourCoverageRate", p.get("quality", {}).get("coverageRate")),
            "record_density_per_hour": p.get("quality", {}).get("recordDensityPerObservedHour"),
            "vfr": o.get("vfrRate"),
            "mvfr": o.get("mvfrRate"),
            "ifr": o.get("ifrRate"),
            "lifr": o.get("lifrRate"),
            "ifr_lifr": round((o.get("ifrRate", 0) or 0) + (o.get("lifrRate", 0) or 0), 4),
            "vis_10km_plus": vs.get("cappedOr10kmPlusRate"),
            "vis_below_5000m": vs.get("below5000mRate"),
            "vis_below_1600m": vs.get("below1600mRate"),
            "ceiling_below_3000ft": cs.get("below3000ftRate"),
            "ceiling_below_1000ft": cs.get("below1000ftRate"),
            "snow": wr.get("snow"),
            "rain": wr.get("rain"),
            "fog_mist": round((wr.get("fog", 0) or 0) + (wr.get("mist", 0) or 0), 4),
            "gust_data_available": ws.get("gustDataAvailableRate"),
            "gust_reliable": ws.get("gustReliable"),
            "gust_over_20kt_observed": ws.get("gustOver20ktObservedRate", ws.get("gustOver20ktRate")) if ws.get("gustReliable") else None,
            "gust_over_20kt_conditional": ws.get("gustOver20ktConditionalRate") if ws.get("gustReliable") else None,
            "median_wind_kt": ws.get("medianWindKt"),
            "p90_wind_kt": ws.get("p90WindKt"),
        })
    return rows


def write_compare_csv(profiles: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = compare_rows(profiles)
    fields = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if fields:
            w.writeheader()
            w.writerows(rows)


def write_compare_charts(profiles: list[dict[str, Any]], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = compare_rows(profiles)
    if not rows:
        return {}
    airports = [str(r["airport"]) for r in rows]
    charts: dict[str, str] = {}
    plt = _import_pyplot()

    def bar(keys: list[str], title: str, filename: str) -> None:
        x = list(range(len(airports)))
        width = 0.8 / max(len(keys), 1)
        fig, ax = plt.subplots(figsize=(10.5, 5.5))
        for idx, key in enumerate(keys):
            vals = [(float(r.get(key) or 0) * 100) for r in rows]
            ax.bar([i + (idx - (len(keys)-1)/2) * width for i in x], vals, width=width, label=key)
        ax.set_xticks(x)
        ax.set_xticklabels(airports)
        ax.set_ylabel("Observation share %")
        ax.set_title(title)
        ax.legend(ncols=min(len(keys), 4), loc="upper center", bbox_to_anchor=(0.5, -0.13))
        _save(fig, out_dir / filename)
        charts[filename.rsplit(".", 1)[0]] = str(out_dir / filename)

    bar(["vfr", "mvfr", "ifr", "lifr"], "Flight category comparison", "compare_flight_category.png")
    bar(["vis_below_5000m", "vis_below_1600m", "ceiling_below_1000ft"], "Low-visibility / low-ceiling comparison", "compare_low_ops.png")
    bar(["snow", "rain", "fog_mist"], "Weather phenomenon comparison", "compare_weather_phenomena.png")
    return charts


def write_compare_html(profiles: list[dict[str, Any]], path: Path, charts: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = compare_rows(profiles)
    headers = list(rows[0].keys()) if rows else []
    def rel(p: str) -> str:
        try:
            return Path(p).resolve().relative_to(path.parent.resolve()).as_posix()
        except Exception:
            return Path(p).as_posix()
    table = "<table><thead><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + "</tr></thead><tbody>"
    for r in rows:
        table += "<tr>" + "".join(f"<td>{html.escape(str(r.get(h, '')))}</td>" for h in headers) + "</tr>"
    table += "</tbody></table>"
    chart_html = "".join(f"<section><h2>{html.escape(k)}</h2><img src='{html.escape(rel(v))}'></section>" for k, v in charts.items())
    path.write_text(f"""<!doctype html><html><head><meta charset='utf-8'><title>Airport Weather Compare</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:28px;background:#f7f7f7}}main{{background:white;max-width:1180px;margin:auto;padding:26px;border-radius:14px}}table{{border-collapse:collapse;width:100%;font-size:12px}}td,th{{border:1px solid #ddd;padding:7px;text-align:right}}td:first-child,th:first-child{{text-align:left}}th{{background:#eee}}img{{max-width:100%;border:1px solid #ddd;border-radius:10px}}</style></head><body><main><h1>Airport Weather Compare</h1><p>Visibility is compared by thresholds, not median visibility.</p>{chart_html}<h2>Summary table</h2>{table}</main></body></html>""", encoding="utf-8")
