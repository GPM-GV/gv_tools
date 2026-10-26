from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from gv_tools import InstrumentMetadata
from gv_tools.adapters import parsivel as module
from gv_tools.adapters.parsivel import ParsivelAdapter


def frames():
    time = pd.date_range("2026-07-21", periods=2, freq="min")
    parameters = pd.DataFrame(
        {
            "Total Drops": [10, 20],
            "Concentration": [100.0, 200.0],
            "LWC": [0.1, 0.2],
            "Z": [100, 200],
            "dBZ": [20, 23],
            "Rain": [1.0, 2.0],
            "Dm": [1.1, 1.2],
            "Dmax": [2.0, 2.5],
            "Sigma_M": [0.2, 0.3],
        },
        index=time,
    )
    psd = pd.DataFrame([[1, 2], [3, 4]], index=time, columns=[0.1, 0.2])
    moments = pd.DataFrame(np.arange(16).reshape(2, 8), index=time, columns=[f"M{i}" for i in range(8)])
    return parameters, psd, moments


def metadata():
    return InstrumentMetadata("apu01", "disdrometer", "WFF", model="Parsivel2")


def test_normalize_combines_all_three_legacy_products(monkeypatch):
    monkeypatch.setattr(module, "_backend", lambda: SimpleNamespace(__version__="1.0.0"))
    dataset = ParsivelAdapter(metadata()).normalize(*frames(), source_path="input.zip")
    assert dataset.sizes == {"time": 2, "drop_diameter": 2, "moment_order": 8}
    assert dataset.precipitation_rate.attrs["units"] == "mm h-1"
    assert dataset.drop_size_distribution.dims == ("time", "drop_diameter")
    assert dataset.drop_size_moment.dims == ("time", "moment_order")
    assert dataset.attrs["site_id"] == "WFF"
    assert dataset.attrs["time_reference"] == "UTC"


def test_read_delegates_to_existing_processor(monkeypatch):
    fake = SimpleNamespace(
        __version__="1.0.0",
        run=lambda *args, **kwargs: {"2026-07-21": frames()},
        discover_input_dates=lambda path: [pd.Timestamp("2026-07-21")],
    )
    monkeypatch.setattr(module, "_backend", lambda: fake)
    adapter = ParsivelAdapter(metadata())
    assert adapter.discover("input") == ["2026-07-21"]
    products = adapter.read("input")
    assert list(products) == ["2026-07-21"]
    assert products["2026-07-21"].attrs["instrument_id"] == "apu01"
    assert products["2026-07-21"].attrs["source_platform"] == "apu"


def test_read_raw_exposes_typed_processor_tables(monkeypatch):
    fake = SimpleNamespace(
        run=lambda *args, **kwargs: {"2026-07-21": frames()},
    )
    monkeypatch.setattr(module, "_backend", lambda: fake)
    raw = ParsivelAdapter(metadata()).read_raw("input")
    assert isinstance(raw["2026-07-21"], module.RawParsivelProduct)
    assert raw["2026-07-21"].parameters.equals(frames()[0])


def test_discover_filters_other_instruments(tmp_path, monkeypatch):
    own = tmp_path / "apu01_20260721.zip"
    other = tmp_path / "apu02_20260722.zip"
    own.touch()
    other.touch()
    fake = SimpleNamespace(
        discover_input_dates=lambda path: [
            pd.Timestamp(str(path).split("_")[-1].split(".")[0])
        ]
    )
    monkeypatch.setattr(module, "_backend", lambda: fake)
    assert ParsivelAdapter(metadata()).discover(tmp_path) == ["2026-07-21"]


def test_bundled_backend_discovers_apu_hour_without_separator(tmp_path):
    source = tmp_path / "apu01_2024030615.zip"
    source.touch()

    assert module._backend().discover_input_dates(source) == [pd.Timestamp("2024-03-06")]


def test_piers_platform_is_inferred_and_recorded(monkeypatch):
    monkeypatch.setattr(module, "_backend", lambda: SimpleNamespace(__version__="1.0.0"))
    piers_metadata = InstrumentMetadata(
        "PIERS0042", "disdrometer", "WFF", model="Parsivel2"
    )
    dataset = ParsivelAdapter(piers_metadata).normalize(*frames())
    assert dataset.attrs["source_platform"] == "piers"


def test_explicit_platform_rejects_mismatched_instrument_id():
    with pytest.raises(ValueError, match="identifies a PIERS platform"):
        ParsivelAdapter(
            InstrumentMetadata("PIERS0042", "disdrometer", "WFF"),
            source_platform="apu",
        )


def test_platform_enum_is_accepted():
    adapter = ParsivelAdapter(
        metadata(), source_platform=module.ParsivelSourcePlatform.APU
    )
    assert adapter.source_platform == "apu"


def test_timezone_aware_input_is_converted_to_naive_utc(monkeypatch):
    monkeypatch.setattr(module, "_backend", lambda: SimpleNamespace(__version__="1.0.0"))
    parameters, psd, moments = frames()
    local_time = parameters.index.tz_localize("America/New_York")
    parameters.index = psd.index = moments.index = local_time
    dataset = ParsivelAdapter(metadata()).normalize(parameters, psd, moments)
    assert str(dataset.time.dtype).startswith("datetime64")
    assert pd.Timestamp(dataset.time.values[0]) == pd.Timestamp("2026-07-21 04:00:00")
