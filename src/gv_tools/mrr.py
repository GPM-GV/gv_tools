"""Readers for METEK Micro Rain Radar products."""

from __future__ import annotations

from collections.abc import Sequence
from glob import glob
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

import numpy as np
import xarray as xr


_MRR2_VARIABLES = frozenset(
    {
        "MRR_H",
        "MRR_TF",
        "MRR_F",
        "MRR_D",
        "MRR_N",
        "MRR_K",
        "MRR_Capital_Z",
        "MRR_Small_z",
        "MRR_PIA",
        "MRR_RR",
        "MRR_LWC",
        "MRR_W",
    }
)
_MRRPRO_VARIABLES = frozenset(
    {
        "Za",
        "Z",
        "Zea",
        "Ze",
        "RR",
        "LWC",
        "PIA",
        "VEL",
        "WIDTH",
        "SNR",
        "spectrum_raw",
        "N",
        "D",
        "range",
        "time",
    }
)
_MRRPRO_POSTPROCESSED_VARIABLES = frozenset(
    {
        "reflectivity_factor",
        "radial_velocity",
        "spectrum_width",
        "spectrum_skewness",
        "spectrum_kurtosis",
        "signal_to_noise_ratio",
        "range",
        "time",
    }
)
_HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"


def _open_zipped_netcdf(source: Path, **options: Any) -> xr.Dataset:
    """Open and eagerly load the single NetCDF payload in *source*."""
    try:
        with ZipFile(source) as archive:
            members = [
                member
                for member in archive.infolist()
                if not member.is_dir()
                and not member.filename.startswith("__MACOSX/")
                and member.filename.lower().endswith((".nc", ".cdf", ".netcdf"))
            ]
            if len(members) != 1:
                raise ValueError(
                    "an MRR ZIP archive must contain exactly one NetCDF file; "
                    f"found {len(members)}"
                )
            payload = archive.read(members[0])
    except BadZipFile as exc:
        raise ValueError(f"invalid MRR ZIP archive: {source}") from exc

    default_engine = "h5netcdf" if payload.startswith(_HDF5_SIGNATURE) else "scipy"
    engine = options.pop("engine", default_engine)
    try:
        with xr.open_dataset(BytesIO(payload), engine=engine, **options) as opened:
            return opened.load()
    except (ImportError, ModuleNotFoundError) as exc:
        if default_engine == "h5netcdf":
            raise ImportError(
                "zipped MRRPro ingest requires h5netcdf and h5py; install "
                "GV Tools with the 'netcdf' extra"
            ) from exc
        raise


def _identify_model(dataset: xr.Dataset) -> str:
    variables = frozenset(dataset.variables)
    if _MRR2_VARIABLES <= variables:
        return "MRR2"
    if _MRRPRO_VARIABLES <= variables:
        title = str(dataset.attrs.get("title", ""))
        conventions = str(dataset.attrs.get("Conventions", ""))
        if "MRR Pro" in title or conventions.casefold().startswith("cf/radial"):
            return "MRRPro"
    if _MRRPRO_POSTPROCESSED_VARIABLES <= variables:
        source = str(dataset.attrs.get("source", ""))
        if "MRRPro" in source:
            return "MRRPro"

    missing_mrr2 = sorted(_MRR2_VARIABLES.difference(variables))
    missing_mrrpro = sorted(_MRRPRO_VARIABLES.difference(variables))
    missing_postprocessed = sorted(_MRRPRO_POSTPROCESSED_VARIABLES.difference(variables))
    raise ValueError(
        "unsupported MRR product: file matches neither the MRR2 processed-data "
        f"schema (missing {', '.join(missing_mrr2[:3])}) nor the MRRPro "
        f"CF/Radial schema (missing {', '.join(missing_mrrpro[:3])}) nor the "
        "post-processed MRRPro schema "
        f"(missing {', '.join(missing_postprocessed[:3])})"
    )


def _resolve_mrr_files(source: str | Path | Sequence[str | Path]) -> list[Path]:
    """Resolve one file, a directory, a glob, or a sequence to MRR inputs."""
    if isinstance(source, (str, Path)):
        text = str(Path(source).expanduser())
        if any(character in text for character in "*?["):
            files = [Path(match) for match in sorted(glob(text))]
        else:
            path = Path(text)
            files = sorted(path.glob("*.nc")) if path.is_dir() else [path]
    else:
        files = [Path(item).expanduser() for item in source]

    if not files:
        raise FileNotFoundError(f"no MRR input files matched: {source}")
    for file in files:
        if not file.is_absolute():
            raise ValueError(f"MRR input filename must be fully qualified: {file}")
        if not file.is_file():
            raise FileNotFoundError(f"MRR input is not a file: {file}")
    return files


def _read_mrr_file(source: Path, **open_dataset_options: Any) -> xr.Dataset:
    """Open and identify one MRR product."""
    if source.suffix.casefold() == ".zip":
        dataset = _open_zipped_netcdf(source, **open_dataset_options)
    else:
        dataset = xr.open_dataset(source, **open_dataset_options)

    try:
        model = _identify_model(dataset)
        if model == "MRR2":
            dataset = _decode_unix_time(dataset)
        dataset.attrs["mrr_model"] = model
        if _MRRPRO_POSTPROCESSED_VARIABLES <= frozenset(dataset.variables):
            dataset.attrs["mrr_product"] = "post_processed_moments"
        return dataset
    except Exception:
        dataset.close()
        raise


def _decode_unix_time(dataset: xr.Dataset) -> xr.Dataset:
    """Decode the non-CF ``UNIX Time Stamp`` coordinate used by MRR2."""
    if "time" not in dataset.coords:
        raise ValueError("invalid MRR2 product: missing time coordinate")

    time = dataset.coords["time"]
    if str(time.attrs.get("units", "")).casefold() != "unix time stamp":
        return dataset

    values = np.asarray(time.values)
    fill_value = time.encoding.get("_FillValue", time.attrs.get("_FillValue", -9999))
    valid = values != fill_value
    decoded = np.full(values.shape, np.datetime64("NaT"), dtype="datetime64[s]")
    decoded[valid] = values[valid].astype("datetime64[s]")
    dataset = dataset.assign_coords(time=(time.dims, decoded.astype("datetime64[ns]")))
    dataset.coords["time"].attrs.update(
        standard_name="time", long_name="Time (UTC)", timezone="UTC"
    )
    return dataset


def read_mrr(
    file: str | Path | Sequence[str | Path], **open_dataset_options: Any
) -> xr.Dataset:
    """Read one or more MRR2 or MRRPro products into an xarray Dataset.

    ``file`` may be a NetCDF/ZIP file, a directory of ``*.nc`` files, a glob,
    or a sequence of files. Multiple files are loaded and concatenated in
    chronological order along ``time``. Options are forwarded to
    :func:`xarray.open_dataset`.
    MRR2's non-CF Unix timestamp is converted to ``datetime64[ns]`` in UTC;
    MRRPro's CF time coordinate is decoded by xarray. The detected instrument
    model is recorded in the dataset attribute ``mrr_model``.
    """
    sources = _resolve_mrr_files(file)
    if len(sources) == 1:
        return _read_mrr_file(sources[0], **open_dataset_options)

    datasets = []
    try:
        for source in sources:
            opened = _read_mrr_file(source, **open_dataset_options)
            try:
                datasets.append(opened.load())
            finally:
                opened.close()
        models = {dataset.attrs["mrr_model"] for dataset in datasets}
        if len(models) != 1:
            raise ValueError(f"MRR inputs contain mixed instrument models: {sorted(models)}")
        combined = xr.concat(
            datasets,
            dim="time",
            data_vars="minimal",
            coords="minimal",
            compat="override",
            combine_attrs="override",
        ).sortby("time")
        time_index = combined.indexes["time"]
        if time_index.has_duplicates:
            combined = combined.isel(time=~time_index.duplicated(keep="first"))
        combined.attrs["mrr_source_file_count"] = len(sources)
        combined.attrs["mrr_source_files"] = ",".join(str(source) for source in sources)
        return combined
    except Exception:
        for dataset in datasets:
            dataset.close()
        raise
