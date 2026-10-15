"""Compare standalone tip increments with PIERS wind on a minute grid.

This module preserves the scientifically important behavior of the former
``comp_standalone_gauges`` distribution while placing it in the unified
``piers_tools`` namespace. Missing observations remain missing: the routines
never interpolate rainfall or wind measurements.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re

import numpy as np
import pandas as pd

from . import __version__


def circular_mean(values):
    """Unweighted circular mean; an undefined resultant returns NaN."""
    radians = np.deg2rad(pd.Series(values).dropna().to_numpy(dtype=float))
    if not len(radians):
        return np.nan
    sine, cosine = np.sin(radians).mean(), np.cos(radians).mean()
    if np.hypot(sine, cosine) < 1e-12:
        return np.nan
    result = float(np.degrees(np.arctan2(sine, cosine)) % 360)
    return 0.0 if np.isclose(result, 360) else result


def _provenance(path: Path) -> dict[str, str]:
    """Return the source path and digest used for reproducibility records."""
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class InputDataError(ValueError):
    """An existing instrument file cannot be read as valid observations."""


def read_standalone(path, date, site="WFFpad", gauges=None):
    """Read rain observations, reporting unusable input with its full path."""
    try:
        return _read_standalone(path, date, site, gauges)
    except (ValueError, IndexError, StopIteration, UnicodeError) as exc:
        raise InputDataError(f"{Path(path)}: {str(exc) or 'incomplete header'}") from exc


def _read_standalone(path, date, site="WFFpad", gauges=None):
    """Sum tip increments; require 60 valid seconds for a complete minute."""
    path = Path(path)
    with path.open() as stream:
        header = [stream.readline().strip() for _ in range(3)]
    if not all(header):
        raise ValueError("empty or truncated file: expected calibration, coordinates, and CSV header")
    calibration, coordinate_line, csv_header = header
    if not coordinate_line.startswith("LAT/LON:") or not csv_header.startswith("TIMESTAMP,"):
        raise ValueError("invalid coordinates or CSV header")
    match = re.fullmatch(r"AMOUNT_OF_RAIN_PER_TIP:\s*([\d.]+)\s+inch", calibration)
    if not match or float(match[1]) <= 0:
        raise ValueError(f"Unsupported calibration: {calibration}")
    scale = float(match[1])
    raw_observations_df = pd.read_csv(path, skiprows=2, na_values=["NAN"], parse_dates=["TIMESTAMP"]).set_index("TIMESTAMP")
    if raw_observations_df.empty:
        raise ValueError("header-only file: no observations")
    all_gauges = list(raw_observations_df.columns)
    coords = [float(x) for x in coordinate_line.split(":", 1)[1].split(",")]
    if len(coords) != 2 * len(all_gauges):
        raise ValueError("Coordinate count does not match gauge columns")
    day = pd.Timestamp(date).normalize()
    if raw_observations_df.index.hasnans or not raw_observations_df.index.is_unique:
        raise ValueError("Standalone timestamps must be valid and unique")
    raw_observations_df = raw_observations_df.loc[(raw_observations_df.index >= day) & (raw_observations_df.index < day + pd.Timedelta(days=1))]
    seconds = pd.date_range(day, periods=86400, freq="s")
    if not raw_observations_df.index.isin(seconds).all():
        raise ValueError("Standalone timestamps must fall on whole seconds")
    raw_observations_df = raw_observations_df.loc[:, all_gauges if gauges is None else list(gauges)].apply(pd.to_numeric, errors="raise")
    if ((raw_observations_df < 0) | (raw_observations_df % 1 != 0) & raw_observations_df.notna()).any().any():
        raise ValueError("Standalone values must be nonnegative integer tip increments")
    aligned_observations_df = raw_observations_df.reindex(seconds)
    sample_counts_df = aligned_observations_df.resample("1min").count()
    rainfall_df = aligned_observations_df.resample("1min").sum(min_count=60) * scale
    names = {g: f"{site}__{g}__rain_in" for g in rainfall_df}
    rainfall_df = rainfall_df.rename(columns=names)
    sample_counts_df = sample_counts_df.rename(columns=names)
    meta = {**_provenance(path), "rain_per_tip_in": scale, "source_rows_in_day": len(raw_observations_df),
            "coordinates": {names[g]: {"latitude": coords[all_gauges.index(g)], "longitude": coords[all_gauges.index(g) + len(all_gauges)]} for g in raw_observations_df}}
    return rainfall_df, sample_counts_df, meta


def read_wind(path, date, station):
    """Read PIERS++ status/direction/speed packets, reporting corrupt rows."""
    path = Path(path)
    records, rejected, outside = [], 0, 0
    day = pd.Timestamp(date).normalize()
    lines = path.read_text(encoding="ascii", errors="replace").splitlines()
    for line in lines:
        fields = line.split()
        try:
            if len(fields) != 4 or not re.fullmatch(r"\d{14}", fields[0]):
                raise ValueError()
            timestamp = pd.to_datetime(fields[0], format="%Y%m%d%H%M%S")
            status, direction, speed = map(float, fields[1:])
            if not np.isfinite([status, direction, speed]).all() or not 0 <= direction <= 360 or speed < 0:
                raise ValueError()
        except (ValueError, OverflowError):
            rejected += 1
            continue
        if not day <= timestamp < day + pd.Timedelta(days=1):
            outside += 1
            continue
        records.append((timestamp, status, direction % 360, speed))
    raw_observations_df = pd.DataFrame(records, columns=["TIMESTAMP", "status", "direction", "speed"])
    duplicates = int(raw_observations_df.duplicated().sum())
    raw_observations_df = raw_observations_df.drop_duplicates()
    if raw_observations_df.TIMESTAMP.duplicated().any():
        raise ValueError(f"Conflicting wind packets at identical timestamps: {path}")
    status_counts = {str(k): int(v) for k, v in raw_observations_df.status.value_counts().items()}
    raw_observations_df = raw_observations_df.set_index("TIMESTAMP").sort_index()
    raw_observations_df.index = pd.DatetimeIndex(raw_observations_df.index)
    grid = pd.date_range(day, periods=1440, freq="min")
    speed_name, direction_name = f"{station}__wind_speed_m_s", f"{station}__wind_direction_deg"
    minute_wind_df = pd.DataFrame({speed_name: raw_observations_df.speed.resample("1min").mean(), direction_name: raw_observations_df.direction.resample("1min").apply(circular_mean)}).reindex(grid)
    wind_sample_counts = raw_observations_df.speed.resample("1min").count().reindex(grid, fill_value=0)
    sample_coverage_df = pd.DataFrame({speed_name: wind_sample_counts, direction_name: wind_sample_counts})
    meta = {**_provenance(path), "lines": len(lines), "valid_packets": len(raw_observations_df), "rejected_lines": rejected,
            "duplicate_packets_removed": duplicates, "out_of_day_packets": outside, "status_counts": status_counts,
            "status_policy": "Numeric status retained in diagnostics; no undocumented status-code filtering (PIERS++ convention)"}
    return minute_wind_df, sample_coverage_df, meta


def load_day(date="2026-07-22", root="/Volumes/TBW/distro", site="WFFpad", stations=("PIERS0027", "PIERS0028"), gauges=None):
    """Return 1440 rows with instrument-qualified rain (inch), speed (m/s), direction (degrees).

    Missing files raise FileNotFoundError. Missing observations remain NaN.
    Timestamp labels are minute starts; timezone is unchanged from the input files.
    """
    day, root = pd.Timestamp(date).normalize(), Path(root).expanduser()
    if day.tzinfo is not None:
        raise ValueError("Use a date without a timezone; input timezone is unspecified")
    if len(set(stations)) != len(stations):
        raise ValueError("Station identifiers must be unique")
    gauge_path = root / f"standalone/{site}/{day:%Y/%m}/Standalone_TB_{day:%Y_%m%d}.dat"
    rainfall_df, sample_coverage_df, gauge_meta = read_standalone(gauge_path, day, site, gauges)
    frames, coverages, sources = [rainfall_df], [sample_coverage_df], {site: gauge_meta}
    for station in stations:
        path = root / f"PIERS_Gauges_Daily/{station}/{day:%Y/%m/%d}/{station}_wind_{day:%Y%m%d}_daily.csv"
        wind_df, sample_counts_df, meta = read_wind(path, day, station)
        frames.append(wind_df)
        coverages.append(sample_counts_df)
        sources[station] = meta
    daily_comparison_df = pd.concat(frames, axis=1).reindex(pd.date_range(day, periods=1440, freq="min", name="TIMESTAMP"))
    sample_counts_df = pd.concat(coverages, axis=1)
    daily_comparison_df.attrs = {"package_version": __version__, "date": str(day.date()), "sources": sources,
                "timezone": "Unspecified; source timestamps preserved", "minute_intervals": "[timestamp, timestamp + 1 minute)",
                "rain_method": "Sum per-second tip increments times header calibration; fewer than 60 valid seconds gives NaN",
                "wind_method": "Arithmetic speed mean, unweighted circular direction mean; at least one valid packet; no interpolation",
                "valid_sample_counts": {c: [int(x) for x in sample_counts_df[c]] for c in sample_counts_df},
                "nan_minutes": {c: int(x) for c, x in daily_comparison_df.isna().sum().items()}}
    return daily_comparison_df


def event_totals(daily_comparison_df, start=None, end=None):
    """Observed rainfall sums and completeness for an inclusive selection of minute labels."""
    rainfall_df = daily_comparison_df.loc[start:end, daily_comparison_df.columns.str.endswith("__rain_in")]
    return pd.DataFrame({"observed_rain_in": rainfall_df.sum(min_count=1), "valid_minutes": rainfall_df.count(),
                         "missing_minutes": rainfall_df.isna().sum(), "complete": rainfall_df.notna().all() & (len(rainfall_df) > 0)})


def save_day(daily_comparison_df, output_dir):
    """Write exactly one CSV containing the daily DataFrame."""
    out = Path(output_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    base = out / f"merged_{daily_comparison_df.attrs['date']}"
    daily_comparison_df.to_csv(base.with_suffix(".csv"), na_rep="NaN")
    return base


def process_range(start_date, end_date, output_dir, *, output_mode="merged",
                  root="/Volumes/TBW/distro", site="WFFpad",
                  stations=("PIERS0027", "PIERS0028"), gauges=None):
    """Process an inclusive range and save one merged CSV or one CSV per day.

    All requested minutes remain in the result. Unavailable instruments are NaN;
    valid collocated instruments are retained. Diagnostics stay in attrs/in memory.
    """
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    if (pd.isna(start) or pd.isna(end) or start.tzinfo is not None or end.tzinfo is not None
            or start != start.normalize() or end != end.normalize() or start > end):
        raise ValueError("Use date-only endpoints with start_date <= end_date")
    if output_mode not in {"merged", "daily"}:
        raise ValueError("output_mode must be merged or daily")
    if len(set(stations)) != len(stations):
        raise ValueError("Station identifiers must be unique")
    root, output_dir = Path(root).expanduser(), Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    daily_frames, diagnostics = [], []
    gauge_columns = list(gauges) if gauges is not None else None
    for day in pd.date_range(start, end, freq="D"):
        day_index = pd.date_range(day, periods=1440, freq="min", name="TIMESTAMP")
        instrument_frames = []
        gauge_path = root / f"standalone/{site}/{day:%Y/%m}/Standalone_TB_{day:%Y_%m%d}.dat"
        try:
            rainfall_df, _, metadata = read_standalone(gauge_path, day, site, gauges)
            if gauge_columns is None:
                gauge_columns = [c.split("__")[1] for c in rainfall_df.columns]
            instrument_frames.append(rainfall_df)
            diagnostics.append({"date": str(day.date()), "instrument": site, "status": "loaded", "detail": str(gauge_path)})
        except (FileNotFoundError, InputDataError) as exc:
            diagnostics.append({"date": str(day.date()), "instrument": site, "status": "unavailable", "detail": str(exc)})
        for station in stations:
            path = root / f"PIERS_Gauges_Daily/{station}/{day:%Y/%m/%d}/{station}_wind_{day:%Y%m%d}_daily.csv"
            try:
                wind_df, _, metadata = read_wind(path, day, station)
                instrument_frames.append(wind_df)
                diagnostics.append({"date": str(day.date()), "instrument": station, "status": "loaded", "detail": str(path)})
            except FileNotFoundError as exc:
                diagnostics.append({"date": str(day.date()), "instrument": station, "status": "unavailable", "detail": str(exc)})
        daily_comparison_df = (pd.concat(instrument_frames, axis=1).reindex(day_index)
                               if instrument_frames else pd.DataFrame(index=day_index))
        daily_frames.append(daily_comparison_df)
        print(f"{day:%Y-%m-%d}: processed", flush=True)
    if gauge_columns is None:
        raise InputDataError("No readable standalone gauge header in the requested range; specify gauges to retain an all-NaN rain schema")
    columns = [f"{site}__{g}__rain_in" for g in gauge_columns]
    columns += [f"{station}__{field}" for station in stations for field in ("wind_speed_m_s", "wind_direction_deg")]
    date_range_comparison_df = pd.concat(daily_frames).reindex(columns=columns)
    date_range_comparison_df.attrs = {"start_date": str(start.date()), "end_date": str(end.date()),
                                     "processing_summary": diagnostics, "timezone": "Unspecified; source timestamps preserved"}
    if output_mode == "merged":
        output_path = output_dir / f"comparison_{start:%Y-%m-%d}_{end:%Y-%m-%d}.csv"
        date_range_comparison_df.to_csv(output_path, na_rep="NaN")
    else:
        for day, daily_comparison_df in date_range_comparison_df.groupby(date_range_comparison_df.index.normalize()):
            daily_comparison_df.to_csv(output_dir / f"comparison_{day:%Y-%m-%d}.csv", na_rep="NaN")
    return date_range_comparison_df


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-07-22")
    parser.add_argument("--root", default="/Volumes/TBW/distro")
    parser.add_argument("--site", default="WFFpad")
    parser.add_argument("--stations", nargs="*", default=["PIERS0027", "PIERS0028"])
    parser.add_argument("--gauges", nargs="+")
    parser.add_argument("--output-dir", default="outputs/daily")
    args = parser.parse_args()
    daily_comparison_df = load_day(args.date, args.root, args.site, args.stations, args.gauges)
    save_day(daily_comparison_df, args.output_dir)
    print(f"Saved {daily_comparison_df.shape[0]} rows x {daily_comparison_df.shape[1]} columns to {args.output_dir}")
    print(event_totals(daily_comparison_df).to_string())
