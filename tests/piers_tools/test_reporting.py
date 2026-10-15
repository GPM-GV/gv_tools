import tempfile
import unittest
import re
from datetime import date
from pathlib import Path

import pandas as pd

from piers_tools.reporting import gauge_report_to_html


class ReportingTests(unittest.TestCase):
    def test_html_rows_follow_requested_group_and_station_order(self):
        base = {
            "Gauge type": "PIERS",
            "Station Location": "Site",
            "latitude": 38.0,
            "longitude": -75.0,
            "Packets": 96,
            "Volts_min": 12.5,
            "Volts_max": 13.0,
            "RSSI_min": -90,
            "RSSI_max": -70,
            "# Tips_A": 0,
            "# Tips_B": 0,
            "Accum_A [mm]": 0.0,
            "Accum_B [mm]": 0.0,
            "Accum_A [in]": 0.0,
            "Accum_B [in]": 0.0,
            "Bias [%]": 0.0,
        }
        report = pd.DataFrame(
            [
                {**base, "Group": "INCUS", "GaugeID": "PIERS0009"},
                {**base, "Group": "WFF", "GaugeID": "PIERS0002"},
                {**base, "Group": "GPM", "GaugeID": "PIERS0010"},
                {**base, "Group": "WFF", "GaugeID": "PIERS0001"},
            ]
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "report.html"
            gauge_report_to_html(
                report, output, coverage_date=date(2026, 7, 21)
            )
            html = output.read_text(encoding="utf-8")
        positions = [
            html.index(gauge)
            for gauge in ("PIERS0010", "PIERS0001", "PIERS0002", "PIERS0009")
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(html.count('class="group-header"'), 3)
        gpm_header = html.index('class="group-header"')
        self.assertLess(gpm_header, html.index("PIERS0010"))
        self.assertIn(
            '<TH colspan="12"',
            html,
        )

    def test_html_content_and_highlighting(self):
        report = pd.DataFrame(
            [
                {
                    "Group": "WFF",
                    "Gauge type": "PIERS",
                    "GaugeID": "PIERS0001",
                    "Station Location": "North Jetty",
                    "latitude": 38.1234567,
                    "longitude": -75.7654321,
                    "Packets": 40,
                    "Volts_min": 11.5,
                    "Volts_max": 13.0,
                    "RSSI_min": -90,
                    "RSSI_max": -70,
                    "# Tips_A": 3,
                    "# Tips_B": 4,
                    "Accum_A [mm]": 1.234,
                    "Accum_B [mm]": 2.345,
                    "Accum_A [in]": 0.049,
                    "Accum_B [in]": 0.092,
                    "Bias [%]": -11.0,
                }
            ]
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "report.html"
            gauge_report_to_html(
                report,
                output,
                coverage_date=date(2026, 7, 21),
                enable_maps=True,
            )
            html = output.read_text(encoding="utf-8")

        self.assertTrue(html.startswith("<TABLE>"))
        self.assertTrue(html.endswith("</TABLE>"))
        self.assertIn("Report Generated: Local ", html)
        self.assertIn(" or ", html)
        self.assertNotIn(" or UTC ", html)
        self.assertIn("Data Coverage for 2026-07-21", html)
        self.assertIn("North Jetty", html)
        self.assertIn(
            'href="https://maps.google.com/maps?output=embed&amp;z=16&amp;q=38.123457,-75.765432"',
            html,
        )
        self.assertIn("width=700,height=500", html)
        self.assertIn("40/96", html)
        self.assertIn("11.50/13.00", html)
        self.assertIn("3/4", html)
        self.assertIn("1.23", html)
        self.assertIn("background-color:#FFC7CE", html)
        self.assertIn("background-color:#C6EFCE", html)
        self.assertIn("background-color:#FF0000", html)
        self.assertRegex(
            html,
            re.compile(
                r'<TD style="[^"]*background-color:#FFC7CE[^"]*"[^>]*>'
                r'<A href="\.\./Plots/Battery/2026/07/21/'
                r'PIERS0001_2026_0721_voltage\.png"[^>]*>11\.50/13\.00</A>'
            ),
        )
        self.assertIn(
            'href="../Plots/Rain/2026/07/21/PIERS0001_2026_0721_rain.png"',
            html,
        )
        self.assertIn(
            'href="../Plots/RSSI/2026/07/21/PIERS0001_2026_0721_rssi.png"',
            html,
        )
        self.assertEqual(html.count('target="_blank"'), 4)
        self.assertEqual(html.count('rel="noopener noreferrer"'), 4)

    def test_maps_are_disabled_by_default(self):
        report = pd.DataFrame(
            [{
                "Group": "WFF",
                "Gauge type": "PIERS",
                "GaugeID": "PIERS0001",
                "Station Location": "North Jetty",
                "latitude": 38.1,
                "longitude": -75.7,
                "Packets": 96,
                "Volts_min": 12.5,
                "Volts_max": 13.0,
                "RSSI_min": -90,
                "RSSI_max": -70,
                "# Tips_A": 0,
                "# Tips_B": 0,
                "Accum_A [mm]": 0.0,
                "Accum_B [mm]": 0.0,
                "Accum_A [in]": 0.0,
                "Accum_B [in]": 0.0,
                "Bias [%]": 0.0,
            }]
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "report.html"
            gauge_report_to_html(
                report, output, coverage_date=date(2026, 7, 21)
            )
            html = output.read_text(encoding="utf-8")
        self.assertNotIn("google.com/maps", html)

    def test_gauge_type_selects_platform_plot_href(self):
        base = {
            "Group": "GPM",
            "Station Location": "Site",
            "latitude": 38.0,
            "longitude": -75.0,
            "Packets": 96,
            "Volts_min": 12.5,
            "Volts_max": 13.0,
            "RSSI_min": -90,
            "RSSI_max": -70,
            "# Tips_A": 0,
            "# Tips_B": 0,
            "Accum_A [mm]": 0.0,
            "Accum_B [mm]": 0.0,
            "Accum_A [in]": 0.0,
            "Accum_B [in]": 0.0,
            "Bias [%]": 0.0,
        }
        report = pd.DataFrame(
            [
                {**base, "Gauge type": "PIERS", "GaugeID": "PIERS0001"},
                {**base, "Gauge type": "PIERS+", "GaugeID": "PIERS0002"},
                {**base, "Gauge type": "PIERS++", "GaugeID": "PIERS0003"},
            ]
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "report.html"
            gauge_report_to_html(
                report, output, coverage_date=date(2026, 7, 21)
            )
            html = output.read_text(encoding="utf-8")
        self.assertIn(">PIERS0001</A>", html)
        self.assertIn(">PIERS0002+</A>", html)
        self.assertIn(">PIERS0003++</A>", html)
        self.assertIn("PIERS0001_2026_0721_rain.png", html)
        self.assertIn("PIERS0002_2026_0721_piers_plus.png", html)
        self.assertIn("PIERS0003_2026_0721_piers_plus_plus.png", html)
        self.assertNotIn("PIERS0002+_2026_0721_rain.png", html)


if __name__ == "__main__":
    unittest.main()
