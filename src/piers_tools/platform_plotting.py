"""Create platform-specific PIERS, PIERS+, and PIERS++ summary plots."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import shutil
import tempfile
import textwrap

import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
import numpy as np
import pandas as pd

from .plotting import _dated_plot_path, _rain_accumulation, decimal_hour


_RM_YOUNG_LINE = re.compile(r"^(\d{14})\s+(.*)$")
_WS800_LINE = re.compile(r"^(\d{14}),\s*(.*)$")


def normalize_platform_type(value: object) -> str:
    """Return one of the three supported platform labels."""
    platform = str(value).strip().upper()
    if platform not in {"PIERS", "PIERS+", "PIERS++"}:
        raise ValueError(
            f"Unsupported Gauge type {value!r}; expected PIERS, PIERS+, or PIERS++"
        )
    return platform


def platform_plot_details(platform_type: object) -> tuple[str, str]:
    """Return the report plot category and filename suffix for a platform."""
    platform = normalize_platform_type(platform_type)
    if platform == "PIERS+":
        return "Platform", "piers_plus"
    if platform == "PIERS++":
        return "Platform", "piers_plus_plus"
    return "Rain", "rain"


def _prefer_daily(paths: list[Path]) -> list[Path]:
    daily = [path for path in paths if path.stem.casefold().endswith("_daily")]
    return daily or paths


def discover_instrument_files(day_dir: str | Path, gauge_id: str, data_date: date) -> dict[str, list[Path]]:
    """Discover additional instrument inputs for a PIERS site/day."""
    root = Path(day_dir)
    stamp = data_date.strftime("%Y%m%d")
    prefix = f"{gauge_id}_"
    groups = {
        "parsivel": sorted(root.glob(f"{prefix}Parsivel_{stamp}*.zip")),
        "wind": sorted(root.glob(f"{prefix}wind_{stamp}*.csv")),
        "wx": sorted(root.glob(f"{prefix}WX_{stamp}*.csv")),
        "ws800": sorted(
            [*root.glob(f"{prefix}WS_800_{stamp}*.csv"),
             *root.glob(f"{prefix}WS800_{stamp}*.csv")]
        ),
    }
    return {name: _prefer_daily(paths) for name, paths in groups.items()}


def _contains_ws800_rows(paths: list[Path]) -> bool:
    """Identify compact WS800 syntax even when files retain the legacy WX name."""
    for path in paths:
        with path.open("r", encoding="ascii", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    return _WS800_LINE.match(line.strip()) is not None
    return False


def _read_aio(paths: list[Path], kind: str, *, ws800: bool = False) -> pd.DataFrame:
    if kind == "wind":
        columns = ["wind_status", "wind_direction_deg", "wind_speed_m_s"]
    else:
        columns = [
            "wx_status", "wx_wind_speed_m_s", "wx_wind_direction_deg",
            "air_temperature_c", "relative_humidity_pct", "pressure_hpa",
        ]
    pattern = _WS800_LINE if ws800 else _RM_YOUNG_LINE
    rows = []
    for path in paths:
        first_line = path.read_text(
            encoding="ascii", errors="replace"
        ).splitlines()[0].strip()
        if ws800 and first_line.casefold().startswith("timestamp,"):
            source = pd.read_csv(path)
            source.columns = source.columns.astype(str).str.strip()
            field_map = {
                "Timestamp": "timestamp",
                "WindSpd_Act": "wx_wind_speed_m_s",
                "WindDir_Act": "wx_wind_direction_deg",
                "AirTemp_Act": "air_temperature_c",
                "RelHum_Act": "relative_humidity_pct",
                "AbsPress_Act": "pressure_hpa",
            }
            missing = [name for name in field_map if name not in source.columns]
            if missing:
                continue
            selected = source.loc[:, list(field_map)].rename(columns=field_map)
            selected["timestamp"] = pd.to_datetime(
                selected["timestamp"].astype("string"),
                format="%Y%m%d%H%M%S", errors="coerce",
            )
            selected.insert(1, "wx_status", 0.0)
            for column in columns:
                selected[column] = pd.to_numeric(selected[column], errors="coerce")
            rows.extend(selected.dropna(subset=["timestamp"]).to_dict("records"))
            continue
        for line in path.read_text(encoding="ascii", errors="replace").splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue
            try:
                values = [float(value) for value in match.group(2).split()]
            except ValueError:
                continue
            timestamp = pd.to_datetime(match.group(1), format="%Y%m%d%H%M%S", errors="coerce")
            if pd.isna(timestamp) or len(values) != len(columns):
                continue
            rows.append({"timestamp": timestamp, **dict(zip(columns, values))})
    if not rows:
        return pd.DataFrame(columns=["timestamp", *columns])
    return pd.DataFrame(rows).drop_duplicates().sort_values("timestamp", kind="stable")


def _one_minute(wind: pd.DataFrame, wx: pd.DataFrame) -> pd.DataFrame:
    products = []
    for frame, scalar_columns, direction_column in (
        (wind, ["wind_speed_m_s"], "wind_direction_deg"),
        (wx, ["wx_wind_speed_m_s", "air_temperature_c", "relative_humidity_pct", "pressure_hpa"], "wx_wind_direction_deg"),
    ):
        if frame.empty:
            continue
        indexed = frame.set_index("timestamp")
        scalar = indexed[scalar_columns].resample("1min").mean()
        direction = indexed[direction_column].resample("1min").apply(_circular_mean)
        products.append(pd.concat([scalar, direction], axis=1))
    return pd.concat(products, axis=1, join="outer").sort_index() if products else pd.DataFrame()


def _circular_mean(values: pd.Series) -> float:
    clean = values.dropna().to_numpy(dtype=float)
    if not len(clean):
        return np.nan
    radians = np.deg2rad(clean)
    return float(np.rad2deg(np.arctan2(np.sin(radians).mean(), np.cos(radians).mean())) % 360)


def _read_parsivel(paths: list[Path], gauge_id: str, data_date: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        from process_parsivel.core import process_input
    except ImportError as exc:
        raise RuntimeError(
            "PIERS+ plotting requires process-parsivel; install the bundled dependency"
        ) from exc
    with tempfile.TemporaryDirectory(prefix="piers_parsivel_") as temporary:
        staging = Path(temporary)
        for archive in paths:
            shutil.copy2(archive, staging / archive.name)
        parameters, psd, _ = process_input(
            staging, gauge_id, str(data_date.year), f"{data_date.month:02d}",
            f"{data_date.day:02d}", temp_root=staging,
        )
    return parameters, psd


def _gauge_frame(tip_data: pd.DataFrame, rain_tip_a_mm: float, rain_tip_b_mm: float) -> pd.DataFrame:
    series = []
    for bucket, label, calibration in (
        ("TB_A_tips", "A", rain_tip_a_mm), ("TB_B_tips", "B", rain_tip_b_mm)
    ):
        hours, accumulation = _rain_accumulation(tip_data, bucket, calibration)
        series.append((label, hours, accumulation))
    return series


def _style(axis: plt.Axes, ylabel: str) -> None:
    axis.set_xlim(0, 24)
    axis.set_xticks(np.arange(0, 25, 2))
    axis.set_ylabel(ylabel)
    axis.grid(True, alpha=0.3)


def generate_platform_plot(
    gauge_id: str,
    platform_type: object,
    data_date: date,
    day_dir: str | Path,
    tip_data: pd.DataFrame,
    *,
    rain_tip_a_mm: float,
    rain_tip_b_mm: float,
    station_location: str = "",
    plot_root: str | Path,
) -> Path | None:
    """Generate the Gauge-ID destination plot for PIERS+ or PIERS++."""
    platform = normalize_platform_type(platform_type)
    if platform == "PIERS":
        return None
    inputs = discover_instrument_files(day_dir, gauge_id, data_date)
    if not inputs["parsivel"]:
        raise FileNotFoundError(f"No Parsivel ZIP found for {gauge_id} on {data_date}")
    parameters, psd = _read_parsivel(inputs["parsivel"], gauge_id, data_date)
    if parameters.empty or psd.empty:
        raise ValueError(f"Parsivel products are empty for {gauge_id} on {data_date}")

    rows = 6 if platform == "PIERS++" else 3
    figure, axes = plt.subplots(rows, 2, figsize=(15, 2.4 * rows), sharex="col", squeeze=False)
    left, right = axes[:, 0], axes[:, 1]
    gauge = _gauge_frame(tip_data, rain_tip_a_mm, rain_tip_b_mm)

    if platform == "PIERS++":
        ws800 = inputs["ws800"]
        compact_wx = ws800 or (inputs["wx"] if _contains_ws800_rows(inputs["wx"]) else [])
        wind = _read_aio(inputs["wind"], "wind")
        wx = _read_aio(compact_wx or inputs["wx"], "wx", ws800=bool(compact_wx))
        if compact_wx:
            instrument_label = "Lufft WS800"
        elif not wind.empty and not wx.empty:
            instrument_label = "RM Young Wind/WX"
        else:
            raise FileNotFoundError(
                f"PIERS++ {gauge_id} requires one WS_800 file or both _wind_ and _WX_ files"
            )
        aio = _one_minute(wind, wx)
        panels = (
            (("wind_speed_m_s", "wx_wind_speed_m_s"), "Wind speed [m s$^{-1}$]"),
            (("wind_direction_deg", "wx_wind_direction_deg"), "Wind direction [degrees]"),
            (("air_temperature_c",), "Air temperature [°C]"),
            (("relative_humidity_pct",), "Relative humidity [%]"),
            (("pressure_hpa",), "Pressure [hPa]"),
        )
        for axis, (columns, ylabel) in zip(left[:5], panels):
            for column in columns:
                if column in aio:
                    axis.plot(decimal_hour(aio.index), aio[column], linewidth=0.8, label=column.replace("_", " "))
            _style(axis, ylabel)
            if axis.get_legend_handles_labels()[0]:
                axis.legend(fontsize="small")
        rain_axis = left[5]
        title = f"{gauge_id} PIERS++ ({instrument_label})"
    else:
        rain_axis = axes[0, 0]
        title = f"{gauge_id} PIERS+"

    if "Rain" in parameters:
        rain_axis.plot(decimal_hour(parameters.index), parameters["Rain"], label="Parsivel rain rate")
    accumulation_axis = rain_axis.twinx()
    for label, hours, accumulation in gauge:
        accumulation_axis.step(hours, accumulation, where="post", label=f"Gauge {label} cumulative")
    _style(rain_axis, "Rain rate [mm h$^{-1}$]")
    accumulation_axis.set_ylabel("Accumulated rain [mm]")
    handles1, labels1 = rain_axis.get_legend_handles_labels()
    handles2, labels2 = accumulation_axis.get_legend_handles_labels()
    rain_axis.legend(handles1 + handles2, labels1 + labels2, fontsize="small")

    diameters = pd.to_numeric(pd.Index(psd.columns), errors="coerce").to_numpy(dtype=float)
    valid_columns = np.isfinite(diameters)
    values = psd.loc[:, valid_columns].to_numpy(dtype=float).T
    dsd_axis = right[0] if platform == "PIERS++" else axes[0, 1]
    mesh = dsd_axis.pcolormesh(
        decimal_hour(psd.index), diameters[valid_columns],
        np.ma.masked_where(~np.isfinite(values) | (values < 1), values),
        shading="auto", norm=LogNorm(vmin=1, vmax=1e4), cmap="viridis",
    )
    _style(dsd_axis, "Drop diameter [mm]")
    color_axis = inset_axes(dsd_axis, width="48%", height="8%", loc="upper center")
    figure.colorbar(mesh, cax=color_axis, orientation="horizontal", label="DSD")
    if platform == "PIERS++":
        parameter_axes = right[1:]
        parameter_panels = (
            (("dBZ",), "Reflectivity [dBZ]"), (("LWC",), "LWC"),
            (("Dm", "Dmax"), "Dm / Dmax [mm]"), (("Total Drops",), "Total drops"),
            (("Concentration",), "Concentration"),
        )
        bottom_axes = (rain_axis, right[-1])
    else:
        parameter_axes = (axes[1, 0], axes[1, 1], axes[2, 0], axes[2, 1])
        parameter_panels = (
            (("dBZ",), "Reflectivity [dBZ]"),
            (("Dm", "Dmax"), "Dm / Dmax [mm]"),
            (("LWC",), "LWC"),
            (("Total Drops",), "Total drops"),
        )
        bottom_axes = (axes[2, 0], axes[2, 1])
    for axis, (columns, ylabel) in zip(parameter_axes, parameter_panels):
        for column in columns:
            if column in parameters:
                axis.plot(decimal_hour(parameters.index), parameters[column], linewidth=0.8, label=column)
        _style(axis, ylabel)
        if axis.get_legend_handles_labels()[0]:
            axis.legend(fontsize="small")
    for axis in bottom_axes:
        axis.set_xlabel("Hour of Day")
        axis.tick_params(axis="x", labelbottom=True)
    location = f" | {station_location}" if str(station_location).strip() else ""
    figure.suptitle(f"{title}{location} | {data_date.isoformat()}", fontsize=15)
    # ``tight_layout`` is incompatible with the inset DSD colorbar and twin
    # rain axis. Explicit spacing is deterministic and warning-free.
    figure.subplots_adjust(
        left=0.07, right=0.94, bottom=0.06, top=0.94,
        wspace=0.34, hspace=0.30,
    )
    _, suffix = platform_plot_details(platform)
    destination = _dated_plot_path(Path(plot_root), "Platform", gauge_id, data_date, suffix)
    figure.savefig(destination, dpi=100)
    plt.close(figure)
    return destination


def create_platform_fallback(
    rain_plot: str | Path,
    gauge_id: str,
    platform_type: object,
    data_date: date,
    plot_root: str | Path,
    *,
    reason: str = "Required instrument data are unavailable or invalid.",
) -> Path:
    """Create an explanatory plot when an auxiliary instrument is unusable."""
    _, suffix = platform_plot_details(platform_type)
    destination = _dated_plot_path(
        Path(plot_root), "Platform", gauge_id, data_date, suffix
    )
    platform = normalize_platform_type(platform_type)
    location = Path(rain_plot).name
    explanation = "\n".join(textwrap.wrap(str(reason).strip(), width=75))
    figure, axis = plt.subplots(figsize=(15, 8), dpi=100)
    axis.set_axis_off()
    axis.text(
        0.5, 0.66,
        f"{gauge_id} {platform} instrument plot unavailable",
        transform=axis.transAxes,
        ha="center", va="center", fontsize=20, fontweight="bold",
    )
    axis.text(
        0.5, 0.48, explanation,
        transform=axis.transAxes,
        ha="center", va="center", fontsize=14,
        bbox={"boxstyle": "round,pad=0.8", "facecolor": "#FFF3CD", "edgecolor": "#B7950B"},
    )
    axis.text(
        0.5, 0.28,
        f"Data date: {data_date.isoformat()}\n"
        f"The tipping-bucket rain plot remains available as {location}.",
        transform=axis.transAxes,
        ha="center", va="center", fontsize=12, color="#444444",
    )
    figure.savefig(destination, dpi=100, bbox_inches="tight")
    plt.close(figure)
    return destination
