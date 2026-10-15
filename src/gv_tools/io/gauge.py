"""Read PIERS tipping-bucket gauge packets without analyzing or writing them."""

from __future__ import annotations

import csv
import fnmatch
import re
import warnings
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

_STATION = re.compile(r"^Station(?:_|\s+)Name\s*:", re.I)


def _value(line: str, *labels: str) -> str:
    key, separator, value = line.partition(":")
    valid = {label.casefold().replace("_", " ") for label in labels}
    if not separator or key.strip().casefold().replace("_", " ") not in valid:
        raise ValueError(f"invalid metadata line: {line!r}")
    return value.strip()


def _resolve_gauge_files(
    source: str | Path | Sequence[str | Path], gauge_id: str | None
) -> list[Path]:
    items = [source] if isinstance(source, (str, Path)) else list(source)
    if not items:
        raise ValueError("source must contain at least one fully qualified path")
    pattern = f"{gauge_id.strip()}*TB*.csv" if gauge_id else "*TB*.csv"
    found: list[Path] = []
    for item in items:
        path = Path(item).expanduser()
        if not path.is_absolute():
            raise ValueError(f"each input path must be fully qualified: {path}")
        if path.is_file():
            found.append(path.resolve())
        elif path.is_dir():
            found.extend(
                candidate.resolve()
                for candidate in sorted(path.rglob("*.csv"))
                if fnmatch.fnmatch(candidate.name, pattern)
            )
        else:
            raise FileNotFoundError(f"input path does not exist: {path}")
    unique = list(dict.fromkeys(found))
    if not unique:
        raise FileNotFoundError(f"no gauge files matching {pattern!r}")
    daily = [path for path in unique if "_daily." in path.name.casefold()]
    return daily or unique


def _measurement(line: str, source: Path, number: int, station: str):
    try:
        row = [item.strip() for item in next(csv.reader([line], strict=True))]
    except csv.Error as exc:
        return None, f"line {number}: malformed CSV ({exc})"
    padded = (row + [None] * 6)[:6]
    timestamp = pd.to_datetime(
        f"{padded[0]} {padded[1]}", format="%m/%d/%Y %H:%M:%S", errors="coerce"
    )
    value = pd.to_numeric(padded[3], errors="coerce")
    if pd.isna(timestamp) or padded[3] in (None, "") or pd.isna(value):
        return None, f"line {number}: invalid measurement"
    return {
        "timestamp": timestamp,
        "station_name": station,
        "source_file": source.name,
        "source_path": str(source),
        "source_line": number,
        "measurement": padded[2],
        "value": value,
        "unit": padded[4],
        "quality": padded[5],
        "extra_fields": row[6:] or None,
    }, None


def _parse_file(path: Path) -> tuple[list[dict], list[dict]]:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    if not any(line.strip() for line in lines):
        raise ValueError(f"{path.name} is empty")
    station = ""
    latitude = longitude = None
    packet = None
    packet_data: list[dict] = []
    metadata: list[dict] = []
    observations: list[dict] = []
    issues: list[str] = []

    def finish_packet() -> None:
        nonlocal packet, packet_data
        if packet is not None and packet_data:
            packet["timestamp"] = packet_data[0]["timestamp"]
            packet["record_count"] = len(packet_data)
            metadata.append(packet)
            observations.extend(packet_data)
        packet, packet_data = None, []

    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        if _STATION.match(line):
            station = _value(line, "Station Name", "Station_Name")
        elif line.casefold().startswith("latitude/longitude"):
            try:
                latitude, longitude = (
                    float(item.strip()) for item in _value(line, "Latitude/Longitude").split(",")
                )
            except (TypeError, ValueError):
                issues.append(f"line {number}: invalid latitude/longitude")
        elif line.casefold().startswith("rssi"):
            finish_packet()
            packet = {
                "station_name": station,
                "latitude": latitude,
                "longitude": longitude,
                "rssi": pd.to_numeric(_value(line, "RSSI"), errors="coerce"),
                "battery_voltage": float("nan"),
                "source_file": path.name,
                "source_path": str(path),
            }
        elif line.casefold().startswith("battery_voltage") and packet is not None:
            packet["battery_voltage"] = pd.to_numeric(
                _value(line, "Battery_Voltage"), errors="coerce"
            )
        elif packet is not None:
            record, problem = _measurement(line, path, number, station)
            if problem:
                issues.append(problem)
            else:
                packet_data.append(record)
    finish_packet()
    if not metadata:
        raise ValueError(f"{path.name} contains no valid packets")
    if issues:
        warnings.warn(
            f"{path.name} parsed with {len(issues)} issue(s)", RuntimeWarning, stacklevel=2
        )
    return metadata, observations


def read_gauge(
    source: str | Path | Sequence[str | Path],
    *,
    gauge_id: str | None = None,
    measurement: str | None = None,
    start=None,
    end=None,
    return_metadata: bool = False,
):
    """Read gauge packets into a pandas DataFrame without resampling or writing.

    ``source`` may be one full-path filename, a directory, or an explicit
    sequence of files/directories. Optional filters never aggregate the data.
    Set ``return_metadata=True`` to return ``(observations, packet_metadata)``.
    """
    metadata_rows: list[dict] = []
    observations: list[dict] = []
    errors: list[str] = []
    paths = _resolve_gauge_files(source, gauge_id)
    for path in paths:
        try:
            file_metadata, file_observations = _parse_file(path)
            metadata_rows.extend(file_metadata)
            observations.extend(file_observations)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
    if not observations:
        raise ValueError("no input files could be parsed: " + "; ".join(errors))
    if errors:
        warnings.warn("skipped input files: " + "; ".join(errors), RuntimeWarning, stacklevel=2)
    frame = pd.DataFrame(observations).set_index("timestamp").sort_index(kind="stable")
    packet_metadata = pd.DataFrame(metadata_rows).set_index("timestamp").sort_index(kind="stable")
    if measurement is not None:
        frame = frame.loc[frame["measurement"].eq(measurement)]
    if start is not None:
        frame = frame.loc[frame.index >= pd.Timestamp(start)]
    if end is not None:
        frame = frame.loc[frame.index <= pd.Timestamp(end)]
    frame.attrs.update(instrument_type="tipping_bucket_gauge", source_files=[str(p) for p in paths])
    return (frame, packet_metadata) if return_metadata else frame
