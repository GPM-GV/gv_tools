"""Command-line interface for range-based PIERS gauge NetCDF ingestion."""

from __future__ import annotations

import argparse

from .gauge import ingest_gauge_range


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("input_path", help="Daily CSV or directory of gauge CSV packets")
    result.add_argument("gauge_id")
    result.add_argument("start_date", help="Inclusive date (YYYY-MM-DD)")
    result.add_argument("end_date", help="Inclusive date (YYYY-MM-DD)")
    result.add_argument("--accumulation-per-tip", type=float, required=True, help="Millimetres per tip")
    result.add_argument("--output-dir", default="output")
    result.add_argument("--network", default="PIERS")
    result.add_argument("--measurement", default="TB_A_tips")
    result.add_argument("--latitude", type=float)
    result.add_argument("--longitude", type=float)
    return result


def main(argv=None) -> None:
    args = parser().parse_args(argv)
    paths = ingest_gauge_range(
        args.input_path, args.gauge_id, args.start_date, args.end_date,
        output_dir=args.output_dir, network=args.network,
        accumulation_per_tip=args.accumulation_per_tip,
        measurement=args.measurement, latitude=args.latitude, longitude=args.longitude,
    )
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
