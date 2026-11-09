from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

import gv_tools


PACKET_1 = "20260810060013 0 004.27 103.1 27.1 66.0 1013.7\n"
PACKET_2 = "20260810060113 0 005.27 104.1 28.1 67.0 1013.8\n"
METONE_HEADER = "01+AIntM  02+.Year  03+..Day  04+.HrMn  05+.WSpd  06+.WDir  07+DirSD  08+.Temp  09+Humid  10+.Press  15+User2\n"
METONE_ROW_1 = "01+0001.  02+2025.  03+0001.  04+0000.  05+001.4  06+0070.  07+023.1  08+005.6  09+071.0  10+0993.2  15+23.71\n"
METONE_ROW_2 = "01+0001.  02+2025.  03+0032.  04+0000.  05+002.4  06+0080.  07+024.1  08+006.6  09+072.0  10+0994.2  15+24.71\n"


def test_aio_requires_file_list_and_merges_files(tmp_path):
    names = ["PIERS0042_WX_20260810060005.csv", "PIERS0042_WX_20260810060105.csv"]
    (tmp_path / names[0]).write_text(PACKET_1, encoding="ascii")
    (tmp_path / names[1]).write_text(PACKET_2, encoding="ascii")

    files = [tmp_path / name for name in names]
    assert gv_tools.io.discover_aio(files) == ["2026-08-10"]
    raw = gv_tools.io.read_aio_raw(files)
    dataset = gv_tools.io.read_aio(files, XARRAY=True)

    assert raw.observations.wind_speed.tolist() == [4.27, 5.27]
    assert dataset.sizes["time"] == 2
    assert dataset.attrs["instrument_id"] == "PIERS0042"
    assert dataset.attrs["source_files"] == ", ".join(names)

    frame = gv_tools.io.read_aio(files)
    assert isinstance(frame, pd.DataFrame)
    assert frame.wind_speed.tolist() == [4.27, 5.27]
    assert frame.attrs["instrument_id"] == "PIERS0042"


def test_reader_accepts_directory_and_rejects_empty_sources(tmp_path):
    with pytest.raises(FileNotFoundError, match="contain no files"):
        gv_tools.io.read_aio(tmp_path)
    with pytest.raises(ValueError, match="at least one"):
        gv_tools.io.read_aio([])


def test_piers_day_directory_reads_daily_and_packets_once_and_ignores_other_instruments(tmp_path):
    daily = tmp_path / "PIERS0042_WX_20260810_daily.csv"
    daily.write_text(
        "20260810060013,0 004.27 103.1 27.1 66.0 1013.7\n", encoding="ascii"
    )
    # A packet that repeats the daily record (with a different value) and one
    # the daily file lacks. 0.50.0 silently dropped every packet here.
    (tmp_path / "PIERS0042_WX_20260810060005.csv").write_text(
        "20260810060013 0 009.99 103.1 27.1 66.0 1013.7\n", encoding="ascii"
    )
    (tmp_path / "PIERS0042_WX_20260810060105.csv").write_text(PACKET_2, encoding="ascii")
    (tmp_path / "PIERS0042_TB_20260810_daily.csv").write_text("not WX", encoding="ascii")
    (tmp_path / "PIERS0042_Parsivel_20260810_daily.zip").touch()

    dataset = gv_tools.io.read_aio(tmp_path, XARRAY=True)

    assert dataset.sizes["time"] == 2
    assert dataset.wind_speed.values.tolist() == [4.27, 5.27]  # the daily value wins
    assert dataset.attrs["duplicate_rows"] == 1
    assert daily.name in dataset.attrs["source_files"]
    assert str(tmp_path) not in dataset.attrs["source"]


def test_metone_merges_monthly_files(tmp_path):
    names = ["AIO_GAIL_202501.dat", "AIO_GAIL_202502.dat"]
    (tmp_path / names[0]).write_text(METONE_HEADER + METONE_ROW_1, encoding="ascii")
    (tmp_path / names[1]).write_text(METONE_HEADER + METONE_ROW_2, encoding="ascii")

    files = [tmp_path / name for name in names]
    raw = gv_tools.io.read_aio_raw(files)
    dataset = gv_tools.io.read_aio(files, XARRAY=True)

    assert raw.observations.wind_speed.tolist() == [1.4, 2.4]
    assert dataset.sizes["time"] == 2
    assert dataset.attrs["instrument_id"] == "AIO_GAIL"
    assert dataset.attrs["manufacturer"] == "Met One"
    frame = gv_tools.io.read_aio(files)
    assert isinstance(frame, pd.DataFrame)
    assert frame.wind_speed.tolist() == [1.4, 2.4]


def test_aio_rejects_mixed_manufacturers(tmp_path):
    rm_young = tmp_path / "PIERS0042_WX_20260810060005.csv"
    metone = tmp_path / "AIO_GAIL_202501.dat"
    rm_young.write_text(PACKET_1, encoding="ascii")
    metone.write_text(METONE_HEADER + METONE_ROW_1, encoding="ascii")
    with pytest.raises(ValueError, match="cannot mix"):
        gv_tools.io.read_aio([rm_young, metone])


def test_aio_uses_observation_times_not_filename_dates(tmp_path):
    source = tmp_path / "PIERS0042_WX_20260809000005.csv"
    source.write_text(PACKET_1, encoding="ascii")

    dataset = gv_tools.io.read_aio([source], XARRAY=True)

    assert dataset.sizes["time"] == 1
    assert str(dataset.time.dt.strftime("%Y-%m-%d").item()) == "2026-08-10"


def _telegram(moment):
    values = [0] * 1024
    values[20 * 32 + 10] = 3  # 1.375 mm at 4.4 m s-1
    return f"{moment:%Y%m%d%H%M%S};0,0,0,0,0,0,0,0,0," + ",".join(f"{v:03d}" for v in values) + ","


def _parsivel_zip(path, moments):
    with ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", "\n".join(_telegram(m) for m in moments) + "\n")
    return path


def test_parsivel_file_list_merges_files(tmp_path):
    first = _parsivel_zip(tmp_path / "PIERS0042_Parsivel_20260721_part1.zip",
                          [datetime(2026, 7, 21, 0, 0, 30)])
    second = _parsivel_zip(tmp_path / "PIERS0042_Parsivel_20260721_part2.zip",
                           [datetime(2026, 7, 21, 0, 1, 30)])
    dataset = gv_tools.io.read_parsivel([first, second])
    assert dataset.sizes["time"] == 2
    assert (dataset.precipitation_rate.values > 0).all()
    assert dataset.attrs["source_platform"] == "piers"
    assert dataset.attrs["instrument_id"] == "PIERS0042"
    assert dataset.attrs["telegrams"] == 2


def test_parsivel_decodes_every_supplied_file_in_any_order(tmp_path):
    files = [
        _parsivel_zip(tmp_path / f"apu04_20260{day}00.zip", [datetime(2026, 7, int(day[1:]), 12, 0, 30)])
        for day in ("723", "721", "722")
    ]
    dataset = gv_tools.io.read_parsivel(files)
    observed = dataset.time.values[dataset.telegram_count.values > 0]
    assert [str(value)[:10] for value in observed] == ["2026-07-21", "2026-07-22", "2026-07-23"]
    # minutes between the observations are missing, not dry
    assert np.isnan(dataset.precipitation_rate.sel(time="2026-07-22T00:00").item())
    assert all(path.name in dataset.attrs["source_files"] for path in files)


def test_parsivel_infers_apu_from_archive_name(tmp_path):
    source = _parsivel_zip(tmp_path / "apu09_2026010100.zip", [datetime(2026, 1, 1, 0, 0, 30)])
    assert gv_tools.io.discover_parsivel([source]) == ["2026-01-01"]
    dataset = gv_tools.io.read_parsivel([source])
    assert dataset.attrs["instrument_id"] == "apu09"
    assert dataset.attrs["source_platform"] == "apu"


@pytest.mark.parametrize(
    "name",
    ["apu09_20240306_15.zip", "apu09_2024030615.zip"],
)
def test_parsivel_accepts_hour_with_or_without_separator(tmp_path, name):
    source = _parsivel_zip(
        tmp_path / name,
        [datetime(2024, 3, 6, 15, 0, 30)],
    )
    dataset = gv_tools.io.read_parsivel([source])

    assert int(dataset.telegram_count.sum()) == 1
    assert dataset.attrs["instrument_id"] == "apu09"


def test_parsivel_rejects_non_parsivel_piers_archive(tmp_path):
    source = tmp_path / "PIERS0042_Gauge_20260722.zip"
    source.touch()
    with pytest.raises(ValueError, match="not a recognized Parsivel archive"):
        gv_tools.io.read_parsivel([source])


def test_list_readers_require_fully_qualified_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = Path("apu09_2026010100.zip")
    source.touch()
    with pytest.raises(ValueError, match="fully qualified"):
        gv_tools.io.read_parsivel([source])


def test_read_radar_accepts_one_file(monkeypatch, tmp_path):
    volume = tmp_path / "volume"
    volume.touch()
    marker = object()
    monkeypatch.setattr("gv_tools.io.readers.ingest_radar", lambda path, **options: marker)
    assert gv_tools.io.read_radar(volume) is marker


def test_read_radar_accepts_file_list(monkeypatch, tmp_path):
    files = [tmp_path / "first", tmp_path / "second"]
    for path in files:
        path.touch()
    monkeypatch.setattr("gv_tools.io.readers.ingest_radar", lambda path, **options: path.name)
    assert gv_tools.io.read_radar(files) == ["first", "second"]


def test_read_radar_forwards_xradar_choice(monkeypatch, tmp_path):
    volume = tmp_path / "volume"
    volume.touch()
    calls = []
    monkeypatch.setattr(
        "gv_tools.io.readers.ingest_radar",
        lambda path, **options: calls.append((path, options)) or "tree",
    )

    assert gv_tools.io.read_radar(volume, XRADAR=True) == "tree"
    assert calls == [(volume, {"XRADAR": True})]


def test_2dvd_vectorized_reader_matches_line_parser(tmp_path):
    from gv_tools.io import py_2dvd

    rows = [
        "1 2 3.500 1.2 0.9 4.5 0.98 9500 1 2 3 4 10 20 30 40",
        "1 2 4.000 1.4 1.4 5.0 0.97 9400 1 2 3 4 10 20 30 40",
        "01:02:05.250 1.6 2.1 5.5 0.96 9300 aa bb 1 2 3 4 10 20 30 40",
    ]
    source = tmp_path / "V23022.drops.txt"
    source.write_text("h1\nh2\n" + "\n".join(rows) + "\n")
    frame = py_2dvd.ingest_raw(source)
    assert frame.shape[0] == 3
    assert frame.second.tolist() == [3.5, 4.0, 5.25]
    assert frame.source_extra_1.iloc[2] == "aa"
    assert frame.source_extra_1.iloc[:2].isna().all()
    assert frame.attrs["source_file"] == "V23022.drops.txt"
    bad = tmp_path / "V23023.drops.txt"
    bad.write_text("h1\nh2\n" + rows[0] + "\n1 2 3 x 0.9 4.5 0.98 9500 1 2 3 4 10 20 30 40\n")
    with pytest.raises(ValueError, match="Line 4"):
        py_2dvd.ingest_raw(bad)
