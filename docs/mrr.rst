MRR2 and MRRPro ingest
======================

MRR2 and MRRPro have their own Micro Rain Radar ingest regime because vertically profiling
radar products differ from both surface instruments and scanning radar
volumes. Use :func:`gv_tools.io.read_mrr` for MRR data. The result is always an
``xarray.Dataset`` that preserves the product's time, range, spectral, and
derived-variable dimensions.

Supported products
------------------

``read_mrr`` detects the instrument generation from dataset contents rather
than the filename:

``MRR2``
   METEK processed-data NetCDF containing the ``MRR_*`` variables, including
   rain rate, liquid-water content, reflectivity, velocity, spectra, and
   range-gate information. The non-CF ``UNIX Time Stamp`` coordinate is
   converted to UTC ``datetime64[ns]``.

``MRRPro``
   CF/Radial NetCDF4/HDF5 containing the MRRPro moment, spectrum, range, and
   time variables, or C. Williams' post-processed hourly moment files with
   reflectivity, radial velocity, spectrum width, skewness, kurtosis, and
   signal-to-noise ratio. Time coordinates are decoded by xarray.

The detected generation is recorded as ``dataset.attrs["mrr_model"]`` with a
value of ``"MRR2"`` or ``"MRRPro"``. Files that match neither schema are
rejected with a message describing representative missing variables.

Files, directories, globs, and ZIP archives
-------------------------------------------

The input may be a NetCDF file or a ZIP archive containing exactly one
``.nc``, ``.cdf``, or ``.netcdf`` member. ZIP content is loaded eagerly so the
returned dataset remains usable after the archive is closed. NetCDF3 content
uses the SciPy engine by default; NetCDF4/HDF5 content uses ``h5netcdf``.

A directory, glob, or sequence of fully qualified filenames reads an hourly
collection into one in-memory dataset. Files are concatenated along ``time``,
sorted chronologically, and duplicate timestamps are retained only once. The
attributes ``mrr_source_file_count`` and ``mrr_source_files`` record the
inputs. This path does not require Dask.

Install NetCDF4/HDF5 support from ``tcsh`` with:

.. code-block:: tcsh

   set WORKSPACE = "$HOME/Desktop/Work/GV Tools"
   set PYTHON = "$HOME/anaconda3/bin/python"
   $PYTHON -m pip install "$WORKSPACE/gv_tools/release/gv_tools-0.34.0-py3-none-any.whl[netcdf]"

Examples
--------

.. code-block:: python

   import gv_tools

   mrr2 = gv_tools.io.read_mrr("/data/mrr2/0722.ave.nc.zip")
   print(mrr2.attrs["mrr_model"])  # MRR2
   print(mrr2.MRR_RR)

   mrrpro = gv_tools.io.read_mrr("/data/mrrpro/20260722_070000.nc")
   print(mrrpro.attrs["mrr_model"])  # MRRPro
   print(mrrpro.RR)

   postprocessed = gv_tools.io.read_mrr(
       "/Volumes/36TB/MRR/TAMU-CC/reprocessed/nc_files/"
       "nc_files_c01_mom/2023/08/22"
   )
   print(postprocessed.reflectivity_factor)

Time-height quicklooks
----------------------

MRR2 and MRRPro use different variable names, so
``plot_mrr_time_height_quicklook`` takes an explicit list of fields. Each field
is drawn in its own row in a shared-time, single-column figure::

   gv_tools.graph.plot_mrr_time_height_quicklook(
       mrr2,
       ["MRR_Capital_Z", "MRR_RR", "MRR_LWC", "MRR_W"],
       cmaps={
           "MRR_Capital_Z": "NWSRef",
           "MRR_RR": "turbo",
           "MRR_LWC": "viridis",
           "MRR_W": "coolwarm",
       },
       colorbar_bounds={
           "MRR_Capital_Z": (-10, 40),
           "MRR_RR": (0, 20),
           "MRR_LWC": (0, 3),
           "MRR_W": (-8, 2),
       },
       height_range_km=(0, 3),
   )

   gv_tools.graph.plot_mrr_time_height_quicklook(
       mrrpro,
       ["Ze", "RR", "LWC", "VEL"],
   )

   gv_tools.graph.plot_mrr_time_height_quicklook(
       postprocessed,
       ["reflectivity_factor", "radial_velocity", "spectrum_width"],
       cmaps={
           "reflectivity_factor": "turbo",
           "radial_velocity": "coolwarm",
           "spectrum_width": "viridis",
       },
       height_range_km=(0, 3),
   )

Colormaps and colorbar bounds may be one setting for every panel or mappings
keyed by field name. Field labels, height and time ranges, colorbar location,
grid, title, figure size, DPI, and output path are also configurable. Invalid
or missing samples are white. MRR2 height is taken from ``MRR_H``; MRRPro
height is taken from its ``range`` coordinate.

Options accepted by :func:`xarray.open_dataset` may be passed through when a
specific engine or decoding behavior is required:

.. code-block:: python

   dataset = gv_tools.io.read_mrr("product.nc", decode_times=True)

Resource handling
-----------------

Uncompressed NetCDF results retain xarray's file-backed behavior. Close them
explicitly or use a context manager when finished. ZIP results are loaded into
memory and do not retain the archive handle.

MRR is not routed through :func:`gv_tools.io.read_radar`: that function is for
scanning SIGMET/IRIS and CF/Radial volumes represented by Py-ART ``Radar``.
Keeping MRR in xarray preserves its native profiling data model.
