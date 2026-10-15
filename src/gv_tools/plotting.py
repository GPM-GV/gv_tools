"""User-directed plotting helpers for pandas and xarray objects."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import xarray as xr


def plot_instrument_timeseries(
    data: pd.DataFrame | xr.Dataset,
    fields: str | Sequence[str],
    output: str | Path,
    *,
    time: str = "time",
    title: str | None = None,
    ylabel: str | None = None,
    colors: dict[str, str] | None = None,
    linewidth: float = 1.2,
    figsize: tuple[float, float] = (12, 5),
    dpi: int = 150,
    grid: bool = True,
    legend: bool = True,
    xlim=None,
    ylim=None,
    figure_options: dict | None = None,
    savefig_options: dict | None = None,
):
    """Plot selected instrument fields against time and save the figure.

    The function performs no resampling, averaging, correction, or other
    analysis. It returns the editable ``(figure, axis)`` pair after saving.
    """
    destination = Path(output).expanduser()
    if not destination.name or not destination.suffix:
        raise ValueError("output must include an image filename with an extension")
    names = [fields] if isinstance(fields, str) else list(fields)
    if not names:
        raise ValueError("fields must contain at least one field name")
    if isinstance(data, xr.Dataset):
        missing = [name for name in names if name not in data]
        if missing:
            raise KeyError(f"dataset is missing fields: {missing}")
        frame = data[names].to_dataframe().reset_index()
    elif isinstance(data, pd.DataFrame):
        missing = [name for name in names if name not in data.columns]
        if missing:
            raise KeyError(f"dataframe is missing fields: {missing}")
        frame = data.reset_index() if time not in data.columns else data.copy()
    else:
        raise TypeError("data must be a pandas DataFrame or xarray Dataset")
    if time not in frame.columns:
        candidates = [name for name in frame.columns if pd.api.types.is_datetime64_any_dtype(frame[name])]
        if len(candidates) != 1:
            raise ValueError(f"could not identify time coordinate {time!r}")
        time = candidates[0]
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=figsize, **(figure_options or {}))
    palette = colors or {}
    for name in names:
        axis.plot(frame[time], frame[name], label=name, color=palette.get(name), linewidth=linewidth)
    axis.set_title(title or "Time series")
    axis.set_xlabel(time)
    axis.set_ylabel(ylabel or "Value")
    axis.grid(grid, alpha=0.3)
    if xlim is not None:
        axis.set_xlim(*xlim)
    if ylim is not None:
        axis.set_ylim(*ylim)
    if legend:
        axis.legend()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=dpi, bbox_inches="tight", **(savefig_options or {}))
    return figure, axis
