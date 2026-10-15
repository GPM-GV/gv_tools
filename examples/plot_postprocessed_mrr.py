"""Read and display C. Williams post-processed MRRPro hourly files."""

from __future__ import annotations

import argparse
from pathlib import Path

import gv_tools


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Hourly-file directory, glob, or NetCDF file")
    parser.add_argument("output", type=Path, help="Complete output PNG path")
    parser.add_argument("--maximum-height-km", type=float, default=3.0)
    args = parser.parse_args()

    dataset = gv_tools.io.read_mrr(args.input.expanduser())
    product_code = dataset.attrs["mrr_product_code"]
    requested_output = args.output.expanduser()
    output = (
        requested_output
        if requested_output.stem.endswith(f"_{product_code}")
        else requested_output.with_name(
            f"{requested_output.stem}_{product_code}{requested_output.suffix}"
        )
    )
    print(dataset)
    gv_tools.graph.plot_mrr_time_height_quicklook(
        dataset,
        ["reflectivity_factor", "radial_velocity", "spectrum_width"],
        savefig=output,
        cmaps={
            "reflectivity_factor": "turbo",
            "radial_velocity": "coolwarm",
            "spectrum_width": "viridis",
        },
        colorbar_bounds={
            "reflectivity_factor": (-20.0, 40.0),
            "radial_velocity": (-8.0, 8.0),
            "spectrum_width": (0.0, 5.0),
        },
        field_labels={
            "reflectivity_factor": "Reflectivity factor (dBZ)",
            "radial_velocity": "Radial velocity (m/s)",
            "spectrum_width": "Spectrum width (m/s)",
        },
        height_range_km=(0.0, args.maximum_height_km),
        title="TAMU-CC C. Williams post-processed MRRPro",
    )


if __name__ == "__main__":
    main()
