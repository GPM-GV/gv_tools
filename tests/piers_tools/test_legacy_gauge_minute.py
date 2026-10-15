import pandas as pd

from piers_tools.daily import _gauge_one_minute


def test_gauge_minute_uses_counter_changes_and_per_bucket_calibration():
    observations = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([
                "2026-07-21 00:00:01", "2026-07-21 00:00:31", "2026-07-21 00:01:01",
                "2026-07-21 00:00:02", "2026-07-21 00:00:32", "2026-07-21 00:01:02",
            ]),
            "station_name": ["PIERS0027_TB"] * 6,
            "measurement": ["TB_A_tips"] * 3 + ["TB_B_tips"] * 3,
            "value": [10, 11, 11, 20, 20, 21],
            "quality": ["G"] * 6,
        }
    )
    result = _gauge_one_minute(observations, (0.2, 0.254)).set_index("timestamp")
    assert result["TB_A_tip_count"].sum() == 1
    assert result["TB_B_tip_count"].sum() == 1
    assert result["rain_A_cumulative_mm"].iloc[-1] == 0.2
    assert result["rain_B_cumulative_mm"].iloc[-1] == 0.254
