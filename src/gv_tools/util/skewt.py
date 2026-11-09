"""Decode a model pressure profile and produce a high-quality Skew-T diagram."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import warnings

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
    metadata: dict = field(default_factory=dict)


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


_GRID_KEYS = [
    "uvRelativeToGrid", "gridType", "LoVInDegrees", "Latin1InDegrees", "Latin2InDegrees", "projectionCentreFlag",
]


def _variable(dataset: Any, *names: str):
    for name in names:
        if name in dataset:
            return dataset[name]
    raise ValueError(f"GRIB2 profile lacks required variable: {' or '.join(names)}")


def _optional_variable(dataset: Any, *names: str):
    for name in names:
        if name in dataset:
            return dataset[name]
    return None


def lambert_rotation_angle(longitude, lov_deg, latin1_deg, latin2_deg) -> np.ndarray:
    """Angle (radians) between grid north and true north on a Lambert conformal grid.

    ``angle = n * (longitude - LoV)`` with the cone constant
    ``n = sin(latin)`` for a tangent cone or
    ``ln(cos f1 / cos f2) / ln(tan(pi/4 + f2/2) / tan(pi/4 + f1/2))`` for a secant cone.
    """
    phi1, phi2 = np.deg2rad(float(latin1_deg)), np.deg2rad(float(latin2_deg))
    if abs(phi1 - phi2) < 1e-9:
        cone = np.sin(phi1)
    else:
        cone = np.log(np.cos(phi1) / np.cos(phi2)) / np.log(
            np.tan(np.pi / 4 + phi2 / 2) / np.tan(np.pi / 4 + phi1 / 2)
        )
    delta = (np.asarray(longitude, dtype=float) - float(lov_deg) + 180.0) % 360.0 - 180.0
    return cone * np.deg2rad(delta)


def grid_to_earth_winds(u_grid, v_grid, angle_rad):
    """Rotate grid-relative wind components to earth-relative (east, north).

    This is the NCEP RAP/HRRR convention (``un = cos(a) u + sin(a) v``,
    ``vn = -sin(a) u + cos(a) v`` with ``a`` from :func:`lambert_rotation_angle`).
    """
    cosine, sine = np.cos(angle_rad), np.sin(angle_rad)
    u_grid = np.asarray(u_grid, dtype=float)
    v_grid = np.asarray(v_grid, dtype=float)
    return cosine * u_grid + sine * v_grid, -sine * u_grid + cosine * v_grid


def _grid_relative_angle(u_variable, longitude) -> float | None:
    """Return the rotation angle when the GRIB winds are grid-relative, else None.

    Lambert conformal (RAP, HRRR, NAM) and polar stereographic (e.g. HRRR
    Alaska) grids are supported. Grid-relative winds on any other projection
    are left as stored, with a warning.
    """
    attrs = getattr(u_variable, "attrs", {})
    grid_type = str(attrs.get("GRIB_gridType", "")).lower()
    flag = attrs.get("GRIB_uvRelativeToGrid")
    if grid_type in ("regular_ll", "reduced_ll", "regular_gg", "reduced_gg", ""):
        return None
    if flag is not None and int(flag) == 0:
        return None
    if flag is None:
        warnings.warn(
            f"{grid_type} winds have no uvRelativeToGrid flag; assuming NCEP grid-relative winds",
            UserWarning, stacklevel=3,
        )
    if grid_type == "lambert":
        keys = ("GRIB_LoVInDegrees", "GRIB_Latin1InDegrees", "GRIB_Latin2InDegrees")
        if all(key in attrs for key in keys):
            return float(lambert_rotation_angle(longitude, *(float(attrs[key]) for key in keys)))
    elif grid_type == "polar_stereographic" and "GRIB_LoVInDegrees" in attrs:
        south = int(attrs.get("GRIB_projectionCentreFlag", 0) or 0) & 128
        delta = (float(longitude) - float(attrs["GRIB_LoVInDegrees"]) + 180.0) % 360.0 - 180.0
        return float(np.deg2rad(delta) * (-1.0 if south else 1.0))
    warnings.warn(
        f"grid-relative winds on a {grid_type!r} grid are not rotated to earth-relative",
        UserWarning, stacklevel=3,
    )
    return None


def _nearest_point(dataset, latitude, longitude):
    if latitude is None or longitude is None:
        return dataset
    if "latitude" not in dataset.coords or "longitude" not in dataset.coords:
        return dataset
    grid_lat = np.asarray(dataset.latitude, dtype=float)
    grid_lon = np.asarray(dataset.longitude, dtype=float)
    if grid_lat.ndim == 1 and grid_lon.ndim == 1 and dataset.latitude.dims != dataset.longitude.dims:
        grid_lat, grid_lon = np.meshgrid(grid_lat, grid_lon, indexing="ij")
        dimensions = (dataset.latitude.dims[0], dataset.longitude.dims[0])
    else:
        dimensions = dataset.latitude.dims
    requested_lon = float(longitude)
    if np.nanmin(grid_lon) >= 0 and requested_lon < 0:
        requested_lon %= 360.0
    lon_delta = (grid_lon - requested_lon + 180.0) % 360.0 - 180.0
    distance = (grid_lat - float(latitude)) ** 2 + (
        lon_delta * np.cos(np.deg2rad(float(latitude)))
    ) ** 2
    nearest = np.unravel_index(np.nanargmin(distance), distance.shape)
    return dataset.isel(dict(zip(dimensions, nearest)))


def _surface_state(source: Path, latitude, longitude) -> dict:
    """Surface pressure, 2 m temperature/humidity and 10 m wind when the file has them."""
    try:
        import cfgrib
    except ImportError:  # pragma: no cover - cfgrib is part of the sounding extra
        return {}
    state: dict = {}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            datasets = cfgrib.open_datasets(
                str(source), backend_kwargs={"indexpath": "", "read_keys": _GRID_KEYS}
            )
    except Exception:  # cfgrib raises many types for odd subsets
        return {}
    for dataset in datasets:
        try:
            level_type = next(
                (str(dataset[name].attrs.get("GRIB_typeOfLevel", "")) for name in dataset.data_vars), ""
            )
            point = _nearest_point(dataset, latitude, longitude).squeeze(drop=True)
            if level_type == "surface":
                for key, names in (("pressure_pa", ("sp", "pres")), ("height_m", ("orog", "gh", "hgt"))):
                    variable = _optional_variable(point, *names)
                    if variable is not None and variable.ndim == 0:
                        state[key] = float(variable)
            elif level_type == "heightAboveGround":
                for key, names in (
                    ("temperature_k", ("t2m",)), ("relative_humidity", ("r2",)),
                    ("dewpoint_k", ("d2m",)), ("specific_humidity", ("sh2",)),
                    ("u_wind", ("u10",)), ("v_wind", ("v10",)),
                ):
                    variable = _optional_variable(point, *names)
                    if variable is not None and variable.ndim == 0:
                        state[key] = float(variable)
                        if key == "u_wind":
                            longitude_value = float(np.asarray(point.coords.get("longitude", longitude)))
                            if longitude_value > 180:
                                longitude_value -= 360
                            state["wind_angle"] = _grid_relative_angle(variable, longitude_value)
        finally:
            dataset.close()
    return state


def load_model_profile(
    path: str | Path,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    below_ground: str = "drop",
) -> SoundingProfile:
    """Read the nearest isobaric profile from a downloaded GRIB2 subset.

    The grid point nearest ``latitude``/``longitude`` is selected. Dew point
    comes from specific humidity when the file has it (unambiguous), else
    from relative humidity. Changes in 0.65.0:

    * Grid-relative winds (Lambert grids: RAP, HRRR, NAM) are rotated to
      earth-relative east/north components before plotting.
    * When the file holds surface pressure, isobaric levels at or below the
      ground (``p >= p_sfc``; model extrapolations) are dropped with
      ``below_ground="drop"`` (default) and, when 2 m temperature/humidity
      and 10 m wind are present, the surface is added as the first level so
      the parcel starts at the ground. ``below_ground="keep"`` keeps them.
    """

    xr, dewpoint_from_relative_humidity, units = _optional_imports()
    if below_ground not in {"drop", "keep"}:
        raise ValueError("below_ground must be 'drop' or 'keep'")
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"sounding file does not exist: {source}")
    dataset = xr.open_dataset(
        source,
        engine="cfgrib",
        backend_kwargs={
            "filter_by_keys": {"typeOfLevel": "isobaricInhPa"},
            "indexpath": "",
            "read_keys": _GRID_KEYS,
        },
    )
    try:
        dataset = _nearest_point(dataset, latitude, longitude)
        dataset = dataset.squeeze(drop=True)

        pressure_coord = next(
            (name for name in ("isobaricInhPa", "pressure") if name in dataset.coords),
            None,
        )
        if pressure_coord is None:
            raise ValueError("GRIB2 profile has no isobaric pressure coordinate")
        pressure = np.asarray(dataset[pressure_coord], dtype=float)
        temperature_k = np.asarray(_variable(dataset, "t", "temperature"), dtype=float)
        u_variable = _variable(dataset, "u", "u_component_of_wind")
        u_wind = np.asarray(u_variable, dtype=float)
        v_wind = np.asarray(_variable(dataset, "v", "v_component_of_wind"), dtype=float)
        height = np.asarray(_variable(dataset, "gh", "z", "geopotential_height"), dtype=float)
        temperature = (temperature_k * units.kelvin).to("degC")
        specific = _optional_variable(dataset, "q", "specific_humidity")
        if specific is not None and np.isfinite(np.asarray(specific, dtype=float)).sum() >= 3:
            from metpy.calc import dewpoint, mixing_ratio_from_specific_humidity, vapor_pressure

            q = np.clip(np.asarray(specific, dtype=float), 1e-8, None) * units("kg/kg")
            dewpoint_c = dewpoint(
                vapor_pressure(pressure * units.hPa, mixing_ratio_from_specific_humidity(q))
            ).to("degC")
            humidity_source = "specific_humidity"
        else:
            relative_humidity = np.asarray(_variable(dataset, "r", "relative_humidity"), dtype=float)
            if np.nanmax(relative_humidity) > 1.5:
                relative_humidity = relative_humidity / 100.0
            relative_humidity = np.clip(relative_humidity, 1e-4, 1.0)
            dewpoint_c = dewpoint_from_relative_humidity(
                temperature, relative_humidity * units.dimensionless
            ).to("degC")
            humidity_source = "relative_humidity"
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
        angle = _grid_relative_angle(u_variable, actual_lon)
        if angle is not None:
            u_wind, v_wind = grid_to_earth_winds(u_wind, v_wind, angle)
        prefix = source.name.split("_", 1)[0]
        model_name = prefix.upper() if prefix.lower() in {"rap", "hrrr", "gfs", "nam"} else "Model"
    finally:
        dataset.close()

    arrays = [pressure, temperature.magnitude, dewpoint_c.magnitude, u_wind, v_wind, height]
    good = np.logical_and.reduce([np.isfinite(values) for values in arrays])
    surface = _surface_state(source, latitude, longitude) if below_ground == "drop" else {}
    surface_pressure = surface.get("pressure_pa", np.nan) / 100.0
    if below_ground == "drop" and np.isfinite(surface_pressure):
        good &= pressure < surface_pressure
    if good.sum() < 3:
        raise ValueError("fewer than three complete pressure levels were found")
    order = np.argsort(pressure[good])[::-1]
    selected = [np.asarray(values)[good][order] for values in arrays]
    base = "lowest isobaric level"
    surface_row = _surface_row(surface, units)
    if surface_row is not None:
        if surface_row[0] > selected[0][0]:
            selected = [np.r_[value, column] for value, column in zip(surface_row, selected)]
            base = "surface (2 m / 10 m)"
    elif np.isfinite(surface_pressure):
        base = "lowest above-ground isobaric level"
    return SoundingProfile(
        *selected,
        latitude=actual_lat,
        longitude=actual_lon,
        model=model_name,
        valid_time=valid_text,
        metadata={
            "humidity_source": humidity_source,
            "winds": (
                "earth-relative (rotated from grid-relative)" if angle is not None
                else "as stored in the GRIB file"
            ),
            "parcel_base": base,
            "surface_pressure_hpa": float(surface_pressure) if np.isfinite(surface_pressure) else None,
        },
    )


def _surface_row(surface: dict, units):
    """Return (p, T, Td, u, v, z) for the surface, or None if a field is missing."""
    needed = ("pressure_pa", "temperature_k", "u_wind", "v_wind", "height_m")
    if any(key not in surface for key in needed):
        return None
    from metpy.calc import dewpoint, dewpoint_from_relative_humidity, mixing_ratio_from_specific_humidity, vapor_pressure

    pressure = surface["pressure_pa"] / 100.0
    temperature = (surface["temperature_k"] * units.kelvin).to("degC")
    if "dewpoint_k" in surface:
        dew = (surface["dewpoint_k"] * units.kelvin).to("degC")
    elif "specific_humidity" in surface:
        q = max(surface["specific_humidity"], 1e-8) * units("kg/kg")
        dew = dewpoint(vapor_pressure(pressure * units.hPa, mixing_ratio_from_specific_humidity(q))).to("degC")
    elif "relative_humidity" in surface:
        rh = surface["relative_humidity"]
        rh = rh / 100.0 if rh > 1.5 else rh
        dew = dewpoint_from_relative_humidity(temperature, min(max(rh, 1e-4), 1.0) * units.dimensionless).to("degC")
    else:
        return None
    u_wind, v_wind = surface["u_wind"], surface["v_wind"]
    if surface.get("wind_angle") is not None:
        u_wind, v_wind = grid_to_earth_winds(u_wind, v_wind, surface["wind_angle"])
    return (
        float(pressure), float(temperature.magnitude), float(dew.magnitude),
        float(u_wind), float(v_wind), float(surface["height_m"]),
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

    if output is None:
        raise ValueError("a full output filename is required")
    destination = Path(output).expanduser()
    if not destination.name or not destination.suffix:
        raise ValueError("output must include an image filename with an extension")

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
        base = profile.metadata.get("parcel_base", "lowest level")
        skew.plot(p, parcel_curve, color="#111827", linewidth=1.8, label=f"Parcel from {base}")
        skew.shade_cape(p, t, parcel_curve, alpha=0.22)
        skew.shade_cin(p, t, parcel_curve, td, alpha=0.18)
        # MetPy >= 1.6 applies the virtual-temperature correction inside cape_cin.
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
            f"CAPE {diagnostics['cape_j_kg']:.0f} J kg⁻¹\nCIN {diagnostics['cin_j_kg']:.0f} J kg⁻¹\n"
            "(virtual-temperature corrected)",
            transform=skew.ax.transAxes,
            fontsize=9.5,
            bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "alpha": 0.85},
        )
    fig.gv_tools_sounding_diagnostics = diagnostics
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=dpi, bbox_inches="tight", facecolor="white")
    return fig
