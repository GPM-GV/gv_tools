from pathlib import Path

from piers_tools.daily import _prefer_daily_files


def test_daily_file_is_preferred_over_packet_files(tmp_path: Path):
    packet_a = tmp_path / "PIERS0027_TB_20260721000000.csv"
    packet_b = tmp_path / "PIERS0027_TB_20260721001500.csv"
    daily = tmp_path / "PIERS0027_TB_20260721_daily.csv"

    result = _prefer_daily_files([packet_a, daily, packet_b])

    assert result == [daily]


def test_packet_files_remain_supported_when_no_daily_file_exists(tmp_path: Path):
    packets = [
        tmp_path / "PIERS0027_wind_20260721000000.csv",
        tmp_path / "PIERS0027_wind_20260721001500.csv",
    ]

    assert _prefer_daily_files(packets) == packets
