import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from piers_tools.pipeline import _records_for_date, build_daily_report, load_locations
from piers_tools.parsing import parse_piers_files, parse_piers_multiple_files


RAW_PACKET = """Station_Name: PIERS0001_TB
Latitude/Longitude: 38.0,-75.0
RSSI: -80
Battery_Voltage: 12.8

07/21/2026,00:00:00,TB_A_tips,0,count,good
07/21/2026,00:01:00,TB_A_tips,1,count,good
07/21/2026,00:02:00,TB_A_tips,1,count,good
07/21/2026,00:03:00,TB_A_tips,2,count,good
07/21/2026,00:04:00,TB_B_tips,0,count,good
07/21/2026,00:05:00,TB_B_tips,1,count,good
"""


class PipelineTests(unittest.TestCase):
    def test_records_are_restricted_to_requested_calendar_date(self):
        records = pd.DataFrame(
            {"value": [1, 2, 3, 4]},
            index=pd.to_datetime(
                [
                    "2026-07-21 23:59:59",
                    "2026-07-22 00:00:00",
                    "2026-07-22 23:59:59",
                    "2026-07-23 00:00:00",
                ]
            ),
        )
        result = _records_for_date(records, date(2026, 7, 22))
        self.assertEqual(result["value"].tolist(), [2, 3])

    def test_parser_accepts_one_file_or_a_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            packet = directory / "PIERS0001_TB_001.csv"
            packet.write_text(RAW_PACKET, encoding="utf-8")

            single_metadata, single_tips = parse_piers_multiple_files(
                packet, "PIERS0001"
            )
            directory_metadata, directory_tips = parse_piers_multiple_files(
                directory, "PIERS0001"
            )

        self.assertEqual(len(single_metadata), 1)
        self.assertEqual(len(single_tips), 6)
        self.assertEqual(len(directory_metadata), 1)
        self.assertEqual(len(directory_tips), 6)

    def test_daily_file_counts_each_rssi_packet_header(self):
        daily = RAW_PACKET + """RSSI: -79
Battery_Voltage: 12.7
07/21/2026,00:15:00,TB_A_tips,2,count,good
07/21/2026,00:15:00,TB_B_tips,1,count,good
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "PIERS0001_TB_20260721_daily.csv"
            path.write_text(daily, encoding="utf-8")
            metadata, tips = parse_piers_files([path])
        self.assertEqual(len(metadata), 2)
        self.assertEqual(len(tips), 8)

    def test_location_loader_ignores_lastupdate_footer_only(self):
        workbook_rows = pd.DataFrame(
            {
                "PIERS Station Name": [
                    "PIERS0001",
                    "LastUpdate: 2026-07-31",
                    "PIERS0042",
                ],
                "Latitude": [38.0, None, 39.0],
            }
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            workbook = Path(temporary_directory) / "locations.xlsx"
            workbook.touch()
            with patch("piers_tools.pipeline.pd.read_excel", return_value=workbook_rows):
                result = load_locations(workbook)

        self.assertEqual(
            result["PIERS Station Name"].tolist(),
            ["PIERS0001", "PIERS0042"],
        )

    def test_one_gauge_daily_pipeline(self):
        locations = pd.DataFrame(
            [
                {
                    "PIERS Station Name": "PIERS0001",
                    "Group": "WFF",
                    "Gauge type": "PIERS+",
                    "Station Location": "North Jetty",
                    "Latitude": 38.0,
                    "Longitude": -75.0,
                    "Rain Tips": "0.2,0.254",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            day_dir = base / "PIERS0001" / "2026" / "07" / "21"
            day_dir.mkdir(parents=True)
            (day_dir / "PIERS0001_TB_20260721_daily.csv").write_text(
                RAW_PACKET, encoding="utf-8"
            )
            report = build_daily_report(
                date(2026, 7, 21),
                locations,
                base,
            )

        self.assertEqual(report.at[0, "Tips_A"], 2)
        self.assertEqual(report.at[0, "Group"], "WFF")
        self.assertEqual(report.at[0, "Gauge type"], "PIERS+")
        self.assertEqual(report.at[0, "Station Location"], "North Jetty")
        self.assertEqual(report.at[0, "Tips_B"], 1)
        self.assertAlmostEqual(report.at[0, "Accum_A [mm]"], 0.4)
        self.assertAlmostEqual(report.at[0, "Accum_B [mm]"], 0.254)
        self.assertIn("start_date", report.columns)
        self.assertIn("end_date", report.columns)


if __name__ == "__main__":
    unittest.main()
