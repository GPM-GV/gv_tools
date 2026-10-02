"""Reader for monthly Met One All-in-One weather-station files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import xarray as xr

from .base import InstrumentAdapter
from ..metadata import InstrumentMetadata
from ..products import validate_product

_FILE_NAME = re.compile(r"^AIO_(?P<site>[^_]+)_(?P<year>\d{4})(?P<month>\d{2})\.dat$", re.I)
_FIELD = re.compile(r"(?P<number>\d{2})\+(?P<value>\S+)")
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

    def _paths(self, input_path: str | Path) -> list[Path]:
        source = Path(input_path).expanduser()
        if source.is_file():
            if not self._matches(source):
                raise ValueError(
                    f"Met One AIO filename must match AIO_{self.metadata.site_id}_YYYYMM.dat: {source.name}"
                )
            return [source]
        if not source.exists():
            raise FileNotFoundError(f"Met One AIO input does not exist: {source}")
        if not source.is_dir():
            raise ValueError(f"Met One AIO input must be a file or directory: {source}")
        return sorted(path for path in source.rglob("*.dat") if path.is_file() and self._matches(path))

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
            fields[int(match.group("number"))] = float(value)
        return fields

    def _decode(self, paths: list[Path]) -> tuple[pd.DataFrame, int, int]:
        records: list[dict] = []
        rejected = 0
        source_timezone = self._source_timezone()
        required = set(_SOURCE_FIELDS)
        for path in paths:
            filename_month = self._filename_month(path)
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
                    try:
                        timestamp = pd.Timestamp(f"{year}-01-01") + pd.Timedelta(
                            days=day - 1, hours=hour, minutes=minute
                        )
                    except (ValueError, OverflowError):
                        rejected += 1
                        continue
                    if day < 1 or hour > 23 or minute > 59 or timestamp.to_period("M") != filename_month:
                        rejected += 1
                        continue
                    timestamp = timestamp.tz_localize(source_timezone).tz_convert("UTC").tz_localize(None)
                    record = {"time": timestamp, "source_file": path.name, "source_line": line_number}
                    record.update({_SOURCE_FIELDS[number]: value for number, value in fields.items()})
                    records.append(record)

        columns = ["time", *_DATA_VARIABLES, "source_file", "source_line"]
        frame = pd.DataFrame.from_records(records, columns=columns)
        if frame.empty:
            return frame, rejected, 0
        frame = frame.sort_values(["time", "source_file", "source_line"], kind="stable")
        duplicates = int(frame.duplicated("time").sum())
        return frame.drop_duplicates("time", keep="first").reset_index(drop=True), rejected, duplicates

    def read_raw(self, input_path, **options):
        if options:
            raise TypeError(f"unsupported Met One AIO options: {sorted(options)}")
        frame, rejected, duplicates = self._decode(self._paths(input_path))
        if frame.empty:
            return {}
        products = {}
        for day, observations in frame.groupby(frame.time.dt.strftime("%Y-%m-%d"), sort=True):
            products[day] = RawMetOneAIOProduct(
                observations.reset_index(drop=True),
                tuple(sorted(observations.source_file.unique())),
                rejected,
                duplicates,
            )
        return products

    def read(self, input_path, **options):
        raw = self.read_raw(input_path, **options)
        return {
            day: self.normalize(
                product.observations,
                source_path=input_path,
                rejected_rows=product.rejected_rows,
                duplicate_rows=product.duplicate_rows,
            )
            for day, product in raw.items()
        }

    def normalize(self, observations, *, source_path=None, rejected_rows=0, duplicate_rows=0):
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
            processing_software_version="0.34.0",
            processing_time=datetime.now(timezone.utc).isoformat(),
            time_reference="UTC",
            source=str(Path(source_path).expanduser()) if source_path is not None else "in_memory",
            product_type="surface_meteorology",
            source_platform="metone_aio",
            rejected_rows=int(rejected_rows),
            duplicate_rows=int(duplicate_rows),
        )
        return validate_product(dataset)
