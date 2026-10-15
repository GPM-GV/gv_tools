"""Resolve time-varying APU deployment locations."""

from __future__ import annotations

from importlib.resources import files as resource_files
from pathlib import Path
import re

import pandas as pd


REQUIRED_COLUMNS = {
    "instrument",
    "latitude",
    "longitude",
    "elevation",
    "city",
    "state",
    "date_range",
    "num_files",
}
INSTRUMENT_PATTERN = re.compile(r"apu\d{2}", re.IGNORECASE)
DATE_RANGE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+-\s+(\d{4}-\d{2}-\d{2})$")


def _location_resource(instrument: str, location_dir=None):
    filename = f"{instrument}_locations.csv"
    if location_dir is not None:
        resource = Path(location_dir).expanduser() / filename
        return resource, f"external:{resource}"
    resource = resource_files("process_parsivel").joinpath("locations", filename)
    return resource, f"packaged:{filename}"


def load_location_timeline(instrument: str, location_dir=None):
    """Load and validate one APU location timeline."""
    name = str(instrument).lower()
    if not INSTRUMENT_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid APU instrument name: {instrument!r}")
    resource, source = _location_resource(name, location_dir)
    if not resource.is_file():
        return None, source
    try:
        with resource.open("r", encoding="utf-8", newline="") as stream:
            timeline = pd.read_csv(stream)
    except OSError as exc:
        raise RuntimeError(f"Could not read APU location timeline {resource}: {exc}") from exc
    missing = REQUIRED_COLUMNS.difference(timeline.columns)
    if missing:
        raise ValueError(f"Location timeline {resource} is missing columns: {sorted(missing)}")
    if timeline.empty:
        raise ValueError(f"Location timeline is empty: {resource}")
    instruments = timeline["instrument"].astype(str).str.lower()
    if not instruments.eq(name).all():
        found = sorted(instruments.unique())
        raise ValueError(f"Location timeline {resource} contains instruments {found}, expected {name}")
    ranges = timeline["date_range"].astype(str).str.extract(DATE_RANGE_PATTERN)
    if ranges.isna().any(axis=None):
        bad = timeline.loc[ranges.isna().any(axis=1), "date_range"].tolist()
        raise ValueError(f"Invalid date_range values in {resource}: {bad}")
    timeline = timeline.copy()
    timeline["start_date"] = pd.to_datetime(ranges[0], errors="raise").dt.normalize()
    timeline["end_date"] = pd.to_datetime(ranges[1], errors="raise").dt.normalize()
    if (timeline["end_date"] < timeline["start_date"]).any():
        raise ValueError(f"Location timeline has an end before its start: {resource}")
    for column in ("latitude", "longitude", "elevation", "num_files"):
        timeline[column] = pd.to_numeric(timeline[column], errors="raise")
    timeline = timeline.sort_values(["start_date", "end_date"]).reset_index(drop=True)
    return timeline, source


def resolve_location(instrument: str, when, location_dir=None) -> dict[str, object]:
    """Resolve an APU location for a date, retaining match provenance.

    A row becomes effective on its start date and remains current until the
    next row begins. The recorded end date is retained as provenance but does
    not make the location expire. Dates before the first row use the first
    recorded location.
    """
    stamp = pd.Timestamp(when)
    if pd.isna(stamp):
        raise ValueError(f"Invalid location date: {when!r}")
    stamp = stamp.normalize()
    timeline, source = load_location_timeline(instrument, location_dir)
    base = {
        "location_status": "timeline_not_found" if timeline is None else "earliest_recorded_location",
        "location_source": source,
        "location_query_date": stamp.strftime("%Y-%m-%d"),
    }
    if timeline is None:
        return base
    matches = timeline[
        (timeline["start_date"] <= stamp) & (stamp <= timeline["end_date"])
    ]
    if len(matches) > 1:
        ranges = matches["date_range"].tolist()
        raise ValueError(
            f"Overlapping location ranges for {instrument} on {stamp.date()}: {ranges}"
        )
    if len(matches) == 1:
        row = matches.iloc[0]
        status = "matched_date_range"
    else:
        prior = timeline[timeline["start_date"] <= stamp]
        if prior.empty:
            row = timeline.iloc[0]
            status = "earliest_recorded_location"
        else:
            row = prior.iloc[-1]
            status = "latest_recorded_location"
    base.update(
        location_status=status,
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        elevation=float(row["elevation"]),
        city=str(row["city"]),
        state=str(row["state"]),
        location_start_date=row["start_date"].strftime("%Y-%m-%d"),
        location_end_date=row["end_date"].strftime("%Y-%m-%d"),
        location_timeline_num_files=int(row["num_files"]),
    )
    return base
