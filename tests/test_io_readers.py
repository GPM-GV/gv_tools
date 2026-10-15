from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import gv_tools
from gv_tools.adapters import parsivel as parsivel_module


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


def test_piers_day_directory_selects_daily_wx_and_ignores_other_instruments(tmp_path):
    daily = tmp_path / "PIERS0042_WX_20260810_daily.csv"
    daily.write_text(
        "20260810060013,0 004.27 103.1 27.1 66.0 1013.7\n", encoding="ascii"
    )
    (tmp_path / "PIERS0042_WX_20260810060105.csv").write_text(PACKET_2, encoding="ascii")
    (tmp_path / "PIERS0042_TB_20260810_daily.csv").write_text("not WX", encoding="ascii")
    (tmp_path / "PIERS0042_Parsivel_20260810_daily.zip").touch()

    dataset = gv_tools.io.read_aio(tmp_path, XARRAY=True)

    assert dataset.sizes["time"] == 1
    assert dataset.attrs["source_files"] == daily.name


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


def test_parsivel_file_list_hides_adapter_and_merges(monkeypatch, tmp_path):
    names = [
        "PIERS0042_Parsivel_20260721_part1.zip",
        "PIERS0042_Parsivel_20260721_part2.zip",
    ]
    for name in names:
        (tmp_path / name).touch()

    calls = []

    def run(path, *args, **kwargs):
        calls.append(kwargs)
        times = pd.date_range("2026-07-21", periods=2, freq="min")
        return {"2026-07-21": (
            pd.DataFrame({"Rain": [1.0, 2.0]}, index=times),
            pd.DataFrame([[1.0], [1.0]], index=times, columns=[0.1]),
            pd.DataFrame([[1.0], [1.0]], index=times, columns=["M0"]),
        )}

    fake = SimpleNamespace(
        __version__="1.0.0", run=run,
        discover_input_dates=lambda path: [pd.Timestamp("2026-07-21")],
    )
    monkeypatch.setattr(parsivel_module, "_backend", lambda: fake)

    files = [tmp_path / name for name in names]
    dataset = gv_tools.io.read_parsivel(files)
    assert dataset.sizes["time"] == 2
    assert dataset.precipitation_rate.values.tolist() == [1.0, 2.0]
    assert dataset.attrs["source_platform"] == "piers"
    assert dataset.attrs["instrument_id"] == "PIERS0042"
    assert calls == [{"start_date": "2026-07-21", "end_date": "2026-07-21"}]


def test_parsivel_decodes_every_supplied_file(monkeypatch, tmp_path):
    files = [
        tmp_path / "apu04_2026072100.zip",
        tmp_path / "apu04_2026072200.zip",
        tmp_path / "apu04_2026072300.zip",
    ]
    for path in files:
        path.touch()
    calls = []

    def run(path, instrument, **options):
        calls.append((sorted(item.name for item in Path(path).iterdir()), options))
        results = {}
        for day in pd.date_range(options["start_date"], options["end_date"]):
            stamp = day.strftime("%Y-%m-%d")
            frames = (
                pd.DataFrame({"Rain": [1.0]}, index=[day]),
                pd.DataFrame([[1.0]], index=[day], columns=[0.1]),
                pd.DataFrame([[1.0]], index=[day], columns=["M0"]),
            )
            results[stamp] = frames
        return results

    fake = SimpleNamespace(
        __version__="1.0.0", run=run,
        discover_input_dates=lambda path: [],
    )
    monkeypatch.setattr(parsivel_module, "_backend", lambda: fake)

    dataset = gv_tools.io.read_parsivel(files)

    assert dataset.sizes["time"] == 3
    assert len(calls) == 1
    assert calls[0][0] == [f"{index:06d}_{path.name}" for index, path in enumerate(files)]
    assert calls[0][1] == {"start_date": "2026-07-21", "end_date": "2026-07-23"}
    assert dataset.attrs["source_files"] == ", ".join(path.name for path in files)


def test_parsivel_infers_apu_from_archive_name(monkeypatch, tmp_path):
    source = tmp_path / "apu09_2026010100.zip"
    source.touch()
    times = pd.date_range("2026-01-01", periods=1, freq="min")
    frames = (
        pd.DataFrame({"Rain": [1.0]}, index=times),
        pd.DataFrame([[1.0]], index=times, columns=[0.1]),
        pd.DataFrame([[1.0]], index=times, columns=["M0"]),
    )
    received = {}

    def run(*args, **kwargs):
        received.update(kwargs)
        return {"2026-01-01": frames}

    fake = SimpleNamespace(
        __version__="1.0.0",
        run=run,
        discover_input_dates=lambda path: [],
    )
    monkeypatch.setattr(parsivel_module, "_backend", lambda: fake)

    assert gv_tools.io.discover_parsivel([source]) == ["2026-01-01"]
    dataset = gv_tools.io.read_parsivel([source])
    assert dataset.attrs["instrument_id"] == "apu09"
    assert dataset.attrs["source_platform"] == "apu"
    assert received == {"start_date": "2026-01-01", "end_date": "2026-01-01"}


def test_parsivel_requires_chronological_file_endpoints(tmp_path):
    files = [
        tmp_path / "apu04_2026072300.zip",
        tmp_path / "apu04_2026072100.zip",
    ]
    for path in files:
        path.touch()

    with pytest.raises(ValueError, match="order files from earliest to latest"):
        gv_tools.io.read_parsivel(files)


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
