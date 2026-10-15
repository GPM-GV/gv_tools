"""Convenient Pandas and Xarray loading of processed PIERS++ daily products."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PRODUCTS = {
    "gauge": "gauge_one_minute.csv",
    "aio": "aio_one_minute.csv",
    "parsivel": "parsivel_parameters.csv",
    "parsivel_psd": "parsivel_psd.csv",
    "parsivel_moments": "parsivel_moments.csv",
}


def load_day(path, *, library="pandas"):
    """Load available one-minute products as DataFrames or Xarray Datasets.

    ``path`` is the directory containing ``manifest.json``. Empty products are
    retained as empty DataFrames/Datasets so notebook code can tolerate missing
    field instruments without special file-existence checks.
    """
    root = Path(path).expanduser()
    if not (root / "manifest.json").is_file():
        raise FileNotFoundError(f"No PIERS++ manifest found in {root}")
    frames = {}
    for name, filename in PRODUCTS.items():
        file_path = root / filename
        frame = pd.read_csv(file_path) if file_path.is_file() else pd.DataFrame(columns=["timestamp"])
        if "timestamp" in frame:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frames[name] = frame
    if library == "pandas":
        return frames
    if library != "xarray":
        raise ValueError("library must be 'pandas' or 'xarray'")
    import xarray as xr
    datasets = {}
    for name, frame in frames.items():
        datasets[name] = (
            frame.dropna(subset=["timestamp"]).set_index("timestamp").to_xarray()
            if len(frame) else xr.Dataset()
        )
    return datasets
