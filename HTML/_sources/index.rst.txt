GV Tools
========

GV Tools reads NASA GPM Ground Validation instrument data into pandas or
xarray objects and saves user-directed figures. It does not select data-output
paths or perform downstream scientific analyses.

.. code-block:: python

   import gv_tools

   files = ["/data/PIERS0042/PIERS0042_Parsivel_20260810_daily.zip"]
   parsivel = gv_tools.io.read_parsivel(files)

.. toctree::
   :maxdepth: 2

   userguide
   dependencies
   mrr
   api/index
   notebooks
   examples
   supported-instruments
   architecture
   metadata

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
