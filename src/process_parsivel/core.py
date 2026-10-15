"""Core Parsivel parsing and derived-product calculations."""

from __future__ import annotations

import concurrent.futures
import logging
import os
import re
import shutil
import sys
import warnings
from importlib.resources import files as resource_files
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import numpy as np
import pandas as pd
import xarray as xr

LOGGER = logging.getLogger(__name__)


def load_tables(table_dir: str | os.PathLike[str] | None = None):
    """Load diameter/velocity parameters and the conditional mask."""
    root = Path(table_dir) if table_dir else resource_files("process_parsivel").joinpath("tables")
    dv = pd.read_csv(root.joinpath("parsivel_diameter_py.txt"), sep=r"\s+")
    mask = pd.read_csv(root.joinpath("parsivel_conditional_matrix.txt"), header=None)
    required = {"Drop_bin", "Measured_Vt", "Theoretical_Vt", "Delta-D"}
    missing = required.difference(dv.columns)
    if missing:
        raise ValueError(f"Diameter table is missing columns: {sorted(missing)}")
    if len(dv) != 32 or mask.shape[0] != 32 or mask.shape[1] < 32:
        raise ValueError(f"Expected 32 bins and at least a 32x32 mask; got {len(dv)} and {mask.shape}")
    return dv, mask


def _parse_data_string(value: object) -> np.ndarray | None:
    if not isinstance(value, str):
        return None
    row = value.split(",")
    if len(row) < 1034:
        return None
    parsed = []
    for raw in row[9:1033]:
        cleaned = raw.replace("00 0", "000").strip()
        try:
            parsed.append(float(cleaned) if cleaned and cleaned != "None" else 0.0)
        except (TypeError, ValueError):
            parsed.append(0.0)
    return np.asarray(parsed, dtype=np.float64) if len(parsed) == 1024 else None


def get_dataset_from_parsivel(path, year, month, day, dv_parms, order="F"):
    """Read a concatenated Parsivel file for one date."""
    frame = pd.read_csv(
        path, sep=";", header=None, names=["datetime", "data"], engine="python",
        on_bad_lines="skip", dtype=str,
    )
    if frame.empty:
        return None, None
    target = f"{year}{month}{day}"
    frame["datetime"] = frame["datetime"].str.strip()
    frame = frame[frame["datetime"].str.startswith(target, na=False)]
    valid_rows = []
    valid_dates = []
    for date_value, data_value in frame[["datetime", "data"]].itertuples(index=False, name=None):
        parsed = _parse_data_string(data_value)
        timestamp = pd.to_datetime(date_value, format="%Y%m%d%H%M%S", errors="coerce")
        if parsed is not None and not pd.isna(timestamp):
            valid_rows.append(parsed)
            valid_dates.append(timestamp)
    if not valid_rows:
        LOGGER.warning("No valid rows for %s in %s", target, path)
        return None, None
    rows = np.stack(valid_rows)
    data = np.stack([row.reshape((32, 32), order=order) for row in rows], axis=0)
    dataset = xr.Dataset(
        {"drops": (["time", "Diam", "Vel"], data)},
        coords={
            "time": pd.DatetimeIndex(valid_dates),
            "Diam": dv_parms["Drop_bin"].to_numpy(),
            "Vel": dv_parms["Measured_Vt"].to_numpy(),
        },
        attrs={"description": "Parsivel data"},
    )
    return dataset, data


SUPPORTED_INPUT_SUFFIXES = {".zip", ".csv", ".dat"}
DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")


def _safe_extract(zip_path: Path, target: Path) -> list[Path]:
    extracted = []
    try:
        with ZipFile(zip_path) as archive:
            for member in archive.infolist():
                name = Path(member.filename)
                if member.is_dir() or name.suffix.lower() not in {".csv", ".dat"} or name.is_absolute() or ".." in name.parts:
                    continue
                destination = target / name.name
                with archive.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
                extracted.append(destination)
    except (BadZipFile, OSError) as exc:
        LOGGER.warning("Skipping unreadable archive %s: %s", zip_path, exc)
    return extracted


def unzip_files_parallel(zip_files, instrument, year, month, day, temp_root=None):
    if not zip_files:
        return [], None
    root = Path(temp_root or ".") / "tmp" / instrument / f"{year}{month}{day}"
    root.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(zip_files))) as pool:
        groups = pool.map(lambda item: _safe_extract(Path(item), root), zip_files)
    return [str(path) for group in groups for path in group], root


def concatenate_files(paths, instrument, year, month, day, temp_root=None):
    if not paths:
        raise ValueError("Cannot concatenate an empty file list")
    root = Path(temp_root or ".") / "tmp" / instrument / f"{year}{month}{day}"
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "combined_input.csv"
    with destination.open("wb") as output:
        for path in paths:
            with Path(path).open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    return destination, root


def get_integral_parameters(instrument, ds_1min, df_mask, dv_parms):
    """Calculate parameters, PSD, and moments using the legacy formulas."""
    drops = ds_1min["drops"].transpose("time", "Diam", "Vel").to_numpy().astype(float, copy=True)
    mask = np.rot90(np.flip(df_mask.to_numpy()[:, :-1], 1), 1)
    if mask.shape != (32, 32) or drops.shape[1:] != (32, 32):
        raise ValueError(f"Expected drop and mask grids of 32x32; got {drops.shape[1:]} and {mask.shape}")
    drops[:, mask == 0] = 0
    diam = dv_parms["Drop_bin"].to_numpy(float)
    velocity = dv_parms["Theoretical_Vt"].to_numpy(float)
    delta = dv_parms["Delta-D"].to_numpy(float)
    cross_section = 180.0 * (30.0 - diam / 2.0)
    volume = np.pi * diam**3 / 6.0
    denominator = 60.0 * cross_section[:, None] * velocity[None, :]
    dsd_denominator = 60.0 * (cross_section / 100.0)[:, None] * velocity[None, :] * delta[:, None] * 100.0
    if np.any(denominator <= 0) or np.any(dsd_denominator <= 0):
        raise ValueError("Tables produce a non-positive calculation denominator")
    total = drops.sum(axis=(1, 2)).astype(np.int64)
    dsd = (1e6 * drops / dsd_denominator).sum(axis=2)
    concentration = (1e6 * drops / denominator).sum(axis=(1, 2))
    lwc = (1e3 * drops * volume[None, :, None] / denominator).sum(axis=(1, 2))
    z = (1e6 * drops * diam[None, :, None] ** 6 / denominator).sum(axis=(1, 2))
    rain = (drops * volume[None, :, None] * 60.0 / cross_section[None, :, None]).sum(axis=(1, 2))
    moments = np.stack([
        (1e6 * drops * diam[None, :, None] ** power / denominator).sum(axis=(1, 2))
        for power in range(8)
    ], axis=1)
    dm = np.divide(moments[:, 4], moments[:, 3], out=np.zeros(len(moments)), where=moments[:, 3] > 0)
    dm[(dm < 0) | (dm > 20)] = 0
    present = drops.any(axis=2)
    last_index = np.where(present, np.arange(32), -1).max(axis=1)
    dmax = np.where(last_index >= 0, diam[np.maximum(last_index, 0)], 0)
    diff = (diam[None, :, None] - dm[:, None, None]) ** 2
    sig1 = (diff * diam[None, :, None] ** 3 * 1e6 * drops / denominator).sum(axis=(1, 2))
    sig2 = (diam[None, :, None] ** 3 * 1e6 * drops / denominator).sum(axis=(1, 2))
    sigma = np.divide(sig1, sig2, out=np.zeros(len(sig1)), where=(sig2 > 0) & (dm != 0))
    sigma[(sigma < 0) | (sigma > 20)] = 0
    dbz = np.zeros_like(z)
    np.log10(z, out=dbz, where=z > 0)
    dbz *= 10
    dbz = np.maximum(dbz, 0)  # Retains the supplied script's output convention.
    index = ds_1min.time.to_numpy()
    parms = pd.DataFrame({
        "Total Drops": total, "Concentration": concentration, "LWC": lwc,
        "Z": z, "dBZ": dbz, "Rain": rain, "Dm": dm, "Dmax": dmax,
        "Sigma_M": sigma,
    }, index=index)
    psd = pd.DataFrame(dsd, index=index, columns=diam)
    moment_frame = pd.DataFrame(moments, index=index, columns=[f"M{i}" for i in range(8)])
    return parms, psd, moment_frame


def process_parsivel_day(instrument, input_dir, year, month, day, *, table_dir=None, temp_root=None):
    dv, mask = load_tables(table_dir)
    base = Path(input_dir)
    upper = instrument.upper()
    if "PIERS" in upper:
        pattern = base / "PIERS_Gauges" / instrument / year / month / day / f"{instrument}_Parsivel_{year}{month}{day}*.zip"
    elif "apu" in instrument.lower():
        pattern = base / "apu" / instrument / f"{year}{month}" / f"{instrument}_{year}{month}{day}*.zip"
    else:
        raise ValueError("Instrument name must identify an APU or PIERS platform")
    import glob
    archives = sorted(glob.glob(str(pattern)))
    extracted, temp_dir = unzip_files_parallel(archives, instrument, year, month, day, temp_root)
    if not extracted:
        LOGGER.warning("No input files found: %s", pattern)
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    try:
        combined, _ = concatenate_files(extracted, instrument, year, month, day, temp_root)
        dataset, _ = get_dataset_from_parsivel(combined, year, month, day, dv, order="F")
        if dataset is None:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        dataset = dataset.sortby("time").resample(time="1min").sum().fillna(0)
        return get_integral_parameters(instrument, dataset, mask, dv)
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def discover_input_dates(input_path):
    """Return valid dates found in supported input filenames, recursively."""
    path = Path(input_path).expanduser()
    candidates = [path] if path.is_file() else (
        [item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in SUPPORTED_INPUT_SUFFIXES]
        if path.is_dir() else []
    )
    dates = set()
    for candidate in candidates:
        for match in DATE_PATTERN.finditer(candidate.name):
            try:
                dates.add(pd.Timestamp(year=int(match[1]), month=int(match[2]), day=int(match[3])))
            except ValueError:
                continue
    return sorted(dates)


def _files_for_date(input_path, date_text):
    path = Path(input_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Input does not exist: {path}")
    if path.is_file():
        if path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
            raise ValueError(f"Unsupported input type {path.suffix!r}; use ZIP, CSV, or DAT")
        return [path]
    files = sorted(
        item for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in SUPPORTED_INPUT_SUFFIXES and date_text in item.name
    )
    if not files:
        LOGGER.warning("No ZIP, CSV, or DAT files named with date %s under %s", date_text, path)
    return files


def process_input(input_path, instrument, year, month, day, *, table_dir=None, temp_root=None):
    """Process a single ZIP/CSV/DAT file or a recursively scanned directory.

    Directory inputs select files containing YYYYMMDD in their filename. A
    single file is filtered by timestamps inside that file, so it may contain
    records from more than one day.
    """
    dv, mask = load_tables(table_dir)
    date_text = f"{year}{month}{day}"
    selected = _files_for_date(input_path, date_text)
    if not selected:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    temp_base = Path(temp_root or ".")
    work_dir = temp_base / "tmp" / instrument / date_text
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        archives = [item for item in selected if item.suffix.lower() == ".zip"]
        raw_files = [item for item in selected if item.suffix.lower() in {".csv", ".dat"}]
        for archive in archives:
            raw_files.extend(_safe_extract(archive, work_dir))
        if not raw_files:
            LOGGER.warning("No CSV or DAT records found for %s", date_text)
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        combined, _ = concatenate_files(raw_files, instrument, year, month, day, temp_root)
        dataset, _ = get_dataset_from_parsivel(combined, year, month, day, dv, order="F")
        if dataset is None:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        one_minute = dataset.sortby("time").resample(time="1min").sum().fillna(0)
        return get_integral_parameters(instrument, one_minute, mask, dv)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def save_dataframes(parms, psd, moments, instrument, year, month, day, output_dir):
    target = Path(output_dir) / "apu" / instrument / year / f"{month}{day}"
    target.mkdir(parents=True, exist_ok=True)
    result = []
    for label, frame in (("parms", parms), ("psd", psd), ("moments", moments)):
        path = target / f"{instrument}_{year}_{month}{day}_{label}.csv"
        frame.to_csv(path, index=True, float_format="%.6g")
        result.append(str(path))
    return tuple(result)


def save_dataframes_to_netcdf(
    parms,
    psd,
    moments,
    output_dir,
    site,
    instrument,
    year,
    month,
    day,
    *,
    engine="auto",
    compression=True,
    complevel=4,
    overwrite=True,
    location=None,
):
    """Save parameters, PSD, and moments to one verified NetCDF file.

    Raises a descriptive ``RuntimeError`` when the directory cannot be created,
    the optional backend is unavailable, writing fails, or no non-empty file is
    produced. On success, logs and returns the exact output filename.
    """
    frames = {"parms": parms, "psd": psd, "moments": moments}
    for name, frame in frames.items():
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError(f"{name} must be a non-empty pandas DataFrame")
    if not parms.index.equals(psd.index) or not parms.index.equals(moments.index):
        raise ValueError("parms, psd, and moments must have identical time indexes")
    if not isinstance(complevel, int) or not 0 <= complevel <= 9:
        raise ValueError("complevel must be an integer from 0 through 9")
    target = (
        Path(output_dir).expanduser()
        / "NetCDF"
        / str(instrument)
        / str(year)
        / str(month)
    )
    path = target / f"{site}_{instrument}_{year}_{month}{day}_derived.nc"
    ds = None
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Could not create NetCDF output directory {target}: {exc}"
        ) from exc
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"NetCDF output already exists and overwrite=False: {path}"
        )
    try:
        time = pd.to_datetime(parms.index)
        ds = xr.Dataset(
            coords={
                "time": time,
                "drop_size": psd.columns.astype(float),
                "moment": np.arange(moments.shape[1]),
            }
        )
        for column in parms.columns:
            ds[column.replace(" ", "_")] = ("time", parms[column].to_numpy())
        ds["PSD"] = (["time", "drop_size"], psd.to_numpy())
        ds["Moments"] = (["time", "moment"], moments.to_numpy())
        ds.attrs.update(
            site=str(site),
            instrument=str(instrument),
            date=f"{year}-{month}-{day}",
            description="Parsivel derived parameters, PSD, and moments",
        )
        if location is not None:
            ds.attrs["location_status"] = str(location["location_status"])
            ds.attrs["location_source"] = str(location["location_source"])
            ds.attrs["location_query_date"] = str(location["location_query_date"])
            if "latitude" in location:
                ds = ds.assign_coords(
                    latitude=float(location["latitude"]),
                    longitude=float(location["longitude"]),
                    elevation=float(location["elevation"]),
                )
                ds.coords["latitude"].attrs.update(
                    standard_name="latitude", long_name="instrument latitude", units="degrees_north"
                )
                ds.coords["longitude"].attrs.update(
                    standard_name="longitude", long_name="instrument longitude", units="degrees_east"
                )
                ds.coords["elevation"].attrs.update(
                    standard_name="height_above_mean_sea_level",
                    long_name="instrument elevation",
                    units="m",
                )
                for key in (
                    "city",
                    "state",
                    "location_start_date",
                    "location_end_date",
                    "location_timeline_num_files",
                ):
                    ds.attrs[key] = location[key]
        encoding = None
        if compression:
            encoding = {
                name: {"zlib": True, "complevel": complevel, "shuffle": True}
                for name in ds.data_vars
            }
        engines = ("h5netcdf", "netcdf4") if engine == "auto" else (engine,)
        errors = []
        selected_engine = None
        for candidate in engines:
            try:
                ds.attrs["writer_engine"] = candidate
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "error",
                        message="numpy.ndarray size changed.*",
                        category=RuntimeWarning,
                    )
                    ds.to_netcdf(
                        path,
                        mode="w",
                        format="NETCDF4",
                        engine=candidate,
                        encoding=encoding,
                    )
                selected_engine = candidate
                break
            except Exception as exc:
                errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
        if selected_engine is None:
            detail = "; ".join(errors)
            raise RuntimeError(
                f"No usable NetCDF backend. Attempts: {detail}. Install compatible "
                f"backends in this kernel with: {sys.executable} -m pip install "
                f"--upgrade h5netcdf h5py netCDF4"
            )
    except Exception as exc:
        raise RuntimeError(f"Failed to write NetCDF file {path}: {exc}") from exc
    finally:
        if ds is not None:
            ds.close()
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(
            f"NetCDF writing completed without producing a non-empty file: {path}"
        )
    LOGGER.info(
        "Saved NetCDF with %s: %s (%s bytes)",
        selected_engine,
        path,
        f"{path.stat().st_size:,}",
    )
    return str(path)
