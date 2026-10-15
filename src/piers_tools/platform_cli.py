from __future__ import annotations

import argparse
from dataclasses import asdict
import json

from .daily import DEFAULT_GAUGE_STATUS_PATH, DEFAULT_INPUT_ROOT, process_day


def parser():
    result = argparse.ArgumentParser(description="Process one complete PIERS++ site day")
    result.add_argument("site")
    result.add_argument("year", type=int)
    result.add_argument("month", type=int)
    result.add_argument("day", type=int)
    result.add_argument(
        "--input-root",
        default=str(DEFAULT_INPUT_ROOT),
        help=f"Daily-file root (default: {DEFAULT_INPUT_ROOT})",
    )
    result.add_argument("--output-dir", default="output")
    result.add_argument(
        "--gauge-status",
        default=str(DEFAULT_GAUGE_STATUS_PATH),
        help=(
            "Gauge-location Excel workbook containing tip calibrations "
            f"(default: {DEFAULT_GAUGE_STATUS_PATH})"
        ),
    )
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    result = process_day(args.input_root, args.site, args.year, args.month, args.day,
                         output_dir=args.output_dir, gauge_status_path=args.gauge_status)
    payload = asdict(result)
    payload.update(day=result.day.isoformat(), input_dir=str(result.input_dir),
                   output_dir=str(result.output_dir))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
