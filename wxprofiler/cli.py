from __future__ import annotations

import os
import sys
import builtins

# Windows portable EXE note:
# The GUI launches this CLI backend as a child process and reads WXPROGRESS
# lines from stdout. On some Windows systems the default pipe encoding is
# cp1252/ANSI, which cannot encode Chinese progress text and crashes the
# frozen executable. Force UTF-8 and fall back to replacement-safe writes.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
    try:
        if _stream and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def safe_print(*args, **kwargs) -> None:
    text = " ".join(str(a) for a in args)
    end = kwargs.pop("end", "\n")
    flush = kwargs.pop("flush", False)
    stream = kwargs.pop("file", sys.stdout)
    try:
        builtins.print(text, end=end, file=stream, flush=flush, **kwargs)
    except UnicodeEncodeError:
        data = (text + end).encode("utf-8", errors="replace")
        try:
            buffer = getattr(stream, "buffer", None)
            if buffer is not None:
                buffer.write(data)
                if flush:
                    buffer.flush()
            else:
                stream.write((text + end).encode("ascii", errors="replace").decode("ascii"))
                if flush:
                    stream.flush()
        except Exception:
            pass

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from wxprofiler.analysis.merge import merge_observations
from wxprofiler.analysis.stats import full_profile
from wxprofiler.config import load_runway_config
from wxprofiler.output.charts import create_all_charts
from wxprofiler.output.compare import write_compare_charts, write_compare_csv, write_compare_html
from wxprofiler.output.html_report import write_html_report
from wxprofiler.output.pdf_report import write_pdf_report
from wxprofiler.output.tables import write_stat_tables
from wxprofiler.output.writers import write_json, write_markdown_report, write_observations_csv
from wxprofiler.parsing.normalize import normalize_iem, normalize_local, normalize_meteostat, normalize_noaa_isd
from wxprofiler.sources.iem_asos import download_range as iem_download_range
from wxprofiler.sources.local_csv import read_local_csv
from wxprofiler.sources.meteostat import download_hourly_by_station_id, find_station_by_icao
from wxprofiler.sources.noaa_isd import NoaaIsdError, download_range as noaa_download_range, resolve_station
from wxprofiler.sources.ourairports import enrich_config_from_ourairports


def parse_date(s: str) -> date:
    return date.fromisoformat(s)


def default_start(years: int) -> date:
    today = date.today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today - timedelta(days=365 * years)


def emit_progress(percent: int, message: str) -> None:
    safe_print(f"WXPROGRESS:{percent}:{message}", flush=True)


def _coverage_for(obs, start: date, end: date) -> float:
    expected = max((end - start).days + 1, 1) * 24
    return len({o.valid_utc.replace(second=0, microsecond=0) for o in obs}) / expected if expected else 0.0


def resolve_config(args, airport: str):
    cfg = load_runway_config(args.runways, airport)
    runway_report = {"source": "none", "warnings": []}
    if getattr(args, "auto_runways", True):
        try:
            cfg, runway_report = enrich_config_from_ourairports(cfg, Path(args.cache_dir), force=args.force, auto_runways=True)
        except Exception as exc:
            runway_report = {"source": "ourairports", "airportMatched": False, "runwaysMatched": bool(cfg.runways), "warnings": [f"OurAirports resolver failed: {exc}"]}
    elif args.runways:
        runway_report = {"source": "user_yaml", "runwaysMatched": bool(cfg.runways), "runways": [{"id": r.id, "heading": r.heading} for r in cfg.runways], "warnings": []}
    return cfg, runway_report


def _source_attempt(name: str, status: str, records: int = 0, **extra: Any) -> dict[str, Any]:
    d = {"source": name, "status": status, "records": records}
    d.update(extra)
    return d


def build_observations_with_report(args, airport: str, cfg):
    cache_dir = Path(args.cache_dir)
    source = args.source
    attempts: list[dict[str, Any]] = []
    groups = []

    def try_iem(required: bool = False):
        try:
            emit_progress(12, "尝试 IEM ASOS/METAR 数据源")
            rows = iem_download_range(airport, args.start, args.end, cache_dir, force=args.force)
            obs = [normalize_iem(r, cfg.timezone) for r in rows]
            attempts.append(_source_attempt("iem_asos", "ok" if obs else "empty", len(obs), station=airport, match="exact_icao"))
            if obs:
                groups.append(("iem_asos", obs))
            emit_progress(24, f"IEM 完成：{len(obs)} 条观测")
        except Exception as exc:
            attempts.append(_source_attempt("iem_asos", "failed", 0, error=str(exc)))
            if required:
                raise

    def try_noaa(required: bool = False):
        try:
            emit_progress(26, "尝试 NOAA ISD 全球历史数据源")
            resolved = None
            try:
                resolved = resolve_station(airport, args.start, args.end, cache_dir, force=args.force, latitude=cfg.latitude, longitude=cfg.longitude)
            except Exception:
                resolved = None
            rows = noaa_download_range(airport, args.start, args.end, cache_dir, force=args.force, latitude=cfg.latitude, longitude=cfg.longitude)
            obs = [normalize_noaa_isd(r, airport, cfg.timezone) for r in rows]
            station_meta = resolved.to_dict() if resolved else (rows[0].get("resolved_station") if rows else None)
            match = "icao_or_noaa_station_id"
            if station_meta and isinstance(station_meta, dict) and station_meta.get("distance_km") is not None:
                match = "nearest_station_by_coordinates"
            attempts.append(_source_attempt("noaa_isd", "ok" if obs else "empty", len(obs), station=station_meta, match=match))
            if obs:
                groups.append(("noaa_isd", obs))
            emit_progress(52, f"NOAA ISD 完成：{len(obs)} 条观测")
        except NoaaIsdError as exc:
            attempts.append(_source_attempt("noaa_isd", "failed", 0, error=str(exc)))
            if required:
                raise SystemExit(str(exc))
        except Exception as exc:
            attempts.append(_source_attempt("noaa_isd", "failed", 0, error=str(exc)))
            if required:
                raise

    def try_meteostat(required: bool = False):
        try:
            emit_progress(54, "尝试 Meteostat 备用数据源")
            station_meta = find_station_by_icao(airport, cache_dir, force=args.force)
            if not station_meta:
                attempts.append(_source_attempt("meteostat", "no_station_match", 0))
                return
            station_id = station_meta.get("id")
            rows = download_hourly_by_station_id(station_id, args.start, args.end, cache_dir, force=args.force)
            obs = [normalize_meteostat(r, airport, cfg.timezone or station_meta.get("timezone")) for r in rows]
            if not cfg.timezone and station_meta.get("timezone"):
                cfg.timezone = station_meta.get("timezone")
            attempts.append(_source_attempt("meteostat", "ok" if obs else "empty", len(obs), station=station_meta, match="identifier_icao"))
            if obs:
                groups.append(("meteostat", obs))
            emit_progress(66, f"Meteostat 完成：{len(obs)} 条观测")
        except Exception as exc:
            attempts.append(_source_attempt("meteostat", "failed", 0, error=str(exc)))
            if required:
                raise

    if source == "local":
        emit_progress(10, "读取本地 CSV")
        if not args.file:
            raise SystemExit("--source local requires --file path/to/observations.csv")
        rows = read_local_csv(args.file)
        obs = [normalize_local(r, airport, cfg.timezone) for r in rows]
        attempts.append(_source_attempt("local_csv", "ok" if obs else "empty", len(obs), file=args.file))
        groups.append(("local_csv", obs))
        emit_progress(60, f"本地 CSV 完成：{len(obs)} 条观测")
    elif source == "iem":
        try_iem(required=True)
    elif source == "noaa-isd":
        try_noaa(required=True)
    elif source == "meteostat":
        try_meteostat(required=True)
    elif source == "auto":
        # Auto mode is intentionally NOAA-first. IEM is a good METAR source,
        # but it is frequently rate-limited with HTTP 429 when users run long
        # 10/20-year jobs or repeatedly test the UI. Treat IEM as opt-in in
        # automatic workflows so normal users do not see noisy source failures.
        try_noaa()

        high_obs = [o for _, obs in groups for o in obs]
        if getattr(args, "include_iem", False):
            # Optional METAR enrichment. It may fail with 429; if so, NOAA/other
            # sources remain usable and the warning explains the rate limit.
            try_iem()
            high_obs = [o for _, obs in groups for o in obs]

        # Pull Meteostat only when long-history coverage is weak, or when the
        # user explicitly asks to merge all available sources.
        if getattr(args, "merge_all_sources", False) or _coverage_for(high_obs, args.start, args.end) < getattr(args, "fallback_coverage", 0.85):
            try_meteostat()
    else:
        raise SystemExit(f"Unsupported source: {source}")

    if not groups:
        report = {"requestedAirport": airport, "mode": source, "attempts": attempts, "selectedSources": [], "warnings": ["No source returned usable observations."]}
        return [], report, {"strategy": "none", "inputRecords": 0, "outputRecords": 0}

    emit_progress(68, "合并并去重多源观测")
    merged, merge_report = merge_observations(groups)
    selected = sorted({name for name, obs in groups if obs})
    warnings = []
    if source == "auto" and len(selected) > 1:
        warnings.append("Multiple sources were merged and deduplicated by UTC timestamp using source-quality priority.")
    failed = [a for a in attempts if a.get("status") == "failed"]
    if failed:
        if any(a.get("source") == "iem_asos" and "429" in str(a.get("error", "")) for a in failed):
            warnings.append("IEM ASOS/METAR was rate-limited with HTTP 429. NOAA ISD/Meteostat fallback data was used when available. You can leave IEM disabled in auto mode.")
        else:
            warnings.append("At least one source failed. See stationResolution.attempts for details.")
    report = {"requestedAirport": airport, "mode": source, "attempts": attempts, "selectedSources": selected, "warnings": warnings}
    return merged, report, merge_report


def build_observations(args, airport: str, cfg):
    obs, _, _ = build_observations_with_report(args, airport, cfg)
    return obs


def _artifact_paths(out_root: Path, airport: str, start: date, end: date) -> dict[str, Path]:
    period = f"{start.isoformat()}_{end.isoformat()}"
    return {
        "processed_csv": out_root / "processed" / airport / f"{airport}_observations_{period}.csv",
        "profile_json": out_root / "profiles" / airport / f"{airport}_weather_profile_{period}.json",
        "report_md": out_root / "reports" / airport / f"{airport}_weather_report_{period}.md",
        "report_html": out_root / "reports" / airport / f"{airport}_weather_report_{period}.html",
        "report_pdf": out_root / "reports" / airport / f"{airport}_weather_report_{period}.pdf",
        "charts_dir": out_root / "reports" / airport / "charts" / period,
        "tables_dir": out_root / "reports" / airport / "tables" / period,
    }


def command_profile(args) -> dict[str, Any]:
    airport = args.airport.upper()
    emit_progress(3, f"准备 {airport} 配置")
    cfg, runway_report = resolve_config(args, airport)
    obs, station_report, merge_report = build_observations_with_report(args, airport, cfg)
    emit_progress(72, "开始统计天气分布")
    if not obs:
        raise SystemExit(f"No observations found for {airport}")

    out_root = Path(args.out_dir)
    paths = _artifact_paths(out_root, airport, args.start, args.end)

    profile = full_profile(airport, obs, cfg, args.start, args.end, wind_sector_size=args.wind_sector)
    emit_progress(78, "统计 profile 已生成")
    profile["stationResolution"] = station_report
    profile["runwayResolution"] = runway_report
    profile["mergeReport"] = merge_report
    if station_report.get("warnings"):
        profile["quality"].setdefault("warnings", []).extend(station_report["warnings"])
    if runway_report.get("warnings"):
        profile["quality"].setdefault("warnings", []).extend(runway_report["warnings"])

    emit_progress(80, "写入标准化观测 CSV")
    write_observations_csv(obs, paths["processed_csv"])
    emit_progress(84, "写入统计表格")
    table_artifacts = write_stat_tables(profile, paths["tables_dir"])
    chart_artifacts = {}
    if not getattr(args, "no_charts", False):
        try:
            emit_progress(88, "生成图表")
            chart_artifacts = create_all_charts(profile, paths["charts_dir"])
        except Exception as exc:
            safe_print(f"Chart generation skipped/failed: {exc}")
    profile["generatedArtifacts"] = {"tables": table_artifacts, "charts": chart_artifacts}
    emit_progress(92, "写入 JSON profile")
    write_json(profile, paths["profile_json"])
    emit_progress(94, "写入 Markdown 报告")
    write_markdown_report(profile, paths["report_md"])
    if not getattr(args, "no_html", False):
        emit_progress(96, "写入 HTML 报告")
        write_html_report(profile, paths["report_html"])
    if not getattr(args, "no_pdf", False):
        try:
            emit_progress(98, "写入 PDF 报告")
            write_pdf_report(profile, paths["report_pdf"])
        except Exception as exc:
            safe_print(f"PDF generation skipped/failed: {exc}")

    emit_progress(100, "完成")
    safe_print(f"{airport}: {len(obs)} observations")
    safe_print(f"Profile: {paths['profile_json']}")
    safe_print(f"Report:  {paths['report_md']}")
    safe_print(f"HTML:    {paths['report_html']}")
    if not getattr(args, "no_pdf", False):
        safe_print(f"PDF:     {paths['report_pdf']}")
    safe_print(f"CSV:     {paths['processed_csv']}")
    safe_print(f"Tables:  {paths['tables_dir']}")
    if chart_artifacts:
        safe_print(f"Charts:  {paths['charts_dir']}")
    if profile["quality"].get("warnings"):
        safe_print("Warnings:")
        for w in profile["quality"]["warnings"]:
            safe_print(f"- {w}")
    return profile


def command_render(args) -> None:
    profile_path = Path(args.profile_json)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    airport = profile.get("airport", {}).get("icao", profile_path.stem).upper()
    period = f"{profile.get('period', {}).get('start', 'unknown')}_{profile.get('period', {}).get('end', 'unknown')}"
    out_root = Path(args.out_dir) if args.out_dir else profile_path.parent.parent.parent if len(profile_path.parents) >= 3 else Path("data/weather")
    report_md = out_root / "reports" / airport / f"{airport}_weather_report_{period}.md"
    report_html = out_root / "reports" / airport / f"{airport}_weather_report_{period}.html"
    report_pdf = out_root / "reports" / airport / f"{airport}_weather_report_{period}.pdf"
    charts_dir = out_root / "reports" / airport / "charts" / period
    tables_dir = out_root / "reports" / airport / "tables" / period
    table_artifacts = write_stat_tables(profile, tables_dir)
    chart_artifacts = {}
    if not getattr(args, "no_charts", False):
        try:
            emit_progress(88, "生成图表")
            chart_artifacts = create_all_charts(profile, charts_dir)
        except Exception as exc:
            safe_print(f"Chart generation skipped/failed: {exc}")
    profile["generatedArtifacts"] = {"tables": table_artifacts, "charts": chart_artifacts}
    write_markdown_report(profile, report_md)
    if not getattr(args, "no_html", False):
        emit_progress(96, "写入 HTML 报告")
        write_html_report(profile, report_html)
    if not getattr(args, "no_pdf", False):
        try:
            emit_progress(98, "写入 PDF 报告")
            write_pdf_report(profile, report_pdf)
        except Exception as exc:
            safe_print(f"PDF generation skipped/failed: {exc}")
    safe_print(f"Rendered report: {report_md}")
    safe_print(f"HTML report:     {report_html}")
    if not getattr(args, "no_pdf", False):
        safe_print(f"PDF report:      {report_pdf}")
    safe_print(f"Tables:          {tables_dir}")
    if chart_artifacts:
        safe_print(f"Charts:          {charts_dir}")


def command_batch(args) -> None:
    airports = [x.strip().upper() for x in Path(args.airports_file).read_text(encoding="utf-8").splitlines() if x.strip() and not x.strip().startswith("#")]
    profiles = []
    total_airports = max(len(airports), 1)
    for idx, airport in enumerate(airports, start=1):
        emit_progress(int((idx - 1) / total_airports * 90), f"批量处理 {idx}/{total_airports}: {airport}")
        args.airport = airport
        args.runways = None
        safe_print(f"\n=== {airport} ===")
        try:
            profiles.append(command_profile(args))
        except Exception as exc:
            safe_print(f"FAILED {airport}: {exc}")
    emit_progress(92, "生成批量对比报告")
    if profiles and getattr(args, "compare_report", True):
        out = Path(args.out_dir) / "reports" / "batch_compare"
        out.mkdir(parents=True, exist_ok=True)
        write_compare_csv(profiles, out / "batch_compare_summary.csv")
        charts = {} if getattr(args, "no_charts", False) else write_compare_charts(profiles, out / "charts")
        write_compare_html(profiles, out / "batch_compare_report.html", charts)
        safe_print(f"Batch compare CSV:  {out / 'batch_compare_summary.csv'}")
        safe_print(f"Batch compare HTML: {out / 'batch_compare_report.html'}")
    emit_progress(100, "批量完成")


def command_compare(args) -> None:
    profiles = []
    total_airports = max(len(args.airports), 1)
    for idx, airport in enumerate(args.airports, start=1):
        emit_progress(int((idx - 1) / total_airports * 82), f"对比处理 {idx}/{total_airports}: {airport}")
        local_args = argparse.Namespace(**vars(args))
        local_args.airport = airport.upper()
        local_args.runways = None
        cfg, runway_report = resolve_config(local_args, airport.upper())
        obs, station_report, merge_report = build_observations_with_report(local_args, airport.upper(), cfg)
        p = full_profile(airport.upper(), obs, cfg, args.start, args.end, args.wind_sector)
        p["stationResolution"] = station_report
        p["runwayResolution"] = runway_report
        p["mergeReport"] = merge_report
        profiles.append(p)
    safe_name = "compare_" + "_".join(p["airport"]["icao"] for p in profiles)
    out = Path(args.out_dir) / "reports" / safe_name
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "compare_summary.csv"
    html_path = out / "compare_report.html"
    write_compare_csv(profiles, csv_path)
    charts = {} if getattr(args, "no_charts", False) else write_compare_charts(profiles, out / "charts")
    write_compare_html(profiles, html_path, charts)
    safe_print(f"Compare CSV:  {csv_path}")
    safe_print(f"Compare HTML: {html_path}")
    safe_print("airport,samples,coverage,vfr,mvfr,ifr,lifr,snow,rain,fog_mist,gust")
    emit_progress(100, "对比完成")
    for p in profiles:
        o = p["overall"]
        wr = o["weatherRates"]
        safe_print(",".join(map(str, [
            p["airport"]["icao"], p["quality"]["sampleCount"], p["quality"]["coverageRate"],
            o["vfrRate"], o["mvfrRate"], o["ifrRate"], o["lifrRate"],
            wr["snow"], wr["rain"], round(wr.get("fog", 0) + wr.get("mist", 0), 4), o["gustRate"],
        ])))


def add_common(p):
    p.add_argument("--years", type=int, default=10, help="Years back from today. Ignored if --start is provided.")
    p.add_argument("--start", type=parse_date, default=None)
    p.add_argument("--end", type=parse_date, default=date.today())
    p.add_argument("--source", choices=["auto", "iem", "meteostat", "noaa-isd", "local"], default="auto")
    p.add_argument("--file", help="Local CSV input when --source local is used")
    p.add_argument("--runways", help="Airport runway YAML config")
    p.add_argument("--cache-dir", default="data/weather/cache")
    p.add_argument("--out-dir", default="data/weather")
    p.add_argument("--wind-sector", type=int, default=20, choices=[10, 20, 30, 45])
    p.add_argument("--force", action="store_true", help="Force re-download cached source files")
    p.add_argument("--no-charts", action="store_true", help="Skip PNG chart generation")
    p.add_argument("--no-html", action="store_true", help="Skip HTML report generation")
    p.add_argument("--no-pdf", action="store_true", help="Skip PDF report generation")
    p.add_argument("--no-auto-runways", dest="auto_runways", action="store_false", help="Disable OurAirports runway/airport resolver")
    p.add_argument("--merge-all-sources", action="store_true", help="In auto mode, also pull lower-priority fallback sources even when coverage is already strong")
    p.add_argument("--include-iem", action="store_true", help="In auto mode, also try IEM ASOS/METAR. Disabled by default because IEM often returns HTTP 429 rate limits on long jobs.")
    p.add_argument("--fallback-coverage", type=float, default=0.85, help="Auto-mode coverage threshold below which Meteostat fallback is attempted")
    p.set_defaults(auto_runways=True, compare_report=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wxprofiler")
    sub = parser.add_subparsers(dest="command", required=True)

    p_profile = sub.add_parser("profile", help="Build one airport weather profile")
    p_profile.add_argument("airport")
    add_common(p_profile)
    p_profile.set_defaults(func=command_profile)

    p_compare = sub.add_parser("compare", help="Compare multiple airports and write CSV/HTML summary")
    p_compare.add_argument("airports", nargs="+")
    add_common(p_compare)
    p_compare.set_defaults(func=command_compare)

    p_batch = sub.add_parser("batch", help="Build profiles for airport ICAOs listed in a text file")
    p_batch.add_argument("airports_file")
    add_common(p_batch)
    p_batch.set_defaults(func=command_batch)

    p_render = sub.add_parser("render", help="Render charts/tables/report from an existing profile JSON")
    p_render.add_argument("profile_json")
    p_render.add_argument("--out-dir", default="data/weather")
    p_render.add_argument("--no-charts", action="store_true", help="Skip PNG chart generation")
    p_render.add_argument("--no-html", action="store_true", help="Skip HTML report generation")
    p_render.add_argument("--no-pdf", action="store_true", help="Skip PDF report generation")
    p_render.set_defaults(func=command_render)

    args = parser.parse_args(argv)
    if hasattr(args, "start") and args.start is None:
        args.start = default_start(args.years)
    args.func(args)


if __name__ == "__main__":
    main()
