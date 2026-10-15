"""Date-range ingestion of PIERS tipping-bucket data to daily NetCDF files."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import xarray as xr


def _as_day(value: str | date | pd.Timestamp, name: str) -> pd.Timestamp:
    try:
        result = pd.Timestamp(value).normalize()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a valid date") from exc
    if result.tz is not None:
        result = result.tz_localize(None)
    return result


def _source_files(input_path: str | Path, gauge_id: str) -> list[Path]:
    source = Path(input_path).expanduser().resolve()
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise FileNotFoundError(f"Input file or directory does not exist: {source}")
    # Recursive discovery supports both a flat collection of daily files and
    # the site/YYYY/MM/DD hierarchy used for 15-minute PIERS packets.
    files = sorted(
        path for path in source.rglob("*.csv")
        if gauge_id.upper() in path.name.upper() and "TB" in path.name.upper()
    )
    if not files:
        raise FileNotFoundError(
            f"No gauge CSV files containing {gauge_id!r} and 'TB' under {source}"
        )
    return files


def ingest_gauge_range(
    input_path: str | Path,
    gauge_id: str,
    start_date: str | date | pd.Timestamp,
    end_date: str | date | pd.Timestamp,
    *,
    output_dir: str | Path = "output",
    network: str = "PIERS",
    accumulation_per_tip: float,
    measurement: str = "TB_A_tips",
    latitude: float | None = None,
    longitude: float | None = None,
) -> list[Path]:
    """Write one 1-minute NetCDF file per day in an inclusive date range.

    ``input_path`` may name one daily CSV or a directory containing daily
    files or multiple packet files. Missing minutes are represented by zero
    tips and zero accumulation. Days having no observations are not written.
    """
    if not str(gauge_id).strip():
        raise ValueError("gauge_id must be non-empty")
    if not str(network).strip():
        raise ValueError("network must be non-empty")
    try:
        tip_amount = float(accumulation_per_tip)
    except (TypeError, ValueError) as exc:
        raise ValueError("accumulation_per_tip must be numeric") from exc
    if not np.isfinite(tip_amount) or tip_amount <= 0:
        raise ValueError("accumulation_per_tip must be positive and finite")
    start = _as_day(start_date, "start_date")
    end = _as_day(end_date, "end_date")
    if end < start:
        raise ValueError("end_date must be on or after start_date")

    from .parsing import parse_one_file
    from .processing import get_bucket_tips

    metadata_rows: list[dict] = []
    observation_rows: list[dict] = []
    errors: list[str] = []
    for path in _source_files(input_path, gauge_id):
        try:
            metadata, observations = parse_one_file(path)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        metadata_rows.append(metadata)
        observation_rows.extend(observations)
    if not metadata_rows:
        raise ValueError("No input files could be parsed: " + "; ".join(errors))
    if errors:
        warnings.warn("Skipped input files: " + "; ".join(errors), RuntimeWarning)

    observations = pd.DataFrame(observation_rows).set_index("timestamp")
    observations = observations.sort_index(kind="stable")
    selected = get_bucket_tips(observations, measurement)
    if selected.empty:
        # Legacy packet writers sometimes used a generic measurement label.
        available = observations["measurement"].dropna().unique().tolist()
        if len(available) == 1:
            selected = get_bucket_tips(observations, str(available[0]))
    if selected.empty:
        raise ValueError(f"No observations found for measurement {measurement!r}")
    selected = selected.loc[~selected.index.duplicated(keep="last")]
    selected = selected[(selected.index >= start) & (selected.index < end + pd.Timedelta(days=1))]
    if selected.empty:
        raise ValueError(f"No observations in requested range {start.date()} through {end.date()}")

    packet_latitudes = {float(row["latitude"]) for row in metadata_rows}
    packet_longitudes = {float(row["longitude"]) for row in metadata_rows}
    if latitude is None:
        if len(packet_latitudes) != 1:
            raise ValueError("Input files contain inconsistent latitudes; specify latitude")
        latitude = packet_latitudes.pop()
    if longitude is None:
        if len(packet_longitudes) != 1:
            raise ValueError("Input files contain inconsistent longitudes; specify longitude")
        longitude = packet_longitudes.pop()

    target = Path(output_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for day in pd.date_range(start, end, freq="D"):
        day_values = selected[(selected.index >= day) & (selected.index < day + pd.Timedelta(days=1))]
        if day_values.empty:
            continue
        minute_index = pd.date_range(day, periods=1440, freq="min")
        counts = day_values["Single_Tip"].resample("1min").sum().reindex(minute_index, fill_value=0)
        counts = counts.astype("int32")
        accumulation = (counts * tip_amount).astype("float32")
        integrated = accumulation.cumsum().astype("float32")
        dataset = xr.Dataset(
            data_vars={
                "number_of_tips": ("DateTime", counts.to_numpy()),
                "one_minute_accumulation": ("DateTime", accumulation.to_numpy()),
                "integrated_rain_accumulation": ("DateTime", integrated.to_numpy()),
            },
            coords={"DateTime": minute_index},
            attrs={
                "Gauge_ID": str(gauge_id).strip(),
                "Network": str(network).strip(),
                "Latitude": float(latitude),
                "Longitude": float(longitude),
                "Accumulation_per_tip": tip_amount,
                "Measurement": measurement,
            },
        )
        dataset["number_of_tips"].attrs.update(long_name="#_of_Tips", units="1")
        dataset["one_minute_accumulation"].attrs.update(
            long_name="1-Minute_Accumulation", units="mm"
        )
        dataset["integrated_rain_accumulation"].attrs.update(
            long_name="Integrated_Rain_Accumulations", units="mm"
        )
        output = target / f"{gauge_id}_{day:%Y%m%d}_gauge_1min.nc"
        dataset.to_netcdf(output)
        written.append(output)
    return written
