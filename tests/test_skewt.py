import numpy as np
import pytest

from gv_tools.util import SoundingProfile, plot_skewt


def test_plot_skewt_writes_high_resolution_figure(tmp_path):
    pytest.importorskip("metpy")
    pressure = np.array([1000, 925, 850, 700, 600, 500, 400, 300, 250, 200], dtype=float)
    temperature = np.array([24, 19, 14, 4, -4, -14, -27, -43, -51, -58], dtype=float)
    profile = SoundingProfile(
        pressure,
        temperature,
        temperature - np.array([3, 4, 5, 7, 9, 11, 13, 15, 18, 20]),
        np.linspace(2, 35, pressure.size),
        np.linspace(1, 20, pressure.size),
        np.linspace(100, 12000, pressure.size),
        37.94,
        -75.47,
        "RAP",
        "2026-10-01T15:00:00",
    )
    destination = tmp_path / "skewt.png"

    figure = plot_skewt(profile, destination, hodograph=True)

    assert destination.read_bytes().startswith(b"\x89PNG")
    assert destination.stat().st_size > 50_000
    assert set(figure.gv_tools_sounding_diagnostics) == {"cape_j_kg", "cin_j_kg"}


def test_lambert_grid_relative_winds_are_rotated_to_earth_relative():
    from gv_tools.util import skewt

    # HRRR: LoV 262.5 E, tangent at 38.5 N. At Wallops (75.47 W) grid north
    # is turned ~13.7 degrees from true north.
    angle = skewt.lambert_rotation_angle(-75.47, 262.5, 38.5, 38.5)
    assert np.rad2deg(angle) == pytest.approx(np.sin(np.deg2rad(38.5)) * 22.03, rel=1e-6)
    u, v = skewt.grid_to_earth_winds(0.0, 10.0, angle)
    assert np.hypot(u, v) == pytest.approx(10.0)
    assert u == pytest.approx(10.0 * np.sin(angle))
    # no rotation on the central meridian
    assert skewt.lambert_rotation_angle(-97.5, 262.5, 38.5, 38.5) == pytest.approx(0.0)


def _grib_profile(path):
    eccodes = pytest.importorskip("eccodes")
    pytest.importorskip("cfgrib")

    def message(handle_file, category, number, level_type, level, value):
        handle = eccodes.codes_grib_new_from_samples("GRIB2")
        eccodes.codes_set(handle, "gridDefinitionTemplateNumber", 30)
        for key, item in {
            "shapeOfTheEarth": 6, "Nx": 3, "Ny": 3,
            "latitudeOfFirstGridPointInDegrees": 37.9, "longitudeOfFirstGridPointInDegrees": 284.5,
            "LaDInDegrees": 38.5, "LoVInDegrees": 262.5, "Latin1InDegrees": 38.5,
            "Latin2InDegrees": 38.5, "DxInMetres": 3000, "DyInMetres": 3000, "uvRelativeToGrid": 1,
        }.items():
            eccodes.codes_set(handle, key, item)
        eccodes.codes_set(handle, "parameterCategory", category)
        eccodes.codes_set(handle, "parameterNumber", number)
        eccodes.codes_set(handle, "typeOfFirstFixedSurface", level_type)
        if level_type in (100, 103):
            eccodes.codes_set(handle, "scaleFactorOfFirstFixedSurface", 0)
            eccodes.codes_set(handle, "scaledValueOfFirstFixedSurface", int(level))
        eccodes.codes_set(handle, "dataDate", 20261001)
        eccodes.codes_set(handle, "dataTime", 1500)
        eccodes.codes_set_values(handle, np.full(9, float(value)))
        eccodes.codes_write(handle, handle_file)
        eccodes.codes_release(handle)

    levels = [1000, 975, 950, 925, 900, 850, 700, 500, 300, 200]
    temperature = dict(zip(levels, [295, 293.5, 292, 290.5, 289, 286, 277, 262, 236, 217]))
    with open(path, "wb") as handle_file:
        for level in levels:
            message(handle_file, 3, 5, 100, level * 100, 44330 * (1 - (level / 1013.25) ** 0.1903))
            message(handle_file, 0, 0, 100, level * 100, temperature[level])
            message(handle_file, 1, 1, 100, level * 100, 70.0)
            message(handle_file, 2, 2, 100, level * 100, 0.0)
            message(handle_file, 2, 3, 100, level * 100, 10.0)
        message(handle_file, 3, 0, 1, 0, 97000.0)   # surface pressure: 1000 and 975 hPa are underground
        message(handle_file, 3, 5, 1, 0, 300.0)
        message(handle_file, 0, 0, 103, 2, 294.0)
        message(handle_file, 1, 1, 103, 2, 60.0)
        message(handle_file, 2, 2, 103, 10, 0.0)
        message(handle_file, 2, 3, 103, 10, 5.0)


def test_model_profile_drops_underground_levels_and_rotates_winds(tmp_path):
    pytest.importorskip("metpy")
    from gv_tools.util import load_model_profile, skewt

    source = tmp_path / "hrrr_20261001_15z_f000.grib2"
    _grib_profile(source)
    profile = load_model_profile(source, latitude=37.95, longitude=-75.45)
    assert profile.pressure_hpa[0] == pytest.approx(970.0)  # surface first
    assert (profile.pressure_hpa[1:] < 970.0).all()
    assert 1000.0 not in profile.pressure_hpa and 975.0 not in profile.pressure_hpa
    angle = skewt.lambert_rotation_angle(profile.longitude, 262.5, 38.5, 38.5)
    assert profile.u_wind_ms[1] == pytest.approx(10.0 * np.sin(angle), rel=1e-3)
    assert profile.metadata["parcel_base"] == "surface (2 m / 10 m)"
    assert profile.metadata["winds"].startswith("earth-relative")
