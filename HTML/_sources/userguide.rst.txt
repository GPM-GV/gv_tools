User guide
==========

Design boundary
---------------

GV Tools reads observations and creates figures. It does not choose data
output locations, aggregate observations for analysis, generate reports, or
publish results. Use pandas and xarray methods for those tasks.

Input selection
---------------

Public readers accept an absolute filename, an absolute directory, or an
explicit sequence of absolute files/directories. Directories are searched
recursively. A single call must contain files compatible with its reader.
PIERS readers prefer consolidated ``*_daily`` products when daily and packet
files are both present.

.. code-block:: python

   import gv_tools

   frame = gv_tools.io.read_aio("/data/piers/PIERS0042")
   dataset = gv_tools.io.read_mrr([
       "/data/mrr/20261015_000000.nc",
       "/data/mrr/20261015_010000.nc",
   ])

One PIERS day directory can be supplied separately to each instrument reader:

.. code-block:: python

   day = "/Volumes/TBW/distro/PIERS_Gauges_Daily/PIERS0045/2026/10/11"
   weather = gv_tools.io.read_aio(day)
   gauge = gv_tools.io.read_gauge(day)
   parsivel = gv_tools.io.read_parsivel(day)

User-controlled data output
---------------------------

.. code-block:: python

   frame.to_csv("/chosen/output/aio.csv", index=False)
   dataset.to_netcdf("/chosen/output/mrr.nc")

GV Tools does not wrap these methods or invent filenames.

User-controlled figures
-----------------------

Every plotting method requires a complete output filename. Plotters expose
field, range, color, sizing, labeling, and rendering options and return the
Matplotlib objects for further user customization.

.. code-block:: python

   figure, axis = gv_tools.graph.plot_instrument_timeseries(
       frame,
       fields=["air_temperature", "relative_humidity"],
       output="/Users/dwolff/Desktop/Work/GV_Tools/Output/PIERS0045-RMYoung_2026-10-11_weather.png",
       colors={"air_temperature": "firebrick", "relative_humidity": "navy"},
       figsize=(14, 5),
       dpi=200,
   )

See :doc:`supported-instruments` for the full API matrix.
