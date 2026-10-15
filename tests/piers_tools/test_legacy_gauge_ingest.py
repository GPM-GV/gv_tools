from pathlib import Path

import pandas as pd
import pytest
import xarray as xr

from piers_tools.gauge import ingest_gauge_range


def _packet(path: Path, day: str, rows: list[tuple[str, int]]) -> None:
    lines = [
        "Station_Name: PIERS0001_TB\n",
        "Latitude/Longitude: 38.1,-75.2\n",
        "RSSI: -80\n",
        "Battery_Voltage: 12.7\n",
        "\n",
    ]
    lines.extend(f"{day},{stamp},x,{value},tips,G\n" for stamp, value in rows)
    path.write_text("".join(lines), encoding="utf-8")


def test_ingests_multiple_packets_to_daily_netcdf(tmp_path):
    _packet(tmp_path / "PIERS0001_TB_20260721_0000.csv", "07/21/2026", [("00:00:01", 10), ("00:01:01", 11)])
    _packet(tmp_path / "PIERS0001_TB_20260721_0015.csv", "07/21/2026", [("00:15:01", 11), ("00:16:01", 13)])
    outputs = ingest_gauge_range(
        tmp_path, "PIERS0001", "2026-07-21", "2026-07-21",
        output_dir=tmp_path / "out", accumulation_per_tip=0.2,
    )
    assert len(outputs) == 1
    with xr.open_dataset(outputs[0]) as dataset:
        assert dataset.sizes["DateTime"] == 1440
        assert int(dataset["number_of_tips"].sum()) == 3
        assert float(dataset["integrated_rain_accumulation"].isel(DateTime=-1)) == pytest.approx(0.6)
        assert dataset.attrs["Gauge_ID"] == "PIERS0001"
        assert dataset.attrs["Network"] == "PIERS"
        assert dataset.attrs["Latitude"] == 38.1


def test_single_daily_file_is_filtered_by_requested_range(tmp_path):
    source = tmp_path / "PIERS0001_TB_daily.csv"
    _packet(source, "07/21/2026", [("23:58:01", 4), ("23:59:01", 5)])
    outputs = ingest_gauge_range(
        source, "PIERS0001", pd.Timestamp("2026-07-21"), "2026-07-21",
        output_dir=tmp_path / "out", accumulation_per_tip=0.254,
    )
    assert outputs[0].name == "PIERS0001_20260721_gauge_1min.nc"
