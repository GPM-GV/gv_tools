Supported instruments and methods
=================================

GV Tools reads instrument files into pandas or xarray objects. Readers never
write data products. A source may be one absolute filename, one absolute
directory (searched recursively), or an explicit sequence of absolute files or
directories. Files supplied together must be compatible with the selected
reader.

For PIERS platforms, consolidated ``*_daily`` files are the default. When a
directory contains both daily files and individual packets, GV Tools selects
the daily files. A PIERS day directory may contain multiple instrument types;
each reader selects only its own WX, WS800, Parsivel, or tipping-bucket files.

.. list-table:: Instrument support
   :header-rows: 1

   * - Instrument / format
     - Reader
     - Return value
   * - R.M. Young All-in-One weather station
     - ``gv_tools.io.read_aio``
     - pandas DataFrame; xarray Dataset with ``XARRAY=True``
   * - OTT HydroMet Lufft WS800
     - ``gv_tools.io.read_aio`` or ``gv_tools.io.read_ws800_full``
     - pandas DataFrame; xarray Dataset with ``XARRAY=True``
   * - Met One All-in-One weather station
     - ``gv_tools.io.read_aio`` (``read_metone`` alias)
     - pandas DataFrame; xarray Dataset with ``XARRAY=True``
   * - OTT Parsivel / Parsivel2 (APU and PIERS archives)
     - ``gv_tools.io.read_parsivel``
     - xarray Dataset
   * - PIERS tipping-bucket rain gauge packets
     - ``gv_tools.io.read_gauge``
     - pandas DataFrame
   * - Micro Rain Radar MRR2 and MRRPro
     - ``gv_tools.io.read_mrr``
     - xarray Dataset
   * - Radar: NEXRAD Level II, SIGMET/IRIS, Universal Format, CF/Radial
     - ``gv_tools.io.read_radar``
     - Py-ART Radar, or a list for multiple files
   * - Two-Dimensional Video Disdrometer drop files
     - ``gv_tools.io.read_2dvd``
     - pandas DataFrame
   * - RAP, RUC, NAM, and GFS model soundings
     - ``gv_tools.util.download_model_soundings`` and ``load_model_profile``
     - downloaded file metadata and a ``SoundingProfile``

Raw-reader variants
-------------------

``read_aio_raw`` and ``read_parsivel_raw`` retain the decoder's raw product
containers. ``discover_aio``, ``discover_metone``, and ``discover_parsivel``
report dates without creating outputs. ``inspect_radar`` reports the detected
radar route without reading the volume.

Plotting methods
----------------

Every plotting call requires an output filename supplied by the user. The path may
be absolute or relative to the current working directory.
Directories are created only beneath that explicitly selected destination.

* ``gv_tools.graph.plot_instrument_timeseries`` — selected columns or data
  variables plotted against an instrument time coordinate
* ``gv_tools.graph.plot_aio_quicklook``
* ``gv_tools.graph.plot_aio_wind_rose``
* ``gv_tools.graph.plot_ws800_full_quicklook``
* ``gv_tools.graph.plot_parsivel_quicklook``
* ``gv_tools.graph.plot_mrr_time_height_quicklook``
* ``gv_tools.graph.plot_radar_ppi_quicklook``
* ``gv_tools.graph.plot_radar_rhi_quicklook``
* ``gv_tools.util.plot_skewt``

Output ownership
----------------

GV Tools does not export CSV, NetCDF, Parquet, Zarr, reports, or derived daily
products. Use methods on the returned pandas or xarray object, for example
``frame.to_csv(...)``, ``frame.to_parquet(...)``, ``dataset.to_netcdf(...)``,
or ``dataset.to_zarr(...)``.
