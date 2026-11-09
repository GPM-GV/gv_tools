"""Smoke and behaviour tests for the 0.65.0 quicklook changes."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import gv_tools

pytest.importorskip("matplotlib")


def test_wind_rose_reports_calms_instead_of_northerly_wind(tmp_path):
    times = pd.date_range("2026-08-10", periods=10, freq="min")
    dataset = xr.Dataset(
        {
            "wind_speed": ("time", [0.0] * 4 + [3.0] * 6),
            "wind_from_direction": ("time", [0.0] * 4 + [180.0] * 6),
        },
        coords={"time": times},
        attrs={"site_id": "WFF", "instrument_id": "PIERS0042"},
    )
    figure, axis, frequencies = gv_tools.graph.plot_aio_wind_rose(dataset, tmp_path / "rose.png")
    assert axis.gv_tools_calm_percent == pytest.approx(40.0)
    north = 0
    south = frequencies.shape[0] // 2
    assert frequencies[north].sum() == 0
    assert frequencies[south].sum() == pytest.approx(60.0)
    assert frequencies.sum() + axis.gv_tools_calm_percent == pytest.approx(100.0)


def test_parsivel_quicklook_uses_log_colours_and_shades_outages(tmp_path):
    from test_parsivel_decoder import RAIN, telegram

    base = datetime(2026, 8, 10, 6, 0, 5)
    lines = [telegram(base + timedelta(seconds=10 * i), RAIN) for i in range(6 * 30)]
    lines += [telegram(base + timedelta(minutes=60, seconds=10 * i), RAIN) for i in range(6 * 30)]
    source = tmp_path / "PIERS0042_Parsivel_20260810_daily.csv"
    source.write_text("\n".join(lines) + "\n")
    dataset = gv_tools.io.read_parsivel([source])
    assert "drop_diameter_width" in dataset.coords
    figure = gv_tools.graph.plot_parsivel_quicklook(dataset, savefig=tmp_path / "parsivel.png")
    mesh = next(item for item in figure.axes[0].collections if hasattr(item, "norm") and item.get_array() is not None)
    assert type(mesh.norm).__name__ == "LogNorm"
    assert mesh.cmap.get_bad()[3] == 0  # missing cells are transparent, so outage shading shows
    assert (tmp_path / "parsivel.png").stat().st_size > 10_000
    assert np.isnan(dataset.precipitation_rate.sel(time="2026-08-10T06:45").item())
