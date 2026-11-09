"""Tests for the 0.65.0 Parsivel decoder (gv_tools._parsivel)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import pytest

import gv_tools
from gv_tools import _parsivel as P

HEADER = "0.12,1.2,61,23.5,9999,18000,123,25,0"


def spectrum(cells: dict[tuple[int, int], int] | None = None) -> list[int]:
    """1024 raw values in OTT field-93 order from {(diameter, velocity): count}."""
    values = [0] * 1024
    for (diameter, velocity), count in (cells or {}).items():
        values[velocity * 32 + diameter] = count
    return values


def telegram(moment: datetime, cells=None, *, body_values=None) -> str:
    values = body_values if body_values is not None else spectrum(cells)
    return f"{moment:%Y%m%d%H%M%S};{HEADER}," + ",".join(f"{v:03d}" for v in values) + ","


RAIN = {(10, 20): 3, (12, 21): 2, (14, 22): 1}  # 1.375 mm @ 4.4 m/s etc. (inside the filter)


def write_zip(path: Path, member: str, lines: list[str], *, final_newline=True) -> Path:
    text = "\n".join(lines) + ("\n" if final_newline else "")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, text)
    return path


def piers_day(tmp_path: Path, day=datetime(2026, 8, 10), *, interval=10, skip=()):
    """Write 10-minute PIERS packets stamped at the END of their interval (+5 s)."""
    paths = []
    start = day - timedelta(minutes=10)
    while start < day + timedelta(days=1):
        end = start + timedelta(minutes=10)
        stamp = end + timedelta(seconds=5)
        lines = []
        moment = start + timedelta(seconds=5)
        while moment <= end:
            if not any(lo <= moment < hi for lo, hi in skip):
                lines.append(telegram(moment, RAIN))
            moment += timedelta(seconds=interval)
        name = f"PIERS0042_Parsivel_{stamp:%Y%m%d%H%M%S}"
        if lines:
            paths.append(write_zip(tmp_path / f"{name}.zip", f"{name}.csv", lines))
        start = end
    return paths


def test_fourteen_digit_piers_names_are_readable_and_day_keeps_its_last_minutes(tmp_path):
    paths = piers_day(tmp_path)
    dataset = gv_tools.io.read_parsivel(paths, start_date="2026-08-10", end_date="2026-08-10")
    assert str(dataset.time.values[0])[:16] == "2026-08-10T00:00"
    assert str(dataset.time.values[-1])[:16] == "2026-08-10T23:59"
    # 23:50-23:59 live in the packet stamped 2026-08-11 00:00:05
    tail = dataset.sel(time=slice("2026-08-10T23:50", "2026-08-10T23:59"))
    assert tail.sizes["time"] == 10
    assert (tail.telegram_count.values == 6).all()
    assert np.isfinite(tail.precipitation_rate.values).all()
    assert int(dataset.telegram_count.sum()) == 8640


def test_ten_digit_apu_names_are_readable(tmp_path):
    lines = [telegram(datetime(2026, 8, 10, 0, 0, 30) + timedelta(minutes=i), RAIN) for i in range(60)]
    source = write_zip(tmp_path / "apu04_2026081000.zip", "apu04_2026081000.csv", lines)
    dataset = gv_tools.io.read_parsivel([source])
    assert dataset.attrs["instrument_id"] == "apu04"
    assert dataset.sizes["time"] == 60
    assert dataset.attrs["telegram_interval_s"] == 60
    assert gv_tools.io.discover_parsivel([source]) == ["2026-08-10"]


def test_minutes_without_telegrams_are_missing_not_dry(tmp_path):
    outage = (datetime(2026, 8, 10, 6, 0), datetime(2026, 8, 10, 6, 30))
    paths = piers_day(tmp_path, skip=[outage])
    result = P.run(paths)["2026-08-10"][0]
    window = result.loc["2026-08-10 06:00":"2026-08-10 06:29"]
    assert (window["Telegrams"] == 0).all()
    assert window["Rain"].isna().all()
    assert window["Total Drops"].isna().all()
    assert (window["Sample_Seconds"] == 0).all()
    assert result.loc["2026-08-10 06:30", "Rain"] > 0


def test_daily_file_and_packets_count_each_telegram_once(tmp_path):
    packets = piers_day(tmp_path)
    daily_lines = []
    for path in packets:
        with zipfile.ZipFile(path) as archive:
            daily_lines.extend(archive.read(archive.namelist()[0]).decode().splitlines())
    write_zip(tmp_path / "PIERS0042_Parsivel_20260810_daily.zip", "PIERS0042_Parsivel_20260810_daily.csv", daily_lines)
    alone = P.run(packets)["2026-08-10"][0]
    both = P.run(tmp_path)["2026-08-10"][0]
    assert both["Telegrams"].sum() == alone["Telegrams"].sum() == 8640
    pd.testing.assert_series_equal(both["Rain"], alone["Rain"])
    assert both.attrs["duplicate_telegrams"] == 8640  # every packet telegram is also in the daily file


def test_equal_member_names_in_different_archives_are_both_read(tmp_path):
    first = write_zip(tmp_path / "PIERS0042_Parsivel_20260810001005.zip", "data.csv",
                      [telegram(datetime(2026, 8, 10, 0, 1), RAIN)])
    second = write_zip(tmp_path / "PIERS0042_Parsivel_20260810002005.zip", "data.csv",
                       [telegram(datetime(2026, 8, 10, 0, 12), RAIN)])
    result = P.run([first, second], full_day=False)["2026-08-10"][0]
    assert int(result["Telegrams"].sum()) == 2


def test_missing_final_newline_quotes_and_bad_bytes_only_cost_their_own_telegram(tmp_path):
    base = datetime(2026, 8, 10, 12, 0, 0)
    good = [telegram(base + timedelta(seconds=10 * i), RAIN) for i in range(6)]
    quoted = good[2].replace(";", ';"', 1)  # a stray quote after the ';' (header field)
    broken = good[3][:500] + "\x93" + good[3][501:]  # non-UTF-8 byte inside the spectrum
    first = tmp_path / "PIERS0042_Parsivel_20260810120005.csv"
    first.write_bytes(("\n".join([good[0], good[1], quoted]) ).encode())  # no final newline
    second = tmp_path / "PIERS0042_Parsivel_20260810120105.csv"
    second.write_bytes(("\n".join([broken, good[4], good[5]]) + "\n").encode("latin-1"))
    parms = P.run([first, second], full_day=False)["2026-08-10"][0]
    # The quote is in a header field, so that telegram survives; only the
    # corrupted spectrum is rejected.
    assert int(parms["Telegrams"].sum()) == 5
    assert parms.attrs["rejected_lines"] == 1


def test_two_telegrams_run_together_on_one_line_are_split(tmp_path):
    base = datetime(2026, 8, 10, 12, 0, 0)
    line = telegram(base, RAIN) + telegram(base + timedelta(seconds=10), RAIN)
    source = tmp_path / "PIERS0042_Parsivel_20260810_daily.csv"
    source.write_text(line + "\n")
    parms = P.run(source, full_day=False)["2026-08-10"][0]
    assert int(parms["Telegrams"].sum()) == 2


def test_no_scratch_files_are_written(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    piers_day(data)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    P.run(data)
    assert list(work.iterdir()) == []
    with pytest.warns(DeprecationWarning):
        P.run(data, temp_root=work)
    assert list(work.iterdir()) == []


def test_source_attributes_hold_no_directories(tmp_path):
    paths = piers_day(tmp_path)
    dataset = gv_tools.io.read_parsivel(tmp_path)
    assert str(tmp_path) not in dataset.attrs["source"]
    assert str(tmp_path) not in dataset.attrs["source_files"]
    assert paths[0].name in dataset.attrs["source_files"]


def test_single_cell_number_concentration_uses_that_cells_velocity():
    classes = P.get_parsivel_classes("ott")
    diameter, velocity = 12, 21  # 1.875 mm, 5.2 m s-1 (inside the filter)
    assert classes.mask[diameter, velocity]
    counts = np.zeros((1, 32, 32))
    counts[0, diameter, velocity] = 10
    parameters, nd, moments = P.integral_parameters(counts, [60.0], classes)
    area_m2 = 180e-3 * (30e-3 - classes.diameter[diameter] / 2 * 1e-3)
    expected = 10 / (area_m2 * 60.0 * classes.velocity[velocity] * classes.diameter_width[diameter])
    assert nd[0, diameter] == pytest.approx(expected, rel=1e-12)
    assert parameters["Concentration"][0] == pytest.approx(expected * classes.diameter_width[diameter])
    theoretical, nd_t, _ = P.integral_parameters(counts, [60.0], classes, fall_speed="theoretical")
    assert nd_t[0, diameter] == pytest.approx(
        expected * classes.velocity[velocity] / classes.terminal_velocity[diameter]
    )
    # rain rate is a volume flux and does not depend on the fall-speed choice
    volume = math.pi / 6 * classes.diameter[diameter] ** 3
    rain = 10 * volume / (area_m2 * 1e6) * 3600 / 60
    assert parameters["Rain"][0] == pytest.approx(rain)
    assert theoretical["Rain"][0] == pytest.approx(rain)


def test_parameters_match_textbook_formulas():
    classes = P.get_parsivel_classes("ott")
    rng = np.random.default_rng(3)
    counts = np.where(classes.mask, rng.poisson(4, (32, 32)), 0)[None].astype(float)
    parameters, nd, moments = P.integral_parameters(counts, [60.0], classes)
    d, dd = classes.diameter, classes.diameter_width
    m = [float((nd[0] * d**k * dd).sum()) for k in range(8)]
    assert moments[0] == pytest.approx(m)
    assert parameters["Dm"][0] == pytest.approx(m[4] / m[3])
    variance = float((nd[0] * dd * d**3 * (d - m[4] / m[3]) ** 2).sum()) / m[3]
    assert parameters["Sigma_M"][0] == pytest.approx(math.sqrt(variance))  # sigma_m is a standard deviation
    lwc = math.pi / 6 * 1e-3 * m[3]
    assert parameters["LWC"][0] == pytest.approx(lwc)
    assert parameters["Nw"][0] == pytest.approx(4**4 / (math.pi * 1e-3) * lwc / (m[4] / m[3]) ** 4)
    assert parameters["dBZ"][0] == pytest.approx(10 * math.log10(m[6]))


def test_dry_observed_minute_has_zero_rain_and_undefined_shape_parameters():
    classes = P.get_parsivel_classes("ott")
    parameters, nd, moments = P.integral_parameters(np.zeros((1, 32, 32)), [60.0], classes)
    assert parameters["Rain"][0] == 0 and parameters["Z"][0] == 0
    assert np.isnan(parameters["dBZ"][0]) and np.isnan(parameters["Dm"][0])
    assert np.isnan(parameters["Sigma_M"][0]) and np.isnan(parameters["Dmax"][0])


def test_partial_minute_rates_use_the_sampled_duration(tmp_path):
    base = datetime(2026, 8, 10, 12, 0, 5)
    lines = [telegram(base + timedelta(seconds=10 * i), RAIN) for i in range(12)]  # 12:00 and 12:01 full
    lines = lines[:6] + lines[6:9]  # 12:01 keeps only 3 of its 6 telegrams
    source = tmp_path / "PIERS0042_Parsivel_20260810_daily.csv"
    source.write_text("\n".join(lines) + "\n")
    parms = P.run(source, full_day=False)["2026-08-10"][0]
    assert list(parms["Telegrams"]) == [6, 3]
    assert list(parms["Sample_Seconds"]) == [60.0, 30.0]
    # Same drops per telegram -> same rate in both minutes.
    assert parms["Rain"].iloc[1] == pytest.approx(parms["Rain"].iloc[0])


def test_legacy_classes_and_tables_round_trip():
    legacy = P.get_parsivel_classes("legacy")
    assert legacy.diameter[0] == pytest.approx(0.064)
    assert not legacy.mask[24, 20]  # isolated cell removed
    dv, mask = P.load_tables(classes="legacy")
    assert mask.shape == (32, 33)
    rebuilt = P.classes_from_tables(dv, mask)
    np.testing.assert_array_equal(rebuilt.mask, legacy.mask)
    ott_dv, _ = P.load_tables()
    assert ott_dv["Drop_bin"].iloc[0] == pytest.approx(0.062)
    assert ott_dv["Measured_Vt"].iloc[10] == pytest.approx(1.1)


def test_get_integral_parameters_keeps_its_signature():
    import xarray as xr

    dv, mask = P.load_tables()
    drops = np.zeros((2, 32, 32))
    drops[0, 12, 21] = 5
    drops[1] = np.nan  # a missing minute
    dataset = xr.Dataset(
        {"drops": (("time", "Diam", "Vel"), drops)},
        coords={"time": pd.date_range("2026-08-10", periods=2, freq="min")},
    )
    parms, psd, moments = P.get_integral_parameters("PIERS0042", dataset, mask, dv)
    assert parms["Rain"].iloc[0] > 0
    assert np.isnan(parms["Rain"].iloc[1])
    assert list(moments.columns) == [f"M{i}" for i in range(8)]


def test_filename_stamps_and_content_based_discovery(tmp_path):
    assert P.filename_stamp("PIERS0042_Parsivel_20260810001005.zip") == pd.Timestamp("2026-08-10 00:10:05")
    assert P.filename_stamp("apu04_2026081000.zip") == pd.Timestamp("2026-08-10 00:00")
    assert P.filename_stamp("PIERS0042_Parsivel_20260810_daily.zip") == pd.Timestamp("2026-08-10")
    # named for Aug 11, holds only an Aug 10 telegram: dates come from the content
    boundary = write_zip(
        tmp_path / "PIERS0042_Parsivel_20260811000005.zip", "x.csv",
        [telegram(datetime(2026, 8, 10, 23, 59, 55), RAIN)],
    )
    assert [str(day.date()) for day in P.discover_input_dates(boundary)] == ["2026-08-10"]


def test_optional_raw_spectrum_marks_missing_minutes(tmp_path):
    base = datetime(2026, 8, 10, 12, 0, 30)
    source = tmp_path / "PIERS0042_Parsivel_20260810_daily.csv"
    source.write_text("\n".join(telegram(base + timedelta(minutes=2 * i), RAIN) for i in range(3)) + "\n")
    dataset = gv_tools.io.read_parsivel([source], include_spectrum=True, telegram_interval_s=60)
    assert dataset.raw_spectrum.dims == ("time", "drop_diameter", "fall_velocity")
    assert np.isnan(dataset.raw_spectrum.sel(time="2026-08-10T12:01").values).all()
    assert float(dataset.raw_spectrum.sel(time="2026-08-10T12:00").sum()) == 6
    raw = gv_tools.io.read_parsivel_raw([source], include_spectrum=True, telegram_interval_s=60)
    assert raw.spectrum is not None and raw.spectrum.sizes["time"] == 1440
    assert raw.parameters.attrs["telegrams"] == 3


def _apu_day(day, *, interval=60, offset=30, start=None, end=None):
    moment = (start or day) + timedelta(seconds=offset)
    stop = end or day + timedelta(days=1)
    lines = []
    while moment < stop:
        lines.append(telegram(moment, RAIN))
        moment += timedelta(seconds=interval)
    return lines


def test_interval_survives_heavy_random_loss(tmp_path):
    rng = np.random.default_rng(0)
    lines = [line for line in _apu_day(datetime(2026, 8, 10)) if rng.random() > 0.6]
    source = tmp_path / "apu04_20260810_daily.csv"
    source.write_text("\n".join(lines) + "\n")
    inferred = P.run(source)["2026-08-10"][0]
    truth = P.run(source, telegram_interval_s=60)["2026-08-10"][0]
    assert inferred.attrs["telegram_interval_s"] == 60
    pd.testing.assert_series_equal(inferred["Rain"], truth["Rain"])


def test_interval_change_within_a_day_is_followed(tmp_path):
    day = datetime(2026, 8, 10)
    lines = _apu_day(day, end=day + timedelta(hours=12)) + _apu_day(
        day, interval=10, offset=5, start=day + timedelta(hours=12)
    )
    source = tmp_path / "apu04_20260810_daily.csv"
    source.write_text("\n".join(lines) + "\n")
    parms = P.run(source)["2026-08-10"][0]
    assert (parms.loc["2026-08-10 06:00":"2026-08-10 11:59", "Sample_Seconds"] == 60).all()
    assert (parms.loc["2026-08-10 12:00":"2026-08-10 18:00", "Sample_Seconds"] == 60).all()
    assert (parms.loc["2026-08-10 12:00":"2026-08-10 18:00", "Telegrams"] == 6).all()
    # same drops per telegram: a 10 s telegram is a 6x higher rate
    assert parms.loc["2026-08-10 18:00", "Rain"] == pytest.approx(6 * parms.loc["2026-08-10 06:00", "Rain"])


def test_telegram_is_counted_in_the_minute_holding_its_interval_centre(tmp_path):
    # 60 s telegrams stamped on the minute: 12:01:00 holds 12:00:00-12:01:00
    source = tmp_path / "apu04_20260810_daily.csv"
    source.write_text("\n".join(_apu_day(datetime(2026, 8, 10, 12), offset=0, end=datetime(2026, 8, 10, 12, 5))) + "\n")
    centre = P.run(source, full_day=False)
    stamp = P.run(source, full_day=False, time_binning="stamp")["2026-08-10"][0]
    assert list(centre) == ["2026-08-10"]
    assert str(centre["2026-08-10"][0].index[0]) == "2026-08-10 11:59:00"
    assert str(stamp.index[0]) == "2026-08-10 12:00:00"


def test_partial_archive_cannot_replace_a_complete_day(tmp_path):
    for day in (8, 9, 10):
        (tmp_path / f"apu04_202608{day:02d}_daily.csv").write_text(
            "\n".join(_apu_day(datetime(2026, 8, day))) + "\n"
        )
    # an archive named for Aug 11 that also holds the second half of Aug 9
    week = _apu_day(datetime(2026, 8, 9), start=datetime(2026, 8, 9, 12), end=datetime(2026, 8, 11, 12))
    write_zip(tmp_path / "apu04_20260811.zip", "apu04_week.csv", week)
    days = list(P.iter_days(tmp_path))
    labels = [label for label, _ in days]
    assert labels == sorted(set(labels))  # each day produced once
    result = dict(days)
    assert int(result["2026-08-09"][0]["Telegrams"].sum()) == 1440
    assert result["2026-08-09"][0].attrs["duplicate_telegrams"] == 720


def test_date_filter_reads_multi_day_file_named_by_its_first_day(tmp_path):
    lines = []
    for day in range(1, 6):
        lines += _apu_day(datetime(2026, 8, day))
    month = tmp_path / "apu04_20260801_month.csv"
    month.write_text("\n".join(lines) + "\n")
    assert len(P.process_input(month, "apu04", 2026, 8, 4)[0]) == 1440
    assert list(P.run(month, start_date="2026-08-04", end_date="2026-08-04")) == ["2026-08-04"]


@pytest.mark.parametrize("header_fields", [8, 10])
def test_telegram_with_wrong_header_field_count_is_rejected(header_fields):
    values = spectrum({(12, 21): 9})
    header = ",".join(["0"] * header_fields)
    line = "20260810120000;" + header + "," + ",".join(f"{v:03d}" for v in values) + ","
    telegrams, rejected = P.parse_telegram_line(line)
    assert telegrams == [] and rejected == 1
    shifted, _ = P.parse_telegram_line(line, spectrum_offset=header_fields)
    assert shifted[0][1][21 * 32 + 12] == 9


def test_undated_names_are_released_day_by_day(tmp_path, monkeypatch):
    for day in range(1, 8):
        (tmp_path / f"apu04_2026-08-{day:02d}.csv").write_text("\n".join(_apu_day(datetime(2026, 8, day))) + "\n")
    held = []
    original = P._Assembler.read

    def spy(self, source, cap=None):
        yield from original(self, source, cap)
        held.append(len({key // 86400 for key in self.spectra}))

    monkeypatch.setattr(P._Assembler, "read", spy)
    assert len(list(P.iter_days(tmp_path))) >= 7
    assert max(held) <= 2


def test_one_long_ordered_file_is_released_while_it_is_read(tmp_path, monkeypatch):
    lines = []
    for day in range(1, 8):
        lines += _apu_day(datetime(2026, 8, day))
    single = tmp_path / "apu04_august.csv"
    single.write_text("\n".join(lines) + "\n")
    held = []
    original = P._Assembler._add

    def spy(self, epoch, counts, label_id):
        added = original(self, epoch, counts, label_id)
        held.append(len({key // 86400 for key in self.spectra}))
        return added

    monkeypatch.setattr(P._Assembler, "_add", spy)
    days = dict(P.iter_days(single))
    assert sorted(days) == [f"2026-08-{day:02d}" for day in range(1, 8)]
    assert max(held) <= 2  # never more than the day being read and the one before
    monkeypatch.undo()
    # identical products to reading the same telegrams in shuffled order (no early release)
    shuffled = tmp_path / "shuffled" / "apu04_august.csv"
    shuffled.parent.mkdir()
    shuffled.write_text("\n".join(lines[1::2] + lines[0::2]) + "\n")
    again = dict(P.iter_days(shuffled))
    for label, (parms, psd, moments) in days.items():
        pd.testing.assert_frame_equal(parms, again[label][0])
        pd.testing.assert_frame_equal(psd, again[label][1])


def test_impossible_stamp_does_not_stop_early_release(tmp_path, monkeypatch):
    lines = ["20261310120000;" + telegram(datetime(2026, 8, 1), RAIN).split(";", 1)[1]]  # month 13
    lines.append(telegram(datetime(1999, 12, 31, 23, 59, 59), RAIN))  # clock not set
    for day in range(1, 6):
        lines += _apu_day(datetime(2026, 8, day))
    (tmp_path / "apu04_august.csv").write_text("\n".join(lines) + "\n")
    held = []
    original = P._Assembler._add

    def spy(self, epoch, counts, label_id):
        added = original(self, epoch, counts, label_id)
        held.append(len({key // 86400 for key in self.spectra}))
        return added

    monkeypatch.setattr(P._Assembler, "_add", spy)
    days = dict(P.iter_days(tmp_path))
    assert len(days) == 5 and max(held) <= 2
    assert days["2026-08-01"][0].attrs["rejected_lines"] == 2


def test_impossible_future_stamp_does_not_close_a_file_early(tmp_path):
    lines = _apu_day(datetime(2026, 8, 1))
    lines.append(telegram(datetime(2099, 1, 1), RAIN))  # logger clock jumped
    lines += _apu_day(datetime(2026, 8, 2)) + _apu_day(datetime(2026, 8, 3))
    (tmp_path / "apu04_august.csv").write_text("\n".join(lines) + "\n")
    days = dict(P.iter_days(tmp_path, start_date="2026-08-01", end_date="2026-08-03"))
    assert {label: frames[0].attrs["telegrams"] for label, frames in days.items()} == {
        "2026-08-01": 1440, "2026-08-02": 1440, "2026-08-03": 1440,
    }


def test_date_window_skips_other_days_without_changing_the_window(tmp_path):
    lines = []
    for day in range(1, 5):
        lines += _apu_day(datetime(2026, 8, day))
    lines.insert(30, "20260801003000;not,a,telegram")  # outside the window: not decoded
    reference = tmp_path / "reference" / "apu04_august.csv"
    reference.parent.mkdir()
    reference.write_text("\n".join(lines) + "\n")
    full = dict(P.iter_days(reference))
    reversed_copy = tmp_path / "reversed" / "apu04_august.csv"
    reversed_copy.parent.mkdir()
    reversed_copy.write_text("\n".join(lines[::-1]) + "\n")
    for path in (reference, reversed_copy):
        window = dict(P.iter_days(path, start_date="2026-08-02", end_date="2026-08-03"))
        assert sorted(window) == ["2026-08-02", "2026-08-03"]
        for label, frames in window.items():
            for mine, expected in zip(frames, full[label]):
                pd.testing.assert_frame_equal(mine, expected)
            assert frames[0].attrs["rejected_lines"] == 0


def test_overlapping_ordered_files_hold_days_the_next_file_can_still_add_to(tmp_path):
    every = []
    for day in range(1, 5):
        every += _apu_day(datetime(2026, 8, day))
    split_a, split_b = 1440 + 720, 1440 + 600  # overlap on 2 Aug, 10:00-12:00
    (tmp_path / "pair").mkdir()
    (tmp_path / "pair" / "apu04_a.csv").write_text("\n".join(every[:split_a]) + "\n")
    (tmp_path / "pair" / "apu04_b.csv").write_text("\n".join(every[split_b:]) + "\n")
    (tmp_path / "one").mkdir()
    (tmp_path / "one" / "apu04_all.csv").write_text("\n".join(every) + "\n")
    expected = dict(P.iter_days(tmp_path / "one"))
    produced = dict(P.iter_days(tmp_path / "pair"))
    assert sorted(produced) == sorted(expected) == [f"2026-08-0{day}" for day in range(1, 5)]
    for label, frames in produced.items():
        for mine, reference in zip(frames, expected[label]):
            pd.testing.assert_frame_equal(mine, reference)
    assert produced["2026-08-02"][0].attrs["duplicate_telegrams"] == 120
    assert produced["2026-08-02"][0].attrs["telegrams"] == 1440


def _guard_release(monkeypatch, limit=500):
    """Fail instead of looping forever if day release stops making progress."""
    calls = {"n": 0}
    original = P._Assembler._release_day

    def guarded(self, day):
        calls["n"] += 1
        assert calls["n"] < limit, f"release loop did not finish (at {P._day_label(day)})"
        return original(self, day)

    monkeypatch.setattr(P._Assembler, "_release_day", guarded)


def test_files_inside_an_earlier_files_gap_do_not_stall_the_release(tmp_path, monkeypatch):
    _guard_release(monkeypatch)
    month = [line for day in (1, 2, 3, 15, 16) for line in _apu_day(datetime(2026, 8, day))]
    write_zip(tmp_path / "apu04_202608.zip", "apu04_202608.csv", month)
    for day in (5, 6):  # recovered later, inside the archive's outage
        (tmp_path / f"apu04_recovered_{day:02d}.csv").write_text("\n".join(_apu_day(datetime(2026, 8, day))) + "\n")
    days = {label: frames[0].attrs["telegrams"] for label, frames in P.iter_days(tmp_path)}
    assert days == {f"2026-08-{day:02d}": 1440 for day in (1, 2, 3, 5, 6, 15, 16)}


def test_mis_stamped_telegram_and_missing_day_do_not_stall_the_release(tmp_path, monkeypatch):
    _guard_release(monkeypatch)
    (tmp_path / "a.csv").write_text(
        "\n".join(_apu_day(datetime(2026, 8, 1)) + [telegram(datetime(2026, 8, 20, 12), RAIN)]) + "\n"
    )
    (tmp_path / "b.csv").write_text("\n".join(_apu_day(datetime(2026, 8, 3))) + "\n")
    days = {label: frames[0].attrs["telegrams"] for label, frames in P.iter_days(tmp_path)}
    assert days == {"2026-08-01": 1440, "2026-08-03": 1440, "2026-08-20": 1}


def test_clock_reset_stamps_are_rejected_not_turned_into_days(tmp_path, monkeypatch):
    _guard_release(monkeypatch)
    for day in (8, 9):
        (tmp_path / f"apu04_202608{day:02d}_daily.csv").write_text(
            "\n".join(_apu_day(datetime(2026, 8, day))) + "\n")
    reset = [telegram(datetime(2000, 1, 1, 0, 5, 12), RAIN), telegram(datetime(2099, 1, 1), RAIN)]
    (tmp_path / "apu04_20260810_daily.csv").write_text(
        "\n".join(reset + _apu_day(datetime(2026, 8, 10))) + "\n")
    days = dict(P.iter_days(tmp_path))
    assert {label: frames[0].attrs["telegrams"] for label, frames in days.items()} == {
        "2026-08-08": 1440, "2026-08-09": 1440, "2026-08-10": 1440,
    }
    assert days["2026-08-10"][0].attrs["rejected_lines_by_file"] == "apu04_20260810_daily.csv=2"
    assert [str(day.date()) for day in P.discover_input_dates(tmp_path)] == ["2026-08-08", "2026-08-09", "2026-08-10"]


def test_discovered_dates_are_the_days_with_telegrams(tmp_path):
    lines = _apu_day(datetime(2026, 8, 1)) + _apu_day(datetime(2026, 8, 20))
    (tmp_path / "apu04_august.csv").write_text("\n".join(lines) + "\n")
    assert [str(day.date()) for day in P.discover_input_dates(tmp_path)] == ["2026-08-01", "2026-08-20"]


def test_telegram_left_for_the_next_day_keeps_its_interval(tmp_path, caplog):
    # 10 s until 23:00, one telegram at 00:00:25, then 60 s from 01:00: with
    # its later neighbours its interval would come out as 60 s and move it
    # back into the finished day
    day9, day10 = datetime(2026, 8, 9), datetime(2026, 8, 10)
    lines = _apu_day(day9, interval=10, offset=5, end=day9 + timedelta(hours=23))
    lines.append(telegram(day10 + timedelta(seconds=25), RAIN))
    lines += _apu_day(day10, interval=60, offset=3600)
    (tmp_path / "a.csv").write_text("\n".join(lines) + "\n")
    with caplog.at_level("WARNING", logger="gv_tools"):
        days = dict(P.iter_days(tmp_path))
    assert sum(frames[0].attrs["telegrams"] for frames in days.values()) == len(lines)
    assert not [record for record in caplog.records if "after their day" in record.getMessage()]


def test_telegram_logged_twice_a_second_apart_counts_once(tmp_path):
    day = datetime(2026, 8, 10)
    lines = []
    for moment in (day + timedelta(seconds=5 + 10 * k) for k in range(8640)):
        lines += [telegram(moment, RAIN), telegram(moment + timedelta(seconds=1), RAIN)]
    (tmp_path / "a.csv").write_text("\n".join(lines) + "\n")
    parms = P.run(tmp_path)["2026-08-10"][0]
    assert parms.attrs["telegram_interval_s"] == 10
    assert parms.attrs["duplicate_telegrams"] == 8640
    assert parms.loc["2026-08-10 12:00", "Telegrams"] == 6
    assert parms.loc["2026-08-10 12:00", "Sample_Seconds"] == 60


def test_late_stamp_next_to_the_following_telegram_is_not_a_repeat(tmp_path):
    # dry 10 s data where one telegram was stamped 9 s late, 1 s before the next
    day = datetime(2026, 8, 10)
    stamps = [day + timedelta(seconds=5 + 10 * k) for k in range(8640)]
    stamps[3000] += timedelta(seconds=9)
    (tmp_path / "a.csv").write_text("\n".join(telegram(moment) for moment in stamps) + "\n")
    parms = P.run(tmp_path)["2026-08-10"][0]
    assert parms.attrs["telegrams"] == 8640
    assert parms.attrs["duplicate_telegrams"] == 0


def test_file_whose_telegrams_are_all_rejected_is_in_the_provenance(tmp_path):
    day = datetime(2026, 8, 10)
    good = _apu_day(day, interval=10, offset=5)
    shifted = [line.replace(HEADER + ",", HEADER.split(",", 1)[1] + ",", 1) for line in good]  # 8-field header
    (tmp_path / "PIERS0042_Parsivel_20260810_daily.csv").write_text("\n".join(good[:4320]) + "\n")
    (tmp_path / "PIERS0042_Parsivel_20260810_b.csv").write_text("\n".join(shifted[4320:]) + "\n")
    dataset = gv_tools.io.read_parsivel([tmp_path])
    assert dataset.attrs["rejected_lines"] == 4320
    assert dataset.attrs["rejected_lines_by_file"] == "PIERS0042_Parsivel_20260810_b.csv=4320"


def test_stamp_scan_matches_the_decoder_across_chunk_edges():
    stamps = [b"20260810120000", b"20260810120100"]
    for cut in range(0, 40):
        text = b"x" * cut + b"\n" + stamps[0] + b";1,2\n" + b"123" + stamps[1] + b";9\n" + stamps[1] + b";3"
        whole = P._stamps_before_semicolons(text)
        # feed it in pieces the way _scan does
        pieces, tail = [], b""
        for begin in range(0, len(text), 7):
            data = tail + text[begin:begin + 7]
            pieces += P._stamps_before_semicolons(data, len(tail))
            tail = data[-15:]
        assert whole == pieces == [stamps[0], stamps[1]]
    # non-ASCII digits are never a time stamp (and never crash the decoder)
    assert P.parse_telegram_line("2026081012\u00b2000;" + ",".join(["0"] * 1033)) == ([], 1)


@pytest.mark.parametrize("cadence", [10, 30, 60])
def test_interval_tolerates_late_stamps_and_loss(cadence):
    # logger stamps 0-3 s late (whole seconds) and 30 % of the telegrams lost
    rng = np.random.default_rng(cadence)
    times = cadence * np.arange(1, 6001) + np.floor(rng.uniform(0, 4, 6000))
    times = times[rng.random(times.size) > 0.3]
    intervals, source = P.telegram_intervals(times)
    assert np.all(intervals == cadence)
    assert set(source) <= {"local", "neighbour", "sequence"}


def test_rejected_lines_are_counted_once_per_file(tmp_path):
    lines = []
    for day in (10, 11, 12):
        lines += _apu_day(datetime(2026, 8, day))
    lines.insert(5, "garbage line;with;semicolons")
    lines.insert(50, "20260810120000;bad")
    source = tmp_path / "apu04_20260810_3day.csv"
    source.write_text("\n".join(lines) + "\n")
    dataset = gv_tools.io.read_parsivel([source])
    assert dataset.attrs["rejected_lines"] == 2
    assert dataset.attrs["telegrams"] == 4320


def test_raw_field_order_maps_to_diameter_and_velocity(tmp_path):
    # OTT field 93 lists the 32 diameters of velocity class 1 first, so value
    # index v * 32 + d is diameter class d at velocity class v.
    source = tmp_path / "apu04_20260810_daily.csv"
    moments = [datetime(2026, 8, 10, 12, 0, 30) + timedelta(minutes=i) for i in range(3)]
    source.write_text("\n".join(telegram(moment, {(12, 21): 7}) for moment in moments) + "\n")
    parms, psd, _ = P.run(source, full_day=False)["2026-08-10"]
    classes = P.get_parsivel_classes()
    assert np.flatnonzero(psd.iloc[0].to_numpy()) .tolist() == [12]
    assert parms["V"].iloc[0] == pytest.approx(classes.velocity[21])
    assert parms["Dmax"].iloc[0] == pytest.approx(classes.diameter[12])
