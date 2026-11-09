"""PIERS tipping-bucket packets: decoding and tip-counter processing."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import gv_tools


def packet(moments_values, *, station="PIERS0042"):
    lines = [f"Station Name: {station}", "Latitude/Longitude: 37.93, -75.47", "RSSI: -81", "Battery_Voltage: 12.7"]
    for moment, value in moments_values:
        lines.append(f"{moment:%m/%d/%Y},{moment:%H:%M:%S},TB_A_tips,{value},tips,G")
    return "\n".join(lines) + "\n"


def minutes(start, count):
    return [start + timedelta(minutes=index) for index in range(count)]


def test_daily_and_packets_are_both_read_and_exact_repeats_dropped(tmp_path):
    day = datetime(2026, 8, 10, 6, 0)
    daily = tmp_path / "PIERS0042_TB_20260810_daily.csv"
    daily.write_text(packet(zip(minutes(day, 3), [10, 10, 11])))
    # packet repeating the last daily record plus one the daily file lacks
    (tmp_path / "PIERS0042_TB_20260810060305.csv").write_text(
        packet([(day + timedelta(minutes=2), 11), (day + timedelta(minutes=3), 13)])
    )
    frame = gv_tools.io.read_gauge(tmp_path)
    assert frame["value"].tolist() == [10, 10, 11, 13]
    assert frame.attrs["duplicate_records"] == 1
    assert frame.attrs["source_files"] == [daily.name, "PIERS0042_TB_20260810060305.csv"]


def test_cumulative_counter_tips_resets_and_gaps(tmp_path):
    start = datetime(2026, 8, 10, 6, 0)
    records = list(zip(minutes(start, 6), [100, 100, 102, 105, 2, 3]))  # reset at 06:04
    records.append((start + timedelta(minutes=20), 7))  # 14-minute reporting gap
    records.append((start + timedelta(minutes=21), 7))
    source = tmp_path / "PIERS0042_TB_20260810_daily.csv"
    source.write_text(packet(records))

    rain = gv_tools.io.read_tipping_bucket(source, tip_depth_mm=0.254)

    tips = rain["TB_A_tips_tips"]
    # a report covers the minute before its time stamp (interval centre)
    assert tips.loc["2026-08-10 06:00"] == 0
    assert tips.loc["2026-08-10 06:01"] == 2
    assert tips.loc["2026-08-10 06:02"] == 3
    assert tips.loc["2026-08-10 06:03"] == 2  # counted since the reset
    assert rain["TB_A_tips_flag"].loc["2026-08-10 06:03"] & 1
    # minutes inside the gap are missing, not dry; the gap's tips close it
    assert tips.loc["2026-08-10 06:05":"2026-08-10 06:18"].isna().all()
    assert tips.loc["2026-08-10 06:19"] == 4
    assert rain["TB_A_tips_flag"].loc["2026-08-10 06:19"] & 2
    assert np.isnan(rain["TB_A_tips_rate_mm_h"].loc["2026-08-10 06:19"])
    assert np.isnan(tips.loc["2026-08-10 06:21"])  # no report covers the last minute
    assert rain["TB_A_tips_depth_mm"].loc["2026-08-10 06:02"] == pytest.approx(3 * 0.254)
    assert rain["TB_A_tips_rate_mm_h"].loc["2026-08-10 06:02"] == pytest.approx(3 * 0.254 * 60)
    accounting = rain.attrs["accounting"]["TB_A_tips"]
    assert accounting["counter_resets"] == 1 and accounting["gaps"] == 1


@pytest.mark.parametrize("values", [[100, 101, 102, 3, 103, 104], [100, 101, 102, 9999, 103, 104]])
def test_isolated_bad_counter_values_are_not_rain(tmp_path, values):
    start = datetime(2026, 8, 10, 6, 0)
    source = tmp_path / "PIERS0042_TB_20260810_daily.csv"
    source.write_text(packet(zip(minutes(start, 6), values)))
    rain = gv_tools.io.read_tipping_bucket(source, tip_depth_mm=0.254)
    assert rain["TB_A_tips_tips"].sum() == 4
    assert rain["TB_A_tips_depth_mm"].sum() == pytest.approx(4 * 0.254)
    assert rain.attrs["accounting"]["TB_A_tips"]["bad_values_removed"] == 1
    assert (rain["TB_A_tips_flag"] & 16).any()


def test_restart_at_a_high_count_is_a_reset_not_a_wrap(tmp_path):
    start = datetime(2026, 8, 10, 6, 0)
    source = tmp_path / "PIERS0042_TB_20260810_daily.csv"
    source.write_text(packet(zip(minutes(start, 6), [40000, 40001, 40002, 0, 1, 2])))
    rain = gv_tools.io.read_tipping_bucket(source, tip_depth_mm=0.254, counter_max=65535)
    assert rain["TB_A_tips_tips"].tolist()[:5] == [1, 1, 0, 1, 1]


def test_missed_report_makes_the_skipped_minute_unknown(tmp_path):
    start = datetime(2026, 8, 10, 6, 0)
    times = minutes(start, 5)
    source = tmp_path / "PIERS0042_TB_20260810_daily.csv"
    source.write_text(packet([(times[0], 100), (times[1], 103), (times[3], 109), (times[4], 112)]))
    rain = gv_tools.io.read_tipping_bucket(source, tip_depth_mm=0.254)
    tips = rain["TB_A_tips_tips"].tolist()
    assert tips[0] == 3 and np.isnan(tips[1]) and tips[2] == 6 and tips[3] == 3
    assert rain["TB_A_tips_flag"].iloc[2] & 8
    assert np.isnan(rain["TB_A_tips_rate_mm_h"].iloc[2])
    # a skipped report with no tips is known to be dry
    source.write_text(packet([(times[0], 100), (times[1], 100), (times[3], 100), (times[4], 100)]))
    dry = gv_tools.io.read_tipping_bucket(source, tip_depth_mm=0.254)
    assert dry["TB_A_tips_tips"].tolist()[:4] == [0, 0, 0, 0]


def test_start_filter_does_not_invent_a_dry_first_minute(tmp_path):
    start = datetime(2026, 8, 10, 6, 0)
    source = tmp_path / "PIERS0042_TB_20260810_daily.csv"
    source.write_text(packet(zip(minutes(start, 6), [100, 105, 110, 115, 120, 125])))
    rain = gv_tools.io.read_tipping_bucket(source, tip_depth_mm=0.254, start="2026-08-10 06:02")
    tips = rain["TB_A_tips_tips"].tolist()
    assert tips[:3] == [5, 5, 5] and np.isnan(tips[3])


def test_incremental_counter_and_required_tip_depth(tmp_path):
    start = datetime(2026, 8, 10, 6, 0)
    source = tmp_path / "PIERS0042_TB_20260810_daily.csv"
    source.write_text(packet(zip(minutes(start, 4), [0, 1, 0, 2])))
    observations = gv_tools.io.read_gauge(source)
    rain = gv_tools.io.tipping_bucket_rain(observations, tip_depth_mm=0.1, counter="incremental")
    # each report covers the minute before it, so the grid starts at 05:59
    assert str(rain.index[0]) == "2026-08-10 05:59:00"
    assert rain["TB_A_tips_tips"].tolist()[:4] == [0, 1, 0, 2]
    with pytest.raises(TypeError):
        gv_tools.io.tipping_bucket_rain(observations)  # no silent default bucket size
    with pytest.raises(ValueError, match="positive"):
        gv_tools.io.tipping_bucket_rain(observations, tip_depth_mm=0)


def test_counter_rollover_with_known_maximum(tmp_path):
    start = datetime(2026, 8, 10, 6, 0)
    source = tmp_path / "PIERS0042_TB_20260810_daily.csv"
    source.write_text(packet(zip(minutes(start, 3), [65534, 65535, 1])))
    rain = gv_tools.io.read_tipping_bucket(source, tip_depth_mm=0.254, counter_max=65535)
    assert rain["TB_A_tips_tips"].tolist()[:2] == [1, 2]
    assert rain.attrs["accounting"]["TB_A_tips"]["counter_wraps"] == 1
    assert isinstance(rain.index, pd.DatetimeIndex)


def observations(records):
    frame = pd.DataFrame(
        [{"timestamp": pd.Timestamp(moment), "measurement": "TB_A_tips", "value": float(value)} for moment, value in records]
    )
    return frame.set_index("timestamp")


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([0, 1, 2, 0, 1, 2, 3], [1, 1, 0, 1, 1, 1]),  # light rain across a reset at a small count
        ([500, 515, 0, 15, 30, 45], [15, 0, 15, 15, 15]),  # logger reboot during heavy rain
        ([4, 4, 5, 5, 0, 4, 5, 6, 7], [0, 1, 0, 0, 4, 1, 1, 1]),  # reset, then a burst back to the old level
    ],
)
def test_possible_resets_are_not_taken_for_bad_values(values, expected):
    start = datetime(2026, 8, 10, 23, 57)
    rain = gv_tools.io.tipping_bucket_rain(observations(zip(minutes(start, len(values)), values)), tip_depth_mm=0.254)
    assert rain["TB_A_tips_tips"].tolist()[: len(expected)] == expected
    assert rain.attrs["accounting"]["TB_A_tips"]["bad_values_removed"] == 0


@pytest.mark.parametrize(
    ("values", "total"),
    [
        ([15, 15, 0, 0, 15, 15], 0),  # dry evening, small counter, two records of 0
        ([1013, 1013, 0, 0, 0, 0, 1016, 1018], 5),  # dropout longer than glitch_window
        ([100, 101, 0, 0, 0, 105, 106], 6),  # dropout during light rain
        ([0, 3, 5, 4, 7, 8], 8),  # a stale value just after a reset
        ([10, 12, 11, 15], 5),  # a small drop reads as a stale value, not a reset with 11 tips
        ([120, 121, 118, 122, 123], 3),  # a stale value on a large counter
        ([2, 3, 40, 4, 5], 3),  # a spike on a small counter
    ],
)
def test_dropouts_and_stale_values_are_not_rain(values, total):
    start = datetime(2026, 8, 10, 18, 0)
    rain = gv_tools.io.tipping_bucket_rain(observations(zip(minutes(start, len(values)), values)), tip_depth_mm=0.254)
    assert np.nansum(rain["TB_A_tips_tips"]) == total
    assert rain.attrs["accounting"]["TB_A_tips"]["counter_resets"] == 0


def test_glitch_window_zero_reads_every_drop_as_a_reset():
    start = datetime(2026, 8, 10, 6, 0)
    values = [10, 12, 11, 15]
    rain = gv_tools.io.tipping_bucket_rain(
        observations(zip(minutes(start, len(values)), values)), tip_depth_mm=0.254, glitch_window=0
    )
    assert rain["TB_A_tips_tips"].tolist()[:3] == [2, 11, 4]


def test_impossible_lasting_jump_is_unknown_not_rain():
    start = datetime(2026, 8, 10, 6, 0)
    values = [100, 101, 5000, 5001, 5002]  # the counter was re-based
    rain = gv_tools.io.tipping_bucket_rain(observations(zip(minutes(start, len(values)), values)), tip_depth_mm=0.254)
    tips = rain["TB_A_tips_tips"].tolist()
    assert tips[0] == 1 and np.isnan(tips[1]) and tips[2:4] == [1, 1]
    assert rain["TB_A_tips_flag"].iloc[1] & 1
    assert rain.attrs["accounting"]["TB_A_tips"]["impossible_jumps"] == 1


def test_tips_counted_before_a_gap_report_are_kept():
    records = [("2026-08-10 06:00:50", 100), ("2026-08-10 06:01:05", 101), ("2026-08-10 06:01:20", 103),
               ("2026-08-10 06:03:50", 110), ("2026-08-10 06:04:00", 111), ("2026-08-10 06:04:10", 112)]
    rain = gv_tools.io.tipping_bucket_rain(observations(records), tip_depth_mm=0.254)
    assert np.nansum(rain["TB_A_tips_tips"]) == 12
    assert rain["TB_A_tips_flag"].loc["2026-08-10 06:03"] & 2


def test_drop_on_the_last_record_is_unknown():
    start = datetime(2026, 8, 10, 6, 0)
    rain = gv_tools.io.tipping_bucket_rain(
        observations(zip(minutes(start, 4), [100, 101, 102, 7])), tip_depth_mm=0.254
    )
    tips = rain["TB_A_tips_tips"].tolist()
    assert tips[:2] == [1, 1] and np.isnan(tips[2])
    assert rain["TB_A_tips_flag"].iloc[2] & 1


def test_counter_cleared_every_ten_minutes_keeps_every_tip():
    rng = np.random.default_rng(11)
    tips = rng.poisson(1.0, 360)
    counter, running = [], 0
    for minute, count in enumerate(tips):
        running = (0 if minute % 10 == 0 and minute else running) + count
        counter.append(running)
    start = datetime(2026, 8, 10)
    rain = gv_tools.io.tipping_bucket_rain(observations(zip(minutes(start, 360), counter)), tip_depth_mm=0.254)
    assert np.nansum(rain["TB_A_tips_tips"]) == tips[1:].sum()
    assert rain.attrs["accounting"]["TB_A_tips"]["counter_resets"] == 35
