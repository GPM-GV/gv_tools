from pathlib import Path

import pandas as pd
import pytest

import gv_tools


def test_public_api_contains_readers_and_not_automatic_writers():
    assert callable(gv_tools.io.read_gauge)
    assert callable(gv_tools.io.read_radar)
    assert callable(gv_tools.graph.plot_instrument_timeseries)
    assert not hasattr(gv_tools.io, "write_product")
    assert not hasattr(gv_tools.io, "save_products")
    assert not hasattr(gv_tools.graph, "plot_timeseries")
    assert not hasattr(gv_tools, "plot_directory")


def test_plot_instrument_timeseries_accepts_relative_output_path(tmp_path, monkeypatch):
    frame = pd.DataFrame(
        {"time": pd.date_range("2026-01-01", periods=3, freq="min"), "value": [1, 2, 3]}
    )
    monkeypatch.chdir(tmp_path)
    destination = Path("output") / "Instrument-01_2026-01-01_timeseries.png"
    figure, _ = gv_tools.graph.plot_instrument_timeseries(frame, "value", destination)
    assert destination.is_file()
    figure.clear()


def test_plot_instrument_timeseries_requires_filename_extension(tmp_path):
    frame = pd.DataFrame(
        {"time": pd.date_range("2026-01-01", periods=3, freq="min"), "value": [1, 2, 3]}
    )
    with pytest.raises(ValueError, match="extension"):
        gv_tools.graph.plot_instrument_timeseries(frame, "value", tmp_path / "figure")


def test_reader_source_must_be_absolute():
    with pytest.raises(ValueError, match="fully qualified"):
        gv_tools.io.read_aio("relative/input.csv")
