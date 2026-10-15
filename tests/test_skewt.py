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
