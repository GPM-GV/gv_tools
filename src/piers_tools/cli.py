"""Command-line interface for the PIERS daily report."""

from __future__ import annotations

import argparse
import os
import socket
from datetime import date
from pathlib import Path
from typing import Sequence

from .pipeline import build_daily_report, load_locations
from .plotting import resolve_plot_root
from .processing import clean_merged_dataframe
from .publishing import publish_report_and_plots
from .reporting import gauge_report_to_html
from .platform_cli import parser


WORKSTATION_HOSTNAME = "gs610wcrystal.ndc.nasa.gov"
DEFAULT_LOCAL_REPORT_ROOT = "d1/wallops-prf/Gauge"


def default_input_base_dir() -> str:
    if socket.gethostname() == WORKSTATION_HOSTNAME:
        return "~/Desktop/Work/distro/PIERS_Gauges_Daily"
    return "/gvraid/distro/PIERS_Gauges_Daily"


def parse_command_line_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse and validate arguments; pass an explicit list from Jupyter."""
    parser = argparse.ArgumentParser(
        description="Build a daily PIERS gauge report."
    )
    parser.add_argument("year", type=int, help="Data year")
    parser.add_argument("month", type=int, help="Data month")
    parser.add_argument("day", type=int, help="Data day")
    parser.add_argument(
        "--locations",
        required=True,
        help="Required path to the current gauge-location Excel workbook",
    )
    parser.add_argument(
        "--ingest-mode", choices=("daily", "packets"), default="daily",
        help="Use concatenated daily files (default) or individual packet files",
    )
    parser.add_argument(
        "--input-file", action="append", dest="input_files",
        help="Fully specified input file; repeat for a list of files",
    )
    parser.add_argument(
        "--input-base-dir",
        default=default_input_base_dir(),
        help="Root directory containing gauge/year/month/day folders",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Override the local staging directory; defaults to "
            "d1/wallops-prf/Gauge beneath the current directory"
        ),
    )
    parser.add_argument(
        "--plots-root",
        default=None,
        help=(
            "Override the local plots staging root; defaults to "
            "d1/wallops-prf/Gauge/Plots beneath the current directory"
        ),
    )
    parser.add_argument(
        "--plot-link-root",
        default=None,
        help="Override the plot URL/path embedded in the HTML report",
    )
    parser.add_argument(
        "--maps",
        action="store_true",
        help="Make Station Location cells open Google Maps",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at the first gauge error instead of reporting other gauges",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish the completed HTML report with SCP",
    )
    parser.add_argument("--publish-user", default="wolff")
    parser.add_argument("--publish-server", default="rain.gsfc.nasa.gov")
    parser.add_argument(
        "--publish-directory",
        default="/d1/wallops-prf/Gauge/",
    )
    parser.add_argument(
        "--publish-plots-directory",
        default="/d1/wallops-prf/Gauge/Plots/",
    )
    args = parser.parse_args(argv)
    try:
        args.data_date = date(args.year, args.month, args.day)
    except ValueError as exc:
        parser.error(str(exc))
    if args.output_dir is None:
        args.output_dir = DEFAULT_LOCAL_REPORT_ROOT
    return args


def run(args: argparse.Namespace) -> tuple[Path, Path]:
    """Execute the daily pipeline from parsed arguments."""
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    locations = load_locations(args.locations)
    plots_root = resolve_plot_root(
        publish=args.publish,
        plot_root=getattr(args, "plots_root", None),
    )
    daily_report = build_daily_report(
        args.data_date,
        locations,
        args.input_base_dir,
        continue_on_gauge_error=not args.fail_fast,
        plot_root=plots_root,
        publish_plots=args.publish,
        ingest_mode=getattr(args, "ingest_mode", "daily"),
        input_paths=getattr(args, "input_files", None),
    )

    archive_dir = (
        output_dir
        / "Daily_Reports"
        / f"{args.data_date.year:04d}"
        / f"{args.data_date.month:02d}"
        / f"{args.data_date.day:02d}"
    )
    archive_dir.mkdir(parents=True, exist_ok=True)
    csv_path = archive_dir / (
        f"Daily_Report_{args.data_date.year:04d}_"
        f"{args.data_date.month:02d}{args.data_date.day:02d}.csv"
    )
    html_path = output_dir / "Gauge_Report.html"
    local_plot_link_root = os.path.relpath(
        plots_root.expanduser().resolve(),
        start=html_path.parent,
    ).replace(os.sep, "/")
    daily_report.to_csv(csv_path, index=False)
    report_table = clean_merged_dataframe(daily_report)
    gauge_report_to_html(
        report_table,
        html_path,
        coverage_date=args.data_date,
        plot_link_root=(
            getattr(args, "plot_link_root", None)
            or ("/Gauge/Plots" if args.publish else local_plot_link_root)
        ),
        enable_maps=getattr(args, "maps", False),
    )

    if args.publish:
        publish_report_and_plots(
            html_path,
            plots_root,
            args.data_date,
            user=args.publish_user,
            server=args.publish_server,
            remote_report_directory=args.publish_directory,
            remote_plot_directory=args.publish_plots_directory,
        )
    return csv_path, html_path


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_command_line_args(argv)
    csv_path, html_path = run(args)
    print(f"Gauge Report CSV: {csv_path}")
    print(f"Web Gauge Report: {html_path}")
    print(f"Published: {args.publish}")


if __name__ == "__main__":
    main()
