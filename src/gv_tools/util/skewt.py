"""Decode a model pressure profile and produce a high-quality Skew-T diagram."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class SoundingProfile:
    """One vertical atmospheric profile in plotting-ready physical units."""

    pressure_hpa: np.ndarray
    temperature_c: np.ndarray
    dewpoint_c: np.ndarray
    u_wind_ms: np.ndarray
    v_wind_ms: np.ndarray
    height_m: np.ndarray
    latitude: float
    longitude: float
    model: str = "model"
    valid_time: str | None = None


def _optional_imports():
    try:
        import xarray as xr
        from metpy.calc import dewpoint_from_relative_humidity
        from metpy.units import units
    except ImportError as exc:
        raise ImportError(
            "Skew-T support requires the 'sounding' extra; install "
            "gv_tools[sounding]"
        ) from exc
    return xr, dewpoint_from_relative_humidity, units


def _variable(dataset: Any, *names: str):
    for name in names:
        if name in dataset:
            return dataset[name]
    raise ValueError(f"GRIB2 profile lacks required variable: {' or '.join(names)}")


def load_model_profile(
    path: str | Path,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> SoundingProfile:
    """Read the nearest isobaric profile from a downloaded GRIB2 subset.

    The function uses cfgrib to select isobaric levels, chooses the grid point
    nearest ``latitude``/``longitude`` when supplied, and derives dew point
    from model temperature and relative humidity.
    """

    xr, dewpoint_from_relative_humidity, units = _optional_imports()
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"sounding file does not exist: {source}")
    dataset = xr.open_dataset(
        source,
        engine="cfgrib",
        backend_kwargs={
            "filter_by_keys": {"typeOfLevel": "isobaricInhPa"},
            "indexpath": "",
        },
    )
    try:
        if latitude is not None and longitude is not None:
            if "latitude" in dataset.coords and "longitude" in dataset.coords:
                grid_lat = np.asarray(dataset.latitude, dtype=float)
                grid_lon = np.asarray(dataset.longitude, dtype=float)
                requested_lon = float(longitude)
                if np.nanmin(grid_lon) >= 0 and requested_lon < 0:
                    requested_lon %= 360.0
                lon_delta = (grid_lon - requested_lon + 180.0) % 360.0 - 180.0
                distance = (grid_lat - float(latitude)) ** 2 + (
                    lon_delta * np.cos(np.deg2rad(float(latitude)))
                ) ** 2
                nearest = np.unravel_index(np.nanargmin(distance), distance.shape)
                dimensions = dataset.latitude.dims
                dataset = dataset.isel(dict(zip(dimensions, nearest)))
        dataset = dataset.squeeze(drop=True)

        pressure_coord = next(
            (name for name in ("isobaricInhPa", "pressure") if name in dataset.coords),
            None,
        )
        if pressure_coord is None:
            raise ValueError("GRIB2 profile has no isobaric pressure coordinate")
        pressure = np.asarray(dataset[pressure_coord], dtype=float)
        temperature_k = np.asarray(_variable(dataset, "t", "temperature"), dtype=float)
        relative_humidity = np.asarray(_variable(dataset, "r", "relative_humidity"), dtype=float)
        u_wind = np.asarray(_variable(dataset, "u", "u_component_of_wind"), dtype=float)
        v_wind = np.asarray(_variable(dataset, "v", "v_component_of_wind"), dtype=float)
        height = np.asarray(_variable(dataset, "gh", "z", "geopotential_height"), dtype=float)
        if np.nanmax(relative_humidity) > 1.5:
            relative_humidity = relative_humidity / 100.0
        relative_humidity = np.clip(relative_humidity, 0.0, 1.0)
        temperature = (temperature_k * units.kelvin).to("degC")
        dewpoint = dewpoint_from_relative_humidity(
            temperature, relative_humidity * units.dimensionless
        ).to("degC")
        valid_time = dataset.coords.get("valid_time", dataset.coords.get("time"))
        valid_text = None
        if valid_time is not None:
            valid_text = np.datetime_as_string(
                np.asarray(valid_time).astype("datetime64[s]"), unit="s"
            )
        actual_lat = float(np.asarray(dataset.coords.get("latitude", latitude)).mean())
        actual_lon = float(np.asarray(dataset.coords.get("longitude", longitude)).mean())
        if actual_lon > 180:
            actual_lon -= 360
        prefix = source.name.split("_", 1)[0]
        model_name = prefix.upper() if prefix.lower() in {"rap", "hrrr", "gfs", "nam"} else "Model"
    finally:
        dataset.close()

    arrays = [pressure, temperature.magnitude, dewpoint.magnitude, u_wind, v_wind, height]
    good = np.logical_and.reduce([np.isfinite(values) for values in arrays])
    if good.sum() < 3:
        raise ValueError("fewer than three complete pressure levels were found")
    order = np.argsort(pressure[good])[::-1]
    selected = [np.asarray(values)[good][order] for values in arrays]
    return SoundingProfile(
        *selected,
        latitude=actual_lat,
        longitude=actual_lon,
        model=model_name,
        valid_time=valid_text,
    )


def plot_skewt(
    profile: SoundingProfile,
    output: str | Path | None = None,
    *,
    title: str | None = None,
    parcel: bool = True,
    hodograph: bool = True,
    dpi: int = 200,
):
    """Plot a polished Skew-T/log-P diagram and optionally save it.

    Temperature and dew point, pressure-thinned wind barbs, reference
    adiabats/mixing-ratio lines, parcel ascent, CAPE/CIN shading, and an inset
    hodograph are included. The returned Matplotlib figure remains editable.
    """

    try:
        import matplotlib.pyplot as plt
        from metpy.calc import cape_cin, parcel_profile, wind_speed
        from metpy.plots import Hodograph, SkewT
        from metpy.units import units
    except ImportError as exc:
        raise ImportError(
            "Skew-T support requires the 'sounding' extra; install gv_tools[sounding]"
        ) from exc

    p = profile.pressure_hpa * units.hPa
    t = profile.temperature_c * units.degC
    td = profile.dewpoint_c * units.degC
    u = profile.u_wind_ms * units("m/s")
    v = profile.v_wind_ms * units("m/s")
    fig = plt.figure(figsize=(12, 10), constrained_layout=False)
    skew = SkewT(fig, rotation=45, rect=(0.07, 0.08, 0.62, 0.82))
    skew.plot(p, t, color="#d62728", linewidth=2.6, label="Temperature")
    skew.plot(p, td, color="#16823b", linewidth=2.6, label="Dew point")
    barb_indices = np.unique(np.linspace(0, len(p) - 1, min(28, len(p))).astype(int))
    skew.plot_barbs(p[barb_indices], u[barb_indices].to("knots"), v[barb_indices].to("knots"), xloc=1.04)
    skew.plot_dry_adiabats(alpha=0.25, linewidth=0.7)
    skew.plot_moist_adiabats(alpha=0.25, linewidth=0.7)
    skew.plot_mixing_lines(alpha=0.25, linewidth=0.7)
    skew.ax.axvline(0, color="#3b82c4", linestyle="--", linewidth=1.0, alpha=0.7)
    skew.ax.set_ylim(float(np.nanmax(profile.pressure_hpa)), 100)
    skew.ax.set_xlim(-45, 45)
    skew.ax.set_xlabel("Temperature (°C)", fontsize=11)
    skew.ax.set_ylabel("Pressure (hPa)", fontsize=11)
    skew.ax.grid(True, which="major", color="0.88", linewidth=0.6)

    diagnostics = {}
    if parcel:
        parcel_curve = parcel_profile(p, t[0], td[0]).to("degC")
        skew.plot(p, parcel_curve, color="#111827", linewidth=1.8, label="Surface parcel")
        skew.shade_cape(p, t, parcel_curve, alpha=0.22)
        skew.shade_cin(p, t, parcel_curve, td, alpha=0.18)
        cape, cin = cape_cin(p, t, td, parcel_curve)
        diagnostics = {"cape_j_kg": float(cape.m), "cin_j_kg": float(cin.m)}

    if hodograph:
        speed = wind_speed(u, v).to("knots")
        component_range = max(40.0, float(np.ceil(np.nanmax(speed.m) / 20.0) * 20.0))
        hodo_ax = fig.add_axes((0.74, 0.62, 0.22, 0.26))
        hodo = Hodograph(hodo_ax, component_range=component_range)
        hodo.add_grid(increment=20, color="0.75", linewidth=0.7)
        hodo.plot_colormapped(u.to("knots"), v.to("knots"), speed, cmap="viridis")
        hodo_ax.set_title("Hodograph (kt)", fontsize=10)

    default_title = f"{profile.model} model sounding"
    subtitle = f"{profile.latitude:.2f}°, {profile.longitude:.2f}°"
    if profile.valid_time:
        subtitle += f"   Valid {profile.valid_time} UTC"
    fig.suptitle(title or default_title, x=0.38, y=0.975, fontsize=16, fontweight="bold")
    fig.text(0.38, 0.942, subtitle, ha="center", fontsize=10.5, color="0.25")
    skew.ax.legend(loc="upper left", frameon=True, framealpha=0.9)
    if diagnostics:
        skew.ax.text(
            0.015,
            0.015,
            f"CAPE {diagnostics['cape_j_kg']:.0f} J kg⁻¹\nCIN {diagnostics['cin_j_kg']:.0f} J kg⁻¹",
            transform=skew.ax.transAxes,
            fontsize=9.5,
            bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "alpha": 0.85},
        )
    fig.gv_tools_sounding_diagnostics = diagnostics
    if output is not None:
        destination = Path(output).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(destination, dpi=dpi, bbox_inches="tight", facecolor="white")
    return fig
