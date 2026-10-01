"""Minimal task-oriented GV Tools examples."""

import os
from pathlib import Path

import gv_tools


INPUT_DIR = Path("/path/to/input")
OUTPUT_DIR = Path("/path/to/output")
FILES = [INPUT_DIR / "PIERS0042_Parsivel_20260810_daily.zip"]
parsivel = gv_tools.io.read_parsivel(FILES)

gv_tools.correct.validate_product(parsivel)
gv_tools.io.write_product(parsivel, OUTPUT_DIR, formats=("netcdf",), day="2026-08-10")


# Optionally demonstrate content-aware radar ingest. For example, point this
# variable at a KCRP..._V06 NEXRAD Level-II file before running the script.
radar_name = os.environ.get("GV_TOOLS_RADAR_FILE")
if radar_name:
    radar_path = Path(radar_name).expanduser().resolve()
    route = gv_tools.io.inspect_radar(radar_path)
    radar = gv_tools.io.read_radar(radar_path)
    print(f"Radar route: {route.family} / {route.file_format} / {route.reader}")
    print(
        f"Radar dimensions: {radar.nsweeps} sweeps, "
        f"{radar.nrays} rays, {radar.ngates} gates"
    )
    print(f"Radar fields: {sorted(radar.fields)}")
else:
    print("Radar example skipped: set GV_TOOLS_RADAR_FILE to one radar file")
