import tempfile
import unittest
from datetime import date
from pathlib import Path

from piers_tools.platform_plotting import (
    _read_aio,
    create_platform_fallback,
    discover_instrument_files,
    normalize_platform_type,
    platform_plot_details,
)


class PlatformPlottingTests(unittest.TestCase):
    def test_plot_destination_depends_on_platform_type(self):
        self.assertEqual(platform_plot_details("PIERS"), ("Rain", "rain"))
        self.assertEqual(platform_plot_details("piers+"), ("Platform", "piers_plus"))
        self.assertEqual(platform_plot_details("PIERS++"), ("Platform", "piers_plus_plus"))
        with self.assertRaises(ValueError):
            normalize_platform_type("unknown")

    def test_discovery_supports_both_piers_plus_plus_layouts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = (
                "PIERS0001_Parsivel_20260721.zip",
                "PIERS0001_wind_20260721_daily.csv",
                "PIERS0001_WX_20260721_daily.csv",
                "PIERS0001_WS_800_20260721.csv",
            )
            for name in names:
                (root / name).touch()
            result = discover_instrument_files(root, "PIERS0001", date(2026, 7, 21))
        self.assertEqual(len(result["parsivel"]), 1)
        self.assertEqual(len(result["wind"]), 1)
        self.assertEqual(len(result["wx"]), 1)
        self.assertEqual(len(result["ws800"]), 1)

    def test_discovery_accepts_ws800_name_without_underscore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "PIERS0001_WS800_20260721_daily.csv").touch()
            result = discover_instrument_files(
                root, "PIERS0001", date(2026, 7, 21)
            )
        self.assertEqual(len(result["ws800"]), 1)

    def test_platform_fallback_creates_explanatory_plot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rain_plot = root / "PIERS0001_2026_0721_rain.png"
            rain_plot.write_bytes(b"rain plot is not copied")
            result = create_platform_fallback(
                rain_plot,
                "PIERS0001",
                "PIERS+",
                date(2026, 7, 21),
                root,
                reason="Parsivel products are empty",
            )

            self.assertTrue(result.is_file())
            self.assertTrue(result.read_bytes().startswith(b"\x89PNG"))
            self.assertNotEqual(result.read_bytes(), rain_plot.read_bytes())

    def test_headered_ws800_data_are_parsed(self):
        content = (
            "Timestamp,AirTemp_Act,RelHum_Act,AbsPress_Act,"
            "WindSpd_Act,WindDir_Act\n"
            "20261014000004,20.3,86.5,1014.8,2.3,255.3\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "PIERS0042_WS800_20261014_daily.csv"
            path.write_text(content, encoding="ascii")
            result = _read_aio([path], "wx", ws800=True)

        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.at[0, "wx_wind_speed_m_s"], 2.3)
        self.assertAlmostEqual(result.at[0, "wx_wind_direction_deg"], 255.3)
        self.assertAlmostEqual(result.at[0, "air_temperature_c"], 20.3)


if __name__ == "__main__":
    unittest.main()
