"""Reader and GV adapter for PIERS RM Young All-in-One weather packets."""

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

_PACKET_LINE = re.compile(r"^(\d{14})\s+(.*)$")
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
        return bool(re.match(rf"^{prefix}_WX_\d{{14}}\.csv$", path.name, re.IGNORECASE))

    def _paths(self, input_path: str | Path) -> list[Path]:
        source = Path(input_path).expanduser()
        if source.is_file():
            return [source]
        if not source.exists():
            raise FileNotFoundError(f"RM Young AIO input does not exist: {source}")
        if not source.is_dir():
            raise ValueError(f"RM Young AIO input must be a file or directory: {source}")
        return sorted(path for path in source.rglob("*") if path.is_file() and self._matches(path))

    @staticmethod
    def _filename_day(path: Path) -> str | None:
        match = re.search(r"_WX_(\d{8})\d{6}\.csv$", path.name, re.IGNORECASE)
        if not match:
            return None
        return pd.to_datetime(match.group(1), format="%Y%m%d").strftime("%Y-%m-%d")

    def discover(self, input_path: str | Path) -> list[str]:
        """Return dates represented by matching PIERS WX packet filenames."""
        return sorted({day for path in self._paths(input_path) if (day := self._filename_day(path))})

    def _source_timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.metadata.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown source timezone: {self.metadata.timezone!r}") from exc

    def _decode(self, paths: list[Path]) -> tuple[pd.DataFrame, int, int]:
        records: list[dict] = []
        rejected = 0
        source_timezone = self._source_timezone()
        for path in paths:
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
                    timestamp = timestamp.tz_localize(source_timezone).tz_convert("UTC").tz_localize(None)
                    record = {"time": timestamp, "source_file": path.name, "source_line": line_number}
                    record.update(zip(_VARIABLES, values))
                    records.append(record)

        columns = ["time", *_VARIABLES, "source_file", "source_line"]
        frame = pd.DataFrame.from_records(records, columns=columns)
        if frame.empty:
            return frame, rejected, 0
        frame = frame.sort_values(["time", "source_file", "source_line"], kind="stable")
        duplicate = int(frame.duplicated(subset=["time"]).sum())
        frame = frame.drop_duplicates(subset=["time"], keep="first").reset_index(drop=True)
        return frame, rejected, duplicate

    def read_raw(self, input_path, **options):
        """Decode source packets into typed, day-keyed pandas products."""
        if options:
            raise TypeError(f"unsupported RM Young AIO options: {sorted(options)}")
        paths = self._paths(input_path)
        frame, rejected, duplicate = self._decode(paths)
        if frame.empty:
            return {}
        products = {}
        for day, observations in frame.groupby(frame.time.dt.strftime("%Y-%m-%d"), sort=True):
            names = tuple(sorted(observations.source_file.unique()))
            products[day] = RawRMYoungAIOProduct(
                observations.reset_index(drop=True), names, rejected, duplicate
            )
        return products

    def read(self, input_path, **options):
        raw = self.read_raw(input_path, **options)
        return {
            day: self.normalize(product.observations, source_path=input_path,
                                rejected_rows=product.rejected_rows,
                                duplicate_rows=product.duplicate_rows)
            for day, product in raw.items()
        }

    def normalize(self, observations, *, source_path=None, rejected_rows=0, duplicate_rows=0):
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
            processing_software_version="0.34.0",
            processing_time=datetime.now(timezone.utc).isoformat(),
            time_reference="UTC",
            source=str(Path(source_path).expanduser()) if source_path is not None else "in_memory",
            product_type="surface_meteorology",
            source_platform="piers",
            rejected_rows=int(rejected_rows),
            duplicate_rows=int(duplicate_rows),
        )
        return validate_product(dataset)
