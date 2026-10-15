"""Plotting helpers for derived Parsivel products."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.colors as colors
from matplotlib.ticker import LogFormatterSciNotation
import numpy as np
import pandas as pd
import math


DEFAULT_PARAMETER_COLUMNS = (
    "Rain",
    "dBZ",
    "LWC",
    "Total Drops",
    "Concentration",
    "Dm",
)

DEFAULT_INTEGRAL_PANELS = (
    ("Rain",),
    ("dBZ",),
    ("LWC",),
    ("Dm", "Dmax"),
    ("Total Drops",),
    ("Concentration",),
)

DEFAULT_INTEGRAL_LABELS = {
    "Rain": "Rain Rate",
    "dBZ": "Reflectivity",
    "LWC": "LWC",
    "Dm": "Dm",
    "Dmax": "Dmax",
    "Total Drops": "Total Drops",
    "Concentration": "Concentration",
}

DEFAULT_INTEGRAL_YLABELS = {
    "Rain": "Rain Rate",
    "dBZ": "Reflectivity",
    "LWC": "LWC",
    "Dm": "Dm & Dmax",
    "Total Drops": "Total Drops",
    "Concentration": "Concentration",
}

DSD_COLORS = (
    "#f7fbff",
    "#9ecae1",
    "#3182bd",
    "#31a354",
    "#addd8e",
    "#ffff33",
    "#fd8d3c",
    "#e31a1c",
    "#6a3d9a",
)


def get_dsd_colormap():
    """Return the package DSD colormap for concentrations from 10^0 upward."""
    colormap = colors.LinearSegmentedColormap.from_list(
        "process_parsivel_dsd", DSD_COLORS, N=256
    )
    return colormap.with_extremes(
        bad=(1, 1, 1, 0), under="white", over="#3f007d"
    )


def _column_list(value, *, default=()):
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [value]
    return list(value)


def _accumulation_columns(accumulate, columns):
    if accumulate is True:
        return ["Rain"]
    if accumulate in (False, None):
        return []
    requested = _column_list(accumulate)
    unknown = sorted(set(requested).difference(columns))
    if unknown:
        raise ValueError(f"Accumulation columns are not plotted: {unknown}")
    return requested


def plot_parameters(
    parms: pd.DataFrame,
    columns=None,
    *,
    accumulate=False,
    accumulation_labels=None,
    title=None,
    figsize=None,
    primary_color="tab:blue",
    accumulation_color="tab:red",
    grid=True,
    save_path=None,
    dpi=150,
    show=True,
):
    """Plot parameter time series with optional cumulative values on y2 axes.

    ``accumulate=True`` accumulates ``Rain``. Pass a column name or iterable,
    such as ``accumulate=["Rain", "Total Drops"]``, to select other plotted
    parameters. Accumulations use pandas ``cumsum()`` and ignore missing values
    by default. The function returns ``(figure, primary_axes, secondary_axes)``;
    ``secondary_axes`` is a dictionary keyed by accumulated column name.
    """
    if not isinstance(parms, pd.DataFrame) or parms.empty:
        raise ValueError("parms must be a non-empty pandas DataFrame")
    selected = _column_list(columns, default=DEFAULT_PARAMETER_COLUMNS)
    missing = sorted(set(selected).difference(parms.columns))
    if missing:
        raise ValueError(f"Parameter columns are missing: {missing}")
    accumulated = _accumulation_columns(accumulate, selected)
    labels = dict(accumulation_labels or {})
    if figsize is None:
        figsize = (14, max(4, 3.2 * len(selected)))
    figure, axes_value = plt.subplots(len(selected), 1, figsize=figsize, sharex=True, squeeze=False)
    axes = axes_value[:, 0]
    secondary_axes = {}
    for axis, column in zip(axes, selected):
        axis.plot(parms.index, parms[column], color=primary_color, label=column)
        axis.set_ylabel(column)
        axis.grid(grid)
        axis.legend(loc="upper left")
        if column in accumulated:
            y2 = axis.twinx()
            label = labels.get(column, f"Accumulated {column}")
            y2.plot(
                parms.index,
                parms[column].cumsum(),
                color=accumulation_color,
                linestyle="--",
                label=label,
            )
            y2.set_ylabel(label, color=accumulation_color)
            y2.tick_params(axis="y", colors=accumulation_color)
            y2.legend(loc="upper right")
            secondary_axes[column] = y2
    axes[-1].set_xlabel("Time")
    if title:
        figure.suptitle(title)
    figure.tight_layout()
    if save_path is not None:
        destination = Path(save_path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, dpi=dpi, bbox_inches="tight")
    if show:
        plt.show()
    return figure, axes, secondary_axes


def plot_integral_parameters(
    parms: pd.DataFrame,
    *,
    panels=None,
    labels=None,
    ylabels=None,
    colors=None,
    alphas=None,
    ylimits=None,
    accumulate=False,
    accumulation_scale=1.0,
    accumulation_labels=None,
    accumulation_color="tab:blue",
    site=None,
    instrument=None,
    date=None,
    title=None,
    figsize=(14, 12),
    ncols=2,
    linewidth=1.0,
    grid=True,
    rotate_xticks=45,
    sharex=True,
    suptitle_y=0.985,
    layout_top=0.93,
    save_path=None,
    output_dir=None,
    dpi=150,
    show=True,
):
    """Create the customizable stacked parameter figure from ``plot_parms.py``.

    ``panels`` is an iterable of column groups; columns in the same group share
    one subplot. ``accumulate=True`` adds cumulative Rain to a secondary axis.
    A string or iterable selects other series. Set ``accumulation_scale=1/60``
    to convert one-minute samples of an hourly rain rate into accumulated depth.
    """
    if not isinstance(parms, pd.DataFrame) or parms.empty:
        raise ValueError("parms must be a non-empty pandas DataFrame")
    panel_groups = [tuple(group) if not isinstance(group, str) else (group,) for group in (panels or DEFAULT_INTEGRAL_PANELS)]
    if not panel_groups or any(not group for group in panel_groups):
        raise ValueError("panels must contain at least one non-empty column group")
    plotted = [column for group in panel_groups for column in group]
    missing = sorted(set(plotted).difference(parms.columns))
    if missing:
        raise ValueError(f"Parameter columns are missing: {missing}")
    accumulated = _accumulation_columns(accumulate, plotted)
    if not np.isscalar(accumulation_scale):
        raise ValueError("accumulation_scale must be a number")
    label_map = {**DEFAULT_INTEGRAL_LABELS, **dict(labels or {})}
    ylabel_map = {**DEFAULT_INTEGRAL_YLABELS, **dict(ylabels or {})}
    color_map = {"Dmax": "tab:red", **dict(colors or {})}
    alpha_map = {"Dmax": 0.5, **dict(alphas or {})}
    limit_map = dict(ylimits or {})
    accumulation_label_map = dict(accumulation_labels or {})
    if not isinstance(ncols, int) or ncols < 1:
        raise ValueError("ncols must be a positive integer")
    nrows = math.ceil(len(panel_groups) / ncols)
    figure, axes_value = plt.subplots(
        nrows, ncols, figsize=figsize, sharex=sharex, squeeze=False,
        facecolor="white",
    )
    all_axes = axes_value.ravel()
    axes = all_axes[:len(panel_groups)]
    for unused_axis in all_axes[len(panel_groups):]:
        unused_axis.set_visible(False)
    secondary_axes = {}
    for axis, group in zip(axes, panel_groups):
        for column in group:
            axis.plot(
                parms.index,
                parms[column].to_numpy(),
                color=color_map.get(column, "black"),
                alpha=alpha_map.get(column, 1.0),
                linewidth=linewidth,
                label=label_map.get(column, column),
            )
        axis.set_ylabel(ylabel_map.get(group[0], " / ".join(group)))
        if group[0] in limit_map:
            axis.set_ylim(*limit_map[group[0]])
        axis.grid(grid)
        axis.legend(loc="upper left")
        axis.tick_params(axis="x", labelrotation=rotate_xticks)
        for column in (item for item in group if item in accumulated):
            y2 = axis.twinx()
            cumulative = parms[column].cumsum() * accumulation_scale
            label = accumulation_label_map.get(column, f"Accumulated {label_map.get(column, column)}")
            y2.plot(
                parms.index,
                cumulative,
                color=accumulation_color,
                linestyle="--",
                linewidth=linewidth,
                label=label,
            )
            y2.set_ylabel(label, color=accumulation_color)
            y2.tick_params(axis="y", colors=accumulation_color)
            y2.legend(loc="upper right")
            secondary_axes[column] = y2
    for axis in axes:
        if axis.get_subplotspec().rowspan.stop == nrows:
            axis.set_xlabel("Time")
    if title is None:
        prefix = "/".join(str(item) for item in (site, instrument) if item)
        display_date = str(date) if date else pd.Timestamp(parms.index[0]).strftime("%m/%d/%Y")
        title = " ".join(item for item in (prefix, display_date) if item)
    if title:
        figure.suptitle(title, fontsize=24, y=suptitle_y)
    figure.tight_layout(rect=(0, 0, 1, layout_top))
    destination = None
    if save_path is not None:
        destination = Path(save_path).expanduser()
    elif output_dir is not None:
        if not instrument:
            raise ValueError("instrument is required when output_dir creates the filename")
        stamp = pd.Timestamp(date or parms.index[0])
        site_prefix = f"{site}_" if site else ""
        destination = (
            Path(output_dir).expanduser()
            / "Plots"
            / instrument
            / "Rain"
            / stamp.strftime("%Y")
            / f"{site_prefix}{instrument}_{stamp:%Y_%m%d}_rain.png"
        )
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, dpi=dpi, bbox_inches="tight")
    if show:
        plt.show()
    return figure, axes, secondary_axes, str(destination) if destination is not None else None


def plot_dsd(
    psd: pd.DataFrame,
    *,
    site=None,
    instrument=None,
    date=None,
    title=None,
    method="contourf",
    diameter_range=(0, 10),
    concentration_range=(1e0, 1e4),
    level_count=17,
    colorbar_tick_count=9,
    cmap="dsd",
    figsize=(10, 8),
    colorbar_location="bottom",
    grid=True,
    rotate_xticks=45,
    save_path=None,
    output_dir=None,
    dpi=150,
    show=True,
):
    """Plot a DSD time series with contours or bin-faithful colored cells.

    The layout follows the supplied ``plot_dsd.py`` function. Values less than
    or equal to zero are masked before logarithmic normalization. If the entire
    selected DSD is dry, the axes are returned with a clear annotation instead
    of raising a log-scale warning. Use ``method="pcolormesh"`` to draw each
    measured time/diameter bin without contour interpolation.
    """
    if not isinstance(psd, pd.DataFrame) or psd.empty:
        raise ValueError("psd must be a non-empty pandas DataFrame")
    try:
        diameters = psd.columns.to_numpy(dtype=float)
        values = psd.to_numpy(dtype=float).T
    except (TypeError, ValueError) as exc:
        raise ValueError("PSD columns and values must be numeric") from exc
    vmin, vmax = concentration_range
    if not (0 < vmin < vmax):
        raise ValueError("concentration_range must contain two increasing positive values")
    if level_count < 2 or colorbar_tick_count < 2:
        raise ValueError("level and colorbar tick counts must be at least 2")
    method_aliases = {
        "contour": "contourf",
        "contourf": "contourf",
        "mesh": "pcolormesh",
        "pcolormesh": "pcolormesh",
    }
    try:
        method = method_aliases[method.lower()]
    except (AttributeError, KeyError) as exc:
        raise ValueError("method must be 'contourf' or 'pcolormesh'") from exc
    if not psd.index.is_monotonic_increasing or not np.all(np.diff(diameters) > 0):
        raise ValueError("PSD time index and diameter columns must be increasing")
    figure, axis = plt.subplots(figsize=figsize, facecolor="white")
    finite_positive = np.isfinite(values) & (values >= vmin)
    contour = None
    colorbar = None
    if finite_positive.any():
        masked = np.ma.masked_where(~finite_positive, values)
        levels = np.logspace(np.log10(vmin), np.log10(vmax), num=level_count)
        ticks = np.logspace(np.log10(vmin), np.log10(vmax), num=colorbar_tick_count)
        norm = colors.LogNorm(vmin=vmin, vmax=vmax)
        selected_cmap = get_dsd_colormap() if cmap == "dsd" else cmap
        if method == "contourf":
            contour = axis.contourf(
                psd.index.to_numpy(),
                diameters,
                masked,
                cmap=selected_cmap,
                levels=levels,
                norm=norm,
                extend="both",
            )
        else:
            time_edges = _datetime_edges(psd.index)
            diameter_edges = _numeric_edges(diameters)
            contour = axis.pcolormesh(
                time_edges,
                diameter_edges,
                masked,
                cmap=selected_cmap,
                norm=norm,
                shading="flat",
            )
        colorbar = figure.colorbar(
            contour,
            ax=axis,
            location=colorbar_location,
            fraction=0.125,
            ticks=ticks,
            label=r"Drops per ($m^{3}$/mm)",
            pad=0.175 if colorbar_location == "bottom" else 0.05,
            aspect=40,
        )
        colorbar.formatter = LogFormatterSciNotation(base=10)
        colorbar.update_ticks()
    else:
        axis.text(
            0.5,
            0.5,
            "No positive DSD values",
            transform=axis.transAxes,
            ha="center",
            va="center",
            fontsize=14,
        )
    axis.set_ylabel("Drop Diameter [mm]")
    axis.set_xlabel("Time")
    axis.set_ylim(*diameter_range)
    axis.grid(grid)
    axis.tick_params(axis="x", labelrotation=rotate_xticks)
    if title is None:
        parts = [part for part in (site, instrument) if part]
        prefix = "/".join(parts)
        if date is None and len(psd.index):
            date = pd.Timestamp(psd.index[0]).strftime("%m/%d/%Y")
        title = " ".join(part for part in (prefix, str(date) if date else None) if part)
    if title:
        figure.suptitle(title, fontsize=20, y=0.97)
    figure.tight_layout()
    destination = None
    if save_path is not None:
        destination = Path(save_path).expanduser()
    elif output_dir is not None:
        if not instrument:
            raise ValueError("instrument is required when output_dir creates the filename")
        stamp = pd.Timestamp(date or psd.index[0])
        year = stamp.strftime("%Y")
        site_prefix = f"{site}_" if site else ""
        destination = (
            Path(output_dir).expanduser()
            / "Plots"
            / instrument
            / "DSD"
            / year
            / f"{site_prefix}{instrument}_{stamp:%Y_%m%d}_dsd.png"
        )
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, dpi=dpi, bbox_inches="tight")
    if show:
        plt.show()
    return figure, axis, colorbar, str(destination) if destination is not None else None


def _numeric_edges(centers):
    """Convert increasing numeric bin centers to cell edges."""
    centers = np.asarray(centers, dtype=float)
    if len(centers) == 1:
        width = max(abs(centers[0]) * 0.1, 0.5)
        return np.array([centers[0] - width, centers[0] + width])
    midpoints = (centers[:-1] + centers[1:]) / 2.0
    return np.concatenate((
        [centers[0] - (midpoints[0] - centers[0])],
        midpoints,
        [centers[-1] + (centers[-1] - midpoints[-1])],
    ))


def _datetime_edges(index):
    """Convert increasing datetime centers to midpoint-based cell edges."""
    timestamps = pd.DatetimeIndex(index)
    nanoseconds = timestamps.asi8
    if len(nanoseconds) == 1:
        half_width = pd.Timedelta(seconds=30).value
        edges = np.array([nanoseconds[0] - half_width, nanoseconds[0] + half_width])
    else:
        midpoints = nanoseconds[:-1] + (nanoseconds[1:] - nanoseconds[:-1]) // 2
        edges = np.concatenate((
            [nanoseconds[0] - (midpoints[0] - nanoseconds[0])],
            midpoints,
            [nanoseconds[-1] + (nanoseconds[-1] - midpoints[-1])],
        ))
    return pd.to_datetime(edges)
