import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import call, patch

from piers_tools.publishing import publish_report_and_plots


class PublishingTests(unittest.TestCase):
    def test_report_and_all_three_plot_categories_are_published(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            report = base / "d1/wallops-prf/Gauge/Gauge_Report.html"
            report.parent.mkdir(parents=True)
            report.write_text("<TABLE></TABLE>", encoding="utf-8")
            plot_root = report.parent / "Plots"
            for category, suffix in (
                ("Rain", "rain"),
                ("Battery", "voltage"),
                ("RSSI", "rssi"),
            ):
                directory = plot_root / category / "2026/07/21"
                directory.mkdir(parents=True)
                (directory / f"PIERS0001_2026_0721_{suffix}.png").touch()

            with patch("piers_tools.publishing.subprocess.run") as run_command:
                publish_report_and_plots(
                    report,
                    plot_root,
                    date(2026, 7, 21),
                    user="wolff",
                    server="rain.gsfc.nasa.gov",
                )

        self.assertEqual(run_command.call_count, 5)
        ssh_command = run_command.call_args_list[0].args[0]
        self.assertEqual(ssh_command[:4], ["ssh", "wolff@rain.gsfc.nasa.gov", "mkdir", "-p"])
        self.assertIn("/d1/wallops-prf/Gauge", ssh_command)
        self.assertIn(
            "/d1/wallops-prf/Gauge/Plots/Rain/2026/07/21",
            ssh_command,
        )
        self.assertEqual(
            run_command.call_args_list[1],
            call(
                [
                    "scp",
                    str(report.resolve()),
                    "wolff@rain.gsfc.nasa.gov:/d1/wallops-prf/Gauge/",
                ],
                check=True,
            ),
        )
        for publish_call in run_command.call_args_list[2:]:
            self.assertEqual(publish_call.args[0][0], "scp")
            self.assertTrue(publish_call.args[0][-1].startswith(
                "wolff@rain.gsfc.nasa.gov:/d1/wallops-prf/Gauge/Plots/"
            ))


if __name__ == "__main__":
    unittest.main()
