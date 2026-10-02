User Guide
==========

The preferred interface starts with a task namespace:

``gv_tools.core``
   Shared scientific data structures and metadata.

``gv_tools.io``
   Direct instrument readers, radar readers, and product writers. Standard
   filenames are used to infer instrument metadata automatically.

``gv_tools.config``
   Adapter registration and installation diagnostics.

``gv_tools.correct``
   Product validation, quality control, and future corrections.

``gv_tools.graph``
   Quicklooks and plot-output paths.

``gv_tools.util``
   General utilities, including NOAA model upper-air profile downloads.

Existing imports such as ``from gv_tools import InstrumentMetadata`` continue
to work during the 0.x migration period. New code should use
``gv_tools.core.InstrumentMetadata`` and the other task namespaces.

Model upper-air profiles
------------------------

``gv_tools.util.download_model_soundings`` downloads geographically subsetted
GRIB2 profiles from NOAA NOMADS. Files include height, temperature, relative
humidity, and U/V wind on all available pressure levels. RAP, HRRR, GFS, and
NAM are supported. RAP is the operational successor to RUC; the retired RUC
Soundings service is not silently substituted.

Download the latest RAP analysis::

   results = gv_tools.util.download_model_soundings(
       38.90, -77.00, model="rap", latest=True, output_dir="Soundings"
   )

Download one GFS initialization or an inclusive range of RAP cycles::

   from datetime import datetime, timezone

   one = gv_tools.util.download_model_soundings(
       38.90, -77.00, model="gfs",
       when=datetime(2026, 9, 30, 18, tzinfo=timezone.utc),
       output_dir="Soundings",
   )
   many = gv_tools.util.download_model_soundings(
       38.90, -77.00, model="rap",
       start=datetime(2026, 9, 29, tzinfo=timezone.utc),
       end=datetime(2026, 9, 30, 23, tzinfo=timezone.utc),
       output_dir="Soundings",
   )

The equivalent command is ``gv-tools-sounding``. Forecast hour zero is the
default analysis; select a forecast lead with ``forecast_hour`` or
``--forecast-hour``. NOMADS retains recent operational data, not a permanent
historical archive.

Install the optional decoder and plot stack with ``gv_tools[sounding]``. Then
decode the GRIB2 subset and make a Skew-T/log-P diagram::

   profile = gv_tools.util.load_model_profile(
       results[0].path, latitude=38.90, longitude=-77.00
   )
   figure = gv_tools.util.plot_skewt(
       profile, "Soundings/rap_skewt.png", title="RAP analysis", dpi=220
   )

The plot includes temperature, dew point, wind barbs, dry and moist adiabats,
mixing-ratio lines, a surface-parcel trace, CAPE/CIN shading, and a hodograph.
See ``notebooks/Upper_Air_Sounding_Downloads.ipynb`` for an end-to-end test and
``examples/plot_model_skewt.py`` for a reusable command-line script.

Direct readers
--------------

Normal use does not require constructing an adapter or metadata object. Every
reader takes the same explicit file-list interface::

   input_dir = "/data/instruments"
   files = [input_dir + "/PIERS0027_WX_20260721000005.csv"]
   raw = gv_tools.io.read_aio_raw(files)
   aio = gv_tools.io.read_aio(files)

   metone = gv_tools.io.read_aio([input_dir + "/AIO_GAIL_202501.dat"])
   parsivel_files = ["/data/PIERS0042/PIERS0042_Parsivel_20260810_daily.zip"]
   parsivel = gv_tools.io.read_parsivel(parsivel_files)
   radar = gv_tools.io.read_radar(input_dir + "/volume.nc.gz")
   mrr = gv_tools.io.read_mrr(input_dir + "/0722.ave.nc.zip")

``files`` must be a non-empty list of fully qualified file paths. Multiple files are
merged chronologically into one raw product or normalized dataset, with
duplicate timestamps removed. Every supplied file is processed; date selection
is the caller's responsibility. Raw and normalized pairs use the same arguments.
Metadata can be overridden with keywords such as ``instrument_id``, ``site_id``,
and ``timezone``. Adapter classes remain an extension-development API.

Radar
-----

``read_radar(radar_file)`` reads one volume at a time and returns Py-ART's
native ``Radar`` object. GV Tools detects SIGMET/IRIS, WSR-88D NEXRAD Level II,
and CF/Radial NetCDF from the file contents and transparently expands gzip,
bzip2, or a ZIP archive that contains exactly one radar file.
After decoding, ingest prints the detected scan type (``PPI``, ``RHI``, or
``BB`` for birdbath) and stores it in ``radar.metadata['gv_tools_scan_type']``.
Py-ART is the default backend. Pass ``XRADAR=True`` to load through xradar;
GV Tools then calls ``tree.pyart.to_radar()`` and returns the converted Py-ART
``Radar``. Both choices therefore have the same return interface. The
NetCDF-safe integer ``radar.metadata['XRADAR']`` records whether xradar was
used (``0`` for Py-ART and ``1`` for xradar), so the result can be passed
directly to ``pyart.io.write_cfradial``.
If ``file_field_names`` is supplied with ``XRADAR=True``, GV Tools warns and
ignores it because it is a Py-ART reader option rather than an xradar option.
The converted result retains Py-ART's native ``radar.info()`` reporting method.
For NEXRAD Level-II volumes, ``XRADAR=True`` warns and falls back to Py-ART's
``read_nexrad_archive`` because xradar-to-Py-ART conversion cannot reliably
combine multi-sweep volumes whose sweeps have unequal gate counts.
The PPI and RHI quicklooks support both the native Py-ART result and the
Py-ART-compatible XRADAR result, including multi-sweep volumes.

PPI radar quicklook
-------------------

``plot_radar_ppi_quicklook`` uses Py-ART's mapped PPI display with Cartopy
coastlines, state/country borders, geographic gridlines, a radar marker,
range rings, and radial azimuth spokes. The sweep number is zero-based.
Spoke intervals are degrees and range-ring intervals are kilometers::

   from pathlib import Path

   output_file = Path.cwd() / "NPOL_sweep01.png"
   figure = gv_tools.graph.plot_radar_ppi_quicklook(
       radar,
       field="reflectivity",
       sweep=1,
       cmap="NWSRef",
       vmin=-10,
       vmax=70,
       max_range_km=150,
       radial_spoke_interval_deg=30,
       radial_spoke_color="white",
       range_ring_interval_km=25,
       range_ring_color="black",
       gridline_interval_deg=1,
       savefig=str(output_file),
   )

``Path.cwd()`` saves into the Jupyter kernel's current working directory.
Supply a different writable directory when needed. Set either overlay interval
to ``None`` to disable it. ``map_resolution`` may
be ``110m``, ``50m``, or ``10m``. The default title reports radar name, field,
UTC volume time, selected sweep, median elevation, and target elevation.
Only the selected Natural Earth resolution is drawn; choosing ``10m`` or
``50m`` does not add a second ``110m`` basemap underneath it.

RHI radar quicklook
-------------------

``plot_radar_rhi_quicklook`` uses Py-ART's native range-height display. Field,
sweep, colormap, color limits, range and height bounds, axis direction,
colorbar orientation, grid, title, figure size, DPI, and output are
configurable. Symbols use range and height in kilometers::

   rhi_symbols = [
       {"Location": (18, 1.2), "Color": "gold", "Symbol": "*", "Size": 180},
       {"Location": (42, 3.5), "Color": "cyan", "Symbol": "^", "Size": 90},
   ]
   figure = gv_tools.graph.plot_radar_rhi_quicklook(
       radar,
       field="reflectivity",
       sweep=0,
       cmap="NWSRef",
       vmin=-10,
       vmax=70,
       max_range_km=100,
       max_height_km=15,
       symbols=rhi_symbols,
   )

A single symbol dictionary may be supplied directly, or multiple dictionaries
may be supplied as a list or tuple. The verbose title reports radar name,
field, UTC volume time, sweep, median azimuth, and target azimuth.

Birdbath ZDR calibration
------------------------

``plot_radar_bb_zdr_calibration`` estimates ZDR bias from a vertical-pointing
birdbath sweep. The left panel shows height-resolved sample density and the
gate-median profile; the right panel shows the ZDR distribution, zero
reference, estimated bias, and recommended additive correction. The returned
figure also stores the numeric result in ``figure.gv_tools_zdr_calibration``::

   figure = gv_tools.graph.plot_radar_bb_zdr_calibration(
       radar,
       field="differential_reflectivity",
       sweep=0,
       min_range_km=0.5,
       max_range_km=10,
       zdr_bounds=(-2, 2),
       statistic="median",
       reflectivity_field="reflectivity",
       reflectivity_bounds_dbz=(10, 30),
   )
   print(figure.gv_tools_zdr_calibration["additive_correction_db"])

The additive correction is the negative of the estimated vertical ZDR bias.
Reflectivity filtering is optional; when supplied, it can isolate the desired
calibration regime. Users should apply scientifically appropriate quality
control and precipitation-selection thresholds for their radar and campaign.

MRR2 and MRRPro
---------------

METEK MRR2 and MRRPro are handled by their own ``read_mrr(file)`` ingest regime.
Unlike scanning radar, MRR products are time-height or time-range datasets and
are returned directly as an ``xarray.Dataset`` rather than a Py-ART ``Radar``.
MRR2 processed products, native MRRPro CF/Radial products, and C. Williams
post-processed MRRPro moment files are detected from variables and metadata.
Directories, globs, and file sequences are concatenated chronologically. See
:doc:`mrr` for supported containers, time decoding, model identification,
examples, and limitations.
Use ``plot_mrr_time_height_quicklook(dataset, fields)`` to plot any explicit
list of two-dimensional profile fields as a stacked, single-column time-height
figure. Explicit names accommodate the different MRR2 and MRRPro schemas.

All-in-One weather stations
---------------------------

``read_aio`` and ``read_aio_raw`` automatically distinguish RM Young PIERS
weather packets named ``PIERS####_WX_*.csv`` from Met One monthly files named
``AIO_SITE_YYYYMM.dat``. The caller supplies the complete set of fully qualified
filenames to process. ``read_aio_raw`` returns decoded pandas observations
and ingest accounting; ``read_aio`` returns the normalized xarray dataset with
units, metadata, validation, and plotting/output compatibility.
``read_aio`` returns a pandas DataFrame by default for every AIO family. Pass
``XARRAY=True`` to return the equivalent xarray Dataset.
Lufft WS800 daily files named ``PIERS####_WS800_*.csv`` passed to ``read_aio``
return a compact pandas DataFrame with the common temperature, humidity,
pressure, wind-speed, and wind-direction names. ``read_ws800_full(files)``
merges a list of files and returns every WS800 field as pandas; pass
``XARRAY=True`` for xarray.

``plot_ws800_full_quicklook`` accepts either return type. Its six-row,
single-column figure groups all matching fields into air temperature
(``air_temperature`` and ``air_temp_*``), dew point
(``dew_point_temperature`` and ``dew_point_*``), relative humidity
(``relative_humidity`` and ``rel_hum_*``), absolute humidity (``abs_hum_*``),
mixing ratio (``mixing_ratio`` and ``mixing_ratio_*``), and lightning
(``lightning_*``) panels::

   ws800_full = gv_tools.io.read_ws800_full(files)
   figure = gv_tools.graph.plot_ws800_full_quicklook(ws800_full)

Every one-dimensional time-series plotting method accepts either a pandas
``DataFrame`` or an xarray ``Dataset``. This includes the AIO, WS800-full, and
wind-rose plotting methods. The multidimensional Parsivel DSD quicklook
requires xarray, while radar plots use the Py-ART-compatible radar object.

``plot_aio_quicklook`` creates a three-row by two-column dashboard. Temperature,
pressure, and humidity occupy the left column. The right column contains a
dual-axis wind-speed/wind-direction time series, a wind rose, and a boxed data
summary. Without ``savefig`` the dashboard displays normally; with an absolute
image path it saves without display and prints the saved filename::

   figure = gv_tools.graph.plot_aio_quicklook(
       aio,
       savefig="/full/path/WFF_PIERS0027_AIO.png",
       title="WFF PIERS0027 AIO",
   )

Parsivel
--------

Standalone APU archives named ``apu##_*.zip`` and PIERS Parsivel archives named
``PIERS####_Parsivel_*.zip`` use the same call. GV Tools infers whether the
source is APU or PIERS, derives the instrument identifier, produces the DSD,
moments, and parameter fields, and merges multiple archives into one dataset::

   parsivel = gv_tools.io.read_parsivel([
       "/data/apu09_2026010100.zip",
       "/data/apu09_2026010101.zip",
   ])

Every supplied archive is processed. Select the desired dates by constructing
the fully qualified filename list before calling the reader, ordered from
earliest to latest. The first filename supplies the internal processing start
date and the last filename supplies the internal end date. Neither date is a
public reader argument.

Parsivel six-panel plot
-----------------------

``plot_parsivel_quicklook`` plots one UTC day in six rows: DSD, dBZ, rain
rate, liquid-water content, concentration, and number of drops. The x-axis
spans midnight to midnight with hourly ticks and every panel has a grid::

   figure = gv_tools.graph.plot_parsivel_quicklook(
       parsivel,
       savefig="/full/path/PIERS0042_Parsivel_2026-08-10.png",
       day="2026-08-10",
       cmap="plasma",
       colorbar_bounds=(0.0, 250.0),
       colorbar_location="right",
       dsd_yrange=(0.0, 8.0),
   )

The default title is built from normalized metadata as
``SITE_ID | INSTRUMENT | YYYY-MM-DD — Parsivel quicklook``. Pass ``title=`` to
add a custom heading above this required metadata context. ``cmap`` accepts
any Matplotlib colormap. ``colorbar_bounds`` and ``dsd_yrange`` accept
``(minimum, maximum)`` pairs, and ``colorbar_location`` may be ``left``,
``right``, ``top``, or ``bottom``. Zero-valued DSD bins are rendered white.
All six panels retain the same plotting width.
When saving, ``savefig`` must contain the complete path and image filename.
Without ``savefig``, the figure remains open for normal Jupyter or Matplotlib
display. With ``savefig``, the image is saved, the figure is closed to suppress
notebook display, and ``Plot saved to PATH`` is printed.
