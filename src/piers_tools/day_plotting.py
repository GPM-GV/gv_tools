"""Create PIERS++ daily Wind/WX/Rain and Parsivel plots.

This file is deliberately standalone: install the two workspace wheels, then
run it from tcsh or import ``create_daily_plots`` in a Jupyter notebook.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import warnings

# Configure native/scientific libraries before importing them.
os.environ.setdefault("KMP_WARNINGS", "0")
os.environ.setdefault("OMP_MAX_ACTIVE_LEVELS", "1")
os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd() / ".matplotlib"))

import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.ticker import MultipleLocator
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
import numpy as np
import pandas as pd
from process_parsivel import get_dsd_colormap, plot_dsd, plot_integral_parameters


def _display_saved_image(path: Path) -> None:
    try:
        from IPython import get_ipython
        from IPython.display import Image, display

        if get_ipython() is not None:
            display(Image(filename=str(path)))
    except ImportError:
        pass


def _finish_figure(figure, show: bool, image_path: Path | None = None) -> None:
    """Display safely in Jupyter and never call ``show`` on plain Agg."""
    backend = str(plt.get_backend()).lower()
    if show and backend == "agg":
        try:
            from IPython import get_ipython
            if get_ipython() is not None:
                if image_path is not None:
                    from IPython.display import Image, display
                    display(Image(filename=str(image_path)))
                else:
                    display(figure)
        except ImportError:
            pass
        finally:
            plt.close(figure)
    elif show:
        plt.show()
    else:
        plt.close(figure)


def _read_time_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if "timestamp" not in frame.columns:
        raise ValueError(f"{path} does not contain a timestamp column")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    return frame.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()


def _time_subset(frame: pd.DataFrame, start_time=None, end_time=None) -> pd.DataFrame:
    if frame.empty:
        return frame
    start = pd.Timestamp(start_time) if start_time is not None else None
    end = pd.Timestamp(end_time) if end_time is not None else None
    if start is not None and end is not None and end < start:
        raise ValueError("end_time must not precede start_time")
    if start is not None:
        frame = frame.loc[frame.index >= start]
    if end is not None:
        frame = frame.loc[frame.index <= end]
    return frame


def _daily_time_subset(frame: pd.DataFrame, start_time=None, end_time=None) -> pd.DataFrame:
    """Subset a daily product by clock time, using the product's calendar day.

    ``day_dir`` selects the date, so a date embedded in a notebook's start/end
    values is intentionally ignored. This lets the same time-window cell work
    for any processed day.
    """
    if frame.empty or (start_time is None and end_time is None):
        return frame
    days = frame.index.normalize().unique()
    if len(days) != 1:
        return _time_subset(frame, start_time, end_time)
    day = pd.Timestamp(days[0])

    def on_product_day(value):
        if value is None:
            return None
        supplied = pd.Timestamp(value)
        return day + pd.Timedelta(
            hours=supplied.hour,
            minutes=supplied.minute,
            seconds=supplied.second,
            microseconds=supplied.microsecond,
        )

    return _time_subset(frame, on_product_day(start_time), on_product_day(end_time))


def _decimal_hour(index: pd.Index) -> np.ndarray:
    """Convert timestamps to fractional hour of day."""
    timestamps = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce"))
    return (
        timestamps.hour.to_numpy(dtype=float)
        + timestamps.minute.to_numpy(dtype=float) / 60.0
        + timestamps.second.to_numpy(dtype=float) / 3600.0
    )


def _format_hour_axis(axis) -> None:
    axis.set_xlim(0, 24)
    axis.xaxis.set_major_locator(MultipleLocator(2))
    axis.set_xlabel("Hour of day")


def _rotate_overlapping_xticks(figure, axes) -> None:
    """Rotate visible x tick labels only when adjacent labels overlap."""
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    for axis in axes:
        labels = [label for label in axis.get_xticklabels() if label.get_visible()]
        boxes = [label.get_window_extent(renderer) for label in labels if label.get_text()]
        if any(left.x1 > right.x0 for left, right in zip(boxes, boxes[1:])):
            for label in labels:
                label.set_rotation(45)
                label.set_horizontalalignment("right")


def _aio_instrument_labels(manifest: dict) -> tuple[str, str]:
    """Return labels for the separate Wind stream and the WX/AIO stream."""
    if manifest.get("aio_configuration") == "lufft_ws800_compact":
        return "RM Young Anemometer", "Lufft WS800"
    return "RM Young Anemometer", "RM Young AIO"


def _parsivel_accumulation_mm(parameters: pd.DataFrame) -> pd.Series:
    """Integrate one-minute Parsivel rain rate (mm h-1) to millimeters."""
    if parameters.empty or "Rain" not in parameters:
        return pd.Series(dtype=float)
    rain_rate = pd.to_numeric(parameters["Rain"], errors="coerce")
    return rain_rate.clip(lower=0).fillna(0).cumsum() / 60.0


def _platform_type(manifest: dict) -> str:
    """Infer PIERS generation from the instruments recorded in a manifest."""
    files = manifest.get("files", {})
    if files.get("wind", 0) or files.get("wx", 0):
        return "PIERS++"
    if files.get("parsivel", 0):
        return "PIERS+"
    return "PIERS"


def _plot_rain_rates(axis, gauge: pd.DataFrame, parms: pd.DataFrame) -> None:
    if "Rain" in parms:
        axis.plot(_decimal_hour(parms.index), parms["Rain"], color="tab:blue",
                  linewidth=0.9, label="Parsivel rain rate")
    for label, color in (("A", "tab:orange"), ("B", "tab:red")):
        column = f"rain_{label}_mm"
        if column in gauge:
            axis.step(_decimal_hour(gauge.index), gauge[column] * 60.0,
                      where="mid", color=color, linewidth=0.8,
                      label=f"Gauge {label} rain rate")


def _plot_accumulations(axis, gauge: pd.DataFrame, parms: pd.DataFrame, calibration) -> None:
    for index, (label, color) in enumerate((("A", "tab:orange"), ("B", "tab:red"))):
        column = f"rain_{label}_cumulative_mm"
        if column in gauge:
            amount = calibration[index] if calibration and index < len(calibration) else None
            legend = f"Gauge {label} cumulative"
            if amount is not None:
                legend += f" ({amount:.3f} mm/tip)"
            axis.step(_decimal_hour(gauge.index), gauge[column], where="mid",
                      color=color, linewidth=0.9, label=legend)
    parsivel_accumulation = _parsivel_accumulation_mm(parms)
    if not parsivel_accumulation.empty:
        axis.plot(_decimal_hour(parsivel_accumulation.index), parsivel_accumulation,
                  color="tab:purple", linestyle="--", linewidth=1.1,
                  label="Parsivel cumulative")


def _normalize_png(path: Path, size: tuple[int, int]) -> None:
    """Fit and center a plot on an exact-size white canvas."""
    from PIL import Image

    with Image.open(path) as source:
        image = source.convert("RGB")
        image.thumbnail(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", size, "white")
        canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
        canvas.save(path)


def plot_all_timeseries(
    day_dir,
    output_path=None,
    *,
    start_time=None,
    end_time=None,
    panel_height=2.4,
    title=None,
    show=False,
    dpi=150,
):
    """Create one multi-panel Wind, Gauge, WX, and Parsivel time-series figure.

    ``start_time`` and ``end_time`` accept anything understood by
    ``pandas.Timestamp``. ``panel_height`` is the height in inches of each of
    the six stacked panels and can be reduced for a more compact figure.
    """
    if panel_height <= 0:
        raise ValueError("panel_height must be greater than zero")
    root = Path(day_dir).expanduser()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    platform = _platform_type(manifest)
    if platform != "PIERS++":
        warnings.warn(
            f"{platform} has no wind instrument; skipping Wind/WX plot. "
            "Use create_piers_plus_summary() for Gauge + Parsivel data.",
            RuntimeWarning, stacklevel=2,
        )
        return None
    calibration = manifest.get("gauge_tip_mm")
    wind_label, wx_label = _aio_instrument_labels(manifest)
    gauge = _time_subset(_read_time_csv(root / "gauge_one_minute.csv"), start_time, end_time)
    parsivel = _time_subset(_read_time_csv(root / "parsivel_parameters.csv"), start_time, end_time)
    if aio.empty and gauge.empty and parsivel.empty:
        raise ValueError(f"No one-minute products found in the selected range under {root}")

    figure, axes = plt.subplots(6, 1, figsize=(15, panel_height * 6), sharex=True)
    panels = (
        ("Wind speed", "m s$^{-1}$"),
        ("Wind direction", "degrees"),
        ("Air temperature", "°C"),
        ("Relative humidity", "%"),
        ("Pressure", "hPa"),
        ("Rain", "Parsivel mm h$^{-1}$"),
    )
    for axis, (label, units) in zip(axes, panels):
        axis.set_ylabel(f"{label}\n[{units}]")
        axis.grid(True, alpha=0.3)

    if not aio.empty:
        for column, label in (("wind_speed_m_s", wind_label),
                              ("wx_wind_speed_m_s", wx_label)):
            if column in aio:
                axes[0].plot(_decimal_hour(aio.index), aio[column], linewidth=0.8, label=label)
        for column, label in (("wind_direction_deg", wind_label),
                              ("wx_wind_direction_deg", wx_label)):
            if column in aio:
                axes[1].plot(_decimal_hour(aio.index), aio[column], linewidth=0.7, marker=".",
                             markersize=1.5, label=label)
        for axis, column in zip(axes[2:5],
                                ("air_temperature_c", "relative_humidity_pct", "pressure_hpa")):
            if column in aio:
                axis.plot(_decimal_hour(aio.index), aio[column], color="tab:green", linewidth=0.9,
                          label=wx_label)
    rain_axis = axes[5]
    if not parsivel.empty and "Rain" in parsivel:
        rain_axis.plot(_decimal_hour(parsivel.index), parsivel["Rain"], color="tab:blue",
                       linewidth=0.9, label="Parsivel rain rate")
    gauge_columns = [column for column in
                     ("rain_A_cumulative_mm", "rain_B_cumulative_mm") if column in gauge]
    legacy_gauge = False
    if not gauge_columns:
        gauge_columns = [column for column in ("TB_A_tips", "TB_B_tips") if column in gauge]
        legacy_gauge = bool(gauge_columns)
    parsivel_accumulation = _parsivel_accumulation_mm(parsivel)
    if gauge_columns or not parsivel_accumulation.empty:
        gauge_axis = rain_axis.twinx()
        for index, (column, color) in enumerate(zip(gauge_columns, ("tab:orange", "tab:red"))):
            if not legacy_gauge and calibration and index < len(calibration):
                label = f"Gauge {chr(65 + index)} cumulative ({calibration[index]:.3f} mm/tip)"
            else:
                label = column.replace("_", " ")
            gauge_axis.step(_decimal_hour(gauge.index), gauge[column], where="mid", color=color,
                            linewidth=0.9, label=label)
        if not parsivel_accumulation.empty:
            gauge_axis.plot(
                _decimal_hour(parsivel_accumulation.index), parsivel_accumulation,
                color="tab:purple", linestyle="--", linewidth=1.1,
                label="Parsivel cumulative",
            )
        gauge_axis.set_ylabel(
            "Accumulated rain [mm]" if not legacy_gauge else "Gauge tip value"
        )
        left_handles, left_labels = rain_axis.get_legend_handles_labels()
        right_handles, right_labels = gauge_axis.get_legend_handles_labels()
        rain_axis.legend(left_handles + right_handles, left_labels + right_labels, loc="upper right")
    for axis in axes[:5]:
        if axis.get_legend_handles_labels()[0]:
            axis.legend(loc="upper right")
    if not gauge_columns and rain_axis.get_legend_handles_labels()[0]:
        rain_axis.legend(loc="upper right")
    _format_hour_axis(axes[-1])
    figure.suptitle(title or f"PIERS++ Wind, WX, and Rain — {root.name}", fontsize=16)
    _rotate_overlapping_xticks(figure, [axes[-1]])
    figure.tight_layout(rect=(0, 0, 1, 0.98))
    destination = Path(output_path).expanduser() if output_path else root / "plots" / "wind_wx_rain.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=dpi, bbox_inches="tight")
    _finish_figure(figure, show, destination)
    return destination


# Backward-compatible name retained for existing notebooks and scripts.
plot_wind_wx_rain = plot_all_timeseries


def create_daily_plots(
    day_dir,
    output_dir=None,
    *,
    start_time=None,
    end_time=None,
    panel_height=2.4,
    timeseries_only=False,
    show=False,
    dpi=150,
):
    """Write the combined plot plus package-native DSD and integral plots."""
    root = Path(day_dir).expanduser()
    target = Path(output_dir).expanduser() if output_dir else root / "plots"
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    site = manifest.get("site", root.parent.name)
    date = manifest.get("day", root.name)
    platform = _platform_type(manifest)
    if platform == "PIERS+":
        return create_piers_plus_summary(
            root, target, start_time=start_time, end_time=end_time,
            panel_height=panel_height, show=show, dpi=dpi,
        )
    if platform == "PIERS":
        warnings.warn(
            "PIERS has no Wind/WX or Parsivel instruments; no instrument-summary plot created.",
            RuntimeWarning, stacklevel=2,
        )
        return {}
    range_suffix = ""
    if start_time is not None or end_time is not None:
        start_label = pd.Timestamp(start_time).strftime("%H%M") if start_time is not None else "start"
        end_label = pd.Timestamp(end_time).strftime("%H%M") if end_time is not None else "end"
        range_suffix = f"_{start_label}-{end_label}"
    outputs = {
        "wind_wx_rain": plot_all_timeseries(
            root, target / f"{site}_{date}{range_suffix}_wind_wx_rain.png",
            start_time=start_time, end_time=end_time, panel_height=panel_height,
            show=show, dpi=dpi,
        )
    }
    if timeseries_only:
        return outputs
    parameters = _read_time_csv(root / "parsivel_parameters.csv")
    psd = _read_time_csv(root / "parsivel_psd.csv")
    parameters = _time_subset(parameters, start_time, end_time)
    psd = _time_subset(psd, start_time, end_time)
    if not psd.empty:
        figure, _, _, saved = plot_dsd(
            psd, site=site, instrument="Parsivel", date=date,
            save_path=target / f"{site}_{date}{range_suffix}_parsivel_dsd.png",
            dpi=dpi, show=False,
        )
        _finish_figure(figure, show, Path(saved))
        outputs["parsivel_dsd"] = Path(saved)
    if not parameters.empty:
        figure, _, _, saved = plot_integral_parameters(
            parameters, site=site, instrument="Parsivel", date=date,
            accumulate=True, accumulation_scale=1 / 60,
            accumulation_labels={"Rain": "Accumulated rain [mm]"},
            save_path=target / f"{site}_{date}{range_suffix}_parsivel_integral_parameters.png",
            dpi=dpi, show=False,
        )
        _finish_figure(figure, show, Path(saved))
        outputs["parsivel_integral_parameters"] = Path(saved)
    if all(name in outputs for name in ("wind_wx_rain", "parsivel_dsd", "parsivel_integral_parameters")):
        from PIL import Image

        with Image.open(outputs["wind_wx_rain"]) as reference:
            exact_size = reference.size
        _normalize_png(outputs["parsivel_dsd"], exact_size)
        _normalize_png(outputs["parsivel_integral_parameters"], exact_size)
    return outputs


def create_piers_plus_summary(
    day_dir,
    output_dir=None,
    *,
    start_time=None,
    end_time=None,
    panel_height=2.4,
    panel_width=7.5,
    show=True,
    dpi=150,
):
    """Create a five-row Gauge/Parsivel summary for a PIERS+ platform."""
    if panel_height <= 0 or panel_width <= 0:
        raise ValueError("panel_height and panel_width must be greater than zero")
    root = Path(day_dir).expanduser()
    target = Path(output_dir).expanduser() if output_dir else root / "plots"
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    platform = _platform_type(manifest)
    if platform != "PIERS+":
        raise ValueError(f"PIERS+ summary requires Gauge + Parsivel data; detected {platform}")
    site = manifest.get("site", root.parent.name)
    date = manifest.get("day", root.name)
    calibration = manifest.get("gauge_tip_mm")
    aio = _time_subset(_read_time_csv(root / "aio_one_minute.csv"), start_time, end_time)
    gauge = _time_subset(_read_time_csv(root / "gauge_one_minute.csv"), start_time, end_time)
    parms = _time_subset(_read_time_csv(root / "parsivel_parameters.csv"), start_time, end_time)
    psd = _time_subset(_read_time_csv(root / "parsivel_psd.csv"), start_time, end_time)
    if psd.empty or parms.empty:
        raise ValueError("PIERS+ summary requires Parsivel PSD and parameter data")

    figure = plt.figure(figsize=(panel_width * 2, panel_height * 5))
    grid = figure.add_gridspec(5, 2)
    left = (
        figure.add_subplot(grid[:2, 0]),
        figure.add_subplot(grid[2:, 0]),
    )
    right = [figure.add_subplot(grid[row, 1]) for row in range(5)]
    left[1].sharex(left[0])
    for axis in right[1:]:
        axis.sharex(right[0])
    left[0].tick_params(labelbottom=False)
    for axis in right[:-1]:
        axis.tick_params(labelbottom=False)
    for axis in (*left, *right):
        axis.grid(True, alpha=0.3)

    _plot_rain_rates(left[0], gauge, parms)
    left[0].set_ylabel("Rain rate\n[mm h$^{-1}$]")
    _plot_accumulations(left[1], gauge, parms, calibration)
    left[1].set_ylabel("Accumulated rain\n[mm]")
    for axis in left:
        if axis.get_legend_handles_labels()[0]:
            axis.legend(loc="upper left", fontsize="small")

    diameters = psd.columns.to_numpy(dtype=float)
    values = psd.to_numpy(dtype=float).T
    masked = np.ma.masked_where(~np.isfinite(values) | (values < 1.0), values)
    mesh = right[0].pcolormesh(
        _decimal_hour(psd.index), diameters, masked, shading="auto",
        cmap=get_dsd_colormap(), norm=LogNorm(vmin=1.0, vmax=1e4),
    )
    right[0].set_ylim(0, 10)
    right[0].set_ylabel("Drop diameter\n[mm]")
    color_axis = inset_axes(right[0], width="38%", height="8%", loc="upper right", borderpad=1)
    figure.colorbar(mesh, cax=color_axis, orientation="horizontal", label="DSD [m⁻³ mm⁻¹]")
    color_axis.tick_params(labelsize=6)

    for axis, columns, ylabel in (
        (right[1], ("dBZ",), "Reflectivity [dBZ]"),
        (right[2], ("LWC",), "LWC"),
        (right[3], ("Dm", "Dmax"), "Dm / Dmax [mm]"),
    ):
        for column in columns:
            if column in parms:
                axis.plot(_decimal_hour(parms.index), parms[column], linewidth=0.8,
                          color="tab:red" if column == "Dmax" else "black", label=column)
        axis.set_ylabel(ylabel)
        axis.legend(loc="upper right", fontsize="small")

    if "Total Drops" in parms:
        right[4].plot(_decimal_hour(parms.index), parms["Total Drops"],
                      color="black", linewidth=0.8, label="Total Drops")
    right[4].set_ylabel("Total drops")
    concentration_axis = right[4].twinx()
    if "Concentration" in parms:
        concentration_axis.plot(_decimal_hour(parms.index), parms["Concentration"],
                                color="tab:purple", linewidth=0.8, label="Concentration")
    concentration_axis.set_ylabel("Concentration")
    handles1, labels1 = right[4].get_legend_handles_labels()
    handles2, labels2 = concentration_axis.get_legend_handles_labels()
    right[4].legend(handles1 + handles2, labels1 + labels2, loc="upper right", fontsize="small")

    _format_hour_axis(left[-1])
    _format_hour_axis(right[-1])
    figure.suptitle(f"{site} PIERS+ instrument summary — {date}", fontsize=16)
    _rotate_overlapping_xticks(figure, [left[-1], right[-1]])
    figure.subplots_adjust(
        left=0.07, right=0.93, bottom=0.07, top=0.93, wspace=0.34, hspace=0.26
    )
    start_label = pd.Timestamp(start_time).strftime("%H%M") if start_time is not None else "start"
    end_label = pd.Timestamp(end_time).strftime("%H%M") if end_time is not None else "end"
    suffix = f"_{start_label}-{end_label}" if start_time is not None or end_time is not None else ""
    summary = target / f"{site}_{date}{suffix}_piers_plus_summary.png"
    figure.savefig(summary, dpi=dpi)
    _finish_figure(figure, show, summary)
    # Keep the public result key stable across PIERS++ and PIERS+ so existing
    # notebooks can always use ``plots["two_column_summary"]``.
    return {
        "two_column_summary": summary,
        "piers_plus_summary": summary,
    }


def create_two_column_summary(
    day_dir,
    output_dir=None,
    *,
    start_time=None,
    end_time=None,
    panel_height=2.4,
    panel_width=7.5,
    show=True,
    dpi=150,
):
    """Create a true 6x2 grid whose twelve panels have identical dimensions."""
    if panel_height <= 0 or panel_width <= 0:
        raise ValueError("panel_height and panel_width must be greater than zero")
    root = Path(day_dir).expanduser()
    target = Path(output_dir).expanduser() if output_dir else root / "plots"
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    site = manifest.get("site", root.parent.name)
    date = manifest.get("day", root.name)
    calibration = manifest.get("gauge_tip_mm")
    wind_label, wx_label = _aio_instrument_labels(manifest)
    aio = _time_subset(_read_time_csv(root / "aio_one_minute.csv"), start_time, end_time)
    gauge = _time_subset(_read_time_csv(root / "gauge_one_minute.csv"), start_time, end_time)
    parms = _time_subset(_read_time_csv(root / "parsivel_parameters.csv"), start_time, end_time)
    psd = _time_subset(_read_time_csv(root / "parsivel_psd.csv"), start_time, end_time)
    if _platform_type(manifest) == "PIERS+":
        return create_piers_plus_summary(
            root, target, start_time=start_time, end_time=end_time,
            panel_height=panel_height, panel_width=panel_width, show=show, dpi=dpi,
        )
    if psd.empty or parms.empty:
        raise ValueError("Two-column summary requires Parsivel PSD and parameter data")

    figure, axes = plt.subplots(
        6, 2, figsize=(panel_width * 2, panel_height * 6), sharex="col",
        squeeze=False,
    )
    left = axes[:, 0]
    right = axes[:, 1]
    for axis in axes.ravel():
        axis.grid(True, alpha=0.3)

    # Left column: surface instruments and the shared Gauge/Parsivel rain panel.
    for column, label in (("wind_speed_m_s", wind_label),
                          ("wx_wind_speed_m_s", wx_label)):
        if column in aio:
            left[0].plot(_decimal_hour(aio.index), aio[column], linewidth=0.8, label=label)
    left[0].set_ylabel("Wind speed\n[m s$^{-1}$]")
    for column, label in (("wind_direction_deg", wind_label),
                          ("wx_wind_direction_deg", wx_label)):
        if column in aio:
            left[1].plot(_decimal_hour(aio.index), aio[column], linewidth=0.7, label=label)
    left[1].set_ylabel("Wind direction\n[degrees]")
    for axis, column, ylabel in zip(
        left[2:5],
        ("air_temperature_c", "relative_humidity_pct", "pressure_hpa"),
        ("Air temperature\n[°C]", "Relative humidity\n[%]", "Pressure\n[hPa]"),
    ):
        if column in aio:
            axis.plot(_decimal_hour(aio.index), aio[column], color="tab:green", linewidth=0.9,
                      label=wx_label)
        axis.set_ylabel(ylabel)
    if "Rain" in parms:
        left[5].plot(_decimal_hour(parms.index), parms["Rain"], color="tab:blue", linewidth=0.9,
                     label="Parsivel rain rate")
    left[5].set_ylabel("Rain rate\n[mm h$^{-1}$]")
    gauge_axis = left[5].twinx()
    for index, (column, color) in enumerate(
        (("rain_A_cumulative_mm", "tab:orange"), ("rain_B_cumulative_mm", "tab:red"))
    ):
        if column in gauge:
            amount = calibration[index] if calibration and index < len(calibration) else None
            label = f"Gauge {chr(65 + index)} cumulative"
            if amount is not None:
                label += f" ({amount:.3f} mm/tip)"
            gauge_axis.step(_decimal_hour(gauge.index), gauge[column], where="mid", color=color,
                            linewidth=0.9, label=label)
    parsivel_accumulation = _parsivel_accumulation_mm(parms)
    if not parsivel_accumulation.empty:
        gauge_axis.plot(
            _decimal_hour(parsivel_accumulation.index), parsivel_accumulation,
            color="tab:purple", linestyle="--", linewidth=1.1,
            label="Parsivel cumulative",
        )
    gauge_axis.set_ylabel("Accumulated rain [mm]")
    for axis in left[:5]:
        if axis.get_legend_handles_labels()[0]:
            axis.legend(loc="upper right", fontsize="small")
    handles1, labels1 = left[5].get_legend_handles_labels()
    handles2, labels2 = gauge_axis.get_legend_handles_labels()
    left[5].legend(handles1 + handles2, labels1 + labels2, loc="upper left", fontsize="small")

    # Right column: one DSD panel plus five non-rain integral-parameter panels.
    diameters = psd.columns.to_numpy(dtype=float)
    values = psd.to_numpy(dtype=float).T
    masked = np.ma.masked_where(~np.isfinite(values) | (values < 1.0), values)
    mesh = right[0].pcolormesh(
        _decimal_hour(psd.index), diameters, masked, shading="auto", cmap=get_dsd_colormap(),
        norm=LogNorm(vmin=1.0, vmax=1e4),
    )
    right[0].set_ylim(0, 10)
    right[0].set_ylabel("Drop diameter\n[mm]")
    color_axis = inset_axes(right[0], width="38%", height="8%", loc="upper right", borderpad=1)
    figure.colorbar(mesh, cax=color_axis, orientation="horizontal", label="DSD [m⁻³ mm⁻¹]")
    color_axis.tick_params(labelsize=6)

    right_panels = (
        (("dBZ",), "Reflectivity [dBZ]"),
        (("LWC",), "LWC"),
        (("Dm", "Dmax"), "Dm / Dmax [mm]"),
        (("Total Drops",), "Total drops"),
        (("Concentration",), "Concentration"),
    )
    for axis, (columns, ylabel) in zip(right[1:], right_panels):
        for column in columns:
            if column in parms:
                axis.plot(_decimal_hour(parms.index), parms[column], linewidth=0.8,
                          color="tab:red" if column == "Dmax" else "black", label=column)
        axis.set_ylabel(ylabel)
        axis.legend(loc="upper right", fontsize="small")
    _format_hour_axis(left[-1])
    _format_hour_axis(right[-1])
    figure.suptitle(f"{site} PIERS++ instrument summary — {date}", fontsize=16)
    _rotate_overlapping_xticks(figure, [left[-1], right[-1]])
    figure.subplots_adjust(
        left=0.07, right=0.96, bottom=0.06, top=0.94, wspace=0.30, hspace=0.24
    )
    start_label = pd.Timestamp(start_time).strftime("%H%M") if start_time is not None else "start"
    end_label = pd.Timestamp(end_time).strftime("%H%M") if end_time is not None else "end"
    range_suffix = f"_{start_label}-{end_label}" if start_time is not None or end_time is not None else ""
    summary = target / f"{site}_{date}{range_suffix}_two_column_summary.png"
    figure.savefig(summary, dpi=dpi)
    _finish_figure(figure, show, summary)
    outputs = {"two_column_summary": summary}
    return outputs


def _wind_rose_frequency(speed, direction, speed_bins, sectors):
    """Return direction-by-speed-bin frequencies as percent of valid samples."""
    speed = np.asarray(speed, dtype=float)
    direction = np.asarray(direction, dtype=float)
    valid = np.isfinite(speed) & np.isfinite(direction) & (speed >= 0)
    speed = speed[valid]
    direction = np.mod(direction[valid], 360.0)
    if not len(speed):
        return np.zeros((sectors, len(speed_bins) - 1)), 0
    sector_width = 360.0 / sectors
    sector_index = np.floor((direction + sector_width / 2) % 360 / sector_width).astype(int)
    speed_index = np.digitize(speed, speed_bins[1:-1], right=False)
    counts = np.zeros((sectors, len(speed_bins) - 1), dtype=float)
    np.add.at(counts, (sector_index, speed_index), 1)
    return counts * (100.0 / len(speed)), len(speed)


def plot_wind_roses(
    day_dir,
    output_path=None,
    *,
    start_time=None,
    end_time=None,
    speed_bins=(0, 2, 4, 6, 8, 10, 15, np.inf),
    sectors=16,
    colormap="viridis",
    panel_width=6.0,
    panel_height=6.0,
    show=True,
    dpi=150,
):
    """Plot side-by-side wind roses for the detected wind instruments.

    Direction is displayed meteorologically with north at the top and angles
    increasing clockwise. Radial values are percent frequency of valid samples.
    """
    if sectors < 4 or not isinstance(sectors, int):
        raise ValueError("sectors must be an integer of at least 4")
    if panel_width <= 0 or panel_height <= 0:
        raise ValueError("panel_width and panel_height must be greater than zero")
    bins = np.asarray(speed_bins, dtype=float)
    if len(bins) < 2 or bins[0] != 0 or not np.all(np.diff(bins) > 0):
        raise ValueError("speed_bins must start at zero and be strictly increasing")
    root = Path(day_dir).expanduser()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    wind_label, wx_label = _aio_instrument_labels(manifest)
    platform = _platform_type(manifest)
    if platform != "PIERS++":
        warnings.warn(
            f"{platform} has no wind instrument; no wind rose was created.",
            RuntimeWarning, stacklevel=2,
        )
        return None
    all_aio = _read_time_csv(root / "aio_one_minute.csv")
    aio = _daily_time_subset(all_aio, start_time, end_time)
    candidates = (
        (wind_label, "wind_speed_m_s", "wind_direction_deg"),
        (wx_label, "wx_wind_speed_m_s", "wx_wind_direction_deg"),
    )
    instruments = tuple(
        item for item in candidates
        if item[1] in aio and item[2] in aio
        and aio[[item[1], item[2]]].notna().all(axis=1).any()
    )
    matrices = []
    sample_counts = []
    for _, speed_column, direction_column in instruments:
        if aio.empty or speed_column not in aio or direction_column not in aio:
            matrix, count = np.zeros((sectors, len(bins) - 1)), 0
        else:
            matrix, count = _wind_rose_frequency(
                aio[speed_column], aio[direction_column], bins, sectors
            )
        matrices.append(matrix)
        sample_counts.append(count)
    if not any(sample_counts):
        available = "none"
        if not all_aio.empty:
            available = f"{all_aio.index.min()} through {all_aio.index.max()}"
        raise ValueError(
            "No valid wind observations in the selected clock-time range; "
            f"available data: {available}"
        )

    figure, axes = plt.subplots(
        1, len(instruments), figsize=(panel_width * len(instruments), panel_height),
        subplot_kw={"projection": "polar"}, squeeze=False,
    )
    axes = axes[0]
    theta = np.deg2rad(np.arange(sectors) * (360.0 / sectors))
    bar_width = np.deg2rad(360.0 / sectors) * 0.88
    try:
        selected_colormap = plt.get_cmap(colormap)
    except ValueError as exc:
        raise ValueError(f"Unknown Matplotlib colormap: {colormap!r}") from exc
    colors = selected_colormap(np.linspace(0.12, 0.92, len(bins) - 1))
    radial_max = max(matrix.sum(axis=1).max(initial=0) for matrix in matrices)
    radial_max = max(5.0, np.ceil(radial_max / 5.0) * 5.0)
    handles = []
    labels = []
    for axis, (instrument, _, _), matrix, count in zip(
        axes, instruments, matrices, sample_counts
    ):
        bottom = np.zeros(sectors)
        for index, color in enumerate(colors):
            bars = axis.bar(
                theta, matrix[:, index], width=bar_width, bottom=bottom,
                color=color, edgecolor="white", linewidth=0.35, align="center",
            )
            if axis is axes[0]:
                handles.append(bars[0])
                upper = bins[index + 1]
                labels.append(
                    f"{bins[index]:g}–{upper:g}" if np.isfinite(upper)
                    else f"≥{bins[index]:g}"
                )
            bottom += matrix[:, index]
        axis.set_theta_zero_location("N")
        axis.set_theta_direction(-1)
        axis.set_thetagrids(np.arange(0, 360, 45), labels=("N", "NE", "E", "SE", "S", "SW", "W", "NW"))
        axis.set_ylim(0, radial_max)
        axis.set_rlabel_position(225)
        axis.set_ylabel("Frequency [%]", labelpad=28)
        axis.set_title(f"{instrument}\n{count:,} one-minute samples", pad=8)
        axis.grid(True, alpha=0.4)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    site = manifest.get("site", root.parent.name)
    date = manifest.get("day", root.name)
    included_start = aio.index.min()
    included_end = aio.index.max()
    interval = (
        f"{included_start:%Y-%m-%d %H:%M} to {included_end:%Y-%m-%d %H:%M}"
        if pd.notna(included_start) and pd.notna(included_end) else "No valid interval"
    )
    figure.suptitle(f"{site} wind roses — {date}\n{interval}", fontsize=15, y=0.98)
    figure.legend(
        handles, labels, title="Wind speed [m s⁻¹]", loc="lower center",
        ncol=len(labels), bbox_to_anchor=(0.5, 0.01), fontsize="small",
    )
    figure.subplots_adjust(left=0.05, right=0.95, bottom=0.25, top=0.79, wspace=0.22)
    if output_path is None:
        start_label = pd.Timestamp(start_time).strftime("%H%M") if start_time is not None else "start"
        end_label = pd.Timestamp(end_time).strftime("%H%M") if end_time is not None else "end"
        suffix = f"_{start_label}-{end_label}" if start_time is not None or end_time is not None else ""
        output_path = root / "plots" / f"{site}_{date}{suffix}_wind_roses.png"
    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=dpi, bbox_inches="tight")
    _finish_figure(figure, show, destination)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("day_dir", help="Processed directory containing manifest.json")
    parser.add_argument("--output-dir")
    parser.add_argument("--start", help="Inclusive start time, e.g. '2026-07-21 18:00'")
    parser.add_argument("--end", help="Inclusive end time, e.g. '2026-07-21 23:00'")
    parser.add_argument("--panel-height", type=float, default=2.4,
                        help="Height of each time-series panel in inches")
    parser.add_argument("--panel-width", type=float, default=7.5,
                        help="Width of every panel in the two-column summary")
    parser.add_argument("--timeseries-only", action="store_true",
                        help="Create only the single combined time-series figure")
    parser.add_argument("--two-column-summary", action="store_true",
                        help="Create and display one two-column all-products PNG")
    parser.add_argument("--wind-roses", action="store_true",
                        help="Create two-column RM Young Anemometer/AIO wind roses")
    parser.add_argument("--sectors", type=int, default=16,
                        help="Number of wind-rose direction sectors")
    parser.add_argument("--colormap", default="viridis",
                        help="Matplotlib colormap used for wind-speed bins")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args(argv)
    if args.wind_roses:
        path = plot_wind_roses(
            args.day_dir,
            Path(args.output_dir).expanduser() / "wind_roses.png" if args.output_dir else None,
            start_time=args.start, end_time=args.end, sectors=args.sectors,
            colormap=args.colormap,
            panel_width=args.panel_width, panel_height=args.panel_height,
            show=args.show, dpi=args.dpi,
        )
        outputs = {"wind_roses": path}
    elif args.two_column_summary:
        outputs = create_two_column_summary(
            args.day_dir, args.output_dir, start_time=args.start, end_time=args.end,
            panel_height=args.panel_height, panel_width=args.panel_width,
            show=args.show, dpi=args.dpi,
        )
    else:
        outputs = create_daily_plots(
            args.day_dir, args.output_dir, start_time=args.start, end_time=args.end,
            panel_height=args.panel_height, timeseries_only=args.timeseries_only,
            show=args.show, dpi=args.dpi,
        )
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
