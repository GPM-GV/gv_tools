Supported instruments and methods
=================================

GV Tools reads instrument files into pandas or xarray objects. Readers never
write data products. A source may be one absolute filename, one absolute
directory (searched recursively), or an explicit sequence of absolute files or
directories. Files supplied together must be compatible with the selected
reader.

For PIERS platforms, consolidated ``*_daily`` files and individual packets may
be supplied together. Every file is read and each observation (or Parsivel
telegram) is kept once, by its own time stamp; when a packet repeats a daily
record the daily value is kept. (0.50.0 dropped all packets whenever one daily
file was present.) A PIERS day directory may contain multiple instrument types;
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
     - ``gv_tools.io.read_gauge`` (records as logged) and
       ``gv_tools.io.read_tipping_bucket`` (tips, depth, rate)
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
   * - RAP, HRRR, NAM, and GFS model soundings
     - ``gv_tools.util.download_model_soundings`` and ``load_model_profile``
     - downloaded file metadata and a ``SoundingProfile``

Parsivel processing choices
---------------------------

``read_parsivel`` and ``read_parsivel_raw`` accept ``start_date``/``end_date``
(UTC days), ``classes`` (``"ott"`` default, or ``"legacy"``), ``fall_speed``
(``"measured"`` default, or ``"theoretical"``), ``velocity_filter`` (0.5),
``max_diameter_mm`` (10), ``telegram_interval_s`` (inferred per telegram),
``time_binning`` (``"centre"`` default, or ``"stamp"``), ``strict_fields``,
``spectrum_offset`` (9) and ``include_spectrum``. See :doc:`parsivel`.

Tipping buckets
---------------

``read_tipping_bucket(source, tip_depth_mm=...)`` differences the cumulative
``TB_*_tips`` counters and returns ``*_tips``, ``*_depth_mm``,
``*_rate_mm_h`` and ``*_flag`` per minute. The tip depth is required.

* A decrease can be a counter reset (the new value counts the tips since
  it, flag 1), a dip (bad records until the counter is back at its old level
  within three records: a dropout to 0, a stale value) or a spike (the record
  before was bad). Each reading implies a rain rate; a reading that needs
  more than ``max_rate_mm_h`` (with an allowance for bursts) is impossible.
  A small drop (to more than half the old level) takes the calmest reading;
  a drop to less than half the old level stays a reset unless the reset
  would need a rate more than three times the dip's plus two tips per
  report. Removed records get flag 16.
* A dropout longer than three records is recognised when the counter jumps
  back to its old level: the records since the drop are removed and the
  tips count from the old level.
* A drop on the last record cannot be confirmed by a later one, and a jump
  no rain can make is a re-based counter: their tips are NaN (flag 1).
* With ``counter_max`` a decrease is a wrap-around only when the implied
  tips are plausible.
* If the logger clears the counter on a schedule (every packet, say), pass
  ``glitch_window=0``: every drop is then a reset. With small counts, resets
  and dropouts look alike, and in a test with the counter cleared every
  10 minutes the default rules counted 6 % fewer tips (2 % with
  ``glitch_window=0``, the tips hidden by resets that show no drop).
* A report covers the time since the previous report and is put in the
  minute whose centre it covers, so a report stamped 06:01:00 fills 06:00.
* Minutes no report covers -- before the first report, inside gaps longer
  than 2.5 x the usual spacing (flag 2), and inside a report spanning several
  minutes in which tips fell (flag 8, tips in its last minute, rate NaN) --
  are missing, not dry. Tips already counted in a minute such a report makes
  unknown move to its last minute, so no tip is lost. A multi-minute report
  without tips makes all its minutes 0.
* Rates above ``max_rate_mm_h`` (300) are flagged (4) and their depth and
  rate set to NaN.

``counter="incremental"`` handles loggers that report tips per record.

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
