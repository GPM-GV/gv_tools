from pathlib import Path
import pytest

from piers_tools.aio import aio_one_minute, read_aio_day


def test_reads_and_pairs_aio(tmp_path: Path):
    wind = tmp_path / "PIERS0027_wind_20260721000005.csv"
    wx = tmp_path / "PIERS0027_WX_20260721000005.csv"
    wind.write_text("20260721000012 01 130 004.0\ncorrupt\n")
    wx.write_text("20260721000013 0 004.27 103.1 27.1 66.0 1013.7\n")
    wind_frame, wx_frame, combined, stats = read_aio_day([wind], [wx])
    assert len(wind_frame) == len(wx_frame) == len(combined) == 1
    assert bool(combined.loc[0, "aio_pair_matched"])
    assert combined.loc[0, "wind_direction_difference_deg"] == pytest.approx(26.9)
    assert combined.loc[0, "pair_time_offset_seconds"] == -1
    assert stats["wind"].rejected_rows == 1
    assert stats["configuration"] == "rm_young_pair"


def test_one_minute_uses_circular_direction_mean(tmp_path: Path):
    wind = tmp_path / "wind.csv"
    wind.write_text("20260721000010 01 359 2.0\n20260721000020 01 001 4.0\n")
    frame, empty, _, _ = read_aio_day([wind], [])
    minute = aio_one_minute(frame, empty)
    assert minute.loc[0, "wind_speed_m_s"] == 3.0
    assert minute.loc[0, "wind_direction_deg"] == pytest.approx(0.0, abs=1e-8)
    assert minute.loc[0, "wind_sample_count"] == 2


def test_compact_ws800_is_detected_and_parsed_without_wind_file(tmp_path: Path):
    wx = tmp_path / "PIERS0045_WX_20261011_daily.csv"
    wx.write_text(
        "20261011000006,0 003.13 112.5 19.6 69.6 1028.2\n"
        "20261011000036,0 003.33 113.5 19.8 69.8 1028.4\n"
    )

    wind_frame, wx_frame, combined, stats = read_aio_day([], [wx])
    minute = aio_one_minute(wind_frame, wx_frame)

    assert wind_frame.empty
    assert combined.empty
    assert stats["configuration"] == "lufft_ws800_compact"
    assert stats["wx"].rejected_rows == 0
    assert len(wx_frame) == 2
    assert wx_frame.loc[0, "wx_wind_speed_m_s"] == 3.13
    assert wx_frame.loc[0, "wx_wind_direction_deg"] == 112.5
    assert wx_frame.loc[0, "air_temperature_c"] == 19.6
    assert minute.loc[0, "wx_wind_speed_m_s"] == pytest.approx(3.23)
