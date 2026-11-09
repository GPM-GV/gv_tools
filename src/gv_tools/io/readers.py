"""Consistent, file-list based readers that hide adapter construction."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from ..adapters import RawLufftWS800Product, RawMetOneAIOProduct, RawParsivelProduct, RawRMYoungAIOProduct
from ..adapters.lufft_ws800 import ws800_dataframe, ws800_units
from ..adapters.parsivel import merge_provenance
from ..ingest_radar import ingest_radar, inspect_radar_file
from ..metadata import InstrumentMetadata
from ..registry import create_adapter

_RM_YOUNG_ID = re.compile(r"(?P<id>PIERS\d+)_WX_", re.IGNORECASE)
_LUFFT_WS800 = re.compile(r"(?P<id>PIERS\d+)_WS800_.*\.csv$", re.IGNORECASE)
_METONE_FILE = re.compile(
    r"AIO_(?P<site>[^_]+)_(?P<year>\d{4})(?P<month>\d{2})\.dat$",
    re.IGNORECASE,
)
_PIERS_PARSIVEL_FILE = re.compile(
    r"^(?P<id>PIERS\d+)_Parsivel_.+\.(?:zip|csv|dat)$", re.IGNORECASE
)
_APU_PARSIVEL_FILE = re.compile(
    r"^(?:APU_)?(?P<id>apu\d+)_.*\.(?:zip|csv|dat)$", re.IGNORECASE
)
_METADATA_KEYS = {
    "metadata", "instrument_id", "site_id", "timezone", "manufacturer",
    "model", "serial_number", "latitude", "longitude", "altitude_m", "campaign", "extra",
}


def _resolve_files(files: str | Path | Sequence[str | Path]) -> list[Path]:
    """Resolve one file, a directory, or an explicit sequence of files.

    Directories are scanned recursively.  Instrument-specific readers validate
    that the resulting files belong to one compatible instrument family.
    """
    items = [files] if isinstance(files, (str, Path)) else list(files)
    if not items:
        raise ValueError("input must contain at least one filename or directory")
    resolved = []
    for filename in items:
        if not isinstance(filename, (str, Path)):
            raise TypeError("each input must be a filename or directory string or Path")
        path = Path(filename).expanduser()
        if not path.is_absolute():
            raise ValueError(f"each input path must be fully qualified: {path}")
        if path.is_file():
            resolved.append(path.resolve())
        elif path.is_dir():
            resolved.extend(item.resolve() for item in sorted(path.rglob("*")) if item.is_file())
        else:
            raise FileNotFoundError(f"input path does not exist: {path}")
    unique = list(dict.fromkeys(resolved))
    if not unique:
        raise FileNotFoundError("input directories contain no files")
    return unique


def _daily_first(paths: list[Path]) -> list[Path]:
    """Order consolidated ``*_daily`` products before individual packets.

    0.50.0 dropped every packet whenever any daily file was present, losing
    packets for days without a daily file and packets the daily file lacked.
    Now every file is read; observations are de-duplicated on their time
    stamps and, on a tie, the daily file's value is kept.
    """
    daily = [path for path in paths if "_daily." in path.name.casefold()]
    return daily + [path for path in paths if path not in set(daily)]


def _aio_files(files) -> list[Path]:
    paths = _resolve_files(files)
    selected = [
        path for path in paths
        if _RM_YOUNG_ID.search(path.name) or _LUFFT_WS800.search(path.name) or _METONE_FILE.match(path.name)
    ]
    if not selected:
        raise FileNotFoundError("input contains no recognized AIO weather-station files")
    return _daily_first(selected)


def _parsivel_files(files) -> list[Path]:
    paths = _resolve_files(files)
    selected = [
        path for path in paths
        if _PIERS_PARSIVEL_FILE.match(path.name) or _APU_PARSIVEL_FILE.match(path.name)
    ]
    if not selected:
        raise ValueError("not a recognized Parsivel archive in the supplied input")
    return _daily_first(selected)


def _take_adapter_options(options: dict[str, Any], *, parsivel=False) -> dict[str, Any]:
    keys = _METADATA_KEYS | ({"source_platform"} if parsivel else set())
    return {key: options.pop(key) for key in tuple(options) if key in keys}


def _single_inferred(values: set[str], description: str) -> str:
    if not values:
        raise ValueError(f"could not infer {description}; pass the identifier explicitly")
    if len(values) != 1:
        raise ValueError(f"files contain multiple {description}s: {sorted(values)}")
    return values.pop()


def _infer_aio_id(files: list[Path]) -> str:
    return _single_inferred(
        {match.group("id").upper() for path in files if (match := _RM_YOUNG_ID.search(path.name))},
        "AIO instrument",
    )


def _aio_family(files: list[Path]) -> str:
    families = set()
    for path in files:
        if _LUFFT_WS800.search(path.name):
            families.add("lufft_ws800")
        elif _RM_YOUNG_ID.search(path.name):
            families.add("rm_young")
        elif _METONE_FILE.match(path.name):
            families.add("metone")
        else:
            raise ValueError(
                "not a recognized AIO file: "
                f"{path.name}; expected PIERS####_WX_*.csv, PIERS####_WS800_*.csv, or AIO_SITE_YYYYMM.dat"
            )
    if len(families) != 1:
        raise ValueError("AIO_FILES cannot mix different AIO instrument families")
    return families.pop()


def _infer_metone_site(files: list[Path]) -> str:
    return _single_inferred(
        {match.group("site").upper() for path in files if (match := _METONE_FILE.match(path.name))},
        "Met One site",
    )


def _infer_parsivel_id(files: list[Path]) -> str:
    identifiers = set()
    for path in files:
        match = _PIERS_PARSIVEL_FILE.match(path.name) or _APU_PARSIVEL_FILE.match(path.name)
        if match is None:
            raise ValueError(
                "not a recognized Parsivel archive: "
                f"{path.name}; expected PIERS####_Parsivel_*.zip/.csv or apu##_*.zip/.csv"
            )
        identifier = match.group("id")
        identifiers.add(
            identifier.upper() if identifier.lower().startswith("piers") else identifier.lower()
        )
    return _single_inferred(identifiers, "Parsivel instrument")


def _parsivel_file_day(path: Path) -> str:
    """Return the YYYY-MM-DD in a Parsivel file name (8-, 10-, 12- or 14-digit stamp)."""
    from .. import _parsivel

    stamp = _parsivel.filename_stamp(path.name)
    if stamp is None:
        raise ValueError(f"could not infer a date from Parsivel archive: {path.name}")
    return stamp.strftime("%Y-%m-%d")


def _metadata(metadata, *, instrument_id, instrument_type, site_id, manufacturer, model, timezone, metadata_options):
    values = dict(
        instrument_id=instrument_id, instrument_type=instrument_type, site_id=site_id,
        manufacturer=manufacturer, model=model, timezone=timezone, **metadata_options,
    )
    if metadata is None:
        return InstrumentMetadata(**values)
    return replace(metadata, **{key: value for key, value in values.items() if value is not None})


def _rm_young_adapter(files, *, metadata=None, instrument_id=None, site_id=None, timezone="UTC", **metadata_options):
    info = _metadata(metadata, instrument_id=instrument_id or _infer_aio_id(files),
                     instrument_type="weather_station", site_id=site_id or "WFF",
                     manufacturer="R.M. Young", model="All-in-One", timezone=timezone,
                     metadata_options=metadata_options)
    return create_adapter("rm_young_aio", info)


def _lufft_adapter(files, *, metadata=None, instrument_id=None, site_id=None, timezone="UTC", **metadata_options):
    identifiers = {match.group("id").upper() for path in files if (match := _LUFFT_WS800.search(path.name))}
    identifier = instrument_id or _single_inferred(identifiers, "Lufft WS800 instrument")
    info = _metadata(metadata, instrument_id=identifier, instrument_type="weather_station",
                     site_id=site_id or "WFF", manufacturer="OTT HydroMet",
                     model="Lufft WS800", timezone=timezone, metadata_options=metadata_options)
    return create_adapter("lufft_ws800", info)


def _metone_adapter(files, *, metadata=None, instrument_id=None, site_id=None, timezone="UTC", **metadata_options):
    site = site_id or _infer_metone_site(files)
    info = _metadata(metadata, instrument_id=instrument_id or f"AIO_{site}",
                     instrument_type="weather_station", site_id=site,
                     manufacturer="Met One", model="AIO", timezone=timezone,
                     metadata_options=metadata_options)
    return create_adapter("metone_aio", info)


def _aio_adapter(files, **metadata_options):
    family = _aio_family(files)
    if family == "lufft_ws800":
        return _lufft_adapter(files, **metadata_options)
    if family == "rm_young":
        return _rm_young_adapter(files, **metadata_options)
    return _metone_adapter(files, **metadata_options)


def _parsivel_adapter(files, *, metadata=None, instrument_id=None, site_id="WFF", timezone="UTC", source_platform="auto", **metadata_options):
    detected_identifier = _infer_parsivel_id(files)
    identifier = instrument_id or detected_identifier
    if identifier.casefold() != detected_identifier.casefold():
        raise ValueError(
            f"instrument_id {instrument_id!r} does not match filenames for "
            f"{detected_identifier!r}"
        )
    info = _metadata(metadata, instrument_id=identifier, instrument_type="disdrometer",
                     site_id=site_id, manufacturer="OTT HydroMet", model="Parsivel2",
                     timezone=timezone, metadata_options=metadata_options)
    return create_adapter("parsivel", info, source_platform=source_platform)


def _read_all(adapter, files, method, **options):
    """Decode every file in ONE adapter call so duplicates across files are seen."""
    daily = getattr(adapter, method)(files, **options)
    products = [daily[day] for day in sorted(daily)]
    if not products:
        raise ValueError("the supplied files contain no valid observations")
    return products


def _merge_frame(frames):
    merged = pd.concat(frames, axis=0)
    if "time" in merged.columns:
        return merged.sort_values("time", kind="stable").drop_duplicates("time", keep="first").reset_index(drop=True)
    merged = merged.sort_index(kind="stable")
    return merged.loc[~merged.index.duplicated(keep="first")]


def _merge_raw(products):
    first = products[0]
    if isinstance(first, (RawLufftWS800Product, RawRMYoungAIOProduct, RawMetOneAIOProduct)):
        # Every day of one adapter call carries the call's totals; do not
        # multiply them by the number of days.
        return replace(
            first,
            observations=_merge_frame([item.observations for item in products]),
            source_files=tuple(dict.fromkeys(name for item in products for name in item.source_files)),
            rejected_rows=max(item.rejected_rows for item in products),
            duplicate_rows=max(item.duplicate_rows for item in products),
        )
    if isinstance(first, RawParsivelProduct):
        parameters = _merge_frame([item.parameters for item in products])
        parameters.attrs = {**first.parameters.attrs, **merge_provenance([item.parameters for item in products])}
        psd = _merge_frame([item.psd for item in products])
        psd.attrs.update(first.psd.attrs)
        spectra = [item.spectrum for item in products if item.spectrum is not None]
        spectrum = None
        if spectra:
            spectrum = xr.concat(spectra, dim="time").sortby("time")
            spectrum = spectrum.isel(time=~spectrum.indexes["time"].duplicated(keep="first"))
        return RawParsivelProduct(
            parameters,
            psd,
            _merge_frame([item.moments for item in products]),
            spectrum,
        )
    raise TypeError(f"unsupported raw product type: {type(first).__name__}")


def _merge_datasets(datasets, files):
    merged = datasets[0] if len(datasets) == 1 else xr.concat(
        datasets, dim="time", data_vars="all", coords="minimal", compat="override",
        join="outer", combine_attrs="override",
    ).sortby("time")
    if merged.indexes["time"].has_duplicates:
        merged = merged.isel(time=~merged.indexes["time"].duplicated(keep="first"))
    if "source_files" not in merged.attrs:
        merged.attrs["source_files"] = ", ".join(path.name for path in files)
    return merged


def _discover(adapter, files):
    return adapter.discover(files)


def _discover_parsivel(adapter, files):
    dates = set(adapter.discover(files))
    if not dates:
        dates.update(_parsivel_file_day(path) for path in files)
    return sorted(dates)


def _continuous_parsivel(dataset: xr.Dataset) -> xr.Dataset:
    """Trim to the first/last minute with telegrams and fill skipped days as missing."""
    if "telegram_count" not in dataset:
        return dataset
    observed = np.flatnonzero(dataset.telegram_count.values > 0)
    if observed.size == 0:
        raise ValueError("the supplied Parsivel files contain no valid telegrams")
    times = dataset.indexes["time"]
    grid = pd.date_range(times[observed[0]], times[observed[-1]], freq="1min")
    fill = {"telegram_count": 0, "sample_duration": 0.0}
    trimmed = dataset.reindex(time=grid, fill_value={**{name: np.nan for name in dataset.data_vars}, **fill})
    trimmed["telegram_count"] = trimmed.telegram_count.astype("int32")
    return trimmed


def discover_aio(files, **metadata_options):
    """Return dates in explicitly supplied RM Young, WS800 or Met One AIO files."""
    paths = _aio_files(files)
    return _discover(_aio_adapter(paths, **metadata_options), paths)


def read_aio_raw(files, **options):
    """Read and merge RM Young, WS800 or Met One AIO files into one raw product."""
    paths = _aio_files(files)
    adapter_options = _take_adapter_options(options)
    return _merge_raw(_read_all(_aio_adapter(paths, **adapter_options), paths, "read_raw", **options))


def _aio_dataframe(dataset):
    frame = dataset.to_dataframe().reset_index()
    frame.attrs.update(dataset.attrs)
    return frame


def _ws800_common_xarray(frame):
    dataset = frame.set_index("time").to_xarray()
    dataset.attrs.update(frame.attrs)
    for name in dataset.data_vars:
        dataset[name].attrs["units"] = ws800_units(name)
    return dataset


def read_aio(files, *, XARRAY=False, **options):
    """Read AIO files as pandas (default) or xarray with ``XARRAY=True``."""
    paths = _aio_files(files)
    adapter_options = _take_adapter_options(options)
    adapter = _aio_adapter(paths, **adapter_options)
    if _aio_family(paths) == "lufft_ws800":
        products = _read_all(adapter, paths, "read_raw", **options)
        frame = ws800_dataframe(_merge_frame([item.observations for item in products]), common_only=True)
        frame.attrs.update(adapter.metadata.to_attrs())
        frame.attrs["source_files"] = ", ".join(
            dict.fromkeys(name for item in products for name in item.source_files)
        )
        return _ws800_common_xarray(frame) if XARRAY else frame
    datasets = _read_all(adapter, paths, "read", **options)
    dataset = _merge_datasets(datasets, paths)
    return dataset if XARRAY else _aio_dataframe(dataset)


def read_ws800_full(files, *, XARRAY=False, **options):
    """Read and merge every field from Lufft WS800 files as pandas or xarray.

    Pandas is returned by default. Pass ``XARRAY=True`` for a normalized
    :class:`xarray.Dataset`.
    """
    paths = _aio_files(files)
    if _aio_family(paths) != "lufft_ws800":
        raise ValueError("files are not recognized PIERS Lufft WS800 CSVs")
    adapter_options = _take_adapter_options(options)
    adapter = _lufft_adapter(paths, **adapter_options)
    if XARRAY:
        datasets = _read_all(adapter, paths, "read", **options)
        return _merge_datasets(datasets, paths)
    products = _read_all(adapter, paths, "read_raw", **options)
    frame = ws800_dataframe(_merge_frame([item.observations for item in products]))
    frame.attrs.update(adapter.metadata.to_attrs())
    frame.attrs["source_files"] = ", ".join(
        dict.fromkeys(name for item in products for name in item.source_files)
    )
    return frame


def discover_metone(files, **metadata_options):
    """Compatibility wrapper for :func:`discover_aio`."""
    paths = _aio_files(files)
    return discover_aio(paths, **metadata_options)


def read_metone_raw(files, **options):
    """Compatibility wrapper for :func:`read_aio_raw`."""
    paths = _aio_files(files)
    return read_aio_raw(paths, **options)


def read_metone(files, **options):
    """Compatibility wrapper for :func:`read_aio`."""
    paths = _aio_files(files)
    return read_aio(paths, **options)


def discover_parsivel(files, **metadata_options):
    """Return dates in the explicitly supplied Parsivel files."""
    paths = _parsivel_files(files)
    return _discover_parsivel(_parsivel_adapter(paths, **metadata_options), paths)


def read_parsivel_raw(files, **options):
    """Read and merge explicitly supplied Parsivel files into one raw product.

    Decoder options (``start_date``, ``end_date``, ``classes``,
    ``fall_speed``, ``velocity_filter``, ``max_diameter_mm``,
    ``telegram_interval_s``) are forwarded to the decoder.
    """
    paths = _parsivel_files(files)
    adapter_options = _take_adapter_options(options, parsivel=True)
    return _merge_raw(_read_all(
        _parsivel_adapter(paths, **adapter_options), paths, "read_raw", **options
    ))


def read_parsivel(files, **options):
    """Read every supplied Parsivel file into one 1-minute xarray Dataset.

    Telegrams from all files are pooled, counted once and put in the minute
    holding the centre of their measuring interval. The result runs from the
    first to the last minute with a telegram; minutes without telegrams inside
    that span are missing (NaN) with ``telegram_count == 0``. Decoder options
    such as ``start_date``/``end_date`` (UTC days), ``classes`` (``"ott"`` or
    ``"legacy"``), ``fall_speed`` (``"measured"`` or ``"theoretical"``),
    ``velocity_filter``, ``max_diameter_mm``, ``telegram_interval_s``,
    ``time_binning`` (``"centre"`` or ``"stamp"``), ``strict_fields``,
    ``spectrum_offset`` and ``include_spectrum`` are forwarded to
    :func:`gv_tools._parsivel.iter_days`. To get one complete day, pass that
    day's files and the next day's first files (they hold its last minutes)
    with ``start_date`` and ``end_date`` set to the day.
    """
    paths = _parsivel_files(files)
    adapter_options = _take_adapter_options(options, parsivel=True)
    datasets = _read_all(
        _parsivel_adapter(paths, **adapter_options), paths, "read", **options
    )
    merged = _merge_datasets(datasets, paths)
    merged.attrs.update(merge_provenance(datasets))
    return _continuous_parsivel(merged)


def read_radar(radar_file, *, XRADAR=False, **reader_options):
    """Read one or more compressed or uncompressed radar files.

    The file format is detected from its content, including Universal Format,
    SIGMET/IRIS, NEXRAD Level II, and CF/Radial NetCDF. ``.gz``, ``.bz2``, and ZIP
    compression are handled transparently. The default reads directly with
    ARM Py-ART. ``XRADAR=True`` loads through xradar, converts the resulting
    DataTree with ``tree.pyart.to_radar()``, and returns the Py-ART Radar.
    """
    paths = _resolve_files(radar_file)
    products = [ingest_radar(path, XRADAR=XRADAR, **reader_options) for path in paths]
    return products[0] if len(products) == 1 else products


def inspect_radar(radar_file):
    """Return automatically detected ingest routes for one or more files."""
    paths = _resolve_files(radar_file)
    routes = [inspect_radar_file(path) for path in paths]
    return routes[0] if len(routes) == 1 else routes
