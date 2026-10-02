"""Adapter for the existing ``process-parsivel`` processor."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from importlib import import_module
from pathlib import Path
from typing import Any

import pandas as pd
import xarray as xr

from .base import InstrumentAdapter
from ..metadata import InstrumentMetadata
from ..products import validate_product

PARAMETER_NAMES = {
    "Total Drops": ("drop_count", "1", "Number of drops in the sampling interval"),
    "Concentration": ("number_concentration", "m-3", "Total drop number concentration"),
    "LWC": ("liquid_water_content", "g m-3", "Liquid water content"),
    "Z": ("reflectivity_factor", "mm6 m-3", "Equivalent radar reflectivity factor"),
    "dBZ": ("radar_reflectivity", "dBZ", "Radar reflectivity"),
    "Rain": ("precipitation_rate", "mm h-1", "Liquid precipitation rate"),
    "Dm": ("mass_weighted_mean_diameter", "mm", "Mass-weighted mean drop diameter"),
    "Dmax": ("maximum_drop_diameter", "mm", "Maximum observed drop diameter"),
    "Sigma_M": ("mass_spectrum_width", "mm2", "Mass spectrum variance"),
}


class ParsivelSourcePlatform(str, Enum):
    """Supported Parsivel archive families."""

    AUTO = "auto"
    APU = "apu"
    PIERS = "piers"


@dataclass(frozen=True)
class RawParsivelProduct:
    """The three tables returned by process-parsivel for one day."""

    parameters: pd.DataFrame
    psd: pd.DataFrame
    moments: pd.DataFrame


def _backend() -> Any:
    try:
        return import_module("process_parsivel")
    except ImportError as exc:
        raise ImportError(
            "Parsivel support requires process-parsivel>=1.0.0; "
            "install GV Tools with the 'parsivel' extra"
        ) from exc


class ParsivelAdapter(InstrumentAdapter):
    """Ingest APU or PIERS Parsivel data and normalize its derived tables."""

    name = "parsivel"

    def __init__(
        self,
        metadata: InstrumentMetadata,
        *,
        source_platform: str | ParsivelSourcePlatform = ParsivelSourcePlatform.AUTO,
    ) -> None:
        super().__init__(metadata)
        requested = (
            source_platform.value
            if isinstance(source_platform, ParsivelSourcePlatform)
            else str(source_platform).strip().lower()
        )
        if requested not in {item.value for item in ParsivelSourcePlatform}:
            raise ValueError("source_platform must be 'auto', 'apu', or 'piers'")
        inferred = self._infer_source_platform(metadata.instrument_id)
        if requested != "auto" and requested != inferred:
            raise ValueError(
                f"instrument_id {metadata.instrument_id!r} identifies a {inferred.upper()} "
                f"platform, not {requested.upper()}"
            )
        self.source_platform = inferred

    @staticmethod
    def _infer_source_platform(instrument_id: str) -> str:
        identifier = instrument_id.strip().lower()
        if identifier.startswith("apu"):
            return "apu"
        if identifier.startswith("piers"):
            return "piers"
        raise ValueError(
            "Parsivel instrument_id must begin with 'apu' or 'PIERS', or supply "
            "metadata using one of those platform identifiers"
        )

    def discover(self, input_path: str | Path) -> list[str]:
        source = Path(input_path).expanduser()
        if source.is_dir():
            identifier = self.metadata.instrument_id.lower()
            candidates = [
                path for path in source.rglob("*")
                if path.is_file()
                and path.suffix.lower() in {".zip", ".csv", ".dat"}
                and identifier in str(path).lower()
            ]
            dates = sorted({
                date for path in candidates
                for date in _backend().discover_input_dates(path)
            })
        else:
            dates = _backend().discover_input_dates(source)
        return [pd.Timestamp(value).strftime("%Y-%m-%d") for value in dates]

    def read_raw(self, input_path, **options):
        """Decode source files without applying the GV normalized schema."""
        date_interval = options.pop("_date_interval", None)
        if date_interval is not None:
            options["start_date"], options["end_date"] = date_interval
        results = _backend().run(
            input_path,
            self.metadata.instrument_id,
            **options,
        )
        return {day: RawParsivelProduct(*frames) for day, frames in results.items()}

    def read(self, input_path, **options):
        raw = self.read_raw(input_path, **options)
        return {day: self.normalize(
            product.parameters, product.psd, product.moments, source_path=input_path
        ) for day, product in raw.items()}

    def normalize(self, parameters, psd, moments, *, source_path=None) -> xr.Dataset:
        """Combine the processor's three DataFrames into one GV Dataset."""
        frames = (parameters, psd, moments)
        if not all(isinstance(frame, pd.DataFrame) for frame in frames):
            raise TypeError("Parsivel results must be three pandas DataFrames")
        if parameters.empty:
            raise ValueError("cannot normalize an empty Parsivel product")
        if not parameters.index.equals(psd.index) or not parameters.index.equals(moments.index):
            raise ValueError("Parsivel parameter, DSD, and moment times must match")

        times = pd.DatetimeIndex(parameters.index)
        if times.tz is not None:
            times = times.tz_convert("UTC").tz_localize(None)
        dataset = xr.Dataset(coords={"time": times})
        for original_name in parameters.columns:
            name, units, long_name = PARAMETER_NAMES.get(
                str(original_name),
                (str(original_name).strip().lower().replace(" ", "_"), "1", str(original_name)),
            )
            dataset[name] = ("time", parameters[original_name].to_numpy())
            dataset[name].attrs.update(
                units=units, long_name=long_name, source_field=str(original_name)
            )

        diameters = pd.Index(psd.columns).astype(float).to_numpy()
        dataset = dataset.assign_coords(drop_diameter=("drop_diameter", diameters))
        dataset.drop_diameter.attrs.update(units="mm", long_name="Drop diameter bin center")
        dataset["drop_size_distribution"] = (
            ("time", "drop_diameter"), psd.to_numpy()
        )
        dataset.drop_size_distribution.attrs.update(
            units="m-3 mm-1", long_name="Drop size distribution"
        )

        orders = [int(str(column).lstrip("Mm")) for column in moments.columns]
        dataset = dataset.assign_coords(moment_order=("moment_order", orders))
        dataset["drop_size_moment"] = (("time", "moment_order"), moments.to_numpy())
        dataset.drop_size_moment.attrs.update(
            units="varies_with_order", long_name="Raw moment of the drop size distribution"
        )

        backend = _backend()
        dataset.attrs.update(self.metadata.to_attrs())
        dataset.attrs.update(
            Conventions="CF-1.10, NASA-GPM-GV-TOOLS-0.2",
            processing_level="2",
            processing_software="gv_tools; process_parsivel",
            processing_software_version=f"0.34.0; {getattr(backend, '__version__', 'unknown')}",
            processing_time=datetime.now(timezone.utc).isoformat(),
            time_reference="UTC",
            source=str(Path(source_path).expanduser()) if source_path is not None else "in_memory",
            product_type="parsivel_disdrometer",
            source_platform=self.source_platform,
        )
        dataset = dataset.sortby("time")
        return validate_product(dataset)
