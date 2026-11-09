"""Reader and GV adapter for PIERS RM Young All-in-One weather packets."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import xarray as xr

from .base import InstrumentAdapter, localize_to_utc
from ..metadata import InstrumentMetadata
from ..products import validate_product
from .. import __version__

_PACKET_LINE = re.compile(r"^(\d{14})(?:,|\s)+(.*)$")
_VARIABLES = (
    "status_code",
    "wind_speed",
    "wind_from_direction",
    "air_temperature",
    "relative_humidity",
    "air_pressure",
)
_VARIABLE_METADATA = {
    "status_code": ("1", "RM Young AIO status code"),
    "wind_speed": ("m s-1", "Wind speed"),
    "wind_from_direction": ("degree", "Meteorological wind direction"),
    "air_temperature": ("degree_Celsius", "Air temperature"),
    "relative_humidity": ("percent", "Relative humidity"),
    "air_pressure": ("hPa", "Atmospheric pressure"),
}


@dataclass(frozen=True)
class RawRMYoungAIOProduct:
    """Decoded observations and source-accounting information for one UTC day."""

    observations: pd.DataFrame
    source_files: tuple[str, ...]
    rejected_rows: int = 0
    duplicate_rows: int = 0


class RMYoungAIOAdapter(InstrumentAdapter):
    """Read the six-field RM Young AIO ``PIERS####_WX_*.csv`` stream."""

    name = "rm_young_aio"

    def __init__(self, metadata: InstrumentMetadata) -> None:
        super().__init__(metadata)
        if not metadata.instrument_id.strip().lower().startswith("piers"):
            raise ValueError("RM Young AIO instrument_id must begin with 'PIERS'")

    def _matches(self, path: Path) -> bool:
        prefix = re.escape(self.metadata.instrument_id)
        return bool(re.match(
            rf"^{prefix}_WX_(?:\d{{14}}|\d{{8}}_daily)\.csv$",
            path.name,
            re.IGNORECASE,
        ))

    def _paths(self, input_path) -> list[Path]:
        """Return input files: explicit files as given, matching files in directories.

        Daily ``*_daily.csv`` files come first so that, when a packet repeats
        a daily observation, the daily value is the one kept.
        """
        items = [input_path] if isinstance(input_path, (str, os.PathLike)) else list(input_path)
        paths: list[Path] = []
        for item in items:
            source = Path(item).expanduser()
            if source.is_file():
                paths.append(source)
            elif source.is_dir():
                paths.extend(path for path in sorted(source.rglob("*")) if path.is_file() and self._matches(path))
            elif not source.exists():
                raise FileNotFoundError(f"RM Young AIO input does not exist: {source}")
            else:
                raise ValueError(f"RM Young AIO input must be a file or directory: {source}")
        paths = list(dict.fromkeys(paths))
        return sorted(paths, key=lambda path: 0 if "_daily." in path.name.casefold() else 1)

    @staticmethod
    def _filename_day(path: Path) -> str | None:
        match = re.search(
            r"_WX_(\d{8})(?:\d{6}|_daily)\.csv$", path.name, re.IGNORECASE
        )
        if not match:
            return None
        return pd.to_datetime(match.group(1), format="%Y%m%d").strftime("%Y-%m-%d")

    def discover(self, input_path: str | Path) -> list[str]:
        """Return the UTC dates of the observations in matching WX daily or packet files."""
        frame, _, _ = self._decode(self._paths(input_path))
        if frame.empty:
            return []
        return sorted(frame.time.dt.strftime("%Y-%m-%d").unique())

    def _source_timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.metadata.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown source timezone: {self.metadata.timezone!r}") from exc

    def _decode(self, paths: list[Path]) -> tuple[pd.DataFrame, int, int]:
        frames: list[pd.DataFrame] = []
        rejected = 0
        self._source_timezone()  # validate early
        columns = ["time", *_VARIABLES, "source_file", "source_line", "_priority"]
        for path in paths:
            priority = 0 if "_daily." in path.name.casefold() else 1
            records: list[dict] = []
            with path.open("r", encoding="ascii", errors="replace") as handle:
                for line_number, line in enumerate(handle.read().splitlines(), 1):
                    match = _PACKET_LINE.match(line.strip())
                    if match is None:
                        rejected += 1
                        continue
                    try:
                        values = [float(value) for value in match.group(2).split()]
                    except ValueError:
                        rejected += 1
                        continue
                    timestamp = pd.to_datetime(match.group(1), format="%Y%m%d%H%M%S", errors="coerce")
                    if pd.isna(timestamp) or len(values) != len(_VARIABLES):
                        rejected += 1
                        continue
                    record = {"time": timestamp, "source_file": path.name, "source_line": line_number,
                              "_priority": priority}
                    record.update(zip(_VARIABLES, values))
                    records.append(record)
            if not records:
                continue
            frame = pd.DataFrame.from_records(records, columns=columns)
            frame["time"], unresolved = localize_to_utc(frame["time"], self.metadata.timezone)
            rejected += unresolved
            frames.append(frame.loc[frame["time"].notna()])

        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
        if frame.empty:
            return frame.drop(columns="_priority"), rejected, 0
        frame = frame.sort_values(["time", "_priority", "source_file", "source_line"], kind="stable")
        duplicate = int(frame.duplicated(subset=["time"]).sum())
        frame = frame.drop_duplicates(subset=["time"], keep="first").drop(columns="_priority").reset_index(drop=True)
        return frame, rejected, duplicate

    def read_raw(self, input_path, **options):
        """Decode daily or packet input into typed, day-keyed pandas products."""
        if options:
            raise TypeError(f"unsupported RM Young AIO options: {sorted(options)}")
        paths = self._paths(input_path)
        frame, rejected, duplicate = self._decode(paths)
        if frame.empty:
            return {}
        products = {}
        for day, observations in frame.groupby(frame.time.dt.strftime("%Y-%m-%d"), sort=True):
            names = tuple(dict.fromkeys(observations.source_file))
            products[day] = RawRMYoungAIOProduct(
                observations.reset_index(drop=True), names, rejected, duplicate
            )
        return products

    def read(self, input_path, **options):
        """Decode and normalize R.M. Young files into day-keyed datasets."""
        raw = self.read_raw(input_path, **options)
        return {
            day: self.normalize(product.observations, source_files=product.source_files,
                                rejected_rows=product.rejected_rows,
                                duplicate_rows=product.duplicate_rows)
            for day, product in raw.items()
        }

    def normalize(self, observations, *, source_path=None, source_files: Sequence[str] = (),
                  rejected_rows=0, duplicate_rows=0):
        """Convert decoded observations to the common GV xarray schema."""
        if not isinstance(observations, pd.DataFrame):
            raise TypeError("RM Young AIO observations must be a pandas DataFrame")
        missing = {"time", *_VARIABLES}.difference(observations.columns)
        if missing:
            raise ValueError(f"RM Young AIO observations are missing columns: {sorted(missing)}")
        if observations.empty:
            raise ValueError("cannot normalize an empty RM Young AIO product")
        frame = observations.sort_values("time", kind="stable").drop_duplicates("time", keep="first")
        dataset = xr.Dataset(coords={"time": pd.DatetimeIndex(frame.time)})
        for name in _VARIABLES:
            dataset[name] = ("time", frame[name].to_numpy())
            units, long_name = _VARIABLE_METADATA[name]
            dataset[name].attrs.update(units=units, long_name=long_name)
        dataset.status_code.attrs["flag_values"] = "0, 1"
        dataset.attrs.update(self.metadata.to_attrs())
        dataset.attrs.update(
            Conventions="CF-1.10, NASA-GPM-GV-TOOLS-0.2",
            processing_level="1",
            processing_software="gv_tools",
            processing_software_version=__version__,
            processing_time=datetime.now(timezone.utc).isoformat(),
            time_reference="UTC",
            source="R.M. Young All-in-One packets (PIERS logger)",
            source_files=", ".join(
                list(source_files)
                or ([Path(str(source_path)).name] if source_path is not None else ["in_memory"])
            ),
            product_type="surface_meteorology",
            source_platform="piers",
            rejected_rows=int(rejected_rows),
            duplicate_rows=int(duplicate_rows),
        )
        return validate_product(dataset)
