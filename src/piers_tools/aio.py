"""Readers for packeted PIERS++ All-in-One Wind and WX observations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd

_RM_YOUNG_LINE = re.compile(r"^(\d{14})\s+(.*)$")
_WS800_LINE = re.compile(r"^(\d{14}),\s*(.*)$")

RM_YOUNG_PAIR = "rm_young_pair"
RM_YOUNG_AIO_ONLY = "rm_young_aio_only"
LUFFT_WS800_COMPACT = "lufft_ws800_compact"
NO_AIO = "none"


@dataclass(frozen=True)
class ReadStats:
    files: int
    rows: int
    rejected_rows: int
    duplicate_rows: int


def detect_aio_configuration(wind_paths: list[Path], wx_paths: list[Path]) -> str:
    """Identify the instrument arrangement from file presence and WX syntax."""
    if wind_paths and wx_paths:
        return RM_YOUNG_PAIR
    if not wx_paths:
        return NO_AIO
    for path in wx_paths:
        with path.open("r", encoding="ascii", errors="replace") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                if _WS800_LINE.match(text):
                    return LUFFT_WS800_COMPACT
                if _RM_YOUNG_LINE.match(text):
                    return RM_YOUNG_AIO_ONLY
    return RM_YOUNG_AIO_ONLY


def _read_packets(
    paths: list[Path], kind: str, *, configuration: str
) -> tuple[pd.DataFrame, ReadStats]:
    if kind == "wind":
        columns = ["wind_status", "wind_direction_deg", "wind_speed_m_s"]
        expected = 3
    elif kind == "wx":
        columns = ["wx_status", "wx_wind_speed_m_s", "wx_wind_direction_deg",
                   "air_temperature_c", "relative_humidity_pct", "pressure_hpa"]
        expected = 6
    else:
        raise ValueError(f"Unsupported AIO kind: {kind}")

    records: list[dict] = []
    rejected = 0
    for path in paths:
        with path.open("r", encoding="ascii", errors="replace") as handle:
            # Packet files use CR delimiters; splitlines handles CR, LF, and CRLF.
            for line_number, line in enumerate(handle.read().splitlines(), 1):
                pattern = (
                    _WS800_LINE
                    if kind == "wx" and configuration == LUFFT_WS800_COMPACT
                    else _RM_YOUNG_LINE
                )
                match = pattern.match(line.strip())
                if not match:
                    rejected += 1
                    continue
                values = match.group(2).split()
                timestamp = pd.to_datetime(match.group(1), format="%Y%m%d%H%M%S", errors="coerce")
                try:
                    numbers = [float(value) for value in values]
                except ValueError:
                    rejected += 1
                    continue
                if pd.isna(timestamp) or len(numbers) != expected:
                    rejected += 1
                    continue
                row = {"timestamp": timestamp, "source_file": path.name,
                       "source_line": line_number}
                row.update(zip(columns, numbers))
                records.append(row)

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        frame = pd.DataFrame(columns=["timestamp", *columns, "source_file", "source_line"])
        return frame, ReadStats(len(paths), 0, rejected, 0)
    frame = frame.sort_values(["timestamp", "source_file", "source_line"], kind="stable")
    duplicate = frame.duplicated(subset=["timestamp", *columns]).sum()
    frame = frame.drop_duplicates(subset=["timestamp", *columns], keep="first").reset_index(drop=True)
    return frame, ReadStats(len(paths), len(frame), rejected, int(duplicate))


def read_aio_day(wind_paths: list[Path], wx_paths: list[Path], *, tolerance="5s"):
    """Read all packets and nearest-time join Wind to WX without losing either reading."""
    configuration = detect_aio_configuration(wind_paths, wx_paths)
    wind, wind_stats = _read_packets(wind_paths, "wind", configuration=configuration)
    wx, wx_stats = _read_packets(wx_paths, "wx", configuration=configuration)
    if wind.empty or wx.empty:
        combined = pd.DataFrame()
    else:
        wind_for_merge = wind.rename(columns={"timestamp": "wind_timestamp"})
        wx_for_merge = wx.rename(columns={"timestamp": "wx_timestamp"})
        combined = pd.merge_asof(
            wx_for_merge.sort_values("wx_timestamp"), wind_for_merge.sort_values("wind_timestamp"),
            left_on="wx_timestamp", right_on="wind_timestamp",
            tolerance=pd.Timedelta(tolerance), direction="nearest",
            suffixes=("_wx_packet", "_wind_packet"),
        )
        combined["aio_pair_matched"] = combined["wind_speed_m_s"].notna()
        combined["wind_speed_difference_m_s"] = (
            combined["wind_speed_m_s"] - combined["wx_wind_speed_m_s"]
        )
        combined["wind_direction_difference_deg"] = (
            (combined["wind_direction_deg"] - combined["wx_wind_direction_deg"] + 180) % 360 - 180
        )
        combined["pair_time_offset_seconds"] = (
            combined["wind_timestamp"] - combined["wx_timestamp"]
        ).dt.total_seconds()
    return wind, wx, combined, {
        "wind": wind_stats,
        "wx": wx_stats,
        "configuration": configuration,
    }


def _circular_mean_degrees(values: pd.Series) -> float:
    """Mean direction on a circle, avoiding the 359/1 degree arithmetic-mean error."""
    clean = values.dropna().to_numpy(dtype=float)
    if not len(clean):
        return np.nan
    radians = np.deg2rad(clean)
    result = float(np.rad2deg(np.arctan2(np.sin(radians).mean(), np.cos(radians).mean())) % 360)
    return 0.0 if np.isclose(result, 360.0) else result


def aio_one_minute(wind: pd.DataFrame, wx: pd.DataFrame) -> pd.DataFrame:
    """Create outer-joined one-minute averages from independent Wind and WX streams."""
    products = []
    if not wind.empty:
        indexed = wind.set_index("timestamp")
        scalar = indexed[["wind_speed_m_s"]].resample("1min").mean()
        direction = indexed["wind_direction_deg"].resample("1min").apply(_circular_mean_degrees)
        count = indexed["wind_speed_m_s"].resample("1min").count().rename("wind_sample_count")
        products.append(pd.concat([scalar, direction, count], axis=1))
    if not wx.empty:
        indexed = wx.set_index("timestamp")
        scalar_columns = ["wx_wind_speed_m_s", "air_temperature_c", "relative_humidity_pct", "pressure_hpa"]
        scalar = indexed[scalar_columns].resample("1min").mean()
        direction = indexed["wx_wind_direction_deg"].resample("1min").apply(_circular_mean_degrees)
        count = indexed["wx_wind_speed_m_s"].resample("1min").count().rename("wx_sample_count")
        products.append(pd.concat([scalar, direction, count], axis=1))
    if not products:
        return pd.DataFrame(columns=["timestamp"])
    result = pd.concat(products, axis=1, join="outer").sort_index().reset_index()
    return result
