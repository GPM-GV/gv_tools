"""Reader for monthly Met One All-in-One weather-station files."""

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
from ..products import validate_product
from .. import __version__

_FILE_NAME = re.compile(r"^AIO_(?P<site>[^_]+)_(?P<year>\d{4})(?P<month>\d{2})\.dat$", re.I)
# "NN+value" or "NN-value": Campbell printable ASCII writes the sign in place
# of the separator, so negative temperatures look like "08-005.6".
_FIELD = re.compile(r"(?P<number>\d{2})(?P<sign>[+-])(?P<value>\S+)")
_SOURCE_FIELDS = {
    1: "averaging_interval",
    2: "year",
    3: "day_of_year",
    4: "hour_minute",
    5: "wind_speed",
    6: "wind_from_direction",
    7: "wind_direction_standard_deviation",
    8: "air_temperature",
    9: "relative_humidity",
    10: "air_pressure",
    15: "user_channel_2",
}
_DATA_VARIABLES = (
    "averaging_interval",
    "wind_speed",
    "wind_from_direction",
    "wind_direction_standard_deviation",
    "air_temperature",
    "relative_humidity",
    "air_pressure",
    "user_channel_2",
)
_VARIABLE_METADATA = {
    "averaging_interval": ("min", "Averaging interval"),
    "wind_speed": ("m s-1", "Wind speed"),
    "wind_from_direction": ("degree", "Meteorological wind direction"),
    "wind_direction_standard_deviation": ("degree", "Wind direction standard deviation"),
    "air_temperature": ("degree_Celsius", "Air temperature"),
    "relative_humidity": ("percent", "Relative humidity"),
    "air_pressure": ("hPa", "Atmospheric pressure"),
    "user_channel_2": ("1", "Met One user channel 2"),
}


@dataclass(frozen=True)
class RawMetOneAIOProduct:
    """Decoded observations and ingest accounting for one UTC day."""

    observations: pd.DataFrame
    source_files: tuple[str, ...]
    rejected_rows: int = 0
    duplicate_rows: int = 0


class MetOneAIOAdapter(InstrumentAdapter):
    """Read ``AIO_SITE_YYYYMM.dat`` monthly Met One AIO files."""

    name = "metone_aio"

    def _matches(self, path: Path) -> bool:
        match = _FILE_NAME.match(path.name)
        return bool(match and match.group("site").casefold() == self.metadata.site_id.casefold())

    def _paths(self, input_path) -> list[Path]:
        items = [input_path] if isinstance(input_path, (str, os.PathLike)) else list(input_path)
        paths: list[Path] = []
        for item in items:
            source = Path(item).expanduser()
            if source.is_file():
                if not self._matches(source):
                    raise ValueError(
                        f"Met One AIO filename must match AIO_{self.metadata.site_id}_YYYYMM.dat: {source.name}"
                    )
                paths.append(source)
            elif source.is_dir():
                paths.extend(path for path in sorted(source.rglob("*.dat")) if path.is_file() and self._matches(path))
            elif not source.exists():
                raise FileNotFoundError(f"Met One AIO input does not exist: {source}")
            else:
                raise ValueError(f"Met One AIO input must be a file or directory: {source}")
        return list(dict.fromkeys(paths))

    def _source_timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.metadata.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown source timezone: {self.metadata.timezone!r}") from exc

    @staticmethod
    def _filename_month(path: Path) -> pd.Period:
        match = _FILE_NAME.match(path.name)
        assert match is not None
        return pd.Period(f"{match.group('year')}-{match.group('month')}", freq="M")

    def discover(self, input_path: str | Path) -> list[str]:
        """Return days covered by valid observations in matching monthly files."""
        frame, _, _ = self._decode(self._paths(input_path))
        if frame.empty:
            return []
        return sorted(frame.time.dt.strftime("%Y-%m-%d").unique())

    @staticmethod
    def _parse_fields(line: str) -> dict[int, float]:
        fields = {}
        for match in _FIELD.finditer(line):
            value = match.group("value").rstrip(".")
            fields[int(match.group("number"))] = float(match.group("sign") + value)
        return fields

    def _decode(self, paths: list[Path]) -> tuple[pd.DataFrame, int, int]:
        frames: list[pd.DataFrame] = []
        rejected = 0
        self._source_timezone()  # validate early
        required = set(_SOURCE_FIELDS)
        for path in paths:
            filename_month = self._filename_month(path)
            month_start = filename_month.start_time
            month_end = (filename_month + 1).start_time
            records: list[dict] = []
            with path.open("r", encoding="ascii", errors="replace") as handle:
                for line_number, line in enumerate(handle, 1):
                    if line_number == 1 and ".Year" in line:
                        continue
                    try:
                        fields = self._parse_fields(line)
                    except ValueError:
                        rejected += 1
                        continue
                    if not required.issubset(fields):
                        rejected += 1
                        continue
                    year = int(fields[2])
                    day = int(fields[3])
                    hhmm = int(fields[4])
                    hour, minute = divmod(hhmm, 100)
                    # Loggers write the end of the last interval of a day as
                    # 2400 on that day; it is 00:00 of the next day.
                    if day < 1 or day > 366 or hour > 24 or minute > 59 or (hour == 24 and minute):
                        rejected += 1
                        continue
                    try:
                        timestamp = pd.Timestamp(f"{year}-01-01") + pd.Timedelta(
                            days=day - 1, hours=hour, minutes=minute
                        )
                    except (ValueError, OverflowError):
                        rejected += 1
                        continue
                    if timestamp.year != year and not (hour == 24 and timestamp == pd.Timestamp(f"{year + 1}-01-01")):
                        rejected += 1
                        continue
                    # Interval-ending stamps: the month's first record may be
                    # 00:00 of day 1 and its last 00:00 of the next month.
                    if not month_start <= timestamp <= month_end:
                        rejected += 1
                        continue
                    record = {"time": timestamp, "source_file": path.name, "source_line": line_number}
                    record.update({_SOURCE_FIELDS[number]: value for number, value in fields.items() if number in _SOURCE_FIELDS})
                    records.append(record)
            if not records:
                continue
            frame = pd.DataFrame.from_records(records, columns=["time", *_DATA_VARIABLES, "source_file", "source_line"])
            # Localize per file, in file order, so a daylight-saving fall-back
            # hour can be resolved from the sequence instead of aborting.
            frame["time"], unresolved = localize_to_utc(frame["time"], self.metadata.timezone)
            rejected += unresolved
            frames.append(frame.loc[frame["time"].notna()])

        columns = ["time", *_DATA_VARIABLES, "source_file", "source_line"]
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
        if frame.empty:
            return frame, rejected, 0
        frame = frame.sort_values(["time", "source_file", "source_line"], kind="stable")
        duplicates = int(frame.duplicated("time").sum())
        return frame.drop_duplicates("time", keep="first").reset_index(drop=True), rejected, duplicates

    def read_raw(self, input_path, **options):
        """Decode Met One source files into day-keyed raw products."""
        if options:
            raise TypeError(f"unsupported Met One AIO options: {sorted(options)}")
        frame, rejected, duplicates = self._decode(self._paths(input_path))
        if frame.empty:
            return {}
        products = {}
        for day, observations in frame.groupby(frame.time.dt.strftime("%Y-%m-%d"), sort=True):
            products[day] = RawMetOneAIOProduct(
                observations.reset_index(drop=True),
                tuple(dict.fromkeys(observations.source_file)),
                rejected,
                duplicates,
            )
        return products

    def read(self, input_path, **options):
        """Decode and normalize Met One files into day-keyed datasets."""
        raw = self.read_raw(input_path, **options)
        return {
            day: self.normalize(
                product.observations,
                source_files=product.source_files,
                rejected_rows=product.rejected_rows,
                duplicate_rows=product.duplicate_rows,
            )
            for day, product in raw.items()
        }

    def normalize(self, observations, *, source_path=None, source_files: Sequence[str] = (),
                  rejected_rows=0, duplicate_rows=0):
        """Convert decoded Met One observations to the common xarray schema."""
        if not isinstance(observations, pd.DataFrame):
            raise TypeError("Met One AIO observations must be a pandas DataFrame")
        missing = {"time", *_DATA_VARIABLES}.difference(observations.columns)
        if missing:
            raise ValueError(f"Met One AIO observations are missing columns: {sorted(missing)}")
        if observations.empty:
            raise ValueError("cannot normalize an empty Met One AIO product")
        frame = observations.sort_values("time", kind="stable").drop_duplicates("time", keep="first")
        dataset = xr.Dataset(coords={"time": pd.DatetimeIndex(frame.time)})
        for name in _DATA_VARIABLES:
            dataset[name] = ("time", frame[name].to_numpy())
            units, long_name = _VARIABLE_METADATA[name]
            dataset[name].attrs.update(units=units, long_name=long_name)
        dataset.attrs.update(self.metadata.to_attrs())
        dataset.attrs.update(
            Conventions="CF-1.10, NASA-GPM-GV-TOOLS-0.2",
            processing_level="1",
            processing_software="gv_tools",
            processing_software_version=__version__,
            processing_time=datetime.now(timezone.utc).isoformat(),
            time_reference="UTC",
            source="Met One All-in-One monthly logger files",
            source_files=", ".join(
                list(source_files)
                or ([Path(str(source_path)).name] if source_path is not None else ["in_memory"])
            ),
            product_type="surface_meteorology",
            source_platform="metone_aio",
            rejected_rows=int(rejected_rows),
            duplicate_rows=int(duplicate_rows),
        )
        return validate_product(dataset)
