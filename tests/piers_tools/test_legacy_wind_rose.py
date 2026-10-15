import numpy as np
import json
import pandas as pd
import pytest

from piers_tools.day_plotting import _daily_time_subset, _wind_rose_frequency, plot_wind_roses


def test_wind_rose_frequency_is_percent_and_wraps_north():
    matrix, count = _wind_rose_frequency(
        speed=[1, 3, 5, 7], direction=[359, 1, 90, 180],
        speed_bins=np.array([0, 2, 4, 6, np.inf]), sectors=8,
    )
    assert count == 4
    assert matrix.sum() == 100
    assert matrix[0].sum() == 50  # 359 and 1 degrees share the north sector.


def test_daily_time_subset_uses_product_day_not_supplied_date():
    frame = pd.DataFrame(
        {"wind": [1, 2, 3]},
        index=pd.to_datetime([
            "2026-10-11 17:00", "2026-10-11 19:00", "2026-10-11 23:00"
        ]),
    )
    selected = _daily_time_subset(
        frame, "2026-07-21 18:00", "2026-07-21 23:30"
    )
    assert selected["wind"].tolist() == [2, 3]


def test_ws800_wind_rose_uses_one_panel_and_accepts_reusable_clock_range(tmp_path):
    day = tmp_path / "PIERS0045" / "2026-10-11"
    day.mkdir(parents=True)
    pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-10-11 19:00", "2026-10-11 20:00"]),
        "wx_wind_speed_m_s": [3.0, 5.0],
        "wx_wind_direction_deg": [90.0, 180.0],
    }).to_csv(day / "aio_one_minute.csv", index=False)
    (day / "manifest.json").write_text(json.dumps({
        "site": "PIERS0045", "day": "2026-10-11",
        "files": {"gauge": 1, "parsivel": 1, "wind": 0, "wx": 1},
        "aio_configuration": "lufft_ws800_compact",
    }))

    output = plot_wind_roses(
        day, tmp_path / "ws800_rose.png",
        start_time="2026-07-21 18:00", end_time="2026-07-21 23:30", show=False,
    )
    assert output.is_file()


def test_piers_plus_wind_rose_returns_none_instead_of_failing(tmp_path):
    day = tmp_path / "PIERS0003" / "2026-02-01"
    day.mkdir(parents=True)
    (day / "manifest.json").write_text(json.dumps({
        "site": "PIERS0003", "day": "2026-02-01",
        "files": {"gauge": 1, "parsivel": 1, "wind": 0, "wx": 0},
    }))
    with pytest.warns(RuntimeWarning, match="no wind instrument"):
        assert plot_wind_roses(day, show=False) is None
