"""Content-aware radar ingest using ARM Py-ART."""

from __future__ import annotations

import bz2
from contextlib import contextmanager
from dataclasses import dataclass
import gzip
from importlib import import_module
from pathlib import Path
import shutil
import tempfile
from typing import Any
import warnings
import zipfile

import numpy as np


@dataclass(frozen=True, slots=True)
class RadarIngestRoute:
    """The input family and Py-ART reader selected for a radar file."""

    family: str
    file_format: str
    reader: str


_NETCDF3_SIGNATURE = b"CDF"
_HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
_SIGMET_SIGNATURE = b"\x1b"
_NEXRAD_LEVEL2_SIGNATURES = (b"AR2V", b"ARCHIVE2.")
_GZIP_SIGNATURE = b"\x1f\x8b"
_BZIP2_SIGNATURE = b"BZh"
_ZIP_SIGNATURE = b"PK\x03\x04"


def _pyart() -> Any:
    try:
        return import_module("pyart")
    except ImportError as exc:
        raise ImportError(
            "Radar ingest requires arm-pyart; install GV Tools with the "
            "'radar' extra"
        ) from exc


def _xradar() -> Any:
    try:
        return import_module("xradar")
    except ImportError as exc:
        raise ImportError(
            "XRADAR=True requires xradar; install GV Tools with the 'radar' extra"
        ) from exc


def _source(path: str | Path) -> Path:
    source = Path(path).expanduser()
    if not source.is_absolute():
        raise ValueError(f"radar input filename must be fully qualified: {source}")
    if not source.is_file():
        raise FileNotFoundError(f"radar input is not a file: {source}")
    return source


def _zip_member(archive: zipfile.ZipFile, source: Path) -> zipfile.ZipInfo:
    members = [item for item in archive.infolist() if not item.is_dir()]
    if len(members) != 1:
        raise ValueError(
            f"radar ZIP archive must contain exactly one file; found {len(members)}: {source}"
        )
    return members[0]


def _uncompressed_signature(source: Path) -> bytes:
    with source.open("rb") as stream:
        outer = stream.read(12)
    if outer.startswith(_GZIP_SIGNATURE):
        with gzip.open(source, "rb") as stream:
            return stream.read(12)
    if outer.startswith(_BZIP2_SIGNATURE):
        with bz2.open(source, "rb") as stream:
            return stream.read(12)
    if outer.startswith(_ZIP_SIGNATURE):
        with zipfile.ZipFile(source) as archive:
            with archive.open(_zip_member(archive, source)) as stream:
                return stream.read(12)
    return outer


def inspect_radar_file(path: str | Path) -> RadarIngestRoute:
    """Inspect file bytes and return the supported radar ingest route.

    Raw ``np1`` files are SIGMET/IRIS volumes, NPOL1 products are CF/Radial
    NetCDF files, and WSR-88D files are NEXRAD Level-II archives. Detection
    intentionally uses format signatures rather than extensions because
    operational archives do not always preserve names.
    """
    source = _source(path)
    signature = _uncompressed_signature(source)

    if signature.startswith(_SIGMET_SIGNATURE):
        return RadarIngestRoute("np1", "SIGMET", "read_sigmet")
    if signature.startswith(_NEXRAD_LEVEL2_SIGNATURES):
        return RadarIngestRoute("WSR-88D", "NEXRAD Level II", "read_nexrad_archive")
    if signature.startswith(_NETCDF3_SIGNATURE):
        return RadarIngestRoute("NPOL1", "NetCDF3", "read_cfradial")
    if signature.startswith(_HDF5_SIGNATURE):
        return RadarIngestRoute("NPOL1", "NetCDF4/HDF5", "read_cfradial")

    preview = signature[:8].hex(" ") or "<empty>"
    raise ValueError(
        "unsupported radar format; expected raw np1 (SIGMET/IRIS), "
        "WSR-88D (NEXRAD Level II), or NPOL1 (CF/Radial NetCDF), "
        f"first bytes: {preview}"
    )


@contextmanager
def _pyart_input(source: Path):
    """Yield an ordinary file path suitable for every Py-ART reader."""
    with source.open("rb") as stream:
        signature = stream.read(4)
    if not signature.startswith((_GZIP_SIGNATURE, _BZIP2_SIGNATURE, _ZIP_SIGNATURE)):
        yield source
        return

    with tempfile.TemporaryDirectory(prefix="gv_tools_radar_") as directory:
        if signature.startswith(_GZIP_SIGNATURE):
            name = source.name.removesuffix(".gz") or "radar"
            opened = gzip.open(source, "rb")
        elif signature.startswith(_BZIP2_SIGNATURE):
            name = source.name.removesuffix(".bz2") or "radar"
            opened = bz2.open(source, "rb")
        else:
            archive = zipfile.ZipFile(source)
            member = _zip_member(archive, source)
            name = Path(member.filename).name or "radar"
            opened = archive.open(member)
        target = Path(directory) / name
        try:
            with opened, target.open("wb") as output:
                shutil.copyfileobj(opened, output)
            yield target
        finally:
            if signature.startswith(_ZIP_SIGNATURE):
                archive.close()


def _datatree_scan_type(tree: Any) -> str | None:
    sweeps = [node.dataset for name, node in tree.children.items() if name.startswith("sweep_")]
    if not sweeps:
        return None
    elevations = []
    azimuth_spans = []
    elevation_spans = []
    for dataset in sweeps:
        if "elevation" not in dataset.coords or "azimuth" not in dataset.coords:
            continue
        elevation = np.asarray(dataset.elevation.values, dtype=float)
        azimuth = np.asarray(dataset.azimuth.values, dtype=float)
        elevations.extend(elevation[np.isfinite(elevation)])
        if np.isfinite(azimuth).any():
            azimuth_spans.append(float(np.nanmax(azimuth) - np.nanmin(azimuth)))
        if np.isfinite(elevation).any():
            elevation_spans.append(float(np.nanmax(elevation) - np.nanmin(elevation)))
    if elevations and np.nanmedian(elevations) >= 85.0:
        return "BB"
    if azimuth_spans and elevation_spans:
        if np.nanmedian(azimuth_spans) < 10.0 and np.nanmedian(elevation_spans) > 10.0:
            return "RHI"
        return "PPI"
    return None


def _scan_type(radar: Any, source: Path) -> str:
    """Return a concise PPI, RHI, BB, or UNKNOWN scan classification."""
    name = source.name.lower()
    tokens = name.replace("-", "_").replace(".", "_").split("_")
    declared = str(getattr(radar, "scan_type", "")).strip().lower()
    if declared == "rhi":
        return "RHI"
    if declared in {"bb", "birdbath", "bird_bath", "vertical_pointing"}:
        return "BB"
    if "bb" in tokens or "birdbath" in tokens or "bird" in tokens and "bath" in tokens:
        return "BB"

    if hasattr(radar, "children"):
        detected = _datatree_scan_type(radar)
        if detected:
            return detected

    elevation = getattr(radar, "elevation", None)
    if isinstance(elevation, dict) and "data" in elevation:
        values = np.ma.asarray(elevation["data"]).compressed()
        if values.size and np.nanmedian(values) >= 85.0:
            return "BB"
    if declared == "ppi":
        return "PPI"
    return "UNKNOWN"


def _prepare_pyart_info(radar: Any) -> None:
    """Make xradar-converted metadata compatible with Py-ART ``Radar.info``."""
    radar_class = import_module("pyart.core").Radar
    if not hasattr(type(radar), "info"):
        type(radar)._dic_info = radar_class._dic_info
        type(radar).info = radar_class.info
    for group_name in ("instrument_parameters", "radar_calibration"):
        group = getattr(radar, group_name, None)
        if isinstance(group, dict):
            for name, value in tuple(group.items()):
                if not isinstance(value, dict):
                    group[name] = {"data": np.asarray(value)}
    for optional_attribute in (
        "altitude_agl", "antenna_transition", "radar_calibration",
        "scan_rate", "target_scan_rate", "rotation", "tilt", "roll",
        "drift", "heading", "pitch", "heading_change_rate",
        "pitch_change_rate", "roll_change_rate", "eastward_wind",
        "northward_wind", "vertical_wind", "eastward_velocity",
        "northward_velocity", "vertical_velocity", "georefs_applied",
    ):
        if not hasattr(radar, optional_attribute):
            setattr(radar, optional_attribute, None)


def ingest_radar(path: str | Path, *, XRADAR: bool = False, **reader_options: Any) -> Any:
    """Read a supported radar file with the content-selected Py-ART reader.

    Parameters after *path* are forwarded unchanged to ``read_sigmet``,
    ``read_nexrad_archive``, or ``read_cfradial``. The returned object is a
    :class:`pyart.core.Radar`.
    """
    source = _source(path)
    route = inspect_radar_file(source)
    use_xradar = XRADAR
    if XRADAR and route.reader == "read_nexrad_archive":
        warnings.warn(
            "XRADAR=True cannot reliably convert multi-sweep NEXRAD Level-II "
            "volumes with unequal gate counts to a Py-ART Radar; using Py-ART "
            "read_nexrad_archive instead",
            UserWarning,
            stacklevel=2,
        )
        use_xradar = False
    if use_xradar and "file_field_names" in reader_options:
        warnings.warn(
            "file_field_names is a Py-ART reader option and is ignored when "
            "XRADAR=True",
            UserWarning,
            stacklevel=2,
        )
        reader_options.pop("file_field_names")
    with _pyart_input(source) as pyart_path:
        if use_xradar:
            reader_name = {
                "read_sigmet": "open_iris_datatree",
                "read_nexrad_archive": "open_nexradlevel2_datatree",
                "read_cfradial": "open_cfradial1_datatree",
            }[route.reader]
            reader = getattr(_xradar().io, reader_name)
            tree = reader(str(pyart_path), **reader_options)
            tree.load()
        else:
            reader = getattr(_pyart().io, route.reader)
            radar = reader(str(pyart_path), **reader_options)
    if use_xradar:
        scan_type = _scan_type(tree, source)
        import_module("pyart.xradar")  # registers DataTree.pyart
        radar = tree.pyart.to_radar()
        _prepare_pyart_info(radar)
        if scan_type in {"PPI", "RHI"}:
            radar.scan_type = scan_type.lower()
    else:
        scan_type = _scan_type(radar, source)
    if hasattr(radar, "metadata") and isinstance(radar.metadata, dict):
        radar.metadata["gv_tools_scan_type"] = scan_type
        # netCDF4 does not support Boolean attributes. Keep the public flag
        # truth-testable while ensuring a Radar returned here can be written
        # directly with pyart.io.write_cfradial().
        radar.metadata["XRADAR"] = int(use_xradar)
    print(f"Radar scan type: {scan_type}")
    return radar
