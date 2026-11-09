# GV Tools 0.65.0

GV Tools is a compact collection of instrument readers and plotting helpers.
It converts user-selected input files to pandas DataFrames or xarray Datasets.
It does not perform research analyses, publish reports, or choose data-output
locations. Users retain control of analysis and serialization through pandas
and xarray.

## Install with tcsh

```tcsh
set WORKSPACE = "/Users/dwolff/Desktop/Work/GV_Tools"
set PACKAGE_DIR = "$WORKSPACE/gv_tools"
set PYTHON = "$HOME/anaconda3/bin/python"
set WHEEL = "$PACKAGE_DIR/dist/gv_tools-0.65.0-py3-none-any.whl"

$PYTHON -m pip install --upgrade "${WHEEL}[all]"
$PYTHON -c 'import gv_tools; print(gv_tools.__version__)'
```

The final command should print `0.65.0`. The `netcdf` extra now requires
`h5netcdf>=1.8` (xarray 2026.9 reads NetCDF-4 through `Variable.filters()`).

## What changed in 0.65.0

0.65.0 corrects the science of the Parsivel DSD integrals, fixes how Parsivel
days are assembled, and adds tipping-bucket processing. Products differ from
0.50.0; see `CHANGES_0.65.0.html` for every change, why, and its effect.
This release incorporates the reviewed 0.60.0 change set after local regression,
static-analysis, documentation, notebook, build, and isolated-wheel checks.

* Parsivel N(D) now divides each count by **its own** velocity class (0.50.0
  used the terminal speed of the diameter class with the same index along the
  velocity axis). `mass_spectrum_width` is sigma_m (mm), not its variance.
  dBZ is NaN for Z = 0 instead of being clamped to 0.
* OTT manual size classes by default (`classes="ott"`); the 1.03-scaled 0.50.0
  tables remain available as `classes="legacy"`.
* Days are built from the telegram time stamps, not file names: raw PIERS and
  APU names work, each day keeps its last minutes, telegrams are counted
  once, minutes without telegrams are missing (not dry), and each telegram's
  measuring interval is inferred from its neighbours. No scratch files; no
  directories in `source`.
* `read_tipping_bucket` turns the tip counters into tips, depth and rate.
* WS800 enthalpy and air-density columns are labelled as such; Met One 2400
  records are kept; model soundings drop below-ground levels and rotate RAP,
  HRRR and NAM grid-relative winds to earth-relative.
* The Parsivel decoder is about 10x faster with a quarter of the memory; the
  2DVD reader is about 2.4x faster.

## Read data

Readers accept one absolute filename, an absolute directory searched
recursively, or a sequence of absolute files/directories. Files in one call
must be compatible.

```python
import gv_tools

aio = gv_tools.io.read_aio("/absolute/path/to/aio/files")
parsivel = gv_tools.io.read_parsivel(["/absolute/path/to/apu01_20240101.zip"])
mrr = gv_tools.io.read_mrr("/absolute/path/to/mrr/files")
radar = gv_tools.io.read_radar("/absolute/path/to/radar/file")
gauge = gv_tools.io.read_gauge("/absolute/path/to/gauge/files", gauge_id="PIERS0042")
rain = gv_tools.io.read_tipping_bucket("/absolute/path/to/gauge/files", gauge_id="PIERS0042",
                                       tip_depth_mm=0.254)  # the gauge's gauge_tip
drops = gv_tools.io.read_2dvd("/absolute/path/to/V23022.drops.txt")
```

Write data with pandas or xarray using paths you select:

```python
gauge.to_csv("/absolute/output/PIERS0042.csv")
parsivel.to_netcdf("/absolute/output/PIERS0042_parsivel.nc")
```

## Plot data

Plotting methods require an explicit output filename. Relative paths are supported:

```python
gv_tools.graph.plot_instrument_timeseries(
    aio,
    ["air_temperature", "relative_humidity"],
    "/Users/dwolff/Desktop/Work/GV_Tools/Output/PIERS0045-RMYoung_2026-10-11_timeseries.png",
)
gv_tools.graph.plot_parsivel_quicklook(
    parsivel,
    "/Users/dwolff/Desktop/Work/GV_Tools/Output/PIERS0045-Parsivel_2026-10-11_quicklook.png",
)
```

The complete instrument/reader/plotter matrix is in the HTML manual and
`docs/supported-instruments.rst`.
