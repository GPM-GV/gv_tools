"""Create a high-quality Skew-T from a GV Tools model sounding download."""

from __future__ import annotations

import argparse
from pathlib import Path

from gv_tools.util import load_model_profile, plot_skewt


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Render a NOAA model pressure-profile GRIB2 file as a Skew-T/log-P diagram."
    )
    result.add_argument("input", type=Path, help="GRIB2 file from gv-tools-sounding")
    result.add_argument("output", type=Path, help="Output PNG or PDF path")
    result.add_argument("--latitude", type=float, help="Nearest grid-point latitude")
    result.add_argument("--longitude", type=float, help="Nearest grid-point longitude")
    result.add_argument("--title")
    result.add_argument("--no-parcel", action="store_true", help="Omit parcel ascent and CAPE/CIN")
    result.add_argument("--no-hodograph", action="store_true", help="Omit inset hodograph")
    result.add_argument("--dpi", type=int, default=200)
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if (args.latitude is None) != (args.longitude is None):
        parser().error("--latitude and --longitude must be supplied together")
    profile = load_model_profile(
        args.input, latitude=args.latitude, longitude=args.longitude
    )
    figure = plot_skewt(
        profile,
        args.output,
        title=args.title,
        parcel=not args.no_parcel,
        hodograph=not args.no_hodograph,
        dpi=args.dpi,
    )
    diagnostics = figure.gv_tools_sounding_diagnostics
    print(args.output.expanduser().resolve())
    if diagnostics:
        print(
            f"CAPE={diagnostics['cape_j_kg']:.1f} J/kg  "
            f"CIN={diagnostics['cin_j_kg']:.1f} J/kg"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
