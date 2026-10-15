import argparse
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from piers_tools.cli import parse_command_line_args, run
from piers_tools.platform_cli import parser as processing_parser
from piers_tools.daily import DEFAULT_GAUGE_STATUS_PATH, DEFAULT_INPUT_ROOT


class CommandLineTests(unittest.TestCase):
    def test_location_workbook_is_required(self):
        with self.assertRaises(SystemExit):
            parse_command_line_args(["2026", "7", "21"])

    def test_user_can_override_gauge_location_workbook(self):
        args = parse_command_line_args(
            ["2026", "7", "21", "--locations", "/data/custom.xlsx"]
        )
        self.assertEqual(args.locations, "/data/custom.xlsx")

    def test_processing_cli_default_and_override(self):
        default_args = processing_parser().parse_args(["PIERS0027", "2026", "7", "21"])
        custom_args = processing_parser().parse_args([
            "PIERS0027", "2026", "7", "21",
            "--gauge-status", "/data/custom.xlsx",
        ])
        self.assertEqual(default_args.gauge_status, str(DEFAULT_GAUGE_STATUS_PATH))
        self.assertEqual(default_args.input_root, str(DEFAULT_INPUT_ROOT))
        self.assertEqual(custom_args.gauge_status, "/data/custom.xlsx")

    def test_notebook_style_argument_list(self):
        args = parse_command_line_args(["2026", "7", "21", "--locations", "sites.xlsx", "--publish"])
        self.assertEqual(args.data_date.isoformat(), "2026-07-21")
        self.assertTrue(args.publish)

    def test_publish_defaults_false(self):
        args = parse_command_line_args(["2026", "7", "21", "--locations", "sites.xlsx"])
        self.assertFalse(args.publish)
        self.assertFalse(args.maps)
        self.assertEqual(args.output_dir, "d1/wallops-prf/Gauge")

    def test_maps_can_be_enabled(self):
        args = parse_command_line_args(["2026", "7", "21", "--locations", "sites.xlsx", "--maps"])
        self.assertTrue(args.maps)

    def test_publish_still_stages_report_locally(self):
        args = parse_command_line_args(["2026", "7", "21", "--locations", "sites.xlsx", "--publish"])
        self.assertEqual(args.output_dir, "d1/wallops-prf/Gauge")
        self.assertEqual(
            args.publish_plots_directory,
            "/d1/wallops-prf/Gauge/Plots/",
        )

    def test_explicit_output_directory_overrides_default(self):
        args = parse_command_line_args(
            ["2026", "7", "21", "--locations", "sites.xlsx", "--output-dir", "custom/reports"]
        )
        self.assertEqual(args.output_dir, "custom/reports")

    def test_invalid_calendar_date_is_rejected(self):
        with self.assertRaises(SystemExit):
            parse_command_line_args(["2026", "2", "30", "--locations", "sites.xlsx"])

    def test_run_writes_one_full_daily_csv_with_dates(self):
        full_report = pd.DataFrame(
            [
                {
                    "Group": "WFF",
                    "Gauge type": "PIERS",
                    "GaugeID": "PIERS0001",
                    "Station Location": "North Jetty",
                    "record_count": 96,
                    "start_date": pd.Timestamp("2026-07-21 00:00:00"),
                    "end_date": pd.Timestamp("2026-07-21 23:45:00"),
                    "latitude": 38.0,
                    "longitude": -75.0,
                    "Rain_Tip_A": 0.2,
                    "Rain_Tip_B": 0.254,
                    "battery_voltage_min": 12.5,
                    "battery_voltage_mean": 12.8,
                    "battery_voltage_std": 0.1,
                    "battery_voltage_max": 13.0,
                    "rssi_min": -90,
                    "rssi_mean": -80,
                    "rssi_std": 5,
                    "rssi_max": -70,
                    "Tips_A": 1,
                    "Tips_B": 1,
                    "Accum_A [mm]": 0.2,
                    "Accum_B [mm]": 0.254,
                    "Accum_A [in]": 0.0079,
                    "Accum_B [in]": 0.01,
                    "Bias [%]": -27.0,
                }
            ]
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            args = argparse.Namespace(
                data_date=date(2026, 7, 21),
                output_dir=temporary_directory,
                locations="locations.xlsx",
                input_base_dir="input",
                fail_fast=False,
                publish=False,
                publish_user="wolff",
                publish_server="example.test",
                publish_directory="/reports",
            )
            with (
                patch("piers_tools.cli.load_locations", return_value=pd.DataFrame()),
                patch("piers_tools.cli.build_daily_report", return_value=full_report),
                patch("piers_tools.cli.gauge_report_to_html"),
            ):
                csv_path, _ = run(args)
            saved = pd.read_csv(csv_path)

        self.assertEqual(
            Path(csv_path).name,
            "Daily_Report_2026_0721.csv",
        )
        self.assertEqual(
            Path(csv_path).parent.parts[-4:],
            ("Daily_Reports", "2026", "07", "21"),
        )
        self.assertIn("start_date", saved.columns)
        self.assertIn("end_date", saved.columns)

    def test_local_plot_links_are_relative_to_html_report(self):
        full_report = pd.DataFrame()
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            output_dir = base / "PIERS_Package" / "Reports"
            plots_root = base / "d1" / "wallops-prf" / "Plots"
            args = argparse.Namespace(
                data_date=date(2026, 7, 21),
                output_dir=str(output_dir),
                locations="locations.xlsx",
                input_base_dir="input",
                fail_fast=False,
                publish=False,
                publish_user="wolff",
                publish_server="example.test",
                publish_directory="/reports",
            )
            with (
                patch("piers_tools.cli.load_locations", return_value=pd.DataFrame()),
                patch("piers_tools.cli.resolve_plot_root", return_value=plots_root),
                patch("piers_tools.cli.build_daily_report", return_value=full_report),
                patch("piers_tools.cli.clean_merged_dataframe", return_value=full_report),
                patch("piers_tools.cli.gauge_report_to_html") as write_html,
            ):
                run(args)

        self.assertEqual(
            write_html.call_args.kwargs["plot_link_root"],
            "../../d1/wallops-prf/Plots",
        )

    def test_published_report_uses_public_url_not_remote_filesystem_path(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            args = argparse.Namespace(
                data_date=date(2026, 7, 21),
                output_dir=temporary_directory,
                locations="locations.xlsx",
                input_base_dir="input",
                fail_fast=False,
                publish=True,
                publish_user="wolff",
                publish_server="rain.gsfc.nasa.gov",
                publish_directory="/d1/wallops-prf/Gauge/",
                publish_plots_directory="/d1/wallops-prf/Gauge/Plots/",
            )
            empty_report = pd.DataFrame()
            with (
                patch("piers_tools.cli.load_locations", return_value=pd.DataFrame()),
                patch("piers_tools.cli.build_daily_report", return_value=empty_report),
                patch("piers_tools.cli.clean_merged_dataframe", return_value=empty_report),
                patch("piers_tools.cli.gauge_report_to_html") as write_html,
                patch("piers_tools.cli.publish_report_and_plots"),
            ):
                run(args)

        self.assertEqual(
            write_html.call_args.kwargs["plot_link_root"],
            "/Gauge/Plots",
        )


if __name__ == "__main__":
    unittest.main()
