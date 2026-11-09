"""Adapter for the bundled Parsivel decoder (:mod:`gv_tools._parsivel`)."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from importlib import import_module
import os
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from .base import InstrumentAdapter
from ..metadata import InstrumentMetadata
from ..products import validate_product
from .. import __version__

PARAMETER_NAMES = {
    "Total Drops": ("drop_count", "1", "Number of drops kept by the velocity-diameter filter"),
    "Concentration": ("number_concentration", "m-3", "Total drop number concentration"),
    "LWC": ("liquid_water_content", "g m-3", "Liquid water content"),
    "Z": ("reflectivity_factor", "mm6 m-3", "Rayleigh radar reflectivity factor (sixth DSD moment)"),
    "dBZ": ("radar_reflectivity", "dBZ", "10 log10 of the Rayleigh reflectivity factor"),
    "Rain": ("precipitation_rate", "mm h-1", "Rain rate from the filtered drop volume flux"),
    "Dm": ("mass_weighted_mean_diameter", "mm", "Mass-weighted mean drop diameter (M4/M3)"),
    "Dmax": ("maximum_drop_diameter", "mm", "Centre of the largest diameter class with drops"),
    "Sigma_M": ("mass_spectrum_width", "mm", "Mass spectrum standard deviation (sigma_m)"),
    "Nw": ("normalized_intercept_parameter", "m-3 mm-1", "Normalized intercept parameter Nw = (4**4/6) M3**5/M4**4"),
    "V": ("mean_fall_speed", "m s-1", "Drop-count-weighted mean measured fall speed of the filtered drops"),
    "Raw Drops": ("raw_drop_count", "1", "Number of particles before the velocity-diameter filter"),
    "Telegrams": ("telegram_count", "1", "Number of telegrams received in the minute"),
    "Sample_Seconds": ("sample_duration", "s", "Sampled duration: telegram count x telegram interval"),
}
_PROVENANCE_ATTRS = (
    "telegrams", "duplicate_telegrams", "conflicting_telegrams", "rejected_lines",
    "rejected_lines_by_file", "telegram_interval_s", "telegram_interval_source", "time_binning",
    "source_files", "parsivel_classes", "fall_speed_method", "class_description",
    "velocity_filter", "max_diameter_mm",
)


class ParsivelSourcePlatform(str, Enum):
    """Supported Parsivel archive families."""

    AUTO = "auto"
    APU = "apu"
    PIERS = "piers"


@dataclass(frozen=True)
class RawParsivelProduct:
    """The tables returned by the decoder for one day.

    ``spectrum`` is the per-minute raw count array (time, drop_diameter,
    fall_velocity) when it was requested with ``include_spectrum=True``.
    """

    parameters: pd.DataFrame
    psd: pd.DataFrame
    moments: pd.DataFrame
    spectrum: Any = None


def _backend() -> Any:
    try:
        return import_module("gv_tools._parsivel")
    except ImportError as exc:
        raise ImportError(
            "The bundled Parsivel decoder could not be imported; "
            "reinstall the complete GV Tools wheel"
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

    def _file_pattern(self) -> re.Pattern[str]:
        identifier = re.escape(self.metadata.instrument_id)
        if self.source_platform == "piers":
            return re.compile(rf"^{identifier}_Parsivel_.*\.(?:zip|csv|dat)$", re.IGNORECASE)
        return re.compile(rf"^(?:APU_)?{identifier}_.*\.(?:zip|csv|dat)$", re.IGNORECASE)

    def _inputs(self, input_path):
        """Return explicit files unchanged; select this instrument's files in directories."""
        items = [input_path] if isinstance(input_path, (str, os.PathLike)) else list(input_path)
        pattern = self._file_pattern()
        selected: list[Path] = []
        for item in items:
            path = Path(item).expanduser()
            if path.is_dir():
                selected.extend(
                    candidate for candidate in sorted(path.rglob("*"))
                    if candidate.is_file() and pattern.match(candidate.name)
                )
            else:
                selected.append(path)
        return selected

    def discover(self, input_path: str | Path) -> list[str]:
        """Return ISO dates represented by compatible source files."""
        inputs = self._inputs(input_path)
        if not inputs:
            return []
        dates = _backend().discover_input_dates(inputs)
        return sorted({pd.Timestamp(value).strftime("%Y-%m-%d") for value in dates})

    def read_raw(self, input_path, **options):
        """Decode source files without applying the GV normalized schema.

        Options are those of :func:`gv_tools._parsivel.iter_days`:
        ``start_date``, ``end_date``, ``classes``, ``fall_speed``,
        ``velocity_filter``, ``max_diameter_mm``, ``telegram_interval_s``,
        ``time_binning``, ``strict_fields``, ``spectrum_offset``,
        ``full_day`` and ``include_spectrum``.
        """
        date_interval = options.pop("_date_interval", None)
        if date_interval is not None:
            options["start_date"], options["end_date"] = date_interval
        inputs = self._inputs(input_path)
        if not inputs:
            return {}
        results = _backend().run(inputs, self.metadata.instrument_id, **options)
        return {day: RawParsivelProduct(*frames) for day, frames in results.items()}

    def read(self, input_path, **options):
        """Decode and normalize source data into day-keyed xarray datasets."""
        raw = self.read_raw(input_path, **options)
        return {day: self.normalize(
            product.parameters, product.psd, product.moments, spectrum=product.spectrum,
        ) for day, product in raw.items()}

    def normalize(self, parameters, psd, moments, *, source_path=None, spectrum=None) -> xr.Dataset:
        """Combine the processor's DataFrames into one GV Dataset.

        ``source_path`` is accepted for compatibility; only its base name is
        recorded (in ``source_files``) when the frames carry no provenance.
        """
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
            values = parameters[original_name].to_numpy()
            if name == "telegram_count":
                values = values.astype("int32")
            dataset[name] = ("time", values)
            dataset[name].attrs.update(
                units=units, long_name=long_name, source_field=str(original_name)
            )

        diameters = pd.Index(psd.columns).astype(float).to_numpy()
        dataset = dataset.assign_coords(drop_diameter=("drop_diameter", diameters))
        dataset.drop_diameter.attrs.update(units="mm", long_name="Drop diameter class centre")
        widths = psd.attrs.get("diameter_width")
        if widths is not None and len(widths) == diameters.size:
            dataset = dataset.assign_coords(
                drop_diameter_width=("drop_diameter", np.asarray(widths, dtype=float))
            )
            dataset.drop_diameter_width.attrs.update(units="mm", long_name="Drop diameter class width")
        dataset["drop_size_distribution"] = (
            ("time", "drop_diameter"), psd.to_numpy()
        )
        dataset.drop_size_distribution.attrs.update(
            units="m-3 mm-1", long_name="Drop size distribution N(D)"
        )

        orders = [int(str(column).lstrip("Mm")) for column in moments.columns]
        dataset = dataset.assign_coords(moment_order=("moment_order", orders))
        dataset["drop_size_moment"] = (("time", "moment_order"), moments.to_numpy())
        dataset.drop_size_moment.attrs.update(
            units="m-3 mm^n", long_name="Moment n of the drop size distribution, sum N(D) D^n dD"
        )
        if spectrum is not None:
            dataset["raw_spectrum"] = spectrum.reindex(time=times)
            dataset = dataset.assign_coords(fall_velocity=spectrum.fall_velocity.values)
            dataset.fall_velocity.attrs.update(units="m s-1", long_name="Fall velocity class centre")

        provenance = {key: parameters.attrs[key] for key in _PROVENANCE_ATTRS if key in parameters.attrs}
        if "source_files" not in provenance and source_path is not None:
            provenance["source_files"] = Path(str(source_path)).name
        dataset.attrs.update(self.metadata.to_attrs())
        dataset.attrs.update(
            Conventions="CF-1.10, NASA-GPM-GV-TOOLS-0.2",
            processing_level="2",
            processing_software="gv_tools",
            processing_software_version=__version__,
            processing_time=datetime.now(timezone.utc).isoformat(),
            time_reference="UTC",
            time_coordinate=(
                "start of each one-minute interval; each telegram is counted in the minute holding "
                "the centre of its measuring interval (stamp - interval / 2)"
                if parameters.attrs.get("time_binning", "centre") == "centre"
                else "start of each one-minute interval; telegrams binned by their logger time stamp"
            ),
            source=f"OTT {self.metadata.model or 'Parsivel'} raw telegrams ({self.source_platform.upper()} logger)",
            product_type="parsivel_disdrometer",
            source_platform=self.source_platform,
            **provenance,
        )
        dataset = dataset.sortby("time")
        return validate_product(dataset)


def _parse_by_file(text) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in str(text or "").split(";"):
        name, separator, value = item.strip().rpartition("=")
        if separator and name:
            try:
                counts[name] = int(value)
            except ValueError:
                continue
    return counts


def merge_provenance(items) -> dict:
    """Combine the per-day provenance attributes of several products.

    ``items`` are Datasets or DataFrames carrying the attributes written by
    the decoder. Telegram counts are summed; rejected lines are counted once
    per file however many days the file spans; source files are joined; the
    telegram interval is reported once when every day agrees. Files are
    known by name only (directories are never stored), so two different
    files with the same name count as one.
    """
    attrs = [getattr(item, "attrs", {}) for item in items]
    merged: dict = {}
    for key in ("telegrams", "duplicate_telegrams", "conflicting_telegrams"):
        values = [item[key] for item in attrs if key in item]
        if values:
            merged[key] = int(sum(int(value) for value in values))
    by_file: dict[str, int] = {}
    for item in attrs:
        for name, count in _parse_by_file(item.get("rejected_lines_by_file")).items():
            # a day produced while its file was still being read saw part of the count
            by_file[name] = max(by_file.get(name, 0), count)
    if any("rejected_lines" in item for item in attrs):
        merged["rejected_lines"] = int(sum(by_file.values()))
        merged["rejected_lines_by_file"] = "; ".join(f"{name}={count}" for name, count in by_file.items())
    names = list(dict.fromkeys(
        name.strip() for item in attrs for name in str(item.get("source_files", "")).split(",") if name.strip()
    ))
    if names:
        merged["source_files"] = ", ".join(names)
        merged["source_file_count"] = len(names)
    for key in ("telegram_interval_s", "telegram_interval_source"):
        values = list(dict.fromkeys(str(item[key]) for item in attrs if key in item))
        if len(values) == 1:
            merged[key] = next(item[key] for item in attrs if key in item)
        elif values:
            merged[key] = "varies by day: " + ", ".join(values)
    return merged
