"""Generate daily PIERS battery, RSSI, and rain-accumulation plots."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .processing import get_bucket_tips


FIGURE_SIZE = (10, 6)
FIGURE_DPI = 100
DEFAULT_LOCAL_PLOT_ROOT = Path("d1/wallops-prf/Gauge/Plots")
DEFAULT_PUBLISHED_PLOT_ROOT = Path("/d1/wallops-prf/Gauge/Plots")


def decimal_hour(index: pd.Index) -> np.ndarray:
    """Convert timestamps to hour-of-day plus minute/60."""
    timestamps = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce"))
    return (
        timestamps.hour.to_numpy(dtype=float)
        + timestamps.minute.to_numpy(dtype=float) / 60.0
        + timestamps.second.to_numpy(dtype=float) / 3600.0
    )


def resolve_plot_root(
    *,
    publish: bool,
    plot_root: str | Path | None = None,
) -> Path:
    """Return an explicit root or the required local/published default root."""
    if plot_root is not None:
        return Path(plot_root).expanduser()
    # Plots are always staged beneath the current directory. Publishing is a
    # separate copy step performed only after every artifact is complete.
    return DEFAULT_LOCAL_PLOT_ROOT


def _dated_plot_path(
    root: Path,
    category: str,
    gauge_id: str,
    data_date: date,
    suffix: str,
) -> Path:
    directory = (
        root
        / category
        / f"{data_date.year:04d}"
        / f"{data_date.month:02d}"
        / f"{data_date.day:02d}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (
        f"{gauge_id}_{data_date.year:04d}_"
        f"{data_date.month:02d}{data_date.day:02d}_{suffix}.png"
    )


def _format_axes(axis: plt.Axes, ylabel: str, title: str) -> None:
    axis.set_xlim(0, 24)
    axis.set_xticks(np.arange(0, 25, 2))
    axis.set_xlabel("Hour of Day")
    axis.set_ylabel(ylabel)
    axis.set_title(title)
    axis.grid(True, alpha=0.3)


def _save_figure(figure: plt.Figure, output_path: Path) -> None:
    figure.tight_layout()
    figure.savefig(output_path, dpi=FIGURE_DPI)
    plt.close(figure)


def _rain_accumulation(
    tip_data: pd.DataFrame,
    bucket: str,
    millimeters_per_tip: float,
) -> tuple[np.ndarray, np.ndarray]:
    bucket_tips = get_bucket_tips(tip_data, bucket)
    if bucket_tips.empty:
        return np.asarray([0.0, 24.0]), np.asarray([0.0, 0.0])
    hours = decimal_hour(bucket_tips.index)
    accumulation = (
        bucket_tips["Single_Tip"].cumsum().to_numpy(dtype=float)
        * millimeters_per_tip
    )
    return hours, accumulation


def generate_gauge_plots(
    gauge_id: str,
    data_date: date,
    metadata_df: pd.DataFrame,
    tip_data: pd.DataFrame,
    *,
    rain_tip_a_mm: float,
    rain_tip_b_mm: float,
    station_location: str = "",
    publish: bool = False,
    plot_root: str | Path | None = None,
) -> dict[str, Path]:
    """Generate the three requested daily time-series plots for one gauge."""
    required_metadata = {"battery_voltage", "rssi"}
    missing = sorted(required_metadata.difference(metadata_df.columns))
    if missing:
        raise ValueError(f"Metadata is missing plot columns: {missing}")

    root = resolve_plot_root(publish=publish, plot_root=plot_root)
    packets = len(metadata_df)
    location_text = str(station_location).strip()
    title_parts = [gauge_id]
    if location_text:
        title_parts.append(location_text)
    title_parts.extend([f"Packets {packets}/96", data_date.isoformat()])
    title = " | ".join(title_parts)
    metadata_hours = decimal_hour(metadata_df.index)

    voltage_path = _dated_plot_path(
        root, "Battery", gauge_id, data_date, "voltage"
    )
    figure, axis = plt.subplots(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)
    axis.plot(
        metadata_hours,
        pd.to_numeric(metadata_df["battery_voltage"], errors="coerce"),
        marker="o",
        markersize=3,
        linewidth=1.5,
    )
    _format_axes(axis, "Battery Voltage (volts)", title)
    _save_figure(figure, voltage_path)

    rssi_path = _dated_plot_path(root, "RSSI", gauge_id, data_date, "rssi")
    figure, axis = plt.subplots(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)
    axis.plot(
        metadata_hours,
        pd.to_numeric(metadata_df["rssi"], errors="coerce"),
        marker="o",
        markersize=3,
        linewidth=1.5,
    )
    _format_axes(axis, "RSSI", title)
    _save_figure(figure, rssi_path)

    rain_path = _dated_plot_path(root, "Rain", gauge_id, data_date, "rain")
    hours_a, accumulation_a = _rain_accumulation(
        tip_data, "TB_A_tips", rain_tip_a_mm
    )
    hours_b, accumulation_b = _rain_accumulation(
        tip_data, "TB_B_tips", rain_tip_b_mm
    )
    figure, axis = plt.subplots(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)
    axis.step(hours_a, accumulation_a, where="post", label="Bucket A")
    axis.step(hours_b, accumulation_b, where="post", label="Bucket B")
    _format_axes(axis, "Rain Accumulation (mm)", title)
    axis.set_ylim(bottom=0)
    axis.legend()
    _save_figure(figure, rain_path)

    return {
        "rain": rain_path,
        "voltage": voltage_path,
        "rssi": rssi_path,
    }
