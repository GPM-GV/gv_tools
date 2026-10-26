"""Core Parsivel parsing and derived-product calculations."""

from __future__ import annotations

import concurrent.futures
import logging
import os
import re
import shutil
from importlib.resources import files as resource_files
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import numpy as np
import pandas as pd
import xarray as xr

LOGGER = logging.getLogger(__name__)


def load_tables(table_dir: str | os.PathLike[str] | None = None):
    """Load diameter/velocity parameters and the conditional mask."""
    root = Path(table_dir) if table_dir else resource_files("gv_tools").joinpath("data", "parsivel")
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
DATE_PATTERN = re.compile(
    r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"
    r"(?:_?(?:[01]\d|2[0-3]))?(?!\d)"
)


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
        # Avoid an optional flox/numpy-groupies acceleration path. Some valid
        # Anaconda installations cannot initialize its Numba disk cache, while
        # xarray's native resampler is sufficient for these daily files.
        with xr.set_options(use_flox=False):
            one_minute = dataset.sortby("time").resample(time="1min").sum().fillna(0)
        return get_integral_parameters(instrument, one_minute, mask, dv)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run(input_path, instrument, *, start_date=None, end_date=None, table_dir=None, temp_root=None):
    """Decode selected dates and return in-memory DataFrames only."""
    dates = discover_input_dates(input_path)
    if start_date is not None:
        dates = [value for value in dates if value >= pd.Timestamp(start_date)]
    if end_date is not None:
        dates = [value for value in dates if value <= pd.Timestamp(end_date)]
    results = {}
    for value in dates:
        frames = process_input(
            input_path,
            instrument,
            f"{value.year:04d}",
            f"{value.month:02d}",
            f"{value.day:02d}",
            table_dir=table_dir,
            temp_root=temp_root,
        )
        if any(not frame.empty for frame in frames):
            results[value.strftime("%Y-%m-%d")] = frames
    return results


