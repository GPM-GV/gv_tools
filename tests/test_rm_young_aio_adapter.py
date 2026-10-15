from pathlib import Path

import pandas as pd
import pytest

from gv_tools import InstrumentMetadata, available_adapters, create_adapter
from gv_tools.adapters.rm_young_aio import RMYoungAIOAdapter, RawRMYoungAIOProduct


def metadata(**changes):
    values = dict(
        instrument_id="PIERS0042", instrument_type="weather_station", site_id="WFF",
        manufacturer="R.M. Young", model="All-in-One", timezone="UTC",
    )
    values.update(changes)
    return InstrumentMetadata(**values)


def packet(path: Path, text="20260810060013 0 004.27 103.1 27.1 66.0 1013.7\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii")
    return path


def test_discovers_only_matching_piers_wx_packets(tmp_path):
    packet(tmp_path / "PIERS0042" / "2026" / "08" / "10" / "PIERS0042_WX_20260810060005.csv")
    packet(tmp_path / "PIERS0043_WX_20260811060005.csv")
    packet(tmp_path / "PIERS0042_wind_20260812060005.csv")
    assert RMYoungAIOAdapter(metadata()).discover(tmp_path) == ["2026-08-10"]


def test_reads_normalizes_and_counts_bad_and_duplicate_rows(tmp_path):
    source = packet(
        tmp_path / "PIERS0042_WX_20260810060005.csv",
        "20260810060013 0 004.27 103.1 27.1 66.0 1013.7\r"
        "bad packet\r"
        "20260810060013 0 004.27 103.1 27.1 66.0 1013.7\r",
    )
    adapter = RMYoungAIOAdapter(metadata())
    raw = adapter.read_raw(source)["2026-08-10"]
    assert isinstance(raw, RawRMYoungAIOProduct)
    assert raw.rejected_rows == 1
    assert raw.duplicate_rows == 1
    dataset = adapter.read(source)["2026-08-10"]
    assert dataset.sizes == {"time": 1}
    assert dataset.wind_speed.item() == pytest.approx(4.27)
    assert dataset.wind_from_direction.item() == pytest.approx(103.1)
    assert dataset.air_temperature.attrs["units"] == "degree_Celsius"
    assert dataset.attrs["source_platform"] == "piers"


def test_converts_configured_source_timezone_to_utc(tmp_path):
    source = packet(tmp_path / "PIERS0042_WX_20260810060005.csv")
    dataset = RMYoungAIOAdapter(metadata(timezone="America/New_York")).read(source)["2026-08-10"]
    assert pd.Timestamp(dataset.time.values[0]) == pd.Timestamp("2026-08-10 10:00:13")


def test_reads_consolidated_daily_filename_and_comma_delimiter(tmp_path):
    source = packet(
        tmp_path / "PIERS0042_WX_20260810_daily.csv",
        "20260810060013,0 004.27 103.1 27.1 66.0 1013.7\n",
    )
    adapter = RMYoungAIOAdapter(metadata())
    assert adapter.discover(tmp_path) == ["2026-08-10"]
    dataset = adapter.read(source)["2026-08-10"]
    assert dataset.sizes["time"] == 1
    assert dataset.wind_speed.item() == pytest.approx(4.27)


def test_directory_read_returns_every_discovered_day_and_registry(tmp_path):
    packet(tmp_path / "PIERS0042_WX_20260810060005.csv")
    packet(tmp_path / "PIERS0042_WX_20260811060005.csv", "20260811060013 0 1 2 3 4 5\n")
    adapter = create_adapter("rm_young_aio", metadata())
    assert "rm_young_aio" in available_adapters()
    assert list(adapter.read(tmp_path)) == ["2026-08-10", "2026-08-11"]


def test_rejects_non_piers_identifier():
    with pytest.raises(ValueError, match="must begin with 'PIERS'"):
        RMYoungAIOAdapter(metadata(instrument_id="AIO01"))
