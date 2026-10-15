"""Command-line interface."""

from __future__ import annotations

import argparse
import logging

from .workflow import run


def build_parser():
    parser = argparse.ArgumentParser(description="Process Parsivel instrument data")
    parser.add_argument("--inst", "-i", required=True)
    parser.add_argument("--syear", "-sy", type=int)
    parser.add_argument("--smonth", "-sm", type=int)
    parser.add_argument("--sday", "-sd", type=int)
    parser.add_argument("--eyear", "-ey", type=int)
    parser.add_argument("--emonth", "-em", type=int)
    parser.add_argument("--eday", "-ed", type=int)
    parser.add_argument(
        "--input", "--input-file", "--input-dir", dest="input_path", required=True,
        help="one ZIP/CSV/DAT file or a directory scanned recursively",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--table-dir")
    parser.add_argument("--temp-dir")
    parser.add_argument(
        "--radar-bands",
        nargs="+",
        help=(
            "one or more Mie reflectivity bands; accepts space-separated "
            "values (S C X Ku K Ka) or a comma-separated value"
        ),
    )
    parser.add_argument("--water-temperature", type=float, default=20.0)
    parser.add_argument("--permittivity-model", default="Liebe1991")
    parser.add_argument("--minimum-dbz", type=float)
    return parser


def parse_args(argv=None):
    """Parse command-line arguments only; never used by the Python workflow."""
    return build_parser().parse_args(argv)


def main(argv=None):
    """Command-line adapter. Notebook code should call ``run`` instead."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    start_values = (args.syear, args.smonth, args.sday)
    end_values = (args.eyear, args.emonth, args.eday)
    if any(value is not None for value in start_values) and not all(value is not None for value in start_values):
        parser.error("start year, month, and day must be supplied together")
    if any(value is not None for value in end_values) and not all(value is not None for value in end_values):
        parser.error("end year, month, and day must be supplied together")
    start_date = "%04d-%02d-%02d" % start_values if all(value is not None for value in start_values) else None
    end_date = "%04d-%02d-%02d" % end_values if all(value is not None for value in end_values) else None
    try:
        results = run(
            args.input_path,
            args.inst,
            start_date=start_date,
            end_date=end_date,
            output_dir=args.output_dir,
            table_dir=args.table_dir,
            temp_dir=args.temp_dir,
            radar_bands=args.radar_bands,
            water_temperature=args.water_temperature,
            permittivity_model=args.permittivity_model,
            minimum_dbz=args.minimum_dbz,
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    return 0 if results else 1
