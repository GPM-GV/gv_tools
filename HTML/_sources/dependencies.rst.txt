Dependencies
============

GV Tools keeps its required installation small. NumPy, pandas, and xarray are
the only unconditional dependencies. Install optional groups only for the file
formats and plotting features in use.

.. list-table:: Optional dependency groups
   :header-rows: 1

   * - Extra
     - Purpose
     - Packages
   * - ``netcdf``
     - NetCDF-backed MRR and xarray input
     - h5netcdf, h5py, scipy
   * - ``plot``
     - All Matplotlib figures
     - matplotlib
   * - ``radar``
     - Scanning-radar ingest and mapped figures
     - ARM Py-ART, xradar, cartopy
   * - ``notebook``
     - Validation and example notebooks
     - JupyterLab, IPython kernel, matplotlib
   * - ``sounding``
     - GRIB model profiles and Skew-T figures
     - MetPy, cfgrib, ecCodes, matplotlib
   * - ``docs``
     - Local HTML documentation builds
     - Sphinx, PyData Sphinx Theme, MyST Parser
   * - ``all``
     - Every runtime, plotting, radar, sounding, and notebook feature
     - Union of the runtime groups above

Install and inspect dependencies with the required Anaconda Python using
``tcsh``:

.. code-block:: tcsh

   set WORKSPACE = /Users/dwolff/Desktop/Work/GV_Tools
   set PACKAGE_DIRECTORY = "$WORKSPACE/gv_tools"
   set PYTHON = "$HOME/anaconda3/bin/python"

   $PYTHON -m pip install "$PACKAGE_DIRECTORY/dist/gv_tools-0.50.0-py3-none-any.whl[all]"
   $PYTHON -m gv_tools.cli check --include radar --include plot --include notebook --include sounding

The dependency checker reports unavailable or older packages but does not
modify the environment.
