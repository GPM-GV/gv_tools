"""Standard quicklook plots for normalized GV datasets."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr


def _pyplot():
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("quicklooks require matplotlib; install GV Tools with the 'plot' extra") from exc
    return plt


def _time_series_dataset(data):
    """Return an xarray Dataset from an AIO Dataset or pandas DataFrame."""
    if isinstance(data, xr.Dataset):
        return data
    try:
        import pandas as pd
    except ImportError:
        pd = None
    if pd is not None and isinstance(data, pd.DataFrame):
        if "time" in data.columns:
            frame = data.set_index("time")
        elif data.index.name == "time":
            frame = data
        else:
            raise ValueError("DataFrame must contain a 'time' column or time index")
        dataset = frame.to_xarray()
        dataset.attrs.update(getattr(data, "attrs", {}))
        return dataset
    raise TypeError("quicklook data must be an xarray Dataset or pandas DataFrame")


def _dataset_plot_title(dataset, plot_name, *, date=None, title=None):
    """Return a title containing site, observation date, and instrument."""
    site = next(
        (
            str(dataset.attrs.get(key, "")).strip()
            for key in ("site_id", "site_name", "facility", "location")
            if str(dataset.attrs.get(key, "")).strip()
        ),
        "Unknown site",
    )
    instrument = next(
        (str(dataset.attrs.get(key, "")).strip() for key in ("instrument_id", "instrument_name", "model", "mrr_model")
         if str(dataset.attrs.get(key, "")).strip()),
        "Unknown instrument",
    )
    if date is None:
        times = np.asarray(dataset.time.values)
        date = np.datetime_as_string(times[0].astype("datetime64[D]"), unit="D")
    context = f"{site} | {instrument} | {date}"
    return f"{title}\n{context}" if title else f"{context} — {plot_name}"


def _radar_plot_identity(metadata):
    site = next(
        (str(metadata.get(key, "")).strip() for key in ("site_name", "site_id", "facility", "location")
         if str(metadata.get(key, "")).strip()),
        "Unknown site",
    )
    instrument = next(
        (str(metadata.get(key, "")).strip() for key in ("instrument_name", "platform_id", "radar_name")
         if str(metadata.get(key, "")).strip()),
        "Radar",
    )
    return site, instrument


def _radar_plot_title(metadata, timestamp, plot_name, *, details="", title=None):
    site, instrument = _radar_plot_identity(metadata)
    date = timestamp.strftime("%Y-%m-%d")
    context = f"{site} | {instrument} | {date}"
    heading = f"{title}\n{context}" if title else f"{context} — {plot_name}"
    return f"{heading}\n{timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}{details}"


def plot_aio_quicklook(
    dataset: xr.Dataset,
    output: str | Path | None = None,
    *,
    savefig: str | Path | None = None,
    title: str | None = None,
    direction_bins: int = 16,
    speed_bins=(0, 1, 2, 4, 6, 8, np.inf),
):
    """Plot a three-row, two-column AIO dashboard and return the Figure."""
    dataset = _time_series_dataset(dataset)
    required = {
        "air_temperature",
        "air_pressure",
        "relative_humidity",
        "wind_speed",
        "wind_from_direction",
    }
    missing = sorted(required.difference(dataset.data_vars))
    if missing:
        raise ValueError(f"dataset is missing AIO quicklook variables: {missing}")
    if "time" not in dataset.coords or dataset.sizes.get("time", 0) == 0:
        raise ValueError("dataset must contain at least one time observation")
    if direction_bins < 4:
        raise ValueError("direction_bins must be at least 4")
    if output is not None and savefig is not None:
        raise ValueError("use either output or savefig, not both")
    if savefig is not None:
        save_path = Path(savefig).expanduser()
        if not save_path.is_absolute() or not save_path.name or not save_path.suffix:
            raise ValueError("savefig must be a full path including an image filename")
    else:
        save_path = None if output is None else Path(output).expanduser()

    plt = _pyplot()
    figure = plt.figure(figsize=(16, 13))
    grid = figure.add_gridspec(3, 2, hspace=0.34, wspace=0.28)
    temperature_axis = figure.add_subplot(grid[0, 0])
    pressure_axis = figure.add_subplot(grid[1, 0], sharex=temperature_axis)
    humidity_axis = figure.add_subplot(grid[2, 0], sharex=temperature_axis)
    wind_axis = figure.add_subplot(grid[0, 1], sharex=temperature_axis)
    direction_axis = wind_axis.twinx()
    rose_axis = figure.add_subplot(grid[1, 1], projection="polar")
    text_axis = figure.add_subplot(grid[2, 1])

    times = dataset.time.values
    time_panels = (
        (temperature_axis, "air_temperature", "Temperature (°C)", "tab:red"),
        (pressure_axis, "air_pressure", "Pressure (hPa)", "tab:purple"),
        (humidity_axis, "relative_humidity", "Humidity (%)", "tab:green"),
    )
    for axis, name, label, color in time_panels:
        axis.plot(times, dataset[name].values, color=color, linewidth=1.1)
        axis.set_ylabel(label, fontsize=13)
        axis.grid(True, alpha=0.35)
        axis.tick_params(labelsize=11)

    wind_axis.plot(times, dataset.wind_speed.values, color="tab:blue", linewidth=1.1)
    direction_axis.plot(times, dataset.wind_from_direction.values, color="tab:orange", linewidth=1.0)
    wind_axis.set_ylabel("Wind speed (m/s)", color="tab:blue", fontsize=13)
    direction_axis.set_ylabel("Wind direction (°)", color="tab:orange", fontsize=13)
    direction_axis.set_ylim(0, 360)
    direction_axis.set_yticks(np.arange(0, 361, 90))
    wind_axis.tick_params(axis="y", colors="tab:blue", labelsize=11)
    direction_axis.tick_params(axis="y", colors="tab:orange", labelsize=11)
    wind_axis.tick_params(axis="x", labelsize=11)
    wind_axis.grid(True, alpha=0.35)

    speeds = np.asarray(dataset.wind_speed.values, dtype=float)
    directions = np.asarray(dataset.wind_from_direction.values, dtype=float) % 360
    valid = np.isfinite(speeds) & np.isfinite(directions) & (speeds >= 0)
    if valid.any():
        direction_edges = np.linspace(-180 / direction_bins, 360 - 180 / direction_bins, direction_bins + 1)
        shifted = (directions[valid] + 180 / direction_bins) % 360 - 180 / direction_bins
        speed_edges = np.asarray(speed_bins, dtype=float)
        counts, _, _ = np.histogram2d(shifted, speeds[valid], bins=(direction_edges, speed_edges))
        frequencies = counts / valid.sum() * 100.0
        width = 2 * np.pi / direction_bins
        angles = np.arange(direction_bins) * width
        bottom = np.zeros(direction_bins)
        labels = []
        for index in range(len(speed_edges) - 1):
            upper = speed_edges[index + 1]
            labels.append(f"{speed_edges[index]:g}–{upper:g}" if np.isfinite(upper) else f"≥{speed_edges[index]:g}")
            rose_axis.bar(
                angles,
                frequencies[:, index],
                width=width,
                bottom=bottom,
                align="center",
                edgecolor="white",
                linewidth=0.35,
            )
            bottom += frequencies[:, index]
        rose_axis.legend(labels, title="Wind speed (m/s)", fontsize=8, title_fontsize=9, loc="upper left", bbox_to_anchor=(1.02, 1.08))
    else:
        rose_axis.text(0.5, 0.5, "No valid wind observations", transform=rose_axis.transAxes, ha="center", va="center")
    rose_axis.set_theta_zero_location("N")
    rose_axis.set_theta_direction(-1)
    rose_axis.set_title("Wind rose", fontsize=14, pad=15)

    first_time = np.datetime_as_string(np.asarray(times)[0], unit="s")
    last_time = np.datetime_as_string(np.asarray(times)[-1], unit="s")
    source_files = dataset.attrs.get("source_files", dataset.attrs.get("source", "Not specified"))
    if isinstance(source_files, (list, tuple)):
        source_files = ", ".join(Path(str(item)).name for item in source_files)
    info = (
        f"Site: {dataset.attrs.get('site_id', 'Not specified')}\n"
        f"Instrument: {dataset.attrs.get('instrument_id', 'Not specified')}\n"
        f"Model: {dataset.attrs.get('model', 'Not specified')}\n"
        f"Observations: {dataset.sizes['time']:,}\n"
        f"Start UTC: {first_time}\n"
        f"End UTC: {last_time}\n"
        f"Source: {source_files}"
    )
    text_axis.axis("off")
    text_axis.text(
        0.04,
        0.96,
        info,
        transform=text_axis.transAxes,
        va="top",
        ha="left",
        fontsize=12,
        linespacing=1.5,
        bbox={"boxstyle": "round,pad=0.7", "facecolor": "whitesmoke", "edgecolor": "0.45"},
    )
    text_axis.set_title("Data summary", fontsize=14, pad=10)

    pressure_axis.tick_params(labelbottom=False)
    temperature_axis.tick_params(labelbottom=False)
    wind_axis.tick_params(labelbottom=False)
    humidity_axis.set_xlabel("UTC time", fontsize=13)
    figure.suptitle(_dataset_plot_title(dataset, "AIO quicklook", title=title), fontsize=18, y=0.99)
    figure.subplots_adjust(left=0.08, right=0.92, top=0.94, bottom=0.07)
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close(figure)
        print(f"Plot saved to {save_path}")
    return figure


def plot_aio_wind_rose(
    dataset: xr.Dataset,
    output: str | Path | None = None,
    *,
    direction_bins: int = 16,
    speed_bins=(0, 1, 2, 4, 6, 8, np.inf),
    title: str | None = None,
):
    """Plot direction/speed occurrence percentages and return Figure, Axes, and frequencies."""
    dataset = _time_series_dataset(dataset)
    if direction_bins < 4:
        raise ValueError("direction_bins must be at least 4")
    for name in ("wind_speed", "wind_from_direction"):
        if name not in dataset:
            raise ValueError(f"dataset is missing {name!r}")
    speeds = np.asarray(dataset.wind_speed.values, dtype=float)
    directions = np.asarray(dataset.wind_from_direction.values, dtype=float) % 360
    valid = np.isfinite(speeds) & np.isfinite(directions) & (speeds >= 0)
    if not valid.any():
        raise ValueError("dataset has no valid wind observations")
    edges = np.linspace(-180 / direction_bins, 360 - 180 / direction_bins, direction_bins + 1)
    shifted = (directions[valid] + 180 / direction_bins) % 360 - 180 / direction_bins
    counts, _, _ = np.histogram2d(shifted, speeds[valid], bins=(edges, np.asarray(speed_bins, dtype=float)))
    frequencies = counts / valid.sum() * 100.0
    width = 2 * np.pi / direction_bins
    angles = np.arange(direction_bins) * width
    plt = _pyplot()
    figure, axis = plt.subplots(figsize=(8, 8), subplot_kw={"projection": "polar"})
    bottom = np.zeros(direction_bins)
    labels = []
    speed_edges = np.asarray(speed_bins, dtype=float)
    for index in range(len(speed_edges) - 1):
        upper = speed_edges[index + 1]
        labels.append(f"{speed_edges[index]:g}–{upper:g}" if np.isfinite(upper) else f"≥{speed_edges[index]:g}")
        axis.bar(angles, frequencies[:, index], width=width, bottom=bottom, align="center", edgecolor="white", linewidth=0.4)
        bottom += frequencies[:, index]
    axis.set_theta_zero_location("N")
    axis.set_theta_direction(-1)
    axis.set_title(_dataset_plot_title(dataset, "AIO wind rose", title=title), pad=20)
    axis.legend(labels, title="Wind speed (m/s)", loc="upper left", bbox_to_anchor=(1.05, 1.0))
    if output is not None:
        destination = Path(output).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, dpi=150, bbox_inches="tight")
    return figure, axis, frequencies


def plot_ws800_full_quicklook(
    data,
    output: str | Path | None = None,
    *,
    savefig: str | Path | None = None,
    title: str | None = None,
    colors: dict[str, str] | None = None,
    linewidth: float = 1.1,
    figsize=(15, 18),
    dpi: int = 150,
):
    """Plot six stacked field-family panels for full Lufft WS800 data.

    ``data`` may be the pandas DataFrame or xarray Dataset returned by
    ``read_ws800_full``. Each panel contains every available field in its
    family: air temperature, dew point, relative humidity, absolute humidity,
    mixing ratio, and lightning. ``colors`` optionally maps field names to
    Matplotlib colors.
    """
    dataset = _time_series_dataset(data)
    if "time" not in dataset.coords or dataset.sizes.get("time", 0) == 0:
        raise ValueError("data must contain at least one time observation")
    if not np.isfinite(linewidth) or linewidth <= 0:
        raise ValueError("linewidth must be positive")
    if output is not None and savefig is not None:
        raise ValueError("use either output or savefig, not both")
    if savefig is not None:
        save_path = Path(savefig).expanduser()
        if not save_path.is_absolute() or not save_path.name or not save_path.suffix:
            raise ValueError("savefig must be a full path including an image filename")
    else:
        save_path = None if output is None else Path(output).expanduser()

    groups = (
        ("Air temperature", "Temperature (°C)", ("air_temperature",), ("air_temp_",)),
        ("Dew point", "Temperature (°C)", ("dew_point_temperature",), ("dew_point_",)),
        ("Relative humidity", "Relative humidity (%)", ("relative_humidity",), ("rel_hum_",)),
        ("Absolute humidity", "Absolute humidity (g m⁻³)", (), ("abs_hum_",)),
        ("Mixing ratio", "Mixing ratio (g kg⁻¹)", ("mixing_ratio",), ("mixing_ratio_",)),
        ("Lightning", "Lightning", (), ("lightning_",)),
    )

    def matching_fields(exact_names, prefixes):
        return [
            name for name in dataset.data_vars
            if name in exact_names or any(name.startswith(prefix) for prefix in prefixes)
        ]

    colors = {} if colors is None else dict(colors)
    unknown_colors = sorted(set(colors).difference(dataset.data_vars))
    if unknown_colors:
        raise ValueError(f"colors contains unavailable WS800 fields: {unknown_colors}")

    plt = _pyplot()
    figure, axes = plt.subplots(6, 1, sharex=True, figsize=figsize)
    times = dataset.time.values
    for axis, (panel_title, ylabel, exact_names, prefixes) in zip(axes, groups):
        fields = matching_fields(exact_names, prefixes)
        for name in fields:
            axis.plot(
                times,
                np.asarray(dataset[name].values, dtype=float),
                label=name,
                color=colors.get(name),
                linewidth=linewidth,
            )
        if fields:
            axis.legend(loc="best", fontsize=9, ncol=min(3, len(fields)))
        else:
            axis.text(0.5, 0.5, "No matching fields", transform=axis.transAxes,
                      ha="center", va="center", color="0.4", fontsize=11)
        axis.set_title(panel_title, fontsize=14, loc="left")
        axis.set_ylabel(ylabel, fontsize=11)
        axis.grid(True, alpha=0.35)
        axis.tick_params(labelsize=10)

    axes[-1].set_xlabel("UTC time", fontsize=12)
    figure.suptitle(_dataset_plot_title(dataset, "Lufft WS800 full quicklook", title=title), fontsize=18, y=0.992)
    figure.subplots_adjust(left=0.11, right=0.97, top=0.955, bottom=0.06, hspace=0.32)
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(save_path, dpi=dpi, bbox_inches="tight")
        plt.close(figure)
        print(f"Plot saved to {save_path}")
    return figure


def plot_radar_ppi_quicklook(
    radar,
    output: str | Path | None = None,
    *,
    savefig: str | Path | None = None,
    field: str | None = None,
    sweep: int = 0,
    cmap: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    max_range_km: float | None = None,
    range_ring_interval_km: float | None = 25.0,
    range_ring_color: str = "black",
    range_ring_linewidth: float = 0.8,
    radial_spoke_interval_deg: float | None = 30.0,
    radial_spoke_color: str = "black",
    radial_spoke_linewidth: float = 0.6,
    gridline_interval_deg: float | None = 1.0,
    map_resolution: str = "50m",
    add_map_features: bool = True,
    add_borders: bool = True,
    projection=None,
    colorbar_label: str | None = None,
    title: str | None = None,
    figsize=(13, 11),
    dpi: int = 150,
):
    """Plot a mapped Py-ART PPI sweep with geographic and radar overlays.

    Radial-spoke spacing is specified in degrees; range-ring spacing and
    ``max_range_km`` are specified in kilometers. Set either interval to
    ``None`` to disable that overlay.
    """
    try:
        import pyart
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
    except ImportError as exc:
        raise ImportError("radar PPI quicklooks require arm-pyart and cartopy; install the 'radar' extra") from exc

    scan_type = str(getattr(radar, "scan_type", "")).lower()
    recorded_type = str(getattr(radar, "metadata", {}).get("gv_tools_scan_type", "")).upper()
    if (scan_type and scan_type != "ppi") or (recorded_type and recorded_type != "PPI"):
        raise ValueError(f"plot_radar_ppi_quicklook requires a PPI radar volume, found {recorded_type or scan_type}")
    sweep = int(sweep)
    nsweeps = int(getattr(radar, "nsweeps", 0))
    if sweep < 0 or sweep >= nsweeps:
        raise ValueError(f"sweep must be between 0 and {max(nsweeps - 1, 0)}")
    if not getattr(radar, "fields", None):
        raise ValueError("radar contains no fields to plot")
    if field is None:
        preferred = ("reflectivity", "corrected_reflectivity", "DBZ", "DBZ_F", "DZ")
        field = next((name for name in preferred if name in radar.fields), next(iter(radar.fields)))
    if field not in radar.fields:
        raise ValueError(f"radar field {field!r} is unavailable; choose from {sorted(radar.fields)}")
    for value, name in (
        (max_range_km, "max_range_km"),
        (range_ring_interval_km, "range_ring_interval_km"),
        (radial_spoke_interval_deg, "radial_spoke_interval_deg"),
        (gridline_interval_deg, "gridline_interval_deg"),
    ):
        if value is not None and (not np.isfinite(value) or value <= 0):
            raise ValueError(f"{name} must be positive or None")
    if output is not None and savefig is not None:
        raise ValueError("use either output or savefig, not both")
    if savefig is not None:
        save_path = Path(savefig).expanduser()
        if not save_path.is_absolute() or not save_path.name or not save_path.suffix:
            raise ValueError("savefig must be a full path including an image filename")
    else:
        save_path = None if output is None else Path(output).expanduser()

    radar_range_km = float(np.nanmax(np.asarray(radar.range["data"], dtype=float))) / 1000.0
    plot_range_km = radar_range_km if max_range_km is None else float(max_range_km)
    radar_lat = float(np.asarray(radar.latitude["data"]).ravel()[0])
    radar_lon = float(np.asarray(radar.longitude["data"]).ravel()[0])
    if projection is None:
        projection = ccrs.LambertConformal(central_longitude=radar_lon, central_latitude=radar_lat)
    if cmap is None:
        cmap = pyart.config.get_field_colormap(field)
    default_vmin, default_vmax = pyart.config.get_field_limits(field, radar, sweep)
    vmin = default_vmin if vmin is None else vmin
    vmax = default_vmax if vmax is None else vmax

    lat_lines = lon_lines = None
    if gridline_interval_deg is not None:
        lat_span = plot_range_km / 111.0
        lon_span = plot_range_km / max(111.0 * np.cos(np.deg2rad(radar_lat)), 1.0)
        interval = float(gridline_interval_deg)
        lat_lines = np.arange(np.floor((radar_lat - lat_span) / interval) * interval,
                              np.ceil((radar_lat + lat_span) / interval) * interval + interval / 2, interval)
        lon_lines = np.arange(np.floor((radar_lon - lon_span) / interval) * interval,
                              np.ceil((radar_lon + lon_span) / interval) * interval + interval / 2, interval)

    plt = _pyplot()
    figure = plt.figure(figsize=figsize)
    axis = figure.add_subplot(1, 1, 1, projection=projection)
    display = pyart.graph.RadarMapDisplay(radar)
    display.plot_ppi_map(
        field,
        sweep=sweep,
        vmin=vmin,
        vmax=vmax,
        cmap=cmap,
        title_flag=False,
        colorbar_flag=True,
        colorbar_label=colorbar_label,
        ax=axis,
        fig=figure,
        width=2 * plot_range_km * 1000.0,
        height=2 * plot_range_km * 1000.0,
        resolution=map_resolution,
        embellish=False,
        add_grid_lines=gridline_interval_deg is not None,
        lat_lines=lat_lines,
        lon_lines=lon_lines,
        raster=True,
    )
    if add_map_features:
        axis.coastlines(resolution=map_resolution, linewidth=0.8, color="0.2", zorder=5)
    if add_borders:
        axis.add_feature(cfeature.BORDERS.with_scale(map_resolution), linewidth=0.8, edgecolor="0.2", zorder=5)
        axis.add_feature(cfeature.STATES.with_scale(map_resolution), linewidth=0.55, edgecolor="0.3", zorder=5)

    if range_ring_interval_km is not None:
        rings = np.arange(float(range_ring_interval_km), plot_range_km + 1e-9, float(range_ring_interval_km))
        ring_angles = np.linspace(0.0, 2.0 * np.pi, 361)
        for ring_km in rings:
            axis.plot(
                ring_km * 1000.0 * np.sin(ring_angles),
                ring_km * 1000.0 * np.cos(ring_angles),
                color=range_ring_color,
                linewidth=range_ring_linewidth,
                transform=display.grid_projection,
            )
    if radial_spoke_interval_deg is not None:
        for azimuth in np.arange(0.0, 360.0, float(radial_spoke_interval_deg)):
            radians = np.deg2rad(azimuth)
            x = plot_range_km * 1000.0 * np.sin(radians)
            y = plot_range_km * 1000.0 * np.cos(radians)
            end_lon, end_lat = pyart.core.cartesian_to_geographic_aeqd(x, y, radar_lon, radar_lat)
            display.plot_line_geo(
                [radar_lon, float(np.asarray(end_lon).ravel()[0])],
                [radar_lat, float(np.asarray(end_lat).ravel()[0])],
                line_style="-",
                color=radial_spoke_color,
                linewidth=radial_spoke_linewidth,
                alpha=0.8,
            )
    display.plot_point(radar_lon, radar_lat, symbol="k+", label_text="Radar")

    if hasattr(radar, "get_elevation"):
        elevation = np.asarray(radar.get_elevation(sweep), dtype=float)
    else:
        start = int(np.asarray(radar.sweep_start_ray_index["data"])[sweep])
        end = int(np.asarray(radar.sweep_end_ray_index["data"])[sweep]) + 1
        elevation = np.asarray(radar.elevation["data"], dtype=float)[start:end]
    fixed_angles = np.asarray(radar.fixed_angle["data"], dtype=float).ravel()
    fallback_elevation = float(np.nanmedian(elevation)) if np.isfinite(elevation).any() else float("nan")
    fixed_angle = float(fixed_angles[sweep]) if sweep < fixed_angles.size else fallback_elevation
    median_elevation = fallback_elevation if np.isfinite(fallback_elevation) else fixed_angle
    timestamp = pyart.util.datetime_from_radar(radar)
    metadata = getattr(radar, "metadata", {})
    field_metadata = radar.fields[field]
    field_name = str(field_metadata.get("long_name", field_metadata.get("standard_name", field))).replace("_", " ").title()
    verbose_title = _radar_plot_title(
        metadata, timestamp, f"{field_name} PPI",
        details=(
            f" | Sweep {sweep} of {nsweeps - 1} | "
            f"Elevation {median_elevation:.2f}° (target {fixed_angle:.2f}°)"
        ),
        title=title,
    )
    axis.set_title(verbose_title, fontsize=15, pad=16)
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(save_path, dpi=dpi, bbox_inches="tight")
        plt.close(figure)
        print(f"Plot saved to {save_path}")
    return figure


def plot_radar_rhi_quicklook(
    radar,
    output: str | Path | None = None,
    *,
    savefig: str | Path | None = None,
    field: str | None = None,
    sweep: int = 0,
    cmap: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    min_range_km: float | None = None,
    max_range_km: float | None = None,
    min_height_km: float = 0.0,
    max_height_km: float | None = None,
    reverse_xaxis: bool | None = None,
    symbols: dict | list[dict] | tuple[dict, ...] | None = None,
    colorbar_label: str | None = None,
    colorbar_orientation: str = "vertical",
    grid: bool = True,
    title: str | None = None,
    figsize=(14, 8),
    dpi: int = 150,
):
    """Plot a Py-ART RHI sweep with optional range-height symbols.

    Symbol dictionaries use ``{'Location': (range_km, height_km),
    'Color': color, 'Symbol': marker, 'Size': size}``. A single dictionary or
    a sequence of dictionaries is accepted.
    """
    try:
        import pyart
    except ImportError as exc:
        raise ImportError("radar RHI quicklooks require arm-pyart; install the 'radar' extra") from exc

    scan_type = str(getattr(radar, "scan_type", "")).lower()
    metadata = getattr(radar, "metadata", {})
    recorded_type = str(metadata.get("gv_tools_scan_type", "")).upper()
    if (scan_type and scan_type != "rhi") or (recorded_type and recorded_type != "RHI"):
        raise ValueError(f"plot_radar_rhi_quicklook requires an RHI radar volume, found {recorded_type or scan_type}")
    sweep = int(sweep)
    nsweeps = int(getattr(radar, "nsweeps", 0))
    if sweep < 0 or sweep >= nsweeps:
        raise ValueError(f"sweep must be between 0 and {max(nsweeps - 1, 0)}")
    if not getattr(radar, "fields", None):
        raise ValueError("radar contains no fields to plot")
    if field is None:
        preferred = ("reflectivity", "corrected_reflectivity", "DBZ", "DBZ_F", "DZ", "CZ")
        field = next((name for name in preferred if name in radar.fields), next(iter(radar.fields)))
    if field not in radar.fields:
        raise ValueError(f"radar field {field!r} is unavailable; choose from {sorted(radar.fields)}")
    if min_range_km is not None and max_range_km is not None and min_range_km >= max_range_km:
        raise ValueError("min_range_km must be less than max_range_km")
    if max_height_km is not None and min_height_km >= max_height_km:
        raise ValueError("min_height_km must be less than max_height_km")
    if colorbar_orientation not in {"vertical", "horizontal"}:
        raise ValueError("colorbar_orientation must be 'vertical' or 'horizontal'")
    if output is not None and savefig is not None:
        raise ValueError("use either output or savefig, not both")
    if savefig is not None:
        save_path = Path(savefig).expanduser()
        if not save_path.is_absolute() or not save_path.name or not save_path.suffix:
            raise ValueError("savefig must be a full path including an image filename")
    else:
        save_path = None if output is None else Path(output).expanduser()

    symbol_items = [] if symbols is None else [symbols] if isinstance(symbols, dict) else list(symbols)
    required_symbol_keys = {"Location", "Color", "Symbol", "Size"}
    for index, item in enumerate(symbol_items):
        if not isinstance(item, dict) or not required_symbol_keys.issubset(item):
            raise ValueError(f"symbols[{index}] must contain {sorted(required_symbol_keys)}")
        location = item["Location"]
        if not isinstance(location, (tuple, list)) or len(location) != 2:
            raise ValueError(f"symbols[{index}]['Location'] must be (range_km, height_km)")

    if cmap is None:
        cmap = pyart.config.get_field_colormap(field)
    default_vmin, default_vmax = pyart.config.get_field_limits(field, radar, sweep)
    vmin = default_vmin if vmin is None else vmin
    vmax = default_vmax if vmax is None else vmax
    plt = _pyplot()
    figure, axis = plt.subplots(figsize=figsize)
    display = pyart.graph.RadarDisplay(radar)
    display.plot_rhi(
        field,
        sweep=sweep,
        vmin=vmin,
        vmax=vmax,
        cmap=cmap,
        title_flag=False,
        axislabels=("Range from radar (km)", "Height above radar (km)"),
        reverse_xaxis=reverse_xaxis,
        colorbar_flag=True,
        colorbar_label=colorbar_label,
        colorbar_orient=colorbar_orientation,
        ax=axis,
        fig=figure,
        raster=True,
    )
    if min_range_km is not None or max_range_km is not None:
        left, right = axis.get_xlim()
        axis.set_xlim(left if min_range_km is None else min_range_km, right if max_range_km is None else max_range_km)
    if max_height_km is not None:
        axis.set_ylim(min_height_km, max_height_km)
    else:
        axis.set_ylim(bottom=min_height_km)
    axis.grid(grid, which="major", color="0.35", alpha=0.35, linewidth=0.8)
    axis.minorticks_on()
    axis.grid(grid, which="minor", color="0.6", alpha=0.16, linewidth=0.5)
    axis.axhline(0.0, color="0.15", linewidth=1.2, zorder=4)
    axis.tick_params(labelsize=11)
    axis.xaxis.label.set_size(13)
    axis.yaxis.label.set_size(13)
    for item in symbol_items:
        range_km, height_km = map(float, item["Location"])
        axis.scatter(range_km, height_km, c=[item["Color"]], marker=item["Symbol"], s=float(item["Size"]),
                     edgecolors="black", linewidths=0.6, zorder=8)

    start = int(np.asarray(radar.sweep_start_ray_index["data"])[sweep])
    end = int(np.asarray(radar.sweep_end_ray_index["data"])[sweep]) + 1
    azimuth = np.asarray(radar.azimuth["data"], dtype=float)[start:end]
    median_azimuth = float(np.nanmedian(azimuth)) if np.isfinite(azimuth).any() else float("nan")
    fixed_angles = np.asarray(radar.fixed_angle["data"], dtype=float).ravel()
    target_azimuth = float(fixed_angles[sweep]) if sweep < fixed_angles.size else median_azimuth
    timestamp = pyart.util.datetime_from_radar(radar)
    field_metadata = radar.fields[field]
    field_name = str(field_metadata.get("long_name", field_metadata.get("standard_name", field))).replace("_", " ").title()
    verbose_title = _radar_plot_title(
        metadata, timestamp, f"{field_name} RHI",
        details=(
            f" | Sweep {sweep} of {nsweeps - 1} | "
            f"Azimuth {median_azimuth:.2f}° (target {target_azimuth:.2f}°)"
        ),
        title=title,
    )
    axis.set_title(verbose_title, fontsize=15, pad=14)
    figure.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(save_path, dpi=dpi, bbox_inches="tight")
        plt.close(figure)
        print(f"Plot saved to {save_path}")
    return figure


def plot_radar_bb_zdr_calibration(
    radar,
    output: str | Path | None = None,
    *,
    savefig: str | Path | None = None,
    field: str | None = None,
    sweep: int = 0,
    min_range_km: float = 0.5,
    max_range_km: float | None = None,
    zdr_bounds: tuple[float, float] = (-3.0, 3.0),
    histogram_bins: int = 60,
    statistic: str = "median",
    reflectivity_field: str | None = None,
    reflectivity_bounds_dbz: tuple[float, float] | None = None,
    min_samples: int = 10,
    density_cmap: str = "viridis",
    title: str | None = None,
    figsize=(15, 8),
    dpi: int = 150,
):
    """Plot a birdbath ZDR calibration diagnostic and estimated correction.

    The reported bias is the selected center statistic of valid vertical ZDR
    samples. The recommended additive correction is the negative of that bias.
    Optional reflectivity bounds can isolate the desired calibration regime.
    """
    try:
        import pyart
    except ImportError as exc:
        raise ImportError("birdbath ZDR calibration plots require arm-pyart; install the 'radar' extra") from exc

    scan_type = str(getattr(radar, "scan_type", "")).lower()
    metadata = getattr(radar, "metadata", {})
    recorded_type = str(metadata.get("gv_tools_scan_type", "")).upper()
    is_birdbath = recorded_type == "BB" or scan_type in {"bb", "birdbath", "bird_bath", "vertical_pointing"}
    if not is_birdbath:
        raise ValueError(f"plot_radar_bb_zdr_calibration requires a BB radar volume, found {recorded_type or scan_type}")
    sweep = int(sweep)
    nsweeps = int(getattr(radar, "nsweeps", 0))
    if sweep < 0 or sweep >= nsweeps:
        raise ValueError(f"sweep must be between 0 and {max(nsweeps - 1, 0)}")
    fields = getattr(radar, "fields", {})
    if field is None:
        preferred = (
            "differential_reflectivity", "corrected_differential_reflectivity",
            "ZDR", "ZDRC", "DR", "ZD",
        )
        field = next((name for name in preferred if name in fields), None)
    if field is None or field not in fields:
        raise ValueError(f"no ZDR field was selected; choose from {sorted(fields)}")
    if len(zdr_bounds) != 2 or zdr_bounds[0] >= zdr_bounds[1]:
        raise ValueError("zdr_bounds must be an increasing (minimum, maximum) pair")
    if min_range_km < 0 or max_range_km is not None and min_range_km >= max_range_km:
        raise ValueError("range bounds must be non-negative and increasing")
    if histogram_bins < 5:
        raise ValueError("histogram_bins must be at least 5")
    if statistic not in {"median", "mean"}:
        raise ValueError("statistic must be 'median' or 'mean'")
    if min_samples < 1:
        raise ValueError("min_samples must be positive")
    if output is not None and savefig is not None:
        raise ValueError("use either output or savefig, not both")
    if savefig is not None:
        save_path = Path(savefig).expanduser()
        if not save_path.is_absolute() or not save_path.name or not save_path.suffix:
            raise ValueError("savefig must be a full path including an image filename")
    else:
        save_path = None if output is None else Path(output).expanduser()

    start = int(np.asarray(radar.sweep_start_ray_index["data"])[sweep])
    end = int(np.asarray(radar.sweep_end_ray_index["data"])[sweep]) + 1
    zdr = np.ma.asarray(fields[field]["data"])[start:end]
    ranges_km = np.asarray(radar.range["data"], dtype=float) / 1000.0
    elevation = np.deg2rad(np.asarray(radar.elevation["data"], dtype=float)[start:end])[:, None]
    heights_km = np.sin(elevation) * ranges_km[None, :]
    valid = ~np.ma.getmaskarray(zdr) & np.isfinite(np.ma.filled(zdr, np.nan))
    valid &= ranges_km[None, :] >= min_range_km
    if max_range_km is not None:
        valid &= ranges_km[None, :] <= max_range_km
    valid &= np.ma.filled(zdr >= zdr_bounds[0], False) & np.ma.filled(zdr <= zdr_bounds[1], False)

    reflectivity_note = "No reflectivity filter"
    if reflectivity_bounds_dbz is not None:
        if len(reflectivity_bounds_dbz) != 2 or reflectivity_bounds_dbz[0] >= reflectivity_bounds_dbz[1]:
            raise ValueError("reflectivity_bounds_dbz must be an increasing pair")
        if reflectivity_field is None:
            reflectivity_candidates = ("reflectivity", "corrected_reflectivity", "DBZ", "DBZ_F", "DZ", "CZ")
            reflectivity_field = next((name for name in reflectivity_candidates if name in fields), None)
        if reflectivity_field is None or reflectivity_field not in fields:
            raise ValueError("reflectivity_bounds_dbz requires an available reflectivity_field")
        reflectivity = np.ma.asarray(fields[reflectivity_field]["data"])[start:end]
        low_dbz, high_dbz = reflectivity_bounds_dbz
        valid &= np.ma.filled(reflectivity >= low_dbz, False) & np.ma.filled(reflectivity <= high_dbz, False)
        reflectivity_note = f"{reflectivity_field}: {low_dbz:g} to {high_dbz:g} dBZ"

    zdr_values = np.asarray(zdr)[valid].astype(float)
    height_values = heights_km[valid].astype(float)
    if zdr_values.size < min_samples:
        raise ValueError(f"only {zdr_values.size} valid ZDR samples remain; min_samples={min_samples}")
    center = float(np.nanmedian(zdr_values) if statistic == "median" else np.nanmean(zdr_values))
    correction = -center
    mean = float(np.nanmean(zdr_values))
    standard_deviation = float(np.nanstd(zdr_values))

    gate_profile = np.ma.masked_where(~valid, zdr)
    profile = np.ma.median(gate_profile, axis=0).filled(np.nan)
    gates_with_samples = np.any(valid, axis=0)
    profile_height = np.full(ranges_km.shape, np.nan, dtype=float)
    profile_height[gates_with_samples] = np.nanmedian(
        np.where(valid[:, gates_with_samples], heights_km[:, gates_with_samples], np.nan), axis=0
    )
    profile_valid = np.isfinite(profile) & np.isfinite(profile_height)

    plt = _pyplot()
    figure, (profile_axis, histogram_axis) = plt.subplots(
        1, 2, figsize=figsize, gridspec_kw={"width_ratios": (1.7, 1.0), "wspace": 0.18}
    )
    density = profile_axis.hexbin(
        zdr_values, height_values, gridsize=(55, 45), bins="log", mincnt=1,
        cmap=density_cmap, extent=(zdr_bounds[0], zdr_bounds[1], 0, float(np.nanmax(height_values))),
    )
    density_colorbar = figure.colorbar(density, ax=profile_axis, pad=0.02)
    density_colorbar.set_label("Samples per bin", fontsize=12)
    profile_axis.plot(profile[profile_valid], profile_height[profile_valid], color="white", linewidth=3.2, label="Gate median")
    profile_axis.plot(profile[profile_valid], profile_height[profile_valid], color="black", linewidth=1.3)
    profile_axis.axvline(0.0, color="white", linestyle="--", linewidth=1.5, label="Expected 0 dB")
    profile_axis.axvline(center, color="magenta", linestyle="-", linewidth=2.0, label=f"{statistic.title()} bias")
    profile_axis.set_xlim(*zdr_bounds)
    profile_axis.set_ylim(bottom=0)
    profile_axis.set_xlabel("Differential reflectivity, ZDR (dB)", fontsize=13)
    profile_axis.set_ylabel("Height above radar (km)", fontsize=13)
    profile_axis.grid(True, alpha=0.25)
    profile_axis.legend(loc="best", fontsize=10)

    histogram_axis.hist(zdr_values, bins=histogram_bins, range=zdr_bounds, color="steelblue", edgecolor="white", alpha=0.9)
    histogram_axis.axvline(0.0, color="black", linestyle="--", linewidth=1.5, label="Expected 0 dB")
    histogram_axis.axvline(center, color="magenta", linewidth=2.0, label=f"{statistic.title()} = {center:+.3f} dB")
    histogram_axis.set_xlim(*zdr_bounds)
    histogram_axis.set_xlabel("Differential reflectivity, ZDR (dB)", fontsize=13)
    histogram_axis.set_ylabel("Gate samples", fontsize=13)
    histogram_axis.grid(True, alpha=0.25)
    histogram_axis.legend(loc="best", fontsize=10)
    summary = (
        f"Valid samples: {zdr_values.size:,}\n"
        f"Median: {np.nanmedian(zdr_values):+.3f} dB\n"
        f"Mean: {mean:+.3f} dB\n"
        f"Std. dev.: {standard_deviation:.3f} dB\n\n"
        f"Estimated ZDR bias: {center:+.3f} dB\n"
        f"Recommended additive correction: {correction:+.3f} dB\n\n"
        f"{reflectivity_note}"
    )
    histogram_axis.text(
        0.98, 0.96, summary, transform=histogram_axis.transAxes, ha="right", va="top",
        fontsize=10.5, linespacing=1.35,
        bbox={"boxstyle": "round,pad=0.6", "facecolor": "white", "edgecolor": "0.4", "alpha": 0.92},
    )
    for axis in (profile_axis, histogram_axis):
        axis.tick_params(labelsize=11)

    timestamp = pyart.util.datetime_from_radar(radar)
    sweep_elevation = np.asarray(radar.elevation["data"], dtype=float)[start:end]
    median_elevation = float(np.nanmedian(sweep_elevation))
    verbose_title = _radar_plot_title(
        metadata, timestamp, "Birdbath ZDR Calibration",
        details=(
            f" | Sweep {sweep} of {nsweeps - 1} | Elevation {median_elevation:.2f}° | "
            f"Correction {correction:+.3f} dB"
        ),
        title=title,
    )
    figure.suptitle(verbose_title, fontsize=16, y=0.99)
    figure.subplots_adjust(top=0.87, bottom=0.11, left=0.08, right=0.96)
    figure.gv_tools_zdr_calibration = {
        "field": field, "statistic": statistic, "bias_db": center,
        "additive_correction_db": correction, "sample_count": int(zdr_values.size),
    }
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(save_path, dpi=dpi, bbox_inches="tight")
        plt.close(figure)
        print(f"Plot saved to {save_path}")
    return figure


def plot_mrr_time_height_quicklook(
    dataset: xr.Dataset,
    fields: list[str] | tuple[str, ...],
    output: str | Path | None = None,
    *,
    savefig: str | Path | None = None,
    cmaps: str | dict[str, str] = "viridis",
    colorbar_bounds: tuple[float, float] | dict[str, tuple[float, float]] | None = None,
    field_labels: dict[str, str] | None = None,
    height_range_km: tuple[float, float] | None = None,
    time_range: tuple[object, object] | None = None,
    colorbar_location: str = "right",
    grid: bool = True,
    title: str | None = None,
    figsize: tuple[float, float] | None = None,
    dpi: int = 150,
):
    """Plot selected MRR2 or MRRPro fields as stacked time-height panels."""
    if not isinstance(dataset, xr.Dataset):
        raise TypeError("MRR quicklook input must be an xarray Dataset")
    model = str(dataset.attrs.get("mrr_model", ""))
    if model not in {"MRR2", "MRRPro"}:
        raise ValueError("dataset must be returned by read_mrr and identify MRR2 or MRRPro")
    if not isinstance(fields, (list, tuple)) or not fields or not all(isinstance(name, str) and name for name in fields):
        raise ValueError("fields must be a non-empty list or tuple of field names")
    if len(set(fields)) != len(fields):
        raise ValueError("fields must not contain duplicates")
    missing = [name for name in fields if name not in dataset.data_vars]
    if missing:
        raise ValueError(f"MRR fields are unavailable: {missing}; choose from {sorted(dataset.data_vars)}")
    if "time" not in dataset.coords or dataset.sizes.get("time", 0) == 0:
        raise ValueError("MRR dataset must contain at least one time observation")
    if colorbar_location not in {"left", "right", "top", "bottom"}:
        raise ValueError("colorbar_location must be 'left', 'right', 'top', or 'bottom'")
    if height_range_km is not None and (len(height_range_km) != 2 or height_range_km[0] >= height_range_km[1]):
        raise ValueError("height_range_km must be an increasing pair")
    if time_range is not None and (len(time_range) != 2 or np.datetime64(time_range[0]) >= np.datetime64(time_range[1])):
        raise ValueError("time_range must be an increasing pair")
    if output is not None and savefig is not None:
        raise ValueError("use either output or savefig, not both")
    if savefig is not None:
        save_path = Path(savefig).expanduser()
        if not save_path.is_absolute() or not save_path.name or not save_path.suffix:
            raise ValueError("savefig must be a full path including an image filename")
    else:
        save_path = None if output is None else Path(output).expanduser()

    def setting(value, field_name, default=None):
        if isinstance(value, dict):
            return value.get(field_name, default)
        return value if value is not None else default

    field_labels = {} if field_labels is None else field_labels
    prepared = []
    for name in fields:
        variable = dataset[name]
        if "time" not in variable.dims or variable.ndim != 2:
            raise ValueError(f"MRR field {name!r} must be a two-dimensional time-height variable")
        vertical_dims = [dimension for dimension in variable.dims if dimension != "time"]
        if len(vertical_dims) != 1:
            raise ValueError(f"cannot determine one vertical dimension for MRR field {name!r}")
        vertical_dim = vertical_dims[0]
        data = variable.transpose("time", vertical_dim)
        if model == "MRR2" and "MRR_H" in dataset and vertical_dim in dataset["MRR_H"].dims:
            height = dataset["MRR_H"]
            if "time" in height.dims:
                height_values = np.nanmedian(np.asarray(height.transpose("time", vertical_dim), dtype=float), axis=0)
            else:
                height_values = np.asarray(height, dtype=float)
        elif vertical_dim in dataset.coords:
            coordinate = dataset.coords[vertical_dim]
            coordinate_values = np.asarray(coordinate, dtype=float)
            height_values = np.nanmedian(coordinate_values, axis=0) if coordinate_values.ndim == 2 else coordinate_values
        elif vertical_dim in dataset:
            height_values = np.asarray(dataset[vertical_dim], dtype=float)
        else:
            raise ValueError(f"cannot determine heights for MRR field {name!r}")
        units = str((dataset["MRR_H"] if model == "MRR2" and "MRR_H" in dataset else dataset.get(vertical_dim, xr.DataArray())).attrs.get("units", "m")).lower()
        if units in {"km", "kilometer", "kilometers"}:
            height_km = height_values
        else:
            height_km = height_values / 1000.0
        if height_km.ndim != 1 or height_km.size != data.sizes[vertical_dim]:
            raise ValueError(f"height coordinate for MRR field {name!r} is incompatible with its data")
        bounds = setting(colorbar_bounds, name)
        if bounds is not None and (len(bounds) != 2 or bounds[0] >= bounds[1]):
            raise ValueError(f"colorbar bounds for {name!r} must be an increasing pair")
        prepared.append((name, data, height_km, bounds))

    plt = _pyplot()
    import matplotlib.dates as mdates

    panel_count = len(fields)
    if figsize is None:
        figsize = (15, max(3.2 * panel_count, 4.5))
    figure, axes = plt.subplots(panel_count, 1, figsize=figsize, sharex=True, squeeze=False)
    axes = axes[:, 0]
    times = np.asarray(dataset.time.values)
    horizontal_colorbar = colorbar_location in {"top", "bottom"}
    for axis, (name, data, height_km, bounds) in zip(axes, prepared):
        cmap_name = setting(cmaps, name, "viridis")
        cmap = plt.get_cmap(cmap_name).copy()
        cmap.set_bad("white")
        values = np.ma.masked_invalid(np.asarray(data, dtype=float))
        vmin, vmax = (None, None) if bounds is None else bounds
        mesh = axis.pcolormesh(times, height_km, values.T, shading="auto", cmap=cmap, vmin=vmin, vmax=vmax, rasterized=True)
        colorbar = figure.colorbar(
            mesh, ax=axis, location=colorbar_location,
            orientation="horizontal" if horizontal_colorbar else "vertical", pad=0.08 if horizontal_colorbar else 0.02,
        )
        variable = dataset[name]
        units = str(variable.attrs.get("units", "")).strip()
        long_name = str(variable.attrs.get("long_name", variable.attrs.get("standard_name", name))).replace("_", " ")
        colorbar.set_label(field_labels.get(name, f"{long_name} ({units})" if units else long_name), fontsize=11)
        axis.set_ylabel("Height (km)", fontsize=12)
        axis.set_title(field_labels.get(name, long_name), loc="left", fontsize=13, fontweight="semibold")
        axis.grid(grid, color="0.35", alpha=0.28, linewidth=0.7)
        axis.tick_params(labelsize=10)
        if height_range_km is not None:
            axis.set_ylim(*height_range_km)
    if time_range is not None:
        axes[-1].set_xlim(np.datetime64(time_range[0]), np.datetime64(time_range[1]))
    locator = mdates.AutoDateLocator(minticks=4, maxticks=12)
    axes[-1].xaxis.set_major_locator(locator)
    axes[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    axes[-1].set_xlabel("Time (UTC)", fontsize=12)
    start_time = np.datetime_as_string(times[0].astype("datetime64[s]"), unit="s")
    end_time = np.datetime_as_string(times[-1].astype("datetime64[s]"), unit="s")
    verbose_title = (
        _dataset_plot_title(dataset, f"{model} time–height profiles", title=title)
        + f"\n{start_time} to {end_time} UTC"
    )
    figure.suptitle(verbose_title, fontsize=16, y=0.995)
    figure.subplots_adjust(
        top=0.86,
        bottom=0.08,
        left=0.08,
        right=0.92,
        hspace=0.32,
    )
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(save_path, dpi=dpi, bbox_inches="tight")
        plt.close(figure)
        print(f"Plot saved to {save_path}")
    return figure


def plot_parsivel_quicklook(
    dataset: xr.Dataset,
    output: str | Path | None = None,
    *,
    savefig: str | Path | None = None,
    day=None,
    title: str | None = None,
    cmap="viridis",
    colorbar_bounds: tuple[float, float] | None = None,
    colorbar_location: str = "right",
    dsd_yrange: tuple[float, float] | None = None,
):
    """Plot one UTC day of Parsivel DSD and precipitation parameters.

    The six rows contain DSD, dBZ, rain rate, liquid-water content,
    concentration, and number of drops.

    ``savefig`` must be a full path including an image filename. The legacy
    positional ``output`` argument remains supported, but cannot be combined
    with ``savefig``. ``colorbar_bounds`` and ``dsd_yrange`` are two-item ``(minimum, maximum)``
    pairs. ``colorbar_location`` accepts ``"left"``, ``"right"``, ``"top"``,
    or ``"bottom"``. Zero-valued DSD bins are displayed in white.
    """
    required = {
        "drop_size_distribution",
        "radar_reflectivity",
        "precipitation_rate",
        "liquid_water_content",
        "number_concentration",
        "drop_count",
    }
    missing = sorted(required.difference(dataset.data_vars))
    if missing:
        raise ValueError(f"dataset is missing Parsivel variables: {missing}")
    if "time" not in dataset.coords or dataset.sizes.get("time", 0) == 0:
        raise ValueError("dataset must contain at least one time observation")
    if "drop_diameter" not in dataset.coords:
        raise ValueError("dataset must contain a drop_diameter coordinate")
    if output is not None and savefig is not None:
        raise ValueError("use either output or savefig, not both")
    if savefig is not None:
        save_path = Path(savefig).expanduser()
        if not save_path.is_absolute() or not save_path.name or not save_path.suffix:
            raise ValueError("savefig must be a full path including an image filename")
    else:
        save_path = None if output is None else Path(output).expanduser()

    def _validated_range(value, name):
        if value is None:
            return None
        if len(value) != 2:
            raise ValueError(f"{name} must contain exactly two values")
        lower, upper = (float(item) for item in value)
        if not np.isfinite([lower, upper]).all() or lower >= upper:
            raise ValueError(f"{name} must be finite and increasing")
        return lower, upper

    colorbar_bounds = _validated_range(colorbar_bounds, "colorbar_bounds")
    dsd_yrange = _validated_range(dsd_yrange, "dsd_yrange")
    colorbar_location = str(colorbar_location).lower()
    if colorbar_location not in {"left", "right", "top", "bottom"}:
        raise ValueError("colorbar_location must be 'left', 'right', 'top', or 'bottom'")

    times = np.asarray(dataset.time.values)
    selected_day = np.datetime64(day if day is not None else times[0], "D")
    day_end = selected_day + np.timedelta64(1, "D")
    daily = dataset.sel(time=slice(selected_day, day_end - np.timedelta64(1, "ns")))
    if daily.sizes.get("time", 0) == 0:
        raise ValueError(f"dataset has no observations for {str(selected_day)}")

    plt = _pyplot()
    import matplotlib.dates as mdates

    plot_cmap = plt.get_cmap(cmap).copy()
    plot_cmap.set_bad("white")
    dsd_values = np.asarray(
        daily.drop_size_distribution.transpose("drop_diameter", "time").values,
        dtype=float,
    )
    dsd_values = np.ma.masked_where(dsd_values == 0, dsd_values)

    figure, axes = plt.subplots(6, 1, figsize=(16, 17), sharex=True)
    axes = np.asarray(axes)
    color_limits = {} if colorbar_bounds is None else {"vmin": colorbar_bounds[0], "vmax": colorbar_bounds[1]}
    dsd = axes[0].pcolormesh(
        daily.time.values,
        daily.drop_diameter.values,
        dsd_values,
        shading="auto",
        cmap=plot_cmap,
        **color_limits,
    )
    axes[0].set_ylabel("Diameter (mm)", fontsize=14)
    if dsd_yrange is not None:
        axes[0].set_ylim(*dsd_yrange)
    units = daily.drop_size_distribution.attrs.get("units", "")
    colorbar_geometry = {
        "right": ([1.015, 0.0, 0.018, 1.0], "vertical"),
        "left": ([-0.075, 0.0, 0.018, 1.0], "vertical"),
        "top": ([0.0, 1.13, 1.0, 0.06], "horizontal"),
        "bottom": ([0.0, -0.28, 1.0, 0.06], "horizontal"),
    }
    bounds, orientation = colorbar_geometry[colorbar_location]
    colorbar_axis = axes[0].inset_axes(bounds)
    colorbar = figure.colorbar(dsd, cax=colorbar_axis, orientation=orientation)
    colorbar.set_label(f"DSD ({units})" if units else "DSD", fontsize=14)
    colorbar.ax.tick_params(labelsize=12)

    panels = (
        ("radar_reflectivity", "dBZ"),
        ("precipitation_rate", "Rain rate (mm h⁻¹)"),
        ("liquid_water_content", "LWC (g m⁻³)"),
        ("number_concentration", "Concentration (m⁻³)"),
        ("drop_count", "Number of drops"),
    )
    for axis, (name, label) in zip(axes[1:6], panels):
        axis.plot(daily.time.values, daily[name].values, linewidth=0.9)
        axis.set_ylabel(label, fontsize=14)

    axes[5].set_xlabel("UTC time", fontsize=14)

    for axis in axes:
        axis.grid(True, which="major", alpha=0.35)
        axis.set_xlim(selected_day, day_end)
        axis.tick_params(axis="both", labelsize=12)
    axes[5].xaxis.set_major_locator(mdates.HourLocator(interval=1))
    axes[5].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    date_text = str(selected_day)
    axes[0].set_title(
        _dataset_plot_title(dataset, "Parsivel quicklook", date=date_text, title=title),
        fontsize=17,
        pad=14,
    )
    figure.subplots_adjust(left=0.12, right=0.91, top=0.96, bottom=0.06, hspace=0.18)
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close(figure)
        print(f"Plot saved to {save_path}")
    return figure
