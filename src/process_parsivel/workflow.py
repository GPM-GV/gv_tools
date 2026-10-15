"""Notebook- and application-friendly processing workflow."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from .core import discover_input_dates, load_tables, process_input, save_dataframes
from .radar import add_band_reflectivities


def _as_timestamp(value, label):
    if value is None:
        return None
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {label}: {value!r}") from exc
    if pd.isna(timestamp):
        raise ValueError(f"Invalid {label}: {value!r}")
    return timestamp.normalize()


def date_range(input_path, start_date=None, end_date=None):
    """Resolve explicit dates or discover YYYYMMDD dates in input filenames."""
    start = _as_timestamp(start_date, "start_date")
    end = _as_timestamp(end_date, "end_date")
    if start is None:
        if end is not None:
            raise ValueError("end_date requires start_date")
        dates = discover_input_dates(input_path)
        if not dates:
            raise ValueError(
                "No YYYYMMDD date found in input filenames; provide start_date"
            )
        return dates
    end = end or start
    if end < start:
        raise ValueError("end_date must not precede start_date")
    return list(pd.date_range(start, end, freq="D"))


def run(
    input_path,
    instrument,
    *,
    start_date=None,
    end_date=None,
    output_dir=None,
    table_dir=None,
    temp_dir=None,
    radar_bands=None,
    water_temperature=20.0,
    permittivity_model="Liebe1991",
    radar_frequencies=None,
    minimum_dbz=None,
):
    """Process one file or directory without reading command-line arguments.

    Parameters use regular Python values and are safe for Jupyter. Dates may be
    strings (``"2023-01-01"``), ``date``/``datetime`` objects, or pandas
    timestamps. If ``start_date`` is omitted, dates are inferred from filenames.

    Returns a dictionary keyed by ``YYYY-MM-DD``. Each value contains the
    ``(parameters, psd, moments)`` DataFrame tuple. Empty days are omitted.
    """
    results = {}
    diameter_widths = None
    if radar_bands is not None:
        dv_parameters, _ = load_tables(table_dir)
        diameter_widths = dv_parameters["Delta-D"].to_numpy()
    for stamp in date_range(input_path, start_date, end_date):
        year, month, day = stamp.strftime("%Y"), stamp.strftime("%m"), stamp.strftime("%d")
        frames = process_input(
            input_path,
            instrument,
            year,
            month,
            day,
            table_dir=table_dir,
            temp_root=temp_dir,
        )
        parms, psd, moments = frames
        if parms.empty:
            continue
        if radar_bands is not None:
            parms = add_band_reflectivities(
                parms,
                psd,
                bands=radar_bands,
                water_temperature=water_temperature,
                permittivity_model=permittivity_model,
                frequencies=radar_frequencies,
                minimum_dbz=minimum_dbz,
                diameter_widths=diameter_widths,
            )
            frames = parms, psd, moments
        results[stamp.strftime("%Y-%m-%d")] = frames
        if output_dir is not None:
            save_dataframes(
                parms, psd, moments, instrument, year, month, day, output_dir
            )
    return results
