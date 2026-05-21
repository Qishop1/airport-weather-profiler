from __future__ import annotations

import csv
import io
import time
from datetime import date
from urllib.error import HTTPError, URLError
from pathlib import Path
from urllib.parse import urlencode

from .cache import fetch_text

IEM_ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
IEM_FIELDS = [
    "tmpc", "dwpc", "relh", "drct", "sknt", "gust", "alti", "mslp", "vsby",
    "skyc1", "skyc2", "skyc3", "skyl1", "skyl2", "skyl3", "wxcodes", "metar",
]


IEM_MIN_INTERVAL_SECONDS = 1.35
IEM_RETRY_WAITS_SECONDS = [0.0, 30.0, 60.0, 120.0, 240.0]
_LAST_IEM_REQUEST = 0.0


def _fetch_iem_polite(url: str, path: Path, force: bool = False) -> str:
    """Fetch IEM ASOS text with polite per-IP throttling and retries.

    IEM documents a per-IP throttle. Year-by-year downloads can otherwise
    trigger HTTP 429 when the GUI is tested repeatedly or when a shared office
    / GitHub Actions IP is used. Cache hits do not sleep.

    Polite mode is the default and only downloader path for IEM. It uses a
    conservative delay and exponential-ish backoff so the GUI can safely try
    IEM as an enrichment source without hammering the public archive.
    """
    global _LAST_IEM_REQUEST
    if path.exists() and not force:
        return fetch_text(url, path, force=force)

    waits = IEM_RETRY_WAITS_SECONDS
    last_exc: Exception | None = None
    for attempt, retry_wait in enumerate(waits):
        if retry_wait:
            time.sleep(retry_wait)
        now = time.monotonic()
        gap = now - _LAST_IEM_REQUEST
        if gap < IEM_MIN_INTERVAL_SECONDS:
            time.sleep(IEM_MIN_INTERVAL_SECONDS - gap)
        _LAST_IEM_REQUEST = time.monotonic()
        try:
            return fetch_text(url, path, force=force)
        except HTTPError as exc:
            last_exc = exc
            if exc.code not in (429, 503, 500, 502, 504):
                raise
        except URLError as exc:
            last_exc = exc
    if last_exc:
        raise last_exc
    return fetch_text(url, path, force=force)


def download_year(station: str, year: int, start: date, end: date, cache_dir: Path, force: bool = False) -> list[dict[str, str]]:
    station = station.upper()
    y_start = max(start, date(year, 1, 1))
    y_end = min(end, date(year, 12, 31))
    params = {
        "station": station,
        "data": IEM_FIELDS,
        "year1": y_start.year,
        "month1": y_start.month,
        "day1": y_start.day,
        "year2": y_end.year,
        "month2": y_end.month,
        "day2": y_end.day,
        "tz": "Etc/UTC",
        "format": "onlycomma",
        "latlon": "yes",
        "elev": "yes",
        "missing": "empty",
        "trace": "empty",
        "direct": "yes",
        "report_type": ["1", "2", "3", "4"],
    }
    url = f"{IEM_ASOS_URL}?{urlencode(params, doseq=True)}"
    path = cache_dir / "iem_asos" / station / f"{station}_{year}.csv"
    text = _fetch_iem_polite(url, path, force=force)
    rows = []
    clean_lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if not clean_lines:
        return rows
    reader = csv.DictReader(io.StringIO("\n".join(clean_lines)))
    for row in reader:
        if row.get("valid"):
            row["_source"] = "iem_asos"
            rows.append(row)
    return rows


def download_range(station: str, start: date, end: date, cache_dir: Path, force: bool = False) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for year in range(start.year, end.year + 1):
        rows.extend(download_year(station, year, start, end, cache_dir, force=force))
    return rows
