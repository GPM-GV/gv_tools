# GV Tools

`GV Tools` 0.34.0 is a scientific Python framework for NASA Global Precipitation
Measurement (GPM) Ground Validation instruments. Version 0.1 establishes the
common package, metadata and output contracts, and an adapter for APU and PIERS
data through `process-parsivel`. It also reads PIERS-associated RM Young
All-in-One weather packets and monthly Met One AIO files directly.

## Model upper-air profiles

The `gv_tools.util` namespace downloads pressure-level profiles from NOAA
NOMADS for RAP, HRRR, GFS, and NAM. Choose the latest available cycle, one UTC
cycle, or an inclusive cycle range. The downloaded GRIB2 subset includes
height, temperature, relative humidity, and U/V wind components.

```tcsh
set WORKSPACE = "$HOME/Desktop/Work/GV Tools"
$HOME/anaconda3/bin/gv-tools-sounding 38.90 -77.00 --model rap --latest \
  --output-dir "$WORKSPACE/Soundings"
```

RAP is the operational successor to RUC. NOAA retired the old RUC Soundings
service, so requesting `model="ruc"` produces an actionable error instead of
silently returning a different model. NOMADS retains recent operational data;
it is not a permanent historical archive.

Install decoding and high-quality Skew-T plotting support with the sounding
extra:

```tcsh
set WORKSPACE = "$HOME/Desktop/Work/GV Tools"
set PYTHON = "$HOME/anaconda3/bin/python"
$PYTHON -m pip install "$WORKSPACE/gv_tools/release/gv_tools-0.34.0-py3-none-any.whl[sounding]"
```

The end-to-end test notebook is
`notebooks/Upper_Air_Sounding_Downloads.ipynb`. The reusable plotting script
accepts a GRIB2 file produced by `gv-tools-sounding`:

```tcsh
$PYTHON examples/plot_model_skewt.py Soundings/profile.grib2 \
  Soundings/profile_skewt.png --latitude 37.94 --longitude -75.47
```

## Install on macOS or Rocky Linux

The wheel is pure Python and works on either platform with Python 3.10 or
newer. It intentionally contains no third-party packages. Pip obtains required
dependencies from the configured package index:

```console
~/anaconda3/bin/python -m pip install "./gv_tools-0.34.0-py3-none-any.whl[parsivel,netcdf]"
python3 -m gv_tools.cli check
```

To inspect availability before installation, unpack the source ZIP and run the
checker after installing GV Tools itself. The checker reports required,
Parsivel, and NetCDF dependencies without silently installing anything. Add
`--include plot --include notebook` to check visualization dependencies.

For an offline machine, download third-party wheels separately on a connected
machine with the same Python and operating-system architecture:

```console
python3 -m pip download --dest third_party_wheels \
  "gv_tools[parsivel,netcdf,plot,notebook]"
```

Keep that wheelhouse separate from the GV Tools release ZIP.

The Python API accepts regular Python values and never reads command-line
arguments, so it is safe in Jupyter notebooks. The supplied notebook is
configured for WFF, PIERS0042, 2026-08-10; its input and output directories are
editable in the first configuration cell.

## Install from tcsh

The commands below use the requested Anaconda Python and the supplied Parsivel
source archive:

```tcsh
set WORKSPACE = "$HOME/Desktop/Work/GV Tools/gv_tools"
set PARSIVEL_ZIP = "$HOME/Desktop/Work/Process_Parsivel/process_parsivel-1.0.0-source.zip"
set BUILD_DIR = `mktemp -d /tmp/gv_tools_install.XXXXXX`

unzip -q "$PARSIVEL_ZIP" -d "$BUILD_DIR"
~/anaconda3/bin/python -m pip install "$BUILD_DIR/source"
~/anaconda3/bin/python -m pip install "$WORKSPACE/release/gv_tools-0.34.0-py3-none-any.whl"
```

For notebook plotting, ensure Jupyter and Matplotlib are installed:

```tcsh
~/anaconda3/bin/python -m pip install jupyterlab matplotlib h5netcdf
```

## Run the supplied notebook from tcsh

```tcsh
cd "$HOME/Desktop/Work/GV Tools/gv_tools"
~/anaconda3/bin/python -m jupyter lab notebooks/RM_Young_AIO_PIERS_sample.ipynb
```

## Command-line processing from tcsh

Choose the raw Parsivel input and output directory:

```tcsh
set INPUT_DIR = "/path/to/PIERS0042/Parsivel/input"
set OUTPUT_DIR = "$HOME/Desktop/Work/GV Tools/Output"

~/anaconda3/bin/python -m gv_tools.cli parsivel "$INPUT_DIR" \
  --instrument-id PIERS0042 --site-id WFF \
  --source-platform piers \
  --output "$OUTPUT_DIR" --format netcdf --format csv
```

Scientific data are stored below
`OUTPUT_DIR/WFF/PIERS0042/YYYY/MM/DD`. Plot code should obtain its directory
with `plot_directory()`, producing
`OUTPUT_DIR/Plots/PlotType/YYYY/MM`.

## Python and Jupyter API

```python
import gv_tools

FILES = ["/data/PIERS0042/PIERS0042_Parsivel_20260810_daily.zip"]
parsivel = gv_tools.io.read_parsivel(FILES)

gv_tools.correct.validate_product(parsivel)
gv_tools.io.write_product(parsivel, OUTPUT_DIR, formats=("netcdf", "csv"), day="2026-08-10")
figure_dir = gv_tools.graph.plot_directory(OUTPUT_DIR, "Parsivel_Parameters", "2026-08-10")
gv_tools.graph.plot_parsivel_quicklook(
    parsivel,
    savefig=figure_dir / "PIERS0042_Parsivel_2026-08-10.png",
    day="2026-08-10",
    cmap="plasma",
    colorbar_bounds=(0.0, 250.0),
    colorbar_location="right",
    dsd_yrange=(0.0, 8.0),
)
```

The Parsivel ingest accepts both supported raw archive families with the same
one-line interface: ``gv_tools.io.read_parsivel(FILES)``. APU filenames identify
an `apu##` instrument, while PIERS filenames identify a `PIERS####` platform.
PIERS filenames must identify the instrument
as ``PIERS####_Parsivel_*.zip``. The source platform and instrument identifier
are inferred and stored in the dataset attributes. Multiple files are merged
chronologically into one dataset.

Readers process every fully qualified filename supplied by the caller. Build
the file list before calling GV Tools when a particular date selection is
required, and order Parsivel files from earliest to latest. GV Tools obtains
the processing start date from the first filename and the end date from the
last filename; these dates are not public reader arguments.

``plot_parsivel_quicklook`` creates a six-row, one-day figure containing DSD,
dBZ, rain rate, LWC, concentration, and number of drops. It uses hourly UTC
ticks, grids on every panel, and the title
``SITE_ID: MODEL YYYY-MM-DD``. The colormap, DSD color bounds, colorbar
location, and DSD y range are configurable. Zero DSD bins are white, and all
six panels use the same time-axis width.
To save the image, pass its complete path and filename through ``savefig=``.
When ``savefig`` is omitted, the figure is displayed normally. When supplied,
the figure is saved without display and its saved path is printed.

See [the architecture](docs/architecture.md), [metadata contract](docs/metadata.md),
and [output conventions](docs/output-conventions.md) before adding another
instrument adapter.

## Radar ingest

Install the radar dependency and ingest a raw np1 SIGMET/IRIS volume, a WSR-88D
NEXRAD Level-II archive, or an NPOL1 CF/Radial NetCDF volume. GV Tools examines
the file signature rather than trusting its extension and returns the native
Py-ART ``Radar`` object:

```bash
python -m pip install 'gv_tools[radar]'
```

```python
import gv_tools

RADAR_FILE = "/data/NPOL1_2026_0722_104802.cf.gz"
route = gv_tools.io.inspect_radar(RADAR_FILE)
radar = gv_tools.io.read_radar(RADAR_FILE)
print(route.family, radar.fields)
```

Pass exactly one filename per call. Uncompressed files, gzip, bzip2, and ZIP
archives containing one radar file are supported; dispatch is based on the
decompressed file signature rather than its extension.
Ingest prints ``Radar scan type: PPI``, ``RHI``, or ``BB`` and records the same
value in ``radar.metadata["gv_tools_scan_type"]``.

Py-ART remains the default. To load through xradar and return the converted
Py-ART Radar:

```python
radar = gv_tools.io.read_radar(RADAR_FILE, XRADAR=True)
print(radar.metadata["gv_tools_scan_type"])
print(radar.metadata["XRADAR"])  # 1 (xradar); Py-ART is 0
radar.info()
```

For NEXRAD Level-II volumes, ``XRADAR=True`` warns and falls back to Py-ART's
``read_nexrad_archive`` because xradar-to-Py-ART conversion cannot reliably
combine multi-sweep volumes whose sweeps have unequal gate counts.

``file_field_names`` is specific to the Py-ART reader. If it is included with
``XRADAR=True``, GV Tools emits a warning and ignores that option.

The backend flag is stored as a NetCDF-safe integer, so an ingested radar can
be written directly back to CF/Radial:

```python
import pyart

radar = gv_tools.io.read_radar(RADAR_FILE, file_field_names=True, XRADAR=False)
pyart.io.write_cfradial("temp.cf", radar, format="NETCDF4")
```

Plot a mapped PPI sweep with Py-ART and Cartopy:

```python
gv_tools.graph.plot_radar_ppi_quicklook(
    radar,
    field="reflectivity",
    sweep=0,
    max_range_km=150,
    radial_spoke_interval_deg=30,
    radial_spoke_color="white",
    range_ring_interval_km=25,
    range_ring_color="black",
)
```

The PPI quicklook includes geographic gridlines, coastlines, state/country
borders, range rings, radial spokes, and a verbose UTC/sweep/elevation title.
Field, sweep, colormap, limits, range, map resolution, grid spacing, overlay
spacing/colors/widths, projection, figure size, DPI, and output are configurable.
The chosen Natural Earth resolution is drawn once, without a lower-resolution
basemap underneath it.

Plot an RHI sweep with optional range-height symbols:

```python
rhi_symbols = {
    "Location": (18, 1.2),
    "Color": "gold",
    "Symbol": "*",
    "Size": 180,
}
gv_tools.graph.plot_radar_rhi_quicklook(
    radar,
    field="reflectivity",
    sweep=0,
    max_range_km=100,
    max_height_km=15,
    symbols=rhi_symbols,
)
```

RHI field, sweep, colormap, limits, range and height bounds, axis direction,
colorbar orientation, grid, title, symbols, figure size, DPI, and output are
configurable. Symbol locations are ``(range_km, height_km)``.

Estimate differential-reflectivity calibration from a birdbath scan:

```python
figure = gv_tools.graph.plot_radar_bb_zdr_calibration(
    radar,
    field="differential_reflectivity",
    min_range_km=0.5,
    max_range_km=10,
    zdr_bounds=(-2, 2),
    reflectivity_bounds_dbz=(10, 30),
)
print(figure.gv_tools_zdr_calibration)
```

The diagnostic combines a height-resolved ZDR density/profile with a
distribution panel and reports the estimated bias and recommended additive
correction. Filtering thresholds remain user-selectable.

## RM Young All-in-One reader

The unified AIO interface returns pandas by default for every supported AIO
instrument. Pass ``XARRAY=True`` for an xarray Dataset. WS800 results contain
only the common AIO columns through this compact interface:

```python
ws800 = gv_tools.io.read_aio([
    "/data/ws800/PIERS0042_WS800_20260831_daily.csv"
])
```

For all WS800 fields, use pandas (default) or request xarray explicitly:

```python
full_frame = gv_tools.io.read_ws800_full(WS800_FILES)
full_dataset = gv_tools.io.read_ws800_full(WS800_FILES, XARRAY=True)
gv_tools.graph.plot_ws800_full_quicklook(full_frame)
```

The WS800 full quicklook accepts either return type and plots six stacked field
families: air temperature, dew point, relative humidity, absolute humidity,
mixing ratio, and lightning. Every available matching ``*_`` field is drawn.
AIO quicklooks also accept DataFrames or xarray Datasets; Parsivel plotting
remains xarray-only because its DSD is multidimensional.

The AIO reader accepts an explicit list of files named
`PIERS####_WX_YYYYmmddHHMMSS.csv`. It decodes the AIO status, wind,
temperature, humidity, and pressure fields, skips malformed records, removes
duplicate timestamps, and merges all supplied files into one normalized dataset:

```python
import gv_tools

FILES = ["/data/PIERS0042_WX_20260810060005.csv"]
raw_aio = gv_tools.io.read_aio_raw(FILES)
aio = gv_tools.io.read_aio(FILES)
```

GV Tools reads every explicitly supplied file. The caller controls date
selection by supplying only the desired fully qualified filenames.

Pass `timezone=` with the IANA timezone used by the source timestamps when
the packets are not recorded in UTC; output times are always converted to UTC.

A compact PIERS0027 packet is included in `Samples`, together with the runnable
`notebooks/RM_Young_AIO_PIERS_sample.ipynb` notebook. The notebook demonstrates
discovery, reading, xarray inspection, pandas conversion, and basic weather
plots.

## Met One All-in-One reader and quicklooks

The unified AIO reader also reads monthly files named `AIO_SITE_YYYYMM.dat`,
including the GAIL archive's `AIO_GAIL_YYYYMM.dat` files. It converts the
year/Julian-day/HHMM fields from the configured source timezone to UTC and
merges all requested files into one normalized dataset. Fields include wind speed and
direction, direction standard deviation, temperature, humidity, pressure,
averaging interval, and user channel 2.

```python
import gv_tools

FILES = ["/Volumes/TBW/distro/aio/AIO_GAIL_202501.dat"]
aio = gv_tools.io.read_aio(FILES)
gv_tools.graph.plot_aio_quicklook(
    aio,
    savefig="/full/path/AIO_quicklook.png",
)
```

The AIO quicklook is a 3×2 dashboard: temperature, pressure, and humidity on
the left; wind speed/direction, a wind rose, and a boxed data summary on the
right. Omit ``savefig`` to display it instead of saving it.

See `notebooks/MetOne_AIO_GAIL_sample.ipynb` for discovery, ingest, product
writing and the combined AIO dashboard quicklook.

## MRR2 and MRRPro ingest

Read an MRR2 or MRRPro NetCDF file, a ZIP archive containing one NetCDF file,
or a directory/glob/list of hourly files as an `xarray.Dataset`. The model is
detected from the schema and stored in `dataset.attrs["mrr_model"]`. Multiple
files are combined chronologically along `time` without Dask:

```python
import gv_tools

mrr2 = gv_tools.io.read_mrr("/data/mrr2/0722.ave.nc.zip")
mrrpro = gv_tools.io.read_mrr("/data/mrrpro/20260722_070000.nc.zip")
print(mrr2.MRR_RR, mrrpro.RR)

postprocessed = gv_tools.io.read_mrr(
    "/Volumes/36TB/MRR/TAMU-CC/reprocessed/nc_files/nc_files_c01_mom/2023/08/22"
)
print(postprocessed.reflectivity_factor)
```

Plot selected profile fields in one stacked column. Field names are explicit
because MRR2 and MRRPro use different schemas:

```python
gv_tools.graph.plot_mrr_time_height_quicklook(
    mrrpro,
    ["Ze", "RR", "LWC", "VEL"],
    cmaps={"Ze": "NWSRef", "RR": "turbo", "LWC": "viridis", "VEL": "coolwarm"},
    colorbar_bounds={"Ze": (-10, 40), "RR": (0, 20), "LWC": (0, 3), "VEL": (-8, 2)},
    height_range_km=(0, 3),
)

gv_tools.graph.plot_mrr_time_height_quicklook(
    postprocessed,
    ["reflectivity_factor", "radial_velocity", "spectrum_width"],
    cmaps={"reflectivity_factor": "turbo", "radial_velocity": "coolwarm"},
    height_range_km=(0, 3),
)
```

The API also accepts per-field labels, a time range, colorbar location, grid
control, title, figure size, DPI, and a complete ``savefig`` path.

## Reference manual

The HTML reference manual follows the task-oriented layout and PyData Sphinx
theme used by ARM Py-ART. Build it from a source checkout with:

```tcsh
set PYTHON = "$HOME/anaconda3/bin/python"
$PYTHON -m pip install -e '.[docs]'
make -C docs html
```

Open `docs/_build/html/index.html`. The API is divided into `gv_tools.core`,
`gv_tools.io`, `gv_tools.config`, `gv_tools.correct`, and `gv_tools.graph`.
Release notebooks live in `notebooks`, and runnable Python scripts live in
`examples`; both are included in the source release.

## 2DVD (py_2dvd)

The capabilities of `py_2dvd_lite` 0.1.2 are bundled in GV Tools; no separate
`py_2dvd` installation is required. Ingestion reads one `VYYDDD.drops.txt` day,
plain or inside ZIP/TGZ/tar.gz, into a Pandas DataFrame. Archives must contain
exactly one matching drop file and are read without extraction.

```tcsh
set WORKSPACE = "$HOME/Desktop/Work/GV Tools"
set PYTHON = "$HOME/anaconda3/bin/python"
$PYTHON -m pip install "${WORKSPACE}/gv_tools/release/gv_tools-0.34.0-py3-none-any.whl[py_2dvd]"
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
with `rain`, `dsd`, and `rcParams` sections. See [plot options](docs/py_2dvd/plotting.md),
[methods](docs/py_2dvd/methods.md), and [references](docs/py_2dvd/references.md).
SciPy is needed for NetCDF export; Matplotlib is needed for plots. Ingestion and
calculation use the base dependencies and do not initialize Matplotlib.
