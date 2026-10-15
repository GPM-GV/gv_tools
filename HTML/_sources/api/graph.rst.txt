gv_tools.graph
==============

One-dimensional time-series plotting functions accept either a pandas
``DataFrame`` or an xarray ``Dataset``. Multidimensional plots retain their
native scientific input: Parsivel DSD plotting uses an xarray ``Dataset``, and
radar plotting uses the Py-ART-compatible object returned by
``gv_tools.io.read_radar``.

.. automodule:: gv_tools.graph
   :members:
   :undoc-members:
   :show-inheritance:

2DVD
----

.. automodule:: gv_tools.graph.py_2dvd
   :members: plot_integral_parameters, plot_dsd
