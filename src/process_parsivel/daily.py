"""Batch conversion of APU hourly archives to daily NetCDF products."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
import logging
from pathlib import Path
import re

import pandas as pd

from .core import process_input, save_dataframes_to_netcdf
from .location import resolve_location

LOGGER = logging.getLogger(__name__)
DEFAULT_APU_INPUT_DIR = Path("/Volumes/TBW/distro/apu")
DEFAULT_APU_OUTPUT_DIR = Path("/Volumes/TBW/APU_Daily")
INSTRUMENT_PATTERN = re.compile(r"apu\d{2}", re.IGNORECASE)
ARCHIVE_PATTERN = re.compile(
    r"^(apu\d{2})_(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:[01]\d|2[0-3])?\.zip$",
    re.IGNORECASE,
)


@dataclass
class DailyNetCDFResult:
    """Results from a batch conversion, including per-day failures."""

    outputs: dict[tuple[str, str], str] = field(default_factory=dict)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    errors: dict[tuple[str, str], str] = field(default_factory=dict)

    @property
    def succeeded(self) -> int:
        return len(self.outputs)


def discover_apu_days(input_dir=DEFAULT_APU_INPUT_DIR, instruments=None):
    """Discover unique ``(instrument, date)`` pairs from hourly APU ZIP names."""
    root = Path(input_dir).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"APU input directory does not exist: {root}")
    requested = None
    if instruments:
        requested = {str(item).lower() for item in instruments}
        invalid = sorted(item for item in requested if not INSTRUMENT_PATTERN.fullmatch(item))
        if invalid:
            raise ValueError(f"Invalid APU instrument name(s): {', '.join(invalid)}")

    found = set()
    for instrument_dir in sorted(root.glob("apu[0-9][0-9]")):
        instrument = instrument_dir.name.lower()
        if requested is not None and instrument not in requested:
            continue
        for archive in instrument_dir.glob("[0-9][0-9][0-9][0-9][0-9][0-9]/*.zip"):
            match = ARCHIVE_PATTERN.fullmatch(archive.name)
            if match is None or match[1].lower() != instrument:
                continue
            try:
                stamp = pd.Timestamp(year=int(match[2]), month=int(match[3]), day=int(match[4]))
            except ValueError:
                LOGGER.warning("Ignoring archive with invalid date: %s", archive)
                continue
            found.add((instrument, stamp))
    return sorted(found, key=lambda item: (item[0], item[1]))


def run_daily_netcdf(
    input_dir=DEFAULT_APU_INPUT_DIR,
    output_dir=DEFAULT_APU_OUTPUT_DIR,
    *,
    instruments=None,
    start_date=None,
    end_date=None,
    site="APU",
    temp_dir=None,
    table_dir=None,
    location_dir=None,
    engine="auto",
    compression=True,
    complevel=4,
    overwrite=True,
    continue_on_error=True,
):
    """Convert hourly ZIP archives into one derived Xarray/NetCDF file per day.

    ZIP archives are only read. Their CSV/DAT members are extracted beneath a
    temporary work directory and removed after every day, including on errors.
    ``start_date`` and ``end_date`` are inclusive when supplied.
    """
    root = Path(input_dir).expanduser()
    start = pd.Timestamp(start_date).normalize() if start_date is not None else None
    end = pd.Timestamp(end_date).normalize() if end_date is not None else start
    if start is None and end_date is not None:
        raise ValueError("end_date requires start_date")
    if start is not None and end < start:
        raise ValueError("end_date must not precede start_date")

    candidates = discover_apu_days(root, instruments)
    if start is not None:
        candidates = [item for item in candidates if start <= item[1] <= end]
    result = DailyNetCDFResult()
    for instrument, stamp in candidates:
        date_key = stamp.strftime("%Y-%m-%d")
        key = instrument, date_key
        LOGGER.info("Processing %s %s", instrument, date_key)
        try:
            month_dir = root / instrument / stamp.strftime("%Y%m")
            parms, psd, moments = process_input(
                month_dir,
                instrument,
                stamp.strftime("%Y"),
                stamp.strftime("%m"),
                stamp.strftime("%d"),
                table_dir=table_dir,
                temp_root=temp_dir,
            )
            if parms.empty:
                result.skipped.append(key)
                LOGGER.warning("No valid records for %s %s", instrument, date_key)
                continue
            result.outputs[key] = save_dataframes_to_netcdf(
                parms,
                psd,
                moments,
                output_dir,
                site,
                instrument,
                stamp.strftime("%Y"),
                stamp.strftime("%m"),
                stamp.strftime("%d"),
                engine=engine,
                compression=compression,
                complevel=complevel,
                overwrite=overwrite,
                location=resolve_location(instrument, stamp, location_dir),
            )
        except Exception as exc:
            result.errors[key] = f"{type(exc).__name__}: {exc}"
            LOGGER.error("Failed %s %s: %s", instrument, date_key, exc)
            if not continue_on_error:
                raise
    return result


def build_daily_parser():
    parser = argparse.ArgumentParser(
        description="Convert APU hourly ZIP archives to daily NetCDF files"
    )
    parser.add_argument("--input-dir", default=str(DEFAULT_APU_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_APU_OUTPUT_DIR))
    parser.add_argument("--instruments", nargs="+", metavar="APU", help="e.g. apu01 apu02")
    parser.add_argument("--start-date", type=date.fromisoformat, metavar="YYYY-MM-DD")
    parser.add_argument("--end-date", type=date.fromisoformat, metavar="YYYY-MM-DD")
    parser.add_argument("--site", default="APU")
    parser.add_argument("--temp-dir")
    parser.add_argument("--table-dir")
    parser.add_argument(
        "--location-dir",
        help="directory of apu??_locations.csv overrides; defaults to packaged timelines",
    )
    parser.add_argument("--engine", choices=("auto", "h5netcdf", "netcdf4"), default="auto")
    parser.add_argument("--complevel", type=int, choices=range(10), default=4)
    parser.add_argument("--no-compression", action="store_true")
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    return parser


def daily_main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_daily_parser().parse_args(argv)
    try:
        result = run_daily_netcdf(
            args.input_dir,
            args.output_dir,
            instruments=args.instruments,
            start_date=args.start_date,
            end_date=args.end_date,
            site=args.site,
            temp_dir=args.temp_dir,
            table_dir=args.table_dir,
            location_dir=args.location_dir,
            engine=args.engine,
            compression=not args.no_compression,
            complevel=args.complevel,
            overwrite=not args.no_overwrite,
            continue_on_error=not args.fail_fast,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}") from exc
    LOGGER.info(
        "Completed: %d written, %d skipped, %d failed",
        result.succeeded,
        len(result.skipped),
        len(result.errors),
    )
    return 1 if result.errors or (not result.outputs and not result.skipped) else 0


if __name__ == "__main__":
    raise SystemExit(daily_main())
