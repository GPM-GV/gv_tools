"""Adapter for Lufft WS800 daily CSV files on PIERS platforms."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import pandas as pd
import xarray as xr

from .base import InstrumentAdapter
from ..metadata import InstrumentMetadata
from ..products import validate_product

_PRIMARY = {
    "AirTemp_Act": "air_temperature", "DewPoint_Act": "dew_point_temperature",
    "WetBulb_Act": "wet_bulb_temperature", "RelHum_Act": "relative_humidity",
    "AbsPress_Act": "air_pressure", "WindSpd_Act": "wind_speed",
    "WindDir_Act": "wind_from_direction", "Precip_Abs": "precipitation_amount",
    "Precip_Diff": "precipitation_increment", "Precip_Intens": "precipitation_rate",
    "Precip_Type": "precipitation_type", "GlobRad_Act": "global_radiation",
}
COMMON_AIO_COLUMNS = {
    "AirTemp_Act": "air_temperature",
    "RelHum_Act": "relative_humidity",
    "AbsPress_Act": "air_pressure",
    "WindSpd_Act": "wind_speed",
    "WindDir_Act": "wind_from_direction",
}


def ws800_dataframe(observations: pd.DataFrame, *, common_only: bool = False) -> pd.DataFrame:
    """Return WS800 observations with public GV Tools column names."""
    columns = COMMON_AIO_COLUMNS if common_only else {
        column: _name(column)
        for column in observations.columns if column not in {"time", "source_file"}
    }
    return observations[["time", *columns]].rename(columns=columns).reset_index(drop=True)


def _name(source: str) -> str:
    if source in _PRIMARY:
        return _PRIMARY[source]
    return re.sub(r"(?<!^)(?=[A-Z])", "_", source).replace("__", "_").lower()


def _units(source: str) -> str:
    if source.startswith(("AirTemp", "DewPoint", "WetBulb")): return "degree_Celsius"
    if source.startswith("RelHum"): return "percent"
    if source.startswith("AbsHum"): return "g m-3"
    if source.startswith("MixingRatio"): return "g kg-1"
    if source.startswith(("AbsPress", "RelPress")): return "hPa"
    if source.startswith("WindSpd"): return "m s-1"
    if source.startswith("WindDir"): return "degree"
    if source.startswith("Precip") and source != "Precip_Type": return "mm h-1" if source == "Precip_Intens" else "mm"
    if source.startswith("GlobRad"): return "W m-2"
    return "1"


@dataclass(frozen=True)
class RawLufftWS800Product:
    observations: pd.DataFrame
    source_files: tuple[str, ...]
    rejected_rows: int = 0
    duplicate_rows: int = 0


class LufftWS800Adapter(InstrumentAdapter):
    """Read ``PIERS####_WS800_*_daily.csv`` files."""

    name = "lufft_ws800"

    def _decode(self, path: Path):
        frame = pd.read_csv(path)
        if "Timestamp" not in frame:
            raise ValueError(f"Lufft WS800 file has no Timestamp column: {path}")
        timestamps = pd.to_datetime(frame.pop("Timestamp").astype(str), format="%Y%m%d%H%M%S", errors="coerce")
        rejected = int(timestamps.isna().sum())
        frame.insert(0, "time", timestamps)
        frame = frame.loc[frame.time.notna()].copy()
        for column in frame.columns[1:]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["time"] = frame.time.dt.tz_localize(ZoneInfo(self.metadata.timezone)).dt.tz_convert("UTC").dt.tz_localize(None)
        frame["source_file"] = path.name
        duplicate = int(frame.duplicated("time").sum())
        return frame.drop_duplicates("time").sort_values("time"), rejected, duplicate

    def discover(self, input_path):
        frame, _, _ = self._decode(Path(input_path).expanduser())
        return sorted(frame.time.dt.strftime("%Y-%m-%d").unique())

    def read_raw(self, input_path, **options):
        if options: raise TypeError(f"unsupported Lufft WS800 options: {sorted(options)}")
        path = Path(input_path).expanduser()
        frame, rejected, duplicate = self._decode(path)
        result = {}
        for day, rows in frame.groupby(frame.time.dt.strftime("%Y-%m-%d"), sort=True):
            result[day] = RawLufftWS800Product(rows.reset_index(drop=True), (path.name,), rejected, duplicate)
        return result

    def read(self, input_path, **options):
        return {day: self.normalize(item.observations, source_path=input_path,
                                    rejected_rows=item.rejected_rows, duplicate_rows=item.duplicate_rows)
                for day, item in self.read_raw(input_path, **options).items()}

    def normalize(self, observations, *, source_path=None, rejected_rows=0, duplicate_rows=0):
        dataset = xr.Dataset(coords={"time": pd.DatetimeIndex(observations.time)})
        for source in observations.columns:
            if source in {"time", "source_file"}: continue
            target = _name(source)
            dataset[target] = ("time", observations[source].to_numpy())
            dataset[target].attrs.update(units=_units(source), long_name=source.replace("_", " "))
        dataset.attrs.update(self.metadata.to_attrs())
        dataset.attrs.update(Conventions="CF-1.10, NASA-GPM-GV-TOOLS-0.2", processing_level="1",
            processing_software="gv_tools", processing_software_version="0.34.0",
            processing_time=datetime.now(timezone.utc).isoformat(), time_reference="UTC",
            source=str(Path(source_path).expanduser()), product_type="surface_meteorology",
            source_platform="piers", rejected_rows=int(rejected_rows), duplicate_rows=int(duplicate_rows))
        return validate_product(dataset)
