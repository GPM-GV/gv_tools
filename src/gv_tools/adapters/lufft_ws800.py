"""Adapter for Lufft WS800 daily CSV files on PIERS platforms."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re

import numpy as np
import pandas as pd
import xarray as xr

from .base import InstrumentAdapter, localize_to_utc
from ..products import validate_product
from .. import __version__

LOGGER = logging.getLogger(__name__)

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
_FILE = re.compile(r"PIERS\d+_WS800_.*\.csv$", re.IGNORECASE)

# Public-name prefix -> units. Checked in order; the first match wins.
_UNITS = (
    (("air_temperature", "air_temp", "dew_point", "wet_bulb", "wind_chill"), "degree_Celsius"),
    (("relative_humidity", "rel_hum"), "percent"),
    (("abs_hum",), "g m-3"),
    (("mixing_ratio",), "g kg-1"),
    (("specific_enthalpy",), "kJ kg-1"),
    (("air_density",), "kg m-3"),
    (("air_pressure", "abs_press", "rel_press"), "hPa"),
    (("wind_speed", "wind_spd"), "m s-1"),
    (("wind_from_direction", "wind_dir", "compass"), "degree"),
    (("precipitation_rate", "precip_intens"), "mm h-1"),
    (("precipitation_type", "precip_type"), "1"),
    (("precipitation_amount", "precipitation_increment", "precip_abs", "precip_diff"), "mm"),
    (("global_radiation", "glob_rad"), "W m-2"),
)


def ws800_units(public_name: str) -> str:
    """Return the physical units of a GV Tools WS800 column name."""
    for prefixes, units in _UNITS:
        if public_name.startswith(prefixes):
            return units
    return "1"


def _snake(source: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", source).replace("__", "_").lower()


def _suffix(source: str) -> str:
    """``_Act`` (actual value) maps to no suffix; ``_Min``/``_Max``/... are kept."""
    _, _, tail = source.partition("_")
    return "" if tail in ("", "Act") else "_" + _snake(tail)


def _saturation_vapour_pressure_hpa(temperature_c):
    """Bolton (1980) saturation vapour pressure over water (hPa)."""
    return 6.112 * np.exp(17.67 * temperature_c / (temperature_c + 243.5))


def _median(values) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return float(np.median(values)) if values.size else float("nan")


def ws800_relabel_plan(observations: pd.DataFrame) -> dict[str, str]:
    """Decide what the WS800 ``MixingRatio_*`` and ``RelPress_*`` columns hold.

    The PIERS WS800 logger writes specific enthalpy (kJ kg-1) under the
    instrument's ``MixingRatio_*`` labels and air density (kg m-3) under
    ``RelPress_*``. The values are checked against the physics: a column
    whose median lies between 0.5 and 2 cannot be a pressure in hPa and is
    air density; the ``MixingRatio`` values are compared with the mixing
    ratio and the moist enthalpy computed from temperature, humidity and
    pressure. Returns ``{"MixingRatio": ..., "RelPress": ...}`` with values
    ``"specific_enthalpy"``/``"mixing_ratio"`` and ``"air_density"``/
    ``"relative_pressure"``.
    """
    plan: dict[str, str] = {}
    pressure_columns = [column for column in observations.columns if str(column).startswith("RelPress")]
    if pressure_columns:
        level = _median(pd.to_numeric(observations[pressure_columns[0]], errors="coerce"))
        if 300.0 <= level <= 1200.0:
            plan["RelPress"] = "relative_pressure"
        else:
            plan["RelPress"] = "air_density"  # the PIERS logger's known layout
            if np.isfinite(level) and not 0.5 <= level <= 2.0:
                LOGGER.warning("WS800 RelPress values (median %s) are neither hPa nor kg m-3", level)
    ratio_columns = [column for column in observations.columns if str(column).startswith("MixingRatio")]
    if ratio_columns:
        verdict = "specific_enthalpy"  # the PIERS logger's known layout
        needed = {"AirTemp_Act", "RelHum_Act", "AbsPress_Act"}
        if needed.issubset(observations.columns):
            frame = observations[[ratio_columns[0], *sorted(needed)]].apply(pd.to_numeric, errors="coerce").dropna()
            if len(frame):
                temperature = frame["AirTemp_Act"].to_numpy(float)
                vapour = frame["RelHum_Act"].to_numpy(float) / 100.0 * _saturation_vapour_pressure_hpa(temperature)
                pressure = frame["AbsPress_Act"].to_numpy(float)
                mixing = 621.97 * vapour / np.maximum(pressure - vapour, 1.0)  # g kg-1
                enthalpy = 1.006 * temperature + mixing / 1000.0 * (2501.0 + 1.86 * temperature)  # kJ kg-1
                value = frame[ratio_columns[0]].to_numpy(float)
                error_mixing = _median(np.abs(value - mixing))
                error_enthalpy = _median(np.abs(value - enthalpy))
                verdict = "mixing_ratio" if error_mixing < error_enthalpy else "specific_enthalpy"
        plan["MixingRatio"] = verdict
    return plan


def ws800_column_names(observations: pd.DataFrame) -> dict[str, str]:
    """Map native WS800 column names to GV Tools names, applying the relabel plan."""
    plan = ws800_relabel_plan(observations)
    names = {}
    for source in observations.columns:
        if source in {"time", "source_file", "_priority"}:
            continue
        source = str(source)
        if source in _PRIMARY:
            names[source] = _PRIMARY[source]
        elif source.startswith("MixingRatio") and plan.get("MixingRatio") == "specific_enthalpy":
            names[source] = "specific_enthalpy" + _suffix(source)
        elif source.startswith("RelPress") and plan.get("RelPress") == "air_density":
            names[source] = "air_density" + _suffix(source)
        else:
            names[source] = _snake(source)
    return names


def ws800_dataframe(observations: pd.DataFrame, *, common_only: bool = False) -> pd.DataFrame:
    """Return WS800 observations with public GV Tools column names."""
    columns = COMMON_AIO_COLUMNS if common_only else ws800_column_names(observations)
    present = {source: target for source, target in columns.items() if source in observations.columns}
    return observations[["time", *present]].rename(columns=present).reset_index(drop=True)


def _name(source: str) -> str:
    """Name of a native column when no relabel plan applies (0.50.0 behaviour)."""
    if source in _PRIMARY:
        return _PRIMARY[source]
    return _snake(source)


def _units(source: str) -> str:
    """Units of a native WS800 field name (kept for compatibility)."""
    return ws800_units(_name(source))


@dataclass(frozen=True)
class RawLufftWS800Product:
    """Decoded WS800 observations and source-accounting metadata."""
    observations: pd.DataFrame
    source_files: tuple[str, ...]
    rejected_rows: int = 0
    duplicate_rows: int = 0


class LufftWS800Adapter(InstrumentAdapter):
    """Read ``PIERS####_WS800_*.csv`` files (daily files and/or packets)."""

    name = "lufft_ws800"

    def _paths(self, input_path) -> list[Path]:
        items = [input_path] if isinstance(input_path, (str, os.PathLike)) else list(input_path)
        paths: list[Path] = []
        for item in items:
            path = Path(item).expanduser()
            if path.is_dir():
                paths.extend(candidate for candidate in sorted(path.rglob("*.csv")) if _FILE.search(candidate.name))
            elif path.is_file():
                paths.append(path)
            else:
                raise FileNotFoundError(f"Lufft WS800 input does not exist: {path}")
        paths = list(dict.fromkeys(paths))
        return sorted(paths, key=lambda item: (0 if "_daily." in item.name.casefold() else 1))

    def _decode_one(self, path: Path):
        frame = pd.read_csv(path)
        if "Timestamp" not in frame:
            raise ValueError(f"Lufft WS800 file has no Timestamp column: {path.name}")
        timestamps = pd.to_datetime(frame.pop("Timestamp").astype(str).str.strip(), format="%Y%m%d%H%M%S", errors="coerce")
        rejected = int(timestamps.isna().sum())
        frame.insert(0, "time", timestamps)
        frame = frame.loc[frame.time.notna()].copy()
        for column in frame.columns[1:]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.reset_index(drop=True)
        frame["time"], unresolved = localize_to_utc(frame["time"], self.metadata.timezone)
        rejected += unresolved
        frame = frame.loc[frame["time"].notna()].copy()
        frame["source_file"] = path.name
        frame["_priority"] = 0 if "_daily." in path.name.casefold() else 1
        return frame, rejected

    def _decode(self, input_path):
        paths = self._paths(input_path)
        frames, rejected = [], 0
        for path in paths:
            frame, bad = self._decode_one(path)
            frames.append(frame)
            rejected += bad
        if not frames:
            raise FileNotFoundError("no Lufft WS800 files were found")
        frame = pd.concat(frames, ignore_index=True)
        frame = frame.sort_values(["time", "_priority", "source_file"], kind="stable")
        duplicate = int(frame.duplicated("time").sum())
        frame = frame.drop_duplicates("time", keep="first").drop(columns="_priority").reset_index(drop=True)
        return frame, rejected, duplicate

    def discover(self, input_path):
        """Return ISO dates represented by WS800 observations."""
        frame, _, _ = self._decode(input_path)
        return sorted(frame.time.dt.strftime("%Y-%m-%d").unique())

    def read_raw(self, input_path, **options):
        """Decode WS800 files into day-keyed raw products (one call = shared totals)."""
        if options:
            raise TypeError(f"unsupported Lufft WS800 options: {sorted(options)}")
        frame, rejected, duplicate = self._decode(input_path)
        result = {}
        for day, rows in frame.groupby(frame.time.dt.strftime("%Y-%m-%d"), sort=True):
            names = tuple(dict.fromkeys(rows.source_file))
            result[day] = RawLufftWS800Product(rows.reset_index(drop=True), names, rejected, duplicate)
        return result

    def read(self, input_path, **options):
        """Decode and normalize WS800 files into day-keyed datasets."""
        return {day: self.normalize(item.observations, source_files=item.source_files,
                                    rejected_rows=item.rejected_rows, duplicate_rows=item.duplicate_rows)
                for day, item in self.read_raw(input_path, **options).items()}

    def normalize(self, observations, *, source_path=None, source_files: Sequence[str] = (),
                  rejected_rows=0, duplicate_rows=0):
        """Convert decoded WS800 observations to the common xarray schema."""
        dataset = xr.Dataset(coords={"time": pd.DatetimeIndex(observations.time)})
        plan = ws800_relabel_plan(observations)
        for source, target in ws800_column_names(observations).items():
            dataset[target] = ("time", observations[source].to_numpy())
            long_name = source.replace("_", " ")
            if target.startswith(("specific_enthalpy", "air_density")):
                long_name = f"{target.replace('_', ' ').capitalize()} (logger column {source})"
            dataset[target].attrs.update(units=ws800_units(target), long_name=long_name, source_field=source)
        files = list(source_files) or ([Path(str(source_path)).name] if source_path is not None else [])
        dataset.attrs.update(self.metadata.to_attrs())
        dataset.attrs.update(Conventions="CF-1.10, NASA-GPM-GV-TOOLS-0.2", processing_level="1",
            processing_software="gv_tools", processing_software_version=__version__,
            processing_time=datetime.now(timezone.utc).isoformat(), time_reference="UTC",
            source="Lufft WS800 observations (PIERS logger CSV)", source_files=", ".join(files),
            product_type="surface_meteorology",
            source_platform="piers", rejected_rows=int(rejected_rows), duplicate_rows=int(duplicate_rows),
            ws800_mixing_ratio_columns=plan.get("MixingRatio", "absent"),
            ws800_rel_press_columns=plan.get("RelPress", "absent"))
        return validate_product(dataset)
