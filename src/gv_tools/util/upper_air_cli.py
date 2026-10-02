"""Command-line interface for model upper-air downloads."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime

from .upper_air import (
    ModelUnavailableError,
    SoundingDownloadError,
    available_models,
    download_model_soundings,
)


def _datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "use an ISO UTC time such as 2026-09-30T18:00Z"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gv-tools-sounding",
        description="Download a NOAA model pressure-level profile as GRIB2.",
    )
    parser.add_argument("latitude", type=float)
    parser.add_argument("longitude", type=float)
    parser.add_argument("--model", default="rap", help=f"Model ({', '.join(available_models())})")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--latest", action="store_true")
    selection.add_argument("--time", type=_datetime, metavar="UTC_TIME")
    selection.add_argument("--start", type=_datetime, metavar="UTC_TIME")
    parser.add_argument("--end", type=_datetime, metavar="UTC_TIME")
    parser.add_argument("--forecast-hour", type=int, default=0)
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the upper-air downloader command."""

    parser = _parser()
    args = parser.parse_args(argv)
    if (args.start is None) != (args.end is None):
        parser.error("--start requires --end, and --end requires --start")
    try:
        results = download_model_soundings(
            args.latitude,
            args.longitude,
            model=args.model,
            output_dir=args.output_dir,
            latest=args.latest,
            when=args.time,
            start=args.start,
            end=args.end,
            forecast_hour=args.forecast_hour,
            overwrite=args.overwrite,
        )
    except (ModelUnavailableError, SoundingDownloadError, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    for item in results:
        print(item.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
