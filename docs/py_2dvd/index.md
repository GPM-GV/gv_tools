# 2DVD ingestion, calculations, and plots


The capabilities of `py_2dvd_lite` 0.1.2 are bundled in GV Tools; no separate
`py_2dvd` installation is required. Ingestion reads one `VYYDDD.drops.txt` day,
plain or inside ZIP/TGZ/tar.gz, into a Pandas DataFrame. Archives must contain
exactly one matching drop file and are read without extraction.

```tcsh
set WORKSPACE = "$HOME/Desktop/Work/GV Tools"
set PYTHON = "$HOME/anaconda3/bin/python"
$PYTHON -m pip install "${WORKSPACE}/gv_tools/release/gv_tools-0.31.0-py3-none-any.whl[py_2dvd]"
$HOME/anaconda3/bin/gv-tools-2dvd-process /path/to/V23022.drops.txt --site WFF --instrument sn37 --output-dir "$WORKSPACE/Output"
$HOME/anaconda3/bin/gv-tools-2dvd-plot "$WORKSPACE/Output/NetCDF/2023/01/WFF_2023_0122_2DVD_measured_velocity.nc" --output-dir "$WORKSPACE/Output"
```

```python
from gv_tools.io import read_2dvd, save_products
from gv_tools.core import calculate_products, prepare_drops
from gv_tools.graph import plot_integral_parameters, plot_dsd

raw = read_2dvd("/path/to/V23022.drops.txt", site="WFF", instrument="sn37")
qc = prepare_drops(raw)  # copy with derived quantities and acceptance flags
parameters, dsd = calculate_products(raw)
rain_figure = plot_integral_parameters(parameters, velocity="measured")
dsd_figure = plot_dsd(dsd, velocity="terminal")
paths = save_products(parameters, dsd, output_dir="Output")
```

`gv_tools.io.ingest_raw` is the original reader spelling. Alternatively,
`from gv_tools import py_2dvd as dvd` exposes the original seven notebook
functions plus `prepare_drops`. Instrument-specific implementations are in
`gv_tools.io.py_2dvd`, `gv_tools.core.py_2dvd`, and `gv_tools.graph.py_2dvd`.

Both calculation products contain a full 1440-minute day and measured/terminal
velocity coordinates. DSD has 50 nominal 0.2-mm bins. QC, numerical precision,
lookup tables, and reporting thresholds are preserved from the source. Missing
minutes have zero counts/DSD and NaN bulk quantities; they do not establish dry
conditions. Source timestamps remain timezone-naive. `output_valid` marks
minutes with more than ten accepted drops and rain rate at least 0.01 mm/h;
plots apply it by default without modifying the data.

Saving creates eight files: NetCDF, integral CSV, DSD CSV, and provenance JSON
for each velocity. Plotting returns editable Matplotlib figures and saves only
when `output_dir` is supplied. The plotting CLI supports `--plot-config` JSON
with `rain`, `dsd`, and `rcParams` sections. See [plot options](plotting.md),
[methods](methods.md), and [references](references.md).
SciPy is needed for NetCDF export; Matplotlib is needed for plots. Ingestion and
calculation use the base dependencies and do not initialize Matplotlib.

```{toctree}
:maxdepth: 1

methods
plotting
references
```
