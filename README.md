# Universal Airport Weather Profiler

Universal Airport Weather Profiler is a desktop and CLI tool for generating long-term airport weather statistics from historical aviation weather observations.

It is designed for ATC simulator development, airport climatology, runway-use modeling, weather-risk analysis, and simulator-ready weather profile generation. It is not tied to RJCC/RJCJ; those are only examples.

The tool can produce:

- wind rose charts
- monthly flight-category statistics
- visibility and ceiling risk statistics
- runway crosswind / tailwind statistics
- operational weather-risk summaries
- HTML / PDF reports
- CSV statistical tables
- simulator-ready JSON weather profiles

## Recommended usage

Most users should use the Windows GUI.

The GUI supports:

- single-airport weather profiling
- multi-airport comparison
- batch report generation
- automatic NOAA ISD source selection
- optional IEM/METAR enrichment
- automatic runway database lookup
- chart preview
- HTML/PDF report opening
- progress display
- canceling long-running jobs
- Chinese / English UI language switching

If you are using the packaged Windows version, no Python installation is required.

## Windows portable EXE

The intended non-developer build is:

```text
AirportWeatherProfiler.exe
```

The portable EXE does not require:

```text
Python
pip
administrator rights
system PATH changes
```

If the EXE is generated through GitHub Actions, download the artifact named:

```text
AirportWeatherProfiler-Windows-Portable
```

Then unzip it and run:

```text
AirportWeatherProfiler.exe
```

## Building the Windows EXE with GitHub Actions

This repository includes a GitHub Actions workflow for building the Windows portable version.

After uploading the repository to GitHub:

1. Open the repository page.
2. Open the `Actions` tab.
3. Select `Build Windows EXE`.
4. Click `Run workflow`.
5. Wait for the build to finish.
6. Download the artifact `AirportWeatherProfiler-Windows-Portable`.

The workflow file is located at:

```text
.github/workflows/build-windows-exe.yml
```

## Data source strategy

The profiler uses source adapters. Every source is normalized into one internal observation table before analysis.

Default `auto` mode is intentionally NOAA-first:

```text
NOAA ISD -> Meteostat fallback
```

IEM is no longer attempted by default because long-range queries are frequently rate-limited with HTTP 429. IEM remains available as a manual optional METAR enrichment source.

Currently implemented sources:

- `noaa-isd`: NOAA Integrated Surface Database / Global Hourly. This is the default global long-term source. It supports ICAO/CALL to USAF-WBAN station resolution, annual gzip download, fixed-width mandatory-section parsing, visibility, ceiling, wind, temperature, dewpoint, sea-level pressure, and coarse optional weather-code extraction.
- `meteostat`: Meteostat bulk hourly data. Useful as a global fallback, but not as METAR-rich as NOAA ISD or IEM.
- `iem`: Iowa Environmental Mesonet ASOS/METAR archive. Useful for METAR-native airport statistics, but disabled by default in auto mode because of frequent rate limiting on large historical requests.
- `local`: User-supplied CSV import.

The station/fallback process is written into the JSON profile under:

```text
stationResolution
```

The merge and deduplication process is written under:

```text
mergeReport
```


### IEM polite mode

IEM is always accessed through polite mode when it is enabled. The downloader waits at least 1.35 seconds between uncached IEM requests and retries rate-limited responses with 30 / 60 / 120 / 240 second backoff. This is intentional because IEM applies per-IP throttling and shared office/GitHub IPs can trigger HTTP 429.

IEM is still not enabled by default in `auto` mode. The normal default remains NOAA ISD first. Enable IEM only when you want METAR-native enrichment or when you choose the `iem` source directly.

## Why not Aviation Weather Center API?

Aviation Weather Center data is good for live or recent aviation weather. It is not the correct source for 10-year or 20-year climatological airport profiles because its public weather database access is short-range, not a long-term archive.

## Operational statistics philosophy

The profiler uses operational aviation-weather statistics rather than simple weather-site summaries.

Some fields should not be summarized by median.

For example, METAR visibility is often capped at `9999`, meaning 10 km or more. A median visibility of `9999` is usually not useful because it hides low-visibility risk. The profiler therefore reports visibility as threshold rates and bucket distributions instead of treating median visibility as a primary result.

The same logic applies to ceiling and weather phenomena. The report emphasizes threshold risk:

```text
VIS >= 10 km
VIS < 5000 m
VIS < 3000 m
VIS < 1600 m
VIS < 800 m
VIS < 550 m

CIG < 3000 ft
CIG < 1000 ft
CIG < 500 ft
CIG < 200 ft
```

The monthly operating summary is built around runway and ATC-relevant risk:

```text
VFR
MVFR
IFR
LIFR
10km+ visibility rate
low-visibility rate
low-ceiling rate
snow / rain / fog / mist rate
wind risk
runway crosswind / tailwind risk
```

## GUI behavior

The desktop GUI supports Chinese / English interface switching and launches long-running profile jobs in a separate backend process.

This allows the UI to:

- remain responsive
- show phase progress
- stream backend logs
- cancel the current job

Canceling a job stops the backend process. Already completed cache files, partial reports, or partial downloaded data may remain on disk. Re-run the profile to regenerate outputs. If a cache file appears corrupted, enable force re-download in the GUI advanced settings.

## Run from source

Developer/source usage requires Python.

From the repository root:

```powershell
python -m wxprofiler.cli profile RJCC --years 10
```

Open the GUI from source:

```powershell
python -m wxprofiler.gui
```

Or run the Windows launcher:

```text
run_gui.bat
```

Install in editable mode:

```powershell
pip install -e .
```

Then run:

```powershell
wxprofiler profile RJCC --years 10
```

## CLI examples

Build a ten-year RJCC profile using default NOAA-first auto mode:

```powershell
python -m wxprofiler.cli profile RJCC --years 10
```

Build a twenty-year KLAX profile:

```powershell
python -m wxprofiler.cli profile KLAX --years 20
```

Use NOAA ISD only:

```powershell
python -m wxprofiler.cli profile RJCC --years 20 --source noaa-isd
```

Use Meteostat only:

```powershell
python -m wxprofiler.cli profile EDDF --years 20 --source meteostat
```

Try IEM manually:

```powershell
python -m wxprofiler.cli profile RJCC --years 10 --source iem
```

Use auto mode with optional IEM enrichment:

```powershell
python -m wxprofiler.cli profile RJCC --years 10 --include-iem
```

Use a local CSV:

```powershell
python -m wxprofiler.cli profile RJCC --source local --file my_rjcc_metar.csv
```

Compare airports:

```powershell
python -m wxprofiler.cli compare RJCC RJTT RJOO --years 10
```

Batch mode:

```powershell
python -m wxprofiler.cli batch airports.txt --years 10
```

Regenerate charts and tables from an existing JSON profile without re-downloading weather data:

```powershell
python -m wxprofiler.cli render data/weather/profiles/RJCC/RJCC_weather_profile_2016-01-01_2026-01-01.json
```

## Runway data

If no runway YAML is supplied, the tool tries to resolve airport and runway information from the built-in / downloaded airport database.

Automatic runway lookup is useful for broad analysis. For high-fidelity runway wind-component analysis, a hand-checked runway YAML is still preferred.

Runway headings derived from runway identifiers are treated as operational magnetic runway headings when possible. Published database headings may be true headings, so the report records runway-resolution warnings when applicable.

Example runway config:

```yaml
airport: RJCC
timezone: Asia/Tokyo
latitude: 42.7752
longitude: 141.6923
elevation_m: 25
runways:
  - id: 01L
    heading: 10
  - id: 19R
    heading: 190
  - id: 01R
    heading: 10
  - id: 19L
    heading: 190
```

Use a runway config:

```powershell
python -m wxprofiler.cli profile RJCC --years 10 --runways configs/RJCC.yaml
```

Disable automatic runway lookup:

```powershell
python -m wxprofiler.cli profile RJCC --years 10 --no-auto-runways
```

## Outputs

By default, output is written under:

```text
data/weather/cache/       downloaded source files
data/weather/processed/   normalized observation CSV
data/weather/profiles/    universal JSON weather profile
data/weather/reports/     Markdown / HTML / PDF reports, charts, and tables
```

Single-airport profile outputs include:

```text
data/weather/profiles/<ICAO>/<ICAO>_weather_profile_<period>.json
data/weather/reports/<ICAO>/<ICAO>_weather_report_<period>.md
data/weather/reports/<ICAO>/<ICAO>_weather_report_<period>.html
data/weather/reports/<ICAO>/<ICAO>_weather_report_<period>.pdf
data/weather/reports/<ICAO>/charts/<period>/
data/weather/reports/<ICAO>/tables/<period>/
```

Chart outputs include:

```text
<ICAO>_wind_rose.png
<ICAO>_monthly_flight_category.png
<ICAO>_monthly_weather_rates.png
<ICAO>_hourly_operational_risk.png
<ICAO>_visibility_buckets.png
<ICAO>_ceiling_buckets.png
<ICAO>_wind_speed_buckets.png
<ICAO>_runway_operational_risks.png
```

Table outputs include:

```text
monthly_summary.csv
hourly_local_summary.csv
wind_rose_table.csv
bucket_distributions.csv
runway_operational_stats.csv
weather_archetypes.csv
```

## JSON profile contents

The JSON profile contains:

- airport summary
- station/source resolution report
- runway resolution report
- merge/deduplication report
- data quality report
- overall VFR/MVFR/IFR/LIFR rates
- monthly operating statistics
- local-hour statistics
- wind sectors
- visibility threshold rates
- visibility buckets
- ceiling threshold rates
- ceiling buckets
- weather-code rates
- rain/snow/fog/mist/thunder/freezing/blowing-snow rates
- gust availability and gust-risk notes
- runway crosswind/tailwind statistics if runway headings are available
- seasonal weather archetypes
- simulator-oriented monthly weather weights

## Data quality metrics

The profiler reports both unique-hour coverage and record density.

This avoids misleading coverage numbers when a source contains multiple observations in the same hour.

Important quality fields include:

```text
uniqueHourCoverageRate
recordDensityPerObservedHour
sampleCount
missingMonths
partialMonths
sourceWarnings
```

If a source provides no reliable gust field, the report should treat gust as unavailable rather than reporting `0.0%`.

## Local CSV input

A local CSV can use either normalized field names or common IEM-style field names.

Useful columns include:

```text
station
valid_utc
valid
raw_metar
metar
wind_dir_deg
drct
wind_speed_kt
sknt
wind_gust_kt
gust
visibility_m
vsby
temperature_c
tmpc
dewpoint_c
dwpc
relative_humidity
relh
ceiling_ft
wx_tokens
wxcodes
cloud_1_cover
cloud_1_base_ft
```

## Compare and batch reports

Compare mode writes CSV, HTML, and comparison charts:

```powershell
python -m wxprofiler.cli compare RJCC RJTT RJOO --years 10
```

Batch mode creates individual profiles and then a batch comparison report:

```powershell
python -m wxprofiler.cli batch airports.txt --years 10
```


### Gust statistics are all-observation probabilities

Gust is handled carefully because METAR/ASOS gust fields are event-style fields: a gust value is normally present only when a gust is explicitly reported. The profiler therefore exports both all-observation and conditional rates:

- `gustReportedRate` / `gustDataAvailableRate`: share of all observations where a gust field exists.
- `gustOver20ktObservedRate`: share of all observations where reported gust is greater than 20 kt. This is the correct simulator risk value.
- `gustOver20ktConditionalRate`: share of reported-gust observations where gust is greater than 20 kt. This is only a diagnostic subset metric and should not be used as the simulator weather probability.

The GUI, HTML, PDF, CSV tables, comparison reports, and `simulatorProfile.gustRisk` use the all-observation observed rate. Older builds used the conditional rate in some places; this was misleading and has been corrected.

## Notes and limitations

- NOAA ISD is the default long-term source because it has broad global historical coverage.
- NOAA ISD is strong for wind, visibility, ceiling, temperature, pressure, and long-term hourly observations.
- NOAA ISD present-weather extraction is coarser than raw METAR and depends on optional ISD groups.
- IEM is useful for METAR-native reports but may be rate-limited on long-range requests.
- Meteostat is useful as a fallback but is not full raw METAR.
- Automatic runway lookup is useful for broad analysis, but hand-checked runway YAML remains preferred for high-fidelity runway-component analysis.
- The profiler is a statistical tool. Always review `stationResolution`, `runwayResolution`, `mergeReport`, and quality warnings before using a profile as simulator truth.

## Relationship to ATC Radar Simulator

This tool is intended as a companion data-generation utility for 
[ATC Radar Simulator](https://github.com/Qishop1/atc-radar-sim).

The simulator should not download 10-year or 20-year historical weather data at runtime. Instead:

```text
Airport Weather Profiler
        -> generates weather_profile.json
        -> imported into an airport data pack
        -> used by the simulator weather engine
```

This keeps historical data processing separate from the runtime simulator.
