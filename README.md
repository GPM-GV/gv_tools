# GV Tools 0.50.0 release candidate

GV Tools is a compact collection of instrument readers and plotting helpers.
It converts user-selected input files to pandas DataFrames or xarray Datasets.
It does not perform research analyses, publish reports, or choose data-output
locations. Users retain control of analysis and serialization through pandas
and xarray.

## Install with tcsh

```tcsh
set WORKSPACE = /Users/dwolff/Desktop/Work/GV_Tools
set package_name = gv_tools
set PACKAGE_DIRECTORY = "$WORKSPACE/$package_name"
set PYTHON = "$HOME/anaconda3/bin/python"
$PYTHON -m pip install --upgrade "$PACKAGE_DIRECTORY/dist/gv_tools-0.50.0-py3-none-any.whl[all]"
$PYTHON -m pip install --force-reinstall --no-deps "$PACKAGE_DIRECTORY/dist/gv_tools-0.50.0-py3-none-any.whl"
```

This is the local 0.50.0 release candidate. It is not published until its API,
dependencies, distributions, and documentation pass release validation.

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
