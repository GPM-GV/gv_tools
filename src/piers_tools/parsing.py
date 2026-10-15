"""Read PIERS packet files and concatenated daily gauge files."""
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
    key, sep, value = line.partition(":")
    valid = {x.casefold().replace("_", " ") for x in labels}
    if not sep or key.strip().casefold().replace("_", " ") not in valid:
        raise ValueError(f"Invalid metadata line: {line!r}")
    return value.strip()


def _files(paths: str | Path | Sequence[str | Path], gauge: str | None) -> list[Path]:
    items = [paths] if isinstance(paths, (str, Path)) else list(paths)
    if not items:
        raise ValueError("input_paths must contain at least one path")
    pattern = f"{gauge.strip()}*TB*.csv" if gauge else "*TB*.csv"
    found: list[Path] = []
    for item in items:
        path = Path(item).expanduser().resolve()
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(p for p in path.iterdir() if p.is_file() and fnmatch.fnmatch(p.name, pattern)))
        else:
            raise FileNotFoundError(f"Input file or directory does not exist: {path}")
    found = list(dict.fromkeys(found))
    if not found:
        raise FileNotFoundError(f"No files matching {pattern!r}")
    return found


def _measurement(line: str, source: Path, number: int, station: str):
    try:
        row = [x.strip() for x in next(csv.reader([line], strict=True))]
    except csv.Error as exc:
        return None, f"line {number}: malformed CSV ({exc})"
    padded = (row + [None] * 6)[:6]
    if len(row) < 2:
        return None, f"line {number}: lacks date and time"
    timestamp = pd.to_datetime(f"{padded[0]} {padded[1]}", format="%m/%d/%Y %H:%M:%S", errors="coerce")
    value = pd.to_numeric(padded[3], errors="coerce")
    if pd.isna(timestamp) or padded[3] in (None, "") or pd.isna(value):
        return None, f"line {number}: invalid measurement"
    return {"timestamp": timestamp, "station_name": station, "source_file": source.name,
            "source_path": str(source), "source_line": number, "date": padded[0],
            "time": padded[1], "measurement": padded[2], "value": value,
            "unit": padded[4], "quality": padded[5], "extra_fields": row[6:] or None}, None


def _parse_file(path: Path) -> tuple[list[dict], list[dict]]:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    if not any(x.strip() for x in lines):
        raise ValueError(f"{path.name} is empty")
    station = ""
    latitude = longitude = None
    packet = None
    packet_data: list[dict] = []
    metadata: list[dict] = []
    observations: list[dict] = []
    issues: list[str] = []

    def finish() -> None:
        nonlocal packet, packet_data
        if packet is None:
            return
        if packet_data:
            packet["timestamp"] = packet_data[0]["timestamp"]
            packet["tip_record_count"] = len(packet_data)
            metadata.append(packet)
            observations.extend(packet_data)
        else:
            issues.append(f"packet {packet['packet_number']}: no valid records")
        packet, packet_data = None, []

    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        if _STATION.match(line):
            station = _value(line, "Station Name", "Station_Name")
        elif line.casefold().startswith("latitude/longitude"):
            coords = _value(line, "Latitude/Longitude").split(",")
            try:
                latitude, longitude = (float(x.strip()) for x in coords)
            except (ValueError, TypeError):
                issues.append(f"line {number}: invalid latitude/longitude")
        elif line.casefold().startswith("rssi"):
            finish()
            rssi = pd.to_numeric(_value(line, "RSSI"), errors="coerce")
            packet = {"station_name": station, "latitude": latitude, "longitude": longitude,
                      "rssi": rssi, "battery_voltage": float("nan"), "source_file": path.name,
                      "source_path": str(path), "packet_number": len(metadata) + 1,
                      "rejected_record_count": 0}
        elif line.casefold().startswith("battery_voltage"):
            if packet is None:
                issues.append(f"line {number}: Battery_Voltage precedes RSSI")
            else:
                packet["battery_voltage"] = pd.to_numeric(_value(line, "Battery_Voltage"), errors="coerce")
        elif packet is not None:
            record, problem = _measurement(line, path, number, station)
            if problem:
                packet["rejected_record_count"] += 1
                issues.append(problem)
            else:
                packet_data.append(record)
        else:
            issues.append(f"line {number}: measurement precedes packet metadata")
    finish()
    if not metadata:
        raise ValueError(f"{path.name} contains no valid packets")
    if issues:
        warnings.warn(f"{path.name} parsed with {len(issues)} issue(s): " + "; ".join(issues), RuntimeWarning, stacklevel=2)
    return metadata, observations


def parse_one_file(csv_path: str | Path) -> tuple[dict, list[dict]]:
    """Parse a traditional file containing exactly one packet."""
    path = Path(csv_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Input file does not exist: {path}")
    metadata, observations = _parse_file(path)
    if len(metadata) != 1:
        raise ValueError(f"{path.name} contains {len(metadata)} packets; use parse_piers_files()")
    return metadata[0], observations


def parse_piers_files(input_paths: str | Path | Sequence[str | Path], gauge_name: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse one file, a fully specified file list, or compatible directories.

    One metadata row is produced per RSSI packet header, so ``len(metadata)``
    is the actual packet count for both daily and individual-packet inputs.
    """
    if gauge_name is not None and not gauge_name.strip():
        raise ValueError("gauge_name must be a non-empty string")
    paths = _files(input_paths, gauge_name)
    metadata: list[dict] = []
    observations: list[dict] = []
    errors: list[str] = []
    for path in paths:
        try:
            file_metadata, file_observations = _parse_file(path)
            metadata.extend(file_metadata)
            observations.extend(file_observations)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
    if not metadata:
        raise ValueError(f"None of the {len(paths)} input file(s) could be parsed: " + "; ".join(errors))
    if errors:
        warnings.warn(f"Skipped {len(errors)} file(s): " + "; ".join(errors), RuntimeWarning, stacklevel=2)
    metadata_df = pd.DataFrame(metadata).set_index("timestamp").sort_index(kind="stable")
    metadata_df.index.name = "timestamp"
    observations_df = pd.DataFrame(observations).set_index("timestamp").sort_index(kind="stable")
    observations_df.index.name = "timestamp"
    return metadata_df, observations_df


def parse_piers_multiple_files(input_path, gauge_name: str | None = None):
    """Backward-compatible alias for :func:`parse_piers_files`."""
    return parse_piers_files(input_path, gauge_name)
