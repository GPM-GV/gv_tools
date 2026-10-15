"""Minimal reader and user-directed plotting example."""

from pathlib import Path

import gv_tools

WORKSPACE = Path("/Users/dwolff/Desktop/Work/GV_Tools")
INPUT = Path("/absolute/path/to/aio/files")
FIGURE = WORKSPACE / "Output" / "PIERS0045-RMYoung_2026-10-11_temperature.png"

data = gv_tools.io.read_aio(INPUT)
gv_tools.graph.plot_instrument_timeseries(data, "air_temperature", FIGURE)

# Users select their own data format and destination when desired:
# data.to_csv(WORKSPACE / "Output" / "PIERS0045-RMYoung_2026-10-11.csv", index=False)
