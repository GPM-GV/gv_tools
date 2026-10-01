"""Consistent, file-list based readers that hide adapter construction."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd
import xarray as xr

from ..adapters import RawLufftWS800Product, RawMetOneAIOProduct, RawParsivelProduct, RawRMYoungAIOProduct
from ..adapters.lufft_ws800 import ws800_dataframe
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
    r"^(?P<id>PIERS\d+)_Parsivel_.+\.zip$", re.IGNORECASE
)
_APU_PARSIVEL_FILE = re.compile(
    r"^(?:APU_)?(?P<id>apu\d+)_.*\.zip$", re.IGNORECASE
)
_METADATA_KEYS = {
    "metadata", "instrument_id", "site_id", "timezone", "manufacturer",
    "model", "serial_number", "latitude", "longitude", "altitude_m", "campaign", "extra",
}


def _resolve_files(files: list[str | Path]) -> list[Path]:
    if not isinstance(files, list):
        raise TypeError("files must be a list of filenames")
    if not files:
        raise ValueError("files must contain at least one filename")
    resolved = []
    for filename in files:
        if not isinstance(filename, (str, Path)):
            raise TypeError("each item in files must be a filename string or Path")
        path = Path(filename).expanduser()
        if not path.is_absolute():
            raise ValueError(f"each input filename must be fully qualified: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"input file does not exist: {path}")
        resolved.append(path.resolve())
    if len(set(resolved)) != len(resolved):
        raise ValueError("files contains duplicate filenames")
    return resolved


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
                f"{path.name}; expected PIERS####_Parsivel_*.zip or apu##_*.zip"
            )
        identifier = match.group("id")
        identifiers.add(
            identifier.upper() if identifier.lower().startswith("piers") else identifier.lower()
        )
    return _single_inferred(identifiers, "Parsivel instrument")


def _parsivel_file_day(path: Path) -> str:
    """Return the YYYY-MM-DD encoded in a supported Parsivel archive name."""
    match = re.search(r"(?<!\d)(\d{8})(?:\d{2})?(?!\d)", path.name)
    if match is None:
        raise ValueError(f"could not infer a date from Parsivel archive: {path.name}")
    try:
        return pd.to_datetime(match.group(1), format="%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"invalid date in Parsivel archive: {path.name}") from exc


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


def _daily_results(adapter, files, method, **options):
    products = []
    for path in files:
        daily = getattr(adapter, method)(path, **options)
        products.extend(daily[day] for day in sorted(daily))
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
        return replace(
            first,
            observations=_merge_frame([item.observations for item in products]),
            source_files=tuple(sorted({name for item in products for name in item.source_files})),
            rejected_rows=sum(item.rejected_rows for item in products),
            duplicate_rows=sum(item.duplicate_rows for item in products),
        )
    if isinstance(first, RawParsivelProduct):
        return RawParsivelProduct(
            _merge_frame([item.parameters for item in products]),
            _merge_frame([item.psd for item in products]),
            _merge_frame([item.moments for item in products]),
        )
    raise TypeError(f"unsupported raw product type: {type(first).__name__}")


def _merge_datasets(datasets, files):
    merged = datasets[0] if len(datasets) == 1 else xr.concat(
        datasets, dim="time", data_vars="all", coords="minimal", compat="override",
        join="outer", combine_attrs="override",
    ).sortby("time")
    if merged.indexes["time"].has_duplicates:
        merged = merged.isel(time=~merged.indexes["time"].duplicated(keep="first"))
    merged.attrs["source_files"] = ", ".join(path.name for path in files)
    merged.attrs["source"] = str(files[0].parent)
    return merged


def _discover(adapter, files):
    return sorted({day for path in files for day in adapter.discover(path)})


def _discover_parsivel(adapter, files):
    dates = set()
    for path in files:
        discovered = adapter.discover(path)
        dates.update(discovered or [_parsivel_file_day(path)])
    return sorted(dates)


def _parsivel_results(adapter, files, method, **options):
    start_date = _parsivel_file_day(files[0])
    end_date = _parsivel_file_day(files[-1])
    if pd.Timestamp(end_date) < pd.Timestamp(start_date):
        raise ValueError(
            "the date in the last Parsivel filename precedes the date in the "
            "first filename; order files from earliest to latest"
        )

    # process_parsivel accepts one file or directory, not an explicit file list.
    # A temporary directory of links preserves the user's exact selection while
    # allowing the complete interval to be decoded in one backend invocation.
    with TemporaryDirectory(prefix="gv_tools_parsivel_") as staging_name:
        staging = Path(staging_name)
        for index, path in enumerate(files):
            (staging / f"{index:06d}_{path.name}").symlink_to(path)
        daily = getattr(adapter, method)(
            staging,
            _date_interval=(start_date, end_date),
            **options,
        )
    products = [daily[day] for day in sorted(daily)]
    if not products:
        raise ValueError("the supplied Parsivel files contain no valid observations")
    return products


def discover_aio(files, **metadata_options):
    """Return dates in explicitly supplied RM Young or Met One AIO files."""
    paths = _resolve_files(files)
    return _discover(_aio_adapter(paths, **metadata_options), paths)


def read_aio_raw(files, **options):
    """Read and merge RM Young or Met One AIO files into one raw product."""
    paths = _resolve_files(files)
    adapter_options = _take_adapter_options(options)
    return _merge_raw(_daily_results(_aio_adapter(paths, **adapter_options), paths, "read_raw", **options))


def _aio_dataframe(dataset):
    frame = dataset.to_dataframe().reset_index()
    frame.attrs.update(dataset.attrs)
    return frame


def _ws800_common_xarray(frame):
    dataset = frame.set_index("time").to_xarray()
    dataset.attrs.update(frame.attrs)
    units = {"air_temperature": "degree_Celsius", "relative_humidity": "percent",
             "air_pressure": "hPa", "wind_speed": "m s-1",
             "wind_from_direction": "degree"}
    for name, unit in units.items():
        dataset[name].attrs["units"] = unit
    return dataset


def read_aio(files, *, XARRAY=False, **options):
    """Read AIO files as pandas (default) or xarray with ``XARRAY=True``."""
    paths = _resolve_files(files)
    adapter_options = _take_adapter_options(options)
    adapter = _aio_adapter(paths, **adapter_options)
    if _aio_family(paths) == "lufft_ws800":
        products = _daily_results(adapter, paths, "read_raw", **options)
        frame = ws800_dataframe(_merge_frame([item.observations for item in products]), common_only=True)
        frame.attrs.update(adapter.metadata.to_attrs())
        return _ws800_common_xarray(frame) if XARRAY else frame
    datasets = _daily_results(adapter, paths, "read", **options)
    dataset = _merge_datasets(datasets, paths)
    return dataset if XARRAY else _aio_dataframe(dataset)


def read_ws800_full(files, *, XARRAY=False, **options):
    """Read and merge every field from Lufft WS800 files as pandas or xarray.

    Pandas is returned by default. Pass ``XARRAY=True`` for a normalized
    :class:`xarray.Dataset`.
    """
    paths = _resolve_files(files)
    if _aio_family(paths) != "lufft_ws800":
        raise ValueError("files are not recognized PIERS Lufft WS800 CSVs")
    adapter_options = _take_adapter_options(options)
    adapter = _lufft_adapter(paths, **adapter_options)
    if XARRAY:
        datasets = _daily_results(adapter, paths, "read", **options)
        return _merge_datasets(datasets, paths)
    products = _daily_results(adapter, paths, "read_raw", **options)
    frame = ws800_dataframe(_merge_frame([item.observations for item in products]))
    frame.attrs.update(adapter.metadata.to_attrs())
    return frame


def discover_metone(files, **metadata_options):
    """Compatibility wrapper for :func:`discover_aio`."""
    paths = _resolve_files(files)
    return discover_aio(paths, **metadata_options)


def read_metone_raw(files, **options):
    """Compatibility wrapper for :func:`read_aio_raw`."""
    paths = _resolve_files(files)
    return read_aio_raw(paths, **options)


def read_metone(files, **options):
    """Compatibility wrapper for :func:`read_aio`."""
    paths = _resolve_files(files)
    return read_aio(paths, **options)


def discover_parsivel(files, **metadata_options):
    """Return dates in the explicitly supplied Parsivel files."""
    paths = _resolve_files(files)
    return _discover_parsivel(_parsivel_adapter(paths, **metadata_options), paths)


def read_parsivel_raw(files, **options):
    """Read and merge explicitly supplied Parsivel files into one raw product."""
    paths = _resolve_files(files)
    adapter_options = _take_adapter_options(options, parsivel=True)
    return _merge_raw(_parsivel_results(
        _parsivel_adapter(paths, **adapter_options), paths, "read_raw", **options
    ))


def read_parsivel(files, **options):
    """Read and merge every explicitly supplied Parsivel file."""
    paths = _resolve_files(files)
    adapter_options = _take_adapter_options(options, parsivel=True)
    datasets = _parsivel_results(
        _parsivel_adapter(paths, **adapter_options), paths, "read", **options
    )
    return _merge_datasets(datasets, paths)


def read_radar(radar_file, *, XRADAR=False, **reader_options):
    """Read one compressed or uncompressed radar file.

    The file format is detected from its content, including SIGMET/IRIS,
    NEXRAD Level II, and CF/Radial NetCDF. ``.gz``, ``.bz2``, and ZIP
    compression are handled transparently. The default reads directly with
    ARM Py-ART. ``XRADAR=True`` loads through xradar, converts the resulting
    DataTree with ``tree.pyart.to_radar()``, and returns the Py-ART Radar.
    """
    if isinstance(radar_file, (list, tuple, set)):
        raise TypeError("radar_file must be one filename, not a list")
    return ingest_radar(radar_file, XRADAR=XRADAR, **reader_options)


def inspect_radar(radar_file):
    """Return the automatically detected ingest route for one radar file."""
    if isinstance(radar_file, (list, tuple, set)):
        raise TypeError("radar_file must be one filename, not a list")
    return inspect_radar_file(radar_file)
