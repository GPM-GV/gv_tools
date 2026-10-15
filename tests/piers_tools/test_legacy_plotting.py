import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import matplotlib.image as mpimg
import pandas as pd

from piers_tools.plotting import decimal_hour, generate_gauge_plots, resolve_plot_root
from piers_tools.day_plotting import _decimal_hour, _parsivel_accumulation_mm


class PlottingTests(unittest.TestCase):
    def test_default_roots_follow_publish_mode(self):
        self.assertEqual(
            resolve_plot_root(publish=False),
            Path("d1/wallops-prf/Gauge/Plots"),
        )
        self.assertEqual(
            resolve_plot_root(publish=True),
            Path("d1/wallops-prf/Gauge/Plots"),
        )

    def test_decimal_hour(self):
        result = decimal_hour(
            pd.DatetimeIndex(["2026-07-21 01:30:00", "2026-07-21 23:45:00"])
        )
        self.assertEqual(result.tolist(), [1.5, 23.75])

    def test_piers_plus_decimal_hour(self):
        result = _decimal_hour(
            pd.DatetimeIndex(["2026-10-11 00:00:06", "2026-10-11 12:30:00"])
        )
        self.assertEqual(result.tolist(), [6 / 3600, 12.5])

    def test_parsivel_accumulation_integrates_one_minute_rain_rate(self):
        parameters = pd.DataFrame(
            {"Rain": [0.0, 60.0, 30.0, float("nan"), -1.0]},
            index=pd.date_range("2026-10-11", periods=5, freq="1min"),
        )
        result = _parsivel_accumulation_mm(parameters)
        self.assertEqual(result.tolist(), [0.0, 1.0, 1.5, 1.5, 1.5])

    def test_three_plots_have_requested_paths_and_dimensions(self):
        metadata = pd.DataFrame(
            {"battery_voltage": [12.5, 12.8], "rssi": [-90, -75]},
            index=pd.DatetimeIndex(
                ["2026-07-21 00:00:00", "2026-07-21 12:30:00"],
                name="timestamp",
            ),
        )
        tip_data = pd.DataFrame(
            {
                "station_name": ["PIERS0001_TB"] * 6,
                "measurement": [
                    "TB_A_tips",
                    "TB_A_tips",
                    "TB_A_tips",
                    "TB_B_tips",
                    "TB_B_tips",
                    "TB_B_tips",
                ],
                "value": [0, 1, 2, 0, 1, 1],
                "quality": ["good"] * 6,
            },
            index=pd.DatetimeIndex(
                [
                    "2026-07-21 00:00:00",
                    "2026-07-21 01:30:00",
                    "2026-07-21 02:00:00",
                    "2026-07-21 00:00:00",
                    "2026-07-21 03:00:00",
                    "2026-07-21 04:00:00",
                ],
                name="timestamp",
            ),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch("piers_tools.plotting._format_axes", wraps=__import__(
                "piers_tools.plotting", fromlist=["_format_axes"]
            )._format_axes) as format_axes:
                paths = generate_gauge_plots(
                    "PIERS0001",
                    date(2026, 7, 21),
                    metadata,
                    tip_data,
                    station_location="North Jetty",
                    rain_tip_a_mm=0.2,
                    rain_tip_b_mm=0.254,
                    plot_root=temporary_directory,
                )
            expected = {
                "rain": "Rain/2026/07/21/PIERS0001_2026_0721_rain.png",
                "voltage": "Battery/2026/07/21/PIERS0001_2026_0721_voltage.png",
                "rssi": "RSSI/2026/07/21/PIERS0001_2026_0721_rssi.png",
            }
            for name, path in paths.items():
                self.assertTrue(path.is_file())
                self.assertTrue(str(path).endswith(expected[name]))
                image = mpimg.imread(path)
                self.assertEqual(image.shape[:2], (600, 1000))
            for format_call in format_axes.call_args_list:
                self.assertEqual(
                    format_call.args[2],
                    "PIERS0001 | North Jetty | Packets 2/96 | 2026-07-21",
                )


if __name__ == "__main__":
    unittest.main()
